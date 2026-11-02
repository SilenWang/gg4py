"""`aes()` —— 美学映射的构造壳（只存原始表达式，不求值）。

M1-1 只把用户写下的东西原样收好，解析与求值是 M1-2 的事：

    p = ggplot(df, aes(x="displ", y="hwy / cyl", colour="class"))
    p.mapping["y"]      # "hwy / cyl"（原字符串，没有被求值）

三条边界：

- `Aes` 是不可变映射（`Mapping` 协议），所以 `p + ...` 的克隆语义可以直接共享
  同一个实例，不必深拷贝；
- `after_stat(expr)` 只打标记（:class:`AfterStat`），表达式原样留存，等 M1-8
  的 stat 产出之后再由 M1-2 的求值器处理；
- 本模块没有 `eval` / `exec`，也不 import `ast`：字符串解析、白名单 AST、数据
  掩码全部属于 M1-2（`ggcore.eval`），这里一点都别提前做。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

__all__ = ["Aes", "AfterStat", "aes", "after_stat", "as_aes", "frozen_mapping"]


def frozen_mapping(values: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    """把映射冻结成只读视图，供各组件共享「不可变值」。

    只做浅冻结：值本身（字符串、数字、numpy 数组）按引用共享，这与克隆语义
    「可变容器复制、不可变值共享」是同一条约定。
    """
    if values is None:
        return MappingProxyType({})
    if isinstance(values, MappingProxyType):
        return values
    return MappingProxyType(dict(values))


@dataclass(frozen=True, slots=True)
class AfterStat:
    """`after_stat(...)` 的标记：只记下原始表达式，不求值。"""

    expr: Any


@dataclass(frozen=True, slots=True, eq=False)
class Aes(Mapping[str, Any]):
    """不可变的美学映射（`x -> "mpg / cyl"` 这样原样保存）。

    继承 `Mapping`，所以 `items()` / `keys()` / `in` 都能直接用；字段名用
    `aesthetics` 而不是 `values`，避免和 `Mapping.values()` 撞名。
    """

    aesthetics: Mapping[str, Any] = field(default_factory=frozen_mapping)

    def __post_init__(self) -> None:
        object.__setattr__(self, "aesthetics", frozen_mapping(self.aesthetics))

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
    """构造一份美学映射；值可以是字符串表达式、常量或 `after_stat(...)`。"""
    return Aes(dict(aesthetics))


def after_stat(expr: Any) -> AfterStat:
    """标记「这个美学取 stat 的计算结果」，例如 `aes(y=after_stat(count))`。

    只打标记，不解析、不求值——求值在 M1-2，数据在 M1-8。
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
