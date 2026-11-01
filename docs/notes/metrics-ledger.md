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

## M0-7 · MetricProvider 与双端度量门禁（M0 阶段新增口径）

M0-7 之前只有 M-1 的实验脚本（`pixi run spike:e2`）；现在是生产代码 + 门禁。
下面每条都能用仓库里的命令复现。

### M0-7-a · 规则只有一份声明

- 规则（粘着码点区间、兜底表不支持的书写系统、受管字体与字族名、默认字体栈）在
  `src/ggcore/metrics/data/rules.json`，Python（`ggcore.metrics.rules`）与
  CanvasKit 度量脚本（`tools/metrics/measure_canvaskit.cjs`）都读它。
- `docs/spike/e2_metrics/measure_canvaskit.cjs` 现在是
  `tools/metrics/measure_canvaskit.cjs` 的薄壳，E2 的命令与输出格式不变。
- `docs/spike/e2_metrics/run_e2.py` 是冻结的实验脚本，保留自己的字面声明；
  `tests/test_run_split_rules.py` 比对它与 rules.json，任何一侧漂移都会红。
- **改规则 = 改 rules.json 的 `version` + `pixi run metrics:table`**：兜底表二进制头
  里带规则版本，解码时版本不符直接拒绝（`ggcore.metrics.table.decode_table`）。

### M0-7-b · 字体只从受管目录读

- 定位顺序：显式 `FontCatalog(root=...)` → `GG_FONT_DIR` → `$CONDA_PREFIX/fonts`。
  **不经过宿主 fontconfig**：L2 已实测容器内 fontconfig 配置缺失时 skia 的 `SkFont`
  文本 API 会段错误；按文件路径建 face 不会。
- 字族名（`DejaVu Sans` / `Noto Sans CJK SC` / `Noto Color Emoji`）与字体文件名的
  映射也写在 rules.json，浏览器端 `TypefaceFontProvider.registerFont` 和以后 TS SVG
  的 `font-family` 用同一份，不另写。

### M0-7-c · 后端分离：HarfBuzz 在 ggcore 之外

- `src/ggcore/` 的 import 白名单（X1）不允许 uharfbuzz 进核心包，而 Pyodide 早期
  路径也确实没有 HarfBuzz。所以「怎么量」是可替换后端：
  - `ggshape.harfbuzz.HarfBuzzBackend`（CPython / 服务端 / 桌面）；
  - `ggcore.metrics.table.TableBackend`（纯 numpy + 标准库，浏览器兜底）。
- 「量成什么规则」（run 切分、`font_units / upem * size`）留在 `ggcore.metrics`，
  两端必须一致，不属于后端。

### M0-7-d · 兜底度量表的能力边界

- 生成：`pixi run metrics:table` → `src/ggcore/metrics/data/metrics_table_v1.{bin,json}`
  （79 KB 二进制 + 人读元数据）。**同一批字体 + 同一套规则 → 字节完全相同**，
  `pixi run metrics:check-table` 重新生成并比对；`gate:metrics` 每次都跑这个检查。
- 内容：每个受管字体的 upem / ascent / descent / `.notdef` advance / 是否把 emoji
  序列合成单字形，以及 cmap 覆盖的每个码点的 advance（字体设计单位）。
- 精度（200 条语料 × 4 字号，`gate:metrics` 每次实测）：
  - run 切分与 HarfBuzz **逐条一致（0/800 不一致）**；
  - 兜底表声明支持的文字（178/200 条）最大相对差 **3.59%**（DejaVu 的 kerning，
    典型是 `Total` 的 `To` 对），均值 0.46%；CJK 子集**完全一致**（advance 恒为 1 em）；
  - **不建模**上下文 shaping：阿拉伯/希伯来/印度诸语/泰文/老挝/藏文/缅文/高棉/
    朝鲜 jamo 一律 `supports() == False`，最大偏差实测 95.8%，**不能**用于布局。
- 口径：兜底表是「没有 HarfBuzz 时的近似」，不是权威宽度。IR 里的文本宽度按 L1
  仍然必须来自实际渲染端；`MetricProvider.supports(text)` 为 False 时必须换引擎。

### M0-7-e · strheight / ascent / descent 的定义

- `ascent` / `descent` 取**字体栈主字族**的 `hb.Font.get_font_extents()`，单位 px；
  HarfBuzz 的 descender 是负数，provider 抹平成**向下的正距离**。
- `strheight` = 该段文字实际用到的字族里 `ascent + descent` 的最大值（px）；空串按
  主字族算，避免空标签把行高算成 0。
- `strwidth` 就是 `advance`（整段 advance，含两端一致的 run 切分），不是
  `available-width` 之类的布局量。

### M0-7-f · 缓存与成本

- 缓存键 `(text, size, font_stack)`，值是该段文字的 run 结果（含每 run 宽度）；
  容量 4096，FIFO 淘汰，`cache_stats()` 暴露 `entries/hits/misses/evictions/hit_rate`。
- `pixi run bench`（`benchmarks/test_metrics.py`）实测（本机，200 条语料 @16px）：
  - cold（清缓存后全量）：约 **6.3 ms / 200 条**（≈31 µs/条，HarfBuzz shaping 成本）；
  - warm（全命中）：约 **118 µs / 200 条**（≈0.6 µs/条，缓存查找 + 求和）；
  - 命中率由 `test_cache_hit_rate` 断言：cold 全 miss、warm 全 hit（语料有重复
    标签，按去重后的条数计）。
- 命中的现实形态：同一张图的 axis/legend/annotation 会反复量同一批字符串。

### M0-7-g · 门禁数据（`pixi run gate:metrics`）

| 项 | 结果 |
|---|---|
| 双端（uharfbuzz × CanvasKit.Paragraph）最差相对差 | **0.241%** @16px（10/12/24px 为 0.151/0.191/0.191%），判据 0.5% |
| run 切分布局不一致 | 0 / 200（四个字号都是 0） |
| 「必须显式切 run」的标签数 | **132 / 200**（与 E2 完全吻合） |
| 桌面端 skia-python 逐字形 advance 最大差 | 0.18%（emoji CBDT strike 推导差异，L1） |
| 兜底表最大差（支持子集） | 3.59% |
| 灵敏度：字体栈砍成单字族 | 132 条判红 → 门禁确实量的是「两端」，不是同一侧 |

注意 **skia-python 腿比的是逐字形 advance**，不是整段宽度：`SkFont.getWidths` 不做
kerning/ligature shaping（`Total` 的 `To` 对，`Width` 的 `Wi` 对都会被算宽 2–30%）。
桌面端的文字宽度只能来自 HarfBuzz shaping（L2 的轮廓路径本来也是这条路），skia
只负责字形到轮廓/像素的最后一步。
