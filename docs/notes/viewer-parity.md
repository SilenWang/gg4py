# 两条渲染腿的语义对拍（skia SVG × 浏览器 DOM SVG）

- 时间：2026-11-03T04:48:11Z
- 复现：`pixi run viewer:parity`
- 结论：pass 82 / 82；最大像素差 0.238%（阈值 0.5%，均值 ≤ 1%）
- 同一份 IR 分别走 `SkiaSvgDevice`（字形轮廓、`<path>`，见 `docs/notes/device.md`）与查看器的 DOM SVG；两侧文字都轮廓化后比三层：颜色集合（完全相等）、墨迹包围盒（≤ 1 pt）与重心（≤ 1 pt）、墨迹差（≤ 0.5%）。

| case | 族 | 颜色 skia/viewer | 墨迹差 | 包围盒差 | 重心差 | 均值 | 结论 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `coord-equal` | `coord` | 2/2 | 0.000% | 0 pt | 0.12 pt | 0.005% | ✅ pass |
| `coord-flip-bar` | `coord` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `coord-flip-points` | `coord` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.006% | ✅ pass |
| `coord-polar-bar` | `coord` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `coord-polar-facet` | `coord` | 3/3 | 0.000% | 0 pt | 0.09 pt | 0.006% | ✅ pass |
| `coord-polar-theta-y` | `coord` | 2/2 | 0.000% | 0 pt | 0.09 pt | 0.006% | ✅ pass |
| `coord-quickmap` | `coord` | 2/2 | 0.000% | 0 pt | 0.16 pt | 0.006% | ✅ pass |
| `coord-radial-inner` | `coord` | 2/2 | 0.000% | 0 pt | 0.05 pt | 0.006% | ✅ pass |
| `coord-radial-partial` | `coord` | 2/2 | 0.000% | 0 pt | 0.05 pt | 0.006% | ✅ pass |
| `coord-sec-axis` | `coord` | 5/5 | 0.000% | 0 pt | 0.26 pt | 0.008% | ✅ pass |
| `coord-trans-log10` | `coord` | 2/2 | 0.000% | 0 pt | 0.02 pt | 0.007% | ✅ pass |
| `coord-trans-sqrt` | `coord` | 2/2 | 0.000% | 0 pt | 0.18 pt | 0.006% | ✅ pass |
| `facet-grid-ab` | `facet` | 3/3 | 0.000% | 0 pt | 0.05 pt | 0.009% | ✅ pass |
| `facet-wrap-2x2` | `facet` | 3/3 | 0.000% | 0 pt | 0.11 pt | 0.014% | ✅ pass |
| `facet-wrap-free-x` | `facet` | 3/3 | 0.000% | 0 pt | 0.13 pt | 0.010% | ✅ pass |
| `facet-wrap-free-y` | `facet` | 3/3 | 0.000% | 0 pt | 0.25 pt | 0.009% | ✅ pass |
| `geom-area-align` | `geom-area` | 4/4 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-area-identity` | `geom-area` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-area-single` | `geom-area` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-area-stacked` | `geom-area` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-bar-dodge` | `geom-bar` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-bar-fill` | `geom-bar` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-bar-horizontal` | `geom-bar` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-bar-stacked` | `geom-bar` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-boxplot-horizontal` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `geom-boxplot-outliers` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.02 pt | 0.003% | ✅ pass |
| `geom-boxplot-precomputed` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-boxplot-varwidth` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-col-basic` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-col-dodge` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-col-horizontal` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-col-identity` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-col-stack` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-curve-basic` | `geom-curve` | 3/3 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `geom-histogram-bins` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-histogram-binwidth` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-histogram-horizontal` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-histogram-identity` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-line-groups` | `geom-line` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-line-na` | `geom-line` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-line-width` | `geom-line` | 2/2 | 0.000% | 0 pt | 0.02 pt | 0.000% | ✅ pass |
| `geom-path-groups` | `geom-path` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-path-order` | `geom-path` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-point-alpha` | `geom-point` | 10/10 | 0.000% | 0 pt | 0.30 pt | 0.014% | ✅ pass |
| `geom-point-basic` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.04 pt | 0.017% | ✅ pass |
| `geom-point-discrete` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.12 pt | 0.011% | ✅ pass |
| `geom-point-na` | `geom-point` | 2/2 | 0.000% | 1 pt | 0.03 pt | 0.009% | ✅ pass |
| `geom-point-shapes` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.38 pt | 0.004% | ✅ pass |
| `geom-point-size` | `geom-point` | 2/2 | 0.000% | 1 pt | 0.05 pt | 0.016% | ✅ pass |
| `geom-smooth-default` | `geom-smooth` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-smooth-groups` | `geom-smooth` | 3/3 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `geom-smooth-se` | `geom-smooth` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-smooth-span` | `geom-smooth` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `geom-text-cjk` | `geom-text` | 3/3 | 0.000% | 0 pt | 0.03 pt | 0.001% | ✅ pass |
| `guide-colourbar` | `guide` | 238/238 | 0.000% | 1 pt | 0.07 pt | 0.015% | ✅ pass |
| `guide-legend-merged` | `guide` | 4/4 | 0.000% | 0 pt | 0.08 pt | 0.008% | ✅ pass |
| `guide-legend-single` | `guide` | 4/4 | 0.000% | 0 pt | 0.19 pt | 0.013% | ✅ pass |
| `scale-colour-default` | `scale` | 4/4 | 0.000% | 0 pt | 0.21 pt | 0.015% | ✅ pass |
| `scale-colour-gradient` | `scale` | 10/10 | 0.000% | 0 pt | 0.05 pt | 0.017% | ✅ pass |
| `scale-colour-identity` | `scale` | 6/6 | 0.000% | 0 pt | 0.07 pt | 0.013% | ✅ pass |
| `scale-colour-viridis-d` | `scale` | 6/6 | 0.000% | 0 pt | 0.26 pt | 0.022% | ✅ pass |
| `scale-fill-brewer` | `scale` | 4/4 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `scale-limits-drop` | `scale` | 2/2 | 0.000% | 0 pt | 0.25 pt | 0.007% | ✅ pass |
| `scale-linetype-discrete` | `scale` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.001% | ✅ pass |
| `scale-size-area` | `scale` | 3/3 | 0.000% | 1 pt | 0.14 pt | 0.023% | ✅ pass |
| `scale-x-log10` | `scale` | 2/2 | 0.000% | 0 pt | 0.10 pt | 0.010% | ✅ pass |
| `scale-y-log10` | `scale` | 2/2 | 0.000% | 0 pt | 0.07 pt | 0.009% | ✅ pass |
| `stat-area-align` | `geom-area` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `stat-boxplot-stat` | `geom-boxplot` | 3/3 | 0.000% | 0 pt | 0.04 pt | 0.003% | ✅ pass |
| `stat-histogram-bin` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `stat-histogram-horizontal` | `geom-histogram` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `stat-smooth-loess` | `geom-smooth` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `text-bold-italic` | `geom-text` | 2/2 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `text-emoji` | `geom-text` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.000% | ✅ pass |
| `text-multiline` | `geom-text` | 2/2 | 0.000% | 0 pt | 0.58 pt | 0.004% | ✅ pass |
| `theme-grey-basic` | `theme` | 6/6 | 0.000% | 0 pt | 0.00 pt | 0.009% | ✅ pass |
| `theme-minimal-basic` | `theme` | 5/5 | 0.238% | 0 pt | 0.24 pt | 0.025% | ✅ pass |
| `theme-void-basic` | `theme` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.007% | ✅ pass |
| `viewer-alpha-fill` | `geom-col` | 5/5 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `viewer-alpha-overlap` | `geom-col` | 3/3 | 0.000% | 0 pt | 0.00 pt | 0.000% | ✅ pass |
| `viewer-linetype-all` | `geom-line` | 2/2 | 0.000% | 0 pt | 0.01 pt | 0.003% | ✅ pass |
| `viewer-pch-all` | `geom-point` | 3/3 | 0.000% | 0 pt | 0.19 pt | 0.108% | ✅ pass |

全部通过。

## 口径

- **颜色集合**：两侧所有已绘制元素的最终涂色（属性 + 继承 + SVG 缺省值），归一成 `#rrggbb` × opacity；按集合比、不计元素个数——skia 每个字形一条路径，查看器一条文本一行。线宽 / 虚线不进这一层（skia 会把虚线展开成填充多边形，见 `docs/notes/device.md`），由像素差兜住。
- **墨迹包围盒 / 重心**：PNG 上非白像素的四条边逐边 ≤ 1 pt（抗锯齿边缘的一档），按亮度加权的墨量重心 ≤ 0.5 pt（整体位移）。
- **墨迹差**：两侧 PNG 的二值墨迹（任一通道 < 250）的对称差占比，带 1 px 形态学容差——同一形状的两种 SVG 表达只差边缘抗锯齿那一档。**均值**沿用 `ggdiff` 的全通道平均差（≤ 1%），保证墨迹内部的颜色强度一致。
