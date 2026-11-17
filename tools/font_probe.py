#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零成本判别实验：主菜单 FONT 表到底是不是从 HDD DLC 的 `.str` 读的。

背景（WORKLOG 第 18 节）：
  文本层已能汉化，但汉字渲染成方块 —— `minion_pro` 的 FONT 字符表只有
  215 个字符、0 个 CJK。要补字形就必须改字体表：
    * 若游戏运行时读的是
      dev_hdd0/game/BLUS30405/USRDIR/dia_core/arena_templates/
      arena_templates_global.str 里那份 **未压缩 SDAT** 的 `minion_pro` FONT，
      改动可局限在 34 MB 散文件，绕开 8.4 GiB VIV 重排；
    * 若读的是光盘 VIV / EBOOT 内的副本，则必须改 BIGH TOC 并重排归档。

做法：全部**等长**，只改 40 字节，不改任何长度、偏移、字符数，可一键回滚。

  探针 A —— 把 4 个几乎不会在菜单里出现的组合重音码点
            (U+02D8/02D9/02DA/02DB) 的记录首 2 字节，改成「开始游戏」
            的 4 个码点 (u16 LE)。
            阳性：4 个方块变成 4 个可见字形 —— 读这份表，且字符表可直接扩。

  探针 B —— 把 e/t/a/o 四条记录的 UV 矩形 (+0x0C..+0x13, 8 B) 替换成
            `W` 的 UV 矩形。码点不动，完全不依赖查表机制。
            阳性：菜单英文里这些字母显示成 W —— 读这份表。
            用途：排除「探针 A 因哈希表/固定索引查表而假阴性」。

  字符表实测是**无序**的（`codes == sorted(codes)` 为 False），因此改码点
  不存在「破坏二分表」的问题；但引擎仍可能按 hash 索引，故必须配探针 B。

判读表：
  A+ B+  -> 捷径成立：后续扩表可只改这份 .str
  A- B+  -> 读这份表，但查表非顺序扫描，扩表要按引擎索引规则
  A- B-  -> 不读这份 .str，走光盘 VIV 副本（回到抓帧 / 日版 diff）
  A+ B-  -> 读这份表（UV 可能被别的图集覆盖），仍算阳性

用法（在 G:\\DanteHanhua 下）：
  py -3 tools/font_probe.py --check     只读，看当前状态
  py -3 tools/font_probe.py --apply     备份 + 写入探针
  py -3 tools/font_probe.py --restore   从备份还原并校验 sha256
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, resolve
from parse_font_str import find_fonts_in_file, parse_font, u16le

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FONT_NAME = "minion_pro"
SEGMENT = "SDAT"
A_SRC = (0x02D8, 0x02D9, 0x02DA, 0x02DB)
A_TEXT = "开始游戏"
B_CPS = (0x65, 0x74, 0x61, 0x6F)   # e t a o
UV_SRC = 0x57                        # W 的字形


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def paths(cfg):
    p = os.path.join(resolve(cfg, "rpcs3_root"), "dev_hdd0", "game",
                     "BLUS30405", "USRDIR", "dia_core", "arena_templates",
                     "arena_templates_global.str")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bdir = os.path.join(root, "patch", "font_probe_backup")
    return p, os.path.join(bdir, "arena_templates_global.str.orig"), \
        os.path.join(root, "patch", "font_probe.json")


def locate(path):
    """动态定位 SDAT 明文 minion_pro FONT 块，不硬编码偏移。"""
    fonts, d = find_fonts_in_file(path)
    hit = [f for f in fonts
           if f["name"] == FONT_NAME and f["segment"] == SEGMENT]
    if len(hit) != 1:
        raise RuntimeError("期望恰好 1 个 SDAT minion_pro FONT 块，实际 %d" % len(hit))
    return hit[0], d


def rec_off(f, idx):
    return f["font_offset"] + f["table_base"] + idx * f["record_stride"]


def build_plan(f, d):
    """返回 [(绝对偏移, 原字节, 新字节, 说明)]。"""
    n = f["char_count"]
    codes = [u16le(d, rec_off(f, i)) for i in range(n)]
    index = {c: i for i, c in enumerate(codes)}
    edits = []

    for src, ch in zip(A_SRC, A_TEXT):
        if src not in index:
            raise RuntimeError("缺少源码点 U+%04X" % src)
        dst = ord(ch)
        if dst in index:
            raise RuntimeError("目标码点 U+%04X 已存在，不该覆盖" % dst)
        o = rec_off(f, index[src])
        edits.append((o, d[o:o + 2], struct.pack("<H", dst),
                      "A 码点 U+%04X -> U+%04X (%s)" % (src, dst, ch)))

    if UV_SRC not in index:
        raise RuntimeError("缺少 UV 参考字符 U+%04X" % UV_SRC)
    uv = d[rec_off(f, index[UV_SRC]) + 0x0C:
           rec_off(f, index[UV_SRC]) + 0x14]
    for cp in B_CPS:
        if cp not in index:
            raise RuntimeError("缺少探针字符 U+%04X" % cp)
        o = rec_off(f, index[cp]) + 0x0C
        edits.append((o, d[o:o + 8], uv,
                      "B UV U+%04X -> W 的 UV" % cp))
    return edits


def check(cfg):
    p, backup, meta = paths(cfg)
    if not os.path.isfile(p):
        print("缺文件:", p)
        return 1
    f, d = locate(p)
    codes = [u16le(d, rec_off(f, i)) for i in range(f["char_count"])]
    cjk = [c for c in codes if 0x4E00 <= c <= 0x9FFF]
    print("文件        :", p)
    print("大小        : %d B   sha256=%s" % (os.path.getsize(p), sha256(p)))
    print("FONT 块     : off=0x%X  chars=%d  stride=%d  无序=%s" % (
        f["font_offset"], f["char_count"], f["record_stride"],
        codes != sorted(codes)))
    print("CJK 码点    : %d %s" % (len(cjk), [hex(c) for c in cjk]))
    print("A 源仍在    :", [hex(c) for c in A_SRC if c in codes])
    if os.path.isfile(meta):
        m = json.load(open(meta, encoding="utf-8"))
        cur = sha256(p)
        state = ("已应用探针" if cur == m["sha256_after"] else
                 "已还原/原始" if cur == m["sha256_before"] else
                 "与记录均不符（文件被外部改过）")
        print("记录状态    :", state)
        print("备份        :", m["backup"], "存在=%s" % os.path.isfile(backup))
    else:
        print("记录状态    : 未应用过探针")
    # 结构自校验
    font = d[f["font_offset"]: f["font_offset"] + f["declared_total"]]
    info = parse_font(font)
    print("FONT 解析   : OK  name=%s  N=%d  表终点=0x%X" % (
        info["name"], info["char_count"], info["table_end"]))
    return 0


def apply(cfg):
    p, backup, meta = paths(cfg)
    if not os.path.isfile(p):
        print("缺文件:", p)
        return 1
    f, d = locate(p)
    edits = build_plan(f, d)
    before = sha256(p)

    if os.path.isfile(meta):
        m = json.load(open(meta, encoding="utf-8"))
        if before == m["sha256_after"]:
            print("探针已经处于应用状态，无需重复执行。")
            return 0
        if before != m["sha256_before"]:
            print("文件状态与记录不符，拒绝覆盖。请先 --restore 或人工核对。")
            return 1
    elif os.path.isfile(backup):
        print("存在无记录的历史备份，拒绝盲目覆盖:", backup)
        return 1

    os.makedirs(os.path.dirname(backup), exist_ok=True)
    shutil.copyfile(p, backup)
    if sha256(backup) != before:
        print("备份校验失败，已中止，未改动原文件。")
        return 1

    try:
        with open(p, "r+b") as fp:
            for o, old, new, tag in edits:
                fp.seek(o)
                if fp.read(len(new)) != old:
                    raise RuntimeError("写入前校验失败 @0x%X (%s)" % (o, tag))
                fp.seek(o)
                fp.write(new)
            fp.flush()
            os.fsync(fp.fileno())
    except PermissionError:
        print("文件被占用（RPCS3 可能正在运行）。请完全退出模拟器后重试；"
              "原文件未被修改，备份已保存在", backup)
        return 1
    except Exception as e:
        shutil.copyfile(backup, p)
        print("写入失败已回滚:", e)
        return 1

    # 严格验证：只有计划中的字节发生变化
    exp = bytearray(d)
    for o, old, new, tag in edits:
        exp[o:o + len(new)] = new
    after = sha256(p)
    if after != hashlib.sha256(bytes(exp)).hexdigest():
        shutil.copyfile(backup, p)
        print("整体校验失败（出现了计划外改动），已回滚。")
        return 1
    if os.path.getsize(p) != len(d):
        shutil.copyfile(backup, p)
        print("文件长度变化，已回滚。")
        return 1

    rec = {
        "purpose": "判别主菜单 FONT 表是否来自 HDD DLC 的 arena_templates_global.str",
        "file": p,
        "backup": backup,
        "sha256_before": before,
        "sha256_after": after,
        "font_offset": f["font_offset"],
        "edits": [{"offset": o, "old_hex": old.hex(), "new_hex": new.hex(),
                   "note": tag} for o, old, new, tag in edits],
        "probe_a": "把 U+02D8/02D9/02DA/02DB 的码点改为「开始游戏」，看方块是否变成可见字形",
        "probe_b": "把 e/t/a/o 的 UV 改为 W 的 UV，看菜单英文是否变成 W",
    }
    with open(meta, "w", encoding="utf-8") as fp:
        json.dump(rec, fp, ensure_ascii=False, indent=1)

    print("应用完成：%d 处、%d 字节，等长；长度 %d B 不变" % (
        len(edits), sum(len(n) for _, _, n, _ in edits), os.path.getsize(p)))
    for o, old, new, tag in edits:
        print("  @0x%08X  %s -> %s  %s" % (o, old.hex(), new.hex(), tag))
    print("sha256: %s -> %s" % (before, after))
    print("备份:", backup)
    print("记录:", meta)
    return 0


def restore(cfg):
    p, backup, meta = paths(cfg)
    if not os.path.isfile(backup):
        print("没有备份，无法还原:", backup)
        return 1
    if not os.path.isfile(meta):
        print("没有记录文件，无法校验:", meta)
        return 1
    m = json.load(open(meta, encoding="utf-8"))
    if sha256(p) == m["sha256_before"]:
        print("原文件已处于原始状态，无需还原。")
        return 0
    try:
        shutil.copyfile(backup, p)
    except PermissionError:
        print("文件被占用（请完全退出 RPCS3 后重试），未改动。")
        return 1
    ok = sha256(p) == m["sha256_before"]
    print("还原:", "PASS" if ok else "FAIL", sha256(p))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="只读查看状态")
    g.add_argument("--apply", action="store_true", help="备份并写入探针")
    g.add_argument("--restore", action="store_true", help="从备份还原")
    args = ap.parse_args()
    cfg = load_config()
    if args.check:
        return check(cfg)
    if args.apply:
        return apply(cfg)
    return restore(cfg)


if __name__ == "__main__":
    sys.exit(main())
