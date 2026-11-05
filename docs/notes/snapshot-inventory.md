# 上游 SVG 快照清单（v4.0.3）

<!-- 生成物：`pixi run snapshots:report`。处置写 `tools/upstream/snapshots.toml`。 -->

- 参考实现：`tidyverse/ggplot2` `v4.0.3` @ `cc1444c10edb87650fbe0cb31d56f0da1a255634`
- 快照总数：**311**（上游 `tests/testthat/_snaps/**/*.svg`）
- 已纳管：**295**（`expected.svg` 与上游快照逐字节相同）
- 已知缺口：**16**（全部按分类归口，见下表）
- 缺口归属：`m2-closeout` **0** 条（M3 开工前归零） / `m3` **16** 条（移交 M3）

## 按簇 burndown

| 簇 | owner | 上游 | 已纳管 | 缺口 |
| --- | --- | ---: | ---: | ---: |
| `coord-polar` | m3 | 11 | 7 | 4 |
| `guide-axis` | m3 | 23 | 19 | 4 |
| `patterns` | m3 | 4 | 1 | 3 |
| `geom-hline-vline-abline` | m3 | 5 | 3 | 2 |
| `coord_sf` | m3 | 9 | 8 | 1 |
| `facet-labels` | m3 | 2 | 1 | 1 |
| `geom-text` | m3 | 1 | 0 | 1 |
| `aes` | m2-closeout | 6 | 6 | 0 |
| `annotate` | m3 | 2 | 2 | 0 |
| `coord-cartesian` | m2-closeout | 5 | 5 | 0 |
| `coord-flip` | m2-closeout | 1 | 1 | 0 |
| `coord-map` | m3 | 2 | 2 | 0 |
| `coord-transform` | m2-closeout | 3 | 3 | 0 |
| `draw-key` | m2-closeout | 6 | 6 | 0 |
| `facet-` | m2-closeout | 4 | 4 | 0 |
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
| `geom-sf` | m3 | 10 | 10 | 0 |
| `geom-smooth` | m2-closeout | 2 | 2 | 0 |
| `geom-violin` | m2-closeout | 14 | 14 | 0 |
| `guide-colorbar` | m2-closeout | 3 | 3 | 0 |
| `guide-legend` | m2-closeout | 7 | 7 | 0 |
| `guides` | m2-closeout | 45 | 45 | 0 |
| `labels` | m2-closeout | 6 | 6 | 0 |
| `legend-draw` | m2-closeout | 1 | 1 | 0 |
| `position-stack` | m2-closeout | 1 | 1 | 0 |
| `scale_date` | m2-closeout | 8 | 8 | 0 |
| `scales-breaks-labels` | m2-closeout | 13 | 13 | 0 |
| `sec-axis` | m2-closeout | 7 | 7 | 0 |
| `stat-align` | m2-closeout | 3 | 3 | 0 |
| `stat-sum` | m2-closeout | 3 | 3 | 0 |
| `theme` | m2-closeout | 39 | 39 | 0 |
| **合计** | — | 311 | 295 | 16 |

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
| `annotate/annotation-borders-utah.svg` | `upstream-annotate-utah` |
| `annotate/line-matches-points.svg` | `upstream-annotate-segment-transform` |
| `coord-cartesian/clip-on-by-default-only-inside-visible.svg` | `upstream-coord-cartesian-clip-on` |
| `coord-cartesian/clip-turned-off-both-inside-and-outside-visible.svg` | `upstream-coord-cartesian-clip-off` |
| `coord-cartesian/contract-range.svg` | `upstream-coord-cartesian-contract-range` |
| `coord-cartesian/expand-range.svg` | `upstream-coord-cartesian-expand-range` |
| `coord-cartesian/reversed-cartesian-coords.svg` | `upstream-coord-cartesian-reversed` |
| `coord-flip/turning-off-secondary-title-with-coord-flip.svg` | `upstream-coord-flip-sec-title` |
| `coord-map/coord-map-switched-scale-position.svg` | `upstream-coord-map-coord-map-switched-scale-position` |
| `coord-map/usa-mercator.svg` | `upstream-coord-map-usa-mercator` |
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
| `coord_sf/limits-specified-in-long-lat.svg` | `upstream-coord-sf-limits-specified-in-long-lat` |
| `coord_sf/limits-specified-in-projected-coords.svg` | `upstream-coord-sf-limits-specified-in-projected-coords` |
| `coord_sf/no-breaks.svg` | `upstream-coord-sf-no-breaks` |
| `coord_sf/no-panel-grid.svg` | `upstream-coord-sf-no-panel-grid` |
| `coord_sf/non-sf-geoms-using-long-lat.svg` | `upstream-coord-sf-non-sf-geoms-using-long-lat` |
| `coord_sf/non-sf-geoms-using-projected-coords.svg` | `upstream-coord-sf-non-sf-geoms-using-projected-coords` |
| `coord_sf/reversed-sf-coords.svg` | `upstream-coord-sf-reversed-sf-coords` |
| `coord_sf/sf-polygons.svg` | `upstream-coord-sf-sf-polygons` |
| `draw-key/appropriate-colour-key-with-alpha-key-as-lines.svg` | `upstream-draw-key-appropriate-colour` |
| `draw-key/circle-glyphs-of-2cm-size.svg` | `upstream-draw-key-circle-2cm` |
| `draw-key/horizontal-boxplot-and-crossbar.svg` | `upstream-draw-key-horizontal-boxplot-crossbar` |
| `draw-key/horizontal-linerange-and-pointrange.svg` | `upstream-draw-key-horizontal-linerange-pointrange` |
| `draw-key/rectangle-and-dotplot-key-glyphs.svg` | `upstream-draw-key-rect-dotplot` |
| `draw-key/time-series-and-polygon-key-glyphs.svg` | `upstream-draw-key-timeseries-polygon` |
| `facet-/facet-grid-with-omitted-inner-axis-labels.svg` | `upstream-facet-facet-grid-with-omitted-inner-axis-labels` |
| `facet-/facet-wrap-with-omitted-inner-axis-labels.svg` | `upstream-facet-wrap-omitted-inner-axis-labels` |
| `facet-/left-justified-facet-labels-with-margins.svg` | `upstream-facet-left-justified-facet-labels-with-margins` |
| `facet-/left-justified-rotated-facet-labels-with-margins.svg` | `upstream-facet-left-justified-rotated-facet-labels-with-margins` |
| `facet-labels/outside-justified-labels.svg` | `upstream-facet-labels-outside-justified-labels` |
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
| `geom-sf/geom-sf-line-legend.svg` | `upstream-geom-sf-line-legend` |
| `geom-sf/geom-sf-point-legend.svg` | `upstream-geom-sf-point-legend` |
| `geom-sf/geom-sf-polygon-legend.svg` | `upstream-geom-sf-polygon-legend` |
| `geom-sf/labels-for-north-carolina.svg` | `upstream-geom-sf-labels-for-north-carolina` |
| `geom-sf/mixed-geometry-types.svg` | `upstream-geom-sf-mixed-geometry-types` |
| `geom-sf/north-carolina-county-boundaries-with-arrow.svg` | `upstream-geom-sf-north-carolina-county-boundaries-with-arrow` |
| `geom-sf/north-carolina-county-boundaries-with-more-than-one-arrow.svg` | `upstream-geom-sf-north-carolina-county-boundaries-with-more-than-one-arrow` |
| `geom-sf/north-carolina-county-boundaries.svg` | `upstream-geom-sf-north-carolina-county-boundaries` |
| `geom-sf/spatial-points.svg` | `upstream-geom-sf-spatial-points` |
| `geom-sf/texts-for-north-carolina.svg` | `upstream-geom-sf-texts-for-north-carolina` |
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
| `guide-axis/align-facet-labels-facets-horizontal.svg` | `upstream-guide-axis-align-facet-labels-horizontal` |
| `guide-axis/align-facet-labels-facets-vertical.svg` | `upstream-guide-axis-align-facet-labels-vertical` |
| `guide-axis/axis-guides-basic.svg` | `upstream-guide-axis-axis-guides-basic` |
| `guide-axis/axis-guides-check-overlap.svg` | `upstream-guide-axis-check-overlap` |
| `guide-axis/axis-guides-negative-rotation.svg` | `upstream-guide-axis-axis-guides-negative-rotation` |
| `guide-axis/axis-guides-positive-rotation.svg` | `upstream-guide-axis-axis-guides-positive-rotation` |
| `guide-axis/axis-guides-text-dodged-into-rows-cols.svg` | `upstream-guide-axis-text-dodged` |
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
| `guide-legend/legend-key-justification.svg` | `upstream-guide-legend-key-justification` |
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
| `guides/stylised-guide-custom.svg` | `upstream-guides-stylised-guide-custom` |
| `guides/vertical-gap-of-1cm-between-guide-title-and-guide.svg` | `upstream-guides-vertical-gap-1cm-title-guide` |
| `labels/defaults.svg` | `upstream-labels-defaults` |
| `labels/tag-in-margin.svg` | `upstream-labels-tag-in-margin` |
| `labels/tag-in-panel-as-character.svg` | `upstream-labels-tag-in-panel-as-character` |
| `labels/tag-in-panel-as-numeric.svg` | `upstream-labels-tag-in-panel-as-numeric` |
| `labels/tag-in-plot-as-character.svg` | `upstream-labels-tag-in-plot-as-character` |
| `labels/tag-in-plot-as-numeric.svg` | `upstream-labels-tag-in-plot-as-numeric` |
| `legend-draw/all-legend-keys.svg` | `upstream-legend-draw-all-keys` |
| `patterns/single-pattern-fill.svg` | `upstream-patterns-single-pattern-fill` |
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
| `theme/custom-strip-elements-can-render.svg` | `upstream-theme-custom-strip-elements` |
| `theme/height-is-3-times-width-2-column-facets.svg` | `upstream-theme-height-is-3-times-width-2-column-facets` |
| `theme/height-is-3-times-width-2-row-facets.svg` | `upstream-theme-height-is-3-times-width-2-row-facets` |
| `theme/height-is-3-times-width-2-wrap-facets.svg` | `upstream-theme-height-is-3-times-width-2-wrap-facets` |
| `theme/height-is-3-times-width-2x2-facets.svg` | `upstream-theme-height-is-3-times-width-2x2-facets` |
| `theme/height-is-3-times-width.svg` | `upstream-theme-height-is-3-times-width` |
| `theme/horizontal-legends-placed-apart.svg` | `upstream-theme-horizontal-legends-placed-apart` |
| `theme/large-margins.svg` | `upstream-theme-large-margins` |
| `theme/large-spacing.svg` | `upstream-theme-large-spacing` |
| `theme/legends-at-all-sides-with-justification.svg` | `upstream-theme-legends-all-sides` |
| `theme/point-elements.svg` | `upstream-theme-point-elements` |
| `theme/polygon-elements.svg` | `upstream-theme-polygon-elements` |
| `theme/rotated-x-axis-tick-labels.svg` | `upstream-theme-rotated-x-axis-tick-labels` |
| `theme/stretched-horizontal-legends.svg` | `upstream-theme-stretched-horizontal-legends` |
| `theme/stretched-vertical-legends.svg` | `upstream-theme-stretched-vertical-legends` |
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
| `theme/vertical-legends-placed-apart.svg` | `upstream-theme-vertical-legends-placed-apart` |
| `theme/width-is-3-times-height.svg` | `upstream-theme-width-is-3-times-height` |

## 已知缺口

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

### `coord_sf` — 1 条 · SIL-715 · m3

SIL-823 纳管 8/9 条（sf-polygons / no-grid / no-breaks / reversed / 4 条 3347 投影与 limits）；剩 `coord-sf-with-custom-guides` 是 plotmath 度数表达式 + `guide_none(angle)` / `n.dodge` 的自定义 guide 组合，版面差 2.85%（节点间 ≤ 2%），见 docs/notes/sf.md 的已知差异。

<details><summary>快照</summary>

- `coord_sf/coord-sf-with-custom-guides.svg`

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

### `geom-text` — 1 条 · SIL-715 · m3

SIL-795 未纳管：`expression(alpha + beta^2, gamma * sqrt(delta))` 走 R 的 plotmath 排版（希腊字母 + 上下标 + 根号笔画，逐 glyph 定位、字号 0.7 倍、根号是 path）。本仓的文本层只吃纯文本，没有 plotmath 解析与排版，`geom_text()` 也没有 `parse = TRUE`。

<details><summary>快照</summary>

- `geom-text/geom-text-with-expressions.svg`

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

### `guide-axis` — 1 条 · SIL-715 · m3

SIL-820 复核（实测 48.7% / 4.76%，与 SIL-817 的 48.97% 同因）：`coord_radial()` 是**整页正方形面板**——参考快照的 `plot.background` 是 575.61×576（`plot.title`、`xlab`/`ylab`、theta 标签全部画在面板内，不占 gtable 行列），本仓仍按 `plot.title` / `axis.title` / `axis.text` 行收缩成 18.64cm 的正方形并居中，同心圆半径与 theta 标签锚点整体错位 8%–9%。这不是一处公式错，而是 `docs/notes/guide.md` §8.5 的 radial 版面子系统：`plot_layout()` 要为 radial 走「面板 = 整页 − 图例、标题画在面板里」的第二条口径（`geom/scene.py`，牵动现有的 theme/facet 版面断言），`polar_axis_grobs()` 要补 theta 轴线 / 刻度 / `cap` / 随角度旋转的锚点（`axis_guide.py`），再叠上本条与 `stacked-radial-axes` 的 `guide_axis_stack('axis_theta', …)` 半径偏移。估工：**3–4 个工作日**（版面 1.5–2 天 + theta 轴 1 天 + 叠放 0.5 天 + 6 条 coord-polar/radial 快照回归 0.5–1 天），且要新增 radial 版面的单测。SIL-820 判断应整块重做；按任务约束**不自行改 owner**，等 leader 决定留在 M2 还是移交 m3。

<details><summary>快照</summary>

- `guide-axis/guide-axis-theta-with-angle-adapting-to-theta.svg`

</details>

### `guide-axis` — 1 条 · SIL-715 · m3

SIL-820 复核：与 `guide-axis-theta-with-angle-adapting-to-theta` 是**同一个 radial 版面子系统**，两条要一起做才有意义（单独叠放做完，面板仍是收缩版式，快照照样红）。原因与估工见 `guide-axis-theta-with-angle-adapting-to-theta` 那一条。

<details><summary>快照</summary>

- `guide-axis/stacked-radial-axes.svg`

</details>

### `patterns` — 1 条 · SIL-715 · m3

SIL-796：`scale_fill_manual(values = rev(patterns))`（值里有 FillSpec）需要标度映射后仍保留 `FillSpec` 并走图层 bbox 解析；当前 `map_scales()` 只保证纯色字符串的映射，图案列表在标度里会被当普通 fill 值落盘。卡在「标度承载 FillSpec」+ 图层级 bbox。

<details><summary>快照</summary>

- `patterns/pattern-fills-through-scale.svg`

</details>

### `patterns` — 1 条 · SIL-715 · m3

SIL-796：除上面的图层级 bbox 外，pattern 的 `alpha = c(0.8, 0.6, 0.4, 0.2)` 在 R 里走 `grid::GridMask`（svglite 写 `<mask style='mask-type:alpha'>`）；IR 没有 mask 节点，`alpha_colour()` 对 FillSpec 也不折 alpha（只接受颜色串）。要先给 IR / 两个设备加 alpha mask 原语。

<details><summary>快照</summary>

- `patterns/pattern-fills-with-alpha.svg`

</details>

### `patterns` — 1 条 · SIL-715 · m3

SIL-833 复核：`fill = list(linearGradient(group = FALSE), radialGradient(group = FALSE), pattern(...), "black")` 是**逐行**的 FillSpec 列表。图层填充包围盒已经做完（`layer_tag` + `Scene.to_ir_scene()` 取并集），但 `build.finish()` 把 FillSpec 挡在数据列之外（`Column` 没有 object kind），逐行混合列表仍落不进 IR——要先给数据列一个「填充规格」的承载方式（按行拆节点或 IR 加逐行 fill）。

<details><summary>快照</summary>

- `patterns/pattern-fills-no-alpha.svg`

</details>
