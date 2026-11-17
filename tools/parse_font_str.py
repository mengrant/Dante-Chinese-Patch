#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析 EA `SHOC` 容器（DLC `.str` / VIV 条目）里的 `FONT` 字体定义。

用途：在不启动游戏、不扫描 8.4 GiB VIV 的前提下，确认本作位图字体的
字符映射表格式，评估「扩图集 + 扩字符表」的工作量。

背景（见 WORKLOG 第 18 节）：
  主菜单字体是 `shared\\fonts\\minion_pro.*`，由三件套组成：
    `.tg4h` 纹理头 + `.tg4d` 图集位图（A8 单通道 alpha，按钮字体为 DXT5）
    + `.ffn`/`.inf` 里的 `FONT` 字符表（码点 -> UV 矩形 + 字宽/基线）。
  HDD 官方 DLC 的 `arena_frontend.str` / `arena_templates_global.str`
  同时打包了 arena 版与主游戏版 `minion_pro` / `buttons` 的 FONT 定义，
  其中 `arena_templates_global.str` 里是**未压缩 SDAT 明文**，
  `arena_frontend.str` 里是 **Rpak 压缩块**，两者可互为校验。

`FONT` 文件布局（big-endian，除非另注）：
  0x00  'FONT'
  0x04  u32  文件总长度
  0x08  u16  未知（实测 7）
  0x0A  u16  字符数 N
  0x0C  u32  字符表起点（实测 0x454）
  0x10  u32  0
  0x14  3×u32 字体度量（实测 34 / 42 / 34）
  0x20  16 B  字体名（NUL 补齐）
  0x40  u32  字符表终点（实测 0x187C）
  0x44  3×u32 分段偏移（实测 4 / 0x404 / 0x804）
  0x454 .. 0x187C  N 条 × 24 B 字符记录：
      +0x00  u16 LE  码点
      +0x02  u16 BE  字宽 / advance（推测）
      +0x04..+0x0A  3×u16 BE  字形边界与基线
      +0x0C..+0x14  4×u16 BE  图集 UV 矩形 (x1,y1,x2,y2)
      +0x16..+0x17  2×u16     保留 0
  0x1880 .. EOF  全 0 预留区

用法（在 G:\\DanteHanhua 下）：
  py -3 tools/parse_font_str.py                 # 解析已知 DLC 样本并写报告
  py -3 tools/parse_font_str.py --self-test     # 用实测常量自测
  py -3 tools/parse_font_str.py --scan-str      # 扫全部 DLC .str 找 FONT 块
"""
import argparse
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, resolve

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 实测常量（用于自测，来自美版 BLUS30405 官方 DLC）
EXPECT = {
    "minion_pro": {"count": 215, "total": 14464, "base": 0x454,
                   "end": 0x187C, "stride": 24},
    "minion_pro_arena": {"count": 215, "total": 14464, "base": 0x454,
                         "end": 0x187C, "stride": 24},
    "buttons": {"count": 51, "total": 3360, "base": 0x454,
                "end": 0x91C, "stride": 24},
    "buttons_arena": {"count": 51, "total": 3360, "base": 0x454,
                      "end": 0x91C, "stride": 24},
}

FONT_RES = re.compile(
    rb"shared\\fonts\\[\x20-\x7e]{4,120}?\.(?:tg4h|tg4d|inf|ffn)", re.I)


def u16be(b, o):
    return struct.unpack_from(">H", b, o)[0]


def u16le(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32be(b, o):
    return struct.unpack_from(">I", b, o)[0]


def parse_font(full):
    """解析一个已解压的 FONT 逻辑文件。"""
    if len(full) < 0x48 or full[:4] != b"FONT":
        raise ValueError("不是 FONT 文件: %r" % full[:8])
    total = u32be(full, 0x04)
    count = u16be(full, 0x0A)
    base = u32be(full, 0x0C)
    end = u32be(full, 0x40)
    name = full[0x20:0x40].split(b"\0")[0].decode("latin-1")
    if not (0 < count < 100000 and 0 <= base < end <= len(full)):
        raise ValueError("表边界不合理: count=%d base=0x%X end=0x%X len=%d"
                         % (count, base, end, len(full)))
    stride = (end - base) // count
    if (end - base) % count or not (8 <= stride <= 64):
        raise ValueError("步长不合理: %d" % stride)
    codes = [u16le(full, base + i * stride) for i in range(count)]
    recs = []
    for i in (0, count - 1):
        rec = full[base + i * stride: base + (i + 1) * stride]
        recs.append({"index": i, "codepoint": codes[i],
                     "fields_be_u16": [u16be(rec, 2 * j) for j in range(1, 12)]})
    uniq = set(codes)
    return {
        "name": name,
        "declared_total": total,
        "actual_length": len(full),
        "char_count": count,
        "table_base": base,
        "table_end": end,
        "record_stride": stride,
        "metrics": [u32be(full, 0x14), u32be(full, 0x18), u32be(full, 0x1C)],
        "section_offsets": [u32be(full, 0x44), u32be(full, 0x48), u32be(full, 0x4C)],
        "codepoint_min": min(codes),
        "codepoint_max": max(codes),
        "unique": len(uniq),
        "ascii_32_126": len({c for c in uniq if 32 <= c <= 126}),
        "latin1_160_255": len({c for c in uniq if 160 <= c <= 255}),
        "above_latin1": sorted(c for c in uniq if c > 0xFF),
        "cjk_count": sum(1 for c in codes if 0x4E00 <= c <= 0x9FFF),
        "has_e_acute": 0xE9 in uniq,
        "has_japanese": all(ord(c) in uniq for c in "日本語"),
        "records_sample": recs,
        "tail_all_zero": not any(full[end:]),
    }


def find_fonts_in_file(path):
    """在一整个 `.str` 文件里定位并解析所有 FONT 块。

    支持两种 SHOC 段：
      SDAT  —— SHOC + u32 size + 'SDAT' + FONT 明文（未压缩）
      Rpak  —— SHOC + u32 size + 'Rpak' + u32 size + RefPack 流
    """
    with open(path, "rb") as f:
        d = f.read()
    out = []
    for mo in re.finditer(b"FONT", d):
        pos = mo.start()
        if pos + 8 > len(d):
            continue
        total = u32be(d, pos + 4)
        if not (1000 <= total <= 2 * 1024 * 1024):
            continue
        shoc = d.rfind(b"SHOC", max(0, pos - 64), pos)
        if shoc < 0 or shoc + 12 > len(d):
            continue
        seg = d[shoc + 8: shoc + 12]
        if seg == b"SDAT":
            font = d[pos: pos + total]
            if len(font) < total:
                continue
            kind = "SDAT"
        elif seg == b"Rpak":
            from lh2_patch import build_full_with_map
            size = u32be(d, shoc + 4)
            try:
                font, _ = build_full_with_map(d[shoc: shoc + size])
            except Exception:
                continue
            kind = "Rpak"
        else:
            continue
        try:
            info = parse_font(font)
        except ValueError:
            continue
        info.update({"file": os.path.basename(path),
                     "shoc_offset": shoc, "font_offset": pos,
                     "segment": kind})
        out.append(info)
    return out, d


def font_resource_descriptors(d):
    """收集字体资源名与纹理格式标记（只读，不解析像素）。"""
    out = []
    for mo in FONT_RES.finditer(d):
        name = mo.group(0).decode("latin-1")
        ctx = d[mo.start(): mo.start() + 96]
        fmt = "A8" if b"A8\x00" in ctx or b"\x00A8\x00" in ctx else (
            "DXT5" if b"DXT5" in ctx else "")
        if name not in [x["name"] for x in out]:
            out.append({"name": name, "offset": mo.start(), "format_hint": fmt})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true", help="用实测常量自测")
    ap.add_argument("--scan-str", action="store_true", help="扫全部 DLC .str 找 FONT 块")
    ap.add_argument("--out", default=None, help="报告输出路径")
    args = ap.parse_args()

    cfg = load_config()
    hdd = os.path.join(resolve(cfg, "rpcs3_root"), "dev_hdd0", "game",
                       "BLUS30405", "USRDIR", "dia_core")
    samples = [
        os.path.join(hdd, "arena_frontend.str"),
        os.path.join(hdd, "arena_templates", "arena_templates_global.str"),
    ]

    if args.self_test:
        ok = True
        for s in samples:
            if not os.path.isfile(s):
                print("SKIP 缺文件:", s)
                continue
            fonts, _ = find_fonts_in_file(s)
            for f in fonts:
                exp = EXPECT.get(f["name"])
                if not exp:
                    print("  ? 未知字体 %s，跳过断言" % f["name"])
                    continue
                key_map = {"count": "char_count", "total": "declared_total",
                           "base": "table_base", "end": "table_end",
                           "stride": "record_stride"}
                good = all(f[key_map[k]] == v for k, v in exp.items())
                good &= f["cjk_count"] == 0
                if f["name"].startswith("minion_pro"):
                    good &= (f["has_e_acute"] and not f["has_japanese"]
                             and f["ascii_32_126"] == 95
                             and f["latin1_160_255"] == 96)
                else:
                    good &= f["ascii_32_126"] == 19
                print("  %-22s %-6s %s" % (
                    f["name"], f["segment"], "PASS" if good else "FAIL"))
                if not good:
                    print("     实际:", {k: f[k] for k in exp})
                    ok = False
        print("自测结论:", "PASS" if ok else "FAIL")
        return 0 if ok else 1

    fonts = []
    descriptors = []
    scanned = []
    if args.scan_str:
        root = os.path.dirname(hdd)
        files = [os.path.join(dp, f) for dp, _, fns in os.walk(root)
                 for f in fns if f.lower().endswith(".str")]
    else:
        files = samples
    for p in sorted(files):
        if not os.path.isfile(p):
            continue
        fs, d = find_fonts_in_file(p)
        if fs:
            scanned.append(os.path.relpath(p, os.path.dirname(hdd)))
            fonts.extend(fs)
            descriptors.extend(font_resource_descriptors(d))
    # 去重
    uniq = {}
    for f in fonts:
        uniq[(f["file"], f["font_offset"])] = f
    fonts = sorted(uniq.values(), key=lambda x: (x["file"], x["font_offset"]))
    seen = set()
    descriptors = [x for x in descriptors
                   if not (x["name"] in seen or seen.add(x["name"]))]

    report = {
        "note": "EA SHOC/FONT 字体定义格式反推；只含结构元数据，不含游戏文本与资源位图。",
        "files_with_font": scanned,
        "font_blocks": fonts,
        "font_resource_names": descriptors[:80],
        "conclusion": {
            "encoding": "UTF-8 文本层无需改动；字形查表走 FONT 字符表",
            "font_table": "N 条 × 24 B，u16 LE 码点 + u16 BE 字宽/UV 矩形",
            "coverage": "minion_pro 215 字符 = ASCII 95/95 + Latin-1 96/96 + 24 个排版/图标码点，0 个 CJK",
            "why_tofu": "汉字码点不在 FONT 表里，查表失败走 fallback 方块",
            "work_required": [
                "用本机 SCE-PS3-DH-R-CGB.TTF（20902 汉字）烘焙 A8 字形位图并扩 .tg4d 图集",
                "把汉字码点追加进 FONT 字符表（N 增大，文件超出 14464 B）",
                "同步改 FONT 头：字符数、表终点、总长、分段偏移",
                "图集/表变大后超出原条目容量，必须改 BIGH TOC 的 span 并重排归档",
            ],
        },
    }
    out = args.out or os.path.join(resolve(cfg, "report"), "font_str_format.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=1)
    print("扫描文件=%d  含 FONT 的文件=%d  FONT 块=%d  资源名=%d"
          % (len(files), len(scanned), len(fonts), len(descriptors)))
    for f in fonts:
        print("  %-34s %-20s %-5s chars=%-4d stride=%-3d CJK=%d é=%s ASCII=%d/95"
              % (f["file"][:34], f["name"], f["segment"], f["char_count"],
                 f["record_stride"], f["cjk_count"], f["has_e_acute"],
                 f["ascii_32_126"]))
    print("报告:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
