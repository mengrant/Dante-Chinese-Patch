#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 TOC 抽取 EA BIGH 归档条目，并探测条目内的 RefPack 压缩块。

字段语义（由 toc_semantics.py 实测确认）：
  B = 条目起始偏移，相对 VIV 文件起点（含 24B 头 + TOC）
  C = 条目的逻辑长度（可能是解压后大小，故物理区间用相邻 B 之差更可靠）
  A = 严格递增的哈希 / 排序键

用法:
  py -3 tools/viv_extract.py --scan                       # 只建 manifest，不落盘
  py -3 tools/viv_extract.py --scan --arc BIGFILE0.VIV
  py -3 tools/viv_extract.py --extract --arc BIGFILE0.VIV --limit 20
  py -3 tools/viv_extract.py --extract --max-size 4194304 --limit 200
"""
import argparse
import json
import os
import re
import sys

from common import ensure_dir, load_config, report_path, resolve
from refpack import RefPackError, decompress

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CFG = load_config()
ISO = resolve(CFG, "iso")
IDX = report_path(CFG, "viv_index.json")
MANIFEST = report_path(CFG, "viv_manifest.json")
EXTRACT_ROOT = ensure_dir(CFG, "extract")

MAGICS = [(b"SHOC", "SHOC"), (b"Rpak", "Rpak"), (b"\x10\xfb", "RefPack"),
          (b"\x90\xfb", "RefPack32"), (b"MVhd", "VP6"), (b"vp60", "VP6"),
          (b"LH2", "LH2"), (b"OLS", "OLS"), (b".ols", "OLS"),
          (b".lh2", "LH2"), (b"font", "FONT"), (b".lua", "LUA"),
          (b"localiz", "LOCALIZE"), (b"strings", "STRINGS"),
          (b"DDS ", "DDS"), (b"BIGH", "BIGH")]

ASCII_RUN = re.compile(rb"[ -~]{6,}")


def detect(blob):
    return [label for magic, label in MAGICS if magic in blob]


def guess_name(blob):
    """从条目前 256 字节里找最像内部资源路径的明文串。"""
    best = ""
    for m in ASCII_RUN.finditer(blob[:256]):
        s = m.group().decode("ascii", "replace")
        if ("\\" in s or "/" in s or "." in s) and len(s) > len(best):
            best = s
    return best.strip()


def safe_name(name, idx):
    if not name:
        return "entry_%05d.bin" % idx
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.replace("\\", "_").replace("/", "_"))
    return ("%05d_" % idx) + cleaned[-100:]


def probe_refpack(blob, limit=2):
    """在条目数据里找并试解 RefPack 块，返回摘要列表。"""
    hits = []
    for magic in (b"\x10\xfb", b"\x90\xfb", b"\x11\xfb", b"\x91\xfb"):
        pos = 0
        while len(hits) < limit:
            i = blob.find(magic, pos)
            if i < 0:
                break
            pos = i + 1
            try:
                out, used = decompress(blob, i, max_out=128 * 1024 * 1024)
            except RefPackError:
                continue
            if used > 8 and len(out) > 32:
                pr = sum(1 for b in out[:4096] if 32 <= b < 127 or b in (9, 10, 13))
                hits.append({"offset": i, "compressed": used, "uncompressed": len(out),
                             "printable": round(pr / min(len(out[:4096]), 4096), 3),
                             "head_hex": out[:16].hex()})
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="只建立 manifest，不写条目文件")
    ap.add_argument("--extract", action="store_true", help="把条目写到 extract/")
    ap.add_argument("--arc", default="", help="只处理名字含该串的 VIV")
    ap.add_argument("--limit", type=int, default=0, help="每个 VIV 最多处理多少条（0=全部）")
    ap.add_argument("--max-size", type=int, default=8 * 1024 * 1024,
                    help="--extract 时单条目最大字节数")
    ap.add_argument("--probe-bytes", type=int, default=65536,
                    help="每个条目读取多少字节用于 magic / RefPack 探测")
    args = ap.parse_args()
    if not args.scan and not args.extract:
        args.scan = True

    with open(IDX, "r", encoding="utf-8") as fp:
        idx = json.load(fp)

    manifest = []
    with open(ISO, "rb") as f:
        for arc in idx["archives"]:
            name = arc["path"].split("/")[-1]
            if args.arc and args.arc.lower() not in name.lower():
                continue
            base, size = arc["iso_offset"], arc["size"]
            recs = sorted(arc["records"], key=lambda r: r["b"])
            if args.limit:
                recs = recs[:args.limit]
            print("=" * 78)
            print("%s  entries=%d  base=%d  size=%d" % (name, len(recs), base, size))

            out_dir = os.path.join(EXTRACT_ROOT, name.replace(".", "_"))
            if args.extract:
                os.makedirs(out_dir, exist_ok=True)

            entries = []
            counts = {}
            for n, r in enumerate(recs):
                start = r["b"]
                end = recs[n + 1]["b"] if n + 1 < len(recs) else size
                span = end - start
                if start < 0 or start >= size:
                    continue
                read_len = min(span, args.probe_bytes)
                f.seek(base + start)
                blob = f.read(read_len)
                tags = detect(blob)
                for t in tags:
                    counts[t] = counts.get(t, 0) + 1
                rp = probe_refpack(blob) if any("RefPack" in t for t in tags) else []
                nm = guess_name(blob)
                entries.append({
                    "idx": r["i"], "a": r["a"], "b": start, "c": r["c"],
                    "span": span, "name": nm, "tags": tags, "refpack": rp,
                    "head": blob[:16].hex(),
                })
                if args.extract and span <= args.max_size:
                    with open(os.path.join(out_dir, safe_name(nm, r["i"])), "wb") as out:
                        out.write(blob)
                if (n + 1) % 500 == 0:
                    print("  ... %d/%d" % (n + 1, len(recs)), flush=True)

            print("  tag counts:", dict(sorted(counts.items(), key=lambda x: -x[1])[:12]))
            refpack_entries = [e for e in entries if e["refpack"]]
            print("  refpack-probed entries:", len(refpack_entries))
            for e in refpack_entries[:6]:
                print("    b=%-10d span=%-8d %s -> %s" %
                      (e["b"], e["span"], str(e["tags"])[:40],
                       str(e["refpack"][0])[:130]))
            named = [e for e in entries if e["name"]]
            print("  named entries: %d/%d  e.g. %s" %
                  (len(named), len(entries), [e["name"][:60] for e in named[:3]]))
            manifest.append({"archive": name, "iso_offset": base, "size": size,
                             "entries": entries})

    with open(MANIFEST, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=1)
    print("\nmanifest:", MANIFEST, os.path.getsize(MANIFEST), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
