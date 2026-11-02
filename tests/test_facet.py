"""分面契约（M1-6）：布局、自由刻度、逐面板流水线、strip 与 gtable。

R 逐值对拍在 `tests/test_facet_r_parity.py`（夹具由
`tools/refs/facet_ref.R` 生成）；这里守的是**手算**能推出的口径：

- 面板顺序按 levels（不是出现序）；`as.table = FALSE` 让 wrap 从下往上、
  grid 的行变量倒序；
- `free` 的 x 按列 / wrap 按面板，`free` 的 y 按行 / wrap 按面板；
- 固定刻度时所有面板共用一套范围；
- 面板循环的结果与「每个面板单独 build」逐列相同；
- gtable 的 panel 矩形等宽等高、strip 文本来自 labeller、spacing 来自主题。
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from ggcore import registry
from ggcore.aes import aes
from ggcore.build import BuildError, build_plot
from ggcore.data import Column, ColumnTable
from ggcore.facet import FacetError, facet_from_component
from ggcore.plot import ggplot
from ggcore.theme import element_blank, theme
from ggcore.units import unit


def categorical(values: list[str], levels: tuple[str, ...]) -> Column:
    index = {level: position for position, level in enumerate(levels)}
    return Column(
        "categorical",
        np.array([index[value] for value in values], dtype=np.int32),
        levels=levels,
    )


DATA = ColumnTable(
    [
        ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0, 10.0, 20.0, 30.0, 40.0]))),
        ("y", Column("float", np.array([10.0, 20.0, 30.0, 40.0, 100.0, 200.0, 300.0, 400.0]))),
        # 出现顺序是 p, q；levels 是 q, p —— 面板顺序必须跟着 levels。
        ("a", categorical(["p", "p", "q", "q", "p", "p", "q", "q"], ("q", "p"))),
        ("b", categorical(["u", "u", "u", "u", "v", "v", "v", "v"], ("v", "u"))),
        (
            "c",
            categorical(["d", "d", "c", "c", "b", "b", "a", "a"], ("d", "c", "b", "a")),
        ),
    ]
)


def base_plot() -> ggplot:
    return ggplot(DATA, aes(x="x", y="y")) + registry.geom_point()


def wrap_plot(**params) -> ggplot:
    return base_plot() + registry.facet_wrap(("a",), **params)


def grid_plot(**params) -> ggplot:
    return base_plot() + registry.facet_grid(("b",), ("a",), **params)


def layout_records(build) -> list[dict[str, object]]:
    layout = build.layout
    assert layout is not None
    records: list[dict[str, object]] = []
    for index in range(layout.table.nrows):
        record: dict[str, object] = {}
        for name in layout.table.names:
            value = layout.table.column(name).values[index]
            record[name] = value.item() if hasattr(value, "item") else value
        records.append(record)
    return records


def table_digest(table: ColumnTable) -> bytes:
    digest = hashlib.sha256()
    digest.update(b"table\x00")
    for name, column in zip(table.names, table.columns(), strict=True):
        digest.update(name.encode())
        digest.update(b"\x00")
        digest.update(column.kind.encode())
        digest.update(b"\x00")
        digest.update("|".join(column.levels).encode())
        digest.update(b"\x00")
        digest.update(str(np.asarray(column.values).dtype).encode())
        digest.update(b"\x00")
        digest.update(np.ascontiguousarray(column.values).tobytes())
        digest.update(b"\x00")
        digest.update(np.ascontiguousarray(column.na_mask).tobytes())
        digest.update(b"\x00")
    return digest.digest()


def build_digest(build) -> str:
    """单面板整份构建的字节摘要（阶段表 + 面板参数 + 提示）。"""
    digest = hashlib.sha256()
    for layer in build.layers:
        for stage in ("aesthetics", "statistic", "mapped", "positioned", "scaled", "data"):
            digest.update(table_digest(getattr(layer, stage)))
        digest.update(repr(dict(layer.dropped_missing)).encode())
    params = build.panel_params
    assert params is not None
    for name in ("x_range", "y_range", "x_limits", "y_limits"):
        digest.update(np.asarray(getattr(params, name), dtype=np.float64).tobytes())
    digest.update(repr(build.warnings).encode())
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# facet_null：与 M1-5 单面板逐字节相同
# ---------------------------------------------------------------------------


def test_facet_null_is_one_panel_with_the_existing_contract() -> None:
    build = build_plot(base_plot())
    assert build.facet is not None and build.facet.kind == "null"
    assert build.layout is not None
    assert layout_records(build) == [{"PANEL": 1, "ROW": 1, "COL": 1, "SCALE_X": 1, "SCALE_Y": 1}]
    assert build.layers[0].data.column("PANEL").values.tolist() == ["1"] * 8
    assert len(build.panels) == 1
    assert build.panels[0].panel_params is build.panel_params


def test_facet_null_build_is_byte_identical_to_m1_5() -> None:
    """钉住 main@efdb65c 的摘要：任何单面板输出（含 IR 输入表）变一位就红。

    摘要在分面实现前后各跑一次（同一脚本、两个 checkout），6 张图逐一相等；
    这里把值钉进测试，避免以后悄悄改变单面板路径。
    """
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))),
            ("y", Column("float", np.array([3.0, 1.0, 4.0, 1.5, 5.0, 2.0]))),
            ("g", Column("str", np.array(["a", "b", "a", "b", "a", "b"], dtype=object))),
        ]
    )
    plots = {
        "points": ggplot(table, aes(x="x", y="y")) + registry.geom_point(),
        "colour": ggplot(table, aes(x="x", y="y", colour="g")) + registry.geom_point(),
        "bars": ggplot(table, aes(x="g", y="y")) + registry.geom_col(),
        "log": (
            ggplot(table, aes(x="x", y="y")) + registry.geom_point() + registry.scale_x_log10()
        ),
        "coord": (
            ggplot(table, aes(x="x", y="y")) + registry.geom_point() + registry.coord_fixed(ratio=2)
        ),
        "line": ggplot(table, aes(x="x", y="y", group="g")) + registry.geom_line(),
    }
    expected = {
        "points": "55ada86e6227f762056a12f65f5cb6905b92266730571550c6b1dd034db4fa2d",
        "colour": "7f12c4a18a1211675fbccf9fc4a91d39754aed3c08270c4ab37b36015ec2b2ce",
        "bars": "002948383a9cc6de503b31cb7720d06f822b52604acd97adc9420d8bde79b9eb",
        "log": "dc85ef22fac590823248c5c800954afba3712d01d51805bd4d3528fe7e0e6787",
        "coord": "55ada86e6227f762056a12f65f5cb6905b92266730571550c6b1dd034db4fa2d",
        "line": "2df31ea85e8ca7d19889c98ece5ef3a9bf9cdd6b7203f3c1e0595d493042c2ec",
    }
    assert {name: build_digest(build_plot(plot)) for name, plot in plots.items()} == expected


# ---------------------------------------------------------------------------
# facet_wrap
# ---------------------------------------------------------------------------


def test_facet_wrap_orders_panels_by_levels_not_appearance() -> None:
    build = build_plot(wrap_plot(ncol=2))
    assert layout_records(build) == [
        {"PANEL": 1, "ROW": 1, "COL": 1, "SCALE_X": 1, "SCALE_Y": 1, "a": "q"},
        {"PANEL": 2, "ROW": 1, "COL": 2, "SCALE_X": 1, "SCALE_Y": 1, "a": "p"},
    ]
    # 原始行序不因分面而改变；PANEL 只是给每行贴上归属。
    assert build.layers[0].data.column("PANEL").values.tolist() == [
        "2",
        "2",
        "1",
        "1",
        "2",
        "2",
        "1",
        "1",
    ]


def test_facet_wrap_as_table_false_starts_at_bottom_left() -> None:
    build = build_plot(base_plot() + registry.facet_wrap(("c",), ncol=2, as_table=False))
    assert [(record["c"], record["ROW"], record["COL"]) for record in layout_records(build)] == [
        ("d", 2, 1),
        ("c", 2, 2),
        ("b", 1, 1),
        ("a", 1, 2),
    ]
    table = build.facet_table()
    assert table.layout.nrow == 2 and table.layout.ncol == 2
    assert {strip.text for strip in table.strips} == {"a", "b", "c", "d"}


def test_facet_wrap_dir_v_fills_columns_first() -> None:
    build = build_plot(base_plot() + registry.facet_wrap(("c",), ncol=2, dir="v"))
    assert [(record["c"], record["ROW"], record["COL"]) for record in layout_records(build)] == [
        ("d", 1, 1),
        ("c", 2, 1),
        ("b", 1, 2),
        ("a", 2, 2),
    ]


def test_facet_wrap_without_facets_falls_back_to_one_panel() -> None:
    build = build_plot(base_plot() + registry.facet_wrap())
    assert build.facet is not None
    assert build.layout is not None and build.layout.kind == "null"
    assert build.layout.npanels == 1


@pytest.mark.parametrize(("levels", "shape"), [(3, (1, 3)), (4, (2, 2)), (5, (2, 3)), (7, (3, 3))])
def test_facet_wrap_default_dims_follow_n2mfrow(levels: int, shape: tuple[int, int]) -> None:
    names = [f"g{index}" for index in range(levels)]
    table = ColumnTable(
        [
            ("x", Column("float", np.arange(float(levels)))),
            ("y", Column("float", np.arange(float(levels)))),
            ("a", categorical(names, tuple(names))),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y")) + registry.geom_point() + registry.facet_wrap(("a",))
    build = build_plot(plot)
    assert (build.layout.nrow, build.layout.ncol) == shape


def test_facet_wrap_drop_false_keeps_unused_combinations() -> None:
    build = build_plot(grid_plot(drop=False))
    # a 有 2 个水平、b 有 2 个水平：drop = FALSE 给 2 × 2；这里数据本来就有 4 组。
    assert build.layout is not None and build.layout.npanels == 4
    sparse = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("a", categorical(["p", "p", "q"], ("q", "p"))),
            ("b", categorical(["u", "v", "u"], ("v", "u"))),
        ]
    )
    plot = ggplot(sparse, aes(x="x", y="y")) + registry.geom_point()
    assert build_plot(plot + registry.facet_grid(("b",), ("a",), drop=False)).layout.npanels == 4
    assert build_plot(plot + registry.facet_grid(("b",), ("a",), drop=True)).layout.npanels == 3


def test_facet_wrap_accepts_a_string_or_an_aes_mapping() -> None:
    plain = build_plot(base_plot() + registry.facet_wrap("a", ncol=2))
    mapped = build_plot(base_plot() + registry.facet_wrap(aes(grp="a"), ncol=2))
    assert plain.layout.facet_vars == ("a",)
    assert mapped.layout.facet_vars == ("grp",)
    assert [(panel.row, panel.col, panel.facet_values) for panel in mapped.panels] == [
        (1, 1, {"grp": "q"}),
        (1, 2, {"grp": "p"}),
    ]


def test_facet_wrap_accepts_a_callable_labeller() -> None:
    def upper(labels: dict[str, list[str]]) -> dict[str, list[str]]:
        return {name: [value.upper() for value in values] for name, values in labels.items()}

    table = build_plot(wrap_plot(ncol=2, labeller=upper)).facet_table()
    assert [strip.text for strip in table.strips] == ["Q", "P"]


# ---------------------------------------------------------------------------
# facet_grid
# ---------------------------------------------------------------------------


def test_facet_grid_layout_is_row_major_by_levels() -> None:
    build = build_plot(grid_plot())
    assert layout_records(build) == [
        {"PANEL": 1, "ROW": 1, "COL": 1, "SCALE_X": 1, "SCALE_Y": 1, "b": "v", "a": "q"},
        {"PANEL": 2, "ROW": 1, "COL": 2, "SCALE_X": 1, "SCALE_Y": 1, "b": "v", "a": "p"},
        {"PANEL": 3, "ROW": 2, "COL": 1, "SCALE_X": 1, "SCALE_Y": 1, "b": "u", "a": "q"},
        {"PANEL": 4, "ROW": 2, "COL": 2, "SCALE_X": 1, "SCALE_Y": 1, "b": "u", "a": "p"},
    ]


def test_facet_grid_as_table_false_reverses_rows_only() -> None:
    build = build_plot(grid_plot(as_table=False))
    assert [
        (record["b"], record["a"], record["ROW"], record["COL"]) for record in layout_records(build)
    ] == [
        ("u", "q", 1, 1),
        ("u", "p", 1, 2),
        ("v", "q", 2, 1),
        ("v", "p", 2, 2),
    ]


def test_facet_grid_free_scales_are_shared_by_row_and_column() -> None:
    build = build_plot(grid_plot(scales="free"))
    assert build.layout is not None
    assert [(panel.scale_x, panel.scale_y) for panel in build.panels] == [
        (1, 1),
        (2, 1),
        (1, 2),
        (2, 2),
    ]
    x_ranges = [panel.panel_params.x_range for panel in build.panels]
    y_ranges = [panel.panel_params.y_range for panel in build.panels]
    assert x_ranges[0] == x_ranges[2]
    assert x_ranges[1] == x_ranges[3]
    assert x_ranges[0] != x_ranges[1]
    assert y_ranges[0] == y_ranges[1]
    assert y_ranges[2] == y_ranges[3]
    assert y_ranges[0] != y_ranges[2]
    # 同一列/行共用一份训练好的标度对象。
    assert build.panels[0].scales.x_set is build.panels[2].scales.x_set
    assert build.panels[0].scales.y_set is build.panels[1].scales.y_set


def test_facet_grid_fixed_scales_use_one_range_everywhere() -> None:
    build = build_plot(grid_plot())
    ranges = {(panel.panel_params.x_range, panel.panel_params.y_range) for panel in build.panels}
    assert len(ranges) == 1
    assert all(panel.scales.x_set is None and panel.scales.y_set is None for panel in build.panels)


def test_facet_grid_one_sided_layouts_keep_a_single_row_or_column() -> None:
    cols_only = build_plot(base_plot() + registry.facet_grid(cols=("a",)))
    assert (cols_only.layout.nrow, cols_only.layout.ncol) == (1, 2)
    assert [(panel.row, panel.col) for panel in cols_only.panels] == [(1, 1), (1, 2)]
    rows_only = build_plot(base_plot() + registry.facet_grid(rows=("b",)))
    assert (rows_only.layout.nrow, rows_only.layout.ncol) == (2, 1)
    assert [(panel.row, panel.col) for panel in rows_only.panels] == [(1, 1), (2, 1)]
    assert [strip.side for strip in rows_only.facet_table().strips] == ["right", "right"]


def test_free_scales_reject_coord_fixed_ratio() -> None:
    with pytest.raises(BuildError, match="coord_fixed"):
        build_plot(wrap_plot(scales="free") + registry.coord_fixed(ratio=2))


# ---------------------------------------------------------------------------
# 逐面板流水线：与单面板 build 逐列一致
# ---------------------------------------------------------------------------


def test_each_panel_runs_the_same_pipeline_as_a_standalone_build() -> None:
    # wrap 的自由刻度是「每个面板一套」；grid 的自由刻度按列/行共享（见上一条测试）。
    build = build_plot(wrap_plot(scales="free"))
    values = DATA.column("a").values
    for panel in build.panels:
        mask = np.array(
            [DATA.column("a").levels[code] == panel.facet_values["a"] for code in values]
        )
        subset = ColumnTable(
            [
                (
                    name,
                    Column(
                        col.kind, col.values[mask], levels=col.levels, na_mask=col.na_mask[mask]
                    ),
                )
                for name, col in zip(DATA.names, DATA.columns(), strict=True)
            ]
        )
        standalone = build_plot(ggplot(subset, aes(x="x", y="y")) + registry.geom_point())
        full = build.layers[0]
        panel_rows = np.flatnonzero(
            np.array([int(value) for value in full.positioned.column("PANEL").values])
            == panel.panel
        )
        for name in ("x", "y"):
            np.testing.assert_allclose(
                np.asarray(full.scaled.column(name).values)[panel_rows],
                np.asarray(standalone.layers[0].scaled.column(name).values),
            )
        assert panel.panel_params.x_range == pytest.approx(standalone.panel_params.x_range)
        assert panel.panel_params.y_range == pytest.approx(standalone.panel_params.y_range)


def test_facet_pipeline_handles_a_count_stat_per_panel() -> None:
    plot = ggplot(DATA, aes(x="a")) + registry.geom_bar() + registry.facet_wrap(("b",), ncol=2)
    build = build_plot(plot)
    data = build.layers[0].data
    assert data.column("PANEL").values.tolist() == ["1", "1", "2", "2"]
    assert data.column("count").values.tolist() == [2.0, 2.0, 2.0, 2.0]


# ---------------------------------------------------------------------------
# strip / gtable
# ---------------------------------------------------------------------------


def test_facet_table_has_panel_rectangles_and_strips() -> None:
    table = build_plot(grid_plot(scales="free")).facet_table()
    assert [panel[1:] for panel in table.panels] == [
        (2, 1, 2, 1),
        (2, 3, 2, 3),
        (4, 1, 4, 1),
        (4, 3, 4, 3),
    ]
    boxes = table.panel_boxes(20.0, 10.0)
    assert len({round(box.width_cm, 12) for box in boxes.values()}) == 1
    assert len({round(box.height_cm, 12) for box in boxes.values()}) == 1
    assert table.strip_for(1, "top") is not None
    assert table.strip_for(1, "top").text == "q"
    assert table.strip_for(1, "right").text == "v"
    assert [strip.text for strip in table.strips if strip.side == "top"] == ["q", "p"]


def test_facet_table_uses_labeller_and_theme_elements() -> None:
    plot = base_plot() + registry.facet_wrap(
        ("a",),
        ncol=2,
        labeller={"a": {"q": "Q level", "p": "P level"}},
    )
    table = build_plot(plot).facet_table()
    assert {strip.text for strip in table.strips} == {"Q level", "P level"}
    # strip 高度 = 文本高度 + 上下 margin（theme_grey 的 8.8pt / 4.4pt）。
    assert table.strip_height_cm == pytest.approx(0.6058, abs=5e-4)
    blank = build_plot(plot + theme(**{"strip.text": element_blank()})).facet_table()
    assert blank.strip_height_cm == 0.0


def test_facet_table_spacing_comes_from_panel_spacing() -> None:
    table = build_plot(wrap_plot(ncol=2)).facet_table()
    spacing = [str(unit) for unit in table.gtable.widths]
    assert spacing == ["1null", "5.5points", "1null"]
    taller = build_plot(
        wrap_plot(ncol=2) + theme(**{"panel.spacing.x": unit(0.5, "cm")})
    ).facet_table()
    assert [str(unit) for unit in taller.gtable.widths] == ["1null", "0.5cm", "1null"]


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def test_facet_grid_rejects_unimplemented_margins_and_free_space() -> None:
    with pytest.raises(FacetError, match="margins"):
        build_plot(grid_plot(margins=True))
    with pytest.raises(FacetError, match="space"):
        build_plot(grid_plot(space="free_x"))
    with pytest.raises(FacetError, match="只能出现在 rows 或 cols"):
        build_plot(base_plot() + registry.facet_grid(("a",), ("a",)))


def test_facet_wrap_rejects_unknown_dir_and_scales() -> None:
    with pytest.raises(FacetError, match="dir"):
        facet_from_component(registry.facet_wrap(("a",), dir="diagonal"))
    with pytest.raises(FacetError, match="scales"):
        facet_from_component(registry.facet_wrap(("a",), scales="free_colour"))


def test_facet_wrap_requires_every_facet_variable_in_some_layer() -> None:
    sparse = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0]))),
            ("y", Column("float", np.array([1.0, 2.0]))),
        ]
    )
    with pytest.raises(FacetError, match="分面变量"):
        build_plot(ggplot(sparse, aes(x="x", y="y")) + registry.geom_point() + wrap_plot().facet)


def test_panel_count_must_fit_the_requested_grid() -> None:
    with pytest.raises(FacetError, match="需要 2 个面板"):
        facet_from_component(registry.facet_wrap(("a",), ncol=1, nrow=1)).compute_layout(DATA)


def test_compute_aesthetics_checks_panel_length() -> None:
    from ggcore.build import compute_aesthetics

    plot = base_plot()
    with pytest.raises(BuildError, match="panels"):
        compute_aesthetics(plot, plot.layers[0], panels=np.array([1, 2], dtype=np.int64))
