"""`ggcore.perf` —— 性能预算：大数据降采样 / 度量缓存 / 增量重算（M3-5）。

三件事各自独立，都在这里收口，不在几何 / 场景代码里各写一份：

**1. 降采样**（:func:`sample_indices` / :func:`sample_rows`）

    p = ggplot(data, aes(x="x", y="y")) + geom_point(max_points=20_000)

`max_points` 是**显式**参数，缺省不降：ggplot2 的对等口径是「给多少点画多少点」，
悄悄丢点是行为改变，不是优化。超过预算时按**行号等距**取子集（`stride` 策略：
确定性、无随机数、保持行序、不改变 IR 的形状——还是同一个 `points` 节点，只是
缓冲行数变少）。见 `docs/notes/performance.md`。

**2. 度量缓存**（:func:`metric_cache_stats` / :func:`clear_metric_cache`）

文字宽度是版式与 IR 的输入，同一段文字在重跑里被反复量。缓存有两层，都在这里
可见：`ggcore.metrics.MetricProvider` 的 LRU（按 `(text, size, font_stack)`），
以及 `ggcore.io` 里「一个后端一份度量实例」的进程内复用（`ggskia` 的
`ShaperMetrics` 每次 ggsave 新建一份就等于没有缓存）。

**3. 增量重算**（:class:`SceneInstructionCache`）

场景遍历（grob 树 → 扁平 IR 指令）是整条链上最贵的一段：10 万点要建 20 万个
单位元素再逐个换算。缓存键是**内容**（`grob` 的指纹 + 视口变换 + 裁剪 + 生效
gpar + 度量实例），不是对象 id——同一段代码重跑会造出内容相同的新 grob，指纹
相同就能命中；改一行只影响变化的那部分（改数据 → 该层叶子重算，其它层照旧）。

内容键保证「同样的输入 ⇒ 同样的指令」：命中返回的就是上次那份不可变
`Instruction` 元组，`to_node()` 之后照常只读。命中率与条目数进
:func:`scene_cache_stats`，`pixi run perf:100k` 会把它们打出来。

关闭缓存：环境变量 `GG4PY_NO_SCENE_CACHE=1`（前后对比实测就用它），或
:func:`disable_scene_cache`。
"""

from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import Any

import numpy as np

from ggcore.data import ColumnTable
from ggcore.units import Unit

__all__ = [
    "DEFAULT_MAX_POINTS",
    "DEFAULT_SAMPLE_STRATEGY",
    "DownsampleWarning",
    "SceneInstructionCache",
    "cache_stats",
    "clear_caches",
    "clear_metric_cache",
    "disable_scene_cache",
    "enable_scene_cache",
    "fingerprint",
    "metric_cache_stats",
    "resolve_max_points",
    "sample_indices",
    "sample_rows",
    "scene_cache",
    "scene_cache_stats",
]


class DownsampleWarning(RuntimeWarning):
    """降采样真的发生了（画出来的点数少于数据行数）。"""


#: `geom_point(max_points=)` 缺省值：`None` 表示不降采样（对等口径，见模块头）。
DEFAULT_MAX_POINTS: int | None = None
#: 目前只有一种策略：按行号等距取子集。
DEFAULT_SAMPLE_STRATEGY = "stride"

#: 指令缓存的容量（条目数 / 总行数）。按行数估算内存：一行点 = 两个 float64
#: buffer（16 B），一行线段 = 四个（32 B），所以 100 万行大约 16–32 MB。
DEFAULT_CACHE_ENTRIES = 512
DEFAULT_CACHE_ROWS = 1_000_000
#: 图层绘制缓存单独一档：它存的是 grob（每行两个 `UnitElement` 对象，约 100 B/行），
#: 同样行数的内存是指令缓存的好几倍，所以封顶更小。
DEFAULT_DRAW_CACHE_ENTRIES = 64
DEFAULT_DRAW_CACHE_ROWS = 400_000

_STRATEGIES = frozenset({DEFAULT_SAMPLE_STRATEGY})


# ---------------------------------------------------------------------------
# 1. 降采样
# ---------------------------------------------------------------------------


def resolve_max_points(value: Any) -> int | None:
    """校验 `max_points` 参数：`None` / 正整数，别的都报错（别静默忽略）。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"max_points 必须是正整数或 None，收到 {value!r}")
    number = int(value)
    if number < 1:
        raise ValueError(f"max_points 必须 >= 1，收到 {value!r}")
    return number


def sample_indices(
    n_rows: int,
    max_points: int | None,
    *,
    strategy: str = DEFAULT_SAMPLE_STRATEGY,
) -> np.ndarray:
    """`n_rows` 行里取至多 `max_points` 个行号（确定性、保持行序）。

    `stride` 策略：`round(linspace(0, n-1, max_points))` 再去重。行号等距意味着
    对**无序**数据是无偏抽样；对已排序的数据也不会把点挤在某一侧（相比「取前 N
    个」）。不引入随机数：同一份数据每次跑出同一张图，IR 才能逐字节可比。
    """
    if strategy not in _STRATEGIES:
        raise ValueError(f"不认识的降采样策略 {strategy!r}（可选：{sorted(_STRATEGIES)}）")
    if isinstance(n_rows, bool) or not isinstance(n_rows, (int, np.integer)):
        raise ValueError(f"n_rows 必须是整数，收到 {n_rows!r}")
    n = int(n_rows)
    if n < 0:
        raise ValueError(f"n_rows 不能为负，收到 {n_rows!r}")
    if max_points is None or n <= int(max_points):
        return np.arange(n, dtype=np.int64)
    budget = resolve_max_points(max_points)
    assert budget is not None  # 上面的分支已经排除 None
    picks = np.linspace(0.0, float(n - 1), num=budget)
    return np.unique(np.rint(picks).astype(np.int64))


def sample_rows(
    table: ColumnTable,
    max_points: int | None,
    *,
    strategy: str = DEFAULT_SAMPLE_STRATEGY,
) -> ColumnTable | None:
    """表格行降采样；不需要降（或没有列）时返回 `None`（调用方沿用原表）。"""
    if max_points is None or table.nrows <= int(max_points):
        return None
    from ggcore.geom.base import row_slice

    indices = sample_indices(table.nrows, max_points, strategy=strategy)
    if indices.size == table.nrows:  # pragma: no cover - 预算比表大时不会到这里
        return None
    return row_slice(table, indices)


# ---------------------------------------------------------------------------
# 2. 度量缓存
# ---------------------------------------------------------------------------


def metric_cache_stats() -> dict[str, Any]:
    """当前进程里两份度量实现的缓存统计（命中率 / 条目数）。

    `ggcore.metrics.fallback.default_metrics()` 是浏览器与门禁路径的单例；
    `ggskia` 的 `ShaperMetrics` 由 `ggcore.io` 在每个线程里复用同一份
    （见 `docs/notes/performance.md` 的「度量缓存」）。
    """
    from ggcore.metrics.fallback import default_metrics

    table = default_metrics()
    stats: dict[str, Any] = {
        "table": _provider_stats(table),
    }
    try:  # pragma: no cover - 桌面 / 服务端才有 skia
        from ggcore.io import backend_metrics

        desktop = backend_metrics()
    except Exception:  # pragma: no cover - 没注册后端就是浏览器 / 纯 ggcore 路径
        desktop = None
    if desktop is not None:
        stats["desktop"] = _provider_stats(desktop)
    return stats


def _provider_stats(metrics: Any) -> dict[str, Any]:
    provider = getattr(metrics, "provider", None)
    if provider is None or not hasattr(provider, "cache_stats"):
        return {"entries": 0, "hits": 0, "misses": 0, "hit_rate": 0.0}
    stats = provider.cache_stats()
    return {
        "entries": int(stats["entries"]),
        "hits": int(stats["hits"]),
        "misses": int(stats["misses"]),
        "hit_rate": float(stats["hit_rate"]),
    }


def clear_metric_cache() -> None:
    """清空两份度量缓存（实测「冷 / 热」两组数字时用）。"""
    from ggcore.metrics.fallback import default_metrics

    _clear_provider(default_metrics())
    try:  # pragma: no cover - 桌面 / 服务端
        from ggcore.io import backend_metrics

        desktop = backend_metrics()
    except Exception:  # pragma: no cover
        desktop = None
    if desktop is not None:
        _clear_provider(desktop)


def _clear_provider(metrics: Any) -> None:
    provider = getattr(metrics, "provider", None)
    if provider is None:
        return
    cache = getattr(provider, "_cache", None)
    if cache is not None:
        cache.clear()
    for name in ("hits", "misses", "evictions"):
        if hasattr(provider, name):
            setattr(provider, name, 0)


# ---------------------------------------------------------------------------
# 3. 增量重算：场景指令缓存
# ---------------------------------------------------------------------------


def _feed(hasher: Any, value: Any) -> None:
    """把任意值喂给哈希（`blake2b`）：类型标签 + 内容，不看对象 id。

    - `Unit`：批量几何走数组（10 万个元素不逐条 `repr`）；
    - numpy 数组：dtype + shape + 字节；
    - dataclass：按字段顺序（`grob` / `Gpar` 都是这种）；
    - 其余：`repr`（浮点用 `repr` 保住 `-0.0` / `NaN` 的区别）。
    """
    if value is None or value is True or value is False:
        hasher.update(b"\x00" + repr(value).encode())
        return
    if isinstance(value, Unit):
        hasher.update(b"u" + str(len(value)).encode())
        elements = value.elements
        kinds = {element.kind for element in elements}
        if len(kinds) == 1:
            hasher.update(b"k" + next(iter(kinds)).encode())
            amounts = np.fromiter(
                (element.amount for element in elements), dtype=np.float64, count=len(elements)
            )
            _feed_array(hasher, amounts)
        else:
            for element in elements:
                hasher.update(b"e" + element.kind.encode())
                hasher.update(np.float64(element.amount).tobytes())
        return
    if isinstance(value, np.ndarray):
        _feed_array(hasher, value)
        return
    if isinstance(value, (bytes, bytearray, memoryview)):
        hasher.update(b"b" + len(value).to_bytes(8, "little"))
        hasher.update(bytes(value))
        return
    if isinstance(value, str):
        encoded = value.encode("utf-8", "surrogatepass")
        hasher.update(b"s" + len(encoded).to_bytes(8, "little") + encoded)
        return
    if isinstance(value, (int, np.integer)):
        hasher.update(b"i" + int(value).to_bytes(8, "little", signed=True))
        return
    if isinstance(value, (float, np.floating)):
        hasher.update(b"f" + np.float64(value).tobytes())
        return
    if is_dataclass(value) and not isinstance(value, type):
        hasher.update(b"d" + type(value).__name__.encode())
        for field in fields(value):
            _feed(hasher, getattr(value, field.name))
        return
    if isinstance(value, Mapping):
        hasher.update(b"m" + str(len(value)).encode())
        for key in sorted(value, key=lambda item: repr(item)):
            _feed(hasher, key)
            _feed(hasher, value[key])
        return
    if isinstance(value, (list, tuple)):
        hasher.update(b"l" + str(len(value)).encode())
        for item in value:
            _feed(hasher, item)
        return
    hasher.update(b"r" + repr(value).encode())


def _feed_array(hasher: Any, array: np.ndarray) -> None:
    hasher.update(b"a" + array.dtype.str.encode() + str(array.shape).encode())
    hasher.update(np.ascontiguousarray(array).tobytes())


def _feed_column(hasher: Any, column: Any) -> None:
    """`ggcore.data.Column` 的内容（kind + 值缓冲 + 缺失掩码）。"""
    hasher.update(b"c" + str(getattr(column, "kind", "")).encode())
    values = getattr(column, "values", None)
    if isinstance(values, np.ndarray):
        _feed_array(hasher, values)
    else:  # pragma: no cover - 列一定是 ndarray
        _feed(hasher, values)
    mask = getattr(column, "na_mask", None)
    if mask is not None:
        _feed_array(hasher, np.asarray(mask, dtype=bool))


def table_fingerprint(table: ColumnTable) -> bytes:
    """`ColumnTable` 的内容指纹（列名 / 列序 / 值 / 缺失位，不看对象 id）。"""
    hasher = hashlib.blake2b(digest_size=16)
    hasher.update(b"t" + str(table.nrows).encode())
    for name in table.names:
        encoded = name.encode("utf-8", "surrogatepass")
        hasher.update(b"n" + len(encoded).to_bytes(8, "little") + encoded)
        _feed_column(hasher, table.column(name))
    return hasher.digest()


def fingerprint(value: Any) -> bytes:
    """值的内容指纹（128 位 blake2b）。"""
    hasher = hashlib.blake2b(digest_size=16)
    _feed(hasher, value)
    return hasher.digest()


class SceneInstructionCache:
    """场景遍历的指令缓存：(内容键) → 不可变指令元组（LRU）。

    键由 `_Traverser` 拼：grob 指纹 + 视口路径 + 页面仿射 + 裁剪框 + 生效 gpar +
    度量实例。任何一项不同都算新内容，宁可重算也不复用错的东西。
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_CACHE_ENTRIES,
        max_rows: int = DEFAULT_CACHE_ROWS,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.max_rows = max(1, int(max_rows))
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self._entries: OrderedDict[tuple[Any, ...], tuple[Any, tuple[Any, ...]]] = OrderedDict()
        self._rows = 0

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def rows(self) -> int:
        return self._rows

    def get(self, key: tuple[Any, ...], metrics: Any) -> tuple[Any, ...] | None:
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        owner, instructions = entry
        if owner is not metrics:  # 度量实例不是同一份：重新算（id 复用也挡得住）
            self.misses += 1
            return None
        self.hits += 1
        self._entries.move_to_end(key)
        return instructions

    def put(self, key: tuple[Any, ...], instructions: tuple[Any, ...], metrics: Any) -> None:
        if not instructions:
            return
        rows = sum(int(getattr(item, "rows", 0)) for item in instructions)
        if rows > self.max_rows:
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._rows -= self._entry_rows(previous)
        self._entries[key] = (metrics, instructions)
        self._rows += rows
        while self._entries and (
            len(self._entries) > self.max_entries or self._rows > self.max_rows
        ):
            _, dropped = self._entries.popitem(last=False)
            self._rows -= self._entry_rows(dropped)
            self.evictions += 1

    @staticmethod
    def _entry_rows(entry: tuple[Any, tuple[Any, ...]]) -> int:
        return sum(int(getattr(item, "rows", 0)) for item in entry[1])

    def clear(self) -> None:
        self._entries.clear()
        self._rows = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "entries": len(self._entries),
            "rows": self._rows,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": (self.hits / total) if total else 0.0,
        }


#: 进程内的一份缓存（编辑器 / 服务端都是「跑一次图再跑一次」的形状）。
_CACHE = SceneInstructionCache()


class LayerDrawCache:
    """`geom.draw()` 的结果缓存：(内容键) → grob（LRU，按行数封顶）。

    键 = geom 名 + 图层数据指纹 + 图层参数指纹 + 面板号 + 面板参数指纹 + 主题
    指纹。geom 只读这三样东西（`build.data` / `build.params` / `metrics`，见
    `src/ggcore/geom/*.py`），所以这组键足以判定「画出来的东西一样」。
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_DRAW_CACHE_ENTRIES,
        max_rows: int = DEFAULT_DRAW_CACHE_ROWS,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.max_rows = max(1, int(max_rows))
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self._entries: OrderedDict[tuple[Any, ...], tuple[Any, Any, int]] = OrderedDict()
        self._rows = 0

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: tuple[Any, ...], metrics: Any) -> Any | None:
        entry = self._entries.get(key)
        if entry is None or entry[0] is not metrics:
            self.misses += 1
            return None
        self.hits += 1
        self._entries.move_to_end(key)
        return entry[1]

    def put(self, key: tuple[Any, ...], grob: Any, metrics: Any, rows: int) -> None:
        rows = int(rows)
        if rows > self.max_rows:
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._rows -= previous[2]
        self._entries[key] = (metrics, grob, rows)
        self._rows += rows
        while self._entries and (
            len(self._entries) > self.max_entries or self._rows > self.max_rows
        ):
            _, dropped = self._entries.popitem(last=False)
            self._rows -= dropped[2]
            self.evictions += 1

    def clear(self) -> None:
        self._entries.clear()
        self._rows = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "entries": len(self._entries),
            "rows": self._rows,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": (self.hits / total) if total else 0.0,
        }


_DRAW_CACHE = LayerDrawCache()

#: 关闭开关：实测前后对比、或排查「为什么复用了旧指令」时用它。
_ENABLED = os.environ.get("GG4PY_NO_SCENE_CACHE", "") not in ("1", "true", "yes")


def scene_cache() -> SceneInstructionCache | None:
    """当前生效的缓存实例；被关掉时返回 `None`（遍历器据此完全不碰缓存）。"""
    return _CACHE if _ENABLED else None


def layer_draw_cache() -> LayerDrawCache | None:
    """图层绘制缓存；与指令缓存同一个开关。"""
    return _DRAW_CACHE if _ENABLED else None


def enable_scene_cache() -> SceneInstructionCache:
    global _ENABLED
    _ENABLED = True
    return _CACHE


def disable_scene_cache() -> None:
    global _ENABLED
    _ENABLED = False


def scene_cache_stats() -> dict[str, Any]:
    return _CACHE.stats()


def cache_stats() -> dict[str, Any]:
    """三类缓存的合并视图（`pixi run perf:100k` 的打印口径）。"""
    return {
        "scene": scene_cache_stats(),
        "layers": _DRAW_CACHE.stats(),
        "metrics": metric_cache_stats(),
        "enabled": _ENABLED,
    }


def clear_caches() -> None:
    _CACHE.clear()
    _DRAW_CACHE.clear()
    clear_metric_cache()
