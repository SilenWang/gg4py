"""grob 的可视化快照（`docs/cases/grob-*`，SIL-594 / M0-6）。

快照由 `pixi run cases:grob` 生成（`tools/cases/grob_cases.py`）。这里守四件事：

1. **覆盖面**：13 种可绘制原语 + `clipPath` / `nullGrob`（共 15 张）+ 文本旋转
   合成 1 张，名单在 `EXPECTED_KINDS` 里钉死——新增原语必须同时加案例，删案例会让
   这里红；
2. **链路对**：案例真的走到了场景遍历**和写 IR**（`grob → Scene → to_ir_scene()`），
   每种案例都能在 `Scene.instructions` 里找到自己的 IR 节点种类；
3. **确定性**：同一份 case 连画两次字节一致；
4. **基线**：仓库里的 `baseline/<case>.png` 与当前代码画出来的一致（像素阈值
   留了抗锯齿余量，见 `docs/notes/snapshot-policy.md`）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from ggcore.ir import NodeKind

REPO = Path(__file__).resolve().parents[1]
CASES_DIR = REPO / "docs" / "cases"

#: 一种原语一张快照（`clipPath` 用 `clip`、`nullGrob` 用 `null` 那两张）。
EXPECTED_KINDS: dict[str, NodeKind] = {
    "grob-rect": NodeKind.RECT,
    "grob-circle": NodeKind.CIRCLE,
    "grob-lines": NodeKind.LINES,
    # 虚线段长的 lwd 边界（lwd = 0.5 / 0.9 / 1.0 / 2.0，SIL-763）
    "grob-dash-lwd": NodeKind.SEGMENTS,
    "grob-segments": NodeKind.SEGMENTS,
    "grob-polyline": NodeKind.POLYLINE,
    "grob-polygon": NodeKind.POLYGON,
    "grob-path": NodeKind.PATH,
    "grob-points": NodeKind.POINTS,
    "grob-text": NodeKind.TEXT,
    "grob-raster": NodeKind.RASTER,
    "grob-xspline": NodeKind.XSPLINE,
    "grob-bezier": NodeKind.BEZIER,
    "grob-curve": NodeKind.CURVE,
    # 文本旋转的合成（SIL-634）：视口旋转 + `rot` 各算一次，不叠加
    "grob-text-rot": NodeKind.TEXT,
    # clipPath 只是容器：案例里能看到的节点是它包住的 rect
    "grob-clip": NodeKind.RECT,
    # nullGrob / zeroGrob 不画，案例里能看到的节点是 gtable 单元格里的 rect / lines
    "grob-null": NodeKind.RECT,
}


def _load_tool() -> Any:
    path = REPO / "tools" / "cases" / "grob_cases.py"
    spec = importlib.util.spec_from_file_location("grob_cases_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()
CASES = TOOL.load_cases(CASES_DIR)
IDS = [case["id"] for _, case in CASES]


def test_every_primitive_has_a_case() -> None:
    assert set(IDS) == set(EXPECTED_KINDS)


@pytest.mark.parametrize("directory,case", CASES, ids=IDS)
def test_case_reaches_its_ir_kind(directory: Path, case: dict[str, Any]) -> None:
    scene, _ppi = TOOL.build(case)
    kinds = {item.kind for item in scene.instructions}
    assert EXPECTED_KINDS[case["id"]] in kinds, kinds


@pytest.mark.parametrize("directory,case", CASES, ids=IDS)
def test_baseline_matches_a_fresh_render(directory: Path, case: dict[str, Any]) -> None:
    baseline = directory / "baseline" / TOOL.baseline_name(case)
    assert baseline.is_file(), f"missing {baseline.relative_to(REPO)}; run pixi run cases:grob"
    png = TOOL.render(case)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert TOOL.decode(png).shape == TOOL.decode(baseline.read_bytes()).shape
    problem = TOOL.compare(png, baseline.read_bytes())
    assert problem is None, f"{case['id']}: {problem}"


@pytest.mark.parametrize("directory,case", CASES, ids=IDS)
def test_render_is_deterministic(directory: Path, case: dict[str, Any]) -> None:
    assert TOOL.render(case) == TOOL.render(case)


@pytest.mark.parametrize("directory,case", CASES, ids=IDS)
def test_canvas_size_follows_the_device(directory: Path, case: dict[str, Any]) -> None:
    device = case["device"]
    pixels = TOOL.decode(TOOL.render(case))
    assert pixels.shape[:2] == (
        round(device["height_in"] * device["pixels_per_inch"]),
        round(device["width_in"] * device["pixels_per_inch"]),
    )


def _case(case_id: str) -> dict[str, Any]:
    for _, case in CASES:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing case {case_id}")


def test_points_case_shows_the_vector_gp_expansion() -> None:
    """一个 points 原语带 6 色向量 col → 6 条指令，颜色顺序就是给的顺序。"""
    scene, _ppi = TOOL.build(_case("grob-points"))
    points = scene.by_kind(NodeKind.POINTS)
    assert len(points) >= 8  # 8 个单点 + 6 条向量展开
    tail = points[-6:]
    assert [item.rows for item in tail] == [1] * 6
    assert [item.gpar.col for item in tail] == [
        (0x4C, 0x78, 0xA8, 255),
        (0xF5, 0x85, 0x18, 255),
        (0xE4, 0x57, 0x56, 255),
        (0x72, 0xB7, 0xB2, 255),
        (0x54, 0xA2, 0x4B, 255),
        (0xB2, 0x79, 0xA2, 255),
    ]


def test_dash_lwd_case_pins_the_max_lwd_boundary() -> None:
    """`lwd < 1` 的段长按 `max(lwd, 1)` 算：0.5 / 0.9 / 1.0 同为 3pt，2.0 才翻倍。

    这是 SIL-763 的专项 case：IR 的 `lty` 是 pt，公式 `pattern × max(lwd, 1) × 0.75`
    （渲染器再乘 `DASH_UNIT = 4/3` 写回 lwd 单位的 `stroke-dasharray`）。
    """
    scene, _ppi = TOOL.build(_case("grob-dash-lwd"))
    dashes = [item.gpar.lty for item in scene.by_kind(NodeKind.SEGMENTS)]
    assert dashes == [(3.0, 3.0), (3.0, 3.0), (3.0, 3.0), (6.0, 6.0)]


def test_null_case_has_no_instructions_for_null_or_zero_grobs() -> None:
    scene, _ppi = TOOL.build(_case("grob-null"))
    kinds = {item.kind for item in scene.instructions}
    assert NodeKind.NULL not in kinds
    assert NodeKind.ZERO not in kinds
    # gtable 的四个格子里只有两格有笔画：rect 与 lines（gTree 的边）
    assert NodeKind.RECT in kinds and NodeKind.LINES in kinds


def test_text_case_uses_metrics_and_a_resolved_font_key() -> None:
    scene, _ppi = TOOL.build(_case("grob-text"))
    texts = scene.by_kind(NodeKind.TEXT)
    assert texts
    for instruction in texts:
        assert instruction.params["font"]
        assert float(instruction.bufs["width"][0]) > 0


def _rotation_probe(*, viewport_angle: float, rot: float) -> dict[str, Any]:
    """同一行字落在页面中心：一种靠视口旋转，一种靠 `rot`（SIL-634 的 A / A'）。"""
    return {
        "id": "grob-text-rot-probe",
        "kind": "grob",
        "device": {"width_in": 2.0, "height_in": 1.5, "pixels_per_inch": 150},
        "viewports": [
            {
                "name": "rot",
                "x": 0.5,
                "y": 0.5,
                "width": 1.0,
                "height": 1.0,
                "angle": viewport_angle,
                "clip": "off",
            }
        ],
        "grobs": [
            {
                "type": "gTree",
                "vp": 0,
                "children": [
                    {
                        "type": "text",
                        "label": "rot",
                        "x": 0.5,
                        "y": 0.5,
                        "rot": rot,
                        "gp": {"fontsize": 12},
                    }
                ],
            }
        ],
    }


def test_viewport_rotation_and_rot_are_not_applied_twice() -> None:
    """视口 20° + `rot = 0` 与无旋转视口 + `rot = 20` 必须画成同一张图。

    修之前前者画成 40°（`angle` 里含一份视口旋转，`transform` 里又一份），
    与 `rot = 20` 的图差一整圈的一半；这条用像素兜住。
    """
    by_viewport = TOOL.render(_rotation_probe(viewport_angle=20.0, rot=0.0))
    by_rot = TOOL.render(_rotation_probe(viewport_angle=0.0, rot=20.0))
    assert TOOL.compare(by_viewport, by_rot) is None

    # 视口 20° + rot 20 是**两段**旋转，合成 40°，与只转 20° 不是一张图
    stacked = TOOL.render(_rotation_probe(viewport_angle=20.0, rot=20.0))
    assert TOOL.compare(stacked, by_rot) is not None


def test_text_rotation_case_covers_both_halves() -> None:
    """快照集里的 A / A' / B 三分支：视口 20° + rot0、rot 20、rot 40。"""
    scene, _ppi = TOOL.build(_case("grob-text-rot"))
    texts = scene.by_kind(NodeKind.TEXT)
    assert [item.params["angle"] for item in texts] == [0.0, 20.0, 40.0]
    assert next(item.vp for item in texts).startswith("rot20")


def test_raster_case_references_a_blob() -> None:
    scene, _ppi = TOOL.build(_case("grob-raster"))
    rasters = scene.by_kind(NodeKind.RASTER)
    assert len(rasters) == 3
    for instruction in rasters:
        assert instruction.params["blob"] in scene.blobs
