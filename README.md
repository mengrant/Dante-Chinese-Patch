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
| **不等长文本 / 偏移表重算** | ✅ `patch_utf8_resize.py`：3294 条全文逐条比对 PASS，`SHDR 0x34` 同步修正 |
| **UTF-8 中文写入 + 双副本回读** | ✅ 已执行：`Start Game → 开始游戏`，逻辑数据 114908 → 114912，流 64829 / FILL 560 |
| **中文渲染目视验证** | ⛔ **缺字形**：主菜单显示 4 个金色占位方块（4 汉字各 1 个）；UTF-8 解码与不等长重排均正确，其余菜单完好 |
| **Latin-1 对照实验** | ✅ `Création` 完整显示、`é`(U+00E9) 正常 → UTF-8 解码与 Unicode→字形查表链路正常，**只缺 CJK 字形**，无需改解码或映射逻辑 |
| **美版 ISO 自带 CJK 文本残留** | ✅ 5 个语言副本均含 `日本語`(#2637) 与日文手柄提示(#1629)；`ll` 副本含 26 个汉字（`地獄`/`使徒`/`本性`…），说明文本与码点体系原生支持 CJK |
| **`日本語` 字形探针** | ⛔ **目视：3 个金色方块**（3 汉字各 1 个），连游戏自带日文串都渲染不出 → **图集确无 CJK 字形**，必须扩图集 |
| PSN 亚洲区 `NPHB00185` PKG | ⛔ 实测是 2009-12-17 **DEMO 试玩版**（`HP0006-NPHB00185_00-DANTEINFERNODEMO`，1.01 GiB / 9 条目），非韩文完整版，无可用字形资源 |
| **本机 HDD 官方 DLC/补丁资源** | ✅ `dev_hdd0/game/BLUS30405/USRDIR` 实存 595 文件 / 1.4 GiB（416 个 `.str`、17 处 `2HCL`），与 VIV 条目同为 `ols3` + `SHOC/SHDR` 容器 |
| **EA 字体资源格式定位** | ✅ `dia_core/arena_frontend.str` 明文含 `shared\fonts\arena\minion_pro_arena.tg4h/.tg4d`、`buttons_arena.tg4d`、`assets_shared_fonts_arena`、DXT5 → 字体是 `.tg4h/.tg4d` 纹理对 |
| VIV 内字体条目检索 | ⛔ `find_font_entries.py` 定点扫 5888 个条目头各 1 KiB，`shared\fonts` / `glyph` 强特征 **0 命中** → 主游戏字体不在 VIV 具名条目里 |
| **RPCS3 `cellFont` 假设** | 🔬 源码 `cellFontOpenFontset()` 把字体类型**硬编码**到 `dev_flash/data/font/*.TTF`，全部 `*_SET` 类型回退 `RD-R-LATIN.TTF`；8.2 MB 的 `DH-R-CGB.TTF`（20902 汉字）不在映射表 → 可解释「é 正常 / 汉字方块」 |
| 系统字体实验 | ⏳ `try_system_font.py` 已备好（`--check` / `--apply` / `--restore`，全量备份），**待用户确认后执行**，只需重启一次 RPCS3 |
| 中文字形图集 / 字体覆盖 | ❌ 唯一剩余关口；优先验证上一条系统字体假设，否则仍需定位图集并扩映射表 |
| Patch PKG 打包 | ❌ 未实现，照 `INFERNOPATCH0003` 形式做 |

> **验证注意**：源 ISO 是未解密的 PS3 光盘镜像，RPCS3 缺 region information / IRD，直接 Add Games 挂载会报 `Decryption failed` 并提示「没有内容可以添加」。请改用已在游戏列表登记的**文件夹格式**游戏，用 `patch_all_copies.py` 覆盖 VIV 条目后**完全退出游戏再重新启动**（不要重新扫描目录、不要新建目录），详见 `WORKLOG.md` 第 8、9 节。
>
> **同名副本陷阱**：BIGH 归档里 `.lh2` 会存多份内容相同的物理副本，同一句文本也可能有多个字符串 ID。只改一份一条时菜单仍显示原文，必须全量覆盖。

## 已知难点

- **RPCS3 侧可能根本不用改游戏（新假设，优先验证）**：本机固件 `dev_flash/data/font/` 有 29 个官方 TTF，`SCE-PS3-DH-R-CGB.TTF` 实测 cmap 覆盖 20902 个 CJK 汉字，且含 ASCII 与 Latin-1（「开始游戏日本語Création」全覆盖）。但 RPCS3 的 `cellFontOpenFontset()` 把 `fontType->type` **硬编码**映射到具体文件名，且全部 `*_SET` 类型因 "not supported yet" 统一回退到 `SCE-PS3-RD-R-LATIN.TTF`（38 KB，纯拉丁），CGB 字体从未被使用。若游戏走 `cellFont`，只需把 CGB 字体挂到它请求的那个文件名上，中文即可显示 —— **不用改 ISO/VIV、不用扩图集、不用改 BIGH TOC、也不用下载任何游戏**。`tools/try_system_font.py` 提供带完整备份的可回滚实验（会影响 RPCS3 全局字体，需确认后执行）。注意这是模拟器实现细节，真机补丁不能依赖它。
- **中文字形图集（唯一剩余关口）**：中文实验确认渲染成 4 个缺字形占位方块；但 `Création` 对照实验里 `é`(U+00E9) 显示正常，说明 UTF-8 解码与 Unicode→字形查表链路是通的，**不需要改解码层或映射逻辑，只需往图集加汉字字形并扩映射表**。资源普查：游戏无独立字体散文件；VIV 5888 个条目中 `shared\ui\apx\` 172 个是 UI 图标、`.vfb` 是特效、`.tg4h` 是角色/场景贴图，4786 个条目名解析为空；条目头 magic 主要是 `\x03...`（纹理类）与 `ols3`（SHOC），**没有 FONT / GLYPH / BMF / DDS 等显式字体容器**；EBOOT.BIN 中 `font`/`glyph`/`cellFont` 字符串均为 0（SELF 加密）；RPCS3 日志只记录 VIV 打开与 `TextureWorkerThread`，无字体资源名。因此字体图集大概率是 VIV 内的无名纹理条目或内嵌于 EBOOT，定位它需要 RSX 纹理捕获 / 动态调试，属于比文本替换高一整个量级的工作。
- **字形来源：不要随便借别的中文版游戏**：字形集是「图集位图 + 码点映射表 + 字宽/基线表」三件套，与引擎绑定；换游戏等于换一套私有格式，风格、尺寸、通道、压缩、字宽都不匹配，还要再逆向一次对方的格式，且有版权风险。本作 PS3 **没有官方中文版**：亚洲版（Death Edition）语音与字幕都是英文；网上流传的「中文版 / 完全汉化版」是 PSP 版或民间作品，资源格式与 PS3 不同。真正有价值的对照组只有**同款日版 `BLJM-60202`**（Best Hits `BLJM-60299`，CERO D，日文界面与字幕，同 Visceral Engine、同 BIGH/VIV、同 `.lh2` 结构）——diff 美版 vs 日版可直接定位字体图集与映射表，省掉 RSX 抓帧；但日文汉字不等于简体中文（「开 / 戏 / 游」等仍需补），且要重新解析一份约 5–6 GiB 的镜像。更可控的替代方案是用开源 CJK 字体（思源黑体 / Noto Sans CJK，SIL OFL）自行渲染字形位图，这也是主流汉化做法。
- **不等长文本（已解决）**：`.lh2` 字符串区实测为 3294 条连续 NUL 结尾 C 串，无空洞、无共享/子串指针，因此长度变化只需把所有后续偏移按累计 delta 平移。必须同步改的字段共 6 处：`full[0x04]` 逻辑总大小、`blob[0x34]` SHDR 解压后大小、偏移表 N 个 u32、`0x84` 块长、`0x8C` 流长、FILL 大小/位置。**等长替换不会暴露 `0x34`，这是最容易漏的一处。**
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
