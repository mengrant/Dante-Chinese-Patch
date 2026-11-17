#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程公共配置加载。

优先以仓库根目录的 config.local.json（本机路径，已被 .gitignore 排除）覆盖
config.json（可提交的模板）。路径值支持：
  - 绝对路径：直接使用
  - 相对路径：相对仓库根目录解析
  - <PLACEHOLDER>：未填写，resolve() 会报错并提示如何配置

公开仓库里不应出现任何本机绝对路径，因此所有脚本都必须通过这里取路径。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    cfg = {}
    base = os.path.join(ROOT, "config.json")
    if os.path.isfile(base):
        with open(base, "r", encoding="utf-8") as fp:
            cfg = json.load(fp)
    local = os.path.join(ROOT, "config.local.json")
    if os.path.isfile(local):
        with open(local, "r", encoding="utf-8") as fp:
            cfg.update(json.load(fp))
        cfg["_source"] = "config.local.json"
    else:
        cfg["_source"] = "config.json"
    if not cfg:
        raise RuntimeError("找不到配置：请在仓库根目录放置 config.json")
    return cfg


def resolve(cfg, key, default=None):
    value = cfg.get(key, default)
    if value is None:
        raise RuntimeError("配置缺少键 %r" % key)
    if isinstance(value, str) and "<" in value and ">" in value:
        raise RuntimeError(
            "配置项 %r 仍是占位符 %s。请把 config.json 复制为 "
            "config.local.json 并填入本机路径（该文件不会提交）。" % (key, value))
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(ROOT, value))


def report_path(cfg, filename):
    d = resolve(cfg, "report")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, filename)


def ensure_dir(cfg, key):
    d = resolve(cfg, key)
    os.makedirs(d, exist_ok=True)
    return d
