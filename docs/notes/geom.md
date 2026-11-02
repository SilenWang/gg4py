# geom 绘制口径（M1-7）

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

## 3. 九个 geom

| geom | 绘制口径（对 R 4.0.3） |
| --- | --- |
| `point` | `pointsGrob`；`size`（mm）+ `stroke` 折成 `fontsize = size * .pt + stroke * .stroke/2`；`col=alpha(colour, alpha)`、`fill=fill_alpha(fill, alpha)`；IR 的 `points.size` 是标量，所以逐点尺寸按 `(pch, size)` 分组画多个 `pointsGrob` |
| `line` / `path` | 每个 group 一条 `polylineGrob`；`line` 在 `setup_data()` 里按 `(PANEL, group, x)` 排序，`path` 保持行序；NA 用 `keep_mid_true()`：组内首尾缺失删掉、中间保留并断成两段；`lwd = linewidth * .pt` |
| `bar` / `col` | 直接用 M1-9 的 `xmin/xmax/ymin/ymax`，画矩形（`just = c("left","top")`）；`fill` 吃 alpha、`col` 不吃（R 的 `fill_alpha()` 只包 fill） |
| `histogram` | 与柱相同（`stat_bin` 归 M1-8；绘制只消费 `x/xmin/xmax/y/ymin/ymax`） |
| `area` | `ymin = 0`、`ymax = y`；上沿正向 + 下沿反向拼一个多边形（`fill` 吃 alpha，按 NA 断段），再按 `outline.type = "both"` 画上下两条轮廓线；横向（`flipped_aes`）在纵向语义拼完再 `flip_data(positions)`，多边形沿长度轴 x 从 `xmin` 铺到 `xmax` |
| `boxplot` | 须线 `(x, upper)→(x, ymax)` / `(x, lower)→(x, ymin)`；箱体 `xmin..xmax × lower..upper`；中位线线宽 `linewidth * fatten`（2）；离群点走 point 的口径（`size * .pt + stroke * .stroke/2`）；`varwidth` 用 `relvarwidth` 缩放箱宽 |
| `smooth` | `se != FALSE` 且有 `ymin/ymax` 时画 ribbon（填充、无边），再画拟合线（线不吃 alpha）；行序同 `line` |

`flipped_aes`（横向 bar / boxplot）照 R 的 `flip_data()`：先把 x/y 族列名对换，
在纵向语义下算完再对换回来。`Geom.setup_params()` 只对 R 里真的调用
`has_flipped_aes()` 的 geom 做检测（bar / col / histogram / area / boxplot /
smooth）；point / line / path 不猜朝向。

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

## 5. 与 R 的已知差异 / 未实现清单

| 能力 | 现状 | 去向 |
| --- | --- | --- |
| `arrow =` | 无 IR 表达 → `GeomError` 点名 | 箭头需要 IR schema 扩展 |
| `geom_boxplot(notch = TRUE)` | 无 IR 表达（缺口多边形）→ `GeomError` | 后续 |
| `geom_boxplot(staplewidth != 0)` | 无 IR 表达（须帽）→ `GeomError` | 后续 |
| 逐点 `size` / 逐点 `pch` | IR 的 `points.size` / `pch` 是标量；绘制层按 `(pch,size)` 分组画多个节点 | 视觉等价，节点数更多 |
| 一条线内部变化的 `linetype` | gpar 的 `lty` 不支持向量 → 取首值（R 会拆 `segmentsGrob`） | 后续 |
| 渐变填充（`fill` 沿 ribbon 变化） | 不支持；R 在非网格设备上同样 abort | 后续 |
| 直线坐标以外的 coord | 未注册（M1-5 的范围） | 后续 coord 任务 |
| 轴标签的 `check.overlap`（重叠时删标签） | 不删 | 后续（`axis.text` 的 `check.overlap`） |
| boxplot 的 `outliers` 列表列 | `ColumnTable` 没有 list kind；绘制层接受数值列或 `;` / `c(...)` 文本 | M1-8 的 `stat_boxplot` |

主题色（`fill = "grey35"` 等语义名）在 `build.data` 里仍是语义名，绘制期的
`fill_alpha()` 会按 `col2rgb()` 折算 RGB；与 R 的 `#595959FF` 在像素上一致。

## 6. 对拍与验收

```bash
pixi run -e refs refs:geom          # 夹具 + 9 张 expected.svg（R 4.5.3 / ggplot2 4.0.3）
pixi run pytest tests/test_geom_draw.py tests/test_geom_r_parity.py -q
pixi run cases:matrix               # 9 个 geom 用例逐张 render + diff
pixi run check                      # 全量门禁
```

夹具：`tests/fixtures/geom_r_reference.json`，14 个 case，记录
`ggplot_build(p)$data[[1]]` 的列名 / 列序 / kind / 逐值、`panel_params` 的
`continuous_range`，以及 `ggplotGrob()` 期间的 warning（`handle_na` 的
"Removed N rows"）。stat 已实现的 7 个 case 在 Python 侧重放整条流水线逐列对拍；
stat 未实现的 4 个（histogram / boxplot / smooth）把 R 的 `$data` 当绘制输入。

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
