"""`MetricProvider`：文本度量（M0-7）。

一个 provider = 一个形状后端（`MetricsBackend`）+ 一份字体目录 + 一份字体栈。
后端决定「怎么量」：

* `ggshape.harfbuzz.HarfBuzzBackend`：CPython/服务端/桌面，真 shaping（HarfBuzz
  15），与浏览器 CanvasKit.Paragraph 同源，差异 < 0.5%（`pixi run gate:metrics`）。
* `ggcore.metrics.table.TableBackend`：无 HarfBuzz 时（Pyodide 早期路径）读预生成
  度量表，只做逐码点 advance + 粘着/grapheme 规则，不支持上下文 shaping 的书写
  系统（`ggcore.metrics.runs.COMPLEX_SCRIPT_RANGES`）。

两件事刻意放在 provider 而不是后端里，因为它们必须两端一致：

1. **run 切分**（`runs.split_runs`）：字族回退 + 粘着码点，逐字面相同。
2. **尺寸换算**：`font_units / upem * size`，结果为 CSS px（与 CanvasKit
   `fontSize` 同一口径）。

缓存：以 `(text, size, font_stack)` 为键缓存整段文字的 run 结果（含每 run 宽度），
命中后移到队尾、超出容量淘汰最旧的一条（LRU）。命中率与耗时进 `pixi run bench`
（`benchmarks/test_metrics.py`）与门禁输出。
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ggcore.metrics.catalog import DEFAULT_FONT_STACK, FontCatalog
from ggcore.metrics.runs import Run, split_runs, stack_tuple


@dataclass(frozen=True)
class FontMetrics:
    """字体的纵向度量，单位是字体设计单位（font units）。"""

    upem: int
    ascent: int
    # 下降部取正数（向下的距离）；HarfBuzz/Skia 的 descender 是负数，这里抹平符号。
    descent: int


@dataclass(frozen=True)
class ShapedRun:
    """一个 run 的形状结果，advance 为字体设计单位。"""

    gids: tuple[int, ...] = ()
    advances: tuple[float, ...] = ()

    @property
    def total(self) -> float:
        return math.fsum(self.advances)


@dataclass(frozen=True)
class RunMeasurement:
    """一个 run 在某个字号下的量度结果。"""

    font: str
    family: str
    text: str
    width: float


@runtime_checkable
class MetricsBackend(Protocol):
    """形状后端接口。文件名（不是路径）作为字体键，由 provider 交给 catalog 解析。"""

    name: str

    def font_metrics(self, filename: str) -> FontMetrics: ...

    def covers(self, filename: str, codepoint: int) -> bool: ...

    def shape(self, filename: str, text: str) -> ShapedRun: ...

    def supports(self, text: str) -> bool: ...


class MetricProvider:
    """把文本量成 px。线程不安全（缓存无锁），跨线程请各建一个实例。"""

    def __init__(
        self,
        backend: MetricsBackend,
        catalog: FontCatalog | None = None,
        font_stack: Sequence[str] = DEFAULT_FONT_STACK,
        cache_size: int = 4096,
    ) -> None:
        self.backend = backend
        self.catalog = catalog if catalog is not None else FontCatalog()
        self.font_stack = tuple(font_stack)
        if not self.font_stack:
            raise ValueError("font_stack must not be empty")
        missing = [name for name in self.font_stack if not self.catalog.exists(name)]
        if missing:
            raise LookupError(f"font_stack has fonts the catalog cannot find: {missing}")
        self.cache_size = int(cache_size)
        self._cache: OrderedDict[tuple[str, float, tuple[str, ...]], tuple[RunMeasurement, ...]]
        self._cache = OrderedDict()
        self._metrics: dict[str, FontMetrics] = {}
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    # --- 度量 -------------------------------------------------------------

    def font_metrics(self, filename: str) -> FontMetrics:
        if filename not in self._metrics:
            self._metrics[filename] = self.backend.font_metrics(filename)
        return self._metrics[filename]

    def runs(
        self,
        text: str,
        size: float,
        font_stack: Sequence[str] | None = None,
    ) -> tuple[RunMeasurement, ...]:
        """显式 run 切分结果与每个 run 的宽度（px）。"""
        stack = stack_tuple(font_stack, self.font_stack)
        px = _check_size(size)
        key = (text, px, stack)
        cached = self._cache.get(key)
        if cached is not None:
            self.hits += 1
            self._cache.move_to_end(key)
            return cached
        self.misses += 1
        measurements = self._measure(text, px, stack)
        self._cache[key] = measurements
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
            self.evictions += 1
        return measurements

    def advance(self, text: str, size: float, font_stack: Sequence[str] | None = None) -> float:
        """整段文字的 advance（px）。"""
        return math.fsum(r.width for r in self.runs(text, size, font_stack))

    def strwidth(self, text: str, size: float, font_stack: Sequence[str] | None = None) -> float:
        """`grid::strwidth` 对等物：整段文字的宽度（px）。"""
        return self.advance(text, size, font_stack)

    def strheight(self, text: str, size: float, font_stack: Sequence[str] | None = None) -> float:
        """`grid::strheight` 对等物：文字占的行高（px）= 最高字族的 ascent + descent。

        空串按字体栈主字族算，这样 theme 的行高不会因为标签为空而塌成 0。
        """
        stack = stack_tuple(font_stack, self.font_stack)
        px = _check_size(size)
        fonts = [run.font for run in self.runs(text, px, stack)] or [stack[0]]
        heights = []
        for filename in dict.fromkeys(fonts):
            metrics = self.font_metrics(filename)
            heights.append((metrics.ascent + metrics.descent) / metrics.upem * px)
        return max(heights)

    def ascent(self, size: float, font_stack: Sequence[str] | None = None) -> float:
        """字体栈主字族的 ascent（px，向上为正）。"""
        metrics = self.font_metrics(stack_tuple(font_stack, self.font_stack)[0])
        return metrics.ascent / metrics.upem * _check_size(size)

    def descent(self, size: float, font_stack: Sequence[str] | None = None) -> float:
        """字体栈主字族的 descent（px，向下为正）。"""
        metrics = self.font_metrics(stack_tuple(font_stack, self.font_stack)[0])
        return metrics.descent / metrics.upem * _check_size(size)

    # --- 能力与缓存 -------------------------------------------------------

    def supports(self, text: str) -> bool:
        """当前后端能否精确量这段文字（兜底表对复杂书写系统返回 False）。"""
        return self.backend.supports(text)

    def clear_cache(self) -> None:
        self._cache.clear()

    def cache_stats(self) -> dict[str, float | int]:
        total = self.hits + self.misses
        return {
            "entries": len(self._cache),
            "capacity": self.cache_size,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": (self.hits / total) if total else 0.0,
        }

    # --- 内部 -------------------------------------------------------------

    def _measure(
        self, text: str, size: float, stack: tuple[str, ...]
    ) -> tuple[RunMeasurement, ...]:
        def covers(index: int, codepoint: int) -> bool:
            return self.backend.covers(stack[index], codepoint)

        runs: tuple[Run, ...] = split_runs(text, covers, len(stack))
        out: list[RunMeasurement] = []
        for run in runs:
            filename = stack[run.font_index]
            metrics = self.font_metrics(filename)
            shaped = self.backend.shape(filename, run.text)
            width = shaped.total / metrics.upem * size
            out.append(
                RunMeasurement(
                    font=filename,
                    family=self.catalog.family(filename),
                    text=run.text,
                    width=width,
                )
            )
        return tuple(out)


def _check_size(size: float) -> float:
    px = float(size)
    if not math.isfinite(px) or px <= 0:
        raise ValueError(f"font size must be a positive finite number, got {size!r}")
    return px
