#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽取并分析 localization/*.lh2 文本容器。

流程：VIV 条目 -> 内部 RefPack 块 -> 解压 -> 结构诊断 -> 导出字符串表。
解压结果写到 extract/lh2/（不入库），报告写到 report/。

用法:
  py -3 tools/lh2_dump.py --name inferno_poem.en.lh2 --hex
  py -3 tools/lh2_dump.py --name inferno_ --limit 8 --export
"""
import argparse
import json
import os
import re
import struct
import sys

from common import ensure_dir, load_config, report_path, resolve
from refpack import scan

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CFG = load_config()
ISO = resolve(CFG, "iso")
MANIFEST = report_path(CFG, "viv_manifest.json")
OUT_JSON = report_path(CFG, "lh2_analysis.json")
OUT_TEXT = report_path(CFG, "lh2_strings.json")
LH2_DIR = os.path.join(ensure_dir(CFG, "extract"), "lh2")

ASCII_RUN = re.compile(rb"[ -~]{4,}")
UTF16_RUN = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")


def hexdump(blob, n=160):
    lines = []
    for off in range(0, min(len(blob), n), 16):
        chunk = blob[off:off + 16]
        hx = " ".join("%02X" % b for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append("%04X  %-47s  %s" % (off, hx, asc))
    return "\n".join(lines)


def u32_series(blob, n=24):
    """看开头是否有一串 u32（大端/小端）递增的指针值。"""
    out = {}
    for endian, fmt in (("be", ">I"), ("le", "<I")):
        vals = [struct.unpack_from(fmt, blob, i * 4)[0]
                for i in range(min(n, len(blob) // 4))]
        diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        out[endian] = {"first": vals[:8],
                       "diffs_first": diffs[:8],
                       "constant_step": len(set(diffs[:12])) == 1 if len(diffs) >= 12 else None}
    return out


def strings_of(blob, cap=400):
    found = []
    for m in ASCII_RUN.finditer(blob):
        s = m.group()
        letters = sum(1 for c in s if 65 <= c <= 90 or 97 <= c <= 122)
        if letters >= len(s) * 0.6:
            found.append({"off": m.start(), "enc": "ascii",
                          "text": s.decode("latin-1", "replace")})
            if len(found) >= cap:
                return found
    for m in UTF16_RUN.finditer(blob):
        found.append({"off": m.start(), "enc": "utf16",
                      "text": m.group()[::2].decode("latin-1", "replace")})
        if len(found) >= cap:
            break
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="lh2", help="条目名子串过滤")
    ap.add_argument("--limit", type=int, default=6, help="最多分析多少个 .lh2")
    ap.add_argument("--max-read", type=int, default=4 * 1024 * 1024)
    ap.add_argument("--hex", action="store_true", help="打印首块 hexdump")
    ap.add_argument("--export", action="store_true", help="把解压块写到 extract/lh2/")
    args = ap.parse_args()

    with open(MANIFEST, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)
    if args.export:
        os.makedirs(LH2_DIR, exist_ok=True)

    analysis, text_table = [], []
    with open(ISO, "rb") as f:
        for arc in manifest:
            for e in arc["entries"]:
                if args.name.lower() not in e["name"].lower():
                    continue
                if len(analysis) >= args.limit:
                    break
                f.seek(arc["iso_offset"] + e["b"])
                blob = f.read(min(e["span"], args.max_read))
                blocks = scan(blob, limit=16)
                print("=" * 78)
                print("%s | b=%d span=%d | blocks=%d" %
                      (e["name"], e["b"], e["span"], len(blocks)))
                for k, (start, used, ulen, out) in enumerate(blocks):
                    print("  block%d off=%-7d comp=%-8d uncomp=%-8d magic=%r" %
                          (k, start, used, ulen, out[:8]))
                if not blocks:
                    analysis.append({"name": e["name"], "b": e["b"], "blocks": 0})
                    continue

                big = max(blocks, key=lambda x: x[2])[3]
                print("  --- first 160 bytes of largest block ---")
                if args.hex:
                    print(hexdump(big))
                print("  u32 series:", json.dumps(u32_series(big), ensure_ascii=False)[:400])
                strs = strings_of(big)
                print("  strings: %d  e.g. %s" %
                      (len(strs), [s["text"][:60] for s in strs[:4]]))

                if args.export:
                    for k, (start, used, ulen, out) in enumerate(blocks):
                        fn = re.sub(r"[^A-Za-z0-9._-]+", "_", e["name"]) + ".blk%d.bin" % k
                        with open(os.path.join(LH2_DIR, fn), "wb") as w:
                            w.write(out)
                analysis.append({
                    "name": e["name"], "b": e["b"], "span": e["span"],
                    "blocks": [{"offset": s, "compressed": u, "uncompressed": ul}
                               for s, u, ul, _ in blocks],
                    "magic": big[:16].hex(),
                    "head": big[:256].decode("latin-1", "replace"),
                    "u32": u32_series(big), "string_count": len(strs),
                })
                text_table.append({"name": e["name"], "b": e["b"],
                                   "strings": strs[:200]})

    with open(OUT_JSON, "w", encoding="utf-8") as fp:
        json.dump(analysis, fp, ensure_ascii=False, indent=1)
    with open(OUT_TEXT, "w", encoding="utf-8") as fp:
        json.dump(text_table, fp, ensure_ascii=False, indent=1)
    print("\nreport:", OUT_JSON, "|", OUT_TEXT, "| entries:", len(analysis))
    return 0


if __name__ == "__main__":
    sys.exit(main())
