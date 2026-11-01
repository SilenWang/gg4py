"""units 与 R `grid` 的逐条对拍（SIL-592）。

夹具 `tests/fixtures/units_r_reference.json` 由 `tools/refs/units_ref.R` 在
pixi 的 `refs` 环境（r-base 4.5.3）里生成：每条用例都带 R 侧表达式、换算上下文、
R 算出的期望值，以及（可选的）单位结构快照。重新生成：

    pixi run -e refs refs:units

`spec` 是 Python 侧构造单位的 JSON（存成字符串，避免 R 侧再带一个 JSON 解析器）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ggcore.units import (
    FixedMetrics,
    Unit,
    UnitContext,
    UnitElement,
    UnitError,
    convert_unit,
    is_simple_unit,
    str_height,
    str_width,
    unit,
    unit_c,
    unit_max,
    unit_min,
    unit_pmax,
    unit_pmin,
    unit_psum,
    unit_sum,
    unit_type,
)

FIXTURE = Path(__file__).parent / "fixtures" / "units_r_reference.json"
DOCUMENT = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = DOCUMENT["cases"]


def build(spec: dict[str, Any]) -> Unit:
    """把夹具里的 spec 还原成 ggcore 的 Unit。"""
    if "kind" in spec:
        kind = spec["kind"]
        if isinstance(kind, str) and kind in {"sum", "min", "max"}:
            children = tuple(build(child).elements[0] for child in spec["children"])
            return Unit((UnitElement(spec["amount"], kind, children),))
        return unit(spec["amount"], kind, data=spec.get("text"))

    op = spec["op"]
    if op == "empty":
        return Unit()
    if op == "str_width":
        return str_width(spec["text"])
    if op == "str_height":
        return str_height(spec["text"])
    if "arg" in spec:
        args = [build(spec["arg"])]
    else:
        args = [build(item) for item in spec.get("args", [])]
    if op == "add":
        return args[0] + args[1]
    if op == "sub":
        return args[0] - args[1]
    if op == "mul":
        return args[0] * spec["scalar"]
    if op == "div":
        return args[0] / spec["scalar"]
    if op == "neg":
        return -args[0]
    if op == "pmax":
        return unit_pmax(*args)
    if op == "pmin":
        return unit_pmin(*args)
    if op == "psum":
        return unit_psum(*args)
    if op == "max":
        return unit_max(*args)
    if op == "min":
        return unit_min(*args)
    if op == "sum":
        return unit_sum(*args)
    if op == "unit_c":
        return unit_c(*args)
    raise AssertionError(f"unknown spec op {op!r}")


def make_context(raw: dict[str, Any]) -> UnitContext:
    metrics = raw.get("metrics") or {}
    provider = (
        FixedMetrics(
            widths={text: values["width"] for text, values in metrics.items()},
            heights={text: values["height"] for text, values in metrics.items()},
        )
        if metrics
        else None
    )
    return UnitContext(
        width_cm=raw["width_cm"],
        height_cm=raw["height_cm"],
        xscale=tuple(raw["xscale"]),
        yscale=tuple(raw["yscale"]),
        fontsize=raw["fontsize"],
        cex=raw["cex"],
        lineheight=raw["lineheight"],
        metrics=provider,
    )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_matches_r(case: dict[str, Any]) -> None:
    ctx = make_context(case["context"])
    target = build(json.loads(case["spec"])) if case["spec"] else None
    conversion = case["convert"]

    if case["python_only"]:
        # R 4.5.3 造不出空单位（`unit.c()` 报错）；我们的契约见台账。
        assert case["r_error"], "python_only 用例应记录 R 侧的失败"
        assert target is not None
        expect = case["python_expect"]
        assert len(target) == expect["length"]
        got = convert_unit(
            target,
            conversion["unit_to"],
            ctx=ctx,
            axis_from=conversion["axis_from"],
            type_from=conversion["type_from"],
            axis_to=conversion["axis_to"],
            type_to=conversion["type_to"],
        )
        assert list(got) == expect["convert_to_cm"]
        return

    assert target is not None
    if case["r_error"]:
        with pytest.raises(UnitError):
            convert_unit(
                target,
                conversion["unit_to"],
                ctx=ctx,
                axis_from=conversion["axis_from"],
                type_from=conversion["type_from"],
                axis_to=conversion["axis_to"],
                type_to=conversion["type_to"],
            )
        return

    got = convert_unit(
        target,
        conversion["unit_to"],
        ctx=ctx,
        axis_from=conversion["axis_from"],
        type_from=conversion["type_from"],
        axis_to=conversion["axis_to"],
        type_to=conversion["type_to"],
    )
    expected = np.atleast_1d(np.asarray(case["expected"], dtype=np.float64))
    if case["tolerance"] == 0:
        np.testing.assert_array_equal(got, expected)
    else:
        np.testing.assert_allclose(got, expected, rtol=case["tolerance"], atol=0)

    if case["structure"] is not None:
        assert target.to_structure() == case["structure"]
        assert len(target) == case["length"]
        assert is_simple_unit(target) == case["simple"]
        assert unit_type(target) == case["types"]


def test_fixture_covers_the_required_boundaries() -> None:
    ids = [case["id"] for case in CASES]
    assert len(ids) >= 40, "验收要求 ≥ 40 条与 R 的对拍用例"
    assert len(ids) == len(set(ids)), "用例 id 必须唯一"
    assert DOCUMENT["r_version"].startswith("R version 4.5"), "夹具必须由钉住的 R 生成"

    # 单位类型：任务列出的每一种都要有换算用例覆盖。
    covered = " ".join(case["spec"] for case in CASES if case["spec"])
    for kind in ("npc", "native", "mm", "pt", "lines", "strwidth", "strheight", "null", "snpc"):
        spellings = (f'"kind":"{kind}"', f'"op":"str_{kind.removeprefix("str")}"')
        assert any(spelling in covered for spelling in spellings), f"缺少 {kind} 用例"

    # 边界：null 不进总和、空单位列表、浮点/舍入各至少一条。
    assert any("null" in case["id"] and "plus" in case["id"] for case in CASES)
    assert any(case["python_only"] for case in CASES)
    assert any(case["tolerance"] == 0 for case in CASES)
