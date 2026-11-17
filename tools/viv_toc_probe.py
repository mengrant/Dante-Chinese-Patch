#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读验证 EA BIGH 归档 TOC 布局：24B 头 + 12B/条 + 明文名字表。"""
import os
import re
import struct
import sys

ISO = r"<ISO_DIR>\Dante's Inferno Divine Edition [BLUS30405].iso"
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


def main():
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
            print("=" * 76)
            print("FILE:", path.strip())
            print("magic=%s  field4=%d  nfiles=%d  tocsize=%d  (24+12*n=%d)"
                  % (magic.decode(), f4, nfiles, tocsize, 24 + 12 * nfiles))

            toc = read_at(f, base + 24, 12 * min(nfiles, 12))
            print("--- first TOC records (A,B,C as BE u32) ---")
            for i in range(min(nfiles, 12)):
                a, b, c = struct.unpack_from(">III", toc, i * 12)
                print("  [%3d] A=%10d (0x%08X)  B=0x%08X  C=%10d (0x%08X)"
                      % (i, a, a, b, c, c))

            # TOC 之后通常是明文名字表
            tail = read_at(f, base + tocsize, 32768)
            strs = [(m.start(), m.group().decode("ascii", "replace"))
                    for m in re.finditer(rb"[ -~]{4,}", tail)]
            named = [(o, s) for o, s in strs if re.search(r"\.[A-Za-z0-9]{2,4}", s)]
            print("--- strings right after TOC (first 30) ---")
            for o, s in named[:30]:
                print("   +%-6d %s" % (o, s[:110]))
            print("total strings in 32KB tail:", len(strs), "named:", len(named))
            print("")

            # 名字表计数：统计 null 结尾字符串数量，看是否等于 nfiles
            blob = read_at(f, base + tocsize, min(2 * 1024 * 1024, fsize - tocsize))
            chunks = blob.split(b"\x00")
            non_empty = [c for c in chunks if 3 <= len(c) < 260
                         and all(32 <= b < 127 for b in c)]
            print("null-terminated ascii tokens in first 2MB after TOC:", len(non_empty))
            print("samples:", [c.decode("ascii", "replace")[:70] for c in non_empty[:12]])
            print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
