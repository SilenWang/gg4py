# 主题账本（theme）

`ggcore.theme` 是 ggplot2 4.0.3 主题系统的对等物：元素对象、元素树、继承、
`rel()` 求值、局部覆盖，以及 `theme_grey()` / `theme_minimal()` / `theme_void()`
三套完整主题。目标不是「看起来像」，而是每个元素都能解析成可断言的数字：

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

`tests/test_theme_r_parity.py` 对三套主题的每个元素逐项比对，夹具里的数值就是
ggplot2 `calc_element()` 的结果（颜色/单位/边距已换成 ggcore 的规范形式）。

## 元素对象

元素是不可变的 frozen dataclass；没给的字段是 `None`（未设置，解析时从父元素
继承）。`element_blank()` 是独立的类型，表示「明确画空白」。

| 构造器 | 字段 |
| --- | --- |
| `element_text(family, face, italic, fontweight, fontwidth, size, colour, hjust, vjust, angle, lineheight, margin)` | 另可 `debug=` / `inherit_blank=`；`italic` / `fontweight` / `fontwidth` 原样透传 |
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

## 三套完整主题

`theme_grey()`（默认）、`theme_minimal()`（`theme_bw()` 再删背景/边框/刻度）、
`theme_void()`（几乎全部 blank，只留标题类文字）都照 4.0.3 的数值构造。
三套主题共享 `base_size=11`、`base_line_size=base_size/22=0.5`、
`base_rect_size=0.5`；`ink="black"`、`paper="white"`、`accent="#3366FF"`。
`theme_void()` 的 `paper` 默认是 `alpha(ink, 0)`（`#00000000`）。
`theme_bw()` 也注册在册：`p + theme_bw()` 与 `p.theme_bw()` 等价。

八类核心元素的解析值（pt 为字号，mm 为线宽）：

| 元素 | theme_grey | theme_minimal | theme_void |
| --- | --- | --- | --- |
| `plot.background` | rect fill=#FFFFFF colour=#FFFFFF lw=0.5mm | rect fill=#FFFFFF colour=NA lw=0.5mm | rect fill=#00000000 colour=NA lw=0mm |
| `panel.background` | rect fill=#EBEBEB colour=NA lw=0.5mm | blank | blank |
| `panel.grid.major` | line #FFFFFF lw=0.5mm | line #EBEBEB lw=0.5mm | blank |
| `axis.text` | text 8.8pt #4D4D4D | text 8.8pt #4D4D4D | blank |
| `axis.title` | text 11pt #000000 | text 11pt #000000 | blank |
| `plot.title` | text 13.2pt #000000 h=0 v=1 margin(0/0/5.5pt/0) | 同 grey | text 13.2pt h=0 v=1 margin(5.5pt/0/0/0) |
| `legend.text` | text 8.8pt #000000 | text 8.8pt #000000 | text 8.8pt #000000 |
| `legend.key` | rect fill=#EBEBEB colour=NA lw=0.5mm | blank | blank |

完整逐元素对照表（`—` = 该主题没有定义、解析结果是 `None`）：

| 元素 | theme_grey | theme_minimal | theme_void |
| --- | --- | --- | --- |
| `aspect.ratio` | — | — | — |
| `axis.line` | blank | blank | blank |
| `axis.line.r` | blank | blank | blank |
| `axis.line.theta` | blank | blank | blank |
| `axis.line.x` | blank | blank | blank |
| `axis.line.x.bottom` | blank | blank | blank |
| `axis.line.x.top` | blank | blank | blank |
| `axis.line.y` | blank | blank | blank |
| `axis.line.y.left` | blank | blank | blank |
| `axis.line.y.right` | blank | blank | blank |
| `axis.minor.ticks.length` | rel(0.75) | rel(0.75) | — |
| `axis.minor.ticks.length.r` | unit(2.0625pt) | unit(2.0625pt) | unit(0pt) |
| `axis.minor.ticks.length.theta` | unit(2.0625pt) | unit(2.0625pt) | unit(0pt) |
| `axis.minor.ticks.length.x` | rel(0.75) | rel(0.75) | — |
| `axis.minor.ticks.length.x.bottom` | unit(2.0625pt) | unit(2.0625pt) | unit(0pt) |
| `axis.minor.ticks.length.x.top` | unit(2.0625pt) | unit(2.0625pt) | unit(0pt) |
| `axis.minor.ticks.length.y` | rel(0.75) | rel(0.75) | — |
| `axis.minor.ticks.length.y.left` | unit(2.0625pt) | unit(2.0625pt) | unit(0pt) |
| `axis.minor.ticks.length.y.right` | unit(2.0625pt) | unit(2.0625pt) | unit(0pt) |
| `axis.minor.ticks.r` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.minor.ticks.theta` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.minor.ticks.x.bottom` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.minor.ticks.x.top` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.minor.ticks.y.left` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.minor.ticks.y.right` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.text` | text 8.8pt #4D4D4D h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 8.8pt #4D4D4D h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | blank |
| `axis.text.r` | text 8.8pt #4D4D4D h=0.5 v=0.5 angle=0 lh=0.9 margin(0/2.2/0/2.2pt) | text 8.8pt #4D4D4D h=0.5 v=0.5 angle=0 lh=0.9 margin(0/2.2/0/2.2pt) | blank |
| `axis.text.theta` | text 8.8pt #4D4D4D h=0.5 v=1 angle=0 lh=0.9 margin(2.2/0/0/0pt) | text 8.8pt #4D4D4D h=0.5 v=1 angle=0 lh=0.9 margin(2.2/0/0/0pt) | blank |
| `axis.text.x` | text 8.8pt #4D4D4D h=0.5 v=1 angle=0 lh=0.9 margin(2.2/0/0/0pt) | text 8.8pt #4D4D4D h=0.5 v=1 angle=0 lh=0.9 margin(2.2/0/0/0pt) | blank |
| `axis.text.x.bottom` | text 8.8pt #4D4D4D h=0.5 v=1 angle=0 lh=0.9 margin(2.2/0/0/0pt) | text 8.8pt #4D4D4D h=0.5 v=1 angle=0 lh=0.9 margin(4.95/0/0/0pt) | blank |
| `axis.text.x.top` | text 8.8pt #4D4D4D h=0.5 v=0 angle=0 lh=0.9 margin(0/0/2.2/0pt) | text 8.8pt #4D4D4D h=0.5 v=1 angle=0 lh=0.9 margin(0/0/4.95/0pt) | blank |
| `axis.text.y` | text 8.8pt #4D4D4D h=1 v=0.5 angle=0 lh=0.9 margin(0/2.2/0/0pt) | text 8.8pt #4D4D4D h=1 v=0.5 angle=0 lh=0.9 margin(0/2.2/0/0pt) | blank |
| `axis.text.y.left` | text 8.8pt #4D4D4D h=1 v=0.5 angle=0 lh=0.9 margin(0/2.2/0/0pt) | text 8.8pt #4D4D4D h=1 v=0.5 angle=0 lh=0.9 margin(0/4.95/0/0pt) | blank |
| `axis.text.y.right` | text 8.8pt #4D4D4D h=0 v=0.5 angle=0 lh=0.9 margin(0/0/0/2.2pt) | text 8.8pt #4D4D4D h=1 v=0.5 angle=0 lh=0.9 margin(0/0/0/4.95pt) | blank |
| `axis.ticks` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.ticks.length` | unit(2.75pt) | unit(2.75pt) | unit(0pt) |
| `axis.ticks.length.r` | unit(2.75pt) | unit(2.75pt) | unit(0pt) |
| `axis.ticks.length.theta` | unit(2.75pt) | unit(2.75pt) | unit(0pt) |
| `axis.ticks.length.x` | unit(2.75pt) | unit(2.75pt) | unit(0pt) |
| `axis.ticks.length.x.bottom` | unit(2.75pt) | unit(2.75pt) | unit(0pt) |
| `axis.ticks.length.x.top` | unit(2.75pt) | unit(2.75pt) | unit(0pt) |
| `axis.ticks.length.y` | unit(2.75pt) | unit(2.75pt) | unit(0pt) |
| `axis.ticks.length.y.left` | unit(2.75pt) | unit(2.75pt) | unit(0pt) |
| `axis.ticks.length.y.right` | unit(2.75pt) | unit(2.75pt) | unit(0pt) |
| `axis.ticks.r` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.ticks.theta` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.ticks.x` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.ticks.x.bottom` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.ticks.x.top` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.ticks.y` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.ticks.y.left` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.ticks.y.right` | line #333333 lw=0.5mm lty=1 butt/round | blank | blank |
| `axis.title` | text 11pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 11pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | blank |
| `axis.title.x` | text 11pt #000000 h=0.5 v=1 angle=0 lh=0.9 margin(2.75/0/0/0pt) | text 11pt #000000 h=0.5 v=1 angle=0 lh=0.9 margin(2.75/0/0/0pt) | blank |
| `axis.title.x.bottom` | text 11pt #000000 h=0.5 v=1 angle=0 lh=0.9 margin(2.75/0/0/0pt) | text 11pt #000000 h=0.5 v=1 angle=0 lh=0.9 margin(2.75/0/0/0pt) | blank |
| `axis.title.x.top` | text 11pt #000000 h=0.5 v=0 angle=0 lh=0.9 margin(0/0/2.75/0pt) | text 11pt #000000 h=0.5 v=0 angle=0 lh=0.9 margin(0/0/2.75/0pt) | blank |
| `axis.title.y` | text 11pt #000000 h=0.5 v=1 angle=90 lh=0.9 margin(0/2.75/0/0pt) | text 11pt #000000 h=0.5 v=1 angle=90 lh=0.9 margin(0/2.75/0/0pt) | blank |
| `axis.title.y.left` | text 11pt #000000 h=0.5 v=1 angle=90 lh=0.9 margin(0/2.75/0/0pt) | text 11pt #000000 h=0.5 v=1 angle=90 lh=0.9 margin(0/2.75/0/0pt) | blank |
| `axis.title.y.right` | text 11pt #000000 h=0.5 v=1 angle=-90 lh=0.9 margin(0/0/0/2.75pt) | text 11pt #000000 h=0.5 v=1 angle=-90 lh=0.9 margin(0/0/0/2.75pt) | blank |
| `geom` | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5mm fontsize=11pt pointsize=1.5 shape=19 | geom ink=#000000 paper=#FFFFFF accent=#3366FF lw=0.5mm fontsize=11pt pointsize=1.5 shape=19 | geom ink=#000000 paper=#00000000 accent=#3366FF lw=0.5mm fontsize=11pt pointsize=1.5 shape=19 |
| `legend.axis.line` | line #000000 lw=0.5mm lty=1 butt/round | line #000000 lw=0.5mm lty=1 butt/round | blank |
| `legend.background` | rect fill=#FFFFFF colour=NA lw=0.5mm lty=1 round | blank | blank |
| `legend.box` | — | — | — |
| `legend.box.background` | blank | blank | blank |
| `legend.box.just` | — | — | — |
| `legend.box.margin` | margin(0/0/0/0pt) | margin(0/0/0/0pt) | margin(0/0/0/0pt) |
| `legend.box.spacing` | unit(11pt) | unit(11pt) | unit(0.2cm) |
| `legend.byrow` | — | — | — |
| `legend.direction` | — | — | — |
| `legend.frame` | rect fill=#FFFFFF colour=#000000 lw=0.5mm lty=1 round | rect fill=#FFFFFF colour=#000000 lw=0.5mm lty=1 round | blank |
| `legend.justification` | 'center' | 'center' | — |
| `legend.justification.bottom` | 'center' | 'center' | — |
| `legend.justification.inside` | 'center' | 'center' | — |
| `legend.justification.left` | 'center' | 'center' | — |
| `legend.justification.right` | 'center' | 'center' | — |
| `legend.justification.top` | 'center' | 'center' | — |
| `legend.key` | rect fill=#EBEBEB colour=NA lw=0.5mm lty=1 round | blank | blank |
| `legend.key.height` | unit(1.2lines) | unit(1.2lines) | unit(1.2lines) |
| `legend.key.justification` | — | — | — |
| `legend.key.size` | unit(1.2lines) | unit(1.2lines) | unit(1.2lines) |
| `legend.key.spacing` | unit(5.5pt) | unit(5.5pt) | unit(5.5pt) |
| `legend.key.spacing.x` | unit(5.5pt) | unit(5.5pt) | unit(5.5pt) |
| `legend.key.spacing.y` | unit(5.5pt) | unit(5.5pt) | unit(5.5pt) |
| `legend.key.width` | unit(1.2lines) | unit(1.2lines) | unit(1.2lines) |
| `legend.location` | — | — | — |
| `legend.margin` | margin(5.5/5.5/5.5/5.5pt) | margin(5.5/5.5/5.5/5.5pt) | margin(0/0/0/0pt) |
| `legend.position` | 'right' | 'right' | 'right' |
| `legend.position.inside` | — | — | — |
| `legend.spacing` | unit(11pt) | unit(11pt) | unit(5.5pt) |
| `legend.spacing.x` | unit(11pt) | unit(11pt) | unit(5.5pt) |
| `legend.spacing.y` | unit(11pt) | unit(11pt) | unit(5.5pt) |
| `legend.text` | text 8.8pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 8.8pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 8.8pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `legend.text.position` | — | — | — |
| `legend.ticks` | line #000000 lw=0.5mm lty=1 butt/round | line #000000 lw=0.5mm lty=1 butt/round | blank |
| `legend.ticks.length` | unit(0.24lines) | unit(0.24lines) | unit(0.24lines) |
| `legend.title` | text 11pt #000000 h=0 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 11pt #000000 h=0 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 11pt #000000 h=0 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `legend.title.position` | — | — | — |
| `line` | line #000000 lw=0.5mm lty=1 butt/round | line #000000 lw=0.5mm lty=1 butt/round | blank |
| `margins` | margin(5.5/5.5/5.5/5.5pt) | margin(5.5/5.5/5.5/5.5pt) | margin(5.5/5.5/5.5/5.5pt) |
| `panel.background` | rect fill=#EBEBEB colour=NA lw=0.5mm lty=1 round | blank | blank |
| `panel.border` | blank | blank | blank |
| `panel.grid` | line #FFFFFF lw=0.5mm lty=1 butt/round | line #EBEBEB lw=0.5mm lty=1 butt/round | blank |
| `panel.grid.major` | line #FFFFFF lw=0.5mm lty=1 butt/round | line #EBEBEB lw=0.5mm lty=1 butt/round | blank |
| `panel.grid.major.x` | line #FFFFFF lw=0.5mm lty=1 butt/round | line #EBEBEB lw=0.5mm lty=1 butt/round | blank |
| `panel.grid.major.y` | line #FFFFFF lw=0.5mm lty=1 butt/round | line #EBEBEB lw=0.5mm lty=1 butt/round | blank |
| `panel.grid.minor` | line #FFFFFF lw=0.25mm lty=1 butt/round | line #EBEBEB lw=0.25mm lty=1 butt/round | blank |
| `panel.grid.minor.x` | line #FFFFFF lw=0.25mm lty=1 butt/round | line #EBEBEB lw=0.25mm lty=1 butt/round | blank |
| `panel.grid.minor.y` | line #FFFFFF lw=0.25mm lty=1 butt/round | line #EBEBEB lw=0.25mm lty=1 butt/round | blank |
| `panel.heights` | — | — | — |
| `panel.ontop` | False | False | False |
| `panel.spacing` | unit(5.5pt) | unit(5.5pt) | unit(5.5pt) |
| `panel.spacing.x` | unit(5.5pt) | unit(5.5pt) | unit(5.5pt) |
| `panel.spacing.y` | unit(5.5pt) | unit(5.5pt) | unit(5.5pt) |
| `panel.widths` | — | — | — |
| `plot.background` | rect fill=#FFFFFF colour=#FFFFFF lw=0.5mm lty=1 round | rect fill=#FFFFFF colour=NA lw=0.5mm lty=1 round | rect fill=#00000000 colour=NA lw=0mm lty=1 round |
| `plot.caption` | text 8.8pt #000000 h=1 v=1 angle=0 lh=0.9 margin(5.5/0/0/0pt) | text 8.8pt #000000 h=1 v=1 angle=0 lh=0.9 margin(5.5/0/0/0pt) | text 8.8pt #000000 h=1 v=1 angle=0 lh=0.9 margin(5.5/0/0/0pt) |
| `plot.caption.position` | 'panel' | 'panel' | 'panel' |
| `plot.margin` | margin(5.5/5.5/5.5/5.5pt) | margin(5.5/5.5/5.5/5.5pt) | margin(0/0/0/0pt) |
| `plot.subtitle` | text 11pt #000000 h=0 v=1 angle=0 lh=0.9 margin(0/0/5.5/0pt) | text 11pt #000000 h=0 v=1 angle=0 lh=0.9 margin(0/0/5.5/0pt) | text 11pt #000000 h=0 v=1 angle=0 lh=0.9 margin(5.5/0/0/0pt) |
| `plot.tag` | text 13.2pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 13.2pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 13.2pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `plot.tag.location` | — | — | — |
| `plot.tag.position` | 'topleft' | 'topleft' | 'topleft' |
| `plot.title` | text 13.2pt #000000 h=0 v=1 angle=0 lh=0.9 margin(0/0/5.5/0pt) | text 13.2pt #000000 h=0 v=1 angle=0 lh=0.9 margin(0/0/5.5/0pt) | text 13.2pt #000000 h=0 v=1 angle=0 lh=0.9 margin(5.5/0/0/0pt) |
| `plot.title.position` | 'panel' | 'panel' | 'panel' |
| `point` | point #000000 shape=19 size=1.5 fill=#FFFFFF stroke=0.5 | point #000000 shape=19 size=1.5 fill=#FFFFFF stroke=0.5 | blank |
| `polygon` | polygon fill=#FFFFFF colour=#000000 lw=0.5mm lty=1 round | polygon fill=#FFFFFF colour=#000000 lw=0.5mm lty=1 round | blank |
| `rect` | rect fill=#FFFFFF colour=#000000 lw=0.5mm lty=1 round | rect fill=#FFFFFF colour=#000000 lw=0.5mm lty=1 round | rect fill=#00000000 colour=NA lw=0mm lty=1 round |
| `spacing` | unit(5.5pt) | unit(5.5pt) | unit(5.5pt) |
| `strip.background` | rect fill=#D9D9D9 colour=NA lw=0.5mm lty=1 round | blank | blank |
| `strip.background.x` | rect fill=#D9D9D9 colour=NA lw=0.5mm lty=1 round | blank | blank |
| `strip.background.y` | rect fill=#D9D9D9 colour=NA lw=0.5mm lty=1 round | blank | blank |
| `strip.clip` | 'on' | 'on' | 'on' |
| `strip.placement` | 'inside' | 'inside' | — |
| `strip.placement.x` | 'inside' | 'inside' | — |
| `strip.placement.y` | 'inside' | 'inside' | — |
| `strip.switch.pad.grid` | unit(2.75pt) | unit(2.75pt) | unit(2.75pt) |
| `strip.switch.pad.wrap` | unit(2.75pt) | unit(2.75pt) | unit(2.75pt) |
| `strip.text` | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=0 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=0 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `strip.text.x` | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=0 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=0 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `strip.text.x.bottom` | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=0 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=0 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `strip.text.x.top` | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=0 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=0 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `strip.text.y` | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=-90 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=-90 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `strip.text.y.left` | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=90 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=90 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `strip.text.y.right` | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=-90 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #1A1A1A h=0.5 v=0.5 angle=-90 lh=0.9 margin(4.4/4.4/4.4/4.4pt) | text 8.8pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `text` | text 11pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 11pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 11pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |
| `title` | text 11pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 11pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) | text 11pt #000000 h=0.5 v=0.5 angle=0 lh=0.9 margin(0/0/0/0pt) |

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
   当未知元素报错；调色板语义不在 M1-10 的范围。

## 与后续任务的接口

- **`panel.grid.*` 的绘制（SIL-723 已接上）**：`ggcore.geom.scene._panel_children()`
  按 `panel.background → panel.grid.major.{x,y} → panel.grid.minor.{x,y} →
  panel.border → 图层` 的顺序装 grob。位置与轴同源：major 用该面板标度的
  `breaks()`，minor 用 `ScaleBase.minor_breaks()`（连续 = 相邻主断点中点，
  离散没有次网格；log10 的中点在对数空间）。元素走继承链
  （`panel.grid.major.x` ← `.major` ← `panel.grid` ← `line`），`element_blank()`
  或 `colour = NA` 不画，`linewidth` / `linetype` / `lineend` 生效。
  `theme_grey()` / `theme_minimal()` 现在都是 1.87%（`theme-grey-basic` /
  `theme-minimal-basic`），SIL-715 #1/#2 关闭。

- `resolve_theme()` 的结果是只读映射：`resolved["axis.text"]` 拿到具体元素，
  `resolved.size_pt("axis.text")` 直接拿字号（pt），`resolved.is_blank(name)`
  判断是否 blank。
- 本任务不做 gtable 装配、边距计算、图例布局与 `theme_set/theme_get` 全局
  状态；这些由 M1-11 与 facet 任务消费这里的解析值。
- `resolve_theme(theme, metrics)` 的 `metrics` 目前只保留给后续的
  `strwidth` / `strheight` 单位与 guide 布局，元素值不依赖字体度量。
- 146 行逐元素表目前是手工维护的（与 `tests/fixtures/theme_r_reference.json`
  同源但未联动）；写生成器是待办，改了主题数值要记得同时更新表和夹具。
