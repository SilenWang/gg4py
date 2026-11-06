# `coord_*`：坐标系

坐标决定「数据坐标 → 面板位置」的映射，以及面板的形状。参数名在构造时就校验，
写错会直接报错并列出可用参数（与 R 的 unused argument 一致）。

| 坐标系 | 参数 |
| --- | --- |
| `coord_cartesian()` | `xlim` `ylim` `expand` `clip`（`"on"` / `"off"` / `"inherit"`）`reverse` `ratio` |
| `coord_fixed()` | 同上；`ratio = y/x` 的纵横比 |
| `coord_equal()` | `coord_fixed(ratio=1)` 的别名 |
| `coord_flip()` | 交换 x / y（轴标签也跟着换） |
| `coord_trans()` / `coord_transform()` | `x=` / `y=` 变换名（`"log10"` `"sqrt"` `"reverse"` `"pseudo_log"` 或 `transform_compose(...)`） |
| `coord_polar()` | `theta`（`"x"` / `"y"`）`start` `direction` `clip` |
| `coord_radial()` | `theta` `start` `end` `thetalim` `rlim` `inner_radius` `reverse` `r_axis_inside` `rotate_angle` `expand` `clip` |
| `coord_sf()` | `crs` `default_crs` `xlim` `ylim` `expand` `label_axes` `label_graticule` `lims_method` `datum` |
| `coord_map()` | `projection`（mapproj 名字）`orientation` `xlim` `ylim` |
| `coord_quickmap()` | `xlim` `ylim` `expand` `orientation` `reverse` |

`coord_munch()` 也在公开命名空间里（非线性坐标的逐边细分），但它不是「加到图上
的坐标」，一般不用手动调用。

## 1. 范围与裁剪

```python
from ggcore.plot import aes, geom_point, ggplot, labs, coord_cartesian
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6],
    "y": [1.0, 2.6, 2.1, 4.2, 3.9, 5.4],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + coord_cartesian(xlim=(2, 5), ylim=(1, 5), expand=False)
    + labs(title="coord_cartesian(xlim, ylim, expand = False)", x="x", y="y")
    + theme_minimal()
)
```

`coord_cartesian()` 的 `xlim` / `ylim` **只裁视图**：面板外的数据仍然参与标度训练
与统计（与 `scale_*_continuous(limits=)` 的「先删数据」不同）。`clip="off"` 让
超出面板的墨迹画到面板外。

## 2. 等比例

```python
from ggcore.plot import aes, geom_point, ggplot, labs, coord_equal, coord_fixed
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4], "y": [1.0, 1.6, 2.9, 3.4]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + coord_fixed(ratio=0.5)  # 1 个 x 单位 = 0.5 个 y 单位的长度
    + labs(title="coord_fixed(ratio = 0.5)", x="x", y="y")
    + theme_minimal()
)
```

`coord_equal()` 就是 `coord_fixed(ratio=1)`；地图 / 几何图常用。面板宽高比由
`ratio × yrange/xrange` 决定，`fixed` / `equal` 会锁死它，不会被画布拉变形。

## 3. 翻转

```python
from ggcore.plot import aes, coord_flip, geom_col, ggplot, labs
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {"class": ["compact", "midsize", "suv"], "n": [12.0, 9.0, 15.0]}

p = (
    ggplot(to_column_table(DATA), aes(x="class", y="n"))
    + geom_col(fill="#4C78A8", width=0.6)
    + coord_flip()
    + labs(title="coord_flip()", x=None, y="n")
    + theme_minimal()
)
```

`coord_flip()` 交换轴与标度槽：原来的 `x` 标度去画纵向。横向柱状图的另一种写法是
让 geom 自己横向（`geom_col()` + 交换映射），两种都行，倾向后者时可少一层坐标。

## 4. 极坐标与放射坐标

```python
from ggcore.plot import aes, coord_polar, geom_col, ggplot, labs
from ggcore.theme import theme, theme_minimal
from ggio.frame import to_column_table

DATA = {
    "class": ["a", "b", "c", "d", "e", "f"],
    "n": [12.0, 9.0, 15.0, 7.0, 11.0, 13.0],
}

p = (
    ggplot(to_column_table(DATA), aes(x="class", y="n", fill="class"))
    + geom_col(width=0.85)
    + coord_polar()
    + labs(title="coord_polar(theta = 'x')", x=None, y=None)
    + theme_minimal()
    + theme(**{"legend.position": "none"})
)
```

```python
from ggcore.plot import aes, coord_radial, geom_col, ggplot, labs
from ggcore.theme import theme, theme_minimal
from ggio.frame import to_column_table

DATA = {
    "class": ["a", "b", "c", "d", "e", "f"],
    "n": [12.0, 9.0, 15.0, 7.0, 11.0, 13.0],
}

p = (
    ggplot(to_column_table(DATA), aes(x="class", y="n", fill="class"))
    + geom_col(width=0.85)
    + coord_radial(inner_radius=0.3, start=-1.2, end=1.2)  # 半圆 + 中空
    + labs(title="coord_radial(inner_radius = 0.3, start, end)")
    + theme_minimal()
    + theme(**{"legend.position": "none"})
)
```

`theta="y"` 时角度来自 `y`、半径来自 `x`（抽屉图那种用法）。放射坐标的
`inner_radius` 用 0–1 的比例；`r_axis_inside` / `rotate_angle` 控制 r 轴位置与
标签旋转。`facet_wrap()` + 极坐标的组合支持固定标度；`space="free"` 会被拒绝
（上游 4.0.3 自己报错）。

## 5. 变换坐标

```python
from ggcore.plot import aes, coord_trans, geom_point, ggplot, labs
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "x": [1.0, 2.0, 4.0, 8.0, 16.0],
    "y": [1.0, 4.0, 9.0, 16.0, 25.0],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + coord_trans(y="sqrt")
    + labs(title="coord_trans(y = 'sqrt')", x="x", y="y")
    + theme_minimal()
)
```

`coord_trans()` 在**几何层面**变换（点 / 线仍按变换后的坐标画直线段），
`scale_*_trans()` 在**数据层面**变换（线在变换空间里是直线）。两者对散点相同，
对线 / 面积不同。

## 6. 次轴

```python
from ggcore.plot import aes, dup_axis, geom_point, ggplot, labs, scale_x_continuous, sec_axis
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 1.5, 4.2, 3.1]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + scale_x_continuous(sec_axis=sec_axis(lambda v: v * 2.54, name="cm"))
    + labs(title="sec_axis(fn, name = 'cm')", x="inch", y="y")
    + theme_minimal()
)
```

`sec_axis()` 收一个**可调用**（把主标度的值映射到次标度）与次轴名；`dup_axis()`
复制主轴。极坐标下没有次轴（与上游一致，报错而不是画错）。

## 7. sf / 地图

`geom_sf` 只能和 `coord_sf()` 一起用；`coord_map()` / `coord_quickmap()` 收
经纬度数据（普通 `x` / `y` 列即可），按 mapproj 的口径算面板比例。完整用法见
[`sf.md`](sf.md)。

## 8. 边界

- 每个坐标系认的参数是**白名单**，多余参数直接报错（`CoordError` 带可用列表）。
- `coord_polar()` / `coord_radial()` 与 `facet_wrap(space="free")` 一起用会报错：
  上游 4.0.3 在 `init_gtable()` 里自己失败，gg4py 不静默出非正圆面板。
- `coord_trans()` 的复合变换用 `ggcore.scales.transform_compose(...)` 组合
  （例如 `transform_compose("log10", "reverse")`），不是字符串拼接。
