"""CSV → `ColumnTable`（编辑器与脚本的数据输入）。

浏览器编辑器里有两个数据入口：**内联数据**（直接写在 Python 里）与 **CSV**（粘贴
或打开 `.csv` 文件）。CSV 这一条不能指望 pandas——Pyodide 里的 pandas 是懒加载的
轮子，「贴一段 CSV 看一下」不该先把 8 MB 拉下来。所以这里只用标准库 `csv`，把
每一列按「全整数 → int，全数值 → float，其余 → str」推断，空串与 `NA` / `NaN`
落成缺失，再交给 `ggio.frame.from_dict()` 走与其它输入同一条归一化路径（列类型、
levels 顺序、缺失掩码都一样，因此 IR 也逐字节一致）。

    from ggio.csv import read_csv
    table = read_csv("/app/data.csv")          # 编辑器数据面板写入的文件
    table = read_csv("x,y\\n1,2\\n3,4\\n")        # 也可以直接给一段文本

口径：

- 首行是列名；列名去首尾空白，重名直接报错（静默改名会让后续 `aes(x=...)` 出错）；
- 数值列里的空单元格 = 缺失；整列都是空 → 该列是 float 且全缺失；
- 不加任何 `sep` 猜测：分隔符默认 `,`，`;`/`\\t` 显式传 `delimiter=`；
- 不做编码探测：文件按 UTF-8 读（Pyodide 里的文本文件也一样）。
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from ggio.frame import from_dict

__all__ = ["read_csv"]

#: 认作缺失的字面量（大小写不敏感）。`NA` / `NaN` / `null` 是 R / pandas / JSON
#: 三边最常见的三种写法。
_MISSING = frozenset({"", "na", "nan", "null", "none"})


def _rows(source: Any, delimiter: str) -> tuple[list[str], list[list[str]]]:
    if isinstance(source, (str, bytes)):
        text = source.decode("utf-8") if isinstance(source, bytes) else source
        # 一段文本 vs 一个路径：带换行的一律当文本，避免把整段 CSV 当文件名。
        if "\n" in text or "\r" in text or not Path(text).exists():
            return _parse(text, delimiter)
        return _parse(Path(text).read_text(encoding="utf-8"), delimiter)
    path = Path(source)
    return _parse(path.read_text(encoding="utf-8"), delimiter)


def _parse(text: str, delimiter: str) -> tuple[list[str], list[list[str]]]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("CSV 是空的：至少要有表头与一行数据")
    header = [cell.strip() for cell in rows[0]]
    if any(not name for name in header):
        raise ValueError(f"CSV 表头有空列名：{rows[0]!r}")
    duplicates = sorted({name for name in header if header.count(name) > 1})
    if duplicates:
        raise ValueError(f"CSV 表头里有重名列：{', '.join(duplicates)}")
    body = rows[1:]
    for index, row in enumerate(body, start=2):
        if len(row) != len(header):
            raise ValueError(
                f"CSV 第 {index} 行有 {len(row)} 个字段，表头是 {len(header)} 个：{row!r}"
            )
    return header, body


def _is_missing(cell: str) -> bool:
    return cell.strip().lower() in _MISSING


def _column(cells: list[str]) -> list[Any]:
    """一列文本 → Python 值列表（缺失 = None，数值尽量转数字）。"""
    present = [cell.strip() for cell in cells if not _is_missing(cell)]
    if not present:
        return [None] * len(cells)

    as_int = True
    as_float = True
    for value in present:
        if not as_int and not as_float:
            break
        try:
            int(value)
        except ValueError:
            as_int = False
        try:
            float(value)
        except ValueError:
            as_float = False

    out: list[Any] = []
    for cell in cells:
        if _is_missing(cell):
            out.append(None)
            continue
        text = cell.strip()
        if as_int:
            out.append(int(text))
        elif as_float:
            out.append(float(text))
        else:
            out.append(text)
    return out


def read_csv(source: Any, *, delimiter: str = ",") -> Any:
    """读一段 CSV 文本或一个文件路径，返回 `ggcore.data.ColumnTable`。"""
    header, body = _rows(source, delimiter)
    columns = {
        name: _column([row[position] for row in body]) for position, name in enumerate(header)
    }
    return from_dict(columns)
