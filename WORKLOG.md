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

## 9. 追加：首次目视验证失败的原因与全副本补丁（同日）

用户询问「是直接改了现有目录里的文件，还是要重新加载编译过的游戏目录」，并给出主菜单截图：仍显示 `Start Game`。

**答复**：改的是现有文件夹格式游戏目录里的 `PS3_GAME/USRDIR/BIGFILE0.VIV` 原地字节，不存在新编译目录，也不需要 Add Games / 重新扫描；但游戏必须**完全退出后重新启动**，因为文本在启动时已读入内存。

### 9.1 真正的两个漏改点

| 漏改 | 实测 |
|---|---|
| **同一 .lh2 有多份物理副本** | `inferno_global.en.lh2` 在 BIGFILE0 里有 2 条 TOC 记录：`b=0x9928C800`（A=785379597）与 `b=0xAB3A2000`（A=3736185383），条目头内部路径同名，原块逐字节一致。上一轮只改了第一份。 |
| **同一句文本有多个 ID** | `.lh2` 里 `Start Game` 出现 2 次：#263（off 34240）与 #1162（off 56905）。UI 按字符串 ID 引用，上一轮只改了 #263。 |

游戏按 TOC 的 A 哈希查表，命中哪份副本不确定；主菜单用的也可能是 #1162。因此只改一份一条时，截图仍是原文。

排查范围确认：BIGFILE0 共 20 个 `.lh2` 条目（5 语言 × 多份副本），只有 2 个 `inferno_global.en.lh2` 含 `Start Game`；光盘 USRDIR 下所有非 VIV 文件（含 EBOOT.BIN）`Start Game` 明文命中 0；`dev_hdd0/game/BLUS30405/USRDIR` 当时已不存在，无散文件覆盖。菜单其余项（`Load Game` #1980、`Movies` #1954、`Special Features` #3233、`Downloadable Content` #184/#2410、`Options` 多处、`Select` #128）都在同一个 `inferno_global.en.lh2`，文本源判断正确。RPCS3 日志也证实 `/dev_bdvd` 挂载的正是该文件夹目录。

### 9.2 新增 `tools/patch_all_copies.py`

- 从 manifest 找出**全部同名副本**，以 ISO 原块为唯一基准（不依赖当前磁盘状态），校验各副本一致；
- 把 `.lh2` 里**所有精确匹配**的条目一次性等长替换，重压整个逻辑数据，同步修 `0x84` / `0x8C` / FILL；
- 写回每一个副本，逐个从磁盘回读重新解压，确认新串条目齐全、旧串 0 残留；
- 首次备份原块到 `patch/all_copies_original.bin`；`--check` 只检查、`--restore` 一次还原全部副本；写前若目标块既非原版也非本补丁就拒绝写入。
- 已执行：`Start Game` → `HANHUA OK!`，命中 #263 与 #1162，流 63538 → 64817，FILL 572；2 个副本回读均 PASS、`旧串残留=[]`。

**经验**：EA BIGH 归档允许同名文件多副本，做差异补丁必须按「所有副本 + 所有同文本 ID」全量覆盖，不能假设 TOC 唯一。这条同样适用于后续批量翻译。

**下一步**：用户完全退出游戏后重新启动已登记的 BLUS30405，主菜单应显示 `HANHUA OK!`。若仍无变化，再改整个主菜单多项做强信号验证，并排查 SHOC/SHDR 段是否有资源校验。

> 注意：`apply_folder_patch.py` 是单副本单条目的早期工具，只覆盖第一份副本；多副本场景统一用 `patch_all_copies.py`，还原也以它的 `--restore` 为准。

## 10. 闭环达成：RPCS3 目视验证 PASS + 文本编码确认为 UTF-8（同日）

用户重启游戏后的主菜单截图：第一项显示 **`HANHUA OK!`**，字体、金色高亮态、排版与其余菜单项完全一致，其余项（`Load Game`、`Downloadable Content`、`Movies`、`Special Features`、`Options`、`Trials of St. Lucia [Coming Soon]`、`Select`）保持原样。

### 10.1 这意味着整条链路已验证

BIGH TOC 定位 → RefPack 解压 → `.lh2` 表解析 → 等长替换 → RefPack 重压 → `0x84`/`0x8C`/FILL 修正 → 多副本 + 多 ID 全量覆盖 → 文件夹格式游戏原地写入 → **RPCS3 运行时读取并渲染**。到此为止不再是「文件层验证」，而是游戏内实际生效。

顺带确认：条目物理长度不变、TOC 不动也能生效，说明 `SHOC/SHDR` 段没有对该条目做额外哈希校验（至少不影响加载）。

### 10.2 关键发现：本地化串是 UTF-8

排查其他语言副本时直接读原始 C 串字节：

| 语言 | 条目 | 原始字节 |
|---|---|---|
| fr | #2 `Création de compte` | `43 72 c3 a9 74 69 6f 6e ...` |
| fr | #8 `Producteur exécutif` | `... 65 78 c3 a9 63 75 74 69 66 ...` |
| es | #16 `¡Deberías comprar esta magia!` | `c2 a1 44 65 62 65 72 c3 ad ...` |
| en | #73 `© 2009 Electronic Arts Inc.` | `c2 a9 20 32 30 30 39 ...` |

`c3 a9` = é、`c2 a1` = ¡、`c2 a9` = ©，标准 UTF-8。**结论：编码层无需改造，中文可直接以 UTF-8 写入 `.lh2`。** 此前担心的「要改字符编码 / 造映射表」被排除，剩下的问题收敛为两点：字形图集是否含汉字、以及不等长文本的重排。

### 10.3 导出器修正

`tools/lh2_export.py` 的 `readable()` 原先把所有 `>=0x80` 的字节一律转成 `\xNN`，导致法/西语译文在 CSV 里全是转义、中文也无法直接查找回填。已改为 `raw.decode("utf-8", errors="surrogateescape")`：合法 UTF-8 多字节字符原样保留，非法字节仍转义为 `\xNN`，`raw_hex` 字段始终保留原始字节保证无损还原。自测 5 项通过（ASCII / 法语 / 西语 / 中文 / 控制码+非法字节）。

### 10.4 下一步的最小实验

把 `HANHUA OK!` 换成 UTF-8 中文（如 `开始游戏`，12 B > 原 10 B），需要顺带实现不等长重排：字符串区后续偏移全部推移、`0x04` 逻辑总大小、`0x84`/`0x8C`、FILL、尾段补齐同步重算，并确保重压流仍 ≤ 65536 B 的原条目容量。一次实验就能同时回答「汉字能否显示」和「不等长回填是否可行」两个问题。若渲染成豆腐块，则必须扩字体图集 / 字符映射，那是下一阶段主体工作。

## 11. UTF-8 中文不等长重排：工具实现与写入（同日，已执行，待目视）

用户选择「做中文最小实验」，本轮实现并落地 `tools/patch_utf8_resize.py`。

### 11.1 结构实测（决定方案可行）

以 ISO 原块为基准解析 `inferno_global.en.lh2`：

| 项 | 值 |
|---|---|
| 逻辑数据 / `full[0x04]` / `blob[0x34]` | 114908 / 114908 / 114908（三者相等） |
| 偏移表 / 字符串区起点 | `0x3398` / `0x6710`（26384） |
| N / 唯一偏移 | 3294 / 3294（**无共享指针**） |
| 字符串区连续性 | 0 处空洞，末串结束于 114907，正好填满 |
| 子串指针 | 0 |
| 头部其他长度 | `0x84`=63556（块长）、`0x8C`=63538（流长）、`0x10`=116（第一块头长，不变） |

因为字符串区完全线性，长度变化只需按「累计 delta」平移后续偏移，不需要重排或处理共享串。

### 11.2 必须同步修改的 6 处

1. `full[0x04]`：`.lh2` 头声明的逻辑总大小（在压缩数据内）
2. `blob[0x34]`：**SHDR 里的「解压后总大小」** —— 等长替换时值不变，旧工具从未动过；不等长时漏改会让游戏按旧长度读截断，这是本次最容易踩的坑
3. 偏移表 3294 个 u32be：`q → q + Σ(len(new)-len(old)) for all edits with p < q`
4. `blob[0x84]` 块长 = `16 + 新流长 + pad`
5. `blob[0x8C]` RefPack 流长
6. `FILL` 位置与 u16 大小（条目物理长度仍固定 65536 B，**TOC 不用动**）

### 11.3 实现与自测

`resize_logical()` 做重排并对 **3294 条文本全量逐条比对**（偏移表错一处就会大面积错位，这是最强的自检）；`rebuild_entry()` 重压后重新解压，再验一次文本表与 SHDR 字段自洽。安全约束沿用 `patch_all_copies.py`：以 ISO 原块为唯一基准、`--check` 只自测、共用备份、`--restore` 一键还原、写前校验目标块状态。

离线自测结果：

- 中文 `开始游戏`（`e5bc80 e5a78b e6b8b8 e6888f`，12 B）替换 `Start Game`（10 B），命中 #263 / #1162，逻辑数据 114908 → **114912**（两处各 +2），流 63538 → 64829，FILL 1852 → 560，pad=3。
- **等长回归**：同一新工具做 `Start Game → HANHUA OK!`，产出与旧 `patch_all_copies.rebuild()` **逐字节一致**，零回归。
- 边界测试：更长的中文串「开始新的冒险旅程」仍能塞进 65536 B 原块（流 64832 / FILL 560）。

### 11.4 已执行写入

先 `patch_all_copies.py --restore` 把上一轮等长补丁还原成 ISO 原块（2 个副本回读一致），再 `patch_utf8_resize.py --check` 预检，最后写入：

```
写入 : 2 个目标完成
回读 : BIGFILE0.VIV @ 0x9928C800 -> PASS | 条目=3294 全文一致=True 新串=[263, 1162] 旧串残留=[]
回读 : BIGFILE0.VIV @ 0xAB3A2000 -> PASS | 条目=3294 全文一致=True 新串=[263, 1162] 旧串残留=[]
```

**待用户目视**：完全退出 RPCS3 → 重开 → 直接启动已登记 BLUS30405 → 看主菜单第一项。显示「开始游戏」= 字库已含 CJK，可以直接进入批量翻译阶段；显示豆腐块 / 空白 / 乱码 = 必须扩字体图集与字符映射，那是下一阶段主体工作。若加载报错，优先怀疑 `0x34` 或偏移表还有别的消费方。

> 还原：`py -3 tools/patch_utf8_resize.py --restore`（与 `patch_all_copies.py --restore` 共用同一份 ISO 原块备份）。

## 12. 中文目视结果：缺字形占位方块；字体资源普查（同日）

用户重启后的主菜单截图：第一项不再有文字，而是 **4 个金色实心小方块**（`开始游戏` 恰好 4 个汉字 → 4 个占位符），其余菜单项 `Load Game` / `Downloadable Content` / `Movies` / `Special Features` / `Options` / `Trials of St. Lucia` / `Select` 全部正常显示、位置无错位、游戏无报错。

### 12.1 这条结果反而证明了链路全通

- **UTF-8 解码正确**：4 个方块对应 4 个 Unicode 字符，而不是 12 个 UTF-8 字节各画一个。渲染器确实按字符查字形表。
- **不等长重排正确**：逻辑数据 +4、偏移表全量平移、`full[0x04]` 与 `blob[0x34]` 同步修正后，游戏正常加载，3294 条文本中其余 3292 条全部完好，菜单布局没有错位。
- **唯一失败点**：字体图集里没有 CJK 字形，查表失败时画出 fallback 占位方块。

至此「文本层」已完全打通，工程难点收敛为**字形层**这一件事。

### 12.2 字体资源普查（只读 manifest + 条目头，未扫全盘）

| 检查项 | 结果 |
|---|---|
| 光盘散文件 | `USRDIR` 只有 `BIGFILE0/1/2.VIV` + `EBOOT.BIN` + `ealogo.vp6`，**无独立字体文件** |
| `shared\ui\` | 172 个条目全为 `.apx`，名字是 `bestiary_*` / `maptile_*` / `upgr_*` 等 UI 图标，不是字体 |
| `.vfb` | 17 个，全在 `shared\vfx\`（特效），是 VFX 不是 Vector Font |
| `.tg4h` | 88 个，全是角色/场景贴图 |
| 无扩展名条目 | 4786 个名字解析为空；条目头 magic 普查 Top：`\x03\x00\x00\x01` 1865、`\x03\x0c\x00\x01` 1714、`ols3` 1181、`\x03\x0c\x00\x02` 419、`\x03\x00\x00\x02` 329，另有 `MVhd` 58 |
| 显式字体 magic | 前 64 字节中 `FONT`/`font`/`Glyph`/`glyph`/`BMF`/`GTF`/`DDS`/`APX` 命中 **0** |
| EBOOT.BIN | 18 MB，`cellFont` / `libfont` / `Font` / `font` / `glyph` / `.ttf` / `.otf` / `SHOC` 均 0 次（SELF 加密，字符串不可见），`lh2` 命中 2 |

**结论**：字体图集大概率是 VIV 里的无名纹理条目（`\x03...` 类），或字形/映射数据内嵌于 EBOOT；没有可直接替换的 `.ttf`/`.fnt`/命名图集。要定位需要 RPCS3 的 RSX 纹理捕获或动态调试（在主菜单暂停、导出当前帧纹理、按字形排列特征筛出图集），再逆向字符映射表与字宽表，工作量比文本替换高一整个量级。

### 12.3 后续可选路径

1. **对照实验**：把 `开始游戏` 换成含 Latin-1 扩展字符的串（如 `Création`），验证渲染器是否支持 ASCII 之外的字形。能显示 = 只缺 CJK；也是方块 = 映射表只覆盖 ASCII，需连解码/映射一起改。成本极低，但要再重启一次游戏。
2. **动态定位图集**：RPCS3 主菜单抓帧导出纹理，找按字符集排列的图集，再逆向映射表并扩图集。这是真正做汉化的正路。
3. **模拟端 hook**：在 RPCS3 上 hook 文本绘制改用系统字体，只在模拟器生效，真机/PKG 无效。
4. **折中过渡**：先做拼音/短英文界面 + 中文对照表，不扩字库。

> 当前磁盘仍是中文补丁态（显示方块）。若想恢复可见文字，可 `--restore` 回原版，或用 `patch_all_copies.py` 重新打 `HANHUA OK!`。

## 13. Latin-1 对照实验 PASS：只缺 CJK 字形（同日）

按 12.3 的路径 1 做对照实验，把 `Start Game` 换成 `Création`（取自 `inferno_global.fr.lh2` #2 `Création de compte` 的真实原文，含 `é` = U+00E9 / UTF-8 `c3 a9`）。

### 13.1 结果

用户重启后的主菜单截图：第一项完整显示 **`Création`**，金色高亮态，`é` 上的重音清晰可见；其余菜单项正常。

**这条结论把字形层问题收窄了一大截**：

- 渲染器做了正确的 **UTF-8 解码**：没有显示成 `CrÃ©ation`（按单字节解释）；
- 渲染器做了 **Unicode 码点 → 字形查表**：U+00E9 能命中字形，说明映射表覆盖 Latin-1 扩展区，查表逻辑是通用的；
- 中文显示 4 个方块，只是因为 **图集里没有 U+4E00 起的 CJK 字形**，查表失败走 fallback。

因此做汉化 **不需要改解码层、不需要改字符映射逻辑**，只需：往图集加汉字字形 + 往映射表/字宽表加对应条目。这比"连解码一起重写"轻得多。

### 13.2 顺带验证

`Création` 是 9 字节 < 原 `Start Game` 10 字节，两处共 -2 字节。工具在**负 delta** 场景下同样通过：逻辑数据 114908 → 114906，偏移表全量平移、3294 条文本逐条比对 PASS，流 63538 → 64821 / FILL 1852 → 568，两个副本回读均 PASS。至此不等长重排的变长、变短两个方向都验证过了。

写入前先用 `patch_utf8_resize.py --restore` 把方块态还原成 ISO 原块；命令行 Unicode 传参测试通过（Git Bash → Windows Python 3 的 wide-char argv，`Création` → `4372c3a96174696f6e`）。

### 13.3 RPCS3 日志复核

`log/RPCS3.log` 25 MB，记录了 `sys_fs_open` 打开 `BIGFILE0/1/2.VIV`（并依次尝试 `BIGFILE3..12.VIV` 得到 `CELL_ENOENT`）以及 `TextureWorkerThread` 创建，但**没有任何字体/字形资源名**，游戏通过 BIGH TOC 的哈希内部取资源，日志帮不上定位。要找图集只能走 RSX 纹理捕获或静态逆向 VIV 无名纹理条目。

### 13.4 字形层的实际路线图

1. **定位图集**：RPCS3 在主菜单暂停，用 RSX 调试器导出当前帧纹理，按「规则网格排列的小字形」特征筛出字体图集；或静态解析 VIV 中 `\x03...` 类无名纹理条目。
2. **解析格式**：确认图集纹理格式（尺寸 / 通道 / 压缩），以及字符映射表的结构（Unicode 码点 → 图集 UV + 字宽 + 基线）。
3. **生成字形**：按游戏原有衬线风格渲染所需汉字（通常 2000–3500 个），写进扩大的图集。
4. **扩表 + 回填**：往映射表加 CJK 条目，必要时改 BIGH TOC 的 span（图集变大会超出原条目容量，这一步会打破目前「定长块覆盖」的便利性）。
5. **批量翻译**：文本层工具链已就绪，`extract/text_table_*.csv` 的 `translation` 列填好即可批量回填。

> 第 4 步是真正的分水岭：目前所有补丁都靠「条目物理长度不变、只改 65536 字节块」实现，图集一旦变大就得改 TOC span 并重排整个归档，工程复杂度会明显上升。

> 当前磁盘是 `Création` 补丁态（可读）。`patch_utf8_resize.py --restore` 回原版；`--text` 可换任意 UTF-8 文本再打补丁。

---

## 14. 「去找中文版游戏借字形」的可行性评估 + 零成本 CJK 探针

### 14.1 用户提议与结论

用户提出：模拟器里装的都是英文版，要不要找一个中文版游戏、从里面找可用的字形集。

**结论：先别找。** 随便一个中文版游戏的字形集不能直接借用，但在评估过程中发现**这个美版 ISO 自己就带着更好的对照组**，可以零成本先做一次决定性实验。

### 14.2 为什么「任意中文版游戏」不可行

- 字形集不是一张可替换的图片，而是「**图集位图 + 码点→UV/字宽/基线映射表 + 渲染代码**」三件套，与具体引擎绑定。换游戏 = 换一套私有格式，风格、尺寸、通道、压缩、字宽全不匹配，还得逆向对方格式一次，等于把同样的活干两遍；从商业游戏提取字体再分发也有版权风险。
- 本作 PS3 **没有官方中文版**：亚洲版 Death Edition（2010-02-09）语音/字幕均为英文；搜索结果里的「PSP 中文版 / 完全汉化版」是 PSP 或民间版本，资源格式与 PS3 完全不同，找错了会白下几 GB。
- **真正有价值的只有同款日版 `BLJM-60238`**（`ダンテズ・インフェルノ 神曲 地獄篇`，2010-02-18，CERO D，日文界面+字幕，日文语音）：同 Visceral Engine、同 BIGH/VIV 容器、同 `.lh2` 结构，diff 美版 vs 日版能直接定位字体图集与字符映射表条目，省掉 RSX 抓帧这一大步。代价是要下载 5–6 GiB、重做一遍解析，且日版有删改；日文汉字也不等于简体中文（`开`/`戏`/`游` 等字形不同或缺失），仍需补字形。
- 另一条不依赖任何游戏的路：用开源 CJK 字体（思源黑体 / Noto Sans CJK，SIL OFL）自行渲染位图字形，配合解析出的映射表格式，可控且无版权问题。

### 14.3 关键发现：美版 ISO 自带 CJK 文本残留

只读 `viv_manifest.json` + 各 `.lh2` 副本（没扫 8.4 GiB）：

| 语言码 | 内容性质 | 汉字 | 假名 |
|---|---|---|---|
| `en` / `es` / `fr` | 正式本地化文本 | 7 | 15 |
| `ll` | 混合残留（含日文诗句/年份） | **26** | 48 |
| `ss` | 未翻译的 key 名（`Credits_characterart_1` 等） | 0 | 0 |

- **每个语言副本** 都保留 `#2637 日本語` 与 `#1629 コントローラ{n}を再接続して、START ボタンを押してください。`；`ll` 另有 `地獄の使徒は本性を剥き出しに…`、`1265年` 等 31 条含汉字字符串。
- 汉字集合（ll）：`今使保再出剥地存年徒性意押接日本注獄目真空続覚解語除`；简体中文特有的 `开`/`始`/`游`/`戏` 等字形**一个都不在**任何副本里。
- 这是 EA 日文本地化流程的开发残留，说明**这套 `.lh2` 文本/码点体系原生就是为 CJK 设计的**，只是美版没打包日文字形。也因此日版与美版共用结构的推断更可信。

### 14.4 零成本探针（已写入，待目视）

把主菜单第一项换成游戏自带的真实字符串 `日本語`（3 汉字 / UTF-8 `e697a5e69cace8aa9e` / 9 B），而不是自造中文：

```
还原 : Création 态 -> ISO 原块
重排 : 'Start Game' -> '日本語' | 命中 [263, 1162] | 逻辑数据 114908 -> 114906 (-2)
重压 : 流 63538 -> 64819 | FILL 1852 -> 572 | pad=1
回读 : 0x9928C800 PASS | 0xAB3A2000 PASS | 3294 条全文一致 | 旧串残留=[]
```

结果分支：

| 目视结果 | 结论 | 下一步 |
|---|---|---|
| 显示 `日本語` 汉字 | 图集里**已有 CJK 字形**，映射表只是覆盖码点有限 | 工作量大幅下降：只需扩映射表 + 补简体字形，甚至可复用现成图集 |
| 仍是方块 | 图集确实无 CJK | 再考虑日版 diff 或 RSX 抓帧；字形位图用开源字体自渲染 |

### 14.5 工具修复：回读判定假阴性

首次写入后工具报 FAIL，但 `全文一致=True`、`旧串残留=[]`。原因是 `#2637` 本来就是游戏自带的 `日本語`，工具用「新串出现次数 == 命中下标数」判定，把这条原有同文也算成异常。已改为 `set(indices).issubset(hits)`，并把「旧串残留」限定为只检查命中下标，避免 `find` 文本在别处原本就存在时误判；复核后两个副本均 PASS。

> 当前磁盘是 `日本語` 探针态。`patch_utf8_resize.py --restore` 回原版；`--text` 可换任意 UTF-8 文本再打补丁。

---

## 15. `日本語` 探针目视结果 + PSN「韩版」PKG 定性

### 15.1 探针：方块 → 图集确无 CJK

用户截图：主菜单第一项显示 **3 个金色小方块**，正好对应「日本語」3 个汉字；其余 `Load Game` / `Downloadable Content` / `Movies` / `Special Features` / `Options` / `Trials of St. Lucia` 全部正常、无错位、无报错。

- 连游戏**自带的真实日文字符串** `#2637 日本語` 都渲染成方块 → **美版字体图集里完全没有 CJK 字形**，不是「映射表只覆盖有限码点」的乐观分支。
- 结合 `Création` 对照（U+00E9 正常）与「开始游戏」4 方块，可以确定：UTF-8 解码 ✅、Unicode→字形查表逻辑 ✅、不等长重排 ✅，**唯一缺口是字形位图 + 映射表条目**。
- 路线收敛为：定位图集/映射表 → 用本机固件 `SCE-PS3-DH-R-CGB.TTF`（8.23 MB / 20902 汉字）烘焙字形 → 扩图集与映射表 → 改 BIGH TOC `span` 并重排归档。

### 15.2 `NPHB00185` PKG 核查

| 项 | 实测 |
|---|---|
| 可达性 | 直连超时；必须走系统代理 `127.0.0.1:12334` |
| `Content-Length` | `1,059,806,864` B = **1.01 GiB** |
| `Last-Modified` | **2009-12-17**（早于 2010-02 发售两个月） |
| PKG 头 | magic `7F504B47`、`revision=0x8000`、`type=1`、`item_count=9`、`data_offset=0x180` |
| **`CONTENT_ID`** | **`HP0006-NPHB00185_00-DANTEINFERNODEMO`** ← **DEMO** |
| 头部资源名 | 前 128 KiB 内 `PARAM.SFO` / `EBOOT` / `BIGFILE` / `.VIV` / `.lh2` / `USRDIR` 命中均为 0；`0x180` 起疑似加密数据 |

结论：**这是亚洲区 PSN 试玩版 Demo，不是韩文完整版。** 1 GiB 主要是视频 + 单个关卡，9 个内部条目，不会有完整 VIV 或字体资源，**不值得整包下载**。

网络经验：`curl -r` 带 Range 被该 CDN 退回 502（HEAD 正常）；改用 Python `urllib` + 显式 `ProxyHandler` + `Range: bytes=0-131071` 成功返回 `206`，只收 128 KiB 即可解析 `CONTENT_ID`。以后筛选 PKG 用这个方法，不用下整包。

### 15.3 「韩文版」说法的核查

- 光盘韩版 `BLKS-20184`（Death Edition / KO / 条码 `8809080311738`）：Play-Asia 明确 Audio 与 Language = **English / French / Spanish**，只有 **Manual: Korean**（韩文说明书与封面）。
- GameKeepr 语言支持列表：EN / FR / DE / IT / ES-MX / ES-ES / JA，**没有 Korean**。
- 即这款游戏很可能**从未有过韩文本地化版**；「韩版」= 韩国发行的英文版。`NPHB` 前缀属亚洲/港区 PSN，也不等于韩文。
- 顺带修正：日版编号在 GameFAQs 资料库为 `BLJM-60202`（Best Hits `BLJM-60299`），第 14 节写的 `BLJM-60238` 有出入，实际以 PARAM.SFO 的 `TITLE_ID` 为准。

### 15.4 高效筛选方法

用户手上有 PSN CDN 直链清单。判断候选是否值得下载，只需 Range 抓头 128 KiB，看三项：`CONTENT_ID`（含 `DEMO`/`TRIAL` 直接弃）、`Content-Length`（PS3 完整游戏通常 9–10 GiB）、文件表里有没有 `BIGFILE0.VIV` / `.lh2`。几分钟筛一个。目标应是不带 DEMO 的完整版，或 `NPJB` / `BLJM` 日版。

> 当前磁盘仍是 `日本語` 方块态。`patch_utf8_resize.py --restore` 回原版；`extract/nphb00185_head.bin` 只是 128 KiB 头部样本，可删。

## 16. 本机 HDD 资源普查 + RPCS3 系统字体假设（同日）

用户提出「可以自己下载那个 PKG 并安装到 RPCS3，让助手去安装目录找资源」。结论：**不需要下载 DEMO，但用户的思路方向正确** —— 安装到 RPCS3 会把 PKG 内层加密资源解密成 `dev_hdd0/game/<ID>/USRDIR/` 下的明文散文件，正是静态分析最省事的入口。而且本机**早已有**这样一份资源池，之前被忽略。

### 16.1 本机已安装内容（只读普查）

`G:\Game\rpcs3-win64\dev_hdd0\game\` 共 15 个 ID。用 PARAM.SFO 键值解析确认：God of War Collection 日版 `BLJM60200`、GoW II HD / Ghost of Sparta / Chains of Olympus、PSN Patch、CounterSpy、Assault Heroes、After Burner Climax、Tetris、Golden Axe、Contrast 等，**没有 EA / Visceral 同引擎游戏**。所以本机借不到现成的中文字形。

关键遗漏：`BLUS30405` 目录并非只有 EBOOT 与 edat，而是 **595 个文件 / 1.4 GiB 的官方 DLC/补丁数据**（`dia_core`、`darkForestBundle`、各 costume bundle），扩展名：`.str` 416、`.snu` 107、`.lua` 17、`.lds` 13、`.edat` 12、`.toc` 10。

### 16.2 `.str` 与 VIV 条目同构

所有 `.str` 头都是 `ols3`（`6f 6c 73 33`）+ `SHOC/SHDR/SDAT`，与光盘 VIV 内条目完全一致；块按 65536 B 对齐。`arena_frontend.str`（3,080,192 B）里有 310 个 SHOC 块，含 17 处 `2HCL`（即 DLC 自带的 `.lh2` 本地化表）。说明 HDD 侧散文件与光盘资源是同一套容器，且游戏确实会从 HDD 读取覆盖资源。

### 16.3 字体资源的真实命名被找到

`dia_core/arena_frontend.str` 明文出现：

```
shared\fonts\arena\buttons_arena.tg4h / .tg4d
shared\fonts\arena\minion_pro_arena.tg4h / .tg4d
assets_shared_fonts_arena
DXT5  assets_shared_fonts_arena.buttons_arena
```

即 EA 把字体烘焙成 **`.tg4h`（头）+ `.tg4d`（数据）纹理对，DXT5 压缩**，路径规则 `shared\fonts\<模块>\<字体名>`。对应 SHDR 块 `@0x1EFA8`（size 0x6c）与 SDAT 块 `@0x1F014`（size 0x7c）。这是第一个可直接解析的字体容器样本。

### 16.4 但 VIV 里没有主游戏字体条目

新增 `tools/find_font_entries.py`：按 manifest 定点 seek 每个条目头 1 KiB（**不扫 8.4 GiB**），搜 `shared\fonts` / `assets_shared_fonts` / `glyph` / `.tg4d` / `2HCL` 等特征。结果：5888 条目中命中 170 个，其中 `.tg4d` 99（都是角色/场景贴图）、`2HCL` 21（本地化表）、`font` 8（关卡名 `eastfont` 之类）、`minion` 44（小怪名）。**真正的 `shared\fonts` / `glyph` 强特征 0 命中，无名条目也是 0 命中。** 报告 `report/font_candidates.json`（不入库）。

结论：主游戏字体不在 VIV 具名条目里，也不在条目头明文里；要么数据被 RefPack 压缩，要么根本不在 VIV（内置 EBOOT / 走系统字体）。

### 16.5 RPCS3 `cellFont` 硬编码映射（关键假设）

查 RPCS3 源码 `rpcs3/Emu/Cell/Modules/cellFont.cpp` 的 `cellFontOpenFontset()`：字体类型被**硬编码**到 `/dev_flash/data/font/SCE-PS3-*.TTF`：

| type | 文件 | 大小 |
|---|---|---|
| `RODIN_SANS_SERIF_LATIN` | `SCE-PS3-RD-R-LATIN.TTF` | 38 KB |
| `RODIN_SANS_SERIF_LATIN2` | `SCE-PS3-RD-R-LATIN2.TTF` | 54 KB |
| `NEWRODIN_GOTHIC_JAPANESE` | `SCE-PS3-NR-R-JPN.TTF` | 3.1 MB |
| **全部 `*_SET` 类型** | **统一回退 `RD-R-LATIN.TTF`**（源码注释 "not supported yet"） | — |

本机固件实测 29 个 TTF，其中 `SCE-PS3-DH-R-CGB.TTF`（8.23 MB）cmap 覆盖 **20902 个 CJK 汉字**且含 ASCII / Latin-1，但它**根本不在 RPCS3 的映射表里**，从未被使用。

这能完美解释之前的对照实验：`é`(U+00E9) 落在 LATIN/EXT 字体覆盖范围内 → 正常；U+4E00 起汉字不在 → fallback 方块。若游戏确实调用 `cellFont`，解法将变成**只改 RPCS3 固件字体目录、完全不碰游戏文件**：把 CGB 字体挂到它请求的那个文件名上即可，连 BIGH TOC `span` / 图集扩容都省掉。

静态确认受阻：两个 EBOOT（光盘 18 MB / HDD 20.6 MB）都是加密 SELF（`SCE\0` 头），`cellFont` / `font` / `/dev_flash` 字符串命中全 0；RPCS3 日志级别 `level=4` 不记录 `todo`，`cellFont` 通道无输出，无法静态判定游戏是否走 cellFont。

### 16.6 可回滚实验（已备好，未执行）

新增 `tools/try_system_font.py`：`--check` 只读查看、`--apply` 先备份 27 个非 CGB 的 TTF 到 `patch/font_backup/` 再用 CGB 字体覆盖、`--restore` 按 sha256 校验完整还原。`--check` 当前结果：0/27 已替换、无备份。

**因为改的是 RPCS3 全局固件字体（会影响其他游戏），需用户确认后才执行。** 执行后完全退出并重启 RPCS3、启动 BLUS30405 看主菜单：显示「开始游戏」= cellFont 假设成立，字形关直接解决；仍是方块 = 确认自绘图集，全部还原后回到图集定位路线。

### 16.7 关于「要不要下载那个文件」

- **`NPHB00185` DEMO 不用下**：已确认是 `DANTEINFERNODEMO` 试玩版。
- **用户的安装思路仍成立**：PKG 内层加密，RPCS3 安装后会解密写出明文散文件，比直接解析 PKG 省事。若以后拿到**同款日版完整版 `BLJM-60202`** 或带 CJK 的亚洲完整版，装到 RPCS3 后 `dev_hdd0/game/<ID>/USRDIR` 可直接 diff 字体条目，这是它独特的价值。
- 但在做这一步之前，应先做 16.6 的零下载实验 —— 若成功，连下载都省了。

## 17. 系统字体实验 FAIL —— 确认游戏用自绘图集，并找到 EA 字体资源命名

### 17.1 实验执行（用户批准，20:5x）

`tools/try_system_font.py --apply` 把 `G:/Game/rpcs3-win64/dev_flash/data/font/` 下 **27/27 个非 CGB 的 TTF 全部替换**为 `SCE-PS3-DH-R-CGB.TTF`（8,226,948 B，sha256 `938fb23c83666309…`，cmap 实测 20902 个 CJK 汉字且含 ASCII / Latin-1）。原文件完整备份到 `patch/font_backup/`（27 份）与 `patch/font_backup.json`，逐份 sha256 校验 0 失败；写后 `--check` 复核 27/27、校验 True。

为省一次重启，同时把菜单探针由 `日本語` 还原后改成简体中文 `开始游戏`（`e5bc80e5a78be6b8b8e6888f`）：命中 [263, 1162]，逻辑数据 114908 → 114912(+4)，流 64829 / FILL 560，3294 条全文比对 PASS，两个 VIV 副本回读均 PASS、旧串 0 残留。

### 17.2 结果与决定性证据

**目视：主菜单第一项仍是 4 个金色方块**（对应「开始游戏」4 个汉字），其余菜单正常、无错位。先排除「没真正重启」：进程 `rpcs3.exe StartTime = 2026-11-17 20:55:05`，日志头 `Current Time: 2026-11-17T20:55:05`，字体覆盖在 20:52–20:53 完成 → 覆盖确实在启动前就位。

再查日志：同一份日志能完整看到几十条 `sys_prx: Loaded module: "/dev_flash/sys/external/lib*.sprx"`（libmic / libadec / libcelpdec / libpngdec / libsysutil_* 等），但 `libfont` / `cellFont` / `cellFontFT` / `fontset` / `FontOpen` **精确搜索 0 命中**。即游戏从未加载 PS3 字体模块 —— **cellFont 假设彻底不成立，游戏使用自绘位图字体图集**。

`tools/try_system_font.py --restore` 已执行：27/27 还原，`--check` 复核 0/27 残留，RPCS3 全局字体恢复原状。

### 17.3 新发现：EA 字体资源的精确命名

在本机 HDD 官方 DLC 散文件里做窄筛选，得到主游戏字体的完整命名（此前只看到 arena 变体）：

```
shared\fonts\minion_pro.inf   /  .tg4h  /  .tg4d
shared\fonts\buttons.inf     /  .tg4h  /  .tg4d
shared\fonts\arena\minion_pro_arena.inf / .tg4h / .tg4d
shared\fonts\arena\buttons_arena.inf   / .tg4h / .tg4d
minion_pro.ffn   minion_pro_arena.ffn
assets_shared_fonts   assets_shared_fonts_arena   (SHOC 块资源名，DXT5)
```

出现位置：`dia_core/arena_frontend.str`（2 处 `assets_shared_fonts*`，SHOC/SHDR 样本在 0xC1EF / 0x1F065）、`dia_core/arena_templates/arena_templates_global.str`（4 处 `.ffn`/`.inf`）。`minion_pro` 是 Adobe Minion Pro 衬线体，与主菜单截图字体风格一致。由此确认字体是 **`.tg4h` 头 + `.tg4d` DXT5 图集 + `.inf`/`.ffn` 字符映射与字宽表** 三件套，`minion_pro` 是主菜单字体、`buttons` 是按钮图标字体。

### 17.4 静态定位的两条尝试与结果

- **VIV 条目表精确回查**：5888 个条目中具名 1191、无名 4697；`minion_pro` / `.inf` / `.ffn` / `shared\fonts` / `buttons` **0 命中**，具名条目扩展名 Top 里也完全没有 `.inf`/`.ffn`（最多的是 `.sbk` 385、`.apx` 172、`.ps3` 156、`.tg4h` 88）。
- **复核上轮被当噪声的 `minion` 命中**：44 个全部是 `minion_bertha.hkx` / `lvl_0X_minion_*.sbk` 等小怪与关卡名，**没有一个是 `minion_pro`**。
- **BIGH TOC `A` 字段是否为路径哈希**：A 非严格递增（min 33268 / max 4293952153），对 40 个具名条目用 CRC32 / FNV-1 / FNV-1a / djb2 / sdbm × 4 种路径变体测试，**全部不匹配**；具名条目里还混有 `<redacted>` 与解析乱码。因此无法靠计算路径哈希直接二分定位字体条目。

结论：主游戏字体图集在 4697 个无名条目或 EBOOT 内，条目头 1 KiB 明文里没有名字。

### 17.5 剩余关口与路线

系统字体捷径排除后，**唯一剩余关口仍是自绘图集**：定位图集 → 解析 DXT5 与 `.inf`/`.ffn` 映射表 → 用本机固件 `DH-R-CGB.TTF` 或开源 CJK 字体烘焙 2000–3500 个汉字 → 扩图集与映射表 → 图集变大后必须改 BIGH TOC 的 `span` 并重排归档（当前所有补丁都依赖「条目物理长度不变」，到这一步会失效）。

零下载可推进的两条：**① 解析 DLC 里 `minion_pro_arena` 的 SHOC/SDAT 样本**，反推图集尺寸、通道与映射表格式（本机已有 3 MB / 34 MB 明文 `.str`，无需下载、无需用户配合）；**② RSX 主菜单帧纹理捕获**，按「规则网格小字形」特征直接找出主 VIV 里的图集条目（需要用户配合）。若两条都卡住，再取同款日版完整版 `BLJM-60202` 装到 RPCS3 做 diff。

> 当前磁盘：固件字体 = **已还原原版**；游戏文本 = `开始游戏` 中文方块态。文本还原 `py -3 tools/patch_utf8_resize.py --restore`。
