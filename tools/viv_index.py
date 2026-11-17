#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读建立 BIGFILE*.VIV 的全量条目索引并校验字段语义。

输出 viv_index.json：每个 VIV 的头部信息、全部 TOC 记录、抽查的数据头 magic。
用法: py -3 viv_index.py
"""
import json
import os
import struct
import sys

from common import load_config, report_path, resolve

CFG = load_config()
ISO = resolve(CFG, "iso")
OUT = report_path(CFG, "viv_index.json")
SECTOR = 2048

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def read_at(f, off, size):
    f.seek(off)
    return f.read(size)


def parse_dir(data):
    out, i = [], 0
    while i + 34 <= len(data):
        ln = data[i]
        if ln == 0:
            i = ((i // SECTOR) + 1) * SECTOR
            continue
        rec = data[i:i + ln]
        if len(rec) < 34:
            break
        lba = struct.unpack_from("<I", rec, 2)[0]
        size = struct.unpack_from("<I", rec, 10)[0]
        isdir = bool(rec[25] & 0x02)
        idlen = rec[32]
        name = rec[33:33 + idlen].decode("ascii", "replace").split(";")[0]
        out.append((name, lba, size, isdir))
        i += ln
    return out


def collect(f, lba, size, path, out, depth=0):
    if depth > 6:
        return
    data = read_at(f, lba * SECTOR, ((size + SECTOR - 1) // SECTOR) * SECTOR)
    for name, e_lba, e_size, isdir in parse_dir(data):
        if name in ("\x00", "\x01", ""):
            continue
        full = path + "/" + name
        if isdir:
            collect(f, e_lba, e_size, full, out, depth + 1)
        else:
            out.append((full, e_lba, e_size))


def sniff(blob):
    """把文件头 32 字节转成可读标记，并识别常见容器 magic。"""
    if not blob:
        return ""
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in blob[:24])
    tags = []
    for magic, label in ((b"SHOC", "SHOC"), (b"%tRpak", "RefPack?"),
                         (b"ols", "OLS?"), (b"LH2", "LH2?"),
                         (b"MVhd", "VP6"), (b"vp60", "VP6"),
                         (b"BIGH", "BIGH"), (b"\x10\xfb", "RefPack"),
                         (b"\x00PSF", "SFO"), (b"DDS ", "DDS")):
        if magic in blob[:64]:
            tags.append(label)
    return (asc + ("  [" + ",".join(tags) + "]" if tags else "")).strip()


def main():
    # 只记录文件名，不把本机绝对路径写进可提交的报告
    result = {"iso_file": os.path.basename(ISO), "archives": []}
    with open(ISO, "rb") as f:
        pvd = read_at(f, 16 * SECTOR, SECTOR)
        root = pvd[156:190]
        root_lba = struct.unpack_from("<I", root, 2)[0]
        root_size = struct.unpack_from("<I", root, 10)[0]
        files = []
        collect(f, root_lba, root_size, "", files)

        for path, lba, fsize in [x for x in files if x[0].upper().endswith(".VIV")]:
            base = lba * SECTOR
            hdr = read_at(f, base, 24)
            magic, f4, nfiles, tocsize = struct.unpack_from(">4sIII", hdr, 0)
            toc = read_at(f, base + 24, 12 * nfiles)
            recs = [struct.unpack_from(">III", toc, i * 12) for i in range(nfiles)]

            a_vals = [r[0] for r in recs]
            c_vals = [r[2] for r in recs]
            print("=" * 76)
            print("%s  files=%d  size=%d (0x%X)" % (path.strip(), nfiles, fsize, fsize))
            print("  A: min=%d max=%d  strictly_increasing=%s  all_in_file=%s"
                  % (min(a_vals), max(a_vals),
                     all(a_vals[i] < a_vals[i + 1] for i in range(nfiles - 1)),
                     max(a_vals) < fsize))
            print("  C: min=%d max=%d  sum=%d (filesize=%d)"
                  % (min(c_vals), max(c_vals), sum(c_vals), fsize))
            print("  tocsize=%d  24+12*n=%d  match=%s"
                  % (tocsize, 24 + 12 * nfiles, tocsize == 24 + 12 * nfiles))
            print("  A[0]=%d  toc_end=%d   C[0]=%d" % (a_vals[0], tocsize, c_vals[0]))

            samples = {}
            for idx in (0, 1, 2, nfiles // 2, nfiles - 2, nfiles - 1):
                if idx < 0 or idx >= nfiles:
                    continue
                for label, off in (("A", recs[idx][0]), ("C", recs[idx][2]),
                                   ("toc_end", tocsize)):
                    key = "%d/%s" % (idx, label)
                    if off < fsize - 32:
                        samples[key] = sniff(read_at(f, base + off, 64))
            for k in sorted(samples, key=lambda x: (int(x.split("/")[0]), x)):
                print("    %-12s %s" % (k, samples[k][:70]))

            result["archives"].append({
                "path": path.strip(),
                "iso_offset": base,
                "size": fsize,
                "magic": magic.decode("ascii", "replace"),
                "field4": f4,
                "num_files": nfiles,
                "toc_size": tocsize,
                "records": [{"i": i, "a": r[0], "b": r[1], "c": r[2]}
                            for i, r in enumerate(recs)],
                "sniffs": samples,
            })

    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=1)
    print("\nindex written:", OUT, os.path.getsize(OUT), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
