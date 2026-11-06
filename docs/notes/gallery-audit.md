# r-graph-gallery 35 图人工核对（M2-13 / SIL-744）

**结论：35 张全部有结论；27 张可画、2 张可画但差异明显、6 张不做（第三方扩展）。
可画（含差异）29/35 = 82.9%。**
6 张不做的是 patchwork / ggExtra / ggforce / ggstream / ggraph / treemapify 这类第三方
扩展的版面与几何（2026-11-04 决策：只复刻 ggplot2 本体），文档里给本体等价写法（§4）；
M2 收口时「画不出」的 7 张里，**fig33 分级地图已由 M3-2 的 `coord_sf` 投影补上**
（EPSG:3857，见 §2 第 33 行）。剩余缺口仍归 SIL-715，不另建清单。

> 这份清单**只作功能清单，不进验收判据**。35 张图都没有 R 参考图，因此判定口径是
> 「能构建 + 能渲染 + 关键结构逐项核对」，不是像素对拍。真正的像素判据仍由
> `docs/cases/` 的 166 条三文件 case 承担（M2-10）。

## 1. 口径

### 1.1 四态

| 结论 | 含义 | 证据 |
| --- | --- | --- |
| ✅ 可画 | 按 gallery 的图层组合能构建并渲染出 SVG；关键结构（面板数 / 图例数 / 扇区 / 堆叠顺序 / 标注元素）逐项核对通过 | `tools/audit/gallery_plots.py` 的对应 `figNN` |
| ⚠️ 可画但差异大 | 能渲染，但有肉眼可见差异；差异归因写在 §2 | 同上 |
| ⛔ 不做 | 图依赖第三方扩展包的布局 / 几何（patchwork、ggExtra、ggforce、ggstream、ggraph、treemapify …）；按 2026-11-04 决策只复刻本体，文档给等价写法（§4） | 同上（脚本打 `OUT`，报错就是「没有同名 API」的证据） |
| ❔ 画不出 | 缺本体能力（非第三方）；缺什么写在 §2 | 同上（脚本打 `MISS`） |

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
- 对 `out` / `missing` 的图，运行器会继续调用 `build_plot()`——只构造对象不算数
  （`coord_sf()` 的投影校验就在构建期），构建成功即判 STALE 并让审计表更新；
- 渲染后用 resvg 光栅化做结构检查：非空墨迹、元素数、面板数、图例数、饼图/甜甜圈
  的内半径（`PolarGeometry.radius(1.5) = 0.2`、`radius(2.5) = 0.4`）；
- 另外逐项读了 `build_plot()` 的 `panels` / `guides`：例如 fig28 = 3 面板、
  fig29 = 6 面板（3 行 × 2 列，space = free_y）、fig31 = 2 个图例
  （colour + shape 合并成一个，size 独立）。

### 1.4 统计

| 结论 | 数量 | 占比 |
| --- | ---: | ---: |
| ✅ 可画 | 27 | 77.1% |
| ⚠️ 可画但差异大 | 2 | 5.7% |
| ⛔ 不做（第三方扩展） | 6 | 17.1% |
| **可画合计（含差异）** | **29** | **82.9%** |

| 族 | 张数 | ✅ | ⚠️ | ⛔ 不做 |
| --- | ---: | ---: | ---: | ---: |
| 散点 / 相关 | 7 | 5 | 2 | 0 |
| 热图 / 矩阵 | 3 | 2 | 0 | 1 |
| 柱状 / 排名 | 5 | 5 | 0 | 0 |
| 极坐标 | 3 | 3 | 0 | 0 |
| 分布（箱线 / 小提琴 / 直方 / 密度） | 6 | 5 | 0 | 1 |
| 时间序列 / 面积 | 3 | 2 | 0 | 1 |
| 分面 / 注释 / 图例 | 4 | 4 | 0 | 0 |
| 版面组合 / 地图 / 网络 / 树图 | 4 | 1 | 0 | 3 |
| 合计 | 35 | 27 | 2 | 6 |

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
| 10 | Heatmap + dendrogram（聚类热图） | `fig10` | ⛔ | 不做：层次聚类 / 树状图 / 并置布局是 ggdendro + patchwork 的扩展能力；等价写法：`geom_tile` 画热图、行列顺序按自己算的聚类结果传给 `scale_*_discrete(limits=)`，树用 `geom_segment` 手画（§4） |
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
| 22 | Split violin（半小提琴） | `fig22` | ⛔ | 不做（ggforce 的 `geom_split_violin`）；等价写法：两组 `geom_violin(position=position_dodge())` 并排，或上下镜像密度（`after_stat("density")` / `after_stat("-density")`，见 `examples/mirrored-density`） |
| 23 | Histogram（直方图） | `fig23`（`geom-histogram-bins`） | ✅ | `geom_histogram(bins=30)` |
| 24 | Density plot（多组密度） | `fig24`（`geom-density-basic`） | ✅ | `geom_density(alpha=0.45, colour=None)` 两组半透明叠放 |
| 25 | Time series（折线 + 置信带） | `fig25`（`geom-ribbon-outline`） | ✅ | 日期轴 + `geom_ribbon(ymin, ymax)` + 折线 / 点 |
| 26 | Stacked area chart（堆叠面积） | `fig26`（`geom-area-stacked`） | ✅ | `geom_area` 默认 stack，3 条带 |
| 27 | Streamgraph（流图） | `fig27` | ⛔ | 不做（ggstream 的对称堆叠 + 平滑 stat）；等价写法：`geom_area(position="stack")` 看组成随时间变化（不居中、不平滑） |
| 28 | Facet wrap（分面） | `fig28`（`facet-wrap-free-y`） | ✅ | 3 面板，`scales="free_y"` + `ncol=2` |
| 29 | Facet grid + space free | `fig29`（`facet-grid-space-free`） | ✅ | 6 面板（3 行 × 2 列），`space="free_y"` 让面板高度随范围变 |
| 30 | Annotation（文字 / 箭头 / 矩形） | `fig30`（`geom-label-basic` / `geom-curve-arrow`） | ✅ | 视觉等价；无 `annotate()`，每个标注一个 `inherit_aes=False` 的常量图层（§3 G1） |
| 31 | Legend position（多图例 / 面板内） | `fig31`（`guide-legend-merged` / `guide-legend-inside`） | ✅ | 2 个图例：colour + shape 合并，size 独立，都锚在面板内 |
| 32 | Scatter + marginal distribution | `fig32` | ⛔ | 不做（ggExtra / patchwork 的版面组合）；等价写法：主图 `geom_point` + `geom_smooth`，边缘分布另出一张 `geom_histogram` / `geom_density` |
| 33 | Choropleth map（分级统计地图） | `fig33` | ✅ | `map_frame("usa", ".")` 的多边形按区域填色 + `coord_sf(crs="EPSG:3857")`；M3-2 落地的 4 个 CRS 里取 3857（墨卡托），真实空间几何见 sf 族 case |
| 34 | Network graph（网络图） | `fig34` | ⛔ | 不做（ggraph 的力导向布局）；等价写法：节点坐标自己算，边 `geom_segment` / `geom_curve`、节点 `geom_point` + `geom_text` |
| 35 | Treemap（矩形树图） | `fig35` | ⛔ | 不做（treemapify 的 squarify 布局）；等价写法：占比用堆叠条 / 分组柱，要矩形版式就自己算坐标后 `geom_rect` |

## 3. 缺口清单（按「影响面 × 出现频次」排序）

排序口径：先看**影响面**（多少类图 / 多少 gallery 页面会踩到、是否有替代写法），
再看**本 35 图的出现频次**。「归属」按 M2 任务表与 M3 任务表现有编号落位，不新造清单。

| 排序 | 缺口 | 现象 / 复现 | 影响面 | 频次 | 归属 |
| ---: | --- | --- | --- | ---: | --- |
| G1 | 扩展 geom 生态：split violin / stream / dendrogram / treemap / network | 5 个构造名都不存在，`from ggcore.plot import ...` 即 ImportError；详见 §4 | 5 个图族；都是 gallery 的独立页面，treemap / network 在业务报告里常见 | 5/35 | **不做**（2026-11-04 决策：只复刻本体；等价写法见 §4） |
| G2 | 多图版面组合（patchwork / cowplot / ggExtra / inset 的等价物） | 无公开 API 把两个 plot 或 panel grob 拼进一个 gtable；`fig32` 的边缘分布、`fig10` 的热图 + 树都卡在这里 | 6 类常见版面（边缘分布、复合面板、插图、树 + 热图、地图 + 小图、拼图） | 2/35 | **不做**（同上；主图与边缘图各自出一张） |
| G3 | `annotate()` 未实现 | `from ggcore.plot import annotate` 不存在；每个标注要手写一个常量 `aes` 图层 + `inherit_aes=False` | 所有注释类图；R → Python 迁移摩擦最大的一处（gallery 几乎每页都用） | 1/35（但 gallery 常见度最高） | **已落地**（M3-1 / SIL-825：`annotate()` / `annotation_borders()` / `borders()`） |
| G4 | 标签避让（ggrepel） | `fig06` 12 个国名重叠；`check_overlap` 只按行序删除重叠，不做位移 | 所有带文字标签的散点 / 气泡 / 地图 | 1/35 | **不做**（ggrepel 是第三方；本体只有 `check_overlap`） |
| G5 | 单水平离散 r 轴上的 `coord_polar(theta="y")` | `aes(x=1)` / `aes(x="''")` 都报 `CoordError: 极坐标的 r_range 必须是两个有限且不等的数，收到 (1.0, 1.0)`；饼图的标准写法 `x = ""` 走不通 | 饼图 / 单组甜甜圈 / 单组极坐标柱 | 1/35（饼图是 gallery 头部页面） | **已修**（M3-1：`x = 1` 的单水平离散 r 轴可用，`fig16` 转 ✅） |
| G6 | `coord_sf()` 的真实投影 | `coord_sf(crs="ESRI:54009")` 在 `build_plot()` 抛 `SfError`（M2-1 只做 identity 投影） | 所有 choropleth / sf 图 | 1/35 | **已落地（4 个 CRS）**：EPSG:4326 / OGC:CRS84 / EPSG:3857 / EPSG:3347（M3-2）；其余投影需 PROJ，本仓不引入，`fig33` 取 3857 |
| G7 | `xlim()` / `ylim()` 简写 | 只有 `scale_x_continuous(limits=...)`；甜甜圈配方里的 `xlim(0.5, 2.5)` 要改写 | gallery 大量示例直接用 `xlim` / `ylim`；迁移摩擦 | 2/35（fig16 / fig17 的改写） | **迁移口径**（M3-6 对照表给 `coord_cartesian(xlim=, ylim=)`；不新增简写） |

**不是缺口（已覆盖，不重复建 case）**：极坐标 / 饼图 / 甜甜圈的几何；facet free scales 与
space=free；多图例合并与面板内定位；gradient2 / viridis / brewer / manual 色阶；
hexbin / contour / density_2d；boxplot / violin / jitter 叠加；日期轴；箭头 / label /
rect / segment 标注。这些在本次核对里都是「一次写成、一次通过」。

## 4. 六张不做的图：第三方扩展的真实报错与本体等价写法

这六张图依赖第三方扩展包的布局 / 几何。按 2026-11-04 的决策**只复刻 ggplot2 本体**，
不实现同名 API；脚本里的函数保留，`ImportError` 就是「确实没有」的证据。

| 图 | 最接近的调用 | 真实报错 | 本体等价写法 |
| --- | --- | --- | --- |
| `fig10` 聚类热图 | `geom_dendrogram` | `ImportError: cannot import name 'geom_dendrogram' from 'ggcore.plot'` | 热图用 `geom_tile`；行列顺序按自己算的聚类结果传给 `scale_*_discrete(limits=)`；树用 `geom_segment` 手画（行/列位置自己算），不做「树 + 热图」并置 |
| `fig22` 半小提琴 | `geom_split_violin` | `ImportError: cannot import name 'geom_split_violin'` | 两组 `geom_violin(position=position_dodge())` 并排；或上下镜像密度（`after_stat("density")` / `after_stat("-density")`，见 `examples/mirrored-density`） |
| `fig27` 流图 | `geom_stream` | `ImportError: cannot import name 'geom_stream'` | `geom_area(position="stack")`（或 `position="fill"` 看占比）；不居中、不平滑 |
| `fig32` 边缘分布 | `ggExtraMarginal` | `ImportError: cannot import name 'ggExtraMarginal'` | 主图 `geom_point` + `geom_smooth`，边缘分布另出一张 `geom_histogram` / `geom_density`；两张图并列，不拼 gtable |
| `fig34` 网络图 | `geom_edge_link` | `ImportError: cannot import name 'geom_edge_link'` | 节点坐标自己算（圆形 / 分层），边 `geom_segment` / `geom_curve`、节点 `geom_point` + `geom_text`；力导向布局是图算法，不在本体范围 |
| `fig35` 矩形树图 | `geom_treemap` | `ImportError: cannot import name 'geom_treemap'` | 占比用堆叠条 / 分组柱（`geom_col`）；要矩形版式就自己算坐标后 `geom_rect(aes(xmin, xmax, ymin, ymax, fill))` |

`fig33` 分级地图原来也在这一节：M3-2 的 `coord_sf()` 真实投影落地后，换成受支持的
`EPSG:3857`（`map_frame("usa", ".")` 的多边形按区域填色）已经能画，见 §2 第 33 行。

## 5. 复现

```bash
# 登记表：图号 / 三态 / gallery 页
pixi run audit:gallery --list

# 全部 35 张：构建 + SVG 到 .gallery-audit/（gitignore），out / missing 的图打印真实报错
pixi run audit:gallery

# 单张
pixi run audit:gallery fig17
```

输出末尾固定是 `35/35 符合登记`。若某个 `out` / `missing` 图哪天能构建成功，运行器会
打印 `STALE figNN` 并以非 0 退出——提醒更新本表，而不是让清单悄悄过期。

## 6. 边界

- 本 issue 不新增 CI case、不改任何 `expected.svg`、不进 `pixi run check` 的判据；
  脚本只写 `.gallery-audit/`（不入库）。
- **第三方扩展不做**（2026-11-04 决策）：patchwork / cowplot / ggrepel / ggforce /
  ggstream / ggExtra / ggraph / treemapify / circlize / PROJ 一律不引入；这类图只给
  本体等价写法（§4），不实现同名 API。`docs/examples.md` 的两张跳过项同理。
- 「可画」不等于「与 R 像素一致」：35 张没有参考图，像素判据仍由 `docs/cases/` 的
  166 条 case 与 M2-10 的 314 份上游快照承担。
- 缺口只登记进 SIL-715，不另建清单；后续按该 issue 的「追加规则」在对应 case 的
  `meta.toml` 里写 `ci = false` + issue key。

## 7. M3-7 收口（SIL-828）

M3-7 按父任务决策复核了本表 §4 的七张「画不出」图：**不实现第三方扩展包**，也不把
缺同名 API 的图塞进 gallery。处置与 §1.1 的四态一一对应：

| 图 | 处置 | 依据 |
| --- | --- | --- |
| `fig22` 半小提琴 / `fig27` 流图 / `fig34` 网络图 / `fig35` 矩形树图 | **不做**（`out`）：`geom_split_violin` / `geom_stream` / `geom_edge_link` / `geom_treemap` 这些同名 API 不实现，只给本体等价写法（§4） | 父任务 2026-11-04 决策：只复刻 ggplot2 本体 |
| `fig10` 聚类热图 / `fig32` 边缘分布 | **不做**（`out`）：ggdendro / patchwork / ggExtra 的版面与几何不实现；热图、树、边缘分布按 §4 的本体写法拆开画 | 同上（多图组合不在本体范围） |
| `fig33` 分级地图 | **转 ✅**：改用受支持的 `EPSG:3857` + `map_frame("usa")` 多边形按区域填色 | M3-2 已落地 4 个 CRS；`ESRI:54009` 需要 PROJ，X1 不引入 |

本表统计随之为 **27 ✅ / 2 ⚠️ / 6 ⛔**（可画 29/35）；`pixi run audit:gallery` 仍是
`35/35 符合登记`。

M3-7 的另一处 gallery 是 `web/viewer/dist/gallery.html`（案例库的浏览器卡片墙），
链接检查走 `pixi run gallery:check`（`tools/viewer/gallery_check.py`）；本表的 35 张
人工核对图与它不是同一份资产。文档与示例里的外链 / `pixi run` 入口由
`pixi run docs:links`（`tools/gallery/links.py`）检查。
