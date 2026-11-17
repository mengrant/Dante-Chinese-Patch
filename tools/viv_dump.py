#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读 dump BIGFILE*.VIV 的头部字节，用于确定 EA BIGH 归档的 TOC 布局。"""
import os
import struct
import sys

from common import load_config, report_path, resolve

CFG = load_config()
ISO = resolve(CFG, "iso")
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
        vifs = [x for x in files if x[0].upper().endswith(".VIV")]

        for path, lba, size in vifs:
            head = read_at(f, lba * SECTOR, 1024)
            print("=" * 76)
            print("FILE:", path.strip(), "size", size)
            print("--- first 256 bytes ---")
            for r in range(0, 256, 16):
                chunk = head[r:r + 16]
                asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
                print("%04X  %-47s  %s" % (r, chunk.hex(" "), asc))
            print("--- candidate fields ---")
            print("magic LE/BE:", head[:4], "|", head[:4][::-1])
            for fmt, label in ((">IIIII", "BE u32 x5"), ("<IIIII", "LE u32 x5")):
                vals = struct.unpack_from(fmt, head, 4)
                print("%-12s %s" % (label, vals))
            for off in (0x10, 0x14, 0x18, 0x20, 0x40):
                print("off 0x%02X BE=%d LE=%d" % (
                    off, struct.unpack_from(">I", head, off)[0],
                    struct.unpack_from("<I", head, off)[0]))
            print("--- bytes 256..512 as ascii ---")
            print(repr(head[256:512]))
            print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
