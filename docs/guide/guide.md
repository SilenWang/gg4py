# `guide_*`：图例与主轴

guide 决定**怎么把标度讲给人看**：图例（legend / colourbar / bins）、主轴
（axis）、以及「不要图例」（none）。两种写法：

<!-- no-run: 三种写法的对照片段（完整可跑的用法见 §1） -->
```python
p + guides(colour="none")  # 按美学名给字符串
p + guides(colour=guide_legend(nrow=1))  # 给 guide 对象
p + scale_colour_discrete(guide="none")  # 落在标度上（优先级更低）
```

| 函数 | 用途 |
| --- | --- |
| `guide_legend()` | 离散图例（键 + 标签）；`nrow` `ncol` `byrow` `title` `reverse` |
| `guide_colourbar()` / `guide_colorbar()` | 连续色条；`nbin` `barwidth` `barheight` `title` |
| `guide_coloursteps()` / `guide_colorsteps()` | 分步色条；`even_steps` `nbin` |
| `guide_bins()` | 分箱图例；`show_limits` `title` |
| `guide_axis()` | 主轴；`angle` `title` `n.dodge` `check.overlap` |
| `guide_axis_logticks()` | 对数轴的小刻度；`base` `short` `mid` `long` |
| `guide_axis_stack()` | 把多个 axis guide 叠起来；`guide_axis_stack(guide_axis(...), guide_axis(...))` |
| `guide_axis_theta()` | 极坐标的 theta 轴 |
| `guide_none()` | 关掉（等价于 `"none"`） |
| `guide_custom()` | 自定义 grob 图例；`guide_custom(grob)` |

`guide_gengrob` / `guide_geom` / `guide_merge` / `guide_train` / `guide_transform`
是 guide 协议钩子（写自定义 guide 用的），不直接加到图上。

## 1. `guides()`：按美学关掉或改

```python
from ggcore.plot import aes, geom_point, ggplot, guides, guide_legend, labs
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6],
    "y": [2.0, 1.5, 4.2, 3.1, 5.4, 2.2],
    "g": ["a", "b", "a", "b", "a", "b"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g"))
    + geom_point(size=3)
    + guides(colour=guide_legend(nrow=1, title="Group"))
    + labs(title="guides(colour = guide_legend(nrow = 1))", x="x", y="y")
    + theme_minimal()
)
```

`guides(colour=None)` 取消 plot 级设置、回落到 `scale_*(guide=)` 的值；
`guides(colour=False)` 是旧写法，等同 `"none"`。`guides()` 也可以传 dict：
`guides({"colour": "none", "size": guide_legend()})`。

```python
from ggcore.plot import aes, geom_point, ggplot, guides, labs
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4],
    "y": [2.0, 1.5, 4.2, 3.1],
    "g": ["a", "b", "a", "b"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g"))
    + geom_point(size=3.2)
    + guides(colour="none")  # 只关颜色图例
    + labs(title='guides(colour = "none")', x="x", y="y")
)
```

## 2. 色条与分箱图例

```python
from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    guides,
    labs,
    scale_colour_viridis_c,
)
from ggcore.theme import theme_minimal
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6],
    "y": [2.0, 1.5, 4.2, 3.1, 5.4, 2.2],
    "z": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
    + geom_point(size=3.4)
    + scale_colour_viridis_c()
    + guides(colour=guide_colourbar(nbin=6, title="value", barwidth=unit(1.0, "cm")))
    + labs(title="guide_colourbar(nbin = 6)", x="x", y="y")
    + theme_minimal()
)
```

`barwidth` / `barheight` 是**长度单位**（`ggcore.units.unit(1.0, "cm")`），直接给
数字会报「无法换算成 cm」。连续标度缺省就是 colourbar；`guide_bins()` 把它换成
分箱的离散块，`guide_coloursteps()` 换成阶梯色条。

## 3. 主轴

```python
from ggcore.plot import aes, geom_point, ggplot, guide_axis, guides, labs
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4, 5], "y": [2.0, 1.5, 4.2, 3.1, 5.4]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + guides(x=guide_axis(angle=45, title="x (degrees of freedom)"))
    + labs(title="guide_axis(angle = 45)", y="y")
)
```

`guide_axis_stack()` 把两个 axis guide 叠起来（上面一行斜的、下面一行正的）：

```python
from ggcore.plot import aes, geom_point, ggplot, guide_axis, guide_axis_stack, guides, labs
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4, 5], "y": [2.0, 1.5, 4.2, 3.1, 5.4]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + guides(x=guide_axis_stack(guide_axis(angle=45), guide_axis()))
    + labs(title="guide_axis_stack(...)", x="x", y="y")
)
```

对数轴上想画更细的小刻度，用 `guide_axis_logticks()`（它画的是刻度，不是标签）：

```python
from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_axis_logticks,
    guides,
    labs,
    scale_y_log10,
)
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4], "y": [1.0, 10.0, 100.0, 1000.0]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + scale_y_log10()
    + guides(y=guide_axis_logticks())
    + labs(title="guide_axis_logticks()", x="x", y="y")
)
```

## 4. 位置：右 / 左 / 上 / 下 / 内嵌 / 无

图例位置在主题元素里：

```python
from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import element_text, theme, theme_minimal
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4],
    "y": [2.0, 1.5, 4.2, 3.1],
    "g": ["a", "b", "a", "b"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g"))
    + geom_point(size=3.2)
    + theme_minimal()
    + theme(
        **{
            "legend.position": "bottom",  # "right" | "left" | "top" | "bottom" | "inside" | "none"
            "legend.title": element_text(size=10),
            "legend.text": element_text(size=8),
        }
    )
    + labs(title="legend.position = 'bottom'", x="x", y="y")
)
```

内嵌图例用 `"inside"` + `legend.position.inside=(x, y)`（0–1 的相对坐标）。
`"none"` 与 `guides(colour="none")` 的差别：前者关掉**所有**图例并收回版面空间，
后者只关某个美学的 guide。

## 5. 边界

- `guides()` 的键可以是美学名，也可以是自定义 guide 的自由名字
  （`guides(custom=guide_custom(grob))`）。
- `guide_colourbar` 的 `barwidth` / `barheight` 要传长度单位对象。
- 极坐标的 theta 轴用 `guide_axis_theta()`；`sec_axis` 在极坐标下不可用。
- 图例的尺寸（键高、标题边距）由主题元素决定（`legend.key.size` /
  `legend.title` / `legend.text`），不是 guide 的参数。
