"""`ggcore.data` — 输入适配层的列式表（纯 numpy）。

pandas DataFrame / Arrow Table / dict of arrays 三种输入在 `ggio.frame` 里归一成
同一份 :class:`ColumnTable`；下游（aes 求值、数据掩码、scale/coord 映射）只认这张
表，不再碰原始 DataFrame。

本模块是 X1 边界内的代码：只 import 标准库 + numpy，pandas / pyarrow 一律留在包外
（`tools/gates/check_import_whitelist.py`）。口径见 `docs/notes/data.md`：

- `kind` 是语义类型：float / int / bool / str / categorical / datetime / timedelta；
- 数值缓冲一律 float64（`int` 的 kind 仍是 int，只是以 float64 的 bulk 表承载；
  datetime / timedelta 是自 epoch 起的秒，`datetime.date` 口径是「天」）；
- 离散列的 `levels` 是**标度顺序**：categorical 用输入给的显式顺序，普通字符串列
  按升序去重（ggplot2 离散标度的缺省顺序）；
- 缺失只进 `na_mask`，数值缓冲里用 0 / False / "" 占位（IR 侧只认 mask）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = ["COLUMN_KINDS", "Column", "ColumnTable"]

#: 允许的语义类型。顺序即文档顺序。
COLUMN_KINDS = ("float", "int", "bool", "str", "categorical", "datetime", "timedelta")

_KINDS = frozenset(COLUMN_KINDS)
_NUMERIC = frozenset({"float", "int", "datetime", "timedelta"})
_DISCRETE = frozenset({"str", "categorical"})


def _frozen(arr: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """只读视图：表一旦建好，调用方就不能悄悄改缓冲。"""
    view = arr.view()
    view.setflags(write=False)
    return view


def _same_buffer(a: np.ndarray[Any, Any], b: np.ndarray[Any, Any]) -> bool:
    """逐位相等：dtype、形状、原始字节都一样（不是 allclose）。"""
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


@dataclass(frozen=True, slots=True, eq=False)
class Column:
    """一列数据。

    Parameters
    ----------
    kind:
        ``COLUMN_KINDS`` 之一。
    values:
        一维 bulk 缓冲。float / int / datetime / timedelta 是 float32/float64；
        bool 是 ``bool``；str 是 numpy unicode 数组；categorical 是 int32 的
        ``levels`` 下标（code）。
    levels:
        离散列的标度顺序。categorical 是显式顺序，str 是升序去重；不含 NA。
    na_mask:
        缺失位置（True = 缺失）。缺省全 False。
    """

    kind: str
    values: np.ndarray[Any, Any]
    levels: tuple[str, ...] = field(default_factory=tuple)
    na_mask: np.ndarray[Any, Any] | None = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"未知的列类型 {self.kind!r}（支持：{', '.join(COLUMN_KINDS)}）")

        values = np.asarray(self.values)
        if values.ndim != 1:
            raise ValueError(f"列的 values 必须是一维数组，实际是 {values.shape}")
        values = self._coerce(values)

        mask = (
            np.zeros(values.shape, dtype=bool) if self.na_mask is None else np.asarray(self.na_mask)
        )
        if mask.dtype != np.bool_:
            raise ValueError(f"na_mask 必须是 bool 数组，实际是 {mask.dtype}")
        if mask.shape != values.shape:
            raise ValueError(f"na_mask 形状 {mask.shape} 与 values 形状 {values.shape} 不一致")

        levels = tuple(str(level) for level in self.levels)
        if levels and self.kind not in _DISCRETE:
            raise ValueError(f"只有 str / categorical 列有 levels，{self.kind} 列收到 {levels!r}")
        if self.kind == "categorical" and values.size:
            present = values[~mask]
            if present.size and (int(present.min()) < 0 or int(present.max()) >= len(levels)):
                raise ValueError(
                    f"categorical 的 code 越界：{int(present.min())}..{int(present.max())}，"
                    f"levels 只有 {len(levels)} 个"
                )

        self._check_placeholders(values, mask)
        object.__setattr__(self, "values", _frozen(values))
        object.__setattr__(self, "na_mask", _frozen(mask))
        object.__setattr__(self, "levels", levels)

    def _coerce(self, values: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        if self.kind in _NUMERIC:
            if values.dtype not in (np.dtype(np.float32), np.dtype(np.float64)):
                values = values.astype(np.float64)
            return values
        if self.kind == "bool":
            return values.astype(np.bool_)
        if self.kind == "categorical":
            return values.astype(np.int32)

        # str：只收字符串，别把数字悄悄 stringify 成 "1"
        if values.dtype.kind == "O" and not all(isinstance(item, str) for item in values.tolist()):
            bad = sorted(
                {type(item).__name__ for item in values.tolist() if not isinstance(item, str)}
            )
            raise TypeError(f"str 列里出现了非字符串值：{', '.join(bad)}")
        if values.dtype.kind not in ("U", "S", "O"):
            raise TypeError(f"str 列的 values 必须是字符串数组，实际是 {values.dtype}")
        return values.astype(str)

    def _check_placeholders(self, values: np.ndarray[Any, Any], mask: np.ndarray[Any, Any]) -> None:
        """mask 位置必须是 0 / False / ""：占位值本身不参与计算，但不能带脏数据。"""
        if not mask.any():
            return
        placeholders = values[mask]
        if self.kind == "str":
            clean = bool(np.all(placeholders == ""))
        elif self.kind == "bool":
            clean = not bool(np.any(placeholders))
        else:
            clean = bool(np.all(placeholders == 0))
        if not clean:
            raise ValueError('na_mask 为 True 的位置必须用 0 / False / "" 占位')

    # -- 便利属性 ---------------------------------------------------------

    @property
    def size(self) -> int:
        return int(self.values.shape[0])

    @property
    def is_discrete(self) -> bool:
        """是否走离散标度（str / categorical）。"""
        return self.kind in _DISCRETE

    @property
    def na_count(self) -> int:
        return int(np.count_nonzero(self.na_mask))

    # -- 值语义 -----------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Column):
            return NotImplemented
        return (
            self.kind == other.kind
            and self.levels == other.levels
            and _same_buffer(self.values, other.values)
            and _same_buffer(self.na_mask, other.na_mask)
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (
            f"Column(kind={self.kind!r}, n={self.size}, "
            f"levels={len(self.levels)}, na={self.na_count})"
        )


class ColumnTable:
    """有序列名 + 行数的列式表；所有列等长。

    >>> table = ColumnTable([("x", Column("float", np.arange(4.0)))])
    >>> table.names, table.nrows
    (('x',), 4)
    >>> table.column("x").kind
    'float'
    """

    __slots__ = ("_columns", "_index", "_names", "_nrows")

    def __init__(
        self,
        columns: Mapping[str, Column] | Iterable[tuple[str, Column]] = (),
        *,
        nrows: int | None = None,
    ) -> None:
        pairs = list(columns.items()) if isinstance(columns, Mapping) else list(columns)
        names: list[str] = []
        built: list[Column] = []
        index: dict[str, int] = {}
        for name, column in pairs:
            if not isinstance(name, str):
                raise TypeError(f"列名必须是 str，收到 {type(name).__name__}")
            if name in index:
                raise ValueError(f"列名重复：{name!r}")
            if not isinstance(column, Column):
                raise TypeError(f"列 {name!r} 必须是 Column，收到 {type(column).__name__}")
            index[name] = len(names)
            names.append(name)
            built.append(column)

        if nrows is None:
            nrows = built[0].size if built else 0
        if isinstance(nrows, bool) or not isinstance(nrows, int) or nrows < 0:
            raise ValueError(f"nrows 必须是非负整数，收到 {nrows!r}")
        for name, column in zip(names, built, strict=True):
            if column.size != nrows:
                raise ValueError(f"列 {name!r} 有 {column.size} 行，表是 {nrows} 行")

        self._names = tuple(names)
        self._columns = tuple(built)
        self._index = index
        self._nrows = nrows

    # -- 结构 -------------------------------------------------------------

    @property
    def names(self) -> tuple[str, ...]:
        """列名，按输入顺序。"""
        return self._names

    @property
    def nrows(self) -> int:
        return self._nrows

    def columns(self) -> tuple[Column, ...]:
        """全部列，顺序与 :attr:`names` 一致。"""
        return self._columns

    def column(self, name: str) -> Column:
        """按列名取列；没有就 KeyError（消息里列出已有列名）。"""
        try:
            return self._columns[self._index[name]]
        except KeyError:
            known = ", ".join(self._names) if self._names else "（空表）"
            raise KeyError(f"表里没有列 {name!r}；已有列：{known}") from None

    def __contains__(self, name: object) -> bool:
        return name in self._index

    # -- 值语义 -----------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ColumnTable):
            return NotImplemented
        return (
            self._names == other._names
            and self._nrows == other._nrows
            and len(self._columns) == len(other._columns)
            and all(a == b for a, b in zip(self._columns, other._columns, strict=True))
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"ColumnTable(nrows={self._nrows}, names={self._names})"
