# 视口口径账本（viewport）

`ggcore.viewport` 是 grid 视口语义的 Python 对等物：视口树（父子/兄弟）、
push / pop / up / down / seek 导航、单位换算后的仿射变换（含旋转与 `just`）、
裁剪区继承、gpar 逐字段继承。它是 gtable（M0-5）、grob 遍历（M0-6）和 IR
（M0-8）共同的坐标底座。

- 代码：`src/ggcore/viewport.py`
- 用例：`tests/test_viewport.py`（手算与契约）、`tests/test_viewport_r_parity.py`
  （与 R 逐条对拍）、`tests/test_viewport_cases.py`（可视化快照）
- 参考实现：R 4.5.3 的 `grid`——`src/library/grid/src/viewport.c`
  （`calcViewportTransform()`、`doSetViewport()`）、`grid.c`（`L_setviewport` /
  `L_downviewport` / `L_upviewport` / `L_unsetviewport`）、`matrix.c`（`trans()` /
  `multiply()`）、`just.c`（`justification()`）、`R/grid.R`（`push.vp.viewport`、
  `downViewport`）、`R/gpar.R`（`set.gpar`）。R 版本由 `pixi.toml` 的
  `[feature.refs]` 钉住，对拍夹具由它生成。

## 1. 坐标口径：设备英寸、y 向上

所有几何计算都在**设备英寸、原点左下、y 向上**的空间里做——这是 R graphics
engine 的口径，也是 `grid` 能把旋转换进矩阵的原因（变换矩阵所有分量都只和
英寸有关）。写 IR 之前才翻成 pt、y 向下（`docs/notes/ir.md` 的坐标约定），
由 `VpNode.ir_transform()` / `VpNode.ir_clip_rect()` 负责，见 §7。

## 2. 变换链

一个视口的变换（行向量 3×3，对应 `matrix.c` 的 `trans()`：`p' = p · M`）：

```
transform = J · R · L · parent.transform
```

按**作用在点上的顺序**读是 `J → R → L → parent`：

| 段 | 含义 | R |
| --- | --- | --- |
| `L` | 把视口原点（左下角）移到父坐标系里的 `(x, y)` | `translation(xINCHES, yINCHES, thisLocation)` |
| `R` | 绕对齐点逆时针旋转 `angle` 度 | `rotation(viewportAngle(vp), thisRotation)` |
| `J` | `just` 的平移 `(-width * hjust, -height * vjust)` | `justification()`：`hadj = -width*hjust` |
| `parent` | 父视口 → 设备 | `multiply(thisTransform, parentTransform, transform)` |

关键点：**旋转是绕“对齐点”转的**，不是绕左下角。`just = "centre"` 时 `J`
把视口中心挪到原点、转完再挪到 `(x, y)`，所以 `(x, y)` 是视口中心；`just =
("left", "bottom")` 时 `(x, y)` 是左下角。`tests/test_viewport.py` 用列向量
3×3 矩阵另写一遍同样的合成，抓出了本文写作时的一次顺序错误（`then` 的第一个
实现把矩阵乘法顺序写反了）。

“绝对坐标”= `transform`；视口内部的点先用自己的
`UnitContext`（宽度、`xscale`/`yscale`、gpar 的字号/cex/行高）换算成本地英寸，
再乘 `transform`（R `transformLocn()` / `deviceLoc()`）。

## 3. 谁的 gpar、谁的尺寸

视口的 `x` / `y` / `width` / `height` 是在**父视口**里给的，所以求值用父视口的
`UnitContext`；视口内部坐标用自己的。R 在 `calcViewportTransform()` 里也是这么
分的：几何用 `parentContext` + `parentgc`，`transformLocn()` 用 `vpc` + `gc`。

但**尺寸和 scale 取父视口，gpar 不取父视口自己的**：R 的 `parentgc` 来自
`gcontextFromgpar(viewportParentGPar(vp))`，也就是本视口 push 那一刻捕获的
`parentgpar`。源码注释写得很直白：“最近一次 gpar 设置可能来自 gTree”——gTree 的
临时 `gp` 下 push 的 `childrenvp`，它的父视口 gpar 可能还是老值。所以：

| 输入 | 来源 | R |
| --- | --- | --- |
| 宽 / 高 / `xscale` / `yscale` | 父视口（根为设备） | `fillViewportContextFromViewport(parent, …)` |
| `fontsize` / `cex` / `lineheight` | `node.parent_gpar`（push 时捕获） | `gcontextFromgpar(viewportParentGPar(vp), …)` |

`lines` / `char` 这类单位两者都要，混用时口径差异**不会报错，只会静默算错尺寸**。
`tests/test_viewport.py::test_units_see_the_temporary_gpar_of_a_g_tree` 用真 gTree
的实测值钉住：`gTree(gp = gpar(fontsize = 20))` 下 `width = unit(2, "lines")` 得
`0.6667 in`，拿父视口的 ps12 会得 `0.4`。

父为设备时（根视口），R 硬编码 `ps = 10`、`lineheight = 1.2`、`cex = 1`。我们
照抄（`ViewportTree._parent_context()`），但根视口的几何是写死的铺满设备，所以
这条只在“根视口自己用 `lines`/`char` 单位”时才有意义——实际用不到。

## 4. 裁剪三态

R 4.5.3 的字符串形式映射到逻辑值（`R/viewport.R` 的 `valid.viewport()`）：
`"on"` → `TRUE`、`"off"` → `NA`、`"inherit"` → `FALSE`；**缺省是 `"inherit"`**
（ggplot2 的 panel 自己显式传 `clip = "on"`）。

| `clip` | 生效的裁剪框 | R |
| --- | --- | --- |
| `on` | 本视口 `0..1 npc` 的设备外包框 | `transformLocn(unit(0,"npc"), unit(0,"npc"))` 到 `(1,"npc")` |
| `off` | 整个设备，略微放宽到 `-0.5..1.5` 倍 | `xx1 = toDeviceX(-0.5*devW)` 等 |
| `inherit` | 父视口记录的裁剪框 | 复制 `parent$cliprect` |

两个不明显的分支：

- `clip = "on"` 但**累计**旋转不是 `0 / 90 / 270 / 360` 时，R 只发
  `cannot clip to rotated viewport` 警告，然后退化成继承父裁剪框（即
  “`clip=TRUE` + 旋转 ≈ `clip=FALSE`”）。**180° 也在退化之列**：它虽然是
  90 的倍数，但两个角点顺序会翻转，R 没把它列进白名单。我们用
  `RotatedClipWarning` 报同一个警告，判定用的是精确的浮点相等（和 R 一致，
  所以 30 + 60 = 90 可以裁剪，45 + 45 = 90 也可以）。
- 根视口（`topLevelVP`）的 `clip="on"` 是特例：视口坐标取 `-0.5..1.5 npc`，
  等价于设备外包框，避免设备名义边界落在物理边界内时被自己裁掉。

裁剪框存成**未规范化**的四元组 `(x0, y0, x1, y1)`——90° 旋转下 `x0 > x1`
和 R 一样。渲染端要排序，用 `VpNode.clip_box`。

## 5. gpar 继承

`ResolvedGpar.merge(delta)` 对应 R `set.gpar()`：

| 增量里的取值 | 结果 |
| --- | --- |
| 没写（`UNSET`，`Gpar()` 的缺省） | 继承父值，**不覆盖** |
| 具体值 | 覆盖父值（`cex` / `alpha` / `lex` 与父值**相乘**） |
| 显式 `None` | 清空：回到 grid 缺省（`GPAR_DEFAULTS`），不参与乘法 |

`cex` / `alpha` / `lex` 的累积是 R 的特例（`set.gpar()` 里 `temp$cex <- temp$cex
* gp$cex`），所以 `cex = 1.5` 的父视口里写 `cex = 0.5` 得到 0.75，而不是 0.5。

**与 R 的差异**：R 的 `gpar(col = NULL)` 走 `validGP()`，是把该字段从增量里
**删掉**（等价于“不覆盖”），不是清空。本项目按任务要求把“显式 `None` 才清空”
做成了显式语义：`Gpar(col=None)` 让该字段回到缺省值，`Gpar()` 才是“不覆盖”。
`docs/notes/units.md` 的写法也是这个路子——R 表达不了或语义反直觉的地方单独列。

字段与缺省值照 `gpar.c` 的 `initGPar()`（也就是 pdf 设备上 `get.gpar()` 的输出）：
`fill="transparent"`、`col="black"`、`lty="solid"`、`lwd=1`、`cex=1`、
`fontsize=12`、`lineheight=1.2`、`font=1`、`fontfamily=""`、`alpha=1`、
`lineend="round"`、`linejoin="round"`、**`linemitre=10`**、`lex=1`。

- `linemitre` 的缺省是 **10**（`initGPar()` 写死的），不是 R 文档里的 1；
  IR 的 `Gpar` 缺省是 1.0（“没写这个字段”），两者含义不同，别混。
- `linejoin` R 不做校验，`"mitre"` 与 `"miter"` 都收；我们也收，值原样保留。
- `fontface`（字符串：plain/bold/italic…）在 R 的 `validGP()` 里就折成 `font`
  整数了，这里只保留 `font`。字符串形式等 M0-6 的 grob 层再补。
- gpar 在 `pop` / `up` 时回到**被弹出视口的 `parentgpar`**（推入那一刻的生效
  值），`down` 则**直接换成**目标视口的解析值（R 特意没用 `set.gpar()`，因为
  `cex` 会累积）。`parentgpar` 单独存，是为了 gTree 在视口之间临时改 gpar：
  `ViewportTree.temporary_gpar(gp)` 就是那条路径（R 的 `set.gpar()` + 退出时恢复，
  `preDraw.gTree()` 的 `tempgp` / `drawGTree()` 的 `tempgpar`），临时 gpar 下 push
  的子视口按它算 `lines` / `char` 几何，见 §3。退出时它只换 gpar、不动视口栈，
  所以调用方要**先 up/pop 回 gTree 层再退出**。R 的视口也在那儿回到 gTree 层，
  但两条恢复路径不是一回事：`childrenvp` 在 `preDraw.gTree()` 里
  `pushViewport()` 之后**立刻** `upViewport(depth(childrenvp))`，早于画子节点、
  更早于 `drawGTree()` 的 `on.exit()`；`postDraw.grob()` 只 `popgrobvp(x$vp)`，
  弹的是 gTree 自己的 `vp`。

## 6. 导航语义

| 操作 | 语义 | R |
| --- | --- | --- |
| `push(*vps)` | 依次压栈，同名子视口顶掉旧的（children 是 environment） | `pushViewport()` / `L_setviewport()` |
| `pop(n)` | 出栈并**从树上摘掉**，`n=0` 一直回到根 | `popViewport()` / `L_unsetviewport()` |
| `up(n)` | 只上移，不动树，返回上移掉的路径 | `upViewport()` / `L_upviewport()` |
| `down(name, strict)` | 从当前视口往下找已存在的视口，gpar 换成它的解析值 | `downViewport()` |
| `seek(name)` | 先回根再往下找 | `seekViewport()` |

查找规则（`downViewport` / `find`）：

- 从**当前视口的孩子**开始，不含自己和祖先（所以不能在 `a` 里 `down("a")`）。
- 同级候选按**名字排序**遍历（R 的 children 是 environment，`ls()` 排过序），
  与 push 顺序无关。
- `strict=False`（R 缺省）对相对路径做**段级后缀**匹配：`down("b")` 能找到任意
  深度的 `b`，`down("b::c")` 能找到段序列以 `b`、`c` 结尾的相对路径。
- `strict=True` 要求从直接子节点起逐段完全一致。
- 名字里的 `::` 会被拆成路径段（`vpPath()` 的行为）。

**与 R 的差异（比 R 更严）**：R 的 `pathMatch()`（`R/grid.R:119`）返回
`paste0(if (strict) "^", path, "$")`，再对累积路径字符串做 `grepl()`——也就是
**最后一段按名字精确查，前面的部分当正则、只锚定末尾**。所以 `xxa/b` 这棵树里
R 的 `down("a::b")` 能命中（`"a::b$"` 匹配 `"xxa::b"`），名字里的 `.` 也会被当
元字符。gg4py 在**段边界**上逐段比较、不做正则解释，不会跨段命中：
`down("a::b")` 在 `xxa/b` 里找不到。ggplot2 4.0.3 只在 `R/plot.R:217` 用单段
`seekViewport()`，这条差异碰不到它。

两条行为都钉住了：`tests/test_viewport.py::test_down_finds_descendants_by_suffix_path`
（gg4py 的后缀语义）与 `::test_non_strict_path_matching_is_segment_exact_where_r_uses_a_regex`
（`a::b` 在 `xxa/b` 里不命中，而 R 会命中）。

## 7. 与 IR 的接口

`docs/notes/ir.md` 里 `viewport` 节点带的是“子坐标 → 父坐标”的 2×3 仿射
（`transform`）和裁剪框（`clip_rect`），坐标是 pt、y 向下、原点左上。本模块提供：

- `VpNode.ir_transform()`：子视口坐标（pt，y 向下）→ **父视口坐标**（pt，y
  向下），根视口是单位阵。推导：先在两端各做一次 `pt ↔ 英寸` 翻转
  （`S(h)` / `S(h)⁻¹`），中间的设备英寸映射是 `M_self · M_parent⁻¹`，而设备
  高度在两次翻转里互相抵消，所以这个函数不需要页面高度。M0-8 直接把它写进
  IR 的 `viewport.transform`。
- `VpNode.ir_clip_rect()`：裁剪框翻成 pt、y 向下并排序成 `(x0, y0, x1, y1)`，
  **页面绝对坐标**（不是子坐标），供 IR 的 `clip_rect` 用。IR v0.2 起
  `viewport.clip_rect` 的口径就是页面坐标：旋转 `inherit` 的生效裁剪框在子坐标
  里不是轴对齐矩形，4 元组表达不了。M0-8 的消费约束是「节点自下而上合成页面
  变换后，在页面空间裁剪」——别拿它去和子坐标求交，那会裁掉右边和下边
  （反例见 `tests/test_viewport.py::test_ir_clip_rect_is_page_space_pt`；父视口不是
  `ROOT` 时的口径见 `::test_ir_clip_rect_is_page_space_under_a_non_root_parent`）。
- `VpNode.convert(unit, to, axis=…, measure=…)`：在视口里换算单位（`convertX`
  / `convertWidth` 的等价物），给 grob 尺寸计算用。

## 8. 参考值怎么来

```bash
pixi run -e refs refs:viewport   # Rscript tools/refs/viewport_ref.R
```

- 设备固定成 6×4 in 的 `pdf(NULL)`（设备单位是 bigpts，1 in = 72）。用到的单位
  都不依赖字体度量，所以夹具与机器字体无关。
- 每条用例是一段**步骤脚本**（push / pop / up / down / seek / check），spec 原样
  写进夹具，Python 侧用同一份脚本重放；每个 check 记下路径、深度、累计旋转、
  视口宽高（英寸）、裁剪框（英寸）、解析后的 14 个 gpar 字段、以及若干探针的
  「本视口英寸」与「设备英寸」（`convertX`/`convertY` 与 `deviceLoc`）。
- `clip_warning` 记录 R 在哪个 check 之前报过 `cannot clip to rotated viewport`，
  Python 侧要报同一个。现在 5 个用例 / 22 个 check 步：单层 + 反向 scale、三层
  旋转叠加、裁剪三态与退化、gpar 逐字段继承、导航（up/down/pop/seek）。

## 9. 刻意不复制 / 不支持

| 行为 | R | gg4py |
| --- | --- | --- |
| 视口 layout（`layout.pos.row/col`） | 从父视口的 layout 里算位置 | 未实现（M0-5 gtable 之后接） |
| 裁剪路径（`clip = grob`）、mask | 支持 | 未实现，`clip` 只收三态字符串 |
| `clip` 的逻辑形式 | `TRUE`/`NA`/`FALSE` 依次是 on/off/inherit | 只收字符串，传 `bool` 直接报错（避免 `clip=False` 被误读成 off） |
| gpar 的 `gamma` / `gradientFill` / 图案填充 | 支持 | 未实现（`gamma` 在 R 4.x 已 defunct） |
| gpar 的向量值（一个 gpar 对应多个 grob） | 支持 | 未实现：一视口一标量，M0-6 按“一组 gp 一个 IR 节点”展开（见 §12） |
| `fontface` 字符串 → `font` 整数 | `validGP()` 里折好 | 只收 `font` 整数 |
| 路径名的正则匹配 | `pathMatch()` 用 `grepl(paste0(path, "$"))` | 按段精确比较（更严，不跨段） |
| 根视口的 `xscale`/`yscale` | 设备原生单位（pdf 下是点，0..432） | 设备英寸（0..6）；显式给 `xscale`/`yscale` 的视口两边一致。`tests/test_viewport.py::test_root_scale_is_device_inches` 钉住 |
| 视口树的序列化 / `grid.grab` | 有 | 未实现（IR 只带解析后的结果，M0-2） |

## 10. 可视化快照

`docs/cases/viewport-*` 是两套 PNG（900×600，`pixi run cases:viewport` 重生成）：

- `viewport-nested-rotate`：三层嵌套，角度 15 / 25 / 50（累计 15 / 40 / 90），
  每层的方框、本地坐标轴、b 的 native 曲线、c 的 native 圆和裁剪框；
- `viewport-clip`：三块面板对照 `clip = inherit / off / on @45°`，内容是本地
  npc 里 `x` 超出 `0..1` 的四条横带——继承的会被父框截断，`off` 的越界，
  旋转的退化成继承。

快照只作可视化回归：`tests/test_viewport_cases.py` 比对像素时留了抗锯齿余量
（不同 CPU 的 SIMD 路径可能差一两个灰阶），结构改动（视口挪位、裁剪框错、
文字缺失）一定过线。数值对不对由 §8 的 R 对拍和手算断言守。

## 11. 与后续模块的接口

- **gtable（M0-5）**：`VpNode.unit_context()` 给出换算上下文；布局算完的
  行高/列宽再回填成 `width`/`height`（R 的 `layout.pos` 就落在这条线上）。
- **grob（M0-6）**：`VpNode.convert()` 换算尺寸，`VpNode.device_points()` 定位；
  `just` 的数值形式（`justifyX()` / `justifyY()`）在 grob 层再实现——视口只
  处理自己的 `just`。gTree 的临时 `gp` 用 `ViewportTree.temporary_gpar()`，
  在它里面 push 的 `childrenvp` 会自动按那份 gpar 算 `lines`/`char` 几何（§3）。
- **设备（M0-8）**：`clip_box`（设备英寸）和 `ir_clip_rect()`（pt、y 向下、
  **页面绝对坐标**）两种形态，skia 用后者：先自下而上合成页面变换，再在页面
  空间裁剪；栅格化时按 `device.dpi` 把 pt 换算成像素。

## 12. 留给 M0-6 / M0-8 的决定

这些是审核提出的扩展点，本模块先定口径、不扩实现：

- **`NA` 的表示**：R 的 gpar 值是向量，元素可以是 `NA`（`col = NA` = 不画）。
  gg4py 的显式 `None` 已经占给「清空回缺省」，**不能再用 `None` 兼职 `NA`**；
  M0-6 加独立哨兵（如 `ggcore.viewport.NA`，与 `None` 并列比较），`NA` 原样进
  IR 的 `gpar` 由设备跳过。本 PR 不改线格式，只在文档里定死这条。
- **gpar 的向量值**：`Gpar` 保持标量。ggplot2 的 `pointsGrob` / `polylineGrob`
  会按顶点传 `gp`（`geom-point.R:26`），M0-6 在 grob → IR 展开时按「同一组 gp
  的顶点一个节点」切开，不把 `Gpar` 扩成数组——IR 节点的 `gpar` 本来就是标量。
- **gpar 校验比 R 严**（`lwd = -1`、`lwd = Inf`、`font = 9`、`lineend = "pointy"`、
  `col = 42`、`col = NA` 在 R 里都能存下来）：这是刻意的，宁可早报错也不让
  设备端拿到画不出来的值。M0-6 若要放宽，按字段单独列进 §9 的差异表。
- **`xscale` / `yscale` 的输入类型**：已放宽到「任意非字符串可迭代对象」，
  `np.ndarray`（panel 的数据范围）直接可用，不必先转 `tuple`。
- **根级 native**：不支持。根视口的 `xscale`/`yscale` 是设备英寸（§9 已钉），
  根视口自己用 `native` 单位没有意义；需要 native 的视口显式给 `xscale`/`yscale`。
