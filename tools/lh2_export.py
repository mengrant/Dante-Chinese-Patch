#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 localization/*.lh2，导出可翻译的文本表（CSV + JSON）。

.lh2 结构（实测 BIGFILE0 的 inferno_poem.en.lh2 等）：
  0x00  magic "2HCL"
  0x04  u32be 逻辑总大小
  0x10  u32be 条目数 N
  0x20  ID 表      N × u32be（分组递增的字符串 ID）
  0x20+4N  偏移表  N × u32be，指向字符串区内各字符串起点
  之后   字符串区  连续的 NUL 结尾 C 字符串（可能含控制码）

VIV 条目是 SHOC 容器，内部逻辑数据按约 64 KiB 分段：多数段是 RefPack
压缩块（第一块带 2HCL 头），末尾可能有一段 SHOC/SDAT 未压缩文本。
按块顺序拼接 + 补齐尾段，才能得到 declared_total 大小的完整数据。

输出（重要：含游戏原文，属资源数据，全部写到不入库的 extract/）：
  extract/text_table_<lang>.csv   可直接用 Excel 打开翻译（UTF-8 BOM）
  extract/text_table_<lang>.json  含原始字节，保证可无损回填
  report/lh2_summary.json          只含结构元数据（无原文），可入库
用法:
  py -3 tools/lh2_export.py --lang en
  py -3 tools/lh2_export.py --lang fr --limit 4
"""
import argparse
import csv
import json
import os
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


def readable(raw):
    """把控制码显示为 \\xNN，保证 CSV 可读且可无损还原。"""
    out = []
    for b in raw:
        if 32 <= b < 127:
            out.append(chr(b))
        elif b in (9, 10, 13):
            out.append({9: "\\t", 10: "\\n", 13: "\\r"}[b])
        else:
            out.append("\\x%02X" % b)
    return "".join(out)


def complete_container(blob, full):
    """补齐尾部 SHOC/SDAT 未压缩段，使长度达到头部声明的逻辑总大小。"""
    if len(full) < 8:
        return full
    declared = struct.unpack_from(">I", full, 4)[0]
    if declared <= len(full):
        return full
    need = declared - len(full)
    pos = 0
    while True:
        i = blob.find(b"SHOC", pos)
        if i < 0:
            break
        pos = i + 4
        if blob[i + 8:i + 12] == b"SDAT":
            tail = blob[i + 12:i + 12 + need]
            if len(tail) == need:
                return full + tail
    return full


def parse_lh2(full):
    if full[:4] != b"2HCL":
        raise ValueError("not a 2HCL container: %r" % full[:8])
    total, count = (struct.unpack_from(">I", full, 0x04)[0],
                    struct.unpack_from(">I", full, 0x10)[0])
    if not 0 < count < 100000:
        raise ValueError("implausible entry count %d" % count)
    id_off = 0x20
    ptr_off = id_off + 4 * count
    if ptr_off + 4 * count > len(full):
        raise ValueError("truncated tables: need %d, have %d" %
                         (ptr_off + 4 * count, len(full)))
    ids = [struct.unpack_from(">I", full, id_off + 4 * i)[0] for i in range(count)]
    ptrs = [struct.unpack_from(">I", full, ptr_off + 4 * i)[0] for i in range(count)]
    rows, missing = [], 0
    for i, (sid, p) in enumerate(zip(ids, ptrs)):
        if p >= len(full):
            missing += 1
            rows.append({"index": i, "id": sid, "offset": p,
                         "source": "", "raw_hex": "", "note": "offset beyond data"})
            continue
        end = full.find(b"\x00", p)
        raw = full[p:end] if end >= 0 else full[p:p + 256]
        rows.append({"index": i, "id": sid, "offset": p,
                     "source": readable(raw), "raw_hex": raw.hex(),
                     "length": len(raw)})
    return {"total_declared": total, "count": count,
            "ptr_table_offset": ptr_off, "data_size": len(full),
            "missing": missing, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="en", help="语言后缀，如 en / fr / es / ll / ss")
    ap.add_argument("--limit", type=int, default=0, help="最多处理几个 .lh2（0=全部）")
    ap.add_argument("--max-read", type=int, default=8 * 1024 * 1024)
    args = ap.parse_args()

    with open(MANIFEST, "r", encoding="utf-8") as fp:
        manifest = json.load(fp)
    suffix = ".%s.lh2" % args.lang

    extract_root = ensure_dir(CFG, "extract")
    out_csv = os.path.join(extract_root, "text_table_%s.csv" % args.lang)
    out_json = os.path.join(extract_root, "text_table_%s.json" % args.lang)
    out_summary = report_path(CFG, "lh2_summary.json")
    tables, seen, duplicates = [], set(), 0

    with open(ISO, "rb") as f:
        for arc in manifest:
            for e in arc["entries"]:
                if suffix.lower() not in e["name"].lower():
                    continue
                if e["name"] in seen:          # 光盘里同一文件存了多份
                    duplicates += 1
                    continue
                if args.limit and len(tables) >= args.limit:
                    break
                seen.add(e["name"])
                f.seek(arc["iso_offset"] + e["b"])
                blob = f.read(min(e["span"], args.max_read))
                blocks = scan(blob, limit=32)
                full = b"".join(out for _, _, _, out in blocks)
                full = complete_container(blob, full)
                print("=" * 78)
                print("%s | b=%d span=%d | blocks=%d full=%d" %
                      (e["name"], e["b"], e["span"], len(blocks), len(full)), flush=True)
                try:
                    info = parse_lh2(full)
                except ValueError as ex:
                    print("  SKIP:", ex)
                    continue
                print("  count=%d declared=%d ptr_table=0x%X missing=%d" %
                      (info["count"], info["total_declared"],
                       info["ptr_table_offset"], info["missing"]))
                for r in info["rows"][:2]:
                    print("   #%d id=%08X off=%d" % (r["index"], r["id"], r["offset"]))
                tables.append({"name": e["name"], "b": e["b"], "span": e["span"],
                               "blocks": len(blocks), **info})

    if not tables:
        print("no .lh2 parsed")
        return 1

    with open(out_csv, "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["file", "index", "id_hex", "offset", "source", "translation", "raw_hex"])
        for t in tables:
            for r in t["rows"]:
                w.writerow([os.path.basename(t["name"].replace("\\", "/")),
                            r["index"], "%08X" % r["id"], r["offset"],
                            r["source"], "", r["raw_hex"]])
    with open(out_json, "w", encoding="utf-8") as fp:
        json.dump(tables, fp, ensure_ascii=False, indent=1)

    # 只含结构元数据的摘要，可安全入库；不含任何游戏原文
    summary = [{"name": t["name"], "b": t["b"], "span": t["span"],
                "blocks": t["blocks"], "count": t["count"],
                "total_declared": t["total_declared"],
                "ptr_table_offset": t["ptr_table_offset"],
                "data_size": t["data_size"], "missing": t["missing"],
                "first_ids": ["%08X" % r["id"] for r in t["rows"][:5]]}
               for t in tables]
    with open(out_summary, "w", encoding="utf-8") as fp:
        json.dump({"lang": args.lang, "duplicates_skipped": duplicates,
                   "files": summary}, fp, ensure_ascii=False, indent=1)

    total_rows = sum(t["count"] for t in tables)
    print("\nfiles=%d duplicates=%d strings=%d missing=%d" %
          (len(tables), duplicates, total_rows, sum(t["missing"] for t in tables)))
    print("csv    :", out_csv, os.path.getsize(out_csv), "bytes")
    print("json   :", out_json, os.path.getsize(out_json), "bytes")
    print("summary:", out_summary, os.path.getsize(out_summary), "bytes (no game text)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
