#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EA RefPack / PSA (LZSS) 解压器，纯标准库实现。

格式依据：
  - NO$FUN "CDROM File Compression EA Methods (LZSS RefPack)" 的解压伪代码
  - SSX Modding Wiki "Formats/Common:Refpack" 的 ImHex 结构定义

头部：
  byte0 flags, byte1 = 0xFB
  flags bit7 (L): 1 = 32-bit sizes, 0 = 24-bit sizes
  flags bit0 (C): 1 = 头部另带 compressed size
  常见 0x10 0xFB -> 3 字节解压后大小，随后是指令流

指令（先拷贝 raw 个字面字节，再从 out[-disp] 拷贝 lzlen 字节）：
  0x00-0x7F : raw=c&3        lzlen=((c>>2)&7)+3   disp=((c&0x60)<<3)+b1+1
  0x80-0xBF : raw=b1>>6      lzlen=(c&0x3F)+4     disp=((b1&0x3F)<<8)+b2+1
  0xC0-0xDF : raw=c&3        lzlen=((c&0x0C)<<6)+b3+5
                             disp=((c&0x10)<<12)+(b1<<8)+b2+1
  0xE0-0xFB : raw=((c&0x1F)+1)*4, 无回引用
  0xFC-0xFF : raw=c&3, 无回引用, 结束

mapped=True 时额外返回「每个输出字节在输入中的绝对偏移」数组；
LZ 回引用产生的字节记为 -1。这让 lh2_patch.py 可以在不重新压缩的
情况下原地改写字面字节（等长替换），压缩流结构完全不变。

用法: py -3 tools/refpack.py          # 跑内建自测
      from refpack import decompress, scan
"""
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class RefPackError(ValueError):
    pass


def decompress(data, offset=0, max_out=256 * 1024 * 1024, mapped=False):
    """解一个 RefPack 流。

    返回 (out_bytes, consumed)；mapped=True 时返回 (out, consumed, srcmap)。
    consumed 为从 offset 起实际消耗的字节数。
    """
    n = len(data)
    p = offset
    if p + 2 > n:
        raise RefPackError("truncated header")
    flags, sig = data[p], data[p + 1]
    p += 2
    if sig != 0xFB:
        raise RefPackError("bad signature 0x%02X at %d" % (sig, offset))

    wide = bool(flags & 0x80)
    has_csize = bool(flags & 0x01)
    step = 4 if wide else 3
    if p + step > n:
        raise RefPackError("truncated size field")
    usize = int.from_bytes(data[p:p + step], "big")
    p += step
    if has_csize:
        p += step
        if p > n:
            raise RefPackError("truncated compressed size field")
    if usize > max_out:
        raise RefPackError("uncompressed size too large: %d" % usize)

    out = bytearray()
    srcmap = [] if mapped else None
    end = False
    while not end:
        if p >= n:
            raise RefPackError("truncated command stream")
        c = data[p]
        p += 1
        raw = lzlen = disp = 0
        if c < 0x80:                       # 0x00-0x7F
            if p >= n:
                raise RefPackError("truncated cmd2")
            b1 = data[p]
            p += 1
            raw = c & 3
            lzlen = ((c >> 2) & 7) + 3
            disp = ((c & 0x60) << 3) + b1 + 1
        elif c < 0xC0:                     # 0x80-0xBF
            if p + 2 > n:
                raise RefPackError("truncated cmd3")
            b1, b2 = data[p], data[p + 1]
            p += 2
            raw = (b1 >> 6) & 3
            lzlen = (c & 0x3F) + 4
            disp = ((b1 & 0x3F) << 8) + b2 + 1
        elif c < 0xE0:                     # 0xC0-0xDF
            if p + 3 > n:
                raise RefPackError("truncated cmd4")
            b1, b2, b3 = data[p], data[p + 1], data[p + 2]
            p += 3
            raw = c & 3
            lzlen = ((c & 0x0C) << 6) + b3 + 5
            disp = ((c & 0x10) << 12) + (b1 << 8) + b2 + 1
        elif c < 0xFC:                     # 0xE0-0xFB
            raw = ((c & 0x1F) + 1) * 4
        else:                              # 0xFC-0xFF stop
            raw = c & 3
            end = True

        if raw:
            if p + raw > n:
                raise RefPackError("truncated literals")
            if mapped:
                srcmap.extend(range(p, p + raw))
            out += data[p:p + raw]
            p += raw
        if lzlen:
            if disp <= 0 or disp > len(out):
                raise RefPackError("bad back-reference disp=%d at out=%d" % (disp, len(out)))
            if mapped:
                srcmap.extend([-1] * lzlen)
            if disp == 1:
                out += bytes([out[-1]]) * lzlen
            else:
                for _ in range(lzlen):
                    out.append(out[-disp])
            if len(out) > usize:
                raise RefPackError("output overflow: %d > %d" % (len(out), usize))

    if len(out) != usize:
        raise RefPackError("size mismatch: got %d, header says %d" % (len(out), usize))
    if mapped:
        return bytes(out), p - offset, srcmap
    return bytes(out), p - offset


def scan(data, limit=32, max_out=256 * 1024 * 1024):
    """在字节串里找可解压的 RefPack 块，返回 [(offset, size, out_len, out), ...]。"""
    found = []
    pos = 0
    while True:
        i = data.find(b"\xfb", pos + 1)
        if i < 0 or len(found) >= limit:
            break
        pos = i
        start = i - 1
        if start < 0:
            continue
        flags = data[start]
        if flags & 0x0E:            # flag 的保留位应多为 0
            continue
        try:
            out, used = decompress(data, start, max_out=max_out)
        except RefPackError:
            continue
        if used > 8 and out:
            found.append((start, used, len(out), out))
            pos = start + used - 1
    return found


def selftest():
    cases = []
    # stop 命令带 2 个字面字节
    cases.append((b"\x10\xfb" + (2).to_bytes(3, "big") + b"\xfeAB", b"AB"))
    # cmd2: 1 字面 + 3 字节回引用(disp=1) -> "AAAA"
    cases.append((b"\x10\xfb" + (4).to_bytes(3, "big") + b"\x01\x00A\xfc", b"AAAA"))
    # cmd1: 4 字面 + stop
    cases.append((b"\x10\xfb" + (5).to_bytes(3, "big") + b"\xe0HELL\xfdO", b"HELLO"))
    # 32-bit size + compressed size 字段（0xFF = stop 带 3 个字面字节）
    cases.append((b"\x91\xfb" + (3).to_bytes(4, "big") +
                  (0).to_bytes(4, "big") + b"\xffABC", b"ABC"))
    for i, (stream, expect) in enumerate(cases, 1):
        got, used = decompress(stream)
        ok = got == expect
        print("selftest %d: %s  got=%r used=%d" % (i, "OK" if ok else "FAIL", got, used))
        if not ok:
            return 1
    # mapped：1 个字面字节有输入偏移，3 个回引用字节为 -1
    stream = cases[1][0]
    out, used, src = decompress(stream, mapped=True)
    ok = out == b"AAAA" and src[0] == 7 and src[1:] == [-1, -1, -1]
    print("selftest 5 (mapped): %s  srcmap=%s" % ("OK" if ok else "FAIL", src))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(selftest())
