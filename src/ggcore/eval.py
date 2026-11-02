"""`ggcore.eval` —— aes 表达式层：解析、白名单 AST 求值、数据掩码与自动分组。

用户写的是字符串表达式（R 语法在该项目里的 Python 写法）：

    aes(x="mpg / cyl", colour="class")        # 列名就是表达式里的名字
    aes(y=after_stat("count"))                # stat 之后才存在的变量

三层边界（`docs/notes/aes.md` 是完整口径）：

1. :func:`parse_aes` 只做 `ast.parse(mode="eval")`，然后**逐节点核对白名单**；
2. :func:`eval_aes` 用自己写的解释器求值——**不调用 `eval` / `exec` / `compile`**，
   只认识下面 `_BINOPS` / `_UNARY` / `_CMP` / `CALLABLES` 里的东西；
3. :func:`compute_groups` 按 ggplot2 4.x 的 `add_group()` 口径推分组：显式
   `group` 优先，否则用所有离散（字符/分类）aes 做 interaction，组合按值域排序
   编号（上游 `id()` 的 `sort(unique())` 口径）；NA 行给 :data:`NO_GROUP`（-1），
   留给 M1-3 的 `remove_missing`。

安全口径（本任务的核心验收）：

- `ast.Attribute` **只在调用位置**、且点分名在 :data:`CALLABLES` 里才被接受；
  `x.__class__`、`().__class__.__bases__[0]` 一律报错；
- 下标、lambda、推导式、f-string、赋值（`ast.parse(..., mode="eval")` 本来就
  没有语句）、`open` / `__import__` / `exec` / `eval` 都不在节点表或函数表里；
- 报错是 :class:`AesError` 家族（`ValueError` 子类），中文消息里带表达式、
  行号、列号与 `^` 指示，绝不静默吞掉。

长度语义（对齐 R 的 recycling，但不做静默截断）：

| 结果长度 | 处理 |
| --- | --- |
| 标量（0 维） | 广播到 `nrows` |
| 1 | 广播到 `nrows` |
| `nrows` | 原样返回 |
| 其它 | :class:`AesEvalError`（带行号列号） |

`after_stat(...)` 的表达式在数据阶段不参与求值：`eval_aes` 会拒绝它，改由
:func:`eval_after_stat` 在 M1-8 产出 stat 变量之后求值。
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.aes import Aes, AesSpec, AfterStat, as_aes
from ggcore.data import Column, ColumnTable

__all__ = [
    "CALLABLES",
    "NO_GROUP",
    "AesError",
    "AesEvalError",
    "AesParseError",
    "AesWhitelistError",
    "compute_groups",
    "eval_aes",
    "eval_after_stat",
    "has_groups",
    "parse_aes",
]

#: 「没有分组」的哨兵，照抄 ggplot2 的 `NO_GROUP`。显式/自动分组从 0 开始编号。
NO_GROUP = -1

#: 自动分组时不参与 interaction 的名字：上游排除 `label` / `PANEL`；`group`
#: 单独处理（有显式 group 就直接用它，不再看别的 aes）。
_GROUP_EXCLUDED = frozenset({"label", "PANEL", "group"})


# ---------------------------------------------------------------------------
# 错误
# ---------------------------------------------------------------------------


class AesError(ValueError):
    """aes 表达式层的基类；能定位到节点时，消息里带表达式与行列位置。"""


class AesParseError(AesError):
    """Python 语法错误（`ast.parse` 失败）。"""


class AesWhitelistError(AesError):
    """语法合法，但节点 / 函数 / 属性不在白名单里。"""


class AesEvalError(AesError):
    """白名单内，但求值失败：未知列、长度不符、类型不支持等。"""


# ---------------------------------------------------------------------------
# 白名单
# ---------------------------------------------------------------------------


def _float_power(left: Any, right: Any) -> Any:
    """`**` 按 R 的 `^` 口径走 double：`2 ** 3` 是 8（double）。

    如果照 Python 的整数幂走，`10 ** 10 ** 10` 会算一个十亿位的大整数——表达式
    由用户提供，这会让求值线程（浏览器里就是整个页面）挂死。R 在这里直接得到
    `Inf`，所以转 float64 既对齐上游，也堵掉这条 DoS。
    """
    # R 的算术对上溢 / NaN 不报警，这里同样静默（结果仍是 Inf / NaN）。
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        return np.power(
            np.asarray(left, dtype=np.float64),
            np.asarray(right, dtype=np.float64),
        )


_BINOPS: Mapping[type[ast.operator], Callable[[Any, Any], Any]] = MappingProxyType(
    {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: _float_power,
        # `&` / `|` 是逐元素逻辑（numpy 数组上比 Python 的 `and/or` 好用），
        # 也是 R 里 `&` / `|` 的直接对应；`and/or` 见 ast.BoolOp。
        ast.BitAnd: np.logical_and,
        ast.BitOr: np.logical_or,
    }
)


_UNARY: Mapping[type[ast.unaryop], Callable[[Any], Any]] = MappingProxyType(
    {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }
)

_CMP: Mapping[type[ast.cmpop], Callable[[Any, Any], Any]] = MappingProxyType(
    {
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
    }
)

_OP_SYMBOLS: Mapping[type[ast.AST], str] = MappingProxyType(
    {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.FloorDiv: "//",
        ast.Mod: "%",
        ast.Pow: "**",
        ast.BitAnd: "&",
        ast.BitOr: "|",
        ast.UAdd: "+",
        ast.USub: "-",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.And: "and",
        ast.Or: "or",
    }
)


def _elementwise_min(*values: Any) -> Any:
    if not values:
        raise TypeError("min() 至少需要一个参数")
    if len(values) == 1:
        return np.min(values[0])
    result = values[0]
    for value in values[1:]:
        result = np.minimum(result, value)
    return result


def _elementwise_max(*values: Any) -> Any:
    if not values:
        raise TypeError("max() 至少需要一个参数")
    if len(values) == 1:
        return np.max(values[0])
    result = values[0]
    for value in values[1:]:
        result = np.maximum(result, value)
    return result


#: 白名单函数：点分名（`np.log`）与裸名（`log`）都登记，裸名是 R 习惯的写法。
#: `min` / `max` 是逐元素（多参数）或整体归约（单参数）；`abs` / `round` 同 R。
CALLABLES: Mapping[str, Callable[..., Any]] = MappingProxyType(
    {
        "np.log": np.log,
        "np.log10": np.log10,
        "np.log2": np.log2,
        "np.sqrt": np.sqrt,
        "np.exp": np.exp,
        "np.abs": np.abs,
        "np.round": np.round,
        "np.floor": np.floor,
        "np.ceil": np.ceil,
        "np.where": np.where,
        "np.isnan": np.isnan,
        "log": np.log,
        "log10": np.log10,
        "log2": np.log2,
        "sqrt": np.sqrt,
        "exp": np.exp,
        "abs": np.abs,
        "round": np.round,
        "floor": np.floor,
        "ceil": np.ceil,
        "where": np.where,
        "isnan": np.isnan,
        "min": _elementwise_min,
        "max": _elementwise_max,
    }
)

#: 报错时列出的函数表（顺序固定，便于断言与复制粘贴）。
FUNCTION_HINT = (
    "np.log / np.log10 / np.log2 / np.sqrt / np.exp / np.abs / np.round / "
    "np.floor / np.ceil / np.where / np.isnan（裸名 log / log10 / log2 / sqrt / "
    "exp / abs / round / floor / ceil / where / isnan 同样可用）以及 min / max；"
    '列名不是合法标识符（或撞上 Python 关键字）时用 col("列名")'
)


# ---------------------------------------------------------------------------
# 报错格式
# ---------------------------------------------------------------------------


def _display_source(source: str) -> str:
    """报错头部用的单行表达式文本（多行表达式里的换行显式写出来）。"""
    return source.replace("\n", "\\n")


def _format_error(source: str, line: int, col: int, end_col: int | None, message: str) -> str:
    """`aes 表达式 ... 第 L 行第 C 列：...` + 出错的源码行 + `^` 指示。"""
    lines = source.splitlines() or [""]
    line = min(max(line, 1), len(lines))
    text = lines[line - 1]
    width = 1 if end_col is None or end_col <= col else end_col - col
    caret = " " * col + "^" * width
    return (
        f"aes 表达式 `{_display_source(source)}` 第 {line} 行第 {col + 1} 列：{message}\n"
        f"  {text}\n"
        f"  {caret}"
    )


def _fail(exc_type: type[AesError], ctx: _Context, node: ast.AST | None, message: str) -> None:
    if node is None:
        line, col, end_col = 1, 0, None
    else:
        line = getattr(node, "lineno", 1) or 1
        col = getattr(node, "col_offset", 0) or 0
        end_col = getattr(node, "end_col_offset", None)
        if getattr(node, "end_lineno", line) != line:
            end_col = None
    raise exc_type(_format_error(ctx.source, line, col, end_col, message))


@dataclass(slots=True)
class _Context:
    """一次求值的上下文：表达式文本（报错用）、名字掩码、行数、可用名字。"""

    source: str
    mask: Mapping[str, Any]
    nrows: int
    stage: str  # "data" | "after_stat"
    available: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# 解析 + 白名单核对
# ---------------------------------------------------------------------------


def _is_dunder(name: str) -> bool:
    return name.startswith("__")


def _dotted(node: ast.AST) -> str | None:
    """把 `a.b.c` 还原成点分名；根不是裸名（如 `x[0].c`）返回 None。"""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _unsupported(ctx: _Context, node: ast.AST) -> None:
    """节点不在白名单里时的报错（常见节点给专用文案）。"""
    shown = ast.unparse(node)
    if isinstance(node, ast.Attribute):
        _fail(
            AesWhitelistError,
            ctx,
            node,
            f"不允许属性访问 `{shown}`：属性可能绕过白名单（列不是对象；"
            f"只有白名单函数的 `np.log` 这类写法可以在调用位置出现）",
        )
    if isinstance(node, ast.Subscript):
        _fail(
            AesWhitelistError,
            ctx,
            node,
            f"不允许下标访问 `{shown}`：aes 表达式不支持按位置取值（整列会广播）",
        )
    if isinstance(node, ast.Lambda):
        _fail(AesWhitelistError, ctx, node, "不允许 lambda：aes 表达式只做算术/比较/条件")
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        _fail(AesWhitelistError, ctx, node, f"不允许推导式 `{shown}`")
    if isinstance(node, ast.JoinedStr):
        _fail(AesWhitelistError, ctx, node, f"不允许 f-string `{shown}`")
    _fail(
        AesWhitelistError,
        ctx,
        node,
        f"不允许的语法 {type(node).__name__} `{shown}`：白名单只支持算术（+ - * / "
        "// % **）、比较、and/or/&/|、条件表达式与白名单函数调用",
    )


def _validate_call(node: ast.Call, ctx: _Context, names: list[str]) -> None:
    func = node.func
    key = func.id if isinstance(func, ast.Name) else _dotted(func)
    shown = ast.unparse(func)
    if key is None:
        _fail(
            AesWhitelistError,
            ctx,
            func,
            f"不允许调用 `{shown}`：只允许白名单函数（{FUNCTION_HINT}）",
        )
    if key == "col":
        _validate_col_call(node, ctx, names)
        return
    if key not in CALLABLES:
        _fail(
            AesWhitelistError,
            ctx,
            func,
            f"不允许调用 `{key}`：只允许白名单函数（{FUNCTION_HINT}）",
        )
    for arg in node.args:
        if isinstance(arg, ast.Starred):
            _fail(AesWhitelistError, ctx, arg, "不允许 `*args` 展开：白名单函数只收定参数")
        _validate(arg, ctx, names)
    for keyword in node.keywords:
        if keyword.arg is None:
            _fail(AesWhitelistError, ctx, keyword.value, "不允许 `**kwargs` 展开")
        _validate(keyword.value, ctx, names)


def _validate_col_call(node: ast.Call, ctx: _Context, names: list[str]) -> None:
    """`col("列名")`：唯一一个按**字符串字面量**取列的入口（非标识符列名用）。"""
    if len(node.args) != 1 or node.keywords:
        _fail(
            AesWhitelistError,
            ctx,
            node,
            'col(...) 只接受一个字符串字面量列名，例如 col("mpg class")',
        )
    arg = node.args[0]
    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
        _fail(
            AesWhitelistError,
            ctx,
            arg,
            'col(...) 需要字符串字面量列名（例如 col("class")），不能是变量或表达式',
        )
    if not arg.value:
        _fail(AesWhitelistError, ctx, arg, "col(...) 的列名不能是空字符串")
    if arg.value not in names:
        names.append(arg.value)


def _validate(node: ast.AST, ctx: _Context, names: list[str]) -> None:
    """逐节点核对白名单，并收集引用到的名字（按首次出现顺序）。"""
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (bool, int, float, str)) and node.value is not None:
            _fail(
                AesWhitelistError,
                ctx,
                node,
                f"不支持的常量 {node.value!r}：只允许数字 / 字符串 / True / False / None",
            )
        return
    if isinstance(node, ast.Name):
        if _is_dunder(node.id):
            _fail(AesWhitelistError, ctx, node, f"不允许引用内部名字 `{node.id}`")
        if node.id not in names:
            names.append(node.id)
        return
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BINOPS:
            _fail(
                AesWhitelistError,
                ctx,
                node,
                f"不允许的运算符 `{type(node.op).__name__}`：只支持 + - * / // % ** & |",
            )
        _validate(node.left, ctx, names)
        _validate(node.right, ctx, names)
        return
    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARY:
            _fail(
                AesWhitelistError,
                ctx,
                node,
                f"不允许的一元运算符 `{type(node.op).__name__}`：只支持 + / -",
            )
        _validate(node.operand, ctx, names)
        return
    if isinstance(node, ast.Compare):
        for op in node.ops:
            if type(op) not in _CMP:
                _fail(
                    AesWhitelistError,
                    ctx,
                    node,
                    f"不允许的比较符 `{type(op).__name__}`：只支持 < <= > >= == !=",
                )
        _validate(node.left, ctx, names)
        for comparator in node.comparators:
            _validate(comparator, ctx, names)
        return
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            _validate(value, ctx, names)
        return
    if isinstance(node, ast.IfExp):
        _validate(node.test, ctx, names)
        _validate(node.body, ctx, names)
        _validate(node.orelse, ctx, names)
        return
    if isinstance(node, ast.Call):
        _validate_call(node, ctx, names)
        return
    _unsupported(ctx, node)


def parse_aes(expr: Any) -> AesSpec:
    """把一条 aes 值解析成 :class:`AesSpec`（语法树 + 引用列名 + 阶段）。

    - `str`：按 Python `eval` 模式解析（`"mpg / cyl"`），白名单外节点立刻报
      :class:`AesWhitelistError`；语法错误报 :class:`AesParseError`；
    - 整串就是一个**标识符**但撞上 Python 关键字时（典型是 mpg 的 `class` 列），
      按列名处理——手动合成 `Name` 节点，它和普通列引用一样过白名单；
    - 列名不是标识符（含空格 / 标点）时用 `col("列名")`；
    - `after_stat(...)`：解析里面的表达式，并置 `after_stat=True`；
    - 非字符串（数字 / `None` / ndarray …）：常量，`constant=True`，求值时广播；
    - 已经是 :class:`AesSpec` 的原样返回。
    """
    if isinstance(expr, AesSpec):
        return expr
    after = isinstance(expr, AfterStat)
    raw = expr.expr if after else expr
    if isinstance(raw, str):
        source = raw
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError as exc:
            if not source.isidentifier():
                raise AesParseError(
                    _format_error(
                        source,
                        exc.lineno or 1,
                        max((exc.offset or 1) - 1, 0),
                        None,
                        f"语法错误：{exc.msg}",
                    )
                ) from None
            # `class` / `lambda` 这类关键字列名：手动合成 Name 节点（位置从 1:1
            # 开始），后续仍走同一套白名单校验。
            body = ast.Name(id=source, ctx=ast.Load())
            body.lineno = body.end_lineno = 1
            body.col_offset = 0
            body.end_col_offset = len(source)
            tree = ast.Expression(body=body)
        except ValueError as exc:  # 例如源码里有 NUL 字节
            raise AesParseError(
                _format_error(source, 1, 0, None, f"表达式无法解析：{exc}")
            ) from None
        names: list[str] = []
        _validate(tree.body, _Context(source=source, mask={}, nrows=0, stage="data"), names)
        return AesSpec(
            expr=expr,
            source=source,
            tree=tree,
            columns=tuple(names),
            after_stat=after,
        )
    source = _describe_constant(raw)
    return AesSpec(expr=expr, source=source, tree=None, columns=(), after_stat=after, constant=True)


def _describe_constant(value: Any) -> str:
    if isinstance(value, np.ndarray):
        return f"<ndarray shape={value.shape} dtype={value.dtype}>"
    return repr(value)


# ---------------------------------------------------------------------------
# 求值：一个只认识白名单节点的解释器
# ---------------------------------------------------------------------------


def _lookup(name: str, node: ast.AST, ctx: _Context) -> Any:
    if name in ctx.mask:
        return ctx.mask[name]
    available = ", ".join(ctx.available) if ctx.available else "（空）"
    if ctx.stage == "after_stat":
        _fail(
            AesEvalError,
            ctx,
            node,
            f"stat 输出里没有变量 {name!r}；可用变量：{available}",
        )
    _fail(AesEvalError, ctx, node, f"数据里没有列 {name!r}；可用列：{available}")


def _wrap(exc: Exception, node: ast.AST, ctx: _Context, what: str) -> None:
    _fail(AesEvalError, ctx, node, f"{what}失败：{type(exc).__name__}: {exc}")


def _eval_binop(node: ast.BinOp, ctx: _Context) -> Any:
    left = _eval(node.left, ctx)
    right = _eval(node.right, ctx)
    symbol = _OP_SYMBOLS[type(node.op)]
    try:
        return _BINOPS[type(node.op)](left, right)
    except (ArithmeticError, TypeError, ValueError) as exc:
        _wrap(exc, node, ctx, f"运算 `{symbol}` ")


def _eval_compare(node: ast.Compare, ctx: _Context) -> Any:
    left = _eval(node.left, ctx)
    results: list[Any] = []
    for op, comparator in zip(node.ops, node.comparators, strict=True):
        right = _eval(comparator, ctx)
        symbol = _OP_SYMBOLS[type(op)]
        try:
            results.append(_CMP[type(op)](left, right))
        except (ArithmeticError, TypeError, ValueError) as exc:
            _wrap(exc, node, ctx, f"比较 `{symbol}` ")
        left = right
    if len(results) == 1:
        return results[0]
    # 链式比较 `a < b < c`：逐项取与（numpy 数组走 logical_and）。
    combined = results[0]
    for result in results[1:]:
        try:
            combined = np.logical_and(combined, result)
        except (TypeError, ValueError) as exc:
            _wrap(exc, node, ctx, "链式比较 ")
    return combined


def _eval_boolop(node: ast.BoolOp, ctx: _Context) -> Any:
    values = [_eval(value, ctx) for value in node.values]
    connector = np.logical_and if isinstance(node.op, ast.And) else np.logical_or
    result = values[0]
    for value in values[1:]:
        try:
            result = connector(result, value)
        except (TypeError, ValueError) as exc:
            _wrap(exc, node, ctx, f"`{_OP_SYMBOLS[type(node.op)]}` ")
    return result


def _eval_ifexp(node: ast.IfExp, ctx: _Context) -> Any:
    test = _eval(node.test, ctx)
    body = _eval(node.body, ctx)
    orelse = _eval(node.orelse, ctx)
    if np.ndim(test) == 0:
        return body if bool(test) else orelse
    try:
        return np.where(test, body, orelse)
    except (TypeError, ValueError) as exc:
        _wrap(exc, node, ctx, "条件表达式 ")


def _eval_call(node: ast.Call, ctx: _Context) -> Any:
    key = node.func.id if isinstance(node.func, ast.Name) else _dotted(node.func)
    if key == "col":  # 解析阶段已核对；手搓的 AesSpec 也走同一道检查
        arg = node.args[0] if len(node.args) == 1 and not node.keywords else None
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value):
            _fail(
                AesWhitelistError,
                ctx,
                node,
                'col(...) 只接受一个非空字符串字面量列名，例如 col("class")',
            )
        return _lookup(arg.value, node, ctx)
    function = CALLABLES.get(key or "")
    if function is None:  # 解析阶段已拦住；手搓的 AesSpec 走这里
        _fail(
            AesWhitelistError,
            ctx,
            node.func,
            f"不允许调用 `{ast.unparse(node.func)}`：只允许白名单函数（{FUNCTION_HINT}）",
        )
    args = [_eval(arg, ctx) for arg in node.args]
    kwargs = {keyword.arg: _eval(keyword.value, ctx) for keyword in node.keywords}
    try:
        return function(*args, **kwargs)
    except (ArithmeticError, TypeError, ValueError) as exc:
        _wrap(exc, node, ctx, f"调用 `{key}` ")


def _eval(node: ast.AST, ctx: _Context) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return _lookup(node.id, node, ctx)
    if isinstance(node, ast.BinOp):
        return _eval_binop(node, ctx)
    if isinstance(node, ast.UnaryOp):
        try:
            return _UNARY[type(node.op)](_eval(node.operand, ctx))
        except (ArithmeticError, TypeError, ValueError) as exc:
            _wrap(exc, node, ctx, f"一元运算 `{_OP_SYMBOLS[type(node.op)]}` ")
    if isinstance(node, ast.Compare):
        return _eval_compare(node, ctx)
    if isinstance(node, ast.BoolOp):
        return _eval_boolop(node, ctx)
    if isinstance(node, ast.IfExp):
        return _eval_ifexp(node, ctx)
    if isinstance(node, ast.Call):
        return _eval_call(node, ctx)
    _unsupported(ctx, node)


def _normalize(value: Any, ctx: _Context, node: ast.AST | None) -> np.ndarray:
    """把求值结果收成 `nrows` 长的一维数组（标量 / 长度 1 广播）。"""
    array = np.asarray(value)
    if array.ndim == 0:
        return np.repeat(array, ctx.nrows)
    if array.ndim != 1:
        _fail(
            AesEvalError,
            ctx,
            node,
            f"求值结果是 {array.ndim} 维数组，aes 只接受一维结果（标量或列）",
        )
    if array.shape[0] == 1:
        return np.repeat(array, ctx.nrows) if ctx.nrows != 1 else array
    if array.shape[0] != ctx.nrows:
        _fail(
            AesEvalError,
            ctx,
            node,
            f"长度为 {array.shape[0]}，与数据行数 {ctx.nrows} 不符"
            "（只有标量和长度 1 会广播，不静默截断）",
        )
    return array


# ---------------------------------------------------------------------------
# 数据掩码
# ---------------------------------------------------------------------------


def _column_array(column: Column) -> np.ndarray:
    """列 → 求值用的 ndarray。

    - 数值列（float / int / datetime / timedelta）：保留源 dtype（float32 仍
      float32），缺失写 `NaN`；
    - bool：无缺失给 bool 数组；有缺失退化成 float（1.0 / 0.0 / NaN），这样
      算术与比较仍然可用；
    - str / categorical：object 数组，元素是 Python `str`，缺失写 `None`
      （分组比较与 `==` 都按值走）。
    """
    if column.kind in ("float", "int", "datetime", "timedelta"):
        values = np.array(column.values, copy=True)
        if column.na_mask.any():
            values[column.na_mask] = np.nan
        return values
    if column.kind == "bool":
        if not column.na_mask.any():
            return np.array(column.values, copy=True)
        values = column.values.astype(np.float64)
        values[column.na_mask] = np.nan
        return values
    if column.kind == "categorical":
        values = np.empty(column.size, dtype=object)
        if column.levels:
            values[:] = np.asarray(column.levels, dtype=object)[column.values]
        else:
            values[:] = None
        if column.na_mask.any():
            values[column.na_mask] = None
        return values
    # str：先转 Python str 再进 object 数组，避免 np.str_ 混进分组键。
    values = np.asarray(column.values.tolist(), dtype=object)
    if column.na_mask.any():
        values[column.na_mask] = None
    return values


def _data_mask(data: ColumnTable, names: tuple[str, ...]) -> dict[str, np.ndarray]:
    """只解引用表达式真正用到的列（大表里别为一条 aes 拷贝所有列）。

    不存在的名字留给 :func:`_lookup` 报错——这样消息里能带上表达式、行列位置
    与全部可用列名。
    """
    return {name: _column_array(data.column(name)) for name in names if name in data}


def _require_table(data: Any) -> ColumnTable:
    if isinstance(data, ColumnTable):
        return data
    hint = ""
    if isinstance(data, Mapping):
        hint = "；列式表请先用 ggio.frame.to_column_table(data) 转换"
    raise TypeError(f"aes 求值需要 ggcore.data.ColumnTable，收到 {type(data).__name__}{hint}")


def _check_nrows(nrows: int) -> int:
    if isinstance(nrows, bool) or not isinstance(nrows, int) or nrows < 0:
        raise ValueError(f"nrows 必须是非负整数，收到 {nrows!r}")
    return nrows


# ---------------------------------------------------------------------------
# 对外求值入口
# ---------------------------------------------------------------------------


def eval_aes(spec: Any, data: ColumnTable, *, nrows: int | None = None) -> np.ndarray:
    """数据阶段求值：`AesSpec`（或原样表达式 / 字符串）+ `ColumnTable` → ndarray。

    `after_stat(...)` 的表达式不在这一阶段求值，会报 :class:`AesEvalError`；
    请等 stat 产出后用 :func:`eval_after_stat`。
    """
    table = _require_table(data)
    resolved = parse_aes(spec)
    n = table.nrows if nrows is None else _check_nrows(nrows)
    if resolved.after_stat:
        raise AesEvalError(
            f"aes 表达式 `{_display_source(resolved.source)}` 标了 after_stat(...)："
            "数据阶段没有这个变量，请在 stat 之后用 eval_after_stat(values) 求值"
            "（真正的 stat 产出是 M1-8）"
        )
    ctx = _Context(
        source=resolved.source,
        mask=_data_mask(table, resolved.columns),
        nrows=n,
        stage="data",
        available=table.names,
    )
    if resolved.tree is None:
        return _normalize(resolved.constant_value, ctx, None)
    value = _eval(resolved.tree.body, ctx)
    return _normalize(value, ctx, resolved.tree.body)


def eval_after_stat(
    spec: Any, values: Mapping[str, np.ndarray], *, nrows: int | None = None
) -> np.ndarray:
    """`after_stat(...)` 的求值入口：用 stat 产出的变量表求值（M1-8 调用）。

    `values` 是 `变量名 → ndarray`；各数组长度必须一致（或为 1，广播）。不给
    `nrows` 时按其中最长的数组推断；全是标量时按 1 行处理。

    没有 `after_stat` 标记的 spec 也接受——M1-3 复用它求默认 aes 很方便。
    """
    resolved = parse_aes(spec)
    if not isinstance(values, Mapping):
        raise TypeError(
            f"eval_after_stat 需要 变量名 → ndarray 的 Mapping，收到 {type(values).__name__}"
        )
    if nrows is not None:
        _check_nrows(nrows)
    mask: dict[str, np.ndarray] = {}
    prefix = f"aes 表达式 `{_display_source(resolved.source)}`："
    for name, value in values.items():
        if not isinstance(name, str):
            raise TypeError(f"stat 变量名必须是 str，收到 {type(name).__name__}")
        array = np.asarray(value)
        if array.ndim > 1:
            raise AesEvalError(f"{prefix}stat 变量 {name!r} 是 {array.ndim} 维数组，只接受一维")
        if array.ndim == 1 and array.shape[0] == 0 and nrows is None:
            raise AesEvalError(f"{prefix}stat 变量 {name!r} 是空数组，无法推断行数；请传 nrows")
        mask[name] = array

    lengths = {array.shape[0] for array in mask.values() if array.ndim == 1 and array.shape[0] > 1}
    if len(lengths) > 1:
        detail = "，".join(f"{name}={array.shape[0]}" for name, array in mask.items())
        raise AesEvalError(f"{prefix}stat 变量长度不一致：{detail}")
    if nrows is None:
        nrows = lengths.pop() if lengths else 1
    ctx = _Context(
        source=resolved.source,
        mask=mask,
        nrows=nrows,
        stage="after_stat",
        available=tuple(mask),
    )
    if resolved.tree is None:
        return _normalize(resolved.constant_value, ctx, None)
    for name, array in mask.items():
        if array.ndim == 1 and array.shape[0] not in (1, nrows):
            _fail(
                AesEvalError,
                ctx,
                resolved.tree.body,
                f"stat 变量 {name!r} 长度 {array.shape[0]} 与 nrows={nrows} 不符",
            )
    value = _eval(resolved.tree.body, ctx)
    return _normalize(value, ctx, resolved.tree.body)


# ---------------------------------------------------------------------------
# 自动分组（ggplot2 的 add_group）
# ---------------------------------------------------------------------------


def _is_discrete(values: np.ndarray) -> bool:
    """是否按离散变量参与分组（上游 `is_discrete()` 的口径）。

    上游是 `is.factor(x) || is.character(x) || is.logical(x)`：所以 bool 列、
    以及 `mpg > 20` 这种算出来的逻辑值，都要参与自动分组。str / categorical 在
    数据掩码里已经变成 object 字符串数组。
    """
    kind = values.dtype.kind
    if kind in ("U", "S", "b"):
        return True
    if kind != "O":
        return False
    return all(item is None or isinstance(item, str) for item in values.tolist())


def _is_missing_item(item: Any) -> bool:
    """单个取值是否缺失（`None` / NaN）。"""
    return item is None or (isinstance(item, (float, np.floating)) and bool(np.isnan(item)))


def _object_codes(values: np.ndarray, order: tuple[str, ...] | None = None) -> np.ndarray:
    """object / 字符串数组 → 每个不同值一个 int 码（缺失排最后，也有码）。

    码是值域顺序里的位置（不是首次出现的位置）：上游 `id_var()` 走
    `levels <- sort(unique0(x), na.last = TRUE); match(x, levels)`。普通字符
    列按升序；**categorical 列按 `Column.levels` 的顺序**（`order`），所以
    `factor(..., levels = c("b", "a"))` 的 group 跟 levels 走，不是字母序。
    """
    items = values.tolist()
    present = [item for item in (order or ()) if item in set(items)]
    known = set(present)
    present.extend(
        sorted({item for item in items if not _is_missing_item(item) and item not in known})
    )
    has_missing = any(_is_missing_item(item) for item in items)
    index = {item: position for position, item in enumerate(present)}
    missing_code = len(present) if has_missing else -1
    codes = np.empty(values.shape[0], dtype=np.int64)
    for i, item in enumerate(items):
        codes[i] = missing_code if _is_missing_item(item) else index[item]
    return codes


def _value_codes(values: np.ndarray, order: tuple[str, ...] | None = None) -> np.ndarray:
    """把一列值编码成 int 码（只保证「相等 ↔ 同码」）；缺失排最后。"""
    kind = values.dtype.kind
    if kind in ("U", "S", "O"):
        return _object_codes(values, order)
    if kind == "f":
        # np.unique 把 NaN 排到最后并给它一个码（与上游 na.last = TRUE 一致）。
        if values.size == 0:
            return np.empty(0, dtype=np.int64)
        _, inverse = np.unique(values, return_inverse=True)
        return inverse.astype(np.int64, copy=False)
    if values.size == 0:
        return np.empty(0, dtype=np.int64)
    _, inverse = np.unique(values, return_inverse=True)
    return inverse.astype(np.int64, copy=False)


def _ids_from_keys(
    keys: list[np.ndarray],
    orders: list[tuple[str, ...] | None] | None = None,
) -> np.ndarray:
    """多列 interaction → 分组 id（缺失作为一个水平，排在最后）。

    编码与编号都照上游 `id()`：第一个 key 变化最慢、最后一个最快（R 的实现把
    `.variables` 反过来做混合进制），再把用到的组合按**组合码升序**编号
    （`id_var(res, drop = TRUE)` 同样是 `match(x, sort(unique(x)))`）。
    `orders` 是每个 key 的 categorical levels（没有就是 None，走升序）。
    """
    n = keys[0].shape[0]
    ids = np.full(n, NO_GROUP, dtype=np.int32)
    if n == 0:
        return ids

    orders = orders or [None] * len(keys)
    combined = np.zeros(n, dtype=np.int64)
    for values, order in zip(keys, orders, strict=True):
        codes = _value_codes(np.asarray(values), order)
        radix = int(codes.max()) + 1 if codes.size else 1
        combined = combined * radix + codes

    uniq = np.unique(combined)
    ids = np.searchsorted(uniq, combined).astype(np.int32, copy=False)
    return ids


def compute_groups(mapping: Aes | Mapping[str, Any], data: ColumnTable) -> np.ndarray:
    """按 ggplot2 4.x `add_group()` 的口径算分组 id。

    - 显式 `aes(group=...)` 优先（`group` 里每个不同值一组）；
    - 否则用**所有离散的 aes**（`str` / `categorical` / 逻辑值，对齐上游
      `is_discrete()`；排除 `label` / `PANEL`）做 interaction，组合按组合码升序
      编号（对齐上游 `id()`：第一个 aes 变化最慢、最后一个最快）；
    - 没有任何离散 aes 时全部是 :data:`NO_GROUP`（-1），`has_groups()` 为 False；
    - 分组列里的 **NA 也作为一个水平**（排在最后）参与编号：上游 `id_var()` 是
      `sort(unique0(x), na.last = TRUE)`，NA 行不会得到 `NO_GROUP`。

    `after_stat(...)` 的 aes 在数据阶段拿不到值，不参与分组（与上游
    `compute_aesthetics()` 先丢弃 calculated aes 再调 `add_group()` 一致）。
    """
    table = _require_table(data)
    resolved = as_aes(mapping)
    n = table.nrows
    if n == 0:
        return np.full(0, NO_GROUP, dtype=np.int32)

    evaluated: dict[str, np.ndarray] = {}
    orders: dict[str, tuple[str, ...]] = {}
    for name, value in resolved.items():
        spec = parse_aes(value)
        if spec.after_stat:
            continue
        evaluated[name] = eval_aes(spec, table, nrows=n)
        column = _column_reference(spec, table)
        if column is not None and column.kind == "categorical" and column.levels:
            orders[name] = column.levels

    if "group" in evaluated:
        keys = [evaluated["group"]]
        key_orders = [orders.get("group")]
    else:
        names = [
            name
            for name, values in evaluated.items()
            if name not in _GROUP_EXCLUDED and _is_discrete(values)
        ]
        keys = [evaluated[name] for name in names]
        key_orders = [orders.get(name) for name in names]
    if not keys:
        return np.full(n, NO_GROUP, dtype=np.int32)
    return _ids_from_keys(keys, key_orders)


def _column_reference(spec: AesSpec, table: ColumnTable) -> Column | None:
    """表达式就是「裸列」时返回源列（用来读 categorical 的 levels 顺序）。"""
    if spec.tree is None or spec.constant:
        return None
    body = spec.tree.body
    name: str | None = None
    if isinstance(body, ast.Name):
        name = body.id
    elif (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Name)
        and body.func.id == "col"
        and len(body.args) == 1
        and isinstance(body.args[0], ast.Constant)
        and isinstance(body.args[0].value, str)
    ):
        name = body.args[0].value
    if name is None or name not in table:
        return None
    return table.column(name)


def has_groups(ids: np.ndarray) -> bool:
    """分组 id 里是否有真实分组（全 `NO_GROUP` 即「未分组」）。"""
    array = np.asarray(ids)
    return bool(array.size) and bool((array >= 0).any())
