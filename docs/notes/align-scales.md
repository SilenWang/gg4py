# 多图刻度对齐：`align_scales()`（M3-1 / SIL-1000）

`align_scales()` 把一组 `ggplot` 的位置标度改成同一套 limits（可选同一套 breaks），
让 patchwork 式组合里的同列 / 同行 panel 拥有相同的刻度。它是 **pre-IR 层**的入口：
只克隆 `ggplot` 对象、替换 `plot.scales`，不碰 `build_plot()` / IR / gtable。

代码：`src/ggcore/align.py`。测试：`tests/test_align_scales.py`（口径 / 负向）、
`tests/test_align_scales_r_parity.py`（与 aplot 0.3.2 逐值对拍）。
R 夹具：`tests/fixtures/align_scales_r_reference.json`，
生成命令 `pixi run -e refs refs:align`（`tools/refs/align_scales_ref.R`）。

```
ggplot 对象们 ──align_scales()──▶ 克隆 + 统一 limits ──▶ 组合层（plot_gtable / wrap_plots）
                    │                                        │
                    └── report：统一后的 limits / 裁剪计数 ───┘
```

## 1. API

```python
import gg4py

aligned = gg4py.align_scales(
    [p1, p2, p3],
    axis="xy",  # "x" / "y" / "xy"
    limits="union",  # "union" / "first" / "explicit"
    x=None,
    y=None,  # limits="explicit" 时的范围
    oob=None,  # None（各标度默认） / "censor" / "squish"
    breaks=None,  # None（不动） / "first" / 显式数据空间序列
    expand="keep",  # "keep" / "first"
    adjust_coord=True,  # 主图 coord_fixed 时给子图补 coord_fixed
    coord_size=1.0,  # 补 ratio 时的缩放因子（对应 aplot 的 size）
)

p1_aligned, p2_aligned, p3_aligned = aligned
aligned.report.limits["x"].limits  # (0.0, 10.0) 之类（数据空间）
aligned.report.clipped  # 每图每轴的裁剪明细（ClipCount）
aligned.report.clipped_plots  # 每图一条的跨轴行并集（PlotClip）
aligned.report.clipped_rows  # 所有图的新增裁剪行数（跨轴并集，不重复计同一行）
```

返回值 `AlignedPlots` 是 `Sequence[ggplot]`：可以遍历 / 下标 / 解包，报告挂在
`.report` 上。原图**不会被修改**（`ggplot.clone()` 之后替换标度）。

### `axis` 指数据轴

`axis="x"` 调的是 `aes(x=…)` 那条标度（`scale_x_*`），**不是**视觉横轴。
`coord_flip()` 只交换视觉轴：flip 图上 `axis="x"` 仍然改数据 x（它显示在视觉 y
上），与 aplot 的 `xlim2()`（视觉轴）方向相反。组合层若按「版面左/右」对齐，
需要自己按 flip 换算成数据轴。

`adjust_coord` 的比例计算是**唯一**按视觉轴取值的地方（flip 时交换 x / y 范围），
这正是 issue 里「内部按 flip 映射到视觉轴」的那一层。

## 2. 三种 limits 模式

| 模式 | 连续 | 离散 | 裁剪 |
| --- | --- | --- | --- |
| `"union"`（默认） | 各图范围的并集（**变换后空间里**取） | levels 并集，顺序 = 第一张图优先、后续追加 | 不引入新的裁剪 |
| `"first"` | 第一张**有该轴数据**的图的 limits | 第一张图的 levels | 其余图可能被裁；计数进 `report` |
| `"explicit"` | `x=` / `y=` 的 2 元数值 | `x=` / `y=` 的水平序列 | 同上 |

- **变换后空间**：`scale_x_log10()` 的并集是 `log10(值)` 的并集，再反变换回数据
  空间写进 `limits=`（`0..2` → `1..100`）。`reverse` / `sqrt` / 日期同一条路径。
- **日期 / 时间**：`Date` = 自 epoch 起的天、`POSIXct` = UTC 秒（与 `ggio` 的列口径
  一致）。`x=` / `y=` 可以给 `datetime.date` / `datetime.datetime`（带时区先转
  UTC），`report.limits[axis].native` 还原成 `date` / `datetime`。
- **离散**：统一的是 `levels`，不是数值 limits。数据里的 NA 是「最后一个水平」，
  统一后仍排在末尾；未知水平在映射阶段就是 NaN，不算对齐引入的裁剪。
- 显式 `limits` 已经裁过的数据**不会**被 `"union"` 恢复：`union` 只是不引入新的
  裁剪（数据在第一次 `build_plot()` 时就被 censor 掉了）。R 也一样。

`limits` 也可以直接传序列（`limits=(-1, 6)` / `limits=("c", "a", "b")`），等价于
单轴 `explicit`；`axis="xy"` 时必须写 `limits="explicit"` + `x=` / `y=`。

## 3. 裁剪不静默

`limits="first"` / `"explicit"` 会按 `oob` 丢数据。报告分**两份口径**：

`report.clipped`（`ClipCount`，每图每轴的明细）：

| 字段 | 含义 |
| --- | --- |
| `plot` | 图序号（0 起） |
| `axis` | `"x"` / `"y"` |
| `rows` | **这条轴**自己的越界行数 |
| `values` | 与 `rows` 相同（保留的别名） |
| `levels` | 离散轴上被去掉的水平 |

`report.clipped_plots`（`PlotClip`，每图一条）= R 的 "Removed N rows" 口径：
**跨轴行级并集**（x 或 y 任一越界即一行，同一行只算一次）。
`report.clipped_rows` / `report.rows_dropped(plot)` 读这一份，所以双轴同时裁剪时
不会把同一行数两次：

```python
# child 的 x = [1,2,4,5]、y = [1,5,4,2]，统一到 1..3：
aligned.report.clipped  # x 轴 rows=2、y 轴 rows=2（明细）
aligned.report.clipped_rows  # 3（第 2/3/4 行，跨轴并集）
```

**不要**把 `report.clipped` 的 `rows` 直接相加——`axis="xy"` 时同一行会在两条轴
上各出现一次。

判定位置是**映射后、stat 前**的表（`LayerBuild.aesthetics`）：连续轴已是标度空间、
离散轴是旧水平号，`_outside_by_layer()` 负责翻回数据空间比较。不在重建后的
`rows_dropped` 里取差值：`stat_count()` / `stat_bin()` 会在统计阶段就把越界行删掉，
留在 `rows_dropped` 里的恒为 0，看起来像「没丢数据」。

`oob` 默认 `None` = 沿用各标度自己的默认（连续 `censor`、分箱位置 `squish`），
与 issue 要求的「默认 censor」在连续位置上等价；显式 `oob="censor"` /
`"squish"` 才覆盖所有图。`oob="squish"` 不删行，`report.clipped` 与
`report.clipped_plots` 都为空。

## 4. breaks / expand

- `breaks=None`（默认）：不动各图的断点。limits 一致后，**默认断点**自然一致
  （`extended_breaks()` 只看范围与变换）。某张图显式写了 `breaks=` 时它仍是自己的
  那套，与 aplot 的 `set_scale_limits()`（只改 limits）相同。
- `breaks="first"`：把第一张图算出来的断点（数据空间）写到所有图上；显式序列则
  直接写。离散轴的断点就是 levels，不需要单独统一。
- `expand="keep"`（默认，与 aplot 相同）保留各图自己的 `expand`。**这条默认值
  不保证 tick 的页面坐标相同**：只要有一张图显式设过 `expand`（例如
  `scale_x_continuous(expand = (0, 0))`），统一 limits 后它的面板范围仍与其他图
  不同，tick 的 npc 位置就会差一截（PR 的
  `test_expand_first_makes_the_panel_ranges_identical` 直接钉住这个差别：
  `(1.0, 2.0)` vs `(0.95, 2.05)`）。

  所以组合层（SIL-1001 的 `wrap_plots()` / `plot_gtable()`）**必须**传
  `expand="first"`，或由调用方保证所有图 `expand` 一致；只比「tick 值集合」时
  `"keep"` 够用。`expand="first"` 把第一张图的 `expand` 抄给所有图。

## 5. `coord_fixed` 适配（`adjust_coord`）

对应 aplot `R/utilities.R` 的 `adjust_coord()`：

- 主图（第一张）是 `coord_fixed()` / `coord_equal()` 时，给其它**没有** `coord_fixed()`
  的图补一个；
- `ratio = 视觉 x 范围 / 视觉 y 范围 / coord_size`（aplot `.cal_ratio()` 的公式；
  aplot 的 `size` 是 layout 的行 / 列号，这里用 `coord_size=` 显式给，布局层可传）；
- 视觉范围按 flip 交换（见 §1）；离散范围 = 水平数；
- 已有 `coord_fixed()` 的图不动；主图不是 fixed 时整体不动；
- 补 `coord_fixed` 会替换原坐标系（`clip` / `expand` 回到默认），与 aplot 的
  `x[[i]] + coord_fixed(ratio = …)` 相同。

## 6. 与 aplot 0.3.2 的对拍

`pixi run -e refs refs:align` 用 aplot 0.3.2 + patchwork 1.3.2 + ggplot2 4.0.3 跑
同一组图，夹具的数字如下（`tests/test_align_scales_r_parity.py` 逐项断言）：

| case | aplot 调用 | 统一后的 limits（标度空间） | 裁剪行数 | gg4py 写法 |
| --- | --- | --- | --- | --- |
| `continuous_first` | `child + xlim2(main)` | `1..3` | 2 | `align_scales(..., axis="x", limits="first")` |
| `continuous_explicit` | `child + xlim2(main, limits=c(-1,6))` | `-1..6` | 0 | `limits="explicit", x=(-1, 6)` |
| `discrete_first` | `child_bar + xlim2(main_bar)` | `a, b` | 1 | `align_scales(..., axis="x", limits="first")` |
| `log10_first` | `child + xlim2(main)` | `0..1`（log10 空间） | 2 | 同上 |
| `reverse_first` | `child + xlim2(main)` | `-2..-1`（reverse 空间） | 2 | 同上 |
| `date_first` | `child + xlim2(main)` | `18262..18414`（天） | 1 | 同上 |
| `flip_first` | `child + xlim2(main)` | 视觉 x = 数据 y `10..20` | 2 | `axis="y"`（数据轴） |
| `dual_axis_first` | `child + xlim2(main) + ylim2(main)` | x `1..3` / y `1..3` | 3（x 2 + y 2 的行并集） | `axis="xy", limits="first"` |
| `adjust_coord_ratio` | `aplot:::adjust_coord(...)` | — | — | `coord_fixed(ratio=2)` |

逐项对拍的口径：

- aplot 的 `xlim2(gg)` 取 `ggfun::xrange(region = "plot")` =
  `panel_params[[1]]$x$limits`，是**标度空间**的值；gg4py 比
  `report.limits[axis].transformed`（同一空间），离散轴比 levels；
- aplot 侧**不打印** "Removed N rows"（`ggplot_build()` 只 censor 不断行），所以
  fixture 数 `data[[1]]` 里新增的 NA；单轴 case 比 `ClipCount.rows`，双轴 case
  比 `clipped_rows` / `rows_dropped()`（跨轴行并集）；
- 面板范围（`panel_range`）也逐值比：log10 / reverse 的 `x.range` 在映射空间，
  gg4py 的 reverse range 保持递减顺序（消费方按 `sorted()` 处理），测试排序后比。

两处**内部写法**与 aplot 不同、结果相同：

1. aplot 把标度空间的 limits 直接写回 `scale$limits`；gg4py 先反变换回数据空间
   （`1..10`）再写回，标度会再变换一次。两条路径的面板 / breaks / 裁剪一致。
2. aplot 的 `set_scale_limits()` 在离散轴上还写 `continuous_limits` 并把 `expand`
   改成 `c(0, 0)`；gg4py 统一 levels 后由 `range_c` 自然重算。本夹具的离散 case
   面板范围相同；child 自己带特殊 `expand` 时，用 `expand="first"` 显式统一。

## 7. 前置条件与非范围

- **坐标系**：首期只处理 `coord_cartesian` / `coord_fixed` / `coord_equal` /
  `coord_flip`。极坐标 / 径向 / `coord_sf` / `coord_map` 不在范围（量纲不是两条
  笛卡尔轴）。
- **分面**：支持单 panel 与 `scales="fixed"`。`scales="free"` 的图直接报
  `AlignError`（各面板范围不同，一套 limits 没有意义）。
- **跨图变换必须一致**：一张 `scale_x_log10()` + 一张线性 → `AlignError`（点名
  每张图的 trans）。离散 vs 连续同样报错。
- **图自己的 `coord xlim/ylim` 优先**：`coord_cartesian(xlim=…)` 会盖过 scale
  limits，所以这张图的这条轴不会被真正对齐。`align_scales()` 在 `report.warnings`
  里点名，并 `warnings.warn()`，不静默。
- **不含**：跨图共享同一个 scale 对象、free-scale 跨图、双轴、极坐标 / 固定纵横比
  的刻度对齐（`coord_fixed` 只做 §5 的适配）。

## 8. 验证

```bash
pixi run test -- tests/test_align_scales.py tests/test_align_scales_r_parity.py
pixi run -e refs refs:align     # 重新生成 R 夹具（需要 refs 环境里的 aplot 0.3.2）
```

`tests/test_align_scales.py::test_aligned_panels_share_ticks_and_page_coordinates`
把「tick 在 SVG 里的坐标相同」落成可断言的数字：`axis_ticks()` 的 npc 位置相同、
`plot_layout()` 的 panel 矩形相同，于是 `panel 原点 + npc × 面板尺寸`（页面 cm
坐标）逐值相等。IR / SVG 的用户单位都是 pt，cm → pt 是全局缩放，不影响相等性。
