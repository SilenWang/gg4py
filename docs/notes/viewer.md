# 浏览器查看器（M1-13）：IR → DOM SVG

`web/viewer/` 是 M1 的第二条渲染腿：桌面 / 服务端走 `ggskia`（PNG / SVG / PDF），
浏览器走 **纯 TS + DOM SVG**。零 wasm、零打包器、零运行时依赖——`tsc` 把几份
`.ts` 编成 ES module，`index.html` 直接 `<script type="module">` 加载。

IR 已经是「已解析几何」（`docs/notes/ir.md`）：单位、gpar 继承、视口变换、字体
度量都在写 IR 之前完成。所以查看器不做测量、不做布局，只做**翻译**——这也是它
只有几百行 TS 的原因。

```bash
pixi run viewer:build     # npm install typescript + tsc → web/viewer/dist/（不入库）
pixi run viewer:sample    # 2×2 分面 + 图例 → web/viewer/samples/*.ggir.cbor
pixi run viewer:shot      # 真 Chromium 打开 index.html 截图（--hover 带 tooltip）
pixi run viewer:browsers  # 装 Playwright 的 Chromium（$HOME 只读 → 装在仓库里）
pixi run viewer:cases     # 61 条案例逐条过 viewer + 与 expected.svg 像素对拍 + gallery
```

手测：起一个静态服务器（`file://` 下浏览器会拦 ES module），打开
`web/viewer/index.html`，把 `.ggir.cbor` 拖进页面或点「打开文件」。工具栏会报
节点数 / 图元数 / 图例项数；解码失败时报错文本带节点 id。

## 1. 模块

| 文件 | 职责 |
| --- | --- |
| `src/ir.ts` | CBOR 解码（只读）+ IR v0 字段校验，错误带节点 id（`0/3/2`） |
| `src/render.ts` | IR → SVG 元素；烘焙坐标、裁剪、gpar 样式、pch 字形 |
| `src/curves.ts` | `xspline` / `curve` 的 R 公式移植（与 `ggskia.curves` 同一套） |
| `src/interact.ts` | hover tooltip、图例 key 开关（节点组隐藏 / 显示） |
| `src/main.ts` | 文件加载（拖拽 + `<input type=file>`）、状态栏、错误展示 |

`main.ts` 还认 `index.html?scene=gallery/<case>.ggir.cbor`：gallery 的卡片用它自动
打开同一张图和同一套 hover / 图例交互。`scene` 是**相对 viewer 根目录**的路径，
所以图片 / IR 资产放在 `<viewer>/gallery/`（`tools/viewer/cases.py` 的
`gallery_assets_dir()`），卡片链接是 `../index.html?scene=gallery/...`。

## 2. IR kind → SVG 元素

| kind | 产出 | 说明 |
| --- | --- | --- |
| `viewport` | `<g>` +（`clip=true` 时）`<g clip-path>` | 裁剪层不带 transform，见 §3 |
| `gtree` | `<g>` | 纯分组 |
| `clip` | `<clipPath>` + `<g clip-path>` | `rect` 一行的矩形或 `points`+`id` 的多子路径 |
| `rect` | 每行一个 `<rect>`；旋转视口下降级为 `<path>` | `x0>x1` 时归一化 |
| `circle` | 每行一个 `<circle>`；非等比变换时用 `<path>` | 半径在视口单位下 |
| `lines` / `polyline` | 一个 `<path>`（`fill="none"`） | `id` 变化切子路径，NaN 断开 |
| `polygon` | 一个 `<path>`（闭合、可填充） | 同上 |
| `path` | 一个 `<path>` + `fill-rule` | `winding` → `nonzero`，`evenodd` → `evenodd` |
| `segments` | 一个 `<path>`，每行一条 `M…L…` | 线段互不相连 |
| `points` | 一个 `<path>`：所有行的 pch 子路径拼进同一个 `d` | 节点级元素，见 §5 |
| `text` | 每行一个 `<text>`（多行用 `<tspan>`） | 见 §4；字体 face 后缀翻成 `font-weight` / `font-style` |
| `raster` | 每行一个 `<image>`，`href` 是 blob 的 data URL | `interpolate=false` → `image-rendering:pixelated` |
| `xspline` / `bezier` / `curve` | 一个 `<path>` | 与设备同一套公式，见 §6 |
| `null` / `zero` | 不产出元素 | 布局语义在写 IR 前已消费 |

gpar → SVG：

| gpar | SVG |
| --- | --- |
| `fill` / `col` | `fill` / `stroke`（`#rrggbb`）+ `fill-opacity` / `stroke-opacity` |
| `alpha` | 乘进上面两个 opacity（`alpha × a/255`） |
| `lwd` | `stroke-width`（pt × 变换的平均缩放 √\|det\|） |
| `lty` | `stroke-dasharray`（同样按缩放折算） |
| `lineend` / `linejoin` / `linemitre` | `stroke-linecap` / `stroke-linejoin` / `stroke-miterlimit` |

## 3. 坐标与裁剪

口径来自 `docs/notes/ir.md` §1 / §4：

- 页面 y 向下、原点左上、单位 pt；`viewport.transform` 是**子坐标 → 父坐标**，
  沿树自下而上合成出页面变换。
- `viewport.clip_rect` 是**页面绝对坐标**，不跟 `transform` 走。

所以查看器把几何**烘焙到页面坐标**（矩阵乘进每个顶点），容器 `<g>` 一律不带
`transform`，裁剪 `<g clip-path>` 里放的就是页面矩形。需要保留局部方向的叶子
（文字、位图）只在自己的元素上带一个 `transform`——它们下面没有子节点，不会把
页面坐标语义带歪。嵌套视口的裁剪因此就是若干页面矩形的交集，与写 IR 时算出的
生效裁剪框一致。

线宽 / 虚线是局部单位下的 pt（设备在 `concat` 之后画），烘焙后按 √|det| 折算，
与 `ggskia` 的 `canvas.concat()` 口径一致。

## 4. 文字

IR 的 `text` 只带**最终宽度**与锚点（`ir.md` §7）：`pos`、`width`、`font`、
`size`、`anchor`、`baseline`、`angle`。查看器：

- `anchor` → `text-anchor: start / middle / end`；
- `baseline` → `dominant-baseline: text-before-edge / central / text-after-edge / alphabetic`；
- `angle` 是绕锚点的局部旋转（逆时针），SVG 的 `rotate()` 在 y 向下时是顺时针，
  所以写 `rotate(-angle)`；元素变换是 `matrix(页面变换) translate(pos) rotate(-angle)`；
- 多行按 grid 的缺省 `lineheight = 1.2` 切 `<tspan>`，行距 `1.44 × size`；
- `font` 是已解析的单个字族 key，浏览器补系统栈：
  `"<font>", "Noto Sans CJK SC", "DejaVu Sans", sans-serif`。

**不**用 `textLength` 去强行对齐 IR 的 `width`：拉伸字形会破坏观感，宽度差异按
`docs/notes/snapshot-policy.md` 的文字容差处理（与桌面设备同一套账）。

## 5. 散点（`points` / pch）

`pch` 在 IR 里是 grid 的编号，字号是 `size`（pt）。查看器按 R `engine.c` 的常量
画：符号半径是 `RADIUS × size`（`RADIUS = 0.375`，直径是 `size` 的 3/4），
**不是** `size / 2`。三角形用 `TRC0/TRC1/TRC2`，菱形 / 方 / 小圆分别用
`SQRC` / `DMDC` / `SMALL`，与 `src/ggskia/pch.py` 逐项一致（`tests/test_viewer.py`
的 `test_every_pch_matches_ggskia_geometry` 逐顶点守住 0..25）。两处容易混的
口径：pch 2 / 6 / 17 / 24 / 25 的底边在 `TRC2 × radius`；只有 pch 11 的双三角
用 `0.5 × (TRC2 + TRC0) × radius` 贴合。pch 14 是普通 `±RADIUS` 三角 + 方，
不走 `TRC`。覆盖：

**一个 `points` 节点只出一个 `<path>`**：每行一条 `M…Z` 子路径，样式统一写在
节点元素上（同一节点的 gpar 相同）。`data-kind` / `data-row` 是节点级，
`data-rows="0-9999"` 给出缓冲行范围——10k 行也只占 1 个 DOM 元素，与 IR 的
bulk 口径一致。hover 因此只到节点粒度（见 §9）。

| pch | 字形 | 画法 |
| --- | --- | --- |
| 0 / 1 / 2 / 5 / 6 | 方 / 圆 / 上三角 / 菱形 / 下三角 | 空心（`stroke`） |
| 3 / 4 | 加号 / 叉 | 只描边 |
| 7 / 8 / 9..14 | 方+叉、叉+加、菱形+加、圆+加、上下三角、方+加、圆+叉、上三角+方 | 按 R 的组合字形 |
| 15 / 16 / 17 / 18 / 19 / 20 | 实心方 / 圆 / 三角 / 菱形 / 圆+同色描边 / 小圆 | 用 `col` 填充（grid 的实心 pch） |
| 21..25 | 实心 + 边框 | `fill` 填充 + `col` 描边；22 / 23 的边长取 `SQRC` / `DMDC` |

字形只用绝对 `M` / `L` / `C` / `Z`，不用 `A`（圆弧的 rx/ry/flag 不是坐标，
套变换会写出非法 `d`）。

## 6. 曲线原语

`src/curves.ts` 是 `src/ggskia/curves.py` 的逐函数移植（后者是 R
`src/main/xspline.c` 与 `grid:::calcCurveGrob` 的移植），采样密度、步长公式、
开/闭控制点窗口都一致。`curve` 先把页面坐标翻成 R 坐标求值、再翻回来
（`ggskia.skia._draw_curve` 的 SIL-636 口径）。

| kind | 查看器实现 | 状态 |
| --- | --- | --- |
| `bezier` | 每 4 个控制点一段三次贝塞尔，原样映射 | 精确 |
| `xspline` | X-spline 混合函数 + 按曲率估步长的折线采样 | 精确（与设备同一套公式） |
| `curve` | `ncp` / `shape` / `square` / `inflect` 控制点 + xspline 采样 | 精确（`geom-curve-basic` 0.02%） |

曲线按折线采样，不改变节点数 / 裁剪 / 颜色；`viewer:cases` 会把形状差异直接量成
像素差。

## 7. 交互：hover 与图例开关

**hover**：鼠标命中叶子（带 `data-row` 的元素）→ tooltip 显示
`<具名视口> · <geom 层>`、`节点 <id> · 数据行 <行>/<总行>`、文本内容。整节点
合成一个元素的图元（`points` / `segments`）显示 `数据行 1–<总行>` 的整段范围。

- 具名视口来自 IR 的 `viewport.name`。`Scene.to_ir_scene()` 现在把**最深视口名**
  （`panel-1` / `guide-0-key-0` / `axis-x-1`）写进这个字段——字段本来就在 schema
  里，此前被写方丢掉了；
- geom 层名是**推断**的：IR v0 没有层名字段，按图元种类映射
  （`points`→point、`polyline`→line、`rect`→bar/col…）；
- 数据行是该节点缓冲里的行号（`0` 起显示为 `1` 起）。IR 没有“原始数据行号”，
  这是几何行号。

**图例**：名字形如 `<guide>-key-<i>` 的视口就是图例 key 的节点组（R 的
`guide-<i>-key-<k>` 视口）。点击：

1. 组上写 `data-hidden="true"` / `aria-pressed="true"`；
2. 组内图元（key 字形）与同一 guide 里**纵向对齐**的底框 / 标签文字一起 `display:none`；
3. 组里盖一块透明热区（`.gg-legend-hit`），所以关掉以后同一位置还能点回来；
4. 工具栏「重置图例」把全部条目恢复。

作用域只有图例本身：**不会**隐藏面板里的数据——IR 没有「图例 level → 数据行」
的映射，硬猜就是错的（`docs/notes/ir.md` §12 的缺口表）。

## 8. 与桌面 SVG 设备的已知差异

| 方面 | 桌面（`ggskia` SVG） | 浏览器（本查看器） | 影响 |
| --- | --- | --- | --- |
| 文字 | 用受管字体度量，必要时按字步写 `tspan` | 同一份受管字体（`fonts.css` 的 `@font-face`，由 `tools/viewer/emit_fonts.py` 从 rules.json 生成）+ 正常排版 | 字宽 / 字面在浏览器里可能有 1 px 级差；对拍口径与桌面同一套 |
| 文字基线 | cap height × 72.27/72（R 的 `strheight`） | 浏览器用 `dominant-baseline`；diff 侧按 `data-baseline` 还原同一 cap 口径 | gallery 截图有亚像素差；像素对拍不受影响 |
| 多行行距 | grid 的 `lineheight`（IR 未携带） | 固定 1.2 | 非缺省行距表达不了（`ir.md` §7 · M1-b） |
| 复合 pch | `ggskia.pch` 的精确符号 | 同一套 `RADIUS` / `TRC` / `SQRC` / `DMDC` 常量（§5） | 无 |
| `xspline` / `curve` | `ggskia.curves` 的公式 | 同一套公式的 TS 移植（§6） | 无 |
| 结构 | 每个 IR 节点一段 `<g>`，几何在局部坐标 | 几何烘焙到页面坐标，容器不带 transform | 像素等价，DOM 结构不同（IR 不承诺对齐 svglite，`ir.md` §12） |
| 交互 | 无 | hover / 图例开关 | 只存在于浏览器 |

## 9. 缺口（IR v0 里没有、查看器只能推断的东西）

这些字段一旦进 IR 就要按 `docs/notes/ir.md` §3 升版本；本任务**不改 schema**，
只记在这里与 `ir.md` §12 的缺口表：

| 缺口 | 现在怎么办 | 真要支持需要什么 |
| --- | --- | --- |
| 节点 id / 稳定标识 | 用索引路径 `0/3/2` 当 id | `node.id`（字符串或整数） |
| geom 层名 / layer 序号 | 按图元 kind 推断（`points`→point） | `node.layer` 或容器参数 |
| 数据行号（原始数据） | 显示缓冲行号 | `node.rows` 索引表 |
| 图例 entry 归属（key ↔ 标签 ↔ 图层） | 名字前缀 + 纵向对齐推断 | guide entry 字段或 key 组命名约定入 schema |
| 图例点击 → 隐藏数据系列 | 只隐藏图例组本身 | level → 数据行 的映射 |
| 多行行距 / `lineheight` | 固定 1.2 | `text.lineheight` |
| 字体文件 | 受管字体副本（`web/viewer/fonts/`，`viewer:build` 从 `$CONDA_PREFIX/fonts` 复制；`font-family` 回退栈只含 rules.json 里的字族，**不含 `sans-serif`**） | 字体 blob 表（`ir.md` §12） |
| 逐行 hover（单点 tooltip） | 节点级：`points` 一个节点一个 `<path>`，tooltip 给整段行范围 | 同一 path 内给子路径标 `data-row` + JS 命中测试（`elementFromPoint` 拿不到子路径），待 M2 |

## 10. 案例对拍（M1-16）

`pixi run viewer:cases` 把案例库逐条走一遍浏览器，并给出可执行的判据：

```
plot.py → ggcore.plotspec → IR(.ggir.cbor)
        → Playwright/Chromium 打开 index.html
        → 取回渲染后的 DOM SVG（补白底）
        → 与 expected.svg 一起：<text> → 受管字体轮廓 → resvg --dpi 72
        → 图级 ≤ 各 case 的 tolerance.png（缺省 2%）、均值 ≤ 1%
```

产物在 `.viewer-cases/`（不入库）：逐 case 的 IR / SVG / PNG、`report.md` /
`report.json`；gallery 在 `web/viewer/dist/gallery.html`，卡片链到
`../index.html?scene=gallery/<case>.ggir.cbor`（资产在 `web/viewer/gallery/`），
点进去就是同一套 hover / 图例开关。

2026-11-02 全量结果（61 条三文件 case）：**pass 61 / fail 0 / error 0 / skip 0**。
SIL-723 之后 `theme-grey-basic` / `theme-minimal-basic` / `guide-colourbar` 也翻成
`ci = true`：三条分别是 1.79% / 1.76% / 1.67%（viewer 侧）。

### 10.1 支持矩阵

行 = IR 节点 / 参数，列 = 查看器状态。`降级` 表示画得出但有意与设备不同（已在
§8 记账）；`不支持` 表示 IR v0 没有该字段或本 viewer 不猜（`ir.md` §12.1）。

| IR 节点 / 参数 | 状态 | 说明 |
| --- | --- | --- |
| `viewport` `transform` / `clip` / `clip_rect` / `name` | 支持 | 页面坐标烘焙；`clip_rect` 是页面绝对坐标，嵌套即矩形交集 |
| `gtree` / `null` / `zero` | 支持 | 顺序容器 / 不产出元素 |
| `clip` `rect` / `points`+`id` / `rule` | 支持 | `rect` 一行一个矩形；`points` 按 id 切子路径，`winding` / `evenodd` 原样 |
| `rect` | 支持 | 轴对齐 → `<rect>`；旋转 → `<path>`；`x0>x1` 归一化 |
| `circle` | 支持 | 等比 → `<circle>`；非等比 → `<path>` |
| `lines` / `polyline` / `polygon` / `path` | 支持 | `id` 变化切子路径，NaN 断开；`path` 带 `fill-rule` |
| `segments` | 支持 | 每行独立 `M…L…`，不连成折线 |
| `points` `pch` 0..25 / `size` | 支持 | R 的 `RADIUS=0.375`、`TRC` / `SQRC` / `DMDC` / `SMALL` 常量；一个节点一个 `<path>` |
| `points` `pch` 字符型（32..127 / 负数） | 不支持 | IR 写方目前只产出 0..25；字符型需要 IR 带字体或写方转 `<text>` |
| `text` `font` / `size` / `anchor` / `baseline` / `angle` | 支持 | `font` 的 `:bold` / `:italic` / `:bold-italic` 后缀翻成 CSS face；多行按 1.44×size |
| `text` 多行 | 支持 | 每行一个 `<tspan>`；锚点按整块（top / middle / bottom） |
| `text` 非缺省 `lineheight` | 不支持 | IR v0 没有字段（`ir.md` §7 · M1-b） |
| `raster` `blob` / `rect` / `mime` / `interpolate` | 支持 | blob → data URL；`interpolate=false` → `image-rendering:pixelated` |
| `xspline` `shape` / `open` | 支持 | `curves.ts` 的 X-spline 移植，采样密度与设备一致 |
| `bezier` | 支持 | 每 4 个控制点一段三次贝塞尔 |
| `curve` `curvature` / `angle` / `ncp` / `shape` / `square` / `inflect` / `open` | 支持 | 先翻 R 坐标求值再翻回页面坐标（SIL-636） |
| gpar `fill` / `col` / `alpha` | 支持 | `#rrggbb` + `fill-opacity` / `stroke-opacity` |
| gpar `lwd` / `lty` / `lineend` / `linejoin` / `linemitre` | 支持 | 线宽 / 虚线按 √\|det\| 缩放；linecap / linejoin / miterlimit 原样 |
| 渐变 / 图案 / mask / 箭头 | 不支持 | IR v0 没有这些字段（`ir.md` §12）；渐变条按实现缺口归 M2 |
| 嵌入字体文件 | 不支持 | 浏览器用系统栈；diff 侧用受管字体转轮廓（§8） |
| 图例 key → 数据系列 | 降级 | 只隐藏图例组本身，IR 没有 level → 行映射 |
| 逐行 hover（bulk `points`） | 降级 | 节点级 tooltip，给 `1–N` 行范围；M2 做子路径命中 |

## 11. 测试

`tests/test_viewer.py`（Playwright + 真 Chromium）：

1. 夹具本身有 4 个面板 + 3 个图例 key；
2. **渲染完整**：SVG 里 `<rect>` / `<path>` / `<text>` / `<image>` 的数量与 IR
   图元行数逐类相等（这张图上三类主元素也等于节点数）；
3. **图例开关**：点 key → `data-hidden="true"`、key 图元不可见、同一行的标签
   一起隐藏；再点回来恢复；
4. **hover**：tooltip 出现且文本含 `panel-1`、`point 层`、`数据行 1/`；
5. **10k 点 bulk**：10000 行的 points 节点只产出 1 个 `<path>`（`d` 里 10000 条
   子路径），DOM 总数 < 100；
6. **零 wasm**：整页请求里没有 `.wasm`；
7. **裁剪口径**：两层嵌套视口的 `clip_rect` 原样落成页面矩形（不乘祖先变换）；
8. **坏 IR**：删掉一个 text 节点的 `size`，页面报错文本含该节点的 id。
9. **pch 0..25**：26 个 `points` 节点的路径顶点与 `ggskia.pch.symbol()` 逐点
   一致（圆比紧包围盒，其余比顶点），容差 0.01pt；
10. **三角形真管线**：`shape` 映射出的 pch 17 散点与图例 key 都在页面上落成
    与 `ggskia` 一致的三角形（不只是合成 IR 里对）。

`tests/test_viewer_cases.py` 用 `viewer:cases` 跑两条真实案例（col + CJK text），
断言汇总、gallery 与零 wasm；它和上面的浏览器测试都要求 `viewer:build`。

CI 走 `pixi run check` 的子集任务 `viewer:cases:ci`（=`--sample 12 --min-pass 12`）：
按族轮转覆盖 12 条代表 case（点 / 柱 / 面积 / 直方图 / 箱线图 / 平滑 / 文本 /
分面 / 图例 / 标度 / 曲线），避免全量 61 条把每个 PR 拖慢。`check` 之前先跑
`viewer:build` / `viewer:browsers`；浏览器缺失时用例 `pytest.skip`（skipped
消息写明装浏览器的任务名），不会把门禁染红。
