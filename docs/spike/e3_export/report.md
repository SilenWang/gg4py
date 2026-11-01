# E3 浏览器导出缺口

**结论：通过——缺口确认，且不阻塞。** CanvasKit 0.42.0 只能出位图（PNG），没有 PDF 文档、没有 SVG canvas；导出分工按原计划成立：SVG 由 TS 序列化器从 IR 生成（零 wasm），PDF 只在桌面/服务端由 skia-python 产出。

## 查证方式

不靠文档描述，直接对真实构建做两件事：

1. **枚举 API + 实跑**（`probe_canvaskit.cjs`）：列出 canvaskit-wasm 0.42.0 全部 159 个导出，按 `/pdf|svg|vector|document/` 过滤；再用同一份绘制尝试出 PNG / SVG / PDF。
2. **桌面侧对照**（`run_e3.py`）：把同一张图用 skia-python 144.1 画一遍，落 PDF 与 SVG，然后检查产物本身。

## 数据

浏览器侧（canvaskit-wasm 0.42.0，Node 22）：

| 项 | 结果 |
|---|---|
| 导出总数 | 159 |
| 含 pdf/svg/document 的导出 | 只有 `Vector`（一个 2D 向量运算工具对象，`dot/length/add/normalize`，与导出无关） |
| surface 工厂 | `MakeSurface`、`MakeCanvasSurface`、`MakeSWCanvasSurface`、`MakeWebGLCanvasSurface`、`MakeOnScreenGLSurface`、`MakeRasterDirectSurface` —— 全是栅格/GPU 后端 |
| `MakePDFDocument` | 不存在 |
| SVG canvas | 不存在 |
| PNG | 可出（`makeImageSnapshot().encodeToBytes()`，签名校验通过） |

桌面/服务端侧（skia-python 144.1）：

| 项 | 结果 |
|---|---|
| PDF | `%PDF-1.4`、1 页、4735 B、**无 `/Font` 资源**、解压后 10.6 KB 内容流、342 条路径算子 |
| SVG | XML 可解析、根元素 `svg`、2 个 `<path>`、5377 B |
| CJK 轮廓 | `月份 增长 42%` → 9 个 glyph，路径非空，bbox 6279×904 字体单位，16 px 下 advance 101.792 px |

产物：`results/artifacts/sample.pdf`、`results/artifacts/sample.svg`（可直接打开核对）。

## 发现

### 1. 缺口是真的，但正好落在设计里

CanvasKit 没有矢量后端：它把 Skia 编译成「只到像素」的子集。IR → DOM `<svg>` 这条路本来就不经过 CanvasKit（零 wasm 分享端），所以浏览器导出 SVG 不需要 skia；PDF 也从来不是浏览器端的需求（浏览器打印走自己的 PDF 生成）。**唯一的约束是：浏览器端不能承诺「导出 PDF」，界面文案与 API 必须按此设计。**

### 2. 文本必须以轮廓进 PDF

产物里没有 `/Font`，文字全部是路径算子——这不是巧合，是本实验的实现方式：文本由 HarfBuzz 取轮廓（`docs/spike/common/hb_path.py`），再交给 skia 绘制。对 CJK 是必须的（否则 PDF 依赖阅读端装了中文字体）。

顺带记一条环境事实：skia-python 的 `SkFont` 文本 API（`unicharToGlyph`/`measureText`/`drawString`）依赖宿主 fontconfig，本容器里 fontconfig 配置不可用时直接段错误。轮廓路径不经过 fontconfig，因此在 CI/容器里更稳——这也是 `MetricProvider` 应该自己管字体文件而不是问系统的又一条理由。

### 3. 三路格式的分工（可直接写进 M0-8 验收）

| 格式 | 产出端 | 实现 |
|---|---|---|
| PNG | 浏览器 / 桌面 | CanvasKit raster surface / skia-python surface |
| SVG | 浏览器（唯一出口） | TS 序列化器：IR → DOM `<svg>`，零 wasm；桌面若要 SVG 可用 `skia.SVGCanvas` 但只作调试 |
| PDF | 桌面 / 服务端 | `skia.PDF.MakeDocument` + HarfBuzz 轮廓 |

## 风险与后续

- SVG 的 `viewBox`：`SVGCanvas.Make(Rect.MakeWH(...))` 输出的是 `width`/`height` 而非 `viewBox`，缩放行为与 TS 序列化器需要对齐口径（M0-8 加一条断言）。
- CanvasKit 的 PNG 编码是位图，色带/字体渲染与桌面 skia 会有细微差异——M3-8「三渲染器两两 diff < 0.5%」要预留 emoji/CBDT 的容差（与 E2 同一来源）。
