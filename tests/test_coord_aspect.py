"""等比例的像素级验证（M1-5）：2×2 合成 panel → PNG / SVG。

测量逻辑在 `tools/cases/coord_aspect_cases.py`：PR 里贴的那两张产物与这里跑的
是同一份场景。断言的是**测量出来的**高/宽，不是 `panel_sizes()` 的返回值：

- `fixed-ratio-1`：PNG / SVG 的高/宽 = 1.000（容差 0.5%）；
- `fixed-ratio-2`：= 2.000（容差 0.5%）；
- `cartesian-control`：不写 `coord_fixed` 时 panel 铺满 6 × 4 in，高/宽 = 4/6，
  证明没有「顺手」强制成 1。

比例只在这里量一次：200 行 `panel_sizes` 的算术断言在 `tests/test_coord.py`。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load_tool() -> object:
    path = REPO / "tools" / "cases" / "coord_aspect_cases.py"
    spec = importlib.util.spec_from_file_location("coord_aspect_cases_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses 在 3.12 里按 __module__ 查 sys.modules（字符串注解要解析），
    # 先登记再 exec，否则 `@dataclass` 的模块会拿到 None。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()
CASES = {case.name: case for case in TOOL.CASES}  # type: ignore[attr-defined]


@pytest.fixture(scope="module")
def measurements() -> dict[str, dict[str, tuple[float, float]]]:
    """每个 case 的 PNG / SVG 面板尺寸（像素 / pt）。"""
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for case in TOOL.CASES:  # type: ignore[attr-defined]
        ir_scene, _ = TOOL.panel_scene(case.coord)  # type: ignore[attr-defined]
        png, svg = TOOL.render(ir_scene)  # type: ignore[attr-defined]
        out[case.name] = {
            "png": TOOL.measure_png(png),  # type: ignore[attr-defined]
            "svg": TOOL.measure_svg(svg),  # type: ignore[attr-defined]
        }
    return out


def test_fixed_ratio_one_panel_is_square(measurements) -> None:
    for label in ("png", "svg"):
        width, height = measurements["fixed-ratio-1"][label]
        assert height / width == pytest.approx(1.0, rel=0.005)


def test_fixed_ratio_two_panel_is_twice_as_tall(measurements) -> None:
    for label in ("png", "svg"):
        width, height = measurements["fixed-ratio-2"][label]
        assert height / width == pytest.approx(2.0, rel=0.005)
    # 具体像素：6 × 4 in、150 dpi，panel 2 × 4 in → 300 × 600 px；SVG 是 pt
    assert measurements["fixed-ratio-2"]["png"] == (300.0, 600.0)
    assert measurements["fixed-ratio-2"]["svg"] == (144.0, 288.0)
    assert measurements["fixed-ratio-1"]["png"] == (600.0, 600.0)
    assert measurements["fixed-ratio-1"]["svg"] == (288.0, 288.0)


def test_without_coord_fixed_the_panel_is_not_forced_to_a_ratio(measurements) -> None:
    """对照：cartesian 的 panel 是整块可用区域，高/宽 = 2/3，不是 1。"""
    for label in ("png", "svg"):
        width, height = measurements["cartesian-control"][label]
        assert height / width == pytest.approx(4.0 / 6.0, rel=0.005)
        assert abs(height / width - 1.0) > 0.1


def test_measured_panel_matches_panel_sizes(measurements) -> None:
    """像素尺寸与 `panel_sizes()` 的英寸值一致（150 dpi 换算）。"""
    for name, case in CASES.items():
        _, params = TOOL.panel_scene(case.coord)  # type: ignore[attr-defined]
        width_in, height_in = params.panel_sizes(*TOOL.DEVICE_IN)  # type: ignore[attr-defined]
        width_px, height_px = measurements[name]["png"]
        assert width_px == pytest.approx(width_in * TOOL.DPI, abs=1.0)  # type: ignore[attr-defined]
        assert height_px == pytest.approx(height_in * TOOL.DPI, abs=1.0)  # type: ignore[attr-defined]


def test_tool_check_mode_passes() -> None:
    assert TOOL.run(check_only=True) == []  # type: ignore[attr-defined]
