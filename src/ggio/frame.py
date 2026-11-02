"""三种输入 → 同一份 `ggcore.data.ColumnTable`。

    from ggio.frame import to_column_table
    table = to_column_table(df)        # pandas.DataFrame / pyarrow.Table / dict

入口按类型分派（:func:`to_column_table`），也可以直接调 ``from_dict`` /
``from_pandas`` / ``from_arrow``。三条路径共用同一套取值口径（`_infer_objects`
与 `_column_from_array`），所以同一份逻辑数据无论从哪进来，得到的表逐列相等，
下游编出的 IR 逐字节相同（`tests/test_data_adapters.py`）。

口径摘要（全文见 `docs/notes/data.md`）：

- 普通字符串列按升序去重成 `levels`；pandas `Categorical` 保留 categories 顺序，
  落成 categorical 的 int32 code + levels；NA 只进 `na_mask`，不进 levels。
- `datetime64[ns]` → 自 1970-01-01 UTC 起的秒（POSIXct）；带时区的先转 UTC；
  python `datetime.date` → 自 1970-01-01 起的天数；`timedelta64` → 秒。
- NaN / None / pd.NA / NaT / arrow null 一律进 `na_mask`，缓冲里用 0 占位。
- arrow / pandas 的整型保 `int` kind；**有缺失**的整型列退化为 float + mask。
- 数值缓冲跟随源端 dtype：源端 float32 三路都保 float32（dict / pandas / arrow
  逐列相等），`int` 一律以 float64 承载。
- **带类型**的全缺列保原类型（pandas datetime / bool / Categorical，arrow
  timestamp / date / boolean / dictionary）；没有类型信息的全缺列统一落 float。
- pandas / pyarrow 是可选导入：没装时抛 ImportError，文案指向 dev 环境与 `pixi add`。
"""

from __future__ import annotations

import datetime as dt
import importlib
import math
import numbers
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ggcore.data import Column, ColumnTable

__all__ = ["SUPPORTED_INPUTS", "from_arrow", "from_dict", "from_pandas", "to_column_table"]

#: 认不出的输入类型在报错里列出的三种支持形态。
SUPPORTED_INPUTS = "dict of arrays（列名 → 一维数组）/ pandas.DataFrame / pyarrow.Table"

_EPOCH_DATE = dt.date(1970, 1, 1)
_EPOCH_DATETIME = dt.datetime(1970, 1, 1)
_UTC = dt.UTC
#: pandas 的缺失哨兵按类型名认，不用为此 import pandas（pd.NA / pd.NaT）。
_NA_TYPE_NAMES = frozenset({"NAType", "NaTType"})


# ---------------------------------------------------------------------------
# 可选依赖
# ---------------------------------------------------------------------------


def _require(module: str, purpose: str) -> Any:
    """可选导入：缺包时换成能照做的 ImportError，而不是裸 ModuleNotFoundError。"""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ImportError(
            f"{purpose} 需要 {module}，但当前环境没有安装。dev 环境已带 dev 依赖"
            f"（`pixi install -e dev` 后即可用）；要装进别的环境，用 "
            f"`pixi add --feature dev --pypi {module}`，不要直接 pip install。"
        ) from exc


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def to_column_table(obj: Any) -> ColumnTable:
    """按类型分派到 ``from_dict`` / ``from_pandas`` / ``from_arrow``。"""
    if isinstance(obj, ColumnTable):
        return obj
    if isinstance(obj, Mapping):
        return from_dict(obj)
    root = type(obj).__module__.split(".")[0]
    if root == "pandas":
        return from_pandas(obj)
    if root == "pyarrow":
        return from_arrow(obj)
    raise TypeError(
        f"不认识的输入类型 {type(obj).__module__}.{type(obj).__qualname__}；"
        f"支持：{SUPPORTED_INPUTS}"
    )


def from_dict(data: Mapping[str, Any]) -> ColumnTable:
    """dict of arrays → ColumnTable（纯 numpy，不需要 pandas）。"""
    if not isinstance(data, Mapping):
        raise TypeError(f"from_dict 需要 dict of arrays，收到 {type(data).__name__}")
    pairs: list[tuple[str, Column]] = []
    nrows: int | None = None
    for name, values in data.items():
        if not isinstance(name, str):
            raise TypeError(f"列名必须是 str，收到 {type(name).__name__}: {name!r}")
        column = _column_from_values(name, values)
        if nrows is None:
            nrows = column.size
        elif column.size != nrows:
            raise ValueError(f"列 {name!r} 有 {column.size} 行，前面的列是 {nrows} 行")
        pairs.append((name, column))
    return ColumnTable(pairs, nrows=0 if nrows is None else nrows)


def from_pandas(frame: Any) -> ColumnTable:
    """pandas.DataFrame → ColumnTable（保留列顺序与 Categorical 的 categories）。"""
    pd = _require("pandas", "ggio.frame.from_pandas")
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"from_pandas 需要 pandas.DataFrame，收到 {type(frame).__name__}")
    pairs: list[tuple[str, Column]] = []
    for position, name in enumerate(frame.columns):
        if not isinstance(name, str):
            raise TypeError(f"列名必须是 str（不支持 MultiIndex），第 {position} 列是 {name!r}")
        pairs.append((name, _column_from_series(frame.iloc[:, position], pd, name)))
    return ColumnTable(pairs, nrows=len(frame))


def from_arrow(table: Any) -> ColumnTable:
    """pyarrow.Table / RecordBatch → ColumnTable。"""
    pa = _require("pyarrow", "ggio.frame.from_arrow")
    if not isinstance(table, (pa.Table, pa.RecordBatch)):
        raise TypeError(f"from_arrow 需要 pyarrow.Table，收到 {type(table).__name__}")
    pairs: list[tuple[str, Column]] = []
    for position, name in enumerate(table.schema.names):
        if not isinstance(name, str):
            raise TypeError(f"列名必须是 str，第 {position} 列是 {name!r}")
        column = table.column(position)
        if isinstance(column, pa.ChunkedArray):  # Table 的列可能是多 chunk
            column = column.combine_chunks()
        pairs.append((name, _column_from_arrow_array(column, pa, name)))
    return ColumnTable(pairs, nrows=table.num_rows)


# ---------------------------------------------------------------------------
# 取值口径：numpy 数组 / python 对象序列 → Column
# ---------------------------------------------------------------------------


def _column_from_values(name: str, values: Any) -> Column:
    if isinstance(values, np.ndarray):
        array = values
    else:
        if isinstance(values, (str, bytes)) or not hasattr(values, "__len__"):
            raise TypeError(
                f"列 {name!r} 必须是一维数组，收到 {type(values).__name__}"
                f"（{SUPPORTED_INPUTS} 的列都要给整列，不是标量）"
            )
        array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(f"列 {name!r} 必须是一维数组，实际是 {array.shape}")
    if array.dtype.kind in ("U", "S") and not isinstance(values, np.ndarray):
        # np.asarray([1, "a"]) 会把数字悄悄 stringify 成 "1"；不许混型。
        stray = sorted({type(item).__name__ for item in values if not isinstance(item, str)})
        if stray:
            raise TypeError(
                f"列 {name!r} 混了不兼容的类型：str, {', '.join(stray)}；"
                "同一列要么数值、要么字符串、要么日期时间"
            )
    return _column_from_array(array, name)


def _column_from_array(array: np.ndarray[Any, Any], name: str) -> Column:
    """按 numpy dtype 走批量路径（不做逐元素 Python 循环）。"""
    kind = array.dtype.kind
    if kind == "f":
        mask = np.isnan(array)
        if mask.any():  # 缺失只进 mask，缓冲里留 0（占位值不参与计算）
            array = array.copy()
            array[mask] = 0.0
        return Column("float", array, na_mask=mask)
    if kind in ("i", "u"):
        # numpy 的整型数组没有 NA 位；有缺失的整型在进这里之前已是 float。
        return Column("int", array.astype(np.float64))
    if kind == "b":
        return Column("bool", array)
    if kind == "M":
        ns = array.astype("datetime64[ns]")
        mask = np.isnat(ns)
        seconds = np.where(mask, 0, ns.view("i8")).astype(np.float64) / 1e9
        return Column("datetime", seconds, na_mask=mask)
    if kind == "m":
        ns = array.astype("timedelta64[ns]")
        mask = np.isnat(ns)
        seconds = np.where(mask, 0, ns.view("i8")).astype(np.float64) / 1e9
        return Column("timedelta", seconds, na_mask=mask)
    if kind in ("U", "S"):
        values = array.astype(str)
        levels = tuple(str(level) for level in np.unique(values))
        return Column("str", values, levels=levels)
    if kind == "O":
        return _infer_objects(array, name)
    raise TypeError(
        f"列 {name!r} 的 dtype {array.dtype} 暂不支持；"
        f"支持数值 / bool / 字符串 / 日期时间（{SUPPORTED_INPUTS}）"
    )


def _is_missing(value: Any) -> bool:
    """None / NaN / pd.NA / NaT / numpy NaT 都算缺失。"""
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, np.floating):
        return bool(np.isnan(value))
    if isinstance(value, (np.datetime64, np.timedelta64)):
        return bool(np.isnat(value))
    return type(value).__name__ in _NA_TYPE_NAMES


def _classify(value: Any) -> str:
    """python 取值的类别；bool 必须排在 int 前面（True 也是 int）。"""
    if isinstance(value, (bool, np.bool_)):
        return "bool"
    if isinstance(value, numbers.Integral):
        return "int"
    if isinstance(value, numbers.Real):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, np.datetime64):
        return "datetime"
    if isinstance(value, np.timedelta64):
        return "timedelta"
    if isinstance(value, dt.datetime):
        return "datetime"
    if isinstance(value, dt.date):
        return "date"
    if isinstance(value, dt.timedelta):
        return "timedelta"
    raise TypeError(
        f"不支持的取值类型 {type(value).__name__}（{value!r}）；"
        "列里只能有数值 / bool / 字符串 / 日期时间"
    )


#: 类别 → 一族取值，同族可以共存（int + float 都是数值）。
_FAMILY = {
    "bool": "bool",
    "int": "number",
    "float": "number",
    "str": "str",
    "datetime": "datetime",
    "date": "date",
    "timedelta": "timedelta",
}


def _datetime_seconds(value: Any) -> float:
    if isinstance(value, np.datetime64):
        ticks = value.astype("datetime64[ns]").view("i8")
        return float(ticks) / 1e9
    moment = value
    if moment.tzinfo is not None:
        moment = moment.astimezone(_UTC).replace(tzinfo=None)
    return (moment - _EPOCH_DATETIME).total_seconds()


def _timedelta_seconds(value: Any) -> float:
    if isinstance(value, np.timedelta64):
        ticks = value.astype("timedelta64[ns]").view("i8")
        return float(ticks) / 1e9
    return float(value.total_seconds())


def _infer_objects(values: Sequence[Any], name: str) -> Column:
    """object 列：先摘出缺失，再按非缺失值的类别选 kind。

    这条路径天生是逐元素的（object 数组没有 dtype 可批量判断）；数值列请直接给
    numpy 数组，那样走的是 :func:`_column_from_array` 的批量分支。
    """
    items = [item for item in values]
    mask = np.fromiter((_is_missing(item) for item in items), dtype=bool, count=len(items))
    present = [item for item, missing in zip(items, mask, strict=True) if not missing]
    if not present:
        return Column("float", np.zeros(len(items), dtype=np.float64), na_mask=mask)

    try:
        families = {_FAMILY[_classify(item)] for item in present}
    except TypeError as exc:
        raise TypeError(f"列 {name!r}：{exc}") from None
    if len(families) > 1:
        kinds = sorted({type(item).__name__ for item in present})
        raise TypeError(
            f"列 {name!r} 混了不兼容的类型：{', '.join(kinds)}；"
            "同一列要么数值、要么字符串、要么日期时间"
        )
    family = families.pop()

    if family == "bool":
        data = np.fromiter(
            (False if missing else bool(item) for item, missing in zip(items, mask, strict=True)),
            dtype=bool,
            count=len(items),
        )
        return Column("bool", data, na_mask=mask)

    if family == "number":
        data = np.fromiter(
            (0.0 if missing else float(item) for item, missing in zip(items, mask, strict=True)),
            dtype=np.float64,
            count=len(items),
        )
        # 有缺失的整型列退化为 float + mask（docs/notes/data.md §5）。
        if mask.any() or any(isinstance(item, (float, np.floating)) for item in present):
            return Column("float", data, na_mask=mask)
        return Column("int", data)

    if family == "str":
        data = np.asarray(
            ["" if missing else str(item) for item, missing in zip(items, mask, strict=True)],
            dtype=str,
        )
        levels = tuple(sorted({str(item) for item in present}))
        return Column("str", data, levels=levels, na_mask=mask)

    if family == "datetime":
        data = np.fromiter(
            (
                0.0 if missing else _datetime_seconds(item)
                for item, missing in zip(items, mask, strict=True)
            ),
            dtype=np.float64,
            count=len(items),
        )
        return Column("datetime", data, na_mask=mask)

    if family == "date":
        data = np.fromiter(
            (
                0.0 if missing else float((item - _EPOCH_DATE).days)
                for item, missing in zip(items, mask, strict=True)
            ),
            dtype=np.float64,
            count=len(items),
        )
        return Column("datetime", data, na_mask=mask)

    # family == "timedelta"
    data = np.fromiter(
        (
            0.0 if missing else _timedelta_seconds(item)
            for item, missing in zip(items, mask, strict=True)
        ),
        dtype=np.float64,
        count=len(items),
    )
    return Column("timedelta", data, na_mask=mask)


# ---------------------------------------------------------------------------
# pandas
# ---------------------------------------------------------------------------


def _column_from_series(series: Any, pd: Any, name: str) -> Column:
    dtype = series.dtype
    api = pd.api.types

    if isinstance(dtype, pd.CategoricalDtype):
        levels = tuple(str(level) for level in dtype.categories)
        codes = series.cat.codes.to_numpy(dtype=np.int32, copy=True)
        mask = codes < 0
        codes = np.where(mask, 0, codes).astype(np.int32)
        return Column("categorical", codes, levels=levels, na_mask=mask)

    if isinstance(dtype, pd.DatetimeTZDtype):
        # 带时区先转 UTC，再按 naive 的 datetime64[ns] 口径算秒。
        local = series.dt.tz_convert("UTC").dt.tz_localize(None)
        return _column_from_array(local.to_numpy(dtype="datetime64[ns]"), name)

    if api.is_datetime64_any_dtype(dtype):
        return _column_from_array(series.to_numpy(dtype="datetime64[ns]"), name)

    if api.is_timedelta64_dtype(dtype):
        return _column_from_array(series.to_numpy(dtype="timedelta64[ns]"), name)

    if api.is_bool_dtype(dtype):
        mask = np.asarray(series.isna(), dtype=bool)
        values = np.asarray(series.fillna(False), dtype=bool)
        return Column("bool", values, na_mask=mask)

    if api.is_integer_dtype(dtype):
        mask = np.asarray(series.isna(), dtype=bool)
        if mask.any():
            # 有缺失的整型列退化为 float + mask（docs/notes/data.md §5）
            values = series.to_numpy(dtype="float64", na_value=np.nan)
            return _column_from_array(np.asarray(values, dtype=np.float64), name)
        return Column("int", np.asarray(series.to_numpy(dtype="float64"), dtype=np.float64))

    if api.is_float_dtype(dtype):
        # 跟随源端 dtype：DataFrame 的 float32 列不该在这里被悄悄抬成 float64
        # （dict / arrow 两条路都保留 float32，抬上去三路就不逐列相等了）。
        target = np.dtype(getattr(dtype, "numpy_dtype", dtype))
        return _column_from_array(series.to_numpy(dtype=target, na_value=np.nan), name)

    return _infer_objects(series.to_numpy(dtype=object, na_value=None), name)


# ---------------------------------------------------------------------------
# Arrow
# ---------------------------------------------------------------------------


def _column_from_arrow_array(array: Any, pa: Any, name: str) -> Column:
    arrow_type = array.type

    if pa.types.is_dictionary(arrow_type):
        levels = tuple(str(level) for level in array.dictionary.to_pylist())
        indices = array.indices
        mask = np.asarray(indices.is_null().to_numpy(zero_copy_only=False), dtype=bool)
        raw = np.nan_to_num(np.asarray(indices.to_numpy(zero_copy_only=False)), nan=0.0)
        codes = np.where(mask, 0, raw).astype(np.int32)
        return Column("categorical", codes, levels=levels, na_mask=mask)

    if pa.types.is_null(arrow_type):
        return Column(
            "float",
            np.zeros(len(array), dtype=np.float64),
            na_mask=np.ones(len(array), dtype=bool),
        )

    if len(array) and array.null_count == len(array):
        # 带类型但全缺：to_pylist / to_numpy 只剩 [None, ...]，类型信息只在 schema
        # 里。按 schema 保住 kind，pandas 才能与 arrow 逐列相等（docs/notes/data.md §5）。
        all_missing = np.ones(len(array), dtype=bool)
        if pa.types.is_boolean(arrow_type):
            return Column("bool", np.zeros(len(array), dtype=np.bool_), na_mask=all_missing)
        if pa.types.is_timestamp(arrow_type) or pa.types.is_date(arrow_type):
            return Column("datetime", np.zeros(len(array), dtype=np.float64), na_mask=all_missing)

    if (
        pa.types.is_string(arrow_type)
        or pa.types.is_large_string(arrow_type)
        or pa.types.is_timestamp(arrow_type)
        or pa.types.is_date(arrow_type)
    ):
        # 字符串列本来就是 object；arrow timestamp → python datetime（秒），
        # arrow date → python date（天）。pandas 的日期列是 datetime64，走秒口径。
        return _infer_objects(np.asarray(array.to_pylist(), dtype=object), name)

    if (
        pa.types.is_integer(arrow_type)
        or pa.types.is_floating(arrow_type)
        or pa.types.is_boolean(arrow_type)
    ):
        # 有 null 的整型 / bool 在这里落成 float+NaN 或 object+None，再按统一口径退化。
        return _column_from_array(np.asarray(array.to_numpy(zero_copy_only=False)), name)

    raise TypeError(
        f"列 {name!r} 的 Arrow 类型 {arrow_type} 暂不支持；"
        f"支持数值 / bool / 字符串 / 日期时间（{SUPPORTED_INPUTS}）"
    )
