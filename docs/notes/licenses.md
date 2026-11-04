# 许可与第三方资产盘点（SIL-831）

本仓库转为 public 后补的两件事：根目录的 `LICENSE`（MIT 全文 + 两段版权声明）
与这一份盘点。本文只记录**事实与产地**，不构成法律意见；判据是 `git ls-files`
里的实际内容，任何人都能按下面的命令复核。

## 结论

**仓内无第三方二进制资产。** 字体、CanvasKit wasm、Pyodide 运行时、Chromium 全部
在构建期或按需从 pixi / npm 取，落点都在 `.gitignore` 覆盖的目录里；入库的二进制
只有我们自己的渲染产物（PNG / PDF / 度量表）。

```bash
# 字体 / wasm / wheel / 动态库：应当没有任何输出
git ls-files | grep -Ei '\.(ttf|otf|woff2?|wasm|whl|so|dylib|dll|zip)$'

# 入库的二进制总量：27 png + 1 pdf + 1 bin
git ls-files | grep -Ei '\.(png|pdf|bin)$' | wc -l        # 29

# 构建期资产的落点都被忽略（每条都会打印命中的 .gitignore 行）
git check-ignore -v web/viewer/fonts/x.ttf node_modules/x \
  docs/spike/e1_coldstart/static/x.js \
  docs/spike/e1_coldstart/.npm/node_modules/x .playwright-browsers/x
```

## 许可

| | |
| --- | --- |
| 上游 | `tidyverse/ggplot2` v4.0.3，commit `cc1444c10edb87650fbe0cb31d56f0da1a255634` |
| 上游许可 | MIT（`DESCRIPTION`：`License: MIT + file LICENSE`） |
| 上游 `LICENSE` 原文 | `YEAR: 2025` / `COPYRIGHT HOLDER: ggplot2 core developer team`（R 包的两行式写法，MIT 模板在 R 的 `R_HOME` 里） |
| 本项目许可 | MIT，见根目录 `LICENSE` |

`LICENSE` 是 MIT 全文，抬头并列两行版权声明——`2025 ggplot2 core developer team`
与 `2026 Sylens Wong`，没有合并、没有取其一。上游那行是把 R 包的两行式 `LICENSE`
按 MIT 模板写成 `Copyright (c) 2025 ...`，年份与持有人原样保留。

为什么必须带上游那行：本仓库的语义层、R 侧夹具、参考图大量移植或生成自它，MIT
要求“保留版权声明与许可全文”。钉版与升级流程见 `docs/notes/upstream.md`。

## 入库资产（逐类）

| 资产 | 数量 | 产地 | 覆盖它的许可 |
| --- | --- | --- | --- |
| `docs/cases/*/expected.svg` | 492 | 见下 | ggplot2 MIT |
| `docs/cases/*/baseline/*.png` | 19 | 我们自己的 skia 设备渲染（`cases:grob` / `cases:viewport`） | 本项目 MIT |
| `tests/fixtures/device_render_r/*.png` | 5 | `pixi run -e refs refs:device-render` 的 R 输出（R 4.5.3 的 png 设备画同一张夹具图） | 本项目 MIT（R 只是工具） |
| `tests/fixtures/*_r_reference.json` | 18 | `refs:*` 各脚本对 R 的观测结果（逐列值 / 尺寸 / 断点），不是上游文件的拷贝 | 本项目 MIT |
| `docs/spike/e1_coldstart/results/*.png` | 3 | E1 冷启动实测截图 | 本项目 MIT |
| `docs/spike/e3_export/results/artifacts/sample.pdf` | 1 | `spike:e3` 用 skia-python 出的 PDF | 本项目 MIT |
| `src/ggcore/metrics/data/metrics_table_v2.bin` | 1 | `metrics:table` 从受管字体量出的 advance 表（纯数值，不含字形轮廓） | 本项目 MIT |
| `src/ggcore/palette_data.py` | 1 | 生成物：brewer 逐 n 表 ← RColorBrewer 1.1.3（Apache-2.0），viridis 8 档 ← viridisLite 0.4.3（MIT）；来源写在文件头 | 同上，已注明出处 |
| `tools/gates/upstream_api.json` | 1 | 上游 v4.0.3 `NAMESPACE` 的导出清单（名字表，非代码） | ggplot2 MIT |

### `expected.svg` 的产地（492 份）

逐 case 的产地写在同目录 `meta.toml` 的 `source` 里，只有两种前缀：

```bash
git ls-files docs/cases | grep -c 'expected\.svg'                    # 492
grep -h '^source' docs/cases/*/meta.toml | grep -c 'upstream:'       # 274
grep -h '^source' docs/cases/*/meta.toml | grep -c 'svglite:'        # 218
```

- **274 份 `upstream:tests/testthat/_snaps/...`**：直接取自上游 v4.0.3 的 vdiffr
  快照，逐字节入库（`snapshots:import` 只复制、不改写），因此是上游的 MIT 资产。
- **218 份 `svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2)`**：由
  `pixi run -e refs refs:*` 在我们的环境里当场渲染。内容是**我们的 plot 规格 +
  ggplot2 的版面**，不是上游文件的拷贝；产物沿用上游 MIT 的归属表述。
- 参考图产线用了 R（GPL）与 svglite（GPL-2+），但它们只作为**工具**参与生成：
  SVG 是渲染结果，本仓库不分发 R 或 svglite 的代码，所以 copyleft 不传染到
  `expected.svg`。这条口径与 `docs/notes/snapshot-policy.md` 的纳管策略一致。

其中 **35 份** `expected.svg` 内嵌 `data:image/png;base64,...`：

```bash
grep -l 'data:image' docs/cases/*/expected.svg | wc -l   # 35
```

这是 svglite 对部分 grob 的光栅回退（同一张图、同一次渲染产生；`geom-raster`、
colourbar、图例版面等），不是任何外部图片素材。

### 非第三方资产的零碎

`git ls-files` 里还有 3 个 `*.orig`（`src/ggcore/axis_guide.py.orig`、
`src/ggcore/geom/scene.py.orig`、`tools/upstream/snapshots.toml.orig`）：本地
冲突备份，内容都是本仓库自己的源码，不涉及第三方。它们不属于本次范围，未删除。

## 不入库的构建期资产

这些是“看起来像第三方二进制、但仓里没有”的部分，逐个核实过：

| 资产 | 从哪来 | 落到哪（已忽略） | 许可 |
| --- | --- | --- | --- |
| 16 个字体文件（Arimo VF、DejaVu Sans/Serif、Noto Sans/Serif VF、Noto Sans CJK SC VF、Noto Emoji、Noto Color Emoji） | conda-forge 的 `font-ttf-dejavu` / `font-ttf-noto` / `font-ttf-noto-cjk` / `font-ttf-noto-emoji`（`pixi.toml` `[dependencies]`） | `viewer:build` 复制到 `web/viewer/fonts/`（`.gitignore` 里点名忽略），`@font-face` 与 TS 常量也是构建期生成 | DejaVu：Bitstream Vera / DejaVu 许可；Arimo 与 Noto 各族：SIL OFL-1.1 |
| CanvasKit wasm（`canvaskit-wasm@0.42.0`） | `pixi run assets:canvaskit`（npm） | `node_modules/` | Apache-2.0 |
| Pyodide 运行时 + numpy / pandas / contourpy 的 wasm 轮子（`pyodide@314.0.7`） | `pixi run spike:e1:assets`（npm + 镜像下载） | `.npm/node_modules/`、`docs/spike/e1_coldstart/static/` | Pyodide MPL-2.0；CPython PSF-2.0；numpy / pandas / contourpy 均 BSD-3 |
| Chromium（Playwright） | `pixi run viewer:browsers` | `.playwright-browsers/` | Chromium 与 Playwright 均 Apache-2.0 |
| 运行期依赖的二进制 | `pixi install` 按 `pixi.lock` 解析 | `.pixi/` | numpy BSD-3、skia-python / Skia BSD-3、uharfbuzz MIT、cbor2 MIT、contourpy BSD-3、Pillow MIT-CMU、resvg MPL-2.0 |
| R 与 R 包（`refs` 环境） | `pixi install -e refs` | `.pixi/` | 只在生产参考值时使用，本仓库不重分发其代码；具体许可见各包 `DESCRIPTION` |

复核要点：`web/viewer/fonts/`、`web/viewer/fonts.css`、
`web/viewer/src/fonts.generated.ts` 都在 `.gitignore` 里，`viewer:build` 每次重建；
`docs/spike/e1_coldstart/static/` 同理（`spike:e1:assets` 里的
`manifest.json` 记录每个字节的来源 URL 与 sha256，但不入库）。字体度量表
`metrics_table_v2.bin` 只有 advance 数值与字体 sha256，不含轮廓数据。

## 本次不做的

- 不加 CLA，不改任何源码逻辑，不动测试与快照。
- 不逐个源文件加许可头（MIT 不要求；要加是另一件事，走单独 issue）。
- 不引入新的依赖，也不把上述构建期资产改成入库，以避免仓库膨胀与许可复核负担。
