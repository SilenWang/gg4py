"""`aes()` —— 美学映射（原样表达式 + M1-2 的解析结果）。

构造壳只把用户写下的东西原样收好，解析与求值在 `ggcore.eval`：

    p = ggplot(df, aes(x="displ", y="hwy / cyl", colour="class"))
    p.mapping["y"]      # "hwy / cyl"（原字符串，没有被求值）

    spec = parse_aes(p.mapping["y"])    # ggcore.eval
    spec.columns                        # ("hwy", "cyl")
    eval_aes(spec, table)               # 数据掩码 → ndarray

四条边界：

- `Aes` 是不可变映射（`Mapping` 协议），所以 `p + ...` 的克隆语义可以直接共享
  同一个实例，不必深拷贝；
- `after_stat(expr)` 只打标记（:class:`AfterStat`），表达式原样留存，等 M1-8
  的 stat 产出之后再由 `ggcore.eval.eval_after_stat` 求值；
- :class:`AesSpec` 只是**解析结果的数据容器**（语法树 + 引用到的列名 + 阶段），
  由 `ggcore.eval.parse_aes` 产出；本模块仍然没有 `eval` / `exec`，也不在运行时
  import `ast`（只有类型标注用到）；
- 字符串表达式按 Python 的 `eval` 模式解析，**但求值只走白名单解释器**，绝不在
  这里或 `ggcore.eval` 里调用 `eval()` / `exec()` / `compile()`。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅用于类型标注；解析本身在 ggcore.eval，AesSpec 不负责解析
    import ast

__all__ = [
    "Aes",
    "AesSpec",
    "AfterStat",
    "aes",
    "after_stat",
    "as_aes",
    "frozen_mapping",
    "frozen_value",
    "standardise_aes_name",
    "standardise_aes_names",
]

#: 上游 `.base_to_ggplot`（R/ggplot-global.R:31）：旧 R 名 → ggplot 名。
#: 整名匹配；`color` → `colour` 的子串替换在 :func:`standardise_aes_name` 里做
#: （对应上游 `sub("color", "colour", x, fixed = TRUE)`）。
_BASE_TO_GGPLOT: Mapping[str, str] = MappingProxyType(
    {
        "col": "colour",
        "color": "colour",
        "pch": "shape",
        "cex": "size",
        "lty": "linetype",
        "lwd": "linewidth",
        "srt": "angle",
        "adj": "hjust",
        "bg": "fill",
        "fg": "colour",
        "min": "ymin",
        "max": "ymax",
    }
)


def standardise_aes_name(name: str) -> str:
    """一个 aes 名的标准化：`color`（含子串）→ `colour`，旧 R 名 → ggplot 名。"""
    if not isinstance(name, str):
        raise TypeError(f"aes 名必须是 str，得到 {type(name).__name__}")
    # 上游的 sub(..., fixed = TRUE) 只换第一处子串，这里保持同一口径。
    standard = name.replace("color", "colour", 1)
    return _BASE_TO_GGPLOT.get(standard, standard)


def standardise_aes_names(names: Iterable[str]) -> tuple[str, ...]:
    """批量标准化 aes 名（上游 `standardise_aes_names()` 的向量版）。"""
    return tuple(standardise_aes_name(name) for name in names)


def _standardise_aesthetics(values: Mapping[str, Any]) -> dict[str, Any]:
    """标准化键并拒绝冲突（`color` 与 `colour` 同时出现时不能悄悄丢一个）。"""
    standardised: dict[str, Any] = {}
    for key, value in values.items():
        standard = standardise_aes_name(key)
        if standard in standardised:
            raise ValueError(
                f"标准化后 aes 名重复：{key!r} 与已有的 {standard!r} 冲突"
                "（例如 color 与 colour 同时出现）"
            )
        standardised[standard] = value
    return standardised


def frozen_value(value: Any) -> Any:
    """递归冻结一个值：`Mapping` → `MappingProxyType`，`list` / `tuple` → `tuple`。

    其它对象（字符串、数字、numpy 数组）原样返回、按引用共享——它们是后续阶段
    只读消费的数据，深拷贝既不必要也会破坏「不可变值共享」的性能约定。
    """
    if isinstance(value, Mapping):
        return MappingProxyType({key: frozen_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(frozen_value(item) for item in value)
    return value


def frozen_mapping(values: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    """把映射递归冻结成只读视图，供各组件共享「不可变值」。

    **任意层级**都不可写：嵌套 dict 变 `MappingProxyType`、list 变 tuple，
    所以拿到克隆的一方改不动原图（见 `tests/test_plot.py` 的 labels 回归用例）。
    其它对象按引用共享，这与克隆语义「可变容器复制、不可变值共享」是同一条约定。
    """
    if values is None:
        return MappingProxyType({})
    return MappingProxyType({key: frozen_value(value) for key, value in values.items()})


@dataclass(frozen=True, slots=True)
class AfterStat:
    """`after_stat(...)` 的标记：只记下原始表达式，不求值。"""

    expr: Any


@dataclass(frozen=True, slots=True, eq=False)
class AesSpec:
    """一条 aes 表达式的**解析结果**（`ggcore.eval.parse_aes` 产出）。

    Parameters
    ----------
    expr:
        用户写下的原值：字符串表达式、`after_stat(...)` 标记，或非字符串常量。
    source:
        **表达式文本**，报错与 `repr` 都用它（常量取 `repr(value)`）。
    tree:
        `ast.parse(mode="eval")` 的语法树；非字符串常量是 `None`。
    columns:
        表达式引用到的名字（列名 / stat 变量名），按首次出现顺序去重。
        函数名（`np` / `log` / `min` …）不算引用。
    after_stat:
        是否来自 `after_stat(...)`：数据阶段不求值，改用
        `ggcore.eval.eval_after_stat(values)`。
    constant:
        是否是非字符串常量（标量 / ndarray / `None` 等），按标量或数组广播。
    """

    expr: Any
    source: str
    tree: ast.Expression | None = None
    columns: tuple[str, ...] = ()
    after_stat: bool = False
    constant: bool = False

    @property
    def constant_value(self) -> Any:
        """常量表达式的原值（`after_stat(...)` 里的也算）；非常量返回 `None`。"""
        if not self.constant:
            return None
        return self.expr.expr if isinstance(self.expr, AfterStat) else self.expr

    def __eq__(self, other: object) -> bool:
        # 语法树按传值比较没有意义（`ast` 节点是引用相等），按解析口径比较：
        # 同一段文本 + 同一阶段 + 同一批引用列 = 同一条 spec。
        if not isinstance(other, AesSpec):
            return NotImplemented
        return (self.source, self.after_stat, self.constant, self.columns) == (
            other.source,
            other.after_stat,
            other.constant,
            other.columns,
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        stage = "after_stat" if self.after_stat else "data"
        if self.constant:
            return f"AesSpec(constant={self.source}, stage={stage!r})"
        return f"AesSpec({self.source!r}, columns={self.columns}, stage={stage!r})"


@dataclass(frozen=True, slots=True, eq=False)
class Aes(Mapping[str, Any]):
    """不可变的美学映射（`x -> "mpg / cyl"` 这样原样保存）。

    继承 `Mapping`，所以 `items()` / `keys()` / `in` 都能直接用；字段名用
    `aesthetics` 而不是 `values`，避免和 `Mapping.values()` 撞名。
    """

    aesthetics: Mapping[str, Any] = field(default_factory=frozen_mapping)

    def __post_init__(self) -> None:
        # 键按上游 standardise_aes_names() 标准化（color → colour、pch → shape …），
        # 值（表达式）原样保留。
        standardised = _standardise_aesthetics(self.aesthetics)
        object.__setattr__(self, "aesthetics", frozen_mapping(standardised))

    def __getitem__(self, key: str) -> Any:
        return self.aesthetics[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.aesthetics)

    def __len__(self) -> int:
        return len(self.aesthetics)

    def __eq__(self, other: object) -> bool:
        # 与任何 Mapping 比较都按内容；`Aes` 本身不可哈希。
        if isinstance(other, Mapping):
            return dict(self.aesthetics) == dict(other)
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        body = ", ".join(f"{key}={value!r}" for key, value in self.aesthetics.items())
        return f"aes({body})"


def aes(**aesthetics: Any) -> Aes:
    """构造一份美学映射；值可以是字符串表达式、常量或 `after_stat(...)`。

    键按上游 `standardise_aes_names()` 标准化（`color` → `colour`、`pch` →
    `shape`、`cex` → `size` …），值（表达式）原样保留。

    字符串按**表达式**解释（`"mpg / cyl"` 是两个列名做除法），不是常量；
    常量字符串要写成带引号的表达式（`aes(colour="'red'")`）或直接传 Python 值。
    """
    return Aes(dict(aesthetics))


def after_stat(expr: Any) -> AfterStat:
    """标记「这个美学取 stat 的计算结果」，例如 `aes(y=after_stat("count"))`。

    只打标记，不解析、不求值；M1-2 的 `ggcore.eval.parse_aes` 负责解析，
    `eval_after_stat(values)` 负责在 stat 产出之后求值（真正的 stat 是 M1-8）。
    """
    return AfterStat(expr)


def as_aes(value: Aes | Mapping[str, Any] | None) -> Aes:
    """把 `None` / 普通映射 / `Aes` 统一成 `Aes`。"""
    if value is None:
        return Aes()
    if isinstance(value, Aes):
        return value
    if isinstance(value, Mapping):
        return Aes(dict(value))
    raise TypeError(f"mapping 必须是 aes() 的结果或 Mapping，得到 {type(value).__name__}")
