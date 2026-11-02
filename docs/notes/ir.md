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
  "ir_version": [0, 2],
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

- 常量：`IR_VERSION = (0, 2)`、`IR_VERSION_STR = "0.2"`，编码时写进 `ir_version`。
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
| `segments` | 独立线段 | `segments` f4 (n,4) | — |
| `polyline` | 单条/多条折线 | `points` f4 (n,2)；`id` 可选 | — |
| `polygon` | 多边形 | `points` f4 (n,2)；`id` 可选 | — |
| `path` | 多条子路径 + 填充规则 | `points` f4 (n,2)；`id` 可选 | `rule`="winding" |
| `points` | 散点 | `points` f4 (n,2) | `pch`=1、`size`=1.0（pt） |
| `text` | 文本（见 §7） | `pos` f4 (n,2)、`width` f4 (n,) | `font`、`size` 必填；`anchor`="center"、`baseline`="middle"、`angle`=0 |
| `raster` | 位图 | `rect` f4 (1,4) | `blob`、`width` ≥1、`height` ≥1 必填；`interpolate`=true |
| `xspline` | xspline | `points` f4 (n,2)；`id` 可选 | `shape`=0.0（-1..1）、`open`=true |
| `bezier` | 三次贝塞尔段 | `control` f4 (4n,2)，每 4 行一段 | — |
| `curve` | grid.curve | `ends` f4 (n,4) = (x1,y1,x2,y2) | `curvature`=1、`angle`=90、`ncp`=1、`shape`=0.5、`square`=true、`inflect`=false、`open`=true |
| `null` | nullGrob：不画、不占位 | — | — |
| `zero` | zeroGrob：不画，参与布局 | — | — |

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
- 解码用 `np.frombuffer` 直接看线格式里的 bytes，不复制；形状与字节长度不符直接报错。
- 允许缓冲里出现 NaN / ±Inf / -0.0（缺失点、断线用 NaN 表达），但**参数字段**必须是有限值。
- **设备输入就是本格式的 `Scene`**：`ggcore.grobs.Scene` 的 `Instruction.bufs` 是
  遍历期的 float64 中间形态，**不进设备接口**——要出图先
  `scene(...).to_ir_scene()`（一次性 float32 舍入）。设备只读 IR，所以不会在
  float64 与 float32 两边各背一份几何（`docs/notes/grobs.md` §7.2）。

## 6. gpar

| 字段 | 类型 | 缺省 | 说明 |
| --- | --- | --- | --- |
| `fill` | RGBA 整数元组 (0..255) 或 null | null | 不填充 |
| `col` | RGBA 整数元组或 null | null | 不描边；`text` 的文字颜色也用 `col` |
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

门禁 `pixi run gate:determinism` 用三个不同 `PYTHONHASHSEED` 的进程编码同一个
`demo_scene()`，比较 stdout（digest / 字节数）；子进程同时做 `encode(decode(data)) == data`
自检。

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

## 11. 错误类型

| 异常 | 何时 | 调用方怎么处理 |
| --- | --- | --- |
| `IRValidationError` | 构造节点/scene 时字段不合法（类型、形状、交叉约束、缺省必填） | 写方 bug，直接修 |
| `IRDecodeError` | 线格式坏：缺 magic、截断、字段类型不符、未知节点/字段 | 拒收，不要猜 |
| `IRVersionError` | `ir_version` 的 major 不认识（`IRDecodeError` 子类） | 提示升级渲染端 |

解码时构造 `Scene` 期间的校验错误会包成 `IRDecodeError`，所以“读不进来”只需捕一个类型。

## 12. 明确不做（留给后续 minor / major）

- **箭头**（`arrow()`）：M0-6 落地真实箭头需求时按 minor 加 param，不预留空字段。
- **渐变 / 图案笔刷**：`fill` 目前只有 RGBA；渐变要么进 gpar 的联合类型（minor），要么进 blob。
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
| 渐变 / 图案笔刷 | 按 256 条细矩形画（M2 的实现缺口） | `fill` 的联合类型或 blob（§12 已记） |

查看器的逐项支持状态（支持 / 降级 / 不支持）见 `docs/notes/viewer.md` §10.1。

## 13. 复现

```bash
pixi run test                      # 含 tests/test_ir.py
pixi run gate:determinism          # 跨进程字节一致（真实 scene）
pixi run ir:size                   # §10 的体积表
pixi run bench                     # 编解码基准
pixi run viewer:build              # 浏览器查看器的 tsc 产物（M1-13）
```
