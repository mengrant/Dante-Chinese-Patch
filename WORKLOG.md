# Dante's Inferno (PS3, BLUS30405) 汉化补丁 — 工作记录

> 仅记录逆向分析与工具开发过程。仓库**不包含**任何游戏资源（ISO / VIV / PKG / EBOOT / 贴图 / 视频 / 文本原文）。
>
> 本文件已脱敏：本机路径一律用占位符表示。实际路径写在 `config.local.json`（不入库），占位符含义见 `config.json` 模板。

## 0. 项目目标

基于美版 `Dante's Inferno Divine Edition [BLUS30405]` 制作个人学习用的中文补丁。
载体应为 **Game Update / Patch PKG** 或散文件覆盖，而不是 DLC（DLC 是追加内容，游戏不会用它替换主程序文本）。

## 1. 环境与素材

| 项 | 值 |
|---|---|
| ISO | `<ISO_PATH>` |
| ISO 大小 | 10,167,930,880 字节 ≈ 9.47 GiB（已完整下载） |
| PARAM.SFO | TITLE_ID `BLUS30405`、APP_VER `01.00`、CATEGORY `DG`、PS3_SYSTEM_VER `3.15` |
| RPCS3 | `<RPCS3_ROOT>`（已安装；`dev_hdd0/game/BLUS30405/USRDIR` 已有补丁/DLC 数据目录） |
| 会话工作区 | `<ISO_DIR>`（保持不变） |
| 工程输出目录 | `<PROJECT_ROOT>`（extract / build / patch / report） |
| 磁盘 | ISO 所在盘约 10 GB 可用（放不下解包产物）；工程盘约 35 GB 可用，且与 RPCS3 同盘 |

下载阶段的坑（已解决）：网络出口对 archive.org 的大文件传输「单连接约存活 2 秒」限流，浏览器长连接被掐断后不会自动续传，于是表现为「下一会就卡住」。最终用 16 MiB 分块 + 块内流式续传 + 断点记录完成下载。系统代理 `<SYSTEM_PROXY>` 可访问 archive.org；工具沙箱注入的另一条代理会返回 502。

## 2. 已完成的分析（全部只读，未改动 ISO）

### 2.1 ISO 层

- `PS3_GAME/USRDIR/`：`BIGFILE0.VIV` 2,873,888,768 B、`BIGFILE1.VIV` 2,625,208,320 B、`BIGFILE2.VIV` 2,951,903,316 B、`EBOOT.BIN` 约 20 MB、`EALOGO.VP6`。
- `/UPDATE/` 下自带 6 个官方 PKG，content ID 均为 `UP0006-BLUS30405_00-*`，其中 `UP0006-BLUS30405_00-INFERNOPATCH0003` 即官方补丁，可作为自制补丁 PKG 的形式样板。

### 2.2 EA BIGH 归档层

三个 VIV 的头部结构已确认：

```
offset 0x00  magic  "BIGH"                 (4 bytes, BE)
offset 0x04  u32be  field4                 (含义待定，疑似校验/版本)
offset 0x08  u32be  num_files
offset 0x0C  u32be  toc_size = 24 + 12 * num_files
offset 0x18  TOC: num_files 条 × 12 bytes，每条 3 个 u32be (A, B, C)
offset toc_size  数据区开始（无集中文件名表）
```

| 归档 | 文件数 | toc_size | 24+12×N |
|---|---|---|---|
| BIGFILE0.VIV | 4898 | 58800 | 58800 ✔ |
| BIGFILE1.VIV | 947 | 11388 | 11388 ✔ |
| BIGFILE2.VIV | 43 | 540 | 540 ✔ |

- TOC 记录按 **A 字段严格递增**排列 → A 极可能是排序用的文件名哈希，而不是偏移；B / C 中一个是偏移、一个是长度（字段语义由 `toc_semantics.py` 校验）。
- TOC 之后**直接是文件数据**，没有集中名字表；内部路径以明文保存在各条目自身头部，例如：
  - `chars\_erosion_shared\absolve_transition_01_c.tg4h` / `.tg4d`
  - `shared\ui\apx\upgr_castus_erupto_lvl2_ps3.apx`
  - `levels\levels\inferno\...\igc_04_030.smb`
  - `chars\summoner\cct\export\summoner_core.bnk.ps3`
- BIGFILE0 数据区前段有**未压缩的 Lua 配置脚本**（如 `manager:AddNewChain("hero.scythe_light_run_01")`、`dNumericOp("add","SCOR...")`）。
- BIGFILE2 只有 43 条，数据区是 VP6 视频（`MVhd` / `vp60`），基本可排除文本在此。

### 2.3 全盘文本热点扫描

对三个 VIV 的整个数据区（约 8.4 GiB）做 8 MiB 顺序块扫描，统计可打印字符密度、英文单词特征与关键字：

- 命中大量 `SHOC`（EA 容器）、`Rpak`（RefPack 压缩标记）、`font`、`.lua`、`.ols` / `.lh2` 字样；
- 明文可见的几乎都是**资源路径**，而不是对话/UI 句子；
- BIGFILE2 的命中多为压缩数据里的随机 ASCII 误命中（无语义）。

结论：与社区情报一致 —— **文本在 `.ols` 容器内、经 EA RefPack 压缩的 `.lh2` 中**，明文扫描看不到，必须走「解 VIV → 解 RefPack → 解析带指针表的二进制」这条路。

## 3. 已产出的工具（tools/）

| 脚本 | 作用 |
|---|---|
| `common.py` | 公共配置加载（模板 + 本机覆盖），所有脚本从这里取路径 |
| `iso_probe.py` | 解析 ISO9660 目录树、PARAM.SFO、列出大文件及 magic |
| `viv_probe.py` | 扫 VIV 头部 / TOC 明文串、列出光盘内置 PKG 的 content ID |
| `viv_dump.py` | 十六进制 dump VIV 头部，用于确定 TOC 布局 |
| `viv_toc_probe.py` | 验证 `toc_size = 24 + 12×N` 假设、查看 TOC 后的数据 |
| `viv_index.py` | 建立全量条目索引 → `report/viv_index.json`（5888 条记录，557 KB） |
| `text_scan.py` | 8 MiB 块顺序扫描数据区 → `report/text_hotspots.json` |

全部为**只读**脚本（除输出报告文件外），不写回 ISO，不删除文件。

## 4. 关键决策 / 捷径

1. **开发主环境用 RPCS3**，真机只做最终验收。RPCS3 优先加载 `dev_hdd0/game/<TITLE_ID>/USRDIR/` 下的同名文件，因此改好的散文件可直接覆盖验证，**不必每次重打包 9 GB ISO**。
2. 光盘自带的 `UP0006-BLUS30405_00-INFERNOPATCH0003` 是补丁形态的样板；成品可做成 Patch PKG，落到 `dev_hdd0/game/BLUS30405/USRDIR/`。
3. 先做**最小闭环验证**：只把一处文本改成中文，跑通「改 `.lh2` → RefPack 重压 → 修 `.ols` 头 → 组回 VIV/散文件覆盖 → RPCS3 运行」，看到中文后再谈批量翻译。
4. 该作有民间汉化先例（2021 俄语版、2026 波兰语版进行中），优先复用其 BMS 脚本与 `.lh2` 工具线索，避免从零逆向。
5. 三个 VIV 共 8.4 GiB，所有「解包—替换—重打包」必须脚本化、增量式，禁止手工改大文件。

## 5. 待办

- [x] 确定 TOC 三个字段的准确语义（偏移 / 长度 / 哈希），写出 `viv_extract.py`
- [x] 实现 EA RefPack 解压，抽出 `.lh2` 文本容器
- [x] 解析 `.lh2` 的 ID 表 / 偏移表，导出可翻译的 CSV/JSON 文本表
- [ ] 实现 RefPack **重压**并写回（当前只有解压）
- [ ] 定位字体贴图（`.tg4h/.tg4d`）与字符映射表，评估中文字库方案
- [ ] 最小闭环：单条文本汉化 + 回填 + RPCS3 截图验证
- [ ] 批量翻译、指针重算、控制码保护
- [ ] 生成 Patch PKG / 差异补丁；真机 CFW/HEN 验收

## 6. 边界

- 基于自有正版做个人学习 / 自用。
- 仓库与补丁只分发**自己写的脚本、配置、索引和翻译差异文本**；不分发原版资源、完整 VIV、ISO、EBOOT、游戏文本原文或任何 DRM / 在线相关内容。
- 提取出的文本表（CSV/JSON）与解压产物一律写到 `extract/`，该目录已被 `.gitignore` 排除；`report/` 里只放不含原文的结构元数据。
- 仓库为 public，所有本机绝对路径、代理地址均已脱敏；本机实际路径只存在 `config.local.json`（`.gitignore` 排除）。
- 仓库级 `http.sslverify=true`（覆盖全局的 false）。
- 真机运行未签名补丁需要 CFW/HEN，OFW 无法安装。

## 7. 追加：TOC 破解、RefPack 解压与文本表导出（同日）

### 7.1 脱敏与工程化

- 新增 `tools/common.py`：优先用 `config.local.json`（本机路径，不入库）覆盖 `config.json` 模板（`<...>` 占位符）；6 个旧脚本不再硬编码 ISO 路径；`viv_index.py` 只把 ISO 文件名写入报告。
- `WORKLOG.md` / `config.json` / `push-to-github.bat` 全部脱敏；`.gitignore` 追加 `config.local.json`、`/extract/`、`/build/`、`/patch/` 及含原文的报告。
- 仓库级 `git config --local http.sslverify true` 已生效。

### 7.2 BIGH TOC 字段语义（已定论）

`toc_semantics.py` 对 (偏移字段, 长度字段, 偏移基准) 组合打分，结论：

| 字段 | 语义 |
|---|---|
| A | 严格递增的哈希 / 排序键 |
| B | **条目起始偏移**，相对 VIV 文件起点（含 24B 头 + TOC） |
| C | **条目物理长度**，且等于按 B 排序后相邻 B 的差值 |

证据：BIGFILE1 抽样 24 个 B 偏移有 19 个直接命中 `SHOC` 数据头；BIGFILE2 命中 46 次 `VP6`；小样本里 `c == next_b - b` 逐条吻合。BIGFILE0 曾出现「C 作偏移、数据区起点为基准」的高可打印率假象，实为小偏移全落在前段未压缩 Lua 区，无容器特征，已排除。

### 7.3 EA RefPack（PSA）解压

按 NO$FUN 伪代码与 SSX Modding Wiki 的 ImHex 结构实现 `tools/refpack.py`（纯标准库），含 4 个自测用例全部通过。命令格式：`0x00-0x7F / 0x80-0xBF / 0xC0-0xDF / 0xE0-0xFB / 0xFC-0xFF(stop)`，头部常见 `10 FB` + 3 字节 u24be 解压后大小。

### 7.4 文本容器定位（决定性进展）

全量 `viv_extract.py --scan`（5888 条）后，BIGFILE0 里发现**明文条目名直接就是本地化文件**：

```
localization\inferno\inferno_poem.en.lh2     b=2568800256  span=196608
localization\inferno\inferno_global.en.lh2   b=2569586688  span=65536
localization\inferno\inferno_dialog.en.lh2   b=2569914368  span=65536
```

语言后缀共 5 种：`en / ll / fr / es / ss`；部分文件在盘里存了两份（已按名去重）。`poem` 解出《神曲》公版译本英文诗句，`global` 含 UI/制作人员名单，`dialog` 含对话。

**VIV 条目是 SHOC 容器**，内部逻辑数据按约 64 KiB 分段：多数段是 RefPack 压缩块（第一块带 `2HCL` 头），末尾可能有一段 `SHOC + SDAT` 的**未压缩**文本；按块顺序拼接并补齐尾段，长度才等于头部声明的 `total`。poem 的 246096 = 232291（2 个压缩块）+ 13805（尾段）。

**`.lh2` 容器结构**（实测）：

```
0x00  "2HCL" magic
0x04  u32be 逻辑总大小 total
0x10  u32be 条目数 N
0x20  ID 表     N × u32be（分组递增的字符串 ID）
0x20+4N  偏移表 N × u32be，指向字符串区内各串起点
之后  字符串区  连续 NUL 结尾的 C 字符串（含控制码）
```

poem: N=4754, 偏移表在 0x4A68, 第一个字符串偏移 0x94B0 = 38064（`（首句英文示例省略）`）。

### 7.5 产出

`tools/lh2_export.py --lang en` 导出 3 个文件、**9900 条字符串、0 条偏移越界**：

| 文件 | 条数 | total | 偏移表 |
|---|---|---|---|
| inferno_poem.en.lh2 | 4754 | 246096 | 0x4A68 |
| inferno_global.en.lh2 | 3294 | 114908 | 0x3398 |
| inferno_dialog.en.lh2 | 1852 | 115281 | 0x1D10 |

CSV 列：`file, index, id_hex, offset, source, translation, raw_hex`；控制码转义为 `\xNN`，并保留 `raw_hex` 保证可无损回填。**含原文的文件只写 `extract/`，不入库**；`report/lh2_summary.json` 只含结构元数据。

### 7.6 下一步的真实卡点

1. **RefPack 重压**：目前只有解压。回填需要自己实现 PSA 压缩器，或做「只改等长字节」的最小验证（中文 UTF-8 三字节通常比英文长，等长改不了）。
2. **偏移表要重算**：任何长度变化都要重写 N 个 u32 偏移，并同步修 `.lh2` 头与 SHOC/`.ols` 头的大小字段（社区汉化组主要卡点）。
3. **字库**：仍需定位 `.tg4h/.tg4d` 与字符映射表，确认引擎能否显示中文。
4. **RPCS3 验证**：改好的散文件可覆盖 `dev_hdd0/game/BLUS30405/USRDIR/`，但主 VIV 在 ISO 里，散文件覆盖是否对 VIV 内条目生效需实测；否则要做增量重打包。

## 8. 追加：RefPack 重压闭环、ISO 挂载失败与散文件验证路径（同日）

### 8.1 已完成（修正第 5、7.6 节的待办状态）

- `tools/refpack_encode.py`：纯标准库 LZSS 编码器，7 项自测通过。修复了命令 3 长度高位权重（`lm>>8`）、纯字面命令上限（112 字节）、短远匹配不可编码三处问题。
- `tools/lh2_rebuild.py`：重压整个逻辑数据，同步修正 `0x84` 块长、`0x8C` 流长与 `FILL` 值；条目总长不变，因此 VIV 条目长度、TOC、`.lh2` 偏移表都不用动。闭环验证从磁盘重新解压后逻辑数据逐字节一致。
- 已生成 `Dante-Hanhua-Test.iso`（完整 10,167,930,880 字节），仅改写 65536 字节的条目块，实际变动 39894 字节；新流 63538→64821，FILL 1852→568。
- 最小闭环目前是**等长单字节替换**：`Start Game` → `HANHUA OK!`。中文显示仍需扩字体图集与字符映射，属下一阶段。

### 8.2 关键坑：测试 ISO 在 RPCS3 里挂不上

在 RPCS3 里 Add Games 选择测试 ISO 所在目录，弹出「没有内容可以添加！未能找到任何新的软件。」，`<RPCS3_ROOT>/log/RPCS3.log` 给出根因：

```
ISO: init: Failed to read region information (region_count=0): '<TEST_ISO>'
ISO: iso_archive: Corrupt ISO file '<TEST_ISO>': Decryption failed
SYS: Failed to load ISO.
```

- 这是**源镜像本身**的问题：该 ISO 是未解密的 PS3 光盘镜像，RPCS3 缺 region information / IRD，无法直接挂载，**与补丁无关**。
- 证据：测试 ISO 与原 ISO 的 sector 0、前 64 KiB、PVD(sector 16)、末尾 64 KiB、最后一个扇区逐字节完全一致；全盘唯一差异就是打了补丁的 65536 字节块。
- 结论：不要把「Add Games 挂 ISO」当作验证手段；改用本机已有的**文件夹格式**（已解包、已登记在游戏列表）游戏。

### 8.3 验证路径改为散文件覆盖

实测文件夹格式游戏的 `PS3_GAME/USRDIR/BIGFILE0.VIV` 在内部偏移 `0x9928C800`（= ISO `0xA956C000` − VIV 起点 `0x102DF800`）处的 65536 字节条目，与原 ISO 对应块**逐字节一致**。因此：

- 新增 `tools/apply_folder_patch.py`：只覆盖这一个定长条目块，不改文件长度 / TOC / 任何其他文件。
- 写前校验目标块必须与原 ISO 一致；首次写入前备份到 `patch/folder_original_entry.bin`；`--restore` 可一键还原；`--check` 只检查不写盘。
- 写后回读并从磁盘重新解压 `.lh2`，确认 #263 为 `HANHUA OK!`；已执行且 **PASS**。
- 配置项 `rpcs3_disc_dir`（模板里是占位符，实际值只在本机 `config.local.json`）。

**下一步（待用户目视验证）**：重启 RPCS3，直接在游戏列表里启动已登记的 BLUS30405（不要 Add Games），进入主菜单看 `Start Game` 是否变成 `HANHUA OK!`。若没变化或加载异常，优先排查 `SHOC/SHDR` 段是否含资源校验，以及 `dev_hdd0/game/BLUS30405/USRDIR` 的补丁数据是否覆盖了同名资源。

### 8.4 附带结论

- 分发/验证首选散文件覆盖或 Patch PKG，重打包 ISO 既慢又受解密限制。
- 测试 ISO 占约 9.47 GiB，验证完成后可删除以释放空间（保留原 ISO 与 `patch/` 即可复现）。
