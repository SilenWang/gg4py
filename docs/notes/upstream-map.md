# 模块 ↔ 上游对照表（X3）

上游行号以 `docs/notes/upstream.md` 钉死的 commit（ggplot2 `v4.0.3`，
`cc1444c10edb87650fbe0cb31d56f0da1a255634`）为准。这张表是**骨架**：实现进度
到了哪一格，就把“状态”从 `未实现` 改成 `已实现` 并补上对应 Python 符号；没人
认领的格子留空没关系，但**新增 ggcore 模块必须加一行**（PR 检查项）。

行号只是入口锚点，不代表整个文件的实现范围——一个上游 `.R` 常常对应多个
Python 模块，反之亦然。

## 绘图语法

| Python 模块（计划） | 上游文件:行 | 上游符号 | 状态 |
| --- | --- | --- | --- |
| `ggcore.plot` | `R/plot.R:106` | `ggplot()` | 未实现（M0-1 只有占位 scene） |
| `ggcore.plot` | `R/plot.R:128` | `class_ggplot`（S7 类） | 未实现 |
| `ggcore.layer` | `R/layer.R:99` | `layer()` | 未实现 |
| `ggcore.aes` | `R/aes.R:93` | `aes()` | 未实现 |
| `ggcore.aes` | `R/aes.R:180` | `standardise_aes_names()` | 未实现 |
| `ggcore.aes_eval` | `R/aes-evaluation.R` | 表达式求值（tidy-eval 对等物） | 未实现 |
| `ggcore.scene` | — | IR（本项目自造，上游无对应） | 占位（`Scene`） |

## geom

| Python 模块（计划） | 上游文件:行 | 上游符号 | 状态 |
| --- | --- | --- | --- |
| `ggcore.geom.base` | `R/geom-.R:77` | `Geom`（ggproto 基类） | 未实现 |
| `ggcore.geom.bar` | `R/geom-bar.R:6` | `GeomBar` | 未实现 |
| `ggcore.geom.point` | `R/geom-point.R:5` | `GeomPoint` | 未实现 |
| `ggcore.geom.path` | `R/geom-path.R:5` | `GeomPath` | 未实现 |
| `ggcore.geom.line` | `R/geom-path.R:123` | `GeomLine` | 未实现 |

## stat / scale / coord / facet / guide / theme

| Python 模块（计划） | 上游文件:行 | 上游符号 | 状态 |
| --- | --- | --- | --- |
| `ggcore.stat.base` | `R/stat-.R:74` | `Stat` | 未实现 |
| `ggcore.scale` | `R/scale-.R:461` | `Scale` | 未实现 |
| `ggcore.scale.continuous` | `R/scale-.R:106` | `continuous_scale()` | 未实现 |
| `ggcore.coord.cartesian` | `R/coord-cartesian-.R:78` | `coord_cartesian()` | 未实现 |
| `ggcore.facet.base` | `R/facet-.R:66` | `Facet` | 未实现 |
| `ggcore.guide` | `R/guides-.R:69` | `guides()` | 未实现 |
| `ggcore.theme` | `R/theme.R:341` | `theme()` | 未实现 |

## 导出

| Python 模块（计划） | 上游文件:行 | 上游符号 | 状态 |
| --- | --- | --- | --- |
| `ggcore.io.save` | `R/save.R:92` | `ggsave()` | 未实现 |
| `ggcore.render.skia` | — | 桌面/服务端渲染（skia-python，上游用 grid） | 未实现 |
| `ggcore.render.svg` | — | 浏览器端 DOM SVG（原生化，上游无对应） | 未实现 |

## 维护规则

- 换 pin 时用 `pixi run upstream:diff` 的报表核对哪些文件动过，只更新动过的行。
- 表格里的行号写“符号定义行”（函数/类声明行），不写调用点。
- 上游没有对应物的模块（IR、skia/浏览器后端）在“上游文件:行”里写 `—` 并说明。
