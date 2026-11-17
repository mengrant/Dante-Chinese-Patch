#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EA RefPack / PSA (LZSS) 压缩器，纯标准库实现，与 refpack.decompress 对称。

贪心 LZ77 + 3 字节前缀哈希链。指令格式直接由解压器反推：
  0x00-0x7F  c,(d&0xFF),[lit]       lzlen 3..10   disp <= 0x400
  0x80-0xBF  c,b1,b2,[lit]          lzlen 4..67   disp <= 0x4000
  0xC0-0xDF  c,b1,b2,b3,[lit]       lzlen 5..1028 disp <= 0x20000
  0xE0-0xFB  c,[4*(n+1) 个字面]     纯字面，4..128 字节
  0xFC-0xFF  c,[0..3 个字面]        结束

注意：字面字节紧跟在命令头（含 disp 字节）之后，因为解压器是
「先读命令头 -> 拷 raw 个字面 -> 再做回引用」。

用法: py -3 tools/refpack_encode.py      # 跑自测
      from refpack_encode import compress
"""
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MAX_WIN = 0x1FFFF
MAX_MATCH = 1028
MIN_MATCH = 3


class EncodeError(ValueError):
    pass


def _flush(out, pending, keep=3):
    """把 pending 中成 4 倍数的字面用 0xE0 命令发出，保留最后 0..keep 个。"""
    while len(pending) > keep:
        chunk = min(112, (len(pending) // 4) * 4)
        if chunk < 4:
            break
        out.append(0xE0 | (chunk // 4 - 1))
        out += pending[:chunk]
        del pending[:chunk]


def encodable(dist, length):
    """该 (距离, 长度) 组合是否能被三类匹配命令表示。"""
    d = dist - 1
    if d <= 0x3FF and 3 <= length <= 10:
        return True
    if d <= 0x3FFF and 4 <= length <= 67:
        return True
    if d <= MAX_WIN and 5 <= length <= MAX_MATCH:
        return True
    return False


def _match_cmd(out, lit, dist, length):
    d = dist - 1
    lm = length - 5 if length >= 5 else 0
    nlit = len(lit)

    if d <= 0x3FF and length <= 10:
        c = (((d >> 8) & 3) << 5) | ((length - 3) << 2) | nlit
        out.append(c)
        out.append(d & 0xFF)
    elif d <= 0x3FFF and length <= 67:
        out.append(0x80 | (length - 4))
        out.append((nlit << 6) | ((d >> 8) & 0x3F))
        out.append(d & 0xFF)
    elif d <= MAX_WIN and length <= MAX_MATCH:
        c = (0xC0 | (((lm >> 8) & 3) << 2)
             | (((d >> 16) & 1) << 4) | nlit)
        out.append(c)
        out.append((d >> 8) & 0xFF)
        out.append(d & 0xFF)
        out.append(lm & 0xFF)
    else:
        raise EncodeError("match out of range: dist=%d len=%d" % (dist, length))
    out += lit


def compress(data, candidates=32):
    """压缩 bytes，返回可被 refpack.decompress 解压的 RefPack 流。

    candidates 越大压缩率越好但越慢；默认 32 足以接近原版压缩率。
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be bytes")
    n = len(data)
    if n >= 1 << 24:
        raise EncodeError("data too large for 24-bit size header")

    out = bytearray(b"\x10\xfb")
    out += n.to_bytes(3, "big")
    heads = {}
    pending = bytearray()
    i = 0

    def add(pos):
        if pos + 3 <= n:
            key = bytes(data[pos:pos + 3])
            lst = heads.setdefault(key, [])
            lst.append(pos)
            if len(lst) > 64:
                del lst[0]

    while i < n:
        best_len, best_dist = 0, 0
        if i + MIN_MATCH <= n:
            lst = heads.get(bytes(data[i:i + MIN_MATCH]), ())
            for j in reversed(lst[-candidates:]):
                dist = i - j
                if dist > MAX_WIN:
                    break
                limit = min(MAX_MATCH, n - i)
                l = MIN_MATCH
                while l < limit and data[j + l] == data[i + l]:
                    l += 1
                if l > best_len:
                    best_len, best_dist = l, dist
                    if l >= limit:
                        break

        if best_len >= MIN_MATCH and encodable(best_dist, best_len):
            _flush(out, pending, keep=3)
            _match_cmd(out, bytes(pending), best_dist, best_len)
            pending.clear()
            for k in range(i, i + best_len):
                add(k)
            i += best_len
        else:
            pending.append(data[i])
            add(i)
            i += 1

    _flush(out, pending, keep=3)
    out.append(0xFC | len(pending))
    out += pending
    return bytes(out)


def selftest():
    import os
    from refpack import decompress
    cases = [
        b"",
        b"A",
        b"HELLO",
        b"A" * 5000,
        b"Start Game" * 300 + b"Select" * 200,
        bytes(os.urandom(4096)),
        (b"the quick brown fox jumps over the lazy dog " * 200),
    ]
    for i, src in enumerate(cases, 1):
        packed = compress(src)
        got, used = decompress(packed)
        ok = got == src and used == len(packed)
        print("selftest %d: in=%-6d packed=%-6d ratio=%.3f %s"
              % (i, len(src), len(packed),
                 len(packed) / max(len(src), 1), "OK" if ok else "FAIL"))
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(selftest())
