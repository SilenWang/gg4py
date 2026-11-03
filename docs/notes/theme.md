# 主题账本（theme）

`ggcore.theme` 是 ggplot2 4.0.3 主题系统的对等物：元素对象、元素树、继承、
`rel()` 求值、局部覆盖、`theme_set()` 一族全局状态，以及 4.0.3 导出的
9 套完整主题与 11 个 `theme_sub_*` 简写。目标不是「看起来像」，
而是每个元素都能解析成可断言的数字：

```python
from ggcore.theme import resolve_theme, theme_grey

resolved = resolve_theme(theme_grey())
resolved["axis.text"].size  # 8.8（pt）
resolved["axis.text"].colour  # "#4D4D4D"
resolved["panel.grid.minor"].linewidth  # 0.25（mm）
```

参考实现：ggplot2 4.0.3 的 `R/theme.R`（元素树、`calc_element()`、
`combine_elements()`）、`R/theme-elements.R`（元素构造器）、
`R/theme-defaults.R`（完整主题）。版本由 `pixi.toml` 的 `[feature.refs]`
钉住；逐元素参考值由它生成：

```
pixi run -e refs refs:theme     # tools/refs/theme_ref.R → tests/fixtures/theme_r_reference.json
```

`tests/test_theme_r_parity.py` 对夹具里每一套主题（9 套完整主题 + 11 个
`theme_sub_*` 组合）的每个元素逐项比对，夹具里的数值就是
ggplot2 `calc_element()` 的结果（颜色/单位/边距已换成 ggcore 的规范形式）。

## 元素对象

元素是不可变的 frozen dataclass；没给的字段是 `None`（未设置，解析时从父元素
继承）。`element_blank()` 是独立的类型，表示「明确画空白」。

| 构造器 | 字段 |
| --- | --- |
| `element_text(family, face, italic, fontweight, fontwidth, size, colour, hjust, vjust, angle, lineheight, margin)` | 另可 `debug=` / `inherit_blank=`；`italic` / `fontweight` / `fontwidth` 原样透传，只校验类型（布尔；字符串或数值） |
| `element_line(colour, linewidth, linetype, lineend, linejoin)` | `linewidth` 单位 mm；`arrow=` / `arrow_fill=` |
| `element_rect(fill, colour, linewidth, linetype, linejoin)` | 背景/边框 |
| `element_polygon(...)` | 与 rect 同字段 |
| `element_point(colour, shape, size, fill, stroke)` | `size` 单位 mm |
| `element_geom(ink, paper, accent, linewidth, borderwidth, linetype, bordertype, family, fontsize, pointsize, pointshape)` | `fontsize` 在 ggcore 里是 pt（见「刻意差异」） |
| `element_blank()` | 无字段 |

`rel(x)` 是相对倍数；`margin(t, r, b, l, unit="pt")` 是四边边距
（`margin_auto(t, r=t, b=t, l=r)` 的四边默认跟随 `t`）。

颜色：输入接受 R 颜色名（`black`、`grey20`、`white`）与 `#RGB` / `#RRGGBB`
/ `#RRGGBBAA`；`NA`（`ggcore.theme.NA`）表示「明确不画」，与 `None`
（未设置、继承）不同。解析后的颜色统一成 `#RRGGBB`（alpha < 255 时
`#RRGGBBAA`），`NA` 折成 `None`。

## 元素树与继承

`ELEMENT_TREE` 照抄 4.0.3 的 `.element_tree`：每个名字有类型和父元素。父元素
元组按顺序生效，第一个父元素优先。`tests/test_theme.py::test_theme_grey_*`
与对拍夹具覆盖了树上的每个节点。

几个关键继承链：

| 元素 | 继承自 | 说明 |
| --- | --- | --- |
| `axis.text` | `text` | 全部文本元素最终都落到 `text` |
| `axis.text.x` / `axis.text.y` | `axis.text` | 方位/边缘变体再往下一层 |
| `axis.title` | `title` → `text` | `title` 只覆盖 family |
| `plot.title` | `title` → `text` | 字号 `rel(1.2)` 相对 `text` |
| `panel.grid.major` / `panel.grid.minor` | `panel.grid` → `line` | 主题只定义 `panel.grid`，粗细在同名子元素上 |
| `legend.key` | `panel.background` → `rect` | `panel.background` 是 blank 时图例键也变 blank |
| `legend.text` | `text` | 字号 `rel(0.8)` |
| `axis.ticks.length` | `spacing` | 主题里是 `rel(0.5)` × `spacing(5.5pt)` = 2.75pt |
| `legend.ticks.length` | `legend.key.size` | `rel(0.2)` × `unit(1.2, "lines")` = 0.24lines |

解析顺序（对应 `calc_element()`）：

1. 取该元素在主题里的定义；没有就是 `None`。
2. 依次合并父元素的解析结果；`None` 字段用父值填，**`rel()` 此时不求值**。
3. 文本/线条的 `size` / `linewidth` 遇到父元素的数值时求 `rel`；文本的
   `margin` 逐边继承（`margin_auto` 的 `None` 边也继承）。
4. 父元素是 `element_blank()` 时：子元素 `inherit.blank=True` 也变 blank，
   `False` 则忽略 blank 父元素（继续用子元素自己的值）。
5. 颜色最后规范化成 `#RRGGBB`。

完整主题里的所有非 blank 元素都带 `inherit.blank=True`（对应
`theme(..., complete=TRUE)`），所以 `theme_void()` 里 `axis.text` 是 blank 时，
`axis.text.x` 等子元素自然也是 blank。

## `None` 与 `element_blank()`

两者在解析结果上必须可区分：

| 写法 | 主题里的值 | 解析结果 |
| --- | --- | --- |
| `theme(**{"panel.background": element_blank()})` | `ElementBlank()` | `ElementBlank()`（画空白） |
| `theme(**{"panel.background": None})` | `None`（删除） | 回落到父元素 `rect`：白底、黑边、0.5mm |
| 不给 `panel.background` | 保持主题原值 | `theme_grey()` 的 `#EBEBEB` 填充 |

`theme()` 是局部覆盖：只合并给到的元素；`theme_grey()` 这类完整主题整份替换
当前主题。`p + theme(...)` 走同一条 `merge_theme()`，`ggplot` 的默认主题是
`theme_grey()`。

## `rel()` 的求值时机

合并只填 `None` 字段，`rel()` 原样保留到解析阶段：

```python
from ggcore.theme import element_text, merge_theme, rel, resolve_theme, theme, theme_grey

base = theme_grey()
scaled = merge_theme(base, theme(text=element_text(size=rel(1.5))))

base.elements["text"].size  # 11
scaled.elements["text"].size  # Rel(mult=1.5)
resolve_theme(scaled)["text"].size  # 16.5
resolve_theme(scaled)["axis.text"].size  # 13.200000000000001（= 11 × 1.5 × 0.8，只乘一次）
```

两层嵌套也只解析一次：`text=rel(1.5)` + `axis.text=rel(0.5)` → `0.5 × 1.5 × 11
= 8.25`，不会把父元素已经算过的结果再乘一遍。

根元素（`text` / `line` / `rect` / `point` / `polygon` / `geom`）上的 `rel()`
在 ggplot2 的 `calc_element()` 里保持 `rel` 原样（渲染时才消费）；ggcore 的
`resolve_theme()` 契约是「每个元素都是可断言的具体值」，所以按主题的
`base_size` 折成 pt/mm。`theme_grey(base_size=16)` 会把这个基数带下去，
`+ theme(text=element_text(size=rel(1.5)))` 得到 24pt。

白名单之外，`ResolvedTheme` 里不会剩下 `Rel`。白名单只有下面两类：

- `point.stroke`、`geom.borderwidth` / `geom.fontsize` / `geom.pointsize`：
  这几个字段不叫 `size` / `linewidth`，`calc_element()` 在 R 侧也不折，
  ggcore 原样保留，渲染时相对根元素消费；
- `axis.minor.ticks.length*`：树里它没有父元素，主题值 `rel(0.75)` 在 R 侧
  也保持 `rel`，由 guide 在绘制时相对主轴刻度消费；`ResolvedTheme` 保留
  `Rel(0.75)` 而不是猜一个基数。

`tests/test_theme.py::test_no_rel_survives_outside_the_whitelist` 守着这条
约定（新增的 `Rel` 落点会让它变红）。

## 主题族（9 套完整主题 + 一个别名）

4.0.3 一共导出 9 套完整主题；它们全部登记在 `ggcore.registry`，所以
`p + theme_bw()`、`p.theme_bw()` 与 `ggcore.plot.theme_bw()` 是同一个构造器
的三个入口。下表由注册表派生（`pixi run docs:theme`），加主题只需
`register_theme()`，文档与 `THEME_NAMES` 会一起跟上：

<!-- BEGIN GENERATED: registered-themes -->
| 入口 | `Theme.name` | 完整主题 | 定义元素 | 解析元素 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `theme_grey()` | `grey` | ✓ | 55 | 146 | ggplot2 的默认主题（`R/theme-defaults.R: theme_grey`）。 |
| `theme_gray()` | `grey` | ✓ | 55 | 146 | ggplot2 的默认主题（`R/theme-defaults.R: theme_grey`）。 |
| `theme_bw()` | `bw` | ✓ | 55 | 146 | `theme_bw()`：theme_grey 的白底变体（theme_minimal 的底）。 |
| `theme_classic()` | `classic` | ✓ | 55 | 146 | `theme_classic()`：只有轴线、没有网格与边框的经典风格。 |
| `theme_light()` | `light` | ✓ | 56 | 146 | `theme_light()`：白底 + 浅灰网格/边框。 |
| `theme_dark()` | `dark` | ✓ | 56 | 146 | `theme_dark()`：灰面板 + 深灰网格（深色背景上的点图）。 |
| `theme_linedraw()` | `linedraw` | ✓ | 56 | 146 | `theme_linedraw()`：`theme_bw()` 的纯黑线条变体（网格线是实黑）。 |
| `theme_minimal()` | `minimal` | ✓ | 58 | 146 | `theme_minimal()`：白底、无边框、无刻度线。 |
| `theme_test()` | `test` | ✓ | 55 | 146 | `theme_test()`：白底 + 面板边框、无网格（上游是独立定义，不派生）。 |
| `theme_void()` | `void` | ✓ | 41 | 146 | `theme_void()`：完全不画背景/网格/坐标轴，只留标题类文字。 |
<!-- END GENERATED: registered-themes -->

派生关系（上游一律用 `%+replace%`：整份替换同名元素，**不**合并字段）：

- `theme_grey()` 是根，也是 `theme_gray()` 的同一份定义；
- `theme_bw()` 在 grey 上换白底 + 浅灰网格 + 边框；
- `theme_minimal()` 在 bw 上抹掉面板背景/边框/刻度；
- `theme_light()` / `theme_dark()` 从 grey 派生（面板色与网格色）；
- `theme_classic()`（轴线取代边框）与 `theme_linedraw()`（纯黑线条）从 bw 派生；
- `theme_void()` 与 `theme_test()` 是独立定义（不派生），前者几乎全 blank，
  后者白底 + 面板边框 + 无网格。

`%+replace%` 与 `+` 在 `merge_theme()` 里是两条分支：前者（`_replace()`）
把同名元素整份换掉，后者（`theme()` 的 `_merge_element()`）只填 `None`
字段、`rel()` 留到解析期。`p + theme_bw()` 走「完整主题替换」是因为
`merge_theme()` 看到 `override.complete` 就返回整份新主题——这就是
`theme_grey() + theme_bw()` 与 `theme_grey() + theme(...)` 语义不同的原因。

### `theme_set` / `theme_get` / `theme_update` / `theme_replace`

全局默认主题对应上游的 `ggplot_global$theme_current`：

| 函数 | 语义 | 返回值 |
| --- | --- | --- |
| `theme_get()` | 当前默认主题（初值 `theme_grey()`） | `Theme` |
| `theme_set(new)` | 整份换掉默认主题；只接受完整主题，`theme_set()` 无参时返回当前值 | 旧主题 |
| `theme_update(**elements)` | `theme_set(theme_get() + theme(...))`：逐元素合并 | 旧主题 |
| `theme_replace(**elements)` | `theme_set(theme_get() %+replace% theme(...))`：整份替换同名元素 | 旧主题 |

`ggplot()` 的默认主题取 `theme_get()`，`resolve_theme()` 对局部主题的合并底
也是 `theme_get()`（对应上游 `calc_element(element, plot_theme(plot))` 里
`default = get_theme()` 的位置）。`theme_set()` 之后新建的图与未指定主题的
局部 `theme()` 都跟着变；已经构造出来的图保留构造时的主题对象（`ggplot`
克隆时主题是不可变值，不做回溯替换）。

### `theme_sub_*`（4.0）

4.0 把「带前缀的元素名」包成了函数：`theme_sub_axis_x(text = ...)` 等价于
`theme(**{"axis.text.x": ...})`。ggcore 的 11 个函数与上游同名同参数，
参数名的 `_` 对应元素名的 `.`（`key_spacing_x` → `legend.key.spacing.x`）：

| 函数 | 前缀 / 后缀 | 映射到的元素 |
| --- | --- | --- |
| `theme_sub_axis` | `axis.` | `title` / `text` / `ticks` / `ticks_length` / `line` / `minor_ticks_length` |
| `theme_sub_axis_x` / `_y` | `axis.`, `.x` / `.y` | 同上 6 个 + 方位后缀 |
| `theme_sub_axis_top` / `_bottom` / `_left` / `_right` | `axis.`, `.x.top` / `.x.bottom` / `.y.left` / `.y.right` | 再加 `minor_ticks`（`axis.minor.ticks.*`） |
| `theme_sub_legend` | `legend.` | 所有 `legend.*`（text / title / key / box / justification / position …） |
| `theme_sub_panel` | `panel.` | 所有 `panel.*`（background / border / grid / spacing / widths / heights / ontop） |
| `theme_sub_plot` | `plot.` | 所有 `plot.*`（background / title / subtitle / caption / tag / margin） |
| `theme_sub_strip` | `strip.` | 所有 `strip.*`（background / text / clip / placement / switch.pad） |

未传的参数（`_UNSET`）不写进主题；显式传 `None` 与 `theme(**{name: None})`
一样表示「删掉这个元素，回落到父元素」。未知参数名是 Python 的 `TypeError`，
未知元素名仍由 `theme()` 报 `ThemeError`。

## 逐元素解析值（全部主题）

下面两张表都由 `resolve_theme()` 直接生成（`pixi run docs:theme`，
`pixi run docs:theme:check` 守新鲜度）。`—` = 该主题没有定义、解析结果是
`None`；`blank` = `element_blank()`（明确画空白，不继承）。每套主题都解析出
`ELEMENT_TREE` 的全部 146 个元素，逐元素与 R 的 `calc_element()` 对拍在
`tests/test_theme_r_parity.py`（21 个夹具键 × 146 个元素）。

写法约定：`lty` = `linetype`，`blty` = `bordertype`，`lw` / `bw` / `fs` / `ps`
= `linewidth` / `borderwidth` / `fontsize` / `pointsize`，`h` / `v` / `a` =
`hjust` / `vjust` / `angle`，`lh` = `lineheight`，`m(...)` = `margin(t,r,b,l)`
（`auto` 是 `margin_auto()` 的自动边），`p<k>` = `shape` / `pointshape` 的 pch。

<!-- BEGIN GENERATED: theme-elements -->
#### 根元素

| 元素 | `grey` | `gray` | `bw` | `classic` | `light` | `dark` | `linedraw` | `minimal` | `test` | `void` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `geom` | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5 bw=0.5 fs=11 ps=1.5 lty1 blty1 p19 | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5 bw=0.5 fs=11 ps=1.5 lty1 blty1 p19 | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5 bw=0.5 fs=11 ps=1.5 lty1 blty1 p19 | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5 bw=0.5 fs=11 ps=1.5 lty1 blty1 p19 | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5 bw=0.5 fs=11 ps=1.5 lty1 blty1 p19 | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5 bw=0.5 fs=11 ps=1.5 lty1 blty1 p19 | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5 bw=0.5 fs=11 ps=1.5 lty1 blty1 p19 | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5 bw=0.5 fs=11 ps=1.5 lty1 blty1 p19 | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5 bw=0.5 fs=11 ps=1.5 lty1 blty1 p19 | geom ink=#000000 paper=#00000000 accent=#3366FF lw=0.5 bw=0.5 fs=11 ps=1.5 lty1 blty1 p19 |
| `line` | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | blank |
| `margins` | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) |
| `point` | point #000000 p19 1.5mm fill=#FFFFFF stroke=0.5 | point #000000 p19 1.5mm fill=#FFFFFF stroke=0.5 | point #000000 p19 1.5mm fill=#FFFFFF stroke=0.5 | point #000000 p19 1.5mm fill=#FFFFFF stroke=0.5 | point #000000 p19 1.5mm fill=#FFFFFF stroke=0.5 | point #000000 p19 1.5mm fill=#FFFFFF stroke=0.5 | point #000000 p19 1.5mm fill=#FFFFFF stroke=0.5 | point #000000 p19 1.5mm fill=#FFFFFF stroke=0.5 | point #000000 p19 1.5mm fill=#FFFFFF stroke=0.5 | blank |
| `polygon` | polygon fill=#FFFFFF colour=#000000 0.5mm lty1 round | polygon fill=#FFFFFF colour=#000000 0.5mm lty1 round | polygon fill=#FFFFFF colour=#000000 0.5mm lty1 round | polygon fill=#FFFFFF colour=#000000 0.5mm lty1 round | polygon fill=#FFFFFF colour=#000000 0.5mm lty1 round | polygon fill=#FFFFFF colour=#000000 0.5mm lty1 round | polygon fill=#FFFFFF colour=#000000 0.5mm lty1 round | polygon fill=#FFFFFF colour=#000000 0.5mm lty1 round | polygon fill=#FFFFFF colour=#000000 0.5mm lty1 round | blank |
| `rect` | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#00000000 colour=NA 0mm lty1 round |
| `spacing` | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt |
| `text` | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |
| `title` | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |

#### `axis.*`

| 元素 | `grey` | `gray` | `bw` | `classic` | `light` | `dark` | `linedraw` | `minimal` | `test` | `void` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `axis.line` | blank | blank | blank | line #000000 0.5mm lty1 square/round | blank | blank | blank | blank | blank | blank |
| `axis.line.r` | blank | blank | blank | line #000000 0.5mm lty1 square/round | blank | blank | blank | blank | blank | blank |
| `axis.line.theta` | blank | blank | blank | line #000000 0.5mm lty1 square/round | blank | blank | blank | blank | blank | blank |
| `axis.line.x` | blank | blank | blank | line #000000 0.5mm lty1 square/round | blank | blank | blank | blank | blank | blank |
| `axis.line.x.bottom` | blank | blank | blank | line #000000 0.5mm lty1 square/round | blank | blank | blank | blank | blank | blank |
| `axis.line.x.top` | blank | blank | blank | line #000000 0.5mm lty1 square/round | blank | blank | blank | blank | blank | blank |
| `axis.line.y` | blank | blank | blank | line #000000 0.5mm lty1 square/round | blank | blank | blank | blank | blank | blank |
| `axis.line.y.left` | blank | blank | blank | line #000000 0.5mm lty1 square/round | blank | blank | blank | blank | blank | blank |
| `axis.line.y.right` | blank | blank | blank | line #000000 0.5mm lty1 square/round | blank | blank | blank | blank | blank | blank |
| `axis.minor.ticks.length` | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | — |
| `axis.minor.ticks.length.r` | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 0pt |
| `axis.minor.ticks.length.theta` | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 0pt |
| `axis.minor.ticks.length.x` | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | — |
| `axis.minor.ticks.length.x.bottom` | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 0pt |
| `axis.minor.ticks.length.x.top` | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 0pt |
| `axis.minor.ticks.length.y` | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | rel(0.75) | — |
| `axis.minor.ticks.length.y.left` | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 0pt |
| `axis.minor.ticks.length.y.right` | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 2.0625pt | 0pt |
| `axis.minor.ticks.r` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.minor.ticks.theta` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.minor.ticks.x.bottom` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.minor.ticks.x.top` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.minor.ticks.y.left` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.minor.ticks.y.right` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.text` | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | blank |
| `axis.text.r` | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,2.2pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,2.2pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h0.5 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | blank |
| `axis.text.theta` | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | blank |
| `axis.text.x` | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | blank |
| `axis.text.x.bottom` | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(4.95pt,0pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(2.2pt,0pt,0pt,0pt) | blank |
| `axis.text.x.top` | text face=plain 8.8pt #4D4D4D h0.5 v0 a0 lh0.9 m(0pt,0pt,2.2pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0 a0 lh0.9 m(0pt,0pt,2.2pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0 a0 lh0.9 m(0pt,0pt,2.2pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.2pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0 a0 lh0.9 m(0pt,0pt,2.2pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0 a0 lh0.9 m(0pt,0pt,2.2pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.2pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v1 a0 lh0.9 m(0pt,0pt,4.95pt,0pt) | text face=plain 8.8pt #4D4D4D h0.5 v0 a0 lh0.9 m(0pt,0pt,2.2pt,0pt) | blank |
| `axis.text.y` | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | blank |
| `axis.text.y.left` | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,4.95pt,0pt,0pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,2.2pt,0pt,0pt) | blank |
| `axis.text.y.right` | text face=plain 8.8pt #4D4D4D h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,2.2pt) | text face=plain 8.8pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,2.2pt) | text face=plain 8.8pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,2.2pt) | text face=plain 8.8pt #4D4D4D h1 v0.5 a0 lh0.9 m(0pt,0pt,0pt,4.95pt) | text face=plain 8.8pt #4D4D4D h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,2.2pt) | blank |
| `axis.ticks` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.ticks.length` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 0pt |
| `axis.ticks.length.r` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 0pt |
| `axis.ticks.length.theta` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 0pt |
| `axis.ticks.length.x` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 0pt |
| `axis.ticks.length.x.bottom` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 0pt |
| `axis.ticks.length.x.top` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 0pt |
| `axis.ticks.length.y` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 0pt |
| `axis.ticks.length.y.left` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 0pt |
| `axis.ticks.length.y.right` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 0pt |
| `axis.ticks.r` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.ticks.theta` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.ticks.x` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.ticks.x.bottom` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.ticks.x.top` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.ticks.y` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.ticks.y.left` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.ticks.y.right` | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #333333 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #B3B3B3 0.25mm lty1 butt/round | line #333333 0.25mm lty1 butt/round | line #000000 0.25mm lty1 butt/round | blank | line #333333 0.5mm lty1 butt/round | blank |
| `axis.title` | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | blank |
| `axis.title.x` | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | blank |
| `axis.title.x.bottom` | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a0 lh0.9 m(2.75pt,0pt,0pt,0pt) | blank |
| `axis.title.x.top` | text face=plain 11pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.75pt,0pt) | text face=plain 11pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.75pt,0pt) | text face=plain 11pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.75pt,0pt) | text face=plain 11pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.75pt,0pt) | text face=plain 11pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.75pt,0pt) | text face=plain 11pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.75pt,0pt) | text face=plain 11pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.75pt,0pt) | text face=plain 11pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.75pt,0pt) | text face=plain 11pt #000000 h0.5 v0 a0 lh0.9 m(0pt,0pt,2.75pt,0pt) | blank |
| `axis.title.y` | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | blank |
| `axis.title.y.left` | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | text face=plain 11pt #000000 h0.5 v1 a90 lh0.9 m(0pt,2.75pt,0pt,0pt) | blank |
| `axis.title.y.right` | text face=plain 11pt #000000 h0.5 v1 a-90 lh0.9 m(0pt,0pt,0pt,2.75pt) | text face=plain 11pt #000000 h0.5 v1 a-90 lh0.9 m(0pt,0pt,0pt,2.75pt) | text face=plain 11pt #000000 h0.5 v1 a-90 lh0.9 m(0pt,0pt,0pt,2.75pt) | text face=plain 11pt #000000 h0.5 v1 a-90 lh0.9 m(0pt,0pt,0pt,2.75pt) | text face=plain 11pt #000000 h0.5 v1 a-90 lh0.9 m(0pt,0pt,0pt,2.75pt) | text face=plain 11pt #000000 h0.5 v1 a-90 lh0.9 m(0pt,0pt,0pt,2.75pt) | text face=plain 11pt #000000 h0.5 v1 a-90 lh0.9 m(0pt,0pt,0pt,2.75pt) | text face=plain 11pt #000000 h0.5 v1 a-90 lh0.9 m(0pt,0pt,0pt,2.75pt) | text face=plain 11pt #000000 h0.5 v1 a-90 lh0.9 m(0pt,0pt,0pt,2.75pt) | blank |

#### `legend.*`

| 元素 | `grey` | `gray` | `bw` | `classic` | `light` | `dark` | `linedraw` | `minimal` | `test` | `void` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `legend.axis.line` | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | blank |
| `legend.background` | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | blank | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | blank |
| `legend.box` | — | — | — | — | — | — | — | — | — | — |
| `legend.box.background` | blank | blank | blank | blank | blank | blank | blank | blank | blank | blank |
| `legend.box.just` | — | — | — | — | — | — | — | — | — | — |
| `legend.box.margin` | m(0pt,0pt,0pt,0pt) | m(0pt,0pt,0pt,0pt) | m(0pt,0pt,0pt,0pt) | m(0pt,0pt,0pt,0pt) | m(0pt,0pt,0pt,0pt) | m(0pt,0pt,0pt,0pt) | m(0pt,0pt,0pt,0pt) | m(0pt,0pt,0pt,0pt) | m(0cm,0cm,0cm,0cm) | m(0pt,0pt,0pt,0pt) |
| `legend.box.spacing` | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 0.2cm |
| `legend.byrow` | — | — | — | — | — | — | — | — | — | — |
| `legend.direction` | — | — | — | — | — | — | — | — | — | — |
| `legend.frame` | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | blank |
| `legend.justification` | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | — |
| `legend.justification.bottom` | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | — |
| `legend.justification.inside` | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | — |
| `legend.justification.left` | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | — |
| `legend.justification.right` | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | — |
| `legend.justification.top` | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | 'center' | — |
| `legend.key` | rect fill=#EBEBEB colour=NA 0.5mm lty1 round | rect fill=#EBEBEB colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#7F7F7F colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | blank | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | blank |
| `legend.key.height` | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines |
| `legend.key.justification` | — | — | — | — | — | — | — | — | — | — |
| `legend.key.size` | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines |
| `legend.key.spacing` | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt |
| `legend.key.spacing.x` | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt |
| `legend.key.spacing.y` | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt |
| `legend.key.width` | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines | 1.2lines |
| `legend.location` | — | — | — | — | — | — | — | — | — | — |
| `legend.margin` | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(0cm,0cm,0cm,0cm) | m(0pt,0pt,0pt,0pt) |
| `legend.position` | 'right' | 'right' | 'right' | 'right' | 'right' | 'right' | 'right' | 'right' | 'right' | 'right' |
| `legend.position.inside` | — | — | — | — | — | — | — | — | — | — |
| `legend.spacing` | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 5.5pt |
| `legend.spacing.x` | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 5.5pt |
| `legend.spacing.y` | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 11pt | 5.5pt |
| `legend.text` | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |
| `legend.text.position` | — | — | — | — | — | — | — | — | — | — |
| `legend.ticks` | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | blank |
| `legend.ticks.length` | 0.24lines | 0.24lines | 0.24lines | 0.24lines | 0.24lines | 0.24lines | 0.24lines | 0.24lines | 0.24lines | 0.24lines |
| `legend.title` | text face=plain 11pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 11pt #000000 h0 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |
| `legend.title.position` | — | — | — | — | — | — | — | — | — | — |

#### `panel.*`

| 元素 | `grey` | `gray` | `bw` | `classic` | `light` | `dark` | `linedraw` | `minimal` | `test` | `void` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `panel.background` | rect fill=#EBEBEB colour=NA 0.5mm lty1 round | rect fill=#EBEBEB colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#7F7F7F colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | blank | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | blank |
| `panel.border` | blank | blank | rect fill=#FFFFFF colour=#333333 0.5mm lty1 round | blank | rect fill=#FFFFFF colour=#B3B3B3 0.5mm lty1 round | blank | rect fill=#FFFFFF colour=#000000 0.5mm lty1 round | blank | rect fill=#FFFFFF colour=#333333 0.5mm lty1 round | blank |
| `panel.grid` | line #FFFFFF 0.5mm lty1 butt/round | line #FFFFFF 0.5mm lty1 butt/round | line #EBEBEB 0.5mm lty1 butt/round | blank | line #DEDEDE 0.5mm lty1 butt/round | line #6B6B6B 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | line #EBEBEB 0.5mm lty1 butt/round | line #000000 0.5mm lty1 butt/round | blank |
| `panel.grid.major` | line #FFFFFF 0.5mm lty1 butt/round | line #FFFFFF 0.5mm lty1 butt/round | line #EBEBEB 0.5mm lty1 butt/round | blank | line #DEDEDE 0.25mm lty1 butt/round | line #6B6B6B 0.25mm lty1 butt/round | line #000000 0.05mm lty1 butt/round | line #EBEBEB 0.5mm lty1 butt/round | blank | blank |
| `panel.grid.major.x` | line #FFFFFF 0.5mm lty1 butt/round | line #FFFFFF 0.5mm lty1 butt/round | line #EBEBEB 0.5mm lty1 butt/round | blank | line #DEDEDE 0.25mm lty1 butt/round | line #6B6B6B 0.25mm lty1 butt/round | line #000000 0.05mm lty1 butt/round | line #EBEBEB 0.5mm lty1 butt/round | blank | blank |
| `panel.grid.major.y` | line #FFFFFF 0.5mm lty1 butt/round | line #FFFFFF 0.5mm lty1 butt/round | line #EBEBEB 0.5mm lty1 butt/round | blank | line #DEDEDE 0.25mm lty1 butt/round | line #6B6B6B 0.25mm lty1 butt/round | line #000000 0.05mm lty1 butt/round | line #EBEBEB 0.5mm lty1 butt/round | blank | blank |
| `panel.grid.minor` | line #FFFFFF 0.25mm lty1 butt/round | line #FFFFFF 0.25mm lty1 butt/round | line #EBEBEB 0.25mm lty1 butt/round | blank | line #DEDEDE 0.125mm lty1 butt/round | line #6B6B6B 0.125mm lty1 butt/round | line #000000 0.025mm lty1 butt/round | line #EBEBEB 0.25mm lty1 butt/round | blank | blank |
| `panel.grid.minor.x` | line #FFFFFF 0.25mm lty1 butt/round | line #FFFFFF 0.25mm lty1 butt/round | line #EBEBEB 0.25mm lty1 butt/round | blank | line #DEDEDE 0.125mm lty1 butt/round | line #6B6B6B 0.125mm lty1 butt/round | line #000000 0.025mm lty1 butt/round | line #EBEBEB 0.25mm lty1 butt/round | blank | blank |
| `panel.grid.minor.y` | line #FFFFFF 0.25mm lty1 butt/round | line #FFFFFF 0.25mm lty1 butt/round | line #EBEBEB 0.25mm lty1 butt/round | blank | line #DEDEDE 0.125mm lty1 butt/round | line #6B6B6B 0.125mm lty1 butt/round | line #000000 0.025mm lty1 butt/round | line #EBEBEB 0.25mm lty1 butt/round | blank | blank |
| `panel.heights` | — | — | — | — | — | — | — | — | — | — |
| `panel.ontop` | False | False | False | False | False | False | False | False | False | False |
| `panel.spacing` | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt |
| `panel.spacing.x` | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt |
| `panel.spacing.y` | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt | 5.5pt |
| `panel.widths` | — | — | — | — | — | — | — | — | — | — |

#### `plot.*`

| 元素 | `grey` | `gray` | `bw` | `classic` | `light` | `dark` | `linedraw` | `minimal` | `test` | `void` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `plot.background` | rect fill=#FFFFFF colour=#FFFFFF 0.5mm lty1 round | rect fill=#FFFFFF colour=#FFFFFF 0.5mm lty1 round | rect fill=#FFFFFF colour=#FFFFFF 0.5mm lty1 round | rect fill=#FFFFFF colour=#FFFFFF 0.5mm lty1 round | rect fill=#FFFFFF colour=#FFFFFF 0.5mm lty1 round | rect fill=#FFFFFF colour=#FFFFFF 0.5mm lty1 round | rect fill=#FFFFFF colour=#FFFFFF 0.5mm lty1 round | rect fill=#FFFFFF colour=NA 0.5mm lty1 round | rect fill=#FFFFFF colour=#FFFFFF 0.5mm lty1 round | rect fill=#00000000 colour=NA 0mm lty1 round |
| `plot.caption` | text face=plain 8.8pt #000000 h1 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) | text face=plain 8.8pt #000000 h1 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) |
| `plot.caption.position` | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' |
| `plot.margin` | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(5.5pt,5.5pt,5.5pt,5.5pt) | m(0pt,0pt,0pt,0pt) |
| `plot.subtitle` | text face=plain 11pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 11pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 11pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 11pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 11pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 11pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 11pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 11pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 11pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 11pt #000000 h0 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) |
| `plot.tag` | text face=plain 13.2pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 13.2pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 13.2pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 13.2pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 13.2pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 13.2pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 13.2pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 13.2pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 13.2pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) | text face=plain 13.2pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |
| `plot.tag.location` | — | — | — | — | — | — | — | — | — | — |
| `plot.tag.position` | 'topleft' | 'topleft' | 'topleft' | 'topleft' | 'topleft' | 'topleft' | 'topleft' | 'topleft' | 'topleft' | 'topleft' |
| `plot.title` | text face=plain 13.2pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 13.2pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 13.2pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 13.2pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 13.2pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 13.2pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 13.2pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 13.2pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 13.2pt #000000 h0 v1 a0 lh0.9 m(0pt,0pt,5.5pt,0pt) | text face=plain 13.2pt #000000 h0 v1 a0 lh0.9 m(5.5pt,0pt,0pt,0pt) |
| `plot.title.position` | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' | 'panel' |

#### `strip.*`

| 元素 | `grey` | `gray` | `bw` | `classic` | `light` | `dark` | `linedraw` | `minimal` | `test` | `void` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `strip.background` | rect fill=#D9D9D9 colour=NA 0.5mm lty1 round | rect fill=#D9D9D9 colour=NA 0.5mm lty1 round | rect fill=#D9D9D9 colour=#333333 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 1mm lty1 round | rect fill=#B3B3B3 colour=NA 0.5mm lty1 round | rect fill=#262626 colour=NA 0.5mm lty1 round | rect fill=#000000 colour=#000000 0.5mm lty1 round | blank | rect fill=#D9D9D9 colour=#333333 0.5mm lty1 round | blank |
| `strip.background.x` | rect fill=#D9D9D9 colour=NA 0.5mm lty1 round | rect fill=#D9D9D9 colour=NA 0.5mm lty1 round | rect fill=#D9D9D9 colour=#333333 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 1mm lty1 round | rect fill=#B3B3B3 colour=NA 0.5mm lty1 round | rect fill=#262626 colour=NA 0.5mm lty1 round | rect fill=#000000 colour=#000000 0.5mm lty1 round | blank | rect fill=#D9D9D9 colour=#333333 0.5mm lty1 round | blank |
| `strip.background.y` | rect fill=#D9D9D9 colour=NA 0.5mm lty1 round | rect fill=#D9D9D9 colour=NA 0.5mm lty1 round | rect fill=#D9D9D9 colour=#333333 0.5mm lty1 round | rect fill=#FFFFFF colour=#000000 1mm lty1 round | rect fill=#B3B3B3 colour=NA 0.5mm lty1 round | rect fill=#262626 colour=NA 0.5mm lty1 round | rect fill=#000000 colour=#000000 0.5mm lty1 round | blank | rect fill=#D9D9D9 colour=#333333 0.5mm lty1 round | blank |
| `strip.clip` | 'on' | 'on' | 'on' | 'on' | 'on' | 'on' | 'on' | 'on' | 'on' | 'on' |
| `strip.placement` | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | — |
| `strip.placement.x` | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | — |
| `strip.placement.y` | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | 'inside' | — |
| `strip.switch.pad.grid` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt |
| `strip.switch.pad.wrap` | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt | 2.75pt |
| `strip.text` | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #E5E5E5 h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |
| `strip.text.x` | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #E5E5E5 h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |
| `strip.text.x.bottom` | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #E5E5E5 h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |
| `strip.text.x.top` | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #E5E5E5 h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a0 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |
| `strip.text.y` | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #E5E5E5 h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |
| `strip.text.y.left` | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #E5E5E5 h0.5 v0.5 a90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |
| `strip.text.y.right` | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #E5E5E5 h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #FFFFFF h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #1A1A1A h0.5 v0.5 a-90 lh0.9 m(4.4pt,4.4pt,4.4pt,4.4pt) | text face=plain 8.8pt #000000 h0.5 v0.5 a0 lh0.9 m(0pt,0pt,0pt,0pt) |

#### 其它

| 元素 | `grey` | `gray` | `bw` | `classic` | `light` | `dark` | `linedraw` | `minimal` | `test` | `void` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `aspect.ratio` | — | — | — | — | — | — | — | — | — | — |

<!-- END GENERATED: theme-elements -->

## 与 ggplot2 的刻意差异

1. **根元素 `rel()` 提前求值**。`calc_element()` 对没有父元素的 `text` /
   `line` 等保持 `rel` 原样，渲染时才消费；`resolve_theme()` 按主题的
   `base_size` 折成 pt/mm（见上文）。这是「解析值必须可断言」这条任务契约
   要求的唯一数值差异。
2. **`NA` 用哨兵表示**。R 的 `NA_character_` 与 `NULL` 是两种值；ggcore 用
   `ggcore.theme.NA` 表示「明确不画」，`None` 表示「未设置、继承」。
   解析后两者都落成 `None`（画的时候没有颜色）。
3. **`margin_auto()` 的自动边用 `None`**。R 用 `NA`；ggcore 的 `Margin`
   四个边各自是 `Unit` 或 `None`，`None` 就是自动。
4. **`element_geom.fontsize` 保持 pt**。上游构造器内部除以 `.pt` 存成 mm；
   ggcore 的 IR/绘制口径统一用 pt，所以这里不转换。
5. **不支持 `palette.*` 元素**（4.0.3 的调色板主题元素）。`theme()` 会把它
   当未知元素报错；调色板语义不在 M1-10 / M2-5 的范围。

## 与后续任务的接口

- **`panel.grid.*` 的绘制（SIL-723 已接上）**：`ggcore.geom.scene._panel_children()`
  按 `panel.background → panel.grid.major.{x,y} → panel.grid.minor.{x,y} →
  panel.border → 图层` 的顺序装 grob。位置与轴同源：major 用该面板标度的
  `breaks()`，minor 用 `ScaleBase.minor_breaks()`（连续 = 相邻主断点中点，
  离散没有次网格；log10 的中点在对数空间）。元素走继承链
  （`panel.grid.major.x` ← `.major` ← `panel.grid` ← `line`），`element_blank()`
  或 `colour = NA` 不画，`linewidth` / `linetype` / `lineend` 生效。
  `theme_grey()` / `theme_minimal()` / `theme_bw()` 现在都有对应 case
  （`theme-grey-basic` / `theme-minimal-basic` / `theme-bw-basic` 等）。
- `resolve_theme()` 的结果是只读映射：`resolved["axis.text"]` 拿到具体元素，
  `resolved.size_pt("axis.text")` 直接拿字号（pt），`resolved.is_blank(name)`
  判断是否 blank。
- 本任务不做 gtable 装配、边距计算与图例布局；这些由 M1-11 与 facet 任务
  消费这里的解析值。`theme_set()` 的全局改动不会回写已构造的图。
- `resolve_theme(theme, metrics)` 的 `metrics` 目前只保留给后续的
  `strwidth` / `strheight` 单位与 guide 布局，元素值不依赖字体度量。
