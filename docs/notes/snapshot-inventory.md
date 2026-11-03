# 上游 SVG 快照清单（v4.0.3）

<!-- 生成物：`pixi run snapshots:report`。处置写 `tools/upstream/snapshots.toml`。 -->

- 参考实现：`tidyverse/ggplot2` `v4.0.3` @ `cc1444c10edb87650fbe0cb31d56f0da1a255634`
- 快照总数：**311**（上游 `tests/testthat/_snaps/**/*.svg`）
- 已纳管：**21**（`expected.svg` 与上游快照逐字节相同）
- 已知缺口：**290**（全部按分类归口，见下表）

## 已纳管（能自动跑）

| 快照 | case |
| --- | --- |
| `guides/facet-grid-legend-on-bottom.svg` | `upstream-guides-facet-grid-legend-bottom` |
| `guides/facet-grid-legend-on-left.svg` | `upstream-guides-facet-grid-legend-left` |
| `guides/facet-grid-legend-on-right.svg` | `upstream-guides-facet-grid-legend-right` |
| `guides/facet-grid-legend-on-top.svg` | `upstream-guides-facet-grid-legend-top` |
| `guides/facet-wrap-legend-on-bottom.svg` | `upstream-guides-facet-wrap-legend-bottom` |
| `guides/facet-wrap-legend-on-left.svg` | `upstream-guides-facet-wrap-legend-left` |
| `guides/facet-wrap-legend-on-right.svg` | `upstream-guides-facet-wrap-legend-right` |
| `guides/facet-wrap-legend-on-top.svg` | `upstream-guides-facet-wrap-legend-top` |
| `theme/theme-bw.svg` | `upstream-theme-bw` |
| `theme/theme-classic.svg` | `upstream-theme-classic` |
| `theme/theme-dark-large.svg` | `upstream-theme-dark-large` |
| `theme/theme-dark.svg` | `upstream-theme-dark` |
| `theme/theme-gray-large.svg` | `upstream-theme-gray-large` |
| `theme/theme-gray.svg` | `upstream-theme-gray` |
| `theme/theme-light-large.svg` | `upstream-theme-light-large` |
| `theme/theme-light.svg` | `upstream-theme-light` |
| `theme/theme-linedraw.svg` | `upstream-theme-linedraw` |
| `theme/theme-minimal-large.svg` | `upstream-theme-minimal-large` |
| `theme/theme-minimal.svg` | `upstream-theme-minimal` |
| `theme/theme-void-large.svg` | `upstream-theme-void-large` |
| `theme/theme-void.svg` | `upstream-theme-void` |

## 已知缺口

### SIL-715 — 6 条

`aes()` 的 stat 侧参数（`stat_count(width=)` / `aes(alpha=)`）在我们的语法层没有逐条复刻。

<details><summary>快照</summary>

- `aes/alpha-set-in-alpha.svg`
- `aes/alpha-set-in-colour.svg`
- `aes/stat-count-width-0-5.svg`
- `aes/stat-count.svg`
- `aes/stat-identity-width-0-5.svg`
- `aes/stat-identity.svg`

</details>

### SIL-715 — 2 条

`annotate()` 的边框与线段共形（`annotation_borders()` / `annotation_segment()`）未复刻。

<details><summary>快照</summary>

- `annotate/annotation-borders-utah.svg`
- `annotate/line-matches-points.svg`

</details>

### SIL-715 — 1 条

`base_size = 33` 下 geom 缺省尺寸没跟着 `theme$pointsize` 走（4.0 的 `from_theme()`）：点径与线宽仍按 11pt 画，实测图级 2.27% / 均值 0.53%。归口 SIL-715 的 `from_theme()` 条目。

<details><summary>快照</summary>

- `theme/theme-bw-large.svg`

</details>

### SIL-715 — 2 条

`coord_map()` 只做注册与最小可用；mapproj 投影与经纬度变换归 M3-2 空间能力。

<details><summary>快照</summary>

- `coord-map/coord-map-switched-scale-position.svg`
- `coord-map/usa-mercator.svg`

</details>

### SIL-715 — 3 条

`coord_trans()` 的 sec axis 与反向组合未逐条复刻。

<details><summary>快照</summary>

- `coord-transform/basic-coord-transform-plot.svg`
- `coord-transform/reversed-transformed-coords.svg`
- `coord-transform/sec-axis-with-coord-transform.svg`

</details>

### SIL-715 — 1 条

`draw_key` 的全量 key 形状未逐条复刻。

<details><summary>快照</summary>

- `legend-draw/all-legend-keys.svg`

</details>

### SIL-715 — 1 条

`facet_wrap(switch=)` 的 strip 换边未复刻。

<details><summary>快照</summary>

- `facet-strips/switched-facet-strips.svg`

</details>

### SIL-715 — 2 条

`geom_curve()` 的翻转（`coord_flip`）未复刻。

<details><summary>快照</summary>

- `geom-curve/flipped-geom-curve.svg`
- `geom-curve/standard-geom-curve.svg`

</details>

### SIL-715 — 35 条

`geom_dotplot()` 的 bin 对齐 / stackgroups / histodot 语义（35 条）是 SIL-715 里单列的 dotplot 缺口。

<details><summary>快照</summary>

- `geom-dotplot/2-na-values-bin-along-y-stack-center.svg`
- `geom-dotplot/2-na-values-dot-density-binning-binwidth-4.svg`
- `geom-dotplot/3-stackgroups-bin-y-histodot.svg`
- `geom-dotplot/3-stackgroups-dot-density-with-aligned-bins.svg`
- `geom-dotplot/3-stackgroups-histodot.svg`
- `geom-dotplot/basic-dotplot-with-dot-density-binning-binwidth-4.svg`
- `geom-dotplot/bin-along-y-stack-center.svg`
- `geom-dotplot/bin-along-y-stack-centerwhole-histodot.svg`
- `geom-dotplot/bin-along-y-stack-centerwhole.svg`
- `geom-dotplot/bin-x-three-y-groups-stack-centerwhole.svg`
- `geom-dotplot/bin-y-continous-x-axis-grouping-by-x.svg`
- `geom-dotplot/bin-y-continous-x-axis-single-x-group.svg`
- `geom-dotplot/bin-y-dodged-coord-flip.svg`
- `geom-dotplot/bin-y-dodged.svg`
- `geom-dotplot/bin-y-dodging-3-stackgroups-histodot.svg`
- `geom-dotplot/bin-y-three-x-groups-bins-aligned-across-groups.svg`
- `geom-dotplot/bin-y-three-x-groups-bins-aligned-coord-flip.svg`
- `geom-dotplot/bin-y-three-x-groups-fill-and-dodge.svg`
- `geom-dotplot/bin-y-three-x-groups-stack-centerwhole.svg`
- `geom-dotplot/dots-stacked-closer-stackratio-5-fill-white.svg`
- `geom-dotplot/facets-3-groups-histodot-stackgroups.svg`
- `geom-dotplot/histodot-binning-equal-bin-spacing.svg`
- `geom-dotplot/larger-dots-dotsize-1-5-fill-white.svg`
- `geom-dotplot/multiple-groups-bins-aligned.svg`
- `geom-dotplot/multiple-groups-bins-not-aligned.svg`
- `geom-dotplot/stack-center-with-coord-flip.svg`
- `geom-dotplot/stack-center.svg`
- `geom-dotplot/stack-centerwhole-with-coord-flip.svg`
- `geom-dotplot/stack-centerwhole.svg`
- `geom-dotplot/stack-down-with-coord-flip.svg`
- `geom-dotplot/stack-down.svg`
- `geom-dotplot/stack-up-with-coord-flip.svg`
- `geom-dotplot/stack-up.svg`
- `geom-dotplot/stackratio-1-5.svg`
- `geom-dotplot/variable-linetype-and-size-specified-as-aesthetics.svg`

</details>

### SIL-715 — 3 条

`geom_hex()` 与极坐标 / 变换轴组合未复刻。

<details><summary>快照</summary>

- `geom-hex/hex-bin-plot-in-polar-coordinates.svg`
- `geom-hex/hex-bin-plot-with-sqrt-transformed-y.svg`
- `geom-hex/single-hex-bin-with-width-and-height-of-0-1.svg`

</details>

### SIL-715 — 1 条

`geom_label()` 的线段参数（`label.size` / `label.padding` 与线段共形）未复刻。

<details><summary>快照</summary>

- `geom-label/geom-label-with-line-parameters.svg`

</details>

### SIL-715 — 12 条

`geom_raster()` 的 just / limits / 离散轴组合（12 条）未逐条复刻。

<details><summary>快照</summary>

- `geom-raster/1-x-3-just-0-0.svg`
- `geom-raster/1-x-3-set-limits.svg`
- `geom-raster/1-x-3.svg`
- `geom-raster/3-x-1-just-0-0.svg`
- `geom-raster/3-x-1-set-limits.svg`
- `geom-raster/3-x-1.svg`
- `geom-raster/3-x-2-just-0-0.svg`
- `geom-raster/3-x-2-set-limits.svg`
- `geom-raster/3-x-2.svg`
- `geom-raster/discrete-positions.svg`
- `geom-raster/irregular-categorical.svg`
- `geom-raster/rectangle-fallback.svg`

</details>

### SIL-715 — 2 条

`geom_smooth()` 的 ribbon 开关未逐条复刻。

<details><summary>快照</summary>

- `geom-smooth/ribbon-turned-off-in-geom-smooth.svg`
- `geom-smooth/ribbon-turned-on-in-geom-smooth.svg`

</details>

### SIL-715 — 14 条

`geom_violin()` 的 dodge / quantile / scale=area（14 条）未逐条复刻。

<details><summary>快照</summary>

- `geom-violin/basic.svg`
- `geom-violin/continuous-x-axis-many-groups-center-should-be-at-2-0.svg`
- `geom-violin/continuous-x-axis-single-group-center-should-be-at-1-0.svg`
- `geom-violin/coord-flip.svg`
- `geom-violin/coord-polar.svg`
- `geom-violin/dodging-and-coord-flip.svg`
- `geom-violin/dodging.svg`
- `geom-violin/grouping-on-x-and-fill-dodge-width-0-5.svg`
- `geom-violin/grouping-on-x-and-fill.svg`
- `geom-violin/narrower-width-5.svg`
- `geom-violin/scale-area-to-sample-size-c-is-smaller.svg`
- `geom-violin/styled-quantiles.svg`
- `geom-violin/with-smaller-bandwidth-and-points.svg`
- `geom-violin/with-tails-and-points.svg`

</details>

### SIL-715 — 2 条

`labeller` 的 plotmath 解析与 outside 对齐未复刻。

<details><summary>快照</summary>

- `facet-labels/outside-justified-labels.svg`
- `facet-labels/parsed-facet-labels.svg`

</details>

### SIL-715 — 6 条

`plot.tag.location`（margin / panel / plot）目前只在主题元素树里，渲染器还没消费；补齐后再纳管 6 条。

<details><summary>快照</summary>

- `labels/defaults.svg`
- `labels/tag-in-margin.svg`
- `labels/tag-in-panel-as-character.svg`
- `labels/tag-in-panel-as-numeric.svg`
- `labels/tag-in-plot-as-character.svg`
- `labels/tag-in-plot-as-numeric.svg`

</details>

### SIL-715 — 1 条

`position_stack()` 的 area 堆叠未复刻。

<details><summary>快照</summary>

- `position-stack/area-stacking.svg`

</details>

### SIL-715 — 3 条

`stat_align()` 的两段面积 cliff / pos-neg 未复刻。

<details><summary>快照</summary>

- `stat-align/align-two-areas-with-cliff.svg`
- `stat-align/align-two-areas-with-pos-neg-y.svg`
- `stat-align/align-two-areas.svg`

</details>

### SIL-715 — 3 条

`stat_sum()` 的 crossbar 汇总未复刻。

<details><summary>快照</summary>

- `stat-sum/summary-with-color-and-lines.svg`
- `stat-sum/summary-with-crossbars-manual-grouping.svg`
- `stat-sum/summary-with-crossbars-no-grouping.svg`

</details>

### SIL-715 — 3 条

colourbar 自定义与双美学合图未复刻。

<details><summary>快照</summary>

- `guide-colorbar/combined-colour-and-fill-aesthetics.svg`
- `guide-colorbar/customized-colorbar.svg`
- `guide-colorbar/white-to-red-colorbar-white-ticks-no-frame.svg`

</details>

### SIL-715 — 5 条

hline/vline/abline 在极坐标与 map 坐标下的曲线化未复刻（M3-2 空间 + 极坐标裁剪）。

<details><summary>快照</summary>

- `geom-hline-vline-abline/cartesian-lines-intersect-mid-bars.svg`
- `geom-hline-vline-abline/flipped-lines-intersect-mid-bars.svg`
- `geom-hline-vline-abline/lines-curved-in-azequalarea.svg`
- `geom-hline-vline-abline/polar-lines-intersect-mid-bars.svg`
- `geom-hline-vline-abline/straight-lines-in-mercator.svg`

</details>

### SIL-715 — 2 条

munched polygon（`coord_munch` 后的闭合多边形）未复刻。

<details><summary>快照</summary>

- `geom-polygon/basic-polygon-plot.svg`
- `geom-polygon/open-and-closed-munched-polygons.svg`

</details>

### SIL-715 — 5 条

path 的绘制顺序与 NA 线型未逐条复刻。

<details><summary>快照</summary>

- `geom-path/lines-changed-order-should-have-same-appearance.svg`
- `geom-path/lines-colour-changed-order-should-have-same-appearance.svg`
- `geom-path/lines-colour.svg`
- `geom-path/lines.svg`
- `geom-path/na-linetype.svg`

</details>

### SIL-715 — 4 条

pattern fill（grid pattern / `tile_pattern()`）未进 SVG 渲染器。

<details><summary>快照</summary>

- `patterns/pattern-fills-no-alpha.svg`
- `patterns/pattern-fills-through-scale.svg`
- `patterns/pattern-fills-with-alpha.svg`
- `patterns/single-pattern-fill.svg`

</details>

### SIL-715 — 1 条

plotmath 表达式标签（`expression()`）未支持。

<details><summary>快照</summary>

- `geom-text/geom-text-with-expressions.svg`

</details>

### SIL-715 — 5 条

依赖上游测试共用的 `mtcars` 数据集夹具（32×11），本批次未内联。

<details><summary>快照</summary>

- `coord-cartesian/clip-on-by-default-only-inside-visible.svg`
- `coord-cartesian/clip-turned-off-both-inside-and-outside-visible.svg`
- `coord-cartesian/contract-range.svg`
- `coord-cartesian/expand-range.svg`
- `coord-cartesian/reversed-cartesian-coords.svg`

</details>

### SIL-715 — 1 条

同 `coord-cartesian`：需要 `mtcars` 夹具与 sec axis 的翻转组合。

<details><summary>快照</summary>

- `coord-flip/turning-off-secondary-title-with-coord-flip.svg`

</details>

### SIL-715 — 1 条

同 `theme-bw-large`：`from_theme(pointsize / borderwidth)` 未实现，点径 / 线宽未随 `base_size` 缩放，实测图级 2.09% / 均值 0.43%。

<details><summary>快照</summary>

- `theme/theme-linedraw-large.svg`

</details>

### SIL-715 — 1 条

同 `theme-bw-large`：`from_theme(pointsize / borderwidth)` 未实现，点径 / 线宽未随 `base_size` 缩放，实测图级 2.22% / 均值 1.05%（均值也超 1% 门）。

<details><summary>快照</summary>

- `theme/theme-classic-large.svg`

</details>

### SIL-715 — 6 条

图例 key 的专项形状（2cm key、boxplot/crossbar/linerange 的 key grob）未逐条复刻。

<details><summary>快照</summary>

- `draw-key/appropriate-colour-key-with-alpha-key-as-lines.svg`
- `draw-key/circle-glyphs-of-2cm-size.svg`
- `draw-key/horizontal-boxplot-and-crossbar.svg`
- `draw-key/horizontal-linerange-and-pointrange.svg`
- `draw-key/rectangle-and-dotplot-key-glyphs.svg`
- `draw-key/time-series-and-polygon-key-glyphs.svg`

</details>

### SIL-715 — 7 条

图例方向 / key 间距 / key 对齐（依赖 `mtcars`）未复刻。

<details><summary>快照</summary>

- `guide-legend/enlarged-guides.svg`
- `guide-legend/horizontal-legend-direction.svg`
- `guide-legend/left-aligned-legend-key.svg`
- `guide-legend/legend-byrow-true.svg`
- `guide-legend/legend-key-justification.svg`
- `guide-legend/legend-with-widely-spaced-keys.svg`
- `guide-legend/vertical-legend-direction.svg`

</details>

### SIL-715 — 13 条

断点 / 标签函数与空图例（13 条）未逐条复刻。

<details><summary>快照</summary>

- `scales-breaks-labels/character.svg`
- `scales-breaks-labels/date.svg`
- `scales-breaks-labels/functional-limits.svg`
- `scales-breaks-labels/no-alpha-breaks-no-legend.svg`
- `scales-breaks-labels/no-colour-breaks-no-legend.svg`
- `scales-breaks-labels/no-fill-breaks-no-legend.svg`
- `scales-breaks-labels/no-size-breaks-no-legend.svg`
- `scales-breaks-labels/no-x-breaks.svg`
- `scales-breaks-labels/no-y-breaks.svg`
- `scales-breaks-labels/numeric-exp.svg`
- `scales-breaks-labels/numeric-log.svg`
- `scales-breaks-labels/numeric-polar.svg`
- `scales-breaks-labels/numeric.svg`

</details>

### SIL-715 — 8 条

日期断点 / 标签（8 条）未逐条复刻。

<details><summary>快照</summary>

- `scale_date/dates-along-x-default-breaks.svg`
- `scale_date/dates-along-y-default-breaks.svg`
- `scale_date/scale-x-date-breaks-3-weeks.svg`
- `scale_date/scale-x-date-breaks-breaks-width-2-weeks.svg`
- `scale_date/scale-x-date-labels-label-date-m-d.svg`
- `scale_date/scale-x-date-labels-label-date-w-week.svg`
- `scale_date/scale-y-date-breaks-3-weeks.svg`
- `scale_date/scale-y-date-breaks-breaks-width-2-weeks.svg`

</details>

### SIL-715 — 23 条

本批次纳管 8 套主题 + 5 个 `base_size = 33` 变体（另 3 个见下方单条归口）；其余 theme 快照（spacing / margin / 元素样式 / aspect.ratio）未复刻，其中 `aspect.ratio` 主题元素尚未支持，已单列进 SIL-715。

<details><summary>快照</summary>

- `theme/axes-styling.svg`
- `theme/caption-aligned-to-entire-plot.svg`
- `theme/custom-strip-elements-can-render.svg`
- `theme/height-is-3-times-width-2-column-facets.svg`
- `theme/height-is-3-times-width-2-row-facets.svg`
- `theme/height-is-3-times-width-2-wrap-facets.svg`
- `theme/height-is-3-times-width-2x2-facets.svg`
- `theme/height-is-3-times-width.svg`
- `theme/horizontal-legends-placed-apart.svg`
- `theme/large-margins.svg`
- `theme/large-spacing.svg`
- `theme/legends-at-all-sides-with-justification.svg`
- `theme/point-elements.svg`
- `theme/polygon-elements.svg`
- `theme/rotated-x-axis-tick-labels.svg`
- `theme/stretched-horizontal-legends.svg`
- `theme/stretched-vertical-legends.svg`
- `theme/strip-styling.svg`
- `theme/theme-with-inverted-colours.svg`
- `theme/ticks-length.svg`
- `theme/titles-aligned-to-entire-plot.svg`
- `theme/vertical-legends-placed-apart.svg`
- `theme/width-is-3-times-height.svg`

</details>

### SIL-715 — 37 条

本批次纳管了 8 条 facet × 图例位置；其余 guides 快照（bins/coloursteps 边界、inside 图例、旧 S3 guide）未复刻。

<details><summary>快照</summary>

- `guides/guide-bins-can-remove-axis.svg`
- `guides/guide-bins-can-show-arrows.svg`
- `guides/guide-bins-can-show-limits.svg`
- `guides/guide-bins-can-show-ticks-and-transparancy.svg`
- `guides/guide-bins-looks-as-it-should.svg`
- `guides/guide-bins-sets-labels-when-limits-is-in-breaks.svg`
- `guides/guide-bins-understands-coinciding-limits-and-bins-2.svg`
- `guides/guide-bins-understands-coinciding-limits-and-bins-3.svg`
- `guides/guide-bins-understands-coinciding-limits-and-bins.svg`
- `guides/guide-bins-work-horizontally.svg`
- `guides/guide-colorsteps-sets-labels-when-limits-is-in-breaks.svg`
- `guides/guide-colorsteps-understands-coinciding-limits-and-bins-2.svg`
- `guides/guide-colorsteps-understands-coinciding-limits-and-bins-3.svg`
- `guides/guide-colorsteps-understands-coinciding-limits-and-bins.svg`
- `guides/guide-coloursteps-can-have-bins-relative-to-binsize.svg`
- `guides/guide-coloursteps-can-show-limits.svg`
- `guides/guide-coloursteps-looks-as-it-should.svg`
- `guides/guide-custom-with-void-theme.svg`
- `guides/guide-title-and-text-positioning-and-alignment-via-themes.svg`
- `guides/horizontal-gap-of-1cm-between-guide-and-guide-text.svg`
- `guides/legend-inside-plot-bottom-left-of-legend-at-center.svg`
- `guides/legend-inside-plot-bottom-left.svg`
- `guides/legend-inside-plot-centered.svg`
- `guides/legend-inside-plot-multiple-positions.svg`
- `guides/legend-inside-plot-top-right.svg`
- `guides/legend-on-bottom.svg`
- `guides/legend-on-left.svg`
- `guides/legend-on-right.svg`
- `guides/legend-on-top.svg`
- `guides/legends-with-all-title-justifications.svg`
- `guides/multi-line-guide-title-works.svg`
- `guides/old-s3-guide-drawing-a-circle.svg`
- `guides/padding-in-legend-box.svg`
- `guides/reversed-guide-bins.svg`
- `guides/rotated-guide-titles-and-labels.svg`
- `guides/stylised-guide-custom.svg`
- `guides/vertical-gap-of-1cm-between-guide-title-and-guide.svg`

</details>

### SIL-715 — 11 条

极坐标 × 轴 / 次轴 / racetrack（内半径切片）组合未逐条复刻；部分能力已实现但缺 atan2 轴标注的像素级对齐。

<details><summary>快照</summary>

- `coord-polar/bottom-half-circle-with-rotated-text.svg`
- `coord-polar/full-circle-with-axes-placed-at-90-and-225-degrees.svg`
- `coord-polar/inner-radius-with-all-axes.svg`
- `coord-polar/partial-with-all-axes.svg`
- `coord-polar/racetrack-plot-closed-and-has-center-hole.svg`
- `coord-polar/racetrack-plot-closed-and-no-center-hole.svg`
- `coord-polar/rays-circular-arcs-and-spiral-arcs.svg`
- `coord-polar/reversed-polar-coords.svg`
- `coord-polar/rose-plot-with-has-equal-spacing.svg`
- `coord-polar/secondary-axis-ticks-and-labels.svg`
- `coord-polar/three-concentric-circles.svg`

</details>

### SIL-715 — 7 条

次轴变换（monotonicity / skew / datetime，7 条）未逐条复刻。

<details><summary>快照</summary>

- `sec-axis/sec-axis-custom-transform.svg`
- `sec-axis/sec-axis-datetime-scale.svg`
- `sec-axis/sec-axis-independent-transformations.svg`
- `sec-axis/sec-axis-monotonicity-test.svg`
- `sec-axis/sec-axis-sec-power-transform.svg`
- `sec-axis/sec-axis-skewed-transform.svg`
- `sec-axis/sec-axis-with-division.svg`

</details>

### SIL-715 — 4 条

省略内轴标签 / 左对齐 strip 的分面布局口径未复刻（SIL-715 #7 的组合矩阵在 M2-S3 另做）。

<details><summary>快照</summary>

- `facet-/facet-grid-with-omitted-inner-axis-labels.svg`
- `facet-/facet-wrap-with-omitted-inner-axis-labels.svg`
- `facet-/left-justified-facet-labels-with-margins.svg`
- `facet-/left-justified-rotated-facet-labels-with-margins.svg`

</details>

### SIL-715 — 10 条

空间几何（`geom_sf*`）归 M3-2；M2 尚未注册 sf 的 list-column 解析。

<details><summary>快照</summary>

- `geom-sf/geom-sf-line-legend.svg`
- `geom-sf/geom-sf-point-legend.svg`
- `geom-sf/geom-sf-polygon-legend.svg`
- `geom-sf/labels-for-north-carolina.svg`
- `geom-sf/mixed-geometry-types.svg`
- `geom-sf/north-carolina-county-boundaries-with-arrow.svg`
- `geom-sf/north-carolina-county-boundaries-with-more-than-one-arrow.svg`
- `geom-sf/north-carolina-county-boundaries.svg`
- `geom-sf/spatial-points.svg`
- `geom-sf/texts-for-north-carolina.svg`

</details>

### SIL-715 — 9 条

空间坐标（`coord_sf`）的 graticule / crs 归 M3-2。

<details><summary>快照</summary>

- `coord_sf/coord-sf-with-custom-guides.svg`
- `coord_sf/limits-specified-in-long-lat.svg`
- `coord_sf/limits-specified-in-projected-coords.svg`
- `coord_sf/no-breaks.svg`
- `coord_sf/no-panel-grid.svg`
- `coord_sf/non-sf-geoms-using-long-lat.svg`
- `coord_sf/non-sf-geoms-using-projected-coords.svg`
- `coord_sf/reversed-sf-coords.svg`
- `coord_sf/sf-polygons.svg`

</details>

### SIL-715 — 3 条

箱线图自定义样式 / 异常值颜色 / staples 未逐条复刻。

<details><summary>快照</summary>

- `geom-boxplot/customised-style.svg`
- `geom-boxplot/outlier-colours.svg`
- `geom-boxplot/staples.svg`

</details>

### SIL-715 — 23 条

轴 guide 的角度 / 叠放 / 稀疏 / 次刻度 / logtick 定制（23 条）未逐条复刻。

<details><summary>快照</summary>

- `guide-axis/align-facet-labels-facets-horizontal.svg`
- `guide-axis/align-facet-labels-facets-vertical.svg`
- `guide-axis/axis-guides-basic.svg`
- `guide-axis/axis-guides-check-overlap.svg`
- `guide-axis/axis-guides-negative-rotation.svg`
- `guide-axis/axis-guides-positive-rotation.svg`
- `guide-axis/axis-guides-text-dodged-into-rows-cols.svg`
- `guide-axis/axis-guides-vertical-negative-rotation.svg`
- `guide-axis/axis-guides-vertical-rotation.svg`
- `guide-axis/axis-guides-with-capped-ends.svg`
- `guide-axis/axis-guides-zero-breaks.svg`
- `guide-axis/axis-guides-zero-rotation.svg`
- `guide-axis/guide-axis-customization.svg`
- `guide-axis/guide-axis-theta-in-cartesian-coordinates.svg`
- `guide-axis/guide-axis-theta-with-angle-adapting-to-theta.svg`
- `guide-axis/guide-titles-with-coord-transform.svg`
- `guide-axis/guides-specified-in-guides.svg`
- `guide-axis/guides-with-minor-ticks.svg`
- `guide-axis/logtick-axes-with-customisation.svg`
- `guide-axis/position-guide-titles.svg`
- `guide-axis/stacked-axes.svg`
- `guide-axis/stacked-radial-axes.svg`
- `guide-axis/thick-axis-lines.svg`

</details>

### SIL-715 — 1 条

非表格布局（`facet_grid` 缺行/列）的轴定位未复刻。

<details><summary>快照</summary>

- `facet-layout/axes-are-positioned-correctly-in-non-table-layout.svg`

</details>
