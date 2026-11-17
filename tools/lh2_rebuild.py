#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重压单个 .lh2 条目并原地回填 —— 让任意菜单文本都能改。

lh2_patch.py 的「只改字面字节」方案对菜单项无效（"Start Game" 等被 LZ
回引用压过）。本工具把整个逻辑数据重新压缩，因此不受回引用限制。

条目结构（实测 BIGFILE0 的 inferno_global/dialog.en.lh2，均为 65536 字节）：
  0x00  "ols3" + 头
  0x0C  "SHOC"  0x10 u32be = 116（第一块头长度）
  0x14  "SHDR" + 元数据
  0x3C  u32be 解压后总大小
  0x3E  文件名 / 路径 / "LH2"
  0x80  "SHOC"
  0x84  u32be 数据块长度 = 16 + 流长 + 对齐填充
  0x88  "Rpak"
  0x8C  u32be RefPack 流长度
  0x90  RefPack 流
  ...   对齐 0（到 4 字节边界）
  ...   "FILL" + u16 0 + u16be fill_size，其后全 0，直到条目末尾

重压后同步修正 0x84 / 0x8C 与 FILL 长度，条目总长始终不变，因此
SHOC 段结构、VIV 条目长度、TOC、.lh2 头与字符串偏移表都不用动。

当前阶段仍是**等长单字节替换**：新文本须能编码为 latin-1 且不长于原串
（短了补 NUL）。中文显示需要扩字库与字符映射，是下一阶段。

产物（patch/，已 gitignore）：
  patch/rebuild_patch.json    元数据与容量/校验结果（不含游戏原文）
  patch/patched_entry.bin     修改后的完整 VIV 条目块

用法:
  py -3 tools/lh2_rebuild.py --find "Start Game" --text "HANHUA OK!"
  py -3 tools/lh2_rebuild.py --index 263 --text "HANHUA OK!" --apply-to "G:/DanteHanhua/build/test.iso"
"""
import argparse
import json
import os
import struct
import sys

from common import ensure_dir, load_config, report_path, resolve
from lh2_export import parse_lh2
from lh2_patch import build_full_with_map, find_entry
from refpack import decompress, scan
from refpack_encode import compress

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CFG = load_config()
ISO = resolve(CFG, "iso")
MANIFEST = report_path(CFG, "viv_manifest.json")

SHOC2 = 0x80
BLK_LEN = 0x84
STREAM_LEN = 0x8C
STREAM_OFF = 0x90


def u32(b, p):
    return struct.unpack_from(">I", b, p)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", default="inferno_global.en.lh2")
    ap.add_argument("--find", default="Start Game")
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--text", default="HANHUA OK!")
    ap.add_argument("--candidates", type=int, default=32, help="LZ 候选数，越大压缩率越好")
    ap.add_argument("--apply-to", default="", help="把整段条目写入指定 ISO 副本")
    args = ap.parse_args()

    with open(MANIFEST, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)
    arc, e = find_entry(manifest, args.entry)
    iso_entry = arc["iso_offset"] + e["b"]
    with open(ISO, "rb") as f:
        f.seek(iso_entry)
        blob = f.read(e["span"])

    # 校验 SHOC 头布局，避免写错条目
    if not (blob[0x0C:0x10] == b"SHOC" and blob[SHOC2:SHOC2 + 4] == b"SHOC"
            and blob[0x88:0x8C] == b"Rpak"):
        print("SHOC 头布局不符合预期，拒绝处理。")
        return 2
    blocks = scan(blob, limit=32)
    if len(blocks) != 1:
        print("当前只处理单压缩块条目；多块需要分段重压。")
        return 2
    off, used, _out_len, _ = blocks[0]
    if off != STREAM_OFF or u32(blob, STREAM_LEN) != used:
        print("流位置/长度字段与实测不一致：off=%d rpak_len=%d used=%d"
              % (off, u32(blob, STREAM_LEN), used))
        return 2
    old_pad = (4 - (off + used) % 4) % 4
    if u32(blob, BLK_LEN) != 16 + used + old_pad:
        print("0x84 块长度公式不符，拒绝处理。")
        return 2
    print("条目 :", e["name"], "| ISO 0x%X | span=%d" % (iso_entry, e["span"]))
    print("头   : 解压后=%d 流长=%d 块长=%d pad=%d FILL=%d"
          % (u32(blob, 0x34), used, u32(blob, BLK_LEN), old_pad,
             struct.unpack_from(">H", blob, off + used + old_pad + 6)[0]))

    full, _ = build_full_with_map(blob)
    info = parse_lh2(full)
    print("解析 : count=%d declared=%d data=%d"
          % (info["count"], info["total_declared"], info["data_size"]))

    target = None
    if args.index:
        target = next((r for r in info["rows"] if r["index"] == args.index), None)
    else:
        target = next((r for r in info["rows"] if r["source"] == args.find), None)
    if target is None:
        print("未找到目标。可用 --index 指定。")
        return 1
    raw = bytes.fromhex(target["raw_hex"])
    p, L = target["offset"], len(raw)
    print("目标 : #%d off=%d len=%d %r -> %r"
          % (target["index"], p, L, target["source"], args.text))

    try:
        new_bytes = args.text.encode("latin-1")
    except UnicodeEncodeError:
        print("新文本含非单字节字符（中文）；需先扩展字库与字符映射。")
        return 3
    if len(new_bytes) > L:
        print("新文本 %d 字节 > 原串 %d 字节，等长替换放不下。" % (len(new_bytes), L))
        return 3
    new_bytes = new_bytes + b"\x00" * (L - len(new_bytes))

    modified = bytearray(full)
    modified[p:p + L] = new_bytes
    packed = compress(bytes(modified), candidates=args.candidates)
    new_len = len(packed)
    new_pad = (4 - (off + new_len) % 4) % 4
    aligned = off + new_len + new_pad
    fill = e["span"] - aligned
    print("重压 : 流 %d -> %d 字节 | pad=%d | FILL %d -> %d"
          % (used, new_len, new_pad,
             struct.unpack_from(">H", blob, off + used + old_pad + 6)[0], fill),
          flush=True)
    if fill < 8:
        print("FILL 空间不足（需 >= 8 字节）；可提高 --candidates 减小压缩流。")
        return 4

    # 重建整个条目：保留 0x90 之前的头，改两个长度字段，写新流 + FILL
    patched = bytearray(e["span"])
    patched[:off] = blob[:off]
    struct.pack_into(">I", patched, BLK_LEN, 16 + new_len + new_pad)
    struct.pack_into(">I", patched, STREAM_LEN, new_len)
    patched[off:off + new_len] = packed
    patched[aligned:aligned + 4] = b"FILL"
    struct.pack_into(">H", patched, aligned + 6, fill)

    # 闭环验证：重新解压必须与目标逻辑数据逐字节一致，且头字段自洽
    rebuilt = b"".join(decompress(bytes(patched), o)[0]
                       for o, _u, _n, _x in scan(bytes(patched), limit=32))
    ok = (rebuilt == bytes(modified)
          and u32(patched, STREAM_LEN) == new_len
          and u32(patched, BLK_LEN) == 16 + new_len + new_pad
          and patched[aligned:aligned + 4] == b"FILL"
          and struct.unpack_from(">H", patched, aligned + 6)[0] == fill)
    print("闭环 : 重解压 %s (%d 字节) | 新串=%r | 头字段自洽=%s"
          % ("PASS" if rebuilt == bytes(modified) else "FAIL", len(rebuilt),
             rebuilt[p:p + L].decode("latin-1").rstrip("\x00"), ok))
    if not ok:
        return 5

    patch_dir = ensure_dir(CFG, "patch")
    out_json = os.path.join(patch_dir, "rebuild_patch.json")
    out_bin = os.path.join(patch_dir, "patched_entry.bin")
    with open(out_json, "w", encoding="utf-8") as fp:
        json.dump({"archive": arc["archive"], "entry": e["name"],
                   "iso_entry_offset": iso_entry, "entry_span": e["span"],
                   "stream_offset": off, "old_stream_len": used,
                   "new_stream_len": new_len, "new_pad": new_pad,
                   "fill_size": fill, "logical_offset": p, "length": L,
                   "row_index": target["index"], "replacement": args.text,
                   "verified": ok}, fp, ensure_ascii=False, indent=1)
    with open(out_bin, "wb") as fp:
        fp.write(patched)
    print("产物 :", out_json, "|", out_bin, len(patched), "bytes")

    if args.apply_to:
        dest = args.apply_to
        if not os.path.exists(dest):
            print("目标 ISO 不存在:", dest)
            return 6
        with open(dest, "r+b") as f:
            f.seek(iso_entry)
            cur = f.read(e["span"])
            if cur != blob:
                raise RuntimeError("ISO 副本该条目与原版不一致，拒绝写入")
            f.seek(iso_entry)
            f.write(patched)
            f.flush()
            os.fsync(f.fileno())
        print("已写入 ISO 副本:", dest, "|", e["span"], "字节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
