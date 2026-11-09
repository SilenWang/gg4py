# `geom_*`：几何对象

几何对象决定「一行数据画成什么」。名字与 ggplot2 4.0.3 的 `NAMESPACE` 一致（51 个
注册名，覆盖上游 53 个 `geom_*` 导出；`geom_sf_text` / `geom_sf_label` 是图层组合，
只在 `gg4py` 的公开命名空间里，见 [`r-to-python.md`](r-to-python.md) §4）。完整清单：

| 族 | 名字 |
| --- | --- |
| 点 / 线 / 路径 | `geom_point` `geom_jitter` `geom_line` `geom_path` `geom_freqpoly` `geom_step` `geom_segment` `geom_curve` `geom_spoke` `geom_rug` `geom_blank` |
| 柱 / 面 | `geom_bar` `geom_col` `geom_histogram` `geom_area` `geom_ribbon` `geom_rect` `geom_tile` `geom_raster` `geom_polygon` `geom_map` |
| 区间 / 分布 | `geom_boxplot` `geom_violin` `geom_dotplot` `geom_crossbar` `geom_errorbar` `geom_errorbarh` `geom_linerange` `geom_pointrange` |
| 文本 | `geom_text` `geom_label` |
| 2D / 密度 | `geom_bin2d` `geom_bin_2d` `geom_hex` `geom_contour` `geom_contour_filled` `geom_density` `geom_density2d` `geom_density_2d` `geom_density2d_filled` `geom_density_2d_filled` `geom_count` |
| 参考线 | `geom_abline` `geom_hline` `geom_vline` |
| 统计快捷 | `geom_smooth` `geom_quantile` `geom_function` `geom_qq` `geom_qq_line` |
| 空间 | `geom_sf` `geom_sf_text` `geom_sf_label`（见 [`sf.md`](sf.md)） |

通用参数（所有 `geom_*()` 都收）：`mapping=`、`data=`、`stat=`、`position=`、
`inherit_aes=`、`show_legend=`，其余 `**params` 是该几何自己的参数（`size` /
`colour` / `width` …）。参数名用下划线（`na_rm`）。

## 1. 点与线

| 参数 | 含义 | 单位 / 缺省 |
| --- | --- | --- |
| `point.size` | 点直径 | mm，缺省 1.5 |
| `point.shape` | 点形状（pch 0–25 与形状名） | 缺省 19 |
| `point.stroke` | 点描边宽 | mm，缺省 0.5 |
| `line.linewidth` / `path.linewidth` | 线宽 | mm，缺省 0.5 |
| `line.linetype` | 线型（1–6 或名字） | 缺省 1（实线） |

```python
from gg4py import aes, geom_line, geom_point, ggplot, labs, theme_minimal, to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6],
    "y": [1.0, 2.4, 2.0, 3.6, 3.1, 4.4, 2.2, 1.6, 2.8, 2.4, 3.9, 3.3],
    "g": ["a"] * 6 + ["b"] * 6,
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", colour="g"))
    + geom_line(linewidth=1.2)
    + geom_point(size=2.6, shape=21, fill="white", stroke=1.0)
    + labs(title="lines + points, shape 21", x="x", y="y")
    + theme_minimal()
)
```

`geom_line()` 按 `x` 排序后连线，`geom_path()` 保持行序。分组来自离散美学；
不想给颜色时用 `aes(group=...)`（见 [`aes.md`](aes.md) §5）。NA 断线：组内首尾
缺失删掉、中间缺失断成两段。

## 2. 柱、直方图与面积

| geom | 默认 stat | 说明 |
| --- | --- | --- |
| `geom_bar()` | `count` | 只给 `x`，高度自动数行数 |
| `geom_col()` | `identity` | 给 `x` + `y`，高度就是 `y` |
| `geom_histogram()` | `bin` | `bins=` / `binwidth=` |
| `geom_area()` | `align` | 到 y=0 的面积；`outline.type` |
| `geom_ribbon()` | `identity` | 自己给 `ymin` / `ymax` |

```python
from gg4py import (
    aes,
    geom_col,
    geom_histogram,
    geom_point,
    ggplot,
    labs,
    theme_minimal,
    to_column_table,
)

DATA = {
    "class": ["compact", "midsize", "suv", "compact", "midsize", "suv"],
    "n": [12.0, 9.0, 15.0, 14.0, 11.0, 18.0],
    "year": ["1999", "1999", "1999", "2008", "2008", "2008"],
}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="class", y="n", fill="year"))
    + geom_col(width=0.65, position="dodge")
    + labs(title="geom_col + position='dodge'", x="class", y="n")
    + theme_minimal()
)
```

```python
from gg4py import aes, geom_histogram, ggplot, labs, to_column_table

DATA = {"value": [1.2, 1.8, 2.1, 2.6, 3.0, 3.4, 3.9, 4.4, 5.1, 5.6, 2.2, 2.9]}

p = (
    ggplot(to_column_table(DATA), aes(x="value"))
    + geom_histogram(bins=6, fill="#4C78A8", colour="white", linewidth=0.4)
    + labs(title="geom_histogram(bins = 6)", x="value", y="count")
)
```

柱系列的 `width` 是相对离散单位的比例（缺省 0.9）；`position` 见
[`position.md`](position.md)。

## 3. 分布：箱线、小提琴、点阵

| geom | 关键参数 |
| --- | --- |
| `geom_boxplot()` | `width`、`varwidth`、`outlier.shape/size/colour`、`coef` |
| `geom_violin()` | `width`、`trim`、`scale`（`area` / `count` / `width`）、`quantile.linetype` |
| `geom_dotplot()` | `binwidth`、`binaxis`、`stackdir`、`stackratio`、`dotsize` |

```python
from gg4py import aes, geom_boxplot, geom_violin, ggplot, labs, theme_minimal, to_column_table

DATA = {
    "class": [
        "compact",
        "compact",
        "compact",
        "midsize",
        "midsize",
        "midsize",
        "suv",
        "suv",
        "suv",
    ],
    "value": [1.9, 2.4, 3.1, 2.6, 3.2, 4.0, 3.4, 4.4, 5.9],
}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="class", y="value", fill="class"))
    + geom_violin(width=0.8, alpha=0.5, colour=None)
    + geom_boxplot(width=0.18, fill="white", **{"outlier.shape": 16, "outlier.size": 1.4})
    + labs(title="violin + boxplot", x="class", y="value")
    + theme_minimal()
)
```

`geom_boxplot()` 的默认 stat 是 `stat_boxplot()`（五数 + 须线 + 离群点）；
预计算好的五数列也能直接画（`aes(x=, lower=, upper=, middle=, ymin=, ymax=)`）。

## 4. 拟合与函数

| geom | 说明 |
| --- | --- |
| `geom_smooth()` | `method="lm"` / `"loess"`，`se=`，`span=`（loess），`formula=` |
| `geom_quantile()` | 分位回归：`quantiles=[0.25, 0.5, 0.75]` |
| `geom_function()` | `fun=` 一个 Python 可调用，配合 `xlim=` |

```python
from gg4py import aes, geom_point, geom_smooth, ggplot, labs, theme_minimal, to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8],
    "y": [1.1, 2.3, 2.0, 3.4, 3.2, 4.5, 4.1, 5.2],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=2.5, colour="#4C78A8")
    + geom_smooth(method="lm", se=True, colour="#E45756")
    + labs(title="geom_smooth(method = 'lm')", x="x", y="y")
    + theme_minimal()
)
```

`geom_smooth()` 的置信带来自 `stat_smooth()` 的 `ymin` / `ymax`；`se=False` 只画线。
`geom_function(fun=lambda x: x * 0.5)` 需要给 `xlim=` 或者由面板范围决定。

## 5. 文本与标签

`geom_text()` 用 `size`（mm，缺省 3.87 ≈ 11 pt）、`hjust` / `vjust`（0–1 或
`"left"` / `"centre"` / `"right"` …）、`angle`、`family`、`fontface`；
`geom_label()` 多一个背景框（`fill` / `label.padding` / `label.r`）。

```python
from gg4py import aes, geom_label, geom_point, ggplot, labs, theme_minimal, to_column_table

DATA = {
    "x": [1, 2, 3, 4],
    "y": [1.0, 3.2, 2.1, 4.4],
    "name": ["alpha", "beta", "gamma", "delta"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=2.6, colour="#4C78A8")
    + geom_label(aes(label="name"), nudge_y=0.22, size=3.4, **{"label.padding": 0.2})
    + labs(title="geom_label with a nudge", x="x", y="y")
    + theme_minimal()
)
```

`check_overlap=True`（`geom_text`）按行序删掉重叠的标签；`geom_text()` /
`geom_label()` 的默认 position 是 `position_nudge()`，可直接传 `nudge_x` /
`nudge_y`。

## 6. 区间与带状

| geom | 需要的美学 |
| --- | --- |
| `geom_errorbar()` / `geom_errorbarh()` | `x`（或 `y`）+ `ymin` / `ymax`（`xmin` / `xmax`），`width=` |
| `geom_linerange()` | 同上，无横杠 |
| `geom_pointrange()` | 再加 `y`（点） |
| `geom_crossbar()` | 再加 `y`（中间横线） |
| `geom_ribbon()` | `x` + `ymin` / `ymax` |
| `geom_segment()` / `geom_curve()` | `x` `y` `xend` `yend`；`arrow=` |

```python
from gg4py import (
    aes,
    arrow,
    geom_errorbar,
    geom_line,
    geom_point,
    ggplot,
    labs,
    theme_minimal,
    to_column_table,
)

DATA = {
    "x": [1, 2, 3, 4],
    "y": [2.0, 3.1, 2.6, 4.0],
    "lo": [1.6, 2.7, 2.1, 3.5],
    "hi": [2.4, 3.5, 3.1, 4.5],
}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="x", y="y"))
    + geom_line(linewidth=1.0, colour="#4C78A8")
    + geom_point(size=2.6)
    + geom_errorbar(aes(ymin="lo", ymax="hi"), width=0.12, colour="#4C78A8")
    + labs(title="error bars from precomputed bounds", x="x", y="y")
    + theme_minimal()
)
```

```python
from gg4py import aes, arrow, geom_curve, geom_point, ggplot, labs, to_column_table

DATA = {"x": [1.0, 2.0], "y": [1.0, 2.0], "xend": [3.0, 4.0], "yend": [2.5, 1.5]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y", xend="xend", yend="yend"))
    + geom_point(size=2.4)
    + geom_curve(curvature=0.35, arrow=arrow(length=6.0))
    + labs(title="geom_curve + arrow()", x="x", y="y")
)
```

## 7. 矩形、瓦片与多边形

| geom | 需要的美学 | 用途 |
| --- | --- | --- |
| `geom_rect()` | `xmin` `xmax` `ymin` `ymax`（或 `x` + `width`） | 任意矩形 |
| `geom_tile()` | `x` `y` + `fill`（`width` / `height`） | 热图格子 |
| `geom_raster()` | `x` `y` + `fill` | 规则网格的位图式填充（更快） |
| `geom_polygon()` | `x` `y` + `group` | 自绘多边形 |

```python
from gg4py import aes, geom_tile, ggplot, labs, scale_fill_viridis_c, theme_minimal, to_column_table

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
YEARS = ["2021", "2022", "2023"]
DATA = {
    "month": [m for _ in YEARS for m in MONTHS],
    "year": [y for y in YEARS for _ in MONTHS],
    "value": [
        3.1,
        4.4,
        6.0,
        9.2,
        13.1,
        16.4,
        3.4,
        4.8,
        6.6,
        9.9,
        13.9,
        17.2,
        3.8,
        5.2,
        7.1,
        10.6,
        14.8,
        18.0,
    ],
}

p = (
    ggplot(to_column_table(DATA), aes(x="month", y="year", fill="value"))
    + geom_tile(colour="white", linewidth=0.6)
    + scale_fill_viridis_c(option="C")
    + labs(title="geom_tile + viridis", x=None, y=None)
    + theme_minimal()
)
```

## 8. 2D 族

| geom | 说明 |
| --- | --- |
| `geom_bin_2d()` / `geom_bin2d()` | 矩形分箱计数，`fill` 映射 `count` |
| `geom_hex()` | 六边形分箱，需要 `hexbin` 的算法（已内联） |
| `geom_contour()` / `geom_contour_filled()` | 等值线 / 等值带，**需要 contourpy** |
| `geom_density_2d()` / `geom_density_2d_filled()` | 二维密度等值线 |

```python
from gg4py import aes, geom_contour_filled, ggplot, labs, to_column_table

GRID = {
    "x": [x for _ in range(1, 6) for x in range(1, 6)],
    "y": [y for y in range(1, 6) for _ in range(1, 6)],
    "z": [x * 0.5 + y for y in range(1, 6) for x in range(1, 6)],
}

p = (
    ggplot(to_column_table(GRID), aes(x="x", y="y", z="z"))
    + geom_contour_filled()
    + labs(title="geom_contour_filled", x="x", y="y")
)
```

`contourpy` 只在等值线路径上加载；在浏览器里要在脚本里写
`needs = ["numpy", "contourpy"]`（见 [`browser.md`](browser.md) §2）。

## 9. 参考线与辅助

| geom | 参数 |
| --- | --- |
| `geom_abline()` | `slope=` / `intercept=` |
| `geom_hline()` / `geom_vline()` | `yintercept=` / `xintercept=` |
| `geom_rug()` | `sides="bl"` |
| `geom_count()` | 点数映射到 `size`（默认 `stat_sum`） |
| `geom_blank()` | 只撑范围、不画东西 |
| `geom_map()` | 最小可用：`map=` / `map_id=` |
| `geom_qq()` / `geom_qq_line()` | 配 `aes(sample="y")` |
| `geom_step()` | `direction="hv"` |

```python
from gg4py import aes, geom_hline, geom_point, geom_rug, geom_vline, ggplot, labs

DATA = {"x": [1.0, 2.2, 2.9, 4.1], "y": [2.0, 3.4, 2.2, 4.6]}
from gg4py import to_column_table

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=2.6, colour="#4C78A8")
    + geom_hline(yintercept=3.0, linetype=2, colour="grey60")
    + geom_vline(xintercept=2.5, linetype=2, colour="grey60")
    + geom_rug(sides="bl", colour="#E45756")
    + labs(title="hline + vline + rug", x="x", y="y")
)
```

## 10. 与上游的差异

- `geom_freqpoly()` 与 `geom_line(stat="bin")` 是同一个画法：默认 stat 是 `bin`，
  IR 与显式写 `geom_line(stat="bin")` 逐字节相同。
- `geom_map()` 只做最小可用（gallery 里依赖完整 `maps` 数据的图不在验收范围）。
- `annotate("abline" / "hline" / "vline", ...)` 不支持（上游同样建议直接用对应
  geom；gg4py 给一条 warning），见 [`annotation.md`](annotation.md)。
- 2D 族里 `geom_bin2d` / `geom_bin_2d` 等别名共用同一个实现；两个名字都注册。
- `geom_point(max_points=N)` 是 gg4py 扩展（按行号等距降采样），用于 10 万点以
  上的散点；默认不降采样（`docs/notes/performance.md`）。
