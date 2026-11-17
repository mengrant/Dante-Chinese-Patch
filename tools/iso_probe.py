#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探测 PS3 ISO 的 ISO9660 目录层：列出 PS3_GAME 结构、USRDIR 文件与大文件特征。
不修改 ISO，不做任何写入。用法: py -3 iso_probe.py
"""
import os
import struct
import sys

from common import load_config, report_path, resolve

CFG = load_config()
ISO = resolve(CFG, "iso")
SECTOR = 2048
MAXDEPTH = 3
MAXLIST = 60

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def read_at(f, offset, size):
    f.seek(offset)
    return f.read(size)


def read_sectors(f, lba, count=1):
    return read_at(f, lba * SECTOR, count * SECTOR)


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
        flags = rec[25]
        idlen = rec[32]
        raw = rec[33:33 + idlen]
        name = raw.decode("ascii", "replace").split(";")[0]
        out.append((name, lba, size, bool(flags & 0x02)))
        i += ln
    return out


def main():
    if not os.path.isfile(ISO):
        print("ISO not found:", ISO)
        return 1
    total = os.path.getsize(ISO)
    print("ISO      :", ISO)
    print("size     : %d bytes (%.2f GiB)" % (total, total / 2**30))

    with open(ISO, "rb") as f:
        pvd = read_sectors(f, 16)
        if pvd[1:6] != b"CD001":
            print("no ISO9660 PVD at sector 16 -> UDF-only image")
            return 1
        volid = pvd[40:72].decode("ascii", "replace").strip()
        print("volume   :", volid)
        root = pvd[156:190]
        root_lba = struct.unpack_from("<I", root, 2)[0]
        root_size = struct.unpack_from("<I", root, 10)[0]
        print("root LBA :", root_lba, "size", root_size)
        print("")

        def walk(lba, size, path, depth):
            data = read_sectors(f, lba, (size + SECTOR - 1) // SECTOR)
            items = parse_dir(data)
            for name, e_lba, e_size, isdir in items:
                if name in ("\x00", "\x01", ""):
                    continue
                full = path + "/" + name
                tag = "DIR " if isdir else "FILE"
                print("  %s%-8s %12d  %s" % ("  " * depth, tag, e_size, full))
                if isdir and depth < MAXDEPTH:
                    walk(e_lba, e_size, full, depth + 1)

        print("=== directory tree (top %d levels) ===" % MAXDEPTH)
        walk(root_lba, root_size, "", 0)

        # 收集 USRDIR / 全部文件的路径，供后续抽取特征
        print("\n=== PARAM.SFO ===")
        def find_file(lba, size, path, wanted, hits):
            data = read_sectors(f, lba, (size + SECTOR - 1) // SECTOR)
            for name, e_lba, e_size, isdir in parse_dir(data):
                if name in ("\x00", "\x01", ""):
                    continue
                full = path + "/" + name
                if not isdir and name.upper() == wanted:
                    hits.append((full, e_lba, e_size))
                if isdir:
                    find_file(e_lba, e_size, full, wanted, hits)

        hits = []
        find_file(root_lba, root_size, "", "PARAM.SFO", hits)
        for full, e_lba, e_size in hits[:1]:
            blob = read_at(f, e_lba * SECTOR, min(e_size, 4096))
            if blob[:4] == b"\x00PSF":
                key_off, dat_off, count = struct.unpack_from("<III", blob, 8)
                for i in range(count):
                    ko, fmt, dl, dmax, do = struct.unpack_from("<HHII I".replace(" ", ""), blob, 20 + i * 16)
                    key = blob[key_off + ko:].split(b"\x00")[0].decode("ascii", "replace")
                    val = blob[dat_off + do:dat_off + do + dl]
                    if key in ("TITLE_ID", "TITLE", "APP_VER", "VERSION", "CATEGORY",
                               "PARENTAL_LEVEL", "PS3_SYSTEM_VER", "ATTRIBUTE"):
                        print("  %-16s = %s" % (key, val.split(b"\x00")[0].decode("utf-8", "replace")))
            else:
                print("  unexpected SFO magic:", blob[:8])

        print("\n=== largest files (potential resource containers) ===")
        big = []
        def collect(lba, size, path, depth):
            if depth > 5:
                return
            data = read_sectors(f, lba, (size + SECTOR - 1) // SECTOR)
            for name, e_lba, e_size, isdir in parse_dir(data):
                if name in ("\x00", "\x01", ""):
                    continue
                full = path + "/" + name
                if isdir:
                    collect(e_lba, e_size, full, depth + 1)
                else:
                    big.append((e_size, full, e_lba))
        collect(root_lba, root_size, "", 0)
        big.sort(reverse=True)
        for sz, full, e_lba in big[:MAXLIST]:
            head = read_at(f, e_lba * SECTOR, 32)
            magic = "".join(chr(c) if 32 <= c < 127 else "." for c in head[:16])
            print("  %12d  %-60s  magic=%s" % (sz, full, magic))
        print("\ntotal files:", len(big))
    return 0


if __name__ == "__main__":
    sys.exit(main())
