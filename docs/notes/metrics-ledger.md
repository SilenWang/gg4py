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
- 精度（200 条语料 × 4 字号，`gate:metrics` 每次实测，**只对这份冻结语料成立**）：
  - run 切分与 HarfBuzz **逐条一致（0/800 不一致）**；
  - 兜底表声明支持的文字（178/200 条）最大相对差 **3.59%**；有差的只有其中 **59 条**，
    这 59 条的算术平均 **0.43%**，另外 119 条与 HarfBuzz 逐条相同，178 条整体平均
    **0.14%**。差全部来自 DejaVu 的 kerning（兜底表不建模 kern），典型是 `Total` 的
    `To` 对：绝对差恒定 **+2.71875 px @16px**（表偏宽，等价于 HarfBuzz 的 kern 修正
    −2.72 px）；
  - 相对差随标签变短而放大：`'To'` 单对 **16.14%**、`'Total'` **7.28%**，最差标签
    `'#️⃣ Total'` 只有 3.59% 是因为前面约 38 px 的 emoji 前缀稀释了分母。
    **3.59% / 5% 不是误差上界，换一份语料就不再成立**；
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
| 「必须显式切 run」的标签数 | **132 / 200**（与 E2 完全吻合） |
| 桌面端 skia-python 逐字形 advance 最大差 | 0.18%（emoji CBDT strike 推导差异，L1） |
| 兜底表最大差 / 均值（178 条支持子集） | 3.59% / **0.1441%**（仅本语料；均值口径见 M0-7-d，绝对值恒定 +2.71875 px @16px，`To` 单对 16.14%） |
| 灵敏度：字体栈砍成单字族 | 132 条判红 → 门禁确实量的是「两端」，不是同一侧 |

注意 **skia-python 腿比的是逐字形 advance**，不是整段宽度：`SkFont.getWidths` 不做
kerning/ligature shaping（`Total` 的 `To` 对，`Width` 的 `Wi` 对都会被算宽 2–30%）。
桌面端的文字宽度只能来自 HarfBuzz shaping（L2 的轮廓路径本来也是这条路），skia
只负责字形到轮廓/像素的最后一步。

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
- 整块高度 = `(n-1) × 行距 + strheight`，`vjust` 对整块生效；`strheight`
  是 **cap height × 72.27/72**（见 M1-d），不是 ascent + descent。
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
- run 切分仍是「第一个 cmap 覆盖该码点的字族」；emoji 字面在回退链里排在
  DejaVu 之前——DejaVu 自带 U+1F600/U+2764 的单色字形（推进 1.05em），排在
  前面会让 emoji 永远落不到 1.25em 的 emoji 字面（R 的口径）。
- 两端仍可对拍的理由：**宽度口径接近**。Noto Color Emoji（CBDT strike）在
  20px 下 24.95px，Noto Emoji 轮廓 25.39px（+1.8%），R/cairo 是 25.00。
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
  | `device-smoke`（PNG/SVG/PDF） | 逐字节不变 |
  | `geom-text-cjk` | 图级 **1.15% → 0.17%**（变好） |
  | `text-bold-italic` | hinted 4.17% → linear **1.25%**（hinted 下根本过不了 2%） |

### M1-f · 已知偏差：CJK 族里的拉丁字形

- R 的 fontconfig 对 `fontfamily = "Noto Sans CJK SC"` 的拉丁字形回退到
  Noto Sans 的度量（"Latin width sample" @10pt：R 89.35 vs 我们 83.76，
  **+6.26%**）；纯 CJK 与 Noto Sans 族本身都在 0.39% 内。
- 我们的 run 切分按 M0-7 的共享规则「第一个 cmap 覆盖的字族」把拉丁留在
  CJK 字面（这条规则要与 CanvasKit 一致，本 issue 不改）。
- 影响：CJK 族里的拉丁标签窄 6%；`text-multiline`（含一行中英混排）实测
  图级 1.33%，仍在 2% 内。`tests/test_text_parity.py` 把这一条钉成
  **已知偏差**（≤ 7%），其它组合仍按 0.5% 判。

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
- 整块高度 = `(n-1
