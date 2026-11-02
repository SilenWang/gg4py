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

`clip = "on"`（默认）/ `"off"`。本任务只**解析并记进**
`PanelParams.clip`；真正的裁剪发生在 geom 绘制期（M1-7）：`clip = "on"` 把
绘制裁到 panel 的 `clip_rect`，`"off"` 允许画到面板外。`coord_*` 只收这两个
值（不像 viewport 还有 `"inherit"`）。

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

## 6. 不支持清单（本任务明确不做）

| 能力 | 现状 | 计划 |
| --- | --- | --- |
| `coord_polar` / `coord_flip` / `coord_trans` / `coord_sf` | 未注册；`coord_from_component` 报「尚未实现」 | 后续 coord 任务 |
| facet free scales（每个 panel 一套范围） | 只有一张 panel | M1-6 |
| secondary axis（`sec_axis`） | 不支持 | M1-11 之后 |
| coord 级别的刻度 / guide 绘制 | 不做；只给范围 | M1-11 |
| 反向坐标（`reverse`） | 不支持 | 后续 |
| `clip = "off"` 的实际裁剪行为 | 只记录参数 | M1-7 的 geom 绘制 |
| 非矩形 clipPath / mask | 不支持 | 见 `docs/notes/viewport.md` |

`coord_cartesian` / `coord_fixed` 的参数集合是封闭的：不认识的参数直接报错
（与 R 的 unused argument 一致），不会静默吞掉。

## 7. 验收命令

```bash
pixi run check                       # 全量门禁（含 gate:imports / gate:determinism）
pixi run -e refs refs:coord          # 重新生成 R 夹具（产物入库，CI 不装 R）
pixi run cases:coord                 # PNG / SVG 等比例测量，产物在 .coord-aspect/
pixi run pytest tests/test_coord.py tests/test_coord_r_parity.py tests/test_coord_aspect.py -q
```
