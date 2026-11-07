# 模块 ↔ 上游对照表（X3）

上游行号以 `docs/notes/upstream.md` 钉死的 commit（ggplot2 `v4.0.3`，
`cc1444c10edb87650fbe0cb31d56f0da1a255634`）为准。

这张表**按 ggcore 的模块清单组织**：`git ls-files src/ggcore` 里每个 `*.py`
都在下表中恰好有一行，反过来表里写出的每个模块都必须能 `import`。两个方向都由
`pixi run docs:upstream-map:check` 断言（`tools/gates/upstream_map.py`），漂移
会让 `pixi run check` 变红，不靠人工复查。

行号只是入口锚点，不代表整个文件的实现范围——一个上游 `.R` 常常对应多个
Python 模块，反之亦然；反过来，标着 `—` 的模块是上游没有对应物的自造层
（IR、skia 设备、性能预算等），它们的契约写在各自的 notes 里。

## 状态口径

状态只有三档，判定依据固定如下，不接受「大概做了」这种写法：

| 状态 | 判定依据 |
| --- | --- |
| `已实现` | 模块里与上游同名/同义的公开符号都在，且主路径有验收资产（R 对拍夹具 `tests/fixtures/*_r_reference.json`、`docs/cases/` 的 `expected.svg`，或 `tests/` 下对应的单测）。只差上游本身就报错的参数（例如上游 `deprecate_stop()`）不算缺口。 |
| `部分实现` | 模块可用，但有**明确缺口**：代码里以 `NotImplementedError` / 显式 `*Error` 点名后续任务或「只支持 X」，或 notes 里记录了口径差异。缺口必须写在同一行的「依据 / 缺口」列，不写在别处。 |
| `刻意不做` | 上游有这个能力，但我们明确不做（或上游无对应物、由别的层承担）。必须写清依据：为什么不做、由谁承担。任何「以后再说」都不算依据。 |

三档以外的状态词（`计划`、`骨架`、`待做`、`待补`）一律不写进状态列；
门禁会拒绝表头或状态格里的这类写法。

## 语法核心

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore` | — | 包门面：`ggplot()` / `aes()` 等公开入口的重导出 | 已实现 | `src/ggcore/__init__.py` 只做重导出，语义在各模块；入口清单见 `docs/notes/aes.md` |
| `ggcore.plot` | `R/plot.R:106` | `ggplot()` / `gg_add()`（`+`）/ `guides()` / `update_geom_defaults()` | 已实现 | M1-1：对象 + `+` + 克隆 + 方法链别名（M1-1 验收，`tests/test_plot.py`） |
| `ggcore.registry` | — | 组件注册表（上游靠 NAMESPACE 导出 + ggproto 继承） | 已实现 | M1-1：一条注册表两个入口（模块函数 / `ggplot` 方法），见 `docs/notes/extension.md` |
| `ggcore.components` | — | scale / theme / coord / facet / guide / labels 的组件占位 | 已实现 | M1-1；真正的语义在 `ggcore.scales` / `theme` / `coord` / `facet` / `guide` |
| `ggcore.layer` | `R/layer.R:99` | `layer()` / `Geom` / `Stat` / `Position` | 已实现 | M1-1：只承载参数对象；`setup_data()` / `draw()` 在 `ggcore.geom.*` |
| `ggcore.aes` | `R/aes.R:93`、`:180` | `aes()` / `after_stat()` / `standardise_aes_names()` | 已实现 | M1-2：原样表达式 + `AesSpec`；`color`/`pch` 等别名在 `__post_init__` 标准化 |
| `ggcore.eval` | `R/aes-evaluation.R:349`、`R/grouping.R:11` | `eval_aesthetics()` / `add_group()` | 已实现 | M1-2：`parse_aes` / `eval_aes` / `eval_after_stat` 白名单解释器；口径见 `docs/notes/aes.md` |
| `ggcore.build` | `R/layer.R`、`R/plot-build.R` | `compute_aesthetics()` / `compute_statistic()` / `map_statistic()` / `compute_position()` / `build_ggplot()` | 已实现 | M1-3 六阶段流水线 + `build_plot()`（只算数据、不出 gtable），见 `docs/notes/build.md` |
| `ggcore.position` | `R/position-*.R` | `Position*$compute_panel()` / `pos_stack()` / `pos_dodge()` / `pos_dodge2()` / `compute_jitter()` / `PositionNudge` | 已实现 | M1-9 + M2-8：NAMESPACE 的 8 个导出（identity / stack / fill / dodge / dodge2 / jitter / jitterdodge / nudge），见 `docs/notes/position.md` |
| `ggcore.data` | — | 列式表 `ColumnTable`（上游数据在 R 的 `data.frame`） | 已实现 | 本项目自造的最小列存；口径见 `docs/notes/data.md` |
| `ggio` | — | DataFrame-like（pandas / Arrow / dict of arrays）→ `ColumnTable` | 已实现 | 包外输入适配层（`ggio.frame` / `ggio.csv`），pandas / pyarrow 可选导入；见 `docs/notes/data.md` |
| `ggcore.plotspec` | `R/plot.R:106`（`ggplot()` 的极小子集）、`R/theme.R:341`（`theme_void()` 口径） | 案例适配层：plot 规格 → grob → IR（M0-9，**不是语法层**） | 已实现 | 只服务 `docs/cases/*/plot.py`；语法层入口是 `ggcore.plot` |
| `ggcore.ir` | — | IR v0 公开接口（`encode` / `decode` / 节点表） | 已实现 | 本项目自造；线格式与节点表见 `docs/notes/ir.md` |
| `ggcore.ir.nodes` | — | IR 节点类型表与 `Scene` | 已实现 | 18 种节点 + `f32` 缓冲，见 `docs/notes/ir.md` |
| `ggcore.ir.codec` | — | IR 的 CBOR 编解码 | 已实现 | `gate:ir-json` / `gate:cbor` 守线格式 |
| `ggcore.ir._cbor` | — | 纯 Python canonical CBOR（Pyodide 侧无 cbor2） | 已实现 | 与 cbor2 的 9330 个取值对拍见 `gate:cbor` |
| `ggcore.ir.errors` | — | IR 异常族 | 已实现 | 与 `codec` 一起验收 |
| `ggcore.ir.demo` | — | 门禁与基准共用的演示 scene | 已实现 | 上游无对应；`gate:determinism` 使用 |
| `ggcore.script` | — | 「一段脚本 → 一张图」的执行契约（浏览器编辑器） | 已实现 | 上游无对应（R 侧是 `source()`）；口径见 `docs/notes/editor.md` |
| `ggcore.perf` | — | 降采样 / 度量缓存 / 场景缓存 | 已实现 | 上游无对应；预算与实测见 `docs/notes/performance.md` |

## geom 绘制层

上游把 `draw_panel()` 挂在 `Geom*` ggproto 上；这里把同一份契约落在
`GeomRenderer`（`ggcore.geom.base`），构造路径不变——`geom_*()` 仍然只产生
`Geom(name=…)` 数据对象。

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.geom` | `R/geom-.R:77` | `Geom` 分派（`renderer_for()` / `registered_renderers()`） | 已实现 | M1-7 / M2-S2 / M2-7；未注册的名字显式报 `GeomError` 并列出已实现项 |
| `ggcore.geom.base` | `R/geom-.R:77` | `Geom`（ggproto 基类：`setup_params` / `setup_data` / `handle_na` / `draw`） | 已实现 | `GeomRenderer` + 共享工具；口径见 `docs/notes/geom.md` |
| `ggcore.geom.bar` | `R/geom-bar.R:6`、`R/geom-histogram.R`、`R/geom-area.R:210` | `GeomBar` / `GeomCol` / `GeomHistogram` / `GeomArea` | 已实现 | M1-7；逐列对拍 `tests/fixtures/geom_r_reference.json` |
| `ggcore.geom.boxplot` | `R/geom-boxplot.R` | `GeomBoxplot` | 已实现 | M1-7；`stat_boxplot` 的加权分位缺口见 `ggcore.stat` 行 |
| `ggcore.geom.point` | `R/geom-point.R:5` | `GeomPoint` + `pch` 全表 | 已实现 | M1-7；pch 0..25 的 case 见 `docs/cases/` 与 `refs:viewer-cases` |
| `ggcore.geom.line` | `R/geom-path.R:5`、`:123`、`R/geom-freqpoly.R` | `GeomPath` / `GeomLine` / `GeomFreqpoly` | 已实现 | M1-7 + SIL-866（`freqpoly` 与 `line` 同一条绘制路径） |
| `ggcore.geom.smooth` | `R/geom-smooth.R` | `GeomSmooth` | 已实现 | M1-7；拟合内核见 `ggcore.loess`，`method` 的缺口归 `ggcore.stat` |
| `ggcore.geom.text` | `R/geom-text.R:5` | `GeomText` / `GeomLabel` | 已实现 | M2-7；`parse = TRUE` 走 `ggcore.plotmath` |
| `ggcore.geom.polygon` | `R/geom-polygon.R:8`、`R/geom-ribbon.R:5`、`R/geom-path.R`（`GeomStep`） | `GeomPolygon` / `GeomRibbon` / `GeomStep` | 已实现 | M2-S2；`geom_area` 在 `ggcore.geom.bar`（上游 `GeomArea` 继承 `GeomRibbon`） |
| `ggcore.geom.rect` | `R/geom-rect.R`、`R/geom-tile.R`、`R/geom-raster.R` | `GeomRect` / `GeomTile` / `GeomRaster` | 已实现 | M2-S2；`raster` 的位图编码见 `ggcore.png` |
| `ggcore.geom.segment` | `R/geom-segment.R`、`R/geom-curve.R`、`R/geom-spoke.R`、`R/geom-abline.R`、`R/geom-hline.R`、`R/geom-vline.R` | `GeomSegment` / `GeomCurve` / `GeomSpoke` / `GeomAbline` / `GeomHline` / `GeomVline` | 已实现 | M2-S2；xspline / curve 与 R 设备对拍见 `tests/fixtures/device_render_r/` |
| `ggcore.geom.interval` | `R/geom-linerange.R`、`R/geom-errorbar.R`、`R/geom-errorbarh.R`、`R/geom-pointrange.R`、`R/geom-crossbar.R` | `GeomLinerange` / `GeomErrorbar` / `GeomErrorbarh` / `GeomPointrange` / `GeomCrossbar` | 已实现 | M2-S2；flipped `aes` 与 `flipped_aes` 同口径 |
| `ggcore.geom.annotation` | `R/geom-blank.R`、`R/geom-rug.R`、`R/geom-map.R` | `GeomBlank` / `GeomRug` / `GeomMap` | 已实现 | M2-S2；`geom_map` 的数据来自 `ggcore.map_data` |
| `ggcore.geom.dist` | `R/geom-density.R`、`R/geom-violin.R`、`R/geom-dotplot.R`、`R/geom-bin2d.R`、`R/geom-hex.R`、`R/geom-contour.R`、`R/geom-density2d.R`、`R/geom-jitter.R`、`R/geom-count.R`、`R/stat-qq.R`、`R/geom-quantile.R`、`R/geom-function.R` | 15 个 `*Renderer`（density / violin / dotplot / bin2d / hex / contour / contour_filled / density_2d(_filled) / jitter / count / qq / qq_line / quantile / function） | 已实现 | M2-7 长尾 B；逐列对拍 `tests/test_stat_2d_r_parity.py` |
| `ggcore.geom.stat2d` | `R/geom-contour.R`、`R/geom-bin2d.R`、`R/geom-hex.R`、`R/geom-density2d.R` | 2D 族的 **build 级** geom（`setup_data()`） | 已实现 | M2-6 的兼容层：5 个名字的 `setup_data` 仍从这里取，`draw()` 已由 `ggcore.geom.dist` 接管，`build_only_renderers()` 为空（`tests/test_stat_2d_r_parity.py` 断言） |
| `ggcore.geom.sf` | `R/geom-sf.R:121` | `GeomSf` / `GeomSfText` / `GeomSfLabel` | 已实现 | M3-2：点 / 线 / 面 / 几何集合按类型分派 + 图例 key；CRS 缺口归 `ggcore.sf` |
| `ggcore.geom.scene` | `R/plot-build.R`（`ggplot_gtable()` 的整页装配） | 上游的 grob 树：背景 + panel + strip + 轴 + 图例 + 标题 | 已实现 | 本项目自造 IR 场景，见 `docs/notes/ir.md`；上游对应物是 `ggplotGrob()` 的产物 |

## stat

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.stat` | `R/stat-bin.R`、`R/stat-count.R`、`R/stat-boxplot.R`、`R/stat-smooth.R`、`R/stat-align.R` | `StatBin` / `StatCount` / `StatBoxplot` / `StatSmooth` / `StatAlign` | 部分实现 | 缺口：`stat_smooth(method = "gam" \| "glm")`、loess 的稳健迭代（`iterations > 1` / `iterTrace`）、`stat_boxplot` 的加权分位（`quantreg::rq` 分支）——代码里都显式报错点名后续任务；口径见 `docs/notes/stat.md` §9 / §10 |
| `ggcore.stat_longtail` | `R/stat-qq.R`、`R/stat-ecdf.R`、`R/stat-ellipse.R`、`R/stat-quantilemethods.R`、`R/stat-summary.R`、`R/stat-summary-bin.R`、`R/stat-sum.R`、`R/stat-unique.R`、`R/stat-density.R`、`R/stat-ydensity.R`、`R/stat-function.R`、`R/stat-connect.R`、`R/stat-manual.R` | `StatQq` / `StatQqLine` / `StatEcdf` / `StatEllipse` / `StatQuantile` / `StatSummary` / `StatSummaryBin` / `StatSum` / `StatUnique` / `StatDensity` / `StatYdensity` / `StatFunction` / `StatConnect` / `StatManual` | 已实现 | M2-6 长尾 B；逐列对拍 `tests/fixtures/stat_longtail_r_reference.json` |
| `ggcore.stat2d` | `R/stat-bin2d.R`、`R/stat-binhex.R`、`R/stat-summary-hex.R`、`R/stat-contour.R`、`R/stat-density-2d.R` | `stat_bin_2d` / `stat_bin_hex` / `stat_summary_2d` / `stat_summary_hex` / `stat_contour(_filled)` / `stat_density_2d(_filled)` | 部分实现 | 缺口：`summary_2d` / `summary_hex` 的 `fun` 按**名字**只认 mean / sum / median / min / max / var / sd（其余名字报错点名；任意函数可传可调用对象），上游接受任意函数名——`docs/notes/stat.md` §9 |
| `ggcore.kde2d` | `MASS::kde2d`（R 4.5 的 MASS） | `kde2d()` / `bandwidth.nrd()` / `bw.nrd0()` | 已实现 | numpy 复刻；`stat_density_2d` 的带宽与网格逐值对拍 |
| `ggcore.hexbin` | `hexbin::hexbin`（1.28.x） | `hexbin()` / `hexBinSummarise()` / `hex_binwidth()` | 已实现 | `stat_bin_hex` / `stat_summary_hex` 的内核 |
| `ggcore.contour` | `isoband` 包（ggplot2 依赖） | `isolines()` / `isobands()` / `contour_breaks()` | 已实现 | **惰性导入** contourpy（SIL-758），`gate:contourpy-lazy` 守这条边界 |
| `ggcore.loess` | R `stats::loess`（`cloess` / `loessf`） | `loess_fit()`（surface = direct）/ `loess_interpolate()`（默认口径） | 部分实现 | 缺口：`family = "symmetric"` 的稳健迭代不在本模块（`stat_smooth` 侧显式报错）；只支持一维预测变量 `y ~ x`，与上游 `stat_smooth` 约束一致 |
| `ggcore.munch` | `R/coord-munch.R` | `coord_munch()` | 已实现 | M2-1：非线性坐标的逐边细分，geom 侧只判断 `panel.is_linear`；见 `docs/notes/coord.md` |

## scale 与色板

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.scales` | `R/scale-.R:461`、`R/scale-continuous.R:106`、`R/scale-discrete.R`、`R/scale-binned.R`、`R/scale-*.R` | `Scale` / `continuous_scale()` / NAMESPACE 的 131 个 `scale_*` 导出（位置、colour / fill、shape、linetype、linewidth、size、alpha、identity / manual / brewer / viridis / distiller / ordinal） | 部分实现 | 缺口：`trans` 的 `log1p` / `reciprocal` / `asn` / `atanh` / `logit` / `probit` 未移植（`ScaleError` 点名后续任务）；其余 limits / expand / breaks / labels / na.value / oob / 分箱已落地。覆盖由 `pixi run api:coverage:check` 守（scale 131/131），口径见 `docs/notes/scales.md` |
| `ggcore.scale_specs` | `R/scale-*.R`（与上一行同一组文件） | 标度导出表：名字 → 美学 / 实现族 / 构造默认值 | 已实现 | 与 `ggcore.scales` 同一注册面；`api:coverage:check` 守 131/131 |
| `ggcore.palettes` | scales 1.4.0 / `RColorBrewer` 1.1.3 / `viridisLite` 0.4.3 | `hue_pal()` / `grey_pal()` / `brewer_pal()` / `viridis_pal()` / `colour_ramp()` / `gradient_n_pal()` / `shape_pal()` / `linetype_pal()` / 面积与线性色板 | 部分实现 | 缺口：R 的 657 个命名颜色只收了 22 个常用名（`_NAMED_COLOURS`），其余传 `#RRGGBB`；色板取值逐色对拍见 `tests/fixtures/palettes_r_reference.json` |
| `ggcore.palette_data` | scales 1.4.0 / `RColorBrewer` 1.1.3 / `viridisLite` 0.4.3 | 生成物：brewer 逐 `n` 表 + viridis 8 档映射 | 已实现 | 由 `pixi run refs:scales` 的 `palettes_ref.R` 生成，勿手改 |
| `ggcore.scales_date` | `R/scale-date.R`、scales 1.4.0 的 `breaks_*` / `label_*` | `pretty()` / `breaks_width_date()` / `breaks_width_time()` / `format_date()` / `format_datetime()` / `format_hms()` | 已实现 | SIL-800：Date 列不写 `scale_x_date()` 的默认解析 case + `refs:date-default` |

## coord

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.coord` | `R/coord-cartesian-.R:78`、`R/coord-fixed.R`、`R/coord-flip.R`、`R/coord-transform.R`、`R/coord-polar.R`、`R/coord-radial.R`、`R/coord-sf.R`、`R/coord-map.R` | `coord_cartesian()` / `coord_fixed()` / `coord_equal()` / `coord_flip()` / `coord_trans()` / `coord_polar()` / `coord_radial()` / `coord_sf()` / `coord_map()` / `coord_quickmap()` | 部分实现 | 缺口：`coord_map()` / `coord_sf()` 的 mapproj 只移植了 `mercator` / `azequalarea`，其它投影显式报 `CoordError`；极坐标下的 `coord_munch` 只覆盖 rect / polygon 图层。其余范围 / expand / clip / 越界计数见 `docs/notes/coord.md` §8 |

## facet

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.facet` | `R/facet-.R:66`、`R/facet-null.R`、`R/facet-wrap.R`、`R/facet-grid-.R` | `Facet` / `facet_null()` / `facet_wrap()` / `facet_grid()` / `labeller()` | 部分实现 | 缺口：`strip.position` 只支持 `"top"`（其余值显式报错）。scales / space（`fixed` / `free` / `free_x` / `free_y`）/ margins / as.table / drop / labeller 都已落地（M1-6 + M2-3），见 `docs/notes/facet.md` |

## guide / axis / legend

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.guide` | `R/guides-.R:69`、`R/guide-legend.R`、`R/guide-colorbar.R`、`R/guide-colorsteps.R`、`R/guide-bins.R`、`R/guide-custom.R` | `guides()` / `guide_legend()` / `guide_colourbar()` / `guide_coloursteps()` / `guide_bins()` / `guide_custom()` / `guide_none()` | 已实现 | M1-11 + M2-2；键与行列尺寸对拍 `tests/fixtures/guide_r_reference.json`，长尾见 `guide_long_r_reference.json`，口径见 `docs/notes/guide.md` |
| `ggcore.axis_guide` | `R/guide-axis.R`、`R/guide-axis-logticks.R`、`R/guide-axis-stack.R`、`R/guide-axis-theta.R` | `guide_axis()` / `guide_axis_logticks()` / `guide_axis_stack()` / `guide_axis_theta()` / `minor_breaks_log()` | 已实现 | SIL-739（M2-S2）：角度、稀疏、分行、次刻度、logticks、叠放都与 R 对拍 |
| `ggcore.axis` | `R/axis-secondary.R`、`R/guide-axis.R`（主轴 grob 的那一半） | `sec_axis()` / `dup_axis()` / 主轴刻度与标题 | 部分实现 | 缺口：`angle ≠ 0` 的轴标签旋转未实现（`AxisError` 点名 M1-11 只画水平标签）；次轴 / top-right 槽已落地，见 `docs/notes/guide.md` |
| `ggcore.legend_draw` | `R/legend-draw.R` | `draw_key_*`（point / rect / polygon / path / vpath / abline / vline / linerange / pointrange / smooth / text / label / boxplot / crossbar / dotplot / timeseries / blank） | 已实现 | M1-11 + M2-2；`key_glyph_for()` 按 geom 名分派 |

## theme

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.theme` | `R/theme.R`、`R/theme-elements.R`、`R/theme-defaults.R` | `theme()` / `element_*()` / `calc_element()` / `margin()` / `rel()` + 9 套完整主题（grey / bw / minimal / void / linedraw / light / dark / classic / test）与 `theme_get()` / `theme_set()` / `theme_update()` / `theme_replace()` | 部分实现 | 缺口：`palette.*` 主题元素未实现（`theme.py` 的元素树注释已记录）。元素继承与 `rel` 解析见 `docs/notes/theme.md`，逐元素对拍 `tests/fixtures/theme_r_reference.json` |

## 标注 / 装饰

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.annotations` | `R/annotation.R:43`、`R/annotation-logticks.R:88`、`R/annotation-borders.R:35` | `annotate()` / `annotation_logticks()` / `annotation_borders()` | 部分实现 | 缺口：`annotation_custom()` / `annotation_map()` / `annotation_raster()` 未移植（仓库内无对应符号）。已实现的三个：`annotate()` 复用注册表转成单图层，`annotation_logticks()` 落成 plot 级标注（口径见模块 docstring），`annotation_borders()` 的数据见 `ggcore.map_data` 行 |
| `ggcore.arrow` | grid `arrow()`（`src/library/grid/R/grob.R`） | `arrow()`（`angle` / `length` / `ends` / `type`） | 已实现 | M2-S2（SIL-739）；`Arrow` / `arrow_node_params()` 与 R 的 `arrow()` 同参数名 |
| `ggcore.fills` | grid `linearGradient()` / `radialGradient()` / `pattern()` | `linear_gradient()` / `radial_gradient()` / `tile_pattern()` / `pattern_rect()` / `pattern_circle()` | 已实现 | SIL-751：linear / radial / pattern 三条 case 的 `expected.svg` 已纳管（`refs:gradient-cases`） |
| `ggcore.map_data` | `maps::map()` | `map_frame()`（lon / lat / group） | 部分实现 | 缺口：只内置 `("usa", ".")` 与 `("state", "utah")` 两份数据；其余区域显式 `NotImplementedError` 并指向 `annotate("polygon", …)` |
| `ggcore.map_data_usa` | `maps::map("usa", fill = TRUE)` | `USA` 的 lon / lat | 已实现 | M3-2 的 `annotation_borders()` 数据源；与 `ggcore.map_data` 共用同一份帧格式 |

## 文本度量与排版

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.metrics` | — | 文本度量公开入口（`MetricProvider` / `TableMetrics`） | 已实现 | 上游在 grid：`grid::strwidth()` / `grid::stringWidth()`；M0-7 口径见 `docs/notes/metrics-ledger.md` |
| `ggcore.metrics.provider` | grid `stringWidth()` / `stringHeight()` | `MetricProvider` / `FontMetrics` / `ShapedRun` | 已实现 | 桌面走 HarfBuzz；逐行对拍 `tests/fixtures/text_r_reference.json` |
| `ggcore.metrics.runs` | grid 的 run / grapheme 切分 | `split_runs()` / `clusters()` / `script_segments()` | 已实现 | M0-7；规则版本 `RULES_VERSION` 与 `metrics_table_v2` 同源 |
| `ggcore.metrics.rules` | — | 度量规则的唯一声明（字体栈、脚本区段） | 已实现 | 生成物与运行时共用，避免两处口径；见 `docs/notes/metrics-ledger.md` |
| `ggcore.metrics.catalog` | — | 受管字体定位（`FontCatalog` / `MANAGED_FONTS`） | 已实现 | 字体来自 `pixi.toml` 的 `font-ttf-*`，不读系统字体 |
| `ggcore.metrics.faces` | — | 字面目录：`(族, weight, italic)` → 字体文件 + 可变轴取值 | 已实现 | M0-7 |
| `ggcore.metrics.table` | — | 兜底度量表（逐码点 advance）的编解码 | 已实现 | `pixi run metrics:table` 生成，`metrics:check-table` 守新鲜度 |
| `ggcore.metrics.fallback` | — | 无 HarfBuzz 时的 `TableMetrics`（浏览器 / Pyodide） | 已实现 | 只做逐码点 advance + 粘着规则，不做上下文 shaping——与 `gate:pyodide` 的口径一致；`docs/notes/pyodide.md` |
| `ggshape.harfbuzz` | — | HarfBuzz 形状后端（上游由 Cairo / grid 内部承担，无对应文件） | 已实现 | M0-7：在 `ggcore` 之外（X1 门禁不允许 `ggcore` import 它）；X5 与 CanvasKit 的 advance 对拍见 `gate:metrics` |
| `ggcore.plotmath` | grid `plotmath`（`src/library/grid/R/plotmath.R`） | `parse()` / `layout()` / `MathText` 的最小子集 | 部分实现 | 缺口：只覆盖 `geom-text-with-expressions` 快照用到的语法（希腊字母、`+`/`-`/`*`/`^`/`[]`、`sqrt`），完整 plotmath 未移植；解析不了时退回普通文本（与 R 的 `parse_safe()` 同口径） |

## 空间数据（sf）

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.sf` | `sf` 包的 `st_*`（随 R 4.5 的 r-sf）+ `R/coord-sf.R` | `st_point()` / `st_polygon()` / `st_sfc()` / `st_crs()` / `st_transform()` / `st_graticule()` / `mapproject()` | 部分实现 | 缺口：CRS 只支持 EPSG:4326 / OGC:CRS84 / EPSG:3857 / EPSG:3347，mapproj 只移植 `mercator` / `azequalarea`，其余显式 `SfError`；口径见 `docs/notes/sf.md` |
| `ggcore.sf_stat` | `R/stat-sf.R`、`R/stat-sf-coordinates.R` | `stat_sf()` / `stat_sf_coordinates()` | 已实现 | M3-2：代表点（`point_on_surface()`）与坐标列；20/21 条上游快照纳管 |
| `ggcore.geom.sf` | `R/geom-sf.R:121` | `GeomSf` / `GeomSfText` / `GeomSfLabel` | 已实现 | M3-2：绘制按几何类型分派，图例 key 与上游一致 |

## 导出 / 设备 / 差分

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.io` | `R/save.R:92` | `ggsave()` / `save_ir()` / `export_ir_json()` | 已实现 | M1-12：按后缀选设备、四单位、`.ggir.cbor` / `.ir.json`，见 `docs/notes/io.md` |
| `ggcore.device` | — | 设备协议 `Device`（一页纸 + `Scene` → 字节） | 已实现 | M0-8；X1 门禁要求 `ggcore` 不 import skia，设备实现在 `ggskia` |
| `ggskia` | `src/library/grid/src/grid.c`（`L_points` / `L_xspline`）、`src/main/engine.c`（`GESymbol` / `GEXspline`） | 桌面 / 服务端渲染（skia-python，PNG / SVG / PDF） | 已实现 | M0-8 + SIL-868（SVG 的 `stroke-dasharray`）；pch 全表与 xspline / curve 对拍见 `tests/fixtures/device_render_r/` |
| `ggcore.png` | — | 最小 PNG 编码（`geom_raster` 的位图路径） | 已实现 | 上游由设备承担；这里只编码 RGBA，不依赖 Pillow |
| `ggcore.grobs` | grid 的 grob 模型（`src/library/grid/R/grob.R`） | `RectGrob` / `TextGrob` / `PointsGrob` / `PathGrob` / `XSplineGrob` / `CurveGrob` / `ClipPathGrob` / `GTreeGrob` + `Scene` | 已实现 | M0-6：每种原语一张可视化快照（`pixi run cases:grob`） |
| `ggdiff` | — | 差分：resvg 统一栅格 + 像素判据 + 报告（上游无对应） | 已实现 | M0-9，见 `docs/notes/diff.md` |

## grid 基础设施

上游 `grid` 不在 ggplot2 仓库里，行号写 R 源码（版本由 `pixi.toml` 的 `refs`
环境钉住，见 `docs/notes/units.md`）。

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.units` | `src/library/grid/R/unit.R:25`、`:59`、`:525`；`src/library/grid/src/unit.c:658`、`:1226` | `unit()` / `convertUnit()` / `unit.c()` / `transform()` / `transformFromINCHES()` | 已实现 | M0-3，93 条 R 对拍；`refs:units` |
| `ggcore.gtable` | `gtable/R/gtable.R:94`、`:291`；`R/add-grob.R:45`；`R/add-rows-cols.R:40`、`:96`；`R/padding.R:29`；`R/grid.R:20`；`src/library/grid/src/layout.c:492` | `gtable()` / `gtable_width()` / `gtable_add_grob()` / `gtable_add_rows()` / `gtable_add_cols()` / `gtable_add_padding()` / `gtable_layout()` / `calcViewportLayout()` | 已实现 | M0-5，22 组 R 设备测量对拍；`refs:gtable` |
| `ggcore.viewport` | `src/library/grid/src/viewport.c:213`；`src/library/grid/src/grid.c:139`、`:413`、`:1019`；`src/library/grid/src/matrix.c:96`；`src/library/grid/src/just.c:98`；`src/library/grid/R/grid.R:29`、`:162`；`src/library/grid/R/gpar.R:232` | `calcViewportTransform()` / `doSetViewport()` / `L_setviewport()` / `L_upviewport()` / `trans()` · `multiply()` / `justification()` / `push.vp.viewport()` / `downViewport()` / `set.gpar()` | 已实现 | M0-4，22 个 check 步的 R 对拍 + 手算断言；`refs:viewport` |

## 运行契约

| Python 模块 | 上游文件:行 | 上游符号 | 状态 | 依据 / 缺口 |
| --- | --- | --- | --- | --- |
| `ggcore.cli` | — | CLI 辅助：`unimplemented()` 占位与 `EXIT_NOT_IMPLEMENTED` | 已实现 | 上游无对应；真正的 `render` / `diff` 入口在 `ggskia.cli` / `ggdiff.cli`（`ggcore` 的 X1 白名单不放 skia / Pillow） |

## 刻意不做的格子

下面这些**不是模块**，所以不进上表（表里写不存在的模块名会让门禁的 import
断言失败）。列在这里是为了让「为什么没有这一格」有据可查：

| 能力 | 状态 | 依据 |
| --- | --- | --- |
| 浏览器端 DOM SVG 渲染器 | 刻意不做 | 由 `web/viewer` 的 TypeScript 承担（`render.ts`），零 wasm；`ggcore` 只出 IR，边界见 `docs/notes/viewer.md` |
| `coord_munch` 之外的上游 `R/coord-*.R` 私有辅助 | 刻意不做 | 上游大量 munch / bbox 逻辑与 grid 内部耦合，复刻它们不改变任何可见输出；我们只保留 `ggcore.coord` 的公开行为并逐条对拍 |
| 上游 `R/zzz.R` / `R/onLoad.R` 的包加载钩子 | 刻意不做 | R 的 namespace 加载机制在 Python 侧没有对等物；`ggcore` 的导入顺序由模块依赖决定 |
| `guide_*` 的 S3 协议类（`Guide*` 继承 `ggproto`） | 刻意不做 | 我们用 `Guide` 数据类 + 函数分派（`guide_train()` / `guide_geom()` / …）表达同一份协议；`api:coverage` 的 public 口径覆盖这些钩子名 |

## 维护规则

1. **新增模块必须加一行。** `src/ggcore` 下任何新 `*.py`（含 `__init__.py`）
   都要在上表有一行，否则 `docs:upstream-map:check` 报「源码有、表里没有」。
2. **表里的模块必须能 import。** 反过来，表里写出的每个 `ggcore.*` /
   `ggio.*` / `ggshape.*` / `ggskia.*` / `ggdiff.*` 名字都会被真的
   `importlib.import_module()`；写错名字或删了模块却留行，门禁报「表里有、源码没有」。
   只查一个方向没有意义——两个方向都会漂，所以两个方向都断言。
3. **状态只写三档**，判定依据见上面的「状态口径」。`部分实现` 必须在同一行写清
   缺哪一块；`刻意不做` 必须写清为什么不做、由谁承担。门禁会拒绝三档以外的状态词。
4. **缺口语义要对得上代码。** 写 `部分实现` 之前先 `grep` 一下对应的
   `NotImplementedError` / `raise *Error(...)` 消息：缺口要么在代码里显式报错，
   要么在 notes 里有差异记录，不能只凭印象。
5. **换 pin 时**先跑 `pixi run upstream:diff` 的报表，只更新动过的行；行号写
   「符号定义行」（函数 / 类 / 常量声明行），不写调用点。新增行如果只确认到文件级
   对应，就只写 `R/xxx.R`（不硬凑行号）——冒号后的数字必须真的指到定义行。
6. **上游没有对应物的模块**（IR、skia 设备、`ggcore.perf`、`ggdiff`）在
   「上游文件:行」列写 `—`，状态仍按三档判定（有验收资产就是 `已实现`）。
7. **表头固定**：状态列必须叫「状态」，第一列必须叫「Python 模块」。旧的
   「Python 模块（计划）」写法是漂移的源头（它暗示整表都可以先占位），门禁拒绝
   带「计划」的表头。
