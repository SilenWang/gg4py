# grob 账本（grob 模型与场景遍历）

`ggcore.grobs` 是 R **grid** grob 系统的 Python 对等物：18 个构造器（13 种可绘制
原语 + `clipPath` + `nullGrob` + `zeroGrob` + `gTree` + `gtable` 的 grob 视图，
§1），以及把 grob 树摊平成绘制指令、再写成 IR 的场景遍历。它是 M0-6 的交付物，
上游是 `src/library/grid/src/grobs.c` / `grob-*.c`、`R/grid.R`（`gTree`、
`drawDetails`、`preDraw.gTree`）与 `R/gpar.R`（`set.gpar`）。

- 代码：`src/ggcore/grobs.py`
- 用例：`tests/test_grobs.py`（构造 / 遍历 / 契约）、`tests/test_grob_cases.py`
  （16 张快照）
- 快照：`docs/cases/grob-*/`，`pixi run cases:grob` 重生成
- 下游：IR（`docs/notes/ir.md` 的 18 种节点）与 M0-8 的 Device

## 1. 名单与计数：三个数，一个口径

先给三个**互不替代**的数（`SIL-634` 把之前漂着的「15 / 14 种」钉死在这里）：

| 数 | 是什么 | 名单 |
| --- | --- | --- |
| **18** | grob **构造器** | 13 种可绘制原语 + `clipPath` + `nullGrob` + `zeroGrob` + `gTree` + `gtable` 的 grob 视图 |
| **18** | **IR 节点种类** | 3 个容器（`viewport` / `gtree` / `clip`）+ 15 个叶子 kind（13 种原语 + `null` + `zero`） |
| **14** | `Scene.to_ir_scene()` **实际产出** | 13 种可绘制原语 + `viewport` |

三个数的共同部分是 **13 种可绘制原语**（表格里 IR 列为真实 kind 的那些行）。
**`null` / `zero` / `gtree` / `clip` 不会从 grob 路径进 IR，是有意为之**：

- `nullGrob` / `zeroGrob` 的区别只在**布局**（≤ 0 尺寸、参与 `unit_max`），而布局
  在写 IR 之前就消费完了——IR 是给设备画图用的，没有布局阶段；
- `gTree` / `clipPath` 是**遍历期的容器**，摊平后各自的语义已经落到子节点上
  （顺序与 `Instructions` 一致、裁剪折成 `clip` 矩形），再写一个空容器只会让
  设备多走一层；
- IR 仍保留这四种 kind（`NODE_SPECS` 里有），因为 IR 是独立格式：别的写方
  （例如以后直接把 gtable 的布局结果写成 `gtree`）可能需要它们。

| grob 构造器 | 类 | IR `NodeKind` | 说明 |
| --- | --- | --- | --- |
| `rect_grob` | `RectGrob` | `rect` | `just` / `hjust` / `vjust` |
| `circle_grob` | `CircleGrob` | `circle` | 椭圆由视口变换表达 |
| `lines_grob` | `LinesGrob` | `lines` | 单笔折线 |
| `segments_grob` | `SegmentsGrob` | `segments` | 互不相连 |
| `polyline_grob` | `PolylineGrob` | `polyline` | `id` 分组 |
| `polygon_grob` | `PolygonGrob` | `polygon` | `id` 分组，闭合 |
| `path_grob` | `PathGrob` | `path` | `id` + 填充规则 |
| `points_grob` | `PointsGrob` | `points` | `pch` / `size` |
| `text_grob` | `TextGrob` | `text` | 需要度量提供者 |
| `raster_grob` | `RasterGrob` | `raster` | 像素进 blob 表 |
| `xspline_grob` | `XSplineGrob` | `xspline` | `shape` / `open` |
| `bezier_grob` | `BezierGrob` | `bezier` | 每 4 个控制点一段 |
| `curve_grob` | `CurveGrob` | `curve` | 两端点 + 弯曲参数 |
| `clip_path` | `ClipPathGrob` | —（容器） | 矩形裁剪，子节点原样摊开 |
| `null_grob` | `NullGrob` | —（`null`） | 不画、不占位 |
| `zero_grob` | `ZeroGrob` | —（`zero`） | 不画，参与布局 |
| `g_tree` | `GTreeGrob` | —（容器） | 子节点 + `childrenvp` + gp |
| `g_table_grob` | `GTableGrob` | —（容器） | gtable 当 grob 画，建单元格视口 |

节点表本身见 `docs/notes/ir.md` §4。

## 2. `UNSET` / `None` / `NA`：三个都不能混

`gpar()` 的字段有四种取值，语义各不相同（这是审核钉死的接口约束之一）：

| 取值 | 含义 | 解析后 | 写 IR |
| --- | --- | --- | --- |
| `UNSET`（缺省） | 没写，继承父值 | 父值 | 不出现继承 |
| `None` | 显式清空 | 回到 grid 缺省（`GPAR_DEFAULTS`） | 按缺省值折 |
| `NA` | 透明 / 不画（R 的 `NA`） | 原样保留 `NA` | 折成“不描边 / 不填充” |
| 具体值 | 覆盖（`cex`/`alpha`/`lex` 相乘） | 覆盖值 | 折成 8 位 RGBA |

哨兵是 `ggcore.viewport.NA`（单例，`is` 判定；`bool(NA)` 直接抛错，防止被当
`False` 用）。`Gpar.fill` / `Gpar.col` / `Gpar.lty` 收 `NA`；其它字段不受影响。

**为什么不能拿 `None` 兼职 `NA`**：`col = None` 清空后会回落到缺省 `"black"`，
画出来是黑的；`col = NA` 是不画。混用会让“透明”静默变成“继承缺省色”。

到 IR 这一层两者**都**折成 `None`（不画）——IR 的 `gpar.col = null` 就是“不描边”，
没有第三态。判断“到底是 NA 还是清空回缺省”看 `Instruction.resolved`（解析后的
gpar 原值），这也是快照之外的断言口径：

```python
transparent = scene(rect_grob(gp=gpar(col=NA)), tree).instructions[0]
assert transparent.resolved.col is NA  # 解析后仍是 NA
assert transparent.gpar.col is None  # 写 IR 时不画
cleared = scene(rect_grob(gp=gpar(col=None)), tree).instructions[0]
assert cleared.resolved.col == "black"  # 清空 → 缺省色
```

## 3. gpar 的继承与临时 gpar（`gTree` 路径）

遍历时每个 grob 的 gp 都是**增量**，叠在“当前 gpar”上（`ViewportTree.temporary_gpar`
= R `set.gpar()`）。当前 gpar 是这条链的结果：

```
视口 gpar → gTree 的 gp（逐层）→ 再往上 wrap 的 gTree…… → 本 grob 的 gp
```

由此有三条不显眼但决定结果的规则：

1. **几何换算用的是这份合成后的 gpar**，不是视口自己的。`width = unit(2, "lines")`
   在一个 `gp = gpar(fontsize = 20)` 的 rect 里是 48pt，用视口的 ps=12 会得 28.8pt。
2. **`childrenvp` 在临时 gpar 下 push**（R `preDraw.gTree()` 先 `pushvpgp` 再
   `pushViewport(childrenvp)`），所以子视口里的 `lines` / `char` 单位按 gTree 的
   gp 换算。这就是 SIL-624 修的那条路径，`tests/test_grobs.py::test_childrenvp_geometry_uses_the_g_tree_gpar`
   钉住 48pt。
3. **退出时先 pop 回 gTree 层、再恢复 gpar**（`temporary_gpar()` 的顺序），
   否则会出现“当前视口与 gpar 短暂不一致”的状态。遍历结束视口树与 gpar 都回到
   进来时的样子（`::test_traversal_leaves_the_viewport_tree_untouched`）。
4. **`widthDetails()` / `heightDetails()` 用同一条链**（SIL-634）：量的不是图纸，
   而是“这份 gp 下会画多大”。`width_details(grob, node)` 从 `node.gpar` 起叠
   本 grob 与外层 `gTree` / `clipPath` 的 `gp`，再把 `lines` / `char` /
   `strwidth` / `npc` 这些要上下文的单位折成绝对 pt；所以
   `gTree(gp = gpar(fontsize = 20))` 里的 `rect_grob(width = unit(2, "lines"))`
   量出 48pt（1.693 cm），不是视口 ps=12 的 28.8pt（1.016 cm）。
   `text_grob` 的子节点同理：宽度按**合并后**的 `fontsize * cex` 问度量提供者，
   高度是合并后的 `fontsize * cex * lineheight`。
   （`width_details` / `height_details` 的返回值已经没有上下文依赖，
   下游用任何 `UnitContext` 求值都是同一个数。）

`cex` / `alpha` / `lex` 与父值**相乘**（R `set.gpar()`），所以视口 `cex = 2` 加
gTree `cex = 0.5` 得 1.0，不是 0.5。

## 4. 向量 gp：不扩 `Gpar`，按元素摊开

R 的 `pointsGrob(x, y, gp = gpar(col = c("red", "blue", ...)))` 是逐点颜色。
`Gpar` 只收标量（M0-4 的约束），所以**向量写法由 grob 构造器吸收**：

```python
points_grob([0.1, 0.2, 0.3, 0.4], [0.5] * 4, gp={"col": ["#ff0000", "#ff0000", "#0000ff", NA]})
```

- 构造时 `gp` 收 `Gpar` 或**映射**；映射里的列表按 R 的按模回收摊成逐元素增量
  （长度必须能回收到元素数，否则报错——宁可报错也不静默错位）；
- 遍历时把**连续同值**的元素合成一个 IR 节点：上面这串得 3 个节点（2 红 + 1 蓝 +
  1 个 NA 不画），顺序与 R 一致（`::test_vector_gp_expands_into_one_node_per_run_of_equal_values`）。

**路径型原语不收向量 gp**：`lines` / `polyline` / `polygon` / `path` / `xspline` /
`bezier` / `curve` 的一条子路径是一个 IR 节点，切 gp 就得复制接缝顶点，IR v0 表达
不了。传向量会报 `GrobError`（`::test_vector_gp_on_path_like_grobs_is_refused`）。
ggplot2 的 `geom_path` 是按组传标量 gp 的，碰不到这条。

`points.size` 同理是单值（IR 的 `points.size` 是一个参数），逐点尺寸会报错。

## 5. 颜色与线型：`col2rgb` 口径

- 颜色收 `#RGB` / `#RRGGBB` / `#RRGGBBAA`、R 颜色名、`(r, g, b[, a])` 元组；
  `"transparent"` 与 `NA` 都折成“不画”。
- 具名颜色只收录常用的一百多个（`docs/notes/grobs.md` 引用 `_NAMED_COLOURS`），
  不认识的**直接报错**——不猜。`grey<k>` / `gray<k>` 按 `round(255 * k / 100)`
  生成（`grey50` = 128、`grey92` = 235）。
  **与 R 的差异**：R 的 `colors()` 是 657 项的表，其中 `grey0..grey100` 的半值
  舍入在个别 k 上与上式差 1 个灰阶（R 用的不是 `round`）；ggplot2 实际用到的
  `grey92` / `grey30` / `grey20` 都对得上。完整表与精确舍入留给颜色模块。
- `lty` 收 R 的三类写法：样式名（`"solid"`…）、编号 `0..6`、十六进制串（`"44"`）、
  显式段长序列。**段长单位是 lwd**，写 IR 前乘 `lwd` 折成 pt（`docs/notes/ir.md`
  的 `lty` 是“已按 lwd 折算好的 pt 段长”）；`lty = "blank"` / `NA` / 编号 0 折成
  “不描边”（`col = None`），因为 IR 的 gpar 没有“有颜色但不画线”这一态。

## 6. `clip` 的消解：一条指令一个页面矩形

裁剪在遍历期消解完，设备不再看视口：

| 来源 | 结果 |
| --- | --- |
| 视口 `clip = "on"` | 本视口 `0..1 npc` 的设备外包框（旋转不是 0/90/270/360 时退化成继承，见 `docs/notes/viewport.md` §4） |
| 视口 `clip = "off"` | 整个设备略微放宽（`-0.5..1.5` 倍） |
| 视口 `clip = "inherit"` | 父视口记录的裁剪框（`VpNode.clip_rect` 已经算完） |
| `clip_path(...)` | 自己的矩形与当前裁剪框**求交** |
| gtable 单元格 | `Placement.clip` 原样变成单元格视口的 `clip`：`on` 裁到格子、`inherit` 取父视口、`off` 放到设备框 |

统一翻成**页面绝对坐标 pt、y 向下**（`VpNode.ir_clip_rect()` 同一口径），写进
`Instruction.clip`。`VpNode.clip_rect` 是设备英寸、y 向上、未规范化，翻页面的
责任在这一层，设备只认页面 pt。

**`clip="inherit"` 不能当 `off`**（`docs/notes/gtable.md` 的约束）：单元格的
`inherit` 映射成 `Clip.INHERIT`，由视口算成父框；`::test_gtable_cells_get_their_own_viewports_in_drawing_order`
用“右格的 clip 等于根视口的 clip”把这条钉住。

`clip_path` 只做**矩形**：扁平指令的裁剪只有一个轴对齐矩形，多边形裁剪得用 IR 的
`clip` 节点（那条路留给需要的时候再走）。旋转视口里的矩形裁剪按外包框退化并报
`RotatedClipWarning`（与 R 对旋转裁剪的退化一致）。

## 7. 指令口径：局部坐标 + 一个页面仿射

一条 `Instruction` 是设备需要的全部：

| 字段 | 口径 |
| --- | --- |
| `kind` | IR 节点种类 |
| `bufs` | 局部坐标（本视口 pt、**y 向下**、原点视口左上）的 **float64** 缓冲 |
| `transform` | 局部坐标 → **页面坐标**（pt、y 向下、原点页面左上）的 2×3 仿射，父视口链已乘完（**含视口旋转**） |
| `clip` | 页面绝对坐标的裁剪矩形，**必填** |
| `gpar` | 折好的 IR gpar（RGBA / pt 段长 / alpha） |
| `resolved` | 解析后的 gpar 原值（`NA` vs `None` 在这里还分得清） |
| `params` / `texts` | IR 的参数与文本 |
| `vp` / `source` | 当前视口路径 / grob 名字（诊断与断言用） |

为什么不是“几何直接写页面坐标”：旋转视口里的 `rect` / `circle` / `text` 一旦
被压成页面坐标就会被绑死成多边形或多边形近似。一个仿射既保留原语语义，又让设备
不需要走视口树——正好是 IR `viewport.transform` 的扁平版。

### 7.1 `text` 的 `angle` 是**局部**旋转（SIL-634 的阻塞）

`params["angle"]` 只放 grob 的 `rot`，**不含视口旋转**：视口旋转已经在
`transform` 的线性部分里。设备按「先 `transform`，再绕锚点转 `angle`」合成：

```
页面方向 = transform 的旋转 ∘ rot
```

- 视口 `angle = 20` + `rot = 0` → 画成 **20°**；
- 无旋转视口 + `rot = 40` → 画成 **40°**；
- 视口 `angle = 20` + `rot = 20` → 画成 **40°**（两段各算一次）。

修之前 `angle` 是 `viewport.rotation + grob.rot`，视口旋转被算了两次：上面第一行
画成了 40°（与第二行像素一致），`docs/cases/grob-text` 的基线也跟着错。
现在由 `::test_text_angle_is_the_local_rotation_only`（断言 `params["angle"] == rot`
与 `transform` 的旋转）与两张快照 `grob-text` / `grob-text-rot` 一起钉住——
`::test_viewport_rotation_and_rot_are_not_applied_twice` 还直接比像素：
「视口 20° + `rot = 0`」与「无旋转视口 + `rot = 20`」必须是同一张图。

### 7.2 设备输入是 IR，不是 `Scene`（float64 的那一份）

`Instruction.bufs` 是 float64，IR 的缓冲是 float32；`Scene` 到 `to_ir_scene()`
时**一次性**舍入（`:meth:`Instruction.to_node`，round-trip 逐位相同）。为了让
「设备会不会多背一份 float64 几何」有明确答案，这里定死：

> **设备只吃 `ir.Scene`。** `ggcore.grobs.Scene` 是遍历期的中间形态，不进设备
> 接口；要出图就 `scene(...).to_ir_scene()`，别一边拿着 `Scene` 一边再建一份 IR。

临时 skia 设备（`tools/cases/grob_cases.py`）就是照这条实现的，所以 grob 快照
现在连「写 IR」这一步一起兜住；M0-8 的 raster 设备直接接手同一份 `ir.Scene`。

`to_ir_scene()` 同时是**单位口径的收口**：R 的 `gpar$lwd` 是 1/96 inch，IR 的
`gpar.lwd` 是 pt，所以写 IR 时按 `72/96 = 0.75` 折算，`lty` 的段长（`lwd` 的
倍数）跟着一起折（`ggcore.grobs._LWD_UNITS_TO_PT`，SIL-636）；其余几何字段在
遍历期就已经是 pt 了。

### 7.3 `clip` 没有“空值”：零面积就是裁掉一切

`Instruction.clip` 是**必填**字段（没有 `(0, 0, 0, 0)` 这种占位默认值）。设备只按
它裁，**不要**把零面积理解成 `inherit` / “不裁剪”：那两种语义在遍历期就已经
消解成具体矩形了（§6），到指令这一层只剩数值。写 IR 时它也是
`viewport.clip_rect`（`clip=true` 必填，见 `docs/notes/ir.md` §4）——同样不存在
“猜一个单位框”的默认。

于是 `Scene.to_ir_scene()` 只是一次重排：根视口（`identity` + 页面裁剪框）下按
**连续的 (transform, clip) 相同**合并出 `viewport` 节点，每个节点带自己的
`clip_rect`（页面坐标，`docs/notes/ir.md` §4）。`::test_scene_converts_to_an_ir_scene_that_round_trips`
把 13 种可绘制原语一次性编码 / 解码，加上 `viewport` 共 14 种 kind，
顺带证明它们都在 IR 的节点表里。

## 8. 布局：`widthDetails` / `heightDetails`

`width_details(grob, node)` / `height_details(grob, node)` 是 R 的同名泛型。单位按
**继承后的 gp**（§3 第 4 条）折算，返回值已经没有上下文依赖：

| grob | 宽 / 高 |
| --- | --- |
| `rect` / `raster` | 自己的 `width` / `height` 单位（按继承后的 gp 折成 pt） |
| `circle` | `2 * r` |
| `points` | `size`（缺省 `unit(1, "char")`，随 gp 字号变化） |
| `text` | 度量给的宽度（英寸，字号取继承后的 `fontsize * cex`）/ `fontsize * cex * lineheight` |
| 路径型 / 曲线型 | 控制点外包框 |
| `null` / `zero` | `unit(0, "cm")` |
| `gTree` / `clipPath` | 子节点的 `unit_max`（自己的 gp 先叠上再往下传） |
| gtable grob | 表的总宽 / 总高（按继承后的 gp 折算） |

**`zeroGrob` 参与布局但不产出指令**：它的宽高都是 0，放回 gtable 里不占空间，
但它是合法子节点、能进 `gTree` 的 `unit_max`。`::test_zero_and_null_grobs_have_zero_size_and_no_instructions`
与 `::test_zero_grob_participates_in_a_g_tree_extent` 一起钉住“布局看得到、遍历画不出”。

`points.size` 的缺省单位照 R 是 `unit(1, "char")`（与字号联动），要绝对尺寸就显式给
`size_units="bigpts"`。

**gp 继承的回归**：`::test_width_details_follows_the_inherited_gp`（48pt / 115.2pt）、
`::test_text_extent_follows_the_inherited_gp`（子节点 `gp.fontsize = 20` 送达度量
提供者）、`::test_points_extent_in_char_units_follows_the_inherited_gp`
（`char` 从 12pt 变 20pt）。

## 9. gtable 的 `vp` 决策点：`g_table_grob`

`docs/notes/gtable.md` 把“gtable 要不要带 `vp`”留给 M0-6。结论是：

- **`GTable` 保持纯几何**（行列尺寸、`region_box`、`drawing_order`），不加 `vp`
  字段——它不该知道视口栈；
- **绘制期的那层放在 grob 侧**：`g_table_grob(table, vp=..., gp=...)` 在遍历时解析
  行列尺寸，为每条 layout 记录 push 一个单元格视口
  `<placement name>.<t>-<r>-<b>-<l>`（`x`/`y`/`width`/`height` 用 cm、`just = ("left", "bottom")`），
  在它里面画对应的 grob（子表递归）。
- `Placement.clip` 直接变成单元格视口的 `clip`，`"inherit"` 因此在绘制期取父视口的
  裁剪框（就是上面 §6 说的那条约束的落点）。
- **嵌套表没有单独的“布局视口”**：单元格视口的尺寸就是子表的解析尺寸，`region_box`
  已经把 `just = "centre"` 的居中偏移算进去了。所以 R 里的路径
  `外层格::子表名::子表格` 在 gg4py 里是 `外层格::子表格`（少一层）——量尺寸不依赖
  这一层，只是路径名少一段。

## 10. 快照：16 张，和一台临时设备

`docs/cases/grob-<name>/case.json` + `baseline/<case>.png`，`pixi run cases:grob`
重生成、`--check` 只比对。链路与正式渲染**一致到 IR 为止**：

```
case.json → grob 树 → scene()（场景遍历）→ Scene（float64）→ to_ir_scene()（float32）
          → 临时 skia 设备（只吃 ir.Scene）→ PNG
```

也就是说快照验证的是遍历结果**加写 IR 这一步**（坐标、gpar、裁剪、顺序、节点分组）
加设备本身，不是另一套几何计算。画图的是 M0-8 的
`ggskia.SkiaRasterDevice`（`docs/notes/device.md`），输入同一份 `ir.Scene`（§7.2），
所以快照同时也是设备的回归资产：16 张 `pixi run cases:grob --check` 全绿。

临时设备在 M0-8 落地时退休，它当初的几处近似如下（现在都有真实现）：

| 原语 | 临时设备（M0-6） | M0-8 |
| --- | --- | --- |
| `xspline` | `shape = 0` 用 Catmull-Rom；`shape ≠ 0` 退化成折线 | R `xspline.c` 的移植（`ggskia.curves`） |
| `bezier` | 每 4 个控制点 `cubicTo` 一段 | 同左（本来就是 IR 的语义） |
| `curve` | 两端点 + 直角拐点的二次曲线 | `grid::curveGrob` 的移植（控制点 + xspline） |
| `points.pch` | 半径 `size / 2`，只实现一个子集 | `engine.c::GESymbol()` 的全表，半径 `0.375 * size` |
| `text` | 一律 Noto Sans CJK SC 单一字面 | 字体栈 + run 切分 + 轮廓（矢量后端） |

`grob-points` / `grob-xspline` / `grob-curve` 三张基线随真实现重录（前者的符号
直径、后两者的曲线形状都变了），其余 13 张逐字节不变——尤其是 `grob-text` /
`grob-text-rot`，它们钉的是 §7.1 的旋转合成，不该受设备换代影响。

**解码 PNG 的坑**（写快照工具时踩到的，留个记号）：`skia.Image.MakeFromEncoded`
是懒解码，它引用的是那份 `bytes`；字节对象先死掉再 `toarray()` 会安静地读出一片
0。所以 `decode()` 必须让 bytes 与 image 在拷贝时都活着（见 `grob_cases.decode`）。

案例清单（16 张）：13 种可绘制原语各一张——`rect` / `circle` / `lines` /
`segments` / `polyline` / `polygon` / `path` / `points` / `text` / `raster` /
`xspline` / `bezier` / `curve`——加 `clip`（`clipPath`）、`null`
（`nullGrob` + `zeroGrob` + gtable + `gTree + childrenvp`），以及 `text-rot`
（文本旋转合成，§7.1 的 A / A' / B）。`tests/test_grob_cases.py` 的
`EXPECTED_KINDS` 把名单钉死：加原语必须加案例。

## 11. 刻意不复制 / 不支持

| 行为 | R grid | gg4py |
| --- | --- | --- |
| 箭头（`arrow`） | `linesGrob(arrow = arrow())` | 未实现（`docs/notes/ir.md` §12 已记为 minor） |
| `clip = grob` / mask / `grid.clipPath` 的任意形状 | 支持 | `clip_path` 只做矩形；多边形裁剪留给 IR 的 `clip` 节点 |
| 向量 gp 逐顶点上色 | `polylineGrob` 支持 | 路径型原语只收标量 gp（§4） |
| `pch` 的完整符号表 / `fontface` 字符串 | `validGP()` 折 `fontface`，设备解 `pch` | `font` 整数 → `<family>:<bold\|italic>` key（M0-7 换真 key）；`pch` 由设备解 |
| `check.overlap` / `text` 的断行 | `grid.text` 支持 | 未实现 |
| `grobWidth` / `grobHeight` 的完整泛型 | 全部 grob 类 | 只实现本模块的 18 个构造器（§8） |
| 全部 657 个 R 颜色名 | `colors()` | 常用子集 + hex + 灰阶（§5），其余报错 |
| `grey<k>` 的精确舍入 | `colors()` 表 | `round(255k/100)`，个别 k 差 1 灰阶（§5） |

## 12. 与后续模块的接口

- **M0-7 度量**：`text` 的宽度只能来自度量提供者（`ViewportTree(metrics=...)`，
  `ggcore.units.Metrics` 协议，返回英寸）；没有就报错不猜。`font` key 现在是
  `fontfamily` + `font` 折出来的，M0-7 的字体目录接管后换成真实 key。
- **M0-8 设备**：只认 `ir.Scene`（`scene(...).to_ir_scene()` 的产物，§7.2）：
  逐层合成 `viewport.transform`、按 `viewport.clip_rect` 在**页面空间**裁剪、
  按 `gpar` 上色；`text.angle` 只叠局部旋转（§7.1）。`pch` 表、曲线求值、
  文本 shaping 都在设备侧（`ggskia`，协议是 `ggcore.device.Device`，
  口径见 `docs/notes/device.md`）。
- **M1 语法层**：ggplot2 的 `geom_*` 落到这里就是 `points_grob` / `path_grob` /
  `text_grob` + `g_table_grob`；面板/轴/图例的组版走 gtable（§9）。
