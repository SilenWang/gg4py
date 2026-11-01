"""基准基线：(pytest-benchmark) 占位 scene 的序列化。

`pixi run bench` 跑这一组，`--benchmark-autosave` 把结果写进 `.benchmarks/`
（不入库）。真正的基准（314 份快照的全量渲染）在 M0 后续阶段加上，判定方式
不变：同机同参数比较 min/mean，回归超过 20% 需要在 PR 里解释。
"""

from __future__ import annotations

from ggcore import placeholder_scene


def test_serialise_placeholder_scene(benchmark) -> None:
    """序列化 + 摘要，是 IR 每次导出都会走的热路径。"""
    scene = placeholder_scene()
    expected = scene.digest()

    assert benchmark(scene.digest) == expected
