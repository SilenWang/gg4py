# 表格布局账本（gtable）

`ggcore.gtable` 是 R **gtable 0.3.6** 的对等物，也是 ggplot2 版式的地基：
panel / axis / legend / title 都按 gtable 的行列拼装。这里记「与 R 对齐但结论
不明显」的口径、R 侧参考值怎么来，以及刻意不复制的行为。

参考实现：gtable 0.3.6（`pixi.toml` 的 `[feature.refs]` 钉 `r-gtable = 0.3.*`）
+ R 4.5.3 的 `grid`（`r-base` 自带）。行高列宽真正的分配在 grid 里，
`grid/src/layout.c` 的 `calcViewportLayout()`（`:492`）。

## 模型：一张表 = 两个单位向量 + 一张 layout 表

| gg4py | R gtable | 说明 |
| --- | --- | --- |
| `GTable.widths` | `x$widths` | 列宽单位向量，长度 = 列数 |
| `GTable.heights` | `x$heights` | 行高单位向量，长度 = 行数 |
| `GTable.layout` | `x$layout` | 每行一个 `Placement(t, l, b, r, z, clip, name)` |
| `GTable.grobs` | `x$grobs` | 与 `layout` 等长的 grob 列表 |
| `GTable.respect` / `.name` / `.rownames` / `.colnames` | 同名 | |

行数 = `len(heights)`，列数 = `len(widths)`——R 的 `gtable()` 签名就是
`gtable(widths, heights, ...)`（`R/gtable.R:94`），行列由这两个向量隐式给出。
gg4py 额外接受 `rows=` / `cols=` 两个别名（分别指向 `heights` / `widths`），
只是为了让「行定义在前」的读法能写出来，不能与 `widths` / `heights` 同时给。

表是不可变的：`gtable_add_*` 返回新表（R 里是 `x <- gtable_add_grob(x, ...)`
的赋值写法，语义相同）。

grob 在 gg4py 里是**任意对象**：M0-6 的 grob 系统还没落地，gtable 只需要
「一个可以挂在单元格上的东西」。子 `GTable` 也是合法 grob，于是嵌套表就是
「表里放表」（见「嵌套」）。

## 尺寸解析：照抄 `calcViewportLayout()`

`Layout.resolve(width_cm, height_cm)` 按 grid 的四步走（`layout.c`）：

1. `findRelWidths()`：哪一列/行是**纯 null**——`units.is_pure_null(widths, i)`。
2. `allocateKnownWidths()`：其余列立刻换算成 cm。所以 `1null + 2cm` 这样的
   复合元素**不是** null，整列按 2cm 固定（`null` 求值为 0，见
   `docs/notes/units.md`）。
3. `allocateRespected()`：`respect` 打开时，null 行/列由两轴的空闲尺寸共同
   决定（「一个 null 单位的宽 = 一个 null 单位的高」）。
4. `allocateRemainingWidth()` / `...Height()`：剩余空间 × `null_value` 权重 /
   `sumWeight`。

任务点名的三个 guard，对应实现里的三处分支：

| guard | 位置 | 行为 |
| --- | --- | --- |
| `sumWeight > 0` 才按比例分 | `allocateRemaining*` 的 `else` | 权重和是 0 → 所有 null 列/行归 0（`unit(0,"null")` 真实存在，直接除会炸） |
| respected 列从分母里排除 | `totalUnrespectedWidth()` | 分母只累加「纯 null 且不受 respect 约束」的权重 |
| 0 列 / 0 行不调用分配 | `_allocate()` 的循环 | 单位向量为空时循环体不执行，不做除零特判 |

另外两条不显眼但决定结果的分支：

- **`allocationRemaining()`** 的 guard 是 `initial == 0 → TRUE`：视口尺寸为 0
  时**分不分，取决于表里有没有固定部分**。纯 null 时初始余量就是 0，分出来仍是
  0；含固定部分时余量已经是负的，R 4.5.3 照样把它分给 null 列/行，于是出现
  **负的 null 宽高**——`2cm,1null` 在 `0×10` 视口里是 `2, -2`，ggcore 照抄。
  视口非 0 而固定部分超宽（`initial > 0, remaining < 0`）时 guard 取 FALSE，
  null 归 0，不会出现负值（`fixed-overflow-eats-null`）。
  版本事实：R-devel 已把这条 guard 改成 FALSE（零余量不再分配），真升级钉住的
  R 时 `zero-viewport-fixed-col` 会变成 `2, 0`；本仓库钉 R 4.5.3，按 4.5.3 的
  结果对齐。
- **没有 null 时**：单元格保持固定尺寸，多出来的空间**不是**分给单元格，而是由
  布局的 `just="centre"` 摊在四周（`subRegion()`）。10cm 视口里的 `2cm,3cm`
  两列就是 `2,3`，不是 `4,6`。

任务点名的三组，`10cm` 视口的实测值（`tests/fixtures/gtable_r_reference.json`）：

| 列宽单位 | R 实测（cm） | gg4py |
| --- | --- | --- |
| `0null, 0null` | `0, 0` | 权重和 0 → 两列 0，不除零 |
| `0null, 1null` | `0, 10` | 只有第二列有权重 |
| `1null+2cm, 1null` | `2, 8` | 混合元素按 2cm 固定，剩余 8cm 给真 null |

0 视口的那个怪癖单独钉住（`zero-viewport-fixed-col`）：`widths = 2cm,1null`、
`heights = 1null`、视口 `0×10` cm → 列 `2, -2`、行 `10`。纯 null 的 0 视口
（`zero-viewport`）是 `0, 0`，两者不矛盾——差别就在初始余量是不是 0。

### `respect` 的含义

gtable 的 `respect` 是**逻辑值**，`gtable_layout()` 原样传给
`grid.layout(respect=)`（`R/grid.R:20`）。逻辑 `TRUE` 在 grid 里等价于
respect 矩阵全真，即「每个 null 行/列都受约束」：一个 null 单位的宽等于一个
null 单位的高（单元格是正方形），能放多大取决于两轴里更紧的那一轴。

`10×10cm` 视口、`widths = 1null,1null`、`heights = 1null`：

- `respect = FALSE`：`5,5` 宽、`10` 高；
- `respect = TRUE`：`5,5` 宽、`5` 高——高度方向只剩 5cm，布局整体缩到
  `10 × 5`，垂直居中。

实现照 `allocateRespected()`：先比两轴宽高比决定 `denom` / `mult`，再按
「`weight / denom * mult`」分配，并把分到的尺寸从 `reducedWidthCM` /
`reducedHeightCM` 里扣掉，剩下的才进 `allocateRemaining*`。

## 位置：`subRegion()`

`region_box(t, l, b, r, width_cm=, height_cm=)` 返回 cm 单位的左下角坐标与
宽高，公式与 `layout.c` 的 `subRegion()` 一致（`hjust` / `vjust` 默认 0.5，
即 `just="centre"`）：

```
x = width*hjust - totalWidth*hjust + sum(widths[0:l-1])
y = height*vjust + (1-vjust)*totalHeight - sum(heights[0:b])
```

所以 span（`l:r` 或 `t:b`）的框就是跨过的行列之和——这正是 grid 给 span
grob 建的位置视口尺寸。`boxes()` 一次给出全部 layout 记录（含 span）的框。

## 嵌套：单元格尺寸沿轴传给子表

把子表放进单元格后，子表在自己**单元格视口**里解析：子表的 `npc` / `null`
参照单元格的宽高，而不是整张画布。这就是尺寸沿轴传播的口径——
`child.resolve(box.width_cm, box.height_cm)`，`box` 来自
`parent.region_box(...)`。

R 侧同样如此，参考值直接量出来：外层 `widths = 4cm, 1null`（10cm 视口）、
子表 `widths = 1null, 3null`，子表两列是 `1.5 / 4.5`cm，两行各 `5`cm。

**不做隐式的 `unit.pmax`**：R 的 gtable 也不会因为子表更大就撑开父表的行列，
ggplot2 是在组版时显式 `widths = unit.pmax(...)`。gg4py 保持同一口径——先
决定行列尺寸，再解析；需要「撑开」时由调用方用 `unit_pmax` 组合单位。

## z、clip、name 查询

- `z` 默认 `Inf`：新增 grob 排在现有 z 之上；显式 `-Inf` / `Inf` 按 R 的规则
  落到现有 z **区间之外**（`zmin - 1 ...` / `zmax + 1 ...`），不是整个表的
  最底/最顶。实测 `z = 5` 之后再加 `Inf` 得 6，再加 `-Inf` 得 **4**。
- `drawing_order()` 是稳定排序（R `makeContent.gtable()` 的 `order(z)`），
  同 z 保持添加顺序。
- `clip` 接受 `"on"` / `"off"` / `"inherit"` 或逻辑值（`True → "on"`）。前两个
  与 R 一致；`"inherit"` 只**照抄存储**：gtable 0.3.6 的 `gtable_add_grob()`
  文档列了这三个值（R 本身不校验），「继承父视口 clip」要等绘制期的视口栈，
  见下面 `vp` 决策点。取到 `"inherit"` 的渲染器应当取父视口的 clip，不能当成
  `"off"`。
- `placements(name)` / `grob(name)` 是 ggplot2 `g$layout[g$layout$name == "panel", ]`
  这类查询的对等物；`gtable_layout(x)` 给出等价于 `grid.layout()` 的
  `Layout` 对象（行数、列数、两个单位向量、respect）。

## `padding`

`gtable_add_padding(x, padding)` 四边各插一行/一列，顺序是 grid 的
`(top, right, bottom, left)`（`R/padding.R:29`）；长度不足 4 时按模回收。
`padding` 是普通单位向量，`pt` / `mm` / `null` 都可以：

- `unit(c(1,2,3,4),"mm")` 在 10cm 视口里得到行 `0.1, 9.6, 0.3`、列
  `0.4, 9.4, 0.2`；
- `unit(1,"null")` 的边距不占固定空间，和表内 null 一起按权重分（三等分）。

插行/插列的索引位移照 R：`pos = 0` 插到最前，`pos = -1` 追加到最后，其余
`pos = k` 表示插在第 k 行/列之后，`t > pos` 的 layout 记录整体 +n。

## 参考值怎么来

```bash
pixi run -e refs refs:gtable     # Rscript tools/refs/gtable_ref.R
```

gtable 自己不解析尺寸，R 也没有公开接口读回「算好的行高列宽」，所以参考值
用**设备测量**：把表画在 10×10cm 的 `pdf(NULL)` 上（页面尺寸 = 视口尺寸），
每个单元格先塞一个 `nullGrob()` 让位置视口存在，然后按视口路径读回

- 宽高：`convertWidth(unit(1,"npc"), "cm")` / `convertHeight(...)`；
- 左下角：`grid:::deviceLoc(unit(0,"npc"), unit(0,"npc")) * 2.54`（cm）。

嵌套表沿视口路径下钻（包装视口 → 子表 `$name` → 子表单元格），span 用额外
的 `nullGrob` 覆盖 `t:b / l:r` 区域直接量。

`tests/test_gtable_r_parity.py` 用 `1e-9` cm 的容差比（0.01 pt ≈ 3.5e-4 cm，
这里严了五个数量级），覆盖 22 组布局：纯 null、混合固定+null、不等权、
纯固定（居中）、单格、0 宽列、0 权重 null、respect（含固定部分）、
`lines`/`pt`/`mm`、padding 叠加（mm / pt / null 两两组合与三者混合）、嵌套
两层、嵌套 + span、插行插列的索引位移、0 尺寸视口（纯 null / 含固定列）、
固定部分超宽的视口。

另外做过一轮 40 组随机布局的对拍（随机单位种类与权重、随机视口尺寸，不入户
夹具）：单元格宽高与坐标全部落在同一容差内，唯一的差异是下面记的 NaN 那条。

## 刻意不复制 / 不支持

| 行为 | R | gg4py |
| --- | --- | --- |
| `respect` 且分母为 0（两轴 null 权重全 0，或只有一个 null 列且权重 0） | `0/0 = NaN`，grid 报 `non-finite location and/or size for viewport` | 该列/行给 0：0 权重本来就该拿 0 的份额 |
| 空表（0 列或 0 行） | 报错（`'x' and 'units' must have length > 0`） | 允许：0 列不调用宽度分配，`gtable_width()` 求值为 0 |
| `respect` 传矩阵（grid 的 `nrow × ncol` 逐格 respect） | `grid.layout()` 支持 | 只支持逻辑值——gtable 自己的 `respect` 就是逻辑值，矩阵属于直接调 grid.layout 的用法 |
| `clip = "inherit"` 的绘制语义 | 继承父视口的 clip | 只存值不解析（`GTable.layout` 里原样保留）；真正的继承要等 M0-6 的视口栈，在那之前渲染器必须取父视口的 clip，**不能**当 `"off"` |
| 越界单元格（`t` / `l` 超出表、`b < t`） | 不校验，画的时候才出错或静默不画 | 添加/取框时立即 `ValueError` |
| grob 必须是 grob 对象 | `stop_input_type()` | 任意对象都可以（M0-6 前没有 grob 类型） |
| `gtable_row` / `gtable_col` / `gtable_matrix`、`gtable_filter`、`gtable_trim`、`rbind` / `cbind`、`gtable_add_row_space` / `col_space` | 有 | 未实现，等 ggplot2 实际调用面需要时补 |

## 整页表：`plot_gtable()`

`ggcore.plot_gtable.plot_gtable(plot, metrics=None, width_in=7, height_in=7)` 是
上游 `ggplotGrob()` 的对等物：把 `plot_layout()` 已经算好的 cm 尺寸装进**一张
命名 gtable**，面板行 / 列留 `null`。它是多图合并（M3-1）真正要合并的东西——
`patchwork` / `cowplot` 合并的是 `ggplotGrob()` 的整页表，不是面板子表。

**单面板固定 16 行 × 13 列**（`tools/refs/plot_gtable_ref.R` 实测 ggplot2
4.0.3）。行列语义与 layout 名称：

| 行 | 内容 | 列 | 内容 |
| --- | --- | --- | --- |
| 1 | `plot.margin` 上 | 1 | `plot.margin` 左 |
| 2 | `tag`（`plot.tag.location = "margin"`） | 2 | `tag` |
| 3 | `title` | 3 | `guide-box-left` |
| 4 | `subtitle` | 4 | `legend.box.spacing` |
| 5 | `guide-box-top` | 5 | `ylab-l` |
| 6 | `legend.box.spacing` | 6 | `axis-l` |
| 7 | `xlab-t` | 7 | `panel` |
| 8 | `axis-t` | 8 | `axis-r` |
| 9 | `panel` | 9 | `ylab-r` |
| 10 | `axis-b` | 10 | `legend.box.spacing` |
| 11 | `xlab-b` | 11 | `guide-box-right` |
| 12 | `legend.box.spacing` | 12 | 空 |
| 13 | `guide-box-bottom` | 13 | `plot.margin` 右 |
| 14 | `caption` | | |
| 15 | 空 | | |
| 16 | `plot.margin` 下 | | |

两条容易踩的口径：

- **`legend.box.spacing` 不在 guide-box 里**。R 把它放在 guide-box 外侧的独立
  spacer 行 / 列：有右图例时列 10 = `11points`、列 11 才是 guide-box 的宽度。
  `plot_layout()` 的 `legend_box_spacing_cm` 就是这一项（SIL-999 新增字段）。
- **`plot.margin` 与 `tag` 分开**。`PlotLayout.margin_cm` 已把 tag 的尺寸折进
  margin（`table_add_tag()` 的做法），整页表用**原始** `plot.margin`（主题值），
  tag 单独占第 2 行 / 第 2 列，否则 tag 会被算两遍。`tag_width_cm` /
  `tag_height_cm` 是同一任务新增的字段。

分面时 R 把面板区**展开**成逐面板网格，规则按 `facet_wrap` / `facet_grid` 分开
（SIL-999 审计缺口 1 修的就是这条，早期版本只对「单一面板行 / 列」成立）：

- `facet_wrap`：**每个面板行**一组 `axis-t` + strip + `panel` + `axis-b`，组间才是
  `panel.spacing.y`；**每个面板列**一组 `axis-l` + `panel` + `axis-r`（right strip
  夹在 panel 与 axis-r 之间），组间是 `panel.spacing.x`。内轴不画标签：只有最左
  一条 `axis-l` / 最右一条 `axis-r` 有宽度，其余 `0cm`（R 实测：`axis-l-1-1` =
  0.3505cm、`axis-l-1-2` = 0cm）。
- **带高只看外边缘那一行**（`axes = "margins"`）：`axis-b` 只有**最后一个面板行**
  满高，内部带是字面量 `0cm`；`axis-t` 对称（只有第一行，默认是 0）。ragged
  （末行不满）时 R 的 `attach_axes()` 先 `bottom[-dim[1], ] <- zeroGrob()`，再由
  `measure_axes()` 把空洞相邻的带清零——**空洞只挪 grob、不给内部带高度**。早期
  版本按 `_axis_visible()`（每列最底面板）给带，ragged 的内部带会凭空多出
  0.4517cm；`dir = "v"` 与 `as.table = FALSE` 走同一条规则。
- **`axes = "all"` 的内侧带只看刻度**：`axis.labels = "margins"`（默认）时
  `censor_labels()` 删掉内面板的标签，内侧 `axis-b` / `axis-l` 只剩刻度
  （R 实测 **0.0967cm**），不能给“tick + label”的满高；`axis.labels = "all"`
  时内侧才与边缘同高（0.4718cm / 0.3505cm）。`axes = "margins"` 的内侧带仍是
  字面量 `0cm`。
- `facet_grid`：每侧**一条**轴 / strip（`seam_table()`）；轴跨整列 / 整行，不是
  每个面板各插一对。

六个 shape 的实测（R 4.5.3 / ggplot2 4.0.3，7×7in）：

| case | gg4py | R |
| --- | --- | --- |
| `facet_wrap(~g)` 1×2 | 17×17 | 17×17 |
| `facet_wrap(~g, ncol = 1)` 2×1 | 22×13 | 22×13 |
| `facet_wrap(~four)` 2×2 | 22×17 | 22×17 |
| `facet_grid(g ~ .)` 2×1 | 18×14 | 18×14 |
| `facet_grid(. ~ g)` 1×2 | 17×15 | 17×15 |
| `facet_grid(h ~ g)` 2×2 | 19×16 | 19×16 |
| `facet_wrap(~five, ncol = 3)` 2×3 ragged | 22×21 | 22×21 |
| `facet_wrap(~five, ncol = 2)` 3×2 ragged | 27×17 | 27×17 |
| `facet_wrap(~five, ncol = 2, dir = "v")` | 27×17 | 27×17 |

命名照 R 的实测顺序，注意 **panel 与 axis 的行列顺序相反**；多行 / 多列时每个
layout 名必须**唯一**——`GTable.grob(name)` / `placements(name)` 取第一个匹配，
重名会让组合层静默拿到错格（早期 `facet_grid` 多列就踩了这个坑）：

- `panel-{col}-{row}`（`facet_wrap` 两列：`panel-1-1` / `panel-2-1`）；
- `facet_wrap` 的轴每面板一组：`axis-l-{row}-{col}` / `axis-r-{row}-{col}`、
  `axis-t-{col}-{row}` / `axis-b-{col}-{row}`；
- `facet_grid` 的轴每侧一条，名字带**另一维**的编号：`axis-l-{row}` /
  `axis-r-{row}`、`axis-t-{col}` / `axis-b-{col}`。

`plot.title.position = "plot"` / `plot.caption.position = "plot"` 时 R 的
title / caption 跨 `guide-box-left .. guide-box-right` 的列范围（13 列的表里是
3..11，实测），不是整张表；`legend.location = "plot"` 不改变这一点。

**单位与 `metrics`**：panel 行列是 `null`，其余固定尺寸来自 `plot_layout()` 的
cm；**文字行 / 列**保留成文字度量单位，而不是用占位度量算成 cm：

- 轴标题行 / 列（xlab-t / xlab-b / ylab-l / ylab-r）与 title / subtitle /
  caption 是 `strheight`（R 里是 `1grobheight`；表按 `UnitContext(fontsize=12)`
  定义，`amount` 用构建时的 `metrics` 校准到目标 cm）；
- 图例盒宽度是 `cm 固定部分 + strwidth(最宽标签)`（R 的 guide-box 是嵌套
  gtable，宽度里含标签的 `stringWidth`）。

于是 `UnitContext` 没有 `metrics` 时 `resolve()` 一律走 `units` 的 `UnitError`
路径（不静默 0，也不回退到占位度量算出一个看起来正常的表）；`tests/
test_plot_gtable.py::test_without_metrics_resolve_raises_unit_error` 钉住普通图，
`::test_legend_width_keeps_strwidth_and_needs_metrics` 钉住图例的 `strwidth`。
构建与解析必须用**同一个** `metrics`：`strheight` / `strwidth` 的 amount 是按
构建时度量校准的。

**逐条记录的 cm 对拍**：`tools/refs/plot_gtable_ref.R` 除了 `widths` / `heights`
的 `as.character()`，还会把表画在 7×7in 视口里、用
`downViewport("<name>.<t>-<r>-<b>-<l>")` 读回**每条 layout 记录**的宽高（`1null`
行列因此拿到分配后的真实 cm，而不是 `convertWidth()` 对 null 给的 0）。
`tests/test_plot_gtable_r_parity.py::test_resolved_records_match_r` 逐条比较，
容差按「记录是否落在 **null 行**」拆开：

| 分组 | 最大残差（实测） | 容差 |
| --- | --- | --- |
| null 行（`1null`） | **0.1013cm**（`titled` 的 `panel` / `axis-l` / `ylab-l` / `guide-box-*`） | 0.105cm |
| null 列 / 固定行 / 固定列 | 0.0409 / 0.0201 / 0.0201cm | 0.05cm（项目既有口径） |

null 行的残差来自**文字行高**：R 的文字行比我们高，实测（R 行高减该元素的
margin，按设备 72.27 折 pt）：

| 行 | 字号 | R 文字高 | 我们 | Δ |
| --- | --- | --- | --- | --- |
| `title` | 13.2pt | 12.24pt | 11.85pt | −0.39pt（0.0136cm） |
| `subtitle` | 11pt | 10.36pt | 9.88pt | −0.48pt（0.0169cm） |
| `xlab-b` | 11pt | 10.36pt | 9.88pt | −0.48pt（0.0169cm） |
| `caption` | 8.8pt | 8.47pt | 7.90pt | −0.57pt（0.0201cm） |
| `axis-b` 标签 | 8.8pt | 8.47pt | 7.90pt | −0.57pt（0.0201cm） |

三点落在一条直线 `文字高 ≈ 0.856·size + 0.94pt` 上，而我们用的是纯比例
（`text_line_cm` 的 0.8945em）——**字号越小亏得越多**。这些负差被高度守恒推进
null 面板行，`titled` 合计 **0.1012cm**（tag 0.0136 + title 0.0136 +
subtitle 0.0169 + xlab-b 0.0169 + caption 0.0201 + axis-b 0.0201）。
所以别把非 null 记录的容差一起放宽：固定行 / 列实测只差 0.0201cm，0.05cm 足够
抓住 1mm 级的真实结构错。要收掉这 0.02cm 得让 gtable 的文字行按上面那条直线
算，是独立改动；**不要**顺手改 `TEXT_LINE_EM`（会动 532 份 `expected.svg`）。

`coord_fixed(ratio = 2)` 的整页表是 `respect = TRUE` + 面板行 `2null` / 面板列
`1null`（与 R 的 `g$respect` 和 heights 实测一致），比例来自
`FacetTable.height_weights` / `width_weights`。

**表里放的是语义槽位，不是渲染 grob**：`PanelSlot`（面板号 + 在 `FacetTable`
里的 t/l/b/r）、`StripSlot`（一条 strip）、`PlotCell`（background / 轴 / 标题 /
guide-box / spacer，带主题元素或 `LegendBoxLayout`）。组合层按名字取行列与尺寸
即可；单图渲染仍走 `scene_from_build()` 的 `PlotLayout` 绝对 cm 路径（非范围
包括「改变单图输出外观」）。参考值：

```bash
pixi run -e refs refs:plot-gtable
pytest -q tests/test_plot_gtable.py tests/test_plot_gtable_r_parity.py
```

**已知差异 / 首期不做**：

- **`facet_grid` 的 `axes =` 非默认值不复刻**（`axes = "all" / "all_x" /
  "all_y"`，`axis.labels =` 同理）：R 会给每条内面板行 / 列各插一条轴带
  （`axes = "all"` 是 21×18、`all_x` 21×16、`all_y` 19×18，2×2 的
  `facet_grid(h ~ g)`），`plot_gtable()` 仍按 `axes = "margins"` 的 **19×16**
  建表——`_seam_*` 每侧只建一条，`axes =` 参数在本路径被忽略；
  `tests/test_plot_gtable.py::test_grid_non_default_axes_is_a_registered_gap`
  钉住当前形状，防止以后误以为已对拍。`axis_row_size()` / `axis_col_size()` 的
  「内侧只留刻度」只服务 `facet_wrap`。
- `scales = "free"` 的逐面板轴尺寸统一用全局 max（父任务首期要求单 panel 或
  `scales = "fixed"`）；
- `strip.placement = "outside"` 仍按 inside 的槽放进表里；
- stretchy legend key（`unit(1, "null")`）按参考画布把拉伸量落成 cm；
- `plot.tag.location = "plot"` / `"panel"` 的数值位置只记录覆盖区域，x/y（npc）
  不属于 gtable 几何。

## 与后续模块的接口

- **M0-4 viewport / M0-6 grob 渲染**：`boxes()` 给的是 cm 坐标；渲染时按
  `drawing_order()` 画，span 直接用框的宽高。视口命名沿用 R 的约定——
  单元格包装视口叫 `<placement name>.<t>-<r>-<b>-<l>`，子表的布局视口叫
  子表的 `name`——参考脚本正是靠这个约定量到嵌套表的单元格。
- **ggplot2 移植**：panel / axis / legend 组版时用 `unit_pmax` 组合各表的
  `widths` / `heights`，再调 `resolve()`；需要栅格位置时用 `region_box()`。
- **`strwidth` / `strheight` 单位**：`resolve(ctx=UnitContext(metrics=...))`
  透传度量提供者；不传 `metrics` 时带 `strwidth` 的表会报 `UnitError`
  （与 `units` 一致，不静默给 0）。

## `vp`：M0-6 的决策点

R 的 gtable 本身是个 grob，带 `vp` 字段（`gtable(vp = viewport(...))` / `x$vp`），
用来表达「这张表画在哪个视口里」——带 `clip` / `gp` / `angle` 的真实 viewport
可以挂在子表上，绘制时再包一层。gg4py 的 `GTable` 没有这个字段。

纯尺寸解析不需要它：`resolve(width_cm, height_cm, ctx=UnitContext(...))` 把视口
尺寸和度量显式传进来就够（嵌套走的就是这条路，见「嵌套」）。表达不了的是
**带 clip / gp / angle 的视口栈**——子表要按自己的 clip/gp 绘制、或者整体按
`angle` 旋转时，没有地方挂。

M0-6 需要在这里做决定：

- **只做几何**（行列尺寸、`region_box()`、`drawing_order()`）→ 可以不管 `vp`，
  调用方继续显式传尺寸；
- **要做 viewport 栈**（绘制期包视口、`clip="inherit"` 的继承、`gp` 传递、
  `angle` 旋转）→ 必须补 `GTable.vp` 或等价的绘制上下文参数，并让渲染器在
  按 `<placement name>.<t>-<r>-<b>-<l>` 建单元格包装视口时把它带上。

在那之前 `clip="inherit"` 只存值不解析（见「刻意不复制」表）。

**M0-6 的结论（已落地）**：选第二条，但把视口栈放在 grob 侧而不是 `GTable` 上——
`GTable` 保持纯几何，绘制期用 `ggcore.grobs.g_table_grob(table, vp=..., gp=...)`
包一层。它按 `drawing_order()` 为每条 layout 记录 push 单元格视口
`<placement name>.<t>-<r>-<b>-<l>`（尺寸用 `region_box()` 的 cm、`just = ("left",
"bottom")`），并把 `Placement.clip` 原样变成该视口的 `clip`：因此 `"inherit"` 在
绘制期取的是父视口的裁剪框，**不是** `"off"`。嵌套表没有单独的“布局视口”
（`region_box` 已含居中偏移），路径名比 R 少一段。实现与用例见
`docs/notes/grobs.md` §9 与
`tests/test_grobs.py::test_gtable_cells_get_their_own_viewports_in_drawing_order`。
