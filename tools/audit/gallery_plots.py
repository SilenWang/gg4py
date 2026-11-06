"""r-graph-gallery 35 图人工核对（SIL-744 / M2-13）：逐张用 gg4py 复写。

这是 `docs/notes/gallery-audit.md` 的配套脚本：每一节对应审计表里的一行，
数据是就地生成的小型仿制集（mtcars / iris / gapminder / 月度序列），不读外部
文件，因此同一台机器上重跑结果一致。

用法（产物写入 `.gallery-audit/`，不入库）：

    pixi run audit:gallery
    pixi run audit:gallery fig01 fig07
    pixi run audit:gallery --list

四态（`VERDICTS`）与审计表一致：

- `ok`：画得出，视觉等价（可能要在写法上绕一下，注释里写明）；
- `diff`：画得出但差异明显（注释里写归因）；
- `out`：**不做**——第三方扩展包的布局 / 几何（patchwork / ggforce / ggstream /
  ggExtra / ggraph / treemapify 一类），按 2026-11-04 的决策只在文档里给本体等价写法；
- `missing`：画不出（缺本体能力；缺什么写在注释里）。

`out` / `missing` 的函数故意调用尚不存在的 API，运行器把真实报错收集进输出，
作为「确实没有」的证据；哪天同名能力真落地了，运行器会打 `STALE` 并判非 0。
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any

import numpy as np

from ggcore.arrow import arrow
from ggcore.map_data import map_frame
from ggcore.plot import (
    aes,
    coord_fixed,
    coord_flip,
    coord_polar,
    coord_sf,
    facet_grid,
    facet_wrap,
    geom_area,
    geom_bar,
    geom_boxplot,
    geom_col,
    geom_density,
    geom_density_2d,
    geom_hex,
    geom_histogram,
    geom_jitter,
    geom_label,
    geom_line,
    geom_point,
    geom_polygon,
    geom_rect,
    geom_ribbon,
    geom_segment,
    geom_smooth,
    geom_text,
    geom_tile,
    geom_violin,
    ggplot,
    guide_legend,
    guides,
    labs,
    position_dodge,
    position_stack,
    scale_colour_manual,
    scale_fill_brewer,
    scale_fill_gradient,
    scale_fill_gradient2,
    scale_fill_manual,
    scale_fill_viridis_c,
    scale_size_area,
    scale_x_continuous,
    scale_x_discrete,
    theme_bw,
    theme_classic,
    theme_minimal,
    theme_void,
)
from ggcore.theme import theme
from ggio.frame import from_dict, to_column_table

__all__ = ["FIGURES", "VERDICTS", "main"]


# ---------------------------------------------------------------------------
# 数据：小型仿制集（形状与 r-graph-gallery 各页一致，数值就地生成）
# ---------------------------------------------------------------------------


def _mtcars() -> Any:
    rng = np.random.default_rng(744)
    n = 32
    wt = np.round(rng.uniform(1.5, 5.4, n), 2)
    cyl = np.array(["4", "6", "8"])[rng.integers(0, 3, n)]
    mpg = np.round(37.0 - 5.1 * wt + rng.normal(0, 2.0, n), 1)
    hp = np.round(40 + 35 * (8 - wt) + rng.normal(0, 12, n))
    return from_dict({"wt": wt, "mpg": mpg, "cyl": cyl, "hp": hp})


def _bubble() -> Any:
    rng = np.random.default_rng(745)
    continent = np.repeat(["Africa", "Americas", "Asia", "Europe"], 10)
    gdp = np.exp(rng.normal(8.5, 1.1, 40))
    life = np.clip(40 + 7.0 * np.log10(gdp) + rng.normal(0, 4, 40), 35, 85)
    pop = np.exp(rng.normal(17.0, 1.4, 40))
    return from_dict({"gdp": gdp, "life": life, "pop": pop, "continent": continent})


def _corr_points() -> Any:
    """两个相关变量的散点（240 点），供平滑 / 2D 密度 / 六边形用。"""
    rng = np.random.default_rng(746)
    x = rng.normal(size=240)
    y = 0.8 * x + rng.normal(0, 0.6, 240)
    return from_dict({"x": x, "y": y})


def _labels() -> Any:
    """12 个国家的 GDP / 寿命，用于标签重叠检查。"""
    rng = np.random.default_rng(747)
    names = [
        "Cambodia",
        "Cameroon",
        "Canada",
        "Chile",
        "China",
        "Colombia",
        "Costa Rica",
        "Croatia",
        "Cuba",
        "Cyprus",
        "Czechia",
        "Denmark",
    ]
    gdp = np.exp(rng.normal(8.5, 0.25, 12))
    life = 55 + 5.0 * np.log10(gdp) + rng.normal(0, 1.0, 12)
    return from_dict({"country": names, "gdp": gdp, "life": life})


def _corr_matrix() -> Any:
    rng = np.random.default_rng(748)
    base = rng.normal(size=(80, 3))
    cols = {
        "alpha": base[:, 0] + rng.normal(0, 0.3, 80),
        "beta": base[:, 0] - base[:, 1] + rng.normal(0, 0.3, 80),
        "gamma": base[:, 1] + rng.normal(0, 0.3, 80),
        "delta": base[:, 2] + rng.normal(0, 0.3, 80),
        "epsilon": -base[:, 2] + rng.normal(0, 0.3, 80),
        "zeta": rng.normal(size=80),
    }
    names = list(cols)
    matrix = np.corrcoef(np.column_stack([cols[name] for name in names]))
    rows = []
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            rows.append((a, b, float(matrix[i, j])))
    return from_dict(
        {
            "var1": [row[0] for row in rows],
            "var2": [row[1] for row in rows],
            "r": [row[2] for row in rows],
            "abs_r": [abs(row[2]) for row in rows],
        }
    )


def _heatmap(n: int, seed: int) -> Any:
    rng = np.random.default_rng(seed)
    values = rng.normal(size=n * n).reshape(n, n)
    return from_dict(
        {
            "row": np.repeat(np.arange(n), n),
            "col": np.tile(np.arange(n), n),
            "z": values.ravel(),
        }
    )


def _bar_long() -> Any:
    return from_dict(
        {
            "part": np.repeat(["A", "B", "C"], 3),
            "group": np.tile(["g1", "g2", "g3"], 3),
            "value": [12.0, 8.0, 5.0, 9.0, 14.0, 4.0, 6.0, 7.0, 11.0],
        }
    )


def _categories() -> Any:
    names = ["K", "D", "A", "F", "B", "H", "C", "G", "E", "J", "I"]
    values = [42.0, 38.0, 35.0, 31.0, 26.0, 24.0, 19.0, 15.0, 11.0, 7.0, 3.0]
    return from_dict({"name": names, "value": values})


def _share() -> Any:
    return from_dict(
        {
            "part": ["A", "B", "C", "D", "E"],
            "value": [30.0, 24.0, 18.0, 16.0, 12.0],
        }
    )


def _circular() -> Any:
    names = [f"item {i:02d}" for i in range(1, 13)]
    rng = np.random.default_rng(749)
    values = np.round(rng.uniform(8, 40, 12), 1)
    angles = 90.0 - 360.0 * (np.arange(12) + 0.5) / 12
    return from_dict(
        {
            "name": names,
            "value": values,
            "label_angle": angles,
            "hjust": np.where(angles > 90, 1.0, 0.0),
        }
    )


def _iris() -> Any:
    rng = np.random.default_rng(750)
    species = np.repeat(["setosa", "versicolor", "virginica"], 50)
    petal = np.concatenate(
        [
            rng.normal(1.5, 0.2, 50),
            rng.normal(4.3, 0.4, 50),
            rng.normal(5.6, 0.5, 50),
        ]
    )
    sepal = np.concatenate(
        [
            rng.normal(5.0, 0.35, 50),
            rng.normal(5.9, 0.5, 50),
            rng.normal(6.6, 0.6, 50),
        ]
    )
    return from_dict({"species": species, "petal": petal, "sepal": sepal})


def _normal() -> Any:
    rng = np.random.default_rng(751)
    return from_dict({"value": rng.normal(0, 1, 300)})


def _two_density() -> Any:
    rng = np.random.default_rng(752)
    g1 = rng.normal(0, 1, 180)
    g2 = rng.normal(2.2, 1.2, 180)
    return from_dict(
        {
            "value": np.concatenate([g1, g2]),
            "group": np.repeat(["a", "b"], 180),
        }
    )


def _months(n: int = 24) -> list[dt.date]:
    start = dt.date(2020, 1, 1)
    return [
        dt.date(start.year + (start.month - 1 + i) // 12, (start.month - 1 + i) % 12 + 1, 1)
        for i in range(n)
    ]


def _timeseries() -> Any:
    rng = np.random.default_rng(753)
    trend = np.linspace(100, 160, 24)
    value = trend + rng.normal(0, 5, 24)
    return from_dict(
        {
            "date": _months(),
            "value": value,
            "lo": value - 8 - rng.uniform(0, 3, 24),
            "hi": value + 8 + rng.uniform(0, 3, 24),
        }
    )


def _stacked_area() -> Any:
    rng = np.random.default_rng(754)
    months = _months()
    rows = []
    for group, level in (("alpha", 60.0), ("beta", 40.0), ("gamma", 25.0)):
        for index, month in enumerate(months):
            rows.append((month, group, max(2.0, level + 0.5 * index + rng.normal(0, 4))))
    return from_dict(
        {
            "date": [row[0] for row in rows],
            "group": [row[1] for row in rows],
            "value": [row[2] for row in rows],
        }
    )


def _facets() -> Any:
    rng = np.random.default_rng(755)
    sites = ["north", "south", "east"]
    rows = []
    for site, level in zip(sites, (10.0, 40.0, 90.0), strict=True):
        for index, month in enumerate(_months()):
            rows.append((site, month, level + 0.4 * index * (1 + level / 60) + rng.normal(0, 3)))
    return from_dict(
        {
            "site": [row[0] for row in rows],
            "date": [row[1] for row in rows],
            "value": [row[2] for row in rows],
        }
    )


def _facet_grid_data() -> Any:
    rng = np.random.default_rng(756)
    regions = ["coast", "inland", "mountain"]
    years = ["2023", "2024"]
    rows = []
    for region, base in zip(regions, (30.0, 90.0, 6.0), strict=True):
        for year, factor in zip(years, (1.0, 1.4), strict=True):
            for quarter in ["Q1", "Q2", "Q3", "Q4"]:
                rows.append((region, year, quarter, base * factor + rng.normal(0, 3)))
    return from_dict(
        {
            "region": [row[0] for row in rows],
            "year": [row[1] for row in rows],
            "quarter": [row[2] for row in rows],
            "value": [row[3] for row in rows],
        }
    )


def _annotated() -> Any:
    return from_dict(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "y": [2.0, 4.1, 3.2, 5.4, 4.8, 6.2],
            "label": ["a", "b", "c", "d", "e", "f"],
        }
    )


def _multi_legend() -> Any:
    rng = np.random.default_rng(757)
    classes = ["compact", "midsize", "suv", "pickup"]
    return from_dict(
        {
            "x": rng.normal(size=40),
            "y": rng.normal(size=40),
            "class": np.array(classes)[rng.integers(0, 4, 40)],
            "hp": rng.uniform(60, 320, 40),
        }
    )


# ---------------------------------------------------------------------------
# 35 张图
# ---------------------------------------------------------------------------


def fig01_scatter_basic() -> Any:
    """r-graph-gallery「Scatter plot」：基础散点，按类别着色。"""
    return (
        ggplot(_mtcars(), aes(x="wt", y="mpg", colour="cyl"))
        + geom_point(size=3.0)
        + scale_colour_manual(values={"4": "#F8766D", "6": "#00BA38", "8": "#619CFF"})
        + labs(title="Weight vs. mileage", x="Weight (1000 lbs)", y="Miles per gallon")
        + theme_bw()
    )


def fig02_scatter_bubble() -> Any:
    """r-graph-gallery「Bubble chart」：size 映射人口，colour 映射大洲。"""
    return (
        ggplot(_bubble(), aes(x="gdp", y="life", size="pop", colour="continent"))
        + geom_point(alpha=0.7)
        + scale_size_area(max_size=14)
        + scale_colour_manual(
            values={
                "Africa": "#E41A1C",
                "Americas": "#377EB8",
                "Asia": "#4DAF4A",
                "Europe": "#984EA3",
            }
        )
        + labs(title="Bubble chart", x="GDP per capita", y="Life expectancy")
        + theme_minimal()
    )


def fig03_scatter_smooth() -> Any:
    """r-graph-gallery「Scatter plot with smooth」：线性拟合 + 置信带。"""
    return (
        ggplot(_corr_points(), aes(x="x", y="y"))
        + geom_point(alpha=0.5, size=1.6)
        + geom_smooth(method="lm")
        + labs(title="Linear trend", x="x", y="y")
        + theme_minimal()
    )


def fig04_scatter_density_2d() -> Any:
    """r-graph-gallery「2D density plot」：等高线叠在散点上。"""
    return (
        ggplot(_corr_points(), aes(x="x", y="y"))
        + geom_point(alpha=0.35, size=1.2)
        + geom_density_2d(colour="#D73027", linewidth=0.7)
        + labs(title="2D density contours", x="x", y="y")
        + theme_bw()
    )


def fig05_scatter_hexbin() -> Any:
    """r-graph-gallery「Hexbin chart」：六边形分箱。"""
    return (
        ggplot(_corr_points(), aes(x="x", y="y"))
        + geom_hex(bins=12)
        + scale_fill_gradient(low="#F7FBFF", high="#08519C")
        + labs(title="Hexbin", x="x", y="y", fill="count")
        + theme_minimal()
    )


def fig06_scatter_repel() -> Any:
    """r-graph-gallery「Avoid overlapping labels (ggrepel)」：差异 = 无避让。"""
    return (
        ggplot(_labels(), aes(x="gdp", y="life"))
        + geom_point(size=2.2)
        + geom_text(aes(label="country"), size=3.2, vjust=-0.6)
        + labs(title="Labels without repel", x="GDP per capita", y="Life expectancy")
        + theme_bw()
    )


def fig07_correlogram() -> Any:
    """r-graph-gallery「Correlogram」：相关系数圆矩阵（手工 size 映射）。"""
    return (
        ggplot(_corr_matrix(), aes(x="var1", y="var2"))
        + geom_tile(fill="white", colour="grey85")
        + geom_point(aes(size="abs_r", fill="r"), shape=21, colour="grey30")
        + geom_text(aes(label="round(r, 2)"), size=2.4)
        + scale_fill_gradient2(low="#2166AC", mid="white", high="#B2182B", midpoint=0.0)
        + scale_size_area(max_size=10)
        + coord_fixed()
        + labs(title="Correlogram", x="", y="", fill="r", size="|r|")
        + theme_minimal()
    )


def fig08_heatmap_tile() -> Any:
    """r-graph-gallery「Heatmap」：矩形热图 + 连续色阶。"""
    return (
        ggplot(_heatmap(10, 758), aes(x="col", y="row", fill="z"))
        + geom_tile()
        + scale_fill_viridis_c()
        + coord_fixed()
        + labs(title="Heatmap", x="column", y="row")
        + theme_minimal()
    )


def fig09_heatmap_values() -> Any:
    """r-graph-gallery「Heatmap with values」：格子里写数值。"""
    data = _heatmap(5, 759)
    return (
        ggplot(data, aes(x="col", y="row", fill="z"))
        + geom_tile(colour="white")
        + geom_text(aes(label="round(z, 1)"), size=3.0)
        + scale_fill_gradient2(low="#4575B4", mid="white", high="#D73027")
        + coord_fixed()
        + labs(title="Heatmap with values", x="", y="")
        + theme_minimal()
    )


def fig10_heatmap_dendrogram() -> Any:
    """r-graph-gallery「Heatmap with dendrogram」：缺聚类 + 树 + 并置。"""
    from ggcore.plot import geom_dendrogram

    return geom_dendrogram()


def fig11_bar_basic() -> Any:
    """r-graph-gallery「Barplot」：按类别计数。"""
    data = from_dict(
        {"class": np.array(["a", "b", "c", "d"])[[0, 1, 1, 2, 2, 2, 3, 3, 3, 3, 0, 1]]}
    )
    return (
        ggplot(data, aes(x="class"))
        + geom_bar(fill="#4E79A7")
        + labs(title="Counts by class", x="class", y="count")
        + theme_classic()
    )


def fig12_bar_grouped() -> Any:
    """r-graph-gallery「Grouped barplot」：position_dodge。"""
    return (
        ggplot(_bar_long(), aes(x="part", y="value", fill="group"))
        + geom_col(position=position_dodge(width=0.85), width=0.75)
        + scale_fill_brewer()
        + labs(title="Grouped bars", x="part", y="value")
        + theme_minimal()
    )


def fig13_bar_stacked_labels() -> Any:
    """r-graph-gallery「Stacked barplot」：段内居中标签。"""
    return (
        ggplot(_bar_long(), aes(x="part", y="value", fill="group"))
        + geom_col(width=0.7)
        + geom_text(aes(label="value"), position=position_stack(vjust=0.5), size=3.0)
        + scale_fill_brewer()
        + labs(title="Stacked bars", x="part", y="value")
        + theme_minimal()
    )


def fig14_bar_horizontal_sorted() -> Any:
    """r-graph-gallery「Horizontal barplot」：按值排序 + coord_flip。"""
    data = _categories()
    order = ["I", "J", "E", "G", "C", "H", "B", "F", "A", "D", "K"]
    return (
        ggplot(data, aes(x="name", y="value"))
        + geom_col(fill="#59A14F", width=0.75)
        + scale_x_discrete(limits=order)
        + coord_flip()
        + labs(title="Ranked bars", x="", y="value")
        + theme_minimal()
    )


def fig15_lollipop() -> Any:
    """r-graph-gallery「Lollipop chart」：segment + point，排序后横向。"""
    data = _categories()
    order = ["I", "J", "E", "G", "C", "H", "B", "F", "A", "D", "K"]
    return (
        ggplot(data, aes(x="name", y="value"))
        + geom_segment(aes(x="name", xend="name", y=0, yend="value"), colour="grey55")
        + geom_point(size=2.6, colour="#E15759")
        + scale_x_discrete(limits=order)
        + coord_flip()
        + labs(title="Lollipop", x="", y="value")
        + theme_minimal()
    )


def fig16_pie() -> Any:
    """r-graph-gallery「Pie chart」：视觉等价；R 的 x = "" 要改写成常数 1。"""
    data = _share()
    return (
        ggplot(data, aes(x=1, y="value", fill="part"))
        + geom_col(width=1, colour="white")
        + geom_text(aes(label="value"), position=position_stack(vjust=0.5), size=3.0)
        + coord_polar(theta="y")
        + scale_fill_brewer()
        + labs(title="Pie chart")
        + theme_void()
    )


def fig17_donut() -> Any:
    """r-graph-gallery「Donut chart」：x = 2、width = 1 + xlim(0.5, 2.5) 挖出内圈。"""
    data = _share()
    return (
        ggplot(data, aes(x=2, y="value", fill="part"))
        + geom_col(width=1, colour="white")
        + geom_text(aes(label="value"), position=position_stack(vjust=0.5), size=3.0)
        + coord_polar(theta="y")
        + scale_x_continuous(limits=(0.5, 2.5))
        + scale_fill_brewer()
        + labs(title="Donut chart")
        + theme_void()
    )


def fig18_circular_barplot() -> Any:
    """r-graph-gallery「Circular barplot」：角度 / hjust 在数据里算（教程同样如此）。"""
    data = _circular()
    return (
        ggplot(data, aes(x="name", y="value", fill="value"))
        + geom_col(width=0.9)
        + geom_text(
            aes(y="value", label="value", angle="label_angle", hjust="hjust"),
            nudge_y=1.8,
            size=2.8,
        )
        + coord_polar(theta="x", start=-np.pi / 2)
        + scale_fill_gradient(low="#FEE0D2", high="#CB181D")
        + labs(title="Circular barplot", x="", y="")
        + theme_void()
    )


def fig19_boxplot_basic() -> Any:
    """r-graph-gallery「Boxplot」：分组箱线图。"""
    return (
        ggplot(_mtcars(), aes(x="cyl", y="mpg", fill="cyl"))
        + geom_boxplot(width=0.6)
        + scale_fill_manual(values={"4": "#8DD3C7", "6": "#FFFFB3", "8": "#BEBADA"})
        + labs(title="Boxplot", x="cylinders", y="mpg")
        + theme_minimal()
    )


def fig20_boxplot_jitter() -> Any:
    """r-graph-gallery「Boxplot with observations」：箱线图 + 抖动点。"""
    return (
        ggplot(_iris(), aes(x="species", y="petal", fill="species"))
        + geom_boxplot(width=0.45, alpha=0.45)
        + geom_jitter(width=0.12, size=1.2, alpha=0.6)
        + scale_fill_brewer()
        + labs(title="Boxplot with observations", x="", y="petal length")
        + theme_bw()
    )


def fig21_violin() -> Any:
    """r-graph-gallery「Violin plot」：小提琴 + 内嵌箱线。"""
    return (
        ggplot(_iris(), aes(x="species", y="petal", fill="species"))
        + geom_violin(alpha=0.55, trim=False)
        + geom_boxplot(width=0.12, fill="white")
        + scale_fill_brewer()
        + labs(title="Violin plot", x="", y="petal length")
        + theme_minimal()
    )


def fig22_violin_split() -> Any:
    """r-graph-gallery「Split violin」：缺对照两组的半小提琴几何。"""
    from ggcore.plot import geom_split_violin

    return geom_split_violin()


def fig23_histogram() -> Any:
    """r-graph-gallery「Histogram」：分箱直方图。"""
    return (
        ggplot(_normal(), aes(x="value"))
        + geom_histogram(bins=30, fill="#69B3A2", colour="white")
        + labs(title="Histogram", x="value", y="count")
        + theme_minimal()
    )


def fig24_density_groups() -> Any:
    """r-graph-gallery「Density plot」：多组半透明密度曲线。"""
    return (
        ggplot(_two_density(), aes(x="value", fill="group"))
        + geom_density(alpha=0.45, colour=None)
        + scale_fill_manual(values={"a": "#F8766D", "b": "#00BFC4"})
        + labs(title="Density plot", x="value", y="density")
        + theme_minimal()
    )


def fig25_timeseries_ribbon() -> Any:
    """r-graph-gallery「Time series」：折线 + 置信带。"""
    return (
        ggplot(_timeseries(), aes(x="date", y="value"))
        + geom_ribbon(aes(ymin="lo", ymax="hi"), fill="#A6CEE3", alpha=0.6)
        + geom_line(colour="#1F78B4", linewidth=0.9)
        + geom_point(size=1.8, colour="#1F78B4")
        + labs(title="Monthly series", x="", y="value")
        + theme_minimal()
    )


def fig26_stacked_area() -> Any:
    """r-graph-gallery「Stacked area chart」：geom_area 堆叠。"""
    return (
        ggplot(_stacked_area(), aes(x="date", y="value", fill="group"))
        + geom_area(alpha=0.75)
        + scale_fill_brewer()
        + labs(title="Stacked area", x="", y="value")
        + theme_minimal()
    )


def fig27_streamgraph() -> Any:
    """r-graph-gallery「Streamgraph」：缺 stream 的对称堆叠几何。"""
    from ggcore.plot import geom_stream

    return geom_stream()


def fig28_facet_wrap_free() -> Any:
    """r-graph-gallery「Facet wrap」：free_y 的多面板。"""
    return (
        ggplot(_facets(), aes(x="date", y="value"))
        + geom_line(colour="#377EB8")
        + geom_point(size=1.4)
        + facet_wrap("site", ncol=2, scales="free_y")
        + labs(title="Facet wrap", x="", y="value")
        + theme_bw()
    )


def fig29_facet_grid_space_free() -> Any:
    """r-graph-gallery「Facet grid with free space」：space = free_y。"""
    return (
        ggplot(_facet_grid_data(), aes(x="quarter", y="value", fill="region"))
        + geom_col(width=0.7)
        + facet_grid(rows="region", cols="year", scales="free_y", space="free_y")
        + labs(title="Facet grid", x="", y="value")
        + theme_minimal()
    )


def fig30_annotation_text_arrow() -> Any:
    """r-graph-gallery「Annotation」：视觉等价；无 annotate()，每个标注一个常量图层。"""
    data = _annotated()
    return (
        ggplot(data, aes(x="x", y="y"))
        + geom_rect(
            aes(xmin=3.6, xmax=5.4, ymin=4.4, ymax=6.6),
            fill="#FDD0A2",
            alpha=0.5,
            inherit_aes=False,
        )
        + geom_point(size=2.6)
        + geom_text(aes(label="label"), vjust=-0.8, size=3.4)
        + geom_segment(
            aes(x=2.0, y=3.2, xend=3.0, yend=4.6),
            arrow=arrow(length=8.0),
            colour="#D94801",
            linewidth=0.8,
        )
        + geom_label(
            aes(x=6.0, y=6.2, label="'peak'"),
            fill="white",
            size=3.2,
            inherit_aes=False,
        )
        + labs(title="Annotated plot", x="x", y="y")
        + theme_bw()
    )


def fig31_multi_legend_inside() -> Any:
    """r-graph-gallery「Legend position」：合并图例 + 第二个图例放面板内。"""
    return (
        ggplot(_multi_legend(), aes(x="x", y="y", colour="class", shape="class", size="hp"))
        + geom_point(alpha=0.8)
        + guides(
            colour=guide_legend(position="inside", title="class / hp"),
            shape=guide_legend(position="inside", title="class / hp"),
            size=guide_legend(position="inside", title="class / hp"),
        )
        + theme(
            **{
                "legend.position": "inside",
                "legend.position.inside": (0.80, 0.78),
                "legend.justification.inside": (0.5, 0.5),
            }
        )
        + labs(title="Legends inside the panel")
        + theme_minimal()
    )


def fig32_marginal_scatter() -> Any:
    """r-graph-gallery「Scatter with marginal distribution」：不做（ggExtra / patchwork 版面组合）。

    本体不做多图版面组合（2026-11-04 决策），等价写法是主图 + 另出一张边缘分布图：
    主图 `geom_point()` + `geom_smooth()`，边缘用 `geom_histogram()` 或
    `geom_density()` 单独出一张（两张图并列放在文档里，或前端排版，不拼 gtable）。
    """
    from ggcore.plot import ggExtraMarginal

    return ggExtraMarginal()


def fig33_choropleth_map() -> Any:
    """r-graph-gallery「Choropleth map」：usa 多边形按区域填色，走 coord_sf 的 EPSG:3857。

    R 侧通常写 `coord_sf(crs = 3857)` 或 PROJ 的其它投影；本仓只内置 4 个 CRS
    （4326 / CRS84 / 3857 / 3347，见 `docs/notes/sf.md`），这里取 3857——同一张分级
    地图的墨卡托版本，不引入 PROJ。数值按区域就地生成，验的是「多边形 + 投影 +
    连续填充 + 图例」这条路径。
    """
    frame = map_frame("usa", ".")
    groups = sorted(set(frame["group"]))
    values = {group: 1.0 + (index * 1.7) % 5.0 for index, group in enumerate(groups)}
    data = to_column_table(
        {
            "x": frame["x"],
            "y": frame["y"],
            "group": [str(group) for group in frame["group"]],
            "value": [values[group] for group in frame["group"]],
        }
    )
    return (
        ggplot(data, aes(x="x", y="y", group="group", fill="value"))
        + geom_polygon(colour="grey40", linewidth=0.2)
        + scale_fill_gradient(low="#f7fbff", high="#08306b", name="指数")
        + coord_sf(crs="EPSG:3857")
        + labs(title="Choropleth (EPSG:3857)")
        + theme_void()
    )


def fig34_network_graph() -> Any:
    """r-graph-gallery「Network graph」：不做（ggraph 布局），节点坐标自己算后画线段。

    等价写法：按圆形 / 层次布局自己算节点坐标，节点 `geom_point()`、
    标签 `geom_text()`、边 `geom_segment()`（或 `geom_curve()` 加弧）——
    力导向布局本身是图算法，不在本体范围内。
    """
    from ggcore.plot import geom_edge_link

    return geom_edge_link()


def fig35_treemap() -> Any:
    """r-graph-gallery「Treemap」：不做（treemapify 的 squarify 布局）。

    等价写法：占比用堆叠条 / 分组柱表达；要矩形版式就自己算矩形坐标，
    用 `geom_rect(aes(xmin, xmax, ymin, ymax, fill))` 画（层级标签自己算位置）。
    """
    from ggcore.plot import geom_treemap

    return geom_treemap()


# ---------------------------------------------------------------------------
# 登记表
# ---------------------------------------------------------------------------

FIGURES: dict[str, Any] = {
    "fig01": fig01_scatter_basic,
    "fig02": fig02_scatter_bubble,
    "fig03": fig03_scatter_smooth,
    "fig04": fig04_scatter_density_2d,
    "fig05": fig05_scatter_hexbin,
    "fig06": fig06_scatter_repel,
    "fig07": fig07_correlogram,
    "fig08": fig08_heatmap_tile,
    "fig09": fig09_heatmap_values,
    "fig10": fig10_heatmap_dendrogram,
    "fig11": fig11_bar_basic,
    "fig12": fig12_bar_grouped,
    "fig13": fig13_bar_stacked_labels,
    "fig14": fig14_bar_horizontal_sorted,
    "fig15": fig15_lollipop,
    "fig16": fig16_pie,
    "fig17": fig17_donut,
    "fig18": fig18_circular_barplot,
    "fig19": fig19_boxplot_basic,
    "fig20": fig20_boxplot_jitter,
    "fig21": fig21_violin,
    "fig22": fig22_violin_split,
    "fig23": fig23_histogram,
    "fig24": fig24_density_groups,
    "fig25": fig25_timeseries_ribbon,
    "fig26": fig26_stacked_area,
    "fig27": fig27_streamgraph,
    "fig28": fig28_facet_wrap_free,
    "fig29": fig29_facet_grid_space_free,
    "fig30": fig30_annotation_text_arrow,
    "fig31": fig31_multi_legend_inside,
    "fig32": fig32_marginal_scatter,
    "fig33": fig33_choropleth_map,
    "fig34": fig34_network_graph,
    "fig35": fig35_treemap,
}

#: 四态。`missing` / `out` 的函数必须失败（没有同名 API 就是证据）；`ok` / `diff` 必须成功。
#: - `out`：按 2026-11-04 的决策**不做**（第三方扩展包的布局 / 几何），只在文档里给
#:   本体等价写法——函数仍保留，用来钉住「我们确实没实现这个同名 API」。
VERDICTS: dict[str, str] = {
    "fig01": "ok",
    "fig02": "ok",
    "fig03": "ok",
    "fig04": "ok",
    "fig05": "ok",
    "fig06": "diff",
    "fig07": "diff",
    "fig08": "ok",
    "fig09": "ok",
    "fig10": "out",
    "fig11": "ok",
    "fig12": "ok",
    "fig13": "ok",
    "fig14": "ok",
    "fig15": "ok",
    "fig16": "ok",
    "fig17": "ok",
    "fig18": "ok",
    "fig19": "ok",
    "fig20": "ok",
    "fig21": "ok",
    "fig22": "out",
    "fig23": "ok",
    "fig24": "ok",
    "fig25": "ok",
    "fig26": "ok",
    "fig27": "out",
    "fig28": "ok",
    "fig29": "ok",
    "fig30": "ok",
    "fig31": "ok",
    "fig32": "out",
    "fig33": "ok",
    "fig34": "out",
    "fig35": "out",
}


# ---------------------------------------------------------------------------
# 运行器
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="fig01 ...（缺省全部）")
    parser.add_argument("--out", default=".gallery-audit", help="产物目录（不入库）")
    parser.add_argument("--list", action="store_true", help="只列出登记项")
    args = parser.parse_args(argv)

    if args.list:
        for name, fn in FIGURES.items():
            print(f"{name}  {VERDICTS[name]:7s}  {fn.__doc__.splitlines()[0]}")
        return 0

    names = args.names or list(FIGURES)
    unknown = [name for name in names if name not in FIGURES]
    if unknown:
        parser.error(f"未知的图号：{', '.join(unknown)}")

    try:
        import ggskia  # noqa: F401  (注册设备后端)
        from ggcore.io import ggsave
    except ImportError as exc:  # pragma: no cover - 运行期依赖
        print(f"需要 ggskia：{exc}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failures = 0
    for name in names:
        fn = FIGURES[name]
        expected = VERDICTS[name]
        try:
            plot = fn()
            if expected in ("missing", "out"):
                # 不做 / 画不出的函数如果**成功**了，说明能力已经补上，审计表要更新。
                # 只构造对象还不够（coord_sf 的投影校验在构建期），所以真构建一次。
                from ggcore.build import build_plot

                build_plot(plot)
                print(f"STALE {name}  已能构建，但审计表记为 {expected}")
                failures += 1
                continue
            result = ggsave(plot, out / f"{name}.svg", width=6, height=4)
            print(f"OK    {name}  {expected:5s}  {result.bytes:8d} bytes")
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}".splitlines()[0]
            if expected == "missing":
                print(f"MISS  {name}  {detail}")
            elif expected == "out":
                # 第三方扩展：确认我们没有同名 API（报错就是证据），不算失败。
                print(f"OUT   {name}  {detail}")
            else:
                failures += 1
                print(f"FAIL  {name}  {detail}")
    print(f"\n{len(names) - failures}/{len(names)} 符合登记")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
