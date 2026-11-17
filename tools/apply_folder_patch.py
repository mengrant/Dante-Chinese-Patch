#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把已验证的 VIV 条目补丁覆盖到「文件夹格式」游戏（散文件覆盖验证）。

背景
----
源 ISO 是未解密的 PS3 光盘镜像，RPCS3 缺 region information / IRD，直接
Add Games 挂载 ISO 会报：

    ISO: init: Failed to read region information (region_count=0)
    ISO: iso_archive: Corrupt ISO file ... Decryption failed
    SYS: Failed to load ISO.

并弹出「没有内容可以添加！未能找到任何新的软件。」

但本机已有从同一镜像解包出来的文件夹格式游戏，RPCS3 游戏列表里也已登记；
实测其 BIGFILE0.VIV 在相同内部偏移处的条目与 ISO 原块逐字节一致。因此
只需覆盖那一个 65536 字节的条目，即可在 RPCS3 里验证，无需重打包 9 GB ISO，
也无需挂载 ISO。

安全约束
--------
- 只写 VIV 内一个定长条目块（默认 65536 字节），不改动文件长度、TOC、任何其他文件。
- 写入前校验目标块与原 ISO 对应块一致；不一致就拒绝写入。
- 首次写入前把原块备份到 patch/folder_original_entry.bin，`--restore` 可一键还原。
- 写后回读，并从磁盘重新解压 .lh2，确认目标字符串确实生效。

用法（路径都从 config.local.json 读取，脚本不含本机路径）:
  py -3 tools/apply_folder_patch.py --check
  py -3 tools/apply_folder_patch.py
  py -3 tools/apply_folder_patch.py --restore
"""
import argparse
import json
import os
import sys

from common import ensure_dir, load_config, report_path, resolve
from lh2_export import parse_lh2
from lh2_patch import build_full_with_map

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CFG = load_config()
ISO = resolve(CFG, "iso")
PATCH_DIR = ensure_dir(CFG, "patch")
MANIFEST = report_path(CFG, "viv_manifest.json")
PATCH_JSON = os.path.join(PATCH_DIR, "rebuild_patch.json")
PATCH_BIN = os.path.join(PATCH_DIR, "patched_entry.bin")
BACKUP_BIN = os.path.join(PATCH_DIR, "folder_original_entry.bin")


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


def verify_text(blob, row_index, expected):
    """从磁盘读回的条目块重新解压，确认目标字符串生效。"""
    full, _ = build_full_with_map(blob)
    info = parse_lh2(full)
    row = next((r for r in info["rows"] if r["index"] == row_index), None)
    if row is None:
        return False, "找不到第 %d 条" % row_index, info
    got = row["source"]
    return got == expected, "%r (期望 %r)" % (got, expected), info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查，不写盘")
    ap.add_argument("--restore", action="store_true", help="从备份还原原块")
    args = ap.parse_args()

    with open(PATCH_JSON, "r", encoding="utf-8") as fp:
        meta = json.load(fp)
    if not meta.get("verified"):
        print("补丁元数据未通过闭环验证，拒绝写入。")
        return 2
    with open(MANIFEST, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)
    arc = next((a for a in manifest if a["archive"] == meta["archive"]), None)
    if arc is None:
        print("manifest 里找不到", meta["archive"])
        return 2

    span = meta["entry_span"]
    iso_off = meta["iso_entry_offset"]
    viv_off = iso_off - arc["iso_offset"]
    disc_dir = resolve(CFG, "rpcs3_disc_dir")
    target = os.path.join(disc_dir, "PS3_GAME", "USRDIR", meta["archive"])

    print("镜像块 : ISO 0x%X (VIV 内 0x%X), %d 字节" % (iso_off, viv_off, span))
    print("目标   :", target)
    if not os.path.isfile(target):
        print("目标 VIV 不存在，请检查 config.local.json 的 rpcs3_disc_dir。")
        return 3
    size = os.path.getsize(target)
    if size != arc["size"]:
        print("目标 VIV 大小 %d 与 manifest %d 不符，拒绝写入。" % (size, arc["size"]))
        return 3

    original = read_at(ISO, iso_off, span)
    current = read_at(target, viv_off, span)
    with open(PATCH_BIN, "rb") as fp:
        patched = fp.read()
    if len(patched) != span:
        print("补丁块长度 %d != %d" % (len(patched), span))
        return 3

    if args.restore:
        if not os.path.isfile(BACKUP_BIN):
            print("没有备份文件，无法还原：", BACKUP_BIN)
            return 4
        with open(BACKUP_BIN, "rb") as fp:
            backup = fp.read()
        if backup != original:
            print("备份与原 ISO 块不一致，拒绝还原。")
            return 4
        if current == backup:
            print("当前已是原版，无需还原。")
            return 0
        if args.check:
            print("可执行还原（当前为补丁态）。")
            return 0
        write_at(target, viv_off, backup)
        after = read_at(target, viv_off, span)
        ok, msg, _ = verify_text(after, meta["row_index"], "Start Game")
        print("还原 : %s | 回读一致=%s | 文本=%s" % ("OK" if after == backup else "FAIL",
                                                  after == backup, msg))
        return 0 if after == backup and ok else 5

    # 应用补丁：目标块必须与 ISO 原块（或已应用的补丁块）一致
    if current == patched:
        print("当前已是补丁态，无需重复写入。")
    elif current != original:
        print("目标块与原 ISO 不一致（可能已被其他补丁改过），拒绝写入。")
        return 4
    else:
        if not os.path.isfile(BACKUP_BIN):
            with open(BACKUP_BIN, "wb") as fp:
                fp.write(current)
            print("备份 :", BACKUP_BIN, len(current), "字节")
        else:
            with open(BACKUP_BIN, "rb") as fp:
                if fp.read() != original:
                    print("已有备份与原 ISO 块不符，拒绝覆盖备份。")
                    return 4
            print("备份 : 已存在且校验通过，复用")
        if args.check:
            ok, msg, _ = verify_text(patched, meta["row_index"], meta["replacement"])
            print("检查 : 可安全写入 | 补丁内文本=%s" % msg)
            return 0 if ok else 5
        write_at(target, viv_off, patched)
        print("写入 : 完成")

    after = read_at(target, viv_off, span)
    ok, msg, info = verify_text(after, meta["row_index"], meta["replacement"])
    print("回读 : 与补丁块一致=%s" % (after == patched))
    print("解压 : count=%d | #%d = %s" % (info["count"], meta["row_index"], msg))
    print("结论 : %s" % ("PASS — 可在 RPCS3 启动已登记的 BLUS30405 验证"
                      if after == patched and ok else "FAIL"))
    return 0 if after == patched and ok else 5


if __name__ == "__main__":
    sys.exit(main())
