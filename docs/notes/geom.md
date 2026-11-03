# geom 绘制口径（M1-7 / M2-S2）

M1-7 把 `Geom.draw()` 从 `NotImplementedError` 做成真绘制：9 个 geom 的 grob 生成、
`handle_na()` / `setup_data()` / `setup_params()` 契约、坐标变换与裁剪，以及
`PlotBuild + FacetTable → ir.Scene` 的面板装配。

代码：

| 文件 | 内容 |
| --- | --- |
| `src/ggcore/geom/base.py` | `GeomRenderer` 契约、列读取、NA 删行、`flip_data`、`alpha_colour` |
| `src/ggcore/geom/point.py` | `geom_point`（shape 名表、逐点 size 分组） |
| `src/ggcore/geom/line.py` | `geom_line` / `geom_path`（断线、行序） |
| `src/ggcore/geom/bar.py` | `geom_bar` / `geom_col` / `geom_histogram` / `geom_area` |
| `src/ggcore/geom/boxplot.py` | `geom_boxplot`（五数 + 须线 + 中位线 + 离群点） |
| `src/ggcore/geom/smooth.py` | `geom_smooth`（se 带 + 拟合线） |
| `src/ggcore/geom/scene.py` | `PlotBuild + FacetTable → ir.Scene`（面板 / strip / clip） |
| `src/ggcore/geom/segment.py` | `segment` / `curve` / `spoke` / `abline` / `hline` / `vline`（M2-S2） |
| `src/ggcore/geom/rect.py` | `rect` / `tile` / `raster`（M2-S2，位图见 `ggcore.png`） |
| `src/ggcore/geom/polygon.py` | `polygon` / `ribbon` / `step`（M2-S2） |
| `src/ggcore/geom/interval.py` | `linerange` / `errorbar` / `errorbarh` / `pointrange` / `crossbar` |
| `src/ggcore/geom/annotation.py` | `blank` / `rug` / `map`（`map` 只做最小可用） |
| `src/ggcore/geom/stat2d.py` | 2D 族里仍只有 build 级的 5 个（`hex` / `contour` / `contour_filled` / `density_2d` / `density_2d_filled`），`draw()` 点名 SIL-735（M2-6） |
| `src/ggcore/arrow.py` | `grid::arrow()` 的对等物 + 箭翼几何（`head_geometry`） |

## 1. 契约

绘制入口挂在 `ggcore.layer.Geom` 上；**构造函数路径不变**（`as_geom()` /
`geom_*()` 注册表仍然只产生 `Geom(name=…)` 数据对象），方法按名字查
`ggcore.geom` 的实现：

```python
Geom.draw(build, panel, coord, theme, metrics) -> Grob | GTable
Geom.handle_na(data, na_rm) -> ColumnTable
Geom.setup_data(data, params) -> ColumnTable
Geom.setup_params(data, params, *, raw=None) -> dict
```

- `build` 是这一面板的 `LayerBuild`（`data` 已按 `PANEL` 切好、已过
  `handle_na()`、带着图层的 `params` 与 `geom_object`）；
- `panel` 是 `coord.PanelParams`；`coord` 目前只透传（线性坐标的变换都在
  `panel.transform()` 里）；
- `theme` 是 `resolve_theme()` 的解析值，`metrics` 是 `Metrics`（strip 的
  `strheight` 与 text grob）。

`non_missing_aes` / `optional_aes` 与 ggplot2 4.0.3 同名同序（`GeomSpec` 里登记）：
point 的 `size/shape/colour`、line/path 的 `linewidth/colour/linetype`、bar 系列的
`xmin/xmax/ymin/ymax`、smooth 的 `ymin/ymax`。

## 2. 坐标与裁剪

- `coord$transform()` 的等价物是 `PanelParams.transform()`：位置列 → 面板 `0..1`
  （npc，y 向上）。grob 一律 `default_units="native"`，面板视口的 `xscale` /
  `yscale` 都是 `0..1`（与 `ggplotGrob()` 的 panel viewport 一致）。
- 越界值**不夹**：`coord_cartesian` 的语义是画到面板外再按 clip 处理。
- clip 三态（`on` / `off` / `inherit`）落在**面板视口**上，`on` 另加一个
  `ClipPathGrob`（矩形裁剪节点），不是画完再对位图做裁剪。`off` 是 R 的设备
  外包框（1.5×），`inherit` 沿用父视口（页面）。
- 每个面板一个 viewport + 自己的一份裁剪矩形；`facet_wrap` 2×2 的场景里有
  4 个互不相同、互不重叠的 `clip_rect`。

## 3. 九个 geom（M1-7）

| geom | 绘制口径（对 R 4.0.3） |
| --- | --- |
| `point` | `pointsGrob`；`size`（mm）+ `stroke` 折成 `fontsize = size * .pt + stroke * .stroke/2`；`col=alpha(colour, alpha)`、`fill=fill_alpha(fill, alpha)`；IR 的 `points.size` 是标量，所以逐点尺寸按 `(pch, size)` 分组画多个 `pointsGrob` |
| `line` / `path` | 每个 group 一条 `polylineGrob`；`line` 在 `setup_data()` 里按 `(PANEL, group, x)` 排序，`path` 保持行序；NA 用 `keep_mid_true()`：组内首尾缺失删掉、中间保留并断成两段；`lwd = linewidth * .pt` |
| `bar` / `col` | 直接用 M1-9 的 `xmin/xmax/ymin/ymax`，画矩形（`just = c("left","top")`）；`fill` 吃 alpha、`col` 不吃（R 的 `fill_alpha()` 只包 fill） |
| `histogram` | 与柱相同（`stat_bin` 见 `docs/notes/stat.md`；绘制只消费 `x/xmin/xmax/y/ymin/ymax`，`xmin/xmax`/`width` 由 stat 给） |
| `area` | `ymin = 0`、`ymax = y`；上沿正向 + 下沿反向拼一个多边形（`fill` 吃 alpha，按 NA 断段），再按 `outline.type = "both"` 画上下两条轮廓线；横向（`flipped_aes`）在纵向语义拼完再 `flip_data(positions)`，多边形沿长度轴 x 从 `xmin` 铺到 `xmax` |
| `boxplot` | 须线 `(x, upper)→(x, ymax)` / `(x, lower)→(x, ymin)`；箱体 `xmin..xmax × lower..upper`；中位线线宽 `linewidth * fatten`（2）；离群点走 point 的口径（`size * .pt + stroke * .stroke/2`）；`varwidth` 用 `relvarwidth` 缩放箱宽。横向（`flipped_aes`）把（粗细轴, 长度轴）在**一处**对换成页面 (x, y)——须线 / 箱体 / 中位线共用同一个 `axes()` 闭包，纵向的字节序不变（SIL-709 修的：之前只有离群点对换，箱体与中位线仍是竖向坐标） |
| `smooth` | `se != FALSE` 且有 `ymin/ymax` 时画 ribbon（填充、无边），再画拟合线（线不吃 alpha）；行序同 `line` |

`flipped_aes`（横向 bar / boxplot）照 R 的 `flip_data()`：先把 x/y 族列名对换，
在纵向语义下算完再对换回来。`Geom.setup_params()` 只对 R 里真的调用
`has_flipped_aes()` 的 geom 做检测（bar / col / histogram / area / boxplot /
smooth）；point / line / path 不猜朝向。

## 4. 场景装配

```
page viewport（整页）
├── plot.background
├── panel viewport ×N（xscale/yscale = 0..1，clip = panel_params$clip）
│   ├── panel.background / panel.border
│   ├── clipPath（clip = "on"）
│   └── 每层 → Geom.draw()
└── strip（strip.background.x/.y + strip.text.x/.y）
```

- 面板矩形来自 `FacetTable.panel_boxes()`（M1-6 的 gtable 解析）；strip 的位置
  来自 gtable 的 layout，尺寸 / 间距 / 字号 / 颜色全部取 `resolve_theme()` 的
  解析值，不硬编码 cm / pt。
- strip 的行高 / 列宽：有 `metrics` 时走 `Metrics.strheight()`（真实
  ascent + descent），否则退回 M1-6 的 `_STRIP_TEXT_EM` 近似。`facet_table()`
  因此多了一个可选 `metrics=`。
- 图层按层序绘进各自面板；空层（0 行）与空面板不产生 grob。
- 单面板（`facet_null`）走同一条路径：1×1 表、面板就是整页。
- 轴、图例、标题由 M1-11 接上（`ggcore.axis` / `ggcore.guide`，
  见 `docs/notes/guide.md`）：M1-7 的面板 + strip 装配仍是同一条路径，
  `plot_layout()` 只是把面板区从整页里扣出来。

## 4.1 长尾 A 的 20 个 geom（M2-S2）

| geom | 绘制口径（对 R 4.0.3） |
| --- | --- |
| `segment` | 线性坐标一条 `segmentsGrob`（逐行 col / lwd / lty；`lineend` / `linejoin` 走参数）；非线性坐标逐行拆成折线 |
| `curve` | `curveGrob(square = FALSE, squareShape = 1, open = TRUE)`；一条曲线一个 grob（IR 的 curve 节点一次一段） |
| `spoke` | `setup_data()` 先算 `xend = x + cos(angle) * radius`，绘制同 segment |
| `abline` / `hline` / `vline` | 端点取自 `PanelParams.backtransform_range()`；`abline` 在 `clip == "on"` 时先把范围扩一个跨度；`unique0(data)` 去重（参数形态的图层数据是 1 行，不去重会画两遍） |
| `rect` | `resolve_rect()` 补缺角（`x/width/xmin/xmax` 里给两个），`rectGrob(xmin, ymax, just = c("left","top"))` |
| `tile` | `compute_data_size(panels = "by", discrete = TRUE)` 求 `width` / `height`（缺省 1） |
| `raster` | 等距格点 → `(nrow, ncol, 4)` 像素矩阵 → RGBA PNG（`ggcore.png`）+ `rasterGrob(interpolate)`；非线性坐标降级成 rect（`linewidth = 0.3`、`colour = fill`） |
| `polygon` | `coord_munch(..., is_closed = TRUE)` 后每组一只多边形；有 `subgroup` 时走 `pathGrob(rule)` |
| `ribbon` | 上沿正向 + 下沿反向拼**一个环**；`outline.type` = both / upper / lower / full；沿 ribbon 变化的美学报错 |
| `step` | `stairstep()` 逐 group 展开（`hv` / `vh` / `mid`，横向时 hv ↔ vh 互换），再交给 `GeomPath` |
| `errorbar` / `errorbarh` | 每行 8 个顶点（帽、竖线、帽），NaN 断开；`width` 走 `compute_data_size(..., discrete = TRUE)`；`errorbarh` 在 4.0.3 是 `geom_errorbar(orientation = "y")` 的软弃用别名（`height` → `width`） |
| `linerange` | 纵向 `(x, ymin)→(x, ymax)`；横向 `(xmin, y) → (xmax, y)`；方向由 `range_is_orthogonal` 推断 |
| `pointrange` | linerange + 中点（点大小 `size * 4`） |
| `crossbar` | 箱体多边形 + 中位线（`linewidth * fatten`，`fatten = 2.5`）；`middle.*` / `box.*` 覆盖参数；缺口报错 |
| `blank` | `nullGrob()`：只训练标度，不产出叶子 |
| `rug` | 按 `sides`（t/b/l/r）在面板边上画短刻度；`length` 缺省 0.03 npc，`outside = TRUE` 伸到面板外 |
| `map` | `map`（`{x, y, id}`）与 `map_id` 取交集，逐 id 一只多边形；不做投影、不带地图数据 |

**横向（`flipped_aes`）的推断**照 `has_flipped_aes()`：

- `boxplot` / `area`：`boxplot` 走 `main_is_orthogonal` + 列类型（y 离散 → 横向）；
  `area` 传 `ambiguous = TRUE`，**没有 explicit orientation 时永远竖向**（R 侧
  `StatAlign` 也是同一个开关）。横向面积两侧都写 `orientation = "y"`（或 R 的
  `coord_flip()`）——见 `docs/cases/README.md` 的 SIL-715 #4。
- 区间族（`ribbon` / `linerange` / `errorbar*`）：`range_is_orthogonal = TRUE`，
  按「y 族区间在场 → 纵向 / x 族区间在场 → 横向」推断，不看列类型。

**箭头的段长换算**：`lty` 的段长是 `lwd` 的倍数，且 `lwd < 1` 时按 1 算（参考产线
svglite 的口径；细线的虚线不会退化成实线）。段长本身在写 IR 之前折成 pt。

## 5. 与 R 的已知差异 / 未实现清单

| 能力 | 现状 | 去向 |
| --- | --- | --- |
| `arrow =` | v0.3 起是 `segments` / `polyline` / `curve` 的节点参数（§4.1 of `ir.md`），设备画箭翼 | 无 |
| `geom_crossbar(notch)` / 缺口 | 无 IR 表达 → `GeomError` | 后续 |
| `geom_map` 的投影 / 地图数据 | 只做「map 表 + map_id」的最小可用 | 归 M3-2 |
| `geom_boxplot(notch = TRUE)` | 无 IR 表达（缺口多边形）→ `GeomError` | 后续 |
| `geom_boxplot(staplewidth != 0)` | 无 IR 表达（须帽）→ `GeomError` | 后续 |
| 逐点 `size` / 逐点 `pch` | IR 的 `points.size` / `pch` 是标量；绘制层按 `(pch,size)` 分组画多个节点 | 视觉等价，节点数更多 |
| 一条线内部变化的 `linetype` | gpar 的 `lty` 不支持向量 → 取首值（R 会拆 `segmentsGrob`） | 后续 |
| 渐变填充（`fill` 沿 ribbon 变化） | 不支持；R 在非网格设备上同样 abort | 后续 |
| 直线坐标以外的 coord | 未注册（M1-5 的范围） | 后续 coord 任务 |
| 轴标签的 `check.overlap`（重叠时删标签） | 不删 | 后续（`axis.text` 的 `check.overlap`） |
| boxplot 的 `outliers` 列表列 | `ColumnTable` 没有 list kind；`stat_boxplot` 产 `str` 文本（`c(20)` / `c()`），绘制层解析它 | 加 list kind 时再改（见 `stat.md` §4） |
| 2D 族 6 个 geom 里仍有 5 个（`hex` / `contour` / `contour_filled` / `density_2d` / `density_2d_filled`）**只有 build 级**：`setup_data()` 与默认美学照上游，`ggplot_build()` 的 `$data` 与 R 逐列一致；`draw()` 报 `GeomError` 并点名归属（见下行） | — |
| `geom_tile` 的绘制 | 已落地（`ggcore/geom/rect.py`）：默认 `fill = grey20` / `linewidth = 0.2`（上游 `col_mix(ink, paper, 0.2)` / `0.4 * borderwidth`），带 `docs/cases/geom-tile` | SIL-737（完成） |
| `hex` / `contour` / `contour_filled` / `density_2d` / `density_2d_filled` 的绘制 | `draw()` 点名 SIL-735 | SIL-735（M2-S2 geom 长尾 B · 2D 族），见 `stat.md` §10.6 |

主题色（`fill = "grey35"` 等语义名）在 `build.data` 里仍是语义名，绘制期的
`fill_alpha()` 会按 `col2rgb()` 折算 RGB；与 R 的 `#595959FF` 在像素上一致。

## 6. 对拍与验收

```bash
pixi run -e refs refs:geom          # 夹具 + 9 张 expected.svg（R 4.5.3 / ggplot2 4.0.3）
pixi run pytest tests/test_geom_draw.py tests/test_geom_r_parity.py -q
pixi run cases:matrix               # 全部 geom 用例逐张 render + diff
pixi run check                      # 全量门禁
```

M2-S2 的 20 个 geom 另有 18 条 case（`geom-segment-arrow` … `geom-area-horizontal`）
与 22 条 R 夹具 case（`tests/test_geom_r_parity.py` 的 `NEW_BUILDERS`），逐列对拍
`ggplot_build(p)$data[[1]]` 的列名 / 列序 / kind / 值；像素对拍全部 < 2% / < 1%。

夹具：`tests/fixtures/geom_r_reference.json`，36 个 case，记录
`ggplot_build(p)$data[[1]]` 的列名 / 列序 / kind / 逐值、`panel_params` 的
`continuous_range`，以及 `ggplotGrob()` 期间的 warning（`handle_na` 的
"Removed N rows"）。stat 已实现的 7 个 case 在 Python 侧重放整条流水线逐列对拍；
stat 未实现的 4 个（histogram / boxplot / smooth）把 R 的 `$data` 当绘制输入。

九张用例图对 R 参考的实测差异（`pixi run diff`）：

| case | 图级 | 平均 |
| --- | --- | --- |
| `geom-point-shapes` | < 1% | < 1% |
| `geom-line-groups` | 0.000% | 0.000% |
| `geom-path-order` | 0.000% | 0.000% |
| `geom-bar-stacked` | 0.000% | 0.000% |
| `geom-col-identity` | 0.000% | 0.000% |
| `geom-area-identity` | 0.000% | 0.000% |
| `geom-histogram-identity` | 0.000% | 0.000% |
| `geom-boxplot-precomputed` | < 2% | < 1% |
| `geom-smooth-se` | 0.019% | 0.001% |

（点与箱线图的残余差异来自符号边缘的抗锯齿；两者都在 2% / 1% 阈值内。）

## 7. 变更记录

| 日期 | 任务 | 改动 | 原因 |
| --- | --- | --- | --- |
| 2026-11-03 | SIL-737 / M2-S2 | 长尾 A：20 个 geom（线段 / 矩形 / 区间 / 标注族）+ IR 0.3 的箭头标记属性（`segments` / `polyline` / `curve`）+ `geom_raster` 的位图路径（`ggcore.png`）+ lty 段长按 `max(lwd, 1)` 折算（参考产线口径）。`geom_abline` / `hline` / `vline` 改成上游的「参数即图层数据」形态（`inherit_aes = FALSE`、`unique0(data)`）。 | M2 长尾补齐；SIL-715 #4/#5 结案。 |
| 2026-11-02 | SIL-709 / SIL-716 | 横向 `geom_boxplot`：`draw()` 里新增 `axes()`，flip 时把长度值（`xlower` / `xupper` / `xmin` / `xmax`）摆到 x、类别位置摆到 y；须线 / 箱体 / 中位线共用这一处对换，纵向分支仍返回原顺序（字节序不变）。 | M1-15 写 `geom-boxplot-horizontal` case 时发现：修前只有离群点做了对换，箱体与中位线仍按纵向坐标拼，横向箱线图整只箱被摆错方向。回归：`tests/test_geom_draw.py::test_horizontal_boxplot_puts_length_on_x_and_category_on_y`。 |
