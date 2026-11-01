"""gtable 的行为测试（SIL-593）。

数值对拍在 `tests/test_gtable_r_parity.py`；这里守 R 对拍夹具覆盖不到的
API 语义：构造参数、z 排序、行列插入位置、padding 四边顺序、查询、嵌套，
以及 R 会算成 NaN / 报错、gg4py 明确定义的那些边界。
"""

from __future__ import annotations

import math

import pytest

from ggcore.gtable import (
    GTable,
    Layout,
    gtable,
    gtable_add_cols,
    gtable_add_grob,
    gtable_add_padding,
    gtable_add_rows,
    gtable_height,
    gtable_layout,
    gtable_width,
    is_gtable,
)
from ggcore.units import Unit, UnitContext, convert_width, unit, unit_c

CM = "cm"


def widths_cm(table: GTable, width_cm: float = 10, height_cm: float = 10) -> list[float]:
    return list(table.resolve(width_cm, height_cm).widths_cm)


def heights_cm(table: GTable, width_cm: float = 10, height_cm: float = 10) -> list[float]:
    return list(table.resolve(width_cm, height_cm).heights_cm)


def nulls(*amounts: float) -> Unit:
    return unit(list(amounts), "null")


# ---------------------------------------------------------------------------
# 构造
# ---------------------------------------------------------------------------


def test_constructor_takes_row_and_column_units() -> None:
    table = gtable(widths=unit([1, 2], "null"), heights=unit([1, 2, 3], "null"))
    assert (table.nrow, table.ncol) == (3, 2)
    assert table.name == "layout"
    assert is_gtable(table) and not is_gtable(object())


def test_rows_and_cols_are_the_same_parameters() -> None:
    rows, cols = unit(1, "cm"), unit(2, "cm")
    assert gtable(rows=rows, cols=cols) == gtable(heights=rows, widths=cols)
    with pytest.raises(TypeError):
        gtable(widths=cols, cols=cols)
    with pytest.raises(TypeError):
        gtable(heights=rows, rows=rows)


def test_units_may_be_given_as_a_list() -> None:
    table = gtable(widths=[unit(1, "cm"), unit(2, "cm")], heights=[unit(1, "null")])
    assert widths_cm(table) == pytest.approx([1.0, 2.0])
    with pytest.raises(TypeError):
        gtable(widths=[1, 2], heights=unit(1, "null"))  # type: ignore[list-item]


def test_rownames_and_colnames_must_match_the_dimensions() -> None:
    table = gtable(widths=unit(1, "null"), heights=unit(1, "null"), rownames=["r"], colnames=["c"])
    assert (table.rownames, table.colnames) == (("r",), ("c",))
    with pytest.raises(ValueError):
        gtable(widths=unit([1, 1], "null"), heights=unit(1, "null"), colnames=["only"])


def test_layout_spec_is_the_grid_layout_of_the_table() -> None:
    table = gtable(widths=nulls(1, 2), heights=nulls(1), respect=True)
    layout = gtable_layout(table)
    assert isinstance(layout, Layout)
    assert (layout.nrow, layout.ncol) == (1, 2)
    assert layout.respect is True
    assert layout.widths == table.widths and layout.heights == table.heights
    with pytest.raises(TypeError):
        gtable_layout(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# null 分配
# ---------------------------------------------------------------------------


def test_pure_null_splits_the_space_by_weight() -> None:
    table = gtable(widths=unit([1, 3], "null"), heights=unit([1, 1], "null"))
    assert widths_cm(table) == pytest.approx([2.5, 7.5])
    assert heights_cm(table) == pytest.approx([5.0, 5.0])


def test_zero_weight_null_columns_do_not_divide_by_zero() -> None:
    """`0null,0null`：权重和为 0，两列都是 0（R 实测 0,0）。"""
    table = gtable(widths=nulls(0, 0), heights=nulls(1))
    assert widths_cm(table) == [0.0, 0.0]
    assert heights_cm(table) == [10.0]


def test_zero_weight_null_next_to_a_real_null() -> None:
    table = gtable(widths=nulls(0, 1), heights=nulls(1))
    assert widths_cm(table) == [0.0, 10.0]


def test_null_mixed_into_a_compound_element_counts_as_fixed() -> None:
    """`1null + 2cm` 不是纯 null：按 2cm 固定，剩下的 8cm 归真正的 null 列。"""
    widths = unit_c(unit(1, "null") + unit(2, "cm"), unit(1, "null"))
    table = gtable(widths=widths, heights=nulls(1))
    assert widths_cm(table) == pytest.approx([2.0, 8.0])


def test_fixed_only_layout_keeps_its_sizes_and_ignores_the_leftover() -> None:
    table = gtable(widths=unit([2, 3], "cm"), heights=unit([1, 4], "cm"))
    sizes = table.resolve(10, 10)
    assert sizes.widths_cm == pytest.approx((2.0, 3.0))
    assert sizes.heights_cm == pytest.approx((1.0, 4.0))
    assert (sizes.total_width_cm, sizes.total_height_cm) == pytest.approx((5.0, 5.0))


def test_fixed_part_wider_than_the_viewport_starves_the_null_columns() -> None:
    table = gtable(widths=unit_c(unit(6, "cm"), unit(6, "cm"), unit(1, "null")), heights=nulls(1))
    assert widths_cm(table) == pytest.approx([6.0, 6.0, 0.0])


def test_zero_viewport_gives_zero_sizes() -> None:
    table = gtable(widths=nulls(1), heights=nulls(1))
    assert table.resolve(0, 0) == table.resolve(0, 0)
    assert widths_cm(table, 0, 0) == [0.0]
    assert heights_cm(table, 0, 0) == [0.0]


def test_no_columns_means_no_width_allocation() -> None:
    """0 列时直接跳过宽度分配（不特判除零），高度照常解析。"""
    table = gtable(heights=unit([1, 3], "null"))
    sizes = table.resolve(10, 10)
    assert sizes.widths_cm == ()
    assert sizes.heights_cm == pytest.approx((2.5, 7.5))


def test_empty_table_resolves_to_nothing() -> None:
    table = gtable()
    assert (table.nrow, table.ncol) == (0, 0)
    assert table.resolve(10, 10).widths_cm == ()
    # R 4.5.3 造不出空 gtable；ggcore 的空表宽度求值是 0。
    assert list(convert_width(gtable_width(table), CM, ctx=UnitContext())) == [0.0]
    assert list(convert_width(gtable_height(table), CM, ctx=UnitContext())) == [0.0]


def test_negative_viewport_is_rejected() -> None:
    table = gtable(widths=nulls(1), heights=nulls(1))
    with pytest.raises(ValueError):
        table.resolve(-1, 10)


def test_respect_makes_null_width_and_height_units_equal() -> None:
    table = gtable(widths=nulls(1, 1), heights=nulls(1), respect=True)
    sizes = table.resolve(10, 10)
    assert sizes.widths_cm == pytest.approx((5.0, 5.0))
    assert sizes.heights_cm == pytest.approx((5.0,))


def test_respect_with_zero_weight_null_heights_falls_back_to_width_allocation() -> None:
    """`sumHeight == 0` 的特例：受 respect 约束的宽列按宽度自己分（R 同）。"""
    table = gtable(widths=nulls(0, 1), heights=nulls(0, 0), respect=True)
    sizes = table.resolve(10, 10)
    assert sizes.widths_cm == pytest.approx((0.0, 10.0))
    assert sizes.heights_cm == pytest.approx((0.0, 0.0))


def test_respect_with_all_weights_zero_gives_zero_instead_of_nan() -> None:
    """R 这里是 0/0 = NaN 并报 non-finite viewport；gg4py 定义成 0。"""
    table = gtable(widths=nulls(0, 0), heights=nulls(0, 0), respect=True)
    sizes = table.resolve(10, 10)
    assert sizes.widths_cm == (0.0, 0.0)
    assert sizes.heights_cm == (0.0, 0.0)


def test_non_null_units_use_the_unit_system() -> None:
    table = gtable(
        widths=unit_c(unit(1, "lines"), unit(2, "pt"), unit(5, "mm")),
        heights=unit(1, "null"),
    )
    # 1 line = 12pt * 1.2 / 72 = 0.2 in；2 pt = 2/72.27 in；5 mm = 0.5 cm。
    assert widths_cm(table) == pytest.approx([0.508, 0.0702919607, 0.5], rel=1e-9)


# ---------------------------------------------------------------------------
# 位置 / span
# ---------------------------------------------------------------------------


def test_cells_are_centred_when_there_is_leftover_space() -> None:
    table = gtable(widths=unit([2, 3], "cm"), heights=unit([1, 4], "cm"))
    first = table.region_box(1, 1, width_cm=10, height_cm=10)
    assert (first.x_cm, first.y_cm) == pytest.approx((2.5, 6.5))
    assert (first.width_cm, first.height_cm) == pytest.approx((2.0, 1.0))


def test_justification_moves_the_whole_layout() -> None:
    table = gtable(widths=unit([2, 3], "cm"), heights=unit([1, 4], "cm"))
    top_left = table.region_box(1, 1, width_cm=10, height_cm=10, hjust=0.0, vjust=1.0)
    assert (top_left.x_cm, top_left.y_cm) == pytest.approx((0.0, 9.0))


def test_span_box_is_the_sum_of_the_spanned_cells() -> None:
    table = gtable(widths=unit_c(unit(4, "cm"), unit(1, "null")), heights=nulls(1))
    span = table.region_box(1, 1, 1, 2, width_cm=10, height_cm=10)
    assert (span.width_cm, span.height_cm) == pytest.approx((10.0, 10.0))
    assert (span.x_cm, span.y_cm) == pytest.approx((0.0, 0.0))


def test_region_box_rejects_indices_outside_the_layout() -> None:
    table = gtable(widths=nulls(1, 1), heights=nulls(1))
    with pytest.raises(ValueError):
        table.region_box(1, 3, width_cm=10, height_cm=10)
    with pytest.raises(ValueError):
        table.region_box(2, 1, width_cm=10, height_cm=10)
    with pytest.raises(ValueError):
        table.region_box(1, 2, 1, 1, width_cm=10, height_cm=10)


# ---------------------------------------------------------------------------
# add_grob：z / 名字 / 下标
# ---------------------------------------------------------------------------


def test_add_grob_appends_the_grob_with_a_default_name() -> None:
    table = gtable_add_grob(gtable(widths=nulls(1), heights=nulls(1)), object(), t=1, l=1)
    assert table.placements()[0].name == "layout"
    assert table.placements("layout") == (table.placements()[0],)
    assert table.grob("layout") is table.grobs[0]
    with pytest.raises(KeyError):
        table.grob("missing")


def test_add_grob_places_infinities_outside_the_existing_z_range() -> None:
    table = gtable(widths=nulls(1), heights=nulls(1))
    table = gtable_add_grob(table, object(), t=1, l=1, z=5, name="mid")
    table = gtable_add_grob(table, object(), t=1, l=1, z=math.inf, name="top")
    table = gtable_add_grob(table, object(), t=1, l=1, z=-math.inf, name="bottom")
    zs = {row.name: row.z for row in table.layout}
    # R：-Inf 落在现有 z 最小值之下（zmin - 1），不是整个表的最底。
    assert zs == {"mid": 5.0, "top": 6.0, "bottom": 4.0}
    assert [table.layout[index].name for index in table.drawing_order()] == [
        "bottom",
        "mid",
        "top",
    ]


def test_negative_indices_count_from_the_end() -> None:
    table = gtable(widths=nulls(1, 1), heights=nulls(1, 1))
    table = gtable_add_grob(table, object(), t=-1, l=-1)
    row = table.layout[0]
    assert (row.t, row.l, row.b, row.r) == (2, 2, 2, 2)


def test_add_grob_recycles_and_validates_arguments() -> None:
    table = gtable(widths=nulls(1, 1), heights=nulls(1))
    two = gtable_add_grob(table, [object(), object()], t=1, l=[1, 2], z=1, name=["a", "b"])
    assert [row.name for row in two.layout] == ["a", "b"]
    with pytest.raises(ValueError):
        gtable_add_grob(table, [object(), object()], t=1, l=[1, 2, 1])
    with pytest.raises(ValueError):
        gtable_add_grob(table, object(), t=2, l=1)
    with pytest.raises(ValueError):
        gtable_add_grob(table, object(), t=1, l=1, clip="maybe")
    assert gtable_add_grob(table, object(), t=1, l=1, clip=False).layout[0].clip == "off"
    # gtable 0.3.6 支持 "on"/"inherit"/"off"；inherit 只存值，继承语义等 M0-6 视口栈。
    inherit = gtable_add_grob(table, object(), t=1, l=1, clip="inherit")
    assert inherit.layout[0].clip == "inherit"


def test_add_grob_with_no_grobs_is_a_no_op() -> None:
    table = gtable(widths=nulls(1), heights=nulls(1))
    assert gtable_add_grob(table, [], t=1, l=1) == table


# ---------------------------------------------------------------------------
# add_rows / add_cols / padding
# ---------------------------------------------------------------------------


def test_add_rows_and_cols_insert_after_pos() -> None:
    table = gtable(widths=unit(1, "null"), heights=unit(1, "null"))
    table = gtable_add_cols(table, unit(2, "cm"), pos=0)
    table = gtable_add_rows(table, unit(3, "mm"), pos=0)
    table = gtable_add_cols(table, unit(1, "cm"), pos=-1)
    table = gtable_add_rows(table, unit(5, "mm"), pos=-1)
    assert widths_cm(table) == pytest.approx([2.0, 7.0, 1.0])
    assert heights_cm(table) == pytest.approx([0.3, 9.2, 0.5])


def test_inserting_rows_shifts_the_layout_indices() -> None:
    table = gtable(widths=nulls(1), heights=nulls(1, 1))
    table = gtable_add_grob(table, object(), t=2, l=1, name="g")
    for pos, expected in ((0, (3, 3)), (1, (3, 3)), (2, (2, 2)), (-1, (2, 2))):
        row = gtable_add_rows(table, unit(1, "mm"), pos=pos).placements("g")[0]
        assert (row.t, row.b) == expected, pos


def test_inserting_units_requires_units() -> None:
    table = gtable(widths=nulls(1), heights=nulls(1))
    with pytest.raises(TypeError):
        gtable_add_rows(table, 1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        gtable_add_cols(table, "1cm")  # type: ignore[arg-type]


def test_padding_adds_top_right_bottom_left() -> None:
    table = gtable_add_padding(
        gtable(widths=unit(1, "null"), heights=unit(1, "null")),
        unit([1, 2, 3, 4], "mm"),
    )
    assert widths_cm(table) == pytest.approx([0.4, 9.4, 0.2])
    assert heights_cm(table) == pytest.approx([0.1, 9.6, 0.3])


def test_padding_recycles_a_short_unit_to_four_sides() -> None:
    table = gtable_add_padding(
        gtable(widths=unit(1, "null"), heights=unit(1, "null")), unit(2, "mm")
    )
    assert widths_cm(table) == pytest.approx([0.2, 9.6, 0.2])
    assert heights_cm(table) == pytest.approx([0.2, 9.6, 0.2])


def test_padding_accepts_null_units() -> None:
    """null 边距不占固定空间，和表里的 null 一起分（R 实测三等分）。"""
    table = gtable_add_padding(
        gtable(widths=unit(1, "null"), heights=unit(1, "null")), unit(1, "null")
    )
    assert widths_cm(table) == pytest.approx([10 / 3] * 3)
    assert heights_cm(table) == pytest.approx([10 / 3] * 3)


def test_padding_keeps_existing_grobs_aligned() -> None:
    table = gtable_add_grob(gtable(widths=nulls(1), heights=nulls(1)), object(), t=1, l=1, name="g")
    padded = gtable_add_padding(table, unit(1, "mm"))
    row = padded.placements("g")[0]
    assert (row.t, row.b, row.l, row.r) == (2, 2, 2, 2)
    box = padded.region_box(row.t, row.l, width_cm=10, height_cm=10)
    assert (box.x_cm, box.y_cm) == pytest.approx((0.1, 0.1))


def test_empty_padding_is_rejected() -> None:
    with pytest.raises(ValueError):
        gtable_add_padding(gtable(widths=nulls(1), heights=nulls(1)), Unit())


# ---------------------------------------------------------------------------
# 查询 / 嵌套
# ---------------------------------------------------------------------------


def test_placements_and_grob_lookup_by_name() -> None:
    table = gtable(widths=nulls(1, 1), heights=nulls(1))
    a, b = object(), object()
    table = gtable_add_grob(table, [a, b], t=1, l=[1, 2], z=[1, 2], name=["a", "b"])
    assert [row.l for row in table.placements("b")] == [2]
    assert table.grob("a") is a
    assert table.drawing_order() == (0, 1)
    assert "2 grobs" in str(table)
    assert "name=b" in str(table)


def test_nested_table_resolves_inside_its_cell() -> None:
    inner = gtable(widths=unit([1, 3], "null"), heights=unit([1, 1], "null"))
    outer = gtable_add_grob(
        gtable(widths=unit_c(unit(4, "cm"), unit(1, "null")), heights=nulls(1)),
        inner,
        t=1,
        l=2,
        name="inner",
    )
    box = outer.boxes(10, 10)[0]
    assert (box.x_cm, box.width_cm) == pytest.approx((4.0, 6.0))
    child = outer.grob("inner")
    assert isinstance(child, GTable)
    sizes = child.resolve(box.width_cm, box.height_cm)
    assert sizes.widths_cm == pytest.approx((1.5, 4.5))
    assert sizes.heights_cm == pytest.approx((5.0, 5.0))


def test_gtable_width_and_height_stay_units() -> None:
    table = gtable(widths=unit_c(unit(2, "cm"), unit(1, "null")), heights=unit(1, "lines"))
    assert isinstance(gtable_width(table), Unit)
    assert list(convert_width(gtable_width(table), CM, ctx=UnitContext())) == pytest.approx([2.0])
    assert next(iter(gtable_height(table))).kind == "lines"
