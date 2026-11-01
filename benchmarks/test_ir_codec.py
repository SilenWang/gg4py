"""基准基线：(pytest-benchmark) IR 编解码。

`pixi run bench` 跑这一组，`--benchmark-autosave` 把结果写进 `.benchmarks/`
（不入库）。真正的基准（314 份快照的全量渲染）在 M0 后续阶段加上，判定方式
不变：同机同参数比较 min/mean，回归超过 20% 需要在 PR 里解释。
"""

from __future__ import annotations

from ggcore.ir import decode, demo_scene, encode


def test_encode_demo_scene(benchmark) -> None:
    """IR 每次导出都会走的热路径：scene → CBOR 字节。"""
    scene = demo_scene()
    expected = encode(scene)

    assert benchmark(lambda: encode(scene)) == expected


def test_decode_demo_scene(benchmark) -> None:
    """浏览器/设备侧的入口：CBOR 字节 → scene。"""
    data = encode(demo_scene())
    expected = decode(data)

    assert benchmark(lambda: decode(data)) == expected
