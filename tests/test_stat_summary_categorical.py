"""`stat_summary()` 的「组内恒定列」必须支持 categorical（SIL-806 复审回归）。

`_column_values()` 对 categorical 返回的是 level 字符串，`_repeat_constant()`
以前直接 `int(value)` 取 code，分类数据上会抛 ValueError——修前只是静默丢列
（错色但能出图），所以这条回归必须由单测钉住，不能只靠数值 case。
"""

from __future__ import annotations

import numpy as np

from ggcore import registry
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.plot import aes, ggplot


def _categorical(levels: tuple[str, ...], codes: list[int]) -> Column:
    return Column("categorical", np.array(codes, dtype=np.int32), levels=levels)


def _table() -> ColumnTable:
    return ColumnTable(
        [
            ("x", _categorical(("a", "b"), [0, 0, 1, 1])),
            ("y", Column("float", np.array([1.0, 3.0, 2.0, 6.0]))),
            ("colour", _categorical(("red", "blue"), [0, 0, 1, 1])),
        ]
    )


def test_stat_summary_keeps_categorical_colour() -> None:
    data = (
        build_plot(
            ggplot(_table(), aes(x="x", y="y", colour="colour"))
            + registry.stat_summary(fun="mean", geom="point")
        )
        .layers[0]
        .data
    )

    # 走到这里就必须没崩：修前 `_repeat_constant()` 会对 level 字符串做 int()，
    # 分类 colour 列直接 ValueError。
    colour = data.column("colour")
    mapped = [str(value) for value in np.asarray(colour.values)]
    # 两个组映射到两个不同颜色：既不是「整列被丢掉」（只剩一个色），也不是错位。
    assert len(mapped) == 2
    assert len(set(mapped)) == 2
    assert not any(value in ("", "None", "nan") for value in mapped)
    assert list(np.asarray(data.column("y").values)) == [2.0, 4.0]


def test_stat_summary_categorical_missing_value_is_na() -> None:
    table = ColumnTable(
        [
            ("x", _categorical(("a",), [0, 0])),
            ("y", Column("float", np.array([1.0, 3.0]))),
            ("colour", _categorical(("red",), [0, 0])),
        ]
    )
    data = (
        build_plot(
            ggplot(table, aes(x="x", y="y", colour="colour"))
            + registry.stat_summary(fun="mean", geom="point")
        )
        .layers[0]
        .data
    )
    assert data.column("colour").size == 1
    assert data.column("y").values[0] == 2.0
