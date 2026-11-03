"""M1-9 与 ggplot2 4.0.3 的位置调整对拍。

夹具 `tests/fixtures/position_r_reference.json` 由
`pixi run -e refs refs:position`（`tools/refs/position_ref.R`）生成，每个 case
记两段数据：

- `input`：geom `setup_data()` 之后、位置调整之前的图层数据（`x / y / xmin /
  xmax / ymin / ymax / PANEL / group / flipped_aes`）；
- `output`：`ggplot_build(p)$data[[1]]` 里同名位置列的逐行值。

Python 侧把 `input` 装回 :class:`ColumnTable`，用注册表里同一个 position 实现
（`registry.construct("position", case["position"], **position_params)`）算出
`compute_layer()`，与 `output` 逐行比。所以夹具只钉位置调整这一个阶段。

对拍口径（`docs/notes/position.md`）：

- 数值 `allclose(rtol=0, atol=1e-12)`，缺失逐行一致；
- 列必须存在且列数一致；`order` 是上游 `PositionDodge$setup_data()` 的产物，
  出现时要逐值相等；
- **jitter 例外**：R 的 Mersenne-Twister 与 `np.random.default_rng()` 的 PCG64
  不可能给出同一串随机数，所以只比「包络」（每个抖动值的偏移不超过
  `width` / `height`）、可复现性，以及 R 自己的值也落在同一包络里。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ggcore.data import Column, ColumnTable
from ggcore.registry import construct

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "position_r_reference.json"
TOLERANCE = 1e-12

#: 夹具里钉死的 case（改夹具就要同时改这里，防止悄悄少比）。
EXPECTED_CASES = (
    "stack_two_groups",
    "stack_reverse",
    "stack_negative",
    "fill_two_groups",
    "dodge_two_groups",
    "dodge_preserve_single",
    "dodge2_two_groups",
    "dodge2_padding",
    "dodge2_preserve_single_no_x",
    "dodge_horizontal",
    "stack_horizontal",
    "fill_horizontal",
    "jitter_seed",
    "nudge",
    "dodge2_preserve_total_uneven",
    "dodge2_preserve_single_uneven",
    "dodge2_boxplot",
    "dodge2_boxplot_varwidth",
    "dodge2_horizontal",
    "jitterdodge_zero_jitter",
    "jitterdodge_dodge_width",
    "jitterdodge_zero_jitter_reverse",
    "jitterdodge_defaults",
    "jitterdodge_two_panels",
    "nudge_text_default",
    "nudge_text_params",
    "nudge_text_vector",
    "nudge_vector_param",
    "stack_two_panels",
    "dodge_two_panels",
    "dodge2_preserve_single_two_panels",
    "jitter_seed_two_panels",
    "identity_noop",
)

#: 随机流跨语言不一致、只比「包络」的 case（其余逐值相等）。
RNG_CASES = frozenset({"jitter_seed", "jitterdodge_defaults", "jitter_seed_two_panels"})

#: R 的点号参数名 → gg4py 的 snake_case。
_PARAM_ALIASES = {
    "dodge.width": "dodge_width",
    "jitter.width": "jitter_width",
    "jitter.height": "jitter_height",
}

#: `setup_params()` 逐项对拍：case → 要比的键。`seed` 单独处理（随机缺省不比较）。
PARAM_CASES = {
    "stack_two_groups": ("vjust", "reverse", "flipped_aes"),
    "stack_horizontal": ("vjust", "reverse", "flipped_aes"),
    "stack_two_panels": ("vjust", "reverse", "flipped_aes"),
    "dodge_two_groups": ("width", "n", "reverse", "flipped_aes"),
    "dodge_preserve_single": ("width", "n", "reverse", "flipped_aes"),
    "dodge_horizontal": ("width", "n", "reverse", "flipped_aes"),
    "dodge_two_panels": ("width", "n", "reverse", "flipped_aes"),
    "dodge2_two_groups": ("width", "n", "padding", "reverse", "flipped_aes"),
    "dodge2_padding": ("width", "n", "padding", "reverse", "flipped_aes"),
    "dodge2_preserve_single_no_x": ("width", "n", "padding", "reverse", "flipped_aes"),
    "dodge2_preserve_total_uneven": ("width", "n", "padding", "reverse", "flipped_aes"),
    "dodge2_preserve_single_uneven": ("width", "n", "padding", "reverse", "flipped_aes"),
    "dodge2_boxplot": ("width", "n", "padding", "reverse", "flipped_aes"),
    "dodge2_boxplot_varwidth": ("width", "n", "padding", "reverse", "flipped_aes"),
    "dodge2_horizontal": ("width", "n", "padding", "reverse", "flipped_aes"),
    "dodge2_preserve_single_two_panels": ("width", "n", "padding", "reverse", "flipped_aes"),
    "jitter_seed": ("width", "height", "seed"),
    "jitterdodge_zero_jitter": (
        "dodge.width",
        "jitter.width",
        "jitter.height",
        "reverse",
        "flipped_aes",
    ),
    "jitterdodge_dodge_width": (
        "dodge.width",
        "jitter.width",
        "jitter.height",
        "reverse",
        "flipped_aes",
    ),
    "jitterdodge_zero_jitter_reverse": (
        "dodge.width",
        "jitter.width",
        "jitter.height",
        "reverse",
        "flipped_aes",
    ),
    "jitterdodge_defaults": ("dodge.width", "jitter.width", "jitter.height", "flipped_aes"),
    "jitterdodge_two_panels": ("dodge.width", "jitter.width", "jitter.height", "flipped_aes"),
}


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _column(spec: dict) -> Column:
    values = spec["values"]
    missing = np.array([value is None for value in values], dtype=bool)
    if spec["kind"] == "float":
        data = np.array([0.0 if value is None else float(value) for value in values])
    elif spec["kind"] == "int":
        data = np.array([0.0 if value is None else float(value) for value in values])
    elif spec["kind"] == "bool":
        data = np.array([False if value is None else bool(value) for value in values], dtype=bool)
    else:
        data = np.array(["" if value is None else str(value) for value in values], dtype=object)
    return Column(spec["kind"], data, na_mask=missing)


def _table(columns: list[dict]) -> ColumnTable:
    return ColumnTable([(spec["name"], _column(spec)) for spec in columns])


def _values(table: ColumnTable, name: str) -> np.ndarray:
    column = table.column(name)
    return np.where(column.na_mask, np.nan, column.values.astype(np.float64))


def _case(reference: dict, case_id: str) -> dict:
    return next(case for case in reference["cases"] if case["id"] == case_id)


def _run(case: dict) -> tuple[ColumnTable, ColumnTable]:
    source = _table(case["input"])
    position = construct("position", case["position"], **case["position_params"])
    return source, position.compute_layer(source)


def test_fixture_comes_from_pinned_ggplot2(reference: dict) -> None:
    assert reference["generated_by"] == "tools/refs/position_ref.R"
    assert reference["ggplot2_version"] == "4.0.3"
    assert reference["locale"] == "C.UTF-8"


def test_fixture_case_set_is_pinned(reference: dict) -> None:
    assert tuple(case["id"] for case in reference["cases"]) == EXPECTED_CASES
    for case in reference["cases"]:
        assert case["position"] in {
            "identity",
            "stack",
            "fill",
            "dodge",
            "dodge2",
            "jitter",
            "jitterdodge",
            "nudge",
        }
        assert case["input"], case["id"]
        assert case["output"], case["id"]


def test_only_rng_cases_have_an_envelope(reference: dict) -> None:
    """随机流跨语言不一致的 case 记包络（`envelope`），其余必须逐值可对。"""
    for case in reference["cases"]:
        if case["id"] in RNG_CASES:
            assert case["envelope"] is not None, case["id"]
        else:
            assert case["envelope"] is None, case["id"]


@pytest.mark.parametrize("case_id", sorted(PARAM_CASES))
def test_setup_params_matches_r(reference: dict, case_id: str) -> None:
    """`setup_params()` 的解析结果逐项与 R 相等（整层口径：n / jitter.width / …）。"""
    case = _case(reference, case_id)
    source = _table(case["input"])
    position = construct("position", case["position"], **case["position_params"])
    merged = {**position.params, **case["position_params"]}
    resolved = position.setup_params(source, merged)

    for key in PARAM_CASES[case_id]:
        py_key = _PARAM_ALIASES.get(key, key)
        assert py_key in resolved, f"{case_id}: setup_params() 少了 {py_key}"
        want = case["params"][key]
        got = resolved[py_key]
        if want is None or got is None:
            assert got is None and want is None, f"{case_id}.{key}: {got!r} != {want!r}"
        elif isinstance(want, bool):
            assert bool(got) is want, f"{case_id}.{key}: {got!r} != {want!r}"
        else:
            assert float(got) == pytest.approx(float(want), abs=TOLERANCE), (
                f"{case_id}.{key}: {got!r} != {want!r}"
            )


@pytest.mark.parametrize("case_id", [case for case in EXPECTED_CASES if case not in RNG_CASES])
def test_position_matches_r_row_by_row(reference: dict, case_id: str) -> None:
    case = _case(reference, case_id)
    source, positioned = _run(case)

    # 不删行、不改 nrows。
    assert positioned.nrows == source.nrows == len(case["output"][0]["values"])

    expected = {spec["name"]: spec for spec in case["output"]}
    for name, spec in expected.items():
        assert name in positioned, f"{case_id}: 缺少列 {name}"
        got = positioned.column(name)
        want = _column(spec)
        assert got.kind == want.kind or (got.kind, want.kind) == ("int", "float"), (
            f"{case_id}.{name}: kind {got.kind} != {want.kind}"
        )
        assert np.array_equal(got.na_mask, want.na_mask), f"{case_id}.{name}: 缺失行不一致"
        if want.kind == "str":
            assert got.values.tolist() == want.values.tolist(), f"{case_id}.{name}: 字符串列不一致"
        else:
            assert np.allclose(
                _values(positioned, name),
                _values(_table([spec]), name),
                rtol=0,
                atol=TOLERANCE,
                equal_nan=True,
            ), f"{case_id}.{name}: 数值列不一致"

    # `order` 是上游 dodge / dodge2 的产物：R 有就要有，并且逐值相等。
    assert ("order" in expected) == ("order" in positioned.names), case_id
    # dodge2 在「每根柱各自一个重叠组」时会漏出 xid/newx/new_width 三列（上游
    # 直接把内部列返回了）；夹具按只记位置列的口径生成，这里断言我们不漏。
    for leaked in ("xid", "newx", "new_width", "pad_width"):
        assert leaked not in positioned.names, case_id


def test_compared_cell_count(reference: dict) -> None:
    """对拍规模：钉住 case 数与「参与比值的值」总数，防止夹具悄悄缩水。"""
    values = 0
    for case in reference["cases"]:
        if case["id"] in RNG_CASES:
            continue
        for spec in case["output"]:
            values += len(spec["values"])
    assert len(EXPECTED_CASES) == 33
    assert values == 1182


def test_rng_envelope_and_determinism(reference: dict) -> None:
    """随机流 case：包络与 R 一致、seed 可复现、R 的值落在同一包络内。

    jitter 与 jitterdodge 的抖动值跨语言不可能相等，比的是：

    - 同一个 seed 两次调用逐位相同；
    - 每个抖动偏移不超过半宽（jitter 相对输入；jitterdodge 的 dodge 相位是
      确定量，所以比「与 R 输出的差」≤ 两边半宽之和）；
    - `height = 0` 时 y 列必须逐值相等。
    """
    assert RNG_CASES == {"jitter_seed", "jitterdodge_defaults", "jitter_seed_two_panels"}
    for case_id in RNG_CASES:
        case = _case(reference, case_id)
        source, first = _run(case)
        _, second = _run(case)
        assert first == second, case_id

        width = case["envelope"]["width"]
        height = case["envelope"]["height"]
        r_output = {spec["name"]: _column(spec) for spec in case["output"]}
        for name, limit in (("x", width), ("y", height)):
            got = _values(first, name)
            original = _values(source, name)
            r_values = r_output[name].values.astype(np.float64)
            if case["position"] == "jitterdodge":
                # dodge 相位相同，只有抖动不同：两边差 ≤ 2 × 半宽。
                assert np.all(np.abs(got - r_values) <= 2 * limit + TOLERANCE), (case_id, name)
                if limit == 0:
                    assert np.array_equal(got, r_values), (case_id, name)
            else:
                assert np.all(np.abs(got - original) <= limit + TOLERANCE), (case_id, name)
                # R 的值同样落在同一个半宽里 —— 说明分辨率口径一致。
                assert np.all(np.abs(r_values - original) <= limit + TOLERANCE), (case_id, name)
                assert not np.allclose(got, original), (case_id, name)

    jitter = _case(reference, "jitter_seed")["envelope"]
    assert jitter["width"] == pytest.approx(0.4, abs=TOLERANCE)
    assert jitter["height"] == pytest.approx(0.4, abs=TOLERANCE)
    jitterdodge = _case(reference, "jitterdodge_defaults")["envelope"]
    # 40% resolution / (ndodge + 2) = 0.4 / 4；height 缺省 0。
    assert jitterdodge["width"] == pytest.approx(0.1, abs=TOLERANCE)
    assert jitterdodge["height"] == 0


def test_jitter_without_seed_is_not_reproducible(reference: dict) -> None:
    for case_id in ("jitter_seed",):
        case = _case(reference, case_id)
        source = _table(case["input"])
        params = dict(case["position_params"])
        params.pop("seed")
        first = construct("position", case["position"], **params).compute_layer(source)
        second = construct("position", case["position"], **params).compute_layer(source)
        assert not np.allclose(_values(first, "x"), _values(second, "x"))

    # jitterdodge 的 seed 缺省同样每次重抽。
    case = _case(reference, "jitterdodge_defaults")
    source = _table(case["input"])
    first = construct("position", "jitterdodge").compute_layer(source)
    second = construct("position", "jitterdodge").compute_layer(source)
    assert not np.allclose(_values(first, "x"), _values(second, "x"))


def test_parity_has_teeth(reference: dict) -> None:
    """把 dodge 的期望值挪 1e-3：逐值比较必须红（夹具不是摆设）。"""
    case = _case(reference, "dodge_two_groups")
    broken = json.loads(json.dumps(case))
    xmin = next(spec for spec in broken["output"] if spec["name"] == "xmin")
    xmin["values"][0] = float(xmin["values"][0]) + 1e-3

    _, positioned = _run(broken)
    spec = next(item for item in broken["output"] if item["name"] == "xmin")
    assert not np.allclose(
        _values(positioned, "xmin"),
        _values(_table([spec]), "xmin"),
        rtol=0,
        atol=TOLERANCE,
        equal_nan=True,
    )
