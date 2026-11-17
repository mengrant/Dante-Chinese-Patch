# Dante's Inferno (PS3, BLUS30405) 汉化补丁 — 工作记录

> 仅记录逆向分析与工具开发过程。仓库**不包含**任何游戏资源（ISO / VIV / PKG / EBOOT / 贴图 / 视频 / 文本原文）。

## 0. 项目目标

基于美版 `Dante's Inferno Divine Edition [BLUS30405]` 制作个人学习用的中文补丁。
载体应为 **Game Update / Patch PKG** 或散文件覆盖，而不是 DLC（DLC 是追加内容，游戏不会用它替换主程序文本）。

## 1. 环境与素材

| 项 | 值 |
|---|---|
| ISO | `<ISO_DIR>\Dante's Inferno Divine Edition [BLUS30405].iso` |
| ISO 大小 | 10,167,930,880 字节 ≈ 9.47 GiB（已完整下载） |
| PARAM.SFO | TITLE_ID `BLUS30405`、APP_VER `01.00`、CATEGORY `DG`、PS3_SYSTEM_VER `3.15` |
| RPCS3 | `<RPCS3_DIR>`（已安装；`dev_hdd0/game/BLUS30405/USRDIR` 已有补丁/DLC 数据目录） |
| 会话工作区 | `<ISO_DIR>`（保持不变） |
| 工程输出目录 | `<WORK_ROOT>`（extract / build / patch / report） |
| 磁盘 | D 剩约 10 GB（放不下解包产物）；G 剩约 35 GB，且与 RPCS3 同盘 |

下载阶段的坑（已解决）：网络出口对 archive.org 的大文件传输「单连接约存活 2 秒」限流，浏览器长连接被掐断后不会自动续传，于是表现为「下一会就卡住」。最终用 16 MiB 分块 + 块内流式续传 + 断点记录完成下载。系统代理 `<PROXY_HOST>` 可访问 archive.org；工具沙箱注入的另一条代理会返回 502。

## 2. 已完成的分析（全部只读，未改动 ISO）

### 2.1 ISO 层

- `PS3_GAME/USRDIR/`：`BIGFILE0.VIV` 2,873,888,768 B、`BIGFILE1.VIV` 2,625,208,320 B、`BIGFILE2.VIV` 2,951,903,316 B、`EBOOT.BIN` 约 20 MB、`EALOGO.VP6`。
- `/UPDATE/` 下自带 6 个官方 PKG，content ID 均为 `UP0006-BLUS30405_00-*`，其中 `UP0006-BLUS30405_00-INFERNOPATCH0003` 即官方补丁，可作为自制补丁 PKG 的形式样板。

### 2.2 EA BIGH 归档层（本次新进展）

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

- TOC 记录按 **A 字段严格递增**排列 → A 极可能是排序用的文件名哈希，而不是偏移；B / C 中一个是偏移、一个是长度（尚未最终定论，需结合条目数据头验证）。
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
| `iso_probe.py` | 解析 ISO9660 目录树、PARAM.SFO、列出大文件及 magic |
| `viv_probe.py` | 扫 VIV 头部 / TOC 明文串、列出光盘内置 PKG 的 content ID |
| `viv_dump.py` | 十六进制 dump VIV 头部，用于确定 TOC 布局 |
| `viv_toc_probe.py` | 验证 `toc_size = 24 + 12×N` 假设、查看 TOC 后的数据 |
| `viv_index.py` | 建立全量条目索引 → `report/viv_index.json`（5888 条记录，557 KB） |
| `text_scan.py` | 8 MiB 块顺序扫描数据区 → `report/text_hotspots.json` |

全部为**只读**脚本，不写回 ISO，不删除文件。

## 4. 关键决策 / 捷径

1. **开发主环境用 RPCS3**，真机只做最终验收。RPCS3 优先加载 `dev_hdd0/game/<TITLE_ID>/USRDIR/` 下的同名文件，因此改好的散文件可直接覆盖验证，**不必每次重打包 9 GB ISO**。
2. 光盘自带的 `UP0006-BLUS30405_00-INFERNOPATCH0003` 是补丁形态的样板；成品可做成 Patch PKG，落到 `dev_hdd0/game/BLUS30405/USRDIR/`。
3. 先做**最小闭环验证**：只把一处文本改成中文，跑通「改 `.lh2` → RefPack 重压 → 修 `.ols` 头 → 组回 VIV/散文件覆盖 → RPCS3 运行」，看到中文后再谈批量翻译。
4. 该作有民间汉化先例（2021 俄语版、2026 波兰语版进行中），优先复用其 BMS 脚本与 `.lh2` 工具线索，避免从零逆向。
5. 三个 VIV 共 8.4 GiB，所有「解包—替换—重打包」必须脚本化、增量式，禁止手工改大文件。

## 5. 待办

- [ ] 确定 TOC 三个字段的准确语义（偏移 / 长度 / 哈希），写出 `viv_extract.py`
- [ ] 实现 EA RefPack 解压与重压，抽出 `.ols` → `.lh2`
- [ ] 解析 `.lh2` 字符串指针表，导出可翻译的 CSV/JSON
- [ ] 定位字体贴图（`.tg4h/.tg4d`）与字符映射表，评估中文字库方案
- [ ] 最小闭环：单条文本汉化 + RPCS3 截图验证
- [ ] 批量翻译、指针重算、控制码保护
- [ ] 生成 Patch PKG / 差异补丁；真机 CFW/HEN 验收

## 6. 边界

- 基于自有正版做个人学习 / 自用。
- 仓库与补丁只分发**自己写的脚本、配置、索引和翻译差异文本**；不分发原版资源、完整 VIV、ISO、EBOOT 或任何 DRM / 在线相关内容。
- 真机运行未签名补丁需要 CFW/HEN，OFW 无法安装。
