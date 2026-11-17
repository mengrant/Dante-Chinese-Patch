#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 VIV 条目头部按 EA 字体资源命名特征定位字体图集 / 字符映射表。

线索来自 HDD 侧官方 DLC 散文件 dia_core/arena_frontend.str，其中明文出现：
    shared\\fonts\\arena\\minion_pro_arena.tg4h
    shared\\fonts\\arena\\buttons_arena.tg4h
    assets_shared_fonts_arena
说明 EA 把字体烘焙成 .tg4h/.tg4d 纹理对，SHOC/SHDR 段里带资源路径。

本工具只读 manifest 里每个条目的前 1 KiB（定点 seek），不扫描整盘、不解压、
不修改任何文件。输出 report/font_candidates.json。

用法: py -3 tools/find_font_entries.py [--head 1024]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, report_path, resolve

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

NEEDLES = [
    b"shared\\fonts", b"shared/fonts", b"assets_shared_fonts",
    b"minion", b"minion_pro", b"glyph", b"font", b"Font", b"FONT",
    b".tg4d", b"2HCL", b"buttons_",
]

READABLE = re.compile(rb"[ -~]{5,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--head", type=int, default=1024, help="每个条目读取的头部字节数")
    args = ap.parse_args()

    cfg = load_config()
    manifest = report_path(cfg, "viv_manifest.json")
    out = report_path(cfg, "font_candidates.json")
    root = os.path.join(resolve(cfg, "rpcs3_disc_dir"), "PS3_GAME", "USRDIR")
    archives = json.load(open(manifest, encoding="utf-8"))

    hits = []
    total = 0
    for a in archives:
        path = os.path.join(root, a["archive"])
        if not os.path.isfile(path):
            print("跳过（文件不存在）: %s" % a["archive"])
            continue
        with open(path, "rb") as f:
            for e in a["entries"]:
                total += 1
                f.seek(e["b"])
                head = f.read(min(args.head, e["span"]))
                found = [n.decode("latin-1") for n in NEEDLES if n in head]
                if not found:
                    continue
                strings = [s.decode("latin-1") for s in READABLE.findall(head)]
                meaningful = [s for s in strings
                              if re.search(r"font|glyph|minion|tg4|2HCL|buttons", s, re.I)]
                hits.append({
                    "archive": a["archive"],
                    "name": e.get("name", ""),
                    "a": e["a"], "b": e["b"], "span": e["span"],
                    "iso_offset": a["iso_offset"] + e["b"],
                    "needles": found,
                    "strings": meaningful[:12],
                    "head_hex": head[:16].hex(),
                })

    print("扫描条目: %d / 归档: %d / 命中: %d" % (total, len(archives), len(hits)))
    print()
    buckets = {}
    for h in hits:
        key = "fontpaths" if any("fonts" in n or "minion" in n or "glyph" in n
                                 for n in h["needles"]) else "other"
        buckets.setdefault(key, []).append(h)
    for key in ("fontpaths", "other"):
        rows = buckets.get(key, [])
        print("=== %s (%d) ===" % (key, len(rows)))
        for h in rows[:40]:
            print("  [%-13s] b=%-11d span=%-9d %s" %
                  (h["archive"], h["b"], h["span"], h["name"][:60] or "(无名)"))
            print("       needles=%s" % h["needles"])
            for s in h["strings"][:3]:
                print("       %r" % s[:100])
        print()

    with open(out, "w", encoding="utf-8") as fp:
        json.dump({"scanned_entries": total, "head_bytes": args.head,
                   "hits": hits}, fp, ensure_ascii=False, indent=1)
    print("报告:", out, os.path.getsize(out), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
