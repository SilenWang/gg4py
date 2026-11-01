# 设备账本（设备接口 + skia 三路出图）

`ir.Scene` → PNG / SVG / PDF。M0-8 的交付物，也是 M0 出口「一张手搓图三路出图」
的实现方。上游对应物是 grid 的设备接口（`src/library/grid/src/grid.c` 的
`L_points` / `L_xspline` 与 `src/main/engine.c` 的 `GESymbol` / `GEXspline`），
ggplot2 自己不做设备。

- 协议：`src/ggcore/device.py`（纯 Python，X1 门禁内）
- 实现：`src/ggskia/`（`skia.py` 三路后端、`text.py` 排版、`pch.py` 符号表、
  `curves.py` 曲线求值）
- CLI：`src/ggskia/cli/render.py`，任务名 `pixi run render`
- 用例：`tests/test_device.py`（三路冒烟 + 能力清单）、
  `tests/test_device_r_parity.py`（曲线纯函数对拍）、
  `tests/test_device_render_r_parity.py`（设备级真渲染对拍）、
  `tests/test_grob_cases.py`（16 张快照）
- 冒烟图：`pixi run cases:device` → `docs/cases/device-smoke/current/`

## 1. 分层：协议在 `ggcore`，后端在包外

X1 门禁要求 `src/ggcore/` 只 import 标准库 / numpy / cbor2——ggcore 是 Pyodide 里
也要跑的内核，渲染后端在包外（`docs/notes/gates.md`）。所以：

| 层 | 位置 | 依赖 |
| --- | --- | --- |
| 设备协议 | `ggcore.device.Device` / `DeviceError` / `FORMATS` | 无（只有 `ir.Scene`） |
| skia 三路后端 | `ggskia.SkiaRasterDevice` / `SkiaSvgDevice` / `SkiaPdfDevice` | `skia-python`、`uharfbuzz` |
| 造设备 | `ggskia.device_for(path, w, h, dpi)` | 同上 |

这和 HarfBuzz 的位置是同一条规则：`ggshape` 在包外（`docs/notes/upstream-map.md`
「文本度量」），`ggcore.metrics` 只管协议与规则。

## 2. 接口：一次 open → 若干 draw_scene → 一次 close

```python
device = device_for("x.svg", 432.0, 288.0, dpi=150)  # 页面尺寸与 DPI 都显式
device.open()
device.draw_scene(scene)  # 只吃 ggcore.ir.Scene
data = device.close()  # bytes
device.render(scene)  # 上面三步的简写
```

四条约束：

1. **单位统一 pt**：页面尺寸、几何、线宽、字号、`lty` 段长都是 pt。`dpi` 只决定
   栅格化的像素换算（`size_px = round(pt / 72 * dpi)`），不改变几何
   （`docs/notes/ir.md` §1）。

   R 的 `gpar$lwd` **不是 pt**，是 1/96 inch：`grobs → IR` 那一步按
   `72/96 = 0.75` 折算（`ggcore.grobs._LWD_UNITS_TO_PT`），`lty` 的段长是
   `lwd` 的倍数，跟着一起折。不折的话所有描边粗 4/3 倍——`lwd = 6` @150 ppi
   实测 R 是 10 px 墨、设备会是 12 px（SIL-636）。
2. **页面尺寸是显式参数**：`draw_scene` 发现 `scene.size != device.size_pt` 直接
   报 `DeviceError`，不替场景改纸、不裁掉多出来的部分。
3. **顺序与状态**：未 `open` 就 `draw_scene` / 重复 `open` / `close` 两次都报
   `DeviceError`；`close` 之后不能再画。
4. **只吃 IR**：`ggcore.grobs.Scene`（float64）不进设备，要出图先
   `to_ir_scene()`（`docs/notes/grobs.md` §7.2）。

## 3. 三路后端：差别只有文字与画布

| 后端 | 文字 | 画布 | 产物 |
| --- | --- | --- | --- |
| `SkiaRasterDevice` | `TextBlob`（skia 的字形渲染，逐像素等于 `drawString()`） | `Surface.MakeRasterN32Premul`，按 `dpi` 缩放 | PNG |
| `SkiaSvgDevice` | 字形轮廓 `Font.getPath()` | `SVGCanvas.Make`（`kNoPrettyXML`） | SVG |
| `SkiaPdfDevice` | 字形轮廓 `Font.getPath()` | `PDF.MakeDocument` + `beginPage` | PDF |

遍历器只有一份（`ggskia.skia._SkiaDevice._paint_node`），所以三路的几何、裁剪、
顺序完全同源；差别只在文字怎么落到画布上。

**矢量后端把文字画成轮廓**，这是硬约束（`docs/notes/metrics-ledger.md` L2 +
E3 的结论：CanvasKit 只有栅格后端，PDF 走 HarfBuzz 轮廓）：

- PDF 里没有 `/Font`，CJK 不依赖阅读端字体；
- SVG 里没有 `<text>` / `font-family`，不依赖查看器字体；
- 原文不进产物，所以也没有编码/乱码这一层。

页面底色在 M0 是白的（`clear(WHITE)`），不做透明背景；页眉页脚不参与场景遍历
（快照工具的说明文字直接画在画布上）。

## 4. 文字：一个 font key、一条 run 切分规则、一套笔位

IR 的 `text` 只有 `font`（单个已解析 key）、`size`、锚点、`angle` 和一个**最终
宽度**（`docs/notes/ir.md` §7）。设备自己排版，宽度只用于对齐与差分统计。

1. **key → 字体栈**（`ggskia.text.resolve_stack`）：`sans`（grob 的缺省 key，
   `DEFAULT_FONT_KEY`）解析成 `NotoSansCJKsc-VF.ttf`——它同时覆盖拉丁与中日韩，
   CJK 验收靠它；登记过的字族名解析成自己的文件；未知字族回落到 `sans`。
   粗体/斜体的后缀（`:bold` 等）暂时落到同一份文件（M1 的字体目录再做合成）。
2. **run 切分**：直接用 M0-7 的 `ggcore.metrics.runs.split_runs()`——两端同一份
   规则（`docs/spike/e2_metrics/report.md` 的 132/200 条就是没切 run 造成的）。
   混排「中文 A」时中文与拉丁各走各的字面；粘着码点不单独起 run。
3. **字形与笔位**：
   - 简单文字（拉丁/希腊/西里尔/CJK/emoji，即 `is_supported()` 为真）用 cmap
     直映 `Font.textToGlyphs()`；
   - 需要上下文 shaping 的书写系统（阿拉伯/印度诸语/泰文/高棉…）走 HarfBuzz
     shaping，连写、重排、合字都在那一步发生；
   - 笔位统一用 skia 的 `Font.getXPos()`，也就是 `drawString()` 自己用的那套
     hinted 推进。三个后端于是落在同一组位置上，栅格也能逐像素复现旧基线。
   - **标签原样落字**：不认 `\n`（也没有 `check.overlap`），换行见 §9。

**为什么简单文字不绕 HarfBuzz**：Noto Sans CJK 是可变字体，HarfBuzz 在
`"r0"` 这种串里会把 '0' 换成另一个字形实例（63153），而 skia 的 `drawString()`
用 cmap 的 17；两者宽度相同、字形不同。M0-7 的度量端与浏览器走 HarfBuzz，但
对比度量的口径是 advance，不受影响；设备这边要的是「与栅格基线同一张图」，
所以简单文字按 cmap 直映，复杂文字再上 HarfBuzz。
`shortcut:` 推进是 hinted 的（整 pt 量化，长标签累计误差 < 1pt）；要线性度量时
换 `setLinearMetrics(True)`，并同步重录 `docs/cases/grob-*/baseline`。

## 5. `pch`：照 R 的常量，不是「直径 = size」

`pch` 的几何在 `ggskia.pch`，逐条抄自 `src/main/engine.c::GESymbol()`：

| 常量 | 值 | 用在哪 |
| --- | --- | --- |
| `RADIUS` | 0.375 | 方/圆/菱形/三角的半径：**直径是 size 的 3/4** |
| `SMALL` | 0.25 | `pch = 20` 的小圆 |
| `SQRC` | 0.8862269254527580 | `pch = 22` 的方（面积与圆相当） |
| `DMDC` | 1.2533141373155003 | `pch = 23` 的菱形 |
| `TRC0/1/2` | 1.5551 / 1.3468 / 0.7776 | 等边三角形的外接圆半径与半宽/半高 |

画法：0..14 只描边（`col`）；15..18 用 `col` 填充；19/20 填充 + 描边都用 `col`；
21..25 用 `fill` 填充 + `col` 描边。字符型 pch（32..127，负数取码点）用
`points.size` 当字号落字（R 用的是 gp 的 fontsize，IR 的 `points` 没有这个字段），
26..31 与 >127 按 R 的口径只警告、不画（`DeviceWarning`）。

`pch = 46`（`'.'`）是 R 的特判（`engine.c::GESymbol()` 的 `case 46`）：画 **0.01 inch
的实心方块**，不是 `.` 的字形。设备照做（`pch.DOT_HALF_PT`，不吃 `points.size`）。
已知偏差：R 那个方块按 `gpar$cex` 缩放，IR 的 `points` 节点没有 `cex` 字段，所以
只对 `cex = 1`（ggplot2 的缺省）逐像素一致；`cex ≠ 1` 时设备仍画 0.01 inch，
要精确对齐得等 IR 带上 `cex`（M1）。

**旧基线为什么改了一处**：临时设备用 `size / 2` 当半径（直径 = size），比 R 大
1/3。M0-8 按 R 的 `RADIUS = 0.375`，`docs/cases/grob-points/baseline` 因此重录。

## 6. 曲线：`xspline` / `curve` 是参考实现的移植

IR 不展平曲线（`docs/notes/ir.md` §4），设备按公式求值：

- `ggskia.curves.xspline_points()` 是 R `src/main/xspline.c`（Xfig 3.2.4 的
  X-spline，Blanc & Schlick '95）的逐函数移植：`f`/`g`/`h` 混合函数、按段长与
  弯曲度估步长（1200 ppi 的 Xfig 单位、页面对角线兜底、`MAX_SPLINE_STEP = 0.2`）。
  **开样条的两端按直线钳制**：R 4.5.3 实测首末控制点的 shape 不生效（closed 样条
  则全部生效），这里照实测行为对齐——`xspline-open-mixed-shapes` 用例逐点钉住。
- `ggskia.curves.curve_points()` 是 `grid:::calcCurveGrob` / `calcControlPoints` /
  `calcSquareControlPoints` / `calcOrigin` 的移植：grid 的 `curveGrob` 本质是把
  算出来的控制点交给 `xsplineGrob(shape = 0 …)`，端点 shape 为 0（直线段），
  中间点用 `shape` / `squareShape`（IR 没有 `squareShape`，按 R 缺省 1）。

对拍：`pixi run -e refs refs:device` 生成
`tests/fixtures/device_r_reference.json`（8 条 xspline + 9 条 curve），
`tests/test_device_r_parity.py` **逐点**比对（采样密度也比，因为步长公式用的是
同一份页面尺寸），最大差 < 1e-12 pt。

### 坐标系：`curve` 必须先翻到 R 坐标，`xspline` 不用

`curve_points()` 的 `angle` 是 R 坐标系（y 向上）里的角度，`grid::curveGrob`
的拐角选哪一侧就靠它；IR 的页面坐标是 y 向下。所以 `_draw_curve` 先按页面高度
翻成 `y' = H - y` 求值，再把折线翻回 `H - y'`。直喂页面坐标会把整条曲线**沿弦线
镜像**：`square = TRUE, angle = 90` 的拐角从 `y2` 那一侧跑到 `y1`（SIL-636 的
阻塞 1，渲染 IoU 0.008–0.015）。

`xspline` 没有角度参数，纯控制点混合在 y 翻转下不变，所以 `_draw_xspline` 直接
喂页面坐标——`curves.py` 的「纯几何」说法对 xspline 成立，对 curve 不成立。

### 设备级对拍（`refs:device-render`）

纯函数对拍挡不住「函数对、集成错」：那两条 bug（镜像、`lwd` 单位）它都是绿的。
所以另有一套**真渲染**的夹具：

- `tools/refs/device_render_ref.R` 在 4×3 in / 150 ppi 的页面上用 R 真画一遍，
  产物是 `tests/fixtures/device_render_r/<id>.png` 与 `index.json`（每条折线的
  **设备坐标**采样点，pt、y 向下）；
- `tests/test_device_render_r_parity.py` 用设备渲染同一张图：PNG 比墨迹 IoU
  （阈值 0.9，实测 0.98–1.00），SVG 从 `d` 里解析出折线与 R 的设备坐标折线逐点
  比（< 0.01 pt），拐角在哪一侧单列一条断言；
- 同一个门里还钉住 `lwd = 6` @150 ppi 的墨高（R 与设备都 10 px）与 `pch = 46`
  的 0.01 inch 方块。

把 `_draw_curve` 的翻转回退，这套门会红 5 条（PNG IoU 掉到 0.011/0.018、
折线、拐角侧各一条）。

两条旧基线因此重录（临时设备是 Catmull-Rom 近似 + 二次曲线近似）：
`docs/cases/grob-xspline/baseline`、`docs/cases/grob-curve/baseline`。
`lwd` 折算又把 16 张 `docs/cases/grob-*/baseline` 全部重录了一遍：有描边的 13 张
像素变化，`grob-text` / `grob-text-rot` / `grob-raster` 不含描边、逐字节不变。

## 7. 裁剪与变换：照 IR 的消费约束

- `viewport.transform` 自下而上合成，**先在页面空间裁 `clip_rect`、再 concat**
  （`docs/notes/ir.md` §4）：`clip_rect` 是页面绝对坐标，不跟子坐标走。
- 零面积裁剪框就是「裁掉一切」，设备不解释成 inherit / 不裁剪
  （`docs/notes/grobs.md` §7.3）。
- `text.angle` 只叠局部旋转：视口旋转已经在 `transform` 的线性部分里
  （`docs/notes/grobs.md` §7.1）。
- `clip` 节点（任意形状裁剪）也支持：`rect` 或 `points` + `rule`，走
  `canvas.clipPath`；grob 路径目前不产出它（矩形裁剪在遍历期就折算完了）。
- NaN / ±Inf 顶点是缺口（`docs/notes/ir.md` §5）：切子路径，不画。

## 8. 验收

| 验收（issue） | 落在哪 |
| --- | --- |
| PDF 非空、> 1 KB、无 `/Font` | `tests/test_device.py::test_raster_svg_pdf_all_render_the_smoke_scene`、`tools/cases/device_cases.py --check` |
| SVG 可 XML 解析且含 `<path` | `::test_svg_is_xml_and_has_paths_not_text` |
| CJK 在 PDF 与 SVG 里都是 path | `::test_cjk_text_becomes_outlines_in_svg_and_pdf`（换一句标签，产物必须不同） |
| 三路同一张手搓图（rect+line+text+CJK+旋转视口文字） | `pixi run cases:device`；PNG 进 PR |
| 3 张已有 grob case 与快照像素一致 | `pixi run cases:grob --check`（16 张全绿；`grob-text` / `grob-text-rot` / `grob-rect` 逐字节一致） |
| 曲线与 R 4.5.3 的渲染一致（SIL-636） | `tests/test_device_render_r_parity.py`：PNG IoU ≥ 0.9、SVG 折线逐点 < 0.01 pt、拐角在 `y2` 侧 |
| `lwd` 与 R 同宽（SIL-636） | `::test_stroke_width_matches_r_at_150_ppi`（`lwd = 6` → 10 px） |
| 坏 blob 干净失败、PDF 不段错误（SIL-636） | `tests/test_device.py::test_bad_raster_blob_fails_cleanly_in_every_backend`（子进程，返回码 2） |

## 9. 刻意不做 / 已知限制

| 行为 | R / 上游 | M0-8 |
| --- | --- | --- |
| 粗体 / 斜体 | 字体文件 + 合成 | key 后缀保留，落到同一份常规字面（M1） |
| 彩色 emoji | CBDT 位图字形 | 矢量后端没有轮廓 → 该字形为空（栅格正常，M1 走位图回退） |
| 字符间 kerning | HarfBuzz / Cairo | 简单文字用 hinted 推进，不做 kerning（< 0.5%，见 M0-7 账本） |
| 标签里的 `\n` | `grid.text` 断行 | **不换行**：`\n` 当作普通码点落字，字体没有它的字形就画 `.notdef` 豆腐块（实测 `"a\nb"` 墨迹 194 px，`"ab"` 61 px）。ggplot2 标签里 `\n` 很常见，M1 要在 `text` 进设备前切行（IR 需要带行距/对齐意图） |
| 断行 / `check.overlap` | `grid.text` 支持 | 不做（IR 没有断行意图） |
| 渐变 / 图案填充 | grid 的 gpar 支持 | IR 的 gpar 只有 RGBA |
| 透明背景 | 设备相关 | 页面固定白底 |
| 多页 / 多文档 | PDF 支持 | 一台设备一页（M1 的 `ggsave` 再谈） |

## 10. 复现

```bash
pixi run test                                   # 含 tests/test_device*.py
pixi run cases:device                           # 三路冒烟图 → docs/cases/device-smoke/current/
pixi run cases:device --check                   # 只验验收条目
pixi run cases:grob --check                     # 16 张 grob 快照
pixi run -e refs refs:device                    # 曲线对拍夹具（需要 R 环境）
pixi run -e refs refs:device-render             # 设备级渲染夹具（R 真画 PNG + 设备坐标折线）
pixi run render --scene <file.ggir.cbor> --out x.png
pixi run render --scene <file.ggir.cbor> --out x.svg
pixi run render --scene <file.ggir.cbor> --out x.pdf
pixi run render docs/cases/<case> --format svg --out docs/cases/<case>/current
pixi run diff docs/cases/<case> --json          # 差分（M0-9，见 docs/notes/diff.md）
```

`render` 的第二种形态（case 目录）是 M0-9 补的适配层：读 `plot.py` →
`ggcore.plotspec` → IR → 设备，文件名 `<case>.<format>`。`--scene` 入口的行为不变。
