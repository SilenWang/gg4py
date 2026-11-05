"""M3-5 性能预算：降采样 / 度量缓存 / 增量重算的机制测试。

三条各自的可断言口径（实测数字在 `docs/notes/performance.md`，`pixi run perf:100k`）：

1. **降采样**只降行数，不换 IR 形状：还是同一个 `points` 节点、同样的 kind 序列，
   只是 `points` 缓冲少了行；同一份数据两次取样逐行相同（确定性）。
2. **度量缓存**：同一段文字第二次不再走 shaping（`MetricProvider` 的 hits 增长、
   misses 不变），`clear_metric_cache()` 之后重新算。
3. **增量重算**：开缓存与关缓存的 IR **逐字节相同**（内容键不会复用错东西），
   且重跑同内容时图层绘制与遍历都命中；改一个图层只让那一个图层失效。

最后一条是这一组测试的重点：缓存键是内容指纹，不是对象 id，所以「命中」必须
永远等价于「重算」。
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from ggcore import ir, perf
from ggcore.geom.scene import scene_from_plot
from ggcore.metrics.fallback import default_metrics
from ggcore.perf import (
    DownsampleWarning,
    fingerprint,
    resolve_max_points,
    sample_indices,
    sample_rows,
    table_fingerprint,
)
from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.script import run_script
from ggio.frame import to_column_table


@pytest.fixture(autouse=True)
def fresh_caches():
    """每条用例从「空缓存 + 开启」开始，互不污染（模块级缓存是进程内单例）。"""
    perf.enable_scene_cache()
    perf.clear_caches()
    yield
    perf.clear_caches()
    perf.enable_scene_cache()


def scatter(n: int, *, max_points: int | None = None) -> tuple[object, str]:
    rng = np.random.default_rng(7)
    data = to_column_table({"x": rng.normal(size=n), "y": rng.normal(size=n)})
    params = {} if max_points is None else {"max_points": max_points}
    return ggplot(data, aes(x="x", y="y")) + geom_point(**params), "scatter"


def points_rows(scene: ir.Scene) -> list[int]:
    """IR 里每个 `points` 节点的行数（降采样的直接证据）。"""
    rows: list[int] = []
    for node in ir.walk(scene.root):
        if node.kind is ir.NodeKind.POINTS:
            rows.append(int(node.bufs["points"].shape[0]))
    return rows


# ---------------------------------------------------------------------------
# 1. 降采样
# ---------------------------------------------------------------------------


def test_sample_indices_caps_and_keeps_order() -> None:
    picks = sample_indices(10_000, 1_000)
    assert picks.size == 1_000
    assert picks[0] == 0 and picks[-1] == 9_999
    assert np.all(np.diff(picks) > 0)  # 严格递增：行序不变


def test_sample_indices_is_deterministic() -> None:
    first = sample_indices(123_457, 4_321)
    second = sample_indices(123_457, 4_321)
    np.testing.assert_array_equal(first, second)


def test_sample_indices_noop_without_budget_or_below_it() -> None:
    np.testing.assert_array_equal(sample_indices(100, None), np.arange(100))
    np.testing.assert_array_equal(sample_indices(100, 100), np.arange(100))
    np.testing.assert_array_equal(sample_indices(100, 1_000), np.arange(100))


@pytest.mark.parametrize("bad", [0, -1, 1.5, "10", True])
def test_resolve_max_points_rejects_junk(bad: object) -> None:
    with pytest.raises(ValueError):
        resolve_max_points(bad)


def test_sample_rows_keeps_columns_in_sync() -> None:
    rng = np.random.default_rng(3)
    table = to_column_table({"x": rng.normal(size=5_000), "c": [f"k{i % 7}" for i in range(5_000)]})
    sampled = sample_rows(table, 500)
    assert sampled is not None
    assert sampled.nrows == 500
    assert sampled.names == table.names
    # 行内的一致性：x 与 c 来自同一行（c 的名字就是行号的函数）
    positions = sample_indices(5_000, 500)
    assert list(sampled.column("c").values) == [f"k{i % 7}" for i in positions]


def test_max_points_only_changes_the_point_buffer() -> None:
    full, _ = scatter(10_000)
    sampled, _ = scatter(10_000, max_points=1_000)
    full_scene = scene_from_plot(full, width_in=5.0, height_in=3.5, metrics=default_metrics())
    with pytest.warns(DownsampleWarning):
        sampled_scene = scene_from_plot(
            sampled, width_in=5.0, height_in=3.5, metrics=default_metrics()
        )
    assert points_rows(full_scene) == [10_000]
    assert points_rows(sampled_scene) == [1_000]
    kinds = [node.kind for node in ir.walk(full_scene.root)]
    assert [node.kind for node in ir.walk(sampled_scene.root)] == kinds


def test_max_points_is_deterministic() -> None:
    plot, _ = scatter(5_000, max_points=500)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DownsampleWarning)
        first = ir.encode(scene_from_plot(plot, metrics=default_metrics()))
        second = ir.encode(scene_from_plot(plot, metrics=default_metrics()))
    assert first == second


def test_max_points_does_not_fire_below_the_budget() -> None:
    plot, _ = scatter(300, max_points=1_000)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DownsampleWarning)
        scene = scene_from_plot(plot, metrics=default_metrics())
    assert points_rows(scene) == [300]


# ---------------------------------------------------------------------------
# 2. 度量缓存
# ---------------------------------------------------------------------------


def test_metrics_cache_reuses_shaping_across_runs() -> None:
    plot, _ = scatter(50)
    plot = plot + labs(title="重复的标题", subtitle="第二行文字")
    metrics = default_metrics()
    perf.clear_metric_cache()
    scene_from_plot(plot, width_in=5.0, height_in=3.5, metrics=metrics)
    cold = perf.metric_cache_stats()["table"]
    # 一张图里同一段文字会被量多次（版式 + 轴 + 图层），所以冷启动也有命中；
    # 判据是**没有新的 shaping**：第二张图的 misses 不再增长。
    assert cold["misses"] > 0

    scene_from_plot(plot, width_in=5.0, height_in=3.5, metrics=metrics)
    warm = perf.metric_cache_stats()["table"]
    assert warm["misses"] == cold["misses"]  # 没有新的 shaping
    assert warm["hits"] > cold["hits"]  # 全部走缓存

    perf.clear_metric_cache()
    assert perf.metric_cache_stats()["table"]["hits"] == 0


def test_metrics_cache_survives_new_plot_objects() -> None:
    """重跑会造新对象：缓存键是文字而不是对象，所以照样命中。"""
    metrics = default_metrics()
    first, _ = scatter(10)
    second, _ = scatter(10)
    scene_from_plot(first, metrics=metrics)
    before = perf.metric_cache_stats()["table"]
    scene_from_plot(second, metrics=metrics)
    after = perf.metric_cache_stats()["table"]
    assert after["misses"] == before["misses"]


# ---------------------------------------------------------------------------
# 3. 增量重算
# ---------------------------------------------------------------------------


def test_cached_and_uncached_scenes_are_byte_identical() -> None:
    plot, _ = scatter(2_000)
    plot = plot + labs(title="t", subtitle="s")
    expected = ir.encode(scene_from_plot(plot, metrics=default_metrics()))

    perf.enable_scene_cache()
    perf.clear_caches()
    cached = ir.encode(scene_from_plot(plot, metrics=default_metrics()))  # 冷
    assert perf.scene_cache_stats()["misses"] > 0
    identical = ir.encode(scene_from_plot(plot, metrics=default_metrics()))  # 热
    assert identical == cached

    perf.disable_scene_cache()
    uncached = ir.encode(scene_from_plot(plot, metrics=default_metrics()))
    assert uncached == cached == expected


def test_second_run_hits_both_caches() -> None:
    plot, _ = scatter(5_000)
    for _ in range(3):
        scene_from_plot(plot, metrics=default_metrics())
    stats = perf.cache_stats()
    assert stats["layers"]["hits"] >= 2
    assert stats["layers"]["misses"] == 1
    assert stats["scene"]["hit_rate"] > 0.6


def test_changing_one_layer_only_invalidates_that_layer() -> None:
    rng = np.random.default_rng(11)
    data = to_column_table({"x": rng.normal(size=2_000), "y": rng.normal(size=2_000)})
    base = ggplot(data, aes(x="x", y="y")) + geom_point() + geom_point(colour="red")
    scene_from_plot(base, metrics=default_metrics())
    first = perf.cache_stats()["layers"]

    changed = ggplot(data, aes(x="x", y="y")) + geom_point(size=2.0) + geom_point(colour="red")
    scene_from_plot(changed, metrics=default_metrics())
    second = perf.cache_stats()["layers"]
    # 两个图层里只有 `size` 变了那一个失效：新增 1 次命中 + 1 次未命中。
    assert second["hits"] - first["hits"] == 1
    assert second["misses"] - first["misses"] == 1


def test_cache_returns_identical_ir_after_a_style_change() -> None:
    rng = np.random.default_rng(5)
    data = to_column_table({"x": rng.normal(size=500), "y": rng.normal(size=500)})
    base = ggplot(data, aes(x="x", y="y")) + geom_point()
    scene = ir.encode(scene_from_plot(base, metrics=default_metrics()))
    styled = ggplot(data, aes(x="x", y="y")) + geom_point(size=3.0)
    perf.disable_scene_cache()
    expected = ir.encode(scene_from_plot(styled, metrics=default_metrics()))
    perf.enable_scene_cache()
    reused = ir.encode(scene_from_plot(styled, metrics=default_metrics()))
    assert reused == expected
    assert scene != expected  # 反面对照：样式真的变了


def test_fingerprint_is_content_addressed() -> None:
    rng = np.random.default_rng(9)
    table = to_column_table({"x": rng.normal(size=100), "y": rng.normal(size=100)})
    clone = to_column_table(
        {
            "x": np.array(table.column("x").values),
            "y": np.array(table.column("y").values),
        }
    )
    assert table_fingerprint(table) == table_fingerprint(clone)
    other = to_column_table({"x": np.array(table.column("x").values) + 0.5, "y": np.zeros(100)})
    assert table_fingerprint(other) != table_fingerprint(table)
    assert fingerprint({"a": 1.0}) == fingerprint({"a": 1.0})
    assert fingerprint({"a": 1.0}) != fingerprint({"a": 1})


def test_script_rerun_is_cheaper_and_identical() -> None:
    """编辑器路径：同一段代码重跑，IR 逐字节相同（缓存不改变结果）。"""
    source = """
import numpy as np
from ggcore.plot import aes, geom_point, ggplot
from ggio.frame import to_column_table

rng = np.random.default_rng(1)
DATA = {"x": rng.normal(size=3000), "y": rng.normal(size=3000)}

def build():
    return {"plot": ggplot(to_column_table(DATA), aes(x="x", y="y")) + geom_point(),
            "size": [5.0, 3.5]}
"""
    first = run_script(source)
    second = run_script(source)
    assert first.ir_bytes == second.ir_bytes
    assert perf.cache_stats()["layers"]["hits"] >= 1
