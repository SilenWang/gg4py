# 度量账本

记录「两端/两实现之间有差异，但结论不直观」的口径决定。每条都要能被复现命令验证。

## L1 · emoji 宽度以渲染端实测为准（E2）

- 现象：`NotoColorEmoji.ttf` 是 CBDT 位图字体（无 `glyf`/`CFF`）。HarfBuzz 报设计单位 advance（2550/2048 em → 16 px 下 19.9219 px），Skia 按最近位图 strike 重算（19.9700 px）。
- 量级：每个 emoji 相差 0.048 px @16 px（≈0.24%），随 emoji 数量线性累积。
- 口径：**IR 里的文本宽度必须来自实际渲染端**，不能让 Python 端算完跨端复用；emoji 密集的标签允许 0.5% 的绝对容差。
- 复现：`pixi run spike:e2`，看 `results/e2_results.json` 里 `category == "emoji"`。

## L2 · 文字进 PDF 一律走轮廓（E3）

- 决定：PDF 中不嵌入字体引用，文本先由 HarfBuzz 取轮廓再绘制。产物里没有 `/Font`，因此 CJK 不需要阅读端装字体。
- 额外理由：skia-python 的 `SkFont` 文本 API 依赖宿主 fontconfig，容器内配置缺失时段错误；轮廓路径不经过 fontconfig。
- 代价：PDF 体积随文字量增长（本样例 9 个 glyph ≈ 4.7 KB），但对图表这种文字量可忽略。
- 复现：`pixi run spike:e3`，检查 `results/artifacts/sample.pdf` 无 `/Font`、内容流有路径算子。

## L3 · 字体回退由我们自己切 run，不依赖 CanvasKit（E2）

- 现象：CanvasKit `TypefaceFontProvider` 不跨字族回退，整串按主字族排版会得到 `.notdef`（132/200 条语料受影响）。
- 口径：`font_stack` + 「第一个覆盖该码点的字族」这条规则是**规范**，Python 与 TS 两端各自实现。粘着码点固定为 `U+200C–200D`、`U+FE00–FE0F`、`U+E0100–E01EF` 三段，两端都按这份区间声明，`tests/test_run_split_rules.py` 校验两份声明逐字一致——早期两端的集合各缺一段，只因语料只含 `U+200D`/`U+FE0F` 才没暴露。
- 复现：`pixi run spike:e2`，`run_layout_mismatches` 必须为 0。
