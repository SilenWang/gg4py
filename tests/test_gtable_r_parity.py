"""gtable 与 R（gtable 0.3.6 + grid）的几何对拍（SIL-593）。

夹具 `tests/fixtures/gtable_r_reference.json` 由 `tools/refs/gtable_ref.R` 在
pixi 的 `refs` 环境生成。gtable 自己不解析尺寸，行高列宽实际由 grid 的
`calcViewportLayout()` 分配，所以 R 侧用**设备测量**当参考值：把表画在
10×10 cm 的 pdf(NULL) 上，逐个视口读回每个单元格的宽高和左下角坐标
（`grid:::deviceLoc`，cm）。重新生成：

    pixi run -e refs refs:gtable

R 侧的坐标是设备绝对坐标；子表单元格在测试里换算成「相对子表 layout 视口」
再比（子表解析的参照系就是它自己所在的单元格）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ggcore.gtable import (
    GTable,
    gtable,
    gtable_add_cols,
    gtable_add_grob,
    gtable_add_padding,
    gtable_add_rows,
)
from ggcore.units import Unit, UnitContext, unit, unit_c

FIXTURE = Path(__file__).parent / "fixtures" / "gtable_r_reference.json"
DOCUMENT = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = DOCUMENT["cases"]

TOLERANCE = 1e-9
"""cm；验收要求 < 0.01 pt = 3.5e-4 cm，这里留了五个数量级的余量。"""

REQUIRED_LAYOUTS = frozenset(
    {
        # 纯 null：等权 / 不等权
        "pure-null-equal",
        "pure-null-uneven",
        # 任务点名的三组
        "zero-null-zero-null",
        "zero-null-one-null",
        "mixed-element-not-null",
        # 固定 + null、纯固定、单格、0 宽列
        "fixed-plus-null",
        "fixed-only-centred",
        "single-cell",
        "zero-width-fixed-col",
        "fixed-overflow-eats-null",
        # respect
        "respect-square-cells",
        "respect-with-fixed",
        # 其它单位与 padding
        "mixed-units",
        "padding-mm-stack",
        "padding-pt-null",
        "padding-mixed-units",
        # 嵌套 + span
        "nested-two-levels",
        "nested-and-span",
        # 加行 / 加列
        "add-rows-cols-positions",
        # 边界
        "zero-viewport",
        "zero-viewport-fixed-col",
        "small-viewport",
    }
)
"""夹具必须覆盖的布局，逐 id 钉死——删一组夹具要让这里红，而不是静默通过。"""


def build_unit(spec: dict[str, Any]) -> Unit:
    """夹具里的单位 spec → ggcore Unit。"""
    if "kind" in spec:
        return unit(spec["amount"], spec["kind"])
    op = spec["op"]
    args = [build_unit(item) for item in spec.get("args", [])]
    if op == "add":
        return args[0] + args[1]
    if op == "sub":
        return args[0] - args[1]
    if op == "mul":
        return args[0] * spec["scalar"]
    if op == "unit_c":
        return unit_c(*args)
    raise AssertionError(f"unknown unit spec op {op!r}")


def build_table(spec: dict[str, Any]) -> GTable:
    """夹具里的表 spec → ggcore GTable。`grob: "probe"` 是占位 grob。"""
    op = spec["op"]
    if op == "gtable":
        return gtable(
            widths=build_unit(spec["widths"]) if "widths" in spec else None,
            heights=build_unit(spec["heights"]) if "heights" in spec else None,
            respect=spec.get("respect", False),
            name=spec.get("name", "layout"),
        )
    if op == "add_rows":
        return gtable_add_rows(build_table(spec["x"]), build_unit(spec["heights"]), pos=spec["pos"])
    if op == "add_cols":
        return gtable_add_cols(build_table(spec["x"]), build_unit(spec["widths"]), pos=spec["pos"])
    if op == "padding":
        return gtable_add_padding(build_table(spec["x"]), build_unit(spec["padding"]))
    if op == "add_grob":
        grob = build_table(spec["grob"]) if isinstance(spec["grob"], dict) else object()
        return gtable_add_grob(
            build_table(spec["x"]),
            grob,
            t=spec["t"],
            l=spec["l"],
            b=spec.get("b"),
            r=spec.get("r"),
            name=spec["name"],
        )
    raise AssertionError(f"unknown table spec op {op!r}")


def make_context(raw: dict[str, Any]) -> UnitContext:
    return UnitContext(
        fontsize=raw["fontsize"],
        cex=raw["cex"],
        lineheight=raw["lineheight"],
        xscale=tuple(raw["xscale"]),
        yscale=tuple(raw["yscale"]),
    )


def assert_close(actual: float, expected: float, what: str) -> None:
    assert actual == pytest.approx(expected, rel=1e-12, abs=TOLERANCE), (
        f"{what}: {actual!r} != {expected!r} cm "
        f"(diff {abs(actual - expected) * 72.27 / 2.54:.3g} pt)"
    )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_matches_r_geometry(case: dict[str, Any]) -> None:
    viewport = case["viewport"]
    width_cm, height_cm = viewport["width_cm"], viewport["height_cm"]
    ctx = make_context(viewport)
    table = build_table(json.loads(case["spec"]))
    sizes = table.resolve(width_cm, height_cm, ctx=ctx)
    assert len(sizes.widths_cm) == table.ncol
    assert len(sizes.heights_cm) == table.nrow

    for cell in case["cells"]:
        box = table.region_box(
            cell["t"],
            cell["l"],
            cell["b"],
            cell["r"],
            width_cm=width_cm,
            height_cm=height_cm,
            ctx=ctx,
            sizes=sizes,
        )
        label = f"{case['id']} cell ({cell['t']},{cell['l']})"
        assert_close(box.width_cm, cell["w"], f"{label} width")
        assert_close(box.height_cm, cell["h"], f"{label} height")
        assert_close(box.x_cm, cell["x"], f"{label} x")
        assert_close(box.y_cm, cell["y"], f"{label} y")

    for region in case["regions"]:
        box = table.region_box(
            region["t"],
            region["l"],
            region["b"],
            region["r"],
            width_cm=width_cm,
            height_cm=height_cm,
            ctx=ctx,
            sizes=sizes,
        )
        label = f"{case['id']} {region['name']}"
        assert_close(box.width_cm, region["w"], f"{label} width")
        assert_close(box.height_cm, region["h"], f"{label} height")
        assert_close(box.x_cm, region["x"], f"{label} x")
        assert_close(box.y_cm, region["y"], f"{label} y")

    for child in case["nested"]:
        row = table.placements(child["name"])[0]
        box = table.region_box(
            row.t,
            row.l,
            row.b,
            row.r,
            width_cm=width_cm,
            height_cm=height_cm,
            ctx=ctx,
            sizes=sizes,
        )
        label = f"{case['id']} nested {child['name']}"
        assert_close(box.width_cm, child["box"]["w"], f"{label} box width")
        assert_close(box.height_cm, child["box"]["h"], f"{label} box height")

        grob = table.grob(child["name"])
        assert isinstance(grob, GTable)
        # 嵌套：子表在自己的单元格里解析，沿该轴继承单元格尺寸。
        child_sizes = grob.resolve(box.width_cm, box.height_cm, ctx=ctx)
        assert len(child_sizes.widths_cm) == grob.ncol
        assert len(child_sizes.heights_cm) == grob.nrow
        for cell in child["cells"]:
            inner = grob.layout_spec().region_box(
                cell["t"],
                cell["l"],
                cell["b"],
                cell["r"],
                width_cm=box.width_cm,
                height_cm=box.height_cm,
                sizes=child_sizes,
            )
            inner_label = f"{label} cell ({cell['t']},{cell['l']})"
            assert_close(inner.width_cm, cell["w"], f"{inner_label} width")
            assert_close(inner.height_cm, cell["h"], f"{inner_label} height")
            assert_close(box.x_cm + inner.x_cm, cell["x"], f"{inner_label} x")
            assert_close(box.y_cm + inner.y_cm, cell["y"], f"{inner_label} y")


def test_fixture_covers_the_required_layouts() -> None:
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids)), "用例 id 必须唯一"
    # 逐 id 比：删一组夹具、或改名都直接红（`len(ids) >= N` 抓不到删除）。
    assert set(ids) == REQUIRED_LAYOUTS, (
        f"夹具集合变了：多出 {sorted(set(ids) - REQUIRED_LAYOUTS)}，"
        f"缺少 {sorted(REQUIRED_LAYOUTS - set(ids))}"
    )
    assert DOCUMENT["r_version"].startswith("R version 4.5"), "夹具必须由钉住的 R 生成"
    assert DOCUMENT["gtable_version"] == "0.3.6", "夹具必须由钉住的 gtable 生成"

    by_id = {case["id"]: case for case in CASES}
    # 任务点名的三组：0null,0null / 0null,1null / (1null+2cm),1null → 0,0 / 0,10 / 2,8 cm
    expected = {
        "zero-null-zero-null": [0.0, 0.0],
        "zero-null-one-null": [0.0, 10.0],
        "mixed-element-not-null": [2.0, 8.0],
        # 0 视口 + 固定列的 R 4.5.3 怪癖：负剩余照样分给 null 列。
        "zero-viewport-fixed-col": [2.0, -2.0],
    }
    for case_id, widths in expected.items():
        case = by_id[case_id]
        row = sorted((cell for cell in case["cells"] if cell["t"] == 1), key=lambda cell: cell["l"])
        assert [round(cell["w"], 6) for cell in row] == widths

    # 嵌套与 span 的组合必须有。
    assert any(case["id"] == "nested-two-levels" for case in CASES)
    assert any(case["regions"] and case["nested"] for case in CASES), "嵌套 + span 组合"
    # 其它验收点名的形态。
    assert any("respect" in case["id"] for case in CASES)
    assert any("padding" in case["id"] for case in CASES)
    assert any("zero-width" in case["id"] or "zero-null" in case["id"] for case in CASES)
    assert any("fixed-only" in case["id"] for case in CASES)
    assert any(case["viewport"]["width_cm"] == 0 for case in CASES)
