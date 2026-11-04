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
from ggcore.axis import sec_axis
from ggcore.build import BuildError, build_plot
from ggcore.data import Column, ColumnTable
from ggcore.facet import FacetError, facet_from_component
from ggcore.geom.scene import axis_title_area, plot_layout
from ggcore.plot import ggplot, guides
from ggcore.theme import element_blank, element_rect, element_text, resolve_theme, theme
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


@pytest.mark.parametrize(
    ("levels", "shape"),
    [
        (3, (1, 3)),
        (4, (2, 2)),
        (5, (2, 3)),
        (7, (3, 3)),
        (10, (3, 4)),
        (13, (4, 4)),
        (17, (4, 5)),
        (20, (4, 5)),
    ],
)
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


def test_facet_grid_drop_true_keeps_empty_combinations() -> None:
    """SIL-694 #2：grid 是各维已观察水平的笛卡尔积，缺组合保留为空面板。"""
    sparse = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("a", categorical(["p", "p", "q"], ("q", "p"))),
            ("b", categorical(["u", "v", "u"], ("v", "u"))),
        ]
    )
    plot = ggplot(sparse, aes(x="x", y="y")) + registry.geom_point()
    build = build_plot(plot + registry.facet_grid(("b",), ("a",)))
    assert build.layout is not None
    assert (build.layout.nrow, build.layout.ncol, build.layout.npanels) == (2, 2, 4)
    # 列顺序跟 levels（q, p），不是出现顺序（p, q）；行同理（v, u）。
    assert [
        (record["b"], record["a"], record["ROW"], record["COL"]) for record in layout_records(build)
    ] == [
        ("v", "q", 1, 1),
        ("v", "p", 1, 2),
        ("u", "q", 2, 1),
        ("u", "p", 2, 2),
    ]
    # v × q 没有数据：面板仍然存在，只是 0 行。
    mapped = [int(value) for value in build.layers[0].positioned.column("PANEL").values]
    assert [mapped.count(panel) for panel in build.layout.panel_ids] == [0, 1, 1, 1]


def test_drop_false_keeps_unobserved_factor_levels() -> None:
    """SIL-694 #3：factor 有 a/b/c 三个 levels、数据只出现 a/b → 3 个面板。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("a", categorical(["a", "a", "b"], ("a", "b", "c"))),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y")) + registry.geom_point()
    wrap = build_plot(plot + registry.facet_wrap(("a",), drop=False))
    assert wrap.layout is not None and wrap.layout.npanels == 3
    assert [wrap.layout.label(panel, "a") for panel in wrap.layout.panel_ids] == ["a", "b", "c"]
    # drop = TRUE 仍然只保留观察到的组合。
    assert build_plot(plot + registry.facet_wrap(("a",), drop=True)).layout.npanels == 2
    grid = build_plot(plot + registry.facet_grid(None, ("a",), drop=False))
    assert grid.layout is not None and grid.layout.npanels == 3
    assert [grid.layout.label(panel, "a") for panel in grid.layout.panel_ids] == ["a", "b", "c"]


def test_facet_wrap_accepts_a_string_or_an_aes_mapping() -> None:
    plain = build_plot(base_plot() + registry.facet_wrap("a", ncol=2))
    mapped = build_plot(base_plot() + registry.facet_wrap(aes(grp="a"), ncol=2))
    assert plain.layout.facet_vars == ("a",)
    assert mapped.layout.facet_vars == ("grp",)
    assert [(panel.row, panel.col, panel.facet_values) for panel in mapped.panels] == [
        (1, 1, {"grp": "q"}),
        (1, 2, {"grp": "p"}),
    ]


def test_numeric_facet_layout_keeps_numeric_values_and_shows_labels() -> None:
    """SIL-694 #1：布局列保留 numeric，显示文本单独在 label_table。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("z", Column("float", np.array([2.0, 2.0, 1.0, 1.0]))),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y")) + registry.geom_point()
    build = build_plot(plot + registry.facet_wrap(("z",), ncol=2))
    layout = build.layout
    assert layout is not None
    column = layout.table.column("z")
    assert column.kind == "float"
    assert column.values.tolist() == [1.0, 2.0]
    assert not column.na_mask.any()
    assert [record["z"] for record in layout_records(build)] == [1.0, 2.0]
    assert [layout.label(panel, "z") for panel in layout.panel_ids] == ["1", "2"]
    assert [strip.text for strip in build.facet_table().strips] == ["1", "2"]
    assert build.layers[0].data.column("PANEL").values.tolist() == ["2", "2", "1", "1"]


def test_logical_facet_layout_keeps_bools_and_uses_r_labels() -> None:
    """SIL-694 #1：逻辑分面保留 bool，strip 文本是 TRUE/FALSE。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("g", Column("bool", np.array([True, True, False, False]))),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y")) + registry.geom_point()
    build = build_plot(plot + registry.facet_wrap(("g",), ncol=2))
    layout = build.layout
    assert layout is not None
    column = layout.table.column("g")
    assert column.kind == "bool"
    assert column.values.tolist() == [False, True]
    assert [layout.label(panel, "g") for panel in layout.panel_ids] == ["FALSE", "TRUE"]
    assert [strip.text for strip in build.facet_table().strips] == ["FALSE", "TRUE"]
    assert build.layers[0].data.column("PANEL").values.tolist() == ["2", "2", "1", "1"]


@pytest.mark.parametrize(
    ("column", "kind", "labels"),
    [
        (
            Column(
                "float",
                np.array([1.0, 1.0, 0.0, 0.0]),
                na_mask=np.array([False, False, True, True]),
            ),
            "float",
            ["1", "NA"],
        ),
        (
            Column(
                "str", np.array(["a", "a", "", ""]), na_mask=np.array([False, False, True, True])
            ),
            "str",
            ["a", "NA"],
        ),
    ],
)
def test_na_facet_values_get_their_own_panel(column: Column, kind: str, labels: list[str]) -> None:
    """SIL-694 #1：NA 是独立面板（不是消失），且与字符串 "NA" 不撞键。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("g", column),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y")) + registry.geom_point()
    build = build_plot(plot + registry.facet_wrap(("g",), ncol=2))
    layout = build.layout
    assert layout is not None and layout.npanels == 2
    assert layout.table.column("g").kind == kind
    assert layout.table.column("g").na_mask.tolist() == [False, True]
    assert layout.value(2, "g") is None
    assert [layout.label(panel, "g") for panel in layout.panel_ids] == labels
    assert [strip.text for strip in build.facet_table().strips] == labels
    assert build.layers[0].data.column("PANEL").values.tolist() == ["1", "1", "2", "2"]


def test_na_facet_value_does_not_collide_with_a_literal_na_string() -> None:
    """真正的缺失值（None）与字符串 "NA" 是两个不同的分面水平。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            (
                "g",
                Column(
                    "str",
                    np.array(["NA", "NA", "", ""]),
                    na_mask=np.array([False, False, True, True]),
                ),
            ),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y")) + registry.geom_point()
    build = build_plot(plot + registry.facet_wrap(("g",)))
    layout = build.layout
    assert layout is not None and layout.npanels == 2
    assert [layout.label(panel, "g") for panel in layout.panel_ids] == ["NA", "NA"]
    assert build.layers[0].data.column("PANEL").values.tolist() == ["1", "1", "2", "2"]


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


def test_init_scales_allocates_one_slot_per_row_or_column() -> None:
    free_plot = grid_plot(scales="free")
    free = facet_from_component(free_plot.facet)
    layout = free.compute_layout(DATA)
    pool = free.init_scales(layout, free_plot.scales)
    assert pool.x_sets is not None and len(pool.x_sets) == 2
    assert pool.y_sets is not None and len(pool.y_sets) == 2
    assert pool.for_panel(1).x_set is pool.for_panel(3).x_set
    assert pool.for_panel(1).y_set is pool.for_panel(2).y_set
    fixed = facet_from_component(grid_plot().facet)
    fixed_pool = fixed.init_scales(fixed.compute_layout(DATA), {})
    assert fixed_pool.x_sets is None and fixed_pool.y_sets is None


def test_facet_grid_one_sided_layouts_keep_a_single_row_or_column() -> None:
    cols_only = build_plot(base_plot() + registry.facet_grid(cols=("a",)))
    assert (cols_only.layout.nrow, cols_only.layout.ncol) == (1, 2)
    assert [(panel.row, panel.col) for panel in cols_only.panels] == [(1, 1), (1, 2)]
    rows_only = build_plot(base_plot() + registry.facet_grid(rows=("b",)))
    assert (rows_only.layout.nrow, rows_only.layout.ncol) == (2, 1)
    assert [(panel.row, panel.col) for panel in rows_only.panels] == [(1, 1), (2, 1)]
    assert [strip.side for strip in rows_only.facet_table().strips] == ["right", "right"]


_FREE_COORD_FIXED_REJECTS = {
    "wrap_free": lambda: wrap_plot(scales="free"),
    "grid_free": lambda: grid_plot(scales="free"),
    "grid_free_x_space_free_x": lambda: grid_plot(scales="free_x", space="free_x"),
    "grid_free_y_space_free_y": lambda: grid_plot(scales="free_y", space="free_y"),
    "grid_free_space_free_x": lambda: grid_plot(scales="free", space="free_x"),
    "grid_free_space_free_y": lambda: grid_plot(scales="free", space="free_y"),
    "wrap_space_free_x": lambda: wrap_plot(space="free_x", scales="free"),
    "wrap_space_free_y": lambda: wrap_plot(space="free_y", scales="free"),
}


@pytest.mark.parametrize("name", sorted(_FREE_COORD_FIXED_REJECTS))
def test_free_scales_with_coord_fixed_is_rejected(name: str) -> None:
    """SIL-759：R 4.0.3 只有 grid + `space = "free"` 允许自由刻度配 ratio。"""
    with pytest.raises(BuildError, match="coord_fixed"):
        build_plot(_FREE_COORD_FIXED_REJECTS[name]() + registry.coord_fixed(ratio=2))


@pytest.mark.parametrize("scales", ["free", "free_x", "free_y"])
def test_grid_space_free_allows_free_scales_with_coord_fixed(scales: str) -> None:
    """两维都 free 时 R 4.0.3 接受自由刻度 + ratio（`respect = TRUE`）。"""
    build = build_plot(grid_plot(scales=scales, space="free") + registry.coord_fixed(ratio=2))
    table = build.facet_table()
    assert table.respect is True
    assert table.aspect_ratio == pytest.approx(2.0)


def test_space_free_with_coord_fixed_folds_ratio_into_row_weights() -> None:
    """SIL-759：`heights` = 行范围差 × |ratio|，面板高/宽 = ratio × yspan / xspan。"""
    build = build_plot(grid_plot(scales="free", space="free") + registry.coord_fixed(ratio=2))
    table = build.facet_table()
    assert table.respect is True

    def span(panel, axis: str) -> float:
        params = panel.panel_params
        low, high = params.x_range if axis == "x" else params.y_range
        return high - low

    x_spans = [span(next(p for p in build.panels if p.col == col), "x") for col in (1, 2)]
    y_spans = [span(next(p for p in build.panels if p.row == row), "y") for row in (1, 2)]
    assert table.width_weights == pytest.approx(tuple(x_spans))
    assert table.height_weights == pytest.approx(tuple(2.0 * value for value in y_spans))

    layout = plot_layout(build)
    for panel in build.panels:
        box = layout.panel_boxes[panel.panel]
        expected = 2.0 * span(panel, "y") / span(panel, "x")
        assert box.height_cm / box.width_cm == pytest.approx(expected, rel=1e-9)


def test_space_free_fixed_scales_aspect_matches_r_values() -> None:
    """固定刻度 + `space = "free"` + `coord_fixed(2)`：行权重全是 19.8（R 值）。"""
    build = build_plot(grid_plot(space="free") + registry.coord_fixed(2))
    table = build.facet_table()
    params = build.panels[0].panel_params
    x_span = params.x_range[1] - params.x_range[0]
    y_span = params.y_range[1] - params.y_range[0]
    assert table.width_weights == pytest.approx((x_span,) * 2)
    assert table.height_weights == pytest.approx((2.0 * y_span,) * 2)
    boxes = list(plot_layout(build).panel_boxes.values())
    assert all(
        box.height_cm / box.width_cm == pytest.approx(2.0 * y_span / x_span, rel=1e-9)
        for box in boxes
    )


@pytest.mark.parametrize("space", ["free", "free_x", "free_y"])
def test_polar_with_space_free_raises(space: str) -> None:
    """R 4.0.3 自己在 `init_gtable()` 里报 `values must be length 1`；这里同口径报错。"""
    facet = (
        registry.facet_grid(("b",), ("a",), space=space)
        if space == "free"
        else registry.facet_wrap(("a",), space=space)
    )
    with pytest.raises(BuildError, match="space"):
        build_plot(base_plot() + facet + registry.coord_polar())


def test_grid_right_strip_puts_the_last_row_variable_next_to_the_panel() -> None:
    """SIL-759：R `build_strip(horizontal = FALSE)` 先 rev() 行变量，b 贴着面板。"""
    build = build_plot(base_plot() + registry.facet_grid(("a", "b"), labeller="label_both"))
    table = build.facet_table()
    rights = [strip for strip in table.strips if strip.side == "right"]
    assert rights
    for strip in rights:
        assert [part.var for part in strip.parts] == ["b", "a"]
        assert strip.parts[0].text.startswith("b: ")
        assert strip.parts[1].text.startswith("a: ")
    # 顶部（列变量）顺序不反转：第一个变量在上，最后一个贴面板。
    top = build_plot(
        base_plot() + registry.facet_grid(cols=("a", "b"), labeller="label_both")
    ).facet_table()
    strip = top.strip_for(1, "top")
    assert strip is not None
    assert [part.var for part in strip.parts] == ["a", "b"]


def test_strip_outside_falls_back_inside_when_a_secondary_axis_is_present() -> None:
    """SIL-759：右侧次轴带会把 `outside` strip 压住；有次轴时回退 inside。"""
    plot = (
        grid_plot()
        + registry.scale_y_continuous(sec_axis=sec_axis(lambda value: value * 2))
        + theme(**{"strip.placement.y": "outside"})
    )
    build = build_plot(plot)
    layout = plot_layout(build)
    table = build.facet_table(right_inside=True)
    assert layout.secondary_y is True
    assert table.right_placement == "inside"
    assert layout.right_strip_band is None
    # strip 落在 gtable 列里：右缘不超过面板区右边界；次轴带在面板区之外。
    placement = next(row for row in table.gtable.layout if row.name.startswith("strip-r"))
    sizes = table.gtable.resolve(layout.panel_area.width_cm, layout.panel_area.height_cm)
    cell = table.gtable.region_box(
        placement.t,
        placement.l,
        placement.b,
        placement.r,
        width_cm=layout.panel_area.width_cm,
        height_cm=layout.panel_area.height_cm,
        sizes=sizes,
    )
    strip_right = layout.panel_area.x_cm + cell.x_cm + cell.width_cm
    assert strip_right <= layout.panel_area.right + 1e-9
    assert layout.panel_area.right + layout.y_axis_right_cm <= layout.width_cm + 1e-9
    # 没有次轴时仍是 outside（不进 gtable 列，另留 band）。
    plain = plot_layout(build_plot(grid_plot() + theme(**{"strip.placement.y": "outside"})))
    assert plain.right_strip_band is not None


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
    assert table.strip_height_cm == pytest.approx(0.5870, abs=5e-4)
    blank = build_plot(plot + theme(**{"strip.text": element_blank()})).facet_table()
    assert blank.strip_height_cm == 0.0


def test_strip_row_height_uses_the_device_text_line_caliber() -> None:
    """有 metrics（真实渲染）时 strip 行高 = `TEXT_LINE_EM`，与 R 的 16.66pt 对齐。

    R 的 strip 行 = `stringHeight()`（cap height）+ `font_descent()` + 上下 margin；
    本项目的设备口径就是 `TEXT_LINE_EM`（0.894em，见 docs/notes/guide.md）。
    8.8pt strip → 7.87pt 文字 + 8.8pt margin = 16.67pt。早先用
    `Metrics.strheight()`（只有 cap height，0.735em）是 15.25pt，分面的面板行
    因此比 R 高 1.4pt、竖向图例中心偏 0.7pt（SIL-725）。
    """

    class Metrics:
        def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
            del font
            return 0.5 * float(fontsize) * float(cex) * len(text) / 72.0

        def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
            del text, font
            return 0.735 * float(fontsize) * float(cex) / 72.0

    plot = base_plot() + registry.facet_wrap(("a",), ncol=2)
    table = build_plot(plot).facet_table(metrics=Metrics())
    strip_pt = table.strip_height_cm * 72.0 / 2.54
    assert strip_pt == pytest.approx(16.67, abs=0.05)
    # 无度量时仍是 M1-6 的历史口径（0.955em），两套口径各自的用途都钉住。
    assert build_plot(plot).facet_table().strip_height_cm == pytest.approx(0.5870, abs=5e-4)


def test_facet_table_spacing_comes_from_panel_spacing() -> None:
    table = build_plot(wrap_plot(ncol=2)).facet_table()
    spacing = [str(unit) for unit in table.gtable.widths]
    assert spacing == ["1null", "5.5points", "1null"]
    taller = build_plot(
        wrap_plot(ncol=2) + theme(**{"panel.spacing.x": unit(0.5, "cm")})
    ).facet_table()
    assert [str(unit) for unit in taller.gtable.widths] == ["1null", "0.5cm", "1null"]


def test_facet_wrap_multirow_puts_a_strip_above_every_panel_row() -> None:
    """SIL-694 #4：3 行面板 → strip / panel / 间距 / strip / panel / 间距 / strip / panel。"""
    names = [f"g{index}" for index in range(7)]
    table = ColumnTable(
        [
            ("x", Column("float", np.arange(7.0))),
            ("y", Column("float", np.arange(7.0))),
            ("g", categorical(names, tuple(names))),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y")) + registry.geom_point() + registry.facet_wrap(("g",))
    facet_table = build_plot(plot).facet_table()
    strip_cm = facet_table.strip_height_cm
    heights = [str(item) for item in facet_table.gtable.heights]
    assert heights[0].endswith("cm")
    assert float(heights[0][:-2]) == pytest.approx(strip_cm)
    assert heights == [heights[0], "1null", "5.5points"] * 2 + [heights[0], "1null"]
    assert [panel[1] for panel in facet_table.panels] == [2, 2, 2, 5, 5, 5, 8]
    placements = {row.name: row for row in facet_table.gtable.layout}
    row_of_panel = {panel: top for panel, top, _, _, _ in facet_table.panels}
    assert len([strip for strip in facet_table.strips if strip.side == "top"]) == 7
    for strip in facet_table.strips:
        if strip.side == "top":
            assert placements[strip.name].t == row_of_panel[strip.panel] - 1


def test_grid_right_strip_follows_strip_text_y_and_strip_background() -> None:
    """SIL-694 #6：右 strip 尺寸读 strip.text.y；strip.background 真正参与。"""
    base = build_plot(grid_plot()).facet_table()
    assert base.strip_width_cm == pytest.approx(0.5870, abs=5e-4)
    taller = build_plot(
        grid_plot() + theme(**{"strip.text.y": element_text(size=20)})
    ).facet_table()
    # R（ggplot2 4.0.3 + svglite）同一条主题改法是 0.9414906cm；
    # strip.text.y 默认 angle=-90，列宽 = 行高（20pt × 0.8945）+ 左右 margin。
    assert taller.strip_width_cm == pytest.approx(0.9415, rel=0.02)
    assert taller.strip_height_cm == base.strip_height_cm

    assert base.strip_for(1, "top").fill == "#D9D9D9"
    assert base.strip_for(1, "right").fill == "#D9D9D9"
    blank = build_plot(grid_plot() + theme(**{"strip.background": element_blank()})).facet_table()
    assert [strip.fill for strip in blank.strips] == [None] * len(blank.strips)
    red = build_plot(
        grid_plot() + theme(**{"strip.background.y": element_rect(fill="#FF0000")})
    ).facet_table()
    assert red.strip_for(1, "right").fill == "#FF0000"
    assert red.strip_for(1, "top").fill == "#D9D9D9"


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def test_facet_grid_rejects_duplicate_variables_across_rows_and_cols() -> None:
    with pytest.raises(FacetError, match="只能出现在 rows 或 cols"):
        build_plot(base_plot() + registry.facet_grid(("a",), ("a",)))
    # margins / space 的合法值已实现（见 margins / space 两组测试）。
    build_plot(grid_plot(margins=True))
    build_plot(grid_plot(space="free_x"))


def test_facet_wrap_space_is_validated_instead_of_silently_ignored() -> None:
    """SIL-694 #5 的校验仍在：非法值点名报错；上游不接受 facet_wrap(space="free")。"""
    with pytest.raises(FacetError, match="space 只能是"):
        facet_from_component(registry.facet_wrap(("a",), space="banana"))
    with pytest.raises(FacetError, match="space 只能是"):
        facet_from_component(registry.facet_wrap(("a",), space="free"))
    assert facet_from_component(registry.facet_wrap(("a",), space="fixed")).space == "fixed"


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


# ---------------------------------------------------------------------------
# margins / space = "free" / strip.placement（M2-3）
# ---------------------------------------------------------------------------


def panel_row_counts(build) -> dict[int, int]:
    """每个面板的数据行数（`scaled` 表里的 PANEL 列计数）。"""
    column = build.layers[0].scaled.column("PANEL")
    counts: dict[int, int] = {}
    for value in np.asarray(column.values):
        panel = int(value)
        counts[panel] = counts.get(panel, 0) + 1
    return counts


def test_facet_grid_margins_add_all_panels_and_duplicate_rows() -> None:
    """margins = TRUE：3×3（含 (all) 行 / 列），一行数据同时进普通与 margin 面板。"""
    build = build_plot(grid_plot(margins=True))
    layout = build.layout
    assert layout is not None
    assert (layout.nrow, layout.ncol) == (3, 3)
    assert [layout.label(panel, "a") for panel in layout.panel_ids] == [
        "q",
        "p",
        "(all)",
        "q",
        "p",
        "(all)",
        "q",
        "p",
        "(all)",
    ]
    assert [layout.label(panel, "b") for panel in layout.panel_ids] == [
        "v",
        "v",
        "v",
        "u",
        "u",
        "u",
        "(all)",
        "(all)",
        "(all)",
    ]
    counts = panel_row_counts(build)
    # b=v 的 4 行覆盖 a=p/p/q/q → 每个交叉格 2 行；margin 面板吃掉整行/整列，
    # (all,all) 是全部 8 行。
    assert counts == {1: 2, 2: 2, 3: 4, 4: 2, 5: 2, 6: 4, 7: 4, 8: 4, 9: 8}


def test_facet_grid_margins_single_variable_adds_one_dimension() -> None:
    build = build_plot(grid_plot(margins="a"))
    layout = build.layout
    assert layout is not None
    assert (layout.nrow, layout.ncol) == (2, 3)
    assert [layout.label(panel, "a") for panel in layout.panel_ids] == [
        "q",
        "p",
        "(all)",
        "q",
        "p",
        "(all)",
    ]
    assert [layout.label(panel, "b") for panel in layout.panel_ids] == [
        "v",
        "v",
        "v",
        "u",
        "u",
        "u",
    ]


def test_facet_grid_margins_reject_unknown_variables() -> None:
    with pytest.raises(FacetError, match="margins"):
        facet_from_component(registry.facet_grid(("b",), ("a",), margins="nope"))


def test_facet_wrap_space_free_forces_one_row_or_column() -> None:
    """上游：space = "free_x" 强制一行（忽略 ncol）；free_y 强制一列。"""
    wrap_x = facet_from_component(registry.facet_wrap(("a",), ncol=2, space="free_x"))
    assert (wrap_x.nrow, wrap_x.ncol) == (1, None)
    build = build_plot(base_plot() + registry.facet_wrap(("a",), space="free_x"))
    layout = build.layout
    assert layout is not None and (layout.nrow, layout.ncol) == (1, 2)
    wrap_y = facet_from_component(registry.facet_wrap(("a",), space="free_y"))
    assert (wrap_y.nrow, wrap_y.ncol) == (None, 1)


def test_facet_wrap_rejects_space_free() -> None:
    """facet_wrap 的上游取值只有 fixed / free_x / free_y。"""
    with pytest.raises(FacetError, match="space 只能是"):
        facet_from_component(registry.facet_wrap(("a",), space="free"))


def test_space_free_weights_follow_panel_ranges() -> None:
    """space = "free" 的 null 权重 = 该列 / 行面板的范围差。"""
    table = build_plot(grid_plot(space="free")).facet_table()
    # 固定刻度：所有面板共用一套范围 → 权重相同（不是 1，R 也读范围差）。
    assert table.width_weights[0] == pytest.approx(table.width_weights[1])
    free = build_plot(grid_plot(scales="free", space="free")).facet_table()
    # x 按列、y 按行：q 组 x 1..3+10..30，p 组 x 2..4+20..40。
    assert all(weight > 0 for weight in free.width_weights)
    assert all(weight > 0 for weight in free.height_weights)


def test_strip_placement_outside_reserves_a_band_above_the_axes() -> None:
    """`strip.placement = "outside"`：strip 块移到轴带之外，面板区让出同高度。"""
    inside = plot_layout(build_plot(wrap_plot(ncol=2)))
    outside_build = build_plot(wrap_plot(ncol=2) + theme(**{"strip.placement": "outside"}))
    outside = plot_layout(outside_build)
    table = outside_build.facet_table()
    assert outside.top_strip_band is not None
    assert outside.top_strip_band.height_cm == pytest.approx(table.strip_height_cm)
    assert inside.panel_area.height_cm - outside.panel_area.height_cm == pytest.approx(
        table.strip_height_cm
    )
    # strip 不再占 gtable 行：面板区里只剩 1null。
    assert [str(item) for item in table.gtable.heights] == ["1null"]


def test_polar_facet_panels_stay_square_and_strips_sit_above_them() -> None:
    """polar × facet：`aspect = 1` 作用在每个面板单元格上，strip 仍在面板上方。"""
    polar = build_plot(base_plot() + registry.coord_polar() + registry.facet_wrap(("a",), ncol=2))
    layout = plot_layout(polar)
    boxes = list(layout.panel_boxes.values())
    assert len(boxes) == 2
    for box in boxes:
        assert box.width_cm == pytest.approx(box.height_cm, rel=1e-6)
    table = polar.facet_table()
    for strip in table.strips:
        if strip.side != "top":
            continue
        placement = next(row for row in table.gtable.layout if row.name == strip.name)
        panel_top = next(top for panel, top, _, _, _ in table.panels if panel == strip.panel)
        assert placement.t == panel_top - 1


def test_grid_switch_moves_strips_to_the_bottom_and_left() -> None:
    """`facet_grid(switch = "both")`：列 strip 到面板下方、行 strip 到左侧。

    上游 `FacetGrid$attach_strips()` 换边后按边取元素
    （`strip.text.x.bottom` / `strip.text.y.left`），y strip 的角度从 -90 翻成 90。
    """
    switched = build_plot(base_plot() + registry.facet_grid(("a",), ("b",), switch="both"))
    table = switched.facet_table()
    sides = {(strip.panel, strip.side) for strip in table.strips}
    assert "top" not in {side for _, side in sides}
    assert "right" not in {side for _, side in sides}
    assert set(table.inside_strip_sides) == {"bottom", "left"}
    for strip in table.strips:
        placement = next(row for row in table.gtable.layout if row.name == strip.name)
        panel_top = next(top for panel, top, _, _, _ in table.panels if panel == strip.panel)
        if strip.side == "bottom":
            assert placement.t > panel_top
        else:
            assert placement.l == 1
    theme_ = resolve_theme(switched.theme)
    assert float(theme_.get("strip.text.y.left").angle) == pytest.approx(90.0)
    assert float(theme_.get("strip.text.y").angle) == pytest.approx(-90.0)


def test_axis_titles_span_panel_cells_not_strips() -> None:
    """SIL-817：行 strip 自带一列，xlab / ylab 的中心不能把它算进去。

    R 的 xlab / ylab 行只跨 panel 列 / 行；`facet_grid(rows = ...)` 的 strip 在
    右侧时，用 `panel_area` 居中会把 x 标题右移半个 strip 宽（上游快照
    `align-facet-labels-facets-horizontal` 实测 27pt）。
    """
    build = build_plot(base_plot() + registry.facet_grid(("a", "b")))
    layout = plot_layout(build, width_in=6.0, height_in=4.0)
    area = axis_title_area(layout)
    table = build.facet_table()
    assert table.strip_width_cm > 0
    assert area.right < layout.panel_area.right - table.strip_width_cm * 0.5
    boxes = list(layout.panel_boxes.values())
    assert area.x_cm == pytest.approx(min(box.x_cm for box in boxes))
    assert area.right == pytest.approx(max(box.right for box in boxes))
    assert area.y_cm == pytest.approx(min(box.y_cm for box in boxes))
    assert area.top == pytest.approx(max(box.top for box in boxes))


def test_facet_strip_cells_share_the_panel_table() -> None:
    """strip 单元格必须和 panel 用同一张 facet gtable（SIL-816）。

    带行间 / 列间轴带（`axes = "all"`）时，另建一张不带 `axis_*_cm` 的表会让
    strip 比 panel 宽出一条轴带宽、并整体上移。
    """
    from ggcore.geom.scene import _strip_box
    from ggcore.units import UnitContext

    build = build_plot(
        wrap_plot(axes="all")
        + guides(**{"x": "axis", "y": "axis", "x.sec": "axis", "y.sec": "axis"})
    )
    layout = plot_layout(build, width_in=10, height_in=8)
    facet_table = layout.facet_table
    assert facet_table is not None
    sizes = facet_table.gtable.resolve(
        layout.panel_area.width_cm,
        layout.panel_area.height_cm,
        ctx=UnitContext(),
    )
    panel_widths = {round(box.width_cm, 6) for box in layout.panel_boxes.values()}
    for strip in facet_table.strips:
        box = _strip_box(facet_table, strip, layout, layout.panel_area, sizes)
        assert box is not None
        assert round(box.width_cm, 6) in panel_widths
