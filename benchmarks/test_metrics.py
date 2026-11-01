"""M0-7 基线：度量缓存命中率与耗时。

`pixi run bench` 跑这一组。三件事分开量：

* **cold**：清空缓存后把 200 条冻结语料量一遍（shaping 的真实成本）；
* **warm**：同一批文字再量一遍（只剩缓存查找 + 求和）；
* **table**：兜底表（无 HarfBuzz 的 Pyodide 路径）同一批文字的成本。

命中率不是「感觉」：`test_cache_hit_rate` 断言 cold 全 miss、warm 全 hit，并把
统计打出来，回归（比如把 key 写成 id()）会直接红。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ggcore.metrics import FontCatalog, MetricProvider, TableBackend
from ggshape import harfbuzz_provider

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "docs" / "spike" / "corpus" / "labels_200.json"
SIZE = 16.0


@pytest.fixture(scope="module")
def texts() -> list[str]:
    return [label["text"] for label in json.loads(CORPUS.read_text(encoding="utf-8"))["labels"]]


@pytest.fixture(scope="module")
def provider() -> MetricProvider:
    return harfbuzz_provider(FontCatalog())


@pytest.fixture(scope="module")
def table_provider() -> MetricProvider:
    return MetricProvider(TableBackend.from_file(), catalog=FontCatalog())


def test_metrics_cold(provider: MetricProvider, texts: list[str], benchmark) -> None:
    def measure_all() -> float:
        return sum(provider.advance(text, SIZE) for text in texts)

    benchmark.pedantic(
        measure_all,
        setup=provider.clear_cache,
        rounds=5,
        iterations=1,
    )


def test_metrics_warm(provider: MetricProvider, texts: list[str], benchmark) -> None:
    expected = sum(provider.advance(text, SIZE) for text in texts)

    def cached() -> float:
        return sum(provider.advance(text, SIZE) for text in texts)

    assert benchmark(cached) == expected


def test_metrics_table_warm(table_provider: MetricProvider, texts: list[str], benchmark) -> None:
    expected = sum(table_provider.advance(text, SIZE) for text in texts)
    assert benchmark(lambda: sum(table_provider.advance(text, SIZE) for text in texts)) == expected


def test_cache_hit_rate(texts: list[str]) -> None:
    # 独立实例：benchmark 用例共用 module 级 provider，统计会被它们污染。
    # 语料里有重复标签，按去重后的条数断言命中/未命中。
    unique = list(dict.fromkeys(texts))
    provider = harfbuzz_provider(FontCatalog())
    for text in unique:
        provider.advance(text, SIZE)
    cold = provider.cache_stats()
    assert cold["misses"] == len(unique)
    assert cold["hits"] == 0
    assert cold["hit_rate"] == 0.0

    for text in unique:
        provider.advance(text, SIZE)
    warm = provider.cache_stats()
    assert warm["hits"] == len(unique)
    assert warm["misses"] == cold["misses"]
    assert warm["hit_rate"] == pytest.approx(0.5)
    print(
        f"metrics cache: entries={warm['entries']} hits={warm['hits']} "
        f"misses={warm['misses']} hit-rate={warm['hit_rate']:.1%}"
    )


def test_table_cache_hit_rate(texts: list[str]) -> None:
    unique = list(dict.fromkeys(texts))
    table_provider = MetricProvider(TableBackend.from_file(), catalog=FontCatalog())
    for text in unique:
        table_provider.advance(text, SIZE)
    for text in unique:
        table_provider.advance(text, SIZE)
    stats = table_provider.cache_stats()
    assert stats["hits"] == len(unique)
    print(f"table cache: entries={stats['entries']} hit-rate={stats['hit_rate']:.1%}")
