# M2 缺口收口计划（SIL-786）

<!-- 人写。数字与逐簇明细以 `docs/notes/snapshot-inventory.md`（生成物）为准；
     本文件只记录「怎么分组推进」。改了分组就改这里，不要改生成物。 -->

## 口径

- 分母 **311**（上游 pin `cc1444c1` 的 `_snaps/**/*.svg`），不回到 314。
- 阈值 **图级 2% / 均值 1%**，不放宽：不新增覆盖、不改既有 case 的阈值。
- 归属两档写在 `tools/upstream/snapshots.toml` 的每个 group 上（owner 按簇声明，
  单条覆盖必须与 group 一致）：

| owner | 开工时缺口 | 含义 |
| --- | ---: | --- |
| `m2-closeout` | 267 | 「M2 已宣称但没做到对等」，M3 开工前必须归零 |
| `m3` | 23 | 真 M3 新能力，移交 |

现状（SIL-822 对齐后）：缺口 **39** 条全部归 `m3`，`m2-closeout` **0** 条。逐簇
数字以 `docs/notes/snapshot-inventory.md` 为准（生成物）；`docs/cases/matrix.md`
的「上游快照」一节与它同源。

burndown 表在 `docs/notes/snapshot-inventory.md` 的「按簇 burndown」一节，生成入口
`pixi run snapshots:report`，新鲜度由 `pixi run snapshots:report:check`（已挂进 `check`）守。

## 7 个 PR 组

数字按台账精确统计（题面里的 76 / 13 是粗算，实际是 77 / 21）。

| 组 | 簇 | 缺口 | 预计触碰 | 并行性 |
| --- | --- | ---: | --- | --- |
| G1 guides | `guides` 37 + `guide-legend` 7 + `guide-colorbar` 3 + `legend-draw` 1 + `draw-key` 6 + `guide-axis` 23 | 77 | `guide.py`、`axis_guide.py`、`grobs.py` | **组内串行**：先 legend（54）后 axis（23），同一个 `guide.py` |
| G2 dotplot | `geom-dotplot` | 35 | `geom/dist.py`、`position.py` | 与其他组无文件重叠 |
| G3 theme | `theme`（含 3 条 `from_theme()` 大字号） | 26 → **8**（SIL-792 纳管 18） | `theme.py`、`registry.py`、`geom/point.py`、`geom/line.py`、`geom/scene.py`、`facet.py`、`axis.py` | 与 G1/G2 无重叠；与 G4 抢 `geom/` 的默认尺寸，串行 |
| G4 violin+raster | `geom-violin` 14 + `geom-raster` 12 | 26 | `geom/dist.py`、`geom/rect.py`、`position.py` | 与 G2 抢 `geom/dist.py`，串行 |
| G5 polar+sec-axis | `coord-polar` 11 + `sec-axis` 7 + `coord-transform` 3 + `coord-cartesian` 5 + `coord-flip` 1 | 27 | `coord.py`、`axis.py` | 与其他组无重叠 |
| G6 scales | `scales-breaks-labels` 13 + `scale_date` 8 | 21 | `scales.py`、`scales_date.py` | 与其他组无重叠 |
| G7 小簇 | `aes` 6、`labels` 6、`geom-hline-vline-abline` 5、`geom-path` 5、`facet-` 4、`patterns` 4、`geom-boxplot` 3、`geom-hex` 3、`stat-align` 3、`stat-sum` 3、`facet-labels` 2、`geom-curve` 2、`geom-polygon` 2、`geom-smooth` 2、`facet-layout` 1、`facet-strips` 1、`geom-label` 1、`geom-text` 1、`position-stack` 1 | 55 | 分散 | 拆成 2–3 个 PR，按文件再分 |

合计 77 + 35 + 26 + 26 + 27 + 21 + 55 = **267**（SIL-792 之后 `theme` 缺口 8）。

## 并行规则

同时最多 **2 条**，且必须**不同簇、无文件重叠**。「大小」不是判断依据，**文件重叠**才是：
M2 期间 6 组并行改同一批文件，付出过多轮「自动合并但语义冲突」的人工并集成本
（lty 公式、`STAT_POSITIONS`、`panel_cols`）。

- 开工前在子任务里写下**本轮实际会改的文件清单**，与正在并行的子任务比对；有交集就串行。
- `snapshots.toml` 是共用文件：新增 `[snapshots."<path>"] case = "..."` 只追加自己簇的条目，
  冲突时 rebase 取两边。

## M3-1 现状（SIL-825）

本阶段簇：`annotate` / `coord_polar·radial` 边界 / `patterns` / `geom-text` + `report`
阈值档。逐项（数字以 `pixi run snapshots:report` 与直接 `render`+`diff` 实测为准）：

| 簇 | 缺口 | 现状 |
| --- | ---: | --- |
| `annotate` | 2 → **0** | 已全部纳管：`annotate()` / `annotation_borders()` / `borders()` 落地，`ggcore.map_data` 内联 Utah 59 点；`upstream-annotate-utah` 0.18% / 0.02%，`upstream-annotate-segment-transform` 0.45% / 0.14% |
| `patterns` | 4 | 未落地。现有 case `upstream-patterns-single-pattern-fill` 实测 **31.02% / 26.36%**：两边都是 1cm 棋盘，**差的是相位**（同一行上黑格起点相差约半块 tile）。根因是内容坐标系——R 的 `pattern()` 内容按**整层 grob 的 bbox** 折 npc 再按 tile 裁剪，本仓 `TilePatternSpec.resolve()` 把内容画在 tile 局部坐标里。另外三条各自还多一层：逐行 FillSpec 列表（`fill = patterns`）、`alpha` 走 `GridMask`（IR 无 mask 节点）、`scale_fill_manual(values = <FillSpec>)` 要在标度里保留 FillSpec |
| `coord-polar`（radial 版式） | 4 + `guide-axis` 2 | 未落地。`matrix-report-facet-polar-grey` 实测 **8.54% / 1.30%**（SIL-820 时 23.99%，面板尺寸已改善但仍不是 R 的整页正方形面板）；`guide_axis_stack('axis_theta')` 仍直接抛 `ValueError`（`axis_guide.py`），`guide_axis()` / `guide_axis_theta()` 还没有逐 guide 的 `theme=` 参数 |
| `geom-text`（plotmath） | 1 | 未落地。本仓文本层只吃纯文本，没有 `parse = TRUE` / plotmath 解析（希腊字母、上下标、根号 path），与 `guide-axis` 的 `label_math()` 卡点同源 |

`report` 档已落地并接入：`matrix-report-facet-wrap-grey` 1.95% / 0.38%、
`matrix-report-facet-grid-grey` 1.75% / 0.38% 进 CI；`matrix-report-facet-polar-grey`
仍 `ci = false`（见上一行，5% 档也装不下）。

## 移交 M3（不在本任务范围）

| 簇 | 缺口 | 去向 |
| --- | ---: | --- |
| `geom-sf` | 10 | M3-2 空间能力（list-column 解析 + geom_sf grob 路径） |
| `coord_sf` | 9 | M3-2（真实投影 / graticule） |
| `coord-map` | 2 | M3-2（mapproj 投影） |
| `annotate` | 2 | M3-1（`annotation_borders()` / `annotation_segment()`） |

版面组合（patchwork 等价物）上游没有对应快照，不占本台账，直接进 M3-1。

## 收口判据

1. `m2-closeout` 的簇全部归零（`pixi run snapshots:report` 里 burndown 剩余 0）。
2. `snapshots.toml` ↔ `snapshot-inventory.md` ↔ 案例矩阵三处口径一致，CI 绿。
3. 每个 PR 由测试工程师独立复核后才合并。
