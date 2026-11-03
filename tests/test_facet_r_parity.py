"""分面与 R ggplot2 4.0.3 的逐值对拍（M1-6）。

夹具由 `pixi run -e refs refs:facet`（`tools/refs/facet_ref.R`）生成，R 与
Python 用同一份 8 行数据（factor levels 故意与出现顺序不同）。对拍的是：

- `ggplot_build(p)$layout$layout` 的 PANEL / ROW / COL / SCALE_X / SCALE_Y
  与分面变量；
- `panel_params[[i]]$x.range` / `y.range`（含 expand，free scales 逐面板）；
- `ggplotGrob(p)` 的 panel 宽高单位（`1null`）、panel / strip 名字，
  以及 strip 的行高 / 列宽（cm；M1-7 起用真实 `stringWidth` / `text_line_cm`
  量，容差 2%）。`respect` / aspect 的 panel 权重按 R `init_gtable()` 的口径
  逐值比（SIL-759）。

数值断言只认夹具，不重算公式。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

from ggcore import registry
from ggcore.aes import aes
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.facet import labeller
from ggcore.geom.scene import plot_layout
from ggcore.plot import coord_polar, ggplot
from ggcore.theme import element_text, theme
from ggskia.text import ShaperMetrics

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "facet_r_reference.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = {case["name"]: case for case in REFERENCE["cases"]}
EXTRA = {case["name"]: case for case in REFERENCE["extra"]}
TOLERANCE = 1e-12


def categorical(values: list[str], levels: list[str]) -> Column:
    index = {level: position for position, level in enumerate(levels)}
    return Column(
        "categorical",
        np.array([index[value] for value in values], dtype=np.int32),
        levels=tuple(levels),
    )


DATA = ColumnTable(
    [
        ("x", Column("float", np.array(REFERENCE["data"]["x"], dtype=np.float64))),
        ("y", Column("float", np.array(REFERENCE["data"]["y"], dtype=np.float64))),
        ("a", categorical(REFERENCE["data"]["a"], REFERENCE["data"]["a_levels"])),
        ("b", categorical(REFERENCE["data"]["b"], REFERENCE["data"]["b_levels"])),
        ("c", categorical(REFERENCE["data"]["c"], REFERENCE["data"]["c_levels"])),
    ]
)


def base_plot() -> ggplot:
    return ggplot(DATA, aes(x="x", y="y")) + registry.geom_point()


BUILDERS = {
    "wrap_ncol2": lambda: base_plot() + registry.facet_wrap(("a",), ncol=2),
    "wrap_as_table_false": lambda: (
        base_plot() + registry.facet_wrap(("c",), ncol=2, as_table=False)
    ),
    "grid_2x2": lambda: base_plot() + registry.facet_grid(("b",), ("a",)),
    "grid_as_table_false": lambda: (
        base_plot() + registry.facet_grid(("b",), ("a",), as_table=False)
    ),
    "grid_free": lambda: base_plot() + registry.facet_grid(("b",), ("a",), scales="free"),
    "wrap_free": lambda: base_plot() + registry.facet_wrap(("a",), ncol=2, scales="free"),
}

EXTRA_BUILDERS = {
    "wrap_numeric": lambda table: (
        ggplot(table, aes(x="x", y="y")) + registry.geom_point() + registry.facet_wrap(("g",))
    ),
    "wrap_logical": lambda table: (
        ggplot(table, aes(x="x", y="y")) + registry.geom_point() + registry.facet_wrap(("g",))
    ),
    "wrap_na_numeric": lambda table: (
        ggplot(table, aes(x="x", y="y")) + registry.geom_point() + registry.facet_wrap(("g",))
    ),
    "wrap_na_str": lambda table: (
        ggplot(table, aes(x="x", y="y")) + registry.geom_point() + registry.facet_wrap(("g",))
    ),
    "grid_sparse": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("b",), ("a",))
    ),
    "wrap_drop_false_unused": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(("a",), drop=False)
    ),
    "grid_drop_false_unused": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(None, ("a",), drop=False)
    ),
    "wrap_multirow": lambda table: (
        ggplot(table, aes(x="x", y="y")) + registry.geom_point() + registry.facet_wrap(("g",))
    ),
    "grid_strip_text_y_20": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("b",), ("a",))
        + theme(**{"strip.text.y": element_text(size=20)})
    ),
}


def _records(build) -> list[dict[str, object]]:
    layout = build.layout
    assert layout is not None
    out: list[dict[str, object]] = []
    for index in range(layout.table.nrows):
        record: dict[str, object] = {}
        for name in layout.table.names:
            value = layout.table.column(name).values[index]
            record[name] = value.item() if hasattr(value, "item") else value
        out.append(record)
    return out


def _cm(text: str) -> float:
    match = re.fullmatch(r"([0-9.eE+-]+)cm", text)
    assert match is not None, text
    return float(match.group(1))


def _as_list(value: object) -> list[object]:
    """jsonlite 的 `auto_unbox` 会把长度 1 的数组写成标量。"""
    return value if isinstance(value, list) else [value]


def _extra_table(case: dict[str, object]) -> ColumnTable:
    data = case["data"]
    types = data["types"]
    levels = data["levels"]
    columns: list[tuple[str, Column]] = []
    for name, raw in data["columns"].items():
        values = _as_list(raw)
        missing = np.array([value is None for value in values], dtype=bool)
        kind = types[name]
        if kind in ("numeric", "integer"):
            columns.append(
                (
                    name,
                    Column(
                        "float",
                        np.array(
                            [
                                0.0 if skip else float(value)
                                for value, skip in zip(values, missing, strict=True)
                            ],
                            dtype=np.float64,
                        ),
                        na_mask=missing,
                    ),
                )
            )
        elif kind == "logical":
            columns.append(
                (
                    name,
                    Column(
                        "bool",
                        np.array(
                            [
                                False if skip else bool(value)
                                for value, skip in zip(values, missing, strict=True)
                            ],
                            dtype=bool,
                        ),
                        na_mask=missing,
                    ),
                )
            )
        elif kind == "factor":
            ordered = tuple(levels[name])
            index = {level: position for position, level in enumerate(ordered)}
            columns.append(
                (
                    name,
                    Column(
                        "categorical",
                        np.array(
                            [
                                0 if skip else index[str(value)]
                                for value, skip in zip(values, missing, strict=True)
                            ],
                            dtype=np.int32,
                        ),
                        levels=ordered,
                        na_mask=missing,
                    ),
                )
            )
        else:
            assert kind == "character", kind
            columns.append(
                (
                    name,
                    Column(
                        "str",
                        np.array(
                            [
                                "" if skip else str(value)
                                for value, skip in zip(values, missing, strict=True)
                            ],
                            dtype=str,
                        ),
                        na_mask=missing,
                    ),
                )
            )
    return ColumnTable(columns)


def _typed_records(build) -> list[dict[str, object]]:
    layout = build.layout
    assert layout is not None
    out: list[dict[str, object]] = []
    for panel in layout.panel_ids:
        record: dict[str, object] = {
            "PANEL": panel,
            "ROW": layout.row_of(panel),
            "COL": layout.col_of(panel),
        }
        for name in layout.facet_vars:
            record[name] = layout.value(panel, name)
        record["SCALE_X"] = layout.scale_x_of(panel)
        record["SCALE_Y"] = layout.scale_y_of(panel)
        out.append(record)
    return out


def test_fixture_covers_the_required_cases() -> None:
    assert REFERENCE["ggplot2"] == "4.0.3"
    assert set(BUILDERS) == set(CASES)
    assert set(EXTRA_BUILDERS) == set(EXTRA)
    assert {"wrap_ncol2", "grid_2x2", "grid_as_table_false", "grid_free"} <= set(CASES)
    assert DATA.column("a").levels == tuple(REFERENCE["data"]["a_levels"])


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_layout_matches_r(name: str) -> None:
    build = build_plot(BUILDERS[name]())
    assert _records(build) == CASES[name]["layout"]


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_panel_ranges_match_r(name: str) -> None:
    build = build_plot(BUILDERS[name]())
    expected = CASES[name]["panels"]
    assert [panel.panel for panel in build.panels] == [item["PANEL"] for item in expected]
    for panel, case in zip(build.panels, expected, strict=True):
        assert panel.panel_params.x_range == pytest.approx(tuple(case["x_range"]), abs=TOLERANCE)
        assert panel.panel_params.y_range == pytest.approx(tuple(case["y_range"]), abs=TOLERANCE)


def test_free_grid_has_four_distinct_combinations() -> None:
    """2×2 自由刻度：x 按列、y 按行，至少三个面板互不相同（验收口径）。"""
    build = build_plot(BUILDERS["grid_free"]())
    ranges = {(panel.panel_params.x_range, panel.panel_params.y_range) for panel in build.panels}
    assert len(ranges) == 4
    assert len({panel.panel_params.x_range for panel in build.panels}) == 2
    assert len({panel.panel_params.y_range for panel in build.panels}) == 2


@pytest.mark.parametrize("name", ["wrap_ncol2", "grid_2x2"])
def test_gtable_panel_units_match_r(name: str) -> None:
    build = build_plot(BUILDERS[name]())
    table = build.facet_table()
    expected = CASES[name]["gtable"]

    columns = sorted({left for _, _, left, _, _ in table.panels})
    rows = sorted({top for _, top, _, _, _ in table.panels})
    assert [str(table.gtable.widths[column - 1]) for column in columns] == _as_list(
        expected["panel_columns"]
    )
    assert [str(table.gtable.heights[row - 1]) for row in rows] == _as_list(expected["panel_rows"])
    assert (
        sorted(row.name for row in table.gtable.layout if row.name.startswith("panel"))
        == (expected["panel_names"])
    )
    assert (
        sorted(row.name for row in table.gtable.layout if row.name.startswith("strip"))
        == (expected["strip_names"])
    )


@pytest.mark.parametrize("name", ["wrap_ncol2", "grid_2x2"])
def test_gtable_strip_extent_matches_r_within_two_percent(name: str) -> None:
    build = build_plot(BUILDERS[name]())
    table = build.facet_table()
    for strip in CASES[name]["gtable"]["strip_sizes"]:
        if strip["name"].startswith("strip-t"):
            expected = _cm(strip["height"])
        else:
            expected = _cm(strip["width"])
        assert table.strip_height_cm == pytest.approx(expected, rel=0.02)


# ---------------------------------------------------------------------------
# extra：SIL-694 补的分面缺口（数值 / 逻辑 / NA / 空组合 / drop=FALSE /
# 多行 strip / strip.text.y）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(EXTRA_BUILDERS))
def test_extra_layout_matches_r(name: str) -> None:
    case = EXTRA[name]
    build = build_plot(EXTRA_BUILDERS[name](_extra_table(case)))
    assert _typed_records(build) == case["layout"]


@pytest.mark.parametrize("name", sorted(EXTRA_BUILDERS))
def test_extra_layout_types_and_labels_match_r(name: str) -> None:
    case = EXTRA[name]
    build = build_plot(EXTRA_BUILDERS[name](_extra_table(case)))
    layout = build.layout
    assert layout is not None
    kinds = {
        "numeric": "float",
        "integer": "float",
        "logical": "bool",
        "factor": "str",
        "character": "str",
    }
    for var, r_type in case["layout_types"].items():
        assert layout.table.column(var).kind == kinds[r_type]
    labels = [
        {var: layout.label(panel, var) for var in layout.facet_vars} for panel in layout.panel_ids
    ]
    assert labels == case["labels"]


@pytest.mark.parametrize("name", sorted(EXTRA_BUILDERS))
def test_extra_panel_ranges_match_r(name: str) -> None:
    case = EXTRA[name]
    build = build_plot(EXTRA_BUILDERS[name](_extra_table(case)))
    expected = case["panels"]
    assert [panel.panel for panel in build.panels] == [item["PANEL"] for item in expected]
    for panel, reference in zip(build.panels, expected, strict=True):
        assert panel.panel_params.x_range == pytest.approx(
            tuple(reference["x_range"]), abs=TOLERANCE
        )
        assert panel.panel_params.y_range == pytest.approx(
            tuple(reference["y_range"]), abs=TOLERANCE
        )


def test_wrap_multirow_structure_matches_r() -> None:
    case = EXTRA["wrap_multirow"]
    expected = case["structure"]
    build = build_plot(EXTRA_BUILDERS["wrap_multirow"](_extra_table(case)))
    table = build.facet_table()
    panel_rows = sorted({panel[1] for panel in table.panels})
    tops = [strip for strip in table.strips if strip.side == "top"]
    assert len(panel_rows) == expected["panel_row_count"]
    assert len(tops) == expected["top_strip_count"]
    assert [str(table.gtable.heights[row - 1]) for row in panel_rows] == expected["panel_rows"]
    placements = {row.name: row for row in table.gtable.layout}
    assert all(
        placements[strip.name].t == row_of_panel - 1
        for strip, row_of_panel in (
            (strip, next(panel[1] for panel in table.panels if panel[0] == strip.panel))
            for strip in tops
        )
    )
    heights = [str(value) for value in table.gtable.heights]
    assert heights.count("5.5points") == expected["panel_spacing_rows"]


def test_strip_text_y_width_matches_r() -> None:
    case = EXTRA["grid_strip_text_y_20"]
    build = build_plot(EXTRA_BUILDERS["grid_strip_text_y_20"](_extra_table(case)))
    table = build.facet_table()
    right_widths = [width for width in case["structure"]["strip_widths"] if width.endswith("cm")]
    assert right_widths
    assert table.strip_width_cm == pytest.approx(_cm(right_widths[0]), rel=0.02)
    # 右 strip 变宽不影响顶部 strip 的高度（strip.text.x 未被改）。
    assert table.strip_height_cm == pytest.approx(0.5870, abs=5e-4)


# ---------------------------------------------------------------------------
# full：M2-3 facet 全量（SIL-733）—— free scales / space=free / margins /
# labellers / strip 主题 / polar×facet
# ---------------------------------------------------------------------------

FULL = {case["name"]: case for case in REFERENCE["full"]}
METRICS = ShaperMetrics()

FULL_BUILDERS = {
    "wrap_free_x": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(("a",), ncol=2, scales="free_x")
    ),
    "wrap_free_y": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(("a",), ncol=2, scales="free_y")
    ),
    "grid_free_x": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("b",), ("a",), scales="free_x")
    ),
    "grid_free_y": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("b",), ("a",), scales="free_y")
    ),
    "wrap_space_free_x": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(("g",), space="free_x", scales="free")
    ),
    "wrap_space_free_y": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(("g",), space="free_y", scales="free")
    ),
    "grid_space_free": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("h",), ("g",), space="free", scales="free")
    ),
    "grid_space_free_aspect": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("h",), ("g",), space="free")
        + registry.coord_fixed(2)
    ),
    "grid_space_free_aspect_scales_free": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("h",), ("g",), space="free", scales="free")
        + registry.coord_fixed(2)
    ),
    "grid_rows_label_both": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("a", "b"), labeller="label_both")
    ),
    "grid_margins": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("b",), ("a",), margins=True)
    ),
    "grid_margins_var": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("b",), ("a",), margins="a")
    ),
    "wrap_label_both": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(("a", "b"), labeller="label_both")
    ),
    "wrap_label_context": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(("a",), labeller="label_context")
    ),
    "grid_label_both": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("b",), ("a",), labeller="label_both")
    ),
    "wrap_labeller_named": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(("a",), labeller=labeller(a={"q": "Q level", "p": "P level"}))
    ),
    "strip_y_angle0": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_grid(("b",), ("a",))
        + theme(**{"strip.text.y": element_text(angle=0)})
    ),
    "strip_x_size20": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(("a",), ncol=2)
        + theme(**{"strip.text.x": element_text(size=20)})
    ),
    "strip_outside": lambda table: (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(("a",), ncol=2)
        + theme(**{"strip.placement": "outside"})
    ),
    "polar_facet": lambda table: (
        ggplot(table, aes(x="a", y="y"))
        + registry.geom_point()
        + coord_polar()
        + registry.facet_wrap(("b",), ncol=2)
    ),
}


def _null_weight(text: str) -> float:
    assert text.endswith("null"), text
    return float(text[: -len("null")])


@pytest.mark.parametrize("name", sorted(FULL_BUILDERS))
def test_full_layout_matches_r(name: str) -> None:
    case = FULL[name]
    build = build_plot(FULL_BUILDERS[name](_extra_table(case)))
    assert _typed_records(build) == case["layout"]


@pytest.mark.parametrize("name", sorted(FULL_BUILDERS))
def test_full_labels_match_r(name: str) -> None:
    """labeller 的全形态：每条 strip 的文本（含 `label_both` 的 `变量: 值`）。"""
    case = FULL[name]
    build = build_plot(FULL_BUILDERS[name](_extra_table(case)))
    layout = build.layout
    assert layout is not None
    labels = [build.facet.strip_labels(layout, panel) for panel in layout.panel_ids]
    assert labels == case["labels"]


@pytest.mark.parametrize("name", sorted(FULL_BUILDERS))
def test_full_panel_ranges_match_r(name: str) -> None:
    case = FULL[name]
    build = build_plot(FULL_BUILDERS[name](_extra_table(case)))
    expected = case["panels"]
    assert [panel.panel for panel in build.panels] == [item["PANEL"] for item in expected]
    for panel, reference in zip(build.panels, expected, strict=True):
        if reference.get("x_range"):
            assert panel.panel_params.x_range == pytest.approx(
                tuple(reference["x_range"]), abs=TOLERANCE
            )
        if reference.get("y_range"):
            assert panel.panel_params.y_range == pytest.approx(
                tuple(reference["y_range"]), abs=TOLERANCE
            )


@pytest.mark.parametrize("name", sorted(FULL_BUILDERS))
def test_full_panel_weights_match_r(name: str) -> None:
    """`space = "free"`：面板 null 权重 = R `init_gtable()` 的范围差。"""
    case = FULL[name]
    build = build_plot(FULL_BUILDERS[name](_extra_table(case)))
    table = build.facet_table()
    expected_columns = [_null_weight(text) for text in _as_list(case["gtable"]["panel_columns"])]
    expected_rows = [_null_weight(text) for text in _as_list(case["gtable"]["panel_rows"])]
    actual_columns = [
        _null_weight(str(unit)) for unit in table.gtable.widths if str(unit).endswith("null")
    ]
    actual_rows = [
        _null_weight(str(unit)) for unit in table.gtable.heights if str(unit).endswith("null")
    ]
    assert actual_columns == pytest.approx(expected_columns, rel=1e-9)
    assert actual_rows == pytest.approx(expected_rows, rel=1e-9)


@pytest.mark.parametrize("name", sorted(FULL_BUILDERS))
def test_full_strip_extents_match_r(name: str) -> None:
    """strip 块的高 / 宽（cm）与 `ggplotGrob()` 逐项一致（svglite 口径）。"""
    case = FULL[name]
    build = build_plot(FULL_BUILDERS[name](_extra_table(case)))
    table = build.facet_table(metrics=METRICS)
    strips = case["gtable"]["strips"]
    top = [strip for strip in strips if strip["name"].startswith("strip-t")]
    right = [strip for strip in strips if strip["name"].startswith("strip-r")]
    if top:
        expected = _cm(_as_list(top[0]["height"])[0])
        assert table.strip_height_cm == pytest.approx(expected, rel=0.02)
    else:
        assert table.strip_height_cm == 0.0
    if right:
        expected = _cm(_as_list(right[0]["width"])[0])
        assert table.strip_width_cm == pytest.approx(expected, rel=0.02)
    else:
        assert table.strip_width_cm == 0.0


@pytest.mark.parametrize("name", sorted(FULL_BUILDERS))
def test_full_strip_cells_match_r(name: str) -> None:
    """每条 strip 的内层单元格文字顺序（右侧 = 最后一个变量最靠近面板）。"""
    case = FULL[name]
    build = build_plot(FULL_BUILDERS[name](_extra_table(case)))
    table = build.facet_table()
    strips = {strip.name: strip for strip in table.strips}
    for reference in case["gtable"]["strips"]:
        strip = strips.get(reference["name"])
        assert strip is not None, reference["name"]
        assert [part.text for part in strip.parts] == [
            str(item) for item in _as_list(reference["cells"])
        ]


@pytest.mark.parametrize("name", ["grid_space_free_aspect", "grid_space_free_aspect_scales_free"])
def test_space_free_aspect_panel_ratio_matches_r(name: str) -> None:
    """SIL-759：`ratio` 折进行权重后，面板高/宽 == ratio × yspan / xspan。"""
    case = FULL[name]
    build = build_plot(FULL_BUILDERS[name](_extra_table(case)))
    table = build.facet_table()
    assert case["gtable"]["respect"] is True
    assert table.respect is True
    layout = plot_layout(build)
    for panel, reference in zip(build.panels, case["panels"], strict=True):
        box = layout.panel_boxes[panel.panel]
        x_span = reference["x_range"][1] - reference["x_range"][0]
        y_span = reference["y_range"][1] - reference["y_range"][0]
        assert box.height_cm / box.width_cm == pytest.approx(2.0 * y_span / x_span, rel=1e-9)


def test_full_fixture_covers_the_required_families() -> None:
    assert set(FULL_BUILDERS) == set(FULL)
    assert {"wrap_free_x", "wrap_free_y", "grid_space_free", "grid_margins"} <= set(FULL)
    # SIL-759：space=free × coord_fixed 的 geometry，以及多行变量的右侧 strip 顺序。
    assert {
        "grid_space_free_aspect",
        "grid_space_free_aspect_scales_free",
        "grid_rows_label_both",
    } <= set(FULL)
    assert any(name.startswith("polar") for name in FULL)
