"""`stat_sf` / `stat_sf_coordinates`（M3-2）。

对应 ggplot2 4.0.3：

- `StatSf$compute_panel()`（`R/stat-sf.R`）：把几何的 bbox 写回 `xmin` / `xmax` /
  `ymin` / `ymax`，让普通位置标度知道「这层数据在哪」。`coord_sf()` 存在时，bbox
  先变换到目标 CRS、再回到 `default_crs`（缺省 CRS 为 NULL 时目标 CRS 就是数据
  CRS）——这正是上游 `coord$record_bbox()` + `sf_transform_xy()` 的两步。
- `StatSfCoordinates$compute_group()`（`R/stat-sf-coordinates.R`）：每个几何取
  一个代表点（缺省 `sf::st_point_on_surface(sf::st_zm(x))`），输出 `x` / `y`。
  `geom_sf_text()` / `geom_sf_label()` 靠它把标签放到多边形内部。

口径与已知差异见 `docs/notes/sf.md`：`point_on_surface` 用面积重心近似 GEOS 的
极值内点算法。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ggcore.data import Column, ColumnTable
from ggcore.sf import (
    Geometry,
    SfError,
    bbox_of,
    point_on_surface,
    st_crs,
    st_transform_xy,
)

__all__ = ["compute_sf", "compute_sf_coordinates"]


def _geometries(table: ColumnTable) -> list[Geometry]:
    if "geometry" not in table:
        raise SfError("stat_sf 需要 geometry 列（geom_sf 的必需美学）")
    column = table.column("geometry")
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [
        item
        for item, missing in zip(values, mask, strict=True)
        if not missing and not item.is_empty
    ]


def _first_crs(geometries: list[Geometry]) -> Any:
    for item in geometries:
        if item.crs is not None:
            return item.crs
    return None


def _coord_targets(coord: Any, data_crs: Any) -> tuple[Any, Any]:
    """`(target, default)`：target = crs（没有就用数据 CRS），default 可为 None。"""
    if coord is None or not hasattr(coord, "name") or getattr(coord, "name", "") != "sf":
        return data_crs, data_crs
    target = getattr(coord, "crs", None)
    target = st_crs(target) if target is not None else data_crs
    default = getattr(coord, "default_crs", None)
    default = st_crs(default) if default is not None else None
    return target, default


def _bbox_in_crs(
    box: tuple[float, float, float, float], source: Any, target: Any
) -> tuple[float, ...]:
    if source is None or target is None or source == target:
        return box
    xmin, ymin, xmax, ymax = box
    midx = (xmin + xmax) / 2.0
    midy = (ymin + ymax) / 2.0
    xs = np.array([midx, midx, xmin, xmax], dtype=np.float64)
    ys = np.array([ymin, ymax, midy, midy], dtype=np.float64)
    tx, ty = st_transform_xy(xs, ys, target, source)
    finite = np.isfinite(tx) & np.isfinite(ty)
    if not finite.any():
        return box
    return (
        float(np.min(tx[finite])),
        float(np.min(ty[finite])),
        float(np.max(tx[finite])),
        float(np.max(ty[finite])),
    )


def compute_sf(table: ColumnTable, coord: Any = None) -> ColumnTable:
    """`StatSf$compute_panel()`：追加整层 bbox 的四个列。"""
    geometries = _geometries(table)
    if not geometries:
        return table
    data_crs = _first_crs(geometries)
    target, default = _coord_targets(coord, data_crs)
    box = bbox_of(geometries)
    box = _bbox_in_crs(box, data_crs, target)
    if default is not None:
        box = _bbox_in_crs(box, target, default)
    nrows = table.nrows
    columns = [(name, table.column(name)) for name in table.names]
    for name, value in zip(("xmin", "ymin", "xmax", "ymax"), box, strict=True):
        columns = _put(columns, name, Column("float", np.full(nrows, float(value))))
    return ColumnTable(columns, nrows=nrows)


def compute_sf_coordinates(
    table: ColumnTable, params: Any = None, coord: Any = None
) -> ColumnTable:
    """`StatSfCoordinates$compute_group()`：每个几何 → 一个代表点 (x, y)。"""
    geometries = _geometries(table)
    if not geometries:
        return table
    data_crs = _first_crs(geometries)
    target, default = _coord_targets(coord, data_crs)
    points = [point_on_surface(item) for item in geometries]
    xs = np.array([item[0] for item in points], dtype=np.float64)
    ys = np.array([item[1] for item in points], dtype=np.float64)
    # 上游：先变换到 default_crs（NULL 时不动），标签坐标随后由 coord 再投到 crs。
    destination = default if default is not None else target
    if data_crs is not None and destination is not None and data_crs != destination:
        xs, ys = st_transform_xy(xs, ys, destination, data_crs)
    nrows = table.nrows
    columns = [(name, table.column(name)) for name in table.names]
    columns = _put(
        columns, "x", Column("float", np.nan_to_num(xs, nan=0.0), na_mask=~np.isfinite(xs))
    )
    columns = _put(
        columns, "y", Column("float", np.nan_to_num(ys, nan=0.0), na_mask=~np.isfinite(ys))
    )
    return ColumnTable(columns, nrows=nrows)


def _put(columns: list[tuple[str, Column]], name: str, column: Column) -> list[tuple[str, Column]]:
    for index, (key, _) in enumerate(columns):
        if key == name:
            out = list(columns)
            out[index] = (name, column)
            return out
    return [*columns, (name, column)]
