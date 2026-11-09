# `theme_*`：主题

主题决定**非数据墨迹**长什么样：背景、网格、轴、字体、图例位置、条带。两层：

1. **完整主题**（`theme_grey()` / `theme_bw()` / `theme_minimal()` …）：一套解析好的
   元素值，`p + theme_minimal()` 会**整份替换**当前主题；
2. **局部主题**（`theme(...)`）：只覆盖给到的元素，`p + theme(**{"panel.grid": ...})`。

元素名带点（`panel.grid.major`），Python 关键字不能带点，所以用 `**{...}` 传。
可用元素共 146 个，逐元素解析值见 [`../notes/theme.md`](../notes/theme.md)（生成物）。

## 1. 完整主题

| 主题 | 说明 |
| --- | --- |
| `theme_grey()` / `theme_gray()` | 默认：灰底白网格 |
| `theme_bw()` | 白底 + 边框 |
| `theme_linedraw()` | 白底黑框、无网格 |
| `theme_light()` | 浅灰网格 + 浅灰边框 |
| `theme_dark()` | 深灰底 |
| `theme_minimal()` | 无背景、浅灰网格 |
| `theme_classic()` | 只有轴线 |
| `theme_test()` | 参考图口径（细边框） |
| `theme_void()` | 什么都没有（地图 / 纯几何图常用） |

都收 `base_size=` / `base_family=` / `header_family=` / `base_line_size=` /
`base_rect_size=`（4.0 起还有 `ink=` / `paper=` / `accent=`）。

```python
from gg4py import aes, geom_point, ggplot, labs, theme_bw, to_column_table

DATA = {"x": [1, 2, 3, 4, 5], "y": [2.0, 1.5, 4.2, 3.1, 5.4]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + theme_bw(base_size=13)
    + labs(title="theme_bw(base_size = 13)", x="x", y="y")
)
```

## 2. `theme()`：局部覆盖

元素值由 `element_*()` 构造：

| 构造函数 | 用于 | 常用参数 |
| --- | --- | --- |
| `element_text()` | 文本 | `size` `colour` `family` `face` `angle` `hjust` `vjust` `lineheight` `margin` |
| `element_line()` | 线 | `colour` `linewidth` `linetype` `lineend` |
| `element_rect()` | 矩形 | `fill` `colour` `linewidth` `linetype` |
| `element_point()` | 点 | `colour` `shape` `size` `stroke` |
| `element_polygon()` | 多边形 | `fill` `colour` `linewidth` |
| `element_geom()` | 逐 geom 的缺省（4.0） | `ink` `paper` `accent` `linewidth` `fontsize` … |
| `element_blank()` | 抹掉 | — |
| `rel(mult)` | 相对字号 / 线宽 | `rel(0.8)` = 父元素的 80% |
| `margin(t, r, b, l, unit="pt")` | 边距 | — |

```python
from gg4py import aes, geom_point, ggplot, labs, theme_minimal, to_column_table
from ggcore.theme import element_blank, element_line, element_rect, element_text, rel, theme

DATA = {"x": [1, 2, 3, 4, 5], "y": [2.0, 1.5, 4.2, 3.1, 5.4]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + theme_minimal()
    + theme(
        **{
            "panel.grid.minor": element_blank(),
            "panel.grid.major": element_line(colour="#E4E4E4", linewidth=0.4),
            "axis.text": element_text(size=rel(0.8), colour="#4D4D4D"),
            "axis.text.x": element_text(angle=45, hjust=1),
            "plot.title": element_text(face="bold", size=rel(1.2), hjust=0),
            "plot.background": element_rect(fill="white", colour=None),
        }
    )
    + labs(title="local theme overrides", x="x", y="y")
)
```

元素继承：`axis.text.x` 继承 `axis.text`，再继承根 `text`；局部只写一项时其余从父
元素来。`None` 表示「删除这一项、回落到父元素」；`element_blank()` 是「真的不画」。

## 3. 逐 geom 的缺省：`element_geom()`

4.0.3 的新元素：`geom` 根元素 + `geom.<class>` 覆盖，影响几何的默认墨色、线宽、
字号等：

```python
from gg4py import aes, geom_point, geom_smooth, ggplot, labs, theme_minimal, to_column_table
from ggcore.theme import element_geom, theme

DATA = {
    "x": [1, 2, 3, 4, 5, 6],
    "y": [1.0, 2.6, 2.1, 4.2, 3.9, 5.4],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=2.6)
    + geom_smooth(method="lm", se=False)
    + theme_minimal()
    + theme(
        **{
            "geom": element_geom(ink="#2F4B7C", accent="#E45756", linewidth=1.1),
        }
    )
    + labs(title="element_geom(): per-geom ink / accent", x="x", y="y")
)
```

## 4. 全局默认：`theme_set` / `theme_get` / `theme_update` / `theme_replace`

```python
from gg4py import aes, geom_point, ggplot, labs, theme_grey, to_column_table
from ggcore.theme import element_blank, theme_get, theme_set, theme_update

DATA = {"x": [1, 2, 3], "y": [3.0, 1.0, 2.0]}

original = theme_get()
try:
    theme_set(theme_grey())  # 之后的 ggplot() 用它
    theme_update(**{"panel.grid.minor": element_blank()})  # 就地改当前默认
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(size=3)
        + labs(title=f"global default: {theme_get().name}")
    )
finally:
    theme_set(original)  # 示例不污染后面的图
```

| 函数 | 语义 |
| --- | --- |
| `theme_set(theme)` | 换掉全局默认（返回新默认） |
| `theme_get()` | 读当前默认 |
| `theme_update(**elements)` | 在当前默认上合并（`+` 的效果） |
| `theme_replace(**elements)` | 只留给到的元素（其余回落根元素） |

**新图才受全局默认影响**；已经构造好的 `ggplot` 保留它当时的主题。

## 5. `theme_sub_*` 简写

4.0.3 起每个元素组有一组简写，省掉字符串键：

```python
from gg4py import aes, geom_point, ggplot, labs, to_column_table
from ggcore.plot import theme_sub_axis, theme_sub_panel
from ggcore.theme import element_blank, element_text

DATA = {"x": [1, 2, 3], "y": [3.0, 1.0, 2.0]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + theme_sub_panel(grid=element_blank())
    + theme_sub_axis(text=element_text(colour="#E45756"))
    + labs(title="theme_sub_panel / theme_sub_axis", x="x", y="y")
)
```

可用的组：`theme_sub_axis`、`theme_sub_axis_x` / `_y` / `_top` / `_right` /
`_bottom` / `_left`、`theme_sub_legend`、`theme_sub_panel`、`theme_sub_plot`、
`theme_sub_strip`。带点的成员名（`spacing.x`）用下划线（`spacing_x`）。

## 6. 边界

- 元素名写错直接报错并列出 146 个可用元素（不静默忽略）。
- 两个 `theme()` 不能相加（`Theme + Theme` 不支持）；把两个都 `+` 到图上即可，
  后加的覆盖先加的。
- 完整主题（`theme_minimal()` 等）会**整份替换**；`theme()` 只合并。先加完整主题
  再加局部主题，顺序反过来会把局部覆盖冲掉。
- 字体：受管字体是 DejaVu / Noto / Noto CJK / Noto Emoji；`family=""` 用默认字族。
  精确的文字度量口径见 `docs/notes/metrics-ledger.md`。
