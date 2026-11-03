# M2 缺口收口计划（SIL-786）

<!-- 人写。数字与逐簇明细以 `docs/notes/snapshot-inventory.md`（生成物）为准；
     本文件只记录「怎么分组推进」。改了分组就改这里，不要改生成物。 -->

## 口径

- 分母 **311**（上游 pin `cc1444c1` 的 `_snaps/**/*.svg`），不回到 314。
- 阈值 **图级 2% / 均值 1%**，不放宽：不新增覆盖、不改既有 case 的阈值。
- 归属两档写在 `tools/upstream/snapshots.toml` 的每个 group 上：

| owner | 缺口 | 含义 |
| --- | ---: | --- |
| `m2-closeout` | 267 | 「M2 已宣称但没做到对等」，M3 开工前必须归零 |
| `m3` | 23 | 真 M3 新能力，移交 |

burndown 表在 `docs/notes/snapshot-inventory.md` 的「按簇 burndown」一节，生成入口
`pixi run snapshots:report`，新鲜度由 `pixi run snapshots:report:check`（已挂进 `check`）守。

## 7 个 PR 组

数字按台账精确统计（题面里的 76 / 13 是粗算，实际是 77 / 21）。

| 组 | 簇 | 缺口 | 预计触碰 | 并行性 |
| --- | --- | ---: | --- | --- |
| G1 guides | `guides` 37 + `guide-legend` 7 + `guide-colorbar` 3 + `legend-draw` 1 + `draw-key` 6 + `guide-axis` 23 | 77 | `guide.py`、`axis_guide.py`、`grobs.py` | **组内串行**：先 legend（54）后 axis（23），同一个 `guide.py` |
| G2 dotplot | `geom-dotplot` | 35 | `geom/dist.py`、`position.py` | 与其他组无文件重叠 |
| G3 theme | `theme`（含 3 条 `from_theme()` 大字号） | 26 | `theme.py`、`registry.py`、`geom/point.py`、`geom/line.py` | 与 G1/G2 无重叠；与 G4 抢 `geom/` 的默认尺寸，串行 |
| G4 violin+raster | `geom-violin` 14 + `geom-raster` 12 | 26 | `geom/dist.py`、`geom/rect.py`、`position.py` | 与 G2 抢 `geom/dist.py`，串行 |
| G5 polar+sec-axis | `coord-polar` 11 + `sec-axis` 7 + `coord-transform` 3 + `coord-cartesian` 5 + `coord-flip` 1 | 27 | `coord.py`、`axis.py` | 与其他组无重叠 |
| G6 scales | `scales-breaks-labels` 13 + `scale_date` 8 | 21 | `scales.py`、`scales_date.py` | 与其他组无重叠 |
| G7 小簇 | `aes` 6、`labels` 6、`geom-hline-vline-abline` 5、`geom-path` 5、`facet-` 4、`patterns` 4、`geom-boxplot` 3、`geom-hex` 3、`stat-align` 3、`stat-sum` 3、`facet-labels` 2、`geom-curve` 2、`geom-polygon` 2、`geom-smooth` 2、`facet-layout` 1、`facet-strips` 1、`geom-label` 1、`geom-text` 1、`position-stack` 1 | 55 | 分散 | 拆成 2–3 个 PR，按文件再分 |

合计 77 + 35 + 26 + 26 + 27 + 21 + 55 = **267**。

## 并行规则

同时最多 **2 条**，且必须**不同簇、无文件重叠**。「大小」不是判断依据，**文件重叠**才是：
M2 期间 6 组并行改同一批文件，付出过多轮「自动合并但语义冲突」的人工并集成本
（lty 公式、`STAT_POSITIONS`、`panel_cols`）。

- 开工前在子任务里写下**本轮实际会改的文件清单**，与正在并行的子任务比对；有交集就串行。
- `snapshots.toml` 是共用文件：新增 `[snapshots."<path>"] case = "..."` 只追加自己簇的条目，
  冲突时 rebase 取两边。

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
