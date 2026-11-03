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
| `ggcore.plot` | `R/plot.R:106` | `ggplot()` | 已实现（M1-1：对象 + `+` + 克隆 + 方法链别名） |
| `ggcore.plot` | `R/all-classes.R:322` | `class_ggplot`（S7 类） | 已实现（M1-1：字段 `data` / `mapping` / `layers` / `scales` / `guides` / `theme` / `coordinates` / `facet` / `labels`） |
| `ggcore.layer` | `R/layer.R:99` | `layer()` | 已实现（M1-1：`Layer` / `Geom` / `Stat` / `Position` 骨架，`draw` 留给 M1-7） |
| `ggcore.aes` | `R/aes.R:93` | `aes()` | 已实现（M1-1 存原样表达式；M1-2 补 `AesSpec` 与解析入口） |
| `ggcore.aes` | `R/aes.R:180` | `standardise_aes_names()` | 已实现（M1-2：`color`/`pch`/… 别名在 `Aes.__post_init__` 标准化） |
| `ggcore.registry` | — | 组件注册表（本项目自造，上游靠 export + ggproto） | 已实现（M1-1：一条注册表，模块函数与 `ggplot` 方法两个入口） |
| `ggcore.scales` | `R/scale-continuous.R` / `R/scale-discrete.R` / `R/scale-*.R` | 13 个标度（位置连续/离散/log10、colour/fill gradient+hue、size/shape/alpha） | 已实现（M1-4：limits / expand / breaks / labels / trans / na.value / values；口径见 `docs/notes/scales.md`） |
| `ggcore.components` | — | 非图层组件的占位类（scale / theme / coord / facet / guide / labels） | 已实现（M1-1：名字 + 参数；scale 语义在 `ggcore.scales`（M1-4），其余在 M1-5 / M1-6 / M1-10 / M1-11） |
| `ggcore.eval` | `R/aes-evaluation.R:349` | `eval_aesthetics()` | 已实现（M1-2：`parse_aes` / `eval_aes` / `eval_after_stat`，白名单解释器） |
| `ggcore.eval` | `R/grouping.R:11` | `add_group()` | 已实现（M1-2：`compute_groups` / `has_groups`，显式 group 与离散 aes interaction） |
| `ggcore.build` | `R/layer.R` | `Layer$compute_aesthetics()` / `compute_statistic()` / `map_statistic()` / `compute_position()` / `finish_statistics()` | 已实现（M1-3：六阶段流水线；`identity` / `count` stat） |
| `ggcore.position` | `R/position-*.R` | `Position*$compute_panel()` / `collide()` / `pos_stack()` / `pos_dodge()` / `pos_dodge2()` / `compute_jitter()` / `PositionNudge` | 已实现（M1-9：identity / stack / fill / dodge / dodge2 / jitter / nudge；口径见 `docs/notes/position.md`） |
| `ggcore.build` | `R/plot-build.R` | `build_ggplot()` | 已实现（M1-3：`build_plot()`，只算数据，不出 gtable） |
| `ggcore.build` | `R/geom-bar.R` / `R/geom-boxplot.R` | `GeomBar$setup_data()` / `GeomBoxplot$setup_data()` | 部分实现（M1-3：`xmin` / `xmax` / `ymin` / `ymax` / `flipped_aes`） |
| `ggcore.ir` | — | IR（本项目自造，上游无对应） | 已实现（v0：18 种节点 + CBOR，`docs/notes/ir.md`） |
| `ggcore.plotspec` | `R/plot.R:106`（`ggplot()` 的极小子集）、`R/theme.R:341`（`theme_void()` 口径） | 案例适配层：plot 规格 → grob → IR（M0-9；不是语法层） | 已实现（point / bar / col / text / curve + `size` / `limits` / `palette`） |

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
| `ggcore.coord`（`CartesianCoord`） | `R/coord-cartesian-.R:78` | `coord_cartesian()` | 已实现（M1-5：范围 / expand / clip / 越界计数，见 `docs/notes/coord.md`） |
| `ggcore.coord`（`FixedCoord`） | `R/coord-fixed.R` | `coord_fixed()` | 已实现（M1-5：`aspect = ratio × yrange/xrange` + `panel_sizes()`） |
| `ggcore.facet.base` | `R/facet-.R:66` | `Facet` | 已实现（M1-6：布局 / 面板标度 / map_data，见 `docs/notes/facet.md`） |
| `ggcore.facet`（`FacetNull`） | `R/facet-null.R` | `facet_null()` | 已实现（M1-6：1×1 面板，输出与 M1-5 逐字节相同） |
| `ggcore.facet`（`FacetWrap`） | `R/facet-wrap.R` | `facet_wrap()` | 已实现（M1-6：ncol/nrow/dir/as.table/drop/labeller/scales；space 只支持 fixed，其余报错） |
| `ggcore.facet`（`FacetGrid`） | `R/facet-grid-.R` | `facet_grid()` | 已实现（M1-6：rows/cols/as.table/scales；margins / space=free 待补，其余非法值报错） |
| `ggcore.guide` | `R/guides-.R:69` | `guides()` | 未实现 |
| `ggcore.theme` | `R/theme.R` / `R/theme-elements.R` / `R/theme-defaults.R` | `theme()` / `element_*()` / `calc_element()` / 四套完整主题（grey / bw / minimal / void） | 已实现（M1-10：元素树 + 继承 + rel 解析，见 `docs/notes/theme.md`） |

## 文本度量

| Python 模块（计划） | 上游文件:行 | 上游符号 | 状态 |
| --- | --- | --- | --- |
| `ggcore.metrics` | — | 上游在 grid 包：`grid::strwidth` / `grid::stringWidth`（不在 ggplot2 `R/` 内） | 已实现（M0-7）：run 切分 + `MetricProvider` + 兜底表 |
| `ggshape.harfbuzz` | — | HarfBuzz 形状后端（上游由 Cairo/grid 内部承担，无对应文件） | 已实现（M0-7）：在 `ggcore` 之外 |

## 导出

| Python 模块（计划） | 上游文件:行 | 上游符号 | 状态 |
| --- | --- | --- | --- |
| `ggcore.io`（`ggsave` / `save_ir` / `export_ir_json`） | `R/save.R:92` | `ggsave()` | 已实现（M1-12）：按后缀选设备、四单位、`.ggir.cbor` / `.ir.json`，见 `docs/notes/io.md` |
| `ggskia`（协议 `ggcore.device`） | `src/library/grid/src/grid.c`（`L_points` / `L_xspline`）、`src/main/engine.c`（`GESymbol` / `GEXspline`） | 桌面/服务端渲染（skia-python，PNG / SVG / PDF） | 已实现（M0-8）：三路出图 + pch 全表 + xspline/curve 对拍 |
| `ggcore.render.svg` | — | 浏览器端 DOM SVG（原生化，上游无对应） | 未实现 |
| `ggdiff`（包外） | — | 差分：resvg 统一栅格 + 像素判据 + 报告（上游无对应） | 已实现（M0-9，`docs/notes/diff.md`） |

## 基础设施（grid 对等）

上游 `grid` 不在 ggplot2 仓库里，行号写 R 源码（版本由 `pixi.toml` 的 `refs`
环境钉住，见 `docs/notes/units.md`）。

| Python 模块 | 上游文件:行 | 上游符号 | 状态 |
| --- | --- | --- | --- |
| `ggcore.units` | `src/library/grid/R/unit.R:25`、`:59`、`:525`；`src/library/grid/src/unit.c:658`、`:1226` | `unit()` / `convertUnit()` / `unit.c()` / `transform()` / `transformFromINCHES()` | 已实现（M0-3，93 条 R 对拍） |
| `ggcore.gtable` | `gtable/R/gtable.R:94`、`:291`；`R/add-grob.R:45`；`R/add-rows-cols.R:40`、`:96`；`R/padding.R:29`；`R/grid.R:20`；`src/library/grid/src/layout.c:492` | `gtable()` / `gtable_width()` / `gtable_add_grob()` / `gtable_add_rows()` / `gtable_add_cols()` / `gtable_add_padding()` / `gtable_layout()` / `calcViewportLayout()` | 已实现（M0-5，22 组 R 设备测量对拍） |
| `ggcore.viewport` | `src/library/grid/src/viewport.c:213`；`src/library/grid/src/grid.c:139`、`:413`、`:1019`；`src/library/grid/src/matrix.c:96`；`src/library/grid/src/just.c:98`；`src/library/grid/R/grid.R:29`、`:162`；`src/library/grid/R/gpar.R:232` | `calcViewportTransform()` / `doSetViewport()` / `L_setviewport()` / `L_upviewport()` / `trans()`·`multiply()` / `justification()` / `push.vp.viewport()` / `downViewport()` / `set.gpar()` | 已实现（M0-4，22 个 check 步的 R 对拍 + 手算断言） |

## 维护规则

- 换 pin 时用 `pixi run upstream:diff` 的报表核对哪些文件动过，只更新动过的行。
- 表格里的行号写“符号定义行”（函数/类声明行），不写调用点。
- 上游没有对应物的模块（IR、skia/浏览器后端）在“上游文件:行”里写 `—` 并说明。
