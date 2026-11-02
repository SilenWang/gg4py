"""`geom_smooth` 的绘制（M1-7）。

绘制层只消费列（method / formula / se 的计算归 M1-8 的 `stat_smooth`）：

- 有 `ymin/ymax` 且 `se != FALSE` 时画 ribbon（多边形，`fill` 吃 alpha，无边）；
- 再画一条线（`GeomLine$draw_panel()`：`alpha = NA`，线条不吃 alpha）；
- 行序用 `GeomLine$setup_data()`（按 `(PANEL, group, x)` 排序）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ggcore.geom.base import (
    POINT_PER_MM,
    GeomRenderer,
    alpha_colour,
    flip_data,
    lty_value,
    npc_values,
    table_numeric,
)
from ggcore.geom.line import LineRenderer, _break_at_na, _group_key, _keys, _values
from ggcore.grobs import g_tree, null_grob, polygon_grob, polyline_grob
from ggcore.units import unit
from ggcore.viewport import NA, gpar

__all__ = ["SmoothRenderer"]


class SmoothRenderer(GeomRenderer):
    """`geom_smooth`：se 带 + 拟合线。"""

    name = "smooth"
    optional_aes = ("ymin", "ymax")
    detect_flipped = True
    ambiguous_flipped = True

    def setup_data(self, data: Any, params: Any, *, raw: Any = None) -> Any:
        return LineRenderer().setup_data(data, params, raw=raw)

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_smooth")
        flip = (
            bool(np.any(np.asarray(data.column("flipped_aes").values)))
            if "flipped_aes" in data
            else False
        )
        frame = flip_data(data, flip)
        x = npc_values(panel, frame, "x", "x")
        y = npc_values(panel, frame, "y", "y")
        groups = _group_key(frame)
        colours = _values(frame, "colour", "#3366FF")
        fills = _values(frame, "fill", "grey60")
        alpha = table_numeric(frame, "alpha", default=0.4)
        linewidth = table_numeric(frame, "linewidth", default=1.0)
        linetype = _values(frame, "linetype", 1)
        lineend = str(build.params.get("lineend", "butt"))
        linejoin = str(build.params.get("linejoin", "round"))
        linemitre = float(build.params.get("linemitre", 10.0))
        with_ribbon = bool(build.params.get("se", True)) and "ymin" in frame and "ymax" in frame
        if with_ribbon:
            ymin = npc_values(panel, frame, "ymin", "y")
            ymax = npc_values(panel, frame, "ymax", "y")

        grobs: list[Any] = []
        for key in _keys(groups):
            rows = np.flatnonzero(groups == key)
            if rows.size < 2:
                continue
            first = rows[0]
            if with_ribbon:
                upper_x, upper_y, upper_id = _break_at_na(x[rows], ymax[rows])
                lower_x, lower_y, lower_id = _break_at_na(x[rows][::-1], ymin[rows][::-1])
                if upper_x.size and lower_x.size:
                    # R 的 ribbon 用**同一组 id**：上沿正向 + 下沿反向拼成闭合多边形。
                    grobs.append(
                        polygon_grob(
                            unit(np.concatenate([upper_x, lower_x]).tolist(), "native"),
                            unit(np.concatenate([upper_y, lower_y]).tolist(), "native"),
                            id=[int(item) for item in upper_id] + [int(item) for item in lower_id],
                            default_units="native",
                            gp=gpar(
                                fill=alpha_colour(fills[first], alpha[first]),
                                col=NA,
                                lwd=0.0,
                            ),
                        )
                    )
            line_x, line_y, line_id = _break_at_na(x[rows], y[rows])
            if line_x.size >= 2:
                grobs.append(
                    polyline_grob(
                        unit(line_x.tolist(), "native"),
                        unit(line_y.tolist(), "native"),
                        id=line_id,
                        default_units="native",
                        gp=gpar(
                            col=alpha_colour(colours[first], math.nan),
                            lwd=float(linewidth[first]) * POINT_PER_MM,
                            lty=lty_value(linetype[first]),
                            lineend=lineend,
                            linejoin=linejoin,
                            linemitre=linemitre,
                        ),
                    )
                )
        if not grobs:
            return null_grob(name="geom_smooth")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_smooth")
