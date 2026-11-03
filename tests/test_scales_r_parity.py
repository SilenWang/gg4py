"""M1-4 与 ggplot2 4.0.3 的标度对拍。

夹具 `tests/fixtures/scales_r_reference.json` 由
`pixi run -e refs refs:scales`（`tools/refs/scales_ref.R`）生成：R 侧构造标度、
`$train()`，记录 `get_limits()` / `default_expansion()` / `dimension()` /
`view_scale_primary()$breaks` / `$get_labels()` / `$map()` 的实际值。

对拍口径（`docs/notes/scales.md`）：

- 数值容差 `1e-12`（断点是浮点乘出来的，R 的 0.30000000000000004 与 0.3 是同一个）；
- 十六进制值**逐字节**相等（大小写也一致）；
- `null` = R 的 `NA`（越界断点 / 缺失值）；
- `"Inf"` / `"-Inf"` = R 的 ±Inf（log10 的 0）：ggcore 按 issue 要求把它记成 NA，
  这里只断言「R 是 Inf，我们是 NA」，不让它悄悄混过去。
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from ggcore.components import Scale
from ggcore.data import Column
from ggcore.scales import gradient_pal, hue_pal, scale_from_component

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "scales_r_reference.json"
TOLERANCE = 1e-12

#: 夹具里钉死的 case（改夹具就要同时改这里，防止悄悄少比）。
EXPECTED_CASES = {
    "alpha_binned",
    "alpha_continuous",
    "colour_binned",
    "colour_date",
    "colour_distiller",
    "colour_fermenter",
    "colour_gradient",
    "colour_gradient2",
    "colour_gradient_limits",
    "colour_gradientn",
    "colour_hue",
    "colour_hue_limits",
    "colour_hue_na_value",
    "colour_manual",
    "colour_steps",
    "colour_steps2",
    "colour_steps_oob",
    "colour_stepsn",
    "continuous_default_expand",
    "continuous_expand_zero",
    "continuous_limits_censor",
    "continuous_manual_breaks_labels",
    "continuous_nbreaks",
    "discrete_drop_false",
    "discrete_levels",
    "discrete_limits",
    "discrete_na_level",
    "discrete_reverse_limits",
    "fill_hue",
    "linewidth_binned",
    "linewidth_continuous",
    "linewidth_date",
    "radius",
    "shape_discrete",
    "size_area",
    "size_binned",
    "size_binned_area",
    "size_continuous",
    "size_date",
    "x_binned",
    "x_binned_breaks",
    "x_date_breaks",
    "x_date_default",
    "x_datetime_breaks",
    "x_log10",
    "x_log10_limits",
    "x_oob_keep",
    "x_oob_squish",
    "x_oob_squish_infinite",
    "x_reverse",
    "x_sqrt",
    "x_time_breaks",
    "y_log10",
}


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _column(values: list) -> Column:
    """夹具里的值 → Column（null → NA）。"""
    missing = np.array([value is None for value in values], dtype=bool)
    if any(isinstance(value, str) for value in values):
        data = np.array(["" if value is None else value for value in values], dtype=object)
        return Column("str", data, na_mask=missing)
    data = np.array(
        [np.nan if value is None else float(value) for value in values], dtype=np.float64
    )
    return Column("float", np.where(missing, 0.0, data), na_mask=missing)


def _build_scale(case: dict):
    params = dict(case["params"])
    # 夹具里是 R 的参数名（n.breaks）；`_param()` 两种写法都认，统一成下划线。
    if "n.breaks" in params:
        params["n_breaks"] = params.pop("n.breaks")
    return scale_from_component(Scale(case["scale"], case["aesthetic"], params))


def _trained_scale(case: dict):
    scale = _build_scale(case)
    if case["id"] == "discrete_drop_false":
        # factor("a", levels = c("b", "a", "c"))：只有 a 出现，但要保留全部水平。
        train = Column("categorical", np.array([0], dtype=np.int32), levels=("b", "a", "c"))
    else:
        train = _column(case["train"])
    scale.train(scale.transform(train))
    return scale


def _close(got, expected) -> bool:
    if got is None or expected is None:
        return got is None and expected is None
    if isinstance(expected, str) or isinstance(got, str):
        return str(got) == str(expected)
    return abs(float(got) - float(expected)) <= TOLERANCE


def _compare(case: dict, scale) -> list[str]:
    """返回不一致项（空列表 = 全对）。`_compare` 也被「断言有牙」用例复用。"""
    problems: list[str] = []

    limits = scale.limits()
    if len(limits) != len(case["limits"]) or not all(
        _close(got, expected) for got, expected in zip(limits, case["limits"], strict=True)
    ):
        problems.append(f"limits {limits!r} != {case['limits']!r}")

    if case["expand"] is not None:
        expand = scale.expansion.as_tuple()
        if not all(
            _close(got, expected) for got, expected in zip(expand, case["expand"], strict=True)
        ):
            problems.append(f"expand {expand!r} != {case['expand']!r}")

    if case["expanded_limits"] is not None:
        expanded = scale.expanded_limits()
        if expanded is None or not all(
            _close(got, expected)
            for got, expected in zip(expanded, case["expanded_limits"], strict=True)
        ):
            problems.append(f"expanded {expanded!r} != {case['expanded_limits']!r}")

    breaks = scale.breaks()
    if len(breaks) != len(case["breaks"]) or not all(
        _close(got, expected) for got, expected in zip(breaks, case["breaks"], strict=True)
    ):
        problems.append(f"breaks {breaks!r} != {case['breaks']!r}")

    labels = scale.labels()
    if list(labels) != list(case["labels"]):
        problems.append(f"labels {labels!r} != {case['labels']!r}")

    mapped = scale.map(scale.transform(_column(case["map"])))
    got_values = mapped.values.tolist()
    got_mask = mapped.na_mask.tolist()
    if len(got_values) != len(case["mapped"]):
        problems.append(f"mapped 长度 {len(got_values)} != {len(case['mapped'])}")
    else:
        for index, (value, missing, expected) in enumerate(
            zip(got_values, got_mask, case["mapped"], strict=True)
        ):
            if isinstance(expected, str) and expected in ("Inf", "-Inf"):
                # R 的 ±Inf：ggcore 明确记成 NA（见 docs/notes/scales.md）。
                if not missing:
                    problems.append(f"mapped[{index}]={value!r}，R 是 {expected}，期望 NA")
                continue
            if expected is None or missing:
                if not (expected is None and missing):
                    problems.append(f"mapped[{index}]={value!r}/{missing} != {expected!r}")
                continue
            if isinstance(expected, str):
                if str(value) != expected:
                    problems.append(f"mapped[{index}]={value!r} != {expected!r}")
            elif abs(float(value) - float(expected)) > TOLERANCE:
                problems.append(f"mapped[{index}]={value!r} != {expected!r}")
    return problems


def test_fixture_comes_from_pinned_ggplot2(reference: dict) -> None:
    assert reference["generated_by"] == "tools/refs/scales_ref.R"
    assert reference["ggplot2_version"] == "4.0.3"
    assert reference["locale"] == "C.UTF-8"
    assert {case["id"] for case in reference["cases"]} == EXPECTED_CASES


def test_palettes_match_r_byte_for_byte(reference: dict) -> None:
    hue = {item["n"]: item["values"] for item in reference["palettes"]["hue"]}
    assert hue.keys() >= {2, 3, 6}
    for n, expected in hue.items():
        assert hue_pal()(n) == expected

    gradient = reference["palettes"]["gradient"]
    assert gradient["low"] == "#132B43"
    assert gradient["high"] == "#56B1F7"
    assert (
        gradient_pal(gradient["low"], gradient["high"])(gradient["positions"]) == gradient["values"]
    )


@pytest.mark.parametrize("case_id", sorted(EXPECTED_CASES))
def test_scale_matches_r(reference: dict, case_id: str) -> None:
    case = next(item for item in reference["cases"] if item["id"] == case_id)
    problems = _compare(case, _trained_scale(case))
    assert problems == [], f"{case_id}:\n" + "\n".join(problems)


def test_compared_cell_count(reference: dict) -> None:
    """规模钉死：53 个 case、218 个断点 / 标签、199 个映射值、24 个 expand 向量。

    M2-4 A 段把连续 / 分箱 / 渐变 / 日期时间四类补进来；规模断言防止悄悄少比。
    """
    assert len(reference["cases"]) == 53
    assert sum(len(case["breaks"]) for case in reference["cases"]) == 218
    assert sum(len(case["labels"]) for case in reference["cases"]) == 218
    assert sum(len(case["mapped"]) for case in reference["cases"]) == 199
    assert sum(len(case["limits"]) for case in reference["cases"]) == 114
    assert sum(1 for case in reference["cases"] if case["expand"] is not None) == 24


def test_parity_has_teeth(reference: dict) -> None:
    """改一个 hex、一个 break，对拍必须红（不是恒真比较）。"""
    case = next(item for item in reference["cases"] if item["id"] == "colour_hue")
    scale = _trained_scale(case)
    assert _compare(case, scale) == []

    mutated = copy.deepcopy(case)
    mutated["mapped"][0] = "#F8766D" if mutated["mapped"][0] != "#F8766D" else "#000000"
    assert _compare(mutated, scale) != []

    break_case = next(
        item for item in reference["cases"] if item["id"] == "continuous_default_expand"
    )
    break_scale = _trained_scale(break_case)
    assert _compare(break_case, break_scale) == []
    mutated_break = copy.deepcopy(break_case)
    mutated_break["breaks"][1] = 2.5
    assert _compare(mutated_break, break_scale) != []


def test_log10_infinity_is_recorded_as_na(reference: dict) -> None:
    """R 把 log10(0) 记成 -Inf；ggcore 按 issue 要求记 NA（并计入 non_finite_count）。"""
    case = next(item for item in reference["cases"] if item["id"] == "x_log10")
    index = case["mapped"].index("-Inf")
    scale = _trained_scale(case)
    mapped = scale.map(scale.transform(_column(case["map"])))
    assert mapped.na_mask.tolist()[index] is True
    assert scale.non_finite_count == 2  # 0 与 -1
    assert case["trans"] == "log-10"
    assert math.isnan(mapped.values.tolist()[index]) is False  # 占位 0，靠 mask 表达 NA
