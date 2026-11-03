# r-graph-gallery 35 图人工核对（M2-13 / SIL-744）

**结论：35 张全部有结论；26 张可画、2 张可画但差异明显、7 张画不出。可画（含差异）28/35 = 80%。**
7 张画不出的图集中在三类能力：**多图版面组合**（1 张 + 1 张复合需求）、**扩展 geom 生态**
（5 张）、**空间投影**（1 张）。所有新缺口已登记进 SIL-715，不另建清单。

> 这份清单**只作功能清单，不进验收判据**。35 张图都没有 R 参考图，因此判定口径是
> 「能构建 + 能渲染 + 关键结构逐项核对」，不是像素对拍。真正的像素判据仍由
> `docs/cases/` 的 166 条三文件 case 承担（M2-10）。

## 1. 口径

### 1.1 三态

| 结论 | 含义 | 证据 |
| --- | --- | --- |
| ✅ 可画 | 按 gallery 的图层组合能构建并渲染出 SVG；关键结构（面板数 / 图例数 / 扇区 / 堆叠顺序 / 标注元素）逐项核对通过 | `tools/audit/gallery_plots.py` 的对应 `figNN` |
| ⚠️ 可画但差异大 | 能渲染，但有肉眼可见差异；差异归因写在 §2 | 同上 |
| ⛔ 画不出 | 缺 API / 缺几何 / 缺布局；脚本只能把真实报错记录下来 | 同上（运行器把报错收进输出） |

「可画」允许**写法改写**（例如 R 的 `annotate()` 拆成常量图层、`x = ""` 改成常数 1）。
写法改写不改变图形语义，但会写进 §3 的迁移类缺口，因为它是 R → Python 迁移的真实摩擦。

### 1.2 选图

覆盖任务要求的十类：基础散点、柱状、箱线、密度、热图、等高线、极坐标、分面、多图例、
注释与文字。**排除 3D、动画（gganimate）与交互图**（不是静态 SVG 的验收对象）。
每张图都对应一个真实的 r-graph-gallery 页面主题，数据是就地生成的小型仿制集
（mtcars / iris / gapminder / 月度序列，固定种子），不依赖外部数据文件。

### 1.3 证据怎么来的

```bash
pixi run audit:gallery --list      # 35 行登记（图号 / 三态 / gallery 页）
pixi run audit:gallery             # 构建 + 渲染到 .gallery-audit/（不入库），35/35 符合登记
```

- 走**生产管线**：`ggplot` → `build_plot()` → `scene_from_plot()` → `ggcore.io.ggsave()`
  → skia SVG 设备，与 `pixi run ggsave` 同一条路径；
- 对 `missing` 的图，运行器会继续调用 `build_plot()`——只构造对象不算数
  （`coord_sf()` 的投影校验就在构建期），构建成功即判 STALE 并让审计表更新；
- 渲染后用 resvg 光栅化做结构检查：非空墨迹、元素数、面板数、图例数、饼图/甜甜圈
  的内半径（`PolarGeometry.radius(1.5) = 0.2`、`radius(2.5) = 0.4`）；
- 另外逐项读了 `build_plot()` 的 `panels` / `guides`：例如 fig28 = 3 面板、
  fig29 = 6 面板（3 行 × 2 列，space = free_y）、fig31 = 2 个图例
  （colour + shape 合并成一个，size 独立）。

### 1.4 统计

| 结论 | 数量 | 占比 |
| --- | ---: | ---: |
| ✅ 可画 | 26 | 74.3% |
| ⚠️ 可画但差异大 | 2 | 5.7% |
| ⛔ 画不出 | 7 | 20.0% |
| **可画合计（含差异）** | **28** | **80.0%** |

| 族 | 张数 | ✅ | ⚠️ | ⛔ |
| --- | ---: | ---: | ---: | ---: |
| 散点 / 相关 | 7 | 5 | 2 | 0 |
| 热图 / 矩阵 | 3 | 2 | 0 | 1 |
| 柱状 / 排名 | 5 | 5 | 0 | 0 |
| 极坐标 | 3 | 3 | 0 | 0 |
| 分布（箱线 / 小提琴 / 直方 / 密度） | 6 | 5 | 0 | 1 |
| 时间序列 / 面积 | 3 | 2 | 0 | 1 |
| 分面 / 注释 / 图例 | 4 | 4 | 0 | 0 |
| 版面组合 / 地图 / 网络 / 树图 | 4 | 0 | 0 | 4 |
| 合计 | 35 | 26 | 2 | 7 |

## 2. 35 行明细

「复写」列指审计脚本里的函数（`pixi run audit:gallery figNN`），括号里是已有的三文件
case（能力已被覆盖时不重复建 case）。

| # | r-graph-gallery 页面主题 | 复写 | 结论 | 依据 / 差异归因 |
| ---: | --- | --- | :---: | --- |
| 1 | Scatter plot（基础散点） | `fig01`（`geom-point-*`） | ✅ | 点 + colour 图例 + `theme_bw`；1 面板 |
| 2 | Bubble chart（气泡） | `fig02`（`scale-size-area`） | ✅ | `size=pop` + `scale_size_area`；colour / size 双图例 |
| 3 | Scatter + smooth（拟合线） | `fig03`（`geom-smooth-*`） | ✅ | `geom_smooth(method="lm")`：拟合线 + 置信带 |
| 4 | 2D density plot（二维密度） | `fig04`（`geom-density2d-*`） | ✅ | `geom_density_2d`（contourpy 内核）+ 散点 |
| 5 | Hexbin chart（六边形分箱） | `fig05`（`geom-hex-basic`） | ✅ | `geom_hex(bins=12)` + 连续填充色阶 |
| 6 | Avoid overlapping labels（ggrepel） | `fig06` | ⚠️ | 无 repel：12 个国名互相重叠；`check_overlap` 只删不挪 |
| 7 | Correlogram（相关矩阵） | `fig07` | ⚠️ | 手工把 `|r|` 映射成点大小 + 写数值；缺 corrplot / ggcorrplot 的显著性标记、上下三角选择与配色口径 |
| 8 | Heatmap（热图） | `fig08`（`geom-tile`） | ✅ | `geom_tile` + `scale_fill_viridis_c` + `coord_fixed` |
| 9 | Heatmap with values（热图 + 数值） | `fig09`（`geom-tile` / `geom-text-*`） | ✅ | tile + `geom_text(aes(label="round(z, 1)"))` |
| 10 | Heatmap + dendrogram（聚类热图） | `fig10` | ⛔ | 缺层次聚类 + 树状图 grob + 与热图并置（§3 G3 / G2） |
| 11 | Barplot（计数柱状） | `fig11`（`geom-col-basic`） | ✅ | `geom_bar()` 走 `stat_count` |
| 12 | Grouped barplot（分组） | `fig12`（`geom-col-dodge`） | ✅ | `position_dodge(width=0.85)` |
| 13 | Stacked barplot（堆叠） | `fig13`（`geom-col-stack`） | ✅ | `position_stack(vjust=0.5)` 在段内放标签 |
| 14 | Horizontal barplot（横向排序） | `fig14`（`geom-col-horizontal`） | ✅ | `scale_x_discrete(limits=...)` 控制顺序 + `coord_flip` |
| 15 | Lollipop chart（棒棒糖） | `fig15`（`geom-segment`） | ✅ | `geom_segment` + `geom_point`，排序后横向 |
| 16 | Pie chart（饼图） | `fig16`（`coord-polar-theta-y`） | ✅ | 视觉等价；R 的 `x = ""` 要改写成 `x=1`（空表达式 + 单水平离散 r 轴，§3 G5） |
| 17 | Donut chart（甜甜圈） | `fig17`（`coord-polar-bar`） | ✅ | `x=2` + `xlim(0.5, 2.5)`；内半径 `0.2`、外半径 `0.4` |
| 18 | Circular barplot（环形柱状） | `fig18`（`coord-polar-bar`） | ✅ | `coord_polar(theta="x", start=-π/2)`，12 个扇区；标签角度 / hjust 在数据里算（教程同写法） |
| 19 | Boxplot（箱线图） | `fig19`（`geom-boxplot-*`） | ✅ | 分组箱线 + 手动填充色 |
| 20 | Boxplot + observations（箱线 + 点） | `fig20`（`geom-jitter-basic`） | ✅ | `geom_boxplot` + `geom_jitter(width=0.12)` |
| 21 | Violin plot（小提琴） | `fig21`（`geom-violin-basic`） | ✅ | `geom_violin(trim=False)` + 内嵌窄箱线 |
| 22 | Split violin（半小提琴） | `fig22` | ⛔ | 无 `geom_split_violin`：两组各画半边，需要按组裁切多边形（§3 G3） |
| 23 | Histogram（直方图） | `fig23`（`geom-histogram-bins`） | ✅ | `geom_histogram(bins=30)` |
| 24 | Density plot（多组密度） | `fig24`（`geom-density-basic`） | ✅ | `geom_density(alpha=0.45, colour=None)` 两组半透明叠放 |
| 25 | Time series（折线 + 置信带） | `fig25`（`geom-ribbon-outline`） | ✅ | 日期轴 + `geom_ribbon(ymin, ymax)` + 折线 / 点 |
| 26 | Stacked area chart（堆叠面积） | `fig26`（`geom-area-stacked`） | ✅ | `geom_area` 默认 stack，3 条带 |
| 27 | Streamgraph（流图） | `fig27` | ⛔ | 无 `geom_stream`：对称堆叠 + 平滑需要独立 stat（§3 G3） |
| 28 | Facet wrap（分面） | `fig28`（`facet-wrap-free-y`） | ✅ | 3 面板，`scales="free_y"` + `ncol=2` |
| 29 | Facet grid + space free | `fig29`（`facet-grid-space-free`） | ✅ | 6 面板（3 行 × 2 列），`space="free_y"` 让面板高度随范围变 |
| 30 | Annotation（文字 / 箭头 / 矩形） | `fig30`（`geom-label-basic` / `geom-curve-arrow`） | ✅ | 视觉等价；无 `annotate()`，每个标注一个 `inherit_aes=False` 的常量图层（§3 G1） |
| 31 | Legend position（多图例 / 面板内） | `fig31`（`guide-legend-merged` / `guide-legend-inside`） | ✅ | 2 个图例：colour + shape 合并，size 独立，都锚在面板内 |
| 32 | Scatter + marginal distribution | `fig32` | ⛔ | 缺版面组合：无法把「散点主图 + 边缘直方图」拼成一张图（§3 G2） |
| 33 | Choropleth map（分级统计地图） | `fig33` | ⛔ | `coord_sf(crs=...)` 直接报错：投影 / graticule / sf 几何归 M3-2（§3 G6） |
| 34 | Network graph（网络图） | `fig34` | ⛔ | 缺边 / 节点几何与力导向布局（§3 G3） |
| 35 | Treemap（矩形树图） | `fig35` | ⛔ | 缺 squarify 布局与层级矩形几何（§3 G3） |

## 3. 缺口清单（按「影响面 × 出现频次」排序）

排序口径：先看**影响面**（多少类图 / 多少 gallery 页面会踩到、是否有替代写法），
再看**本 35 图的出现频次**。「归属」按 M2 任务表与 M3 任务表现有编号落位，不新造清单。

| 排序 | 缺口 | 现象 / 复现 | 影响面 | 频次 | 归属 |
| ---: | --- | --- | --- | ---: | --- |
| G1 | 扩展 geom 生态：split violin / stream / dendrogram / treemap / network | 5 个构造名都不存在，`from ggcore.plot import ...` 即 ImportError；详见 §4 | 5 个图族；都是 gallery 的独立页面，treemap / network 在业务报告里常见 | 5/35 | **M3-1**（剩余 geom）+ **M3-7**（案例收口） |
| G2 | 多图版面组合（patchwork / cowplot / ggExtra / inset 的等价物） | 无公开 API 把两个 plot 或 panel grob 拼进一个 gtable；`fig32` 的边缘分布、`fig10` 的热图 + 树都卡在这里 | 6 类常见版面（边缘分布、复合面板、插图、树 + 热图、地图 + 小图、拼图） | 2/35 | **M3-1**（组合/布局）+ **M3-7** |
| G3 | `annotate()` 未实现 | `from ggcore.plot import annotate` 不存在；每个标注要手写一个常量 `aes` 图层 + `inherit_aes=False` | 所有注释类图；R → Python 迁移摩擦最大的一处（gallery 几乎每页都用） | 1/35（但 gallery 常见度最高） | **M3-1** + **M3-6**（迁移对照表） |
| G4 | 标签避让（ggrepel） | `fig06` 12 个国名重叠；`check_overlap` 只按行序删除重叠，不做位移 | 所有带文字标签的散点 / 气泡 / 地图 | 1/35 | **M3-1** |
| G5 | 单水平离散 r 轴上的 `coord_polar(theta="y")` | `aes(x=1)` / `aes(x="''")` 都报 `CoordError: 极坐标的 r_range 必须是两个有限且不等的数，收到 (1.0, 1.0)`；饼图的标准写法 `x = ""` 走不通 | 饼图 / 单组甜甜圈 / 单组极坐标柱 | 1/35（饼图是 gallery 头部页面） | **M3-1**（边界情形）+ M2-1 回归 |
| G6 | `coord_sf()` 的真实投影 | `coord_sf(crs="ESRI:54009")` 在 `build_plot()` 抛 `CoordError`（identity 投影以外都不支持） | 所有 choropleth / sf 图 | 1/35 | **M3-2**（可选空间能力） |
| G7 | `xlim()` / `ylim()` 简写 | 只有 `scale_x_continuous(limits=...)`；甜甜圈配方里的 `xlim(0.5, 2.5)` 要改写 | gallery 大量示例直接用 `xlim` / `ylim`；迁移摩擦 | 2/35（fig16 / fig17 的改写） | **M3-6**（迁移对照） |

**不是缺口（已覆盖，不重复建 case）**：极坐标 / 饼图 / 甜甜圈的几何；facet free scales 与
space=free；多图例合并与面板内定位；gradient2 / viridis / brewer / manual 色阶；
hexbin / contour / density_2d；boxplot / violin / jitter 叠加；日期轴；箭头 / label /
rect / segment 标注。这些在本次核对里都是「一次写成、一次通过」。

## 4. 七张画不出的图：真实报错与缺什么

| 图 | 最接近的调用 | 真实报错 / 缺什么 |
| --- | --- | --- |
| `fig10` 聚类热图 | `geom_dendrogram` | `ImportError: cannot import name 'geom_dendrogram' from 'ggcore.plot'`。还缺两件事：层次聚类（上游 `hclust` 的距离 / 连接口径）与「树 + 热图」的并置布局 |
| `fig22` 半小提琴 | `geom_split_violin` | `ImportError: cannot import name 'geom_split_violin'`。需要按 `group` 把密度多边形裁成左右半边；`geom_violin` 本体已有 |
| `fig27` 流图 | `geom_stream` | `ImportError: cannot import name 'geom_stream'`。需要 `geom_stream` 的对称堆叠 + 平滑 stat（ggstream 的 `smooth` / `type` 口径） |
| `fig32` 边缘分布 | `ggExtraMarginal` | `ImportError: cannot import name 'ggExtraMarginal'`。根因是 G2：没有版面组合 API，不是缺某个 geom |
| `fig33` 分级地图 | `coord_sf(crs=...)` | `CoordError: coord_sf(crs) 需要真实的空间投影，M2-1 只做注册与最小可用（identity 投影）；投影 / graticule / sf 几何归 M3-2` |
| `fig34` 网络图 | `geom_edge_link` | `ImportError: cannot import name 'geom_edge_link'`。还缺节点 / 边的布局（力导向、圆形、层次） |
| `fig35` 矩形树图 | `geom_treemap` | `ImportError: cannot import name 'geom_treemap'`。需要 squarify 布局 + 层级矩形 + 父级标签 |

## 5. 复现

```bash
# 登记表：图号 / 三态 / gallery 页
pixi run audit:gallery --list

# 全部 35 张：构建 + SVG 到 .gallery-audit/（gitignore），missing 的图打印真实报错
pixi run audit:gallery

# 单张
pixi run audit:gallery fig17
```

输出末尾固定是 `35/35 符合登记`。若某个 `missing` 图哪天能构建成功，运行器会打印
`STALE figNN` 并以非 0 退出——提醒更新本表，而不是让清单悄悄过期。

## 6. 边界

- 本 issue 不新增 CI case、不改任何 `expected.svg`、不进 `pixi run check` 的判据；
  脚本只写 `.gallery-audit/`（不入库）。
- 「可画」不等于「与 R 像素一致」：35 张没有参考图，像素判据仍由 `docs/cases/` 的
  166 条 case 与 M2-10 的 314 份上游快照承担。
- 缺口只登记进 SIL-715，不另建清单；后续按该 issue 的「追加规则」在对应 case 的
  `meta.toml` 里写 `ci = false` + issue key。
