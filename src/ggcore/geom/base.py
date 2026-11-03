"""geom 绘制契约与共享工具（M1-7）。

一个 geom 的绘制实现 = 一个 :class:`GeomRenderer` 子类。绘制入口挂在
:class:`ggcore.layer.Geom` 上（`Geom.draw()` / `Geom.handle_na()` /
`Geom.setup_data()` / `Geom.setup_params()`），按名字查这里的注册表拿实现：
构造函数路径（`as_geom()` / `register_geom()`）不变。

三件事与 ggplot2 4.0.3 一一对应：

- :meth:`GeomRenderer.setup_params`：`Geom$setup_params()`。当前只做
  `flipped_aes` 检测（横向 bar / boxplot）。
- :meth:`GeomRenderer.setup_data`：`Geom$setup_data()`。派生坐标列
  （`xmin/xmax/ymin/ymax` 等）与行序。
- :meth:`GeomRenderer.handle_na`：`Geom$handle_na()` 的**绘制期**删行；与
  `build` 的 `dropped_missing`（只计数）是两件事（`docs/notes/build.md` §3）。

`draw()` 的坐标口径与 R 一致：`coord$transform()` → 面板 `0..1`（npc，y 向上），
grob 用 `default_units="native"`，面板视口的 `xscale`/`yscale` 都是 `0..1`
（`docs/notes/geom.md`）。
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from typing import Any, ClassVar

import numpy as np

from ggcore.build import BuildWarning
from ggcore.data import Column, ColumnTable
from ggcore.viewport import NA
from ggcore.viewport import NA as _NA

__all__ = [
    "POINT_PER_MM",
    "STROKE_PER_MM",
    "GeomError",
    "GeomRenderer",
    "alpha_colour",
    "flip_data",
    "flipped_names",
    "lty_value",
    "munch_xy",
    "npc_values",
    "put_column",
    "resolve_rect_axis",
    "row_slice",
    "table_column",
    "table_numeric",
    "table_strings",
    "table_values",
]

#: ggplot2 的 `.pt`：mm → pt（1 mm = 72.27/25.4 pt）。
POINT_PER_MM = 72.27 / 25.4
#: ggplot2 的 `.stroke`：`stroke`（mm）→ pt 的换算常量。
STROKE_PER_MM = 96.0 / 25.4


class GeomError(ValueError):
    """geom 绘制契约错误（参数、缺列、无 IR 表达的能力）。"""


# ---------------------------------------------------------------------------
# 列读取
# ---------------------------------------------------------------------------


def table_column(table: ColumnTable, name: str) -> Column | None:
    """按名字取列；没有返回 `None`。"""
    return table.column(name) if name in table else None


def table_numeric(table: ColumnTable, name: str, *, default: float = math.nan) -> np.ndarray:
    """数值列 → float64；缺失位是 NaN。没有列时整列取 `default`。"""
    column = table_column(table, name)
    if column is None:
        return np.full(table.nrows, float(default), dtype=np.float64)
    values = np.asarray(column.values, dtype=np.float64).copy()
    values[np.asarray(column.na_mask, dtype=bool)] = default
    return values


def table_strings(table: ColumnTable, name: str) -> list[Any]:
    """字符串列 → list（缺失位是 `None`）。"""
    column = table_column(table, name)
    if column is None:
        return [None] * table.nrows
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [None if missing else value for value, missing in zip(values, mask, strict=True)]


def table_values(table: ColumnTable, name: str, default: Any) -> list[Any]:
    """逐行取值（缺失位是 `NA`）；没有列时整列取 `default`。

    `default` 是 `None` 时返回 `None`（不是 `NA`）——R 的 `colour = NULL` 与
    `colour = NA` 是两件事：前者不描边，后者是缺失。
    """
    if name not in table:
        return [default] * table.nrows
    column = table.column(name)
    values = column.values.tolist()
    mask = np.asarray(column.na_mask, dtype=bool).tolist()
    return [NA if missing else value for value, missing in zip(values, mask, strict=True)]


def put_column(
    columns: list[tuple[str, Column]], name: str, column: Column
) -> list[tuple[str, Column]]:
    """按 R 的 `data[[name]] <- value` 语义就地替换或追加（位置保持首次出现处）。"""
    for position, (key, _) in enumerate(columns):
        if key == name:
            columns[position] = (name, column)
            return columns
    columns.append((name, column))
    return columns


def resolve_rect_axis(
    minimum: Any,
    maximum: Any,
    center: Any,
    length: Any,
    *,
    names: tuple[str, str, str, str],
    fun: str,
) -> tuple[np.ndarray, np.ndarray] | None:
    """`resolve_rect()`：`(min, max, center, length)` 里缺一个就按其余三个补。

    `names` 是 `(min, max, center, length)` 在报错文案里的 aes 名。四个都给或
    只给三个以外的情况照上游报错。返回 `(min, max)`；`min` / `max` 都给了时返回
    `None`（调用方保留原列）。
    """
    absent = [minimum is None, maximum is None, center is None, length is None]
    if sum(absent) > 2:
        present = [name for name, missing in zip(names, absent, strict=True) if not missing]
        raise GeomError(
            f"geom_{fun} 需要 {', '.join(names[:2])} 与 {', '.join(names[2:])} 里的两个；"
            f"当前只给了 {', '.join(present) if present else '（无）'}"
        )
    if absent[0] and absent[1]:
        low = center - 0.5 * length
        high = center + 0.5 * length
        return low, high
    if absent[0]:
        if center is None:
            return maximum - length, maximum
        return maximum - 2 * (maximum - center), maximum
    if absent[1]:
        if center is None:
            return minimum, minimum + length
        return minimum, minimum + 2 * (center - minimum)
    return None


def row_slice(table: ColumnTable, keep: np.ndarray) -> ColumnTable:
    """按布尔/整数行号取子表（保留 kind / levels / na_mask）。"""
    index = np.asarray(keep)
    columns: list[tuple[str, Column]] = []
    for name in table.names:
        column = table.column(name)
        mask = None if column.na_mask is None else np.asarray(column.na_mask, dtype=bool)[index]
        columns.append(
            (
                name,
                Column(column.kind, np.asarray(column.values)[index], column.levels, mask),
            )
        )
    nrows = int(np.count_nonzero(index)) if index.dtype == bool else int(index.size)
    return ColumnTable(columns, nrows=nrows)


# ---------------------------------------------------------------------------
# 默认尺寸（R 的 resolution() / compute_data_size()）
# ---------------------------------------------------------------------------


def resolution(values: Any) -> float:
    """上游 `resolution(x, zero = FALSE)`：相邻唯一值的最小间距。

    全等（或只有一个水平）时给 1；离散位置在 ggplot2 里本来就是 1..n，间距为 1，
    所以不需要单独的 `is_mapped_discrete()` 分支。口径与
    :func:`ggcore.position._resolution` 一致（jitter 的缺省抖动幅度用同一个数）。
    """
    data = np.asarray(values, dtype=np.float64)
    finite = data[~np.isnan(data)]
    if finite.size == 0:
        return 1.0
    unique = np.unique(finite)
    if unique.size <= 1:
        return 1.0
    diffs = np.diff(unique)
    tolerance = float(np.sqrt(np.finfo(np.float64).eps))
    if np.all(diffs < tolerance):
        return 1.0
    return float(np.min(diffs[diffs > tolerance]))


def panel_resolution(table: ColumnTable, name: str) -> float:
    """`compute_data_size(panels = "across")`：逐 PANEL 求 resolution 后取最小值。"""
    values = table_numeric(table, name, default=np.nan)
    if "PANEL" not in table or table.nrows == 0:
        return resolution(values)
    labels = [str(item) for item in table.column("PANEL").values.tolist()]
    panels = sorted(set(labels))
    if len(panels) < 2:
        return resolution(values)
    groups = [values[[label == panel for label in labels]] for panel in panels]
    return min(resolution(group) for group in groups)


def default_size(table: ColumnTable, name: str, default: float = 0.9) -> float:
    """`compute_data_size(data, default = 0.9, zero = FALSE)` 的标量宽度 / 高度。"""
    return panel_resolution(table, name) * float(default)


# ---------------------------------------------------------------------------
# 横向（flipped_aes）与列名重命名
# ---------------------------------------------------------------------------

#: ggplot2 的 `ggplot_global$x_aes` / `y_aes` 与 `switch_orientation()` 现在住在
#: :mod:`ggcore.aes`——coord 的 flip / 极坐标也要用同一份名字表，这里只做再导出。
from ggcore.aes import flipped_names as flipped_names  # noqa: E402


def flip_data(table: ColumnTable, flip: bool) -> ColumnTable:
    """`flip_data()`：`flipped_aes = TRUE` 时交换 x / y 族列名（列序不变）。"""
    if not flip:
        return table
    names = flipped_names(True)
    return ColumnTable([(names.get(name, name), table.column(name)) for name in table.names])


def _flag_map(params: Mapping[str, Any]) -> bool:
    """参数里显式的 `flipped_aes` / `orientation`。"""
    if "flipped_aes" in params and params["flipped_aes"] is not None:
        return bool(params["flipped_aes"])
    orientation = params.get("orientation")
    if orientation is not None:
        if orientation not in ("x", "y"):
            raise GeomError(f"orientation 只能是 'x' 或 'y'，收到 {orientation!r}")
        return orientation == "y"
    return False


def _is_discrete(column: Column | None) -> bool:
    if column is None:
        return False
    # map_position 之后离散位置是 1..n 的 float（R 的 `mapped_discrete`）；
    # `build` 在映射前会把原始列类型折进 params，见 `has_flipped_aes`。
    return column.is_discrete or column.kind == "bool"


def _with_discrete_position(resolved: dict[str, Any], source: ColumnTable) -> dict[str, Any]:
    """记下「宽度轴是不是离散位置」。

    R 的 `mapped_discrete` 列在 `setup_data()` 里仍带整数类，`resolution()` 的
    `is.integer(x)` 分支直接给 1（多图层共用全局水平、位置是 1/3/5 时也一样）。
    这里从映射前的原始列复现同一个判断，供 bar / boxplot 的 `compute_data_size()`：
    离散位置 → 默认宽度恒为 0.9；连续位置 → `resolution(x) * 0.9`。
    """
    axis = "y" if resolved.get("flipped_aes") else "x"
    column = source.column(axis) if axis in source else None
    resolved["_discrete_position"] = _is_discrete(column)
    return resolved


class GeomRenderer:
    """一个 geom 的绘制实现。子类至少实现 :meth:`draw`。"""

    name: ClassVar[str] = ""
    #: 与 ggplot2 的 `Geom$non_missing_aes` 同名同序。
    non_missing_aes: ClassVar[tuple[str, ...]] = ()
    #: 与 ggplot2 的 `Geom$optional_aes` 同名同序。
    optional_aes: ClassVar[tuple[str, ...]] = ()
    #: 是否复现 R 的 `has_flipped_aes()` 检测（bar / col / histogram / area /
    #: boxplot / smooth 在 `Geom$setup_params()` 里调它；point / line / path 不调）。
    detect_flipped: ClassVar[bool] = False
    #: R 的 `has_flipped_aes(ambiguous = TRUE)`：没有显式 orientation 时不猜横向。
    ambiguous_flipped: ClassVar[bool] = False
    #: R 的 `has_flipped_aes(range_is_orthogonal = ...)`：区间类 geom（ribbon /
    #: linerange / errorbar）按「哪一族区间列在场」推方向，不看列类型。
    #: `None` = 不传这个参数（默认行为）。
    range_is_orthogonal: ClassVar[bool | None] = None

    # -- setup ------------------------------------------------------------

    def setup_params(
        self,
        data: ColumnTable,
        params: Mapping[str, Any],
        *,
        raw: ColumnTable | None = None,
    ) -> dict[str, Any]:
        """`Geom$setup_params()`：解析 `flipped_aes`。

        `raw` 是**映射到位置标度之前**的美学表（离散位置还是 str/categorical），
        用来复现 R 的 `is_mapped_discrete()` 判断；缺省时退回 `data` 本身的列类型
        与显式的 `orientation`。
        """
        resolved = dict(params)
        source = raw if raw is not None else data
        # 上游 `has_flipped_aes()` 的第一分支：先读统计阶段已经产出的
        # `data$flipped_aes`（`stat_bin` 的横向 histogram 就是靠它把方向传给
        # geom 的）；只有它缺失时才按 `orientation` / 列类型推断。
        if "flipped_aes" in data:
            column = data.column("flipped_aes")
            mask = np.asarray(column.na_mask, dtype=bool).tolist()
            for value, missing in zip(np.asarray(column.values).tolist(), mask, strict=True):
                if missing:
                    continue
                resolved["flipped_aes"] = bool(value)
                return _with_discrete_position(resolved, source)
        if "flipped_aes" in resolved and resolved["flipped_aes"] is not None:
            resolved["flipped_aes"] = bool(resolved["flipped_aes"])
            return _with_discrete_position(resolved, source)
        orientation = resolved.get("orientation")
        if orientation is not None:
            if orientation not in ("x", "y"):
                raise GeomError(f"orientation 只能是 'x' 或 'y'，收到 {orientation!r}")
            resolved["flipped_aes"] = orientation == "y"
            return _with_discrete_position(resolved, source)
        if not self.detect_flipped:
            resolved.setdefault("flipped_aes", False)
            return _with_discrete_position(resolved, source)
        if self.range_is_orthogonal is not None:
            # R：`range_is_orthogonal = TRUE` 时「y 族区间在场 → 纵向；x 族区间在场
            # → 横向」，两边都在场时 y 族优先（上游只看 ymin / ymax 是否非空）。
            if "ymin" in source or "ymax" in source:
                resolved["flipped_aes"] = not self.range_is_orthogonal
                return _with_discrete_position(resolved, source)
            if "xmin" in source or "xmax" in source:
                resolved["flipped_aes"] = bool(self.range_is_orthogonal)
                return _with_discrete_position(resolved, source)
        if self.ambiguous_flipped:
            resolved["flipped_aes"] = False
            return _with_discrete_position(resolved, source)
        x = source.column("x") if "x" in source else None
        y = source.column("y") if "y" in source else None
        x_discrete = _is_discrete(x)
        y_discrete = _is_discrete(y)
        # R `has_flipped_aes()` 的离散分支：xor(y_is_discrete, x_is_discrete) 时
        # 返回 `y_is_discrete`（`main_is_continuous = FALSE`）。
        resolved["flipped_aes"] = bool(y_discrete != x_discrete and y_discrete)
        return _with_discrete_position(resolved, source)

    def setup_data(self, data: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
        """`Geom$setup_data()` 的缺省实现：不改数据。"""
        return data

    # -- NA ---------------------------------------------------------------

    def na_aesthetics(self, geom: Any) -> tuple[str, ...]:
        """`handle_na()` 看的美学：`required_aes` + `non_missing_aes`。

        与 R 一样**原样**保留 `"x|y"` 这种备选写法（它们不匹配任何列名，R 的
        `detect_missing()` 会把它们从 `vars` 里 intersect 掉），所以 boxplot 的
        `required_aes` 在这里不起作用——上游行为如此。
        """
        non_missing = tuple(getattr(geom, "non_missing_aes", ())) or tuple(self.non_missing_aes)
        return tuple(geom.required_aes) + non_missing

    def handle_na(self, geom: Any, data: ColumnTable, na_rm: bool) -> ColumnTable:
        """绘制期删行：缺失（或越界被标成 NA）的行整行删掉，并发 warning。"""
        variables = [name for name in self.na_aesthetics(geom) if name in data]
        if not variables:
            return data
        missing = np.zeros(data.nrows, dtype=bool)
        for name in variables:
            missing |= np.asarray(data.column(name).na_mask, dtype=bool)
        return _remove_missing(data, missing, na_rm, f"geom_{geom.name}")

    # -- draw -------------------------------------------------------------

    def draw(
        self,
        geom: Any,
        build: Any,
        panel: Any,
        coord: Any,
        theme: Any,
        metrics: Any,
    ) -> Any:  # pragma: no cover - 抽象方法
        raise NotImplementedError(f"geom_{self.name} 没有实现 draw()")


def _remove_missing(data: ColumnTable, missing: np.ndarray, na_rm: bool, name: str) -> ColumnTable:
    if not bool(missing.any()):
        return data
    if not na_rm:
        count = int(missing.sum())
        noun = "row" if count == 1 else "rows"
        warnings.warn(
            f"Removed {count} {noun} containing missing values or values outside "
            f"the scale range (`{name}()`).",
            BuildWarning,
            stacklevel=4,
        )
    return row_slice(data, ~missing)


# ---------------------------------------------------------------------------
# 坐标与 gpar
# ---------------------------------------------------------------------------


def npc_values(panel: Any, table: ColumnTable, name: str, axis: str) -> np.ndarray:
    """一列数据坐标 → 面板 npc（`coord$transform()`；y 向上）。

    走 :meth:`ggcore.coord.PanelParams.transform_column`——flip 时读对侧列、
    极坐标时把该列与配对轴一起投到二维。geom 只按**屏幕**轴要坐标，不判断
    coord 名字。

    缺失位保持 NaN（由调用方决定断线 / 跳过）；越界值不夹。
    """
    transformed = panel.transform_column(table, name, axis)
    values = np.asarray(transformed.values, dtype=np.float64).copy()
    values[np.asarray(transformed.na_mask, dtype=bool)] = np.nan
    return values


def munch_xy(
    panel: Any,
    xs: Any,
    ys: Any,
    groups: Any,
    *,
    closed: bool = False,
    segment_length: float = 0.01,
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """数据空间折线 / 多边形 → npc，非线性坐标按 `segment_length` 逐边细分。

    R 的 geom 在坐标非线性时都走 `coord_munch()`（rect / polygon / path）。这里
    是同一件事的 numpy 版本：每组独立插值（归一化距离用面板跨度），再
    `panel.project_xy()`。返回 `(x_npc, y_npc, id)`，`id` 直接喂给
    `polygon_grob` / `polyline_grob` 的 `id=`。

    线性坐标不细分（与上游 `if (coord$is_linear()) return(...)` 一致），
    输出与逐列 `npc_values()` 相同。
    """
    x_values = np.asarray(xs, dtype=np.float64)
    y_values = np.asarray(ys, dtype=np.float64)
    group_values = list(groups)
    if len(x_values) != len(y_values) or len(group_values) != len(x_values):
        raise GeomError(
            f"munch_xy 的 x / y / group 长度必须一致，收到 {len(x_values)} / "
            f"{len(y_values)} / {len(group_values)}"
        )
    if getattr(panel, "is_linear", True):
        px, py = panel.project_xy(x_values, y_values)
        ids: list[int] = []
        current = 0
        previous: Any = object()
        for key in group_values:
            if key != previous:
                current += 1
                previous = key
            ids.append(current)
        return px, py, ids
    if not (math.isfinite(float(segment_length)) and float(segment_length) > 0):
        raise GeomError(f"segment_length 必须是正有限数，收到 {segment_length!r}")
    x_span = float(panel.x_range[1]) - float(panel.x_range[0])
    y_span = float(panel.y_range[1]) - float(panel.y_range[0])
    out_x: list[float] = []
    out_y: list[float] = []
    out_id: list[int] = []
    start = 0
    identifier = 0
    for index in range(1, len(group_values) + 1):
        if index < len(group_values) and group_values[index] == group_values[start]:
            continue
        identifier += 1
        gx = x_values[start:index].tolist()
        gy = y_values[start:index].tolist()
        if closed and len(gx) >= 2:
            gx.append(gx[0])
            gy.append(gy[0])
        if gx:
            out_x.append(gx[0])
            out_y.append(gy[0])
            out_id.append(identifier)
        pairs = zip(
            zip(gx[:-1], gy[:-1], strict=True), zip(gx[1:], gy[1:], strict=True), strict=True
        )
        for (x0, y0), (x1, y1) in pairs:
            if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
                out_x.append(x1)
                out_y.append(y1)
                out_id.append(identifier)
                continue
            distance = math.hypot((x1 - x0) / x_span, (y1 - y0) / y_span)
            steps = max(1, math.ceil(distance / float(segment_length)))
            for step in range(1, steps + 1):
                ratio = step / steps
                out_x.append(x0 + (x1 - x0) * ratio)
                out_y.append(y0 + (y1 - y0) * ratio)
                out_id.append(identifier)
        start = index
    px, py = panel.project_xy(np.asarray(out_x), np.asarray(out_y))
    return px, py, out_id


#: R `lty` 的编号 → 名字（gpar 的 `lty` 同时接受两者；向量只认名字）。
LTY_NAMES = {
    0: "blank",
    1: "solid",
    2: "dashed",
    3: "dotted",
    4: "dotdash",
    5: "longdash",
    6: "twodash",
}


def lty_value(value: Any) -> Any:
    """`lty` 取值 → gpar 接受的形式（编号转名字，其余原样）。"""
    if isinstance(value, bool):
        return "solid" if value else "blank"
    if isinstance(value, (int, np.integer)):
        return LTY_NAMES.get(int(value), "solid")
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            return "solid"
        return LTY_NAMES.get(int(value), "solid")
    return value


def alpha_colour(colour: Any, alpha: Any) -> Any:
    """`ggplot2:::alpha(colour, alpha)`：把 alpha 折进颜色（`#RRGGBBAA`）。

    `alpha` 是 `None` / `NA` / 1 时原样返回；`colour` 是 `NA` 时保持 `NA`。
    颜色名（`grey60` / `steelblue`）先按 `col2rgb()` 的口径折成 RGB，再乘上
    已有 alpha——否则 `alpha("grey60", 0.4)` 会原样返回一个不带透明的颜色。
    """
    if colour is None or colour is _NA:
        return colour
    if alpha is None or alpha is _NA:
        return colour
    try:
        value = float(alpha)
    except (TypeError, ValueError):
        return colour
    if not math.isfinite(value) or value >= 1.0:
        return colour
    value = max(value, 0.0)
    if not isinstance(colour, str):
        return colour
    from ggcore.grobs import parse_colour

    try:
        red, green, blue, current = parse_colour(colour)
    except ValueError:
        return colour
    return f"#{red:02X}{green:02X}{blue:02X}{round(current / 255.0 * value * 255):02X}"
