# 案例覆盖矩阵

<!-- 生成物，不要手改：pixi run cases:matrix；pixi run cases:matrix --check 校验是否最新 -->

矩阵是**静态**覆盖视图（只由仓库内容决定）：行 = 族，列 = 特性标签，`—` = 该组合没有 case。运行时红绿与「差多少」在 `.cases-matrix/report.md`（`pixi run cases:matrix` 生成，不入库）。

- 三文件 case：**0** 个（`plot.py` + `expected.svg|png` + `meta.toml`）
- 历史快照目录：**18** 个（`case.json`，M0-4 / M0-6，不进矩阵）

## 覆盖矩阵

| 族 \ 特性 | `aes-mapping` | `aes-grouping` | `aes-inherit` | `colour-aes` | `size-aes` | `alpha-aes` | `shape-aes` | `line-type` | `na-removal` | `sort-order` | `scale-log10` | `scale-discrete` | `scale-limits` | `coord-flip` | `facet-wrap` | `stat-count` | `stat-bin` | `position-dodge` | `position-stack` | `position-jitter` | `theme-text` | `guide-legend` | `annotation-text` | `lab-title` | `rotation` | `cjk-text` | 合计 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `geom-point` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-line` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-path` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-bar` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-col` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-area` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-histogram` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-boxplot` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-violin` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-smooth` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-text` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-tile` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-raster` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-polygon` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-errorbar` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-ribbon` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-step` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `geom-hline` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `scale` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `coord` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `facet` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `theme` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `annotation` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `guide` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `lab` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **合计** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |

## 覆盖缺口（650 个空位）

按族列出没有 case 的特性（要补哪个格子就看这一节）：

| 族 | 未覆盖的特性 |
| --- | --- |
| `geom-point` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-line` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-path` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-bar` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-col` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-area` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-histogram` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-boxplot` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-violin` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-smooth` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-text` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-tile` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-raster` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-polygon` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-errorbar` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-ribbon` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-step` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `geom-hline` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `scale` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `coord` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `facet` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `theme` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `annotation` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `guide` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |
| `lab` | `aes-mapping`、`aes-grouping`、`aes-inherit`、`colour-aes`、`size-aes`、`alpha-aes`、`shape-aes`、`line-type`、`na-removal`、`sort-order`、`scale-log10`、`scale-discrete`、`scale-limits`、`coord-flip`、`facet-wrap`、`stat-count`、`stat-bin`、`position-dodge`、`position-stack`、`position-jitter`、`theme-text`、`guide-legend`、`annotation-text`、`lab-title`、`rotation`、`cjk-text` |

## 案例清单

（还没有三文件 case；新增一个目录就会自动出现在这里。）

## 未登记的族 / 特性

无：矩阵里的每个族 / 特性都在 `taxonomy.toml` 里登记过。

## 其他来源（不进 geom 矩阵）

| 来源 | 数量 | 说明 |
| --- | --- | --- |
| `docs/cases/*/case.json`（M0-4 viewport / M0-6 grob） | 18 | 快照由 `pixi run cases:viewport` / `pixi run cases:grob` 维护，不套三文件约定 |
| `docs/spike/e2_metrics` | 200 条 | X5 双端度量语料（200 标签 × 4 字号），不迁移；gate:metrics 直接消费 |
| `docs/spike/e3_export` | — | E3 导出可行性实验（CanvasKit / PDF），不迁移 |
