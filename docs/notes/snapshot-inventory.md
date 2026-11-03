# 上游 SVG 快照清单（v4.0.3）

<!-- 生成物：`pixi run snapshots:report`。处置写 `tools/upstream/snapshots.toml`。 -->

- 参考实现：`tidyverse/ggplot2` `v4.0.3` @ `cc1444c10edb87650fbe0cb31d56f0da1a255634`
- 快照总数：**311**（上游 `tests/testthat/_snaps/**/*.svg`）
- 已纳管：**177**（`expected.svg` 与上游快照逐字节相同）
- 已知缺口：**134**（全部按分类归口，见下表）
- 缺口归属：`m2-closeout` **111** 条（M3 开工前归零） / `m3` **23** 条（移交 M3）

## 按簇 burndown

| 簇 | owner | 上游 | 已纳管 | 缺口 |
| --- | --- | ---: | ---: | ---: |
| `guide-axis` | m2-closeout | 23 | 10 | 13 |
| `coord-polar` | m2-closeout | 11 | 0 | 11 |
| `geom-sf` | m3 | 10 | 0 | 10 |
| `coord_sf` | m3 | 9 | 0 | 9 |
| `theme` | m2-closeout | 39 | 31 | 8 |
| `sec-axis` | m2-closeout | 7 | 0 | 7 |
| `aes` | m2-closeout | 6 | 0 | 6 |
| `labels` | m2-closeout | 6 | 0 | 6 |
| `coord-cartesian` | m2-closeout | 5 | 0 | 5 |
| `geom-hline-vline-abline` | m2-closeout | 5 | 0 | 5 |
| `geom-path` | m2-closeout | 5 | 0 | 5 |
| `draw-key` | m2-closeout | 6 | 2 | 4 |
| `facet-` | m2-closeout | 4 | 0 | 4 |
| `patterns` | m2-closeout | 4 | 0 | 4 |
| `coord-transform` | m2-closeout | 3 | 0 | 3 |
| `geom-boxplot` | m2-closeout | 3 | 0 | 3 |
| `geom-hex` | m2-closeout | 3 | 0 | 3 |
| `stat-align` | m2-closeout | 3 | 0 | 3 |
| `stat-sum` | m2-closeout | 3 | 0 | 3 |
| `annotate` | m3 | 2 | 0 | 2 |
| `coord-map` | m3 | 2 | 0 | 2 |
| `facet-labels` | m2-closeout | 2 | 0 | 2 |
| `geom-curve` | m2-closeout | 2 | 0 | 2 |
| `geom-polygon` | m2-closeout | 2 | 0 | 2 |
| `geom-smooth` | m2-closeout | 2 | 0 | 2 |
| `guide-legend` | m2-closeout | 7 | 5 | 2 |
| `coord-flip` | m2-closeout | 1 | 0 | 1 |
| `facet-layout` | m2-closeout | 1 | 0 | 1 |
| `facet-strips` | m2-closeout | 1 | 0 | 1 |
| `geom-label` | m2-closeout | 1 | 0 | 1 |
| `geom-text` | m2-closeout | 1 | 0 | 1 |
| `guides` | m2-closeout | 45 | 44 | 1 |
| `legend-draw` | m2-closeout | 1 | 0 | 1 |
| `position-stack` | m2-closeout | 1 | 0 | 1 |
| `geom-dotplot` | m2-closeout | 35 | 35 | 0 |
| `geom-raster` | m2-closeout | 12 | 12 | 0 |
| `geom-violin` | m2-closeout | 14 | 14 | 0 |
| `guide-colorbar` | m2-closeout | 3 | 3 | 0 |
| `scale_date` | m2-closeout | 8 | 8 | 0 |
| `scales-breaks-labels` | m2-closeout | 13 | 13 | 0 |
| **合计** | — | 311 | 177 | 134 |

口径：`m2-closeout` 的簇是「M2 已宣称但没做到对等」的缺口，必须在 M3 开工前清零（与上游逐字节相同，或落在 2% / 1% 档）；`m3` 的簇移交空间能力 / 版面组合 / `annotate()`，不在本台账里重复计。

## 已纳管（能自动跑）

| 快照 | case |
| --- | --- |
| `draw-key/horizontal-boxplot-and-crossbar.svg` | `upstream-draw-key-horizontal-boxplot-crossbar` |
| `draw-key/horizontal-linerange-and-pointrange.svg` | `upstream-draw-key-horizontal-linerange-pointrange` |
| `geom-dotplot/2-na-values-bin-along-y-stack-center.svg` | `upstream-geom-dotplot-2-na-bin-along-y` |
| `geom-dotplot/2-na-values-dot-density-binning-binwidth-4.svg` | `upstream-geom-dotplot-2-na-dotdensity` |
| `geom-dotplot/3-stackgroups-bin-y-histodot.svg` | `upstream-geom-dotplot-3-stackgroups-bin-y-histodot` |
| `geom-dotplot/3-stackgroups-dot-density-with-aligned-bins.svg` | `upstream-geom-dotplot-3-stackgroups-dotdensity-aligned` |
| `geom-dotplot/3-stackgroups-histodot.svg` | `upstream-geom-dotplot-3-stackgroups-histodot` |
| `geom-dotplot/basic-dotplot-with-dot-density-binning-binwidth-4.svg` | `upstream-geom-dotplot-basic-dotdensity` |
| `geom-dotplot/bin-along-y-stack-center.svg` | `upstream-geom-dotplot-bin-along-y-stack-center` |
| `geom-dotplot/bin-along-y-stack-centerwhole-histodot.svg` | `upstream-geom-dotplot-bin-along-y-stack-centerwhole-histodot` |
| `geom-dotplot/bin-along-y-stack-centerwhole.svg` | `upstream-geom-dotplot-bin-along-y-stack-centerwhole` |
| `geom-dotplot/bin-x-three-y-groups-stack-centerwhole.svg` | `upstream-geom-dotplot-bin-x-three-y-groups-stack-centerwhole` |
| `geom-dotplot/bin-y-continous-x-axis-grouping-by-x.svg` | `upstream-geom-dotplot-bin-y-continuous-x-grouping-by-x` |
| `geom-dotplot/bin-y-continous-x-axis-single-x-group.svg` | `upstream-geom-dotplot-bin-y-continuous-x-single-group` |
| `geom-dotplot/bin-y-dodged-coord-flip.svg` | `upstream-geom-dotplot-bin-y-dodged-coord-flip` |
| `geom-dotplot/bin-y-dodged.svg` | `upstream-geom-dotplot-bin-y-dodged` |
| `geom-dotplot/bin-y-dodging-3-stackgroups-histodot.svg` | `upstream-geom-dotplot-bin-y-dodging-3-stackgroups-histodot` |
| `geom-dotplot/bin-y-three-x-groups-bins-aligned-across-groups.svg` | `upstream-geom-dotplot-bin-y-three-x-groups-bins-aligned-across-groups` |
| `geom-dotplot/bin-y-three-x-groups-bins-aligned-coord-flip.svg` | `upstream-geom-dotplot-bin-y-three-x-groups-bins-aligned-coord-flip` |
| `geom-dotplot/bin-y-three-x-groups-fill-and-dodge.svg` | `upstream-geom-dotplot-bin-y-three-x-groups-fill-and-dodge` |
| `geom-dotplot/bin-y-three-x-groups-stack-centerwhole.svg` | `upstream-geom-dotplot-bin-y-three-x-groups-stack-centerwhole` |
| `geom-dotplot/dots-stacked-closer-stackratio-5-fill-white.svg` | `upstream-geom-dotplot-stackratio-half` |
| `geom-dotplot/facets-3-groups-histodot-stackgroups.svg` | `upstream-geom-dotplot-facets-3-groups-histodot-stackgroups` |
| `geom-dotplot/histodot-binning-equal-bin-spacing.svg` | `upstream-geom-dotplot-histodot` |
| `geom-dotplot/larger-dots-dotsize-1-5-fill-white.svg` | `upstream-geom-dotplot-dotsize-large` |
| `geom-dotplot/multiple-groups-bins-aligned.svg` | `upstream-geom-dotplot-multiple-groups-bins-aligned` |
| `geom-dotplot/multiple-groups-bins-not-aligned.svg` | `upstream-geom-dotplot-multiple-groups-bins-not-aligned` |
| `geom-dotplot/stack-center-with-coord-flip.svg` | `upstream-geom-dotplot-stack-center-coord-flip` |
| `geom-dotplot/stack-center.svg` | `upstream-geom-dotplot-stack-center` |
| `geom-dotplot/stack-centerwhole-with-coord-flip.svg` | `upstream-geom-dotplot-stack-centerwhole-coord-flip` |
| `geom-dotplot/stack-centerwhole.svg` | `upstream-geom-dotplot-stack-centerwhole` |
| `geom-dotplot/stack-down-with-coord-flip.svg` | `upstream-geom-dotplot-stack-down-coord-flip` |
| `geom-dotplot/stack-down.svg` | `upstream-geom-dotplot-stack-down` |
| `geom-dotplot/stack-up-with-coord-flip.svg` | `upstream-geom-dotplot-stack-up-coord-flip` |
| `geom-dotplot/stack-up.svg` | `upstream-geom-dotplot-stack-up` |
| `geom-dotplot/stackratio-1-5.svg` | `upstream-geom-dotplot-stackratio-1-5` |
| `geom-dotplot/variable-linetype-and-size-specified-as-aesthetics.svg` | `upstream-geom-dotplot-variable-linetype-size` |
| `geom-raster/1-x-3-just-0-0.svg` | `upstream-geom-raster-1-x-3-just-0-0` |
| `geom-raster/1-x-3-set-limits.svg` | `upstream-geom-raster-1-x-3-set-limits` |
| `geom-raster/1-x-3.svg` | `upstream-geom-raster-1-x-3` |
| `geom-raster/3-x-1-just-0-0.svg` | `upstream-geom-raster-3-x-1-just-0-0` |
| `geom-raster/3-x-1-set-limits.svg` | `upstream-geom-raster-3-x-1-set-limits` |
| `geom-raster/3-x-1.svg` | `upstream-geom-raster-3-x-1` |
| `geom-raster/3-x-2-just-0-0.svg` | `upstream-geom-raster-3-x-2-just-0-0` |
| `geom-raster/3-x-2-set-limits.svg` | `upstream-geom-raster-3-x-2-set-limits` |
| `geom-raster/3-x-2.svg` | `upstream-geom-raster-3-x-2` |
| `geom-raster/discrete-positions.svg` | `upstream-geom-raster-discrete-positions` |
| `geom-raster/irregular-categorical.svg` | `upstream-geom-raster-irregular-categorical` |
| `geom-raster/rectangle-fallback.svg` | `upstream-geom-raster-rectangle-fallback` |
| `geom-violin/basic.svg` | `upstream-geom-violin-basic` |
| `geom-violin/continuous-x-axis-many-groups-center-should-be-at-2-0.svg` | `upstream-geom-violin-continuous-x-axis-many-groups` |
| `geom-violin/continuous-x-axis-single-group-center-should-be-at-1-0.svg` | `upstream-geom-violin-continuous-x-axis-single-group` |
| `geom-violin/coord-flip.svg` | `upstream-geom-violin-coord-flip` |
| `geom-violin/coord-polar.svg` | `upstream-geom-violin-coord-polar` |
| `geom-violin/dodging-and-coord-flip.svg` | `upstream-geom-violin-dodging-and-coord-flip` |
| `geom-violin/dodging.svg` | `upstream-geom-violin-dodging` |
| `geom-violin/grouping-on-x-and-fill-dodge-width-0-5.svg` | `upstream-geom-violin-grouping-on-x-and-fill-dodge-width` |
| `geom-violin/grouping-on-x-and-fill.svg` | `upstream-geom-violin-grouping-on-x-and-fill` |
| `geom-violin/narrower-width-5.svg` | `upstream-geom-violin-narrower-width` |
| `geom-violin/scale-area-to-sample-size-c-is-smaller.svg` | `upstream-geom-violin-scale-area-to-sample-size` |
| `geom-violin/styled-quantiles.svg` | `upstream-geom-violin-styled-quantiles` |
| `geom-violin/with-smaller-bandwidth-and-points.svg` | `upstream-geom-violin-with-smaller-bandwidth-and-points` |
| `geom-violin/with-tails-and-points.svg` | `upstream-geom-violin-with-tails-and-points` |
| `guide-axis/axis-guides-basic.svg` | `upstream-guide-axis-axis-guides-basic` |
| `guide-axis/axis-guides-negative-rotation.svg` | `upstream-guide-axis-axis-guides-negative-rotation` |
| `guide-axis/axis-guides-positive-rotation.svg` | `upstream-guide-axis-axis-guides-positive-rotation` |
| `guide-axis/axis-guides-vertical-negative-rotation.svg` | `upstream-guide-axis-axis-guides-vertical-negative-rotation` |
| `guide-axis/axis-guides-vertical-rotation.svg` | `upstream-guide-axis-axis-guides-vertical-rotation` |
| `guide-axis/axis-guides-zero-breaks.svg` | `upstream-guide-axis-axis-guides-zero-breaks` |
| `guide-axis/axis-guides-zero-rotation.svg` | `upstream-guide-axis-axis-guides-zero-rotation` |
| `guide-axis/guide-titles-with-coord-transform.svg` | `upstream-guide-axis-guide-titles-with-coord-transform` |
| `guide-axis/position-guide-titles.svg` | `upstream-guide-axis-position-guide-titles` |
| `guide-axis/thick-axis-lines.svg` | `upstream-guide-axis-thick-axis-lines` |
| `guide-colorbar/combined-colour-and-fill-aesthetics.svg` | `upstream-guide-colorbar-combined-aesthetics` |
| `guide-colorbar/customized-colorbar.svg` | `upstream-guide-colorbar-customized` |
| `guide-colorbar/white-to-red-colorbar-white-ticks-no-frame.svg` | `upstream-guide-colorbar-white-to-red` |
| `guide-legend/horizontal-legend-direction.svg` | `upstream-guide-legend-horizontal-direction` |
| `guide-legend/left-aligned-legend-key.svg` | `upstream-guide-legend-left-aligned-key` |
| `guide-legend/legend-byrow-true.svg` | `upstream-guide-legend-byrow-true` |
| `guide-legend/legend-with-widely-spaced-keys.svg` | `upstream-guide-legend-widely-spaced-keys` |
| `guide-legend/vertical-legend-direction.svg` | `upstream-guide-legend-vertical-direction` |
| `guides/facet-grid-legend-on-bottom.svg` | `upstream-guides-facet-grid-legend-bottom` |
| `guides/facet-grid-legend-on-left.svg` | `upstream-guides-facet-grid-legend-left` |
| `guides/facet-grid-legend-on-right.svg` | `upstream-guides-facet-grid-legend-right` |
| `guides/facet-grid-legend-on-top.svg` | `upstream-guides-facet-grid-legend-top` |
| `guides/facet-wrap-legend-on-bottom.svg` | `upstream-guides-facet-wrap-legend-bottom` |
| `guides/facet-wrap-legend-on-left.svg` | `upstream-guides-facet-wrap-legend-left` |
| `guides/facet-wrap-legend-on-right.svg` | `upstream-guides-facet-wrap-legend-right` |
| `guides/facet-wrap-legend-on-top.svg` | `upstream-guides-facet-wrap-legend-top` |
| `guides/guide-bins-can-remove-axis.svg` | `upstream-guides-guide-bins-remove-axis` |
| `guides/guide-bins-can-show-arrows.svg` | `upstream-guides-guide-bins-show-arrows` |
| `guides/guide-bins-can-show-limits.svg` | `upstream-guides-guide-bins-show-limits` |
| `guides/guide-bins-can-show-ticks-and-transparancy.svg` | `upstream-guides-guide-bins-ticks-transparency` |
| `guides/guide-bins-looks-as-it-should.svg` | `upstream-guides-guide-bins-looks-as-it-should` |
| `guides/guide-bins-sets-labels-when-limits-is-in-breaks.svg` | `upstream-guides-guide-bins-labels-limits-in-breaks` |
| `guides/guide-bins-understands-coinciding-limits-and-bins-2.svg` | `upstream-guides-guide-bins-coinciding-2` |
| `guides/guide-bins-understands-coinciding-limits-and-bins-3.svg` | `upstream-guides-guide-bins-coinciding-3` |
| `guides/guide-bins-understands-coinciding-limits-and-bins.svg` | `upstream-guides-guide-bins-coinciding-1` |
| `guides/guide-bins-work-horizontally.svg` | `upstream-guides-guide-bins-work-horizontally` |
| `guides/guide-colorsteps-sets-labels-when-limits-is-in-breaks.svg` | `upstream-guides-guide-colorsteps-labels-limits-in-breaks` |
| `guides/guide-colorsteps-understands-coinciding-limits-and-bins-2.svg` | `upstream-guides-guide-colorsteps-coinciding-2` |
| `guides/guide-colorsteps-understands-coinciding-limits-and-bins-3.svg` | `upstream-guides-guide-colorsteps-coinciding-3` |
| `guides/guide-colorsteps-understands-coinciding-limits-and-bins.svg` | `upstream-guides-guide-colorsteps-coinciding-1` |
| `guides/guide-coloursteps-can-have-bins-relative-to-binsize.svg` | `upstream-guides-guide-coloursteps-binsize` |
| `guides/guide-coloursteps-can-show-limits.svg` | `upstream-guides-guide-coloursteps-show-limits` |
| `guides/guide-coloursteps-looks-as-it-should.svg` | `upstream-guides-guide-coloursteps-looks-as-it-should` |
| `guides/guide-custom-with-void-theme.svg` | `upstream-guides-guide-custom-with-void-theme` |
| `guides/guide-title-and-text-positioning-and-alignment-via-themes.svg` | `upstream-guides-title-text-positioning-alignment` |
| `guides/horizontal-gap-of-1cm-between-guide-and-guide-text.svg` | `upstream-guides-horizontal-gap-1cm-guide-text` |
| `guides/legend-inside-plot-bottom-left-of-legend-at-center.svg` | `upstream-guides-legend-inside-plot-bottom-left-of-legend-at-center` |
| `guides/legend-inside-plot-bottom-left.svg` | `upstream-guides-legend-inside-plot-bottom-left` |
| `guides/legend-inside-plot-centered.svg` | `upstream-guides-legend-inside-plot-centered` |
| `guides/legend-inside-plot-multiple-positions.svg` | `upstream-guides-legend-inside-plot-multiple-positions` |
| `guides/legend-inside-plot-top-right.svg` | `upstream-guides-legend-inside-plot-top-right` |
| `guides/legend-on-bottom.svg` | `upstream-guides-legend-on-bottom` |
| `guides/legend-on-left.svg` | `upstream-guides-legend-on-left` |
| `guides/legend-on-right.svg` | `upstream-guides-legend-on-right` |
| `guides/legend-on-top.svg` | `upstream-guides-legend-on-top` |
| `guides/legends-with-all-title-justifications.svg` | `upstream-guides-legends-all-title-justifications` |
| `guides/multi-line-guide-title-works.svg` | `upstream-guides-multi-line-guide-title` |
| `guides/old-s3-guide-drawing-a-circle.svg` | `upstream-guides-old-s3-guide-circle` |
| `guides/padding-in-legend-box.svg` | `upstream-guides-padding-in-legend-box` |
| `guides/reversed-guide-bins.svg` | `upstream-guides-reversed-guide-bins` |
| `guides/rotated-guide-titles-and-labels.svg` | `upstream-guides-rotated-guide-titles-labels` |
| `guides/vertical-gap-of-1cm-between-guide-title-and-guide.svg` | `upstream-guides-vertical-gap-1cm-title-guide` |
| `scale_date/dates-along-x-default-breaks.svg` | `upstream-scale-date-dates-along-x-default-breaks` |
| `scale_date/dates-along-y-default-breaks.svg` | `upstream-scale-date-dates-along-y-default-breaks` |
| `scale_date/scale-x-date-breaks-3-weeks.svg` | `upstream-scale-date-scale-x-date-breaks-3-weeks` |
| `scale_date/scale-x-date-breaks-breaks-width-2-weeks.svg` | `upstream-scale-date-scale-x-date-breaks-breaks-width-2-weeks` |
| `scale_date/scale-x-date-labels-label-date-m-d.svg` | `upstream-scale-date-scale-x-date-labels-label-date-m-d` |
| `scale_date/scale-x-date-labels-label-date-w-week.svg` | `upstream-scale-date-scale-x-date-labels-label-date-w-week` |
| `scale_date/scale-y-date-breaks-3-weeks.svg` | `upstream-scale-date-scale-y-date-breaks-3-weeks` |
| `scale_date/scale-y-date-breaks-breaks-width-2-weeks.svg` | `upstream-scale-date-scale-y-date-breaks-breaks-width-2-weeks` |
| `scales-breaks-labels/character.svg` | `upstream-scales-character` |
| `scales-breaks-labels/date.svg` | `upstream-scales-date` |
| `scales-breaks-labels/functional-limits.svg` | `upstream-scales-functional-limits` |
| `scales-breaks-labels/no-alpha-breaks-no-legend.svg` | `upstream-scales-no-alpha-breaks` |
| `scales-breaks-labels/no-colour-breaks-no-legend.svg` | `upstream-scales-no-colour-breaks` |
| `scales-breaks-labels/no-fill-breaks-no-legend.svg` | `upstream-scales-no-fill-breaks` |
| `scales-breaks-labels/no-size-breaks-no-legend.svg` | `upstream-scales-no-size-breaks` |
| `scales-breaks-labels/no-x-breaks.svg` | `upstream-scales-no-x-breaks` |
| `scales-breaks-labels/no-y-breaks.svg` | `upstream-scales-no-y-breaks` |
| `scales-breaks-labels/numeric-exp.svg` | `upstream-scales-numeric-exp` |
| `scales-breaks-labels/numeric-log.svg` | `upstream-scales-numeric-log` |
| `scales-breaks-labels/numeric-polar.svg` | `upstream-scales-numeric-polar` |
| `scales-breaks-labels/numeric.svg` | `upstream-scales-numeric` |
| `theme/axes-styling.svg` | `upstream-theme-axes-styling` |
| `theme/caption-aligned-to-entire-plot.svg` | `upstream-theme-caption-aligned-to-entire-plot` |
| `theme/height-is-3-times-width-2-column-facets.svg` | `upstream-theme-height-is-3-times-width-2-column-facets` |
| `theme/height-is-3-times-width-2-row-facets.svg` | `upstream-theme-height-is-3-times-width-2-row-facets` |
| `theme/height-is-3-times-width-2-wrap-facets.svg` | `upstream-theme-height-is-3-times-width-2-wrap-facets` |
| `theme/height-is-3-times-width-2x2-facets.svg` | `upstream-theme-height-is-3-times-width-2x2-facets` |
| `theme/height-is-3-times-width.svg` | `upstream-theme-height-is-3-times-width` |
| `theme/horizontal-legends-placed-apart.svg` | `upstream-theme-horizontal-legends-placed-apart` |
| `theme/large-margins.svg` | `upstream-theme-large-margins` |
| `theme/large-spacing.svg` | `upstream-theme-large-spacing` |
| `theme/rotated-x-axis-tick-labels.svg` | `upstream-theme-rotated-x-axis-tick-labels` |
| `theme/strip-styling.svg` | `upstream-theme-strip-styling` |
| `theme/theme-bw-large.svg` | `upstream-theme-bw-large` |
| `theme/theme-bw.svg` | `upstream-theme-bw` |
| `theme/theme-classic-large.svg` | `upstream-theme-classic-large` |
| `theme/theme-classic.svg` | `upstream-theme-classic` |
| `theme/theme-dark-large.svg` | `upstream-theme-dark-large` |
| `theme/theme-dark.svg` | `upstream-theme-dark` |
| `theme/theme-gray-large.svg` | `upstream-theme-gray-large` |
| `theme/theme-gray.svg` | `upstream-theme-gray` |
| `theme/theme-light-large.svg` | `upstream-theme-light-large` |
| `theme/theme-light.svg` | `upstream-theme-light` |
| `theme/theme-linedraw-large.svg` | `upstream-theme-linedraw-large` |
| `theme/theme-linedraw.svg` | `upstream-theme-linedraw` |
| `theme/theme-minimal-large.svg` | `upstream-theme-minimal-large` |
| `theme/theme-minimal.svg` | `upstream-theme-minimal` |
| `theme/theme-void-large.svg` | `upstream-theme-void-large` |
| `theme/theme-void.svg` | `upstream-theme-void` |
| `theme/ticks-length.svg` | `upstream-theme-ticks-length` |
| `theme/titles-aligned-to-entire-plot.svg` | `upstream-theme-titles-aligned-to-entire-plot` |
| `theme/width-is-3-times-height.svg` | `upstream-theme-width-is-3-times-height` |

## 已知缺口

### `aes` — 6 条 · SIL-715 · m2-closeout

`aes()` 的 stat 侧参数（`stat_count(width=)` / `aes(alpha=)`）在我们的语法层没有逐条复刻。

<details><summary>快照</summary>

- `aes/alpha-set-in-alpha.svg`
- `aes/alpha-set-in-colour.svg`
- `aes/stat-count-width-0-5.svg`
- `aes/stat-count.svg`
- `aes/stat-identity-width-0-5.svg`
- `aes/stat-identity.svg`

</details>

### `annotate` — 2 条 · SIL-715 · m3

`annotate()` 的边框与线段共形（`annotation_borders()` / `annotation_segment()`）未复刻。

<details><summary>快照</summary>

- `annotate/annotation-borders-utah.svg`
- `annotate/line-matches-points.svg`

</details>

### `coord-cartesian` — 5 条 · SIL-715 · m2-closeout

依赖上游测试共用的 `mtcars` 数据集夹具（32×11），本批次未内联。

<details><summary>快照</summary>

- `coord-cartesian/clip-on-by-default-only-inside-visible.svg`
- `coord-cartesian/clip-turned-off-both-inside-and-outside-visible.svg`
- `coord-cartesian/contract-range.svg`
- `coord-cartesian/expand-range.svg`
- `coord-cartesian/reversed-cartesian-coords.svg`

</details>

### `coord-flip` — 1 条 · SIL-715 · m2-closeout

同 `coord-cartesian`：需要 `mtcars` 夹具与 sec axis 的翻转组合。

<details><summary>快照</summary>

- `coord-flip/turning-off-secondary-title-with-coord-flip.svg`

</details>

### `coord-map` — 2 条 · SIL-715 · m3

`coord_map()` 只做注册与最小可用；mapproj 投影与经纬度变换归 M3-2 空间能力。

<details><summary>快照</summary>

- `coord-map/coord-map-switched-scale-position.svg`
- `coord-map/usa-mercator.svg`

</details>

### `coord-polar` — 11 条 · SIL-715 · m2-closeout

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

### `coord-transform` — 3 条 · SIL-715 · m2-closeout

`coord_trans()` 的 sec axis 与反向组合未逐条复刻。

<details><summary>快照</summary>

- `coord-transform/basic-coord-transform-plot.svg`
- `coord-transform/reversed-transformed-coords.svg`
- `coord-transform/sec-axis-with-coord-transform.svg`

</details>

### `coord_sf` — 9 条 · SIL-715 · m3

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

### `draw-key` — 1 条 · SIL-715 · m2-closeout

依赖 `geom_point(show.legend = c(colour = NA, alpha = FALSE))` 这种逐美学 show.legend 写法，本仓的 `show_legend` 只有布尔。

<details><summary>快照</summary>

- `draw-key/appropriate-colour-key-with-alpha-key-as-lines.svg`

</details>

### `draw-key` — 1 条 · SIL-715 · m2-closeout

依赖 `key_glyph = 'timeseries'` / 'polygon'`；同上。

<details><summary>快照</summary>

- `draw-key/time-series-and-polygon-key-glyphs.svg`

</details>

### `draw-key` — 1 条 · SIL-715 · m2-closeout

依赖 `key_glyph = draw_key_rect` / `draw_key_dotplot`；本仓的图例 key 只走 `Geom.draw()`，没有 `key_glyph`。

<details><summary>快照</summary>

- `draw-key/rectangle-and-dotplot-key-glyphs.svg`

</details>

### `draw-key` — 1 条 · SIL-715 · m2-closeout

依赖 `key_glyph` 自定义函数 + grob 上的 `width` / `height` 属性（2cm key 撑开图例）；本仓还没有 `key_glyph` 覆盖点。

<details><summary>快照</summary>

- `draw-key/circle-glyphs-of-2cm-size.svg`

</details>

### `facet-` — 4 条 · SIL-715 · m2-closeout

省略内轴标签 / 左对齐 strip 的分面布局口径未复刻（SIL-715 #7 的组合矩阵在 M2-S3 另做）。

<details><summary>快照</summary>

- `facet-/facet-grid-with-omitted-inner-axis-labels.svg`
- `facet-/facet-wrap-with-omitted-inner-axis-labels.svg`
- `facet-/left-justified-facet-labels-with-margins.svg`
- `facet-/left-justified-rotated-facet-labels-with-margins.svg`

</details>

### `facet-labels` — 2 条 · SIL-715 · m2-closeout

`labeller` 的 plotmath 解析与 outside 对齐未复刻。

<details><summary>快照</summary>

- `facet-labels/outside-justified-labels.svg`
- `facet-labels/parsed-facet-labels.svg`

</details>

### `facet-layout` — 1 条 · SIL-715 · m2-closeout

非表格布局（`facet_grid` 缺行/列）的轴定位未复刻。

<details><summary>快照</summary>

- `facet-layout/axes-are-positioned-correctly-in-non-table-layout.svg`

</details>

### `facet-strips` — 1 条 · SIL-715 · m2-closeout

`facet_wrap(switch=)` 的 strip 换边未复刻。

<details><summary>快照</summary>

- `facet-strips/switched-facet-strips.svg`

</details>

### `geom-boxplot` — 3 条 · SIL-715 · m2-closeout

箱线图自定义样式 / 异常值颜色 / staples 未逐条复刻。

<details><summary>快照</summary>

- `geom-boxplot/customised-style.svg`
- `geom-boxplot/outlier-colours.svg`
- `geom-boxplot/staples.svg`

</details>

### `geom-curve` — 2 条 · SIL-715 · m2-closeout

`geom_curve()` 的翻转（`coord_flip`）未复刻。

<details><summary>快照</summary>

- `geom-curve/flipped-geom-curve.svg`
- `geom-curve/standard-geom-curve.svg`

</details>

### `geom-hex` — 3 条 · SIL-715 · m2-closeout

`geom_hex()` 与极坐标 / 变换轴组合未复刻。

<details><summary>快照</summary>

- `geom-hex/hex-bin-plot-in-polar-coordinates.svg`
- `geom-hex/hex-bin-plot-with-sqrt-transformed-y.svg`
- `geom-hex/single-hex-bin-with-width-and-height-of-0-1.svg`

</details>

### `geom-hline-vline-abline` — 5 条 · SIL-715 · m2-closeout

hline/vline/abline 在极坐标与 map 坐标下的曲线化未复刻（M3-2 空间 + 极坐标裁剪）。

<details><summary>快照</summary>

- `geom-hline-vline-abline/cartesian-lines-intersect-mid-bars.svg`
- `geom-hline-vline-abline/flipped-lines-intersect-mid-bars.svg`
- `geom-hline-vline-abline/lines-curved-in-azequalarea.svg`
- `geom-hline-vline-abline/polar-lines-intersect-mid-bars.svg`
- `geom-hline-vline-abline/straight-lines-in-mercator.svg`

</details>

### `geom-label` — 1 条 · SIL-715 · m2-closeout

`geom_label()` 的线段参数（`label.size` / `label.padding` 与线段共形）未复刻。

<details><summary>快照</summary>

- `geom-label/geom-label-with-line-parameters.svg`

</details>

### `geom-path` — 5 条 · SIL-715 · m2-closeout

path 的绘制顺序与 NA 线型未逐条复刻。

<details><summary>快照</summary>

- `geom-path/lines-changed-order-should-have-same-appearance.svg`
- `geom-path/lines-colour-changed-order-should-have-same-appearance.svg`
- `geom-path/lines-colour.svg`
- `geom-path/lines.svg`
- `geom-path/na-linetype.svg`

</details>

### `geom-polygon` — 2 条 · SIL-715 · m2-closeout

munched polygon（`coord_munch` 后的闭合多边形）未复刻。

<details><summary>快照</summary>

- `geom-polygon/basic-polygon-plot.svg`
- `geom-polygon/open-and-closed-munched-polygons.svg`

</details>

### `geom-sf` — 10 条 · SIL-715 · m3

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

### `geom-smooth` — 2 条 · SIL-715 · m2-closeout

`geom_smooth()` 的 ribbon 开关未逐条复刻。

<details><summary>快照</summary>

- `geom-smooth/ribbon-turned-off-in-geom-smooth.svg`
- `geom-smooth/ribbon-turned-on-in-geom-smooth.svg`

</details>

### `geom-text` — 1 条 · SIL-715 · m2-closeout

plotmath 表达式标签（`expression()`）未支持。

<details><summary>快照</summary>

- `geom-text/geom-text-with-expressions.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 实测 15%：`guide_axis_stack()` 的两层轴能画（间距 = 主轴刻度长），但叠放后的**轴带宽度**仍按单层算，R 按 `guide_axis_stack` 的 measured gtable 累加。

<details><summary>快照</summary>

- `guide-axis/stacked-axes.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 实测 17.3%：`facet_grid(rows=, scales/space = 'free')` + `reorder(model, hwy)` 的38 个离散水平（均值序已按 R 的 `levels(reorder())` 写死）在逐面板 y 轴带里错位，属 G7 的`facet-` 簇口径，不在轴 guide 这一簇。

<details><summary>快照</summary>

- `guide-axis/align-facet-labels-facets-horizontal.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 实测 17.5%：同上（横向分面 + 90° 标签），同属 `facet-` 簇。

<details><summary>快照</summary>

- `guide-axis/align-facet-labels-facets-vertical.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 实测 2.22%（阈值 2%）：同上——次轴的 `n.dodge` 两条标签行 + R 的空标题行未进版式，面板顶边差 17.3pt；差 0.22 个百分点，不是阈值问题。

<details><summary>快照</summary>

- `guide-axis/guides-specified-in-guides.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 实测 3.05%：`n.dodge = 2` 的竖轴标签在 R 里占两列（26.7pt），本仓的 `plot_layout` 仍按一列（14.7pt）留位，面板左边界差 12pt。

<details><summary>快照</summary>

- `guide-axis/guide-axis-customization.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 实测 3.49%：`check_overlap` 的**标签保留集合**已和上游一致（1/3/5/7/10/12/15/17/20），剩下的是 R 把整组轴当 grid 单元画时的字形/轴线半像素差；再调就到阈值内但会改 `guide_axis` 的公共排版。

<details><summary>快照</summary>

- `guide-axis/axis-guides-check-overlap.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 实测 3.58%：`n.dodge = 2` 的分行位置对，差在长标签（10 位数字）在面板边缘的半像素落点。

<details><summary>快照</summary>

- `guide-axis/axis-guides-text-dodged-into-rows-cols.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 实测 54.9%：`coord_radial()` 下的 `guide_axis_theta(angle=)` 标签锚点（R 的`flip_text_angle()` + 半径 0.45）与我们的极坐标轴差异仍大，见 `docs/notes/coord.md` §12。

<details><summary>快照</summary>

- `guide-axis/guide-axis-theta-with-angle-adapting-to-theta.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 实测 7.65%：`cap=` 的轴线端点已对，但 R 在次轴（top/right）上方额外留了一行空轴标题（17.3pt，`xlab-t` 空行），本仓的版式不占这一行，面板顶边因此高 17.3pt。

<details><summary>快照</summary>

- `guide-axis/axis-guides-with-capped-ends.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 实测 8.71%：直角坐标下的 `axis_theta` 四条轴能画（颜色分开），但 R 的 theta 轴在笛卡尔坐标里退化成带角度的普通轴，标签锚点不同于 `axis_theta` 的极坐标口径。

<details><summary>快照</summary>

- `guide-axis/guide-axis-theta-in-cartesian-coordinates.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 未纳管：`label_math()` 的 plotmath 标签 + 负长度的 `axis.ticks.length.x.top` 已能画，但 `axis.minor.ticks.length.y.right = 5cm` 会把次轴带撑到 5cm，R 的 gtable 与我们的轴带宽度分配不一致（实测 >10%）。

<details><summary>快照</summary>

- `guide-axis/guides-with-minor-ticks.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 未纳管：`transform_compose(transform_log10(), transform_reverse())` 与`coord_transform(x = transform_pseudo_log())` 两个变换都还没有（`scales.py` / `coord.py`把 pseudo_log 记在 M3-2），logticks 本身已能画。

<details><summary>快照</summary>

- `guide-axis/logtick-axes-with-customisation.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

G1b 未纳管：径向坐标下的 `r.sec` / `theta.sec` 叠放仍是 `docs/notes/guide.md` §8.5 记的「报 ValueError / 未做」，两层 theta 轴要在半径上推第二圈（`stack_offset`）。

<details><summary>快照</summary>

- `guide-axis/stacked-radial-axes.svg`

</details>

### `guide-legend` — 1 条 · SIL-715 · m2-closeout

key 尺寸没跟着 `size` / `linewidth` 标度走：R 的 `draw_key` 会把 key 的宽高报回 gtable（17.28pt → 34.02pt），我们固定用 `legend.key.size`（图级 8.1%）。卡在「复数 size 撑开 key 格」这条测量链。

<details><summary>快照</summary>

- `guide-legend/enlarged-guides.svg`

</details>

### `guide-legend` — 1 条 · SIL-715 · m2-closeout

同上（key 格要按 `size` 标度撑开）+ 多行标签下 `legend.key.justification` 的对齐（图级 10.5%）。

<details><summary>快照</summary>

- `guide-legend/legend-key-justification.svg`

</details>

### `guides` — 1 条 · SIL-715 · m2-closeout

空图（没有图层）的版面口径未复刻：R 的 `ggplot()` 没有轴占位，面板直接铺满 plot.margin 内区；我们仍按轴 / 标题占位，面板左边界差 22pt（图级 10.4%）。要先改「无图层 → 无轴占位」这条版式规则。

<details><summary>快照</summary>

- `guides/stylised-guide-custom.svg`

</details>

### `labels` — 6 条 · SIL-715 · m2-closeout

`plot.tag.location`（margin / panel / plot）目前只在主题元素树里，渲染器还没消费；补齐后再纳管 6 条。

<details><summary>快照</summary>

- `labels/defaults.svg`
- `labels/tag-in-margin.svg`
- `labels/tag-in-panel-as-character.svg`
- `labels/tag-in-panel-as-numeric.svg`
- `labels/tag-in-plot-as-character.svg`
- `labels/tag-in-plot-as-numeric.svg`

</details>

### `legend-draw` — 1 条 · SIL-715 · m2-closeout

这条快照不是 ggplot 对象，而是把 17 个 `draw_key_*` 直接拼成 gtable 后画；三文件 case 只接 plot 规格，得先有 `key_glyph` 才能用图例复现同一组 key。

<details><summary>快照</summary>

- `legend-draw/all-legend-keys.svg`

</details>

### `patterns` — 4 条 · SIL-715 · m2-closeout

pattern fill（grid pattern / `tile_pattern()`）未进 SVG 渲染器。

<details><summary>快照</summary>

- `patterns/pattern-fills-no-alpha.svg`
- `patterns/pattern-fills-through-scale.svg`
- `patterns/pattern-fills-with-alpha.svg`
- `patterns/single-pattern-fill.svg`

</details>

### `position-stack` — 1 条 · SIL-715 · m2-closeout

`position_stack()` 的 area 堆叠未复刻。

<details><summary>快照</summary>

- `position-stack/area-stacking.svg`

</details>

### `sec-axis` — 7 条 · SIL-715 · m2-closeout

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

### `stat-align` — 3 条 · SIL-715 · m2-closeout

`stat_align()` 的两段面积 cliff / pos-neg 未复刻。

<details><summary>快照</summary>

- `stat-align/align-two-areas-with-cliff.svg`
- `stat-align/align-two-areas-with-pos-neg-y.svg`
- `stat-align/align-two-areas.svg`

</details>

### `stat-sum` — 3 条 · SIL-715 · m2-closeout

`stat_sum()` 的 crossbar 汇总未复刻。

<details><summary>快照</summary>

- `stat-sum/summary-with-color-and-lines.svg`
- `stat-sum/summary-with-crossbars-manual-grouping.svg`
- `stat-sum/summary-with-crossbars-no-grouping.svg`

</details>

### `theme` — 1 条 · SIL-715 · m2-closeout

`element_point()` 的 `element_grob()` 渲染（`pch = 21` + 逐点 fill），是 `grid.newpage()` + `grid.draw()` 的裸 grob 快照，不走 ggplot 管线。

<details><summary>快照</summary>

- `theme/point-elements.svg`

</details>

### `theme` — 1 条 · SIL-715 · m2-closeout

`element_polygon()` 的 `element_grob()` 渲染（两段 `id` 的 pathgrob），同 `point-elements`，是裸 grob 快照。

<details><summary>快照</summary>

- `theme/polygon-elements.svg`

</details>

### `theme` — 1 条 · SIL-715 · m2-closeout

`legend.key.height = unit(1, 'null')` 是 stretchy key：R 让 key 吃掉 guide-box 的剩余高度，本仓的 `_key_size()` 把 `null` 换算成 0 后直接报错。归口 G1 的 stretchy 版式（SIL-715）。

<details><summary>快照</summary>

- `theme/stretched-vertical-legends.svg`

</details>

### `theme` — 1 条 · SIL-715 · m2-closeout

`legend.spacing.y = unit(1, 'null')` 要在 guide-box 内分配剩余高度；本仓的 `legend_box_layout()` 只按固定 cm 累加（横向的 `spacing.x` 版`horizontal-legends-placed-apart` 已纳管）。

<details><summary>快照</summary>

- `theme/vertical-legends-placed-apart.svg`

</details>

### `theme` — 1 条 · SIL-715 · m2-closeout

`plot.tag` 还没有渲染（R 的 `table_add_tag()` 会为 tag 单开一行），所以整页版式比上游少一行；色板与面板背景已对。修好 tag 后重测，预期进档。

<details><summary>快照</summary>

- `theme/theme-with-inverted-colours.svg`

</details>

### `theme` — 1 条 · SIL-715 · m2-closeout

上游用 `S7::new_class()` 造 `element_text` 子类并覆写 `element_grob()` 画 1cm 方块；Python 侧没有可子类化的 element 渲染协议，属扩展能力。

<details><summary>快照</summary>

- `theme/custom-strip-elements-can-render.svg`

</details>

### `theme` — 1 条 · SIL-715 · m2-closeout

同 `stretched-vertical-legends`：`legend.key.width` 的 `null` 单位未实现。

<details><summary>快照</summary>

- `theme/stretched-horizontal-legends.svg`

</details>

### `theme` — 1 条 · SIL-715 · m2-closeout

需要 `mtcars` 完整夹具（`hp` / `gear` / `wt` 三列本仓还没有内联），且用 `legend.location = 'plot'` 把图例挂在整页而不是面板行；`legend.justification.<side>` 已实现。

<details><summary>快照</summary>

- `theme/legends-at-all-sides-with-justification.svg`

</details>
