#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UTF-8 不等长文本替换 —— .lh2 字符串区重排 + 全副本覆盖。

为什么需要它
------------
`patch_all_copies.py` 只做**等长单字节**替换，中文既非单字节也几乎必然
不等长。实测 `inferno_global.en.lh2` 的本地化串就是标准 UTF-8（法语
`Création` = 43 72 c3 a9...，西语 `¡` = c2 a1，英文 `©` = c2 a9），
所以编码层不用改，只要处理「长度变了」带来的连带影响：

  1. 字符串区是 3294 条连续 NUL 结尾 C 串，中间没有空洞、没有共享指针、
     没有子串指针（已实测）。插长 2 字节后，后续所有字符串起点都要平移，
     偏移表 N 个 u32be 必须全部重算。
  2. `.lh2` 头 `full[0x04]` 声明的逻辑总大小要改。
  3. 容器头 `blob[0x34]` 的 SHDR「解压后总大小」也要改 —— 等长替换时
     两者值不变所以旧工具没动，不等长时漏改会导致游戏读截断。
  4. `0x84` 块长 / `0x8C` 流长 / FILL 随重压结果重算（条目物理长度不变，
     仍是 65536 字节，因此 TOC 不用动）。

安全约束：以 ISO 原块为唯一基准；只写定长条目块；写前校验目标块状态；
共用 `patch_all_copies.py` 的备份；`--check` 只做离线自测；`--restore`
一键还原全部副本。

用法（路径全部取自 config.local.json）:
  py -3 tools/patch_utf8_resize.py --check
  py -3 tools/patch_utf8_resize.py
  py -3 tools/patch_utf8_resize.py --restore
  py -3 tools/patch_utf8_resize.py --find "Start Game" --text "开始游戏"
"""
import argparse
import json
import os
import struct
import sys

from common import ensure_dir, load_config, report_path, resolve
from lh2_export import parse_lh2
from lh2_patch import build_full_with_map
from refpack import decompress, scan
from refpack_encode import compress
from patch_all_copies import (BACKUP_BIN, BLK_LEN, SHOC2, STREAM_LEN,
                              STREAM_OFF, find_copies, read_at, u32, write_at)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CFG = load_config()
ISO = resolve(CFG, "iso")
PATCH_DIR = ensure_dir(CFG, "patch")
MANIFEST = report_path(CFG, "viv_manifest.json")
META_JSON = os.path.join(PATCH_DIR, "utf8_resize_patch.json")

HDR_DECLARED = 0x34          # SHDR 中的「解压后逻辑总大小」


def resize_logical(full, find, text):
    """重排字符串区，返回 (新逻辑数据, 命中条目下标, 校验用全文列表)。"""
    info = parse_lh2(full)
    n = info["count"]
    ptr_off = 0x20 + 4 * n
    if ptr_off + 4 * n > len(full):
        raise RuntimeError("偏移表越界")
    declared = u32(full, 4)
    if declared != len(full):
        raise RuntimeError("逻辑数据长度 %d 与头声明 %d 不一致" % (len(full), declared))
    ptrs = [u32(full, ptr_off + 4 * i) for i in range(n)]

    rows = [r for r in info["rows"] if r["source"] == find]
    if not rows:
        raise RuntimeError("找不到匹配文本 %r" % find)
    new_bytes = text.encode("utf-8")
    if b"\x00" in new_bytes:
        raise RuntimeError("替换文本不能含 NUL")

    edits = []
    for r in rows:
        raw = bytes.fromhex(r["raw_hex"])
        p, L = r["offset"], len(raw)
        if p < ptr_off + 4 * n or p + L > len(full):
            raise RuntimeError("目标 #%d 偏移 0x%X 落在表区或越界" % (r["index"], p))
        if full[p + L] != 0:
            raise RuntimeError("目标 #%d 不是 NUL 结尾 C 串" % r["index"])
        edits.append((p, L, new_bytes))
    edits.sort(key=lambda x: x[0])
    for (p1, L1, _), (p2, _, _) in zip(edits, edits[1:]):
        if p1 + L1 > p2:
            raise RuntimeError("编辑区间重叠：0x%X / 0x%X" % (p1, p2))
    for q in ptrs:
        for p, L, _ in edits:
            if p < q < p + L:
                raise RuntimeError("偏移 0x%X 落在被替换串内部（子串指针）" % q)

    out = bytearray()
    cur = 0
    for p, L, nb in edits:
        out += full[cur:p]
        out += nb
        cur = p + L
    out += full[cur:]

    # q 要么等于某个编辑起点（不平移），要么在该编辑之后（累计平移）
    deltas = [(p, len(nb) - L) for p, L, nb in edits]
    for i, q in enumerate(ptrs):
        shifted = q + sum(d for p, d in deltas if p < q)
        struct.pack_into(">I", out, ptr_off + 4 * i, shifted)
    struct.pack_into(">I", out, 4, len(out))

    # 强校验：3294 条文本全量逐条比对，偏移表错一处就会大面积错位
    expected = [text if r["source"] == find else r["source"] for r in info["rows"]]
    got_info = parse_lh2(bytes(out))
    got = [r["source"] for r in got_info["rows"]]
    if got != expected:
        for i, (a, b) in enumerate(zip(expected, got)):
            if a != b:
                raise RuntimeError("重排后第 %d 条文本错位：期望 %r 实得 %r"
                                   % (i, a[:40], b[:40]))
        raise RuntimeError("重排后条目数不符：%d != %d" % (len(got), len(expected)))
    if got_info["missing"]:
        raise RuntimeError("重排后有 %d 条偏移越界" % got_info["missing"])

    return bytes(out), [r["index"] for r in rows], expected


def rebuild_entry(blob, find, text, span, candidates):
    """重排 + 重压单个条目块，返回 (补丁块, 命中下标, 元数据)。"""
    if not (blob[0x0C:0x10] == b"SHOC" and blob[SHOC2:SHOC2 + 4] == b"SHOC"
            and blob[0x88:0x8C] == b"Rpak"):
        raise RuntimeError("SHOC 头布局不符合预期")
    blocks = scan(blob, limit=32)
    if len(blocks) != 1:
        raise RuntimeError("只支持单压缩块条目")
    off, used, _, _ = blocks[0]
    if off != STREAM_OFF or u32(blob, STREAM_LEN) != used:
        raise RuntimeError("流位置/长度字段与实测不一致")
    old_pad = (4 - (off + used) % 4) % 4
    if u32(blob, BLK_LEN) != 16 + used + old_pad:
        raise RuntimeError("0x84 块长度公式不符")

    full, _ = build_full_with_map(blob)
    if u32(blob, HDR_DECLARED) != len(full):
        raise RuntimeError("SHDR 解压后大小 %d != 逻辑数据 %d"
                           % (u32(blob, HDR_DECLARED), len(full)))
    new_full, indices, expected = resize_logical(full, find, text)

    packed = compress(new_full, candidates=candidates)
    new_len = len(packed)
    new_pad = (4 - (off + new_len) % 4) % 4
    aligned = off + new_len + new_pad
    fill = span - aligned
    if fill < 8:
        raise RuntimeError("FILL 空间不足，可提高 --candidates")

    patched = bytearray(span)
    patched[:off] = blob[:off]
    struct.pack_into(">I", patched, HDR_DECLARED, len(new_full))
    struct.pack_into(">I", patched, BLK_LEN, 16 + new_len + new_pad)
    struct.pack_into(">I", patched, STREAM_LEN, new_len)
    patched[off:off + new_len] = packed
    patched[aligned:aligned + 4] = b"FILL"
    struct.pack_into(">H", patched, aligned + 6, fill)

    rebuilt = b"".join(decompress(bytes(patched), o)[0]
                       for o, _u, _n, _x in scan(bytes(patched), limit=32))
    if rebuilt != new_full:
        raise RuntimeError("重解压与重排后逻辑数据不一致")
    got = [r["source"] for r in parse_lh2(rebuilt)["rows"]]
    if got != expected:
        raise RuntimeError("重解压后文本表与预期不符")
    if u32(patched, HDR_DECLARED) != len(new_full):
        raise RuntimeError("SHDR 解压后大小未同步")
    return bytes(patched), indices, expected, {
        "count": len(expected),
        "old_logical_len": len(full), "new_logical_len": len(new_full),
        "old_stream_len": used, "new_stream_len": new_len,
        "new_pad": new_pad, "fill_size": fill,
        "old_fill": struct.unpack_from(">H", blob, off + used + old_pad + 6)[0],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", default="inferno_global.en.lh2")
    ap.add_argument("--find", default="Start Game")
    ap.add_argument("--text", default="开始游戏")
    ap.add_argument("--candidates", type=int, default=32)
    ap.add_argument("--check", action="store_true", help="只做离线自测与状态检查")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--also-iso", action="store_true",
                    help="同时写测试 ISO 副本（可选）")
    args = ap.parse_args()

    with open(MANIFEST, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)
    copies = find_copies(manifest, args.entry)
    if not copies:
        print("找不到条目", args.entry)
        return 2
    print("副本 : %d 份" % len(copies),
          ["VIV内0x%X" % c["viv_internal_offset"] for c in copies])

    originals = [read_at(ISO, c["iso_entry_offset"], c["span"]) for c in copies]
    if any(b != originals[0] for b in originals):
        print("各副本 ISO 原块不一致，拒绝处理。")
        return 3
    original = originals[0]
    span = copies[0]["span"]
    print("基准 : ISO 原块 %d 字节，所有副本一致 = True" % span)

    disc_dir = resolve(CFG, "rpcs3_disc_dir")
    targets = [{"path": os.path.join(disc_dir, "PS3_GAME", "USRDIR", c["archive"]),
                "offset": c["viv_internal_offset"]} for c in copies]
    if args.also_iso:
        test_iso = os.path.join(resolve(CFG, "build"), "Dante-Hanhua-Test.iso")
        if os.path.isfile(test_iso):
            targets += [{"path": test_iso, "offset": c["iso_entry_offset"]}
                        for c in copies]
    for t in targets:
        if not os.path.isfile(t["path"]):
            print("目标不存在:", t["path"])
            return 3

    if args.restore:
        if not os.path.isfile(BACKUP_BIN):
            print("没有备份，无法还原:", BACKUP_BIN)
            return 4
        with open(BACKUP_BIN, "rb") as fp:
            backup = fp.read()
        if backup != original:
            print("备份与 ISO 原块不一致，拒绝还原。")
            return 4
        if args.check:
            print("检查 : 可执行还原（备份校验通过）")
            return 0
        for t in targets:
            write_at(t["path"], t["offset"], backup)
        okall = all(read_at(t["path"], t["offset"], span) == backup for t in targets)
        print("还原 : %d 个目标，回读一致=%s" % (len(targets), okall))
        return 0 if okall else 5

    patched, indices, expected, details = rebuild_entry(
        original, args.find, args.text, span, args.candidates)
    print("重排 : %r -> %r | 命中 %s | 逻辑数据 %d -> %d 字节 (+%d)"
          % (args.find, args.text, indices, details["old_logical_len"],
             details["new_logical_len"],
             details["new_logical_len"] - details["old_logical_len"]))
    print("重压 : 流 %d -> %d | FILL %d -> %d | pad=%d"
          % (details["old_stream_len"], details["new_stream_len"],
             details["old_fill"], details["fill_size"], details["new_pad"]))
    print("编码 : %r -> %s" % (args.text, args.text.encode("utf-8").hex()))
    print("自测 : 文本表 %d 条全量比对 PASS | SHDR/头字段自洽 PASS" % len(expected))

    states = [read_at(t["path"], t["offset"], span) for t in targets]
    if any(s not in (original, patched) for s in states):
        print("某目标块既非 ISO 原块也非本补丁，请先执行：")
        print("  py -3 tools/patch_all_copies.py --restore")
        return 4
    if not os.path.isfile(BACKUP_BIN):
        with open(BACKUP_BIN, "wb") as fp:
            fp.write(original)
        print("备份 :", BACKUP_BIN)
    else:
        with open(BACKUP_BIN, "rb") as fp:
            if fp.read() != original:
                print("已有备份与 ISO 原块不符，拒绝覆盖备份。")
                return 4
        print("备份 : 已存在且校验通过，复用")

    if args.check:
        print("检查 : 可安全写入 | 目标数=%d | 离线自测 PASS" % len(targets))
        return 0

    for t in targets:
        write_at(t["path"], t["offset"], patched)
    print("写入 : %d 个目标完成" % len(targets))

    ok = True
    for t in targets:
        blob = read_at(t["path"], t["offset"], span)
        full, _ = build_full_with_map(blob)
        got = [r["source"] for r in parse_lh2(full)["rows"]]
        same = got == expected
        hits = [i for i, s in enumerate(got) if s == args.text]
        # 目标文本可能本来就存在于其它条目（例如「日本語」是游戏自带的语言选项名），
        # 不能要求「出现次数 == 命中数」，只需确认所有命中下标都已生效即可。
        extra = [i for i in hits if i not in indices]
        left = [i for i in indices if i < len(got) and got[i] == args.find]
        good = same and set(indices).issubset(hits) and not left
        print("回读 : %s @ 0x%X -> %s | 条目=%d 全文一致=%s 新串命中=%s 原有同文=%s 旧串残留=%s"
              % (os.path.basename(t["path"]), t["offset"], "PASS" if good else "FAIL",
                 len(got), same, hits, extra, left))
        ok = ok and good

    with open(META_JSON, "w", encoding="utf-8") as fp:
        json.dump({"entry": args.entry, "find": args.find, "text": args.text,
                   "copies": copies, "targets": targets, "indices": indices,
                   "details": details, "verified": ok}, fp,
                  ensure_ascii=False, indent=1)
    print("结论 : %s" % ("PASS — 完全退出并重启 RPCS3 后观察主菜单渲染效果" if ok else "FAIL"))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
