# dante-chinese-fix

> PS3《Dante's Inferno: Divine Edition》美版（`BLUS30405`）中文补丁 —— 逆向分析与工具工程

[![Language](https://img.shields.io/badge/code-Python%203-blue)](#快速开始)
[![Stage](https://img.shields.io/badge/stage-逆向分析%2F预研-orange)](#当前状态)
[![Content](https://img.shields.io/badge/游戏资源-0%20个-brightgreen)](#合规声明)

## 这个项目是什么

目标是让 PS3 美版《但丁的地狱：神圣版》显示中文：把游戏里的界面、菜单与字幕文本提取出来，翻译成可维护的文本表，再以补丁形式回填，并在模拟器里验证显示效果。

**本仓库不是补丁下载页，也不是游戏文件镜像。** 这里只放实现目标所需的原创脚本、格式分析结论、元数据索引与工作记录。任何 ISO、VIV、PKG、EBOOT、贴图、视频、种子文件都不入库，也不会通过本仓库分发。

## 当前状态

> ⚠️ **预研阶段，尚未产出可安装的汉化补丁。**

目前完成的是 ISO 与资源容器层的**只读分析**：摸清了光盘结构、破解了 EA `BIGH` 归档头、建立了 5888 条记录的完整 TOC 索引，并确认了文本的隐藏层级。下一步是解压与文本提取，之后才谈得上翻译。

想跟进细节请看 [`WORKLOG.md`](WORKLOG.md)（含实测数据、格式推导过程与决策记录）。

## 目标

| 阶段 | 目标 | 状态 |
|---|---|---|
| 1. 定位 | 解 ISO → 解 VIV → 找到文本容器，产出可复现的分析工具 | ✅ 基本完成 |
| 2. 提取 | 实现 EA RefPack 解压，解析 `.lh2` 字符串指针表，导出 CSV/JSON 文本表 | 🔜 进行中 |
| 3. 闭环 | 只改一处文本，跑通「重压 → 回填 → RPCS3 显示中文」，验证字库与编码可行 | ⬜ 未开始 |
| 4. 翻译 | 批量翻译、术语统一、重算指针、保护控制码与换行 | ⬜ 未开始 |
| 5. 交付 | 生成 Patch PKG / 差异补丁，模拟器与真机验收 | ⬜ 未开始 |

**明确不做**：不改 `EBOOT.BIN` 渲染代码（除非字库方案走不通）、不碰在线功能与 DRM、不提供任何游戏本体或完整资源包。

## 一个容易走弯路的概念：这不是 DLC

PS3 的 DLC 是「追加内容」，游戏不会拿它替换主程序里的文本。汉化的正确载体是 **Game Update / Patch PKG** 或**散文件覆盖**。

巧的是这张盘自带样板：`/UPDATE/` 下的官方补丁 content ID 为 `UP0006-BLUS30405_00-INFERNOPATCH0003`，自制补丁照这个形式落到 `dev_hdd0/game/BLUS30405/USRDIR/` 即可。同时 RPCS3 会优先读取该目录下的同名文件，所以开发期**不必每次重打包 9.47 GiB 的 ISO**，散文件覆盖就能验证。

## 已确认的技术事实（均为实测，非推测）

| 项 | 结论 |
|---|---|
| 光盘 | 单个 ISO，10,167,930,880 字节 ≈ 9.47 GiB；`PARAM.SFO`：TITLE_ID `BLUS30405`、APP_VER `01.00`、CATEGORY `DG`、系统版本 3.15 |
| 主资源 | `PS3_GAME/USRDIR/BIGFILE0/1/2.VIV` = 2.87 / 2.63 / 2.95 GiB，magic 均为 `BIGH`（EA BIG 归档变体） |
| 归档结构 | 头 24 字节；TOC 从 `0x18` 起、每条 12 字节；`toc_size = 24 + 12 × 文件数`，三个 VIV 分别 4898 / 947 / 43 条，全部精确吻合 |
| 名字表 | **无集中文件名表**，TOC 之后直接是数据；内部路径以明文藏在条目自身头部（`*.tg4h`、`*.apx`、`*.smb`、`*.bnk.ps3`） |
| 文本位置 | 全量扫描 8.4 GiB 数据区后，明文几乎只有资源路径，没有英文句子。文本在 `.ols` 容器内、经 **EA RefPack** 压缩的 `.lh2` 中，属**带字符串指针表的二进制** |
| 视频 | `BIGFILE2` 仅 43 条，为 VP6 过场视频，基本可排除文本在此 |

BIGH 头部布局：

```
0x00  magic  "BIGH"                  (4B, BE)
0x04  u32be  field4                  (含义待定)
0x08  u32be  num_files
0x0C  u32be  toc_size = 24 + 12*N
0x18  TOC    N 条 × 12B，每条 3 个 u32be (A, B, C)
toc_size     数据区开始
```

TOC 按 A 字段严格递增排列，推测为排序用的文件名哈希；B / C 中哪个是偏移、哪个是长度，仍需结合条目数据头最终确认 —— 这是写 `viv_extract.py` 前必须解决的一点。

## 仓库内容

```
.
├── README.md                    # 本文件
├── WORKLOG.md                   # 实测数据、格式推导、决策与待办（个人环境记录，含本机路径）
├── config.json                  # 本机路径与容器参数示例，请按自己机器修改
├── .gitignore                   # 排除一切游戏资源与临时产物
├── push-to-github.bat           # Windows 下一键推送（首次使用会弹 GitHub 登录）
├── tools/
│   ├── iso_probe.py             # ISO9660 目录树、PARAM.SFO、大文件 magic
│   ├── viv_probe.py             # VIV 头部/TOC 明文串、光盘内置 PKG content ID
│   ├── viv_dump.py              # 十六进制 dump VIV 头部，用于推断 TOC 布局
│   ├── viv_toc_probe.py         # 验证 toc_size 公式与 TOC 后的数据形态
│   ├── viv_index.py             # 建立全量 TOC 索引 → report/viv_index.json
│   └── text_scan.py             # 8 MiB 块顺序扫描数据区 → report/text_hotspots.json
└── report/
    ├── viv_index.json           # 5888 条 TOC 记录索引
    └── text_hotspots.json       # 文本/容器关键字命中统计
```

**所有现有脚本都是只读的**：不写回 ISO、不删除文件、不修改任何游戏数据。`config.json` 里记录的是本机环境，仅供参考，不要直接照搬。

## 快速开始

需要：**Python 3.x**（脚本只用标准库）、一份**自己拥有的正版 ISO**、以及（可选的）**RPCS3** 用于验证。不需要安装 QuickBMS 或 010 Editor 就能跑现有的分析脚本。

```bash
# 1. 克隆
git clone https://github.com/mengrant/dante-chinese-fix.git
cd dante-chinese-fix

# 2. 把 tools/*.py 顶部的 ISO 常量改成你本机的 ISO 路径
#    （当前脚本把路径写死在文件头，统一读 config.json 已列入待办）

# 3. 依次运行只读探针
py -3 tools/iso_probe.py
py -3 tools/viv_probe.py
py -3 tools/viv_toc_probe.py
py -3 tools/viv_index.py
py -3 tools/text_scan.py        # 顺序读约 8.4 GiB，耗时较长
```

Windows 用 `py -3`，其他平台把 `py -3` 换成 `python3` 即可；路径分隔符需自行调整（脚本目前面向 Windows）。`report/*.json` 是脚本输出，可用任意 JSON 工具查看。

## 后续工具链（尚未入库）

| 环节 | 计划采用的方案 |
|---|---|
| 解 VIV / 抽条目 | 自写 `viv_extract.py`（纯 Python，增量式） |
| 解压与重压 | EA RefPack（PSA）实现；必要时对照 QuickBMS 的 EA BIG / 该作专用 BMS 脚本 |
| 文本与指针表 | 导出 CSV/JSON；参考 Kruptar 处理带指针的二进制文本 |
| 字库 | 生成中文图集 + 自定义 `char → glyph` 映射，替换 `.tg4h/.tg4d` 并扩字符映射表 |
| 验证 | RPCS3 直接覆盖 `dev_hdd0/game/BLUS30405/USRDIR/` 下的散文件，截图确认字形 |
| 打包 | 照 `INFERNOPATCH0003` 的形式生成 Patch PKG；真机需 CFW/HEN |

## 已知难点

- **中文字库**：3000+ 字形要塞进原有贴图图集，还要扩展字符映射表，通常是整个工程最大的坑。
- **RefPack 重压**：`.ols` 头里的 block size / compressed size / uncompressed size 必须同步修正，否则游戏读不出来。社区汉化组多次卡在这一步。
- **指针表与控制码**：中文变多字节后长度与指针都要重算；`%s`、颜色码、换行、按钮图标等控制符一旦破坏就会崩溃。
- **预渲染 CG**：若过场视频带硬字幕，需要单独重压视频。
- **体积**：三个 VIV 共 8.4 GiB，所有「解包 → 替换 → 重打包」必须脚本化、增量式。分发时只发差异文件。
- **签名**：PS3 有完整性校验，未签名补丁在 OFW 上装不了。

## 合规声明

- 本项目基于**自有正版**做个人学习与自用研究，与版权方无任何关联。
- 本仓库**只分发原创脚本、配置、索引与翻译差异文本**；不分发原版资源、完整 VIV、ISO、EBOOT、PKG 或任何 DRM / 在线相关内容。`.gitignore` 已硬性排除这些类型。
- 请自行准备游戏本体，不要向本项目索取或提交游戏资源文件。
- 真机运行未签名补丁需要 CFW/HEN，请自行了解相关风险。
- 游戏名称、商标与内容版权归各自权利人所有。

## 参考与致谢

- 社区已有的民间本地化先例（2021 年俄语版、2026 年进行中的波兰语版讨论），其容器链路与踩坑记录是重要线索。
- 相关工具与格式资料：EA RefPack / PSA、EA BIG(`BIGH`) 归档、QuickBMS、Kruptar、010 Editor、RPCS3、Ghidra。

## 许可证

仓库中的原创脚本与文档尚未选定开源许可证，如需复用请先联系维护者。游戏资源与商标不适用任何本项目许可。
