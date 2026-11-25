# 两条渲染腿的语义对拍（skia SVG × 浏览器 DOM SVG）

- 时间：2026-11-25T14:05:11Z
- 复现：`pixi run viewer:parity:report`
- 案例清单：532 条（`ci = true` 且三文件齐备）· 指纹 `sha256:7c5217b8154c5a79`
- 结论：pass 513 / fail 19 / error 0 / 共 532；最大像素差 0.000%（阈值 0.5%，均值 ≤ 1%）
- 校验：`pixi run viewer:parity:report:check` —— 清单漂移、计数、失败名单任一处与实测对不上即红；手改本文件任何数字都会失败。
- 同一份 IR 分别走 `SkiaSvgDevice`（字形轮廓、`<path>`，见 `docs/notes/device.md`）与查看器的 DOM SVG；两侧文字都轮廓化后比三层：颜色集合（完全相等）、墨迹包围盒（≤ 1 pt）与重心（≤ 1 pt）、墨迹差（≤ 0.5%）。

| case | 族 | 颜色 skia/viewer | 墨迹差 | 包围盒差 | 重心差 | 均值 | 结论 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `annotation-logticks` | `annotation` | 5/5 | 0.000% | 0 pt | 0.40 pt | 0.056% | ✅ pass |
| `coord-equal` | `coord` | 2/2 | 0.000% | 0 pt | 0.12 pt | 0.005% | ✅ pass |
| `coord-flip-bar` | `coord` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `coord-flip-points` | `coord` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.006% | ✅ pass |
| `coord-polar-bar` | `coord` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `coord-polar-facet` | `coord` | 3/3 | 0.000% | 0 pt | 0.09 pt | 0.006% | ✅ pass |
| `coord-polar-theta-y` | `coord` | 2/2 | 0.000% | 0 pt | 0.09 pt | 0.006% | ✅ pass |
| `coord-quickmap` | `coord` | 2/2 | 0.000% | 0 pt | 0.16 pt | 0.006% | ✅ pass |
| `coord-radial-inner` | `coord` | 2/2 | 0.000% | 0 pt | 0.05 pt | 0.006% | ✅ pass |
| `coord-radial-partial` | `coord` | 2/2 | 0.000% | 0 pt | 0.05 pt | 0.006% | ✅ pass |
| `coord-sec-axis` | `coord` | 5/5 | 0.000% | 0 pt | 1.17 pt | 0.034% | ❌ fail |
| `coord-trans-log10` | `coord` | 2/2 | 0.000% | 0 pt | 0.02 pt | 0.007% | ✅ pass |
| `coord-trans-sqrt` | `coord` | 2/2 | 0.000% | 0 pt | 0.18 pt | 0.006% | ✅ pass |
| `ext-custom-geom` | `extension` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `facet-grid-ab` | `facet` | 3/3 | 0.000% | 0 pt | 0.18 pt | 0.009% | ✅ pass |
| `facet-grid-free-fixed` | `facet` | 3/3 | 0.000% | 0 pt | 0.21 pt | 0.018% | ✅ pass |
| `facet-grid-margins` | `facet` | 3/3 | 0.000% | 0 pt | 0.03 pt | 0.036% | ✅ pass |
| `facet-grid-rows-label-both` | `facet` | 3/3 | 0.000% | 0 pt | 0.31 pt | 0.013% | ✅ pass |
| `facet-grid-space-free` | `facet` | 3/3 | 0.000% | 0 pt | 0.03 pt | 0.021% | ✅ pass |
| `facet-wrap-2x2` | `facet` | 3/3 | 0.000% | 0 pt | 0.11 pt | 0.014% | ✅ pass |
| `facet-wrap-free-x` | `facet` | 3/3 | 0.000% | 0 pt | 0.13 pt | 0.010% | ✅ pass |
| `facet-wrap-free-y` | `facet` | 3/3 | 0.000% | 0 pt | 0.25 pt | 0.009% | ✅ pass |
| `facet-wrap-strip-bottom` | `facet` | 8/8 | 0.000% | 0 pt | 0.14 pt | 0.027% | ✅ pass |
| `facet-wrap-strip-left` | `facet` | 8/8 | 0.000% | 0 pt | 0.14 pt | 0.025% | ✅ pass |
| `facet-wrap-strip-right` | `facet` | 8/8 | 0.000% | 0 pt | 0.15 pt | 0.027% | ✅ pass |
| `geom-abline-hline-vline` | `geom-reference` | 6/6 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `geom-area-align` | `geom-area` | 4/4 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-area-horizontal` | `geom-area` | 1/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ❌ fail |
| `geom-area-identity` | `geom-area` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-area-single` | `geom-area` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-area-stacked` | `geom-area` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-bar-dodge` | `geom-bar` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-bar-fill` | `geom-bar` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-bar-horizontal` | `geom-bar` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-bar-stacked` | `geom-bar` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-bin-2d-alias` | `geom-bin2d` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-bin2d-basic` | `geom-bin2d` | 6/6 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-blank-rug` | `geom-blank` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-boxplot-horizontal` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `geom-boxplot-horizontal-auto` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `geom-boxplot-outliers` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.02 pt | 0.003% | ✅ pass |
| `geom-boxplot-precomputed` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-boxplot-varwidth` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-col-basic` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-col-dodge` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-col-horizontal` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-col-identity` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-col-stack` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-contour-basic` | `geom-contour` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-contour-filled` | `geom-contour` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-count-basic` | `geom-count` | 2/2 | 0.000% | 0 pt | 0.02 pt | 0.006% | ✅ pass |
| `geom-crossbar` | `geom-crossbar` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-curve-arrow` | `geom-curve` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `geom-curve-basic` | `geom-curve` | 3/3 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `geom-density-2d-alias` | `geom-density2d` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `geom-density-2d-filled-alias` | `geom-density2d` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-density-basic` | `geom-density` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-density2d-basic` | `geom-density2d` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `geom-density2d-filled` | `geom-density2d` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-dotplot-basic` | `geom-dotplot` | 3/3 | 0.000% | 0 pt | 0.01 pt | 0.006% | ✅ pass |
| `geom-errorbar` | `geom-errorbar` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-errorbarh` | `geom-errorbarh` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-function-basic` | `geom-function` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-hex-basic` | `geom-hex` | 4/4 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-histogram-bins` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-histogram-binwidth` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-histogram-horizontal` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-histogram-identity` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-jitter-basic` | `geom-jitter` | 2/2 | 0.000% | 1 pt | 0.04 pt | 0.008% | ✅ pass |
| `geom-label-basic` | `geom-text` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-line-groups` | `geom-line` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-line-na` | `geom-line` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-line-width` | `geom-line` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `geom-linerange-pointrange` | `geom-linerange` | 3/3 | 0.000% | 0 pt | 0.11 pt | 0.009% | ✅ pass |
| `geom-map` | `geom-map` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-path-groups` | `geom-path` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-path-order` | `geom-path` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-point-alpha` | `geom-point` | 10/10 | 0.000% | 0 pt | 0.30 pt | 0.014% | ✅ pass |
| `geom-point-basic` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.04 pt | 0.017% | ✅ pass |
| `geom-point-discrete` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.12 pt | 0.011% | ✅ pass |
| `geom-point-na` | `geom-point` | 2/2 | 0.000% | 1 pt | 0.03 pt | 0.009% | ✅ pass |
| `geom-point-shapes` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.38 pt | 0.004% | ✅ pass |
| `geom-point-size` | `geom-point` | 2/2 | 0.000% | 1 pt | 0.05 pt | 0.016% | ✅ pass |
| `geom-polygon` | `geom-polygon` | 4/4 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-qq-basic` | `geom-qq` | 2/2 | 0.000% | 0 pt | 0.02 pt | 0.008% | ✅ pass |
| `geom-qq-line-basic` | `geom-qq` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-quantile-basic` | `geom-quantile` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-raster` | `geom-raster` | 1/1 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-rect` | `geom-rect` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-ribbon-outline` | `geom-ribbon` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-segment-arrow` | `geom-segment` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-smooth-default` | `geom-smooth` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-smooth-groups` | `geom-smooth` | 3/3 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `geom-smooth-se` | `geom-smooth` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-smooth-span` | `geom-smooth` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-spoke` | `geom-spoke` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-step` | `geom-step` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-text-align` | `geom-text` | 2/2 | 0.000% | 0 pt | 0.03 pt | 0.000% | ✅ pass |
| `geom-text-cjk` | `geom-text` | 3/3 | 0.000% | 0 pt | 0.03 pt | 0.001% | ✅ pass |
| `geom-text-rotate` | `geom-text` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-text-wrap` | `geom-text` | 2/2 | 0.000% | 0 pt | 0.04 pt | 0.001% | ✅ pass |
| `geom-tile` | `geom-tile` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-violin-basic` | `geom-violin` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `guide-axis-angle` | `guide` | 5/5 | 0.000% | 0 pt | 0.15 pt | 0.031% | ✅ pass |
| `guide-axis-cap` | `guide` | 5/5 | 0.000% | 0 pt | 0.10 pt | 0.028% | ✅ pass |
| `guide-axis-logticks` | `guide` | 5/5 | 0.000% | 0 pt | 0.14 pt | 0.031% | ✅ pass |
| `guide-axis-stack` | `guide` | 5/5 | 0.000% | 0 pt | 0.24 pt | 0.039% | ✅ pass |
| `guide-bins` | `guide` | 15/15 | 0.000% | 0 pt | 0.19 pt | 0.018% | ✅ pass |
| `guide-bins-reverse` | `guide` | 15/15 | 0.000% | 0 pt | 0.17 pt | 0.018% | ✅ pass |
| `guide-colourbar` | `guide` | 244/244 | 0.000% | 0 pt | 0.01 pt | 0.014% | ✅ pass |
| `guide-colourbar-full` | `guide` | 18/19 | 0.000% | 0 pt | 0.08 pt | 0.014% | ❌ fail |
| `guide-colourbar-gradient` | `guide` | 23/23 | 0.000% | 0 pt | 0.02 pt | 0.014% | ✅ pass |
| `guide-coloursteps` | `guide` | 15/15 | 0.000% | 0 pt | 0.02 pt | 0.014% | ✅ pass |
| `guide-legend-inside` | `guide` | 5/5 | 0.000% | 0 pt | 0.02 pt | 0.012% | ✅ pass |
| `guide-legend-merge-fill` | `guide` | 5/5 | 0.000% | 0 pt | 0.01 pt | 0.013% | ✅ pass |
| `guide-legend-merged` | `guide` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.008% | ✅ pass |
| `guide-legend-override` | `guide` | 5/5 | 0.000% | 0 pt | 0.16 pt | 0.009% | ✅ pass |
| `guide-legend-single` | `guide` | 4/4 | 0.000% | 0 pt | 0.18 pt | 0.013% | ✅ pass |
| `guide-legend-top` | `guide` | 5/5 | 0.000% | 0 pt | 0.05 pt | 0.011% | ✅ pass |
| `guide-legend-two` | `guide` | 5/5 | 0.000% | 0 pt | 0.15 pt | 0.022% | ✅ pass |
| `matrix-coord-flip-legend-right-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.49 pt | 0.006% | ✅ pass |
| `matrix-coord-flip-legend-top` | `matrix` | 4/4 | 0.000% | 0 pt | 0.14 pt | 0.015% | ✅ pass |
| `matrix-coord-polar-legend-bottom-horizontal` | `matrix` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.015% | ✅ pass |
| `matrix-coord-polar-legend-left` | `matrix` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.015% | ✅ pass |
| `matrix-coord-radial-legend-bottom` | `matrix` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.015% | ✅ pass |
| `matrix-coord-radial-legend-right-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.31 pt | 0.006% | ✅ pass |
| `matrix-coord-trans-legend-bottom` | `matrix` | 4/4 | 0.000% | 1 pt | 0.06 pt | 0.015% | ✅ pass |
| `matrix-coord-trans-legend-left-horizontal` | `matrix` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.016% | ✅ pass |
| `matrix-facet-grid-coord-cartesian` | `matrix` | 4/4 | 0.000% | 0 pt | 0.22 pt | 0.015% | ✅ pass |
| `matrix-facet-grid-coord-flip` | `matrix` | 4/4 | 0.000% | 1 pt | 0.20 pt | 0.015% | ✅ pass |
| `matrix-facet-grid-coord-polar` | `matrix` | 4/4 | 0.000% | 0 pt | 0.07 pt | 0.015% | ✅ pass |
| `matrix-facet-grid-coord-radial` | `matrix` | 4/4 | 0.000% | 0 pt | 0.07 pt | 0.015% | ✅ pass |
| `matrix-facet-grid-coord-trans` | `matrix` | 4/4 | 0.000% | 0 pt | 0.11 pt | 0.015% | ✅ pass |
| `matrix-facet-grid-flip-legend-left-horizontal` | `matrix` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.016% | ✅ pass |
| `matrix-facet-grid-margins-cartesian-legend-bottom` | `matrix` | 4/4 | 0.000% | 0 pt | 0.07 pt | 0.056% | ✅ pass |
| `matrix-facet-grid-rows-polar-legend-right` | `matrix` | 4/4 | 0.000% | 0 pt | 0.05 pt | 0.015% | ✅ pass |
| `matrix-facet-grid-space-free-flip-legend-right` | `matrix` | 4/4 | 0.000% | 0 pt | 0.20 pt | 0.014% | ✅ pass |
| `matrix-facet-polar-legend-bottom` | `matrix` | 4/4 | 0.000% | 0 pt | 0.08 pt | 0.015% | ✅ pass |
| `matrix-facet-polar-legend-left` | `matrix` | 4/4 | 0.000% | 1 pt | 0.20 pt | 0.014% | ✅ pass |
| `matrix-facet-polar-legend-right` | `matrix` | 4/4 | 0.000% | 0 pt | 0.14 pt | 0.015% | ✅ pass |
| `matrix-facet-polar-legend-top-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.32 pt | 0.005% | ✅ pass |
| `matrix-facet-wrap-coord-cartesian` | `matrix` | 4/4 | 0.000% | 0 pt | 0.28 pt | 0.016% | ✅ pass |
| `matrix-facet-wrap-coord-flip` | `matrix` | 4/4 | 0.000% | 0 pt | 0.07 pt | 0.016% | ✅ pass |
| `matrix-facet-wrap-coord-polar` | `matrix` | 4/4 | 0.000% | 0 pt | 0.18 pt | 0.015% | ✅ pass |
| `matrix-facet-wrap-coord-radial` | `matrix` | 4/4 | 0.000% | 0 pt | 0.18 pt | 0.015% | ✅ pass |
| `matrix-facet-wrap-coord-trans` | `matrix` | 4/4 | 0.000% | 0 pt | 0.12 pt | 0.015% | ✅ pass |
| `matrix-facet-wrap-free-x-flip-legend-right` | `matrix` | 4/4 | 0.000% | 0 pt | 0.14 pt | 0.015% | ✅ pass |
| `matrix-facet-wrap-free-y-polar-legend-bottom` | `matrix` | 4/4 | 0.000% | 0 pt | 0.10 pt | 0.015% | ✅ pass |
| `matrix-facet-wrap-free-y-trans-legend-bottom` | `matrix` | 4/4 | 0.000% | 0 pt | 0.15 pt | 0.015% | ✅ pass |
| `matrix-facet-wrap-radial-legend-bottom` | `matrix` | 4/4 | 0.000% | 0 pt | 0.08 pt | 0.015% | ✅ pass |
| `matrix-facet-wrap-trans-legend-top-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.28 pt | 0.005% | ✅ pass |
| `matrix-legend-bottom-horizontal-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.23 pt | 0.005% | ✅ pass |
| `matrix-legend-bottom-horizontal-single` | `matrix` | 4/4 | 0.000% | 0 pt | 0.09 pt | 0.015% | ✅ pass |
| `matrix-legend-bottom-vertical-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.29 pt | 0.005% | ✅ pass |
| `matrix-legend-bottom-vertical-single` | `matrix` | 4/4 | 0.000% | 0 pt | 0.02 pt | 0.015% | ✅ pass |
| `matrix-legend-left-horizontal-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.29 pt | 0.005% | ✅ pass |
| `matrix-legend-left-horizontal-single` | `matrix` | 4/4 | 0.000% | 0 pt | 0.09 pt | 0.015% | ✅ pass |
| `matrix-legend-left-vertical-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.37 pt | 0.005% | ✅ pass |
| `matrix-legend-left-vertical-single` | `matrix` | 4/4 | 0.000% | 0 pt | 0.06 pt | 0.016% | ✅ pass |
| `matrix-legend-right-horizontal-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.49 pt | 0.005% | ✅ pass |
| `matrix-legend-right-horizontal-single` | `matrix` | 4/4 | 0.000% | 0 pt | 0.09 pt | 0.015% | ✅ pass |
| `matrix-legend-right-vertical-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.26 pt | 0.005% | ✅ pass |
| `matrix-legend-right-vertical-single` | `matrix` | 4/4 | 0.000% | 0 pt | 0.12 pt | 0.014% | ✅ pass |
| `matrix-legend-top-horizontal-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.47 pt | 0.005% | ✅ pass |
| `matrix-legend-top-horizontal-single` | `matrix` | 4/4 | 0.000% | 1 pt | 0.04 pt | 0.015% | ✅ pass |
| `matrix-legend-top-vertical-double` | `matrix` | 4/4 | 0.000% | 0 pt | 0.35 pt | 0.005% | ✅ pass |
| `matrix-legend-top-vertical-single` | `matrix` | 4/4 | 0.000% | 0 pt | 0.15 pt | 0.016% | ✅ pass |
| `matrix-report-default-expand` | `matrix` | 7/7 | 0.000% | 0 pt | 0.10 pt | 0.027% | ✅ pass |
| `matrix-report-facet-grid-grey` | `matrix` | 9/9 | 0.000% | 0 pt | 0.20 pt | 0.034% | ✅ pass |
| `matrix-report-facet-polar-grey` | `matrix` | 9/9 | 0.000% | 0 pt | 0.31 pt | 0.036% | ✅ pass |
| `matrix-report-facet-wrap-grey` | `matrix` | 9/9 | 0.000% | 0 pt | 0.19 pt | 0.036% | ✅ pass |
| `scale-colour-default` | `scale` | 4/4 | 0.000% | 0 pt | 0.21 pt | 0.015% | ✅ pass |
| `scale-colour-gradient` | `scale` | 10/10 | 0.000% | 0 pt | 0.05 pt | 0.017% | ✅ pass |
| `scale-colour-identity` | `scale` | 6/6 | 0.000% | 0 pt | 0.07 pt | 0.013% | ✅ pass |
| `scale-colour-viridis-d` | `scale` | 6/6 | 0.000% | 0 pt | 0.14 pt | 0.020% | ✅ pass |
| `scale-date-implicit-default-breaks` | `scale` | 5/5 | 0.000% | 0 pt | 0.05 pt | 0.006% | ✅ pass |
| `scale-fill-brewer` | `scale` | 4/4 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `scale-limits-drop` | `scale` | 2/2 | 0.000% | 0 pt | 0.25 pt | 0.007% | ✅ pass |
| `scale-linetype-discrete` | `scale` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `scale-size-area` | `scale` | 3/3 | 0.000% | 1 pt | 0.34 pt | 0.029% | ✅ pass |
| `scale-x-log10` | `scale` | 2/2 | 0.000% | 0 pt | 0.10 pt | 0.010% | ✅ pass |
| `scale-y-log10` | `scale` | 2/2 | 0.000% | 0 pt | 0.07 pt | 0.009% | ✅ pass |
| `stat-area-align` | `geom-area` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `stat-boxplot-stat` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.04 pt | 0.003% | ✅ pass |
| `stat-connect-line` | `geom-line` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `stat-density-area` | `geom-area` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `stat-ecdf-line` | `geom-line` | 2/2 | 0.000% | 0 pt | 0.06 pt | 0.000% | ✅ pass |
| `stat-ellipse-path` | `geom-path` | 3/3 | 0.000% | 0 pt | 0.03 pt | 0.007% | ✅ pass |
| `stat-function-line` | `geom-line` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `stat-histogram-bin` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `stat-histogram-horizontal` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `stat-manual-point` | `geom-point` | 2/2 | 0.000% | 0 pt | 0.05 pt | 0.005% | ✅ pass |
| `stat-qq-line` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.02 pt | 0.013% | ✅ pass |
| `stat-qq-point` | `geom-point` | 2/2 | 0.000% | 0 pt | 0.13 pt | 0.013% | ✅ pass |
| `stat-quantile-line` | `geom-line` | 3/3 | 0.000% | 0 pt | 0.02 pt | 0.008% | ✅ pass |
| `stat-smooth-loess` | `geom-smooth` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `stat-sum-count` | `geom-point` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.009% | ✅ pass |
| `stat-summary-bin-point` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.25 pt | 0.010% | ✅ pass |
| `stat-summary-point` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.03 pt | 0.009% | ✅ pass |
| `stat-unique-point` | `geom-point` | 2/2 | 0.000% | 0 pt | 0.05 pt | 0.004% | ✅ pass |
| `stat-ydensity-point` | `geom-point` | 2/2 | 0.000% | 1 pt | 0.85 pt | 0.045% | ✅ pass |
| `text-bold-italic` | `geom-text` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `text-emoji` | `geom-text` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `text-multiline` | `geom-text` | 2/2 | 0.000% | 0 pt | 0.58 pt | 0.004% | ✅ pass |
| `theme-bw-basic` | `theme` | 6/6 | 0.000% | 0 pt | 0.56 pt | 0.024% | ✅ pass |
| `theme-classic-basic` | `theme` | 3/3 | 0.000% | 0 pt | 0.27 pt | 0.030% | ✅ pass |
| `theme-dark-basic` | `theme` | 7/7 | 0.000% | 0 pt | 0.00 pt | 0.006% | ✅ pass |
| `theme-grey-basic` | `theme` | 6/6 | 0.000% | 0 pt | 0.20 pt | 0.026% | ✅ pass |
| `theme-light-basic` | `theme` | 6/6 | 0.000% | 0 pt | 0.02 pt | 0.007% | ✅ pass |
| `theme-linedraw-basic` | `theme` | 3/3 | 0.000% | 0 pt | 0.01 pt | 0.013% | ✅ pass |
| `theme-minimal-basic` | `theme` | 5/5 | 0.000% | 0 pt | 0.08 pt | 0.014% | ✅ pass |
| `theme-test-basic` | `theme` | 5/5 | 0.000% | 0 pt | 0.71 pt | 0.022% | ✅ pass |
| `theme-void-basic` | `theme` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.007% | ✅ pass |
| `upstream-aes-alpha-set-in-alpha` | `geom-point` | 5/5 | 0.000% | 0 pt | 0.37 pt | 0.004% | ✅ pass |
| `upstream-aes-alpha-set-in-colour` | `geom-point` | 5/5 | 0.000% | 0 pt | 0.38 pt | 0.004% | ✅ pass |
| `upstream-aes-stat-count` | `geom-bar` | 5/5 | 0.000% | 0 pt | 0.01 pt | 0.002% | ✅ pass |
| `upstream-aes-stat-count-width` | `geom-bar` | 5/5 | 0.000% | 0 pt | 0.01 pt | 0.002% | ✅ pass |
| `upstream-aes-stat-identity` | `geom-bar` | 5/5 | 0.000% | 0 pt | 0.00 pt | 0.001% | ✅ pass |
| `upstream-aes-stat-identity-width` | `geom-bar` | 5/5 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `upstream-annotate-segment-transform` | `annotate` | 4/4 | 0.000% | 0 pt | 0.06 pt | 0.001% | ✅ pass |
| `upstream-annotate-utah` | `annotate` | 5/5 | 0.000% | 0 pt | 0.86 pt | 0.003% | ✅ pass |
| `upstream-coord-cartesian-clip-off` | `coord` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `upstream-coord-cartesian-clip-on` | `coord` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `upstream-coord-cartesian-contract-range` | `coord` | 4/4 | 0.000% | 0 pt | 0.90 pt | 0.005% | ✅ pass |
| `upstream-coord-cartesian-expand-range` | `coord` | 4/4 | 0.000% | 0 pt | 0.56 pt | 0.008% | ✅ pass |
| `upstream-coord-cartesian-reversed` | `coord` | 4/4 | 0.000% | 0 pt | 0.37 pt | 0.002% | ✅ pass |
| `upstream-coord-flip-sec-title` | `coord` | 6/6 | 0.000% | 0 pt | 0.35 pt | 0.008% | ✅ pass |
| `upstream-coord-map-coord-map-switched-scale-position` | `coord-map` | 5/5 | 0.000% | 0 pt | 0.62 pt | 0.003% | ✅ pass |
| `upstream-coord-map-usa-mercator` | `coord-map` | 5/5 | 0.000% | 0 pt | 0.74 pt | 0.003% | ✅ pass |
| `upstream-coord-polar-axes-at-90-225` | `coord` | 5/5 | 0.000% | 0 pt | 0.00 pt | 0.001% | ✅ pass |
| `upstream-coord-polar-half-circle-rotated-text` | `coord` | 7/7 | 0.000% | 0 pt | 0.04 pt | 0.001% | ✅ pass |
| `upstream-coord-polar-inner-radius-all-axes` | `coord` | 9/9 | 0.000% | 0 pt | 0.12 pt | 0.009% | ✅ pass |
| `upstream-coord-polar-partial-all-axes` | `coord` | 9/9 | 0.000% | 0 pt | 0.07 pt | 0.008% | ✅ pass |
| `upstream-coord-polar-racetrack-hole` | `coord` | 6/6 | 0.000% | 0 pt | 0.01 pt | 0.002% | ✅ pass |
| `upstream-coord-polar-racetrack-no-hole` | `coord` | 6/6 | 0.000% | 0 pt | 0.01 pt | 0.002% | ✅ pass |
| `upstream-coord-polar-rays` | `coord` | 12/12 | 0.000% | 0 pt | 0.58 pt | 0.008% | ✅ pass |
| `upstream-coord-polar-reversed` | `coord` | 4/4 | 0.000% | 0 pt | 0.13 pt | 0.002% | ✅ pass |
| `upstream-coord-polar-rose` | `coord` | 5/5 | 0.000% | 0 pt | 0.02 pt | 0.002% | ✅ pass |
| `upstream-coord-polar-sec-axis` | `coord` | 4/4 | 0.000% | 0 pt | 0.27 pt | 0.003% | ✅ pass |
| `upstream-coord-polar-three-circles` | `coord` | 5/5 | 0.000% | 0 pt | 0.20 pt | 0.002% | ✅ pass |
| `upstream-coord-sf-coord-sf-with-custom-guides` | `coord_sf` | 5/5 | 0.000% | 0 pt | 0.15 pt | 0.006% | ✅ pass |
| `upstream-coord-sf-limits-specified-in-long-lat` | `coord_sf` | 5/5 | 0.000% | 0 pt | 0.89 pt | 0.003% | ✅ pass |
| `upstream-coord-sf-limits-specified-in-projected-coords` | `coord_sf` | 5/5 | 0.000% | 0 pt | 0.90 pt | 0.003% | ✅ pass |
| `upstream-coord-sf-no-breaks` | `coord_sf` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.001% | ✅ pass |
| `upstream-coord-sf-no-panel-grid` | `coord_sf` | 5/5 | 0.000% | 0 pt | 0.06 pt | 0.003% | ✅ pass |
| `upstream-coord-sf-non-sf-geoms-using-long-lat` | `coord_sf` | 5/5 | 0.000% | 0 pt | 0.75 pt | 0.003% | ✅ pass |
| `upstream-coord-sf-non-sf-geoms-using-projected-coords` | `coord_sf` | 5/5 | 0.000% | 0 pt | 0.76 pt | 0.003% | ✅ pass |
| `upstream-coord-sf-reversed-sf-coords` | `coord_sf` | 4/4 | 0.000% | 0 pt | 0.62 pt | 0.004% | ✅ pass |
| `upstream-coord-sf-sf-polygons` | `coord_sf` | 6/6 | 0.000% | 0 pt | 0.11 pt | 0.003% | ✅ pass |
| `upstream-coord-transform-basic` | `coord` | 4/4 | 0.000% | 0 pt | 0.82 pt | 0.019% | ✅ pass |
| `upstream-coord-transform-reversed` | `coord` | 4/4 | 0.000% | 0 pt | 0.42 pt | 0.002% | ✅ pass |
| `upstream-coord-transform-sec-axis` | `coord` | 4/4 | 0.000% | 0 pt | 0.68 pt | 0.023% | ✅ pass |
| `upstream-draw-key-appropriate-colour` | `guide` | 8/8 | 0.000% | 0 pt | 0.66 pt | 0.003% | ✅ pass |
| `upstream-draw-key-circle-2cm` | `guide` | 7/7 | 0.000% | 0 pt | 0.86 pt | 0.008% | ✅ pass |
| `upstream-draw-key-horizontal-boxplot-crossbar` | `guide` | 6/6 | 0.000% | 0 pt | 0.06 pt | 0.003% | ✅ pass |
| `upstream-draw-key-horizontal-linerange-pointrange` | `guide` | 6/6 | 0.000% | 0 pt | 0.55 pt | 0.003% | ✅ pass |
| `upstream-draw-key-rect-dotplot` | `guide` | 7/7 | 0.000% | 0 pt | 0.80 pt | 0.006% | ✅ pass |
| `upstream-draw-key-timeseries-polygon` | `guide` | 7/7 | 0.000% | 0 pt | 0.55 pt | 0.004% | ✅ pass |
| `upstream-facet-facet-grid-with-omitted-inner-axis-labels` | `facet` | 6/6 | 0.000% | 0 pt | 1.18 pt | 0.035% | ❌ fail |
| `upstream-facet-labels-outside-justified-labels` | `facet-labels` | 7/7 | 0.000% | 0 pt | 0.01 pt | 0.003% | ✅ pass |
| `upstream-facet-labels-parsed-facet-labels` | `facet` | 6/6 | 0.000% | 0 pt | 0.58 pt | 0.002% | ✅ pass |
| `upstream-facet-layout-axes-are-positioned-correctly-in-non-table-layout` | `facet` | 6/6 | 0.000% | 0 pt | 0.80 pt | 0.040% | ✅ pass |
| `upstream-facet-left-justified-facet-labels-with-margins` | `facet` | 6/6 | 0.000% | 0 pt | 0.73 pt | 0.006% | ✅ pass |
| `upstream-facet-left-justified-rotated-facet-labels-with-margins` | `facet` | 6/6 | 0.000% | 0 pt | 0.45 pt | 0.006% | ✅ pass |
| `upstream-facet-strips-switched` | `facet` | 6/6 | 0.000% | 0 pt | 0.13 pt | 0.011% | ✅ pass |
| `upstream-facet-wrap-omitted-inner-axis-labels` | `facet` | 6/6 | 0.000% | 0 pt | 0.60 pt | 0.054% | ✅ pass |
| `upstream-geom-boxplot-customised-style` | `geom-boxplot` | 12/12 | 0.000% | 0 pt | 0.26 pt | 0.004% | ✅ pass |
| `upstream-geom-boxplot-outlier-colours` | `geom-boxplot` | 7/7 | 0.000% | 0 pt | 0.35 pt | 0.003% | ✅ pass |
| `upstream-geom-boxplot-staples` | `geom-boxplot` | 7/7 | 0.000% | 0 pt | 0.29 pt | 0.002% | ✅ pass |
| `upstream-geom-curve-flipped` | `geom-curve` | 4/4 | 0.000% | 0 pt | 0.54 pt | 0.003% | ✅ pass |
| `upstream-geom-curve-standard` | `geom-curve` | 4/4 | 0.000% | 0 pt | 0.47 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-2-na-bin-along-y` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-2-na-dotdensity` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-3-stackgroups-bin-y-histodot` | `geom-dotplot` | 11/11 | 0.000% | 0 pt | 0.14 pt | 0.009% | ✅ pass |
| `upstream-geom-dotplot-3-stackgroups-dotdensity-aligned` | `geom-dotplot` | 11/11 | 0.000% | 0 pt | 0.11 pt | 0.020% | ✅ pass |
| `upstream-geom-dotplot-3-stackgroups-histodot` | `geom-dotplot` | 11/11 | 0.000% | 0 pt | 0.11 pt | 0.005% | ✅ pass |
| `upstream-geom-dotplot-basic-dotdensity` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.02 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-bin-along-y-stack-center` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-bin-along-y-stack-centerwhole` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-bin-along-y-stack-centerwhole-histodot` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.07 pt | 0.004% | ✅ pass |
| `upstream-geom-dotplot-bin-x-three-y-groups-stack-centerwhole` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.02 pt | 0.014% | ✅ pass |
| `upstream-geom-dotplot-bin-y-continuous-x-grouping-by-x` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.011% | ✅ pass |
| `upstream-geom-dotplot-bin-y-continuous-x-single-group` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.07 pt | 0.015% | ✅ pass |
| `upstream-geom-dotplot-bin-y-dodged` | `geom-dotplot` | 7/7 | 0.000% | 0 pt | 0.18 pt | 0.009% | ✅ pass |
| `upstream-geom-dotplot-bin-y-dodged-coord-flip` | `geom-dotplot` | 7/7 | 0.000% | 0 pt | 0.09 pt | 0.010% | ✅ pass |
| `upstream-geom-dotplot-bin-y-dodging-3-stackgroups-histodot` | `geom-dotplot` | 9/9 | 0.000% | 0 pt | 0.21 pt | 0.010% | ✅ pass |
| `upstream-geom-dotplot-bin-y-three-x-groups-bins-aligned-across-groups` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.07 pt | 0.010% | ✅ pass |
| `upstream-geom-dotplot-bin-y-three-x-groups-bins-aligned-coord-flip` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.02 pt | 0.008% | ✅ pass |
| `upstream-geom-dotplot-bin-y-three-x-groups-fill-and-dodge` | `geom-dotplot` | 6/6 | 0.000% | 0 pt | 0.25 pt | 0.018% | ✅ pass |
| `upstream-geom-dotplot-bin-y-three-x-groups-stack-centerwhole` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.06 pt | 0.006% | ✅ pass |
| `upstream-geom-dotplot-dotsize-large` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.21 pt | 0.016% | ✅ pass |
| `upstream-geom-dotplot-facets-3-groups-histodot-stackgroups` | `geom-dotplot` | 11/11 | 0.000% | 0 pt | 0.20 pt | 0.007% | ✅ pass |
| `upstream-geom-dotplot-histodot` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.007% | ✅ pass |
| `upstream-geom-dotplot-multiple-groups-bins-aligned` | `geom-dotplot` | 9/9 | 0.000% | 0 pt | 0.18 pt | 0.008% | ✅ pass |
| `upstream-geom-dotplot-multiple-groups-bins-not-aligned` | `geom-dotplot` | 9/9 | 0.000% | 0 pt | 0.17 pt | 0.007% | ✅ pass |
| `upstream-geom-dotplot-stack-center` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-stack-center-coord-flip` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-stack-centerwhole` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-stack-centerwhole-coord-flip` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-stack-down` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.06 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-stack-down-coord-flip` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.11 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-stack-up` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-stack-up-coord-flip` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-stackratio-1-5` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.28 pt | 0.008% | ✅ pass |
| `upstream-geom-dotplot-stackratio-half` | `geom-dotplot` | 4/4 | 0.000% | 0 pt | 0.21 pt | 0.003% | ✅ pass |
| `upstream-geom-dotplot-variable-linetype-size` | `geom-dotplot` | 6/6 | 0.000% | 0 pt | 0.04 pt | 0.010% | ✅ pass |
| `upstream-geom-hex-polar` | `geom-hex` | 246/246 | 0.000% | 0 pt | 0.01 pt | 0.002% | ✅ pass |
| `upstream-geom-hex-single-bin` | `geom-hex` | 246/246 | 0.000% | 0 pt | 0.72 pt | 0.003% | ✅ pass |
| `upstream-geom-hex-sqrt-y` | `geom-hex` | 246/246 | 0.000% | 0 pt | 0.03 pt | 0.004% | ✅ pass |
| `upstream-geom-hline-vline-azequalarea` | `geom-hline` | 4/4 | 0.000% | 0 pt | 0.25 pt | 0.002% | ✅ pass |
| `upstream-geom-hline-vline-cartesian` | `geom-hline` | 8/8 | 0.000% | 0 pt | 0.02 pt | 0.003% | ✅ pass |
| `upstream-geom-hline-vline-flipped` | `geom-hline` | 8/8 | 0.000% | 0 pt | 0.02 pt | 0.003% | ✅ pass |
| `upstream-geom-hline-vline-mercator` | `geom-hline` | 4/4 | 0.000% | 0 pt | 0.19 pt | 0.001% | ✅ pass |
| `upstream-geom-hline-vline-polar` | `geom-hline` | 8/8 | 0.000% | 0 pt | 0.03 pt | 0.003% | ✅ pass |
| `upstream-geom-label-line-parameters` | `geom-label` | 7/7 | 0.000% | 0 pt | 0.61 pt | 0.003% | ✅ pass |
| `upstream-geom-path-lines` | `geom-path` | 4/4 | 0.000% | 0 pt | 0.38 pt | 0.003% | ✅ pass |
| `upstream-geom-path-lines-changed-order` | `geom-path` | 4/4 | 0.000% | 0 pt | 0.42 pt | 0.003% | ✅ pass |
| `upstream-geom-path-lines-colour` | `geom-path` | 10/10 | 0.000% | 0 pt | 0.54 pt | 0.003% | ✅ pass |
| `upstream-geom-path-lines-colour-changed-order` | `geom-path` | 10/10 | 0.000% | 0 pt | 0.58 pt | 0.003% | ✅ pass |
| `upstream-geom-path-na-linetype` | `geom-path` | 4/4 | 0.000% | 0 pt | 0.94 pt | 0.002% | ✅ pass |
| `upstream-geom-polygon-basic` | `geom-polygon` | 4/4 | 0.000% | 0 pt | 0.02 pt | 0.002% | ✅ pass |
| `upstream-geom-polygon-munched` | `geom-polygon` | 5/5 | 0.000% | 0 pt | 0.02 pt | 0.000% | ✅ pass |
| `upstream-geom-raster-1-x-3` | `geom-raster` | 247/247 | 0.000% | 0 pt | 0.01 pt | 0.004% | ✅ pass |
| `upstream-geom-raster-1-x-3-just-0-0` | `geom-raster` | 247/247 | 0.000% | 0 pt | 0.01 pt | 0.004% | ✅ pass |
| `upstream-geom-raster-1-x-3-set-limits` | `geom-raster` | 247/247 | 0.000% | 0 pt | 0.04 pt | 0.004% | ✅ pass |
| `upstream-geom-raster-3-x-1` | `geom-raster` | 247/247 | 0.000% | 0 pt | 0.01 pt | 0.004% | ✅ pass |
| `upstream-geom-raster-3-x-1-just-0-0` | `geom-raster` | 247/247 | 0.000% | 0 pt | 0.01 pt | 0.004% | ✅ pass |
| `upstream-geom-raster-3-x-1-set-limits` | `geom-raster` | 247/247 | 0.000% | 0 pt | 0.03 pt | 0.004% | ✅ pass |
| `upstream-geom-raster-3-x-2` | `geom-raster` | 247/247 | 0.000% | 0 pt | 0.01 pt | 0.004% | ✅ pass |
| `upstream-geom-raster-3-x-2-just-0-0` | `geom-raster` | 247/247 | 0.000% | 0 pt | 0.01 pt | 0.005% | ✅ pass |
| `upstream-geom-raster-3-x-2-set-limits` | `geom-raster` | 247/247 | 0.000% | 0 pt | 0.01 pt | 0.005% | ✅ pass |
| `upstream-geom-raster-discrete-positions` | `geom-raster` | 8/8 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `upstream-geom-raster-irregular-categorical` | `geom-raster` | 6/6 | 0.000% | 0 pt | 0.01 pt | 0.003% | ✅ pass |
| `upstream-geom-raster-rectangle-fallback` | `geom-raster` | 8/8 | 0.000% | 0 pt | 0.03 pt | 0.002% | ✅ pass |
| `upstream-geom-sf-labels-for-north-carolina` | `geom-sf` | 4/4 | 0.000% | 0 pt | 0.60 pt | 0.003% | ✅ pass |
| `upstream-geom-sf-line-legend` | `geom-sf` | 6/6 | 0.000% | 0 pt | 1.14 pt | 0.003% | ❌ fail |
| `upstream-geom-sf-mixed-geometry-types` | `geom-sf` | 6/6 | 0.000% | 0 pt | 0.13 pt | 0.007% | ✅ pass |
| `upstream-geom-sf-north-carolina-county-boundaries` | `geom-sf` | 6/6 | 0.000% | 0 pt | 0.10 pt | 0.004% | ✅ pass |
| `upstream-geom-sf-north-carolina-county-boundaries-with-arrow` | `geom-sf` | 4/4 | 0.000% | 0 pt | 0.53 pt | 0.003% | ✅ pass |
| `upstream-geom-sf-north-carolina-county-boundaries-with-more-than-one-arrow` | `geom-sf` | 4/4 | 0.000% | 0 pt | 0.51 pt | 0.003% | ✅ pass |
| `upstream-geom-sf-point-legend` | `geom-sf` | 6/6 | 0.000% | 0 pt | 1.05 pt | 0.003% | ❌ fail |
| `upstream-geom-sf-polygon-legend` | `geom-sf` | 7/7 | 0.000% | 0 pt | 0.52 pt | 0.003% | ✅ pass |
| `upstream-geom-sf-spatial-points` | `geom-sf` | 4/4 | 0.000% | 0 pt | 0.85 pt | 0.003% | ✅ pass |
| `upstream-geom-sf-texts-for-north-carolina` | `geom-sf` | 4/4 | 0.000% | 0 pt | 0.61 pt | 0.003% | ✅ pass |
| `upstream-geom-smooth-ribbon-off` | `geom-smooth` | 6/6 | 0.000% | 0 pt | 0.56 pt | 0.002% | ✅ pass |
| `upstream-geom-smooth-ribbon-on` | `geom-smooth` | 8/8 | 0.000% | 0 pt | 0.03 pt | 0.002% | ✅ pass |
| `upstream-geom-text-with-expressions` | `geom` | 4/4 | 0.000% | 0 pt | 0.91 pt | 0.003% | ✅ pass |
| `upstream-geom-violin-basic` | `geom-violin` | 4/4 | 0.000% | 0 pt | 0.64 pt | 0.003% | ✅ pass |
| `upstream-geom-violin-continuous-x-axis-many-groups` | `geom-violin` | 4/4 | 0.000% | 0 pt | 0.57 pt | 0.003% | ✅ pass |
| `upstream-geom-violin-continuous-x-axis-single-group` | `geom-violin` | 4/4 | 0.000% | 0 pt | 0.56 pt | 0.003% | ✅ pass |
| `upstream-geom-violin-coord-flip` | `geom-violin` | 4/4 | 0.000% | 0 pt | 0.34 pt | 0.003% | ✅ pass |
| `upstream-geom-violin-coord-polar` | `geom-violin` | 4/4 | 0.000% | 0 pt | 0.52 pt | 0.002% | ✅ pass |
| `upstream-geom-violin-dodging` | `geom-violin` | 7/7 | 0.000% | 0 pt | 0.06 pt | 0.002% | ✅ pass |
| `upstream-geom-violin-dodging-and-coord-flip` | `geom-violin` | 7/7 | 0.000% | 0 pt | 0.04 pt | 0.002% | ✅ pass |
| `upstream-geom-violin-grouping-on-x-and-fill` | `geom-violin` | 6/6 | 0.000% | 0 pt | 0.04 pt | 0.002% | ✅ pass |
| `upstream-geom-violin-grouping-on-x-and-fill-dodge-width` | `geom-violin` | 6/6 | 0.000% | 0 pt | 0.04 pt | 0.002% | ✅ pass |
| `upstream-geom-violin-narrower-width` | `geom-violin` | 4/4 | 0.000% | 0 pt | 0.52 pt | 0.003% | ✅ pass |
| `upstream-geom-violin-scale-area-to-sample-size` | `geom-violin` | 4/4 | 0.000% | 0 pt | 0.50 pt | 0.003% | ✅ pass |
| `upstream-geom-violin-styled-quantiles` | `geom-violin` | 5/5 | 0.000% | 0 pt | 0.45 pt | 0.003% | ✅ pass |
| `upstream-geom-violin-with-smaller-bandwidth-and-points` | `geom-violin` | 4/4 | 0.000% | 0 pt | 0.50 pt | 0.026% | ✅ pass |
| `upstream-geom-violin-with-tails-and-points` | `geom-violin` | 4/4 | 0.000% | 0 pt | 0.37 pt | 0.023% | ✅ pass |
| `upstream-guide-axis-align-facet-labels-horizontal` | `guide` | 6/6 | 0.000% | 0 pt | 0.82 pt | 0.043% | ✅ pass |
| `upstream-guide-axis-align-facet-labels-vertical` | `guide` | 6/6 | 0.000% | 0 pt | 0.93 pt | 0.069% | ✅ pass |
| `upstream-guide-axis-axis-guides-basic` | `guide` | 4/4 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `upstream-guide-axis-axis-guides-negative-rotation` | `guide` | 4/4 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `upstream-guide-axis-axis-guides-positive-rotation` | `guide` | 4/4 | 0.000% | 0 pt | 0.02 pt | 0.001% | ✅ pass |
| `upstream-guide-axis-axis-guides-vertical-negative-rotation` | `guide` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.000% | ✅ pass |
| `upstream-guide-axis-axis-guides-vertical-rotation` | `guide` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.001% | ✅ pass |
| `upstream-guide-axis-axis-guides-zero-breaks` | `guide` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `upstream-guide-axis-axis-guides-zero-rotation` | `guide` | 4/4 | 0.000% | 0 pt | 0.00 pt | 0.001% | ✅ pass |
| `upstream-guide-axis-capped-ends` | `guide` | 5/5 | 0.000% | 0 pt | 0.02 pt | 0.008% | ✅ pass |
| `upstream-guide-axis-check-overlap` | `guide` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.016% | ✅ pass |
| `upstream-guide-axis-customization` | `guide` | 4/4 | 0.000% | 0 pt | 0.83 pt | 0.019% | ✅ pass |
| `upstream-guide-axis-guide-titles-with-coord-transform` | `guide` | 4/4 | 0.000% | 0 pt | 0.06 pt | 0.005% | ✅ pass |
| `upstream-guide-axis-guides-specified` | `guide` | 4/4 | 0.000% | 0 pt | 0.60 pt | 0.020% | ✅ pass |
| `upstream-guide-axis-guides-with-minor-ticks` | `guide` | 6/6 | 0.000% | 0 pt | 0.45 pt | 0.034% | ✅ pass |
| `upstream-guide-axis-logtick-axes-with-customisation` | `guide` | 4/4 | 0.000% | 0 pt | 2.13 pt | 0.025% | ❌ fail |
| `upstream-guide-axis-position-guide-titles` | `guide` | 3/3 | 0.000% | 0 pt | 0.04 pt | 0.001% | ✅ pass |
| `upstream-guide-axis-stacked-axes` | `guide` | 5/5 | 0.000% | 0 pt | 0.03 pt | 0.012% | ✅ pass |
| `upstream-guide-axis-stacked-radial-axes` | `guide-axis` | 5/5 | 0.000% | 0 pt | 0.20 pt | 0.009% | ✅ pass |
| `upstream-guide-axis-text-dodged` | `guide` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.009% | ✅ pass |
| `upstream-guide-axis-theta-angle` | `guide-axis` | 5/5 | 0.000% | 0 pt | 0.06 pt | 0.008% | ✅ pass |
| `upstream-guide-axis-theta-cartesian` | `guide` | 9/9 | 0.000% | 0 pt | 0.03 pt | 0.010% | ✅ pass |
| `upstream-guide-axis-thick-axis-lines` | `guide` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.006% | ✅ pass |
| `upstream-guide-colorbar-combined-aesthetics` | `guide` | 546/546 | 0.000% | 0 pt | 0.60 pt | 0.008% | ✅ pass |
| `upstream-guide-colorbar-customized` | `guide` | 262/262 | 0.000% | 0 pt | 3.06 pt | 0.011% | ❌ fail |
| `upstream-guide-colorbar-white-to-red` | `guide` | 289/289 | 0.000% | 0 pt | 1.13 pt | 0.005% | ❌ fail |
| `upstream-guide-legend-byrow-true` | `guide` | 10/10 | 0.000% | 0 pt | 0.60 pt | 0.002% | ✅ pass |
| `upstream-guide-legend-enlarged-guides` | `guide` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.007% | ✅ pass |
| `upstream-guide-legend-horizontal-direction` | `guide` | 247/247 | 0.000% | 0 pt | 0.67 pt | 0.004% | ✅ pass |
| `upstream-guide-legend-key-justification` | `guide` | 8/8 | 0.000% | 0 pt | 0.09 pt | 0.020% | ✅ pass |
| `upstream-guide-legend-left-aligned-key` | `guide` | 8/8 | 0.000% | 0 pt | 0.06 pt | 0.006% | ✅ pass |
| `upstream-guide-legend-vertical-direction` | `guide` | 247/247 | 0.000% | 0 pt | 0.48 pt | 0.004% | ✅ pass |
| `upstream-guide-legend-widely-spaced-keys` | `guide` | 10/10 | 0.000% | 0 pt | 0.69 pt | 0.007% | ✅ pass |
| `upstream-guides-facet-grid-legend-bottom` | `guides` | 8/8 | 0.000% | 0 pt | 0.09 pt | 0.001% | ✅ pass |
| `upstream-guides-facet-grid-legend-left` | `guides` | 8/8 | 0.000% | 0 pt | 0.08 pt | 0.001% | ✅ pass |
| `upstream-guides-facet-grid-legend-right` | `guides` | 8/8 | 0.000% | 0 pt | 0.11 pt | 0.001% | ✅ pass |
| `upstream-guides-facet-grid-legend-top` | `guides` | 8/8 | 0.000% | 0 pt | 0.11 pt | 0.001% | ✅ pass |
| `upstream-guides-facet-wrap-legend-bottom` | `guides` | 8/8 | 0.000% | 0 pt | 0.11 pt | 0.001% | ✅ pass |
| `upstream-guides-facet-wrap-legend-left` | `guides` | 8/8 | 0.000% | 0 pt | 0.08 pt | 0.001% | ✅ pass |
| `upstream-guides-facet-wrap-legend-right` | `guides` | 8/8 | 0.000% | 0 pt | 0.15 pt | 0.001% | ✅ pass |
| `upstream-guides-facet-wrap-legend-top` | `guides` | 8/8 | 0.000% | 0 pt | 0.13 pt | 0.001% | ✅ pass |
| `upstream-guides-guide-bins-coinciding-1` | `guide` | 9/9 | 0.000% | 0 pt | 0.68 pt | 0.016% | ✅ pass |
| `upstream-guides-guide-bins-coinciding-2` | `guide` | 9/9 | 0.000% | 0 pt | 0.68 pt | 0.016% | ✅ pass |
| `upstream-guides-guide-bins-coinciding-3` | `guide` | 9/9 | 0.000% | 0 pt | 0.69 pt | 0.016% | ✅ pass |
| `upstream-guides-guide-bins-labels-limits-in-breaks` | `guide` | 9/9 | 0.000% | 0 pt | 0.72 pt | 0.016% | ✅ pass |
| `upstream-guides-guide-bins-looks-as-it-should` | `guide` | 4/4 | 0.000% | 0 pt | 0.93 pt | 0.005% | ✅ pass |
| `upstream-guides-guide-bins-remove-axis` | `guide` | 4/4 | 0.000% | 0 pt | 0.89 pt | 0.007% | ✅ pass |
| `upstream-guides-guide-bins-show-arrows` | `guide` | 4/4 | 0.000% | 0 pt | 0.89 pt | 0.007% | ✅ pass |
| `upstream-guides-guide-bins-show-limits` | `guide` | 4/4 | 0.000% | 0 pt | 0.91 pt | 0.007% | ✅ pass |
| `upstream-guides-guide-bins-ticks-transparency` | `guide` | 11/11 | 0.000% | 0 pt | 0.68 pt | 0.003% | ✅ pass |
| `upstream-guides-guide-bins-work-horizontally` | `guide` | 4/4 | 0.000% | 0 pt | 0.86 pt | 0.007% | ✅ pass |
| `upstream-guides-guide-colorsteps-coinciding-1` | `guide` | 246/246 | 0.000% | 0 pt | 0.63 pt | 0.016% | ✅ pass |
| `upstream-guides-guide-colorsteps-coinciding-2` | `guide` | 246/246 | 0.000% | 0 pt | 0.60 pt | 0.016% | ✅ pass |
| `upstream-guides-guide-colorsteps-coinciding-3` | `guide` | 246/246 | 0.000% | 0 pt | 0.62 pt | 0.016% | ✅ pass |
| `upstream-guides-guide-colorsteps-labels-limits-in-breaks` | `guide` | 246/246 | 0.000% | 0 pt | 0.47 pt | 0.016% | ✅ pass |
| `upstream-guides-guide-coloursteps-binsize` | `guide` | 8/8 | 0.000% | 0 pt | 0.74 pt | 0.004% | ✅ pass |
| `upstream-guides-guide-coloursteps-looks-as-it-should` | `guide` | 246/246 | 0.000% | 0 pt | 0.69 pt | 0.004% | ✅ pass |
| `upstream-guides-guide-coloursteps-show-limits` | `guide` | 8/8 | 0.000% | 0 pt | 0.71 pt | 0.004% | ✅ pass |
| `upstream-guides-guide-custom-with-void-theme` | `guide` | 2/2 | 0.000% | 0 pt | 0.09 pt | 0.001% | ✅ pass |
| `upstream-guides-horizontal-gap-1cm-guide-text` | `guide` | 249/249 | 0.000% | 0 pt | 0.66 pt | 0.005% | ✅ pass |
| `upstream-guides-legend-inside-plot-bottom-left` | `guide` | 249/249 | 0.000% | 0 pt | 0.01 pt | 0.003% | ✅ pass |
| `upstream-guides-legend-inside-plot-bottom-left-of-legend-at-center` | `guide` | 249/249 | 0.000% | 0 pt | 0.01 pt | 0.002% | ✅ pass |
| `upstream-guides-legend-inside-plot-centered` | `guide` | 249/249 | 0.000% | 0 pt | 0.01 pt | 0.002% | ✅ pass |
| `upstream-guides-legend-inside-plot-multiple-positions` | `guide` | 249/249 | 0.000% | 0 pt | 0.03 pt | 0.004% | ✅ pass |
| `upstream-guides-legend-inside-plot-top-right` | `guide` | 249/249 | 0.000% | 0 pt | 0.00 pt | 0.003% | ✅ pass |
| `upstream-guides-legend-on-bottom` | `guide` | 6/6 | 0.000% | 0 pt | 0.11 pt | 0.001% | ✅ pass |
| `upstream-guides-legend-on-left` | `guide` | 6/6 | 0.000% | 0 pt | 0.07 pt | 0.000% | ✅ pass |
| `upstream-guides-legend-on-right` | `guide` | 6/6 | 0.000% | 0 pt | 0.16 pt | 0.001% | ✅ pass |
| `upstream-guides-legend-on-top` | `guide` | 6/6 | 0.000% | 0 pt | 0.18 pt | 0.001% | ✅ pass |
| `upstream-guides-legends-all-title-justifications` | `guide` | 8/8 | 0.000% | 0 pt | 0.72 pt | 0.005% | ✅ pass |
| `upstream-guides-multi-line-guide-title` | `guide` | 249/249 | 0.000% | 0 pt | 0.50 pt | 0.005% | ✅ pass |
| `upstream-guides-old-s3-guide-circle` | `guide` | 4/4 | 0.000% | 0 pt | 0.53 pt | 0.009% | ✅ pass |
| `upstream-guides-padding-in-legend-box` | `guide` | 249/249 | 0.000% | 0 pt | 0.01 pt | 0.003% | ✅ pass |
| `upstream-guides-reversed-guide-bins` | `guide` | 10/10 | 0.000% | 0 pt | 0.82 pt | 0.007% | ✅ pass |
| `upstream-guides-rotated-guide-titles-labels` | `guide` | 247/247 | 0.000% | 0 pt | 0.50 pt | 0.007% | ✅ pass |
| `upstream-guides-stylised-guide-custom` | `guide` | 4/4 | 0.000% | 0 pt | 0.00 pt | 0.001% | ✅ pass |
| `upstream-guides-title-text-positioning-alignment` | `guide` | 247/247 | 0.000% | 0 pt | 0.52 pt | 0.006% | ✅ pass |
| `upstream-guides-vertical-gap-1cm-title-guide` | `guide` | 249/249 | 0.000% | 0 pt | 0.80 pt | 0.005% | ✅ pass |
| `upstream-labels-defaults` | `labels` | 4/4 | 0.000% | 0 pt | 0.52 pt | 0.004% | ✅ pass |
| `upstream-labels-tag-in-margin` | `labels` | 5/5 | 0.000% | 0 pt | 0.07 pt | 0.004% | ✅ pass |
| `upstream-labels-tag-in-panel-as-character` | `labels` | 5/5 | 0.000% | 0 pt | 0.04 pt | 0.004% | ✅ pass |
| `upstream-labels-tag-in-panel-as-numeric` | `labels` | 5/5 | 0.000% | 0 pt | 0.04 pt | 0.004% | ✅ pass |
| `upstream-labels-tag-in-plot-as-character` | `labels` | 5/5 | 0.000% | 0 pt | 0.05 pt | 0.004% | ✅ pass |
| `upstream-labels-tag-in-plot-as-numeric` | `labels` | 5/5 | 0.000% | 0 pt | 0.04 pt | 0.004% | ✅ pass |
| `upstream-legend-draw-all-keys` | `guide` | 4/4 | 0.000% | 0 pt | 0.03 pt | 0.002% | ✅ pass |
| `upstream-patterns-pattern-fills-no-alpha` | `patterns` | 4/4 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `upstream-patterns-pattern-fills-through-scale` | `patterns` | 4/4 | 0.000% | 0 pt | 0.01 pt | 0.002% | ✅ pass |
| `upstream-patterns-pattern-fills-with-alpha` | `patterns` | 10/10 | 0.000% | 0 pt | 0.03 pt | 0.001% | ✅ pass |
| `upstream-patterns-single-pattern-fill` | `patterns` | 4/4 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `upstream-position-stack-area` | `geom-area` | 6/6 | 0.000% | 0 pt | 0.03 pt | 0.001% | ✅ pass |
| `upstream-scale-date-dates-along-x-default-breaks` | `scale` | 4/4 | 0.000% | 0 pt | 0.23 pt | 0.004% | ✅ pass |
| `upstream-scale-date-dates-along-y-default-breaks` | `scale` | 4/4 | 0.000% | 0 pt | 0.10 pt | 0.003% | ✅ pass |
| `upstream-scale-date-scale-x-date-breaks-3-weeks` | `scale` | 4/4 | 0.000% | 0 pt | 0.20 pt | 0.005% | ✅ pass |
| `upstream-scale-date-scale-x-date-breaks-breaks-width-2-weeks` | `scale` | 4/4 | 0.000% | 0 pt | 0.21 pt | 0.005% | ✅ pass |
| `upstream-scale-date-scale-x-date-labels-label-date-m-d` | `scale` | 4/4 | 0.000% | 0 pt | 0.22 pt | 0.004% | ✅ pass |
| `upstream-scale-date-scale-x-date-labels-label-date-w-week` | `scale` | 4/4 | 0.000% | 0 pt | 0.39 pt | 0.007% | ✅ pass |
| `upstream-scale-date-scale-y-date-breaks-3-weeks` | `scale` | 4/4 | 0.000% | 0 pt | 0.12 pt | 0.004% | ✅ pass |
| `upstream-scale-date-scale-y-date-breaks-breaks-width-2-weeks` | `scale` | 4/4 | 0.000% | 0 pt | 0.16 pt | 0.004% | ✅ pass |
| `upstream-scales-character` | `scale` | 5/5 | 0.000% | 0 pt | 0.33 pt | 0.002% | ✅ pass |
| `upstream-scales-date` | `scale` | 5/5 | 0.000% | 0 pt | 0.18 pt | 0.002% | ✅ pass |
| `upstream-scales-functional-limits` | `scale` | 7/7 | 0.000% | 0 pt | 0.04 pt | 0.003% | ✅ pass |
| `upstream-scales-no-alpha-breaks` | `scale` | 6/6 | 0.000% | 0 pt | 1.04 pt | 0.003% | ❌ fail |
| `upstream-scales-no-colour-breaks` | `scale` | 7/7 | 0.000% | 0 pt | 0.89 pt | 0.003% | ✅ pass |
| `upstream-scales-no-fill-breaks` | `scale` | 7/7 | 0.000% | 0 pt | 0.94 pt | 0.003% | ✅ pass |
| `upstream-scales-no-size-breaks` | `scale` | 4/4 | 0.000% | 0 pt | 0.95 pt | 0.004% | ✅ pass |
| `upstream-scales-no-x-breaks` | `scale` | 4/4 | 0.000% | 0 pt | 1.03 pt | 0.002% | ❌ fail |
| `upstream-scales-no-y-breaks` | `scale` | 4/4 | 0.000% | 0 pt | 0.95 pt | 0.002% | ✅ pass |
| `upstream-scales-numeric` | `scale` | 5/5 | 0.000% | 0 pt | 0.22 pt | 0.002% | ✅ pass |
| `upstream-scales-numeric-exp` | `scale` | 5/5 | 0.000% | 0 pt | 0.27 pt | 0.003% | ✅ pass |
| `upstream-scales-numeric-log` | `scale` | 5/5 | 0.000% | 0 pt | 0.26 pt | 0.002% | ✅ pass |
| `upstream-scales-numeric-polar` | `scale` | 5/5 | 0.000% | 0 pt | 2.24 pt | 0.022% | ❌ fail |
| `upstream-sec-axis-custom` | `scale` | 2/2 | 0.000% | 0 pt | 0.02 pt | 0.001% | ✅ pass |
| `upstream-sec-axis-datetime` | `scale` | 2/2 | 0.000% | 0 pt | 0.04 pt | 0.001% | ✅ pass |
| `upstream-sec-axis-independent` | `scale` | 2/2 | 0.000% | 0 pt | 0.04 pt | 0.002% | ✅ pass |
| `upstream-sec-axis-monotonicity` | `scale` | 2/2 | 0.000% | 0 pt | 0.04 pt | 0.001% | ✅ pass |
| `upstream-sec-axis-power` | `scale` | 2/2 | 0.000% | 0 pt | 0.12 pt | 0.003% | ✅ pass |
| `upstream-sec-axis-skewed` | `scale` | 2/2 | 0.000% | 0 pt | 0.11 pt | 0.020% | ✅ pass |
| `upstream-sec-axis-with-division` | `scale` | 2/2 | 0.000% | 0 pt | 0.51 pt | 0.028% | ✅ pass |
| `upstream-stat-align-areas` | `geom-area` | 6/6 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `upstream-stat-align-areas-cliff` | `geom-area` | 6/6 | 0.000% | 0 pt | 0.01 pt | 0.002% | ✅ pass |
| `upstream-stat-align-areas-pos-neg` | `geom-area` | 6/6 | 0.000% | 0 pt | 0.02 pt | 0.002% | ✅ pass |
| `upstream-stat-summary-colour-lines` | `geom-point` | 6/6 | 0.000% | 0 pt | 0.61 pt | 0.006% | ✅ pass |
| `upstream-stat-summary-crossbars` | `geom-point` | 4/4 | 0.000% | 0 pt | 0.31 pt | 0.008% | ✅ pass |
| `upstream-stat-summary-crossbars-grouped` | `geom-point` | 4/4 | 0.000% | 0 pt | 0.30 pt | 0.008% | ✅ pass |
| `upstream-theme-axes-styling` | `theme` | 8/8 | 0.000% | 0 pt | 0.02 pt | 0.006% | ❌ fail |
| `upstream-theme-bw` | `theme` | 9/9 | 0.000% | 0 pt | 0.81 pt | 0.003% | ✅ pass |
| `upstream-theme-bw-large` | `theme` | 9/9 | 0.000% | 0 pt | 0.36 pt | 0.008% | ✅ pass |
| `upstream-theme-caption-aligned-to-entire-plot` | `theme` | 10/10 | 0.000% | 0 pt | 0.19 pt | 0.006% | ✅ pass |
| `upstream-theme-classic` | `theme` | 5/5 | 0.000% | 0 pt | 0.86 pt | 0.004% | ✅ pass |
| `upstream-theme-classic-large` | `theme` | 5/5 | 0.000% | 0 pt | 0.35 pt | 0.008% | ✅ pass |
| `upstream-theme-custom-strip-elements` | `theme` | 6/6 | 0.000% | 0 pt | 0.17 pt | 0.006% | ✅ pass |
| `upstream-theme-dark` | `theme` | 10/10 | 0.000% | 0 pt | 0.00 pt | 0.001% | ✅ pass |
| `upstream-theme-dark-large` | `theme` | 10/10 | 0.000% | 0 pt | 0.04 pt | 0.007% | ✅ pass |
| `upstream-theme-gray` | `theme` | 9/9 | 0.000% | 0 pt | 0.09 pt | 0.004% | ✅ pass |
| `upstream-theme-gray-large` | `theme` | 9/9 | 0.000% | 0 pt | 0.22 pt | 0.009% | ✅ pass |
| `upstream-theme-height-is-3-times-width` | `theme` | 4/4 | 0.000% | 0 pt | 1.63 pt | 0.004% | ❌ fail |
| `upstream-theme-height-is-3-times-width-2-column-facets` | `theme` | 6/6 | 0.000% | 0 pt | 1.01 pt | 0.004% | ❌ fail |
| `upstream-theme-height-is-3-times-width-2-row-facets` | `theme` | 6/6 | 0.000% | 0 pt | 0.58 pt | 0.005% | ✅ pass |
| `upstream-theme-height-is-3-times-width-2-wrap-facets` | `theme` | 6/6 | 0.000% | 0 pt | 1.02 pt | 0.004% | ❌ fail |
| `upstream-theme-height-is-3-times-width-2x2-facets` | `theme` | 6/6 | 0.000% | 0 pt | 0.68 pt | 0.006% | ✅ pass |
| `upstream-theme-horizontal-legends-placed-apart` | `theme` | 9/9 | 0.000% | 0 pt | 0.07 pt | 0.003% | ✅ pass |
| `upstream-theme-inverted-colours` | `theme` | 10/10 | 0.000% | 0 pt | 0.01 pt | 0.021% | ✅ pass |
| `upstream-theme-large-margins` | `theme` | 9/9 | 0.000% | 0 pt | 0.07 pt | 0.003% | ✅ pass |
| `upstream-theme-large-spacing` | `theme` | 9/9 | 0.000% | 0 pt | 0.24 pt | 0.007% | ✅ pass |
| `upstream-theme-legends-all-sides` | `theme` | 280/280 | 0.000% | 0 pt | 0.60 pt | 0.007% | ✅ pass |
| `upstream-theme-light` | `theme` | 7/7 | 0.000% | 0 pt | 0.02 pt | 0.001% | ✅ pass |
| `upstream-theme-light-large` | `theme` | 7/7 | 0.000% | 0 pt | 0.22 pt | 0.004% | ✅ pass |
| `upstream-theme-linedraw` | `theme` | 4/4 | 0.000% | 0 pt | 0.04 pt | 0.001% | ✅ pass |
| `upstream-theme-linedraw-large` | `theme` | 4/4 | 0.000% | 0 pt | 0.27 pt | 0.009% | ✅ pass |
| `upstream-theme-minimal` | `theme` | 7/7 | 0.000% | 0 pt | 0.15 pt | 0.001% | ✅ pass |
| `upstream-theme-minimal-large` | `theme` | 7/7 | 0.000% | 0 pt | 0.06 pt | 0.002% | ✅ pass |
| `upstream-theme-point-elements` | `theme` | 7/7 | 0.000% | 0 pt | 0.58 pt | 0.005% | ❌ fail |
| `upstream-theme-polygon-elements` | `theme` | 4/4 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `upstream-theme-rotated-x-axis-tick-labels` | `theme` | 5/5 | 0.000% | 0 pt | 0.05 pt | 0.003% | ✅ pass |
| `upstream-theme-stretched-horizontal-legends` | `theme` | 247/247 | 0.000% | 0 pt | 0.51 pt | 0.004% | ✅ pass |
| `upstream-theme-stretched-vertical-legends` | `theme` | 247/247 | 0.000% | 0 pt | 0.48 pt | 0.005% | ✅ pass |
| `upstream-theme-strip-styling` | `theme` | 8/8 | 0.000% | 0 pt | 0.13 pt | 0.006% | ❌ fail |
| `upstream-theme-ticks-length` | `theme` | 4/4 | 0.000% | 0 pt | 1.78 pt | 0.008% | ❌ fail |
| `upstream-theme-titles-aligned-to-entire-plot` | `theme` | 10/10 | 0.000% | 0 pt | 0.19 pt | 0.006% | ✅ pass |
| `upstream-theme-vertical-legends-placed-apart` | `theme` | 9/9 | 0.000% | 0 pt | 0.07 pt | 0.003% | ✅ pass |
| `upstream-theme-void` | `theme` | 4/4 | 0.000% | 0 pt | 0.60 pt | 0.001% | ✅ pass |
| `upstream-theme-void-large` | `theme` | 4/4 | 0.000% | 0 pt | 0.39 pt | 0.001% | ✅ pass |
| `upstream-theme-width-is-3-times-height` | `theme` | 4/4 | 0.000% | 0 pt | 0.68 pt | 0.003% | ✅ pass |
| `viewer-alpha-fill` | `geom-col` | 5/5 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `viewer-alpha-overlap` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `viewer-gradient-linear` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `viewer-gradient-radial` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `viewer-gradient-stops-alpha` | `geom-col` | 5/5 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `viewer-linetype-all` | `geom-line` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.003% | ✅ pass |
| `viewer-pattern` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `viewer-pch-all` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.19 pt | 0.108% | ✅ pass |

## 未通过

### `coord-sec-axis`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.17 pt

### `geom-area-horizontal`

- 结论：fail；涂色集合不一致
- viewer 多出：#4c78a8 @ 1

### `guide-colourbar-full`

- 结论：fail；涂色集合不一致
- viewer 多出：#3366cc @ 1

### `upstream-facet-facet-grid-with-omitted-inner-axis-labels`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.18 pt

### `upstream-geom-sf-line-legend`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.14 pt

### `upstream-geom-sf-point-legend`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.05 pt

### `upstream-guide-axis-logtick-axes-with-customisation`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 2.13 pt

### `upstream-guide-colorbar-customized`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 3.06 pt；涂色集合不一致
- skia 有、viewer 缺：lime @ 1
- viewer 多出：#00ff00 @ 1

### `upstream-guide-colorbar-white-to-red`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.13 pt

### `upstream-scales-no-alpha-breaks`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.04 pt

### `upstream-scales-no-x-breaks`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.03 pt

### `upstream-scales-numeric-polar`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 2.24 pt

### `upstream-theme-axes-styling`

- 结论：fail；涂色集合不一致
- skia 有、viewer 缺：lime @ 1; yellow @ 1
- viewer 多出：#00ff00 @ 1; #ffff00 @ 1

### `upstream-theme-height-is-3-times-width`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.63 pt

### `upstream-theme-height-is-3-times-width-2-column-facets`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.01 pt

### `upstream-theme-height-is-3-times-width-2-wrap-facets`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.02 pt

### `upstream-theme-point-elements`

- 结论：fail；涂色集合不一致
- skia 有、viewer 缺：gray @ 1
- viewer 多出：#808080 @ 1

### `upstream-theme-strip-styling`

- 结论：fail；涂色集合不一致
- skia 有、viewer 缺：lime @ 1
- viewer 多出：#00ff00 @ 1

### `upstream-theme-ticks-length`

- 结论：fail；墨迹包围盒差 0.00 pt / 重心差 1.78 pt

## 机读摘要

`pixi run viewer:parity:report:check` 只比这一块（并与上面的表格交叉校验）：手改任何计数、失败名单或清单指纹，门禁都会变红。

```json
{
  "signature": "viewer-parity/2",
  "generated_at": "2026-11-25T14:05:11Z",
  "command": "pixi run viewer:parity:report",
  "inventory": {
    "cases": 532,
    "sha256": "7c5217b8154c5a79a826c51842e3efbda1bd47911eb92b20da14448a95601913"
  },
  "counts": {
    "pass": 513,
    "fail": 19,
    "error": 0
  },
  "failures": [
    {
      "case": "coord-sec-axis",
      "family": "coord",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.17 pt"
    },
    {
      "case": "geom-area-horizontal",
      "family": "geom-area",
      "status": "fail",
      "reason": "涂色集合不一致"
    },
    {
      "case": "guide-colourbar-full",
      "family": "guide",
      "status": "fail",
      "reason": "涂色集合不一致"
    },
    {
      "case": "upstream-facet-facet-grid-with-omitted-inner-axis-labels",
      "family": "facet",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.18 pt"
    },
    {
      "case": "upstream-geom-sf-line-legend",
      "family": "geom-sf",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.14 pt"
    },
    {
      "case": "upstream-geom-sf-point-legend",
      "family": "geom-sf",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.05 pt"
    },
    {
      "case": "upstream-guide-axis-logtick-axes-with-customisation",
      "family": "guide",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 2.13 pt"
    },
    {
      "case": "upstream-guide-colorbar-customized",
      "family": "guide",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 3.06 pt；涂色集合不一致"
    },
    {
      "case": "upstream-guide-colorbar-white-to-red",
      "family": "guide",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.13 pt"
    },
    {
      "case": "upstream-scales-no-alpha-breaks",
      "family": "scale",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.04 pt"
    },
    {
      "case": "upstream-scales-no-x-breaks",
      "family": "scale",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.03 pt"
    },
    {
      "case": "upstream-scales-numeric-polar",
      "family": "scale",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 2.24 pt"
    },
    {
      "case": "upstream-theme-axes-styling",
      "family": "theme",
      "status": "fail",
      "reason": "涂色集合不一致"
    },
    {
      "case": "upstream-theme-height-is-3-times-width",
      "family": "theme",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.63 pt"
    },
    {
      "case": "upstream-theme-height-is-3-times-width-2-column-facets",
      "family": "theme",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.01 pt"
    },
    {
      "case": "upstream-theme-height-is-3-times-width-2-wrap-facets",
      "family": "theme",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.02 pt"
    },
    {
      "case": "upstream-theme-point-elements",
      "family": "theme",
      "status": "fail",
      "reason": "涂色集合不一致"
    },
    {
      "case": "upstream-theme-strip-styling",
      "family": "theme",
      "status": "fail",
      "reason": "涂色集合不一致"
    },
    {
      "case": "upstream-theme-ticks-length",
      "family": "theme",
      "status": "fail",
      "reason": "墨迹包围盒差 0.00 pt / 重心差 1.78 pt"
    }
  ]
}
```

## 口径

- **颜色集合**：两侧所有已绘制元素的最终涂色（属性 + 继承 + SVG 缺省值），归一成 `#rrggbb` × opacity；按集合比、不计元素个数——skia 每个字形一条路径，查看器一条文本一行。线宽 / 虚线不进这一层（skia 会把虚线展开成填充多边形，见 `docs/notes/device.md`），由像素差兜住。
- **墨迹包围盒 / 重心**：PNG 上非白像素的四条边逐边 ≤ 1 pt（抗锯齿边缘的一档），按亮度加权的墨量重心 ≤ 0.5 pt（整体位移）。
- **墨迹差**：两侧 PNG 的二值墨迹（任一通道 < 250）的对称差占比，带 1 px 形态学容差——同一形状的两种 SVG 表达只差边缘抗锯齿那一档。**均值**沿用 `ggdiff` 的全通道平均差（≤ 1%），保证墨迹内部的颜色强度一致。
