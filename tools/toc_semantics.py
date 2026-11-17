#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 EA BIGH TOC 三个 u32 字段的真实语义。

对 (偏移字段, 长度字段, 偏移基准) 的每种组合打分：
  - 区间合法性：offset/length 是否落在文件内、按 offset 排序后是否重叠
  - 数据头特征：抽样的 offset 处 48 字节里可打印字符比例与已知 magic 命中数
输出 report/toc_semantics.json，并给出结论。只读 ISO。
用法: py -3 tools/toc_semantics.py
"""
import json
import os
import sys
from collections import Counter

from common import load_config, report_path, resolve

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CFG = load_config()
ISO = resolve(CFG, "iso")
IDX = report_path(CFG, "viv_index.json")
OUT = report_path(CFG, "toc_semantics.json")

MAGICS = [(b"SHOC", "SHOC"), (b"\x10\xfb", "RefPack"),
          (b"\x90\xfb", "RefPack32"), (b"Rpak", "Rpak"),
          (b"MVhd", "VP6"), (b"vp60", "VP6"),
          (b"LH2", "LH2"), (b"BIGH", "BIGH"),
          (b"font", "FONT"), (b".lua", "LUA"),
          (b"manager:", "LUA"), (b"Dante", "TEXT")]

SAMPLE_N = 24


def printable_ratio(blob):
    if not blob:
        return 0.0
    return sum(1 for b in blob if 32 <= b < 127 or b in (9, 10, 13)) / len(blob)


def tags(blob):
    return [label for magic, label in MAGICS if magic in blob]


def sample_offsets(records):
    n = len(records)
    if n <= SAMPLE_N:
        return list(range(n))
    return sorted({round(i * (n - 1) / (SAMPLE_N - 1)) for i in range(SAMPLE_N)})


def main():
    with open(IDX, "r", encoding="utf-8") as fp:
        idx = json.load(fp)

    report = []
    with open(ISO, "rb") as f:
        for arc in idx["archives"]:
            recs = arc["records"]
            base, size, toc = arc["iso_offset"], arc["size"], arc["toc_size"]
            print("=" * 78)
            print("%s  n=%d  size=%d  toc=%d" %
                  (arc["path"].split("/")[-1], len(recs), size, toc))

            candidates = []
            for off_field, len_field in (("b", "c"), ("c", "b"), ("a", "c"), ("c", "a")):
                offs = [r[off_field] for r in recs]
                lens = [r[len_field] for r in recs]
                spans = sorted(zip(offs, lens))
                in_range = sum(1 for o, l in spans if 0 <= o and o + l <= size)
                overlaps = sum(1 for i in range(1, len(spans))
                               if spans[i - 1][0] + spans[i - 1][1] > spans[i][0])
                covered = sum(l for _, l in spans)
                print("  off=%s len=%s | in_range=%d/%d overlap=%d covered=%d (size-toc=%d)"
                      % (off_field, len_field, in_range, len(recs), overlaps,
                         covered, size - toc))

                for origin_name, origin in (("file_start", 0), ("data_start", toc)):
                    if origin and min(offs) < toc:
                        # data_start 基准下 offset 必须从数据区起算，仍照测以便对比
                        pass
                    score, pr_sum, tag_counter = 0, 0.0, Counter()
                    samples = sample_offsets(recs)
                    for i in samples:
                        r = recs[i]
                        pos = base + origin + r[off_field]
                        if pos < 0 or pos + 48 > base + size:
                            continue
                        f.seek(pos)
                        blob = f.read(48)
                        pr = printable_ratio(blob)
                        pr_sum += pr
                        t = tags(blob)
                        for x in t:
                            tag_counter[x] += 1
                        score += pr + 2 * len(t)
                    score += in_range / max(len(recs), 1) * 3
                    score -= overlaps / max(len(recs), 1) * 3
                    candidates.append({
                        "off_field": off_field, "len_field": len_field,
                        "origin": origin_name, "score": round(score, 2),
                        "avg_printable": round(pr_sum / max(len(samples), 1), 3),
                        "tags": dict(tag_counter),
                        "in_range": in_range, "overlaps": overlaps,
                    })

            candidates.sort(key=lambda x: x["score"], reverse=True)
            print("  --- top hypotheses ---")
            for c in candidates[:4]:
                print("    off=%-1s len=%-1s origin=%-11s score=%7.2f print=%.2f tags=%s" %
                      (c["off_field"], c["len_field"], c["origin"], c["score"],
                       c["avg_printable"], str(c["tags"])[:80]))
            report.append({"archive": arc["path"].split("/")[-1],
                           "num_files": len(recs), "size": size, "toc_size": toc,
                           "candidates": candidates})

    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=1)
    print("\nreport:", OUT, os.path.getsize(OUT), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
