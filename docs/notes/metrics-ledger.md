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

- 现象：CanvasKit `TypefaceFontProvider` 不跨字族回退，整串按主字族排版会得到
  `.notdef`。主字族是 `Noto Sans CJK SC` 时 51/200 条语料受影响；M0-7 的
  DejaVu 主字族栈下是 132/200。
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
- 字族名（`Arimo` / `DejaVu Sans` / `Noto Sans CJK SC` / `Noto Color Emoji` …）与
  字体文件名的映射也写在 rules.json，浏览器端 `TypefaceFontProvider.registerFont`
  和 viewer 的 `font-family` 用同一份（M2-e 起由 `tools/viewer/emit_fonts.py` 生成），
  不另写。

### M0-7-c · 后端分离：HarfBuzz 在 ggcore 之外

- `src/ggcore/` 的 import 白名单（X1）不允许 uharfbuzz 进核心包，而 Pyodide 早期
  路径也确实没有 HarfBuzz。所以「怎么量」是可替换后端：
  - `ggshape.harfbuzz.HarfBuzzBackend`（CPython / 服务端 / 桌面）；
  - `ggcore.metrics.table.TableBackend`（纯 numpy + 标准库，浏览器兜底）。
- 「量成什么规则」（run 切分、`font_units / upem * size`）留在 `ggcore.metrics`，
  两端必须一致，不属于后端。

### M0-7-d · 兜底度量表的能力边界（数字在 M2-b 之后更新，见那一节）

- 生成：`pixi run metrics:table` → `src/ggcore/metrics/data/metrics_table_v1.{bin,json}`
  （79 KB 二进制 + 人读元数据）。**同一批字体 + 同一套规则 → 字节完全相同**，
  `pixi run metrics:check-table` 重新生成并比对；`gate:metrics` 每次都跑这个检查。
- 内容：每个受管字体的 upem / ascent / descent / `.notdef` advance / 是否把 emoji
  序列合成单字形，以及 cmap 覆盖的每个码点的 advance（字体设计单位）。
- 精度（200 条语料 × 4 字号，`gate:metrics` 每次实测，**只对这份冻结语料成立**）。
  下面这组是 **v1（不建模 kerning）** 的读数，留作对照；M2-S1 的 v2 已经把它们
  压到 0（见 M2-b）：
  - run 切分与 HarfBuzz **逐条一致（0/800 不一致）**；
  - 兜底表声明支持的文字（178/200 条）最大相对差 **2.374%**；有差的只有其中 **73 条**，
    这 73 条的算术平均 **0.38%**，另外 105 条与 HarfBuzz 逐条相同，178 条整体平均
    **0.1574%**。差来自兜底表不建模 kerning（73 条有差行里 68 条表偏宽、5 条偏窄），
    典型是 `'#️⃣ Total'` 的 1.584 px @16px；绝对差随字对与标签长度累加（这份语料
    0.05–2.72 px @16px，最大的是长标签 `L172`，不是相对差最差的 `L110`），不是一个常数；
  - 相对差随标签变短而放大：`'To'` 单对 **5.84%**、`'Total'` **4.53%**，最差标签
    `'#️⃣ Total'` 只有 2.374% 是因为前面约 38 px 的 emoji 前缀稀释了分母。
    **2.374% / 5% 不是误差上界，换一份语料就不再成立**；
  - CJK 子集**完全一致**（advance 恒为 1 em）；
  - **不建模**上下文 shaping：阿拉伯/希伯来/印度诸语/泰文/老挝/藏文/缅文/高棉/
    朝鲜 jamo 一律 `supports() == False`，最大偏差实测 95.8%，**不能**用于布局。
- 口径：兜底表是「没有 HarfBuzz 时的近似」，不是权威宽度。IR 里的文本宽度按 L1
  仍然必须来自实际渲染端；`MetricProvider.supports(text)` 为 False 时必须换引擎。
- 「178 条整体平均 0.14%」是一个被引用了很多次的数，口径钉死在这里，换个算法就是
  另一个数：
  - **分母是 178 条 supported 标签**（`TableBackend.supports()` 为 True 的那些），
    不是 200 条全量。按 200 条算、把 22 条不支持的直接记 0，得到 **0.1282%**，
    那是另一个口径，不要混用。
  - 相对差是**逐标签** `abs(table - ref) / ref`，`ref` 是同一标签在 HarfBuzz/provider
    下的整段 advance（不是字形单位，不是 CanvasKit 的宽度）。
  - 178 个相对差做**未加权算术平均**：每条标签权重相同，不按字符数、不按宽度加权。
  - 与 HarfBuzz 逐条相同的 **119 条照样进分母、按 0 计**——只平均那 59 条有差的，
    得到的是 0.43%，不是 0.14%。
  - 精确值 **0.144087%** @16px（下面命令输出的 `0.001440869726923`）。账本里写过
    的 0.1445% 复现不出来，是本轮之前临时脚本的口径/转录差异，以这里为准。
- 复现：跑一遍门禁，再从报告里取已经算好的 `table_fallback.mean_rel`。
  `gate:metrics` 现在也直接把同一个值打在 `table max …` 那行，两边必须一致。

  ```
  pixi run gate:metrics >/dev/null && pixi run python -c "import json;print(json.load(open('.gate-metrics/metrics_gate.json'))['per_size']['16']['table_fallback']['mean_rel'])"
  ```

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
  - cold（清缓存后全量）：**median ≈ 6.35 ms / 200 条**（≈32 µs/条，HarfBuzz shaping
    成本）；引用这个数请用 median——5 轮里有 1 轮 ≈52 ms 的离群，mean 因此是 15.1 ms，
    写 mean 会把成本高估一倍多；
  - warm（全命中）：median ≈ **119 µs / 200 条**（≈0.6 µs/条，缓存查找 + 求和）；
  - 命中率由 `test_cache_hit_rate` 断言：cold 全 miss、warm 全 hit（语料有重复
    标签，按去重后的条数计）。
- 命中的现实形态：同一张图的 axis/legend/annotation 会反复量同一批字符串。

### M0-7-g · 门禁数据（`pixi run gate:metrics`）

| 项 | 结果 |
|---|---|
| 双端（uharfbuzz × CanvasKit.Paragraph）最差相对差 | **0.241%** @16px（10/12/24px 为 0.151/0.191/0.191%），判据 0.5% |
| run 切分布局不一致 | 0 / 200（四个字号都是 0） |
| 「必须显式切 run」的标签数 | **51 / 200**（CJK 主字族栈；M0-7 的 DejaVu 主字族栈下 132 / 200） |
| 桌面端 skia-python 逐字形 advance 最大差 | **0.2353%** @16px（10/12/24px 为 0.141/0.183/0.183%；emoji CBDT strike 推导差异，L1） |
| 兜底表最大差 / 均值（178 条支持子集） | **2.374% / 0.1574%**（四档同值；最差行 `L110 "#️⃣ Total"`，绝对差 1.584 px @16px） |
| 灵敏度：字体栈砍成单字族 | 51 条判红 + 58 条 run-mismatch（最差 289%） → 门禁确实量的是「两端」，不是同一侧 |

注意 **skia-python 腿比的是逐字形 advance**，不是整段宽度：`SkFont.getWidths` 不做
kerning/ligature shaping（`Total` 的 `To` 对，`Width` 的 `Wi` 对都会被算宽 2–30%）。
桌面端的文字宽度只能来自 HarfBuzz shaping（L2 的轮廓路径本来也是这条路），skia
只负责字形到轮廓/像素的最后一步。

> M2-b 之后表中那一行是 **0 / 0**：兜底表 v2 带上了字对 kerning，判据也从 5% 收到 1%。

## M1 · 文字测量（SIL-655）

M1-7 / M1-10 / M1-11 之前的四块短板：真实 bold/italic 字面、`\n` 多行、
emoji 轮廓、hinted vs linear 推进。每条都能用仓库里的命令复现。

### M1-a · 字面解析：`(族, weight, italic)` → 受管文件

- 声明在 `src/ggcore/metrics/faces.py`（`FAMILY_FACES`），文件仍只来自
  `pixi.toml` 的 `font-ttf-*` 包；rules.json 登记「文件 → 字族名」，faces.py
  补同族的字面与可变轴。`FontCatalog.resolve()` 是唯一入口，raster / SVG / PDF
  共用（`ggskia.text.resolve_stack`）。
- gpar 的 `font` 1..5 → weight 400/700 × italic：`2` bold、`3` italic、
  `4` bold-italic。**可变字体用 `wght` 轴**（Noto Sans / Noto Sans CJK /
  Noto Serif），静态字面直接选文件（DejaVu）。
- 没有对应字面时 `strict=True` 报错并列出可用字面，不静默回落常规：
  `Noto Sans CJK SC 没有 italic 字面；可用字面：regular`。回退字族
  （DejaVu / CJK / emoji）用 `strict=False`：某档缺 italic 时用常规字面继续
  找覆盖，与 R 的 fontconfig 回退一致。
- 复现：`pixi run python -c "from ggcore.metrics.catalog import FontCatalog;
  print(FontCatalog().resolve('Noto Sans', 700, True))"` → NotoSans-Italic-VF.ttf
  + `variation=700`。
- `shortcut:` skia-python 的 `setVariationDesignPosition` 只持有
  `VariationPosition` 的引用；中间对象被回收时 `makeClone` **静默退回设计默认
  字重**（Bold 与 Regular 推进完全相同）。`ggskia.text._variation_args()`
  因此把三个中间对象一起保活到 `makeClone` 返回。

### M1-b · `\n` 多行：R 的实测口径

- 行距（draw 时）：**`1.2 × lineheight × fontsize`**，grid 的
  `gpar(lineheight = 1.2)` 缺省 → **1.44 × fontsize**。R 4.5.3 实测：
  30pt 三行的基线 39.12 / 82.32 / 125.52（间距 43.2 = 1.44 × 30）；
  `lineheight = 1.0` 时 36.0、`2.0` 时 72.0。issue 里「行高 = 1.2 × fontsize」
  是 grid 的 `heightDetails` 口径的一半事实：那一步用的行盒是
  `fontsize × lineheight`，而**画出来的行距再多乘 1.2**。这里按实测对齐。
- 整块高度 = `(n-1) × 行距 + 单行 cap height`，`vjust` 对整块生效；cap height 是
  **cap × 72.27/72**（见 M1-d），不是 ascent + descent。注意别在这里再调一次
  `ShaperMetrics.strheight(text)`：那个函数内部已经加了 `(n-1) × 行距`。
- 宽 = 各行的最大推进（R 的 `stringWidth` / `widthDetails` 同口径）；
  `hjust` 对每一行分别作用（R 实测 `text-anchor` 保持 middle、x 按行宽偏移），
  0 / 0.5 / 1 时与「整块对齐」等价。
- 复现：`pixi run -e refs refs:text` → `tests/fixtures/text_r_reference.json`
  的 `multiline` 段（逐行宽度、整块高度、行距），对拍在
  `tests/test_text_parity.py`。实测行宽最大差 0.39%，整块高度 0.30%。
- IR 缺口：`text` 节点没有 `lineheight`、没有连续 `hjust/vjust`、没有逐行
  宽度。设备按 grid 缺省 `lineheight = 1.2` 画；非默认 lineheight 与
  小数 just 目前表达不了（`docs/notes/ir.md` §7 的字段没变）。

### M1-c · emoji：矢量后端用单色轮廓，栅格保留彩色位图

- 策略：`NotoColorEmoji.ttf` 是 CBDT 位图（无 glyf/CFF），PDF/SVG 走轮廓时
  一个字形也出不来；因此 `SkiaSvgDevice` / `SkiaPdfDevice` 的
  `TextShaper(emoji="outline")` 把 `Noto Color Emoji` 换成
  `NotoEmoji-Regular.ttf`（单色轮廓），`SkiaRasterDevice` 保持彩色位图。
- run 切分仍是「第一个 cmap 覆盖该码点的字族」。回退顺序只有一份声明：
  `rules.json` 的 `default_font_stack`（CJK → Noto Color Emoji → DejaVu），
  `MetricProvider` / `TableBackend` / 设备 `ggskia.text.resolve_stack` 与
  CanvasKit 都读它。emoji 字面必须排在 DejaVu 之前——DejaVu 自带
  U+1F600/U+2764 的单色字形（推进 1.05em），排在前面会让 emoji 永远落不到
  1.25em 的 emoji 字面（R 的口径）；SIL-661 之前只有设备侧改了顺序，共享声明
  仍是 DejaVu 在前，`U+1F600` @20pt 因此 provider 20.85 vs 设备 24.95。
- 主字族变成 CJK 之后，一个 run 里可能混着不同书写系统：HarfBuzz 的
  `guess_segment_properties()` 每段只取一个 script，`n=각` 会被整段当
  Latin 排（61.78px vs CanvasKit 32.34px，+91%）。`runs.script_segments()`
  按**真实 script** 切段后再 shape：script 没变就不切（Hangul 音节 `AC00-D7A3`
  与 jamo `1100-11FF` 都是 `Hang`），ZWJ / ZWNJ / 组合记号黏在前一段。script
  表是 `data/scripts.json`（`tools/metrics/build_scripts.py` 从 HarfBuzz 的
  unicode script 数据冻结，ggcore 仍只依赖标准库）。SIL-663 之前按「复杂/非复杂」
  二值切段，把 `가`+尾 jamo（29.44 vs 14.72）、`م`+ZWJ+`ر`（17.63 vs 17.40）、
  `क्‍ष` 切成半截；四条反例钉在 `tests/test_metrics.py`。改完后 200 条语料
  逐条宽度不变。
- 两端仍可对拍的理由：**宽度口径接近**。Noto Color Emoji（CBDT strike）在
  20px 下 provider / 兜底表 24.90px、设备 24.95px（R/cairo 25.00，最大偏差
  0.4%），Noto Emoji 轮廓 25.39px（+1.8%）。
  参考图 svglite 写的是 `<text>` + `textLength`，diff 管线
  （`ggdiff.svgtext`）按同一套 run 规则转轮廓，所以像素比的是位置与字形，
  不是「彩色 vs 单色」的颜色差；`text-emoji` 实测图级 1.67% / 均值 0.52%。
- 单元测试：`tests/test_text_layout.py` 钉住「混排时切成两个 run」「SVG/PDF
  的 emoji 轮廓非空」「栅格画出的 emoji 有非灰像素」。

### M1-d · 纵向口径：R 的 `strheight` 是 cap height

- R 4.5.3 实测（svglite，`gpar(fontsize = 20)`）：

  | 字族 | R `stringHeight`（pt） | em | skia `fCapHeight` |
  | --- | --- | --- | --- |
  | Noto Sans | 14.338 | 0.7169 | 14.280 |
  | Noto Sans CJK SC | 14.714 | 0.7357 | 14.660 |
  | DejaVu Sans | 14.635 | 0.7317 | 15.000（OS/2 sCapHeight 1493 ≈ R） |
  | Arimo | 13.818 | 0.6909 | 13.760 |

  `cap × 72.27/72` 与 R 逐条差 < 0.1%。旧实现用
  `(ascent - descent) / 2`，在 vjust=0.5 时多偏 0.03 em，落在 1px 字画的
  抗锯齿边缘上——`geom-text-cjk` 的图级差因此从 1.15% 降到 **0.17%**。
  设备与 `ShaperMetrics.strheight` 现在都用 cap 口径（位图字体 cap=0 时
  退回字面框）。

### M1-e · hinted vs linear 推进：切到 linear，并逐张交代基线

- 复现：`pixi run metrics:advance`（`.metrics-advance/advance.json`）。样本 =
  现有 7 个含文字的 case（20 条标签）+ 冻结 200 条语料，共 **220 条**。
- 结果（16px 语料 / 各 case 自己的字号）：

  | 口径 | 最大差 | 均值 | 最差标签 |
  | --- | --- | --- | --- |
  | hinted vs linear | **10.61%** | 1.51% | `n=ü` @16（24.00 vs 26.85） |
  | hinted vs HarfBuzz | **10.61%** | — | 同上（linear 与 HB 都是 26.85） |

  现有 case 标签里：`right` @10pt **+8.75%**、`left` +7.60%、
  `displ (mm)` −7.43%。155/220 条可比；复杂书写系统与 emoji 序列不比
  （设备走另一条 shaping 路径，见 M1-c 与 device.md §4）。
- 结论：**切 linear**（`Font.setLinearMetrics(True)`）。R 的 cairo/svglite
  就是线性推进；同一串 12pt "Bold text sample"：hinted 108.00 /
  linear 100.78 / HarfBuzz 100.54 / **R 100.53**——hinted 偏宽 7.4%，
  linear 差 0.25%。
- 基线影响（逐张，不整批重录）：

  | 资产 | 结果 |
  | --- | --- |
  | `grob-text` | 重录：1104 px 不同（mean 0.227）——字面从整 pt 量化变成线性，**修正** |
  | `grob-text-rot` | 重录：1490 px 不同（mean 0.260）——同上，**修正** |
  | 其余 14 张 `grob-*` | 逐字节不变 |
  | `viewport-*`（2 张） | 逐字节不变 |
  | `device-smoke`（PNG/SVG/PDF） | PNG 1800 px 不同（mean 0.383）：linear 改变文字位置，SVG/PDF 同源变化 |
  | `geom-text-cjk` | 图级 **1.15% → 0.17%**（变好） |
  | `text-bold-italic` | hinted 4.17% → linear **1.25%**（hinted 下根本过不了 2%） |

- SIL-661 复核时发现 `tools/cases/grob_cases.py` 的 `SkiaMetrics`（grob 案例
  的 IR 宽度来源）还是 hinted，而且 `strheight` 用 ascent + descent：同一段
  文字在 IR 与设备各量一套。改成线性 + cap height 后重录：`grob-text` 776 px
  不同（mean 0.156），`grob-text-rot` 171 px（mean 0.032）；IR 宽度与
  `strwidth()` 的线性计算值逐位相等。

### M1-f · 已知偏差：CJK 族里的拉丁字形（默认栈已在 M2-a 改掉，显式族仍在）

- R 的 fontconfig 对 `fontfamily = "Noto Sans CJK SC"` 的拉丁字形回退到
  Noto Sans 的度量（"Latin width sample" @10pt：R 89.35 vs 我们 83.76，
  **+6.26%**）；纯 CJK 与 Noto Sans 族本身都在 0.39% 内。
- 我们的 run 切分按 M0-7 的共享规则「第一个 cmap 覆盖的字族」把拉丁留在
  CJK 字面（这条规则要与 CanvasKit 一致，本 issue 不改）。
- M2-a 之后**默认栈**把 Arimo 排在首位，缺省字面的拉丁不再落进 CJK 字面；
  这一条只对**显式**请求 `Noto Sans CJK SC` 的图成立。
- 影响：CJK 族里的拉丁标签窄 6%；`text-multiline`（含一行中英混排）实测
  图级 1.33%，仍在 2% 内。`tests/test_text_parity.py` 把这一条钉成
  **已知偏差**（≤ 7%），其它组合仍按 0.5% 判。

## M2 · 文字度量对齐（SIL-728）

M1 的缺省拉丁字面是 `Noto Sans CJK SC`，而参考产线（ggplot2 4.0.3 + svglite）画的是
**Arimo**；两套 advance 差 4%（`Noto Sans` 族）到 14%（DejaVu），多文本节点的图会整体错位。
本节四条口径都能用仓库命令复现。

### M2-a · 默认拉丁字面 = 参考产线的 Arimo

- 解析链：ggplot2 的 `base_family = ""` → grid `gpar(fontfamily = "")` → svglite 设备
  把它当 `sans` 交给 systemfonts/fontconfig。实测（`pixi run -e refs Rscript`）：
  `grid.text()` 分别写 `family = ""` / `"sans"` / `"Arimo"`，导出的 `expected.svg`
  **三种都写成 `font-family: "Arimo"`**；`systemfonts::match_font("Arimo")` 落到
  `$CONDA_PREFIX/fonts/Arimo-Italic-VF.ttf` —— `font-ttf-noto` 20201206 只提供这一份
  Arimo（`fvar` 的 `wght` 轴只有一个 400 实例，`post.italicAngle = -12`）。
- 是不是这一份，用 `expected.svg` 的 `textLength` 认：`"Total 0.00 To"` @8.8px 是
  **50.17**；同一串在 HarfBuzz 下 Arimo-Italic-VF **50.2348（+0.13%）**、不带 kern
  51.85（+3.35%）、Google Fonts 的 Arimo 正体 49.74（−0.86%）。15 条 Arimo 标签逐条
  在 +0.10%～+0.26%，是 2 位小数的转录差（`'l'` 1.9500 / 1.9551）。
- 口径：`rules.json` 把 `Arimo-Italic-VF.ttf` 登记为字族 `Arimo` 并排在
  `default_font_stack` 首位；`faces.py` 的常规 / 粗体 / 斜体都落这一份文件——
  conda 侧没有别的 Arimo，R 侧 fontconfig 同样只能拿到它（粗体就是合成粗体），
  编一个不存在的 `wght` 轴反而会把粗体画错。
- 复现：`pixi run -e refs Rscript -e 'print(systemfonts::match_font("Arimo"))'`。

### M2-b · kerning：设备端一律 HarfBuzz，兜底表 v2 带字对 kerning

- 设备端（`ggskia.text._shape_one`）以前对「简单文字」走 skia 的 `measureText` /
  `getXPos`，两者都不做 kerning：`"Total 0.00 To"` @8.8px 在 Noto Sans 上是 52.83，
  带 kern 的 HarfBuzz 是 51.62（偏宽 2.3%）。IR 的 `text.width` 与笔画位置都来自它，
  所以布局跟着偏。现在**一律 HarfBuzz shaping**（glyph id + 累计笔位 + 推进），
  skia 只负责把字形画出来。
- 兜底表（`metrics_table_v2`）新增字对 kerning：构建期对 cmap 里 `U+0000–U+2FFF` 的
  单码点字对逐对 shape，存 `(first, second, delta)`（int16，设计单位）；
  `TableBackend.shape` 在相邻码点之间加这个增量。对的取舍是「单独 shape 恰好一个
  字形、推进等于 hmtx」——格式控制符（U+2062 之类不可见运算符）会被 HarfBuzz 整个
  吞掉，不剔除会算出几 em 的假 kerning。
- 覆盖：Arimo 905 对、DejaVu 8634 对、CJK 18134 对、emoji 0 对；表 102 KB（v1 79 KB）。
  字对表只在默认实例上取（可变字重不逐字重展开），与 v1 的边界相同。
- 结果（`pixi run gate:metrics`，200 条语料 × 4 字号）：兜底表最大相对差
  **2.374% → 0**、均值 **0.1574% → 0**（178 条支持子集，逐条与 HarfBuzz 相同）；
  判据从 5% 收到 **1%**（`tools/gates/check_metrics.py` 的 `TABLE_GATE`）。
  双端（HarfBuzz × CanvasKit）不变：0.241% @16px、run 切分 0 不一致（`spike:e2` 同）。
- 复现：`pixi run metrics:table && pixi run gate:metrics`。

### M2-c · 旋转文字的包围盒

- IR 的 `text` 节点带 `pos`（锚点）、`width`（最终宽度）、`angle`（绕 `pos` 的局部旋转，
  `ir.md` §7）。查看器算叶子包围盒时只用了平移矩阵：`angle != 0` 时把一条竖排文字
  算成水平细条（20×10 的文字 rot=90 仍算成 20×10，而不是 10×20），hover / 裁剪 /
  视口统计全跟着错。现在旋转进包围盒。
- `tests/test_viewer.py::test_rotated_text_bbox_follows_the_rotation` 钉住：
  `pos=(100,100)`、`width=20`、`size=10`、`anchor=left`、`baseline=top`、`angle=90`
  → 包围盒 `(100,80)-(110,100)`。
- 设备侧本来就在 `_place_text` 里绕锚点转，不用改。轴标签自身的 `angle`
  （`axis.text` 的 rot）仍是 M1-11 的已知缺口，`axis.py:_angle()` 对
  `angle % 360 != 0` 直接报未实现。

### M2-d · 量化：密集报告图与 case 集

图：`scripts/exit_report.py` 对 `scripts/exit_report.R`（同数据、同绘图代码，svglite
出 SVG），比法 `pixi run diff <ref> /tmp/after/report.svg`（svgtext 把参考文本转轮廓、
resvg 72 dpi）。

| 指标 | 修前 | 修后 |
| --- | --- | --- |
| 图级差异 | **21.78%** | **20.98%** |
| 平均差异 | **4.06%** | **3.78%** |

文本度量已经对齐：同一张图 22 条文本的宽度（R 的 `textLength` vs 我们 IR 的
`text.width`）最大相对差 **0.17%**（标题 216.09 / 216.45），其余 ≤0.06%
（`control` 26.39/26.41、`Series` 31.19/31.18、`Elapsed time (days)` 97.25/97.21、
`Response (arb. units)` 105.22/105.16）。

剩下的 21% 不是字体、也不是 AA，份额如下（都在本 task 的边界外）：

- **面板几何（主因，占差异像素 56.6%）**：面板宽 87.13 vs R 88.56（−1.43pt，−1.6%），
  改字面前后只动 0.09pt（87.04 → 87.13，文本宽度收敛带来的）。面板内 33.45% 的像素
  不同，整块网格/曲线/点随面板宽度平移。
- **分面轴重复（占差异像素 5.4%）**：我们这张图有 34 个 text 节点、R 只有 22 ——
  上排也画了 x 轴标签、右列也画了 y 轴标签。面积小，但把行距与条带位置进一步推开。
- **AA 不是主因**：两版都做 σ=0.8 / 1.5 的高斯模糊后差异不降反升
  （0.2098 → 0.2475 / 0.2330），说明差的是整块内容错位，不是边缘抗锯齿。

前两条归 SIL-715 #7（report-style case 覆盖盲区）与 #8（facet 列宽用文本高度近似），
本 task 明确不碰 gtable / 布局。

case 集（`pixi run viewer:cases`，61 条全绿；括号里是 M1 出口时的读数）：
`text-bold-italic` 1.25% → **0.51%**、`theme-grey-basic` 1.8695% → **1.73%**、
`theme-minimal-basic` 1.8727% → **1.70%**、`guide-colourbar` 1.7409% → **1.63%**、
`geom-text-cjk` 0.17% → 0.17%、`text-emoji` 1.67% → 1.69%。

### M2-e · 浏览器端的字面只有一份来源

- 查看器以前写死 `"Noto Sans CJK SC", "DejaVu Sans", sans-serif`，真正画字的是宿主
  fontconfig（`tools/viewer/playwright_env.py` 把 `FONTCONFIG_FILE` 指进 pixi 环境）。
  现在 `tools/viewer/emit_fonts.py` 从 `rules.json` + `faces.py` 生成
  `web/viewer/fonts.css`（逐字面 `@font-face`，`src` 指向 `web/viewer/fonts/` 里的
  受管字体副本）与 `web/viewer/src/fonts.generated.ts`（文件 → 字族、默认栈）；
  `render.ts` 的 `font-family` 只由后者拼，**不带 `sans-serif`**。
- `pixi run viewer:build` 先跑该脚本再 `tsc`；字体副本与生成物都不入库。
