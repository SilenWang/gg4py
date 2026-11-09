"""gg4py — 面向用户的顶层入口：一条 `import` 拿到 `library(ggplot2)` 能用的名字。

    import gg4py

    p = gg4py.ggplot(df, gg4py.aes(x="wt", y="mpg")) + gg4py.geom_point()
    gg4py.ggsave(p, "out.png", width=6, height=4, dpi=150)

三层边界（提升策略与迁移示例见 `docs/notes/public-api.md`）：

- **顶层**（本模块）：`ggcore.plot.__all__` 的**投影**——注册表里每个 `geom_*` /
  `stat_*` / `scale_*` / `coord_*` / `facet_*` / `theme_*`，加上 `ggplot` / `aes` /
  `labs` / `guides` 等静态名字；再补上输入适配的 `from_*` / `to_column_table`、
  `ggsave` 与 `__version__`。名字**不手抄**：`__all__` 每次从
  `ggcore.plot.__all__` 现算，新登记的组件自动出现在顶层
  （`tests/test_public_api.py` 守着这条）。
- **子命名空间**：`gg4py.io` / `gg4py.ir` / `gg4py.diff` —— IR、codec、差分这类
  开发者 API，首次访问时才导入。
- **内部包**：`ggcore.*` / `ggio` / `ggshape` / `ggskia` / `ggdiff` 路径与导出
  完全不变，高级入口、既有文档与扩展写法不受影响。

X1 门禁不允许 `ggcore` import `ggskia`，所以 `ggsave`（唯一需要渲染后端的顶层
名字）由模块级 `__getattr__` 惰性取：没有 skia-python / uharfbuzz 的环境里
`import gg4py` 仍然成功，`gg4py.ggsave` 回落到 `ggcore.io.ggsave`，调用时才报
「没有后端」。
"""

from __future__ import annotations

import importlib
from typing import Any

import ggcore.plot as _plot
from ggcore import __version__ as _core_version
from ggio import frame as _frame

__version__ = _core_version

#: 顶层补充的输入适配名。与 `ggio.frame.__all__` 同源：只提升可调用的入口，
#: `SUPPORTED_INPUTS` 这类说明性常量留给 `ggio.frame`。
_ADAPTERS: tuple[str, ...] = tuple(
    name for name in _frame.__all__ if callable(getattr(_frame, name))
)

#: 需要渲染后端的名字 → 提供它的模块。`ggcore` 不能 import 它们（X1），
#: 所以只能惰性取。
_LAZY: dict[str, str] = {"ggsave": "ggskia"}

#: 开发者 API 的子命名空间，首次访问时才导入（`gg4py.diff` 会拉 numpy / pillow）。
_SUBMODULES: tuple[str, ...] = ("diff", "io", "ir")

_MISSING = object()


def _public_names() -> list[str]:
    """顶层导出名：`ggcore.plot.__all__` 现算 + 少量补充名，顺序稳定且不重复。"""
    names = list(_plot.__all__)
    for name in (*_ADAPTERS, *_LAZY, "__version__"):
        if name not in names:
            names.append(name)
    return names


def _lazy_entry(name: str, provider: str) -> Any:
    """从渲染后端取一个顶层名字；后端缺席时回落到设备无关的 `ggcore.io`。"""
    try:
        module = importlib.import_module(provider)
    except ModuleNotFoundError as exc:
        # 只兜「渲染栈根本不在这台机器上」：`ggskia` 自己的 bug 照旧抛出。
        if exc.name not in {"ggskia", "skia"}:
            raise
        from ggcore.io import ggsave

        return ggsave
    return getattr(module, name)


def __getattr__(name: str) -> Any:
    if name == "__all__":
        # 不落进模块 `__dict__`：每次访问都重算，注册表一变顶层立刻跟上。
        return _public_names()
    if name in _LAZY:
        return _lazy_entry(name, _LAZY[name])
    if name in _SUBMODULES:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    if name in _ADAPTERS:
        return getattr(_frame, name)
    value = getattr(_plot, name, _MISSING)
    if value is not _MISSING:
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_public_names()) | set(_SUBMODULES))
