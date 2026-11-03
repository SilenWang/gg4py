# 标度口径（M1-4 / M2-4）

`ggcore.scales` 把 ggplot2 4.0.3 的标度实现搬过来。M1-4 落了位置（连续 / 离散 /
log10）与 `colour` / `fill` / `size` / `shape` / `alpha` 的基础形状；M2-4 把它扩成
**「家族 × 变体」**：位置、colour / color / fill、shape、linetype、linewidth、size、
alpha 七个家族，每个家族一套实现，变体（`discrete` / `ordinal` / `manual` /
`identity` / `brewer` / `viridis_*` / `area` / `binned` …）只换色板与映射函数。
注册表里现在有 **80 个标度名**（M1 的 13 个 + M2-4 B 的 65 个 + A 的连续 / 分箱族
另注册），全部由 `registry.SCALE_SPECS` 一张表驱动。

参数覆盖 `limits` / `breaks` / `labels` / `trans` / `expand` / `na.value` /
`values`（`palette`）；训练后的范围、断点、标签、色值与 R 逐项对拍。

代码：`src/ggcore/scales.py`（标度类）、`src/ggcore/palettes.py`（色板与颜色空间）、
`src/ggcore/palette_data.py`（**生成物**：brewer / viridis 的取值表）。测试：
`tests/test_scales.py`（口径 / 负向）、`tests/test_scales_r_parity.py`（54 个 case
的 R 对拍）、`tests/test_palettes_r_parity.py`（逐色对拍）。

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
| `size` / `alpha` | —（恒为连续） | 连续（area / 线性） |
| `shape` | 离散（16/17/15/3/7/8） | 离散 |
| `linetype` | `scale_linetype_discrete()`（`pal_linetype`） | 离散（连续即报错，同上游） |
| `linewidth` | —（离散走 ordinal） | `scale_linewidth()`（线性到 1..6） |
| 其它（`group` / `PANEL` / `weight` / `width` …） | 不建标度，原样通过 | 同左 |

`xmin` / `xmax` / `xend` **共用 x 标度**，`ymin` / `ymax` / `yend` 共用 y 标度
（上游 `ggplot_global$x_aes` / `$y_aes`）。数值列进离散位置标度时**原样通过**
（上游 `ScaleDiscrete$map()` 只处理离散值），所以柱子的 `xmin = x - width/2`
不会被离散水平编码吃掉。

### 2.1 名字表与「家族 × 变体」分派

`scale_from_component()` 只看注册名的**前缀**（家族）与**后缀**（变体）：

| 家族 | 变体（M2-4 B 落地的部分） |
| --- | --- |
| `colour_` / `color_` / `fill_` | `continuous` / `gradient` / `discrete` / `hue` / `brewer` / `distiller` / `grey` / `ordinal` / `manual` / `identity` / `viridis_c` / `viridis_d` / `viridis_b` |
| `shape_` | `shape` / `discrete` / `ordinal` / `manual` / `identity` / `binned`（`continuous` 报错） |
| `linetype_` | `linetype` / `discrete` / `manual` / `identity` / `binned`（`continuous` 报错） |
| `linewidth_` | `linewidth` / `continuous` / `discrete` / `ordinal` / `manual` / `identity` / `binned` |
| `size_` | `size` / `continuous` / `discrete` / `ordinal` / `manual` / `identity` / `area` / `binned_area` / `radius` |
| `alpha_` | `alpha` / `continuous` / `discrete` / `ordinal` / `manual` / `identity` |
| 跨美学 | `scale_discrete_manual(aesthetics=)` / `scale_discrete_identity(aesthetics=)` / `scale_continuous_identity(aesthetics=)` |

`color_*` 与 `colour_*` 是同一族（两个注册名、同一实现）。跨美学的三个名字由
`aesthetics=` 决定美学（上游同样没有缺省），注册表的工厂会把它写进
`Scale.aesthetic`，否则 `p + scale_discrete_manual(...)` 会落到错误的美学上。

`*_continuous` / `*_discrete` 在 4.0.3 里就是 gradient / hue 的别名；
`scale_colour_gradient()` / `scale_fill_gradient()` 在 SIL-723 也注册成同义名。
`scale_shape_continuous()` / `scale_linetype_continuous()` 在 R 里**构造即
`cli_abort()`**（连续变量不能映射到这两种美学），ggcore 同样在构造时报
`ScaleError`，名字保留在注册表里（NAMESPACE 里有它们）。

`scale_type()` 不是标度构造器，是「一个向量该用哪类标度」的查询函数：
`Column("float")` → `("continuous",)`、字符 / 逻辑 / categorical →
`("discrete",)`、datetime 列 → `("datetime", "continuous")`。R 的
`("ordinal", "discrete")`（有序 factor）与 `("date", "continuous")` 依赖
ordered / Date 标记，`ggcore.Column` 还没有这两种标记（日期标度归 M2-4 A），
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
  含 `%` 的格式串（`"%.1f"`）。

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

### 6.1 RColorBrewer（`scale_*_brewer()`）

`brewer.pal(n, name)` **不是**「取最大表的前 n 个」：同一 palette 在 n = 3..max
是各自插值出来的一张表（`Blues` 的 3 色 ≠ 9 色的前 3 个），所以表里按 n 存整张
（35 个 palette、3..max 全量；qual 类的前缀恰好相同，但不能靠这个规律偷懒）。
`type`（`seq` / `div` / `qual`）与 `palette`（编号或名字）按 `scales::pal_name()`
解析；`palette` 不认识时发 warning 并回落 `Greens`。

`n < 3` 时 `brewer.pal()` 本身会警告并回落到 3 色表，再取前 n 个——我们照抄。
`n > maxcolors` 时上游只给 maxcolors 个、余下的索引是 `NA`，ggcore 记 `None`
（走 `na.value`）。`direction = -1` 反序。

### 6.2 viridis（`scale_*_viridis_c|d|b()`）

`viridisLite::viridis(n, alpha, begin, end, direction, option)` 的链路是：

```
viridis.map[option] 的 256 色（8 位量化）
  → colorRamp(space = "Lab", interpolate = "spline")   # grDevices
  → 在 seq(begin, end, length.out = n) 上采样
  → rgb() 量化成 #RRGGBBAA（alpha 恒在，缺省 FF）
```

三步都复刻了，所以十六进制值（含 alpha 的两字符）与 R **逐字节**相同：

1. **颜色空间走 grDevices，不是 farver。** `grDevices::convertColor()` 的 sRGB
   矩阵与白点是 R 自己的常量（白点 = 矩阵列和 `(0.9532, 1, 1.0854)`，不是 CIE 的
   `(0.95047, 1, 1.08883)`），而且 `to = "sRGB"` 这一路会把结果**四舍五入到 5 位
   小数**。`ggcore.palettes.srgb_to_lab_gd()` / `lab_to_srgb_gd()` 是这条路径；
   `hex_to_lab()` / `lab_to_hex()` 是 farver 路径（hue / gradient 用）。两条路径的
   Lab 值差 1e-2 量级，混用会让 viridis 掉一位色。
2. **插值是 fmm 三次样条。** `stats::splinefun(method = "fmm")`：结点 256 个等距
   点，两端的二阶导由「端点区间的三阶导 = 前/后 4 点的三阶差商」定
   （Forsythe–Malcolm–Moler，不是 natural）。`_fmm_coefficients()` 用三对角
   （Thomas）解法复刻；系数缓存，采样只做多项式求值。
3. **采样点是 `seq(begin, end, length.out = n)`**：末项**强制**等于 `end`
   （与 `numpy.linspace` 同口径，不是 `from + i*step`）。

`option` 收 `A`–`H` 与 viridisLite 的名字（`magma` / `inferno` / `plasma` /
`viridis` / `cividis` / `rocket` / `mako` / `turbo`）；不认识的发 warning 回落 `D`。

三个变体：

| 标度 | 实现 | 色数 | `na.value` |
| --- | --- | --- | --- |
| `viridis_d`（离散） | `pal_viridis()` | n 个水平 | `NA`（不是 grey50） |
| `viridis_c`（连续） | `pal_gradient_n(pal_viridis()(6))`：6 色再走 Lab 线性插值 | 6 | `"grey50"` |
| `viridis_b`（分箱） | `pal_binned(pal_viridis())`：每箱一个色 | 箱数 | `"grey50"` |

`alpha` 参数在离散 / 分箱色板里直接进 8 位十六进制；连续色板补回固定的 alpha 字节
（`colour_ramp()` 只插值 RGB，所有采样点的 alpha 相同，所以是等价的）。

### 6.3 其余色板

| 标度 | 实现 | `na.value` 缺省 |
| --- | --- | --- |
| `scale_*_hue()` / `*_discrete` | `hue_pal(h = c(15, 375), c = 100, l = 65)` | `"grey50"` |
| `scale_*_grey()` | `pal_grey(start = 0.2, end = 0.8)`（`grey.colors(n, start, end)`，gamma 2.2） | **`"red"`**（上游签名如此） |
| `scale_*_ordinal()` | 4.0.3 缺省 `scale_*_viridis_d`；`type =` 给一串颜色时走 `pal_ordinal()`（`colour_ramp()` 等距取样） | `NA` |
| `scale_*_distiller()` | `pal_gradient_n(pal_brewer(type, palette, direction = -1)(7))` | `"grey50"` |
| `scale_*_manual()` | 序列按水平顺序（不够**报错**，不循环）/ 映射按水平名 | colour：`"grey50"`；size / alpha / shape / linetype / linewidth：`NA` |

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

## 7. NA / 越界

- 连续标度：`oob = censor`（默认）——超出 `limits` 的**有限值** → NA，然后
  `na.value` 填空（位置标度是 `NA_real_`，colour 是 `"grey50"`，size / alpha 是 NA）。
- `oob = "squish"`：**只有分箱标度**支持（上游 `binned_scale(oob = squish)` 是
  它的缺省）；连续标度传 `oob = "squish"` 仍然报 `ScaleError`。
- 离散位置：没有 `na.value` 概念，未知值 / 不在 limits 里的值 → NA（`mapped_discrete(NA)`）。
- **log10 的 0 与负值**：`ggcore` 一律记 NA（`Column.na_mask`），并累加到
  `Scale.non_finite_count`。上游这里有个 wart：`censor()` 只 censor 有限值，
  所以 `log10(0) = -Inf` 会原样留在 `$data$x` 里（R 的 `ggplot_build()` 实测是
  `-Inf`）。本任务按 issue 要求把它统一成 NA；夹具里那个位置记成字符串
  `"-Inf"`，`tests/test_scales_r_parity.py` 明确断言「R 是 Inf，我们是 NA」。

## 8. 与 R 对拍

夹具：`tests/fixtures/scales_r_reference.json`，由
`pixi run -e refs refs:scales`（`tools/refs/scales_ref.R`）生成；产物入库，CI 不装 R。

每个 case 记录：`scale`（注册名）、`params`、`train`、`map`、`limits`、
`expand`（4 元）、`expanded_limits`、`breaks`、`labels`、`mapped`。
R 侧取的是 `scale$get_limits()` / `default_expansion()` / `scale$dimension()` /
`view_scale_primary()$breaks` / `$get_labels()` / `scale$map()`——与 `ggplot_build()`
里 `layout$setup_panel_params()` 转出来的那一份同源。位置标度的断点按 **expand
之后**的范围算（`view_scales_from_scale()` 的口径），colour / size / alpha / shape
按 `limits` 算（guide 的口径）。

**54 个 case**。M1-4 的 23 个：连续默认 expand / `expand = c(0, 0)` / 显式 limits /
手动 breaks + labels / `n.breaks` / log10（x 与 y，外加「log10 + 显式 limits」）/
离散水平 / 显式 limits / `drop = FALSE` / NA 水平 / limits 反序 / hue（含 na.value
与 limits）/ manual values / fill / gradient（含 limits）/ size / alpha / shape。

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

## 9. 不支持清单

| 项 | 状态 |
| --- | --- |
| `date` / `datetime` / `time` 标度、`scale_*_date\|datetime` | 归 M2-4 A |
| 位置侧的 `sqrt` / `reverse` / `binned`、`scale_*_binned` / `_steps*` / `gradient2` / `gradientn` / `fermenter` | 归 M2-4 A |
| `sec.axis` / `dup_axis` | 不做（M2-1 已接次轴，标度侧的 `sec.axis` 参数仍报错） |
| `oob = squish`（连续标度） | 不做（只有分箱标度支持 squish） |
| `trans = reverse` / `sqrt` / `log2` / `exp` / `pseudo_log` | 归 M2-4 A；构造时报错并点名 |
| 位置标度以外的 expand / 面板范围 | 不做（只有 x / y 有 `expanded_limits()`） |
| `guide_bins` / `guide_coloursteps` | 不做（M2-2）；`viridis_b` 因此回落 colourbar |
| coord 变换对 limits 的接管（`coord_cartesian(xlim=)`） | 不做（M1-5） |
| `scale_type()` 的 `("ordinal", "discrete")` / `("date", "continuous")` | `ggcore.Column` 还没有 ordered / Date 标记（随 A 的日期标度一起做） |
| `scale_shape_continuous()` / `scale_linetype_continuous()` | 上游本身 `cli_abort()`；ggcore 在构造时报同样的错 |

## 10. 已知边界

- **默认标签的极端量级**：`format_numbers()` 复刻 R `format()` 的常见路径
  （同组同小数位 + 定宽/科学记号比宽度）。量级 >= 1e7 或 < 1e-4 时 R 的取舍依赖
  `width` / `scipen`，个别值可能差一位；夹具覆盖的 10 组是逐字节相同的。
- **非位置标度的 expand**：`Expansion` 在类上都有默认值（与上游
  `default_expansion()` 一致），但 `expanded_limits()` 只对位置标度返回数值，
  其余返回 `None`——coord（M1-5）只消费 x / y。
- **非位置标度的训练时点**：上游在 stat / geom setup 之后才
  `npscales$train_df(data)`；`ggcore` 在两段 `train` 里就用 aesthetics 列训练。
  对已支持的两个 stat（identity / count）等价（stat 不改 colour / fill 的水平），
  接更多 stat 时如果出现「stat 之后才产生的离散美学」，要回到这里补一次训练。
- **`scale_colour_continuous()` 的主题调色板**：4.0.3 里它的 palette 由
  `theme$palette.colour.continuous` 提供，缺省回退到
  `pal_seq_gradient("#132B43", "#56B1F7")`。`ggcore` 直接用这个回退值（主题的
  调色板元素留给 M1-10）；夹具里 gradient 的两个端点就是用 `scale_colour_gradient()`
  钉的，并自检别名与它一致。
- **`values` 的循环补齐**：上游 4.0.3 的 manual scale 在 values 不够时直接 abort，
  `ggcore` 同样报错（不做 ggplot2 2.x 的循环）。
- 不动 IR 版本；`map_scales` 的结果仍只在数据层，进 IR 是 M1-7。
- **`lty` 串的段长折算**（与标度无关，登记在这里因为 M2-4 B 的 linetype case 踩到）：
  R 的 `gpar$lwd` 是 1/96 inch，`ggcore` 写 IR 时乘 `72/96 = 0.75` 折成 pt，
  `lty` 的段长（`lwd` 的倍数）**跟着一起折**（`docs/notes/grobs.md`、SIL-636）。
  svglite 的 `stroke-dasharray` 只折算线宽、不折算段长，所以参考图里 `"22"` 的
  段长是 6.26pt，而按物理口径应是 4 × 3.13 × 0.75 = 9.4pt 量级的比例关系；
  实测把段长改成 ×4/3 后 `geom-line-width` 的图级差异从 1.31% 降到 0.13%。
  这条属于 **SVG 渲染器的 dash 口径（M2-12）**，不在标度任务里改；
  `scale-linetype-discrete` 的 case 因此关掉图例（键宽 + dash 口径叠加会越过 2%）。
- **`scale_*_viridis_d` 的十六进制是 8 位**（`#440154FF`）：R 的 `pal_viridis()`
  把 alpha 一起编码，`$data$colour` 里就是 8 位；`gpar` 的 `col2rgb` 认 8 位，
  渲染结果与 6 位相同。viridis_c 走 `colour_ramp()`，输出是 6 位。
