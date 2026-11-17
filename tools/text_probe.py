#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 VIV 条目里定位可本地化文本。

依据 viv_manifest.json 的标签筛出候选条目，重读条目数据，解出其中的
RefPack 块，再在解压结果里提取 ASCII / UTF-16 可读字符串，判断哪个
条目是真正的文本容器。只读 ISO，输出 report/text_probe.json。

用法:
  py -3 tools/text_probe.py --limit 60 --top 15
  py -3 tools/text_probe.py --arc BIGFILE0.VIV --limit 120
"""
import argparse
import json
import os
import re
import sys

from common import load_config, report_path, resolve
from refpack import RefPackError, decompress, scan

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CFG = load_config()
ISO = resolve(CFG, "iso")
MANIFEST = report_path(CFG, "viv_manifest.json")
OUT = report_path(CFG, "text_probe.json")

KEY_TAGS = {"LH2", "OLS", "LOCALIZE", "STRINGS", "FONT"}
NAME_RE = re.compile(r"lh2|ols|local|string|text|font|dialog|subtitle|menu|ui", re.I)
ASCII_RUN = re.compile(rb"[ -~]{5,}")
UTF16_RUN = re.compile(rb"(?:[\x20-\x7e]\x00){5,}")
WORD_PAIR = re.compile(rb"[A-Za-z][a-z]{2,}\s+[A-Za-z][a-z]{2,}")


def plausible(s):
    if len(s) < 6:
        return False
    letters = sum(1 for c in s if 65 <= c <= 90 or 97 <= c <= 122)
    if letters < len(s) * 0.55:
        return False
    # 排除纯十六进制 / 纯路径噪声
    if b"\\" in s and letters < len(s) * 0.7:
        return False
    return True


def extract_strings(blob, cap=40):
    found = []
    for m in ASCII_RUN.finditer(blob):
        s = m.group()
        if plausible(s):
            found.append(("ascii", s.decode("latin-1", "replace")))
            if len(found) >= cap:
                return found
    for m in UTF16_RUN.finditer(blob):
        s = m.group()[::2]
        if plausible(s):
            found.append(("utf16", s.decode("latin-1", "replace")))
            if len(found) >= cap:
                break
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arc", default="")
    ap.add_argument("--limit", type=int, default=80, help="最多分析多少候选条目")
    ap.add_argument("--top", type=int, default=12, help="控制台打印多少个最佳候选")
    ap.add_argument("--max-read", type=int, default=4 * 1024 * 1024,
                    help="单条目最多读取字节数")
    args = ap.parse_args()

    with open(MANIFEST, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)

    results = []
    with open(ISO, "rb") as f:
        for arc in manifest:
            name = arc["archive"]
            if args.arc and args.arc.lower() not in name.lower():
                continue
            base = arc["iso_offset"]
            cands = [e for e in arc["entries"]
                     if (set(e["tags"]) & KEY_TAGS) or NAME_RE.search(e["name"])]
            # 已验证含可解压 RefPack 块的条目优先，文本容器最可能在这些里面
            cands.sort(key=lambda e: (0 if e.get("refpack") else 1, e["b"]))
            print("=" * 78)
            print("%s  candidates=%d (from %d entries)" %
                  (name, len(cands), len(arc["entries"])), flush=True)

            for e in cands[:args.limit]:
                f.seek(base + e["b"])
                blob = f.read(min(e["span"], args.max_read))
                blocks = []
                # manifest 里已验证过的块优先
                for rp in e.get("refpack", []):
                    i = rp["offset"]
                    if i + 2 > len(blob):
                        continue
                    try:
                        out, used = decompress(blob, i, max_out=128 * 1024 * 1024)
                    except RefPackError:
                        continue
                    blocks.append((i, used, out))
                # 再补扫最多 4 个新块
                for start, used, ulen, out in scan(blob, limit=4):
                    if all(abs(start - b[0]) > 8 for b in blocks):
                        blocks.append((start, used, out))
                    if len(blocks) >= 8:
                        break

                all_strings, best_preview = [], ""
                for i, used, out in blocks:
                    strs = extract_strings(out)
                    all_strings.extend({"enc": enc, "text": s} for enc, s in strs)
                    if not best_preview and strs:
                        best_preview = " | ".join(s[:70] for _, s in strs[:4])
                words = sum(len(WORD_PAIR.findall(s["text"].encode("latin-1", "replace")))
                            for s in all_strings)
                score = len(all_strings) + 5 * words
                results.append({
                    "archive": name, "b": e["b"], "span": e["span"],
                    "name": e["name"], "tags": e["tags"],
                    "blocks": [{"offset": i, "compressed": used, "uncompressed": len(out)}
                               for i, used, out in blocks],
                    "string_count": len(all_strings), "word_pairs": words,
                    "score": score, "preview": best_preview[:300],
                    "strings": all_strings[:40],
                })
                if len(results) % 20 == 0:
                    print("  ... %d analysed" % len(results), flush=True)

    results.sort(key=lambda x: x["score"], reverse=True)
    print("\n=== top candidates ===")
    for r in results[:args.top]:
        print("score=%-6d str=%-4d words=%-4d b=%-11d %s" %
              (r["score"], r["string_count"], r["word_pairs"], r["b"],
               str(r["tags"])[:38]))
        print("   name :", r["name"][:90])
        print("   prev :", r["preview"][:180])

    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump({"candidates": results}, fp, ensure_ascii=False, indent=1)
    print("\nreport:", OUT, os.path.getsize(OUT), "bytes | analysed", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
