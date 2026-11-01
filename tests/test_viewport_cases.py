"""viewport 的可视化快照（`docs/cases/viewport-*`，SIL-596 / M0-4）。

快照由 `pixi run cases:viewport` 生成（`tools/cases/viewport_cases.py`），这里守
三件事：案例确实覆盖了要演示的语义（三层旋转叠加、裁剪三态）、渲染是确定的、
仓库里的 baseline 与当前代码画出来的图一致（像素阈值留了抗锯齿余量）。
"""

from __future__ import annotations

import importlib.util
import warnings
from pathlib import Path
from typing import Any

import pytest

from ggcore.viewport import Clip

REPO = Path(__file__).resolve().parents[1]
CASES_DIR = REPO / "docs" / "cases"


def _load_tool() -> Any:
    path = REPO / "tools" / "cases" / "viewport_cases.py"
    spec = importlib.util.spec_from_file_location("viewport_cases_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()
CASES = TOOL.load_cases(CASES_DIR)
IDS = [case["id"] for _, case in CASES]


def test_both_required_cases_exist() -> None:
    assert set(IDS) == {"viewport-nested-rotate", "viewport-clip"}


@pytest.mark.parametrize("directory,case", CASES, ids=IDS)
def test_baseline_matches_a_fresh_render(directory: Path, case: dict[str, Any]) -> None:
    baseline = directory / "baseline" / TOOL.BASELINE
    assert baseline.is_file(), f"missing {baseline.relative_to(REPO)}; run pixi run cases:viewport"
    png = TOOL.render(case)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pixels = TOOL.decode(png)
    expected_pixels = TOOL.decode(baseline.read_bytes())
    assert pixels.shape == expected_pixels.shape
    problem = TOOL.compare(png, baseline.read_bytes())
    assert problem is None, f"{case['id']}: {problem}"


@pytest.mark.parametrize("directory,case", CASES, ids=IDS)
def test_render_is_deterministic(directory: Path, case: dict[str, Any]) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # 旋转裁剪是案例本身要演示的行为
        first = TOOL.render(case)
        second = TOOL.render(case)
    assert first == second


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


def test_nested_case_stacks_three_rotations_into_ninety_degrees() -> None:
    case = _case("viewport-nested-rotate")
    assert len(case["viewports"]) == 3
    tree = TOOL.ViewportTree(TOOL.Device(case["device"]["width_in"], case["device"]["height_in"]))
    rotations = []
    for spec in case["viewports"]:
        rotations.append(tree.push(TOOL._build(spec)).rotation)
    assert rotations == [15.0, 40.0, 90.0]
    # 累计 90° 仍可轴对齐：最内层的 clip=on 不退化，裁剪框是它自己的盒子
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert tree.current.clip is Clip.ON
        x0, y0, x1, y1 = tree.current.clip_rect
        # 90° 时两个角点的顺序翻转（R 也这样存未规范化的四元组）
        assert x0 > x1 and y0 < y1
        assert tree.current.clip_box == pytest.approx(
            (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        )
    assert tree.current.rotation == 90.0


def test_clip_case_covers_all_three_states() -> None:
    case = _case("viewport-clip")
    clips = {spec.get("clip", "inherit") for spec in case["viewports"]}
    assert clips == {"on", "off", "inherit"}
    angles = [spec.get("angle", 0) for spec in case["viewports"]]
    assert 45 in angles  # 旋转裁剪的退化分支要在案例里
