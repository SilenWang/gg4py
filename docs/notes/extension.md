# 扩展 API：写一个组件类，不碰布局

gg4py 的组件基类在 `ggcore.layer`（`Geom` / `Stat` / `Position`）与
`ggcore.components`（`Scale` / `Coord` / `Guide` / `Theme`）。自定义组件就是
**一个 Python 子类**：

- 用类属性声明契约（`required_aes` / `default_aes`）；
- 覆写执行钩子（`Geom.draw()`、`Stat.compute_panel()`、`Position.compute_layer()`、
  `Scale.build_scale()`、`Coord.build_coord()`、`Guide.build_guide()`）；
- 用 `register_*()` 登记。

注册表仍然只有一条：`register_geom("mysegment", GeomMySegment)` 同时生成
`ggcore.registry.geom_mysegment()`、`ggcore.plot.geom_mysegment()` 与
`ggplot.geom_mysegment()` 三个入口。它们都在调用时回注册表查找，所以替换 /
注销立刻生效。

第三方登记默认**不能覆盖内置名字**（例如 `register_geom("point", ...)` 会报错）。
确实要做对照实验时传 `allow_override=True`；`unregister()` 会把内置原件恢复。
自定义名字的重复登记是替换（保持第一次出现的位置），`unregister()` 后两个入口
一起消失。

## 最小自定义 geom

只需要一个类、一个 `draw()`。返回值是普通的 grid grob（下面返回
`segmentsGrob`），场景装配会把它放进面板的 `panel-clip`；坐标变换、分面、
图例、gtable 尺寸都不需要自己写。

<!-- extension-example: geom -->
```python
from typing import Any, ClassVar

from ggcore import ir, plot, registry
from ggcore.geom.base import (
    POINT_PER_MM,
    alpha_colour,
    npc_values,
    table_numeric,
    table_strings,
)
from ggcore.geom.scene import scene_from_plot
from ggcore.grobs import g_tree, null_grob, segments_grob
from ggcore.layer import Geom
from ggcore.units import unit
from ggio.frame import to_column_table


class GeomMySegment(Geom):
    required_aes = ("x", "y", "xend", "yend")
    default_aes: ClassVar[dict[str, Any]] = {
        "colour": "#4C78A8",
        "linewidth": 0.8,
        "alpha": None,
    }

    def draw(self, build, panel, coord, theme, metrics):
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_mysegment")
        x0 = npc_values(panel, data, "x", "x")
        y0 = npc_values(panel, data, "y", "y")
        x1 = npc_values(panel, data, "xend", "x")
        y1 = npc_values(panel, data, "yend", "y")
        colours = table_strings(data, "colour")
        alpha = table_numeric(data, "alpha", default=float("nan"))
        width = table_numeric(data, "linewidth", default=0.8)
        return g_tree(
            segments_grob(
                unit(x0.tolist(), "native"),
                unit(y0.tolist(), "native"),
                unit(x1.tolist(), "native"),
                unit(y1.tolist(), "native"),
                default_units="native",
                gp={
                    "col": [alpha_colour(c, a) for c, a in zip(colours, alpha, strict=True)],
                    "lwd": (width * POINT_PER_MM).tolist(),
                    "lineend": "butt",
                },
                name="mysegment",
            ),
            name="geom_mysegment",
        )


registry.register_geom("mysegment", GeomMySegment)
data = to_column_table(
    {
        "x": [0.10, 0.45],
        "y": [0.20, 0.65],
        "xend": [0.55, 0.90],
        "yend": [0.80, 0.30],
    }
)
p = (
    plot.ggplot(data, plot.aes(x="x", y="y", xend="xend", yend="yend"))
    + registry.geom_mysegment()
    + plot.scale_x_continuous(limits=(0, 1), expand=(0, 0))
    + plot.scale_y_continuous(limits=(0, 1), expand=(0, 0))
    + plot.theme_void()
)
scene = scene_from_plot(p, width_in=4, height_in=3)
kinds = [node.kind.value for node in ir.walk(scene.root)]
assert "segments" in kinds
assert kinds.count("viewport") >= 2  # 页面 + panel-clip
registry.unregister("geom", "mysegment")
```

同一个类也能直接进案例库：`docs/cases/ext-custom-geom/plot.py` 就是这段代码
（数据换成 6 条线段），参考图由 R 的等价 `geom_segment()` 生成，CPython 与
浏览器查看器两条路径都跑它。

## 自定义 stat + scale

`Stat` 子类覆写 `compute_panel(data, scales=None)`；返回一张
`ggcore.data.ColumnTable`。`Scale` 子类覆写 `build_scale()`，返回
`ggcore.scales.ScaleBase` 的实现。下面按组求均值，并用一个二值颜色标度把
均值以上/以下映射成深浅两色。

<!-- extension-example: stat-scale -->
```python
import numpy as np

from ggcore import plot, registry
from ggcore.build import build_plot
from ggcore.components import Scale
from ggcore.data import Column, ColumnTable
from ggcore.layer import Stat
from ggcore.scales import ContinuousScale
from ggio.frame import to_column_table


class StatGroupMean(Stat):
    required_aes = ("x", "y")
    geom = "point"

    def compute_panel(self, data, scales=None):
        x = np.asarray(data.column("x").values, dtype=float)
        y = np.asarray(data.column("y").values, dtype=float)
        groups = (
            [str(value) for value in data.column("group").values.tolist()]
            if "group" in data
            else ["1"] * data.nrows
        )
        levels = list(dict.fromkeys(groups))
        keys = np.array(groups)
        return ColumnTable(
            [
                ("x", Column("float", np.array([x[keys == g].mean() for g in levels]))),
                ("y", Column("float", np.array([y[keys == g].mean() for g in levels]))),
                ("group", Column("int", np.arange(1, len(levels) + 1))),
            ],
            nrows=len(levels),
        )


class BinaryColourScale(ContinuousScale):
    def map(self, column):
        rescaled, missing = self._rescaled(column)
        values = [
            "grey50" if skipped else ("#2166AC" if value >= 0.5 else "#D1E5F0")
            for value, skipped in zip(rescaled.tolist(), missing.tolist(), strict=True)
        ]
        return Column("str", np.array(values, dtype=object))


class ScaleColourBinary(Scale):
    aesthetic = "colour"

    def build_scale(self):
        return BinaryColourScale(self.aesthetic, dict(self.params))


registry.register_stat("group_mean", StatGroupMean)
registry.register_scale("colour_binary", ScaleColourBinary)

data = to_column_table(
    {"x": [0, 1, 2, 3, 4, 5], "y": [1, 3, 2, 8, 6, 7], "g": ["a", "a", "a", "b", "b", "b"]}
)
mean_plot = plot.ggplot(data, plot.aes(x="x", y="y", group="g")) + registry.stat_group_mean()
mean_data = build_plot(mean_plot).layers[0].data
assert mean_data.column("x").values.tolist() == [1.0, 4.0]
assert mean_data.column("y").values.tolist() == [2.0, 7.0]

colour_plot = (
    plot.ggplot(data, plot.aes(x="x", y="y", colour="x"))
    + plot.geom_point()
    + registry.scale_colour_binary()
)
colours = build_plot(colour_plot).layers[0].data.column("colour").values
assert colours.tolist()[:3] == ["#D1E5F0"] * 3
assert colours.tolist()[-3:] == ["#2166AC"] * 3

registry.unregister("stat", "group_mean")
registry.unregister("scale", "colour_binary")
```

## 自定义 guide

`Guide` 子类覆写 `build_guide()`，返回 `ggcore.guide` 的运行时 guide。运行时
guide 若实现 `draw_keys(guide_build, theme, layout, *, metrics, name)`，图例的
key 区就交给它画；标题、背景、布局仍由现有 guide 体系负责。下面的
`GuideStar` 用实心圆 + 标签替掉默认的几何 key。

<!-- extension-example: guide -->
```python
from dataclasses import dataclass

from ggcore import plot, registry
from ggcore.axis import font_int, paint
from ggcore.build import build_plot
from ggcore.components import Guide
from ggcore.grobs import points_grob, text_grob
from ggcore.guide import AUTO, GuideLegend, build_guides, legend_grob, legend_layout
from ggcore.theme import ElementText, resolve_theme
from ggcore.units import unit
from ggcore.viewport import gpar
from ggio.frame import to_column_table


@dataclass(frozen=True)
class GuideStar(GuideLegend):
    kind: str = "star"

    def draw_keys(self, guide_build, theme, layout, *, metrics=None, name="guide"):
        element = theme.get("legend.text")
        if not isinstance(element, ElementText):
            return []
        text_gp = gpar(
            col=paint(element.colour) or "black",
            fontsize=float(element.size or 8.8),
            fontfamily=element.family or "",
            font=font_int(element.face),
            lineheight=float(element.lineheight or 1.2),
        )
        grobs = []
        for index, cell in enumerate(layout.keys):
            colour = cell.key.values.get("colour") or "black"
            grobs.append(
                points_grob(
                    unit(cell.box.x_cm + cell.box.width_cm / 2, "cm"),
                    unit(cell.box.y_cm + cell.box.height_cm / 2, "cm"),
                    pch=19,
                    size=unit(4, "pt"),
                    default_units="cm",
                    gp=gpar(col=colour),
                    name=f"{name}.star-{index}",
                )
            )
            grobs.append(
                text_grob(
                    cell.key.label,
                    cell.label_box.x_cm,
                    cell.label_box.y_cm + cell.label_box.height_cm / 2,
                    hjust=0.0,
                    vjust=0.5,
                    default_units="cm",
                    gp=text_gp,
                    name=f"{name}.label-{index}",
                )
            )
        return grobs


class GuideStarSpec(Guide):
    def build_guide(self):
        return GuideStar(
            title=self.params.get("title", AUTO),
            direction=self.params.get("direction"),
        )


registry.register_guide("star", GuideStarSpec)
data = to_column_table({"x": [1, 2, 3], "y": [1, 2, 3], "g": ["a", "b", "c"]})
p = (
    plot.ggplot(data, plot.aes(x="x", y="y", colour="g"))
    + plot.geom_point()
    + registry.guide_star(aesthetic="colour")
)
build = build_plot(p)
theme = resolve_theme(build.theme)
guides = build_guides(build)
assert len(guides) == 1 and guides[0].guide.kind == "star"
layout = legend_layout(guides[0], theme)
grobs = legend_grob(guides[0], build, theme, layout)
assert any(getattr(grob, "name", "").startswith("guide.star-") for grob in grobs)
registry.unregister("guide", "star")
```

## 七个基类的钩子

| 基类 | 声明 / 覆写 | 注册入口 |
| --- | --- | --- |
| `ggcore.layer.Geom` | `required_aes`、`default_aes`、`draw()`，可选 `setup_params()` / `setup_data()` / `handle_na()` | `register_geom()` |
| `ggcore.layer.Stat` | `required_aes`、`non_missing_aes`、`geom`、`compute_panel()` | `register_stat()` |
| `ggcore.layer.Position` | `compute_layer()`；面板级实现可继承 `ggcore.position.PanelPosition` 只写 `setup_params()` / `setup_data()` / `compute_panel()` | `register_position()` |
| `ggcore.components.Scale` | `aesthetic`、`build_scale()`（返回 `ScaleBase`） | `register_scale()` |
| `ggcore.components.Coord` | `build_coord()`（返回 `CoordBase`） | `register_coord()` |
| `ggcore.components.Guide` | `build_guide()`（返回 `ggcore.guide.Guide`） | `register_guide()` |
| `ggcore.components.Theme` | `elements` / `complete` / `base_size`（子类同时自动继承 `ggcore.theme` 的解析） | `register_theme()` |

`Geom.default_aes` 在子类里是**合并**语义：子类只写差异项，父类的键保留；
父类那本字典不会被修改。

这三段代码由 `tests/test_extension.py` 从本文件抽取执行（CI 的一部分），
不是只给人看的片段。
