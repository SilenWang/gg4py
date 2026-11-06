# 标度口径（M1-4 / M2-4）

`ggcore.scales` 把 ggplot2 4.0.3 的标度实现搬过来。M1-4 的 15 个基础名字（位置连续 /
离散 / log10、`colour` / `fill` 的渐变与 hue、`size`、`shape`、`alpha`）打底；
M2-4 按「家族 × 变体」补齐到 **129 个注册名**（A 段连续侧 75 个、B 段离散 / 色板
新增 54 个），每个家族一套实现，变体（`discrete` / `ordinal` / `manual` /
`identity` / `brewer` / `viridis_*` / `area` / `binned` …）只换色板与映射函数。

| 族 | 导出 | 实现 |
| --- | --- | --- |
| 位置连续 | `x/y_continuous`、`_log10`、`_sqrt`、`_reverse`；`trans = "log2"` / `("exp", base)` | `PositionContinuousScale` + `trans` |
| 位置分箱 | `x/y_binned` | `BinnedPositionScale`（stat 前箱号 / stat 后箱中心） |
| 位置日期时间 | `x/y_date`、`_datetime`、`_time` | `PositionContinuousScale` + `trans = date/time/hms` |
| 连续渐变 | `{colour,color,fill}_continuous`、`_gradient`、`_date`、`_datetime` | `GradientScale` |
| 发散 / n 色渐变 | `_gradient2`、`_gradientn` | `Gradient2Scale` / `GradientNScale` |
| 分箱颜色 | `_binned`、`_steps`、`_steps2`、`_stepsn` | `BinnedGradient*Scale` |
| Brewer 连续侧 | `_distiller`、`_fermenter` | `DistillerScale` / `FermenterScale` |
| 离散颜色 | `_hue`、`_brewer`、`_grey`、`_ordinal`、`_manual`、`_identity`、`_viridis_d`、`_viridis_b` | `HueScale` / `BrewerScale` / `GreyScale` / `OrdinalColourScale` / `DiscreteIdentityScale` / `BinnedColourScale` |
| 连续 viridis | `_viridis_c` | `GradientNScale`（6 色） |
| 其它美学 | `alpha` / `alpha_binned` / `alpha_date` / `alpha_datetime` / `_ordinal` / `_manual` / `_identity`；`size` / `_area` / `_binned` / `_binned_area` / `_date` / `_datetime` / `_ordinal` / `_manual` / `_identity`、`radius`；`linewidth` / `_continuous` / `_binned` / `_date` / `_datetime` / `_ordinal` / `_manual` / `_identity`；`shape*` / `linetype*` | `AlphaScale` / `SizeScale` / `RadiusScale` / `LinewidthScale` / `ShapeScale` / `LinetypeScale` / `NumericDiscreteScale`（+ 分箱版 / identity 版） |

名字 → 美学 / 实现族 / 默认值的唯一来源是 `src/ggcore/scale_specs.py`：注册表
（`registry.SCALE_SPECS`）与 `scale_from_component()` 都读这张表，新增一个导出
只需要加一行，不另写一个构造函数。`scale_color_*` 与 `scale_colour_*` 是同一实现
的别名（上游 NAMESPACE 两个都导出）。

参数覆盖 `limits` / `breaks` / `labels` / `minor_breaks` / `n.breaks` / `trans` /
`expand` / `na.value` / `oob` / `palette` / `values` / `date_breaks` /
`date_labels` / `date_minor_breaks` / `right` / `nice.breaks` / `show.limits`，
训练后的范围、断点、标签、色值与 R 逐项对拍。

代码：`src/ggcore/scales.py`（实现）、`src/ggcore/scale_specs.py`（导出表）、
`src/ggcore/palettes.py`（色板与颜色空间）、`src/ggcore/palette_data.py`
（**生成物**：brewer / viridis 取值表）、`src/ggcore/scales_date.py`（日期时间
`pretty` / `breaks_width` / 格式化）。测试：`tests/test_scales.py`（口径 / 负向）、
`tests/test_scales_families.py`（族级 + 每个导出进 build）、
`tests/test_scales_r_parity.py`（84 个 case 的 R 对拍）、
`tests/test_palettes_r_parity.py`（逐色对拍）。

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
- 第二段 `train`：`compute_position()` 之后，先用 `ScaleSet.reset()` 复现
  `layout$reset_scales()`（连续位置标度清空范围、离散位置标度只清 `range_c`），
  再用 **positioned** 数据重训。训练列是上游 `ggplot_global$x_aes` / `y_aes`
  的全集（`x` / `xmin` / `xmax` / `xend` / `xintercept` / `xmin_final` /
  `lower` / `middle` / `upper` …），所以 `geom_boxplot()` 的离群点（只存在于
  `ymax_final`）仍在面板里，而 `geom_hex()` 的面板取六边形中心的范围。柱子的
  锚点 `x ± width/2` 也靠这一段收进范围，否则 stage 5 的 `oob` 会 censor 成 NA；
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
| `size` / `alpha` | —（恒为连续） | 连续（area / 线性） |
| `shape` | 离散（16/17/15/3/7/8） | 离散 |
| `linetype` | `scale_linetype_discrete()`（`pal_linetype`） | 离散（连续即报错，同上游） |
| `linewidth` | —（离散走 ordinal） | `scale_linewidth()`（线性到 1..6） |
| 其它（`group` / `PANEL` / `weight` / `width` …） | 不建标度，原样通过 | 同左 |

`xmin` / `xmax` / `xend` **共用 x 标度**，`ymin` / `ymax` / `yend` 共用 y 标度
（上游 `ggplot_global$x_aes` / `$y_aes`）。数值列进离散位置标度时**原样通过**
（上游 `ScaleDiscrete$map()` 只处理离散值），所以柱子的 `xmin = x - width/2`
不会被离散水平编码吃掉。

日期列（`kind = "date"` / `"datetime"`）不走上面的 identity 分支：位置 / colour /
fill / size / alpha / linewidth 的默认标度都带日历变换（`date` → `trans = "date"`、
`datetime` → `trans = "time"`），断点与标签按 `pretty.Date()` / `pretty.POSIXt()`
取，细则见 §9。

注册表现在是 **129 个名字**（M1-4 的 15 个 + M2-4 A 新增 64 个 + B 新增的离散 /
色板 54 个；两边重名的 `size_area` / `radius` / `linewidth_*` / `*_distiller`
只登记一次）。`*_continuous` / `*_discrete` 在 4.0.3 里就是 gradient / hue 的
别名；`scale_colour_gradient()` / `scale_fill_gradient()` 在 SIL-723 注册成同义名
（`colour_gradient` / `fill_gradient` → `GradientScale`，`+` 与方法链两条入口）
（`tools/refs/scales_ref.R` 末尾有自检）。`scale_colour_gradientn()` /
`scale_colour_stepsn()` 与上游一样**必须**给 `colours`。

### 2.1 名字表与「家族 × 变体」分派

`scale_from_component()` 先查 `scale_specs` 的声明表（名字 → 家族 + 默认值），
家族再映射到实现类；变体只是同一家族的另一种色板 / 映射函数：

| 家族 | 变体 |
| --- | --- |
| `colour_` / `color_` / `fill_` | `continuous` / `gradient` / `discrete` / `hue` / `brewer` / `distiller` / `grey` / `ordinal` / `manual` / `identity` / `viridis_c` / `viridis_d` / `viridis_b` / `binned` / `steps` / `gradient2` / `gradientn` / `steps2` / `stepsn` / `fermenter` / `date` / `datetime` |
| `shape_` | `shape` / `discrete` / `ordinal` / `manual` / `identity` / `binned`（`continuous` 报错） |
| `linetype_` | `linetype` / `discrete` / `manual` / `identity` / `binned`（`continuous` 报错） |
| `linewidth_` | `linewidth` / `continuous` / `discrete` / `ordinal` / `manual` / `identity` / `binned` / `date` / `datetime` |
| `size_` | `size` / `continuous` / `discrete` / `ordinal` / `manual` / `identity` / `area` / `binned` / `binned_area` / `radius` / `date` / `datetime` |
| `alpha_` | `alpha` / `continuous` / `discrete` / `ordinal` / `manual` / `identity` / `binned` / `date` / `datetime` |
| 位置 | `x_/y_` 的 `continuous` / `discrete` / `log10` / `sqrt` / `reverse` / `binned` / `date` / `datetime` / `time` |
| 跨美学 | `scale_discrete_manual(aesthetics=)` / `scale_discrete_identity(aesthetics=)` / `scale_continuous_identity(aesthetics=)` |

`color_*` 与 `colour_*` 是同一族（两个注册名、同一实现、同一 `colour` 美学）。
跨美学的三个名字由 `aesthetics=` 决定美学（上游同样没有缺省），注册表的工厂会把
它写进 `Scale.aesthetic`，否则 `p + scale_discrete_manual(...)` 会落到错误的美学上。

`scale_shape_continuous()` / `scale_linetype_continuous()` 在 R 里**构造即
`cli_abort()`**（连续变量不能映射到这两种美学），ggcore 同样在构造时报
`ScaleError`，名字保留在注册表里（NAMESPACE 里有它们）。

`scale_type()` 不是标度构造器，是「一个向量该用哪类标度」的查询函数：
`Column("float")` → `("continuous",)`、字符 / 逻辑 / categorical →
`("discrete",)`、`date` 列 → `("date", "continuous")`、datetime 列 →
`("datetime", "continuous")`（SIL-800）。R 的 `("ordinal", "discrete")`（有序
factor）仍依赖 ordered 标记，`ggcore.Column` 还没有它，
`tests/test_palettes_r_parity.py` 里钉住 R 侧的取值并注明未支持。

## 3. limits / expand

两个不同的东西，别混：

- `Scale.limits()` = 上游 `scale$get_limits()`：**训练后的数据范围**（或显式
  `limits`），**没有** expand；两边都是**变换后**的空间，见下一条；
- 显式 `limits` 是**数据空间**的值（`scale_x_log10(limits = c(1, 100))` 里的
  1 / 100 是原始数据），`limits()` 里先过 `trans` 再返回——R 4.0.3 的
  `get_limits()` 存的也是变换后的值（上例 → `(0, 2)`），`expanded_limits()` /
  `breaks()` / `map()` 都在这个空间里消费。单侧 `None` 取训练范围（已经是变换
  后的值，不能再变换一次）；log10 下给 0 / 负值时按模块统一约定落成 NA；
- `limits` 可以是**函数**（`scale_y_continuous(limits = function(lims) ...)`）：
  上游 `ScaleContinuous$get_limits()` 把**变换后**的训练范围喂给它，返回值也按
  变换后空间消费；无数据时给 `(0, 1)`，返回值不是 2 元就报 `ScaleError`。
  `functional-limits` 快照的 `limiter(50)`（计数 0..62 → 0..100）就是这条；
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
- `labels=` 支持四种写法：等长序列（按位置）、映射（断点值 / 水平 → 标签）、
  含 `%` 的格式串（`"%.1f"`）、**函数**（`label_date(...)` / 自定义回调）。函数只
  收**未 censor** 的断点（`None` 位置留空），返回长度不等就报错——与
  `Scale$get_labels()` 一致。`breaks = NULL` / `labels = NULL` 是显式「不要」，
  与不写参数（默认）不同，`_has_param()` 区分这两者。
- `breaks=` 可以是序列 / 映射 / 函数；日期时间标度上还可以是**字符串**
  （`scale_x_date(breaks = "week")`）——上游 `datetime_scale()` 把它当
  `breaks_width(<spec>)` 的简写。`breaks_width()` 的回调收一个 limits 向量
  （`function(x)`），本仓的 `breaks_width_date/time/hms()` 同时接受 `(limits)` 与
  `(low, high)` 两种写法。
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

色板的**取值表逐色入库**（`src/ggcore/palette_data.py`），不靠近似公式。表由
`tools/refs/palettes_ref.R` 生成，表头记录来源版本：

| 来源 | 版本 | 本仓库用到的部分 |
| --- | --- | --- |
| R | 4.5.3 | `grDevices::convertColor()` / `colorRamp()`（viridis 的插值链路） |
| ggplot2 | 4.0.3（上游 pin） | 各标度的参数与 `na.value` 缺省 |
| RColorBrewer | 1.1.3 | `brewer.pal()` 的**逐 n 表** |
| viridisLite | 0.4.3 | `viridis.map` 的 8 档 × 256 色量化表 |
| scales | 1.4.0 | `pal_hue()` / `pal_grey()` / `pal_area()` / `pal_rescale()` 等公式 |

`pixi run -e refs refs:scales` 一次重生成两份产物：`src/ggcore/palette_data.py`
（表）与 `tests/fixtures/palettes_r_reference.json`（夹具）。重跑必须零 diff。

### 6.0 各族色板一览（A 段）

| 用途 | 实现 |
| --- | --- |
{ours_rows}
### 6.1 RColorBrewer（`scale_*_brewer()`）

`brewer.pal(n, name)` **不是**「取最大表的前 n 个」：同一 palette 在 n = 3..max
是各自插值出来的一张表（`Blues` 的 3 色 ≠ 9 色的前 3 个），所以表里按 n 存整张
（35 个 palette、3..max 全量；qual 类的前缀恰好相同，但不能靠这个规律偷懒）。
`type`（`seq` / `div` / `qual`）与 `palette`（编号或名字）按 `scales::pal_name()`
解析；`palette` 不认识时发 warning 并回落 `Greens`。

`n < 3` 时 `brewer.pal()` 本身会警告并回落到 3 色表，再取前 n 个——我们照抄。
`n > maxcolors` 时上游只给 maxcolors 个、余下的索引是 `NA`，ggcore 记 `None`
（走 `na.value`）。`direction = -1` 反序。

hue 的十六进制值与 R 4.0.3 **逐字节相同**：n = 2 → `#F8766D #00BFC4`，n = 3 →
`#F8766D #00BA38 #619CFF`，n = 6 → `#F8766D #B79F00 #00BA38 #00BFC4 #619CFF
#F564E3`。gradient 在 0 / 0.25 / 0.5 / 0.75 / 1 上同样逐字节相等。

### 6.4 形状 / 线型 / 数值型离散色板

| 标度族 | 缺省取值 | 备注 |
| --- | --- | --- |
| `shape` | `c(16, 17, 15, 3, 7, 8)`（`solid = FALSE` 时 `c(1, 2, 0, 3, 7, 8)`） | 超过 6 个水平：warning + 多出来的记 `NA`（上游同样） |
| `linetype` | `"solid" / "22" / "42" / "44" / "13" / "1343" / "73" / "2262" / "12223242" / "F282" / "F4448444" / "224282F2" / "F1"` | 13 种，超出报错（上游 `manual_pal` 同样 abort） |
| `size_ordinal` | `sqrt(seq(4, 36, length.out = n))` | 与 `size` 连续的 area 缺省一致 |
| `alpha_ordinal` | `seq(0.1, 1, length.out = n)` | |
| `linewidth_ordinal` | `seq(2, 6, length.out = n)` | |
| `size_area` | `max_size * sqrt(v / max(v))`（`abs_area()` + `rescale_max`） | 面积正比于值 |
| `radius` / `linewidth` 连续 | `1 + 5 × v`（`pal_rescale(1:6)`） | 线性到 1..6 |
| `size` 连续 | `1 + 5 × sqrt(v)`（`pal_area()`） | 与 M1-4 相同 |

`_discrete` 在 size / alpha / linewidth 上是 `_ordinal` 的别名，并各发一条上游
同款 warning（"Using size for a discrete variable is not advised." 等）；
`shape_ordinal` 也有对应 warning。

{ours_text}
### 6.5 identity 与分箱

**identity**（`scale_*_identity()`）：映射是**原样通过**（上游 `pal_identity()`）。
它挂在连续 Range 上，字符 / 颜色值训练不进去，所以 `limits()` 恒为 `(0, 1)`、
`breaks()` 为空、`guide` 缺省 `"none"`——照抄上游，别按「水平表」理解它。

**分箱**（`shape_binned` / `linetype_binned` / `size_binned_area` /
`linewidth_binned` / `viridis_b`）：复刻 `binned_scale()` 的三件事：

1. `oob` 缺省是 `squish`（不是连续标度的 `censor`）：越界值压到两端；
2. `get_breaks()` 在**没有显式 limits** 时把数据范围往外扩到相邻断点
   （`extended_breaks(limits)` 的最外两个断点变成新的 limits）。例：数据
   `[2, 20]` 的断点是 `5 / 10 / 15`，limits 扩成 `(0, 20)`；
3. `map()` 先 `cut()` 成箱（`right = TRUE`、`include.lowest = TRUE`，等于边界的
   值归**下**一箱），再把**箱中点**喂给 palette——`pal_binned()` 只看长度（每箱
   一个固定值），`abs_area()` / `pal_rescale()` 这类连续色板逐箱取值。

`n.breaks` 给断点个数（缺省 5，走 `extended_breaks`）；`right` 可切分箱方向。
分箱标度的 `breaks()` / `labels()` 就是**箱边界**（不含两端 limits），与 guide
看到的是同一份。

## 7. NA / 越界（`oob`）

- `oob = censor`（连续默认）：超出 `limits` 的**有限值** → NA，然后 `na.value`
  填空（位置标度是 `NA_real_`，colour 是 `"grey50"`，size / alpha 是 NA）。
- `oob = squish`（**分箱默认**）：越界值钳到 `limits` 端点，不产生 NA；
- `oob = squish_infinite`：只钳 ±Inf，有限越界值原样保留；
- `oob = keep`：不做任何处理；
- `oob` 也可以给可调用对象（`oob(values, limits)` 或只收 `values`）。
- 离散位置：没有 `na.value` 概念，未知值 / 不在 limits 里的值 → NA（`mapped_discrete(NA)`）。
- **log10 / sqrt 的 0 与负值**：`ggcore` 一律记 NA（`Column.na_mask`），并累加到
  `Scale.non_finite_count`。上游这里有个 wart：`censor()` 只 censor 有限值，
  所以 `log10(0) = -Inf` 会原样留在 `$data$x` 里（R 的 `ggplot_build()` 实测是
  `-Inf`）。本任务按 issue 要求把它统一成 NA；夹具里那个位置记成字符串
  `"-Inf"`，`tests/test_scales_r_parity.py` 明确断言「R 是 Inf，我们是 NA」。

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

**默认标度按日历单位解析（SIL-800）**：`ggio` 把 `Date` 归一成
`kind = "date"`（自 1970-01-01 起的**天**）、`POSIXct` 归一成
`kind = "datetime"`（**秒**，见 `docs/notes/data.md`），所以默认标度解析
（`scales._default_scale()`）给日期列建 `trans = "date"`、给 datetime 列建
`trans = "time"`——与 R 的 `find_scale()` 找 `scale_<aes>_date` / `_datetime` 同义。
日期列不写 `scale_x_date()` 时，断点也是 `pretty.Date()` 的日历步长、标签是
ISO 日期，不再退回 `extended_breaks()` 的数值。位置 / colour / fill / size /
alpha / linewidth 六类美学都走这条规则；端到端 case 是
`docs/cases/scale-date-implicit-default-breaks`（R 侧同样不写标度）。

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

**84 个 case**（314 个断点 / 标签、294 个映射值、24 个 expand 向量）。A 段带来
连续位置（默认 expand / `expand = c(0, 0)` / 显式 limits / 手动 breaks + labels /
`n.breaks` / log10 / sqrt / reverse / 分箱）、日期时间（Date / datetime / hms 与各
`date_*` 参数）、颜色连续侧（gradient / gradient2 / gradientn / steps* / binned /
distiller / fermenter）与 alpha / size / linewidth 的连续 / 分箱 / 日期变体；
B 段带来离散 / brewer / viridis / grey / ordinal / manual / identity / 线型 / 线宽 /
面积 / 分箱各至少一条。两边重名的 6 个 case（`colour_distiller` / `radius` /
`size_area` / `size_binned_area` / `linewidth_*`）口径不同，合并后保留两边的期望
值，B 侧那条加 `_default` / `_fraction` 后缀区分。
规模钉死在 `tests/test_scales_r_parity.py::test_compared_cell_count`。

M2-4 B 的 31 个：brewer（含 `type = qual` 的编号 palette、`direction = -1`、
fill 侧、NA）/ viridis_d（选项 + begin/end/direction）/ grey（缺省 + 自定义端点）/
ordinal / identity（colour 与 alpha）/ distiller / viridis_c / viridis_b /
shape_manual / shape_binned / linetype_discrete / linetype_manual / linetype_identity /
linetype_binned / linewidth（连续 / ordinal / manual / binned / identity）/
size_area / size_binned_area / radius / size_ordinal / alpha_ordinal / alpha_manual。
规模钉死在 `tests/test_scales_r_parity.py::test_compared_cell_count`（183 个断点 /
标签、170 个映射值、13 个 expand 向量）。

分箱标度不走 `view_scale_primary()`（它的断点就是箱边界），R 侧改取标度自己的
`get_breaks()` / `get_labels()`；identity 标度上游不打断点，夹具里记空数组。

**色板夹具**：`tests/fixtures/palettes_r_reference.json`（同一任务的第二个脚本
`tools/refs/palettes_ref.R`）：

- brewer 35 个 palette 在 maxcolors 下的首 / 中 / 尾色 + 8 个 palette 的**逐 n 整表**；
- viridis A–H 每档的 n = 2/3/5/8 抽样 + `begin/end` / `direction` / `alpha` 变体；
- grey（n = 1..10 与自定义 start/end）、hue（n = 2..7,10）、数值型离散色板、`scale_type()`。

对拍口径：数值 `abs <= 1e-12`，十六进制逐字节（含 viridis 的 alpha 字节），
`null` = NA，`"Inf"` / `"-Inf"` = R 的 ±Inf（见 §7）。

## 11. 不支持清单

| 项 | 状态 |
| --- | --- |
| `trans = "log1p" / "reciprocal" / "logit" / "probit" / "asn" / "atanh"` | 未实现；构造时报错并点名后续任务 |
| `trans = "pseudo_log"` / `transform_pseudo_log(sigma, base)` | SIL-856 已实现：`asinh(x / (2σ)) / ln(base)`，逆变换 `2σ·sinh(y·ln(base))`。上游不传 `breaks`，断点仍是 `extended_breaks()`（在数据空间取，再变换回来），所以 `x = -100..100` 的断点是 -100/-50/0/50/100，不是等距的伪对数位置 |
| `transform_compose(...)` | SIL-856 已实现：正向按顺序、反向逆序；**断点取第一个变换的**（`compose(log10, reverse)` 仍是十次幂）；`domain` 由第一个变换的 domain 推过去再推回来，交集为空时报 `ScaleError`。字符串 / `("log", base)` / 变换对象三种写法都收 |
| `trans = "log2"` / `"exp"` / `("log", base)` / `("exp", base)` | SIL-790 已实现：`_Log(base)` / `_Exp(base)`。`log2` 的断点走 `breaks_log(base = 2)`（2 的幂）；`exp` 与上游 `transform_exp()` 一样不传 breaks / domain，断点仍在数据空间。`"exp"` 单独写等于自然底 |
| `space != "Lab"` 的渐变插值 | 上游 4.0.3 已废弃；这里报 `ScaleError` |
| secondary axis（`sec.axis`） | M2-1 已实现（`sec_axis()` / `dup_axis()`，见 `docs/notes/coord.md` §12）；标度侧只存引用，断点 / 标签在 `ggcore.axis` |
| 位置标度以外的 expand / 面板范围 | 不做（只有 x / y 有 `expanded_limits()`） |
| guide / 图例排版（`colourbar` / `coloursteps` / `bins`） | M2-2（guides 任务）；`guide="bins"` 仍按既有文案报错 |
| coord 变换对 limits 的接管（`coord_cartesian(xlim=)`） | M1-5 已实现；`coord_trans` 的逐轴变换见 M2-1（`docs/notes/coord.md` §8） |
| `scale_linetype_*` / `scale_size_manual` 等未登记的名字 | 不在 `registry.SCALE_SPECS` 里，不加第二套注册 |
| `scale_type()` 的 `("ordinal", "discrete")` / `("date", "continuous")` | `ggcore.Column` 还没有 ordered / Date 标记 |
| `scale_shape_continuous()` / `scale_linetype_continuous()` | 上游本身 `cli_abort()`；ggcore 在构造时报同样的错 |

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
- **`lty` 串的段长折算**（与标度无关，登记在这里因为 M2-4 B 的 linetype case 踩到）：
  两段折算缺一不可，公式是

  ```
  IR lty (pt) = pattern × max(gpar$lwd, 1) × 72/96
  SVG dasharray (1/96 in) = IR lty × DASH_UNIT(4/3) = pattern × max(lwd, 1)
  ```

  - `max(lwd, 1)`：段长是 `lwd` 的倍数，`lwd < 1` 时按 1 算（参考产线 svglite 的
    口径：`lwd = 0.5` / `0.9` / `1.0` 的 `lty = "dashed"` 都是 `4,4` 段长，只有
    线的粗细跟着 `lwd` 变）。用 `lwd` 本身会在细线上把虚线画密（SIL-737 的
    abline 用例）；专项 case 见 `docs/cases/grob-dash-lwd` 与
    `tests/test_grobs.py::test_dash_length_follows_max_lwd_one`。
  - `72/96 = 0.75`：IR 的 `lty` 是 pt，而 `pattern × max(lwd, 1)` 是 lwd 单位
    （1/96 inch）。漏了这一步，渲染器再乘 `DASH_UNIT` 就让**所有虚线长 4/3 倍**
    （SIL-737 只做了第一段折算，SIL-763 补上这一段；6 张 `grob-*` 基线正是按
    漏乘的代码录的，补上后逐字节复现）。
  - 参考产线把 `pattern × max(lwd, 1)` 的数值直接写进 SVG 的 `stroke-dasharray`
    （只折线宽、不折段长），所以 `"22"`、`lwd = 1` 的参考图里段长就是 `2,2`；
    `web/viewer/src/render.ts` 与 `src/ggskia/skia.py` 都乘 `DASH_UNIT = 4/3`
    回到这个口径，`lwd = 0` 两边都不描边。实测 `geom-line-width` 1.31% → 0.13%，
    `scale-linetype-discrete` 1.25% → 0.06%，`viewer-linetype-all` 3.70% → 0.43%
    （口径见 `docs/notes/viewer.md` §10.1）。
- **`scale_*_viridis_d` 的十六进制是 8 位**（`#440154FF`）：R 的 `pal_viridis()`
  把 alpha 一起编码，`$data$colour` 里就是 8 位；`gpar` 的 `col2rgb` 认 8 位，
  渲染结果与 6 位相同。viridis_c 走 `colour_ramp()`，输出是 6 位。
