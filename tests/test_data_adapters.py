"""`ggio.frame` 三种输入 → 同一张列式表 → 同一份 IR 字节（M1-14）。

最硬的一条是 :func:`test_three_inputs_encode_identical_ir_bytes`：同一份逻辑数据
从 dict / pandas / Arrow 三条路进来，喂给同一个最小 scene 构造，`ir.encode` 的
字节必须完全相等。其余用例逐条守住 `docs/notes/data.md` 的口径：分类顺序、时区、
NaT、有缺失的整型、时间单位、缺失哨兵、可选依赖的报错文案与 1e6 行的批量路径。
"""

from __future__ import annotations

import datetime as dt
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

import ggio.frame as frame
from ggcore import ir
from ggcore.grobs import points_grob, scene
from ggcore.units import unit
from ggcore.viewport import Device, ViewportTree, gpar, viewport
from ggio.frame import from_arrow, from_dict, from_pandas, to_column_table

#: 三路输入共用的逻辑数据：float / str / int / bool 四种 dtype。
DATA = {
    "x": [0.25, 1.75, 3.5, 2.0],
    "y": [1.0, 2.5, 0.5, 3.0],
    "g": ["b", "a", "b", "c"],
    "n": [1, 2, 3, 4],
    "ok": [True, False, True, True],
}
POINT_COLOURS = ("#E41A1C", "#377EB8", "#4DAF4A")


def _routes(data: dict) -> tuple[object, object, object]:
    return (
        to_column_table({name: list(values) for name, values in data.items()}),
        to_column_table(pd.DataFrame(data)),
        to_column_table(pa.table(data)),
    )


def _scene_bytes(table) -> bytes:
    """最小 scene 构造：x/y → bigpts，离散列 → palette，编成 IR 字节。"""
    x = table.column("x").values
    y = table.column("y").values
    group = table.column("g")
    codes = [group.levels.index(str(value)) for value in group.values]

    tree = ViewportTree(Device(4.0, 3.0))
    tree.push(
        viewport("page", x=0.5, y=0.5, width=1.0, height=1.0, clip="off", gp=gpar(fontsize=11.0))
    )
    grobs = []
    for xi, yi, code in zip(x, y, codes, strict=True):
        colour = POINT_COLOURS[int(code)]
        grobs.append(
            points_grob(
                unit(float(xi) * 72.0, "bigpts"),
                unit(float(yi) * 72.0, "bigpts"),
                pch=19,
                size=unit(7.0, "bigpts"),
                size_units="bigpts",
                gp=gpar(col=colour, fill=colour, lwd=0.0),
            )
        )
    return ir.encode(scene(grobs, tree).to_ir_scene())


# ---------------------------------------------------------------------------
# 三路同一张表 / 同一份 IR
# ---------------------------------------------------------------------------


def test_three_inputs_make_the_same_table() -> None:
    by_dict, by_pandas, by_arrow = _routes(DATA)
    assert by_dict == by_pandas == by_arrow
    assert [column.kind for column in by_dict.columns()] == ["float", "float", "str", "int", "bool"]


def test_three_inputs_encode_identical_ir_bytes() -> None:
    """dict / pandas / Arrow 三路输入 → 同一 scene → `ir.encode` 逐字节相等。"""
    by_dict, by_pandas, by_arrow = _routes(DATA)
    first = _scene_bytes(by_dict)
    assert first
    assert _scene_bytes(by_pandas) == first
    assert _scene_bytes(by_arrow) == first
    assert ir.decode(first) == ir.decode(_scene_bytes(by_arrow))


def test_to_column_table_passes_a_table_through() -> None:
    table = from_dict(DATA)
    assert to_column_table(table) is table


def test_to_column_table_rejects_unknown_inputs() -> None:
    with pytest.raises(TypeError, match=r"pandas\.DataFrame"):
        to_column_table([1, 2, 3])
    with pytest.raises(TypeError, match=r"pyarrow\.Table"):
        to_column_table(object())


def test_from_dict_rejects_ragged_and_scalar_columns() -> None:
    with pytest.raises(ValueError, match="行"):
        from_dict({"x": [1.0, 2.0], "y": [1.0]})
    with pytest.raises(TypeError, match="一维数组"):
        from_dict({"x": 1.0})
    with pytest.raises(ValueError, match="一维"):
        from_dict({"x": np.zeros((2, 2))})


# ---------------------------------------------------------------------------
# 分类顺序
# ---------------------------------------------------------------------------


def test_pandas_categorical_keeps_its_category_order() -> None:
    df = pd.DataFrame({"g": pd.Categorical(["b", "a", "b"], categories=["b", "a", "c"])})
    column = from_pandas(df).column("g")
    assert column.kind == "categorical"
    assert column.levels == ("b", "a", "c")
    assert column.values.tolist() == [0, 1, 0]


def test_arrow_dictionary_keeps_its_category_order() -> None:
    table = pa.table({"g": pa.array(["b", "a", "b"]).dictionary_encode()})
    column = from_arrow(table).column("g")
    assert column.kind == "categorical"
    assert column.levels == ("b", "a")
    assert column.values.tolist() == [0, 1, 0]


def test_plain_strings_get_sorted_levels_on_every_route() -> None:
    by_dict, by_pandas, by_arrow = _routes({"g": ["b", "c", "a", "b"]})
    for table in (by_dict, by_pandas, by_arrow):
        column = table.column("g")
        assert column.kind == "str"
        assert column.levels == ("a", "b", "c")


def test_categorical_na_is_masked_and_not_a_level() -> None:
    df = pd.DataFrame({"g": pd.Categorical(["b", None, "a"], categories=["a", "b"])})
    column = from_pandas(df).column("g")
    assert column.levels == ("a", "b")
    assert column.na_mask.tolist() == [False, True, False]
    assert column.values.tolist() == [1, 0, 0]


# ---------------------------------------------------------------------------
# 时间 / 时长
# ---------------------------------------------------------------------------


def test_datetime64_ns_becomes_posix_seconds() -> None:
    values = np.array(["1970-01-01T00:00:00", "2020-01-01T00:00:00"], dtype="datetime64[ns]")
    column = from_dict({"t": values}).column("t")
    assert column.kind == "datetime"
    assert column.values.dtype == np.float64
    assert column.values.tolist() == [0.0, 1577836800.0]
    # pandas / arrow 两条路同一口径
    assert from_pandas(pd.DataFrame({"t": pd.to_datetime(values)})) == from_dict({"t": values})
    assert from_arrow(pa.table({"t": pa.array(values)})) == from_dict({"t": values})


def test_timezone_aware_values_are_converted_to_utc() -> None:
    df = pd.DataFrame({"t": pd.to_datetime(["2020-01-01T08:00:00+08:00"], utc=True)})
    assert from_pandas(df).column("t").values.tolist() == [1577836800.0]
    # dict 路径里带时区的 python datetime 也先转 UTC
    aware = dt.datetime(2020, 1, 1, 8, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    assert from_dict({"t": [aware]}).column("t").values.tolist() == [1577836800.0]


def test_python_date_is_days_since_epoch() -> None:
    column = from_dict({"d": [dt.date(1970, 1, 3), dt.date(2020, 1, 1)]}).column("d")
    # Date 与 POSIXct 的日历单位不同（天 / 秒），kind 必须分开：默认标度靠这一位
    # 选 trans = "date"（SIL-800）。
    assert column.kind == "date"
    assert column.values.tolist() == [2.0, 18262.0]


def test_date_inputs_agree_across_the_three_routes() -> None:
    """python date / pandas object 列 / arrow date32 都落成同一条 `date` 列。"""
    values = [dt.date(2012, 2, 29), dt.date(2012, 6, 8), None]
    from_dict_table = from_dict({"d": values})
    from_pandas_table = to_column_table(pd.DataFrame({"d": values}))
    from_arrow_table = to_column_table(pa.table({"d": pa.array(values, type=pa.date32())}))
    column = from_dict_table.column("d")
    assert column.kind == "date"
    assert column.values.tolist() == [15399.0, 15499.0, 0.0]
    assert column.na_mask.tolist() == [False, False, True]
    assert from_dict_table == from_pandas_table == from_arrow_table


def test_all_missing_arrow_date_keeps_the_date_kind() -> None:
    table = to_column_table(pa.table({"d": pa.array([None, None], type=pa.date32())}))
    column = table.column("d")
    assert column.kind == "date"
    assert column.na_mask.tolist() == [True, True]


def test_timedelta_becomes_seconds() -> None:
    column = from_dict({"dt": np.array([1_500_000_000], dtype="timedelta64[ns]")}).column("dt")
    assert column.kind == "timedelta"
    assert column.values.tolist() == [1.5]
    assert from_dict({"dt": [dt.timedelta(seconds=2, milliseconds=500)]}).column(
        "dt"
    ).values.tolist() == [2.5]
    assert from_pandas(pd.DataFrame({"dt": pd.to_timedelta([1.5], unit="s")})) == from_dict(
        {"dt": [dt.timedelta(seconds=1.5)]}
    )


# ---------------------------------------------------------------------------
# 缺失
# ---------------------------------------------------------------------------


def test_nat_goes_to_the_mask() -> None:
    values = np.array(["2020-01-01T00:00:00", "NaT"], dtype="datetime64[ns]")
    column = from_dict({"t": values}).column("t")
    assert column.na_mask.tolist() == [False, True]
    assert column.values.tolist() == [1577836800.0, 0.0]

    df = pd.DataFrame({"t": pd.to_datetime(["2020-01-01T00:00:00", None], utc=True)})
    assert from_pandas(df).column("t").na_mask.tolist() == [False, True]


def test_none_and_nan_go_to_the_mask() -> None:
    column = from_dict({"x": [1.0, None, float("nan"), 4.0]}).column("x")
    assert column.kind == "float"
    assert column.na_mask.tolist() == [False, True, True, False]
    assert column.values.tolist() == [1.0, 0.0, 0.0, 4.0]


def test_pd_na_goes_to_the_mask() -> None:
    df = pd.DataFrame({"x": pd.array([1.0, None, 3.0], dtype="Float64")})
    column = from_pandas(df).column("x")
    assert column.na_mask.tolist() == [False, True, False]
    assert column.values.tolist() == [1.0, 0.0, 3.0]


def test_arrow_null_goes_to_the_mask() -> None:
    table = pa.table({"x": pa.array([1.0, None, 3.0], type=pa.float64())})
    column = from_arrow(table).column("x")
    assert column.kind == "float"
    assert column.na_mask.tolist() == [False, True, False]
    assert column.values.tolist() == [1.0, 0.0, 3.0]


def test_string_na_is_masked_and_not_a_level() -> None:
    column = from_dict({"g": ["b", None, "a"]}).column("g")
    assert column.levels == ("a", "b")
    assert column.na_mask.tolist() == [False, True, False]
    assert column.values.tolist() == ["b", "", "a"]
    assert from_pandas(pd.DataFrame({"g": ["b", None, "a"]})) == from_dict({"g": ["b", None, "a"]})


def test_all_missing_column_is_float_and_fully_masked() -> None:
    for table in (
        from_dict({"z": [None, None]}),
        to_column_table(pd.DataFrame({"z": [None, None]})),
        to_column_table(pa.table({"z": pa.array([None, None])})),
    ):
        column = table.column("z")
        assert column.kind == "float"
        assert column.na_mask.tolist() == [True, True]
        assert column.values.tolist() == [0.0, 0.0]


def test_all_missing_typed_columns_keep_their_kind() -> None:
    """源端带类型时，全缺列不该退化：pandas 与 arrow 两条路逐列相等。"""
    timestamps = (
        from_dict({"t": np.array(["NaT", "NaT"], dtype="datetime64[ns]")}),
        to_column_table(pd.DataFrame({"t": pd.to_datetime([None, None])})),
        to_column_table(pa.table({"t": pa.array([None, None], type=pa.timestamp("ns"))})),
    )
    for table in timestamps:
        column = table.column("t")
        assert column.kind == "datetime"
        assert column.na_mask.tolist() == [True, True]
    assert timestamps[0] == timestamps[1] == timestamps[2]

    booleans = (
        to_column_table(pd.DataFrame({"b": pd.array([None, None], dtype="boolean")})),
        to_column_table(pa.table({"b": pa.array([None, None], type=pa.bool_())})),
    )
    for table in booleans:
        column = table.column("b")
        assert column.kind == "bool"
        assert column.na_mask.tolist() == [True, True]
    assert booleans[0] == booleans[1]


def test_float32_columns_stay_float32_on_every_route() -> None:
    """三路同表要守住 dtype 口径：pandas 不能把 float32 悄悄抬成 float64。"""
    values = np.array([1.0, np.nan, 3.0], dtype=np.float32)
    by_dict = from_dict({"x": values})
    by_pandas = to_column_table(pd.DataFrame({"x": values}))
    by_arrow = to_column_table(pa.table({"x": pa.array(values)}))
    for table in (by_dict, by_pandas, by_arrow):
        column = table.column("x")
        assert column.values.dtype == np.float32
        assert column.na_mask.tolist() == [False, True, False]
    assert by_dict == by_pandas == by_arrow


# ---------------------------------------------------------------------------
# 整型退化
# ---------------------------------------------------------------------------


def test_int_column_without_missing_stays_int() -> None:
    for table in (
        from_dict({"n": np.array([1, 2, 3], dtype=np.int64)}),
        to_column_table(pd.DataFrame({"n": np.array([1, 2, 3], dtype=np.int64)})),
        to_column_table(pa.table({"n": pa.array([1, 2, 3], type=pa.int64())})),
    ):
        column = table.column("n")
        assert column.kind == "int"
        assert column.values.dtype == np.float64
        assert column.values.tolist() == [1.0, 2.0, 3.0]
        assert column.na_count == 0


def test_int_column_with_missing_degrades_to_float_plus_mask() -> None:
    cases = (
        from_dict({"n": [1, None, 3]}),
        to_column_table(pd.DataFrame({"n": pd.array([1, None, 3], dtype="Int64")})),
        to_column_table(pa.table({"n": pa.array([1, None, 3], type=pa.int64())})),
    )
    for table in cases:
        column = table.column("n")
        assert column.kind == "float"
        assert column.na_mask.tolist() == [False, True, False]
        assert column.values.tolist() == [1.0, 0.0, 3.0]
    assert cases[0] == cases[1] == cases[2]


# ---------------------------------------------------------------------------
# 依赖 / 报错文案
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("module", "call"),
    [("pandas", frame.from_pandas), ("pyarrow", frame.from_arrow)],
)
def test_missing_optional_dependency_points_at_pixi(monkeypatch, module, call) -> None:
    real_import = frame.importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == module:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(frame.importlib, "import_module", fake_import)
    with pytest.raises(ImportError) as excinfo:
        call(object())
    assert type(excinfo.value) is ImportError  # 不是原始 ModuleNotFoundError
    message = str(excinfo.value)
    assert module in message
    assert "pixi install -e dev" in message
    assert f"pixi add --feature dev --pypi {module}" in message


def test_unsupported_column_type_names_the_column() -> None:
    with pytest.raises(TypeError, match="列 'z'"):
        from_dict({"z": [1 + 2j]})
    with pytest.raises(TypeError, match="混了不兼容的类型"):
        from_dict({"z": [1, "a"]})
    with pytest.raises(TypeError, match="暂不支持"):
        from_arrow(pa.table({"z": pa.array([[1, 2]], type=pa.list_(pa.int64()))}))


# ---------------------------------------------------------------------------
# 批量路径（宽松的性能断言，不做门禁）
# ---------------------------------------------------------------------------


def test_million_row_dict_is_converted_in_bulk() -> None:
    rows = 1_000_000
    data = {
        "x": np.arange(rows, dtype=np.float64),
        "y": [float(index % 97) for index in range(rows)],
        "n": np.arange(rows, dtype=np.int64),
    }
    started = time.perf_counter()
    table = from_dict(data)
    elapsed = time.perf_counter() - started

    assert table.nrows == rows
    assert table.column("x").values[rows - 1] == rows - 1
    assert table.column("n").kind == "int"
    # 宽松：逐元素 Python 循环在 1e6 行上要几十秒，这里只守「别退化成循环」。
    assert elapsed < 5.0, f"dict → ColumnTable 用了 {elapsed:.2f}s（应 < 5s）"
