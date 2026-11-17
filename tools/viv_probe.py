#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读扫描 BIGFILE*.VIV 的头部/TOC 与 UPDATE/*.PKG 的 content id。
用于汉化前期定位文本容器，不修改任何文件。用法: py -3 viv_probe.py
"""
import os
import re
import struct
import sys

ISO = r"<ISO_DIR>\Dante's Inferno Divine Edition [BLUS30405].iso"
SECTOR = 2048
SCAN_MB = 4

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def read_at(f, off, size):
    f.seek(off)
    return f.read(size)


def parse_dir(data):
    out = []
    i = 0
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


def ascii_strings(blob, minlen=4):
    return [m.group().decode("ascii", "replace")
            for m in re.finditer(rb"[ -~]{%d,}" % minlen, blob)]


def main():
    if not os.path.isfile(ISO):
        print("ISO not found")
        return 1
    with open(ISO, "rb") as f:
        pvd = read_at(f, 16 * SECTOR, SECTOR)
        root = pvd[156:190]
        root_lba = struct.unpack_from("<I", root, 2)[0]
        root_size = struct.unpack_from("<I", root, 10)[0]
        files = []
        collect(f, root_lba, root_size, "", files)

        vifs = [x for x in files if x[0].upper().endswith(".VIV")]
        for path, lba, size in vifs:
            head = read_at(f, lba * SECTOR, SCAN_MB * 1024 * 1024)
            print("=" * 78)
            print("FILE :", path.strip(), "(%d bytes)" % size)
            print("magic:", head[:4], " hex[0:32]:", head[:32].hex(" "))
            strs = ascii_strings(head)
            # 归档 TOC 里通常是明文路径/文件名
            named = [s for s in strs if re.search(r"\.[A-Za-z0-9]{2,4}($|/)", s)]
            print("TOC-like strings (first 25):")
            for s in named[:25]:
                print("   ", s[:100])
            keys = ("ols", "lh2", "font", "text", "loc", "lang", "sub", "string",
                    "speech", "movie", "vp6", "dds", "gtf", "fnt", "bin")
            print("keyword hits:", {k: sum(1 for s in strs if k in s.lower()) for k in keys})
            print("")

        pkgs = [x for x in files if "/UPDATE/" in x[0]]
        print("=" * 78)
        print("=== disc-bundled PKG (real DLC / install packages) ===")
        for path, lba, size in pkgs:
            head = read_at(f, lba * SECTOR, 4096)
            ids = [s for s in ascii_strings(head, 8)
                   if re.search(r"(BLUS|NPUB|UP\d{4}|EP\d{4}|DANTE|INSTALL|DLC)", s, re.I)]
            print("  %-28s %11d  %s" % (path.strip().split("/")[-1], size,
                                        " | ".join(ids[:3])[:110]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
