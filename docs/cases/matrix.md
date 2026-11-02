# 案例覆盖矩阵

<!-- 生成物，不要手改：pixi run cases:matrix；pixi run cases:matrix --check 校验是否最新 -->

矩阵是**静态**覆盖视图（只由仓库内容决定）：行 = 族，列 = 特性标签，`—` = 该组合没有 case。运行时红绿与「差多少」在 `.cases-matrix/report.md`（`pixi run cases:matrix` 生成，不入库）。

- 三文件 case：**21** 个（`plot.py` + `expected.svg|png` + `meta.toml`）
- 历史快照目录：**18** 个（`case.json`，M0-4 / M0-6，不进矩阵）

## 覆盖矩阵

| 族 \ 特性 | `aes-mapping` | `aes-grouping` | `aes-inherit` | `colour-aes` | `size-aes` | `alpha-aes` | `shape-aes` | `line-type` | `na-removal` | `sort-order` | `scale-log10` | `scale-discrete` | `scale-limits` | `coord-flip` | `facet-wrap` | `stat-count` | `stat-bin` | `stat-boxplot` | `stat-smooth` | `stat-align` | `position-dodge` | `position-stack` | `position-jitter` | `theme-text` | `guide-legend` | `annotation-text` | `lab-title` | `rotation` | `cjk-text` | `font-face` | `multiline` | `emoji-text` | 合计 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `geom-point` | `geom-point-basic`<br>`geom-point-shapes` | `geom-point-basic`<br>`geom-point-shapes` | — | `geom-point-basic`<br>`geom-point-shapes` | — | — | `geom-point-shapes` | — | — | — | — | `geom-point-shapes` | `geom-point-shapes` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 2 |
| `geom-line` | `geom-line-groups` | `geom-line-groups` | — | `geom-line-groups` | — | — | — | — | — | `geom-line-groups` | — | — | `geom-line-groups` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1 |
| `geom-path` | `geom-path-order` | — | — | — | — | — | — | `geom-path-order` | — | — | — | — | `geom-path-order` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1 |
| `geom-bar` | `geom-bar-stacked` | `geom-bar-stacked` | — | — | — | — | — | — | — | — | — | `geom-bar-stacked` | — | — | — | `geom-bar-stacked` | — | — | — | — | — | `geom-bar-stacked` | — | — | — | — | — | — | — | — | — | — | 1 |
| `geom-col` | `geom-col-basic`<br>`geom-col-identity` | `geom-col-identity` | — | `geom-col-basic`<br>`geom-col-identity` | — | — | — | — | — | — | — | — | `geom-col-basic`<br>`geom-col-identity` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 2 |
| `geom-area` | `geom-area-identity`<br>`stat-area-align` | `stat-area-align` | — | — | — | — | — | — | — | — | — | — | `geom-area-identity`<br>`stat-area-align` | — | — | — | — | — | — | `stat-area-align` | — | `stat-area-align` | — | — | — | — | — | — | — | — | — | — | 2 |
| `geom-histogram` | `geom-histogram-identity`<br>`stat-histogram-bin`<br>`stat-histogram-horizontal` | — | — | — | — | — | — | — | — | — | — | — | `geom-histogram-identity`<br>`stat-histogram-bin`<br>`stat-histogram-horizontal` | — | — | — | `geom-histogram-identity`<br>`stat-histogram-bin`<br>`stat-histogram-horizontal` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 3 |
| `geom-boxplot` | `geom-boxplot-precomputed`<br>`stat-boxplot-stat` | — | — | — | — | — | — | — | — | — | — | — | `geom-boxplot-precomputed`<br>`stat-boxplot-stat` | — | — | — | — | `stat-boxplot-stat` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 2 |
| `geom-violin` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-smooth` | `geom-smooth-se`<br>`stat-smooth-loess` | — | — | — | — | `geom-smooth-se` | — | — | — | — | — | — | `geom-smooth-se`<br>`stat-smooth-loess` | — | — | — | — | — | `stat-smooth-loess` | — | — | — | — | — | — | — | — | — | — | — | — | — | 2 |
| `geom-text` | `geom-text-cjk` | — | — | `geom-text-cjk` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | `geom-text-cjk` | `text-bold-italic` | `text-multiline` | `text-emoji` | 4 |
| `geom-tile` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-raster` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-polygon` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-errorbar` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-ribbon` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-step` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-hline` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-curve` | `geom-curve-basic` | — | — | `geom-curve-basic` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1 |
| `scale` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `coord` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `facet` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `theme` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `annotation` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `guide` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `lab` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **合计** | 18 | 6 | — | 7 | — | 1 | 1 | 1 | — | 1 | — | 2 | 14 | — | — | 1 | 3 | 1 | 1 | 1 | — | 2 | — | — | — | — | — | — | 1 | 1 | 1 | 1 | 21 |

## 覆盖缺口（786 个空位）

按族列出没有 case 的特性（要补哪个格子就看这一节）：

| 族 | 未覆盖的特性 |
| --- | --- |
| `geom-point` | `aes-inherit`、`size-aes`、`alpha-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-line` | `aes-inherit`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`scale-log10`、`scale-discrete`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-path` | `aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-bar` | `aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-col` | `aes-inherit`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-area` | `aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`position-dodge`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-histogram` | `aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-boxplot` | `aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-violin` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-smooth` | `aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-text` | `aes-grouping`、`aes-inherit`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation` |
| `geom-tile` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-raster` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-polygon` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-errorbar` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-ribbon` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-step` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-hline` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `geom-curve` | `aes-grouping`、`aes-inherit`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `scale` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `coord` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `facet` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `theme` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `annotation` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `guide` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |
| `lab` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`stat-boxplot`、`stat-smooth`、`stat-align`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text`、`font-face`、`multiline`、`emoji-text` |

## 案例清单

| case | 族 | 特性 | 容差 | ci | 参考 | 来源 | 契约 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `geom-area-identity` | `geom-area` | `aes-mapping`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-bar-stacked` | `geom-bar` | `aes-mapping`<br>`aes-grouping`<br>`stat-count`<br>`position-stack`<br>`scale-discrete` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-boxplot-precomputed` | `geom-boxplot` | `aes-mapping`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-col-basic` | `geom-col` | `aes-mapping`<br>`colour-aes`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-col-identity` | `geom-col` | `aes-mapping`<br>`aes-grouping`<br>`colour-aes`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-curve-basic` | `geom-curve` | `aes-mapping`<br>`colour-aes` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-histogram-identity` | `geom-histogram` | `aes-mapping`<br>`stat-bin`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-line-groups` | `geom-line` | `aes-mapping`<br>`aes-grouping`<br>`colour-aes`<br>`sort-order`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-path-order` | `geom-path` | `aes-mapping`<br>`line-type`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-point-basic` | `geom-point` | `aes-mapping`<br>`aes-grouping`<br>`colour-aes` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-point-shapes` | `geom-point` | `aes-mapping`<br>`aes-grouping`<br>`colour-aes`<br>`shape-aes`<br>`scale-discrete`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-smooth-se` | `geom-smooth` | `aes-mapping`<br>`alpha-aes`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-text-cjk` | `geom-text` | `aes-mapping`<br>`colour-aes`<br>`cjk-text` | png 0.014 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `stat-area-align` | `geom-area` | `aes-mapping`<br>`aes-grouping`<br>`stat-align`<br>`position-stack`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `stat-boxplot-stat` | `geom-boxplot` | `aes-mapping`<br>`stat-boxplot`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `stat-histogram-bin` | `geom-histogram` | `aes-mapping`<br>`stat-bin`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `stat-histogram-horizontal` | `geom-histogram` | `aes-mapping`<br>`stat-bin`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `stat-smooth-loess` | `geom-smooth` | `aes-mapping`<br>`stat-smooth`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `text-bold-italic` | `geom-text` | `font-face` | 默认（X4） | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `text-emoji` | `geom-text` | `emoji-text` | 默认（X4） | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `text-multiline` | `geom-text` | `multiline` | 默认（X4） | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |

## 未登记的族 / 特性

无：矩阵里的每个族 / 特性都在 `taxonomy.toml` 里登记过。

## 其他来源（不进 geom 矩阵）

| 来源 | 数量 | 说明 |
| --- | --- | --- |
| `docs/cases/*/case.json`（M0-4 viewport / M0-6 grob） | 18 | 快照由 `pixi run cases:viewport` / `pixi run cases:grob` 维护，不套三文件约定 |
| `docs/spike/e2_metrics` | 200 条 | X5 双端度量语料（200 标签 × 4 字号），不迁移；gate:metrics 直接消费 |
| `docs/spike/e3_export` | — | E3 导出可行性实验（CanvasKit / PDF），不迁移 |
