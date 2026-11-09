# 数据输入

`ggcore` 只认一种表：`ggcore.data.ColumnTable`（列式、只读缓冲）。DataFrame-like
的解析只在 `ggio` 里做一次：

```
pandas.DataFrame ─┐
pyarrow.Table    ─┼─→ ggio.frame ─→ ggcore.data.ColumnTable ─→ aes / scale / IR
dict of arrays   ─┘
```

`ggio` 在 `ggcore` 之外，pandas / pyarrow 是**可选导入**：没装就报 `ImportError`，
不会把 pandas 拖进内核（X1 门禁守着这条）。

## 1. 三个入口

| 函数 | 输入 | 备注 |
| --- | --- | --- |
| `gg4py.to_column_table(obj)` | 三种都收；已经是 `ColumnTable` 就原样返回 | 按类型分派，认不出报错并列出支持的三类 |
| `gg4py.from_dict(data)` | 列名 → 一维数组 | 纯 numpy，不碰 pandas |
| `gg4py.from_pandas(frame)` | `pandas.DataFrame` | 保列顺序与 `Categorical` 的 categories |
| `gg4py.from_arrow(table)` | `pyarrow.Table` / `RecordBatch` | 多 chunk 先合并 |

```python
from gg4py import aes, geom_point, ggplot, labs, to_column_table

DATA = {"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 1.5, 4.2, 3.1], "g": ["a", "b", "a", "b"]}

data = to_column_table(DATA)
print(data)  # ColumnTable(nrows=4, names=('x', 'y', 'g'))
print(data.column("g").kind)  # str
print(data.column("g").levels)  # ('a', 'b') —— 离散列的标度顺序

p = ggplot(data, aes(x="x", y="y", colour="g")) + geom_point(size=3) + labs(title="dict of arrays")
```

**同一份逻辑数据，三条路径得到的表逐列相等**，编出的 IR 逐字节相同——这也是
`editor:check` / `gate:pyodide` 能用 sha256 对拍的前提。

## 2. pandas：分类顺序

普通字符串列按**升序去重**得到 levels；pandas `Categorical` 保 `categories` 顺序
（`ordered` 与否不影响）。想让柱子按自定义顺序排，用 `Categorical`：

```python
import pandas as pd

from gg4py import aes, from_pandas, geom_col, ggplot, labs

FRAME = pd.DataFrame(
    {
        "level": pd.Categorical(
            ["high", "low", "mid", "high", "mid", "low"],
            categories=["low", "mid", "high"],  # 想要的顺序
        ),
        "n": [12.0, 31.0, 20.0, 15.0, 24.0, 28.0],
    }
)

data = from_pandas(FRAME)
print(data.column("level").kind)  # categorical
print(data.column("level").levels)  # ('low', 'mid', 'high')

p = (
    ggplot(data, aes(x="level", y="n"))
    + geom_col(fill="#4C78A8")
    + labs(title="Categorical keeps its order", x="level", y="n")
)
```

不写 `Categorical` 时字符串列按字母序（`high` < `low` < `mid`）。另一种办法是给
标度传 `limits`（见 [`scale.md`](scale.md)）。

## 3. Arrow

```python
import pyarrow as pa

from gg4py import aes, from_arrow, geom_point, ggplot, labs

TABLE = pa.table(
    {
        "x": [1.0, 2.0, 3.0, 4.0],
        "y": [2.0, 1.5, 4.2, 3.1],
        "g": ["a", "b", "a", "b"],
    }
)

data = from_arrow(TABLE)
p = (
    ggplot(data, aes(x="x", y="y", colour="g"))
    + geom_point(size=3)
    + labs(title="pyarrow.Table input")
)
```

Arrow 的 `dictionary` 列与 pandas 的 `Categorical` 一样保留字典顺序。

## 4. 缺失、类型与日期

| 源 | 落成 |
| --- | --- |
| `None` / `float("nan")` / `pandas.NA` / `pd.NaT` / Arrow null | 缺失掩码（缓冲里写 0，绘图时该行删掉） |
| `int` | 内部以 float64 承载；有缺失的整型列退化为 float + 掩码 |
| `float32` | 三路输入都保 float32 |
| `datetime.date` | `kind="date"`（自 1970-01-01 起的天） |
| `datetime.datetime` | `kind="datetime"`（自 1970-01-01 UTC 起的秒） |
| `bool` | `kind="bool"` |
| 字符串 | `kind="str"`，levels 升序去重 |
| 全缺失且没有类型信息 | float 列，全缺失 |

日期列配对应的标度：`Date` 用 `scale_x_date()`，`POSIXct`（`datetime`）用
`scale_x_datetime()`——**`datetime` 不能喂 `scale_x_date()`**（上游同样拒绝）。

```python
import datetime as dt

from gg4py import aes, geom_line, geom_point, ggplot, labs, scale_x_date, to_column_table

DATA = {
    "date": [dt.date(2020, m, 1) for m in range(1, 7)],
    "value": [12.0, 15.0, None, 19.0, 22.0, 21.0],  # None = 缺失
}

data = to_column_table(DATA)
print(data.column("date").kind)  # date
print(data.column("value").na_mask)  # [False False  True False False False]

p = (
    ggplot(data, aes(x="date", y="value"))
    + geom_line()
    + geom_point(size=2.5)
    + scale_x_date(date_breaks="1 month", date_labels="%b")
    + labs(title="dates and one missing value", x=None, y="value")
)
```

缺失行在几何层被删掉（`geom_line()` 断线，`geom_point()` 少一个点），与 R 的
`na.rm = FALSE` 默认行为一致；想让缺失显示出来就显式换标度或补值。

## 5. CSV（编辑器 / 脚本）

`ggio.csv.read_csv()` 只用标准库，不需要 pandas：

```python
from gg4py import aes, geom_col, ggplot, labs
from ggio.csv import read_csv

CSV_TEXT = """class,value
a,3.2
b,4.8
c,2.1
d,5.6
"""

data = read_csv(CSV_TEXT)  # 也可以传文件路径
print(data.names)  # ('class', 'value')

p = ggplot(data, aes(x="class", y="value")) + geom_col(fill="#4C78A8") + labs(title="CSV input")
```

口径：首行表头（去空白；空列名 / 重名列直接报错）、空单元格与
`NA`/`NaN`/`null`/`none` 算缺失、全整数列 → int、其余数值列 → float、其它 →
字符串；分隔符默认 `,`，`;` / 制表符显式传 `delimiter=`；文件按 UTF-8 读。
浏览器编辑器在「数据输入」面板里贴的 CSV 会被写到虚拟文件系统的 `data.csv`，
脚本写 `read_csv("data.csv")` 即可（见 [`browser.md`](browser.md)）。

## 6. 一张图，多份数据

`ggplot(data)` 是默认数据；图层可以覆盖（见 [`aes.md`](aes.md) §6）。所有 `data=`
都要求是 `ColumnTable`——**直接传 dict / DataFrame 能构造 `ggplot`，但构图期会
报错**，这是最常见的第一个坑：

```python
from gg4py import aes, geom_point, ggplot, to_column_table

DATA = {"x": [1, 2, 3], "y": [3, 1, 2]}

good = ggplot(to_column_table(DATA), aes(x="x", y="y")) + geom_point()
bad = ggplot(DATA, aes(x="x", y="y")) + geom_point()  # 能构造，构图期才报错
print(repr(good), repr(bad))  # 两者都打印 3×2
```

（这段只演示构造；`bad` 没有被构建，所以示例本身不报错。）

数据列在构造时被复制并设成只读：之后改源数组不会影响已经建好的表，`Column` /
`ColumnTable` 的 `==` 是逐位比较（kind + dtype + 形状 + 字节 + levels + mask）。

## 7. 边界

- `ggio` 的 pandas / Arrow 路径是可选导入；prod 环境只有 numpy。用前确认
  `pixi run -e dev python -c "import pandas"` 能过。
- 表是**不可变**的：改数据就重建一张表，不要原地改 `values`。
- 列名必须唯一；重复列名在构造时报错（不是静默改名）。
- 一个大列（10 万点）直接进 IR 是允许的；`geom_point(max_points=N)` 可以按行号
  等距降采样（`docs/notes/performance.md`），默认不降。
