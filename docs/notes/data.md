# 输入适配口径：三种输入 → 一张列式表

M1-3 的流水线与 M1-2 的 aes 掩码都吃同一张列式表，所以 DataFrame-like 的解析
只做一次、只在一个地方定口径：

```
pandas.DataFrame ─┐
pyarrow.Table    ─┼─→ ggio.frame ─→ ggcore.data.ColumnTable ─→ aes / scale / IR
dict of arrays   ─┘
```

- 表本身在 `src/ggcore/data.py`：纯 numpy，X1 门禁守着（不 import pandas /
  pyarrow，连函数体内也不行）；
- 适配层在 `src/ggio/`（新包，`ggcore` 之外）：pandas / pyarrow 是**可选导入**，
  缺包时抛 `ImportError` 并指向 dev 环境与 `pixi add`；
- `import ggio` 只需要 numpy：prod 环境（没有 dev 依赖）能 import，只是用不了
  `from_pandas` / `from_arrow` 两条路径。验证命令要带 `PYTHONPATH=src`
  （`PYTHONPATH=src pixi run -e prod python -c "import ggio"`）：仓库是 src
  layout、没有 build backend，裸跑 `pixi run -e prod python -c "import ggio"` 报
  `ModuleNotFoundError` 是路径问题，不是 prod 环境的回归。

## 1. 入口

| 函数 | 输入 | 备注 |
| --- | --- | --- |
| `ggio.frame.to_column_table(obj)` | 三种都收；`ColumnTable` 原样返回 | 按类型分派，认不出就 `TypeError` 并列出支持的三种 |
| `ggio.frame.from_dict(data)` | 列名 → 一维数组的 mapping | 纯 numpy，不需要 pandas |
| `ggio.frame.from_pandas(frame)` | `pandas.DataFrame` | 保留列顺序与 `Categorical` 的 categories |
| `ggio.frame.from_arrow(table)` | `pyarrow.Table` / `RecordBatch` | 多 chunk 列先合并 |

三条路径共用同一套取值口径（`_column_from_array` 走 dtype 批量分支，
`_infer_objects` 处理 object 列），所以**同一份逻辑数据 + 同一份源端类型信息**
三路进来得到的表**逐列相等**，下游编出的 IR **逐字节相同**
（`tests/test_data_adapters.py` 的两条断言）。两条边界：数值缓冲跟随源端 dtype
（`float32` 三路都保 `float32`，`int` 一律以 `float64` 承载），全缺列见 §5。

## 2. `ColumnTable` / `Column` 契约

`ColumnTable`：有序列名 + `nrows`；`names` / `columns()` / `column(name)` 顺序
一致，缺列抛 `KeyError`（消息里列出已有列名）。所有列等长，重复列名直接报错。

`Column` 四件套：

| 字段 | 含义 |
| --- | --- |
| `kind` | `float` / `int` / `bool` / `str` / `categorical` / `datetime` / `date` / `timedelta` |
| `values` | 一维 bulk 缓冲；数值是 float32/float64，`int` 以 float64 承载，categorical 是 int32 code，`str` 是 numpy unicode 数组 |
| `levels` | 离散列的标度顺序（categorical 显式顺序；str 升序去重），不含 NA |
| `na_mask` | bool 数组，True = 缺失 |

缓冲建好即只读：`Column` 拿的是**自己的副本**（`values.setflags(write=False)`），
建成后连源数组的后续修改也影响不到表；`Column` / `ColumnTable` 的 `==` 是逐位
比较（kind + dtype + 形状 + 字节 + levels + mask），不是 `allclose`。

## 3. 分类顺序

- pandas `Categorical`：**保留 categories 顺序**，落成 `categorical` 列（int32
  code + `levels`）；`ordered=True/False` 不影响顺序，NA 的 code 是 `-1`，进
  `na_mask` 后缓冲里写 0。
- Arrow `dictionary`：保留 dictionary 顺序，同样落成 categorical。
- 普通字符串列（dict 的 `list[str]`、pandas object/string、arrow string）：
  `kind = "str"`，`levels` 是**升序去重**的非缺失值（ggplot2 离散标度的默认顺序）。
- NA 永远不进 `levels`；整列全空且源端不给类型（`[None, None]` 这类）时落成
  `float` + 全 True 的 mask（见 §5），不是「空 levels 的字符串列」；pandas
  datetime / bool / Categorical 与 arrow timestamp / boolean / dictionary 这类
  **带类型**的全缺列保原类型。

## 4. 时间

| 输入 | 落成 | 单位 |
| --- | --- | --- |
| numpy `datetime64[ns]` / pandas datetime（含 `DatetimeTZDtype`）/ arrow timestamp | `datetime` | float64 秒，自 1970-01-01 **UTC**（POSIXct） |
| 带时区的值 | 同上 | 先转 UTC 再算秒 |
| python `datetime.datetime` | `datetime` | 秒；naive 一律按 UTC 解释 |
| python `datetime.date` | `date` | **天**，自 1970-01-01 起 |
| arrow `date32/date64` | `date` | 天（走 python `date` 口径） |
| numpy `timedelta64` / pandas timedelta / python `timedelta` | `timedelta` | float64 秒 |

`date` 与 `datetime` 分成两个 kind 是为了**默认标度解析**（SIL-800）：前者选
`trans = "date"`、后者选 `trans = "time"`，与 R 的 `scale_type()` 区分 `Date` /
`POSIXct` 一致。pandas 的日期列只有 `datetime64`，所以 pandas 路径给的是
`datetime`（POSIXct 口径）；要 Date 口径请用 python `datetime.date` / arrow date。

秒数用 float64 承载，纳秒级精度在 2^53 之外会丢（2020 年已属正常范围），这是
「IR 只认 float32/float64 bulk 缓冲」的代价，也在 IR 之前就固定下来。

## 5. 缺失

- `NaN` / `None` / `pd.NA` / `NaT` / arrow null 一律进 `na_mask`；
- 数值缓冲里用 **0** 占位，bool 用 `False`，字符串用 `""`，categorical 用 code 0
  ——IR 侧只认 mask，占位值不参与计算；`Column` 构造时校验这条不变量；
- **带类型**的全缺列保留原类型：pandas `datetime64` / `boolean` / `Categorical`，
  arrow `timestamp` / `date` / `boolean` / `dictionary` → `datetime` / `date` /
  `bool` / `categorical` + 全 True 的 mask（pandas 与 arrow 两侧同一结果）；
- **没有类型信息**的全缺列（dict 的 `[None, None]`、pandas object 列、arrow
  `null` 类型）统一落成 `float` + 全 True 的 mask，三路一致；字符串全缺列
  （pandas string / arrow string）同样落 `float`（字符串没有可区分的标度类型）；
- 全缺的 `int64` / `Int64` 列按 §6 退化：`float` + 全 True 的 mask；
- 字符串列里 NA 不进 `levels`；numpy 的 `""` 是合法取值，不是缺失。

## 6. 整型

- arrow int / pandas int（含 `Int64` 等 nullable）/ numpy int 都保 `kind = "int"`；
  数值仍以 float64 bulk 缓冲承载（IR 的数值口径），`kind` 表示「语义上是整数」；
- **有缺失的整型列退化为 `float` + mask**：`[1, None, 3]` → `kind="float"`，
  `values=[1, 0, 3]`，`na_mask=[F, T, F]`。三条输入路径同一结果；
- `uint64` 超过 2^53 的值在 float64 里会丢精度，属于已知边界（ggplot2 的连续
  标度本身也是 double）。

## 7. 性能

数值 / bool / 字符串 / datetime 的 numpy 数组走 dtype 批量分支，1e6 行的
`dict → ColumnTable` 不做逐元素 Python 循环（`tests/test_data_adapters.py` 有一条
宽松的 `< 5s` 断言，不做门禁）。object 数组（含 python `date` / `datetime` 的混合
列）天生只能逐元素判断，这条路径慢是预期内的，数值列请直接给 typed numpy 数组；
`Decimal` 暂不支持（`_classify` 只认 `numbers.Real`，会抛 `TypeError`）。

## 8. 测试

- `tests/test_data.py`：`Column` / `ColumnTable` 的校验、只读（含源数组快照）、
  相等语义；
- `tests/test_data_adapters.py`：三路同表、**三路同 IR 字节**
  （`test_three_inputs_encode_identical_ir_bytes`）、分类顺序、时区、`NaT`、
  全缺列的带类型 / 不带类型两态、float32 三路一致、有缺失的整型、缺失哨兵、
  可选依赖文案、1e6 行批量。
