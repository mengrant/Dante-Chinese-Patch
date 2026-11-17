# Dante-Chinese-Patch

> PS3《Dante's Inferno: Divine Edition》美版（`BLUS30405`）中文补丁 —— 逆向分析与工具工程

[![Python](https://img.shields.io/badge/python-3.x-blue)](#快速开始)
[![Stage](https://img.shields.io/badge/stage-extraction%20done-orange)](#当前状态)
[![Game assets](https://img.shields.io/badge/game%20assets-none-brightgreen)](#合规声明)

## 这个项目是什么

目标是让 PS3 美版《但丁的地狱：神圣版》显示中文：把游戏里的界面、菜单与字幕文本提取出来，翻译成可维护的文本表，再以补丁形式回填，并在模拟器里验证显示效果。

**本仓库不是补丁下载页，也不是游戏文件镜像。** 这里只放实现目标所需的原创脚本、格式分析结论、元数据索引与工作记录。任何 ISO、VIV、PKG、EBOOT、贴图、视频、种子文件以及**游戏文本原文**都不入库，也不会通过本仓库分发。

## 当前状态

> ⚠️ **文本提取链路已打通，但还没有可安装的汉化补丁。**

已完成：破解 `BIGH` 归档 TOC 的字段语义、用纯 Python 实现 EA RefPack 解压、定位到 `localization\inferno\*.lh2` 文本容器、解析出 ID 表与字符串偏移表，并导出 **9900 条英文文本表**（3 个文件，0 条偏移越界）。文本表只保存在本机 `extract/`，不入库。

尚未完成：RefPack **重压**、偏移量重算、中文字库、回填与 RPCS3 显示验证。这几步才是真正把中文塞进游戏的硬骨头。

想跟进细节请看 [`WORKLOG.md`](WORKLOG.md)（含实测数据、格式推导过程与决策记录）。

## 目标

| 阶段 | 目标 | 状态 |
|---|---|---|
| 1. 定位 | 解 ISO → 解 VIV → 找到文本容器，产出可复现的分析工具 | ✅ 完成 |
| 2. 提取 | RefPack 解压、解析 `.lh2` 的 ID/偏移表，导出 CSV/JSON 文本表 | ✅ 完成 |
| 3. 闭环 | 只改一处文本，跑通「重压 → 修偏移表 → 回填 → RPCS3 显示中文」 | 🔜 进行中 |
| 4. 翻译 | 批量翻译、术语统一、控制码与换行保护 | ⬜ 未开始 |
| 5. 交付 | 生成 Patch PKG / 差异补丁，模拟器与真机验收 | ⬜ 未开始 |

**明确不做**：不改 `EBOOT.BIN` 渲染代码（除非字库方案走不通）、不碰在线功能与 DRM、不提供任何游戏本体或完整资源包。

## 一个容易走弯路的概念：这不是 DLC

PS3 的 DLC 是「追加内容」，游戏不会拿它替换主程序里的文本。汉化的正确载体是 **Game Update / Patch PKG** 或**散文件覆盖**。

巧的是这张盘自带样板：`/UPDATE/` 下的官方补丁 content ID 为 `UP0006-BLUS30405_00-INFERNOPATCH0003`，自制补丁照这个形式落到 `dev_hdd0/game/BLUS30405/USRDIR/` 即可。同时 RPCS3 会优先读取该目录下的同名文件，所以开发期**不必每次重打包 9.47 GiB 的 ISO**，散文件覆盖就能验证（主 VIV 在 ISO 里，实际是否生效仍需实测）。

## 已确认的技术事实（均为实测，非推测）

| 项 | 结论 |
|---|---|
| 光盘 | 单个 ISO，10,167,930,880 字节 ≈ 9.47 GiB；`PARAM.SFO`：TITLE_ID `BLUS30405`、APP_VER `01.00`、CATEGORY `DG`、系统版本 3.15 |
| 主资源 | `PS3_GAME/USRDIR/BIGFILE0/1/2.VIV` = 2.87 / 2.63 / 2.95 GiB，magic 均为 `BIGH` |
| 归档结构 | 头 24 字节；TOC 从 `0x18` 起、每条 12 字节；`toc_size = 24 + 12 × 文件数`，三个 VIV 分别 4898 / 947 / 43 条 |
| TOC 字段 | **A = 递增哈希，B = 条目起始偏移（相对 VIV 文件起点），C = 物理长度**（= 相邻 B 之差）。BIGFILE1 抽样 24 个 B 有 19 个直接命中 `SHOC` 头，BIGFILE2 命中 46 次 `VP6` |
| 名字表 | **无集中文件名表**，内部路径以明文藏在条目自身头部（`*.tg4h`、`*.apx`、`*.lh2`…） |
| 压缩 | 条目多为 `SHOC` 容器，内部按约 64 KiB 分段用 **EA RefPack** 压缩，末段可能是 `SHOC/SDAT` 未压缩文本 |
| 文本容器 | `localization\inferno\{inferno_poem,inferno_global,inferno_dialog}.{en,ll,fr,es,ss}.lh2`，共 20 个条目（含重复） |
| `.lh2` 结构 | `2HCL` 头 → N 条 u32be ID 表 → N 条 u32be 字符串偏移表 → 连续 NUL 结尾 C 字符串 |
| 视频 | `BIGFILE2` 仅 43 条，为 VP6 过场视频，可排除文本在此 |

BIGH 头部布局：

```
0x00  magic  "BIGH"                  (4B, BE)
0x04  u32be  field4                  (含义待定)
0x08  u32be  num_files
0x0C  u32be  toc_size = 24 + 12*N
0x18  TOC    N 条 × 12B，每条 3 个 u32be (A, B, C)
toc_size     数据区开始
```

`.lh2` 容器布局（以 `inferno_poem.en.lh2` 为例，N=4754）：

```
0x00  "2HCL"       magic
0x04  u32be        total = 246096
0x10  u32be        N = 4754
0x20  ID 表        N × u32be
0x4A68  偏移表     N × u32be（0x20 + 4N）
0x94B0  字符串区   连续 NUL 结尾 C 字符串
```

## 仓库内容

```
.
├── README.md                    # 本文件
├── WORKLOG.md                   # 实测数据、格式推导、决策与待办（已脱敏）
├── config.json                  # 可提交的配置模板，路径为 <...> 占位符
├── config.local.json            # 本机实际路径（本地文件，不入库）
├── .gitignore                   # 排除游戏资源、文本原文、本机配置与构建产物
├── push-to-github.bat           # Windows 下一键推送（首次使用会弹 GitHub 登录）
├── tools/
│   ├── common.py                # 公共配置加载，所有脚本从这里取路径
│   ├── refpack.py               # EA RefPack/PSA 解压器 + 自测
│   ├── iso_probe.py             # ISO9660 目录树、PARAM.SFO、大文件 magic
│   ├── viv_probe.py             # VIV 头部/TOC 明文串、光盘内置 PKG content ID
│   ├── viv_dump.py              # 十六进制 dump VIV 头部
│   ├── viv_toc_probe.py         # 验证 toc_size 公式
│   ├── viv_index.py             # 全量 TOC 索引 → report/viv_index.json
│   ├── toc_semantics.py         # 校验 TOC 三个字段的语义
│   ├── viv_extract.py           # 按 B/C 切分条目、探测内部 RefPack 块 → manifest
│   ├── text_scan.py             # 8 MiB 块顺序扫描数据区 → 热点统计
│   ├── text_probe.py            # 候选条目解压 + 字符串提取，定位文本容器
│   ├── lh2_dump.py              # .lh2 结构诊断，解压块写到 extract/
│   └── lh2_export.py            # 解析 .lh2 → 可翻译 CSV/JSON 文本表
├── report/                      # 只含不含原文的元数据
│   ├── viv_index.json           # 5888 条 TOC 记录索引
│   ├── toc_semantics.json       # 字段语义打分结果
│   ├── viv_manifest.json        # 5888 个条目的偏移/长度/标签清单
│   ├── lh2_summary.json         # .lh2 结构摘要（条数、偏移表位置，无原文）
│   └── text_hotspots.json       # 数据区关键字命中统计
└── extract/                     # 【不入库】解压产物与游戏文本原文
    ├── text_table_<lang>.csv    # 列：file,index,id_hex,offset,source,translation,raw_hex
    └── text_table_<lang>.json   # 含 raw_hex，保证可无损回填
```

**所有脚本都是只读的**：不写回 ISO、不删除文件、不修改任何游戏数据；输出只落在 `report/`（元数据）与 `extract/`（原文数据，不入库）。脚本通过 `tools/common.py` 读路径，仓库里不含任何本机绝对路径。

## 快速开始

需要：**Python 3.x**（脚本只用标准库）、一份**自己拥有的正版 ISO**、以及（可选的）**RPCS3** 用于验证。不需要安装 QuickBMS 或 010 Editor。

```bash
# 1. 克隆
git clone https://github.com/mengrant/Dante-Chinese-Patch.git
cd Dante-Chinese-Patch

# 2. 复制配置模板为本机配置，填入 ISO 路径（该文件不会提交）
cp config.json config.local.json
#    编辑 config.local.json，把 "<ISO_PATH>" 改成你本机的 ISO 绝对路径

# 3. 自测解压器
py -3 tools/refpack.py

# 4. 依次跑分析链（前两步较慢，会顺序读约 8.4 GiB）
py -3 tools/viv_index.py          # 建 TOC 索引
py -3 tools/toc_semantics.py      # 校验字段语义
py -3 tools/viv_extract.py --scan # 5888 个条目建 manifest
py -3 tools/text_probe.py --arc BIGFILE0.VIV --limit 70   # 定位文本容器
py -3 tools/lh2_export.py --lang en                        # 导出英文文本表
```

Windows 用 `py -3`，其他平台换成 `python3`；路径分隔符需自行调整（脚本目前面向 Windows）。`--lang` 还支持 `ll / fr / es / ss`。

## 工具链现状

| 环节 | 状态 |
|---|---|
| 解 ISO / 解 VIV / 切分条目 | ✅ 纯 Python，已实现 |
| EA RefPack **解压** | ✅ 纯 Python，含 4 个自测用例 |
| `.lh2` ID 表 / 偏移表 / 文本表导出 | ✅ 已实现，CSV 带 `translation` 空列与 `raw_hex` |
| EA RefPack **重压** | ✅ `refpack_encode.py`，7 项自测通过 |
| SHOC 块长 / 流长 / FILL 同步修正 | ✅ `lh2_rebuild.py`，条目总长不变，无需动 TOC |
| 单条文本等长替换 + 回填 | ✅ 文件层闭环 PASS（`Start Game → HANHUA OK!`） |
| 散文件覆盖到文件夹格式游戏 | ✅ `apply_folder_patch.py`（单副本）/ `patch_all_copies.py`（全副本，推荐） |
| 同名多副本 + 多 ID 全量覆盖 | ✅ 2 份副本 × #263/#1162 均已回读校验，旧串 0 残留 |
| **RPCS3 端到端目视验证** | ✅ **PASS**：重启游戏后主菜单第一项显示 `HANHUA OK!`（截图确认） |
| 本地化文本编码 | ✅ 实测为 **UTF-8**（法/西语重音字母、`©`、`¡`），中文可直接按 UTF-8 写入，无需改编码层 |
| 中文字形图集 / 字体覆盖 | ❌ 未实现（编码已通，剩字形与渲染，仍是最大难点） |
| 不等长文本 / 偏移表重算 | ❌ 未实现（UTF-8 中文必然不等长，是汉化前置） |
| Patch PKG 打包 | ❌ 未实现，照 `INFERNOPATCH0003` 形式做 |

> **验证注意**：源 ISO 是未解密的 PS3 光盘镜像，RPCS3 缺 region information / IRD，直接 Add Games 挂载会报 `Decryption failed` 并提示「没有内容可以添加」。请改用已在游戏列表登记的**文件夹格式**游戏，用 `patch_all_copies.py` 覆盖 VIV 条目后**完全退出游戏再重新启动**（不要重新扫描目录、不要新建目录），详见 `WORKLOG.md` 第 8、9 节。
>
> **同名副本陷阱**：BIGH 归档里 `.lh2` 会存多份内容相同的物理副本，同一句文本也可能有多个字符串 ID。只改一份一条时菜单仍显示原文，必须全量覆盖。

## 已知难点

- **中文字形图集**：编码层已确认是 UTF-8，不需要改动；但美版字体贴图只含拉丁字形，3000+ 汉字要塞进原有图集并扩展字符映射/字宽表，仍是整个工程最大的坑。**下一步最小实验：把 `HANHUA OK!` 换成 UTF-8 中文，直接看渲染成汉字还是豆腐块**，一次就能定性。
- **不等长文本 + 偏移表重算**：`.lh2` 的字符串区是连续 NUL 结尾 C 串，改动长度会推移后续所有偏移；`0x04` 逻辑总大小、`0x84`/`0x8C` 段长、FILL、尾段补齐都要同步重算。UTF-8 中文必然不等长，这是汉化的硬前置。
- **RefPack 重压**：条目物理长度固定（65536 B），重压后的流必须能塞回原块；超出时需要改 BIGH TOC 的 span 并重排归档。目前等长替换已验证可用。
- **控制码**：`\xNN` 形式的颜色码、换行、按钮图标、格式化占位符必须原样保留；导出器用 `readable()` 转义并保留 `raw_hex` 以便无损回填。
- **预渲染 CG**：若过场视频带硬字幕，需要单独重压视频。
- **体积**：三个 VIV 共 8.4 GiB，所有「解包 → 替换 → 重打包」必须脚本化、增量式。分发时只发差异文件。
- **签名**：PS3 有完整性校验，未签名补丁在 OFW 上装不了。

## 合规声明

- 本项目基于**自有正版**做个人学习与自用研究，与版权方无任何关联。
- 本仓库**只分发原创脚本、配置、不含原文的元数据索引与翻译差异文本**；不分发原版资源、完整 VIV、ISO、EBOOT、PKG、游戏文本原文或任何 DRM / 在线相关内容。`extract/` 与含原文的报告已被 `.gitignore` 硬性排除。
- 仓库为 public，工作记录与配置模板均已脱敏，不含本机绝对路径、代理地址等环境细节。
- 请自行准备游戏本体，不要向本项目索取或提交游戏资源文件。
- 真机运行未签名补丁需要 CFW/HEN，请自行了解相关风险。
- 游戏名称、商标与内容版权归各自权利人所有。

## 参考与致谢

- 社区已有的民间本地化先例（2021 年俄语版、2026 年进行中的波兰语版讨论），其容器链路与踩坑记录是重要线索。
- RefPack 规范：NO$FUN「CDROM File Compression EA Methods (LZSS RefPack)」解压伪代码、SSX Modding Wiki「Formats/Common:Refpack」ImHex 结构定义。
- 相关工具与格式资料：EA BIG(`BIGH`) 归档、QuickBMS、Kruptar、010 Editor、RPCS3、Ghidra。

## 许可证

仓库中的原创脚本与文档尚未选定开源许可证，如需复用请先联系维护者。游戏资源与商标不适用任何本项目许可。
