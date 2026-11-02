# 标度口径（M1-4）

`ggcore.scales` 把 ggplot2 4.0.3 的标度实现搬过来：位置（连续 / 离散 / log10）、
`colour` / `fill`（连续渐变 + 离散 hue）、`size`、`shape`、`alpha`。参数覆盖
`limits` / `breaks` / `labels` / `trans` / `expand` / `na.value` / `values`
（`palette`），训练后的范围、断点、标签、色值与 R 逐项对拍。

代码：`src/ggcore/scales.py`。测试：`tests/test_scales.py`（口径 / 负向）、
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
- 第一段 `train`：aesthetics 之后；
- `map_position()` 只映射**位置美学**（上游 `layout$map_position()` 也只碰 x / y）；
- 第二段 `train`：`compute_position()` 之后，用 **positioned** 数据（含
  `xmin` / `xmax` / `ymin` / `ymax`）。这一点是必须的：柱子的锚点是
  `x ± width/2`，不把它们收进范围，stage 5 的 `oob` 会把锚点 censor 成 NA；
- `map_scales()`（阶段 5）映射**全部**美学：位置 = censor（幂等），
  colour / fill / size / shape / alpha = 调色板 / rescale。

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

注册表里的 13 个名字就是全部实现：`x/y_continuous`、`x/y_discrete`、
`x/y_log10`、`colour/fill_continuous`（= gradient）、`colour/fill_discrete`
（= hue）、`size_continuous`、`shape_discrete`、`alpha_continuous`。
`*_continuous` / `*_discrete` 在 4.0.3 里就是 gradient / hue 的别名
（`tools/refs/scales_ref.R` 末尾有自检）。

## 3. limits / expand

两个不同的东西，别混：

- `Scale.limits()` = 上游 `scale$get_limits()`：**训练后的数据范围**（或显式
  `limits`），**没有** expand；
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
  `docs/notes/scales.md` 的实现与 R 在 19 组范围上逐项相等
  （`tests/test_scales.py::test_extended_breaks_match_r`）。
- `n.breaks = 3` → 用 `n = 3` 调 breaks 函数（Python 关键字可写 `n_breaks` 或
  `n.breaks`）。
- `breaks = c(2, 4, 6)` 手动断点优先；`trans = "log10"` 时用
  `breaks_log()`（整十次幂，不够时走 `log_sub_breaks`）。
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

| 标度 | 实现 | 取值 |
| --- | --- | --- |
| 离散 colour / fill | `hue_pal(h = c(15, 375), c = 100, l = 65)` | HCL → sRGB，D65 白点 |
| 连续 colour / fill | `gradient_pal(low, high)` | Lab 空间线性插值，默认 `#132B43` → `#56B1F7` |
| 连续 size | area 标度 | `1 + 5 × sqrt((x - lo) / (hi - lo))`，范围 1..6 |
| 连续 alpha | 线性 | 0..1 → 0.1..1 |
| 离散 shape | `pal_shape()` | 16, 17, 15, 3, 7, 8（超过 6 个水平记 NA 并发 warning） |

hue 的十六进制值与 R 4.0.3 **逐字节相同**：n = 2 → `#F8766D #00BFC4`，n = 3 →
`#F8766D #00BA38 #619CFF`，n = 6 → `#F8766D #B79F00 #00BA38 #00BFC4 #619CFF
#F564E3`（`tests/test_scales.py` 逐字节钉住，R 侧在夹具的 `palettes.hue`）。

gradient 在 0 / 0.25 / 0.5 / 0.75 / 1 上同样逐字节相等（`#132B43` `#22496C`
`#336A98` `#448DC6` `#56B1F7`）；容差不需要放宽——Lab 插值与 R 的
`scales::colour_ramp()` 同一条路径（同一套 D65 / 矩阵 / 伽马）。

`values=`（manual）按水平顺序取色，长度不够时**报错**，不循环补齐（上游 4.0.3
的 manual scale 同样要求足够长度的 values）。`palette=` 可以给可调用对象或序列。

## 7. NA / 越界

- 连续标度：`oob = censor`（默认）——超出 `limits` 的**有限值** → NA，然后
  `na.value` 填空（位置标度是 `NA_real_`，colour 是 `"grey50"`，size / alpha 是 NA）。
- `oob = "squish"` **未实现**（报 `ScaleError`，点名后续任务）。
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

22 个 case：连续默认 expand / `expand = c(0, 0)` / 显式 limits / 手动 breaks +
labels / `n.breaks` / log10（x 与 y）/ 离散水平 / 显式 limits / `drop = FALSE` /
NA 水平 / limits 反序 / hue（含 na.value 与 limits）/ manual values / fill / gradient
（含 limits）/ size / alpha / shape。规模钉死在
`tests/test_scales_r_parity.py::test_compared_cell_count`（82 个断点、70 个映射值）。

对拍口径：数值 `abs <= 1e-12`，十六进制逐字节，`null` = NA，`"Inf"` / `"-Inf"` =
R 的 ±Inf（见 §7）。

## 9. 不支持清单

| 项 | 状态 |
| --- | --- |
| `date` / `datetime` / `time` 标度（`scale_x_date`） | 不做（后续标度任务） |
| binned 标度（`scale_x_binned` / `scale_colour_steps`） | 不做 |
| `scale_colour_viridis_*` / `gradient2` / `gradientn` | 不做（只有两端 gradient） |
| secondary axis（`sec.axis`） | 不做 |
| `oob = squish` | 不做（只有 censor） |
| `trans = reverse` / `sqrt` / `log2` / `exp` / `pseudo_log` | 不做；构造时报错并点名后续任务 |
| 位置标度以外的 expand / 面板范围 | 不做（只有 x / y 有 `expanded_limits()`） |
| guide / 图例排版 | 不做（M1-11） |
| coord 变换对 limits 的接管（`coord_cartesian(xlim=)`） | 不做（M1-5） |
| `scale_linetype_*` / `scale_size_manual` 等未登记的名字 | 不在 `registry.SCALE_SPECS` 里，不加第二套注册 |

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
