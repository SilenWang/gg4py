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
from ggcore.viewport import NA as _NA

__all__ = [
    "POINT_PER_MM",
    "STROKE_PER_MM",
    "GeomError",
    "GeomRenderer",
    "alpha_colour",
    "compute_data_size",
    "flip_data",
    "flipped_names",
    "lty_value",
    "npc_values",
    "position_is_discrete",
    "resolution",
    "row_slice",
    "table_column",
    "table_numeric",
    "table_strings",
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
# 默认尺寸（上游 `resolution()` / `compute_data_size()`）
# ---------------------------------------------------------------------------


def resolution(values: Any, *, zero: bool = True) -> float:
    """上游 `resolution()`：相邻取值的**最小**间距（没有可用间距时是 1）。

    `zero = TRUE` 把 0 也算进取值集合（R 的缺省）；`GeomBar$setup_data()` /
    `GeomBoxplot$setup_data()` 走 `zero = FALSE`，只看数据本身。`discrete`
    参数没有对应物：ggcore 的离散位置在标度映射后已经是 `1..n` 的数值编码，
    分辨率必然为 1（与 R 的 `is_mapped_discrete()` 分支同一个结果）。
    """
    array = np.asarray(values, dtype=np.float64).ravel()
    array = array[np.isfinite(array)]
    if array.size == 0:
        return 1.0
    if zero:
        array = np.append(array, 0.0)
    unique = np.unique(array)
    if unique.size <= 1:
        return 1.0
    differences = np.diff(unique)
    tolerance = math.sqrt(np.finfo(np.float64).eps)
    usable = differences[differences > tolerance]
    if usable.size == 0:
        return 1.0
    return float(usable.min())


def compute_data_size(
    table: ColumnTable,
    params: Mapping[str, Any],
    *,
    default: float = 0.9,
    target: str = "width",
    discrete: bool = False,
) -> np.ndarray:
    """上游 `compute_data_size(target = "width")`：逐行宽度。

    取值顺序与 R 一致：

    1. 数据里已有 `width` 列（映射出来的美学）→ 原样用，**不**再乘分辨率；
    2. `params$width` 显式给了 → 全表广播；
    3. 都没有 → `resolution(x, zero = FALSE) * default`；分面时取各面板分辨率的
       最小值（R 的 `panels = "across"` 缺省）。

    `discrete = True` 对应该位置的标度是离散的：R 的 `setup_data()` 跑在
    `map_position()` **之前**，那时的 x 是因子（内部整型），`resolution()` 直接
    返回 1；映射之后 x 是 `1..n` 的全局编码，编码之间的间隔可能大于 1，不能拿
    它算分辨率。调用方从 `raw`（映射前的美学表）判断 `discrete`。

    `target = "height"` 时读 `y` 族，口径对称（当前没有 geom 用到）。
    """
    if target in table:
        return table_numeric(table, target, default=float(default))
    explicit = params.get(target)
    if explicit is not None:
        return np.full(table.nrows, float(explicit))

    axis = "y" if target == "height" else "x"
    values = table_numeric(table, axis, default=math.nan)
    if discrete:
        span = 1.0
    elif "PANEL" in table:
        labels = np.asarray(table.column("PANEL").values)
        spans = [
            resolution(values[labels == label], zero=False)
            for label in dict.fromkeys(labels.tolist())
        ]
        span = min(spans) if spans else resolution(values, zero=False)
    else:
        span = resolution(values, zero=False)
    return np.full(table.nrows, span * float(default))


# ---------------------------------------------------------------------------
# 横向（flipped_aes）与列名重命名
# ---------------------------------------------------------------------------

#: ggplot2 的 `ggplot_global$x_aes` / `y_aes`（4.0.3）。
X_AES: tuple[str, ...] = (
    "x",
    "xmin",
    "xmax",
    "xend",
    "xintercept",
    "xmin_final",
    "xmax_final",
    "xlower",
    "xmiddle",
    "xupper",
    "x0",
)
Y_AES: tuple[str, ...] = (
    "y",
    "ymin",
    "ymax",
    "yend",
    "yintercept",
    "ymin_final",
    "ymax_final",
    "lower",
    "middle",
    "upper",
    "y0",
)


def flipped_names(flip: bool = True) -> dict[str, str]:
    """`switch_orientation()`：x 族 ↔ y 族的**对换**（两个方向都在表里）。

    对换是自反的，所以同一个映射既能翻过去也能翻回来——与 R 的
    `names(data) <- switch_orientation(names(data))` 一致。
    """
    mapping: dict[str, str] = {}
    for x_name, y_name in zip(X_AES, Y_AES, strict=True):
        mapping[x_name] = y_name
        mapping[y_name] = x_name
    return mapping


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


def position_is_discrete(table: ColumnTable | None, *, flipped: bool = False) -> bool:
    """映射前的位置列是否离散（`flipped` 时看 y 族）。

    R 的 `Geom$setup_data()` 跑在 `map_position()` 之前：离散位置的 x 还是因子 /
    字符串，`resolution()` 对因子（内部整型）直接返回 1。默认宽度要按那一刻的
    口径算，映射之后 `1..n` 编码之间的间隔可能大于 1。
    """
    if table is None:
        return False
    name = "y" if flipped else "x"
    return _is_discrete(table.column(name) if name in table else None)


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
        if "flipped_aes" in resolved and resolved["flipped_aes"] is not None:
            resolved["flipped_aes"] = bool(resolved["flipped_aes"])
            return resolved
        orientation = resolved.get("orientation")
        if orientation is not None:
            if orientation not in ("x", "y"):
                raise GeomError(f"orientation 只能是 'x' 或 'y'，收到 {orientation!r}")
            resolved["flipped_aes"] = orientation == "y"
            return resolved
        if not self.detect_flipped:
            resolved.setdefault("flipped_aes", False)
            return resolved
        if self.ambiguous_flipped:
            resolved["flipped_aes"] = False
            return resolved
        source = raw if raw is not None else data
        x = source.column("x") if "x" in source else None
        y = source.column("y") if "y" in source else None
        x_discrete = _is_discrete(x)
        y_discrete = _is_discrete(y)
        # R `has_flipped_aes()` 的离散分支：xor(y_is_discrete, x_is_discrete) 时
        # 返回 `y_is_discrete`（`main_is_continuous = FALSE`）。
        resolved["flipped_aes"] = bool(y_discrete != x_discrete and y_discrete)
        return resolved

    def setup_data(
        self, data: ColumnTable, params: Mapping[str, Any], *, raw: ColumnTable | None = None
    ) -> ColumnTable:
        """`Geom$setup_data()` 的缺省实现：不改数据。

        `raw` 是位置标度映射**之前**的美学表（与 :meth:`setup_params` 的 `raw`
        同源）：R 的 `setup_data()` 跑在 `map_position()` 之前，离散位置那时
        还是因子 / 字符串，默认宽度 / 朝向等要按那时的口径判断。
        """
        return data

    # -- NA ---------------------------------------------------------------

    def na_aesthetics(self, geom: Any) -> tuple[str, ...]:
        """`handle_na()` 看的美学：`required_aes` + `non_missing_aes`。

        与 R 一样**原样**保留 `"x|y"` 这种备选写法（它们不匹配任何列名，R 的
        `detect_missing()` 会把它们从 `vars` 里 intersect 掉），所以 boxplot 的
        `required_aes` 在这里不起作用——上游行为如此。
        """
        return tuple(geom.required_aes) + tuple(self.non_missing_aes)

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

    缺失位保持 NaN（由调用方决定断线 / 跳过）；越界值不夹。
    """
    column = table.column(name)
    transformed = panel.transform(column, axis)
    values = np.asarray(transformed.values, dtype=np.float64).copy()
    values[np.asarray(transformed.na_mask, dtype=bool)] = np.nan
    return values


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
