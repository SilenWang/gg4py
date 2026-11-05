"""`ggcore.script` — 「一段脚本 → 一张图」的执行契约（M3-4 浏览器编辑器）。

浏览器编辑器不是把数据塞进表单再重算，而是在页面上**写这个包的代码**。于是需要
一条两端共用的最小契约：同一段源码在 CPython 与 Pyodide 上各跑一次，产出的 IR
必须逐字节相同。这条契约放在 `ggcore` 里而不是 worker 的字符串里，理由与
`docs/notes/pyodide.md` §2 的第 1 条相同——否则「两端一致」只是测试脚手架的巧合：

    from ggcore.script import run_script
    result = run_script(source, filename="hello.py")
    result.ir_bytes, result.meta["digest"]

脚本的写法（与 `docs/cases/*/plot.py`、`web/runtime/demos/*.py` 同一形状）::

    from ggcore.plot import aes, geom_point, ggplot

    DATA = {"x": [1, 2, 3], "y": [2, 1, 3]}

    def build():
        return {"plot": ggplot(DATA, aes(x="x", y="y")) + geom_point(),
                "size": [5.0, 3.6]}

`build()` 也可以直接返回一个 `ggplot` 对象（尺寸取 :data:`DEFAULT_SIZE`），或者
干脆不写函数、把图放进模块级的 `plot` 变量——编辑器里的第一段代码越短越好。
两种写法在 :func:`run_script` 里归一到同一条 `build_scene()` 路径。

可选声明 ::

    needs = ["numpy", "contourpy"]

`needs` 是「这段代码要用到的 Pyodide 包」：浏览器只按它和静态 import 扫描加载
轮子（表度量走 `ggcore.metrics.fallback`，不需要熊猫）。`contourpy` 只在
`stat_contour*` 真正被调用时才 import，静态扫描看不见——要画等值线的脚本必须
显式写进 `needs`。

口径：

- 度量固定用 :func:`ggcore.metrics.fallback.default_metrics`（TableMetrics）。
  浏览器里没有 skia / HarfBuzz，桌面端要跟浏览器逐字节相同就只能也用它；
- 执行在**新命名空间**里（`__name__ = "__gg4py_script__"`，`__file__` 为传入的
  文件名），不改调用方的全局变量；
- 用户代码抛错时抛 :class:`ScriptError`，它的 `traceback_text` 只保留**用户源文件**
  的栈帧——浏览器回显的 traceback 不该出现 `ggcore/script.py` 的内部行。
"""

from __future__ import annotations

import ast
import hashlib
import time
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ggcore import ir
from ggcore.metrics.fallback import default_metrics
from ggcore.plotspec import PlotSpecError, build_scene

__all__ = [
    "DEFAULT_SIZE",
    "MODULE_PACKAGES",
    "ScriptError",
    "ScriptResult",
    "detect_needs",
    "run_script",
]

#: 脚本没给 `size` 时的页面尺寸（英寸）：比案例库的 4×3 宽一点，适合编辑器右栏。
#: 取 0.5 in 的整数倍，落在 pt 上就是 36 的整数倍（5.0 in = 360 pt），导出的 PNG
#: 因此不会因为半像素对不齐屏幕（M3-4 的「导出与屏幕逐像素相同」）。
DEFAULT_SIZE = (5.0, 3.5)

#: 顶层模块名 → Pyodide 包名。只列**真正需要单独 loadPackage** 的：ggcore / ggio
#: 自己就在 `gg4py.tar` 里，标准库随运行时一起到。
MODULE_PACKAGES = {
    "numpy": "numpy",
    "contourpy": "contourpy",
    "pandas": "pandas",
    "pyarrow": "pyarrow",
}

#: `build()` 的返回值允许的键（见 `ggcore.plotspec.build_scene`）。
_SPEC_KEYS = frozenset({"plot", "grob", "gtable", "data"})

_SCRIPT_NAME = "__gg4py_script__"


class ScriptError(Exception):
    """用户脚本的错误（语法 / 运行时 / 契约）。

    `message` 是一行用户能读的原因，`traceback_text` 是同一件事的 Python
    traceback（只有用户源文件的帧），`line` 是出错行（能做到时）。
    """

    def __init__(
        self,
        message: str,
        *,
        traceback_text: str = "",
        filename: str | None = None,
        line: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.traceback_text = traceback_text
        self.filename = filename
        self.line = line

    def as_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "traceback": self.traceback_text or self.message,
            "filename": self.filename,
            "line": self.line,
        }

    @classmethod
    def from_exception(cls, exc: BaseException, filename: str) -> ScriptError:
        line = None
        for frame in traceback.extract_tb(exc.__traceback__):
            if frame.filename == filename:
                line = frame.lineno
        return cls(
            f"{type(exc).__name__}: {exc}",
            traceback_text=_user_traceback(exc, filename),
            filename=filename,
            line=line,
        )


@dataclass(frozen=True)
class ScriptResult:
    """脚本跑成功的结果：IR 字节 + 一份可直接 JSON 化的元数据。"""

    ir_bytes: bytes
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        return self.meta["digest"]


def _user_traceback(exc: BaseException, filename: str) -> str:
    """只保留用户源文件的帧；没有用户帧时退回标准的 `format_exc()`。

    Pyodide 侧 `runPython` 抛出来的 message 会带上一整条 harness 栈（`<exec>`、
    `ggcore/script.py` 的内部行），在编辑器里既吵又误导——用户要看的是「我写的
    第 7 行」。
    """
    try:
        te = traceback.TracebackException.from_exception(exc)
    except Exception:  # pragma: no cover - 极端的自引用异常
        return traceback.format_exc()
    frames = [frame for frame in te.stack if frame.filename == filename]
    if not frames:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    lines = ["Traceback (most recent call last):\n"]
    for frame in frames:
        lines.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n')
        source = (frame.line or "").strip()
        if source:
            lines.append(f"    {source}\n")
    lines.extend(te.format_exception_only())
    return "".join(lines)


def detect_needs(source: str) -> list[str]:
    """静态扫描源码，列出要 `loadPackage` 的包（不执行代码）。

    两个来源合并：显式 `needs = [...]` 字面量（与 `web/runtime/demos/*.py` 同一
    写法，用来声明静态扫描看不见的懒加载依赖，例如 contourpy）与 `import` /
    `from ... import` 的顶层模块名。认不出的模块忽略——它们可能是标准库、ggcore
    自己，或者用户环境里本来就有。

    语法错误返回 `[]`（真正的报错留给 :func:`run_script`，那里的 traceback 更准）。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    declared: list[str] = []
    roots: set[str] = set()
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if any(isinstance(t, ast.Name) and t.id == "needs" for t in targets):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            if isinstance(value, (list, tuple)):
                declared.extend(str(item) for item in value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            roots.add(node.module.split(".")[0])

    found = list(declared)
    found.extend(MODULE_PACKAGES[root] for root in roots if root in MODULE_PACKAGES)
    # 去重保序：`needs` 里写的顺序就是页面加载轮子的顺序，别让 set 打乱。
    seen: set[str] = set()
    ordered: list[str] = []
    for name in found:
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def _spec_from_namespace(namespace: Mapping[str, Any], size: Any) -> Mapping[str, Any]:
    builder = namespace.get("build")
    raw: Any
    if callable(builder):
        raw = builder()
    elif "plot" in namespace:
        raw = namespace["plot"]
    else:
        raise ScriptError(
            '脚本没有出图：定义 build()（返回 {"plot": ..., "size": [宽, 高]} 或一个图对象）'
            "或者在模块里放一个名为 plot 的图对象"
        )

    if isinstance(raw, Mapping):
        if not _SPEC_KEYS.intersection(raw):
            raise ScriptError(
                "build() 返回的 dict 里没有 plot / grob / gtable / data 中任何一项"
                f"（收到 {sorted(raw)!r}）"
            )
        spec = dict(raw)
        if "size" not in spec:
            spec["size"] = size if size is not None else DEFAULT_SIZE
        return spec
    # 直接返回一个图对象：与 `plot` 变量同一条口径。
    return {"plot": raw, "size": size if size is not None else DEFAULT_SIZE}


def run_script(
    source: str,
    *,
    filename: str = "<gg4py editor>",
    size: Any = None,
    metrics: Any = None,
    variables: Mapping[str, Any] | None = None,
) -> ScriptResult:
    """执行 `source` 并把它的图编成 IR。

    Parameters
    ----------
    source:
        Python 源码（编辑器里的整页代码）。
    filename:
        traceback 与 `__file__` 用的文件名；浏览器里是 `/app/<name>.py`。
    size:
        页面尺寸（英寸）的兜底值，脚本自己给了 `size` 就以脚本为准。
    metrics:
        文字度量；缺省 `default_metrics()`（两端一致的那一份）。
    variables:
        执行前预置到脚本命名空间的变量（编辑器的「内联数据」面板就是用它把
        `DATA` 放进去的）。不写进源码，所以 traceback 的行号仍然是用户在编辑器里
        看到的行号。
    """
    started = time.perf_counter()
    namespace: dict[str, Any] = {
        "__name__": _SCRIPT_NAME,
        "__file__": filename,
        "__builtins__": __builtins__,
    }
    if variables:
        for key, value in variables.items():
            if key.startswith("__") and key.endswith("__"):
                raise ValueError(f"预置变量不能用双下划线名字：{key!r}")
            namespace[key] = value

    try:
        code = compile(source, filename, "exec")
    except SyntaxError as exc:
        raise ScriptError(
            f"SyntaxError: {exc.msg}",
            traceback_text=_syntax_traceback(exc),
            filename=filename,
            line=exc.lineno,
        ) from None

    try:
        exec(code, namespace)
        spec = _spec_from_namespace(namespace, size)
    except ScriptError:
        raise
    except BaseException as exc:
        raise ScriptError.from_exception(exc, filename) from None

    build_start = time.perf_counter()
    try:
        scene = build_scene(spec, metrics=metrics if metrics is not None else default_metrics())
    except PlotSpecError as exc:
        raise ScriptError(f"PlotSpecError: {exc}", filename=filename) from None
    build_ms = (time.perf_counter() - build_start) * 1000.0

    encode_start = time.perf_counter()
    data = ir.encode(scene)
    encode_ms = (time.perf_counter() - encode_start) * 1000.0

    width_in, height_in = (
        spec.get("size", DEFAULT_SIZE) if isinstance(spec, Mapping) else DEFAULT_SIZE
    )
    meta = {
        "digest": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "nodes": sum(1 for _ in ir.walk(scene.root)),
        "width_in": float(width_in),
        "height_in": float(height_in),
        "build_ms": round(build_ms, 3),
        "encode_ms": round(encode_ms, 3),
        "total_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "needs": detect_needs(source),
        "ir_version": ir.IR_VERSION_STR,
        "cbor": ir.CBOR_BACKEND,
    }
    return ScriptResult(ir_bytes=data, meta=meta)


def _syntax_traceback(exc: SyntaxError) -> str:
    """语法错误的 traceback：Python 标准形状（箭头指到出错的记号）。

    `format_exception_only()` 自己就带 `File "..."` 与出错的源码行，别再补一行
    ——否则编辑器里会看到两遍同一个文件名。
    """
    body = "".join(traceback.format_exception_only(type(exc), exc))
    return f"Traceback (most recent call last):\n{body}"
