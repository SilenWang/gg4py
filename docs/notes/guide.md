# 图例与主轴（guide / axis）

`ggcore.guide` 与 `ggcore.axis` 是 ggplot2 4.0.3 的 `guide_legend` / `guide_colourbar`
/ `guide_custom` 与 `guide_axis` 的对等物，M1-11 落地、M2-2（SIL-738）补齐
`guides()` 入口 / key 合并 / 多美学图例 / override / 图例盒布局。整页装配在
`ggcore.geom.scene.plot_layout()` / `scene_from_build()`：

```
page（plot.margin）
├── plot.background
├── plot.title
├── legend 盒（right / left / top / bottom / inside；多方位可并存）
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
| `GuideLegend` | `guide_legend()` | 离散键；`direction` / `nrow` / `ncol` / `byrow` / `override_aes` / `keywidth` / `keyheight` / `reverse` / `order` / `position` / `title_position` / `title_hjust` / `title_vjust` / `label_position` / `label_hjust` / `label_vjust` / `subtitle` |
| `GuideColourbar` | `guide_colourbar()` | 连续色条；`barwidth` / `barheight` / `nbin` / `ticks` / `position` |
| `GuideCustom` | `guide_custom()` | 任意 grob（或 `(width_cm, height_cm) -> grob` 可调用对象）放进图例盒，不绑定标度 |
| `GuideNone` | `guide = "none"` | 该美学不画图例 |
| `GuideBuild` | `guide$train()` 的产物 | 一张要画的图例：美学、标题、键、参与绘制的图层、`position` |
| `GuideKey` | `params$key` 的一行 | 标签 + 断点原值 + 各美学映射后的值 |

`plot.guides` 里的组件（`components.Guide`：注册名 + 参数）经
`guide_from_component()` 转成实现；`guides(...)`（`ggcore.plot`）产生
`components.Guides`，`p + guides(...)` 按美学把条目写进 `plot.guides`（后加替换
先加，值 `None` = 取消 plot 级设置、回落到 `scale_*(guide=)`，值 `False` 按
`"none"` 处理）。条目值可以是字符串、注册表组件、`Guide` 实现，也可以是
`guide_custom()` 这种无标度 guide（键名任意，如 `guides(custom = ...)`）。

`scale_*(guide = )` 也认（SIL-705）：字符串（`"none"` / `"legend"` /
`"colourbar"`）、`components.Guide`（`registry.guide_legend(...)`）与
`ggcore.guide` 的 `Guide` 实例（`guide_legend(...)`）三种写法等价；
`plot.guides` 里同美学的条目优先于它（`build_guides()` 先查 `plot.guides`，
没有条目才回落到 `scale.params["guide"]`）。通过
`registry.register_guide(name, ComponentSubclass)` 登记的自定义类型也能用字符串
点名（组件子类覆写 `build_guide()`，见下）；未注册的名字（比如 `guide_bins`）
明确报 `GuideError`，不降级。

### 扩展点（与 M2-9 的注册表扩展 API 对齐）

| 方法 | R 4.0.3 | 默认行为 |
| --- | --- | --- |
| `Guide.train(build, aesthetic, scale)` | `Guide$train()` | 从标度的 breaks / map / labels 提取键，返回 `GuideBuild` |
| `Guide.transform(keys)` | `Guide$transform()` | 恒等（色条之类的变换在这里做） |
| `Guide.geom(layer)` | `Guide$geom()` | 返回 `None`：键图形复用图层自己的 `Geom.draw()` |
| `Guide.gengrob(guide_build, build, theme, layout)` | `Guide$draw()` / `guide_gengrob` | 画成 grob 列表（默认 `legend_grob()`） |
| `Guide.draw_keys(...)`（M2-9） | 无直接对等物 | 不实现；实现时 key 区由它画，标题 / 背景仍走默认路径 |

注册路径是 M2-9 的 `registry.register_guide(name, ComponentSubclass)`：
组件子类覆写 `build_guide()` 返回运行期 `Guide` 实例（`docs/notes/extension.md`
的「自定义 guide」一节有完整示例）。`tests/test_guide.py` 的 `_DescribeGuide`
与 `test_registered_guide_component_uses_build_guide_and_draw_keys` 是两组最小示例。
`guide_custom()` 就是 `GuideCustom` 覆盖 `train()`（返回 `None`）与
`gengrob()` 的一个实例。

### 方位（`position`）

`guide_legend(position=)` / `guide_colourbar(position=)` / `guide_custom(position=)`
覆盖整张图的 `legend.position`；不同 guide 可以落在不同方位。对齐 R 4.0.3：

- `right` / `left` → 竖排盒（`legend.box` 默认 `vertical`），在 panel 行里垂直居中；
  横向贴 **panel 单元格**的边（`panel_area` 的右边 / 左边）而不是页面内区：
  等比例面板（`coord_polar()` 的正圆）比内区窄，多出来的空白留在图例右侧；
- `top` / `bottom` → 横排盒（默认 `horizontal`），水平居中；
- `inside` → 用 `legend.position.inside = c(x, y)`（npc）+ `legend.justification.inside`
  锚在面板区内，**不占版面**；`legend.position = c(x, y)` 等价于 inside。

## 2. 合并规则（照 `Guide$merge()` / `Guides$merge()`）

R 4.0.3 的判据是 `hashables = (title, key$.label, name)`：**标题、按键标签、guide
类型三者都相同**才合并；`Guides$merge()` 分组用的键是 `order` + 这三个值的 hash
（`orders[orders == 0] <- 99`，即没写 order 的排在显式 order 之后）。
`params$key <- cbind(params$key, new_key)` 把两个美学的键值并到同一行（只保留
第一个 guide 的 `.label` / `.value`），`params$aesthetic <- union(...)`；
`override.aes` 先到先得，重名的后来者被忽略并告警。绘制时按图层顺序把每个图层的
key 图形叠在同一个 key 格里。

ggcore 的实现（`build_guides()`）：

1. 按固定顺序扫描 `colour / fill / size / shape / alpha / linetype / linewidth`，
   每个美学最多一张 guide（`GUIDE_AESTHETICS`；后两个是 M2-4 B 加的——linetype /
   linewidth 的键分别画成短线段与不同粗细的线段）
   （`plot.guides` 里同美学后加的替换先加的，与 `plot.scales` 同一口径）；
2. 默认 guide：连续 colour / fill → `GuideColourbar`，其余 → `GuideLegend`；
3. 只有「被**映射**过的」美学进图例：`aes(colour = "g")` 进，
   `geom_point(colour = "red")`（常量）不进；`show_legend = False` 的图层排除。
   `Stat$default_aes` 补出来的映射也算：`geom_hex()` 的
   `fill = after_stat(count)` 出 `count` 的 colourbar（标题用 stat 输出列名）；
4. `guide = "none"`（`plot.guides` 或 `scale_*(guide = )`）或
   `legend.position = "none"` 直接没有图例；
5. 每个美学 `guide.train()` → `GuideBuild`；再按 `order` + `(kind, title, 标签序列)`
   分组，组内 `Reduce(merge)`（`_merge_guides` / `_merge`）；
6. `guide_custom()` 不绑标度，单独收集，按 `(title, grob 身份, 尺寸, order, position)`
   去重后与普通 guide 一起排序；
7. 排序键：`(order == 0 ? 99 : order, 美学顺序)`，显式 order 小的在前。

**与 R 的一处已知差异**：`order` 相同（多为两张都没写 order）时，R 用
`rlang::hash()`（xxhash）的字符串排先后，属于不可复现的内部值；ggcore 固定按
美学顺序（colour 先于 fill / shape）。两张图例同侧叠放时这会改变谁在上/左；
需要与 R 完全一致的顺序时显式给 `guide_legend(order=)`（新增的
`guide-legend-two` case 就是这么钉的）。

由此得到三种典型结果（`tests/test_guide.py` 钉住）：

| 图 | 图例 |
| --- | --- |
| `colour = g` | 1 张 |
| `colour = g, fill = h`（不同变量） | 2 张，竖向叠放，`legend.spacing`（11pt）隔开 |
| `colour = g, shape = g`（同一变量） | 1 张，键同时带 colour 与 shape，键数不变 |
| `colour = g, fill = g`（同一变量） | 1 张，键同时带描边与填充（`guide-legend-merge-fill`） |

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

**只有常量美学进 key**（SIL-705）：被标度映射、但不由这张 guide 管理的美学不能
从第一行带进来，否则 `colour = cyl, fill = gear` + `shape = 21` 时 colour 图例的
圆会被灌进第一行的 `fill`。实现上 `key_table()` 接收图层的 `raw_mappings`：
`colour` / `fill` 置成全 NA（与 R 一致：colour 图例的圆只有 stroke，fill 图例的
圆只有 fill），其余映射美学直接省略、回落到几何默认值（mapped `size` 不参与
colour 图例，键用 1.5mm 的默认点大小）。

## 4. 尺寸口径

所有数字都来自主题（默认 `theme_grey()`，`--` 表示 R 4.0.3 的实测值，见 R 脚本）：

| 量 | 来源 / 公式 | 默认 |
| --- | --- | --- |
| key 宽 / 高 | `legend.key.width/height`（1.2 lines） | 1.2 × 12pt × 1.2 = 17.28pt = **0.6096cm** |
| key 行距 | 竖排方向 R 把 `legend.key.spacing.y` 置 0 | 0 |
| key 与标签的间距 | `legend.key.spacing`（5.5pt）折进标签的 margin：标签列宽 = 间距 + 文字宽 | 0.1933cm |
| 网格列之间的间距 | `legend.key.spacing.x`（5.5pt，只在 ncol > 1 时占一列） | 0.1933cm |
| 图例内边距 | `legend.margin`（5.5pt 四边） | 0.1933cm |
| 标题占位 | `legend.title` 的行高 + 朝内容一侧的 `legend.key.spacing`（top/bottom 是一行，left/right 是一列） | 11pt 时 R 0.5573cm |
| 标签 / 标题的对齐 | `title_hjust` / `title_vjust` / `label_hjust` / `label_vjust`（缺省取 `legend.title` / `legend.text` 的 hjust/vjust） | 标题 hjust = 0；标签按方位（left → 1，其余 → 0） |
| 标签宽 | `Metrics.strwidth()`（没有度量时 0.6em/字符） | — |
| 图例盒与面板的间隙 | `legend.box.spacing`（11pt） | 0.3866cm |
| 多张图例之间 | `legend.spacing`（11pt）；横排用 `legend.spacing.x`，竖排用 `legend.spacing.y` | 0.3866cm |
| 图例盒内边距 | `legend.box.margin` | 0 |
| 色条（竖向） | 宽 = `legend.key.width`，高 = **5 ×** `legend.key.height` | 0.6096 × 3.048cm |
| 色条（横向） | 宽 = **5 ×** `legend.key.width`，高 = `legend.key.height`；断点标签排在色条下方一行 | 3.048 × 0.6096cm（R 的盒高 1.487cm） |
| 横排键网格 | 未给 nrow/ncol 时 `nrow = ceil(n / 5)`；竖排 `ncol = ceil(n / 20)` | — |

`LegendLayout.col_widths_cm` / `row_heights_cm` 按 **R 的 gtable 分解**给出列宽 /
行高：`[legend.margin 左] [标题列] [键列, 标签列, (间距, 键列, 标签列)…] [标题列] [legend.margin 右]`，
行同理。标签侧的间距折在标签列里（R `measure_grobs()` 的 interleave 口径），
所以 ncol = 1 时没有单独的间距列，ncol ≥ 2 时列与列之间才出现一列 `spacing_x`。
`LegendBoxLayout` 再按 `legend.box` / `legend.box.just` / `legend.spacing.*`
把同一方位的图例排成 `gtable_col`（竖排）或 `gtable_row`（横排）。
`tests/test_guide_r_parity.py::test_legend_row_and_column_sizes_match_r` 逐项对拍
R 的 `guide$widths / heights`（容差 0.05cm）。

文字行高取 **0.894em**（`TEXT_LINE_EM`）：R 4.5.3 + svglite 的
`stringHeight()` + `font_descent()` 在 8.8 / 11 / 20pt 上都是 0.894em
（Arimo 的 cap height 0.691em + descent 0.203em）。旧值 0.955em 是 **pdf 设备**
（Helvetica）的口径，用它排 4×3 svglite 参考图时轴带高 1.2pt、面板底边整条错。

列宽里的**拉丁文字**用 `LAYOUT_LATIN_FONT = "Arimo"` 量宽度（M2-a 把参考产线的
默认拉丁字面定位成 Arimo，与绘制端 `ggskia.text.SANS_FAMILY` 同一字面）。
之前用 Noto Sans 时 `gear` 这类字符串宽 7%（`g` 的字面差），图例盒 / y 轴列宽
整体偏；换回 Arimo 后 16 个 `refs:guide` case 的行列尺寸全部落在 0.5mm 内。
这里只量列宽 / 图例标签盒，IR 的 `text.width` 仍由绘制端按自己的字面量。

### 与 R 的实测差（7×7in，容差要求 ≤ 0.5mm）

| 量 | gg4py | R 4.0.3 | 差 |
| --- | --- | --- | --- |
| `axis-l` 列宽 | 0.5193cm | 0.5270cm | 0.08mm |
| `axis-b` 行高 | 0.4517cm | 0.4718cm | 0.20mm |
| `ylab-l` 列宽 | 0.4438cm | 0.4606cm | 0.17mm |
| `xlab-b` 行高 | 0.4438cm | 0.4606cm | 0.17mm |
| 离散图例盒 | 1.3622 × 2.7558cm | 1.3660 × 2.7727cm | 0.04 / 0.17mm |
| 色条图例盒 | 1.7075 × 3.9750cm | 1.7191 × 3.9919cm | 0.12 / 0.17mm |

换回 Arimo 后**宽度**差已经到 0.1mm 量级；剩余差异几乎都在**文字行高**上
（0.894em 与 R 的 0.878em 差 0.017em，11pt 时约 0.17mm），所以竖向尺寸系统性
偏小一点。口径本身（`Metrics.strwidth` / `text_line_cm`）不变；16 个
`refs:guide` case 的图例行列都落在 0.5mm 容差内。

### 整页表的结构

R 的 `ggplotGrob()` 在 4.0.3 里是一个 **16×13** 的 gtable（`layout` 里 21 行，
含 `background` / `spacer` / `axis-*` / `xlab-*` / `ylab-*` / `guide-box-*` /
`title` / `subtitle` / `caption`）。ggcore 不复刻这张表：`plot_layout()` 直接把
`plot.margin` / 标题行 / 图例盒 / 轴带 / 面板区算成 cm 矩形，`FacetTable` 只在
面板区里解析。区域语义一一对应（夹具的 `structure.regions` 记录了 R 的区域名，
`test_page_layout_covers_the_r_gtable_regions` 断言我们实现了同一组），但**行列数
不同**——像素级差异来自各区域的尺寸（上面那张表），不是表格行数。

**竖向图例的纵向位置**：R 的 guide 列挂在**面板行**上（strip 在 gtable 里是独立
行，`guide-box-right` 的 `t`/`b` 只跨 panel 行），所以居中区 = 所有面板单元格的
并集，顶部 / 底部 strip 带不算；分面时图例比整个 `panel_area` 的中心低半个 strip
（2×2 + `theme_grey` 的 R 报告图：strip 16.66pt，中心 112.28 vs 103.95）。
`tests/test_guide.py::test_vertical_legend_is_centred_on_the_panel_rows` 钉 ±0.1pt，
单面板（没有 strip，panel 行 == `panel_area`）不许因此移动。SIL-725。

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
  （`scales = "free"` 时断点也各自取），轴标题整块面板区只画一份。轴标题的
  摆放区是 **panel 单元格的并集**，不是 `panel_area`：`facet_grid` 的 strip
  自带一行 / 一列，标题的中心不能把它算进去（SIL-817：行 strip 在右侧时，
  拿 `panel_area` 居中会把 x 标题右推半个 strip 宽；`axis_title_area()`）。
- `axis.line` / `axis.line.x` / `axis.line.y` 若解析成 `element_line()` 就画一条
  沿面板边的线（默认 `element_blank()`，不画）。

## 6. 轴 / 图例与 panel 的间距从哪来

| 间距 | 主题元素 | 默认 |
| --- | --- | --- |
| 页面四周 | `plot.margin` | 5.5pt（0.1933cm） |
| 刻度线长度 | `axis.ticks.length` | 2.75pt（0.0967cm）；`axis.ticks.*` 是 `element_blank()` 时为 0（R 量的是 zeroGrob） |
| 刻度与标签 | `axis.text.<aes>.<side>` 的 margin | 2.2pt（`theme_minimal()` 的 side-specific 元素是 4.95pt） |
| 标签与轴标题 | `axis.title.x/y` 的 margin | 2.75pt |
| 标题行 | `plot.title` 的行高 + margin(b) | 13.2pt 文字 + 5.5pt |
| 面板之间 / strip 与面板 | `panel.spacing.x/y`、strip 元素 | 5.5pt（M1-6 的 facet 表） |
| 图例盒与面板 | `legend.box.spacing` | 11pt |
| 多图例之间 | `legend.spacing` | 11pt |

### 6.1 图例盒挂在哪一格

R 的 guide-box 不进 `panel_area` 的居中逻辑，而是挂在 gtable 的**具体行列**上：

- `guide-box-right` / `-left` 的 t..b = panel 行（顶部 / 底部 strip 行不算），所以
  竖向图例的中心是 **panel 行的中心**，不是整个面板区的中心——分面时二者差半条
  strip（M1 的「分面竖向图例上移」，SIL-724）。
- `guide-box-top` / `-bottom` 的 l..r = panel **列**。`facet_grid` 的行 strip 自成
  一列（`strip.placement = "inside"` 时它在面板区里面），所以拿整个 `panel_area`
  居中会把图例往右推半个 strip 宽（SIL-743 修：`matrix-facet-grid-margins-*`
  2.12% → 1.76%）。

`ggcore.geom.scene` 用 `panel_rows` / `panel_cols` 两个「面板单元格的并集」分别
实现这两条；`tests/test_cases_matrix_combos.py` 用 2×2 分面 × 极坐标的 case 钉住
行高、键间距与居中。

## 7. `theme_void()`：轴消失，图例保留

任务初稿写的是「`theme_void()` 下轴/图例都消失」，但 **ggplot2 4.0.3 的
`theme_void()` 只抹轴**（`legend.position` 仍是 `"right"`，`legend.margin` 归零、
`legend.background` 空白）。R 侧实测：`axis-l` / `axis-b` / `xlab` / `ylab` 全是
0，`guide-box-right` 仍有内容（图例盒 1.366cm 宽）。ggcore 按 R 的实际行为实现，
`tests/test_guide_r_parity.py::test_theme_void_axes_are_gone_but_the_legend_stays`
钉住这一点；需要图例也消失请显式 `theme(legend.position = "none")` 或
`guide = "none"`。

## 8. guides 长尾（M2-S2 / SIL-739）

### 8.1 `guide_colourbar()` 的 4.0.3 参数面

`guide_colourbar()` 在 4.0.3 把一批老参数挪进了主题，本仓两套写法都认
（guide 上的显式参数优先，与 R 的 `replace_null()` 同口径）：

| 参数 | 4.0.3 的等价写法 | 说明 |
| --- | --- | --- |
| `nbin` / `display` | 同名 | `display` 是 `raster` / `rectangles` / `gradient`；缺省 `nbin` 按 display 取 300 / 300 / 15。旧写法 `raster=TRUE/FALSE` 在工厂里折成 `raster` / `rectangles` |
| `barwidth` / `barheight` | `legend.key.width` / `legend.key.height` | 长轴缺省是短轴的 5 倍 |
| `ticks.colour` | `legend.ticks` | 只改刻度线颜色；`ticks=FALSE` 仍保留标签（R 同） |
| `frame.colour` | `legend.frame` | 主题里**没有显式写** `legend.frame` 时不画边框（R 的 `setup_elements()` 用 `element_blank()` 兜底） |
| `title.position` | `legend.title.position` | `top` / `bottom` / `left` / `right`；标题**从不旋转**，左 / 右是普通横排文字 |
| `draw.ulim` / `draw.llim` | 同名 | 只去掉首 / 尾的刻度与标签，色条仍按 limits 全量程画 |
| `alpha` | 同名 | 混到白底上（与 svglite 白底等价） |

刻度位置照 R 的 `extract_params()`：键值重标到**箱心**
`(0.5, nbin - 0.5) / nbin`（`display = "gradient"` 时是 `(0, 1)`），不是 0..1。
`tests/test_guide_long_r_parity.py` 用 `get_guide_data()` 的 `.value` 逐值对拍。

### 8.2 `guide_bins()` / `guide_coloursteps()`

两者都吃「连续色标 + 断点」，训练结果是 `BinnedKeys`：边界 = limits 两端 +
范围内的断点，每箱的颜色取**箱心**的映射值。

- `guide_bins`：每箱一格键（复用 `Geom.draw()`），标签落在箱的**边界**上；
  R 的竖排 bins **低值在上**（`build_labels()` 先 `1 - .value`），与色条相反，
  这里照搬。`show.limits` 控制首尾两个边界标签。
  `reverse = TRUE` 照 `GuideBins$extract_params()` 统一翻转：键格颜色、边界
  标签、刻度三者同向镜像（`docs/cases/guide-bins-reverse`）。
- `guide_coloursteps`：分段色条。`even.steps=TRUE` 等宽，`FALSE` 按数据间距切；
  `show.limits` 在两端补 limits 标签。
- `get_guide_data()` 的形状也对拍：bins 是 `箱数 + 1` 行（最后一行的映射值是
  NA），coloursteps 是断点行。

R 4.0.3 没有 `guide_steps` / `guide_steps2` / `guide_stepsn` 这三个名字
（`guide_colorsteps` 是 `guide_coloursteps` 的别名）；本仓只实现真实存在的
API：`bins` / `coloursteps` / `colorsteps`。

### 8.3 轴 guide（`ggcore.axis_guide`）

`guides(x = guide_axis(...))` 走 `plot.guides`（键 = `x` / `y` / `theta`），
由 scene 的轴阶段消费。`guide_axis()` 的参数与 R 一一对应：

| 参数 | 行为 |
| --- | --- |
| `angle` | 标签旋转；锚点照 R 的 `label_angle_heuristic()`（bottom: `hjust=sine` / `vjust=cosine`，其余方位见 `_anchor()`）。主题 `axis.text.*(angle=)` 同样生效 |
| `check.overlap` | 按 R 的 `axis_label_priority()`（首、尾、中点递归）保留，重叠的丢弃 |
| `n.dodge` | 标签分 `n` 行 / 列；轴带按 `行数 × 标签盒` 加宽（R 的 `measure_grobs()`） |
| `minor.ticks` | 画 `scale.minor_breaks()` 的刻度；`axis.minor.ticks.*` 的样式，长度是主轴刻度的 0.75（`Rel(0.75)` 在 guide 里消费） |
| `guide_axis_logticks(long, mid, short, expanded, cap)` | 三档长度 = 倍数 × 主轴刻度长；位置来自 `scales::minor_breaks_log()` 的移植（`axis_guide.minor_breaks_log()`，含负数分支）。**即使区间里没有 long 刻度，轴带也按 long 留位**（R 用 `elements$major_length`）——这就是 M1 复验抓到的「最外两段缺失」口径 |
| `guide_axis_stack(first, ...)` | 从内到外叠放多条轴；间距 = 主轴刻度长（R 的缺省） |
| `guide_axis_theta(angle, minor.ticks)` | 极坐标 theta 标签：半径 0.45，`hjust = 0.5 - sin(θ+a)/2`、`vjust = 0.5 - cos(θ+a)/2`，角度按 `flip_text_angle()` 翻正 |

`cap`（`none` / `both` / `upper` / `lower`）照 R 的
`GuideAxis$extract_decor()`：轴线本来是整条边 `(-Inf, Inf)`，`upper` 把上端、
`lower` 把下端、`both` 把两端收到**最外一根刻度**（`axis_line_range()` 算端点，
scene 的 `_axis_line_grobs()` 按它裁 `axis.line.x` / `axis.line.y`）。
`docs/cases/guide-axis-cap` 与 R 的 `expected.svg` 对拍（图级 1.5% 内）。
`cap` 对 `guide_axis()` 同样生效。

`preserve="top"/"bottom"` 是本仓给 `cap` 的别名（`upper` / `lower`）；
ggplot2 4.0.3 **没有** `preserve` 这个参数名，只在 `guide_axis_logticks()` 的工厂里
折成 `cap`。

`guide_axis_theta(minor.ticks=TRUE)` 沿圆周画 `axis.minor.ticks` 样式的次刻度
（半径 1、伸出 0.75 × `axis.ticks.length`，照 `theta_tickmarks()`）；离散 theta
标度没有 minor breaks，与 R 一样不画。

### 8.4 `annotation_logticks()`

R 4.0.3 把它标成 superseded（推荐 `guide_axis_logticks()`），但它仍是一个
`GeomLogticks` 图层。本仓的图层流水线假定每层都有数据表，所以落成 plot 级标注
（`ggplot.annotations` → `PlotBuild.annotations` → scene 轴阶段）：

```
p + annotation_logticks(sides = "bl")
```

位置 / 三档长度 / `sides` / `outside` / `scaled` 都照 `GeomLogticks$draw_panel()`
（`calc_logticks()` 的移植）。差别只在不参与图例、分面与 `inherit.aes`，与 R 的
`show.legend = FALSE, inherit.aes = FALSE` 同义。案例
`docs/cases/annotation-logticks` 与 R 的 `expected.svg` 逐像素对拍（图级 1.5%）。

### 8.5 已知差异（长尾）

| 能力 | 现状 |
| --- | --- |
| secondary axis（`sec_axis()` / `dup_axis()`） | **M2-1 已实现**（`ggcore.axis.secondary_ticks()`，画在 top / right 槽）；极坐标下的 `r.sec` / `theta.sec` 仍报 `AxisError`，见 `docs/notes/coord.md` §12 |
| 极坐标带轴时的底部空轴行（≈0.24cm） | 仍不占位（`docs/notes/coord.md` §9）；`axis_theta` 的 case 用标签锚点 / 单测钉住，不比对整页高度 |
| `guide_axis_theta` 与 `guide_axis_stack` 叠放 | **已对等**（SIL-844，见 §8.5.2）：theta key 的 `(x, y)` 落在 r = `label.position - 0.5`（主 r 断点）/ inner（`theta.sec`，它把 `r` 列设成 `-Inf`），标签沿半径外推；叠放时第二圈再加 `spacing(2.25pt) + 上一层标签盒沿半径的投影`（上游 `GuideAxisStack$draw()` 的 `offset <- offset + spacing + offset_i`） |
| `coord_radial()` 的 theta 轴体系 | **已对等**（SIL-843 版式 + SIL-844 轴体系，见 §8.5.1 / §8.5.2）：`r.sec` / `theta.sec` 的次轴槽、逐 guide `theme=`、`r.axis.inside` 的数值 / 两角度旋转轴、`rotate.angle = TRUE`、`guide_axis_stack("axis_theta", …)` 的多层半径偏移、partial arc 的环形扇区背景。`coord-polar` 的 11 条快照全部 `ci = true`（四条轴体系 case 实测 1.26% / 0.86% / 0.64% / 1.00%） |
### 8.5.1 radial 版式与 theta 轴（SIL-843）

`coord_radial()` 的整页几何只有一条口径，四条约束叠起来才等于 R 的输出（都以上游
SVG 逐值量过，见 `docs/cases/upstream-guide-axis-theta-angle`）：

| 口径 | R 的做法 | 本仓 |
| --- | --- | --- |
| 面板是正方形 | `CoordRadial$aspect() = diff(bbox$y) / diff(bbox$x)`（满圆 = 1）→ `Facet$init_gtable()` 的 `respect = TRUE`，面板 cell 的长宽取同一个物理尺寸 | `table.respect` + `_aspect_panel_area()`：面板区取等比例内接正方形 |
| 整表水平居中 | `grid.layout(..., respect = TRUE)` 会把收缩后的表放进视口并 **居中**（`just = "centre"`）：表宽 = 5.5 + ylab + axis-l + 面板 + axis-r + 5.5，比整页窄时左右各留一半 | 面板在「扣掉左列」的区域里居中——两者等价（推导见 `_aspect_panel_area()` 的注释） |
| `panel.background` 是圆环 | `guide_grid(square = FALSE)` 把 `panel.background` 换成 `c(±Inf)` 的 polygon 再 `coord_munch`：满圆 munched 完是**外圆 − 内孔**的双环（上游 SVG 里 317 点的 `#EBEBEB` polygon），不是外接方形 | `_radial_panel_background()`：`path_grob(rule = "evenodd")` 两段子路径 |
| 次网格要 `setdiff` | `guide_grid()` 的 `x_minor <- setdiff(mapped_breaks_minor(), x_major)`；`CoordPolar$render_bg()` 不筛（主辐条画两遍）。radial 走前者，**r 也有次圆**（主断点中点） | `_polar_grid_grobs()`：radial 下 minor 先减主断点，r 次圆用同一条 `panel.grid.minor.<r>` |
| r 轴读 `axis.*.r` | `CoordRadial$train_panel_guides()` 给 `r` / `r.sec` 一律设 `theme_suffix = "r"`（全圆 + `r.axis.inside = FALSE` 也一样） | `_radial_axis_theme()` → `AxisSuffixTheme`：把 `axis.text/ticks/line/minor.ticks.<x\|y>` 映射到 `.r`。`axis.text.r` 两侧各 2.2pt margin、`hjust = 0.5`，与 `axis.text.y` 只留右侧 margin 不同——差这 2.2pt 面板整体横移 1.1pt |

为什么之前的 48.7% 几乎全是版式：`panel.background` 铺成外接方形、面板比 R 小 3.4%、
标签锚点整体错位。版式对上之后，剩下的 theta 轴细节（轴线 / 刻度 / `cap` / 逐角度
旋转的锚点）在 SIL-839 已经写好，只是被版式误差掩住了。

### 8.5.2 radial 的轴体系（SIL-844）

`coord_radial()` 的四条轴（`r` / `theta` / `r.sec` / `theta.sec`）各有自己的槽位与
绘制口径，全部照 `CoordRadial$setup_panel_guides()` + `render_fg()`：

| 口径 | R 的做法 | 本仓 |
| --- | --- | --- |
| 次轴槽 | `Theme$theme_suffix = "r"` / `"theta"`；`r.sec` 与 `r` 共用 `axis-r` 列（`panel_guides_grob(position = "right")`），`theta.sec` 与 `theta` 共用一条弧 | `_radial_axis_theme()` 的 `AxisSuffixTheme`；`plot_layout()` 在径向下 `guide_for(build, "r")` / `"r.sec"` 各取一份 ticks，`r.sec` 的标题另占一格（`_guide_title(guide_rsec, None)`：次轴不继承主标度的名字） |
| 逐 guide `theme=` | `GuideAxis$setup_elements()` 里 `theme <- plot_theme %+% self$theme`，再按 `theme_suffix` 取元素 | `_axis_guide_theme()` = `guide_theme()`（`plot_theme %+% guide$theme`）后再套 `.r` 后缀。`guides(r.sec = guide_axis(theme = theme(axis.line.r = …)))` 的 `theme=` 现在也会穿过 `axis_guide_from_component()`（早前在转写里被丢掉了） |
| `r.axis.inside` | 数值 → `theta_scale$transform()` → `oob_squish()` → `theta_rescale(…, arc)`，`rep_len(…, 2)` 给主 / 次轴各一个角度；`render_fg()` 用 `rotate_r_axis()` 把整条 r 轴（轴线 / 刻度 / 标签）绕面板中心转到该角度 | `RadialCoord._decorate()`：`_is_numeric_form()`（标量或两元序列，bool 除外）→ `axis_rotation` 一对角度；`polar_r_axis_inside_grobs()` 在面板坐标系里画，`position` 决定标签落在轴的哪一侧，`bbox` 决定归一化 |
| 旋转轴的标签锚点 | `element_grob(label_element, y = break_positions, margin_x = TRUE)`：`y` 是 native 坐标，`margin_x` 把 margin 折进标签盒；`rotate_r_axis()` 再整体转 | `AxisGuideTicks.hjust / vjust`：`guide.angle is None` 时取元素自己的 `hjust` / `vjust`（`axis.text.r` 是 `0.5 / 0.5`），`axis_guide_grobs()` 的「精确」分支用 `text_width_cm()` / `text_block_cm()` 把锚点算到半个标签盒 |
| `rotate.angle = TRUE` | `flip_data_text_angle()`：`angle <- (angle - rad2deg(theta)) %% 360`，落在 (90, 270) 的再 `+180` 并把 `hjust` / `vjust` 取反 | `TextRenderer.draw()` 在 `coord.rotate_angle` 且面板是极坐标时按行重算 `angle`（theta 取自 theta 轴那一列，不反解 `atan2()`，避免 glibc / emscripten 的 1 ULP 差） |
| partial arc 的 `panel.background` | `guide_grid(square = FALSE)` 的 4 个 ±Inf 角点经 `coord_munch()` 投到 bbox，partial arc 下折成**一段**闭合的环形扇区 | `_radial_panel_background()`：`arc < 2π` 时一段子路径（外弧 + 内弧回程），满圆才是两段（`rule = "evenodd"`） |
| 叠放的径向偏移 | `GuideAxisStack$draw()` 的 theta 分支：`offset <- offset + spacing + grobs[[i]]$offset`，`grobs[[i]]$offset` 来自 `measure_grobs()`（标签盒沿半径的投影）；`spacing` 缺省 2.25pt | `polar_axis_grobs()` 的 stack 分支：逐层累加 `_theta_ring_extent()`（标签盒沿半径投影 + `spacing`），第二层起按累积量外推 key 半径 |

SIL-849 把剩下两条也收进 2% 档（`ci = true`），量到的口径补进上表的两行：

- `guide-axis/stacked-radial-axes`：**1.62% / 0.49%**（原 2.94% / 1.18%）。三处：
  1. `theta.sec` 的叠放方向是**反的**——上游 `GuideAxisTheta$transform()` 先给 key 的
     theta 加 `π`，之后 `build_decor()` / `theta_tickmarks()` / `build_labels()` 都用
     `sin/cos(theta + π)` 加 `stack_offset`，第二圈因此落在内半径**里侧**
     （实测 125.39pt → 103.33pt）。之前一律向外推，两条 `theta.sec` 标签错 40pt；
  2. `measure_grobs()` 的 margin 是 `rep(max(margin), 4)`（四个方向都取最大值），
     不是只用元素自己那一侧的 `t = 2.2pt`；theta 第二圈的步长因此差 3.3pt；
  3. 旋转 r 轴的层间方向：`rotate_r_axis()` 的 viewport 旋转在**设备空间**里是刚性的，
     45° 不随面板长宽比（bbox 1 × 0.8536）变形。之前按 `width/height` 归一化成
     40.5°，第二层标签错 6.4pt；`+2 × margin` 的补偿也是多余的（上游列宽只含一次
     margin）。现在两层 r 标签逐值对到 0.65pt、第一层 0.3pt。
- `coord_sf/coord-sf-with-custom-guides`：**1.56% / 0.32%**（原 2.83% / 0.92%）。
  `n.dodge = 2` 的第 2..n 列在 R 里是独立 gtable 轨道，尺寸**逐组**量
  （`width_cm(grobs$labels)`：组 k = 下标 `k, k+n, …` 取最大值，再加该元素的
  cross margin）。之前一律按全局最大值，右轴带宽多 2pt、整表宽 2pt，面板因此
  左移 1.1pt（`y_axis_right_cm` 50.1 → 49.3，上游实测 49.34）。修完面板左边界
  157.144（上游 157.15）、左 / 上 / 右三条轴带的标签残差都 ≤ 0.15pt。`°` 的
  advance 差 0.21px 未动（本仓 0.4em、上游 plotmath `degree` 0.376em），单独一层。

| `legend.frame` / 高级图例盒子主题 | 只画 `legend.frame` 的描边与 `legend.box.background` 的矩形；`legend.box.just` / `legend.box` / `legend.box.margin` 已参与行列分配 |
| 色条的 raster 渐变 | IR 的 `fill` 没有渐变类型（`docs/notes/ir.md` §12），仍是 `nbin` 个矩形。SIL-723 的两条修法：颜色按 `GuideBuild.palette` 在**标度 limits 的全量程**取（端点是标度最小/最大值的 Lab 色，不是断点色阶）；相邻矩形多铺 1pt，让后画的条盖住 `resvg` 的缝（否则整条偏白约 30%）。`guide-colourbar` 现在 1.74% / 均值 0.31%，SIL-715 #3 关闭。`display = "gradient"` 同样落成 15 条矩形，由 `docs/cases/guide-colourbar-gradient` 钉住视觉（图级 1.48%） |
| 横向 colourbar 的标题方位 | R 把标题旋转 90° 放在色条左侧（盒宽因此多一列文字宽）；ggcore 的 `legend.title.position` 已生效但标题**不旋转**，与竖向共用横排文字 |
| 色条的 gtable 行列分解 | `LegendLayout` 只给普通图例填了 `col_widths_cm` / `row_heights_cm`；colourbar / coloursteps / bins 只钉总尺寸（`bar` + `ticks`），没有逐列数组 |
| 同 `order` 的图例先后 | R 按 `rlang::hash()` 字符串排；ggcore 按美学顺序。需要确定顺序时显式 `guide_legend(order=)`（见 §2） |

## 9. 确定性

轴、图例、标题都是既有 grob（`segments` / `text` / `rect` / `Geom.draw()` 的产物）
拼出来的，没有新增 IR 字段；同一张图两次 `scene_from_plot()` → `ir.encode()` 的
sha256 相等（`tests/test_guide.py::test_axis_and_legend_are_deterministic`，覆盖
2×2 分面 + colour 图例 + 标题；9 个 M1-7 geom 的旧断言仍在（M2-S2 的 20 个 geom 另在 `tests/test_geom_longtail.py`）
`tests/test_geom_draw.py`）。`pixi run gate:determinism` 的载荷也加上了同一份整页
场景（`tools/gates/_determinism_child.py` 的 `plot_scene()`），三个
`PYTHONHASHSEED` 进程的 `plot_digest` 必须一致。

没有给 `metrics` 时，`scene_from_plot()` 用内置的 0.6em/0.955em 占位度量，保证
`text.width` 有值且字节稳定；`pixi run render` 传入 `ggskia.text.ShaperMetrics`
时以设备排版为准。

## 10. 复现

```bash
pixi run -e refs refs:guide       # 重新生成 tests/fixtures/guide_r_reference.json（16 个 case）
pixi run -e refs refs:guide-long  # guides 长尾夹具（27 个 case + 对数次刻度取值）
pixi run -e refs Rscript tools/refs/cases_battery_ref.R guide-legend-top   # 只重画点名的 case
pixi run test                     # 含 test_axis / test_guide / test_guide_r_parity / test_guide_long*_r_parity
pixi run render --scene <scene>.ggir.cbor --out report.png
```

### 评审前自检（SIL-705 起）

```bash
pixi run check                    # lint + test + 各 gate（含静态的 cases:matrix:check）
pixi run cases:matrix             # 案例回归，必须全绿（当前 116 个三文件 case）
pixi run gate:determinism         # 整页场景的 plot_digest 跨进程一致
```

`pixi run check` 里的 `cases:matrix:check` 只跑 `--no-run`：校验矩阵新鲜度与
`plot.py` 可导入，**不渲染也不比图**。所以本地 `check` 绿不代表案例回归绿——
改 guide / geom / theme 之后必须单独跑一次 `cases:matrix`。SIL-705 的教训就是
5 个 case 在 `check` 全绿的 PR 上仍然红（新增图例改变了像素）。

## 11. G1a（SIL-788）：图例侧的边界情形

`guides` / `guide-legend` / `guide-colorbar` / `legend-draw` / `draw-key` 五簇
54 条上游快照里，46 条在本轮复刻成三文件 case（`_G1A_SPECS`）；剩下 8 条的单条
卡点写进 `tools/upstream/snapshots.toml` 的 `reason`。这一轮补齐 / 修正的口径：

| 能力 | R 4.0.3 的写法 | ggcore 现在的行为 |
| --- | --- | --- |
| 逐 guide 主题 | `guide_legend(theme = theme(...))` | `GuideLegend` / `GuideColourbar` / `GuideBins` / `GuideColoursteps` / `GuideCustom` 都有 `theme=` 字段；`guide_theme()` 用 `merge_theme()` 把 `plot_theme %+% guide$theme` 合到**这一张**图例上（布局与绘制都走合并后的主题） |
| inside 图例各自定位 | 每个 `position = "inside"` 的 guide 是独立的 guide-box | `plot_layout()` 按 guide 分组（`inside:<index>`），每张图例用自己的 `legend.position.inside` / `justification.inside`（可来自 guide 的 `theme=`） |
| `legend.direction` | `Guide$setup_params()` 的第二档 | `legend_direction(guide, position, theme)`：guide 显式 > 主题 > 方位默认 |
| 旋转的标签 / 标题 | gtable 量的是旋转后的 grob | `_text_footprint()`：`angle = 90 / 270` 时宽高互换；`text_grob(rot=)` 按元素角度画 |
| `legend.axis.line`（bins） | `GuideBins$draw()` 沿 key 区外边画轴线，箭头来自 `element_line(arrow = arrow(...))` | `_legend_axis_line_grob()`；`element_line(arrow=)` 现在收 `ggcore.arrow.Arrow`（以前只认布尔） |
| 位置参数的含义 | `guide_legend(title = waiver(), ...)` 的第一个位置参数是标题 | 注册表工厂按「是不是美学名」分流：`guide_legend("colour title")` 当标题，`guide_axis("x", angle=45)` 当美学，`guide_custom(grob)` 当 grob |

另外修掉一条与图例无关但挡路的 bug：`registry.construct()` 的 `kind` / `name`
改成**位置专用参数**，否则 `scale_colour_discrete(name = "…")` 会撞上
`construct(name=)`（`TypeError: got multiple values for argument 'name'`）。

SIL-810（G8）补齐的尾部能力：

| 能力 | 实现 |
| --- | --- |
| `geom_*(key_glyph = "timeseries" / "rect" / "polygon" / "dotplot" / …)` | `ggcore.legend_draw.KEY_GLYPHS`，17 个 `draw_key_*`；没有显式 `key_glyph=` 时按 geom 名取上游缺省 glyph |
| 自定义 key 函数 | `key_glyph=<callable>`，签名 `(data, params, size_mm)`；返回 `Grob` 或 `KeyGlyph(grob, width_cm, height_cm)`（上游的 grob `width` / `height` 属性） |
| key 尺寸随标度变化 | `_key_dimensions()`：`max(legend.key.size, (size + linewidth) / 10)`，逐键算、按列/行取最大（`legend.key.justification` 也按逐键尺寸锚定） |
| 逐美学 `show.legend` | `show_legend = {"colour": None, "alpha": False}`（`None` = `NA` 自动） |
| 无图层版面 | `plot_layout()` 不再给 `ggplot()` 留轴占位，面板铺满 `plot.margin` 内区 |

## 12. G1b（SIL-791）：轴 guide 侧的边界情形

`guide-axis` 簇 23 条上游快照里，10 条在本轮复刻成三文件 case（`_G1B_SPECS`，
`pixi run snapshots:import` 可重生成）；剩下 13 条的单条卡点写进
`tools/upstream/snapshots.toml` 的 `reason`，不放宽阈值。

### 12.1 负 `axis.ticks.length`：刻度与标签一起压进面板内侧

上游 `test_draw_axis()` 不是 ggplot：它把 `draw_axis()` 的 grob 直接放进
0.05 / 0.9 / 0.05 npc 的三格 gtable，轴线、刻度、文字全画在**同一个单元格里**。
用一张空面板 + 主轴 / `dup_axis()` 复现同一版式时，对应的是负的
`axis.ticks.length`（刻度朝面板内）。这一轮把 `guide_axis` 的标签排版补齐：

| 口径 | 修正 |
| --- | --- |
| 内压标签的锚点 | 刻度长为负时，锚点换到**对面**那一侧（bottom 取 top 的 `hjust/vjust`，其余同理） |
| 内压标签的边距 | margin 跟着翻到内侧：bottom `+mt`、top `-mb`、left `+mr`、right `-ml`；`n.dodge` 的第二行也朝内侧推 |
| `check_overlap` 的单位 | 标签长度用 cm、位置是 npc，比较前要先除以轴长——以前 20 个断点会把除第一个之外的全丢掉 |
| 竖轴的「沿轴长」 | 是旋转包围盒的**高度**（`angle = 0` 时是行高，不是文字宽），所以竖排 20 个标签一个都不丢 |
| `axis_label_priority()` | 递归中点改成 R 的闭区间口径（`n = y - x + 1`、`mid = x - 1 + (n + 1) // 2`）；旧迭代版在 `right - left` 为奇数时自我入栈，`check_overlap` + 20 断点直接挂死 |

9 条 grid 直画快照（basic / zero breaks / 4 个旋转 / 竖向负旋转）与
`thick axis lines` 现在都在图级 2% 内。

### 12.2 次轴：`guides(x.sec=)` 不必有 `sec_axis()`

R 4.0.3 里 `guides(x.sec = guide_axis(...))` 会画一条**恒等**的次轴（没有标题），
即使标度上没有 `sec_axis()` / `dup_axis()`。以前只有 `scale$secondary_axis` 存在
时才画，`capped ends` / `stacked axes` / `minor ticks` / `axis_theta` 这几条都卡在
这里。现在 `has_secondary_axis()` 两路都认，次轴走与主轴同一条
`axis_guide_ticks()` + `axis_guide_grobs()`，并且补上 top / right 的轴线
（`axis.line.x.top` / `axis.line.y.right`）。guide 优先级：
`guides(<aes>.sec = ...)` → `dup_axis(guide = ...)` → 缺省。

### 12.3 其余小口径

- `guide_none(title = "...")`：只去掉刻度与标签，**保留轴标题**（以前整条 guide
  都被当成「没有」，标题一起消失）。
- `guides(x = "axis_theta")`：字符串写法对轴 guide 也认（图例侧返回「无图例」）。
- `guide_axis_stack(first, ...)`：注册表工厂接受多个位置参数（R 的 `first` +
  `...`），子 guide 可以是 `"axis"` / `"axis_theta"` / `"axis_logticks"`。
- `secondary_ticks()` 的恒等分支：`breaks` 里带 `None` 时先 zip 再过滤，否则
  `labels` 比 `positions` 长（离散次轴 `zip(strict=True)` 直接抛异常）。

### 12.4 尚未对等（0 条；2026-11-06 收口）

SIL-810 收掉 `n.dodge` 进版式、`guide_axis_stack` 逐层累加、`cap=` 与直角坐标
`axis_theta`（5 条）。SIL-817 收掉 `align facet labels, facets vertical`。
SIL-820 又收掉 6 条（见 §12.6）。最后 3 条由后面的任务收掉：

| 曾经的卡点 | 收口 |
| --- | --- |
| 径向坐标的 full-bleed 面板 + `guide_axis_theta(angle=)` 的锚点 | SIL-843（`guide-axis-theta-with-angle-adapting-to-theta`，1.9%） |
| 同一套 radial 版面 + `guide_axis_stack` 在 theta 方向的两圈 `stack_offset` | SIL-843 / SIL-844（轴体系 / 叠放）、SIL-849 收进 2% 档（1.62% / 0.49%） |
| `guides-with-minor-ticks` 的 plotmath 两段落字 | SIL-855（`10^2`，0.62% / 0.15%） |
| `logtick-axes-with-customisation` 的两个复合变换 | SIL-856（见 §12.8，1.97% / 0.73%） |

`guide-axis` 簇的 23 条上游快照现在全部纳管，`snapshots.toml` 里本簇缺口为 0。

### 12.5 SIL-816：stretchy key 与逐边 justification

- **stretchy key**：`legend.key.height / width = unit(1, "null")` 不再换算成 0
  报错。`_key_size()` 把纯 `null` 记成权重（`_null_weight()`），`legend_layout()`
  按 `stretch_h / stretch_w` 把剩余尺寸摊给这些行 / 列；行高就是那个 `null`
  （标签高度不进行高），所以两张 stretchy 图例的**绝对部分**相等、最终一样高。
  外层 `plot_layout()` 在 panel 行 / 列尺寸算出来之后重排一遍：`guide-box` 在
  left / right 上占 panel 行高、top / bottom 上占 panel 列宽，剩余按 null 权重
  分给每张图例（R 的 `redistribute_null_units()`）。
- **null 间隔**：`legend.spacing.y / x = unit(1, "null")` 由 `legend_box_layout()`
  在盒内分配（`target_height / target_width`），图例被推成贴顶 / 贴底。
- **逐边 justification**：`legend.justification.<side>` 决定 guide-box 贴哪个角
  （默认 0.5 = 居中）；`legend.location = "plot"` 时参照区从 panel 行 / 列换成
  整个绘图区内区。
- **guide-box 背景**盖住 `legend.box.margin`（R 先 `gtable_add_padding()` 再放
  background），不再只盖图例矩形的并集。
- **guide 顺序**：R 按 `order` + 内容 hash 排序；我们的 `_sort_key` 是
  `order` + 美学序号 + 名字。同方位多图例且顺序有差时，case 里显式 `order=`
  钉住（`stretched-vertical-legends` / `stretched-horizontal-legends`）。

### 12.6 SIL-820：裸 gtable 入口、逐键行高、`guide_custom()` 的包围盒

- **裸 gtable case 契约**：`plot.py` 可以返回 `{"gtable": <GTable>, "size": [...]}`
  （R 的 `plot(gt)`）。`ggcore.axis_guide.draw_axis()` 是 R `draw_axis()` 的移植：
  收现成的断点 / 标签（npc）与一个 `CellBox`，把轴线 + 刻度 + 标签画进去；方位
  口径照 `GuideAxis$assemble_drawing()`——`side="top"` 贴**下**沿、刻度向上
  （真实版式里它的单元格就在面板上方），`"bottom"` 反之，左右同理。
  `build()` 声明 `metrics` 参数时会拿到设备的字体度量（`check.overlap` 要按真实
  字宽筛标签，估算值会多删一半）。
- **逐键行高**：`legend_layout()` 的每一行按**该键自己的**标签块高与 key 高取
  max，不再全场用最大标签高度；多行标签的高度用 `text_block_cm()`（单行高 +
  (n-1) 个行距），行距 = `1.2 × lineheight × fontsize`（`legend.text` 的
  lineheight 是 0.9，缺省 1.2 时才是 1.44em）。`size` 图例的 key 高 = 标度值
  (`(size + linewidth) / 10` cm)，所以三行不再等高。
- **`guide_custom()` 的内容盒**：缺省取 grob 的 `grobWidth()` / `grobHeight()`
  （`circleGrob(r = unit(1, "cm"))` → 2×2cm），不再退回 `legend.key.size`。只对
  **绝对单位**成立：`npc` / `null` 这类相对单位要先有视口才折得开，R 在 guide 的
  绘制上下文里量、本仓在临时页视口里量，结论不同（`old-s3-guide-circle`），
  所以 `grobs.is_absolute_size()` 为假时仍退回 key 尺寸。标题按旋转后量
  （`angle = 90` 时列宽 = 一行行距、行高 = 文字宽），标题比内容长时按 vjust 在
  上下补行。
- **1 px 描边**：主题的 `linewidth`（mm）→ `lwd`（pt）改用 R 的 `.pt = 72.27/25.4`
  （`geom/base.POINT_PER_MM` 同一个常数）。0.4% 的差在 1 px 边框上就是从 0.75
  翻到 0.56 的覆盖率：`align facet labels, facets horizontal` 因此从 2.05%
  降到 1.91%。

### 12.7 SIL-855：plotmath 接进文本层（`label_math()` 的轴标签）

上游 `scale_x_continuous(labels = label_math())` 的断点标签是 plotmath 表达式
（`10^2`），一段要拆成两段落字。这一轮把 `ggcore.plotmath` 接进文本层与两处
调用点（轴 guide、facet strip）：

- **标记**：`plotmath.MathText`（`str` 子类）。`scales.label_math()` 与
  `facet.label_parsed()` 产出的标签带这个标记，整条流水线（标度 → guide →
  grob）照旧当字符串用；解析不了的串退回普通 `str`（同 `parse_safe()`）。
- **量尺寸**：`text_width_cm()` / `text_block_cm()` 认标记，宽度 = 各 run 推进之
  和，行高 = 基线以上 0.999em + 以下 0.21em（8.8pt 的 `10^2` 是 10.64pt，纯文本
  是 7.87pt）。`_label_box()` / `_strip_extent()` 因此把上标顶出来的那截算进轴带
  / strip 行高。
- **落字**：`grobs.math_text_grobs()` 把一段 plotmath 展开成多个 text grob（每个
  run 一个，各自字号 + 基线抬升；根号走 polyline）。IR 不新增字段——一个标签就
  是多个 text 节点（`docs/notes/ir.md` 的 text 口径不变）。
- **负刻度**：`axis.ticks.length.*.top = unit(-0.5, "cm")` 这类负值画进面板内侧，
  R 的 `GuideAxis$measure_grobs()` 取 `range(0, major)`，负的一段不占轴带。
  `_guide_extent()` 改成 `max(0, tick) + 标签盒`，`guides-with-minor-ticks` 的
  axis-t 行才对得上（以前整条轴带塌成 0，标签压进面板、面板上移 12.8pt）。
- 上游 `guide-axis/guides-with-minor-ticks` 0.62% / 0.15%、
  `facet-labels/parsed-facet-labels` 0.15% / 0.02%。

### 12.8 SIL-856：guide 自己的标题与两个复合变换

`guide-axis/logtick-axes-with-customisation` 的四条轴标题都不是 `labs()` 给的，
而是**每条 guide 自己的 `title=`**：

- `guide_axis_logticks()` 补上 `title` / `angle` / `theme` / `position`
  （R 里由 `...` 继承 `GuideAxis`；以前这四个参数会被忽略，标题退回标度名
  "x" / "y"）。注册表工厂的 `allowed` 同步补登记。
- 次轴（`x.sec` / `y.sec`）没有 `sec_axis()` 时，标题取
  `_guide_title(secondary_axis_guide(...), None)`——`snapshots.toml` 里记的
  「恒等次轴（没有标题）」只适用于 guide 不带 `title=` 的情形。

图本身靠两处新能力（详见 `docs/notes/scales.md` §11）：

- `transform_compose(...)`：`scale_y_continuous(transform =
  transform_compose(transform_log10(), transform_reverse()))` 的断点仍走
  `breaks_log()`（第一个变换的 breaks）、标签在数据空间格式化、映射按复合顺序；
- `transform_pseudo_log()`：`coord_transform(x = transform_pseudo_log())` 直接收
  `ggcore.scales` 的变换对象（`as_coord_transform()` 适配一层），面板范围在
  伪对数空间 expand、`continuous_range` 再反解回数据空间给断点 / logticks 用。

上游快照 1.97% / 0.73%（差异集中在 11pt 轴标题的字形宽度，面板与刻度位置逐点对齐）。
