"""`geom_sf` / `geom_sf_text` / `geom_sf_label` 的绘制（M3-2）。

照 ggplot2 4.0.3 的 `GeomSf$draw_panel()`（`R/geom-sf.R`）：

- 一个 `geom_sf()` 图层里可以混着点 / 线 / 面 / 几何集合；每种几何的缺省美学
  不同——点用 `GeomPoint` 的缺省（pch 19、size 1.5、stroke 0.5），线用
  `GeomLine` 的（linewidth 0.5），面用 `GeomPolygon` 加上 sf 专属的
  `fill = col_mix(ink, paper, 0.899)` / `colour = col_mix(ink, paper, 0.35)` /
  `linewidth = 0.4 * borderwidth`（`theme_test()` 下是 `#E5E5E5` / `#595959` /
  0.43）；几何集合按「点 + 线」的合成缺省画。
- `alpha` 折颜色的规则：点 / 线的 `colour` 吃 alpha，面的 `colour` 不吃、`fill`
  吃（`GeomSf$draw_panel()` 的两行 subset 赋值）。
- 绘制前几何统一投到 `coord_sf()` 的目标 CRS；投影后的顶点直接用面板 npc。
- 图例类型由几何类型决定（`LayerSf$compute_geom_1()` 的 `detect_sf_type()`）：
  全点 → point，全线 → line，其余 → polygon。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ggcore.data import ColumnTable
from ggcore.geom.base import (
    POINT_PER_MM,
    STROKE_PER_MM,
    GeomError,
    GeomRenderer,
    alpha_colour,
    lty_value,
)
from ggcore.grobs import g_tree, null_grob, path_grob, points_grob, polyline_grob
from ggcore.sf import Geometry, SfError
from ggcore.units import unit
from ggcore.viewport import NA, gpar

__all__ = ["SfRenderer", "sf_legend_type", "sf_type_of_rows"]

#: `col_mix(ink, paper, t)`：在 sRGB 上按权重混色（`theme_test()` 下黑白两色）。
_PAPER = (1.0, 1.0, 1.0)


def _mix(t: float) -> str:
    red, green, blue = (round(255.0 * (1.0 - t * (1.0 - channel))) for channel in _PAPER)
    del red, green, blue
    value = round(255.0 * t)
    return f"#{value:02X}{value:02X}{value:02X}"


#: sf 的三种缺省美学（`GeomSf$use_defaults()` 的 `other_default` 与
#: `GeomPoint` / `GeomLine` 的缺省值）。
SF_POLYGON_DEFAULTS: dict[str, Any] = {
    "fill": "#E5E5E5",
    "colour": "#595959",
    "linewidth": 0.43,
}
SF_COLLECTION_DEFAULTS: dict[str, Any] = {
    **SF_POLYGON_DEFAULTS,
    "shape": 19,
    "colour": "black",
    "size": 1.5,
    "stroke": 0.5,
}


def _geom_defaults(name: str) -> dict[str, Any]:
    """点 / 线 / 面的**静态**缺省 + `update_geom_defaults()` 的覆盖。

    `Geom$default_aes` 里的 `from_theme()` 在 ggplot2 侧由主题求值；sf 的
    点 / 线 / 面缺省在这里用 `theme_grey()` 解析后的静态值（与注册表里
    `GeomPoint` / `GeomLine` / `GeomPolygon` 的缺省一致），覆盖值直接生效。
    """
    from ggcore import registry

    static = {
        "point": {"shape": 19, "colour": "black", "fill": None, "size": 1.5, "stroke": 0.5},
        "line": {"colour": "black", "linewidth": 0.5, "linetype": 1},
        "polygon": {"colour": "black", "fill": "grey35", "linewidth": 0.5, "linetype": 1},
    }.get(name, {})
    overrides = getattr(registry, "geom_default_overrides", None)
    if overrides is None:  # pragma: no cover - 注册表版本更旧时
        return static
    return {**static, **dict(overrides(name))}


def _table_values(table: ColumnTable, name: str) -> list[Any] | None:
    if name not in table:
        return None
    column = table.column(name)
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [NA if missing else value for value, missing in zip(values, mask, strict=True)]


def _pick(value: Any, default: Any) -> Any:
    return default if value is NA or value is None else value


def _as_float(value: Any, default: float) -> float:
    if value is NA or value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if not math.isfinite(number) else number


class SfRenderer(GeomRenderer):
    """`geom_sf`：按几何类型分派点 / 线 / 面，缺省美学逐类型取。"""

    name = "sf"
    # `GeomSf$handle_na()` 只在 `use_defaults()` 之后删行：点 / 线 / 面的
    # 缺省美学在那一刻已经按类型补齐，所以这里不把 shape / colour / size 当
    # 「必须非缺失」——绘制期按类型取缺省（见 docs/notes/sf.md）。
    non_missing_aes = ()

    def draw(self, geom: Any, build: Any, panel: Any, coord: Any, theme: Any, metrics: Any) -> Any:
        data = build.data
        if data.nrows == 0:
            return null_grob(name="geom_sf")
        sf = getattr(panel, "sf", None)
        if sf is None:
            raise GeomError(
                "geom_sf 只能和 coord_sf() 一起用（R: GeomSf can only be used with coord_sf）"
            )
        geometries = _geometry_column(data)
        target = sf.crs
        lineend = str(build.params.get("lineend", "butt"))
        linejoin = str(build.params.get("linejoin", "round"))
        linemitre = float(build.params.get("linemitre", 10.0))
        arrow = build.params.get("arrow")

        shapes = _table_values(data, "shape")
        colours = _table_values(data, "colour")
        fills = _table_values(data, "fill")
        sizes = _table_values(data, "size")
        linewidths = _table_values(data, "linewidth")
        linetypes = _table_values(data, "linetype")
        alphas = _table_values(data, "alpha")
        strokes = _table_values(data, "stroke")

        point_defaults = _geom_defaults("point")
        line_defaults = _geom_defaults("line")
        polygon_defaults = {**_geom_defaults("polygon"), **SF_POLYGON_DEFAULTS}

        mapped = getattr(build, "mapped", None)

        def na_default(name: str) -> bool:
            """这一列的 NA 是不是「没给 → 取类型缺省」而不是用户显式写的 NA。"""
            if name in build.params:
                return False
            return not (mapped is not None and name in mapped)

        def pick(name: str, row: int, values: Any, default: Any) -> Any:
            value = NA if values is None else values[row]
            if value is None:
                return default
            if value is NA and na_default(name):
                return default
            return value

        def number(name: str, row: int, values: Any, default: float) -> float:
            value = pick(name, row, values, default)
            return _as_float(value, default)

        grobs: list[Any] = []
        for row, geometry in enumerate(geometries):
            if geometry is None or geometry.is_empty:
                continue
            kind = geometry.sf_type
            if kind == "point":
                grobs.append(
                    _draw_points(
                        [geometry],
                        row,
                        npc=panel,
                        target=target,
                        shape=pick("shape", row, shapes, 19),
                        colour=pick("colour", row, colours, point_defaults.get("colour", "black")),
                        fill=pick("fill", row, fills, point_defaults.get("fill", NA)),
                        size=number("size", row, sizes, float(point_defaults.get("size", 1.5))),
                        stroke=number(
                            "stroke", row, strokes, float(point_defaults.get("stroke", 0.5))
                        ),
                        alpha=number("alpha", row, alphas, 1.0),
                    )
                )
                continue
            if kind == "line":
                grobs.append(
                    _draw_lines(
                        geometry,
                        row,
                        panel=panel,
                        target=target,
                        colour=pick("colour", row, colours, line_defaults.get("colour", "black")),
                        linewidth=number(
                            "linewidth", row, linewidths, float(line_defaults.get("linewidth", 0.5))
                        ),
                        linetype=pick("linetype", row, linetypes, line_defaults.get("linetype", 1)),
                        alpha=number("alpha", row, alphas, 1.0),
                        arrow=arrow,
                        lineend=lineend,
                        linejoin=linejoin,
                        linemitre=linemitre,
                    )
                )
                continue
            if kind == "collection":
                grobs.append(
                    _draw_collection(
                        geometry,
                        row,
                        panel=panel,
                        target=target,
                        shape=pick("shape", row, shapes, 19),
                        colour=pick("colour", row, colours, "black"),
                        fill=pick("fill", row, fills, SF_COLLECTION_DEFAULTS["fill"]),
                        size=number("size", row, sizes, 1.5),
                        stroke=number("stroke", row, strokes, 0.5),
                        linewidth=number("linewidth", row, linewidths, 0.43),
                        linetype=pick("linetype", row, linetypes, 1),
                        alpha=number("alpha", row, alphas, 1.0),
                        arrow=arrow,
                        lineend=lineend,
                        linejoin=linejoin,
                        linemitre=linemitre,
                    )
                )
                continue
            grobs.append(
                _draw_polygon(
                    geometry,
                    row,
                    panel=panel,
                    target=target,
                    fill=pick("fill", row, fills, polygon_defaults.get("fill", "#E5E5E5")),
                    colour=pick("colour", row, colours, polygon_defaults.get("colour", "#595959")),
                    linewidth=number(
                        "linewidth", row, linewidths, float(polygon_defaults.get("linewidth", 0.43))
                    ),
                    linetype=pick("linetype", row, linetypes, 1),
                    alpha=number("alpha", row, alphas, 1.0),
                    lineend=lineend,
                    linejoin=linejoin,
                    linemitre=linemitre,
                )
            )
        if not grobs:
            return null_grob(name="geom_sf")
        if len(grobs) == 1:
            return grobs[0]
        return g_tree(*grobs, name="geom_sf")

    def setup_params(self, data: Any, params: Any, *, raw: Any = None) -> dict[str, Any]:
        """`LayerSf$compute_geom_1()`：图例类型按几何类型确定。"""
        merged = dict(params)
        if "legend" not in merged:
            merged["legend"] = sf_legend_type(data)
        return merged


# ---------------------------------------------------------------------------
# 逐类型绘制
# ---------------------------------------------------------------------------


def _geometry_column(table: ColumnTable) -> list[Geometry | None]:
    if "geometry" not in table:
        raise GeomError("geom_sf 需要 geometry 列（aes(geometry = ...) 或 sf() 数据）")
    column = table.column("geometry")
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [None if missing else item for item, missing in zip(values, mask, strict=True)]


def _transform_vertices(geometry: Geometry, target: Any) -> list[tuple[float, float]]:
    try:
        transformed = geometry if target is None else geometry.transform(target)
    except SfError as exc:
        raise GeomError(str(exc)) from exc
    return transformed.vertices()


def _npc(panel: Any, xs: Any, ys: Any) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.asarray(panel.npc("x", np.asarray(xs, dtype=np.float64)), dtype=np.float64),
        np.asarray(panel.npc("y", np.asarray(ys, dtype=np.float64)), dtype=np.float64),
    )


def _draw_points(
    geometries: list[Geometry],
    row: int,
    *,
    npc: Any,
    target: Any,
    shape: Any,
    colour: Any,
    fill: Any,
    size: float,
    stroke: float,
    alpha: float,
) -> Any:
    from ggcore.geom.point import translate_shape

    xs: list[float] = []
    ys: list[float] = []
    for geometry in geometries:
        for point in geometry.parts if geometry.kind == "multipoint" else [geometry.parts[0]]:
            xs.append(point[0])
            ys.append(point[1])
    if not xs:
        return null_grob(name="geom_sf")
    vertices = _transform_vertices(Geometry("multipoint", tuple(zip(xs, ys, strict=True))), target)
    px, py = _npc(npc, [item[0] for item in vertices], [item[1] for item in vertices])
    pch = translate_shape(shape if shape is not NA else 19)
    size_pt = size * POINT_PER_MM + stroke * STROKE_PER_MM / 2.0
    lwd = stroke * STROKE_PER_MM / 2.0
    del row
    return points_grob(
        unit(px.tolist(), "native"),
        unit(py.tolist(), "native"),
        pch=pch,
        size=unit(size_pt, "bigpts"),
        size_units="bigpts",
        default_units="native",
        gp={
            "col": [alpha_colour(colour, alpha)] * len(px),
            "fill": [alpha_colour(fill, alpha)] * len(px),
            "lwd": lwd,
        },
        name="geom_sf",
    )


def _line_parts(geometry: Geometry) -> list[tuple[tuple[float, float], ...]]:
    if geometry.kind == "linestring":
        return [geometry.parts]
    if geometry.kind == "multilinestring":
        return list(geometry.parts)
    return []


def _polygon_parts(geometry: Geometry) -> list[list[tuple[tuple[float, float], ...]]]:
    if geometry.kind == "polygon":
        return [list(geometry.parts)]
    if geometry.kind == "multipolygon":
        return [list(polygon) for polygon in geometry.parts]
    return []


def _draw_lines(
    geometry: Geometry,
    row: int,
    *,
    panel: Any,
    target: Any,
    colour: Any,
    linewidth: Any,
    linetype: Any,
    alpha: float,
    arrow: Any,
    lineend: str,
    linejoin: str,
    linemitre: float,
) -> Any:
    del row
    parts = _line_parts(geometry)
    xs: list[float] = []
    ys: list[float] = []
    ids: list[int] = []
    transformed = geometry if target is None else geometry.transform(target)
    for part in _line_parts(transformed):
        for x, y in part:
            xs.append(x)
            ys.append(y)
            ids.append(len(xs))
    if not xs:
        return null_grob(name="geom_sf")
    px, py = _npc(panel, xs, ys)
    run_ids: list[int] = []
    for group, part in enumerate(parts):
        run_ids.extend([group + 1] * len(part))
    width = _as_float(linewidth, 0.5)
    gp = gpar(
        col=alpha_colour(colour, alpha),
        lwd=width * POINT_PER_MM,
        lty=lty_value(linetype),
        lineend=lineend,
        linejoin=linejoin,
        linemitre=linemitre,
    )
    return polyline_grob(
        unit(px.tolist(), "native"),
        unit(py.tolist(), "native"),
        id=run_ids,
        default_units="native",
        name="geom_sf",
        gp=gp,
        arrow=arrow,
    )


def _draw_polygon(
    geometry: Geometry,
    row: int,
    *,
    panel: Any,
    target: Any,
    fill: Any,
    colour: Any,
    linewidth: Any,
    linetype: Any,
    alpha: float,
    lineend: str,
    linejoin: str,
    linemitre: float,
) -> Any:
    del row
    transformed = geometry if target is None else geometry.transform(target)
    xs: list[float] = []
    ys: list[float] = []
    ids: list[int] = []
    ring_id = 0
    for polygon in _polygon_parts(transformed):
        for ring in polygon:
            ring_id += 1
            ring_points = list(ring)
            if len(ring_points) > 1 and ring_points[0] == ring_points[-1]:
                ring_points = ring_points[:-1]
            for x, y in ring_points:
                xs.append(x)
                ys.append(y)
                ids.append(ring_id)
    if not xs:
        return null_grob(name="geom_sf")
    px, py = _npc(panel, xs, ys)
    width = _as_float(linewidth, 0.43)
    gp = gpar(
        col=alpha_colour(colour, 1.0),
        fill=alpha_colour(fill, alpha),
        lwd=width * POINT_PER_MM,
        lty=lty_value(linetype),
        lineend=lineend,
        linejoin=linejoin,
        linemitre=linemitre,
    )
    return path_grob(
        unit(px.tolist(), "native"),
        unit(py.tolist(), "native"),
        id=ids,
        rule="evenodd",
        default_units="native",
        name="geom_sf",
        gp=gp,
    )


def _draw_collection(
    geometry: Geometry,
    row: int,
    *,
    panel: Any,
    target: Any,
    shape: Any,
    colour: Any,
    fill: Any,
    size: float,
    stroke: float,
    linewidth: float,
    linetype: Any,
    alpha: float,
    arrow: Any,
    lineend: str,
    linejoin: str,
    linemitre: float,
) -> Any:
    children: list[Any] = []
    for item in geometry.parts:
        if item.sf_type == "point":
            children.append(
                _draw_points(
                    [item],
                    row,
                    npc=panel,
                    target=target,
                    shape=shape,
                    colour=colour,
                    fill=fill,
                    size=size,
                    stroke=stroke,
                    alpha=alpha,
                )
            )
        elif item.sf_type == "line":
            children.append(
                _draw_lines(
                    item,
                    row,
                    panel=panel,
                    target=target,
                    colour=colour,
                    linewidth=linewidth,
                    linetype=linetype,
                    alpha=alpha,
                    arrow=arrow,
                    lineend=lineend,
                    linejoin=linejoin,
                    linemitre=linemitre,
                )
            )
        else:
            children.append(
                _draw_polygon(
                    item,
                    row,
                    panel=panel,
                    target=target,
                    fill=fill,
                    colour=colour,
                    linewidth=linewidth,
                    linetype=linetype,
                    alpha=alpha,
                    lineend=lineend,
                    linejoin=linejoin,
                    linemitre=linemitre,
                )
            )
    if len(children) == 1:
        return children[0]
    return g_tree(*children, name="geom_sf")


# ---------------------------------------------------------------------------
# 图例类型
# ---------------------------------------------------------------------------


def sf_type_of_rows(data: ColumnTable) -> str:
    """`detect_sf_type()`：唯一几何类型 → 分组名，多类型 → "other"。"""
    geometries = [item for item in _geometry_column(data) if item is not None]
    if not geometries:
        return "other"
    kinds = {item.geometry_type for item in geometries}
    if len(kinds) != 1:
        return "other"
    return geometries[0].sf_type


def sf_legend_type(data: ColumnTable) -> str:
    kind = sf_type_of_rows(data)
    return {"point": "point", "line": "line"}.get(kind, "other")
