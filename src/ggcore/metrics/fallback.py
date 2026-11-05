"""没有 HarfBuzz 时的 `ggcore.units.Metrics`：读兜底度量表（浏览器 / Pyodide）。

`ggcore` 在浏览器里跑（Pyodide / wasm）时没有 `ggshape` 的 HarfBuzz，也没有
`ggskia` 的 `TextShaper`——`ggcore.units.Metrics` 的三个方法于是没有实现，凡是
要**自己**决定宽度的地方（版式、`geom_label` 的盒子、裸 `textGrob` 快照）都会抛
`GrobError`。本模块补上这条腿：

    from ggcore.metrics.fallback import default_metrics

    scene = build_scene(spec, metrics=default_metrics())

宽度不是另估的：走 `TableBackend` 的预生成度量表（与 `pixi run gate:metrics`
守的兜底表同一份），规则仍是 `provider` 的 run 切分 + `font_units / upem * size`。
所以同一段文字在 CPython 与 Pyodide 上量出同一个数，IR 才能逐字节一致
（`pixi run gate:pyodide` 的全部 case）。

两条与 :class:`ggskia.text.ShaperMetrics` 的差别，必须写清楚：

* **按 em 的 cap height 近似**。兜底表不存 cap height（表格式 v2 只有
  upem / ascent / descent，见 `ggcore/metrics/table.py`），而 R 的
  `stringHeight()` = cap height + 行距，不是 ascent + descent。受管字面的
  `fCapHeight / upem`（skia 实测）落在 0.688（Arimo）– 0.729（DejaVu Sans）
  之间，CJK 是 0.733；取 :data:`CAP_HEIGHT_EM` = 0.72，最大误差 ~4.5%。
  这条只影响「文字盒子有多高」，不影响宽度，也不影响任何写进 IR 的文本位置。
* **不做上下文 shaping**（连写 / 字对重排），与表本身的能力边界一致
  （`TableBackend.supports()`）。IR 的 `text.width` 因此以本实现为准——浏览器
  里画的就是它，不再有第二份「屏幕上的宽度」。

X1 白名单内：只用标准库 + numpy + `ggcore` 自身（不 import `ggshape` / `ggskia`）。
"""

from __future__ import annotations

from ggcore.metrics.catalog import MANAGED_FONTS
from ggcore.metrics.faces import FACE_SUFFIXES, FontFaceError, canonical_family, resolve_face
from ggcore.metrics.provider import MetricProvider
from ggcore.metrics.rules import DEFAULT_FONT_STACK
from ggcore.metrics.table import TableBackend

__all__ = [
    "CAP_HEIGHT_EM",
    "LINE_PITCH",
    "TableMetrics",
    "default_metrics",
]

#: cap height / upem 的 em 近似（受管字面实测 0.688–0.733，见模块说明）。
CAP_HEIGHT_EM = 0.72
#: R 4.5.3 实测的绘制行距系数（`gpar(lineheight = 1.2)` → 1.44 × fontsize）。
LINE_PITCH = 1.44
#: R/svglite 参考产线的缺省拉丁字族；未登记的字族回落到它（与 `ggskia` 一致）。
_SANS_FAMILY = MANAGED_FONTS[DEFAULT_FONT_STACK[0]].family
#: 英寸换算：72 pt/in（与 `ShaperMetrics` 同一口径）。
_PER_INCH = 72.0


class _TableCatalog:
    """`MetricProvider` 只用到 `exists()` / `family()`；表里已有字体，不碰磁盘。

    `FontCatalog` 构造时会去 `$CONDA_PREFIX/fonts` 找**字体文件**，浏览器里没有
    这些文件（也不需要：宽度来自表里的 advance）。所以这里给一个只认表内容的
    最小目录，避免为了量一个宽度把 20 MB 的 CJK 字体塞进虚拟 FS。
    """

    def __init__(self, backend: TableBackend) -> None:
        self._files = frozenset(backend.fonts)

    def exists(self, filename: str) -> bool:
        return filename in self._files

    def family(self, filename: str) -> str:
        managed = MANAGED_FONTS.get(filename)
        return managed.family if managed is not None else filename.rsplit(".", 1)[0]


class TableMetrics:
    """`ggcore.units.Metrics` 的表实现（返回英寸，与 `ShaperMetrics` 同口径）。

    多行文本按 R 的 `stringWidth()` 取各行的最大值；`strheight()` 仍是 R 的
    `stringHeight()` = cap height + (n-1) × 行距。
    """

    def __init__(self, backend: TableBackend | None = None) -> None:
        backend = backend if backend is not None else TableBackend.from_file()
        self.backend = backend
        self.provider = MetricProvider(
            backend,
            catalog=_TableCatalog(backend),
            font_stack=DEFAULT_FONT_STACK,
        )
        #: 表里有的字体文件：解析出来的字面若不在表里就回落到栈首（如 `Noto Sans`
        #: 只在表外登记，见 `pixi run metrics:table` 的受管字体清单）。
        self._available = frozenset(backend.fonts)
        #: IR 字体 key → 字面栈。`stack()` 要按 key 解析字重/斜体，缓存住。
        self._stacks: dict[str, tuple[str, ...]] = {}

    # --- 字形栈 -----------------------------------------------------------

    def stack(self, key: str = "sans") -> tuple[str, ...]:
        """IR 的字体 key（`族` 或 `族:bold-italic`）→ 表里的字面栈（主字面在前）。"""
        cached = self._stacks.get(key)
        if cached is not None:
            return cached
        family, weight, italic = _parse_key(key)
        name = canonical_family(family) or _SANS_FAMILY
        try:
            primary = resolve_face(name, weight, italic, strict=False).filename
        except FontFaceError:  # pragma: no cover - 受管字族不会缺字面
            primary = DEFAULT_FONT_STACK[0]
        if primary not in self._available:
            # 表只收了一部分受管字面（生成清单见 `tools/metrics/build_table.py`）；
            # 缺的字面回落到栈首，而不是把「表里没有」变成一次崩溃。
            primary = DEFAULT_FONT_STACK[0]
        stack = tuple(
            filename
            for filename in dict.fromkeys((primary, *DEFAULT_FONT_STACK))
            if filename in self._available
        )
        self._stacks[key] = stack
        return stack

    # --- ggcore.units.Metrics --------------------------------------------

    def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        size = _size(fontsize, cex)
        if size <= 0.0:  # R 里 0 号字就是零宽；`provider` 对 <= 0 会报错
            return 0.0
        stack = self.stack(font)
        widths = [self.provider.strwidth(line, size, stack) for line in str(text).split("\n")]
        return (max(widths) if widths else 0.0) / _PER_INCH

    def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        size = _size(fontsize, cex)
        if size <= 0.0:
            return 0.0
        # cap height 与 `ShaperMetrics` 一样按 72.27 pt/in 的 typographic point 换算
        # （`docs/notes/metrics-ledger.md` · M0-7）；行距按 `gpar(lineheight)` 的缺省值。
        box = CAP_HEIGHT_EM * size * (72.27 / 72.0)
        lines = len(str(text).split("\n"))
        return (box + max(0, lines - 1) * LINE_PITCH * size) / _PER_INCH

    def descent(self, *, fontsize: float, cex: float = 1.0, font: str = "sans") -> float:
        size = _size(fontsize, cex)
        if size <= 0.0:
            return 0.0
        return self.provider.descent(size, self.stack(font)) / _PER_INCH


#: 单例：表解码 + 缓存只做一次（浏览器每次 `default_metrics()` 都重建会很慢）。
_DEFAULT: TableMetrics | None = None


def default_metrics() -> TableMetrics:
    """缺省的表度量（进程内单例）。浏览器与门禁都用它，两端读同一份表。"""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = TableMetrics()
    return _DEFAULT


def _size(fontsize: float, cex: float) -> float:
    return float(fontsize) * float(cex)


def _parse_key(key: str) -> tuple[str, int, bool]:
    """`族:style` → (族, weight, italic)；没有后缀时按常规字面。"""
    family, sep, style = str(key).rpartition(":")
    if not sep:
        return str(key), 400, False
    weight, italic = FACE_SUFFIXES.get(style.strip().lower(), (400, False))
    return (family.strip() or str(key)), weight, italic
