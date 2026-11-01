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
