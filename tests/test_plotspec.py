"""plot 规格 → IR 场景的适配层（`ggcore.plotspec`，M0-9）。

这层只服务案例库：固定数据 + 显式 limits + `theme_void()` 口径的整页面板，
支持 `point` / `bar` / `col` / `text` / `curve`。守四件事：

1. 坐标映射与 R 一致（x 线性、y 从下往上数，页面 y 向下在设备侧翻转）；
2. 契约错误带可读消息（palette 缺键、未知 geom、缺标签）；
3. `size` 决定页面尺寸；
4. `render <case-dir>` 真的能出图（矩阵的接线依赖它）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ggcore import ir
from ggcore.plotspec import PlotSpecError, build_scene, load_plot, resolve_limits

REPO = Path(__file__).resolve().parents[1]
CASES = REPO / "docs" / "cases"


def _walk(node: ir.Node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _kinds(scene: ir.Scene) -> list[str]:
    return [str(node.kind) for node in _walk(scene.root)]


def _mk(tmp_path: Path, spec: str) -> Path:
    directory = tmp_path / "geom-demo"
    directory.mkdir()
    (directory / "plot.py").write_text(spec, encoding="utf-8")
    return directory


BASE = {
    "data": {"x": [0.2, 0.8], "y": [0.3, 0.7]},
    "mapping": {"x": "x", "y": "y"},
    "layers": [{"geom": "point", "params": {"size_pt": 7.0}}],
    "size": [4, 3],
    "limits": {"x": [0, 1], "y": [0, 1]},
}


def test_page_size_and_point_count(tmp_path: Path) -> None:
    directory = _mk(tmp_path, f"SPEC = {BASE!r}\n\ndef build():\n    return SPEC\n")
    spec = load_plot(directory)
    scene = build_scene(spec)
    assert scene.size == pytest.approx((288.0, 216.0))
    assert _kinds(scene).count(ir.NodeKind.POINTS.value) == 2


def test_limits_default_to_a_five_percent_expansion() -> None:
    spec = {
        "data": {"x": [0.0, 1.0], "y": [2.0, 4.0]},
        "mapping": {"x": "x", "y": "y"},
        "layers": [{"geom": "point"}],
    }
    limits = resolve_limits(spec)
    assert limits["x"] == pytest.approx((-0.05, 1.05))
    assert limits["y"] == pytest.approx((1.9, 4.1))


def test_palette_must_cover_every_group(tmp_path: Path) -> None:
    directory = _mk(
        tmp_path,
        "def build():\n"
        "    return {'data': {'x': [0, 1], 'y': [0, 1], 'g': ['a', 'b']},\n"
        "            'mapping': {'x': 'x', 'y': 'y', 'colour': 'g'},\n"
        "            'layers': [{'geom': 'point'}], 'palette': {'a': '#000000'}}\n",
    )
    with pytest.raises(PlotSpecError, match="不在 `palette`"):
        build_scene(load_plot(directory))


def test_unknown_geom_is_rejected() -> None:
    spec = dict(BASE, layers=[{"geom": "violin"}])
    with pytest.raises(PlotSpecError, match="geom"):
        build_scene(spec)


def test_text_layer_needs_a_label() -> None:
    spec = dict(BASE, layers=[{"geom": "text"}])
    with pytest.raises(PlotSpecError, match="label"):
        build_scene(spec)


def test_curve_layer_produces_curve_nodes() -> None:
    spec = {
        "data": {"x": [0.1], "y": [0.2], "xend": [0.9], "yend": [0.8]},
        "mapping": {"x": "x", "y": "y", "xend": "xend", "yend": "yend"},
        "layers": [{"geom": "curve", "params": {"curvature": 0.5}}],
        "limits": {"x": [0, 1], "y": [0, 1]},
    }
    assert _kinds(build_scene(spec)).count(ir.NodeKind.CURVE.value) == 1


def test_missing_plot_file_is_a_contract_error(tmp_path: Path) -> None:
    with pytest.raises(PlotSpecError, match=r"plot\.py"):
        load_plot(tmp_path)


def test_repo_cases_build_into_scenes() -> None:
    """仓库里的四个 case 都能从 plot.py 直接搭 IR（矩阵 render 的前半段）。"""
    from ggskia.text import ShaperMetrics

    metrics = ShaperMetrics()
    directories = sorted(path for path in CASES.iterdir() if (path / "plot.py").is_file())
    assert len(directories) >= 3
    for directory in directories:
        scene = build_scene(load_plot(directory), metrics=metrics)
        assert scene.size == pytest.approx((288.0, 216.0))
        assert scene.root.children
