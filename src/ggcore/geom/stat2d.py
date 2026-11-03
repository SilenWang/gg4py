"""2D 族的 **build 级** geom 实现（M2-6）。

M2-6 交付的是 8 个 2D stat；它们的默认 geom（`tile` / `hex` / `contour` /
`contour_filled` / `density_2d` / `density_2d_filled`）只需要 `setup_data()` 就能
让 `ggplot_build()` 的 `$data` 与 R 逐列一致（`bin_2d` 的 `xmin/xmax/ymin/ymax`
就是 `geom_tile` 派生的）。真正的绘制不在这里，`draw()` 直接点名**归属任务**，
不静默画一个空图：

- `geom_tile` 的绘制在 **SIL-737**（M2-S2 geom 长尾 A，带 `docs/cases/geom-tile`）；
- 其余 5 个（`hex` / `contour` / `contour_filled` / `density_2d` /
  `density_2d_filled`）归 **SIL-735**（M2-S2 geom 长尾 B · 2D 族）。

`renderer_for()` 先查可绘制的 `GEOM_RENDERERS`，再查这里的 `BUILD_ONLY_RENDERERS`；
`registered_renderers()`（「已实现绘制」）不包含它们。
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from ggcore.data import Column, ColumnTable
from ggcore.geom.base import GeomError, GeomRenderer, panel_resolution

__all__ = ["BUILD_ONLY_RENDERERS", "BuildOnlyRenderer", "ContourRenderer", "TileRenderer"]


class BuildOnlyRenderer(GeomRenderer):
    """只有 `setup_data()` 的 geom：`draw()` 明确报出绘制归哪个任务。"""

    #: 绘制实现所在的任务（子类按需覆盖；`geom_tile` 在 SIL-737 落地）。
    followup: ClassVar[str] = "SIL-735（M2-S2 geom 长尾 B · 2D 族）"

    def draw(
        self,
        geom: Any,
        build: Any,
        panel: Any,
        coord: Any,
        theme: Any,
        metrics: Any,
    ) -> Any:
        raise GeomError(
            f"geom_{self.name} 的绘制实现尚未落地（M2-6 只交付 stat + setup_data）；"
            f"绘制归 {self.followup}。"
            "当前可用于 ggplot_build() 的逐列对拍与数据校验。"
        )


class TileRenderer(BuildOnlyRenderer):
    """`geom_tile`：宽度 / 高度 → 四角（上游 `GeomTile$setup_data()`）。

    绘制已在 SIL-737（M2-S2 geom 长尾 A）实现，所以 `draw()` 的报错指向那里，
    而不是本任务的后续 2D 族（SIL-735）。
    """

    name: ClassVar[str] = "tile"
    followup: ClassVar[str] = "SIL-737（M2-S2 geom 长尾 A）"
    non_missing_aes: ClassVar[tuple[str, ...]] = ("xmin", "xmax", "ymin", "ymax")

    def setup_data(self, data: ColumnTable, params: dict[str, Any]) -> ColumnTable:
        width_column = self._size(data, "width", params.get("width"), 1.0)
        height_column = self._size(data, "height", params.get("height"), 1.0)
        x = _numeric(data, "x")
        y = _numeric(data, "y")
        width = width_column
        height = height_column
        columns = [(name, data.column(name)) for name in data.names]
        columns = [(name, column) for name, column in columns if name not in ("width", "height")]
        columns.extend(
            [
                ("xmin", _column(x - width / 2.0)),
                ("xmax", _column(x + width / 2.0)),
                ("ymin", _column(y - height / 2.0)),
                ("ymax", _column(y + height / 2.0)),
            ]
        )
        return ColumnTable(columns, nrows=data.nrows)

    def _size(self, data: ColumnTable, target: str, param: Any, default: float) -> np.ndarray:
        """`compute_data_size()`：数据里有这一列就原样用，否则 `resolution * default`。"""
        if target in data:
            values = _numeric(data, target)
            if np.all(np.isnan(values)):
                values = np.full(data.nrows, panel_resolution(data, target) * default)
            return values
        if param is not None:
            return np.full(data.nrows, float(param))
        axis = "x" if target == "width" else "y"
        return np.full(data.nrows, panel_resolution(data, axis) * default)


class ContourRenderer(BuildOnlyRenderer):
    """`geom_contour` / `geom_density_2d`：`GeomPath` 没有 `setup_data()`（行序由 stat 给）。

    只有 `geom_line` 会按 `(PANEL, group, x)` 重排（上游 `GeomLine$setup_data()`），
    等值线不重排——这一点常被误抄成「path 都排序」。
    """

    name: ClassVar[str] = "contour"

    def setup_data(self, data: ColumnTable, params: dict[str, Any]) -> ColumnTable:
        flipped = params.get("flipped_aes")
        if flipped:
            raise GeomError("geom_contour 不支持 flipped_aes = TRUE（上游同样不翻转等值线）")
        return data


class Density2dRenderer(ContourRenderer):
    name: ClassVar[str] = "density_2d"


def _numeric(table: ColumnTable, name: str) -> np.ndarray:
    column = table.column(name)
    values = np.asarray(column.values, dtype=np.float64).copy()
    values[np.asarray(column.na_mask, dtype=bool)] = np.nan
    return values


def _column(values: np.ndarray) -> Column:
    array = np.asarray(values, dtype=np.float64)
    missing = np.isnan(array)
    if missing.any():
        return Column("float", np.where(missing, 0.0, array), na_mask=missing)
    return Column("float", array)


class HexRenderer(BuildOnlyRenderer):
    name: ClassVar[str] = "hex"


class ContourFilledRenderer(BuildOnlyRenderer):
    name: ClassVar[str] = "contour_filled"


class Density2dFilledRenderer(BuildOnlyRenderer):
    name: ClassVar[str] = "density_2d_filled"


#: 只有 build 级的 geom（`draw()` 点名归属任务：`tile` → SIL-737，其余 → SIL-735）。
BUILD_ONLY_RENDERERS: dict[str, GeomRenderer] = {
    "tile": TileRenderer(),
    "hex": HexRenderer(),
    "contour": ContourRenderer(),
    "contour_filled": ContourFilledRenderer(),
    "density_2d": Density2dRenderer(),
    "density_2d_filled": Density2dFilledRenderer(),
}
