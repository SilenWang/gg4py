# E2 双端度量一致性

**结论：通过。** 同一批字体、同一份 200 条语料下，uharfbuzz 与 CanvasKit.Paragraph 的文本 advance 最差差 0.241%（判据 0.5%），均值 0.02%，四个字号下 0 条超阈。

附带一个必须写进 M0-7 的结构性发现：**CanvasKit 不做跨字族回退**，200 条标签里有 132 条（CJK / emoji / 组合字符 / 长串）只有在「显式按字体切 run」之后才量准；整串丢给主字族会退化成 `.notdef` 方块。

## 方法

- 语料：`docs/spike/corpus/labels_200.json`（冻结，sha256 `6c93e414…bedfb1`），5 类各 40 条：latin / cjk / emoji / combining（含 RTL、天城文、泰文、越南语）/ long（40–200 字符）。
- 字体：conda-forge 提供的真实文件，两端读同一份字节：`DejaVuSans.ttf`、`NotoSansCJKsc-VF.ttf`、`NotoColorEmoji.ttf`。
- 两侧 **run 切分规则完全一致**：逐码点选「font_stack 里第一个 cmap 覆盖它的字族」；`ZWJ`/变体选择符/组合标记黏在前一个 run 上。
- CPython 侧：`hb.shape()` 逐 run 取 `x_advance`，按 `size/upem` 换成 px。
- 浏览器侧：每个 run 单独建一个 `SkParagraph`（`TypefaceFontProvider` + `FontCollection` + 显式 `fontFamilies`），取 `getMaxIntrinsicWidth()` 求和。这是渲染器真实会走的路径。
- 字号：10 / 12 / 16 / 24 px（度量问题通常在字号边界暴露）。
- 代码：`run_e2.py`（编排 + CPython 侧）、`measure_canvaskit.cjs`（CanvasKit 侧）；`pixi run spike:e2` 一条命令复现。

## 数据

| 字号 | 最差相对差 | 均值 | p99 | 最大绝对差 | 超阈条数 | run 切分不一致 |
|---|---|---|---|---|---|---|
| 10 px | 0.151% | 0.014% | 0.151% | 0.040 px | 0 | 0 |
| 12 px | 0.191% | 0.015% | 0.191% | 0.057 px | 0 | 0 |
| 16 px | 0.241% | 0.020% | 0.241% | 0.100 px | 0 | 0 |
| 24 px | 0.191% | 0.015% | 0.191% | 0.118 px | 0 | 0 |

分类（16 px）：

| 类别 | n | 最差 | 均值 | 最大绝对差 |
|---|---|---|---|---|
| latin | 40 | 0.0094% | 0.0022% | 0.005 px |
| cjk | 40 | 0.0085% | 0.0028% | 0.005 px |
| combining | 40 | 0.0163% | 0.0036% | 0.005 px |
| long | 40 | 0.0025% | 0.0007% | 0.025 px |
| emoji | 40 | 0.2410% | 0.0907% | 0.100 px |

原始逐条数据：`results/e2_results.json`（含每条标签的双端宽度、run 结构、差值）。

## 发现

### 1. 非 emoji 文本两端几乎逐位相同

latin / cjk / 组合字符的最大绝对差是 0.005 px —— 这是 1/64 px 量化误差（Skia 行宽按 1/64 px 上报），不是 shaping 差异。也就是说两端跑的是同一套 HarfBuzz 逻辑、同一份字体、同一套 fallback 决策。

### 2. emoji 是唯一真实差异，来源是 CBDT 位图字体

最差的一条是 `🕰️`（16 px）：uharfbuzz 给 19.9219 px，CanvasKit 给 19.9700 px。`NotoColorEmoji.ttf` 没有 `glyf`/`CFF`，只有 CBDT 位图数据：HarfBuzz 报的是设计单位 advance（2550/2048 em），Skia 对位图字形按最近位图 strike 重新推导 advance，于是每个 emoji 差 0.048 px（≈0.24%）。

这类误差随 emoji 数量线性累积但仍极低（长串里 5 个 emoji 也才 0.5 px 级别），**判据通过**。写进账本的口径：emoji 宽度以「渲染端实测」为准，IR 里的宽度必须来自实际渲染端，不能跨端复用。

### 3. CanvasKit 不做跨字族回退（对 M0-7 的硬约束）

`TypefaceFontProvider` 注册了三个字体后，把「月份（万元）」整串按主字族 `DejaVu Sans` 送去排版，得到的是 6 个 `.notdef` 盒子（57.61 px），而不是 CJK 的 96 px。全量语料里 **132/200 条标签**受此影响（判据 0.5% 以上）。

`FontCollection.setDefaultFontManager()` 并不能修复它。可行且必须的做法是：**度量/渲染前显式切 run，每个 run 指定字族**。这与三处设计正好同向：

- M0-2 的 IR 里 text 节点携带最终宽度与锚点；
- M1-13/M2-12 的 TS SVG 序列化器本来就要为每段文字写 `font-family`/`tspan`；
- M0-7 的双端门禁需要「同一套 run 切分规则」作为验收项之一。

## 风险与后续

- **字体集合是前提**：本实验绑定 DejaVu + Noto Sans CJK SC + Noto Color Emoji 三个实际文件。产品若换字体（比如跟 R 的 `sans` 对齐到 Liberation/DejaVu），必须重跑门禁；语料与脚本已可直接复用。
- **可变字体**：`NotoSansCJKsc-VF.ttf` 用的是默认实例，两端一致。若后续要支持字重轴，需要在门禁里加 `variation` 维度。
- **未覆盖**：竖排、字距调整（`letter-spacing`）、`font-feature-settings` 的端到端差异；这些留到 M0-7 实现 `MetricProvider` 时补齐测试矩阵。
