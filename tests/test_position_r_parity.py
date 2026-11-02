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
)

#: 唯一一个随机流跨语言不一致的 case（其余逐值相等）。
RNG_CASES = frozenset({"jitter_seed"})


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
            "nudge",
        }
        assert case["input"], case["id"]
        assert case["output"], case["id"]


def test_only_jitter_has_an_rng_dependent_output(reference: dict) -> None:
    """11 个 case 里只有 jitter 的随机流跨语言不一致；其余必须逐值可对。"""
    assert RNG_CASES == {"jitter_seed"}
    for case in reference["cases"]:
        if case["id"] in RNG_CASES:
            assert case["envelope"] is not None, case["id"]
        else:
            assert case["envelope"] is None, case["id"]


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
    assert len(EXPECTED_CASES) == 14
    assert values == 496


def test_jitter_envelope_and_determinism(reference: dict) -> None:
    """jitter：缺省包络与 R 一致、seed 可复现、R 的值也在同一包络内。"""
    case = _case(reference, "jitter_seed")
    source, first = _run(case)
    _, second = _run(case)
    assert first == second

    width = case["envelope"]["width"]
    height = case["envelope"]["height"]
    assert width == pytest.approx(0.4, abs=TOLERANCE)
    assert height == pytest.approx(0.4, abs=TOLERANCE)

    r_output = {spec["name"]: _column(spec) for spec in case["output"]}
    for name, limit in (("x", width), ("y", height)):
        jittered = _values(first, name)
        original = _values(source, name)
        assert np.all(np.abs(jittered - original) <= limit + TOLERANCE), name
        # R 的值（不同随机流）同样落在同一个半宽里 —— 说明分辨率口径一致。
        r_values = r_output[name].values.astype(np.float64)
        assert np.all(np.abs(r_values - original) <= limit + TOLERANCE), name
        assert not np.allclose(jittered, original), name


def test_jitter_without_seed_is_not_reproducible(reference: dict) -> None:
    case = _case(reference, "jitter_seed")
    source = _table(case["input"])
    params = dict(case["position_params"])
    params.pop("seed")
    first = construct("position", "jitter", **params).compute_layer(source)
    second = construct("position", "jitter", **params).compute_layer(source)
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
