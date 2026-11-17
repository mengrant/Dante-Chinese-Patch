#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 RefPack 压缩流中直接原地改写字面字节 —— .lh2 文本最小改动闭环。

原理
----
RefPack 指令流里的「字面字节」是明文。若待改字符串在解压结果中全部来自
字面（而非 LZ 回引用），就能在压缩流里按 1:1 替换这些字节：压缩流长度、
SHOC 段结构、VIV 条目长度、TOC 偏移全部不变 —— 不需要 RefPack 重压、
不需要重算字符串偏移表、不需要重建 9 GB ISO，只需改动 ISO 上的几个字节。

这是「最小闭环验证」最省事的一条路：先证明回灌链路通，再谈中文与字库。

限制：新文本必须能编码成单字节且不长于原串（短了用 NUL 补齐）。
中文显示需要扩展字体贴图与字符映射，属于下一阶段，本工具不假装支持。

产物（都在 patch/，已 gitignore，不入库）：
  patch/inplace_patch.json   差异记录：ISO 绝对偏移 + 原/新字节 + 校验结果
  patch/patched_entry.bin    修改后的完整 VIV 条目块

用法:
  py -3 tools/lh2_patch.py --list
  py -3 tools/lh2_patch.py --find "Start Game" --text "HANHUA OK!"
  py -3 tools/lh2_patch.py --index 263 --text "HANHUA OK!" --apply-to "G:/DanteHanhua/build/test.iso"
"""
import argparse
import json
import os
import struct
import sys

from common import ensure_dir, load_config, report_path, resolve
from lh2_export import parse_lh2, readable
from refpack import decompress, scan

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CFG = load_config()
ISO = resolve(CFG, "iso")
MANIFEST = report_path(CFG, "viv_manifest.json")
DEFAULT_ENTRY = "inferno_global.en.lh2"


def build_full_with_map(blob):
    """解压所有 RefPack 块并补齐未压缩尾段。

    返回 (逻辑完整数据, 源映射)；源映射第 i 项是第 i 个输出字节在 blob 中的
    绝对偏移，-1 表示该字节由 LZ 回引用生成（不能直接改）。
    """
    full = bytearray()
    srcmap = []
    for off, _used, _out_len, _out in scan(blob, limit=32):
        out, _consumed, smap = decompress(blob, off, mapped=True)
        full += out
        srcmap.extend(smap)

    # 尾段：SHOC/SDAT 里的未压缩文本，直接映射 blob 绝对偏移
    if len(full) >= 8:
        declared = struct.unpack_from(">I", full, 4)[0]
        need = declared - len(full)
        if need > 0:
            pos = 0
            while True:
                i = blob.find(b"SHOC", pos)
                if i < 0:
                    break
                pos = i + 4
                if blob[i + 8:i + 12] == b"SDAT":
                    base = i + 12
                    tail = blob[base:base + need]
                    if len(tail) == need:
                        full += tail
                        srcmap.extend(range(base, base + need))
                        break
    return bytes(full), srcmap


def find_entry(manifest, name):
    matches = [(a, e) for a in manifest for e in a["entries"]
               if os.path.basename(e["name"].replace("\\", "/")).lower() == name.lower()]
    if not matches:
        raise RuntimeError("找不到条目: " + name)
    return matches[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", default=DEFAULT_ENTRY)
    ap.add_argument("--find", default="Start Game", help="按原文精确匹配")
    ap.add_argument("--index", type=int, default=0, help="按条目序号覆盖 --find")
    ap.add_argument("--text", default="HANHUA OK!", help="替换文本（单字节，等长或更短）")
    ap.add_argument("--list", action="store_true", help="只列出短的可显示字符串")
    ap.add_argument("--apply-to", default="", help="把差异写入指定 ISO 副本（原地改字节）")
    args = ap.parse_args()

    with open(MANIFEST, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)
    arc, e = find_entry(manifest, args.entry)
    iso_entry = arc["iso_offset"] + e["b"]
    print("条目 :", e["name"])
    print("位置 : ISO 0x%X | span=%d | 块数=%d"
          % (iso_entry, e["span"], len(e.get("refpack", []))), flush=True)

    with open(ISO, "rb") as f:
        f.seek(iso_entry)
        blob = f.read(e["span"])
    full, srcmap = build_full_with_map(blob)
    info = parse_lh2(full)
    print("解析 : count=%d declared=%d data=%d missing=%d"
          % (info["count"], info["total_declared"], info["data_size"], info["missing"]))

    rows = info["rows"]
    if args.list:
        shown = 0
        for r in rows:
            s = r["source"]
            if 3 <= len(s) <= 24 and s.isprintable() and not s.startswith(" "):
                p = r["offset"]
                raw = bytes.fromhex(r["raw_hex"])
                literal = all(x >= 0 for x in srcmap[p:p + len(raw)])
                print("  #%-5d len=%-3d %-9s %s" %
                      (r["index"], len(raw), "字面OK" if literal else "需重压", repr(s)))
                shown += 1
                if shown >= 60:
                    break
        return 0

    target = None
    if args.index:
        target = next((r for r in rows if r["index"] == args.index), None)
    else:
        target = next((r for r in rows if r["source"] == args.find), None)
    if target is None:
        print("未找到目标。用 --list 看候选，或换 --find/--index。")
        return 1

    raw = bytes.fromhex(target["raw_hex"])
    p, L = target["offset"], len(raw)
    print("目标 : #%d off=%d len=%d %r -> %r"
          % (target["index"], p, L, target["source"], args.text))

    # 1) 目标必须全部来自字面字节
    hits = srcmap[p:p + L]
    if len(hits) < L or any(x < 0 for x in hits):
        print("该字符串含 LZ 回引用字节，不能原地替换；需要 RefPack 重压器。")
        print("  srcmap:", hits[:20])
        return 2

    # 2) 新文本必须是单字节且不长于原串
    try:
        new_bytes = args.text.encode("latin-1")
    except UnicodeEncodeError:
        print("新文本含非单字节字符（中文）。中文显示需先扩展字库与字符映射，本阶段不支持。")
        return 3
    if len(new_bytes) > L:
        print("新文本 %d 字节 > 原串 %d 字节，超出等长替换范围。" % (len(new_bytes), L))
        return 3
    new_bytes = new_bytes + b"\x00" * (L - len(new_bytes))

    # 3) 原地写入压缩流
    edits, patched = [], bytearray(blob)
    for i, src in enumerate(hits):
        if blob[src] != raw[i]:
            raise RuntimeError("源映射校验失败 @%d" % i)
        if raw[i] != new_bytes[i]:
            patched[src] = new_bytes[i]
            edits.append({"iso_offset": iso_entry + src,
                          "old_hex": "%02X" % raw[i],
                          "new_hex": "%02X" % new_bytes[i]})
    print("差异 : %d 个字节需要改动" % len(edits))

    # 4) 闭环验证：重新解压，确认只有目标串变了，其它字节完全不变
    full2, _ = build_full_with_map(bytes(patched))
    ok = (len(full2) == len(full)
          and full2[:p] == full[:p]
          and full2[p:p + L] == new_bytes
          and full2[p + L:] == full[p + L:])
    print("闭环 : 重解压验证 %s（其余 %d 字节逐字节一致）"
          % ("PASS" if ok else "FAIL", len(full)))
    if not ok:
        return 4
    print("     新串 =", repr(full2[p:p + L].decode("latin-1").rstrip("\x00")))

    # 5) 写出补丁产物
    patch_dir = ensure_dir(CFG, "patch")
    out_json = os.path.join(patch_dir, "inplace_patch.json")
    out_bin = os.path.join(patch_dir, "patched_entry.bin")
    record = {
        "archive": arc["archive"], "entry": e["name"],
        "entry_b": e["b"], "entry_span": e["span"],
        "iso_entry_offset": iso_entry,
        "logical_offset": p, "length": L,
        "row_index": target["index"],
        "source": target["source"], "replacement": args.text,
        "literal_only": True, "verified": ok, "edits": edits,
    }
    with open(out_json, "w", encoding="utf-8") as fp:
        json.dump(record, fp, ensure_ascii=False, indent=1)
    with open(out_bin, "wb") as fp:
        fp.write(patched)
    print("产物 :", out_json, "|", out_bin, len(patched), "bytes")

    if args.apply_to:
        dest = args.apply_to
        if not os.path.exists(dest):
            print("目标 ISO 不存在:", dest)
            return 5
        with open(dest, "r+b") as f:
            for ed in edits:
                f.seek(ed["iso_offset"])
                cur = f.read(1)
                if cur.hex().upper() != ed["old_hex"]:
                    raise RuntimeError("ISO 内容不匹配 @0x%X：期望 %s 实际 %s"
                                       % (ed["iso_offset"], ed["old_hex"], cur.hex().upper()))
            for ed in edits:
                f.seek(ed["iso_offset"])
                f.write(bytes.fromhex(ed["new_hex"]))
            f.flush()
            os.fsync(f.fileno())
        print("已写入 ISO 副本:", dest, "|", len(edits), "字节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
