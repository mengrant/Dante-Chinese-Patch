#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RPCS3 系统字体实验：把简中 CJK 字体挂到 cellFont 会请求的文件名上。

背景（见 WORKLOG 第 16 节）：
  RPCS3 的 cellFontOpenFontset() 把字体类型**硬编码**映射到
  /dev_flash/data/font/SCE-PS3-*.TTF，且所有 *_SET 类型都回退到
  SCE-PS3-RD-R-LATIN.TTF（38 KB，纯拉丁）。固件里 8.2 MB 的
  SCE-PS3-DH-R-CGB.TTF（20902 个 CJK 汉字）根本不在映射表内。
  这可以解释「é 正常显示 / 汉字变方块」，且暗示一条不用改游戏文件、
  不用扩图集、不用改 BIGH TOC 的验证路径。

本工具只动 RPCS3 的 dev_flash/data/font/*.TTF，不碰游戏 ISO / VIV / DLC。
所有被覆盖的原文件都完整备份到 patch/font_backup/，可一键还原。

用法（在 G:\\DanteHanhua 下）：
  py -3 tools/try_system_font.py --check      # 只读查看当前状态
  py -3 tools/try_system_font.py --apply      # 备份后替换（需用户确认）
  py -3 tools/try_system_font.py --restore    # 从备份完整还原

实验后必须**完全退出并重启 RPCS3**（字体在启动时加载）。
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, resolve

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SOURCE = "SCE-PS3-DH-R-CGB.TTF"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="只读查看状态")
    g.add_argument("--apply", action="store_true", help="备份并替换")
    g.add_argument("--restore", action="store_true", help="从备份还原")
    args = ap.parse_args()

    cfg = load_config()
    root = resolve(cfg, "rpcs3_root")
    font_dir = os.path.join(root, "dev_flash", "data", "font")
    backup_dir = os.path.join(resolve(cfg, "patch"), "font_backup")
    manifest_path = os.path.join(resolve(cfg, "patch"), "font_backup.json")
    src = os.path.join(font_dir, SOURCE)

    if not os.path.isfile(src):
        print("FAIL 找不到简中字体:", src)
        return 2
    targets = sorted(f for f in os.listdir(font_dir)
                     if f.upper().endswith(".TTF") and f != SOURCE
                     and os.path.isfile(os.path.join(font_dir, f)))
    src_hash = sha256(src)
    src_size = os.path.getsize(src)
    print("字体目录 : %s" % font_dir)
    print("字形来源 : %s (%d B, sha256=%s...)" % (SOURCE, src_size, src_hash[:16]))
    print("可覆盖   : %d 个 TTF" % len(targets))

    if args.check:
        print("\n=== 当前状态 ===")
        patched = [f for f in targets
                   if sha256(os.path.join(font_dir, f)) == src_hash]
        print("  已替换为 CGB 字体的文件: %d / %d" % (len(patched), len(targets)))
        for f in patched[:8]:
            print("    ", f)
        print("  备份目录存在: %s" % os.path.isdir(backup_dir))
        print("  备份清单存在: %s" % os.path.isfile(manifest_path))
        return 0

    if args.restore:
        if not os.path.isfile(manifest_path):
            print("FAIL 没有备份清单，无法还原:", manifest_path)
            return 2
        man = json.load(open(manifest_path, encoding="utf-8"))
        n = 0
        for name, meta in man["files"].items():
            bpath = os.path.join(backup_dir, name)
            if not os.path.isfile(bpath):
                print("  跳过（备份缺失）:", name)
                continue
            if sha256(bpath) != meta["sha256"]:
                print("  跳过（备份校验不符）:", name)
                continue
            shutil.copy2(bpath, os.path.join(font_dir, name))
            n += 1
        print("还原完成: %d / %d 个文件" % (n, len(man["files"])))
        return 0 if n == len(man["files"]) else 1

    # --apply
    os.makedirs(backup_dir, exist_ok=True)
    man = {"source": SOURCE, "source_sha256": src_hash, "files": {}}
    for name in targets:
        path = os.path.join(font_dir, name)
        bpath = os.path.join(backup_dir, name)
        if not os.path.isfile(bpath):
            shutil.copy2(path, bpath)
        man["files"][name] = {"size": os.path.getsize(bpath),
                              "sha256": sha256(bpath)}
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(man, fp, ensure_ascii=False, indent=1)

    n = 0
    for name in targets:
        shutil.copy2(src, os.path.join(font_dir, name))
        n += 1
    print("\n已替换 %d 个字体文件；原文件备份在 %s" % (n, backup_dir))
    print("校验:", all(sha256(os.path.join(font_dir, f)) == src_hash for f in targets))
    print("下一步：完全退出并重启 RPCS3 → 启动 BLUS30405 → 看主菜单中文是否显示")
    print("还原：py -3 tools/try_system_font.py --restore")
    return 0


if __name__ == "__main__":
    sys.exit(main())
