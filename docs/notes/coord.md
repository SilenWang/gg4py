# 坐标口径（M1-5）

`ggcore.coord` 是 ggplot2 4.0.3 的坐标系对等物：`coord_cartesian()` 与
`coord_fixed()`。它只回答三件事，全部在**设备单位**上可断言：

1. **面板范围**（`PanelParams.x_range` / `y_range`）——含 expand；
2. **数据 → 面板 npc**（`PanelParams.transform`）——已过标度映射的位置列 → `0..1`；
3. **面板尺寸**（`PanelParams.panel_sizes`）——给定可用区域时 panel 的宽高；
   `coord_fixed` 在这里落实比例，不是把 `ratio` 存进参数对象就完事。

代码：`src/ggcore/coord.py`。测试：`tests/test_coord.py`（口径 / 负向）、
`tests/test_coord_r_parity.py`（R 逐值对拍）、`tests/test_coord_aspect.py`
（PNG / SVG 像素测量）。R 夹具：`tests/fixtures/coord_r_reference.json`，
生成命令 `pixi run -e refs refs:coord`。

```
plot.coordinates (ggcore.components.Coord)
        │  coord_from_component()
        ▼
CartesianCoord / FixedCoord ──panel_params(scales)──▶ PanelParams
                                                        │
                            build_plot() 追加越界计数 ──┤
                                                        ▼
                         PlotBuild.coord / PlotBuild.panel_params
```

`build_plot()` 的六个阶段一个都没改：只在末尾读一次 `plot.coordinates`，
用训练好的 `ScaleSet` 算面板参数，并把越界提示并进 `PlotBuild.warnings`。

## 1. 面板范围 = base + expand

```
base  = coord 的 xlim/ylim（有就覆盖，先过标度变换）或位置标度的 limits()
range = expand_range(base, mult, add)
```

- **连续标度**：`base = ScaleSet.limits("x")`（训练范围或显式 `limits`）；
  默认 `expand = expansion(mult = 0.05)`。
- **`xlim` / `ylim` 是数据空间的值**：连续标度上先过位置的
  `transformation$transform()` 再 expand（R 4.0.3 `expand_limits_scale()`）。
  所以 `scale_x_log10() + coord_cartesian(xlim = c(1, 100))` 的 base 是
  `0..2`、面板 `-0.1..2.1`；`xlim = c(10, 100)` 是 `1..2` / `0.95..2.05`。
  离散标度不做变换（按水平序号解释，见 §2）。
  - `x_limits` 记录的是**变换后**的 base（log10 下 `0..2`），与
    `panel_params$x.range` 只差一次 expand。
  - 变换后不是有限值（log10 的 0 / 负值）直接报 `CoordError`，不静默变 NaN。
- **离散标度**：`base = 1..n`（n = 水平数，含 NA 水平）；默认
  `expand = expansion(add = 0.6)`。所以 3 个水平的面板范围是
  **`0.4 .. 3.6`**。
  - 注意：**不是 `0.5 .. n + 0.5`**。那是「每个水平占一格、再各留半格」的
    直觉口径，但 ggplot2 3.0 之后离散默认 expansion 就是 `add = 0.6`
    （`default_expansion()` 的 `discrete = expansion(add = 0.6)`），
    由 `pixi run -e refs refs:coord` 的 `discrete_default` 逐值确认。
  - 本 issue 正文里写的 `0.5 .. n + 0.5` 与 R 4.0.3 不符；验收以 R 的
    `panel_params$x.range` 为准（容差 1e-12）。
- **`expand = FALSE`**：完全不扩；`base` 就是面板范围。
- **数值序列 / `Expansion`**：按上游 `expansion()` 的 `rep_len(…, 4)` 解释
  （标量 / 2 元 `(mult, add)` / 4 元 `(mult_low, add_low, mult_high, add_high)`）。
  这是对 R 的**放宽**：R 的 `coord_*(expand=)` 只收 `TRUE`/`FALSE` 逻辑值。
- 标度自己的 `expand`（`scale_x_continuous(expand = c(0, 0))`）照常生效；
  `coord_cartesian(expand = FALSE)` 覆盖它。

expand 只改面板范围，**不改** `ScaleSet.limits()` 的数据范围（口径见
`docs/notes/scales.md` §expand）。

## 2. `xlim` / `ylim` 与越界点

`coord_cartesian(xlim = c(2, 5))` 与 `scale_x_continuous(limits = c(2, 5))`
的**面板范围相同**（都是 `1.85 .. 5.15`：base 2..5 再扩 5%），区别在数据：

| 写法 | 面板范围 | 越界点 | R 的提示 |
| --- | --- | --- | --- |
| `coord_cartesian(xlim = c(2, 5))` | 1.85..5.15 | **保留**（画到面板外，按 clip 处理） | 无 |
| `scale_x_continuous(limits = c(2, 5))` | 1.85..5.15 | 变 NA（`oob = censor`），绘制期删除 | `Removed N rows …` |

缺失与越界都不静默，分别记在三个计数里（`PanelParams`）：

- `dropped[aesthetic]`：**按轴**统计的缺失值数（原始数据的 NA + 标度
  `oob = censor` 丢掉的值）。同一行 x、y 都缺会各记一次，所以
  `sum(dropped.values())` **不是** R 的 "Removed N rows"，别再拿它当行数说；
- `rows_dropped`：**行级**计数（x / y 任一缺失即一行）——这个才对应 R 的
  "Removed N rows"；
- `out_of_bounds[aesthetic]`：仍是有限值、但落在 **base 范围**（`x_limits` /
  `y_limits`）之外的行数 = `coord_cartesian(xlim=)` 会画到面板外的点。

`coord_cartesian(xlim=(2, 5))` 的 R 参考值是 `removed = 0`、`na_x = 0`，
两个点（x = 1.513 / 5.424）都还在 `$data` 里；Python 侧 `dropped = 0`、
`out_of_bounds = 2`，同一份 6 行数据一行不少。`PlotBuild.warnings` 会按
「行级 Removed + 按轴 NA 数」分别发提示，不会把原始 NA 说成「被 scale
limits 丢弃」。

离散标度上的 `xlim`：

- **数值**（`xlim = c(0.5, 2.5)`）：按连续坐标解释（`base = 0.5..2.5`，
  再按离散 expansion `add = 0.6` → `-0.1 .. 3.1`），与 R 一致；
- **水平名**（`xlim = c("a", "b")`）：按水平序号解释（`base = 1..2` →
  `0.4 .. 2.6`，等价于 `scale_x_discrete(limits = c("a", "b"))` 的面板范围）。
  R 4.0.3 的 `coord_cartesian(xlim = c("a", "b"))` 会直接报
  `missing value where TRUE/FALSE needed`；这里做了一个更有用的口径，
  水平名不存在时报错并列出可用水平。
- 面板要「去掉某些水平」请用 `scale_x_discrete(limits = …)`（R 的标准做法）；
  它会删数据行，`rows_dropped` 计数与 R 的 `Removed N rows` 一致。

## 3. clip

`clip = "on"`（默认）/ `"off"` / `"inherit"`。本任务只**解析并记进**
`PanelParams.clip`；真正的裁剪发生在 geom 绘制期（M1-7）：`clip = "on"` 把
绘制裁到 panel 的 `clip_rect`，`"off"` 允许画到面板外，`"inherit"` 沿用父视口
（页面，clip 也是 off）。三态与 grid 的 `viewport(clip=)` 一致；R 4.0.3 的
`coord_cartesian(clip = "inherit")` 是合法入口。

## 4. `coord_fixed(ratio)`

物理高/宽不是直接等于 `ratio`，而是上游 `CoordFixed$aspect()`：

```r
aspect <- function(self, ranges) diff(ranges$y.range) / diff(ranges$x.range) * self$ratio
```

即

```
panel 的高 / 宽 = ratio × (y 范围跨度 / x 范围跨度)
```

`panel_sizes(device_w, device_h)` 在给定的**面板可用区域**里取满足该比例的最大
内接矩形（宽高同单位；`ggcore.viewport.Device` 用英寸）：

```
aspect >= 1:  width = min(device_w, device_h / aspect), height = aspect × width
aspect <  1:  同理，height 先撞到 device_h
```

轴标签 / 标题的留白由布局负责（M1-11），本模块拿到的就是扣完留白的面板区域。
x / y 数据范围等宽时 `高/宽 = ratio`；共享数据的 x/y 跨度不同时比例会差一个
`y跨度/x跨度` 的因子，这不是 bug（R 的 gtable 也这么排）。

跨度算出来是 0（`xlim` / `ylim` 退化成一个点、或 `expand = FALSE` 下数据全相同）
时 `aspect_ratio` 抛 `CoordError` 并点名是哪条轴 —— 不是 `ZeroDivisionError`，
也不会算出 `Inf` 交给下游布局。

**等比例验证**（`pixi run cases:coord`，产物 `.coord-aspect/`，不入库）：

| case | 场景 | PNG | SVG | 高/宽 |
| --- | --- | --- | --- | --- |
| `fixed-ratio-1` | 6×4 in 页面、x/y 范围等宽 | 600 × 600 px | 288 × 288 pt | 1.0000 |
| `fixed-ratio-2` | 同上 | 300 × 600 px | 144 × 288 pt | 2.0000 |
| `cartesian-control` | 不写 coord | 900 × 600 px | 432 × 288 pt | 0.6667 |

PNG 量「非白像素外接框」（150 dpi），SVG 量面板底色矩形的 `width/height`；
两条路径独立，容差都是 0.5%。对照 case 证明「不写 `coord_fixed` 时没有偷偷
把面板做成 1:1」。

## 5. 根视口的 `native` = 英寸

M0 交接的遗留口径在本任务收口：

- R 的根视口 `xscale`/`yscale` 是**设备原生单位**（pdf 下 0..504 点）；
- ggcore 的 `Device` 以英寸计量，所以根视口 `xscale = 0..width_in`、
  `yscale = 0..height_in`，于是**根级 `unit(1, "native")` = 1 英寸**（位置与
  尺寸都成立）；
- 子视口不改语义：仍按自己的 `xscale` / `yscale` 换算。`xscale = 0..10` 铺满
  6in 的视口里，`unit(1, "native")` = 0.6in（R 一致）。

测试：`tests/test_viewport.py::test_root_native_units_are_device_inches`。

## 6. M2-1：`coord_*` 全量（12 个导出）

4.0.3 NAMESPACE 的 12 个 `coord_*` 导出全部落地（`coord_munch` 是函数，不是
坐标系构造器）：

| 导出 | 实现 | 关键口径 |
| --- | --- | --- |
| `coord_cartesian` | `CartesianCoord` | 范围 / `xlim` / `expand` / `clip` / `reverse` / `ratio` |
| `coord_fixed` | `FixedCoord` | `aspect = ratio × y 跨度 / x 跨度` |
| `coord_equal` | `EqualCoord` | 就是 `coord_cartesian(ratio = 1)`（上游同） |
| `coord_flip` | `FlipCoord` | 见 §7；**不是**交换 x/y 映射 |
| `coord_trans` / `coord_transform` | `TransCoord` | 见 §8；`coord_trans()` 在 4.0.3 已弃用，仍导出 |
| `coord_polar` | `PolarCoord` | 见 §9；`theta` / `start` / `direction` / `clip` |
| `coord_radial` | `RadialCoord` | 见 §9；partial arc / `inner.radius` / `reverse` / `r.axis.inside` |
| `coord_sf` / `coord_map` / `coord_quickmap` | `SfCoord` / `MapCoord` / `QuickmapCoord` | 见 §11（M3-2：真实投影 / graticule / mapproj mercator） |
| `coord_munch` | `ggcore.coord.coord_munch()` | 见 §10（非线性坐标的逐边细分） |

`PanelParams` 新增（都有默认值，旧调用点不受影响）：

- `flipped`：`coord_flip` 的屏幕轴 ↔ 数据轴对调；
- `trans`：`{axis: CoordTransform}`（`coord_trans`）；
- `cont_ranges`：上游的 `continuous_range`（标度空间的 expand 结果；断点与
  次轴用它，`coord_cartesian(xlim=)` 下与 `ranges` 不同）；
- `polar`：`PolarGeometry`（theta / r 范围、`arc`、`inner_radius`、`bbox`、
  `axis_rotation`）；
- `reverse`：`{axis: bool}`（只翻转映射 `1 - t`，不改范围）。

两个入口（`+` 与方法链）由注册表统一生成；**位置参数**按上游签名落位：
`coord_polar("y")`、`coord_fixed(2)`、`coord_transform("log10")`、
`coord_radial(inner_radius=0.3)`（点号名在 Python 侧折成下划线）。

## 7. `coord_flip`

上游（`CoordFlip`）做的是三件事，这里逐条落实、geom 里**不判断 coord 名字**：

1. `flip_axis_labels(data)`：`transform_column()` 读对侧列（`x` ← `y`，
   `xmin` ← `ymin` …；表在 `ggcore.aes.flipped_names()`）；
2. `flip_axis_labels(panel_params)`：`x_range` / `y_range`、`*_limits`、
   `cont_ranges`、`discrete` 全部对调；
3. `setup_layout()` 交换 `SCALE_X` / `SCALE_Y`：底部轴用原 y 标度（位置按
   `x_range`），左侧轴用原 x 标度——`PanelParams.scale_key("bottom")` 给出这一点。

所以 `geom_col() + coord_flip()` 就是横向柱：柱的数据列不变，屏幕坐标在
`transform_column()` 里换边。`coord_flip` 接受 `xlim` / `ylim` / `ratio` /
`reverse`（上游继承 `CoordCartesian`）。

## 8. `coord_trans` / `coord_transform`

- 变换在**标度空间之后**再作用一次（上游 `CoordTransform$transform()`）：
  `data$x` 已经是标度变换后的值，`coord_trans` 再套一次 `trans$x$transform`。
- 面板范围：`expand(trans(base))`，**先变换再 expand**（上游
  `expand_limits_continuous_trans()`）。例：identity 标度 + `x = "log10"`、
  数据 1.513..5.424 → `log10` 空间 0.180..0.734 → 面板 `0.152..0.762`。
  `continuous_range` 是反变换回标度空间的结果（断点用它）。
- 刻度位置：`rescale(trans(break), range)`；标签仍是未变换的断点文本。
- 已实现的名字：`identity` / `log` / `log2` / `log10` / `log1p` / `exp` /
  `sqrt` / `reciprocal` / `reverse`，也接受函数（函数没有逆变换，涉及反演时
  报 `CoordError`）。其余（`boxcox` / `logit` / `probit` …）点名报错。
- 定义域外（`log10` 的 0 / 负值）在范围计算阶段就报错，不静默画 NaN。

## 9. `coord_polar` / `coord_radial`

范围与上游 `CoordPolar$setup_panel_params()` 一致：

| 轴 | 展开 |
| --- | --- |
| theta（`coord_polar`） | 离散 `add = 0.5`（**不是** 0.6）、连续不展开 |
| r（`coord_polar`） | 不展开 |
| theta / r（`coord_radial`） | 标度默认展开（连续 5% / 离散 add 0.6），`expand = FALSE` 关闭 |

映射：`theta_rescale()`（弧度，`start` + `direction`，`%% 2π`）与
`r_rescale()`（默认 donut `0..0.4`，radial 用 `inner.radius·0.4 .. 0.4`），
`x = r·sin θ + 0.5`、`y = r·cos θ + 0.5`；partial arc（`start` / `end`）再按
上游 `polar_bbox()` 的包围盒缩放。`coord_radial` 默认 `clip = "off"`，
`coord_polar` 是 `"on"`。

渲染（`ggcore.geom.scene`）：

- **断点走面板范围**（SIL-839）：R 的 `scale$break_info(range)` 拿到的是
  `setup_panel_params()` 里展开后的 `theta.range` / `r.range`，所以
  `coord_polar()` 的两条轴都**不展开**——`y` 数据 0.25..0.8 的 r 断点是
  0.3/0.4/…/0.8 六条（每 0.1），不是标度自己的 5% 展开范围给出的
  0.4/0.6/0.8 三条。`ggcore.axis.polar_axis_breaks()` / `polar_minor_breaks()`
  负责这件事；直接调 `scale.breaks()` 会让 r 圈少一半、theta 辐条错位
  （`matrix-report-facet-polar-grey` 图级 8.54% → 4.45%）；
- 背景网格换成「theta 辐条 + r 同心圆」：辐条 `0 → 0.45`（radial 从内半径
  到 0.4），圆按 **`r` 的主断点**采样 100 点（polar 额外画 0.45 外圈）。
  R 的 `CoordPolar$render_bg()` 只渲染 `panel.grid.major.<r>`：theta 有 minor
  辐条，r **没有** minor 圆——`panel.grid.minor.<r>` 在 polar 下不消费（SIL-790）。
  theta 的次辐条序列是 `scales::regular_minor_breaks()` 的原样输出（「每段
  左端点 + 中点」再补最后一个主断点），**包含主断点本身**，所以每条主辐条会
  被画两遍（细线压在粗线下，SVG 里两份都在）；
- theta 标签画在面板里、半径 0.45 处（`axis.text.x` 的样式，`hjust = vjust =
  0.5`）；首尾重合（`ends_apart < 0.05`）时合并成 `"a/b"`；
- r 轴在 `left` 槽，位置 `r_rescale(r) + 0.5`（`r.axis.inside` 时不上槽）；
- `aspect = 1`（polar）或 `diff(bbox$y)/diff(bbox$x)`（radial）作用在**每个
  panel 单元格**上：spacing / strip 不变，整块居中（R 的 `respect`）。
  `coord-polar-facet` 的 141.26pt 面板宽度与 R 逐像素一致。

**radial 的 `respect` 实测（SIL-839，待照抄）**：`coord_radial(inner.radius = 0.5)`
+ `theme_test()` 的 10×8in 图上，`ggplotGrob()` 的表是（grid pt）：

| 项 | 值 |
| --- | --- |
| `gt$widths` | `5.5, 0, 0, 0, 12.637(ylab-l), 1null + 0.422cm + max(0, -0.0966cm) + 0.0966cm(axis-l), 1null(panel), 0, 0, 0, 0, 0, 5.5` |
| `gt$heights` | `5.5, …, 12.637(xlab-b), …, 1null(panel), …, 5.5` |
| `respect` | `TRUE` |
| panel viewport | 554.52 × 554.52（grid pt）＝ 552.45 × 552.45（SVG pt） |
| **实际绘制方形** | **535.11 × 535.11（SVG pt）**（`x = 107.19, y = 22.79`） |

两个数是分开的：panel viewport 552.45，绘制内容只有 535.11，差 **17.34pt**。
`axis-l` 那一列不是纯 null，而是 `1null + 0.519cm`（0.422 + 0.0966）的复合单位，
所以 `respect` 的 null 分摊与面板绘制尺寸不是同一个量；差值的 17.34 ≈ 0.519cm(14.71)
+ 2.63，尚未对上是哪一项。**下一步照这张表复刻**：先按 `1null + 0.519cm` 给
`axis-l` 建模，再看 `respect` 解出来的 null 与实际绘制方形的关系——不要再用
「可用高度减 17.36」这类数值拟合（SIL-839 试过：方形尺寸对上了，但居中位置差 9.7pt）。

**`axis-b` 行（SIL-790 已对齐）**：R 的 `CoordPolar$render_axis_h()` 返回
`draw_axis(NA, "", "bottom")`，`ggplotGrob()` 仍给底部轴留一行：刻度长度 +
theta 标签行。标签行高来自 `titleGrob`（`grobheight + |cos θ|·descent`），对
4–52 pt 的轴文字是一条直线 `0.22·size + 2.2` pt（8.8 pt → 4.19 pt，合计
`axis-b = 6.94 pt`），见 `ggcore.axis.polar_axis_row_cm()`。修前按 0 处理，
带轴的 polar 图面板比 R 大 6.8 pt，同心圆全部错位（`numeric-polar` 图级
5.24% → 1.78%）。轴文字是 `element_blank()` 时只剩刻度长度。

`coord_radial()` **没有**这一行（SIL-839）：它的 `render_axis_h()` 在
`r.axis.inside = FALSE`（整圆时的默认值）才委托给 `CoordCartesian`，而 radial
的 `panel_params` 只有 `theta` / `r` 两组 view scale、没有 `x`，于是左右两侧
拿到的都是 `zeroGrob()`。R 的 gtable 实测（`guide-axis-theta with angle adapting`，
10×8in）：row 10（`axis-b`）= 0，只有 row 11（`xlab-b`）= 12.97pt。theta 标签
永远画在面板里，不占行列。

## 10. `coord_munch()`

非线性坐标（polar / radial / 非 identity 的 `coord_trans`）下，rect / polygon
的边不能只变换端点（会变成弦）。`coord_munch(panel, table, ...)`：

- 线性坐标直接 `project_xy()`（与上游 `if (coord$is_linear())` 同）；
- 非线性坐标按**数据空间**的归一化距离（除以面板跨度）细分（默认
  `segment_length = 0.01`），再逐点投影；`is_closed=True` 先闭合成多边形。

geom 侧唯一的分支点是 `panel.is_linear`（能力判断，不是 coord 名字）：
`geom_bar` / `geom_col` / `geom_histogram` 走 `_munch_rects()`，
`geom_area` 走 `_munch_area()`。玫瑰图（`coord-polar-bar`）因此逐像素通过。

## 11. `coord_sf` / `coord_map` / `coord_quickmap`（M3-2 起完整）

M2-1 只做注册与最小可用；**M3-2 已落地**（口径与已知差异见
`docs/notes/sf.md`）：

- `coord_sf()`：EPSG:4326 / 3857 / 3347 的真实投影，`crs` 缺省取第一层几何的
  CRS，`default_crs` / `lims_method` / `reverse` / `label_axes` /
  `label_graticule` 全部落地；经纬度的 `aspect = (y/x) / cos(中心纬度)`；
  面板网格与四边刻度来自 `st_graticule()`。
- `coord_map()`：mapproj 球面 mercator（`orientation` 缺省
  `c(90, 0, mean(lon))`）；其它投影（`gilbert` / `ortho` / `conic` …）显式报
  `CoordError` 并点名 M3-2。
- `coord_quickmap()` 可用：`aspect = (y/x) / cos(面板中心纬度)`，与上游
  `CoordQuickmap$aspect()` 同式；`coord-quickmap` 案例逐像素对拍（0.14%）。
- 主轴位置：`scale_*_continuous(position = "top" | "right")` 生效（M3-2，
  `coord-map` 的 switched-scale-position 快照）。

## 12. 次轴（`sec_axis()` / `dup_axis()`）

- `scale_y_continuous(sec.axis = sec_axis(~ . * 2, name = "double"))`：断点 /
  标签由 `ggcore.axis.secondary_ticks()` 推出（上游
  `AxisSecondary$break_info()` 的移植）：主轴 `continuous_range` 上取 1000 个
  样点 → 变换 → `extended_breaks()` → `np.interp()` 反演回主轴值 → npc。
  变换必须严格单调，否则报 `AxisError`。
- `dup_axis()` 是 `sec_axis(identity)`：位置 / 标签与主轴完全相同。
- 次轴标题（R `AxisSecondary$make_title()`，4.0.3 实测）：`sec_axis()` 的
  `name` 缺省是 `waiver()`（gg4py 的 `None`）→ **不显示标题**（`name = NULL`
  相同）；只有显式给名字才画标题。`dup_axis()` 的缺省是 `derive()`（gg4py 的
  `DERIVE`）→ 沿用主轴标题。旧的 gg4py 把「没给名字」也当成沿用主轴，顶部会
  多出 0.444cm 的 `xlab-t`（SIL-759）。
- 次轴画在 **top / right** 槽（R 的 axis-t / axis-r），主轴仍是 bottom / left；
  两边的占位分别计算（`x_axis_top_cm` / `y_axis_right_cm` +
  `x_title_top_cm` / `y_title_right_cm`），次轴不会把主轴槽撑大。
- 极坐标 / 径向坐标下的次轴（`r.sec` / `theta.sec`）明确报
  `AxisError`（M2-1 未做）。
- `sec_axis()` 的 `breaks` 目前只接受 2 元范围（R 的 `c(lo, hi)` 形式）；
  自定义函数 / 标签照上游支持。

## 13. 不支持清单（M2-1 之后仍缺）

| 能力 | 现状 | 计划 |
| --- | --- | --- |
| polar / radial 的 `theta.sec` / `r.sec` 次轴 | 明确报错 | 后续 coord 任务 |
| polar 带轴时的空轴行（≈0.147cm，见 §9） | 不占位 | 与 theme 口径一起收 |
| 非矩形 clipPath（radial 的扇形裁剪） | 只有矩形裁剪；数据在 arc 外不会被裁掉 | IR 多边形 clip 接入后 |
| `coord_sf` 的 plotmath 度数标签 | 单段文本（宽度按 degree 符号 0.376em 折算） | 完整 plotmath 引擎 |
| `coord_map` 的非 mercator 投影 | 明确报错 | 需要 mapproj 全量 |
| facet free scales × `coord_trans` | 每面板范围独立，但断点仍共用一个 `continuous_range` | 后续 |
| 离散标度的显式 `limits` 里没有数据的水平 | `levels` 不含它（M1-4 缺口），轴断点会少一个 | SIL-715 同族 |

`coord_*` 的参数集合是封闭的：不认识的参数直接报错（与 R 的 unused argument
一致），不会静默吞掉。

## 14. 验收命令

```bash
pixi run check                       # 全量门禁（含 gate:imports / gate:determinism）
pixi run -e refs refs:coord          # 重新生成 R 夹具（产物入库，CI 不装 R）
pixi run -e refs refs:cases          # 重画 docs/cases/*/expected.svg（含 coord 族）
pixi run cases:coord                 # PNG / SVG 等比例测量，产物在 .coord-aspect/
pixi run pytest tests/test_coord.py tests/test_coord_ext.py \
  tests/test_coord_r_parity.py tests/test_coord_aspect.py -q
```

coord 族的案例（`docs/cases/coord-*`，12 条，全部 `ci = true`）：

| case | 演示 |
| --- | --- |
| `coord-flip-points` / `coord-flip-bar` | flip 的点 / 横向柱 |
| `coord-trans-log10` / `coord-trans-sqrt` | 逐轴变换 |
| `coord-equal` | 等比例面板 |
| `coord-polar-bar` | 玫瑰图（munch 弧边） |
| `coord-polar-facet` | polar × facet（每块面板正圆） |
| `coord-polar-theta-y` | theta = y |
| `coord-radial-partial` / `coord-radial-inner` | partial arc / 甜甜圈 |
| `coord-sec-axis` | 右侧次轴 + 标题 |
| `coord-quickmap` | 经纬度的等距圆柱近似 |
