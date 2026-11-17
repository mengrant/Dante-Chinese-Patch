#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""覆盖 VIV 内同名 .lh2 的「所有副本」+「所有匹配文本」—— 菜单文本补丁闭环。

为什么需要它
------------
BIGH 归档里同一个逻辑文件会存**多份完全相同的物理副本**：TOC 里是两条
独立记录（A 哈希不同），但条目头里的路径字符串同名、内容逐字节一致。游戏
按哈希查表，可能命中任意一份，所以只改第一份时菜单仍显示原文。

同一个句子在 .lh2 里也可能出现多次（例如 inferno_global.en.lh2 里
`Start Game` 有 #263 和 #1162 两条），UI 按字符串 ID 引用，因此必须把所有
匹配项一起替换，否则改的那条不一定是屏幕上显示的那条。

本工具：找全部副本 → 校验内容一致 → 重压一次生成补丁块 → 把所有匹配串
等长替换 → 回写每一个副本 → 从磁盘回读重新解压验证。

安全约束：只写定长条目块，不改文件长度 / TOC / 任何其他文件；首次运行
备份原块；`--restore` 一键还原全部副本。

用法（路径全部取自 config.local.json，脚本不含本机路径）:
  py -3 tools/patch_all_copies.py --check
  py -3 tools/patch_all_copies.py
  py -3 tools/patch_all_copies.py --restore
  py -3 tools/patch_all_copies.py --find "Load Game" --text "LOAD OK!!"
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

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CFG = load_config()
ISO = resolve(CFG, "iso")
PATCH_DIR = ensure_dir(CFG, "patch")
MANIFEST = report_path(CFG, "viv_manifest.json")
BACKUP_BIN = os.path.join(PATCH_DIR, "all_copies_original.bin")
META_JSON = os.path.join(PATCH_DIR, "all_copies_patch.json")

SHOC2, BLK_LEN, STREAM_LEN, STREAM_OFF = 0x80, 0x84, 0x8C, 0x90


def u32(b, p):
    return struct.unpack_from(">I", b, p)[0]


def read_at(path, offset, length):
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(length)
    if len(data) != length:
        raise RuntimeError("读取不足 %d 字节：%s @ %d" % (length, path, offset))
    return data


def write_at(path, offset, data):
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def find_copies(manifest, basename):
    out = []
    for arc in manifest:
        for e in arc["entries"]:
            name = os.path.basename(e.get("name", "").replace("\\", "/"))
            if name.lower() == basename.lower():
                out.append({
                    "archive": arc["archive"],
                    "viv_iso_offset": arc["iso_offset"],
                    "iso_entry_offset": arc["iso_offset"] + e["b"],
                    "viv_internal_offset": e["b"],
                    "span": e["span"],
                    "toc_a": e["a"],
                })
    return out


def rebuild(blob, find, text, span, candidates):
    """把 blob 内所有精确匹配 find 的字符串等长替换为 text，重压整个条目。"""
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
    info = parse_lh2(full)
    rows = [r for r in info["rows"] if r["source"] == find]
    if not rows:
        raise RuntimeError("找不到匹配文本 %r" % find)
    try:
        new_bytes = text.encode("latin-1")
    except UnicodeEncodeError:
        raise RuntimeError("新文本含非单字节字符（中文需先扩字库）")

    modified = bytearray(full)
    for r in rows:
        raw = bytes.fromhex(r["raw_hex"])
        p, L = r["offset"], len(raw)
        if len(new_bytes) > L:
            raise RuntimeError("新文本 %d 字节 > 原串 %d 字节" % (len(new_bytes), L))
        modified[p:p + L] = new_bytes + b"\x00" * (L - len(new_bytes))

    packed = compress(bytes(modified), candidates=candidates)
    new_len = len(packed)
    new_pad = (4 - (off + new_len) % 4) % 4
    aligned = off + new_len + new_pad
    fill = span - aligned
    if fill < 8:
        raise RuntimeError("FILL 空间不足，可提高 --candidates")

    patched = bytearray(span)
    patched[:off] = blob[:off]
    struct.pack_into(">I", patched, BLK_LEN, 16 + new_len + new_pad)
    struct.pack_into(">I", patched, STREAM_LEN, new_len)
    patched[off:off + new_len] = packed
    patched[aligned:aligned + 4] = b"FILL"
    struct.pack_into(">H", patched, aligned + 6, fill)

    rebuilt = b"".join(decompress(bytes(patched), o)[0]
                       for o, _u, _n, _x in scan(bytes(patched), limit=32))
    if rebuilt != bytes(modified):
        raise RuntimeError("重解压与逻辑数据不一致")
    for r in rows:
        got = bytes(rebuilt[r["offset"]:r["offset"] + len(bytes.fromhex(r["raw_hex"]))])
        if got.decode("latin-1").rstrip("\x00") != text:
            raise RuntimeError("第 %d 条替换后校验失败: %r" % (r["index"], got))
    return bytes(patched), [r["index"] for r in rows], {
        "count": info["count"], "old_stream_len": used, "new_stream_len": new_len,
        "new_pad": new_pad, "fill_size": fill,
    }


def verify_from_disk(path, offset, span, find, text, expected_indices):
    blob = read_at(path, offset, span)
    full, _ = build_full_with_map(blob)
    info = parse_lh2(full)
    hits = [r["index"] for r in info["rows"] if r["source"] == text]
    left = [r["index"] for r in info["rows"] if r["source"] == find]
    ok = (set(hits) == set(expected_indices) and not left)
    return ok, "count=%d 新串=%s 旧串残留=%s" % (info["count"], hits, left)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", default="inferno_global.en.lh2")
    ap.add_argument("--find", default="Start Game")
    ap.add_argument("--text", default="HANHUA OK!")
    ap.add_argument("--candidates", type=int, default=32)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--also-iso", action="store_true",
                    help="同时写测试 ISO 副本（可选，默认只写文件夹格式游戏）")
    args = ap.parse_args()

    with open(MANIFEST, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)
    copies = find_copies(manifest, args.entry)
    if not copies:
        print("找不到条目", args.entry)
        return 2
    print("副本 : %d 份" % len(copies), [("VIV内0x%X" % c["viv_internal_offset"]) for c in copies])

    # 以 ISO 原块为唯一基准，保证可重复、不依赖当前磁盘状态
    originals = [read_at(ISO, c["iso_entry_offset"], c["span"]) for c in copies]
    if any(b != originals[0] for b in originals):
        print("各副本原块内容不一致，需逐个重压，当前工具拒绝处理。")
        return 3
    original = originals[0]
    span = copies[0]["span"]
    print("基准 : ISO 原块 %d 字节，所有副本一致 = True" % span)

    disc_dir = resolve(CFG, "rpcs3_disc_dir")
    targets = []
    for c in copies:
        fv = os.path.join(disc_dir, "PS3_GAME", "USRDIR", c["archive"])
        targets.append({"path": fv, "offset": c["viv_internal_offset"]})
    if args.also_iso:
        test_iso = os.path.join(resolve(CFG, "build"), "Dante-Hanhua-Test.iso")
        if os.path.isfile(test_iso):
            for c in copies:
                targets.append({"path": test_iso, "offset": c["iso_entry_offset"]})

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

    patched, indices, details = rebuild(original, args.find, args.text,
                                        span, args.candidates)
    print("重压 : %r -> %r | 命中条目 %s | 流 %d -> %d | FILL %d"
          % (args.find, args.text, indices, details["old_stream_len"],
             details["new_stream_len"], details["fill_size"]))

    # 写前状态检查 + 备份
    states = [read_at(t["path"], t["offset"], span) for t in targets]
    if any(s not in (original, patched) for s in states):
        print("某目标块既不是原版也不是本补丁，可能被其他修改动过，拒绝写入。")
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
        print("检查 : 可安全写入 | 目标数=%d | 补丁自校验 PASS" % len(targets))
        return 0

    for t in targets:
        write_at(t["path"], t["offset"], patched)
    print("写入 : %d 个目标完成" % len(targets))

    ok = True
    for t in targets:
        good, msg = verify_from_disk(t["path"], t["offset"], span,
                                    args.find, args.text, indices)
        print("回读 : %s @ 0x%X -> %s | %s"
              % (os.path.basename(t["path"]), t["offset"],
                 "PASS" if good else "FAIL", msg))
        ok = ok and good

    with open(META_JSON, "w", encoding="utf-8") as fp:
        json.dump({"entry": args.entry, "find": args.find, "text": args.text,
                   "copies": copies, "targets": targets, "indices": indices,
                   "details": details, "verified": ok}, fp,
                  ensure_ascii=False, indent=1)
    print("结论 : %s" % ("PASS — 重启游戏后应看到 %r" % args.text if ok else "FAIL"))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
