# 标度口径（M1-4 / M2-4 A）

`ggcore.scales` 把 ggplot2 4.0.3 的标度实现搬过来。M1-4 的 15 个名字（位置连续 /
离散 / log10、`colour` / `fill` 的渐变与 hue、`size`、`shape`、`alpha`）是打底；
M2-4 A（SIL-731）按族补齐到 **75 个注册名**，覆盖 v4.0.3 NAMESPACE 里连续侧的
70 个 `scale_*` 导出：

| 族 | 导出 | 实现 |
| --- | --- | --- |
| 位置连续 | `x/y_continuous`、`_log10`、`_sqrt`、`_reverse` | `PositionContinuousScale` + `trans` |
| 位置分箱 | `x/y_binned` | `BinnedPositionScale`（stat 前箱号 / stat 后箱中心） |
| 位置日期时间 | `x/y_date`、`_datetime`、`_time` | `PositionContinuousScale` + `trans = date/time/hms` |
| 连续渐变 | `{colour,color,fill}_continuous`、`_gradient`、`_date`、`_datetime` | `GradientScale` |
| 发散 / n 色渐变 | `_gradient2`、`_gradientn` | `Gradient2Scale` / `GradientNScale` |
| 分箱颜色 | `_binned`、`_steps`、`_steps2`、`_stepsn` | `BinnedGradient*Scale` |
| Brewer 连续侧 | `_distiller`、`_fermenter` | `DistillerScale` / `FermenterScale` |
| 其它美学 | `alpha` / `alpha_binned` / `alpha_date` / `alpha_datetime`；`size` / `_area` / `_binned` / `_binned_area` / `_date` / `_datetime`、`radius`；`linewidth` / `_continuous` / `_binned` / `_date` / `_datetime` | `AlphaScale` / `SizeScale` / `RadiusScale` / `LinewidthScale`（+ 分箱版） |

名字 → 美学 / 实现族 / 默认值的唯一来源是 `src/ggcore/scale_specs.py`：注册表
（`registry.SCALE_SPECS`）与 `scale_from_component()` 都读这张表，新增一个导出
只需要加一行，不另写一个构造函数。`scale_color_*` 与 `scale_colour_*` 是同一实现
的别名（上游 NAMESPACE 两个都导出）。

参数覆盖 `limits` / `breaks` / `labels` / `minor_breaks` / `n.breaks` / `trans` /
`expand` / `na.value` / `oob` / `palette` / `values` / `date_breaks` /
`date_labels` / `date_minor_breaks` / `right` / `nice.breaks` / `show.limits`，
训练后的范围、断点、标签、色值与 R 逐项对拍。

代码：`src/ggcore/scales.py`（实现）、`src/ggcore/scale_specs.py`（导出表）、
`src/ggcore/palettes.py`（Brewer 表）、`src/ggcore/scales_date.py`（日期时间
`pretty` / `breaks_width` / 格式化）。测试：`tests/test_scales.py`（口径 / 负向）、
`tests/test_scales_families.py`（族级 + 每个导出进 build）、
`tests/test_scales_r_parity.py`（R 对拍）。

```
compute_aesthetics → transform_scales → train → map_position → … → map_scales → finish
                     （上游 scales$transform_df）
```

## 1. 数据流：变换 → 训练 → 映射

上游 `ggplot_build()` 的顺序是：

```r
data <- lapply(data, scales$transform_df)      # 位置数据先做变换
layout$train_position(data, x_scale, y_scale)  # 在**变换后**的空间训练
data <- layout$map_position(data)              # map 只做 oob censor / 调色板，不再变换
...
layout$reset_scales(); layout$train_position(...); layout$map_position(...)
npscales$set_palettes(theme); npscales$train_df(data); data <- npscales$map_df(data)
```

`ggcore.build` 逐条对应：

- `transform_scales(scales, aesthetics)`（M1-4 新增）= `scales$transform_df()`；
- `ScaleBase.transform_limits(limits)` = 上游
  `transformation$transform(coord_limits)`：只给 coord 的 `xlim` / `ylim` 用
  （连续标度变换到标度空间，离散原样返回；见 `docs/notes/coord.md` §1）；
- 第一段 `train`：aesthetics 之后；
- `map_position()` 只映射**位置美学**（上游 `layout$map_position()` 也只碰 x / y）；
- 第二段 `train`：`compute_position()` 之后，用 **positioned** 数据（含
  `xmin` / `xmax` / `ymin` / `ymax`）。这一点是必须的：柱子的锚点是
  `x ± width/2`，不把它们收进范围，stage 5 的 `oob` 会把锚点 censor 成 NA；
- `map_scales()`（阶段 5）映射**全部**美学：位置 = censor（幂等），
  colour / fill / size / shape / alpha = 调色板 / rescale。

> `ScaleSet.map` 会被 `map_position()` 与阶段 5 各调一次，所以**自定义的
> `ScaleSet.map` 必须幂等**（常量映射、censor 都是幂等的；累加 / 有状态的
> 映射不行）。`tests/test_build.py::test_pipeline_calls_the_scale_set_instead_of_hardcoding`
> 里注明了这一点。

因此 `scale_x_log10()` 下 `LayerBuild.data$x` 是 log10 空间的值：x = 1 / 10 / 100
→ 0 / 1 / 2；不写 `scale_x_log10()` 时同一张图仍是 1 / 10 / 100（反向对照在
`tests/test_scales.py::test_reverse_check_log10_versus_plain`）。

## 2. 默认标度解析

`build_plot()` 用 `ScaleSet(plot.scales)`：显式 `p + scale_*(...)` 优先，其余按
**第一个训练到的列**的类型解析默认标度（上游 `plot@scales$add_missing()`）：

| 美学 | 列是离散（`str` / `categorical` / `bool`） | 列是数值 |
| --- | --- | --- |
| `x` / `y` | `scale_x_discrete()`（水平 → 1..n） | `scale_x_continuous()` |
| `colour` / `fill` | `scale_colour_hue()`（`hue_pal`） | `scale_colour_gradient()`（Lab） |
| `size` / `alpha` | —（恒为连续） | 连续 |
| `shape` | 离散（16/17/15/3/7/8） | 离散 |
| 其它（`group` / `PANEL` / `weight` / `width` …） | 不建标度，原样通过 | 同左 |

`xmin` / `xmax` / `xend` **共用 x 标度**，`ymin` / `ymax` / `yend` 共用 y 标度
（上游 `ggplot_global$x_aes` / `$y_aes`）。数值列进离散位置标度时**原样通过**
（上游 `ScaleDiscrete$map()` 只处理离散值），所以柱子的 `xmin = x - width/2`
不会被离散水平编码吃掉。

注册表现在是 75 个名字（M1-4 的 15 个 + M2-4 A 的 64 个新增，其中 5 个离散名
留给 M2-4 B）。`*_continuous` / `*_discrete` 在 4.0.3 里就是 gradient / hue 的
别名；`scale_colour_gradient()` / `scale_fill_gradient()` 在 SIL-723 注册成同义名
（`colour_gradient` / `fill_gradient` → `GradientScale`，`+` 与方法链两条入口）
（`tools/refs/scales_ref.R` 末尾有自检）。`scale_colour_gradientn()` /
`scale_colour_stepsn()` 与上游一样**必须**给 `colours`。

## 3. limits / expand

两个不同的东西，别混：

- `Scale.limits()` = 上游 `scale$get_limits()`：**训练后的数据范围**（或显式
  `limits`），**没有** expand；两边都是**变换后**的空间，见下一条；
- 显式 `limits` 是**数据空间**的值（`scale_x_log10(limits = c(1, 100))` 里的
  1 / 100 是原始数据），`limits()` 里先过 `trans` 再返回——R 4.0.3 的
  `get_limits()` 存的也是变换后的值（上例 → `(0, 2)`），`expanded_limits()` /
  `breaks()` / `map()` 都在这个空间里消费。单侧 `None` 取训练范围（已经是变换
  后的值，不能再变换一次）；log10 下给 0 / 负值时按模块统一约定落成 NA；
- `Scale.expanded_limits()` = 上游 `scale$dimension(expand = …)`：面板范围，
  只对**位置**标度有意义（非位置标度返回 `None`）；
- 模块级 `expand_range(low, high, mult=0.05, add=0)` 是**唯一**的 expand 实现
  （M1-5 的 coord 只消费它），离散标度调用时传 `mult = 0, add = 0.6`。

默认 expand（上游 `default_expansion()`）：

| 标度 | 默认 | 面板范围 |
| --- | --- | --- |
| 连续位置 | `expansion(mult = 0.05)` | `limits ± 0.05 × 宽度` |
| 离散位置 | `expansion(add = 0.6)` | `0.4 .. n + 0.6` |

> 离散面板范围是 **0.4 .. n + 0.6**，不是 0.5 .. n + 0.5（那是 ggplot2 2.x 的
> `add = 0.5`）。issue 里的括号备注顺手写错了，以 R 实测为准：
> `tools/refs/scales_ref.R` 的 `discrete_levels` case 记录 `expanded_limits =
> [0.4, 3.6]`。

`expand = c(0, 0)` 关掉扩边；`expand = 0.1` 按上游 `rep_len(expand, 4)` 解释成
四个分量都是 0.1（不是「只改 mult」）；2 元 = `(mult, add)` 两端相同；4 元 =
`(mult_low, add_low, mult_high, add_high)`。宽度为零（只有一种取值）时按上游
`zero_width = 1` 处理。

## 4. 断点与标签

- 连续默认断点 = `labeling::extended(dmin, dmax, n = 5)`（`extended_breaks()` 的
  完整移植：simplicity / coverage / density / legibility 加权打分）。
  `extended_breaks()` 的实现与 R 在 19 组范围上逐项相等
  （`tests/test_scales.py::test_extended_breaks_match_r`）。
- `n.breaks = 3` → 用 `n = 3` 调 breaks 函数（Python 关键字可写 `n_breaks` 或
  `n.breaks`）。
- `breaks = c(2, 4, 6)` 手动断点优先；`trans = "log10"` 时用
  `breaks_log()`（整十次幂，不够时走 `log_sub_breaks`）。
- **次断点**（`panel.grid.minor` 的位置）由 `ScaleBase.minor_breaks()` 给：
  连续标度 = **未 censor 的主断点序列**（`extended_breaks` 的全序列，含越界端点）
  的相邻中点，取完再按面板范围过滤；limits 超出主断点两端时先照 R 的
  `regular_minor_breaks()` 各补一个 `bd` 宽的端点，次网格才能贴到面板边界。
  log10 的中点也在对数空间；离散标度没有次网格（返回空）。SIL-723 / SIL-725。
  修前先按 `breaks()` 过滤再求中点，最外两个半区间整个丢掉：x `[2, 30]` 只剩
  15/25（R 是 5/15/25，35 在面板外不画），y `[2.34, 5.50]` 只剩 3.5/4.5
  （R 是 2.5/3.5/4.5/5.5）。
- 断点在**变换后**的空间里；`labels()` 反向变换回数据空间再格式化。
- **越界断点记 `None`**（R 的 `NA`）：面板范围 expand 之后，`get_breaks()` 里
  落在外面的项会被 censor——`scale_x_log10()` 的默认断点是
  `(None, 0, 1, 2, None)`，标签 `(None, "1", "10", "100", None)`。
- 默认标签仿 R 的 `format(x, trim = TRUE, justify = "left")`：整组取同一套小数位
  （`c(0, 0.25, 0.5)` → `"0.00" "0.25" "0.50"`），定宽与科学记号比宽度
  （`1e5` → `"1e+05"`，`123456` 仍是定宽）。
- `labels=` 支持三种写法：等长序列（按位置）、映射（断点值 / 水平 → 标签）、
  含 `%` 的格式串（`"%.1f"`）。`breaks = NULL` / `labels = NULL` 是显式「不要」，
  与不写参数（默认）不同，`_has_param()` 区分这两者。
- `minor_breaks = NULL` 关掉次网格；给定序列 / 函数时走上游
  `get_breaks_minor()` 的优先级（`date_minor_breaks` 优先于 `minor_breaks`）。

## 5. 离散标度

- 水平顺序：普通字符列**升序**；`categorical`（factor）按 `Column.levels`；
  逻辑值 `False` 在前；跨层合并时以第一个 categorical 列的 levels 为基底，
  其余水平升序追加（上游 `DiscreteRange$train`）。
- **NA 是一个水平**（排在最后）：`limits()` 返回 `("a", "b", None)`，映射成
  `n + 1`。`geom_bar(aes(x = c("a", NA)))` 的 NA 因此是一根独立的柱。
- `drop = FALSE`：保留 factor 里没出现的水平（`test_discrete_drop_false`）。
- 显式 `limits` 完全接管：`scale_x_discrete(limits = c("b", "a", "z"))` 的编码是
  `2, 1, NA`（不在 limits 里的值 → NA；`z` 即使没出现过也占位置）。
- colour / fill 的离散标度里 NA **不是**水平：走 `na.value`（默认 `"grey50"`）。

## 6. 色板

| 标度 | 实现 | 取值 |
| --- | --- | --- |
| 离散 colour / fill | `hue_pal(h = c(15, 375), c = 100, l = 65)` | HCL → sRGB，D65 白点 |
| 连续 colour / fill | `colour_ramp([low, high])` | Lab 空间逐段线性插值，默认 `#132B43` → `#56B1F7` |
| 发散渐变 | `colour_ramp([low, mid, high])` | 停靠点 0 / 0.5 / 1；默认 `muted("red")` `#832424` / `white` / `muted("blue")` `#3A3A98` |
| n 色渐变 | `gradient_n_pal(colours, values)` | `values` 给颜色停靠的数据位置（`approxfun` 口径，范围外 NA） |
| 分箱颜色 | `BinnedGradient*Scale` | 每个箱取**箱中心**在 0..1 上的颜色（`palette(midpoints)`） |
| Brewer 连续侧 | `brewer_gradient` / `brewer_binned` | `RColorBrewer::brewer.pal(n, name)` 全表（n = 3..maxcolors），默认 `direction = -1` |
| 连续 size | area 标度 | `1 + 5 × sqrt(rescale(x))`，默认范围 1..6 |
| `scale_size_area` | `abs_area(max_size)` + `rescale_max` | `sqrt(x / max(x)) × max_size` |
| `scale_radius` | 线性 | `range`（默认 1..6） |
| 连续 / 分箱 alpha | 线性 | 0..1 → 0.1..1 |
| 连续 / 分箱 linewidth | 线性 | 0..1 → 1..6（上游 fallback 口径） |
| 离散 shape | `pal_shape()` | 16, 17, 15, 3, 7, 8（超过 6 个水平记 NA 并发 warning） |

hue 的十六进制值与 R 4.0.3 **逐字节相同**：n = 2 → `#F8766D #00BFC4`，n = 3 →
`#F8766D #00BA38 #619CFF`，n = 6 → `#F8766D #B79F00 #00BA38 #00BFC4 #619CFF
#F564E3`（`tests/test_scales.py` 逐字节钉住，R 侧在夹具的 `palettes.hue`）。

gradient 在 0 / 0.25 / 0.5 / 0.75 / 1 上同样逐字节相等（`#132B43` `#22496C`
`#336A98` `#448DC6` `#56B1F7`）；容差不需要放宽——Lab 插值与 R 的
`scales::colour_ramp()` 同一条路径（同一套 D65 / 矩阵 / 伽马）。

Brewer 表在 `src/ggcore/palettes.py`：RColorBrewer 1.1.3 的
`brewer.pal(n, name)` 全量逐色入库（seq 18 个、div 9 个、qual 8 个色板），
`brewer_pal(type, palette, direction)` 复刻上游 `pal_name()` / `pal_brewer()`
的口径：名字跨类型查、`direction = -1` 反转、`n` 超过 `maxcolors` 的多余位置是
NA（`None`）。`scale_*_distiller()` 用 7 色表做连续渐变，
`scale_*_fermenter()` 用 `pal_binned(pal_brewer(...))` 按箱数取色。
完整色板数据只此一份，M2-4 B 的 `scale_colour_brewer()` 直接复用。

颜色名：内部先把 R 颜色名解析成 `#RRGGBB`。M2-4 A 只收标度默认值 /
`gradient2` 端点用到的常见名字（`white` / `black` / `red` / `blue` / `grey` /
`greyNN` 等，见 `scales._NAMED_COLOURS`）；完整的 657 个名字表留给 M2-4 B 的
`scale_*_manual()`。

`values=`（manual）与 R 的 `scale_*_manual()` 同一套口径：序列按水平顺序取色，
长度不够时**报错**，不循环补齐（上游 4.0.3 的 manual scale 同样 abort）；**映射
（dict）按水平名取色**（`values = {"a": "red", "b": "blue"}`），名字对不上的水平
用 `na.value`，与数据水平完全没交集时发一条 `UserWarning`（上游同样警告）。
`palette=` 可以给可调用对象（收 n，返回 n 个颜色）或序列（按水平顺序取）。

## 7. NA / 越界（`oob`）

- `oob = censor`（连续默认）：超出 `limits` 的**有限值** → NA，然后 `na.value`
  填空（位置标度是 `NA_real_`，colour 是 `"grey50"`，size / alpha 是 NA）。
- `oob = squish`（**分箱默认**）：越界值钳到 `limits` 端点，不产生 NA；
- `oob = squish_infinite`：只钳 ±Inf，有限越界值原样保留；
- `oob = keep`：不做任何处理；
- `oob` 也可以给可调用对象（`oob(values, limits)` 或只收 `values`）。

离散位置：没有 `na.value` 概念，未知值 / 不在 limits 里的值 → NA（`mapped_discrete(NA)`）。

**log10 / sqrt 的 0 与负值**：`ggcore` 一律记 NA（`Column.na_mask`），并累加到
`Scale.non_finite_count`。上游 log10 这里有个 wart：`censor()` 只 censor 有限值，
所以 `log10(0) = -Inf` 会原样留在 `$data$x` 里（R 的 `ggplot_build()` 实测是
`-Inf`）。本任务按 issue 要求把它统一成 NA；夹具里那个位置记成字符串
`"-Inf"`，`tests/test_scales_r_parity.py` 明确断言「R 是 Inf，我们是 NA」。

## 8. 分箱标度（`ScaleBinned`）

`scale_*_binned` / `_steps*` / `_fermenter` / `size_binned*` / `alpha_binned` /
`linewidth_binned` 共用 `BinnedScale`：

1. 训练范围（变换后空间）与连续标度一致；`limits()` 默认是数据范围。
2. `_get_breaks(limits)` 逐条照 `ScaleBinned$get_breaks()`：
   - limits 反变换回数据空间排序；`nice.breaks = TRUE`（默认）时走变换自己的
     断点函数（identity → `extended_breaks`，date → `pretty.Date`），否则按
     `n.breaks` 等距切；
   - 断点先 discard 到 limits 内；用户**没给 limits**时，把两端补齐到等宽箱，
     必要时改写 `self.limits`（`scale_x_binned()` 的 n.breaks = 10 因此会得到
     11 个箱边界，最外两箱与内部等宽）；
   - 结果缓存——`breaks()` / `map()` / `bins()` 看到同一份断点。
3. `map()`：`oob`（默认 squish）→ 重标到 0..1 → 按 `right`（默认 `TRUE`，
   区间 `(b[i], b[i+1]]`，最低值并入第一箱）切箱 → 箱中心在 0..1 上的调色板值。
4. `bins()` 给出 issue 要求的三件套：
   - `edges`：分箱边界（变换后空间，含最外两个 limits，长度 = 箱数 + 1）；
   - `values`：每箱颜色（colour 族）或数值（size / alpha / linewidth）；
   - `breaks`：图例断点（与 `breaks()` 一致，已按面板范围 censor）。
5. 位置分箱（`scale_x_binned`）与上游一样分两段：第一次 `map()` 返回 **1 起的
   箱号**（stat 因此把它当离散位置），`ScaleSet.reset()` 之后（`build_plot` 在
   stat / position 之后、第二段训练之前调用，对应上游 `layout$reset_scales()`）
   把箱号换回**箱中心**。第一段与 R 逐值相同，第二段只影响最终绘制位置。

## 9. 日期时间

`ggio` 已把 `datetime.date` / `datetime64` / pandas / Arrow 的日期时间归一成
「自 1970-01-01 起的天 / 秒」（`docs/notes/data.md`），所以日期时间标度就是
`trans = "date"`（天）/ `"time"`（秒）/ `"hms"`（一天内的秒）的连续标度：

- **默认断点**：`scales::breaks_pretty()` → base R 的 `pretty.Date()` /
  `pretty.POSIXt()`。这里逐行移植了日历步长阶梯（sec / min / hour / day / week /
  halfmonth / month / quarter / halfyear / year / decade …），断点值与 R 浮点
  相等，标签格式也用同一套（如半年步长 → `%Y-%m`，日步长 → `%b %d`）。
  R 把标签挂在断点上，`format()` 走 names 分支，所以**被 censor 的端点也带标签**
  （夹具 `x_date_default` 就是原样）；`ggcore` 在默认断点路径复现了这一点。
- **`date_breaks` / `date_minor_breaks`**：字符串按
  `scales::breaks_width()` → `fullseq()` 解析（`"2 months"` / `"1 week"` /
  `"15 min"` / `"1 year"`…）。日 / 周用数值栅格，月 / 年 / 季度按 `cut.Date()` /
  `cut.POSIXt()` 的日历对齐（周一为一周之始），`hms` 按秒做数值对齐。
- **`date_labels`**：`strftime()` 格式串（`"%Y-%m"` / `"%b"` / `"%H:%M:%S"`）。
  不给 `date_labels` 时用 `format()` 的默认口径：Date → `%Y-%m-%d`，POSIXct →
  非零时刻时带 `%H:%M:%S`，hms → `%H:%M:%S`。
- `limits` / `expand` / `oob` / `breaks` / `labels` 与连续标度同一套实现，没有
  第二份日期分支。

`scale_*_date` / `_datetime` / `_time` 作用在非位置美学（`colour_date` /
`size_date` / `alpha_datetime` …）时是同一个 `datetime_scale` 的实现，只是
palette 换成对应的连续调色板（渐变 / area / 线性）。

## 10. 与 R 对拍

夹具：`tests/fixtures/scales_r_reference.json`，由
`pixi run -e refs refs:scales`（`tools/refs/scales_ref.R`）生成；产物入库，CI 不装 R。

每个 case 记录：`scale`（注册名）、`params`、`train`、`map`、`limits`、
`expand`（4 元）、`expanded_limits`、`breaks`、`labels`、`mapped`。
R 侧取的是 `scale$get_limits()` / `default_expansion()` / `scale$dimension()` /
`view_scale_primary()$breaks` / `$get_labels()` / `scale$map()`——与
`ggplot_build()` 里 `layout$setup_panel_params()` 转出来的那一份同源。位置标度的
断点按 **expand 之后**的范围算（`view_scales_from_scale()` 的口径），其余按
`limits` 算（guide 的口径）。日期值在夹具里是「天 / 秒」数值（`vector_json`
对 Date / POSIXct / hms / difftime 先 `as.numeric()`）。

53 个 case（218 个断点 / 标签、199 个映射值、24 个 expand 向量）：

- 连续位置：默认 expand / `expand = c(0, 0)` / 显式 limits / 手动 breaks +
  labels / `n.breaks` / log10（x 与 y，外加「log10 + 显式 limits」）/ sqrt /
  reverse / 分箱（默认与显式 breaks）；
- 日期时间：Date 默认 pretty 断点 / `date_breaks = "2 months"` /
  datetime `"2 hours"` / hms `"15 min"`；colour / size / linewidth 的 date 变体；
- 颜色：hue（含 na.value 与 limits）/ manual values / gradient（含 limits）/
  gradient2 / gradientn / steps（含 limits 的 squish）/ steps2 / stepsn /
  binned / distiller / fermenter；
- 其它美学：size（连续 / area / binned / binned_area）/ alpha（连续 / 分箱）
  / linewidth（连续 / 分箱）/ radius / shape；
- `oob` 三态：squish / keep / squish_infinite。

规模钉死在 `tests/test_scales_r_parity.py::test_compared_cell_count`。

对拍口径：数值 `abs <= 1e-12`，十六进制逐字节，`null` = NA，`"Inf"` / `"-Inf"` =
R 的 ±Inf（见 §7）。

## 11. 不支持清单

| 项 | 状态 |
| --- | --- |
| 离散 colour / fill（`_discrete` / `_ordinal` / `_manual` / `_identity`）、brewer / viridis / grey / hue 的离散导出 | M2-4 B（SIL-730） |
| `scale_linetype_*` / `scale_shape_*` 的长尾 / `scale_type` | M2-4 B |
| `trans = "log2" / "log" / "exp" / "log1p" / "pseudo_log" / "reciprocal" / "logit" / "probit" / "asn" / "atanh"` | 未实现；构造时报错并点名后续任务 |
| `space != "Lab"` 的渐变插值 | 上游 4.0.3 已废弃；这里报 `ScaleError` |
| secondary axis（`sec.axis`） | M2-1 已实现（`sec_axis()` / `dup_axis()`，见 `docs/notes/coord.md` §12）；标度侧只存引用，断点 / 标签在 `ggcore.axis` |
| 位置标度以外的 expand / 面板范围 | 不做（只有 x / y 有 `expanded_limits()`） |
| guide / 图例排版（`colourbar` / `coloursteps` / `bins`） | M2-2（guides 任务）；`guide="bins"` 仍按既有文案报错 |
| coord 变换对 limits 的接管（`coord_cartesian(xlim=)`） | M1-5 已实现；`coord_trans` 的逐轴变换见 M2-1（`docs/notes/coord.md` §8） |
| `scale_linetype_*` / `scale_size_manual` 等未登记的名字 | 不在 `registry.SCALE_SPECS` 里，不加第二套注册 |
| 完整 R 颜色名表（657 个） | M2-4 B；A 段只收默认值会用到的常见名字 |

## 12. 已知边界

- **默认标签的极端量级**：`format_numbers()` 复刻 R `format()` 的常见路径
  （同组同小数位 + 定宽/科学记号比宽度）。量级 >= 1e7 或 < 1e-4 时 R 的取舍依赖
  `width` / `scipen`，个别值可能差一位；夹具覆盖的取值是逐字节相同的。
- **日期时间的 `pretty`**：sec / min / hour / day / week / halfmonth / month /
  quarter / halfyear / year / decade / century 的步长阶梯与 R 对齐；极小范围
  （< 1 秒）与 `start.on.monday = FALSE` 没有覆盖。周对齐按 R 的默认
  （周一为一周之始）。
- **分箱的 `n.breaks` 语义**：`scale_x_binned()` 默认 `n.breaks = 10`（位置分箱
  上游默认 10），colour 分箱默认 `NULL` → 变换断点函数的默认（identity 时约 5）。
  `n.breaks` 只影响 `nice.breaks = TRUE` 的默认断点，给了 `breaks` 就不生效
  （上游同样如此）。
- **分箱位置的两段语义**：第一段 `map()` 返回箱号是 R 的契约；`ScaleSet.reset()`
  在 `build_plot` 的第二段训练前调用。直接调用 `scale.map()`（不经 build）拿到
  的是箱号，需要箱中心时先 `scale.reset()`。
- **非位置标度的训练时点**：上游在 stat / geom setup 之后才
  `npscales$train_df(data)`；`ggcore` 在两段 `train` 里就用 aesthetics 列训练。
  对已支持的 stat（identity / count / bin）等价；接更多 stat 时如果出现
  「stat 之后才产生的离散美学」，要回到这里补一次训练。
- **`scale_colour_continuous()` 的主题调色板**：4.0.3 里它的 palette 由
  `theme$palette.colour.continuous` 提供，缺省回退到
  `pal_seq_gradient("#132B43", "#56B1F7")`。`ggcore` 直接用这个回退值（主题的
  调色板元素留给 M2-5）；夹具里 gradient 的两个端点就是用
  `scale_colour_gradient()` 钉的。
- **`values` 的循环补齐**：上游 4.0.3 的 manual scale 在 values 不够时直接 abort，
  `ggcore` 同样报错（不做 ggplot2 2.x 的循环）。
- 不动 IR 版本；`map_scales` 的结果仍只在数据层，进 IR 是 M1-7。
