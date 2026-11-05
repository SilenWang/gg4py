# IR v0 口径

IR（`ggcore.ir`）承载**已解析几何**，是渲染（skia / DOM SVG）、差分、浏览器查看器
唯一的中间表示。本文记录字段、约定和账本数字；改字段先改
`src/ggcore/ir/nodes.py` 的 `NODE_SPECS`，再改这里。

- 代码：`src/ggcore/ir/nodes.py`（节点表 + 校验）、`codec.py`（CBOR）、`demo.py`（门禁载荷）
- 用例：`tests/test_ir.py`（round-trip / 确定性 / 版本 / 体积 / 校验）
- 门禁：`pixi run gate:determinism`（真实 scene，跨进程字节一致）

## 1. 定位：写进 IR 的都是“已经算完的”

在写 IR 之前完成，IR 里不再出现：

| 已经做完的事 | 归属阶段 | IR 里对应什么 |
| --- | --- | --- |
| 单位换算（npc/native/mm/pt/lines/strwidth…） | M0-3 | 最终坐标（float32） |
| 视口 push/pop、旋转、gpar 继承、裁剪 | M0-4 | `viewport` 的 2×3 仿射 + 裁剪框 |
| gtable 布局（null 单位、padding） | M0-5 | 已消费：只有最终矩形 |
| grob 树遍历、gpar 解析 | M0-6 | 扁平的节点顺序 + 解析后的 `gpar` |
| 字体度量、字族回退切 run | M0-7 | `text` 的最终 `width` + 单个已解析字体 key |
| data → npc 的 scale/coord 映射 | M1 | 最终坐标 |

IR 里**没有**：单位对象、scale、主题继承链、font stack、字符测量上下文、布局约束。
容器（`viewport` / `gtree` / `clip`）不带 `gpar`——每个可绘制节点带的就是解析后的
最终值，没有“继承”这一步。

坐标约定：

- **y 轴向下**，原点在页面左上角（与 SVG / Canvas / skia 一致；grid 的 y-up 在写 IR 前翻转）。
- 几何坐标是所在节点坐标系下的最终值；`viewport` 的 `transform` 把子坐标映射到父坐标。
- 例外是 `viewport.clip_rect`：**页面绝对坐标**，不跟 `transform` 走（§4）。
- 页面尺寸 `Scene.size` 单位 pt；`Scene.dpi` 只影响栅格化的像素换算，不改变几何。
- 子节点顺序即绘制顺序：先出现先画（自后向前）。

## 2. 线格式

CBOR（`cbor2`），canonical 编码。Pyodide 里没有 `cbor2`（没有 wasm 轮子），那边
换用同字节的纯 Python 实现 `ggcore/ir/_cbor.py`，一致性由 `pixi run gate:pyodide`
逐字节守住（`docs/notes/pyodide.md`）。结构：

```
{
  "magic": "ggir",
  "ir_version": [0, 4],
  "scene": {
    "size": [w, h],                       # pt
    "dpi": 72.0,
    "blobs": {"sha256:…": {"mime": "image/png", "data": b"…"}},
    "root": {"kind": "viewport", …}       # 必须是 viewport
  }
}
```

节点：

```
{
  "kind": "path",
  "gpar": {"col": [31, 119, 180, 255], "lwd": 1.5},        # 只写非缺省字段
  "params": {"rule": "evenodd"},                            # 只写非缺省字段
  "bufs": {"points": {"dtype": "f4", "shape": [10000, 2], "data": b"…"}},
  "texts": ["…"],                                           # 仅 text
  "children": [ … ]                                         # 仅容器
}
```

bulk 数据永远是**原始 float32 小端字节**，不做逐元素 JSON，也不 base64（体积账见 §10）。

## 3. 版本

- 常量：`IR_VERSION = (0, 4)`、`IR_VERSION_STR = "0.4"`，编码时写进 `ir_version`。
  版本号只有这一处来源（`src/ggcore/ir/codec.py`），文档、测试、查看器都从它派生。
- 解码只认 **major**：`major != IR_VERSION[0]`（现在是 0）抛 `IRVersionError`
  （`IRDecodeError` 的子类），不尝试“猜一个相近版本”。
- 同一 major 内的规则只分两档，**每一层映射都走同一份判断**：

  | 线格式 | 未知键（envelope / `scene` / `blobs` 条目 / 节点 / `params` / `bufs` / 缓冲对象 / `gpar`） | 未知节点种类 & 未知缓冲 `dtype` |
  | --- | --- | --- |
  | minor ≤ 本实现 | 报 `IRDecodeError`（防止截断或拼错被静默吞掉） | 报错 |
  | minor > 本实现 | 跳过不读（前向兼容） | **报错**（画不出来、读不懂的东西不能猜） |

  两档的边界由 `tests/test_ir.py::test_decode_rejects_unknown_keys_at_the_same_minor`
  与 `::test_decode_tolerates_unknown_keys_from_a_newer_minor` 逐层钉住。
- 因此新增字段是 minor，删除/改语义/改必需性是 major。
- **例外：从未被消费过的语义可以走 minor**。某字段的语义**从未被任何消费端按语义
  读过**时，改它的语义按 minor 处理。判据必须可核查：先立前提 ②③，再满足下面
  任一资格。

  前提（两条都得成立）：
  - ②写入方与读方都在本仓库内，能一起改；
  - ③该字段的口径只在仓库里跟着参考实现对过，没有对外承诺过旧语义。

  资格（二选一即判 minor）：
  - **资格 A（没有语义读方）**：①仓库**外**（含 release / tag / 外部只读实现）
    没有任何实现读取该字段的语义；仓库内的读取只有形状校验与往返/黄金样例。
  - **资格 B（没有按旧语义写过值）**：从未有任何写入方**按被改掉的旧语义**产出过
    该字段的值。旧语义一个样本都没落地，也就无从被依赖。仓内 fixture 按旧语义
    写过值就不满足 B——那种情形归资格 A 管（写方归我，改的时候一起改）。

  两条资格各自独立的失效条件：
  - 资格 A 失效：出现仓库外读取该字段语义的实现（外部集成的只读实现也算），或
    仓库内出现不能跟着一起改的读方（② 不成立）。
  - 资格 B 失效：有写入方真的按旧语义产出过该字段的值。

  一条失效不自动否掉另一条；两个资格都不成立时，该字段才失去例外资格，**之后
  同类改动一律按 major 处理**。这个例外只覆盖“改语义”，不覆盖删除字段、改必需性
  或改 `bufs[k].dtype` 的值域。
- 已知一个 minor 升上去也会被严格拒绝的例外：`bufs[k].dtype` 必须是本实现认识的
  `f4` / `i4`。新增 dtype 属于 major 变更。
- **0.2 → 0.3 记账（判 minor，纯加字段）**：`segments` / `polyline` / `curve` 各加了
  四个带缺省值的参数（§4.1 的 `arrow*`）。没有改任何既有字段的语义、必需性或
  `bufs` 的 dtype；缺省值不写进线格式（编码只写非缺省），所以 v0.2 的 scene
  编码字节完全不变。旧读方（minor 0.2 ≤ 自己的实现）遇到这四个键会按上表报错
  ——这是预期的“读不懂就拒绝”，不是回归。
- **0.1 → 0.2 记账（判 minor，决定性事实是资格 A）**：`viewport.clip_rect` 的坐标系
  从“子坐标”改成“页面坐标”，按普通规则属于“改语义”。逐条对判据（`25b3575` 是
  IR v0 那个提交，下面每条都能用 `git show 25b3575:<path>` 复算）：
  - **资格 B 不成立**：仓内确实写过值——`src/ggcore/ir/demo.py:52` 写
    `[[0, 0, 600, 480]]`，`tests/test_ir.py` 的 186/240/246 行各写了一个小方框。
    按 v0.1 的契约（`src/ggcore/ir/nodes.py` 里 `BufferSpec` 的 note、v0.1 那份
    `docs/notes/ir.md` 的 §4“子坐标”）这些数字就是子坐标值；git 历史里没有证据
    表明它们是页面值。所以 B 用不上，它**不是**这次判定的依据。
  - **资格 A 成立**：仓库外没有按语义读该字段的实现——`git ls-remote --tags origin`
    为空、`gh release list` 为空、仓库 private、无外部只读集成；仓库内读
    `clip_rect` 的只有 `nodes.py` 的必填/形状校验、`codec.py` 与 `tests/test_ir.py`
    的往返、`tests/test_viewport.py` 的黄金样例（它在改语义的同一次改动里一起改），
    没有渲染或语义消费端（M0-8 还没做）。
  - **前提 ②③ 成立**：写方（`demo.py`、`tests/test_ir.py`）与读方都在本仓库内，
    0.1→0.2 时一起改；口径只在仓库内跟着参考实现对过，没有对外承诺过旧语义。

  故按资格 A 判 minor。若 v0.1 已有渲染端按子坐标读它、或仓库外有实现/发布物按
  语义读过它，这次就是 major。
- **0.3 → 0.4 记账（判 minor，只加字段）**：新增 `gpar.fill` 的三种非纯色分支
  （`linear` / `radial` / `pattern`，§6.1）。纯色的线格式**一个字节没动**（仍是
  不带 `kind` 的 `[r, g, b, a]`），`GPAR_FIELDS` 的字段集合也没变——`fill` 只是从
  「四元组或 null」扩成「四元组 / 三类带 `kind` 的映射 / null」的联合类型。旧
  v0.3（与更早的 v0.2 / v0.1）文件里 `fill` 只可能是四元组，新读方照原样读，所以
  `tests/test_ir_fill.py::test_v0_2_file_still_reads` / `::test_v0_2_file_without_fill_still_reads`
  / `::test_v0_3_arrow_file_still_reads` 都钉住。
- **为什么渐变不能占 0.3**（SIL-767 §1）：#61 的箭头 IR 与这份渐变 IR 曾各自都写
  `(0, 3)`，而「minor ≤ 本实现」是严格模式，于是两份 0.3 文件交叉解码双向失败
  （箭头文件报 `segments 有未知参数`、渐变文件报 `gpar.fill 必须是四元组`）。
  同 minor 只能有**一种**语义，所以渐变改占 0.4。
- **新文件给旧读方**：不承诺向前兼容，但必须**明确报版本错误**、不能静默降级。
  两类各有一条路：读方是 0.3（不认识 `kind`）时，文件里的 `fill` 映射按「必须是
  四元组」报错；读方用 `decode(..., reader_version=(0, 3))` 时，`_FILL_MINOR`
  直接报 `IRVersionError`（渐变 / 图案 fill 引入于 0.4，跳过未知键等于画成不填充）。
  都由 `tests/test_ir_fill.py::test_v0_4_gradient_file_is_rejected_by_a_v0_3_reader`
  覆盖（同一个用例里对纯色再断言一次「0.3 读方照常读」）。

## 4. 节点类型表

18 种节点 = 3 个容器（`viewport` / `gtree` / `clip`）+ 15 个叶子（13 个可绘制原语
+ `null` + `zero`）。计数口径只有这一份，三种数别混（`docs/notes/grobs.md` §1）：

- 18 = grob 构造器个数（13 种可绘制原语 + `clipPath` + `nullGrob` + `zeroGrob` +
  `gTree` + `gtable` 的 grob 视图）；
- 18 = 本表的节点 kind；
- 14 = `ggcore.grobs.Scene.to_ir_scene()` **实际产出**的 kind（13 种可绘制原语 +
  `viewport`）。`null` / `zero` / `gtree` / `clip` 不会从 grob 路径来——`null` /
  `zero` 只有布局语义（布局在写 IR 前消费掉），`gTree` / `clipPath` 是遍历容器
  （顺序与裁剪已经落到子节点上）。它们保留在表里是给别的写方用。

| kind | 用途 | 缓冲（dtype / shape） | 参数（缺省） |
| --- | --- | --- | --- |
| `viewport` | 变换 + 裁剪 + 子节点 | `clip_rect` f4 (1,4) 可选（页面坐标 pt） | `name`=""、`clip`=true、`transform`=(1,0,0,1,0,0) |
| `gtree` | 纯分组容器（v0 只表达顺序） | — | `name`="" |
| `clip` | 任意形状裁剪 | `rect` f4 (1,4) 或 `points` f4 (n,2)；`id` i4 (n,) 可选 | `name`=""、`rule`="winding" |
| `rect` | 矩形 | `rect` f4 (n,4) | — |
| `circle` | 圆 | `circle` f4 (n,3) = (cx, cy, r) | — |
| `lines` | 折线组 | `points` f4 (n,2)；`id` i4 (n,) 可选 | — |
| `segments` | 独立线段 | `segments` f4 (n,4) | `arrow`="none" 等（见 §4.1） |
| `polyline` | 单条/多条折线 | `points` f4 (n,2)；`id` 可选 | `arrow`="none" 等（见 §4.1） |
| `polygon` | 多边形 | `points` f4 (n,2)；`id` 可选 | — |
| `path` | 多条子路径 + 填充规则 | `points` f4 (n,2)；`id` 可选 | `rule`="winding" |
| `points` | 散点 | `points` f4 (n,2) | `pch`=1、`size`=1.0（pt） |
| `text` | 文本（见 §7） | `pos` f4 (n,2)、`width` f4 (n,) | `font`、`size` 必填；`anchor`="center"、`baseline`="middle"、`angle`=0 |
| `raster` | 位图 | `rect` f4 (1,4) | `blob`、`width` ≥1、`height` ≥1 必填；`interpolate`=true |
| `xspline` | xspline | `points` f4 (n,2)；`id` 可选 | `shape`=0.0（-1..1）、`open`=true |
| `bezier` | 三次贝塞尔段 | `control` f4 (4n,2)，每 4 行一段 | — |
| `curve` | grid.curve | `ends` f4 (n,4) = (x1,y1,x2,y2) | `curvature`=1、`angle`=90、`ncp`=1、`shape`=0.5、`square`=true、`inflect`=false、`open`=true；另有 §4.1 的箭头参数 |
| `null` | nullGrob：不画、不占位 | — | — |
| `zero` | zeroGrob：不画，参与布局 | — | — |

### 4.1 箭头（v0.3）

`segments` / `polyline` / `curve` 三个节点多了四个**标记属性**（M2-S2）：

| 参数 | 取值 | 缺省 | 含义 |
| --- | --- | --- | --- |
| `arrow` | `none` / `first` / `last` / `both` | `none` | 箭头画在哪个端点（`grid::arrow(ends =)`） |
| `arrow_length` | pt（≥0） | 0 | 每条箭翼的长度（`arrow(length =)` 已换算成 pt） |
| `arrow_angle` | 0..90 度 | 30 | 箭翼与轴线的夹角 |
| `arrow_type` | `open` / `closed` | `open` | 两条边 / 填色三角（填充用 gpar 的 `fill`） |

箭翼的**几何不进 IR**：切向由设备按端点相邻点求（曲线的切向要按 `curvature` /
`ncp` 采样，只有设备算得出）。公式只有一行，两边共用：从端点 `tip` 沿
`back → tip` 的方向退 `arrow_length`，再左右各转 `arrow_angle`，得到两个底点；
`open` 画 `tip→b1`、`tip→b2` 两条线，`closed` 画 `tip,b1,b2` 的三角。Python 侧的
`ggcore.arrow.head_geometry()` 是这句的参考实现，TS 侧逐行移植。

不带箭头时四个参数都等于缺省值，编码按“只写非缺省”省略——所以 v0.2 的 scene
字节不变（0.2 → 0.3 是加字段的 minor）。旧读方遇到未知参数会按 §3 的口径拒绝
（minor ≤ 自己时）或忽略（minor 更新时）。

细则：

- **id 分组**：每个顶点一个分组号，值一变化就切一条子路径（grid 的 `id` 语义）。
  `id` 行数必须等于 `points` 行数。
- **矩形/圆**：不要求 `x0 < x1`，设备自己归一化；`circle` 的半径在视口单位下，
  椭圆用视口变换表达（不做 rx/ry）。
- **clip**：`rect` 与 `points` 二选一，且 `rect` 只能一行；`points` 可配 `id` 画多子路径。
  子节点在裁剪形状内绘制。
- **viewport.clip**：`clip=true` 时 `clip_rect` 必填（**页面绝对坐标**，见下条），
  不存在“猜一个单位框”的默认；宁可报错也不要两端各猜一个。`clip=false` 时可以不带。
  **零面积的 `clip_rect` 就是裁掉一切**，不代表 `inherit` / “不裁剪”：那两种语义在
  写 IR 之前就折成具体矩形了（`docs/notes/grobs.md` §6 / §7.3）。
- **`viewport.clip_rect` 的坐标系**：页面绝对坐标（pt、y 向下、原点页面左上），
  **不是子坐标**；与 `Scene.size` 同一套坐标，和节点自身的 `transform` 无关。
  旋转 `inherit` 的生效裁剪框在子坐标里不是轴对齐矩形，4 元组表达不了，页面坐标无损。
  消费约束（M0-8）：节点自下而上合成 `transform` 得到页面变换后，**在页面空间**
  裁剪，不要拿它去和子坐标求交。自 v0.2 起，此前“子坐标”的写法作废。
- **`viewport.name`**：写方填**最深视口名**（`panel-1-1` / `guide-0-key-0` /
  `axis-x-1`），空串表示没有名字。它不参与几何，是浏览器查看器（M1-13）唯一的分组
  依据：hover 显示所在视口、图例 key 靠 `*-key-<i>` 认出来。`Scene.to_ir_scene()`
  按 `(transform, clip, name)` 合并连续指令（`docs/notes/grobs.md` §7），所以同一
  视口里的连续图元仍然合成一个 `viewport`，不会因为加名字而膨胀。
- **curve / xspline / bezier**：控制参数是**解析后的语义参数**，曲线由设备按同一公式求值；
  它们还没被展平成折线，因为上游快照的对齐点在曲线形状本身。
- **取值范围在 IR 里校验，不留给渲染端**：`bezier.control` 的行数必须是 4 的倍数
  （每 4 行一段；0 行合法，等于不画），`raster.width` / `raster.height` 是不小于 1
  的整数像素，`xspline.shape` 落在 [-1, 1]。写方给错值在构造节点时就报
  `IRValidationError`——渲染端不需要替写方猜一个合法值。`int` 参数另外有一条
  全局上界 `[INT_MIN, INT_MAX]`（`ggcore.ir` 导出）：canonical CBOR 的 major 0/1
  只到 64 位，再大就要 bignum tag，而线格式不写 tag——所以这不是业务上界，是
  编解码口径（`docs/notes/pyodide.md` §7）。
- **null / zero**：区别只在布局阶段，布局信息不进 IR，所以两者在 IR 里都不产出绘制指令。

## 5. 缓冲

- dtype 只有两种：`f4`（float32，几何/宽度）、`i4`（int32，分组 id）；**小端**（写死 `<f4` / `<i4`）。
- 必须 C 连续；用 `ggcore.ir.f32()` / `i32()` 构造，构造后是只读视图（`writeable=False`）。
- 输入是 float64 / Python list 时在 `f32()` 一次性舍入到 float32，IR 里不再有第二次舍入，
  所以 round-trip 是**逐位**相同（dtype + shape + 原始字节），不是 `allclose`。
- 舍入前先量化到 1e-6 的十进制网格（`ggcore.ir.nodes._canonical_buffer`）：几何顶点来自
  宿主 libm 的 `sin` / `cos` / `exp`，1 ULP 的差**通常**被 float32 吸收，但值恰好贴着
  float32 的舍入边界时会翻一格——那同样让 IR 的 sha256 变化。见 §9 的「跨机器确定性」。
- 解码用 `np.frombuffer` 直接看线格式里的 bytes，不复制；形状与字节长度不符直接报错。
- 允许缓冲里出现 NaN / ±Inf / -0.0（缺失点、断线用 NaN 表达），但**参数字段**必须是有限值。
- **设备输入就是本格式的 `Scene`**：`ggcore.grobs.Scene` 的 `Instruction.bufs` 是
  遍历期的 float64 中间形态，**不进设备接口**——要出图先
  `scene(...).to_ir_scene()`（一次性 float32 舍入）。设备只读 IR，所以不会在
  float64 与 float32 两边各背一份几何（`docs/notes/grobs.md` §7.2）。

## 6. gpar

| 字段 | 类型 | 缺省 | 说明 |
| --- | --- | --- | --- |
| `fill` | 纯色 RGBA 四元组 / 渐变或图案映射 / null | null | 不填充；三种非纯色分支见 §6.1 |
| `col` | RGBA 整数元组或 null | null | 不描边；`text` 的文字颜色也用 `col`（**没有**渐变描边） |
| `lwd` | float | 1.0 | pt |
| `lty` | float 元组 | () | 已按 `lwd` 折算的 pt 段长；空 = 实线 |
| `lineend` | "round" / "butt" / "square" | "round" | 对标 grid 缺省 |
| `linejoin` | "round" / "miter" / "bevel" | "round" | 对标 grid 缺省 |
| `linemitre` | float ≥ 1 | 1.0 | 对标 grid 缺省 |
| `alpha` | float 0..1 | 1.0 | 乘在颜色上 |

- 颜色在写 IR 前完成 8 位舍入（`col2rgb` 口径）；IR 不做色彩空间转换。
- `lwd` 的 pt 是**折算后**的口径：R 的 `gpar$lwd` 单位是 1/96 inch，写 IR 时
  乘 `72/96`（`docs/notes/grobs.md` §7.2）。设备不做第二次换算。
- 缺省 = 什么都不画；`gpar` 键缺省与 `gpar: {}` 不同：前者表示“没有 gpar”，后者表示
  “gpar 全是缺省值”。解码保持这个区别。
- 只有非缺省字段上线（canonical + 体积）。

### 6.1 `fill` 的渐变与图案（v0.4）

纯色还是 `[r, g, b, a]`；其余三种是带 `kind` 的映射。**色标写成一条 f4 `(n, 5)`
缓冲**（`offset + r, g, b, a`），不是逐档的小映射——线格式与 `bufs` 里的缓冲对象
同构（`{"dtype": "f4", "shape": [n, 5], "data": b"…"}`），所以体积是 20 B/档：

```text
"fill": {"kind": "linear",  "stops": <f4 (n,5)>, "start": [x1, y1], "end": [x2, y2],
         "extend": "pad"}
"fill": {"kind": "radial",  "stops": <f4 (n,5)>, "center": [cx, cy], "radius": r,
         "focal": [fx, fy, fr], "extend": "pad"}        # focal 可缺省
"fill": {"kind": "pattern", "content": [<节点>, …], "size": [w, h], "origin": [x, y],
         "extend": "repeat"}
```

坐标口径（三条渲染腿共用一套）：

- **全部在节点局部坐标里**，与几何同一个坐标系（不是页面坐标、不是子视口坐标）。
  `viewport.transform` 会同时作用在几何与渐变 / 图案上，所以不需要第二套变换。
- 写方的 `ggcore.fills` 用 grid 的 npc 口径：`npc` 是**被填充对象包围盒**的比例，
  `pt` 是局部坐标直通。注意 npc 的 **y 向上**（npc 0 = 包围盒底边）、IR 的局部
  坐标 y 向下，写 IR 时翻一次——`fill` 的分支里只有 y 位置翻，尺寸不翻。
- 多行节点（一个 `rectGrob` 画三根柱子）只有**一整层包围盒**：R 也是这样解析的
  （`geom_col()` 的三行共用一个多行 grob，svglite 写三条**坐标相同**的
  `<linearGradient>`，实测见 `docs/cases/viewer-gradient-linear/expected.svg`）。
- `pattern.content` 的原语用**与节点几何同一个局部坐标**（不是 tile 相对坐标）。
  窗口是 `[origin, origin + size)`；第 `(i, j)` 块 = 内容 + `(i·w, j·h)`，裁到窗口。
  这与 R `grid::pattern()`、SVG `patternContentUnits="userSpaceOnUse"` 一致。
- `pattern` 的 tile 以写方的 `(x, y)` 为**中心**（grid `just = "centre"`），所以
  `origin = 中心 − size/2`。
- `stop.offset` 必须单调不减、`0..1`；颜色分量必须是 `0..255` 的整数；线性渐变的
  两端点不能重合；`radial.radius > 0`，给 `focal` 时 `0 ≤ fr < radius`。这些都
  在构造 / 解码时校验，渲染端不猜。
- `pattern.content` 只收 `rect` / `circle` / `polygon` / `path` / `polyline` /
  `lines` / `segments`，`gpar.fill` 只能是纯色——不允许在图案里再嵌渐变 / 图案。

消费端状态（三条渲染腿：skia PNG / SVG / PDF + 查看器 DOM SVG）：

| 项 | 现状 | 守护用例 |
| --- | --- | --- |
| SVG `spreadMethod` | **已修**（SIL-767 §3）：skia 的序列化器不写它，设备在序列化之后按 IR 的 `extend` 补写；`pad` 是 SVG 缺省值、不写 | `tests/test_skia_fill.py::test_gradient_extend_is_written_to_svg_as_spread_method` |
| SVG focal 渐变 | **已修**（SIL-767 §2）：skia 把两圆锥渐变的 `cx/cy/r`（start 圆）与 `fx/fy/fr`（end 圆）写反，设备按 IR 重写成规范形式（`cx/cy/r` = `center`/`radius`，`fx/fy/fr` = `focal`） | `::test_radial_gradient_with_focal_point`、`::test_focal_gradient_svg_rasterizes_the_way_png_renders`（resvg 像素对照） |
| 图案只支持 `extend = repeat` | `pad` / `reflect` 在 skia 侧显式 `DeviceError`，浏览器侧 `<pattern>` 本身只有平铺语义 | `::test_pattern_rejects_non_repeat_extend` |

SVG 侧的两处修法都落在 `ggskia.skia` 的序列化**之后**（`_rewrite_svg_gradients`）：
skia 把视口变换写成元素上的 `transform="matrix(…)"`，渐变坐标仍是节点局部坐标，
所以标签里的几何可以逐值对照 IR 的 fill；对不上的标签直接 `DeviceError`，不猜。

图案的**跨腿相位差**（已记录差异，不修）：resvg 与 Chromium 的 `<pattern>` 平铺都
按整数像素步进，tile 尺寸带小数时第 `n` 块会比 `n · w` 偏 `frac(w)` 像素，逐块累积。

| tile 周期 | 两腿对拍（图级 / 均值） | 说明 |
| --- | --- | --- |
| 整数 pt（现有 case：30 pt） | 0.000% / 0.25% | 相位不漂，对拍稳定 |
| 分数 pt（31.32 pt） | 0.46% / 0.46% | 每块比理论位置偏 0.32 px，越往右越多 |

上表是 SIL-767 审核在 Chromium 下的实测（不是本仓库的自动门禁）：分数周期的
case 还没有入库，因为它的参考图要走 R 产线，而这条差异本身不打算修。

写方的 npc 口径不受影响（IR 里存的是解析后的 tile 尺寸，没有任何量化）；这条差异
只在「同一份 IR 的两条腿逐像素比」时出现，所以对拍 case 的 tile 周期取整数 pt。

## 7. text：只带最终宽度与锚点

度量账本 L1 的结论：**文本宽度必须来自实际渲染端**，Python 端算完跨端复用会撞上
emoji 位图字体的 advance 差异（0.24%，随 emoji 数量累积）。L3 的结论：字族回退是两端
各自实现的**规范**，不是 IR 的请求。所以 text 节点只有：

| 字段 | 形状 | 含义 |
| --- | --- | --- |
| `texts` | (n,) str | 要画的字符串 |
| `pos` | f4 (n,2) | 锚点坐标（已按 anchor/baseline 对齐后的最终位置） |
| `width` | f4 (n,) | 最终文本宽度，pt |
| `font` | str | 已解析的**单个**字族 key（不是 font stack，不含回退链） |
| `size` | float | 字号 pt |
| `anchor` | "left" / "center" / "right" | `pos` 指文本的哪一边 |
| `baseline` | "top" / "middle" / "bottom" / "alphabetic" | 竖直锚定方式（不是数值偏移） |
| `angle` | float | **局部**旋转角，度（逆时针，绕 `pos`；**不含视口旋转**） |

`angle` 的口径（SIL-634）：视口旋转已经在祖先 `viewport.transform` 的线性部分里，
`text.angle` 只表达 grob 自己的 `rot`。设备按「先合成 `transform`，再绕锚点转
`angle`」落字，所以页面上的最终方向 = 视口旋转 ∘ `angle`：

| 写方给的 | `angle` | 页面方向 |
| --- | --- | --- |
| 视口 20° + `rot = 0` | 0 | 20° |
| 无旋转视口 + `rot = 40` | 40 | 40° |
| 视口 20° + `rot = 20` | 20 | 40°（两段各算一次） |

写方**不要**把视口旋转预乘进 `angle`——那是重复应用（`docs/notes/grobs.md` §7.1
记的就是这次修正）。

消费方算包围盒 / hover 命中区时必须把 `angle` 一起用上（绕 `pos` 转 `width × 行高`
那个盒子）；只看 `pos` 与 `width` 会把它当成轴对齐的水平条。M2-S1 修的就是查看器
这一处，`tests/test_viewer.py::test_rotated_text_bbox_follows_the_rotation` 钉住。

**不携带**测量意图：没有 `font_stack` / `fallback` / `glyphs` / `advance` / `shaping` /
`hjust` / `vjust` 之类的字段（`tests/test_ir.py::test_text_node_carries_no_measurement_intent`
逐名断言，加这类字段会红）。逐元素的 hjust/vjust 差异由写 IR 的一方折进 `pos`。

多行（SIL-655）：`texts` 里允许 `\n`，`width` 是**各行的最大推进**，`pos` 与
`anchor` / `baseline` 对整块。渲染端按 grid 的缺省 `lineheight = 1.2` 切行
（绘制行距 `1.2 × lineheight × size` = 1.44 × size），整块高度用 R 的
`strheight`（cap height）。IR 目前**没有** `lineheight` 字段，非缺省行距与
小数 `hjust/vjust` 表达不了——这是 M1 已知缺口（`metrics-ledger.md` · M1-b）；
要支持时加字段并升 IR 版本，不在这条节点上偷偷塞参数。

渲染端拿 `width` 做对齐与差分统计；它自己排出来的宽度如果和 IR 里的 `width` 有差
（不同字体版本、emoji strike），按 `docs/notes/snapshot-policy.md` 的文字容差处理，
不回写 IR、不做二次测量。

## 8. blob 表

- 位置：`scene.blobs`，`id → {mime, data}`；`raster` 等节点用 `params.blob` 引用。
- **内容寻址**：`id = "sha256:" + sha256(mime + b"\0" + data).hexdigest()`（`blob_id()`）。
  同一份字节 + 同一个 mime 在任何机器上同 id，所以编码确定、重复内容不会进表两次。
  mime 参与哈希：同样的字节按不同 mime 引用是两个 blob。
- **mime 缺省**：解码时缺 `mime` 或为 null → `application/octet-stream`；编码总是写出 mime。
- 编码按 id 排序写出，表内插入顺序不影响字节。
- **不做压缩、不做 base64**；大 blob 原样通过（用例覆盖 4 MiB）。
- 表里可以有不被引用的 blob（删除节点时不必同步清理），但节点引用了**不存在**的 id
  会在构造 `Scene` 时直接报错。
- 本阶段不打包字体文件：字体由两端各自按 `font` key 解析（M0-7 的受管字体目录）。

## 9. 确定性

同一 scene 两次编码字节完全一致，规则：

1. canonical CBOR（键排序）；
2. 参数 / gpar 只写非缺省字段（缺省值由 `NODE_SPECS` 单点定义）；
3. blob 表按 id 排序；
4. 不含时间戳、随机 id、运行环境信息；
5. 缓冲直接取 numpy 的 C 连续原始字节（无字典序、无浮点格式化）。

6. **写进字节的浮点先量化到固定十进制网格**：参数与 `gpar` 是 10 位
   （`ggcore.ir.nodes.PARAM_DECIMALS`），缓冲是 1e-6（`BUFFER_DECIMALS`），
   `coord_trans` 的变换结果是 1e-12（`ggcore.coord.TRANSFORM_DECIMALS`）。

门禁 `pixi run gate:determinism` 用三个不同 `PYTHONHASHSEED` 的进程编码同一个
`demo_scene()`，比较 stdout（digest / 字节数）；子进程同时做 `encode(decode(data)) == data`
自检。

### 跨机器确定性（SIL-824 返工）

第 6 条不是为了省字节，而是为了**换一台机器也逐字节相同**。2026-11-05，`gate:pyodide`
在本机 515/515 全绿，在 CI runner 上有 3 条 `coord_sf` case 两端 IR 不一致：同长度、
不同 sha256，差在 `viewport.transform` 的平移量末位。

链条是这样的：`coord_sf` 的 `1 / cos(lat)` 比例 → 面板版式 → `transform` 的 cm→pt 平移，
而 `cos` 来自宿主 libm。glibc 的不同版本、不同 CPU、emscripten 的 libm 在同一输入上
会差 1 ULP（1e-16 相对），经比例放大后仍然是 1e-13 量级的 pt 差——渲染上看不见，
但足以翻过 double 的末位。

所以「进 IR 的浮点」一律先量化：1 ULP 级的差要么被舍掉，要么需要恰好落在十进制网格
边界 ±1e-16 内才会翻一格（概率 ~1e-4/值）。量化网格与实现无关：`round()` 对 float 是
正确舍入的十进制转换，不经过 libm。

同一类问题还有两处**离散**判定（量化吸收不了，必须单独处理）：

| 位置 | 判定 | 处理 |
| --- | --- | --- |
| `ggcore.munch.munch_steps` | `ceil(distance / segment_length)` 的段数 | 先把商舍到 1e-6 再 `ceil` |
| `ggcore.axis_guide.polar_axis_grobs` | `90° < angle < 270°` 的标签翻面 | 先把角度舍到 1e-6 再比较 |
| `ggcore.sf.st_transform_xy` | 投影坐标（窄面板会放大） | 投影结果舍到 1e-5 m / 1e-7° |

`pixi run gate:libm-noise` 把 `math` / `numpy` 的三角与指数函数整体偏 ±1 ULP（三种
方向），把全部 case 再跑一遍：任何一条的 sha256 变了就红。它不需要 CI，也不需要
第二台机器——这是「换一台 runner」在本机能做的最接近的代理。

## 10. 体积：10k 点 path vs 逐元素 JSON

`pixi run ir:size`（`tools/ir_size_report.py`，固定种子、10,000 个顶点、一份 path 节点）：

| 表示 | 字节 | 每点 | IR 小多少 |
| --- | ---: | ---: | ---: |
| IR（CBOR + float32 缓冲） | 80,187 | 8.02 B | — |
| JSON `[[x, y], …]`（float64 文本，信息无损） | 412,816 | 41.28 B | **5.15×** |
| JSON `[{"x":…,"y":…}, …]`（每点带字段名） | 492,816 | 49.28 B | **6.15×** |
| JSON `[[round(x,4), round(y,4)], …]`（**丢精度**） | 167,872 | 16.79 B | 2.09× |
| JSON 里塞 base64(float32)（同样的位串） | 106,668 | 10.67 B | 1.33× |

结论写清楚，别把话说大：

- **信息无损**的 JSON 基线（前两行）是 5.2–6.2×，不是 10×。原因很直白：float32 二进制
  就是 8 B/点，文本十进制最省也要 ~16 B/点（4 位小数），而完整十进制是 41 B/点。
- JSON 想压到 2× 以内只能丢精度（第三行），那已经破坏了“float32 逐位一致”这条验收；
  base64 是“把同样的位串塞进 JSON”的最好情况，仍比 CBOR 大 33%，而且还要额外容器。
- 所以“禁止逐元素 JSON”这条门禁（X1）站得住：不是为了 10× 的营销数字，而是 5× 起步、
  且是**唯一**能保住逐位精度的表示。314 份快照的规模下这个差值是几百 MB 的量级。

### 10.1 渐变 / 图案的账（v0.4）

色标是「一个小结构」而不是 bulk 数据，但仍然按缓冲写（一条 f4 `(n, 5)`，20 B/档），
所以档数线性增长、没有逐档的映射开销。数字由 `pixi run ir:size` 打印
（`tools/ir_size_report.py::fill_sizes`，量法写在函数 docstring 里，可复跑）：

| fill | fill 值 CBOR | 承载它的 `gpar` 段 | 逐档 JSON | 说明 |
| --- | ---: | ---: | ---: | --- |
| 纯色 `[r, g, b, a]` | 9 | 21 | — | 与 v0.2 完全一致（不含键名，键名由 gpar 映射承担） |
| 2 档线性渐变 | 120 | 132 | 159 | 每多一档 +20 B |
| 3 档线性渐变 | 140 | 152 | 200 | |
| 10 档线性渐变 | 280 | 292 | 517 | |
| 3 档径向渐变 | 140 | 152 | 197 | 多一个 `radius` / 可选 `focal` |
| 图案（1 个内容矩形） | 146 | 158 | — | 图案的体积由**内容节点**决定，不含位图 |

三列口径（同一份 wire，三种外层装法）：

- **fill 值 CBOR**：`gpar.fill` 这个**值本身**的 canonical CBOR，**含** `kind` 与
  `extend`（缺省也显式写，读方不用猜），不含承载它的 `fill` 键名。上一版表的
  120 / 140 / 280 就是这个口径，但表里既没说清、又把 `3 档径向` 误写成 152
  （152 是下一列的数）、`图案` 误写成 170（实测 146）——SIL-767 §4 的错数来自这里。
- **承载它的 `gpar` 段**：真实节点里新增的 `"gpar": {"fill": …}` 总字节
  （映射头 + 两个键名），也就是「加一条渐变填充」在图里实际贵多少。
- **逐档 JSON**：同一条 fill 写成 JSON 文本（`{"kind":…,"stops":[{"offset":…,
  "colour":[r,g,b,a]}, …]}`）的字节数，用来说明「20 B/档」不是营销数字。

结论：渐变不是体积风险，档数再多也只是 20 B/档；图案内容是普通 IR 节点（缓冲仍然是
float32），不引入第二套坐标系，也不往 blob 表里塞位图。

## 11. 错误类型

| 异常 | 何时 | 调用方怎么处理 |
| --- | --- | --- |
| `IRValidationError` | 构造节点/scene 时字段不合法（类型、形状、交叉约束、缺省必填） | 写方 bug，直接修 |
| `IRDecodeError` | 线格式坏：缺 magic、截断、字段类型不符、未知节点/字段 | 拒收，不要猜 |
| `IRVersionError` | `ir_version` 的 major 不认识（`IRDecodeError` 子类） | 提示升级渲染端 |

解码时构造 `Scene` 期间的校验错误会包成 `IRDecodeError`，所以“读不进来”只需捕一个类型。

## 12. 明确不做（留给后续 minor / major）

- **箭头**（`arrow()`）：M0-6 落地真实箭头需求时按 minor 加 param，不预留空字段。
- **渐变描边**：`col` 只有纯色；渐变 / 图案只做 `fill`（§6.1）。加渐变描边按 minor
  扩 `col` 的联合类型，渲染端要各自补一条描边画笔。
- **组级不透明度 / 混合模式**：`gtree` 在 v0 只是顺序容器。
- **glyph run / 字体文件表**：如果 M0-8 的 PDF 需要“字体随 IR 走”，届时定 blob 里的字体约定；
  现在按 `font` key 两端各自解析。
- **布局信息**（gtable 单元格、null 单位分配结果）：写 IR 前消费掉，不进 IR。
- **上游 SVG 结构对齐**：IR 不对标 svglite 的 DOM 结构（对齐走像素 diff，见 snapshot-policy）。

### 12.1 查看器需要的字段（缺口表）

M1-13 的浏览器查看器（`docs/notes/viewer.md`）只能在现有字段上做**推断**。下面是
它想要、但 v0 没有的东西；真要支持就按 §3 加字段升版本，本任务不改 schema：

| 缺的字段 | 查看器现在的做法 | 进 IR 的话 |
| --- | --- | --- |
| 节点 id / 稳定标识 | 用索引路径 `0/3/2` 当 id | 节点或容器参数里加 `id` |
| geom 层名 / layer 序号 | 按图元 kind 推断（`points`→point、`rect`→bar） | `node.layer` 或写方补 `gtree.name` |
| 原始数据行号 | 显示缓冲行号（`bufs[k]` 的行下标） | 节点带「行 → 原始数据下标」的表 |
| 图例 entry 归属（key ↔ 标签 ↔ 图层） | 视口名前缀 + 页面包围盒纵向对齐 | guide entry 字段，或把 key/标签合成一个具名容器 |
| 图例 level → 数据行 | 不做（点图例只隐藏图例组本身） | 同上，需要 level 到行的映射 |
| `text.lineheight` / 非缺省行距 | 固定 grid 缺省 1.2（§7 已记 M1-b） | `text.lineheight`（minor） |
| 字符型 `points.pch`（32..127 / 负数） | 只画 0..25 的几何符号；字符型不猜 | 要么写方先转 `<text>`，要么 IR 带字体引用 |
| 图案内嵌文字 / 位图 | 不支持（`pattern.content` 只收几何图元） | `pattern.content` 放开到 `text` / `raster`，并把字体 / blob 约定带进去 |

查看器的逐项支持状态（支持 / 降级 / 不支持）见 `docs/notes/viewer.md` §10.1。

## 13. 复现

```bash
pixi run test                      # 含 tests/test_ir.py
pixi run gate:determinism          # 跨进程字节一致（真实 scene）
pixi run ir:size                   # §10 的体积表
pixi run bench                     # 编解码基准
pixi run viewer:build              # 浏览器查看器的 tsc 产物（M1-13）
```
