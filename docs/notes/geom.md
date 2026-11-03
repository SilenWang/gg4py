# geom 绘制口径（M1-7 / M2-S2）

M1-7 把 `Geom.draw()` 从 `NotImplementedError` 做成真绘制：9 个 geom 的 grob 生成、
`handle_na()` / `setup_data()` / `setup_params()` 契约、坐标变换与裁剪，以及
`PlotBuild + FacetTable → ir.Scene` 的面板装配。

代码：

| 文件 | 内容 |
| --- | --- |
| `src/ggcore/geom/base.py` | `GeomRenderer` 契约、列读取、NA 删行、`flip_data`、`alpha_colour` |
| `src/ggcore/geom/point.py` | `geom_point`（shape 名表、逐点 size 分组） |
| `src/ggcore/geom/line.py` | `geom_line` / `geom_path`（断线、行序） |
| `src/ggcore/geom/bar.py` | `geom_bar` / `geom_col` / `geom_histogram` / `geom_area` |
| `src/ggcore/geom/boxplot.py` | `geom_boxplot`（五数 + 须线 + 中位线 + 离群点） |
| `src/ggcore/geom/smooth.py` | `geom_smooth`（se 带 + 拟合线） |
| `src/ggcore/geom/scene.py` | `PlotBuild + FacetTable → ir.Scene`（面板 / strip / clip） |
| `src/ggcore/geom/segment.py` | `segment` / `curve` / `spoke` / `abline` / `hline` / `vline`（M2-S2） |
| `src/ggcore/geom/rect.py` | `rect` / `tile` / `raster`（M2-S2，位图见 `ggcore.png`） |
| `src/ggcore/geom/polygon.py` | `polygon` / `ribbon` / `step`（M2-S2） |
| `src/ggcore/geom/interval.py` | `linerange` / `errorbar` / `errorbarh` / `pointrange` / `crossbar` |
| `src/ggcore/geom/annotation.py` | `blank` / `rug` / `map`（`map` 只做最小可用） |
| `src/ggcore/arrow.py` | `grid::arrow()` 的对等物 + 箭翼几何（`head_geometry`） |

## 1. 契约

绘制入口挂在 `ggcore.layer.Geom` 上；**构造函数路径不变**（`as_geom()` /
`geom_*()` 注册表仍然只产生 `Geom(name=…)` 数据对象），方法按名字查
`ggcore.geom` 的实现：

```python
Geom.draw(build, panel, coord, theme, metrics) -> Grob | GTable
Geom.handle_na(data, na_rm) -> ColumnTable
Geom.setup_data(data, params) -> ColumnTable
Geom.setup_params(data, params, *, raw=None) -> dict
```

- `build` 是这一面板的 `LayerBuild`（`data` 已按 `PANEL` 切好、已过
  `handle_na()`、带着图层的 `params` 与 `geom_object`）；
- `panel` 是 `coord.PanelParams`；`coord` 目前只透传（线性坐标的变换都在
  `panel.transform()` 里）；
- `theme` 是 `resolve_theme()` 的解析值，`metrics` 是 `Metrics`（strip 的
  `strheight` 与 text grob）。

`non_missing_aes` / `optional_aes` 与 ggplot2 4.0.3 同名同序（`GeomSpec` 里登记）：
point 的 `size/shape/colour`、line/path 的 `linewidth/colour/linetype`、bar 系列的
`xmin/xmax/ymin/ymax`、smooth 的 `ymin/ymax`。

## 2. 坐标与裁剪

- `coord$transform()` 的等价物是 `PanelParams.transform()`：位置列 → 面板 `0..1`
  （npc，y 向上）。grob 一律 `default_units="native"`，面板视口的 `xscale` /
  `yscale` 都是 `0..1`（与 `ggplotGrob()` 的 panel viewport 一致）。
- 越界值**不夹**：`coord_cartesian` 的语义是画到面板外再按 clip 处理。
- clip 三态（`on` / `off` / `inherit`）落在**面板视口**上，`on` 另加一个
  `ClipPathGrob`（矩形裁剪节点），不是画完再对位图做裁剪。`off` 是 R 的设备
  外包框（1.5×），`inherit` 沿用父视口（页面）。
- 每个面板一个 viewport + 自己的一份裁剪矩形；`facet_wrap` 2×2 的场景里有
  4 个互不相同、互不重叠的 `clip_rect`。

## 3. 九个 geom（M1-7）

| geom | 绘制口径（对 R 4.0.3） |
| --- | --- |
| `point` | `pointsGrob`；`size`（mm）+ `stroke` 折成 `fontsize = size * .pt + stroke * .stroke/2`；`col=alpha(colour, alpha)`、`fill=fill_alpha(fill, alpha)`；IR 的 `points.size` 是标量，所以逐点尺寸按 `(pch, size)` 分组画多个 `pointsGrob` |
| `line` / `path` | 每个 group 一条 `polylineGrob`；`line` 在 `setup_data()` 里按 `(PANEL, group, x)` 排序，`path` 保持行序；NA 用 `keep_mid_true()`：组内首尾缺失删掉、中间保留并断成两段；`lwd = linewidth * .pt` |
| `bar` / `col` | 直接用 M1-9 的 `xmin/xmax/ymin/ymax`，画矩形（`just = c("left","top")`）；`fill` 吃 alpha、`col` 不吃（R 的 `fill_alpha()` 只包 fill） |
| `histogram` | 与柱相同（`stat_bin` 见 `docs/notes/stat.md`；绘制只消费 `x/xmin/xmax/y/ymin/ymax`，`xmin/xmax`/`width` 由 stat 给） |
| `area` | `ymin = 0`、`ymax = y`；上沿正向 + 下沿反向拼一个多边形（`fill` 吃 alpha，按 NA 断段），再按 `outline.type = "both"` 画上下两条轮廓线；横向（`flipped_aes`）在纵向语义拼完再 `flip_data(positions)`，多边形沿长度轴 x 从 `xmin` 铺到 `xmax` |
| `boxplot` | 须线 `(x, upper)→(x, ymax)` / `(x, lower)→(x, ymin)`；箱体 `xmin..xmax × lower..upper`；中位线线宽 `linewidth * fatten`（2）；离群点走 point 的口径（`size * .pt + stroke * .stroke/2`）；`varwidth` 用 `relvarwidth` 缩放箱宽。横向（`flipped_aes`）把（粗细轴, 长度轴）在**一处**对换成页面 (x, y)——须线 / 箱体 / 中位线共用同一个 `axes()` 闭包，纵向的字节序不变（SIL-709 修的：之前只有离群点对换，箱体与中位线仍是竖向坐标） |
| `smooth` | `se != FALSE` 且有 `ymin/ymax` 时画 ribbon（填充、无边），再画拟合线（线不吃 alpha）；行序同 `line` |

`flipped_aes`（横向 bar / boxplot）照 R 的 `flip_data()`：先把 x/y 族列名对换，
在纵向语义下算完再对换回来。`Geom.setup_params()` 只对 R 里真的调用
`has_flipped_aes()` 的 geom 做检测（bar / col / histogram / area / boxplot /
smooth / density / violin）；point / line / path 不猜朝向。

### 3.1 M2-7 长尾 B：文本 / 点 / 分布 / 2D 族（SIL-735）

代码：`src/ggcore/geom/text.py`（`text` / `label`）与
`src/ggcore/geom/dist.py`（其余 18 个导出）。这一段的**统计量**归
M2-6 的 stat 任务；geom 只消费 stat 输出的列。stat 落地前，case 用
`stat = "identity"` 喂同形状的列，与 M1-7 对 boxplot / smooth 的口径一致。

| geom | 绘制口径（对 R 4.0.3） |
| --- | --- |
| `text` | `textGrob`：`compute_just()` 的 `left/centre/right/bottom/middle/top` 与 `inward/outward`；`size`（mm）× `size.unit`；`angle` / `hjust` / `vjust` 在 IR 里是单值，按 `(hjust, vjust, angle)` 分组画多个 text grob；`nudge_x` / `nudge_y` 折进数据坐标；`check_overlap` 用面板尺寸 + 真实度量算旋转后 bbox，按行序删重叠 |
| `label` | `labelGrob()`：`padding[1]=max(padding, descent)`、`padding[3]=max(padding-descent,0)`；背景宽 = 文字宽 + 左右内边距 + rotated descent，高同理；IR 无 roundrect，背景用方角矩形（`label.r` 默认 0.15 lines ≈ 2pt） |
| `jitter` | 绘制同 `geom_point`；`width` / `height` → `position_jitter(width=, height=)`（两者与 `position=` 同时给是上游的显式错误） |
| `count` | 绘制同 `geom_point`；`size` 来自 `stat_sum` 的 `n`（`_STAT_DEFAULT_AES` 的 `sum → size`） |
| `bin2d` / `bin_2d` | `x/y/width/height → xmin/xmax/ymin/ymax`（`GeomTile`），画矩形；非线性坐标按 `coord_munch` 细分 |
| `hex` | `hexbin::hexcoords(dx = width/2, dy = height/√3/2)` 的 6 个顶点；按 `(colour, fill, alpha, linewidth, linetype)` 分组，每组一个 `polygonGrob`（矢量 gp 表达不了） |
| `density` | 同 `geom_area` 的多边形 + `outline.type = "upper"`（只描上沿） |
| `density_2d` / `density2d` | 同 `geom_path`：每个 `group` 一条折线，默认 `accent` 色 |
| `density_2d_filled` / `density2d_filled` | 同 `geom_contour_filled` |
| `contour` | 同 `geom_path`（默认 `accent` 色） |
| `contour_filled` | 每个 band（`group`）一条 `pathGrob`：洞用 `subgroup` 拆子路径、`rule = "evenodd"` 填充 |
| `dotplot` | `setup_data()` 按 `count` 展开成点、按 bin（`binaxis`）+ group 求 `stackpos`；圆半径 = `dotsize × binwidth / 非堆叠轴范围 / 2`，堆叠偏移是**绝对长度**（按面板宽高比换轴）；`lwd` 照 `gg_par(lwd = stroke/.pt)` 的 `.pt` 往返 = `stroke` |
| `violin` | `xminv/xmaxv = x ∓ violinwidth × (x ∓ xmin)`；沿 y 排序、右沿反向、首尾闭合；`quantile.linetype != 0` 时再画分位线 |
| `qq` / `qq_line` | 绘制同 `geom_point` / `geom_path`（`x/y` 来自 `stat_qq` / `stat_qq_line`） |
| `quantile` | 绘制同 `geom_path`（`stat_quantile` 给多组分位线，默认 `accent` 色） |
| `function` | 绘制同 `geom_path`；多个绘制组时发 R 同文案的警告 |

**文本度量的来源**：`build.metrics`（M2-S1 的字体对齐结果，Arimo +
HarfBuzz kerning），geom 不各自测量；`geom_label` 的 descent 在
`ggskia.text.ShaperMetrics.descent()`，兜底实现按 0.22 em 估。
文本 case 的残余差异见 `docs/notes/metrics-ledger.md` M2-b（默认字面与参考
产线一致后的读数）。

**2D 等值带的填充语义**：`fill` 来自 `stat_contour_filled` 的 `level`
（factor），每个 band 一个 `group`，band 内的洞是同一 group 里的多条
`subgroup` 子路径；图例 key 复用同一个 `draw()`（`_GEOM_KEYS` 的
`contour_filled` 模板是一个 4 点多边形）。

## 4. 场景装配

```
page viewport（整页）
├── plot.background
├── panel viewport ×N（xscale/yscale = 0..1，clip = panel_params$clip）
│   ├── panel.background / panel.border
│   ├── clipPath（clip = "on"）
│   └── 每层 → Geom.draw()
└── strip（strip.background.x/.y + strip.text.x/.y）
```

- 面板矩形来自 `FacetTable.panel_boxes()`（M1-6 的 gtable 解析）；strip 的位置
  来自 gtable 的 layout，尺寸 / 间距 / 字号 / 颜色全部取 `resolve_theme()` 的
  解析值，不硬编码 cm / pt。
- strip 的行高 / 列宽：有 `metrics` 时走 `Metrics.strheight()`（真实
  ascent + descent），否则退回 M1-6 的 `_STRIP_TEXT_EM` 近似。`facet_table()`
  因此多了一个可选 `metrics=`。
- 图层按层序绘进各自面板；空层（0 行）与空面板不产生 grob。
- 单面板（`facet_null`）走同一条路径：1×1 表、面板就是整页。
- 轴、图例、标题由 M1-11 接上（`ggcore.axis` / `ggcore.guide`，
  见 `docs/notes/guide.md`）：M1-7 的面板 + strip 装配仍是同一条路径，
  `plot_layout()` 只是把面板区从整页里扣出来。

## 4.1 长尾 A 的 20 个 geom（M2-S2）

| geom | 绘制口径（对 R 4.0.3） |
| --- | --- |
| `segment` | 线性坐标一条 `segmentsGrob`（逐行 col / lwd / lty；`lineend` / `linejoin` 走参数）；非线性坐标逐行拆成折线 |
| `curve` | `curveGrob(square = FALSE, squareShape = 1, open = TRUE)`；一条曲线一个 grob（IR 的 curve 节点一次一段） |
| `spoke` | `setup_data()` 先算 `xend = x + cos(angle) * radius`，绘制同 segment |
| `abline` / `hline` / `vline` | 端点取自 `PanelParams.backtransform_range()`；`abline` 在 `clip == "on"` 时先把范围扩一个跨度；`unique0(data)` 去重（参数形态的图层数据是 1 行，不去重会画两遍） |
| `rect` | `resolve_rect()` 补缺角（`x/width/xmin/xmax` 里给两个），`rectGrob(xmin, ymax, just = c("left","top"))` |
| `tile` | `compute_data_size(panels = "by", discrete = TRUE)` 求 `width` / `height`（缺省 1） |
| `raster` | 等距格点 → `(nrow, ncol, 4)` 像素矩阵 → RGBA PNG（`ggcore.png`）+ `rasterGrob(interpolate)`；非线性坐标降级成 rect（`linewidth = 0.3`、`colour = fill`） |
| `polygon` | `coord_munch(..., is_closed = TRUE)` 后每组一只多边形；有 `subgroup` 时走 `pathGrob(rule)` |
| `ribbon` | 上沿正向 + 下沿反向拼**一个环**；`outline.type` = both / upper / lower / full；沿 ribbon 变化的美学报错 |
| `step` | `stairstep()` 逐 group 展开（`hv` / `vh` / `mid`，横向时 hv ↔ vh 互换），再交给 `GeomPath` |
| `errorbar` / `errorbarh` | 每行 8 个顶点（帽、竖线、帽），NaN 断开；`width` 走 `compute_data_size(..., discrete = TRUE)`；`errorbarh` 在 4.0.3 是 `geom_errorbar(orientation = "y")` 的软弃用别名（`height` → `width`） |
| `linerange` | 纵向 `(x, ymin)→(x, ymax)`；横向 `(xmin, y) → (xmax, y)`；方向由 `range_is_orthogonal` 推断 |
| `pointrange` | linerange + 中点（点大小 `size * 4`） |
| `crossbar` | 箱体多边形 + 中位线（`linewidth * fatten`，`fatten = 2.5`）；`middle.*` / `box.*` 覆盖参数；缺口报错 |
| `blank` | `nullGrob()`：只训练标度，不产出叶子 |
| `rug` | 按 `sides`（t/b/l/r）在面板边上画短刻度；`length` 缺省 0.03 npc，`outside = TRUE` 伸到面板外 |
| `map` | `map`（`{x, y, id}`）与 `map_id` 取交集，逐 id 一只多边形；不做投影、不带地图数据 |

**横向（`flipped_aes`）的推断**照 `has_flipped_aes()`：

- `boxplot` / `area`：`boxplot` 走 `main_is_orthogonal` + 列类型（y 离散 → 横向）；
  `area` 传 `ambiguous = TRUE`，**没有 explicit orientation 时永远竖向**（R 侧
  `StatAlign` 也是同一个开关）。横向面积两侧都写 `orientation = "y"`（或 R 的
  `coord_flip()`）——见 `docs/cases/README.md` 的 SIL-715 #4。
- 区间族（`ribbon` / `linerange` / `errorbar*`）：`range_is_orthogonal = TRUE`，
  按「y 族区间在场 → 纵向 / x 族区间在场 → 横向」推断，不看列类型。

**箭头的段长换算**：`lty` 的段长是 `lwd` 的倍数，且 `lwd < 1` 时按 1 算（参考产线
svglite 的口径；细线的虚线不会退化成实线）。段长本身在写 IR 之前折成 pt。

## 5. 与 R 的已知差异 / 未实现清单

| 能力 | 现状 | 去向 |
| --- | --- | --- |
| `arrow =` | v0.3 起是 `segments` / `polyline` / `curve` 的节点参数（§4.1 of `ir.md`），设备画箭翼 | 无 |
| `geom_crossbar(notch)` / 缺口 | 无 IR 表达 → `GeomError` | 后续 |
| `geom_map` 的投影 / 地图数据 | 只做「map 表 + map_id」的最小可用 | 归 M3-2 |
| `geom_boxplot(notch = TRUE)` | 无 IR 表达（缺口多边形）→ `GeomError` | 后续 |
| `geom_boxplot(staplewidth != 0)` | 无 IR 表达（须帽）→ `GeomError` | 后续 |
| 逐点 `size` / 逐点 `pch` | IR 的 `points.size` / `pch` 是标量；绘制层按 `(pch,size)` 分组画多个节点 | 视觉等价，节点数更多 |
| 逐行 `angle` / `hjust` / `vjust`（text） | IR 的 text 参数是单值；按 `(hjust, vjust, angle)` 分组画多个 text grob | 视觉等价，节点数更多 |
| `geom_label` 的圆角（`label.r`） | IR 没有 roundrect 节点 → 方角矩形（默认 0.15 lines ≈ 2pt） | 后续 IR schema 扩展 |
| `geom_hex` 的矢量 gp | 一个 path 节点只有一份 gpar；按 `(colour, fill, alpha, linewidth, linetype)` 分组 | 视觉等价，节点数更多 |
| 未映射的 data 列 | 我们的 `compute_aesthetics` 只留 mapped 列（R 保留整个 data.frame）；`stat = "identity"` 要喂 `width` / `height` / `subgroup` 这类列时必须 `aes()` 映射 | 与 M1-3 的列口径一致；stat 落地后由 stat 输出携带 |
| `geom_dotplot(binaxis = "y")` | 支持；`binaxis` 非 `x` 时圆半径按 y 轴换算（`CircleGrob.r_axis`） | — |
| 一条线内部变化的 `linetype` | gpar 的 `lty` 不支持向量 → 取首值（R 会拆 `segmentsGrob`） | 后续 |
| 渐变填充（`fill` 沿 ribbon 变化） | 不支持；R 在非网格设备上同样 abort | 后续 |
| 直线坐标以外的 coord | 未注册（M1-5 的范围） | 后续 coord 任务 |
| 轴标签的 `check.overlap`（重叠时删标签） | 不删 | 后续（`axis.text` 的 `check.overlap`） |
| boxplot 的 `outliers` 列表列 | `ColumnTable` 没有 list kind；`stat_boxplot` 产 `str` 文本（`c(20)` / `c()`），绘制层解析它 | 加 list kind 时再改（见 `stat.md` §4） |
| 2D / 分布族的 stat | `stat_density` / `stat_ydensity` / `stat_bindot` / `stat_bin_2d` / `stat_bin_hex` / `stat_contour(_filled)` / `stat_density_2d(_filled)` / `stat_qq(_line)` / `stat_quantile` / `stat_function` / `stat_sum` 归 M2-6；geom 的默认 stat 名已按上游登记，stat 未实现时 `compute_stat()` 点名报错 | M2-6 |

主题色（`fill = "grey35"` 等语义名）在 `build.data` 里仍是语义名，绘制期的
`fill_alpha()` 会按 `col2rgb()` 折算 RGB；与 R 的 `#595959FF` 在像素上一致。

## 6. 对拍与验收

```bash
pixi run -e refs refs:geom          # 夹具 + 58 张 expected.svg（R 4.5.3 / ggplot2 4.0.3）
pixi run pytest tests/test_geom_draw.py tests/test_geom_r_parity.py tests/test_geom_long_tail_b.py -q
pixi run cases:matrix               # 全部 geom 用例逐张 render + diff
pixi run check                      # 全量门禁
```

M2-S2 的 20 个 geom 另有 18 条 case（`geom-segment-arrow` … `geom-area-horizontal`）
与 22 条 R 夹具 case（`tests/test_geom_r_parity.py` 的 `NEW_BUILDERS`），逐列对拍
`ggplot_build(p)$data[[1]]` 的列名 / 列序 / kind / 值；像素对拍全部 < 2% / < 1%。

夹具：`tests/fixtures/geom_r_reference.json`，59 个 case，记录
`ggplot_build(p)$data[[1]]` 的列名 / 列序 / kind / 逐值、`panel_params` 的
`continuous_range`，以及 `ggplotGrob()` 期间的 warning（`handle_na` 的
"Removed N rows"）。stat 已实现的 case 在 Python 侧重放整条流水线逐列对拍；
stat 未实现的部分（M1 的 histogram / boxplot / smooth，M2-7 的 2D / 分布族）
把 R 的 `$data`（或 stat 形状的列）当绘制输入。

M2-7 的 22 条新 case（`docs/cases/geom-*`）走 `stat = "identity"` + stat 形状
的列，实测全部在图级 < 2% / 均值 < 1% 的阈值内（`pixi run cases:matrix` 100/100
pass）；文本三条（对齐 / 旋转 / 换行）与 label 一条也在阈值内，残余差异来自
字体度量的亚像素，见 `docs/notes/metrics-ledger.md` M2-b。

九张用例图对 R 参考的实测差异（`pixi run diff`）：

| case | 图级 | 平均 |
| --- | --- | --- |
| `geom-point-shapes` | < 1% | < 1% |
| `geom-line-groups` | 0.000% | 0.000% |
| `geom-path-order` | 0.000% | 0.000% |
| `geom-bar-stacked` | 0.000% | 0.000% |
| `geom-col-identity` | 0.000% | 0.000% |
| `geom-area-identity` | 0.000% | 0.000% |
| `geom-histogram-identity` | 0.000% | 0.000% |
| `geom-boxplot-precomputed` | < 2% | < 1% |
| `geom-smooth-se` | 0.019% | 0.001% |

（点与箱线图的残余差异来自符号边缘的抗锯齿；两者都在 2% / 1% 阈值内。）

## 7. 变更记录

| 日期 | 任务 | 改动 | 原因 |
| --- | --- | --- | --- |
| 2026-11-03 | SIL-737 / M2-S2 | 长尾 A：20 个 geom（线段 / 矩形 / 区间 / 标注族）+ IR 0.3 的箭头标记属性（`segments` / `polyline` / `curve`）+ `geom_raster` 的位图路径（`ggcore.png`）+ lty 段长按 `max(lwd, 1)` 折算（参考产线口径）。`geom_abline` / `hline` / `vline` 改成上游的「参数即图层数据」形态（`inherit_aes = FALSE`、`unique0(data)`）。 | M2 长尾补齐；SIL-715 #4/#5 结案。 |
| 2026-11-02 | SIL-709 / SIL-716 | 横向 `geom_boxplot`：`draw()` 里新增 `axes()`，flip 时把长度值（`xlower` / `xupper` / `xmin` / `xmax`）摆到 x、类别位置摆到 y；须线 / 箱体 / 中位线共用这一处对换，纵向分支仍返回原顺序（字节序不变）。 | M1-15 写 `geom-boxplot-horizontal` case 时发现：修前只有离群点做了对换，箱体与中位线仍按纵向坐标拼，横向箱线图整只箱被摆错方向。回归：`tests/test_geom_draw.py::test_horizontal_boxplot_puts_length_on_x_and_category_on_y`。 |
| 2026-11-03 | SIL-735 | 新增 20 个 geom 注册名（18 个导出 + `bin_2d` / `density2d` / `density2d_filled` 别名）与两套绘制实现：`geom/text.py`（text / label）、`geom/dist.py`（density / violin / dotplot / hex / bin2d / contour(_filled) / density_2d(_filled) / qq(_line) / quantile / function / count / jitter）。`AreaRenderer` 支持 `outline.type`；`CircleGrob` 支持 `r_axis`；`compute_position()` 保留 `setup_data()` 改变后的行数（dotplot 按 count 展开）；`PanelParams` 增加面板尺寸（text 的 `check_overlap` / label 的内边距换算）。 | M2-7 长尾 B：文本 / 点 / 分布 / 2D 族补齐；22 条新 case（文本 3 + label 1 + 其余每族 1–2 条）走 `stat = "identity"` + stat 形状的列，`cases:matrix` 100/100 通过。 |
