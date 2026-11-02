"""M1-3 与 ggplot2 4.0.3 的对拍：五张图的图层数据逐列比。

夹具由 `pixi run -e refs refs:build`（`tools/refs/build_ref.R`）生成：R 侧
`ggplot_build(p)$data[[1]]` 的列名、列序、类型与每一行的值原样写进
`tests/fixtures/build_r_reference.json`，数据集也一起落盘，所以跑测试不需要 R。

对拍口径（`docs/notes/build.md`）：

- **列名与列序**必须完全一致（含 `PANEL` / `group` / geom 派生的 `xmin/xmax`）；
- 数值 `allclose(rtol=0, atol=1e-9)`，字符串精确相等，缺失（R 的 `NA` /
  这里的 `na_mask`）逐行一致；
- 只有三列**比列名与位置、不比值**，因为它们的值由本任务之外的部分决定：
  `count_bar.fill` 与 `box_precomputed.colour` 是 theme_grey 解析出的主题色
  （M1-10），`stacked_bar_interaction.fill` 是离散调色板（M1-4）。本任务的
  identity scale 不做调色板，M1-10 之前 `Geom.default_aes` 也只存语义色名。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ggcore.build import LayerBuild, build_plot
from ggcore.data import Column, ColumnTable
from ggcore.plot import aes, geom_bar, geom_boxplot, geom_col, geom_line, geom_point, ggplot

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "build_r_reference.json"

#: 只比列名/列序、不比值的列（值归 M1-4 / M1-10）。
SKIP_VALUES: dict[str, frozenset[str]] = {
    "count_bar": frozenset({"fill"}),
    "box_precomputed": frozenset({"colour"}),
    "stacked_bar_interaction": frozenset({"fill"}),
    "point_na_colour": frozenset({"colour"}),
    "count_na_x": frozenset({"fill"}),
    "col_identity": frozenset({"fill"}),
    "col_width_param": frozenset({"fill"}),
    "categorical_group": frozenset({"colour"}),
    "multi_layer_levels": frozenset({"fill"}),
}

#: 每个 case 的（列数, 行数, 参与比值的列数）——钉住，防止「悄悄少比一列」。
EXPECTED: dict[str, tuple[int, int, int]] = {
    "point_computed": (10, 234, 10),
    "count_bar": (17, 7, 16),
    "box_precomputed": (20, 4, 19),
    "stacked_bar_interaction": (17, 12, 16),
    "layer_data_override": (10, 81, 10),
    "point_na_colour": (10, 5, 9),
    "count_na_x": (17, 4, 16),
    "col_identity": (15, 6, 14),
    "col_width_param": (15, 6, 14),
    "line_unsorted": (9, 4, 9),
    "point_params": (10, 234, 10),
    "bar_fill_param": (17, 7, 17),
    "aes_reordered": (10, 234, 10),
    "categorical_group": (10, 3, 9),
    "bool_discrete_x": (10, 3, 10),
    "multi_layer_levels": (17, 3, 16),
}

TOLERANCE = 1e-9


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _column_from_reference(spec: dict) -> Column:
    """夹具里的列 → Column（null → na_mask）。"""
    values = spec["values"]
    missing = np.array([value is None for value in values], dtype=bool)
    kind = spec["kind"]
    if kind == "float":
        data = np.array([0.0 if value is None else float(value) for value in values])
        return Column("float", data, na_mask=missing)
    if kind == "int":
        data = np.array([0 if value is None else int(value) for value in values])
        return Column("int", data, na_mask=missing)
    if kind == "bool":
        data = np.array([False if value is None else bool(value) for value in values])
        return Column("bool", data, na_mask=missing)
    if "levels" in spec:
        levels = tuple(spec["levels"])
        codes = np.array(
            [0 if value is None else levels.index(value) for value in values], dtype=np.int32
        )
        return Column("categorical", codes, levels=levels, na_mask=missing)
    data = np.array(["" if value is None else value for value in values], dtype=object)
    return Column("str", data, na_mask=missing)


def _table(spec: dict) -> ColumnTable:
    return ColumnTable(
        [(column["name"], _column_from_reference(column)) for column in spec["columns"]]
    )


def _row_subset(table: ColumnTable, mask: np.ndarray) -> ColumnTable:
    """按行掩码取子集，保留 kind / levels / na_mask（层级 data 覆盖用）。"""
    return ColumnTable(
        [
            (name, Column(column.kind, column.values[mask], column.levels, column.na_mask[mask]))
            for name, column in zip(table.names, table.columns(), strict=True)
        ]
    )


def _plots(reference: dict) -> dict[str, ggplot]:
    datasets = {name: _table(spec) for name, spec in reference["datasets"].items()}
    mpg = datasets["mpg"]
    boxes = datasets["boxes"]
    na_point = datasets["na_point"]
    na_x = datasets["na_x"]
    col_data = datasets["col_data"]
    line_data = datasets["line_data"]
    categorical_data = datasets["categorical_data"]
    bool_data = datasets["bool_data"]
    multi_data = datasets["multi_data"]
    cyl4 = _row_subset(mpg, mpg.column("cyl").values == 4.0)
    return {
        "point_computed": ggplot(mpg, aes(x="displ", y="hwy / cyl")) + geom_point(),
        "count_bar": ggplot(mpg, aes(x="class")) + geom_bar(),
        "box_precomputed": ggplot(boxes, aes(x="g"))
        + geom_boxplot(
            stat="identity",
            position="identity",
            mapping=aes(lower="lo", upper="hi", middle="mid", ymin="y0", ymax="y1"),
        ),
        "stacked_bar_interaction": ggplot(mpg, aes(x="drv", fill="class")) + geom_bar(),
        "layer_data_override": ggplot(mpg, aes(x="displ", y="hwy")) + geom_point(data=cyl4),
        "point_na_colour": ggplot(na_point, aes(x="x", y="y", colour="g")) + geom_point(),
        "count_na_x": ggplot(na_x, aes(x="xs")) + geom_bar(),
        "col_identity": ggplot(col_data, aes(x="xs", y="ys")) + geom_col(),
        "col_width_param": ggplot(col_data, aes(x="xs", y="ys")) + geom_col(width=0.3),
        "line_unsorted": ggplot(line_data, aes(x="x", y="y", group="g")) + geom_line(),
        "point_params": ggplot(mpg, aes(x="displ", y="hwy")) + geom_point(colour="red", size=3),
        "bar_fill_param": ggplot(mpg, aes(x="class")) + geom_bar(fill="steelblue"),
        "aes_reordered": ggplot(mpg, aes(y="hwy", x="displ")) + geom_point(),
        "categorical_group": ggplot(categorical_data, aes(x="x", y="y", colour="g")) + geom_point(),
        "bool_discrete_x": ggplot(bool_data, aes(x="x", y="y")) + geom_point(),
        "multi_layer_levels": ggplot(multi_data, aes(x="cls"))
        + geom_bar()
        + geom_bar(aes(x="drv")),
    }


def _built(reference: dict, case_id: str) -> LayerBuild:
    return build_plot(_plots(reference)[case_id]).layers[0]


def test_fixture_comes_from_pinned_ggplot2(reference: dict) -> None:
    assert reference["generated_by"] == "tools/refs/build_ref.R"
    assert reference["ggplot2_version"] == "4.0.3"
    assert reference["locale"] == "C.UTF-8"
    assert {case["id"] for case in reference["cases"]} == set(EXPECTED)


@pytest.mark.parametrize("case_id", list(EXPECTED))
def test_layer_data_matches_r(reference: dict, case_id: str) -> None:
    """五张图：列名 / 列序 / 行数 / 逐列值。"""
    case = next(item for item in reference["cases"] if item["id"] == case_id)
    layer = _built(reference, case_id)
    skip = SKIP_VALUES.get(case_id, frozenset())
    expected_names = [column["name"] for column in case["columns"]]

    assert list(layer.data.names) == expected_names
    assert layer.data.nrows == case["rows"] == len(case["columns"][0]["values"])
    assert len(expected_names) == EXPECTED[case_id][0]

    checked = 0
    for spec in case["columns"]:
        name = spec["name"]
        column = layer.data.column(name)
        if name in skip:
            # 值归 M1-4 / M1-10 的调色板与主题；kind 仍然比（唯一例外是
            # categorical 源列：我们保留 categorical code，R 的 $data 是 character）。
            if not (case_id == "categorical_group" and name == "colour"):
                assert column.kind == spec["kind"], f"{name}: kind 不一致"
            continue
        assert column.kind == spec["kind"], f"{name}: kind 不一致"
        expected_missing = np.array([value is None for value in spec["values"]], dtype=bool)
        assert np.array_equal(column.na_mask, expected_missing), f"{name}: 缺失行不一致"
        values = column.values
        if spec["kind"] == "str":
            got = [
                None if missing else str(value)
                for value, missing in zip(values.tolist(), column.na_mask.tolist(), strict=True)
            ]
            assert got == spec["values"], f"{name}: 字符串列不一致"
        else:
            got = np.array(
                [
                    np.nan if missing else float(value)
                    for value, missing in zip(values.tolist(), column.na_mask.tolist(), strict=True)
                ]
            )
            expected = np.array(
                [np.nan if value is None else float(value) for value in spec["values"]]
            )
            assert np.allclose(got, expected, rtol=0, atol=TOLERANCE, equal_nan=True), (
                f"{name}: 数值列不一致；最大差 "
                f"{np.nanmax(np.abs(got - expected)) if got.size else 0}"
            )
        checked += 1
    assert checked == EXPECTED[case_id][2]


def test_compared_cell_count(reference: dict) -> None:
    """对拍规模：214 列里 205 列参与比值、8747 个值（钉住，不许悄悄缩水）。"""
    total_columns = 0
    total_values = 0
    for case in reference["cases"]:
        columns, rows, compared = EXPECTED[case["id"]]
        assert columns == len(case["columns"])
        assert rows == case["rows"]
        total_columns += compared
        total_values += compared * rows
    assert total_columns == 205
    assert total_values == 8747


def test_skipped_columns_only_carry_scale_or_theme_values(reference: dict) -> None:
    """被跳过值的列仍然存在且位置一致；跳过的只有 theme 色 / 调色板。"""
    for case in reference["cases"]:
        skipped = SKIP_VALUES.get(case["id"], frozenset())
        names = [column["name"] for column in case["columns"]]
        assert skipped <= set(names)
        for name in skipped:
            assert name in ("colour", "fill")


def test_multi_layer_levels_match_r(reference: dict) -> None:
    """多层离散 x：跨层水平全局排序，两层各自的 x 编码都要对上。"""
    case = next(item for item in reference["cases"] if item["id"] == "multi_layer_levels")
    build = build_plot(_plots(reference)["multi_layer_levels"])
    assert list(build.scales.trained["x"]) == case["x_labels"]
    assert len(case["layers"]) == 2
    for index, layer_spec in enumerate(case["layers"]):
        layer = build.layers[index]
        names = [column["name"] for column in layer_spec["columns"]]
        assert list(layer.data.names) == names
        assert layer.data.nrows == layer_spec["rows"]
        for spec in layer_spec["columns"]:
            name = spec["name"]
            if name in SKIP_VALUES["multi_layer_levels"]:
                continue
            column = layer.data.column(name)
            assert column.kind == spec["kind"], f"layer[{index}].{name}: kind 不一致"
            values = column.values
            if spec["kind"] == "str":
                got = [
                    None if missing else str(value)
                    for value, missing in zip(values.tolist(), column.na_mask.tolist(), strict=True)
                ]
                assert got == spec["values"], f"layer[{index}].{name}: 字符串列不一致"
            else:
                got = np.array(
                    [
                        np.nan if missing else float(value)
                        for value, missing in zip(
                            values.tolist(), column.na_mask.tolist(), strict=True
                        )
                    ]
                )
                expected = np.array(
                    [np.nan if value is None else float(value) for value in spec["values"]]
                )
                assert np.allclose(got, expected, rtol=0, atol=TOLERANCE, equal_nan=True), (
                    f"layer[{index}].{name}: 数值列不一致"
                )


def test_parity_has_teeth(reference: dict) -> None:
    """改一个值，对拍必须红（不是恒真比较）。"""
    case = next(item for item in reference["cases"] if item["id"] == "point_computed")
    layer = _built(reference, "point_computed")
    expected = np.array(
        [np.nan if value is None else float(value) for value in case["columns"][1]["values"]]
    )
    got = np.array(
        [
            np.nan if missing else float(value)
            for value, missing in zip(
                layer.data.column("y").values.tolist(),
                layer.data.column("y").na_mask.tolist(),
                strict=True,
            )
        ]
    )
    assert np.allclose(got, expected, rtol=0, atol=TOLERANCE, equal_nan=True)
    assert not np.allclose(got + 1.0, expected, rtol=0, atol=TOLERANCE, equal_nan=True)
