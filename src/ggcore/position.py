"""位置调整（position adjustments）：把「同 x 的多行」摆到互不重叠的位置。

对标 ggplot2 4.0.3 的 `R/position-*.R`（`PositionStack` / `PositionFill` /
`PositionDodge` / `PositionDodge2` / `PositionJitter` / `PositionJitterdodge` /
`PositionNudge` / `PositionIdentity`），执行侧统一成一条接口：

    position.compute_layer(data, params=None) -> ColumnTable

四段调用照上游 `Layer$compute_position()`：`setup_params(data)` →
`setup_data(data, params)` → 按 PANEL 拆 → 每块 `compute_panel(data, params)`。
:class:`PanelPosition` 是这条骨架的基类：`setup_params()` / `setup_data()`
在**整层**上跑一次（`n`、`order` 这类跨面板的量因此与 R 同源），`compute_panel()`
只拿一个面板。`identity` / `nudge` 在 R 里是图层级实现（没有 `compute_panel`），
所以它们仍然直接覆写 `compute_layer()`。

`data` 是流水线第 4 阶段（`compute_position`）的表：`x / y / xmin / xmax /
ymin / ymax / PANEL / group`（另有 geom `setup_data()` 派生的 `flipped_aes`）。
**所有分支都不删行、不改 `nrows`**：行序保持输入顺序（上游 `collide()` 末尾
`match(seq_along(ord), ord)` 把排序还原）。

注册表里的名字（`ggcore.registry.KINDS` 的 `position` 一类）由
:data:`POSITION_FACTORIES` 登记，`position_dodge()` 与
`geom_col(position="dodge")` 都经 `registry.construct("position", …)` 解析成
同一个类的实例，所以「改注册项，两条路径同时变」。

口径与差异面见 `docs/notes/position.md`。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar

import numpy as np

from ggcore.data import Column, ColumnTable
from ggcore.layer import Position

__all__ = [
    "POSITION_FACTORIES",
    "POSITION_NAMES",
    "PanelPosition",
    "PositionDodge",
    "PositionDodge2",
    "PositionFill",
    "PositionIdentity",
    "PositionJitter",
    "PositionJitterdodge",
    "PositionNudge",
    "PositionStack",
    "flipped_aes",
]

#: ggplot2 的 x / y 美学族（`ggplot_global$x_aes` / `y_aes`，顺序即上游顺序）。
X_AESTHETICS: tuple[str, ...] = (
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
Y_AESTHETICS: tuple[str, ...] = (
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

#: `switch_orientation()`：x 族 ↔ y 族逐名对调（双向映射，用在 flip 两次）。
_ORIENTATION_SWAP: Mapping[str, str] = MappingProxyType(
    {
        **dict(zip(X_AESTHETICS, Y_AESTHETICS, strict=True)),
        **dict(zip(Y_AESTHETICS, X_AESTHETICS, strict=True)),
    }
)

#: 参与位置计算、按 float64 读写的列（其余列（colour/fill/…）原样带过）。
_NUMERIC_KINDS = frozenset({"float", "int", "datetime", "date", "timedelta"})

#: 上游 `pos_stack()` 里判断「总量够大才归一」的阈值：`sqrt(.Machine$double.eps)`。
_EPS = float(np.sqrt(np.finfo(np.float64).eps))


def _build_error(message: str) -> Exception:
    """构造 `ggcore.build.BuildError`。

    build 在模块级 import 本模块，反向 import 必须推迟到调用时，否则成环。
    """
    from ggcore.build import BuildError

    return BuildError(message)


# ---------------------------------------------------------------------------
# 工作副本：保留列序，数值列按 float64 + NaN 读写
# ---------------------------------------------------------------------------


class _Frame:
    """一张表的可变工作副本。

    - 数值列读成 float64，`na_mask` 落成 NaN（位置计算只认这一种缺失表示）；
    - `set()` 写回成 `Column("float", …)`（`kind="int"` 时写 `Column("int", …)`，
      用于上游的 `order` 列）：已有列原位替换、没有的列追加到末尾（与 R 的
      `data$col <- …` 一致，列序因此可复现）；
    - `flip()` 按 `switch_orientation()` 对调 x/y 族列名，列位置不变。
    """

    __slots__ = ("columns", "nrows")

    def __init__(self, table: ColumnTable) -> None:
        self.columns = dict(zip(table.names, table.columns(), strict=True))
        self.nrows = table.nrows

    def __contains__(self, name: object) -> bool:
        return name in self.columns

    def values(self, name: str) -> np.ndarray:
        """数值列 → float64（缺失 NaN）。非数值列直接报错。"""
        column = self.columns[name]
        if column.kind in _NUMERIC_KINDS:
            values = np.array(column.values, dtype=np.float64, copy=True)
        elif column.kind == "bool":
            values = column.values.astype(np.float64)
        else:
            raise _build_error(f"位置调整需要数值列 {name!r}，实际是 {column.kind}")
        values[column.na_mask] = np.nan
        return values

    def numeric(self, name: str, default: float | None = None) -> np.ndarray:
        """列存在就读，否则给 `default` 广播（`default=None` 表示必需）。"""
        if name in self.columns:
            return self.values(name)
        if default is None:
            raise _build_error(f"位置调整需要列 {name!r}；已有列：{', '.join(self.columns)}")
        return np.full(self.nrows, float(default))

    def raw(self, name: str) -> np.ndarray:
        """原始取值（任意类型，缺失 → None）：`PANEL` 这类离散列用。"""
        column = self.columns[name]
        values = np.array(column.values, dtype=object, copy=True)
        values[column.na_mask] = None
        return values

    def panel(self) -> np.ndarray:
        """`PANEL` 列的原始取值；没有该列时当作单面板。"""
        if "PANEL" in self.columns:
            return self.raw("PANEL")
        return np.full(self.nrows, 1.0, dtype=object)

    def set(self, name: str, values: np.ndarray, *, kind: str = "float") -> None:
        values = np.asarray(values, dtype=np.float64)
        missing = np.isnan(values)
        if kind == "int":
            clean = np.where(missing, 0.0, values).astype(np.int64)
        else:
            clean = np.where(missing, 0.0, values)
        self.columns[name] = Column(kind, clean, na_mask=missing)

    def flip(self, flip: bool) -> None:
        if not flip:
            return
        self.columns = {
            _ORIENTATION_SWAP.get(name, name): column for name, column in self.columns.items()
        }

    def table(self) -> ColumnTable:
        return ColumnTable(list(self.columns.items()), nrows=self.nrows)


def flipped_aes(table: ColumnTable, default: bool = False) -> bool:
    """`has_flipped_aes()`：取 `flipped_aes` 列的第一个非缺失值，没有就用默认。

    横向的 bar / boxplot 在 geom `setup_data()` 里把 `flipped_aes` 置 TRUE
    （上游 `Geom$setup_data()` 的 `flipped_aes(data, params)`），位置调整据此
    把 x 族与 y 族对调后再计算。
    """
    if "flipped_aes" not in table:
        return default
    column = table.column("flipped_aes")
    for value, missing in zip(column.values.tolist(), column.na_mask.tolist(), strict=True):
        if not missing:
            return bool(value)
    return default


# ---------------------------------------------------------------------------
# 面板拆分：上游 `Position$compute_layer()` 的 `dapply(data, "PANEL", ...)`
# ---------------------------------------------------------------------------


def _take(table: ColumnTable, rows: np.ndarray) -> ColumnTable:
    """按行号取子表（保留 kind / levels / na_mask）。"""
    return ColumnTable(
        [
            (
                name,
                Column(
                    column.kind,
                    column.values[rows],
                    levels=column.levels,
                    na_mask=column.na_mask[rows],
                ),
            )
            for name, column in zip(table.names, table.columns(), strict=True)
        ],
        nrows=int(rows.size),
    )


def _stack(tables: Sequence[ColumnTable]) -> ColumnTable:
    """竖向拼接（同一层各面板的同一阶段输出，列名与列序必须一致）。"""
    pieces = [table for table in tables if table.nrows]
    if not pieces:
        return ColumnTable()
    names = pieces[0].names
    columns: list[tuple[str, Column]] = []
    for name in names:
        columns_in = [table.column(name) for table in pieces]
        kinds = {column.kind for column in columns_in}
        if len(kinds) > 1:
            raise _build_error(f"面板拼接时列 {name!r} 的类型不一致：{sorted(kinds)}")
        first = columns_in[0]
        columns.append(
            (
                name,
                Column(
                    first.kind,
                    np.concatenate([np.asarray(column.values) for column in columns_in]),
                    levels=first.levels,
                    na_mask=np.concatenate([np.asarray(column.na_mask) for column in columns_in]),
                ),
            )
        )
    return ColumnTable(columns, nrows=sum(table.nrows for table in pieces))


def _restore_order(table: ColumnTable, order: np.ndarray) -> ColumnTable:
    """拼接后的表按原行序还原（`order` 是拼接顺序里的源行号）。"""
    if order.size == 0 or bool(np.array_equal(order, np.arange(order.size))):
        return table
    return _take(table, np.argsort(order))


def _panel_rows(table: ColumnTable) -> list[np.ndarray]:
    """`(PANEL, 行号)`：按 PANEL 首次出现顺序分组；没有 PANEL 列就是一块。"""
    if "PANEL" not in table:
        return [np.arange(table.nrows, dtype=np.int64)]
    column = table.column("PANEL")
    groups: dict[str, list[int]] = {}
    for index, value in enumerate(column.values.tolist()):
        groups.setdefault(repr(value), []).append(index)
    return [np.asarray(rows, dtype=np.int64) for rows in groups.values()]


class PanelPosition(Position):
    """内置 position 的公共骨架：`compute_layer()` 按 PANEL 拆、`compute_panel()` 算一块。

    上游 `Position$compute_layer()` 是 `dapply(data, "PANEL", ...)`，而
    `setup_params()` / `setup_data()` 在**整层**数据上各跑一次。这个顺序有语义：
    `dodge(preserve = "single")` 的 `n`、`dodge2` 的同名字段都是「全层最大
    组数」，逐面板各算会得到不同结果（SIL-734 的夹具里有不均匀分面用例）。
    """

    def setup_params(self, table: ColumnTable, params: Mapping[str, Any]) -> dict[str, Any]:
        """`Position$setup_params()` 的扩展点：在整层上解析参数。"""
        return dict(params)

    def setup_data(self, table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
        """`Position$setup_data()` 的扩展点：在整层上补列（`order` 等）。"""
        return table

    def compute_panel(self, table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
        """`Position$compute_panel()` 的扩展点：只处理一个面板。"""
        raise NotImplementedError(
            f"position_{self.name} 没有实现 compute_panel(data, params)"
            "（PanelPosition 的子类需要覆写它）"
        )

    def compute_layer(
        self, data: ColumnTable, params: Mapping[str, Any] | None = None
    ) -> ColumnTable:
        if data.nrows == 0:
            return data
        resolved = self.setup_params(data, _merged(self.params, params))
        prepared = self.setup_data(data, resolved)
        groups = _panel_rows(prepared)
        if len(groups) == 1:
            return self.compute_panel(prepared, resolved)
        pieces = [self.compute_panel(_take(prepared, rows), resolved) for rows in groups]
        return _restore_order(_stack(pieces), np.concatenate(groups))


# ---------------------------------------------------------------------------
# 分组 / 名次的小工具（对齐上游 vec_ave(..., match_sorted) 的口径）
# ---------------------------------------------------------------------------


def _keys(values: np.ndarray, panels: np.ndarray) -> list[tuple[str, str]]:
    """每行的分组键：位置值用 `repr`（NaN 因此算同一个水平）+ PANEL 的原始值。"""
    return [
        (repr(x), repr(panel)) for x, panel in zip(values.tolist(), panels.tolist(), strict=True)
    ]


def _match_sorted(values: np.ndarray) -> np.ndarray:
    """`match_sorted()`：每个值在升序去重后的名次（1 起）。NaN 排最后。"""
    unique = np.unique(values)
    lookup = {repr(float(value)): index + 1 for index, value in enumerate(unique.tolist())}
    return np.array([lookup[repr(float(value))] for value in values.tolist()], dtype=np.float64)


def _ave_match_sorted(values: np.ndarray, keys: Iterable[tuple[Any, ...]]) -> np.ndarray:
    """`vec_ave(values, by, match_sorted)`：按 by 分组，各自取名次。"""
    out = np.full(values.shape, np.nan, dtype=np.float64)
    groups: dict[tuple[Any, ...], list[int]] = {}
    for index, key in enumerate(keys):
        groups.setdefault(key, []).append(index)
    for rows in groups.values():
        index = np.asarray(rows, dtype=np.int64)
        out[index] = _match_sorted(values[index])
    return out


def _group_rows(values: np.ndarray) -> list[np.ndarray]:
    """按值分组（保持各组第一次出现的顺序；NaN 归一组），返回行号数组。"""
    groups: dict[str, list[int]] = {}
    for index, value in enumerate(values.tolist()):
        groups.setdefault(repr(value), []).append(index)
    return [np.asarray(rows, dtype=np.int64) for rows in groups.values()]


def _max_groups(values: np.ndarray, panels: np.ndarray, group: np.ndarray) -> float:
    """每个 (PANEL, 位置值) 里有多少个不同 group，取最大值（preserve="single"）。"""
    per_key: dict[tuple[str, str], set[float]] = {}
    for key, value in zip(_keys(values, panels), group.tolist(), strict=True):
        per_key.setdefault(key, set()).add(float(value))
    return float(max((len(items) for items in per_key.values()), default=1))


def _count_per_key(values: np.ndarray, panels: np.ndarray) -> np.ndarray:
    """每个 (PANEL, 位置值) 的行数（dodge2 的 `table(panel$x)`）。"""
    keys = _keys(values, panels)
    counts: dict[tuple[str, str], int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    return np.array([counts[key] for key in keys], dtype=np.float64)


def _max_overlap_groups(frame: _Frame, panels: np.ndarray) -> float:
    """`PositionDodge2$setup_params()` 没有 x 时的 n：逐 PANEL 跑 `find_x_overlaps()`。

    上游 `groups <- lapply(split(data, data$PANEL), find_x_overlaps)` +
    `max(vapply(groups, max, ...))`；`find_x_overlaps()` 给出的是 1..k 的组号，
    所以 `max` 就是该面板的重叠组数。
    """
    xmin = frame.values("xmin")
    xmax = frame.values("xmax")
    rows_by_panel: dict[str, list[int]] = {}
    for index, panel in enumerate(panels.tolist()):
        rows_by_panel.setdefault(repr(panel), []).append(index)
    counts = []
    for rows in rows_by_panel.values():
        picked = np.asarray(rows, dtype=np.int64)
        overlaps = _find_x_overlaps(xmin[picked], xmax[picked])
        counts.append(int(overlaps.max()) if overlaps.size else 0)
    return float(max(counts, default=1))


# ---------------------------------------------------------------------------
# 实现：identity / stack / fill
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionIdentity(Position):
    """`position_identity()`：不改数据。"""

    name: str = "identity"

    def compute_layer(
        self, data: ColumnTable, params: Mapping[str, Any] | None = None
    ) -> ColumnTable:
        return data


@dataclass(frozen=True, slots=True)
class PositionStack(PanelPosition):
    """`position_stack()`：同 x 的行按 group 反向累加（上游 `collide(pos_stack)`）。"""

    name: str = "stack"
    #: `PositionFill` 把它打开（上游 `PositionFill <- ggproto(..., fill = TRUE)`）。
    fill: ClassVar[bool] = False

    def setup_params(self, table: ColumnTable, params: Mapping[str, Any]) -> dict[str, Any]:
        """上游 `PositionStack$setup_params()` 的 `var` 分支。

        x 没有重复、非 fill、`vjust == 1` 时整层退化成 identity（`var = NULL`）：
        判断在**整层**上做，逐面板判断会让「A 面板唯一、B 面板重复」时两个面板
        的列集不一致（拼接时报错）。
        """
        frame = _Frame(table)
        flipped = flipped_aes(table)
        frame.flip(flipped)
        resolved = {**params, "flipped_aes": flipped}
        if "x" not in frame:
            return {**resolved, "stacked": True}
        keys = [repr(value) for value in frame.values("x").tolist()]
        resolved["stacked"] = (
            self.fill or float(params.get("vjust", 1.0)) != 1.0 or len(set(keys)) != len(keys)
        )
        return resolved

    def compute_panel(self, table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
        if not params.get("stacked", True):
            return table
        return _collide_stack(table, params, fill=self.fill)


@dataclass(frozen=True, slots=True)
class PositionFill(PositionStack):
    """`position_fill()`：stack 之后把每个 x 的 y / ymin / ymax 归一到 0..1。"""

    name: str = "fill"
    fill: ClassVar[bool] = True


def _merged(params: Mapping[str, Any], extra: Mapping[str, Any] | None) -> dict[str, Any]:
    return {**params, **(extra or {})}


def _collide_stack(table: ColumnTable, params: Mapping[str, Any], *, fill: bool) -> ColumnTable:
    """上游 `PositionStack$compute_panel()` / `PositionFill$compute_panel()`。

    逐 x 取组内行，按 `-group`（`reverse=True` 时 `group`）稳定排序后正负分开累加：
    `heights = c(0, cumsum(y))`，相邻两段取 min/max；`vjust=1` 时 `y` 取 `ymax`
    （第一个 group 在上面），`vjust=0` 时取 `ymin`。`fill` 再把 heights 除以该 x
    的累计总量，得到 0..1 的比例。
    """
    frame = _Frame(table)
    flipped = flipped_aes(table)
    frame.flip(flipped)
    if "x" not in frame or "y" not in frame:
        raise _build_error("position_stack / position_fill 需要 x 与 y 两列")

    vjust = float(params.get("vjust", 1.0))
    reverse = bool(params.get("reverse", False))

    x = frame.values("x")
    y = frame.values("y")
    nrows = frame.nrows
    group = frame.numeric("group", default=1.0)

    # 「整层退化成 identity」的判断在 `setup_params()`（整层）做：这里再按面板
    # 判一次会让 x 恰好唯一的那个面板少加 xmin/xmax，`_stack()` 拼不回列集。
    keys = [repr(value) for value in x.tolist()]

    ymin = np.zeros(nrows, dtype=np.float64)
    ymax = np.zeros(nrows, dtype=np.float64)
    # 上游 `pos_stack()`：输入行里 ymax < ymin（面积/ribbon 的负段）时输出保持这个
    # 朝向（max_is_lower），y 仍取 pmax（vjust = 1）。
    if "ymin" in frame and "ymax" in frame:
        with np.errstate(invalid="ignore"):
            max_is_lower = frame.values("ymax") < frame.values("ymin")
    else:
        max_is_lower = np.zeros(nrows, dtype=bool)
    for index in dict.fromkeys(keys):
        rows = np.array([i for i, key in enumerate(keys) if key == index], dtype=np.int64)
        # collide(reverse = params$reverse)：reverse=FALSE 时按 -group（第一个
        # group 在最上面），TRUE 时按 group。
        weights = group[rows] if reverse else -group[rows]
        rows = rows[np.argsort(weights, kind="stable")]
        values = y[rows]
        # 上游把正负分开各 collide 一次（NA 当 0 高度，保留有效坐标）。
        positive = rows[(values >= 0) | np.isnan(values)]
        negative = rows[values < 0]
        for subset in (positive, negative):
            if subset.size == 0:
                continue
            heights = np.concatenate(([0.0], np.cumsum(np.nan_to_num(y[subset]))))
            if fill:
                total = abs(heights[-1])
                if total > _EPS:
                    heights = heights / total
            ymin[subset] = np.minimum(heights[:-1], heights[1:])
            ymax[subset] = np.maximum(heights[:-1], heights[1:])

    # 上游在**翻转坐标里**写 ymin/ymax/y，最后才 `flip_data()` 回原朝向：横向
    # 时这三个名字就是 x 族（长度轴），累计值因此落到 xmin/xmax/x 上，而 y 族
    # （类别轴）原样保留。先 flip 回来再 set 会把累计值写进类别轴（SIL-692）。
    frame.set("ymin", np.where(max_is_lower, ymax, ymin))
    frame.set("ymax", np.where(max_is_lower, ymin, ymax))
    frame.set("y", (1.0 - vjust) * ymin + vjust * ymax)
    # 上游 `collide()`：跑累加的层一定有区间列。geom 已经给了 xmin/xmax（柱）就
    # 原样保留；面积没有（`GeomArea$setup_data()` 只补 ymin/ymax），宽度按 0 算
    # → `xmin = xmax = x`。缺了这两列，`stat_align` 的端到端结果会少列。
    if "xmin" not in frame:
        frame.set("xmin", x)
    if "xmax" not in frame:
        frame.set("xmax", x)
    frame.flip(flipped)
    return frame.table()


# ---------------------------------------------------------------------------
# 实现：dodge / dodge2
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionDodge(PanelPosition):
    """`position_dodge()`：同 x 的 group 并排（上游 `pos_dodge()`）。"""

    name: str = "dodge"

    def setup_params(self, table: ColumnTable, params: Mapping[str, Any]) -> dict[str, Any]:
        return _dodge_setup_params(table, params, dodge2=False)

    def setup_data(self, table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
        return _dodge_setup_data(table, params)

    def compute_panel(self, table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
        return _dodge_compute_panel(table, params, dodge2=False)


@dataclass(frozen=True, slots=True)
class PositionDodge2(PositionDodge):
    """`position_dodge2()`：按重叠区间分组并排，可加 padding（上游 `pos_dodge2()`）。

    上游 `PositionDodge2` 继承 `PositionDodge`，只覆写 `setup_params()` /
    `compute_panel()`——`setup_data()`（补 x 中点、`order` 列）也是继承来的，
    所以这里同样只覆写那两个。
    """

    name: str = "dodge2"

    def setup_params(self, table: ColumnTable, params: Mapping[str, Any]) -> dict[str, Any]:
        return _dodge_setup_params(table, params, dodge2=True)

    def compute_panel(self, table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
        return _dodge_compute_panel(table, params, dodge2=True)


def _dodge_setup_params(
    table: ColumnTable, params: Mapping[str, Any], *, dodge2: bool
) -> dict[str, Any]:
    """上游 `PositionDodge(2)$setup_params()`：翻转朝向 + preserve="single" 的 n。

    `n` 是**全层**的最大组数（R 在 setup_params 里算一次，再喂给每个面板的
    `compute_panel()`），所以不均匀分面时每个面板都按同一个 n 分槽。
    """
    name = "position_dodge2" if dodge2 else "position_dodge"
    preserve = _arg_match(params.get("preserve", "total"), ("total", "single"), "preserve")
    reverse = bool(params.get("reverse", False))

    # 上游 setup_params() 的必需美学校验在**翻转之前**的原列名上做
    # （`if (flipped_aes) "y|ymin" else "x|xmin"`），翻转后再查会看错轴。
    flipped = flipped_aes(table, default=bool(params.get("orientation") == "y"))
    main, edges = ("y", "ymin") if flipped else ("x", "xmin")
    if main not in table and edges not in table:
        raise _build_error(f"{name} 需要 {main} 或 {edges} 列；已有列：{', '.join(table.names)}")

    frame = _Frame(table)
    frame.flip(flipped)

    # 上游 `PositionDodge2$setup_params()` 是 `if ("x" %in% names(data))
    # table(panel$x) else find_x_overlaps`：分支要在**补 x 之前**定下来，
    # 否则只有 xmin/xmax 的表会被当成「每行一个 x」，n 恒为 1（SIL-692）。
    has_x = "x" in frame
    panel = frame.panel()
    if preserve == "total":
        n_total: float | None = None
    elif dodge2:
        # dodge2 的 single：有 x 时 `table(panel$x)`，没有 x 时 `find_x_overlaps`。
        n_total = (
            float(np.max(_count_per_key(frame.values("x"), panel)))
            if has_x
            else _max_overlap_groups(frame, panel)
        )
    else:
        xmin = frame.values("xmin") if "xmin" in frame else frame.values("x")
        n_total = _max_groups(xmin, panel, frame.numeric("group", default=1.0))

    resolved: dict[str, Any] = {
        "width": None if params.get("width") is None else float(params["width"]),
        "n": n_total,
        "preserve": preserve,
        "reverse": reverse,
        "flipped_aes": flipped,
    }
    if dodge2:
        resolved["padding"] = float(params.get("padding", 0.1))
    else:
        resolved["orientation"] = _arg_match(
            params.get("orientation", "x"), ("x", "y"), "orientation"
        )
    return resolved


def _dodge_setup_data(table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
    """上游 `PositionDodge$setup_data()`：只有 xmin/xmax 时补 x 中点，再补 `order`。

    `order` 是 `pos_dodge()` 的 groupidx 来源：每个 (x, PANEL) 内 group 的升序
    名次；`reverse` 取负；`preserve = "single"` 时全局重新取名次。
    """
    frame = _Frame(table)
    flipped = bool(params.get("flipped_aes", flipped_aes(table)))
    frame.flip(flipped)
    _ensure_x(frame)
    if "x" not in frame:
        raise _build_error("position_dodge 需要 x 或 xmin/xmax 列")

    x = frame.values("x")
    panel = frame.panel()
    keys = _keys(x, panel)
    if "order" in frame:
        order = frame.values("order")
    else:
        order = _ave_match_sorted(frame.numeric("group", default=1.0), keys)
    if bool(params.get("reverse", False)):
        order = -order
    if params.get("n") is None:
        order = _ave_match_sorted(order, keys)
    else:
        order = _match_sorted(order)
    # R 的 order 列是 integer（`xtfrm()` / `match_sorted()` 都返回 integer）。
    frame.set("order", order, kind="int")
    frame.flip(flipped)
    return frame.table()


def _dodge_compute_panel(
    table: ColumnTable, params: Mapping[str, Any], *, dodge2: bool
) -> ColumnTable:
    """上游 `PositionDodge(2)$compute_panel()`：`collide(2)()` + `pos_dodge(2)()`。"""
    frame = _Frame(table)
    flipped = bool(params.get("flipped_aes", flipped_aes(table)))
    frame.flip(flipped)

    # collide_setup()：宽度缺省取第一个 (xmax - xmin)。
    width = _collide_width(frame, params.get("width"))
    n_total = params.get("n")
    if dodge2:
        result = _dodge2_panel(frame, width, n_total, params)
    else:
        order = frame.values("order") if "order" in frame else None
        result = _dodge_panel(frame, width, n_total, order)
        if "ymax" not in frame and "y" in frame:
            # 上游 collide()：没有 ymax 时把 y 复制过去（柱/点的 dodge 输出因此多一列）。
            frame.set("ymax", frame.values("y"))
    frame.set("x", result["x"])
    frame.set("xmin", result["xmin"])
    frame.set("xmax", result["xmax"])
    frame.flip(flipped)
    return frame.table()


def _ensure_x(frame: _Frame) -> None:
    """上游 setup_data()：只有 xmin/xmax 时用中点补 x。"""
    if "x" not in frame and "xmin" in frame and "xmax" in frame:
        frame.set("x", (frame.values("xmin") + frame.values("xmax")) / 2.0)


def _collide_width(frame: _Frame, width_param: Any) -> float:
    """上游 `collide_setup()`：显式 width 直接用；否则取第一个 (xmax-xmin)。"""
    if width_param is not None:
        width = float(width_param)
        if "xmin" not in frame or "xmax" not in frame:
            x = frame.values("x")
            frame.set("xmin", x - width / 2.0)
            frame.set("xmax", x + width / 2.0)
        return width
    if "xmin" not in frame or "xmax" not in frame:
        x = frame.values("x")
        frame.set("xmin", np.array(x, copy=True))
        frame.set("xmax", np.array(x, copy=True))
    diffs = frame.values("xmax") - frame.values("xmin")
    diffs = diffs[~np.isnan(diffs)]
    return float(diffs[0]) if diffs.size else float("nan")


def _dodge_panel(
    frame: _Frame, width: float, n_total: float | None, order: np.ndarray | None
) -> dict[str, np.ndarray]:
    """上游 `pos_dodge()`：按 xmin 分组，groupidx 由 `order` 列（或组内 group 名次）给出。

    `order is None` 是 `position_jitterdodge()` 的路径：上游那里没有
    `PositionDodge$setup_data()` 的 `order` 列，`pos_dodge()` 回退到
    `match_sorted(df$group)` —— 注意是**组内**（按 xmin 切出的那一段）重新取名次。
    """
    x = frame.values("x")
    xmin = frame.values("xmin")
    xmax = frame.values("xmax")
    group = frame.numeric("group", default=1.0)

    new_x = np.array(x, copy=True)
    new_xmin = np.array(xmin, copy=True)
    new_xmax = np.array(xmax, copy=True)
    for rows in _group_rows(xmin):
        n = n_total if n_total is not None else float(np.unique(group[rows]).size)
        if n == 1:
            continue
        # R 的 max(..., na.rm = FALSE)：组里有 NA 时整组变 NA。
        d_width = float(np.max(xmax[rows] - xmin[rows]))
        groupidx = _match_sorted(group[rows]) if order is None else order[rows]
        shifted = x[rows] + width * ((groupidx - 0.5) / n - 0.5)
        new_x[rows] = shifted
        new_xmin[rows] = shifted - d_width / n / 2.0
        new_xmax[rows] = shifted + d_width / n / 2.0
    return {"x": new_x, "xmin": new_xmin, "xmax": new_xmax}


def _dodge2_panel(
    frame: _Frame, width: float, n_total: float | None, params: Mapping[str, Any]
) -> dict[str, np.ndarray]:
    """上游 `collide2()` + `pos_dodge2()`：按重叠的 x 区间分组并排。

    `width` 只是 `collide2()` 的签名占位：`pos_dodge2()` 不用它算任何东西
    （每行的柱宽由 `xmax - xmin` 决定），保留参数是为了与上游调用点对称。
    """
    del width  # 上游 pos_dodge2() 同样不使用 collide 的 width
    padding = float(params.get("padding", 0.1))
    reverse = bool(params.get("reverse", False))

    x = frame.values("x")
    xmin = frame.values("xmin")
    xmax = frame.values("xmax")
    group = frame.numeric("group", default=1.0)

    # collide2(reverse = params$reverse)：order(x, group) / order(x, -group)。
    secondary = -group if reverse else group
    sorted_rows = np.lexsort((secondary, x))
    sx, sxmin, sxmax = x[sorted_rows], xmin[sorted_rows], xmax[sorted_rows]

    xid = _find_x_overlaps(sxmin, sxmax)
    unique_ids = np.unique(xid)
    newx = np.empty(sx.size, dtype=np.float64)
    for identifier in unique_ids.tolist():
        rows = xid == identifier
        newx[rows] = (np.min(sxmin[rows]) + np.max(sxmax[rows])) / 2.0

    counts = np.array([np.count_nonzero(xid == identifier) for identifier in xid], dtype=np.float64)
    if n_total is None:
        new_width = (sxmax - sxmin) / counts
    else:
        new_width = (sxmax - sxmin) / n_total

    # aggregate(size = new_width, by = newx, sum)：按 newx 升序分组求和。
    order_by_newx = np.argsort(newx, kind="stable")
    sizes_per_newx: dict[float, float] = {}
    for index in order_by_newx.tolist():
        sizes_per_newx[float(newx[index])] = sizes_per_newx.get(float(newx[index]), 0.0) + float(
            new_width[index]
        )
    sorted_newx = sorted(sizes_per_newx)
    starts = {value: value - sizes_per_newx[value] / 2.0 for value in sorted_newx}

    out_xmin = np.array(sxmin, copy=True)
    out_xmax = np.array(sxmax, copy=True)
    for identifier, value in zip(unique_ids.tolist(), sorted_newx, strict=True):
        rows = np.flatnonzero(xid == identifier)
        # `cumsum(c(starts[i], df[df$xid == i, "new_width"]))`：行序就是 collide2
        # 排序后的顺序，divisions 的前 k 项是 xmin、后 k 项是 xmax。
        divisions = np.cumsum(np.concatenate(([starts[value]], new_width[rows])))
        out_xmin[rows] = divisions[:-1]
        out_xmax[rows] = divisions[1:]

    out_x = (out_xmin + out_xmax) / 2.0
    # 每个 x 只有一根柱（xid 全不同）时上游直接返回、不叠 padding：退化成 identity。
    if np.unique(xid).size != xid.size:
        pad_width = new_width * (1.0 - padding)
        out_xmin = out_x - pad_width / 2.0
        out_xmax = out_x + pad_width / 2.0

    new_x = np.empty_like(out_x)
    new_xmin = np.empty_like(out_xmin)
    new_xmax = np.empty_like(out_xmax)
    new_x[sorted_rows] = out_x
    new_xmin[sorted_rows] = out_xmin
    new_xmax[sorted_rows] = out_xmax
    return {"x": new_x, "xmin": new_xmin, "xmax": new_xmax}


def _find_x_overlaps(xmin: np.ndarray, xmax: np.ndarray) -> np.ndarray:
    """上游 `find_x_overlaps()`：把重叠（或相接）的 x 区间划成一组，返回 1 起组号。"""
    if xmin.size == 0:
        return np.zeros(0, dtype=np.int64)
    missing = np.isnan(xmin) | np.isnan(xmax)
    start = _fill_missing(xmin)
    end = _fill_missing(xmax)
    nonzero = (xmax != xmin) & ~missing
    previous_end = np.concatenate(([end[0]], np.maximum.accumulate(end[:-1])))
    with np.errstate(invalid="ignore"):
        breaks = (start > previous_end) | ((start == previous_end) & nonzero)
    overlaps = np.cumsum(breaks & ~missing)
    if missing.any():
        overlaps = np.asarray(overlaps, dtype=np.float64)
        top = float(np.nanmax(overlaps)) if overlaps.size else 0.0
        overlaps[missing] = np.arange(1, int(missing.sum()) + 1, dtype=np.float64) + top
    # match(overlaps, unique0(overlaps))：按首次出现顺序重新编号。
    seen: dict[float, int] = {}
    result = np.empty(overlaps.size, dtype=np.int64)
    for index, value in enumerate(np.asarray(overlaps, dtype=np.float64).tolist()):
        if value not in seen:
            seen[value] = len(seen) + 1
        result[index] = seen[value]
    return result


def _fill_missing(values: np.ndarray) -> np.ndarray:
    """上游 `vec_fill_missing(x, "downup")`：先用前一个非缺失值，再补前面的。"""
    out = np.array(values, dtype=np.float64, copy=True)
    missing = np.isnan(out)
    if not missing.any():
        return out
    indices = np.arange(out.size)
    valid = np.flatnonzero(~missing)
    if valid.size == 0:
        return out
    # 前向填充
    positions = np.searchsorted(valid, indices, side="right") - 1
    filled = out[valid[np.clip(positions, 0, valid.size - 1)]]
    out[missing] = filled[missing]
    return out


# ---------------------------------------------------------------------------
# 实现：jitter / jitterdodge / nudge
# ---------------------------------------------------------------------------


def _random_seed() -> int:
    """R 的 `sample.int(.Machine$integer.max, 1L)`：不碰全局 RNG。"""
    return int(np.random.default_rng().integers(0, 2**31 - 1))


@dataclass(frozen=True, slots=True)
class PositionJitter(PanelPosition):
    """`position_jitter()`：按 width / height 均匀抖动（seed 给定时可复现）。"""

    name: str = "jitter"

    def setup_params(self, table: ColumnTable, params: Mapping[str, Any]) -> dict[str, Any]:
        """上游 `PositionJitter$setup_params()`：只把 `NA` 的 seed 换成一个随机整数。

        seed 在**整层**上定一次，再喂给每个面板 —— 与 R 的
        `with_seed_null()` 每个面板重设同一个 seed 同效，因此各面板的抖动
        偏移相同。
        """
        seed = params.get("seed")
        if seed is not None and isinstance(seed, float) and np.isnan(seed):
            seed = None
        return {
            "width": params.get("width"),
            "height": params.get("height"),
            "seed": _random_seed() if seed is None else int(seed),
        }

    def compute_panel(self, table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
        return _jitter(table, params)


@dataclass(frozen=True, slots=True)
class PositionJitterdodge(PanelPosition):
    """`position_jitterdodge()`：先按 `dodge.width` 并排，再抖动（`geom_point` 配 boxplot）。

    参数名在 Python 侧是 `jitter_width` / `jitter_height` / `dodge_width`；
    R 的点号写法（`jitter.width` 等）由构造器一并接受。
    """

    name: str = "jitterdodge"

    def setup_params(self, table: ColumnTable, params: Mapping[str, Any]) -> dict[str, Any]:
        """上游 `PositionJitterdodge$setup_params()`。

        `jitter.width` 缺省是 40% resolution，再按 `ndodge + 2` 收缩；`ndodge` 是
        「同一 (PANEL, x) 上的最多 group 数」——这是**全层**统计量。
        """
        frame = _Frame(table)
        flipped = flipped_aes(table)
        frame.flip(flipped)
        if "x" not in frame or "y" not in frame:
            raise _build_error("position_jitterdodge 需要 x 与 y 两列")

        x = frame.values("x")
        width = params.get("jitter_width")
        width = float(_resolution(x) * 0.4) if width is None else float(width)
        ndodge = _max_groups(x, frame.panel(), frame.numeric("group", default=1.0))
        dodge_width = params.get("dodge_width")
        jitter_height = params.get("jitter_height")
        seed = params.get("seed")
        return {
            "dodge_width": 0.75 if dodge_width is None else float(dodge_width),
            "jitter_height": 0.0 if jitter_height is None else float(jitter_height),
            "jitter_width": width / (ndodge + 2.0),
            "seed": _random_seed() if seed is None else int(seed),
            "flipped_aes": flipped,
            "reverse": bool(params.get("reverse", False)),
        }

    def compute_panel(self, table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
        return _jitterdodge_panel(table, params)


def _jitterdodge_panel(table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
    """上游 `PositionJitterdodge$compute_panel()`：`collide(pos_dodge)` 后 `compute_jitter()`。

    注意上游 `reverse` 在这里**不改变结果**：`collide()` 只拿它决定行序，
    而 `pos_dodge()` 的 groupidx 来自 `match_sorted(group)`；夹具里
    `jitterdodge_zero_jitter_reverse` 与正向逐值相等，钉住这个口径。
    """
    frame = _Frame(table)
    flipped = bool(params["flipped_aes"])
    frame.flip(flipped)

    width = float(params["dodge_width"])
    if "xmin" not in frame or "xmax" not in frame:
        # collide_setup()：显式 width → xmin/xmax = x ∓ width / 2。
        x = frame.values("x")
        frame.set("xmin", x - width / 2.0)
        frame.set("xmax", x + width / 2.0)
    if "ymax" not in frame and "y" in frame:
        frame.set("ymax", frame.values("y"))

    result = _dodge_panel(frame, width, None, None)
    frame.set("x", result["x"])
    frame.set("xmin", result["xmin"])
    frame.set("xmax", result["xmax"])

    jittered = _jitter(
        frame.table(),
        {
            "width": params["jitter_width"],
            "height": params["jitter_height"],
            "seed": params["seed"],
        },
    )
    out = _Frame(jittered)
    out.flip(flipped)
    return out.table()


@dataclass(frozen=True, slots=True)
class PositionNudge(Position):
    """`position_nudge()`：x / y 整体平移。

    上游 `PositionNudge` 的 `default_aes` 是 `nudge_x = 0` / `nudge_y = 0`：
    流水线在 `compute_position()` 里按这两列补缺（`geom_text(nudge_x = …)` 这类
    图层参数因此能传到位置层），`compute_layer()` 再读列做逐行平移。
    """

    name: str = "nudge"
    default_aes: ClassVar[Mapping[str, float]] = MappingProxyType({"nudge_x": 0.0, "nudge_y": 0.0})

    def compute_layer(
        self, data: ColumnTable, params: Mapping[str, Any] | None = None
    ) -> ColumnTable:
        return _nudge(data, _merged(self.params, params))


def _jitter(table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
    """上游 `compute_jitter()`：缺省 40% resolution，抖动量作用在整个 x / y 族上。"""
    frame = _Frame(table)
    nrows = frame.nrows
    x = frame.values("x") if "x" in frame else np.zeros(nrows)
    y = frame.values("y") if "y" in frame else np.zeros(nrows)

    width = params.get("width")
    height = params.get("height")
    width = float(_resolution(x) * 0.4) if width is None else float(width)
    height = float(_resolution(y) * 0.4) if height is None else float(height)

    seed = params.get("seed")
    if seed is not None and isinstance(seed, float) and np.isnan(seed):
        seed = None
    # 不碰全局 RNG：同一个 seed 两次调用逐位相同（docs/notes/position.md 的差异面）。
    rng = np.random.default_rng(None if seed is None else int(seed))
    x_jitter = rng.uniform(-width, width, nrows) if width > 0 else np.zeros(nrows)
    y_jitter = rng.uniform(-height, height, nrows) if height > 0 else np.zeros(nrows)
    x_jitter[np.isinf(x)] = 0.0
    y_jitter[np.isinf(y)] = 0.0

    for name in X_AESTHETICS:
        if name in frame:
            frame.set(name, frame.values(name) + x_jitter)
    for name in Y_AESTHETICS:
        if name in frame:
            frame.set(name, frame.values(name) + y_jitter)
    return frame.table()


def _nudge(table: ColumnTable, params: Mapping[str, Any]) -> ColumnTable:
    """上游 `PositionNudge$compute_layer()`：`transform_position(x + dx, y + dy)`。

    `x` / `y` 参数缺省时回退到数据里的 `nudge_x` / `nudge_y` 列（上游
    `setup_params()` 的 `self$x %||% data$nudge_x`），因此映射出来的 nudge 量
    也能用；两者都没有就是 0（`position_nudge()` 本身是恒等）。
    """
    frame = _Frame(table)
    dx = _nudge_shift(frame, params.get("x"), "nudge_x")
    dy = _nudge_shift(frame, params.get("y"), "nudge_y")
    if np.any(dx != 0.0):
        for name in X_AESTHETICS:
            if name in frame:
                frame.set(name, frame.values(name) + dx)
    if np.any(dy != 0.0):
        for name in Y_AESTHETICS:
            if name in frame:
                frame.set(name, frame.values(name) + dy)
    return frame.table()


def _nudge_shift(frame: _Frame, value: Any, column: str) -> np.ndarray:
    """nudge 的位移量：参数 > 数据列 > 0。

    参数可以是标量、长度 1 的向量，或逐行向量（与 R 的
    `x = c(0.1, 0.2)` 回调一致）；长度既不等于 1 也不等于行数时报错。
    """
    if value is None:
        return frame.values(column) if column in frame else np.zeros(frame.nrows)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return np.full(frame.nrows, float(value))
    shift = np.asarray(value, dtype=np.float64)
    if shift.size == 1:
        return np.full(frame.nrows, float(shift.reshape(-1)[0]))
    if shift.size != frame.nrows:
        raise _build_error(
            f"nudge 的位移长度必须是 1 或 {frame.nrows}（数据行数），得到 {shift.size}"
        )
    return shift.reshape(-1).astype(np.float64, copy=True)


def _resolution(values: np.ndarray) -> float:
    """上游 `resolution(x, zero = FALSE, discrete = TRUE)`。

    全等（或只有一个水平）时给 1。离散位置在 ggplot2 里本来就是 1..n 的整数
    编码，与 R 的 `is_mapped_discrete()` 分支得到同一个分辨率，所以这里不需要
    单独的 discrete 判断。
    """
    finite = values[~np.isnan(values)]
    if finite.size == 0:
        return 1.0
    unique = np.unique(finite)
    if unique.size <= 1:
        return 1.0
    diffs = np.diff(unique)
    tolerance = _EPS
    if np.all(diffs < tolerance):
        return 1.0
    return float(np.min(diffs[diffs > tolerance]))


# ---------------------------------------------------------------------------
# 构造器（注册表登记的工厂：参数校验口径照上游 `arg_match0()` / `check_bool()`）
# ---------------------------------------------------------------------------


def _arg_match(value: Any, choices: tuple[str, ...], name: str) -> str:
    if value not in choices:
        raise ValueError(f"{name} 必须是 {' / '.join(choices)} 之一，得到 {value!r}")
    return str(value)


def _check_bool(value: Any, name: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} 必须是布尔值，得到 {type(value).__name__}")
    return bool(value)


def _position_identity() -> PositionIdentity:
    return PositionIdentity()


def _position_stack(vjust: float = 1.0, reverse: bool = False) -> PositionStack:
    return PositionStack(params={"vjust": float(vjust), "reverse": _check_bool(reverse, "reverse")})


def _position_fill(vjust: float = 1.0, reverse: bool = False) -> PositionFill:
    return PositionFill(params={"vjust": float(vjust), "reverse": _check_bool(reverse, "reverse")})


def _position_dodge(
    width: float | None = None,
    preserve: str = "total",
    orientation: str = "x",
    reverse: bool = False,
) -> PositionDodge:
    return PositionDodge(
        params={
            "width": None if width is None else float(width),
            "preserve": _arg_match(preserve, ("total", "single"), "preserve"),
            "orientation": _arg_match(orientation, ("x", "y"), "orientation"),
            "reverse": _check_bool(reverse, "reverse"),
        }
    )


def _position_dodge2(
    width: float | None = None,
    preserve: str = "total",
    padding: float = 0.1,
    reverse: bool = False,
) -> PositionDodge2:
    return PositionDodge2(
        params={
            "width": None if width is None else float(width),
            "preserve": _arg_match(preserve, ("total", "single"), "preserve"),
            "padding": float(padding),
            "reverse": _check_bool(reverse, "reverse"),
        }
    )


def _position_jitter(
    width: float | None = None,
    height: float | None = None,
    seed: int | None = None,
) -> PositionJitter:
    return PositionJitter(
        params={
            "width": None if width is None else float(width),
            "height": None if height is None else float(height),
            "seed": None if seed is None else int(seed),
        }
    )


def _shift_arg(value: Any, name: str) -> float | tuple[float, ...] | None:
    """nudge 的 `x` / `y`：`None` / 标量 / 长度 1 的向量 / 逐行向量。

    R 的 `position_nudge(x = c(0.2))` 与标量等价；长度大于 1 时按行广播
    （长度不等于行数由 `_nudge_shift()` 在知道行数后报错）。
    """
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    try:
        values = tuple(float(item) for item in value)
    except TypeError:
        raise TypeError(
            f"nudge 的 {name} 必须是数字或数字序列，得到 {type(value).__name__}"
        ) from None
    if not values:
        raise ValueError(f"nudge 的 {name} 不能是空序列")
    return values


def _position_nudge(
    x: float | Sequence[float] | None = None,
    y: float | Sequence[float] | None = None,
) -> PositionNudge:
    return PositionNudge(params={"x": _shift_arg(x, "x"), "y": _shift_arg(y, "y")})


def _position_jitterdodge(
    jitter_width: float | None = None,
    jitter_height: float | None = 0.0,
    dodge_width: float | None = 0.75,
    reverse: bool = False,
    seed: int | None = None,
    **aliases: Any,
) -> PositionJitterdodge:
    """`position_jitterdodge()`：点号写法（`jitter.width` 等）与 snake_case 都认。"""
    values: dict[str, Any] = {
        "jitter_width": jitter_width,
        "jitter_height": jitter_height,
        "dodge_width": dodge_width,
    }
    for dotted, target in (
        ("jitter.width", "jitter_width"),
        ("jitter.height", "jitter_height"),
        ("dodge.width", "dodge_width"),
    ):
        if dotted in aliases:
            values[target] = aliases.pop(dotted)
    if aliases:
        raise TypeError(f"position_jitterdodge() 不认识的参数：{', '.join(sorted(aliases))}")
    return PositionJitterdodge(
        params={
            "jitter_width": None
            if values["jitter_width"] is None
            else float(values["jitter_width"]),
            "jitter_height": (
                None if values["jitter_height"] is None else float(values["jitter_height"])
            ),
            "dodge_width": (
                None if values["dodge_width"] is None else float(values["dodge_width"])
            ),
            "reverse": _check_bool(reverse, "reverse"),
            "seed": None if seed is None else int(seed),
        }
    )


#: 注册名 → 构造器（`ggcore.registry` 逐项登记，两个入口都查这张表）。
POSITION_FACTORIES: Mapping[str, Callable[..., Position]] = MappingProxyType(
    {
        "identity": _position_identity,
        "stack": _position_stack,
        "fill": _position_fill,
        "dodge": _position_dodge,
        "dodge2": _position_dodge2,
        "jitter": _position_jitter,
        "jitterdodge": _position_jitterdodge,
        "nudge": _position_nudge,
    }
)

#: 已实现的 position 名字，按登记顺序（也是 `registry.registered("position")`）。
POSITION_NAMES: tuple[str, ...] = tuple(POSITION_FACTORIES)
