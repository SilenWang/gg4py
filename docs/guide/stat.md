# `stat_*`：统计变换

stat 在「映射之后、标度之前」重算数据：分箱、计数、五数、拟合、密度、分位、
汇总……结果列再交给 geom 画。两个写法等价：

<!-- no-run: 两种写法的对照片段（下面每节都有完整可跑的示例） -->
```python
geom_histogram(bins=30)  # geom 的快捷方式：改这一层的默认 stat 参数
stat_bin(geom="bar", bins=30)  # stat 的快捷方式：改这一层的默认 geom
```

参数路由（与上游一致，别混）：`geom_*(...)` 的 `**params` 进 **geom 层**，
`stat_*(...)` 的 `**params` 进 **stat**。`geom_histogram(bins=30)` 的 `bins` 落在
图层参数里、由 `stat_bin` 读取；直接构造 `stat_bin(bins=30)` 则进 stat 参数。

## 1. 清单（37 个注册名，覆盖上游 36 个 `stat_*` 导出）

`stat_bindot` 是 gg4py 的额外注册名（上游 4.0.3 的 `NAMESPACE` 不导出它）。

| 族 | 名字 | 默认 geom |
| --- | --- | --- |
| 基础 | `stat_identity` / `stat_manual` / `stat_unique` / `stat_align` | point / point / point / area |
| 分箱 / 计数 | `stat_bin` / `stat_count` / `stat_sum` / `stat_summary_bin` | bar / bar / point / pointrange |
| 分布 | `stat_boxplot` / `stat_ydensity` / `stat_density` / `stat_ecdf` / `stat_qq` / `stat_qq_line` / `stat_ellipse` / `stat_quantile` / `stat_function` / `stat_connect` | boxplot / violin / area / step / point / abline / path / quantile / function / path |
| 拟合 | `stat_smooth` | smooth |
| 汇总 | `stat_summary` | pointrange |
| 2D | `stat_bin_2d` / `stat_bin2d` / `stat_bin_hex` / `stat_binhex` / `stat_summary_2d` / `stat_summary2d` / `stat_summary_hex` / `stat_contour` / `stat_contour_filled` / `stat_density_2d` / `stat_density2d` / `stat_density_2d_filled` / `stat_density2d_filled` | tile / tile / hex / hex / tile / tile / hex / contour / contour_filled / density_2d / density_2d / density_2d_filled / density_2d_filled |
| 空间 | `stat_sf` / `stat_sf_coordinates` | rect / point |

**废弃**：`stat_spoke()` 在 4.0.3 是 `deprecate_stop()`，调用即报错，用 `geom_spoke()`。

## 2. 分箱与计数

| stat | 关键参数 | 产出列（`after_stat`） |
| --- | --- | --- |
| `stat_bin` | `bins` / `binwidth` / `center` / `boundary` / `closed` | `count` `density` `ncount` `ndensity` `width` |
| `stat_count` | `width` | `count` `prop` |
| `stat_sum` | — | `n` |
| `stat_summary_bin` | `bins` / `fun` / `fun.min` / `fun.max` | `y` `ymin` `ymax` |

```python
from gg4py import (
    aes,
    after_stat,
    geom_bar,
    geom_histogram,
    ggplot,
    labs,
    theme_minimal,
    to_column_table,
)

DATA = {
    "class": ["compact", "compact", "midsize", "midsize", "suv", "suv", "suv"],
    "value": [1.2, 1.8, 2.1, 2.6, 3.0, 3.4, 3.9],
}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="class"))
    + geom_bar(aes(y=after_stat("count")), fill="#4C78A8")
    + labs(title="stat_count → count", x="class", y="count")
    + theme_minimal()
)
```

```python
from gg4py import aes, after_stat, geom_histogram, ggplot, labs, scale_y_continuous, to_column_table

DATA = {"value": [1.2, 1.8, 2.1, 2.6, 2.9, 3.0, 3.4, 3.6, 3.9, 4.4]}

p = (
    ggplot(to_column_table(DATA), aes(x="value"))
    + geom_histogram(aes(y=after_stat("density")), bins=5, fill="#4C78A8")
    + scale_y_continuous(name="density")
    + labs(title="stat_bin → density", x="value")
)
```

## 3. 分布

| stat | 关键参数 | 说明 |
| --- | --- | --- |
| `stat_boxplot` | `coef` | 五数：`lower` / `upper` / `middle` / `ymin` / `ymax` / `outliers` |
| `stat_ydensity` | `trim` / `scale` / `adjust` | 小提琴的密度宽度 |
| `stat_density` | `bw` / `adjust` / `kernel` / `trim` / `n` | 一维核密度 |
| `stat_ecdf` | `n` / `pad` | 经验分布阶梯 |
| `stat_qq` / `stat_qq_line` | `distribution` / `dparams` | 配 `aes(sample="y")` |
| `stat_ellipse` | `type` / `level` / `segments` | 置信椭圆 |
| `stat_quantile` | `quantiles` / `formula` / `method` | 分位回归 |
| `stat_function` | `fun` / `xlim` / `n` / `args` | 函数曲线 |
| `stat_connect` | `direction` | 按观测顺序连接 |

```python
from gg4py import (
    aes,
    geom_point,
    ggplot,
    labs,
    stat_ellipse,
    stat_qq,
    stat_qq_line,
    to_column_table,
)

DATA = {
    "x": [1.0, 1.4, 1.9, 2.2, 2.6, 3.0, 3.3, 3.8],
    "y": [1.2, 1.8, 1.5, 2.6, 2.2, 3.1, 2.8, 3.9],
    "value": [1.9, 2.4, 2.6, 3.0, 3.2, 3.7, 4.1, 4.8],
}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="x", y="y"))
    + geom_point(size=2.4)
    + stat_ellipse(level=0.95, linetype=2, colour="#E45756")
    + labs(title="stat_ellipse(level = 0.95)")
)
```

```python
from gg4py import aes, ggplot, labs, stat_qq, stat_qq_line, theme_minimal, to_column_table

DATA = {"value": [1.9, 2.4, 2.6, 3.0, 3.2, 3.7, 4.1, 4.8]}

p = (
    ggplot(to_column_table(DATA), aes(sample="value"))
    + stat_qq(size=2.4, colour="#4C78A8")
    + stat_qq_line(colour="#E45756")
    + labs(title="Q-Q plot", x="theoretical", y="sample")
    + theme_minimal()
)
```

## 4. 拟合

```python
from gg4py import aes, geom_point, geom_smooth, ggplot, labs, to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "y": [1.1, 2.4, 2.9, 3.2, 4.6, 4.9, 6.2, 6.0, 7.6, 8.4],
}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=2.4)
    + geom_smooth(method="loess", span=0.75, se=False, colour="#E45756", linewidth=1.2)
    + labs(title="stat_smooth(method = 'loess')", x="x", y="y")
)
```

`method="lm"` 走最小二乘，`method="loess"` 走局部回归（`span`）；`se=True` 时带
`ymin` / `ymax` 的置信带由 ribbon 画出。`stat_smooth(formula=...)` 只支持实现过的
形式，写不认识的公式会在构图期报错。

## 5. 汇总

`stat_summary()` 把每组压成一个（或几个）数：`fun` / `fun.min` / `fun.max` 可以是
字符串别名（`mean` `median` `sd` `var` `min` `max` `sum` `length` `first`
`last`）或任意 Python 可调用；`fun.data` 支持 `mean_se` / `mean_cl_normal` /
`mean_sdl` / `median_hilow`。默认 geom 是 `pointrange`。

```python
from gg4py import aes, geom_point, ggplot, labs, stat_summary, theme_minimal, to_column_table

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
    ggplot(data, aes(x="class", y="value"))
    + geom_point(size=1.8, alpha=0.45, colour="#4C78A8")
    + stat_summary(fun="mean", geom="point", size=5, colour="#E45756")
    + stat_summary(fun="median", geom="crossbar", width=0.5, linewidth=0.6)
    + labs(title="stat_summary: mean point + median crossbar", x="class", y="value")
    + theme_minimal()
)
```

`**{"fun.data": "mean_se"}` 这类带点的参数要用 `**{}` 传。

## 6. 2D 与空间

```python
from gg4py import aes, after_stat, ggplot, labs, stat_summary_2d, theme_minimal, to_column_table

DATA = {
    "x": [1, 1, 2, 2, 3, 3, 4, 4, 2, 3],
    "y": [1, 2, 1, 3, 2, 4, 3, 4, 2, 3],
    "z": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="x", y="y", z="z"))
    + stat_summary_2d(aes(fill=after_stat("value")), fun="mean", bins=3)
    + labs(title="stat_summary_2d(fun = 'mean')", x="x", y="y")
    + theme_minimal()
)
```

`stat_sf` 把几何压成 `xmin` / `xmax` / `ymin` / `ymax`（供 `geom_rect`），
`stat_sf_coordinates` 取代表点（供 `geom_sf_text` / `geom_sf_label`），见
[`sf.md`](sf.md)。

## 7. 边界

- `after_stat("列名")` 里的列名必须是该 stat 真产出的；写错在构图期报
  「没有这一列」，不会静默变成 NA。
- `stat_contour*` / `stat_density_2d*` 依赖 `contourpy`；桌面端由 pixi 提供，浏览器
  里必须写进脚本的 `needs`。
- `stat_spoke()`：上游 4.0.3 已 `deprecate_stop`，gg4py 同样抛错并指向
  `geom_spoke()`。
- loess 的口径（`surface="direct"` vs R 默认 `"interpolate"`）见
  `docs/notes/stat.md`；画出来的形状一致，残差在 1e-6 量级。
