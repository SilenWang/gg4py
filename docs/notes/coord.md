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

**polar 网格当前的实测缺口（SIL-839，待修）**：`guide-axis-theta-with-angle-adapting-to-theta`（口径已按上游测试修正：默认 `theme_grey()`，见 `theme.md` 第 6 条）在 55.2% 时，
逐项数是：

| 元素 | expected.svg | 我们的 SVG |
| --- | --- | --- |
| `fill: #EBEBEB` 的 panel 背景 | 1 个 polygon | **1 个 rect ✓**（scene 里也是 1 个 `(235,235,235,255)`） |
| `stroke: #FFFFFF` 网格线 | **47 条** | **0 条** |
| `stroke: #333333` | 40 条 | 46 条 |

所以「背景 rect 缺失」不成立——背景两条路径（scene / SVG）都在。缺的是 **polar 的
网格线**：`theme_grey()` 的 `panel.grid = element_line(colour = paper)`（白）与
`panel.grid.major` 的 `linewidth = rel(0.1)` 都在，但 `_polar_grid_grobs()` 一条
都没产出。下一步查这一步（`theme.get("panel.grid.major.x"/".y")` 的解析结果、
`paint()` 对白的返回值、以及 `polar_theta_ticks()` 是否为空导致早退），改完必须
跑全量 `cases:matrix`（polar 背景/网格影响所有 polar 快照，`matrix-report-facet-polar-grey`
当前 4.39% 不能破线）。
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

**`0.9686` 的定论（SIL-839，别再在 SVG 坐标系里反推几何）**：`expected.svg` 里量到的
`#EBEBEB` 背景 polygon 是 **428.10 × 428.08**，而 R 的几何是 **0.1..0.9 npc**，
按 552.45 的 panel cell 换算应为 `0.8 × 552.45 = 441.97`；`428.10 / 441.97 = 0.9686`。
refs 环境直接跑 `ggplot2:::coord_munch(coord, data_frame0(x=c(1,1,-1,-1), y=c(1,-1,-1,1))*Inf, pp, is_closed=TRUE)`
得到的 x/y 范围是 **0.1000..0.9000**（`ggplot2:::r_rescale(35.075, r.range, inner_radius)`
的上界是 0.4），**几何里没有 0.9686**。所以：

- `0.9686` 是 **svglite 输出层的 viewport 缩放**（panel viewport 的内容坐标被缩放后写进
  SVG），ggplot2 的几何里不存在；
- 反过来也成立：**不能拿 `expected.svg` 的绝对坐标当 ggplot2 的几何值**——两边要比较，
  必须先除以 0.9686（或只比 `尺寸/panel cell` 的比值）；
- 同一条也解释了为什么我们的背景 rect 441.97 是**对的**、而 SVG 里看起来比 R 大 3.2%。

**`respect` 不是按 null 权重分配，而是整体等比缩放（SIL-839 实测）**：把同一张图的
panel 列从 `1null` 改成 `2null` 再 draw，panel 从 554.39×554.39 变成 683.93×341.97，
而**固定列也被一起缩放**——panel 的左边界从 `1.357in` 移到 `0.460in`（`ylab-l` /
`axis-l` 这些 `grobwidth` / `points` 单位跟着变了）。把 panel 行改成 `2null` 同样让左边界
跳到 `3.274in`。所以 `_aspect_panel_area` **不能**按「两轴 null 的权重比例」算，也不该引入
常数：grid 在 `respect = TRUE` 时先把 fixed 单位与 null 一起按比例缩放，再让 null 相等。

`coord_sf()` 的同一次实测（`r-sf` 已进 refs 环境）：

| 项 | 值 |
| --- | --- |
| `widths` | `5.5, 0, 0, 0, 12.637(ylab-l), **sum(0cm, 1null, 0.8287cm, 0null, max(0,-0.0966cm), 0.0966cm)**(axis-l), 1null(panel), **sum(0.0966cm, max(0,-0.0966cm), 0null, 0.7790cm, 0.8478cm, 1null, 0cm)**(axis-r), 12.637(ylab-r), …, 5.5` |
| axis-l 的**固定**部分 | 0.8287 + 0.0966 = 0.9253cm ＝ 26.22pt（`convertWidth` 对它给 26.33，null 不计） |
| axis-r 的固定部分 | 1.7234cm ＝ 48.83pt |
| panel viewport | 397.65 × 528.19（grid pt，**非方形**：528.19/397.65 = 1.328 = sf 的 aspect） |
| 实际绘制内容 | 383.48 × 509.38（SVG pt）＝ cell × **0.9644**（等比缩放，不是减常数；radial 那条同样是等比：535.11 / 552.45 = 0.9686） |

**下一轮照这张表复刻**：先按 `1null + 固定 cm` 给三类列（panel / axis-l / axis-r）建模，
把 grid 的「整体等比缩放」写进 `_aspect_panel_area`，再核对 0.9644 / 0.9686 这同一个
缩放因子；不要再用「减 17.36」这类常数（regression：数值拟合会让居中位置差 9.7pt）。

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

**数 SVG 要用 `pixi run svg:stats -- a.svg b.svg`**（SIL-839）：颜色先归一化
（`white` / `#FFFFFF` / `rgb()` / `grey60`）再按 `(stroke, stroke-width)` 分组，
两个 SVG 并列打出差异。手数连通两轮栽在 `#FFFFFF` vs `white` 上。
注意它数的是**元素数**：R 的 `element_render(..., id.lengths = rep(2, n))` 会把
theta 的 35 条次辐条合成**一个** `<polyline>`，我们的设备每条一组元素——所以
「`#FFFFFF 0.53` 23 vs 35」这种差首先是分组差，必须再数线段（`points` 个数 / 2）
才能判断几何是否真的多画了。

**参考系换算的完整例子（SIL-839，跨文件比较必须走这一步）**

同一个元素（`panel.background`，几何上是 npc 0.1..0.9）在两个文件里的绝对 x：

| | 左边界 | 右边界 | 宽度 |
| --- | ---: | ---: | ---: |
| `expected.svg`（svglite） | 160.70 | 588.80 | 428.10 |
| 我们的 SVG | 152.665 | 594.634 | 441.970 |

由这两个点解 `x_expected = a + s · x_ours`：

- `s = 428.10 / 441.970 = 0.96861`
- `a = 160.70 − 0.96861 × 152.665 = 12.83`

用中心回验：R 的中心 `374.75` 换算到我们的参考系是
`(374.75 − 12.83) / 0.96861 = 373.65`，我们的中心是 `373.649`——**差 0.001**。

所以之前记的「中心差 1.10 = `axis-l` 列宽」**是参考系产物**，换算后归零；
`coord_sf` 那条的 1.1pt 与本条不是同一根因，不要合并处理。

**`coord_sf` 的 1.1pt 是真实存在的（SIL-839 实测，非参考系产物）**

两边的页面坐标系完全一致（`viewBox` 都是 `0 0 720 576`、根节点无额外 transform），
所以直接取 panel 绘制区（`clipPath` 的 rect）比较即可：

| | 左 | 顶 | 宽 | 高 |
| --- | ---: | ---: | ---: | ---: |
| `expected.svg` | 157.15 | 48.55 | 383.48 | 509.38 |
| 我们的 SVG | 156.05 | 48.40 | 383.61 | 509.54 |
| 差 | **+1.10** | +0.15 | −0.13 | −0.16 |

宽度与高度几乎相等（差 0.13 / 0.16），**只有左边少 1.10**——即 `plot.margin` +
`axis.title.y` + `axis-l` 这一串左侧固定宽度合计少 1.1pt。

我们这边的 `y_axis`（axis-l）是 **25.42pt**；R 的 gtable 里 `axis-l` 固定部分是
`0.8287cm(axis.text) + 0.0966cm(ticks)` = **26.22pt**。差 **0.80pt**，
剩下 0.30pt 应在 `plot.margin`（5.5 vs 5.48）与 `axis.title.y`（12.637 vs 12.57）的
舍入差里，合计刚好 1.1。

修法（尚未实施）：把 angle≠0 轴标签的旋转 extent 固定部分从 25.42 提到 26.22
（`_label_stats` 的 `cross` 项），再跑全量矩阵确认没有别的角度轴被带偏。

**`0.8pt` 归因到哪一类：隔离实验的第一轮（SIL-839，未收敛）**

思路是拿 0°/90° 的已绿 case 比 `axis-l` 列宽——0° 时 `cross` 只吃 `line`，
90° 只吃 `width`，两条都对得上就说明字体口径没问题、`0.8pt` 落在旋转路径的附加项上。

第一轮选的是 `upstream-guide-axis-axis-guides-basic`（0°，`theme_test()`）：

| | 我们 |
| --- | ---: |
| `y_axis`（axis-l） | 4.73pt |
| `x_axis`（axis-b） | 7.32pt |

**这条不能用来做隔离**：它的轴标签是单字符（`"0"` 这类），`x_axis 7.32pt`
里几乎全是 tick。要判断字体口径得挑一条 **0° + 8.8pt 长标签**的 case
（和 `coord_sf` 同字号），再和 R 的 `axis-l` 固定部分
（`0.8287cm(axis.text) + 0.0966cm(ticks)` = 26.22pt）对——两者一致就说明
`text_line_cm` 没问题，`0.8pt` 属于旋转附加项；差 0.8 就是字体口径。

**下一轮第一件事**就是这条对照（一条 0° 长标签 case 的 `y_axis_cm` 对 26.22），
不要直接改 `_label_stats()`——按 SIL-839 的硬要求，`0.8pt` 必须先归到某个分量。

**`0.8pt` 归因完成：不在字体口径，在旋转路径（SIL-839 原语直接对比）**

refs 里直接量 grid 原语（`textGrob("25", gp = gpar(fontsize = 8.8))`），对我们同口径函数：

| 量 | R（pt） | 我们（pt） | 差 |
| --- | ---: | ---: | ---: |
| 行高 `grobHeight` / `text_line_cm(8.8)` | 6.486232 | 7.8716（`TEXT_LINE_EM = 0.8945`） | **+1.385** |
| 字宽 `grobWidth` / `text_width_cm("25", 8.8)` | 10.04553 | 10.56 | **+0.514** |

45° 下 `cross = 0.707·(width + line)`，所以字体原语让我们**偏大**
`(1.385 + 0.514) × 0.707 = +1.34pt`。

而实测我们的 `axis-l` 反而**小 0.80pt**。两者符号相反 ⇒

```
旋转路径上还少了一项 ≈ 1.34 + 0.80 = 2.14pt
```

再拆一层：两边 `axis.text` 部分（扣掉 `axis.ticks.length` 2.74pt）：

| | `axis.text` 段 | 旋转 extent（`0.707·(w+line)`） | 余下 margin |
| --- | ---: | ---: | ---: |
| R | 23.49 | 11.69 | **11.80** |
| 我们 | 22.68 | 13.03 | **9.65** |

**差额正好 2.15pt，落在 margin 上，不在字体度量。** 所以不要改 `TEXT_LINE_EM` /
`text_width_cm`（我们本来就比 R 大 1.34pt，改了只会更偏）；要改的是旋转标签那段
（`_label_stats()` 里 `ml + mr` / `mt + mb` 的取用，以及 R
`R/guide-axis.R` 的 `axis_label_element` → `axis.text.x` margin 口径）。

**待改规格：`axis-l` 的两项必须一起改（SIL-839 转 review 时的缺口清单）**

只补 margin 会超，只改 extent 会少——两项是耦合的：

| | 旋转 extent | margin | 合计 |
| --- | ---: | ---: | ---: |
| R | 11.69 | 11.80 | **23.49** |
| 我们 | 13.03 | 9.65 | **22.68** |

1. **旋转 extent** 换成 R 口径：`0.707 × (strwidth + strheight)`
   = `0.707 × (10.0455 + 6.4862)` = **11.69**。
   现状用的是 `text_line_cm()`（`TEXT_LINE_EM = 0.8945`，
   `facet.py` 注释说明它是「R 的 `stringHeight()` + descent」）与
   `text_width_cm()`（10.56，比 `grobWidth` 大 0.51）——
   旋转 bbox 应当用 **`grobWidth`/`grobHeight` 的值**，不是 line-em。
2. **margin** 按 R 的 **11.80** 取（现状 9.65）。

**验收看合计 `23.49`（+ `axis.ticks.length` 2.74 = 26.22），不要逐项去凑**——
单项能对上是因为两项互相抵消，SIL-839 前几轮的 0.8 / 1.13 都是这么绕出来的。

动手前需确认：`text_line_cm()` / `text_width_cm()` 只服务布局，还是也参与字形推进
（`axis.py:785/849/851`、`axis_guide.py:747/849`、`facet.py:1935` 都是布局侧的调用，
但 `Metrics.strwidth()` 若同时用于绘制，改口径会让已渲染文本跟着变）。

**列宽的真正入口是 `_label_box()`，不是 `_label_stats()`（SIL-839 更正）**

- 列宽 / 轴带尺寸全部由 `_label_box()`（`src/ggcore/axis_guide.py:719`）的
  `width·cos + line·sin` / `width·sin + line·cos` 决定；
- `_label_stats()`（同文件 `:839`）**只服务 `check.overlap` 与标签定位**，改它列宽纹丝不动
  （SIL-839 实测：改 `_label_stats()` 后 `coord_sf` 的 panel clip 左边界仍是 156.05，
  改 `_label_box()` 才变成 154.94）。

**R 侧两点实验的实测值（refs，`guide_axis(angle = 45)` + `theme_grey()`）—— 两条结论未定论**

```
axis.text.x size    : 8.8
axis.text.x margin  : 2.2points, 0points, 0points, 0points
gtable axis-b 行高  : 读到 0cm（p1 与 margin=0 的 p2 都是 0）
```

**这两条结论目前未定论，不要据此改代码**（SIL-839 复核）：

- 这张图是 **mtcars 代理图，不是 `coord_sf` 那条 case**；
- 一张有可见底部轴标签的图，`axis-b` 行高不该是 0cm——两版都读到 0，
  说明取的行索引/行名不对（`heights` 里固定行不止一个：`panel-spacing` /
  `axis-t` / `axis-b` 都在），必须用 `gt$layout$name == "axis-b"` 精确定位。

要定论，得用**这条 case 自己的 gtable**：把 `docs/cases/upstream-coord-sf-coord-sf-with-custom-guides/plot.py`
的代码在 refs 里原样跑出来，`ggplotGrob()` 后按 `layout$name` 取 `axis-l` 的列和
`axis-b` 的行，再用 `widthDetails()` / `heightDetails()` 出宽高。R 的 axis-l
26.22pt（0.8287cm + 0.0966cm）本来就是从这条 case 量到的，直接对它即可。

在那之前，「margin 11.80 / 合计 23.49」和「margin 只有 2.2pt / extent 不占行高」
**两套数字都不作数**。
