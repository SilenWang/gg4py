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
pixi run viewer:cases     # M1-16：61 条 case + grob 快照逐张渲染 + 与桌面/参考对拍
```

`viewer:cases` 的报告写 `.viewer-cases/report.md` / `.json`（不入库）：
每张的 IR 节点数、SVG 图元数、整页 DOM、加载耗时、与 `expected.*` 和桌面 SVG
的像素差（mean / >4/255 / >90/255）。有红 case 时退出码非 0；单张加载 > 5 s
标 `slow`。单张冒烟用 `--only facet-wrap-2x2,grob-raster,grob-text-rot`。

手测：起一个静态服务器（`file://` 下浏览器会拦 ES module），打开
`web/viewer/index.html`，把 `.ggir.cbor` 拖进页面或点「打开文件」。工具栏会报
节点数 / 图元数 / 图例项数；解码失败时报错文本带节点 id。

## 1. 模块

| 文件 | 职责 |
| --- | --- |
| `src/ir.ts` | CBOR 解码（只读）+ IR v0 字段校验，错误带节点 id（`0/3/2`） |
| `src/render.ts` | IR → SVG 元素；烘焙坐标、裁剪、gpar 样式、pch 字形 |
| `src/curves.ts` | `xspline` / `curve` 求值（`ggskia.curves` 的移植，逐点一致） |
| `src/interact.ts` | hover tooltip、图例 key 开关（节点组隐藏 / 显示） |
| `src/main.ts` | 文件加载（拖拽 + `<input type=file>`）、状态栏、错误展示 |

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
| `points` | 默认一个 `<path>`（所有行拼进同一个 `d`）；半透明时每行一个 `<path>` | 见 §5 |
| `text` | 每行一个 `<text>`（多行用 `<tspan>`） | 见 §4 |
| `raster` | 每行一个 `<image>`，`href` 是 blob 的 data URL | `interpolate=false` → `image-rendering:pixelated` |
| `xspline` / `bezier` / `curve` | 一个 `<path>` | 采样与桌面同一份公式，见 §6 |
| `null` / `zero` | 不产出元素 | 布局语义在写 IR 前已消费 |

### 2.1 61 条 case 的实测覆盖（M1-16）

`pixi run viewer:cases` 扫三文件 case（61 条）与 `docs/cases/grob-*/case.json`
（16 条快照），每张都编码成 IR、用真 Chromium 加载、导出页内 SVG，并让同一份
IR 过桌面 SVG 设备；两侧都用 resvg 2× 光栅化后比像素（文字区域按 IR `text`
的边界掩掉，见 §8）。最近一次实测（本仓库 + pixi 锁定环境）：

| 项 | 值 |
| --- | --- |
| 总数 | 77（61 三文件 + 16 grob 快照） |
| pass / fail | **77 / 0** |
| slow（> 5 s） | 0（最慢单张 15 ms） |
| 整批耗时 | 约 16 s |
| `.wasm` 请求 | 0 |
| 与桌面最差 | `grob-path` mean 0.28% / >90 0.52%；`geom-point-basic` 0.23% / 0.49% |
| 与 expected 最差（`ci = true`） | `geom-boxplot-precomputed` >4/255 1.73% |

族 → case 数 / 该族最差的「与桌面 mean」/「与 expected >4/255」：

| 族 | 数 | 与桌面 mean | 与 expected >4/255 |
| --- | ---: | ---: | ---: |
| facet | 4 | 0.009% | 0.43% |
| geom-area | 5 | 0.001% | 0.05% |
| geom-bar | 4 | 0.000% | 0.00% |
| geom-boxplot | 5 | 0.001% | 1.73% |
| geom-col | 5 | 0.000% | 0.00% |
| geom-curve | 1 | 0.000% | 0.06% |
| geom-histogram | 6 | 0.000% | 0.00% |
| geom-line | 3 | 0.001% | 1.02% |
| geom-path | 2 | 0.000% | 0.07% |
| geom-point | 6 | 0.233% | 0.07% |
| geom-smooth | 5 | 0.000% | 0.92% |
| geom-text | 4 | 0.001% | 0.00% |
| guide | 3 | 0.011% | 2.88%（`ci=false`） |
| scale | 5 | 0.013% | 0.04% |
| theme | 3 | 0.009% | 8.56%（`ci=false`） |

IR kind 与真实 case 的对应（`tests/test_viewer.py` 的参数化覆盖表）：

| kind | 真实 case |
| --- | --- |
| `viewport` / `rect` / `points` / `text` | 61 条三文件 case 的主体 |
| `polygon` / `polyline` / `segments` | `geom-area-*` / `geom-line-*` / `geom-boxplot-*` |
| `curve` | `geom-curve-basic` |
| `raster` / `xspline` / `bezier` / `circle` / `lines` / `path` | grob 快照（`grob-raster` / `grob-xspline` / `grob-bezier` / …） |

三张 `ci = false` 的 case（`theme-grey-basic` / `theme-minimal-basic` /
`guide-colourbar`）与 expected 的差是 case 自己登记的缺口（panel 网格线未接、
渐变条在 resvg 下覆盖率不足），桌面管线同样差这么多——查看器与桌面之间仍然
判绿，报告里单列「已知缺口」一节。

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

`pch` 在 IR 里是 grid 的编号，字号是 `size`（pt）。查看器的字形逐条照 R
`src/main/engine.c::GESymbol()` 的几何（与 `ggskia/pch.py` 同一张表）：

- 符号半径是 **`0.375 × size`**（`RADIUS` 常量），即直径只有 `size` 的 3/4；
  曾按半径 0.5 画过，结果点大了 1/3（`geom-point-basic` 与桌面的 >90/255 差
  0.49%，改回 R 的常量后降到 AA 级）。
- 实心 / 空心 / 谁上色逐条对齐：15..18 只填充 `col`，19 / 20 填充 + `col`
  描边，21..25 用 `fill` 填充 + `col` 描边，7..14 是复合字形（方+叉、星、
  圆+加号…），不是“近似到最近的简单形状”。
- `pch = 46`（`'.'`）是 0.01 inch 的实心方块，不吃 `size`。
- 字形只用绝对 `M` / `L` / `C` / `Z`，不用 `A`（圆弧的 rx/ry/flag 不是坐标，
  套变换会写出非法 `d`）。

**一个 `points` 节点默认只出一个 `<path>`**：每行一条 `M…Z` 子路径，样式写在
节点元素上（同一节点的 gpar 相同），`data-rows="0-9999"` 给出缓冲行范围——10k
行也只占 1 个 DOM 元素，与 IR 的 bulk 口径一致。

**半透明的点例外**：`gpar.alpha < 1`、`col` 的 alpha < 255 或 `fill` 的 alpha
< 255 时，回退成**每行一个 `<path>`**。SVG 对一个 `<path>` 只做一次合成，
两个重叠的半透明点合成整条路径后只算一层，比桌面（逐点绘制）更浅：

| 两个完全重叠的 pch 19，`col = #e45756` alpha 128 | 中心像素 |
| --- | --- |
| 修前：整节点一个 `<path>` | `rgb(241, 171, 170)` |
| 修后：逐行 `<path>` | `rgb(234, 129, 128)` |
| 桌面设备（同一份 IR） | `rgb(234, 129, 128)` |

代价是 DOM 元素数等于行数：alpha=1 的 10k 点仍是 1 个元素，alpha<1 的 10k 点
会是 10000 个（`tests/test_viewer.py::test_opaque_points_stay_one_element` 与
`test_alpha_points_overlap_matches_desktop` 两侧都钉住）。hover 对聚合元素只
到节点粒度（见 §9）。

## 6. 曲线原语

`src/curves.ts` 是 `src/ggskia/curves.py` 的逐函数移植（后者本身是 R
`src/main/xspline.c` 与 `grid:::calcCurveGrob` 的移植），**不是贝塞尔近似**：

| kind | 查看器实现 | 与桌面同 IR 的实测差 |
| --- | --- | --- |
| `bezier` | 每 4 个控制点一段三次贝塞尔，原样映射 | `grob-bezier`：0.21% / >90 0.42% |
| `xspline` | X-spline 混合函数 + R 的步长公式，采样成折线 | `grob-xspline`：0.000% / 0.004% |
| `curve` | `calcControlPoints` / `calcSquareControlPoints` + X-spline 采样；`angle` 在 R 的 y 向上坐标系里求值，再翻回页面坐标 | `grob-curve`：0.001% / 0.034%；`geom-curve-basic`：0.000% / 0.011% |

`bezier` 剩下的小差是 skia 与 resvg 在同一个三次贝塞尔上的抗锯齿/数值差异，
不是形状差。`curve` / `xspline` 的采样密度用同一个页面尺寸算，所以折线顶点
逐点一致。

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

## 8. 与桌面 SVG 设备的已知差异（附实测数字）

判据是 `snapshot-policy.md` 的 B 栏：同一份 `.ggir.cbor` 分别走查看器与桌面
`pixi run render --scene … --out …svg`，两侧都用 resvg 2×（144 dpi / `zoom 2`）
光栅化，**文字区域按 IR `text` 的边界掩掉**后比像素——平均差异 ≤ 1%、
单像素最大通道差 > 90/255 的占比 ≤ 2%。每张 case 的两个数字都在
`.viewer-cases/report.md` 里。

| 方面 | 桌面（`ggskia` SVG） | 浏览器（本查看器） | 实测 / 处理 |
| --- | --- | --- | --- |
| 文字 | 受管字体 + HarfBuzz 度量，字面来自字体文件 | 系统字体栈 + 正常排版 | 位置锚点一致；掩掉文字后 `geom-text-*` 的残差 0.00%，按 snapshot-policy 的文字容差 |
| 文字基线 | 设备自己算 ascent/descent | `dominant-baseline` 近似 | 掩码按页内 `getBBox` + IR 宽度取包围盒，容差内 |
| 多行行距 | grid 的 `lineheight`（IR 未携带） | 固定 1.2 | 非缺省行距表达不了（`ir.md` §7 · M1-b） |
| pch | `ggskia.pch` 的 `GESymbol()` 几何 | 同一张表（§5） | 尺寸误差已修；剩 0.5% 量级差来自 19 号的描边宽度（见下） |
| `xspline` / `curve` | `ggskia.curves` 的公式 | `curves.ts` 逐函数移植（§6） | 0.00–0.03%，已是抗锯齿级 |
| `bezier` | skia 的 `cubicTo` | 同一条三次贝塞尔 | `grob-bezier` 0.21% / >90 0.42%（光栅器数值差） |
| 结构 | 每个 IR 节点一段 `<g>`，几何在局部坐标 | 几何烘焙到页面坐标，容器不带 transform | 像素等价，DOM 结构不同（IR 不承诺对齐 svglite，`ir.md` §12） |
| 交互 | 无 | hover / 图例开关 | 只存在于浏览器 |

**已知的非零差**（都不影响判绿，但写在这里免得下次重新查）：

1. **pch 19 的描边**：桌面设备按 gpar 的 `lwd` 给实心圆描边，R 的 svglite
   参考图在同一位置几乎是干净的填充边。查看器与桌面因此差在圆的轮廓上
   （`geom-point-basic` 0.23% / >90 0.49%）。这是桌面设备与参考实现之间的
   口径差，不在查看器侧修（本任务不改桌面 SVG 设备）。
2. **`ci = false` 的三张 case**：`theme-grey-basic` / `theme-minimal-basic`（panel
   网格线未接）、`guide-colourbar`（渐变条在 resvg 下覆盖率不足）。查看器与
   **桌面**只差 0.01% 量级；与 expected 的 8.3% / 2.9% 是 case 自己登记的缺口，
   报告里单列「已知缺口」。
3. **文字掩码**：掩码来自页内 `getBBox`（旋转文字的轴对齐包围盒）再按 6 pt
   膨胀。它只掩「文字可能占的地方」，不会掩盖文字的**位置**错误：IR 锚点若算错
   到掩码外，`geom-text-*` 的残差会立刻变红（M1-16 修 `getCTM` 的 4/3 缩放时
   就是这样发现的）。

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
| 字体文件 | 浏览器系统字体栈 | 字体 blob 表（`ir.md` §12） |
| 字符型 pch（32..127、负数） | 按 `pch = 1`（空心圆）兜底；案例库没有这种点，`GESymbol()` 的字符分支未移植 | 字符 → 字形轮廓（要字体表） |
| 逐行 hover（单点 tooltip） | 节点级：`points` 一个节点一个 `<path>`，tooltip 给整段行范围 | 同一 path 内给子路径标 `data-row` + JS 命中测试（`elementFromPoint` 拿不到子路径），待 M2 |

## 10. 测试

`tests/test_viewer.py`（Playwright + 真 Chromium，20 条）：

契约（M1-13，8 条）：

1. 夹具本身有 4 个面板 + 3 个图例 key；
2. **渲染完整**：SVG 里 `<rect>` / `<path>` / `<text>` / `<image>` 的数量与 IR
   图元行数逐类相等（这张图上三类主元素也等于节点数）；
3. **图例开关**：点 key → `data-hidden="true"`、key 图元不可见、同一行的标签
   一起隐藏；再点回来恢复；
4. **hover**：tooltip 出现且文本含 `panel-1`、`point 层`、`数据行 1/`；
5. **10k 点 bulk**：10000 行的 points 节点只产出 1 个 `<path>`（`d` 里 10000 条
   子路径），**整页** `document.querySelectorAll('*').length < 100`；
6. **零 wasm**：整页请求里没有 `.wasm`；
7. **裁剪口径**：两层嵌套视口的 `clip_rect` 原样落成页面矩形（不乘祖先变换）；
8. **坏 IR**：删掉一个 text 节点的 `size`，页面报错文本含该节点的 id。

覆盖与对拍（M1-16，12 条）：

9. **案例库 kind 下限**：`docs/cases` 至少覆盖 viewport / rect / points / text /
   polygon / polyline / segments / curve，防止参数化悄悄少测；
10. **每种 IR kind 一条真实 case**（参数化，按案例库实际出现的 kind 生成）：
    场景来自 `plot.py` 的 `build()`，加载后必须有对应元素，且标签符合映射表；
11. **alpha 叠加**：两个完全重叠、`col` alpha=128 的 pch 19 → 查看器出 2 个
    `<path>`，中心像素与桌面同 IR 差 ≤ 4/255（修前 40+）；
12. **不透明点**：alpha=255 的同一场景仍是 1 个 `<path>`（bulk 口径没丢）；
13. **批量 runner 冒烟**：`tools/viewer/cases.py --only
    facet-wrap-2x2,grob-raster,grob-text-rot` 退出码 0，报告里三条都 `pass`，
    且 SVG / 截图 / 桌面 SVG 产物齐全。

CI 里由 `pixi run check` 先跑 `viewer:build` 与 `viewer:browsers`；浏览器缺失时
用例 `pytest.skip`（skipped 消息写明装浏览器的任务名），不会把门禁染红。
全量 `pixi run viewer:cases`（77 张，约 16 s）**不进** `check`：它要真 Chromium
和全量 resvg 光栅化，CI 里单独跑；`check` 只跑 3 张的 runner 冒烟。
