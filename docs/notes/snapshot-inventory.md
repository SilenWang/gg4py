# 上游 SVG 快照清单（v4.0.3）

<!-- 生成物：`pixi run snapshots:report`。处置写 `tools/upstream/snapshots.toml`。 -->

- 参考实现：`tidyverse/ggplot2` `v4.0.3` @ `cc1444c10edb87650fbe0cb31d56f0da1a255634`
- 快照总数：**311**（上游 `tests/testthat/_snaps/**/*.svg`）
- 已纳管：**257**（`expected.svg` 与上游快照逐字节相同）
- 已知缺口：**54**（全部按分类归口，见下表）
- 缺口归属：`m2-closeout` **17** 条（M3 开工前归零） / `m3` **37** 条（移交 M3）

## 按簇 burndown

| 簇 | owner | 上游 | 已纳管 | 缺口 |
| --- | --- | ---: | ---: | ---: |
| `geom-sf` | m3 | 10 | 0 | 10 |
| `coord_sf` | m3 | 9 | 0 | 9 |
| `guide-axis` | m2-closeout | 23 | 16 | 7 |
| `theme` | m2-closeout | 39 | 32 | 7 |
| `coord-polar` | m3 | 11 | 7 | 4 |
| `patterns` | m3 | 4 | 0 | 4 |
| `annotate` | m3 | 2 | 0 | 2 |
| `coord-map` | m3 | 2 | 0 | 2 |
| `facet-labels` | m2-closeout | 2 | 0 | 2 |
| `geom-hline-vline-abline` | m2-closeout | 5 | 3 | 2 |
| `facet-` | m2-closeout | 4 | 3 | 1 |
| `geom-text` | m3 | 1 | 0 | 1 |
| `guide-legend` | m2-closeout | 7 | 6 | 1 |
| `guides` | m2-closeout | 45 | 44 | 1 |
| `legend-draw` | m2-closeout | 1 | 0 | 1 |
| `aes` | m2-closeout | 6 | 6 | 0 |
| `coord-cartesian` | m2-closeout | 5 | 5 | 0 |
| `coord-flip` | m2-closeout | 1 | 1 | 0 |
| `coord-transform` | m2-closeout | 3 | 3 | 0 |
| `draw-key` | m2-closeout | 6 | 6 | 0 |
| `facet-layout` | m2-closeout | 1 | 1 | 0 |
| `facet-strips` | m2-closeout | 1 | 1 | 0 |
| `geom-boxplot` | m2-closeout | 3 | 3 | 0 |
| `geom-curve` | m2-closeout | 2 | 2 | 0 |
| `geom-dotplot` | m2-closeout | 35 | 35 | 0 |
| `geom-hex` | m2-closeout | 3 | 3 | 0 |
| `geom-label` | m2-closeout | 1 | 1 | 0 |
| `geom-path` | m2-closeout | 5 | 5 | 0 |
| `geom-polygon` | m2-closeout | 2 | 2 | 0 |
| `geom-raster` | m2-closeout | 12 | 12 | 0 |
| `geom-smooth` | m2-closeout | 2 | 2 | 0 |
| `geom-violin` | m2-closeout | 14 | 14 | 0 |
| `guide-colorbar` | m2-closeout | 3 | 3 | 0 |
| `labels` | m2-closeout | 6 | 6 | 0 |
| `position-stack` | m2-closeout | 1 | 1 | 0 |
| `scale_date` | m2-closeout | 8 | 8 | 0 |
| `scales-breaks-labels` | m2-closeout | 13 | 13 | 0 |
| `sec-axis` | m2-closeout | 7 | 7 | 0 |
| `stat-align` | m2-closeout | 3 | 3 | 0 |
| `stat-sum` | m2-closeout | 3 | 3 | 0 |
| **合计** | — | 311 | 257 | 54 |

口径：`m2-closeout` 的簇是「M2 已宣称但没做到对等」的缺口，必须在 M3 开工前清零（与上游逐字节相同，或落在 2% / 1% 档）；`m3` 的簇移交空间能力 / 版面组合 / `annotate()`，不在本台账里重复计。

## 已纳管（能自动跑）

| 快照 | case |
| --- | --- |
| `aes/alpha-set-in-alpha.svg` | `upstream-aes-alpha-set-in-alpha` |
| `aes/alpha-set-in-colour.svg` | `upstream-aes-alpha-set-in-colour` |
| `aes/stat-count-width-0-5.svg` | `upstream-aes-stat-count-width` |
| `aes/stat-count.svg` | `upstream-aes-stat-count` |
| `aes/stat-identity-width-0-5.svg` | `upstream-aes-stat-identity-width` |
| `aes/stat-identity.svg` | `upstream-aes-stat-identity` |
| `coord-cartesian/clip-on-by-default-only-inside-visible.svg` | `upstream-coord-cartesian-clip-on` |
| `coord-cartesian/clip-turned-off-both-inside-and-outside-visible.svg` | `upstream-coord-cartesian-clip-off` |
| `coord-cartesian/contract-range.svg` | `upstream-coord-cartesian-contract-range` |
| `coord-cartesian/expand-range.svg` | `upstream-coord-cartesian-expand-range` |
| `coord-cartesian/reversed-cartesian-coords.svg` | `upstream-coord-cartesian-reversed` |
| `coord-flip/turning-off-secondary-title-with-coord-flip.svg` | `upstream-coord-flip-sec-title` |
| `coord-polar/racetrack-plot-closed-and-has-center-hole.svg` | `upstream-coord-polar-racetrack-hole` |
| `coord-polar/racetrack-plot-closed-and-no-center-hole.svg` | `upstream-coord-polar-racetrack-no-hole` |
| `coord-polar/rays-circular-arcs-and-spiral-arcs.svg` | `upstream-coord-polar-rays` |
| `coord-polar/reversed-polar-coords.svg` | `upstream-coord-polar-reversed` |
| `coord-polar/rose-plot-with-has-equal-spacing.svg` | `upstream-coord-polar-rose` |
| `coord-polar/secondary-axis-ticks-and-labels.svg` | `upstream-coord-polar-sec-axis` |
| `coord-polar/three-concentric-circles.svg` | `upstream-coord-polar-three-circles` |
| `coord-transform/basic-coord-transform-plot.svg` | `upstream-coord-transform-basic` |
| `coord-transform/reversed-transformed-coords.svg` | `upstream-coord-transform-reversed` |
| `coord-transform/sec-axis-with-coord-transform.svg` | `upstream-coord-transform-sec-axis` |
| `draw-key/appropriate-colour-key-with-alpha-key-as-lines.svg` | `upstream-draw-key-appropriate-colour` |
| `draw-key/circle-glyphs-of-2cm-size.svg` | `upstream-draw-key-circle-2cm` |
| `draw-key/horizontal-boxplot-and-crossbar.svg` | `upstream-draw-key-horizontal-boxplot-crossbar` |
| `draw-key/horizontal-linerange-and-pointrange.svg` | `upstream-draw-key-horizontal-linerange-pointrange` |
| `draw-key/rectangle-and-dotplot-key-glyphs.svg` | `upstream-draw-key-rect-dotplot` |
| `draw-key/time-series-and-polygon-key-glyphs.svg` | `upstream-draw-key-timeseries-polygon` |
| `facet-/facet-grid-with-omitted-inner-axis-labels.svg` | `upstream-facet-facet-grid-with-omitted-inner-axis-labels` |
| `facet-/left-justified-facet-labels-with-margins.svg` | `upstream-facet-left-justified-facet-labels-with-margins` |
| `facet-/left-justified-rotated-facet-labels-with-margins.svg` | `upstream-facet-left-justified-rotated-facet-labels-with-margins` |
| `facet-layout/axes-are-positioned-correctly-in-non-table-layout.svg` | `upstream-facet-layout-axes-are-positioned-correctly-in-non-table-layout` |
| `facet-strips/switched-facet-strips.svg` | `upstream-facet-strips-switched` |
| `geom-boxplot/customised-style.svg` | `upstream-geom-boxplot-customised-style` |
| `geom-boxplot/outlier-colours.svg` | `upstream-geom-boxplot-outlier-colours` |
| `geom-boxplot/staples.svg` | `upstream-geom-boxplot-staples` |
| `geom-curve/flipped-geom-curve.svg` | `upstream-geom-curve-flipped` |
| `geom-curve/standard-geom-curve.svg` | `upstream-geom-curve-standard` |
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
| `geom-hex/hex-bin-plot-in-polar-coordinates.svg` | `upstream-geom-hex-polar` |
| `geom-hex/hex-bin-plot-with-sqrt-transformed-y.svg` | `upstream-geom-hex-sqrt-y` |
| `geom-hex/single-hex-bin-with-width-and-height-of-0-1.svg` | `upstream-geom-hex-single-bin` |
| `geom-hline-vline-abline/cartesian-lines-intersect-mid-bars.svg` | `upstream-geom-hline-vline-cartesian` |
| `geom-hline-vline-abline/flipped-lines-intersect-mid-bars.svg` | `upstream-geom-hline-vline-flipped` |
| `geom-hline-vline-abline/polar-lines-intersect-mid-bars.svg` | `upstream-geom-hline-vline-polar` |
| `geom-label/geom-label-with-line-parameters.svg` | `upstream-geom-label-line-parameters` |
| `geom-path/lines-changed-order-should-have-same-appearance.svg` | `upstream-geom-path-lines-changed-order` |
| `geom-path/lines-colour-changed-order-should-have-same-appearance.svg` | `upstream-geom-path-lines-colour-changed-order` |
| `geom-path/lines-colour.svg` | `upstream-geom-path-lines-colour` |
| `geom-path/lines.svg` | `upstream-geom-path-lines` |
| `geom-path/na-linetype.svg` | `upstream-geom-path-na-linetype` |
| `geom-polygon/basic-polygon-plot.svg` | `upstream-geom-polygon-basic` |
| `geom-polygon/open-and-closed-munched-polygons.svg` | `upstream-geom-polygon-munched` |
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
| `geom-smooth/ribbon-turned-off-in-geom-smooth.svg` | `upstream-geom-smooth-ribbon-off` |
| `geom-smooth/ribbon-turned-on-in-geom-smooth.svg` | `upstream-geom-smooth-ribbon-on` |
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
| `guide-axis/align-facet-labels-facets-vertical.svg` | `upstream-guide-axis-align-facet-labels-vertical` |
| `guide-axis/axis-guides-basic.svg` | `upstream-guide-axis-axis-guides-basic` |
| `guide-axis/axis-guides-negative-rotation.svg` | `upstream-guide-axis-axis-guides-negative-rotation` |
| `guide-axis/axis-guides-positive-rotation.svg` | `upstream-guide-axis-axis-guides-positive-rotation` |
| `guide-axis/axis-guides-vertical-negative-rotation.svg` | `upstream-guide-axis-axis-guides-vertical-negative-rotation` |
| `guide-axis/axis-guides-vertical-rotation.svg` | `upstream-guide-axis-axis-guides-vertical-rotation` |
| `guide-axis/axis-guides-with-capped-ends.svg` | `upstream-guide-axis-capped-ends` |
| `guide-axis/axis-guides-zero-breaks.svg` | `upstream-guide-axis-axis-guides-zero-breaks` |
| `guide-axis/axis-guides-zero-rotation.svg` | `upstream-guide-axis-axis-guides-zero-rotation` |
| `guide-axis/guide-axis-customization.svg` | `upstream-guide-axis-customization` |
| `guide-axis/guide-axis-theta-in-cartesian-coordinates.svg` | `upstream-guide-axis-theta-cartesian` |
| `guide-axis/guide-titles-with-coord-transform.svg` | `upstream-guide-axis-guide-titles-with-coord-transform` |
| `guide-axis/guides-specified-in-guides.svg` | `upstream-guide-axis-guides-specified` |
| `guide-axis/position-guide-titles.svg` | `upstream-guide-axis-position-guide-titles` |
| `guide-axis/stacked-axes.svg` | `upstream-guide-axis-stacked-axes` |
| `guide-axis/thick-axis-lines.svg` | `upstream-guide-axis-thick-axis-lines` |
| `guide-colorbar/combined-colour-and-fill-aesthetics.svg` | `upstream-guide-colorbar-combined-aesthetics` |
| `guide-colorbar/customized-colorbar.svg` | `upstream-guide-colorbar-customized` |
| `guide-colorbar/white-to-red-colorbar-white-ticks-no-frame.svg` | `upstream-guide-colorbar-white-to-red` |
| `guide-legend/enlarged-guides.svg` | `upstream-guide-legend-enlarged-guides` |
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
| `labels/defaults.svg` | `upstream-labels-defaults` |
| `labels/tag-in-margin.svg` | `upstream-labels-tag-in-margin` |
| `labels/tag-in-panel-as-character.svg` | `upstream-labels-tag-in-panel-as-character` |
| `labels/tag-in-panel-as-numeric.svg` | `upstream-labels-tag-in-panel-as-numeric` |
| `labels/tag-in-plot-as-character.svg` | `upstream-labels-tag-in-plot-as-character` |
| `labels/tag-in-plot-as-numeric.svg` | `upstream-labels-tag-in-plot-as-numeric` |
| `position-stack/area-stacking.svg` | `upstream-position-stack-area` |
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
| `sec-axis/sec-axis-custom-transform.svg` | `upstream-sec-axis-custom` |
| `sec-axis/sec-axis-datetime-scale.svg` | `upstream-sec-axis-datetime` |
| `sec-axis/sec-axis-independent-transformations.svg` | `upstream-sec-axis-independent` |
| `sec-axis/sec-axis-monotonicity-test.svg` | `upstream-sec-axis-monotonicity` |
| `sec-axis/sec-axis-sec-power-transform.svg` | `upstream-sec-axis-power` |
| `sec-axis/sec-axis-skewed-transform.svg` | `upstream-sec-axis-skewed` |
| `sec-axis/sec-axis-with-division.svg` | `upstream-sec-axis-with-division` |
| `stat-align/align-two-areas-with-cliff.svg` | `upstream-stat-align-areas-cliff` |
| `stat-align/align-two-areas-with-pos-neg-y.svg` | `upstream-stat-align-areas-pos-neg` |
| `stat-align/align-two-areas.svg` | `upstream-stat-align-areas` |
| `stat-sum/summary-with-color-and-lines.svg` | `upstream-stat-summary-colour-lines` |
| `stat-sum/summary-with-crossbars-manual-grouping.svg` | `upstream-stat-summary-crossbars-grouped` |
| `stat-sum/summary-with-crossbars-no-grouping.svg` | `upstream-stat-summary-crossbars` |
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
| `theme/theme-with-inverted-colours.svg` | `upstream-theme-inverted-colours` |
| `theme/ticks-length.svg` | `upstream-theme-ticks-length` |
| `theme/titles-aligned-to-entire-plot.svg` | `upstream-theme-titles-aligned-to-entire-plot` |
| `theme/width-is-3-times-height.svg` | `upstream-theme-width-is-3-times-height` |

## 已知缺口

### `annotate` — 2 条 · SIL-715 · m3

`annotate()` 的边框与线段共形（`annotation_borders()` / `annotation_segment()`）未复刻。

<details><summary>快照</summary>

- `annotate/annotation-borders-utah.svg`
- `annotate/line-matches-points.svg`

</details>

### `coord-map` — 2 条 · SIL-715 · m3

`coord_map()` 只做注册与最小可用；mapproj 投影与经纬度变换归 M3-2 空间能力。

<details><summary>快照</summary>

- `coord-map/coord-map-switched-scale-position.svg`
- `coord-map/usa-mercator.svg`

</details>

### `coord-polar` — 1 条 · SIL-715 · m3

SIL-793 实测 33.9%：`coord_radial(rotate.angle = TRUE, r.axis.inside = FALSE)` 的 theta 标签要跟着角度旋转、r 轴要落到面板外，`axis.line.theta` / `axis.line.r` 也要按各自颜色画；`guide_axis_theta()` 现在只按 `axis.text.theta` 画在半径 0.45，没有旋转与外侧 r 轴。

<details><summary>快照</summary>

- `coord-polar/bottom-half-circle-with-rotated-text.svg`

</details>

### `coord-polar` — 1 条 · SIL-715 · m3

SIL-793 未纳管：`guides(r.sec = guide_axis(theme = ...), theta.sec = guide_axis_theta(theme = ...))` 要求 guide 自带 `theme=`（逐 guide 主题，`docs/notes/guide.md` 第 8 节）；当前 `guide_axis()` / `guide_axis_theta()` 没有 `theme` 参数，`axis.line.r` / `axis.line.theta` 的颜色也只走面板级主题。

<details><summary>快照</summary>

- `coord-polar/inner-radius-with-all-axes.svg`

</details>

### `coord-polar` — 1 条 · SIL-715 · m3

SIL-793 未纳管：`r.axis.inside = c(90, 225)` 是两个角度的 r 轴，`guides(r.sec = "axis")` 还要在同一角度画第二条；`RadialCoord` 只接受标量 `r_axis_inside`（旋转一条轴），两轴叠放属于 `guide_axis_stack()` 的径向分支（`docs/notes/guide.md` 第 8.5 节记的同一条缺口）。

<details><summary>快照</summary>

- `coord-polar/full-circle-with-axes-placed-at-90-and-225-degrees.svg`

</details>

### `coord-polar` — 1 条 · SIL-715 · m3

SIL-793 未纳管：同 `inner.radius with all axes`（逐 guide `theme=` + 次轴颜色），再加 `theta = "y"` 的 partial arc（`start = 0.25 pi, end = 0.75 pi`）下 theta 标签的锚点。

<details><summary>快照</summary>

- `coord-polar/partial-with-all-axes.svg`

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

### `facet-` — 1 条 · SIL-715 · m2-closeout

SIL-811 未纳管（case `upstream-facet-wrap-omitted-inner-axis-labels` 登记为 `ci = false`）：顶部 / 右侧轴标签已按 R 挪到 strip 之外（2.92% → 2.55%，均值 0.53%），剩下的 2.55% 是行间轴带被 gtable 的 null 行二次扣除——`panel_boxes()` 的分辨高度比表高少 5.48pt，两个面板各矮 2.74pt，第二行的 strip 与面板因此整体上移。卡在 `facet_table.panel_boxes()` 与 `plot_layout()` 谁扣 `x_axis_cm` 的口径，不是阈值问题。

<details><summary>快照</summary>

- `facet-/facet-wrap-with-omitted-inner-axis-labels.svg`

</details>

### `facet-labels` — 1 条 · SIL-715 · m2-closeout

SIL-796：`axis.text.*` 的 hjust / vjust 已接到轴标签锚点（`_anchor()` 之后的显式覆盖），但 `scales = "free"` × 多行轴标签（`"X\nX\nX\nX\nX"`）的外侧对齐仍差 15.5%：free 面板的轴带宽度按每面板标签单独量，R 的 `outside` 口径要求四边标签基线跨面板统一。卡在「自由标度 × 多行标签的跨面板对齐」。

<details><summary>快照</summary>

- `facet-labels/outside-justified-labels.svg`

</details>

### `facet-labels` — 1 条 · SIL-715 · m3

SIL-796：`labeller = label_parsed`（R plotmath 表达式）未实现——`_NAMED_LABELLERS` 只有 label_value / label_both / label_context，label_parsed 会直接报 FacetError；要先把 plotmath 解析成 `alpha ^ beta` 的上标 grob。

<details><summary>快照</summary>

- `facet-labels/parsed-facet-labels.svg`

</details>

### `geom-hline-vline-abline` — 1 条 · SIL-715 · m3

SIL-795 未纳管：`coord_map(projection = "azequalarea", orientation = c(-36.92, 174.6, 0))` 要 mapproj 的 Lambert 方位等积投影 + 以经纬度为中心的旋转，`MapCoord` 目前只做注册与最小可用（不做投影核）。数据侧还要 `maps::map_data("nz")` 的经纬度多边形。归 M3-2。

<details><summary>快照</summary>

- `geom-hline-vline-abline/lines-curved-in-azequalarea.svg`

</details>

### `geom-hline-vline-abline` — 1 条 · SIL-715 · m3

SIL-795 未纳管：同 `lines curved in azequalarea`——`coord_map()` 的 Mercator 投影核（含 `orientation` 与经纬度裁剪）未实现，`MapCoord` 只做最小可用。归 M3-2。

<details><summary>快照</summary>

- `geom-hline-vline-abline/straight-lines-in-mercator.svg`

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

### `geom-text` — 1 条 · SIL-715 · m3

SIL-795 未纳管：`expression(alpha + beta^2, gamma * sqrt(delta))` 走 R 的 plotmath 排版（希腊字母 + 上下标 + 根号笔画，逐 glyph 定位、字号 0.7 倍、根号是 path）。本仓的文本层只吃纯文本，没有 plotmath 解析与排版，`geom_text()` 也没有 `parse = TRUE`。

<details><summary>快照</summary>

- `geom-text/geom-text-with-expressions.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

SIL-817 复核：同 `axis-guides-check-overlap`，是 `test_draw_axis(10, labels = comma(b * 1e9), n.dodge = 2)` 的裸轴 gtable。`n.dodge = 2` 的分行逻辑（`_grid_shape()` + `_visible_labels()`）已能跑，缺的是「不经过 ggplot 版面」的渲染入口。

<details><summary>快照</summary>

- `guide-axis/axis-guides-text-dodged-into-rows-cols.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

SIL-817 复核：这条快照不是 ggplot 对象，而是 `test_draw_axis()` 用 `draw_axis()` 拼四条轴再放进 `gtable(widths = c(0.05, 0.9, 0.05) npc)` 直接 `plot()` 的**裸 gtable**；三文件 case 只接 plot 规格，所以任何 plot 近似（SIL-810 用 20 个断点的面板试过）都多出 36pt/28.8pt 的面板边距。实测近似图 3.62% / 0.45%。卡点与 `all-legend-keys` 同一个：case 契约要先支持「plot.py 返回 gtable / grob」。

<details><summary>快照</summary>

- `guide-axis/axis-guides-check-overlap.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

SIL-817 实测 2.05% / 0.27%（阈值 2% / 1%，差 0.05 个点）。版面已经对齐：15 行面板高 34.78 / 45.65 / 13.04…（= `diff(y.range)` 的 null 权重）、38 个 y 标签、plot/axis 标题位置与 R 逐点相同；8522 个差异像素里 2400 px 是 4 条面板边框的 1 px 落点——本仓 y 轴带宽 115.4418pt vs R 115.47pt（最长标签 `land cruiser wagon 4wd` 的 HarfBuzz 宽度差 0.028pt），0.002–0.03pt 的偏移把 resvg 对 1.07pt 描边的整行覆盖率从 0.75 翻到 0.56（灰度 103 vs 141）。卡在「文本度量与 svglite 对齐到 0.01pt」，不是版面公式。

<details><summary>快照</summary>

- `guide-axis/align-facet-labels-facets-horizontal.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

SIL-817 实测 48.97% / 4.82%：`coord_radial()` 的 full-bleed 版面未复刻——R 的面板是整页的正方形（575.61×575.61：`plot.title` 与两条 axis title 都画在面板内、不占 gtable 行），本仓仍按 `plot.title` / `axis.title` / `axis.text` 行收缩（528.3×528.3，另加 `inner.radius = 0.5` 的环），同心圆半径与 theta 标签的锚点因此整体差 8%–9%。卡在 `plot_layout()` 对 radial 的「面板 = 整页 − 图例」口径 + `guide_axis_theta(angle=)` 的锚点随角度旋转。

<details><summary>快照</summary>

- `guide-axis/guide-axis-theta-with-angle-adapting-to-theta.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m2-closeout

SIL-817 实测仍然报错：`ValueError: guide_axis_theta 暂不支持与 guide_axis_stack 叠放`（`src/ggcore/axis_guide.py:1163` 的 `polar_axis_grobs()`）。R 的径向叠放是两层 theta 轴沿半径各占一圈（`guide_axis_stack("axis_theta", guide_axis_theta(cap = "both"))` 进 `guides(theta=, theta.sec=)`），需要 radial 版的 `stack_offset`（直角坐标由 G8 的 `axis_guide_stack` 累加轴带完成），与 `coord-polar` 剩下 4 条同属 `docs/notes/guide.md` §8.5 的 radial 轴体系。

<details><summary>快照</summary>

- `guide-axis/stacked-radial-axes.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m3

SIL-817：卡点是 plotmath 上标，不是次刻度。参考图的 x 轴标签是 `label_math()`（`10` 用 8.80px、指数用 6.16px 两次落字，见快照 `guides-with-minor-ticks.svg` 的 8 段 text），本仓所有 text 走一条 shaping，画不出上下标；plotmath 已在 SIL-786 由 00b6d04 整块移交 M3。次轴带本身（`axis.minor.ticks.length.y.right = 5cm` 撑开 `axis-r` 列）已经算对，等 plotmath 落地后可直接复测。按 SIL-817 约束作为新能力整条移交 m3。

<details><summary>快照</summary>

- `guide-axis/guides-with-minor-ticks.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m3

SIL-817：卡点是两个复合变换，不是 logticks 本身（`guide_axis_logticks()` 的三档长度已能画）。`scale_y_continuous(transform = transform_compose(transform_log10(), transform_reverse()))` 需要变换对象的组合（`scales.py` 的 `_TRANSFORMS` 只接单个变换，没有 `transform_compose()` 对应物）；`coord_transform(x = transform_pseudo_log())` 的 `pseudo_log` 在 `scales.py:1015` 与 `coord.py:295` 都已登记为 M3-2。按 SIL-817 的约束整条作为新能力移交 m3，不做只支持一半变换的半套实现。

<details><summary>快照</summary>

- `guide-axis/logtick-axes-with-customisation.svg`

</details>

### `guide-legend` — 1 条 · SIL-715 · m2-closeout

SIL-817 实测 3.72% / 1.49%。顺序可以显式对齐（R 没写 `order`，`Guides$build()` 因此按 `order_<rlang::hash>` 排：drat 在前；case 里写成 `guides(size = guide_legend(order = 1), colour = guide_legend(order = 2))` 后降到 2.66% / 1.04%）。剩下的 0.66% / 0.04% 是 `size` 图例的**逐键高度**：R 的三行是 0.6096 / 1.3037 / 1.6389cm（随点径撑开，点 3/4/5 映射到 `range = c(0, 20)`），本仓三行等高（整摞图例 226pt vs R 277pt）；`_key_dimensions()` 只按标度值算 key 宽高，没把点径（`stroke` 外的直径）计入行高。卡在「逐键行高 = max(key 尺寸, 点径 + 2×stroke)」。

<details><summary>快照</summary>

- `guide-legend/legend-key-justification.svg`

</details>

### `guides` — 1 条 · SIL-715 · m2-closeout

SIL-817 实测 5.13% / 0.80%：无图层版面已对（SIL-810），圆也画对了（IR 里 1 个 circle，圆心 (673.6, 296.65) 与 R 的 (680.69, 296.65) 之差就是图例框偏移），差在 `_custom_layout()` 的盒子尺寸——R 用 `grobWidth()` / `grobHeight()`（circleGrob r = 1cm → 2cm），逐列 [0.193 外边距, 0.557 旋转标题列, 2 内容, 0.193]，逐行 [0.193, 0.154, 2, 0.154, 0.193]（标题转 90° 后高 2.31cm，撑开上下各 0.154cm）；本仓退回 `legend.key.size`，图例框 2.89×1.34cm vs R 2.94×2.69cm，面板因此宽 1.1pt、网格线整列错位。卡在「`guide_custom()` 的 grob 包围盒测量（circle / rect / text / gtable / null）+ 标题列按 `angle` 交换宽高」。

<details><summary>快照</summary>

- `guides/stylised-guide-custom.svg`

</details>

### `legend-draw` — 1 条 · SIL-715 · m2-closeout

这条快照不是 ggplot 对象，而是把 17 个 `draw_key_*` 直接拼成 gtable 后画；三文件 case 只接 plot 规格，得先有 `key_glyph` 才能用图例复现同一组 key。

<details><summary>快照</summary>

- `legend-draw/all-legend-keys.svg`

</details>

### `patterns` — 1 条 · SIL-715 · m3

SIL-796：`geom_col(fill = pattern(...))` 已能渲染（`tile_pattern()` 走 IR `TilePattern`），但相位差 31%——`TilePatternSpec.resolve()` 用单节点 bbox 折 npc，R 的 `pattern()` 内容按**图层 bbox** 的 npc（`userSpaceOnUse`）并锚在图层中心；单根 bar 的 bbox 让每根柱的图案各从自身左下角起算。卡在「图案内容坐标系 = 图层包围盒」。

<details><summary>快照</summary>

- `patterns/single-pattern-fill.svg`

</details>

### `patterns` — 1 条 · SIL-715 · m3

SIL-796：`scale_fill_manual(values = rev(patterns))`（值里有 FillSpec）需要标度映射后仍保留 `FillSpec` 并走图层 bbox 解析；当前 `map_scales()` 只保证纯色字符串的映射，图案列表在标度里会被当普通 fill 值落盘。卡在「标度承载 FillSpec」+ 图层级 bbox。

<details><summary>快照</summary>

- `patterns/pattern-fills-through-scale.svg`

</details>

### `patterns` — 1 条 · SIL-715 · m3

SIL-796：同 `single-pattern-fill`——`linearGradient(group = FALSE)` / `radialGradient(group = FALSE)` 与 `pattern()` 的混合列表已能经 `fill=` 传进 geom，但渐变端点 / 图案相位按单节点 bbox 折，R 按图层 bbox。卡在「图层级填充包围盒」。

<details><summary>快照</summary>

- `patterns/pattern-fills-no-alpha.svg`

</details>

### `patterns` — 1 条 · SIL-715 · m3

SIL-796：除上面的图层级 bbox 外，pattern 的 `alpha = c(0.8, 0.6, 0.4, 0.2)` 在 R 里走 `grid::GridMask`（svglite 写 `<mask style='mask-type:alpha'>`）；IR 没有 mask 节点，`alpha_colour()` 对 FillSpec 也不折 alpha（只接受颜色串）。要先给 IR / 两个设备加 alpha mask 原语。

<details><summary>快照</summary>

- `patterns/pattern-fills-with-alpha.svg`

</details>

### `theme` — 1 条 · SIL-715 · m2-closeout

SIL-811 未纳管（case `upstream-theme-legends-all-sides` 登记为 `ci = false`）：实测 3.10% / 1.28%。`mtcars` 七列夹具已内联，`legend.location = "plot"` 与逐边 `legend.justification.<side>` 已接上；差的是同一层同时映射 `colour` / `fill`（数值列 → 连续 fill）/ `shape` / `size` / `alpha` 时点层画不出来（图例只出标题、无键），属多重非位置标度的绘制链。

<details><summary>快照</summary>

- `theme/legends-at-all-sides-with-justification.svg`

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

上游用 `S7::new_class()` 造 `element_text` 子类并覆写 `element_grob()` 画 1cm 方块；Python 侧没有可子类化的 element 渲染协议，属扩展能力。

<details><summary>快照</summary>

- `theme/custom-strip-elements-can-render.svg`

</details>

### `theme` — 1 条 · SIL-715 · m2-closeout

同 `stretched-vertical-legends`：`legend.key.width` 的 `null` 单位未实现。

<details><summary>快照</summary>

- `theme/stretched-horizontal-legends.svg`

</details>
