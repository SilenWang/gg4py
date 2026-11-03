"""extension：只实现一个 Geom 子类就出图（不写布局代码）。

`GeomMySegment` 只声明 `required_aes` / `default_aes` 并覆写 `draw()`；它返回
普通的 grid grob（线段），由 `ggcore.geom.scene` 放进 panel clip。布局、gtable、
坐标、标度都不需要自定义。

R 参考用等价的 `geom_segment()`（同一份数据、颜色、线宽与 limits），见
`tools/refs/cases_battery_ref.R` 的 extension 段。
"""

from __future__ import annotations

from typing import Any, ClassVar

from ggcore import registry
from ggcore.geom.base import (
    POINT_PER_MM,
    alpha_colour,
    npc_values,
    table_numeric,
    table_strings,
)
from ggcore.grobs import g_tree, null_grob, segments_grob
from ggcore.layer import Geom
from ggcore.plot import (
    aes,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.registry import register_geom
from ggcore.theme import theme
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {
    "x": [0.08, 0.18, 0.28, 0.42, 0.56, 0.70],
    "y": [0.20, 0.72, 0.42, 0.86, 0.16, 0.60],
    "xend": [0.24, 0.34, 0.48, 0.66, 0.76, 0.92],
    "yend": [0.78, 0.28, 0.64, 0.20, 0.58, 0.88],
}

SIZE = [4, 3]
COLOUR = "#4C78A8"
LINEWIDTH = 0.8


class GeomMySegment(Geom):
    """最小自定义 geom：把 (x, y) → (xend, yend) 画成线段。

    只实现一个类；没有布局 / gtable / 面板裁剪代码——这些由现有流水线负责。
    """

    name = "mysegment"
    required_aes = ("x", "y", "xend", "yend")
    default_aes: ClassVar[dict[str, Any]] = {
        "colour": COLOUR,
        "linewidth": LINEWIDTH,
        "alpha": None,
    }
    non_missing_aes = ("colour", "linewidth")

    def draw(self, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_mysegment")
        x0 = npc_values(panel, data, "x", "x")
        y0 = npc_values(panel, data, "y", "y")
        x1 = npc_values(panel, data, "xend", "x")
        y1 = npc_values(panel, data, "yend", "y")
        colours = table_strings(data, "colour")
        alpha = table_numeric(data, "alpha", default=float("nan"))
        width = table_numeric(data, "linewidth", default=LINEWIDTH)
        gp = {
            "col": [
                alpha_colour(colour, value) for colour, value in zip(colours, alpha, strict=True)
            ],
            "lwd": (width * POINT_PER_MM).tolist(),
            "lineend": "butt",
        }
        return g_tree(
            segments_grob(
                unit(x0.tolist(), "native"),
                unit(y0.tolist(), "native"),
                unit(x1.tolist(), "native"),
                unit(y1.tolist(), "native"),
                default_units="native",
                gp=gp,
                name="mysegment",
            ),
            name="geom_mysegment",
        )


def build():
    # 案例模块在 CI 里与本进程的其他测试共享注册表：构造完图层就把名字注销，
    # 图层自己持有 Geom 实例，后续 build / draw 不再查注册表。
    registered_here = "mysegment" not in registry.registered("geom")
    if registered_here:
        register_geom("mysegment", GeomMySegment)
    try:
        p = (
            ggplot(to_column_table(DATA), aes(x="x", y="y", xend="xend", yend="yend"))
            + registry.geom_mysegment()
            + scale_x_continuous(limits=(0, 1), expand=(0, 0))
            + scale_y_continuous(limits=(0, 1), expand=(0, 0))
            + theme_void()
            + theme(**{"legend.position": "none"})
        )
    finally:
        if registered_here:
            registry.unregister("geom", "mysegment")
    return {"plot": p, "size": SIZE}
