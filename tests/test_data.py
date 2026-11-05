"""`ggcore.data` 的列式表契约（纯 numpy，M1-14）。

守这些事（口径见 `docs/notes/data.md`）：

1. 列的 kind / values / levels / na_mask 四件套各自校验，缺失只用 mask 表达；
2. 表是有序列名的：`names` / `columns()` / `column(name)` 顺序一致，缺列报 KeyError；
3. 相等是逐位比较（dtype + 形状 + 字节），表用于三路输入的「同一张表」断言；
4. 缓冲建好即只读，下游不能悄悄改写。
"""

from __future__ import annotations

import numpy as np
import pytest

from ggcore.data import COLUMN_KINDS, Column, ColumnTable


def test_column_kinds_are_the_documented_set() -> None:
    assert COLUMN_KINDS == (
        "float",
        "int",
        "bool",
        "str",
        "categorical",
        "datetime",
        "date",
        "timedelta",
        "geometry",
    )


def test_numeric_column_accepts_float32_and_float64_buffers() -> None:
    single = Column("float", np.array([1.5, 2.5], dtype=np.float32))
    double = Column("float", np.array([1.5, 2.5], dtype=np.float64))
    assert single.values.dtype == np.float32
    assert double.values.dtype == np.float64
    assert not single == double  # 逐位比较：dtype 不同就不相等


def test_int_column_is_carried_in_a_float_bulk_buffer() -> None:
    column = Column("int", np.array([1, 2, 3], dtype=np.int64))
    assert column.kind == "int"
    assert column.values.dtype == np.float64
    assert column.values.tolist() == [1.0, 2.0, 3.0]


def test_string_column_keeps_levels_in_the_given_order() -> None:
    column = Column("str", np.array(["b", "a", "b"]), levels=("b", "a"))
    assert column.values.tolist() == ["b", "a", "b"]
    assert column.levels == ("b", "a")
    assert column.is_discrete
    assert not column.na_count


def test_categorical_column_carries_codes_and_levels() -> None:
    column = Column(
        "categorical",
        np.array([0, 1, 0], dtype=np.int32),
        levels=("b", "a"),
    )
    assert column.values.dtype == np.int32
    assert column.levels == ("b", "a")


def test_masked_positions_must_use_placeholders() -> None:
    with pytest.raises(ValueError, match="占位"):
        Column("float", np.array([1.0, np.nan]), na_mask=np.array([False, True]))
    with pytest.raises(ValueError, match="占位"):
        Column("str", np.array(["a", "b"]), na_mask=np.array([False, True]))
    # 0 / False / "" 是合法占位
    column = Column("float", np.array([1.0, 0.0]), na_mask=np.array([False, True]))
    assert column.na_count == 1


def test_na_mask_must_be_bool_and_match_length() -> None:
    with pytest.raises(ValueError, match="bool"):
        Column("float", np.array([1.0, 2.0]), na_mask=np.array([0, 1]))
    with pytest.raises(ValueError, match="形状"):
        Column("float", np.array([1.0, 2.0]), na_mask=np.array([False]))


def test_levels_are_only_for_discrete_columns() -> None:
    with pytest.raises(ValueError, match="只有 str / categorical"):
        Column("float", np.array([1.0]), levels=("a",))


def test_categorical_codes_must_fit_levels() -> None:
    with pytest.raises(ValueError, match="越界"):
        Column("categorical", np.array([0, 2], dtype=np.int32), levels=("a", "b"))


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="未知的列类型"):
        Column("decimal", np.array([1.0]))


def test_buffers_are_read_only() -> None:
    column = Column("float", np.array([1.0, 2.0]))
    with pytest.raises(ValueError):
        column.values[0] = 9.0
    with pytest.raises(ValueError):
        column.na_mask[0] = True


def test_column_snapshots_the_source_buffer() -> None:
    """只读不能是浅的：调用方留着源数组，也不该能改到已经建好的表。"""
    source = np.array([1.0, 2.0])
    mask = np.array([False, False])
    column = Column("float", source, na_mask=mask)
    source[0] = 9.0
    mask[0] = True
    assert column.values.tolist() == [1.0, 2.0]
    assert column.na_mask.tolist() == [False, False]


def test_table_keeps_column_order_and_lookup() -> None:
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0]))),
            ("g", Column("str", np.array(["a", "b"]), levels=("a", "b"))),
        ]
    )
    assert table.names == ("x", "g")
    assert table.nrows == 2
    assert [column.kind for column in table.columns()] == ["float", "str"]
    assert table.column("g").levels == ("a", "b")
    assert "g" in table
    assert "nope" not in table


def test_missing_column_error_lists_existing_names() -> None:
    table = ColumnTable([("x", Column("float", np.array([1.0])))])
    with pytest.raises(KeyError, match="已有列：x"):
        table.column("y")


def test_table_rejects_non_square_and_duplicate_columns() -> None:
    x = Column("float", np.array([1.0, 2.0]))
    short = Column("float", np.array([1.0]))
    with pytest.raises(ValueError, match="行"):
        ColumnTable([("x", x), ("y", short)])
    with pytest.raises(ValueError, match="列名重复"):
        ColumnTable([("x", x), ("x", x)])
    with pytest.raises(ValueError, match="表是 3 行"):
        ColumnTable([("x", x)], nrows=3)


def test_empty_table_has_zero_rows() -> None:
    table = ColumnTable([])
    assert table.names == ()
    assert table.nrows == 0
    assert table.columns() == ()


def test_table_equality_is_value_based() -> None:
    def build(mask: np.ndarray, levels: tuple[str, ...]) -> ColumnTable:
        return ColumnTable(
            [
                ("x", Column("float", np.array([1.0, 0.0]), na_mask=mask)),
                ("g", Column("str", np.array(["b", "a"]), levels=levels)),
            ]
        )

    clean = np.array([False, False])
    assert build(clean, ("a", "b")) == build(clean, ("a", "b"))
    assert build(clean, ("a", "b")) != build(np.array([False, True]), ("a", "b"))
    assert build(clean, ("a", "b")) != build(clean, ("b", "a"))
    assert build(clean, ("a", "b")) != "not a table"
