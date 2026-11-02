# 图例与主轴（guide / axis）

`ggcore.guide` 与 `ggcore.axis` 是 ggplot2 4.0.3 的 `guide_legend` / `guide_colourbar`
与 `guide_axis` 的对等物，M1-11 落地。整页装配在
`ggcore.geom.scene.plot_layout()` / `scene_from_build()`：

```
page（plot.margin）
├── plot.background
├── plot.title
├── legend 盒（right / left / top / bottom）
├── 每个面板：panel.background / panel.border / 图层 / strip
│   └── axis.ticks.* / axis.text.*（每个面板自己的标度）
└── x / y 轴标题（整块面板区一份）
```

参考实现：ggplot2 4.0.3（`pixi.toml` 的 `[feature.refs]` 钉死），R 侧夹具由
`pixi run -e refs refs:guide`（`tools/refs/guide_ref.R`）生成，Python 侧逐值对拍在
`tests/test_guide_r_parity.py`。

## 1. guide 的数据模型

| gg4py | R 4.0.3 | 说明 |
| --- | --- | --- |
| `GuideLegend` | `guide_legend()` | 离散键；`direction` / `nrow` / `ncol` / `byrow` / `override_aes` / `keywidth` / `keyheight` / `reverse` / `order` |
| `GuideColourbar` | `guide_colourbar()` | 连续色条；`barwidth` / `barheight` / `nbin` / `ticks` |
| `GuideNone` | `guide = "none"` | 该美学不画图例 |
| `GuideBuild` | `guide$train()` 的产物 | 一张要画的图例：美学、标题、键、参与绘制的图层 |
| `GuideKey` | `params$key` 的一行 | 标签 + 断点原值 + 各美学映射后的值 |

`plot.guides` 里的组件（`components.Guide`：注册名 + 参数）经
`guide_from_component()` 转成实现。未注册的名字（比如 `guide_bins`）明确报
`GuideError`，不降级成 `guide_legend`。

## 2. 合并规则（照 `Guide$merge()`）

R 4.0.3 的判据是 `hashables = (title, key$.label, name)`：**标题、按键标签、guide
类型三者都相同**才合并。`params$key <- cbind(params$key, new_key)` 把两个美学的
键值并到同一行，`params$aesthetic <- union(...)`；绘制时按图层顺序把每个图层的
key 图形叠在同一个 key 格里。

ggcore 的实现（`build_guides()`）：

1. 按固定顺序扫描 `colour / fill / size / shape / alpha`，每个美学最多一张 guide
   （`plot.guides` 里同美学后加的替换先加的，与 `plot.scales` 同一口径）；
2. 默认 guide：连续 colour / fill → `GuideColourbar`，其余 → `GuideLegend`；
3. 只有「被**映射**过的」美学进图例：`aes(colour = "g")` 进，
   `geom_point(colour = "red")`（常量）不进；`show_legend = False` 的图层排除；
4. `guide = "none"` 或 `legend.position = "none"` 直接没有图例；
5. 合并：`kind` + 标题 + 标签序列相同且美学不重叠 → 合成一张（`_can_merge`）；
6. 按 `order` 排序，同 order 按美学顺序（colour 先于 shape）。

由此得到三种典型结果（`tests/test_guide.py` 钉住）：

| 图 | 图例 |
| --- | --- |
| `colour = g` | 1 张 |
| `colour = g, fill = h`（不同变量） | 2 张，竖向叠放，`legend.spacing`（11pt）隔开 |
| `colour = g, shape = g`（同一变量） | 1 张，键同时带 colour 与 shape，键数不变 |

## 3. key 的绘制：复用 `Geom.draw()`

图例键不另写形状代码：`guide.key_table()` 造一张假数据表，再交给图层的
`Geom.draw()`，key 视口的 `xscale / yscale` 都是 `(0, 1)`，位置列由每个几何的
模板铺满 key 格：

| geom | 模板（key 视口里的数据坐标） |
| --- | --- |
| `point` | `x = y = 0.5` |
| `line` / `path` / `smooth` | `x = y = (0.2, 0.8)`（两个点才画得出线） |
| `bar` / `col` / `histogram` | `xmin/xmax/ymin/ymax = (0, 1)`（整格矩形） |
| `area` | `x = (0, 1)`，`ymin = 0`，`ymax = (0, 1)` |
| `boxplot` | `x = 0.5`、`xmin/xmax = (0.2, 0.8)`、五数 `(0.1, 0.3, 0.5, 0.7, 0.9)` |

模板之外的美学列取图层数据的**第一行**（`geom_point(colour = "red")` 的常量色因此
能带进图例），再被 guide 管理的键值覆盖；`override_aes` 最后覆盖。没有模板的
geom 报 `GuideError` 并点名已实现的 geom。

## 4. 尺寸口径

所有数字都来自主题（默认 `theme_grey()`，`--` 表示 R 4.0.3 的实测值，见 R 脚本）：

| 量 | 来源 / 公式 | 默认 |
| --- | --- | --- |
| key 宽 / 高 | `legend.key.width/height`（1.2 lines） | 1.2 × 12pt × 1.2 = 17.28pt = **0.6096cm** |
| key 行距 | 竖排方向 R 把 `legend.key.spacing.y` 置 0 | 0 |
| key 与标签的横向间距 | `legend.key.spacing.x`（5.5pt） | 0.1933cm |
| 图例内边距 | `legend.margin`（5.5pt 四边） | 0.1933cm |
| 标题行 | 文字行高 0.955em + `legend.key.spacing`（5.5pt） | 11pt 时 0.564cm（R 0.5573） |
| 标签宽 | `Metrics.strwidth()`（没有度量时 0.6em/字符） | — |
| 图例盒与面板的间隙 | `legend.box.spacing`（11pt） | 0.3866cm |
| 多张图例之间 | `legend.spacing`（11pt） | 0.3866cm |
| 色条 | 宽 = `legend.key.width`，高 = **5 ×** `legend.key.height` | 0.6096 × 3.048cm |

文字行高取 0.955em（`TEXT_LINE_EM`，与 `ggcore.facet` 的 strip 同一常量）：R 的
`stringHeight()` + `font_descent()` 在 8.8/11/20pt 上量出来都是 ≈0.94–0.96em。

### 与 R 的实测差（7×7in，容差要求 ≤ 0.5mm）

| 量 | gg4py | R 4.0.3 | 差 |
| --- | --- | --- | --- |
| `axis-l` 列宽 | 0.4973cm | 0.5270cm | 0.30mm |
| `axis-b` 行高 | 0.4704cm | 0.4718cm | 0.01mm |
| `ylab-l` 列宽 | 0.4672cm | 0.4606cm | 0.07mm |
| `xlab-b` 行高 | 0.4672cm | 0.4606cm | 0.07mm |
| `title` 行高 | 0.6380cm | 0.6235cm | 0.15mm |
| 离散图例盒 | 1.3512 × 2.7793cm | 1.3660 × 2.7727cm | 0.15 / 0.07mm |
| 色条图例盒 | 1.6746 × 3.9985cm | 1.7191 × 3.9919cm | 0.45 / 0.07mm |

剩余差异几乎都在**文字宽度**上：R 的 pdf 设备把 `sans` 解析成 Helvetica（数字
0.556em），我们的设备量表是 DejaVu/Noto（数字约 0.52em）。换成同一个字体后
差值会继续缩小；口径本身（`Metrics.strwidth`）不变。

### 整页表的结构

R 的 `ggplotGrob()` 在 4.0.3 里是一个 **16×13** 的 gtable（`layout` 里 21 行，
含 `background` / `spacer` / `axis-*` / `xlab-*` / `ylab-*` / `guide-box-*` /
`title` / `subtitle` / `caption`）。ggcore 不复刻这张表：`plot_layout()` 直接把
`plot.margin` / 标题行 / 图例盒 / 轴带 / 面板区算成 cm 矩形，`FacetTable` 只在
面板区里解析。区域语义一一对应（夹具的 `structure.regions` 记录了 R 的区域名，
`test_page_layout_covers_the_r_gtable_regions` 断言我们实现了同一组），但**行列数
不同**——像素级差异来自各区域的尺寸（上面那张表），不是表格行数。

## 5. 轴

- **断点 / 标签**取该面板自己的标度：`scale.breaks()` 给的是**变换后的空间**
  （`scale_x_log10()` → log10 值），离散标度的断点是水平名、位置按 `1..n` 换算；
  两条路径最后都落到 `(value - panel_low) / span` 的 npc。
- **连续 / 离散**的标签对齐相同（都在 tick 中间，`hjust = 0.5`）；区别只在位置
  来源。`labels = NULL` 或空串的断点不画 tick。
- **尺寸**：`axis.ticks.length`（2.75pt）+ `axis.text.*` 的 margin 与行高 +
  `axis.title.*` 的 margin 与行高，全部走 `resolve_theme()`；轴标题旋转 90° 时
  外向尺寸是行高而不是文字宽度。
- **位置**：x 轴在面板底边下方、y 轴在面板左边左侧；分面时每个面板各自一套
  （`scales = "free"` 时断点也各自取），轴标题整块面板区只画一份。
- `axis.line` / `axis.line.x` / `axis.line.y` 若解析成 `element_line()` 就画一条
  沿面板边的线（默认 `element_blank()`，不画）。

## 6. 轴 / 图例与 panel 的间距从哪来

| 间距 | 主题元素 | 默认 |
| --- | --- | --- |
| 页面四周 | `plot.margin` | 5.5pt（0.1933cm） |
| 刻度线长度 | `axis.ticks.length` | 2.75pt（0.0967cm） |
| 刻度与标签 | `axis.text.x/y` 的 margin | 2.2pt |
| 标签与轴标题 | `axis.title.x/y` 的 margin | 2.75pt |
| 标题行 | `plot.title` 的行高 + margin(b) | 13.2pt 文字 + 5.5pt |
| 面板之间 / strip 与面板 | `panel.spacing.x/y`、strip 元素 | 5.5pt（M1-6 的 facet 表） |
| 图例盒与面板 | `legend.box.spacing` | 11pt |
| 多图例之间 | `legend.spacing` | 11pt |

## 7. `theme_void()`：轴消失，图例保留

任务初稿写的是「`theme_void()` 下轴/图例都消失」，但 **ggplot2 4.0.3 的
`theme_void()` 只抹轴**（`legend.position` 仍是 `"right"`，`legend.margin` 归零、
`legend.background` 空白）。R 侧实测：`axis-l` / `axis-b` / `xlab` / `ylab` 全是
0，`guide-box-right` 仍有内容（图例盒 1.366cm 宽）。ggcore 按 R 的实际行为实现，
`tests/test_guide_r_parity.py::test_theme_void_axes_are_gone_but_the_legend_stays`
钉住这一点；需要图例也消失请显式 `theme(legend.position = "none")` 或
`guide = "none"`。

## 8. 未实现（明确报错 / 不静默）

| 能力 | 现状 |
| --- | --- |
| `guide_bins` / `guide_coloursteps` | 未注册；`guide_from_component()` 报 `GuideError` 并列出已实现的名字 |
| secondary axis（`sec_axis()`） | 未注册；没有 API，不会静默忽略 |
| `legend.position = "inside"` | `plot_layout()` 报 `GuideError`，点名「面板内定位未实现」 |
| `legend.position = c(x, y)`（数值坐标） | 同上 |
| 旋转的轴标签（`axis.text.*(angle != 0)`） | `axis_grobs()` 报 `AxisError`（锚点要照 R 的 `rotate_just()`，未做） |
| `legend.frame` / 高级图例盒子主题（`legend.box.just` 等） | 只画 `legend.frame` 的描边；`legend.box.background` 只画矩形 |
| 色条的 raster 渐变 | IR 的 `fill` 没有渐变类型（`docs/notes/ir.md` §12）；改成 `nbin` 个等高矩形，视觉一致、节点更多 |
| `override_aes` 的高级形态（逐键不同值） | 只支持标量覆盖所有键 |

## 9. 确定性

轴、图例、标题都是既有 grob（`segments` / `text` / `rect` / `Geom.draw()` 的产物）
拼出来的，没有新增 IR 字段；同一张图两次 `scene_from_plot()` → `ir.encode()` 的
sha256 相等（`tests/test_guide.py::test_axis_and_legend_are_deterministic`，覆盖
2×2 分面 + colour 图例 + 标题；9 个 geom 的旧断言仍在
`tests/test_geom_draw.py`）。`pixi run gate:determinism` 的载荷也加上了同一份整页
场景（`tools/gates/_determinism_child.py` 的 `plot_scene()`），三个
`PYTHONHASHSEED` 进程的 `plot_digest` 必须一致。

没有给 `metrics` 时，`scene_from_plot()` 用内置的 0.6em/0.955em 占位度量，保证
`text.width` 有值且字节稳定；`pixi run render` 传入 `ggskia.text.ShaperMetrics`
时以设备排版为准。

## 10. 复现

```bash
pixi run -e refs refs:guide       # 重新生成 tests/fixtures/guide_r_reference.json
pixi run test                     # 含 tests/test_axis.py / test_guide.py / test_guide_r_parity.py
pixi run render --scene <scene>.ggir.cbor --out report.png
```
