#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读扫描 BIGFILE*.VIV 数据区，定位可本地化文本与容器的聚集区。

按 8 MiB 顺序块扫描，统计可打印 ASCII 密度、英文单词特征与关键字命中，
输出 text_hotspots.json 与控制台 TOP 列表。用法: py -3 text_scan.py
"""
import json
import mmap
import os
import re
import struct
import sys

ISO = r"<ISO_DIR>\Dante's Inferno Divine Edition [BLUS30405].iso"
IDX = r"<ISO_DIR>\viv_index.json"
OUT = r"<ISO_DIR>\text_hotspots.json"
BLOCK = 8 * 1024 * 1024
KEYS = [b"ols", b"lh2", b"OLS", b"LH2", b"Rpak", b"SHOC",
        b"localiz", b"Localiz", b"strings", b"Strings",
        b"Press", b"START", b"font", b"Font", b".lua", b"TG4H",
        b"Greed", b"Lust", b"Gluttony", b"Inferno", b"Dante"]

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WORD = re.compile(rb"[A-Za-z][a-z]{2,}\s+[A-Za-z][a-z]{2,}")


def main():
    with open(IDX, "r", encoding="utf-8") as fp:
        idx = json.load(fp)
    report = []
    with open(ISO, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        for arc in idx["archives"]:
            base = arc["iso_offset"]
            start = base + arc["toc_size"]
            end = base + arc["size"]
            name = arc["path"].split("/")[-1]
            print("=" * 76)
            print("scanning", name, "%.2f GiB" % ((end - start) / 2**30), flush=True)
            hot = []
            off = start
            nblk = 0
            while off < end:
                size = min(BLOCK, end - off)
                chunk = mm[off:off + size]
                printable = sum(1 for b in chunk[::16] if 32 <= b < 127 or b in (9, 10, 13))
                density = printable / max(len(chunk[::16]), 1)
                words = len(WORD.findall(chunk))
                hits = {k.decode("ascii", "replace"): chunk.count(k)
                        for k in KEYS if chunk.count(k)}
                if density > 0.12 or words > 30 or hits:
                    hot.append({"rel": off - base, "abs": off, "density": round(density, 3),
                                "words": words, "hits": hits,
                                "sample": chunk[:0].decode()})
                    # 留一小段可读样本
                    m = re.search(rb"[ -~]{40,}", chunk)
                    if m:
                        hot[-1]["sample"] = m.group()[:160].decode("ascii", "replace")
                off += size
                nblk += 1
                if nblk % 100 == 0:
                    print("  ... %.1f%%" % (100 * (off - start) / (end - start)), flush=True)

            hot.sort(key=lambda x: (x["words"] + x["density"] * 500), reverse=True)
            print("  candidate blocks:", len(hot))
            for h in hot[:15]:
                print("   rel=0x%09X words=%-6d dens=%.2f hits=%s"
                      % (h["rel"], h["words"], h["density"],
                         str(h["hits"])[:110]))
                if h["sample"]:
                    print("      ", h["sample"][:110])
            report.append({"archive": name, "candidates": hot[:80],
                           "total_candidate_blocks": len(hot)})
        mm.close()
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=1)
    print("\nreport:", OUT, os.path.getsize(OUT), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
