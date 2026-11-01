# 案例覆盖矩阵

<!-- 生成物，不要手改：pixi run cases:matrix；pixi run cases:matrix --check 校验是否最新 -->

矩阵是**静态**覆盖视图（只由仓库内容决定）：行 = 族，列 = 特性标签，`—` = 该组合没有 case。运行时红绿与「差多少」在 `.cases-matrix/report.md`（`pixi run cases:matrix` 生成，不入库）。

- 三文件 case：**4** 个（`plot.py` + `expected.svg|png` + `meta.toml`）
- 历史快照目录：**18** 个（`case.json`，M0-4 / M0-6，不进矩阵）

## 覆盖矩阵

| 族 \ 特性 | `aes-mapping` | `aes-grouping` | `aes-inherit` | `colour-aes` | `size-aes` | `alpha-aes` | `shape-aes` | `line-type` | `na-removal` | `sort-order` | `scale-log10` | `scale-discrete` | `scale-limits` | `coord-flip` | `facet-wrap` | `stat-count` | `stat-bin` | `position-dodge` | `position-stack` | `position-jitter` | `theme-text` | `guide-legend` | `annotation-text` | `lab-title` | `rotation` | `cjk-text` | 合计 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `geom-point` | `geom-point-basic` | `geom-point-basic` | — | `geom-point-basic` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1 |
| `geom-line` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-path` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-bar` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-col` | `geom-col-basic` | — | — | `geom-col-basic` | — | — | — | — | — | — | — | — | `geom-col-basic` | — | — | — | — | — | — | — | — | — | — | — | — | — | 1 |
| `geom-area` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-histogram` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-boxplot` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-violin` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-smooth` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-text` | `geom-text-cjk` | — | — | `geom-text-cjk` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | `geom-text-cjk` | 1 |
| `geom-tile` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-raster` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-polygon` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-errorbar` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-ribbon` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-step` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-hline` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-curve` | `geom-curve-basic` | — | — | `geom-curve-basic` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | 1 |
| `scale` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `coord` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `facet` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `theme` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `annotation` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `guide` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `lab` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **合计** | 4 | 1 | — | 4 | — | — | — | — | — | — | — | — | 1 | — | — | — | — | — | — | — | — | — | — | — | — | 1 | 4 |

## 覆盖缺口（665 个空位）

按族列出没有 case 的特性（要补哪个格子就看这一节）：

| 族 | 未覆盖的特性 |
| --- | --- |
| `geom-point` | `aes-inherit`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-line` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-path` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-bar` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-col` | `aes-grouping`、`aes-inherit`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-area` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-histogram` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-boxplot` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-violin` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-smooth` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-text` | `aes-grouping`、`aes-inherit`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation` |
| `geom-tile` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-raster` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-polygon` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-errorbar` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-ribbon` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-step` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-hline` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-curve` | `aes-grouping`、`aes-inherit`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `scale` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `coord` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `facet` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `theme` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `annotation` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `guide` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `lab` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |

## 案例清单

| case | 族 | 特性 | 容差 | ci | 参考 | 来源 | 契约 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `geom-col-basic` | `geom-col` | `aes-mapping`<br>`colour-aes`<br>`scale-limits` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-curve-basic` | `geom-curve` | `aes-mapping`<br>`colour-aes` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-point-basic` | `geom-point` | `aes-mapping`<br>`aes-grouping`<br>`colour-aes` | png 0.02 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |
| `geom-text-cjk` | `geom-text` | `aes-mapping`<br>`colour-aes`<br>`cjk-text` | png 0.014 | 是 | `expected.svg` | svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2) | ok |

## 未登记的族 / 特性

无：矩阵里的每个族 / 特性都在 `taxonomy.toml` 里登记过。

## 其他来源（不进 geom 矩阵）

| 来源 | 数量 | 说明 |
| --- | --- | --- |
| `docs/cases/*/case.json`（M0-4 viewport / M0-6 grob） | 18 | 快照由 `pixi run cases:viewport` / `pixi run cases:grob` 维护，不套三文件约定 |
| `docs/spike/e2_metrics` | 200 条 | X5 双端度量语料（200 标签 × 4 字号），不迁移；gate:metrics 直接消费 |
| `docs/spike/e3_export` | — | E3 导出可行性实验（CanvasKit / PDF），不迁移 |
