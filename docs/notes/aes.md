# aes 表达式口径：解析、白名单求值、数据掩码与自动分组

M1-2 把 `aes()` 里存下的原样表达式变成数组。三层严格分开：

```
aes(x="mpg / cyl")            # 构造：原样字符串（ggcore.aes，M1-1）
    ↓ parse_aes
AesSpec(tree, columns, …)     # 解析：语法树 + 引用列名 + 阶段（ggcore.eval）
    ↓ eval_aes(spec, table)
ndarray                       # 求值：ColumnTable → 数据掩码 → 白名单解释器
```

代码：`src/ggcore/aes.py`（`AesSpec` 容器）、`src/ggcore/eval.py`（解析 / 求值 /
分组）。测试：`tests/test_aes.py`、`tests/test_aes_eval.py`。

## 1. 表达式语法

字符串按 Python 的 `eval` 模式解析（`ast.parse(mode="eval")`），名字就是列：

| 写法 | 含义 |
| --- | --- |
| `aes(x="mpg / cyl")` | 两列相除（`mpg`、`cyl` 都是数据列） |
| `aes(colour="class")` | 离散列 `class` 直接参与映射 |
| `aes(y=after_stat("count"))` | stat 产出之后再求值（M1-8） |
| `aes(colour=1)`、`aes(size=3.5)` | 非字符串常量，求值时广播到 `nrows` |
| `aes(colour="'red'")` | 字符串**常量**要写成带引号的表达式（外层字符串是表达式） |
| `aes(x='col("mpg class")')` | 列名不是合法标识符（空格 / 标点）时的显式写法 |

键（aesthetic 名）按上游 `standardise_aes_names()` 标准化：`color`（含子串，
如 `point_color`）→ `colour`，`pch` → `shape`、`cex` → `size`、`lty` →
`linetype`、`lwd` → `linewidth`、`srt` → `angle`、`adj` → `hjust`、`bg` →
`fill`、`fg` → `colour`、`min` → `ymin`、`max` → `ymax`、`col` → `colour`。
标准化后重名（`color` 与 `colour` 同时出现）直接报错，不静默丢一个。

两点例外，都是为了让 mpg 这类真实数据可用：

- 整串是标识符但撞上 Python 关键字（`class`、`lambda` …）时按**列名**处理：
  `parse_aes` 合成一个 `Name` 节点，仍然过白名单；
- `col("列名")` 是唯一按字符串字面量取列的入口（`col(...)` 只收一个字面量，
  不接受变量 / 表达式），列名不会被当成函数名，也不会被拆成标识符。

函数名只在**调用位置**解析，列名在建值位置解析：数据里有叫 `log` 的列时，
`aes(x="log")` 取列，`aes(x="log(mpg)")` 调函数。

## 2. 白名单（求值路径不是任意代码执行）

`parse_aes` 先逐节点核对，`eval_aes` 再用一个**只认识白名单节点的解释器**求值：
全程不调用 `eval()` / `exec()` / `compile()`，手搓的 `AesSpec` 也绕不过去
（`tests/test_aes_eval.py::test_a_hand_built_spec_cannot_bypass_the_whitelist`）。

允许的节点：

| 类别 | 内容 |
| --- | --- |
| 值 | `Constant`（数字 / 字符串 / `bool` / `None`）、`Name`（列名，`__` 开头拒绝） |
| 算术 | `+ - * / // % **`，以及逐元素的 `&` / `\|` |
| 一元 | `+` / `-` |
| 比较 | `< <= > >= == !=`（支持链式，如 `18 <= mpg < 27`） |
| 逻辑 / 条件 | `and` / `or`（逐元素）、`a if cond else b`（数组条件走 `np.where`） |
| 调用 | 只允许下面函数表里的名字 |

函数表（`ggcore.eval.CALLABLES`，按需扩时同步改这里与 `FUNCTION_HINT`）：

- `np.log` / `np.log10` / `np.log2` / `np.sqrt` / `np.exp` / `np.abs` /
  `np.round` / `np.floor` / `np.ceil` / `np.where` / `np.isnan`，裸名
  `log` / `log10` / `log2` / `sqrt` / `exp` / `abs` / `round` / `floor` /
  `ceil` / `where` / `isnan` 等价（R 习惯的写法）；
- `min` / `max`：多参数逐元素（`np.minimum` / `np.maximum`），单参数整体归约；
- `col("列名")`：按字符串字面量取列。

拒绝（负向用例都在 `tests/test_aes_eval.py`）：

| 写法 | 结果 |
| --- | --- |
| `__import__("os")` | `AesWhitelistError`：`__import__` 不在函数表 |
| `open(...)` / `exec(...)` / `eval(...)` | 同上 |
| `mpg.__class__` | `AesWhitelistError`：非调用位置的属性访问 |
| `mpg.__class__()` | 同上：调用位置也不是白名单函数 |
| `mpg[0]` | `AesWhitelistError`：不允许下标 |
| `lambda` / 推导式 / f-string | `AesWhitelistError` |
| `*args` / `**kwargs` 展开 | `AesWhitelistError` |

验收里那条会写文件的表达式
`__import__("pathlib").Path(<tmp>).write_text("x")` 在 `parse_aes` 阶段就被拒绝，
测试同时断言目标文件不存在。

## 3. 报错

错误类型（都在 `ggcore.eval`，是 `ValueError` 的子类）：

| 类型 | 场景 |
| --- | --- |
| `AesParseError` | Python 语法错误 |
| `AesWhitelistError` | 语法合法但节点 / 函数 / 属性不在白名单 |
| `AesEvalError` | 白名单内求值失败：未知列、长度不符、类型不支持 |

消息统一带表达式、行号、列号与 `^` 指示，例如：

```
aes 表达式 `mpg / zzz` 第 1 行第 7 列：数据里没有列 'zzz'；可用列：mpg, cyl, class, drv
  mpg / zzz
        ^
```

未知列在数据阶段与 `eval_after_stat` 阶段分别列出「可用列」与「可用变量」。

## 4. 数据掩码与类型

`ColumnTable` → 求值用的 ndarray（`ggcore.eval._column_array`）：

| 列 kind | 求值时的数组 | 缺失（`na_mask`） |
| --- | --- | --- |
| `float` / `int` / `datetime` / `timedelta` | 保留源 dtype（float32 仍 float32；int 以 float64 承载） | `NaN` |
| `bool` | 无缺失时 `bool` 数组 | 有缺失退化成 float：`1.0` / `0.0` / `NaN` |
| `str` | `object` 数组，元素是 Python `str` | `None` |
| `categorical` | `object` 数组，元素取 `levels` 里的字符串 | `None` |

只解引用表达式真正用到的列（`AesSpec.columns`），不为一条 aes 拷贝整张表。
缺失不参与静默替换：数值运算按 `NaN` 传播，离散比较按 `None` 走。

## 5. 长度语义（对齐 R 的 recycling，但不静默截断）

| 结果长度 | 处理 |
| --- | --- |
| 标量（0 维） | 广播到 `nrows` |
| 1 | 广播到 `nrows` |
| `nrows` | 原样返回 |
| 其它 | `AesEvalError`（带表达式与位置） |

`eval_after_stat(values)` 对每个 stat 变量做同一套检查：所有变量长度必须一致
（或为 1）；不给 `nrows` 时按最长的变量推断，全是标量时按 1 行处理。

## 6. 自动分组（ggplot2 4.x `add_group()`）

`compute_groups(mapping, table)` 返回 `int32` 的 group id：

1. 显式 `aes(group=…)` 优先：`group` 的每个不同值一组；
2. 否则用**所有离散的 aes**（求值结果是字符 / 分类）做 interaction，`label` /
   `PANEL` 不参与；
3. 组合 id 按**首次出现**编号（0, 1, 2 …）；只出现过的组合占 id，未出现的组合
   不占（上游 `id(..., drop = TRUE)`）；
4. 没有任何离散 aes（也没有显式 `group`）时全部是 `NO_GROUP = -1`，
   `has_groups(ids)` 为 `False`；显式/自动分组从 0 开始；
5. 分组列里有 NA 的行给 `NO_GROUP`，留给 M1-3 的 `remove_missing`；
6. 常量映射不改变分组：常量 colour 只有一个水平，interaction 后仍是原分区；
7. `after_stat(...)` 的 aes 在数据阶段拿不到值，不参与分组（上游也是先丢弃
   calculated aes 再 `add_group()`）。

例：`class = [compact, compact, midsize, compact, suv]` →
`compute_groups(aes(colour="class"), table) == [0, 0, 1, 0, 2]`。

## 7. 边界

- 不做 stat 计算（M1-8）：`after_stat` 只解析 + 标记，`eval_aes` 明确拒绝它；
- 不做 scale 变换、不做图层流水线（M1-3）；
- 不引入第三方表达式库（numexpr / asteval 等）；求值器就是本文件里的递归解释器；
- 不支持下标 / 切片 / 属性 / lambda / 推导式；列名引用走 `col("…")`。
