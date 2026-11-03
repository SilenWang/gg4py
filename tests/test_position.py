"""M1-9 位置调整：identity / stack / fill / dodge / dodge2 / jitter / nudge。

两类断言：

- **执行侧语义**：直接用 `ColumnTable` 走 `Position.compute_layer()`，输入是
  geom `setup_data()` 之后、位置调整之前的那张表（与 R 的输入同形），期望值
  取自 `tests/fixtures/position_r_reference.json`（R 4.5.3 + ggplot2 4.0.3）；
- **流水线接线**：`geom_col(position="dodge")` / `p + position_dodge()` 与
  `position_dodge()` 同源（注册表里换一项，两条路径同时变）。

口径见 `docs/notes/position.md`；逐值 R 对拍在 `tests/test_position_r_parity.py`。
"""

from __future__ import annotations

import numpy as np
import pytest

from ggcore import plot, registry
from ggcore.build import (
    BuildError,
    build_plot,
    compute_aesthetics,
    compute_position,
    compute_stat,
    map_statistic,
)
from ggcore.data import Column, ColumnTable
from ggcore.position import (
    POSITION_FACTORIES,
    POSITION_NAMES,
    PanelPosition,
    PositionDodge,
    PositionDodge2,
    PositionFill,
    PositionIdentity,
    PositionJitter,
    PositionJitterdodge,
    PositionNudge,
    PositionStack,
    flipped_aes,
)

TOLERANCE = 1e-12


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def float_column(values) -> Column:
    return Column("float", np.asarray(values, dtype=np.float64))


def bar_table(
    x=(1.0, 1.0, 2.0, 2.0),
    y=(1.0, 2.0, 3.0, 4.0),
    group=(1, 2, 1, 2),
    *,
    width: float = 0.9,
    flipped: bool = False,
) -> ColumnTable:
    """geom bar / col `setup_data()` 之后的那张表（xmin/xmax/ymin/ymax 都齐）。"""
    x_values = np.asarray(x, dtype=np.float64)
    y_values = np.asarray(y, dtype=np.float64)
    return ColumnTable(
        [
            ("x", float_column(x_values)),
            ("y", float_column(y_values)),
            ("PANEL", Column("str", np.full(x_values.size, "1", dtype=object))),
            ("group", Column("int", np.asarray(group, dtype=np.float64))),
            ("flipped_aes", Column("bool", np.full(x_values.size, flipped, dtype=bool))),
            ("ymin", float_column(np.minimum(y_values, 0.0))),
            ("ymax", float_column(np.maximum(y_values, 0.0))),
            ("xmin", float_column(x_values - width / 2.0)),
            ("xmax", float_column(x_values + width / 2.0)),
        ]
    )


def horizontal_bar_table() -> ColumnTable:
    """横向柱（`flipped_aes = TRUE`）`setup_data()` 之后的表。

    与夹具的 `stack_horizontal` / `fill_horizontal` 同形：x 是长度（0..4），
    y 是类别轴（1 / 2 两档，厚度 y ± 0.45），四个 group 各占一行。
    """
    return ColumnTable(
        [
            ("x", float_column([1.0, 2.0, 3.0, 4.0])),
            ("y", float_column([1.0, 1.0, 2.0, 2.0])),
            ("PANEL", Column("str", np.full(4, "1", dtype=object))),
            ("group", Column("int", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("flipped_aes", Column("bool", np.ones(4, dtype=bool))),
            ("xmin", float_column([0.0, 0.0, 0.0, 0.0])),
            ("xmax", float_column([1.0, 2.0, 3.0, 4.0])),
            ("ymin", float_column([0.55, 0.55, 1.55, 1.55])),
            ("ymax", float_column([1.45, 1.45, 2.45, 2.45])),
        ]
    )


def values_of(table: ColumnTable, name: str) -> list[float]:
    column = table.column(name)
    return np.where(column.na_mask, np.nan, column.values.astype(np.float64)).tolist()


def position(name: str, **params):
    return registry.construct("position", name, **params)


# ---------------------------------------------------------------------------
# 注册表：名字、两个入口、同源
# ---------------------------------------------------------------------------


def test_position_names_are_registered_in_order() -> None:
    assert registry.registered("position") == (
        "identity",
        "stack",
        "fill",
        "dodge",
        "dodge2",
        "jitter",
        "jitterdodge",
        "nudge",
    )
    assert POSITION_NAMES == registry.registered("position")
    assert tuple(POSITION_FACTORIES) == POSITION_NAMES


def test_every_position_has_a_module_entry_and_a_ggplot_method() -> None:
    for name in POSITION_NAMES:
        entry = registry.entry_name("position", name)
        assert entry == f"position_{name}"
        assert getattr(plot, entry) is getattr(registry, entry)
        constructed = getattr(registry, entry)()
        via_plot = getattr(plot.ggplot(), entry)()
        assert via_plot.position == constructed
        # 构造器返回的实例自己带执行入口（不是第二套实现）。
        assert callable(constructed.compute_layer)


def test_plot_level_position_is_recorded_without_touching_layers() -> None:
    base = plot.ggplot()
    with_position = base.position_dodge(width=0.2)
    assert base.position is None
    assert with_position.position == registry.position_dodge(width=0.2)
    assert with_position.layers == base.layers
    assert isinstance(with_position.position, PositionDodge)


def test_compute_position_dispatches_through_the_registry() -> None:
    """换掉注册项：`position_dodge()` 与 `geom_col(position="dodge")` 同时变。"""
    original = POSITION_FACTORIES["dodge"]
    data = ColumnTable(
        [
            ("x", float_column([1.0, 1.0, 2.0, 2.0])),
            ("y", float_column([1.0, 2.0, 3.0, 4.0])),
            ("g", Column("str", np.array(["p", "q", "p", "q"], dtype=object))),
        ]
    )
    patched = {"width": 0.1, "preserve": "total", "orientation": "x", "reverse": False}

    def narrow(**params):
        return PositionDodge(params=patched)

    try:
        registry.register_position("dodge", narrow, allow_override=True)
        # 入口一：模块级构造器。
        assert registry.position_dodge().params["width"] == 0.1
        # 入口二：图层名字（流水线里按名字查注册表）。
        built = build_plot(
            plot.ggplot(data, plot.aes(x="x", y="y", fill="g")) + plot.geom_col(position="dodge")
        ).layers[0]
        assert values_of(built.positioned, "x") == pytest.approx(
            [0.975, 1.025, 1.975, 2.025], abs=TOLERANCE
        )
        assert values_of(built.positioned, "xmin") == pytest.approx(
            [0.75, 0.8, 1.75, 1.8], abs=TOLERANCE
        )
        assert values_of(built.positioned, "xmax") == pytest.approx(
            [1.2, 1.25, 2.2, 2.25], abs=TOLERANCE
        )
        # 入口三：`p.position_dodge()`（同一个注册表项）。
        assert plot.ggplot().position_dodge().position.params["width"] == 0.1
    finally:
        registry.register_position("dodge", original, allow_override=True)

    assert registry.position_dodge().params["width"] is None


def test_unknown_position_is_rejected() -> None:
    layer = plot.geom_point(position="sparkle")
    mapped = ColumnTable([("x", float_column([1.0])), ("y", float_column([2.0]))])
    with pytest.raises(BuildError, match="sparkle"):
        compute_position(layer, mapped)


def test_constructor_validates_its_parameters() -> None:
    with pytest.raises(ValueError, match="preserve"):
        registry.position_dodge(preserve="everything")
    with pytest.raises(ValueError, match="orientation"):
        registry.position_dodge(orientation="z")
    with pytest.raises(TypeError, match="reverse"):
        registry.position_stack(reverse=1)


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------


def test_identity_position_is_a_no_op() -> None:
    table = bar_table()
    assert position("identity").compute_layer(table) == table
    assert isinstance(registry.position_identity(), PositionIdentity)


# ---------------------------------------------------------------------------
# stack / fill
# ---------------------------------------------------------------------------


def test_stack_orders_groups_and_rewrites_y() -> None:
    """R: y = (3, 2, 7, 4)，ymin = (2, 0, 4, 0)（第一个 group 在最上面）。"""
    stacked = position("stack").compute_layer(bar_table())
    assert values_of(stacked, "y") == pytest.approx([3.0, 2.0, 7.0, 4.0], abs=TOLERANCE)
    assert values_of(stacked, "ymin") == pytest.approx([2.0, 0.0, 4.0, 0.0], abs=TOLERANCE)
    assert values_of(stacked, "ymax") == pytest.approx([3.0, 2.0, 7.0, 4.0], abs=TOLERANCE)
    assert isinstance(registry.position_stack(), PositionStack)


def test_stack_reverse_puts_the_first_group_at_the_bottom() -> None:
    """R: reverse = TRUE → y = (1, 3, 3, 7)，ymin = (0, 1, 0, 3)。"""
    stacked = position("stack", reverse=True).compute_layer(bar_table())
    assert values_of(stacked, "y") == pytest.approx([1.0, 3.0, 3.0, 7.0], abs=TOLERANCE)
    assert values_of(stacked, "ymin") == pytest.approx([0.0, 1.0, 0.0, 3.0], abs=TOLERANCE)


def test_stack_vjust_slides_between_ymin_and_ymax() -> None:
    bottom = position("stack", vjust=0.0).compute_layer(bar_table())
    assert values_of(bottom, "y") == pytest.approx([2.0, 0.0, 4.0, 0.0], abs=TOLERANCE)
    middle = position("stack", vjust=0.5).compute_layer(bar_table())
    assert values_of(middle, "y") == pytest.approx([2.5, 1.0, 5.5, 2.0], abs=TOLERANCE)


def test_stack_splits_negative_values_downwards() -> None:
    """R: 正值向上、负值向下各堆一次；负值那一段 y = ymax = 0（vjust = 1）。"""
    table = bar_table(y=(2.0, -1.0, 3.0, -2.0))
    stacked = position("stack").compute_layer(table)
    assert values_of(stacked, "y") == pytest.approx([2.0, 0.0, 3.0, 0.0], abs=TOLERANCE)
    assert values_of(stacked, "ymin") == pytest.approx([0.0, -1.0, 0.0, -2.0], abs=TOLERANCE)
    assert values_of(stacked, "ymax") == pytest.approx([2.0, 0.0, 3.0, 0.0], abs=TOLERANCE)


def test_stack_without_duplicate_x_is_a_no_op() -> None:
    table = bar_table(x=(1.0, 2.0), y=(3.0, 4.0), group=(1, 1))
    assert position("stack").compute_layer(table) == table


def test_stack_with_unique_x_still_applies_when_vjust_is_not_one() -> None:
    """上游 `setup_params()`：x 无重复但 vjust != 1 时 var 仍非 NULL。"""
    table = bar_table(x=(1.0, 2.0), y=(3.0, 4.0), group=(1, 1))
    stacked = position("stack", vjust=0.0).compute_layer(table)
    assert values_of(stacked, "y") == pytest.approx([0.0, 0.0], abs=TOLERANCE)
    assert values_of(stacked, "ymax") == pytest.approx([3.0, 4.0], abs=TOLERANCE)


def test_fill_normalises_each_x_to_zero_one() -> None:
    """R: x = 1 的两段是 0..2/3、2/3..1；x = 2 是 0..4/7、4/7..1。"""
    filled = position("fill").compute_layer(bar_table())
    assert values_of(filled, "y") == pytest.approx([1.0, 2 / 3, 1.0, 4 / 7], abs=TOLERANCE)
    assert values_of(filled, "ymin") == pytest.approx([2 / 3, 0.0, 4 / 7, 0.0], abs=TOLERANCE)
    assert values_of(filled, "ymax") == pytest.approx([1.0, 2 / 3, 1.0, 4 / 7], abs=TOLERANCE)
    assert isinstance(registry.position_fill(), PositionFill)


def test_fill_of_a_single_group_is_one() -> None:
    table = bar_table(x=(1.0, 2.0), y=(3.0, 4.0), group=(1, 1))
    filled = position("fill").compute_layer(table)
    assert values_of(filled, "y") == pytest.approx([1.0, 1.0], abs=TOLERANCE)
    assert values_of(filled, "ymin") == pytest.approx([0.0, 0.0], abs=TOLERANCE)


def test_stack_horizontal_writes_the_cumulative_values_to_the_x_family() -> None:
    """flipped_aes = TRUE：累计值落在 x 族（长度轴），y 族（类别轴）原样保留。

    R: x = (3, 2, 7, 4)、xmin = (2, 0, 4, 0)、y = (1, 1, 2, 2) 不动。
    """
    stacked = position("stack").compute_layer(horizontal_bar_table())
    assert values_of(stacked, "x") == pytest.approx([3.0, 2.0, 7.0, 4.0], abs=TOLERANCE)
    assert values_of(stacked, "xmin") == pytest.approx([2.0, 0.0, 4.0, 0.0], abs=TOLERANCE)
    assert values_of(stacked, "xmax") == pytest.approx([3.0, 2.0, 7.0, 4.0], abs=TOLERANCE)
    assert values_of(stacked, "y") == pytest.approx([1.0, 1.0, 2.0, 2.0], abs=TOLERANCE)
    assert values_of(stacked, "ymin") == pytest.approx([0.55, 0.55, 1.55, 1.55], abs=TOLERANCE)
    assert values_of(stacked, "ymax") == pytest.approx([1.45, 1.45, 2.45, 2.45], abs=TOLERANCE)


def test_fill_horizontal_normalises_the_x_family_and_keeps_the_category_axis() -> None:
    """R: x = (1, 2/3, 1, 4/7)、xmin = (2/3, 0, 4/7, 0)、y = (1, 1, 2, 2) 不动。"""
    filled = position("fill").compute_layer(horizontal_bar_table())
    assert values_of(filled, "x") == pytest.approx([1.0, 2 / 3, 1.0, 4 / 7], abs=TOLERANCE)
    assert values_of(filled, "xmin") == pytest.approx([2 / 3, 0.0, 4 / 7, 0.0], abs=TOLERANCE)
    assert values_of(filled, "xmax") == pytest.approx([1.0, 2 / 3, 1.0, 4 / 7], abs=TOLERANCE)
    assert values_of(filled, "y") == pytest.approx([1.0, 1.0, 2.0, 2.0], abs=TOLERANCE)
    assert values_of(filled, "ymin") == pytest.approx([0.55, 0.55, 1.55, 1.55], abs=TOLERANCE)
    assert values_of(filled, "ymax") == pytest.approx([1.45, 1.45, 2.45, 2.45], abs=TOLERANCE)


# ---------------------------------------------------------------------------
# dodge
# ---------------------------------------------------------------------------


def test_dodge_places_two_groups_side_by_side() -> None:
    """R: x = (0.775, 1.225, 1.775, 2.225)，xmin/xmax 各占半根柱。"""
    dodged = position("dodge").compute_layer(bar_table())
    assert values_of(dodged, "x") == pytest.approx([0.775, 1.225, 1.775, 2.225], abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx([0.55, 1.0, 1.55, 2.0], abs=TOLERANCE)
    assert values_of(dodged, "xmax") == pytest.approx([1.0, 1.45, 2.0, 2.45], abs=TOLERANCE)
    # 高度轴不动。
    assert values_of(dodged, "y") == pytest.approx([1.0, 2.0, 3.0, 4.0], abs=TOLERANCE)
    assert values_of(dodged, "ymax") == pytest.approx([1.0, 2.0, 3.0, 4.0], abs=TOLERANCE)
    assert isinstance(registry.position_dodge(), PositionDodge)


def test_dodge_width_param_scales_the_shift_but_not_the_bar_width() -> None:
    """R: width = 0.4 → x 位移用 0.4，柱宽仍由 d_width / n 决定。"""
    dodged = position("dodge", width=0.4).compute_layer(bar_table())
    assert values_of(dodged, "x") == pytest.approx([0.9, 1.1, 1.9, 2.1], abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx([0.675, 0.875, 1.675, 1.875], abs=TOLERANCE)
    assert values_of(dodged, "xmax") == pytest.approx([1.125, 1.325, 2.125, 2.325], abs=TOLERANCE)


def test_dodge_reverse_flips_the_group_order() -> None:
    """R: reverse = TRUE → group 1 在右边（x = (1.225, 0.775)）。"""
    dodged = position("dodge", reverse=True).compute_layer(bar_table())
    assert values_of(dodged, "x") == pytest.approx([1.225, 0.775, 2.225, 1.775], abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx([1.0, 0.55, 2.0, 1.55], abs=TOLERANCE)
    assert values_of(dodged, "order") == pytest.approx([2.0, 1.0, 2.0, 1.0], abs=TOLERANCE)


def test_dodge_preserve_single_uses_the_largest_group_count() -> None:
    """R: 不均匀分组（x=1 一组、x=2 三组、x=3 两组）→ n = 3。"""
    table = bar_table(
        x=(1.0, 2.0, 2.0, 2.0, 3.0, 3.0),
        y=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
        group=(1, 1, 2, 3, 1, 2),
    )
    dodged = position("dodge", preserve="single").compute_layer(table)
    assert values_of(dodged, "x") == pytest.approx([0.7, 1.7, 2.0, 2.3, 2.7, 3.0], abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx(
        [0.55, 1.55, 1.85, 2.15, 2.55, 2.85], abs=TOLERANCE
    )
    assert values_of(dodged, "order") == pytest.approx([1, 1, 2, 3, 1, 2], abs=TOLERANCE)


def test_dodge_without_width_only_adds_the_anchors() -> None:
    """点图没有 xmin/xmax：缺省 width = 0，位置不动，但补 xmin/xmax/ymax。"""
    table = ColumnTable(
        [
            ("x", float_column([1.0, 2.0, 1.0, 2.0])),
            ("y", float_column([1.0, 2.0, 3.0, 4.0])),
            ("PANEL", Column("str", np.full(4, "1", dtype=object))),
            ("group", Column("int", np.array([1.0, 2.0, 1.0, 2.0]))),
        ]
    )
    dodged = position("dodge").compute_layer(table)
    assert values_of(dodged, "x") == pytest.approx([1.0, 2.0, 1.0, 2.0], abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx([1.0, 2.0, 1.0, 2.0], abs=TOLERANCE)
    assert values_of(dodged, "xmax") == pytest.approx([1.0, 2.0, 1.0, 2.0], abs=TOLERANCE)
    assert values_of(dodged, "ymax") == pytest.approx([1.0, 2.0, 3.0, 4.0], abs=TOLERANCE)
    # R 的列序：…, group, order, xmin, xmax, ymax（后面才是 default_aes）。
    assert dodged.names[-4:] == ("order", "xmin", "xmax", "ymax")


def test_dodge_horizontal_moves_along_the_y_axis() -> None:
    """flipped_aes = TRUE：x 是长度（不动），y 是组内位置（被并排）。

    横向柱的「位置轴」厚度是 y ± 0.45，长度轴是 xmin = 0 … xmax = 长度——
    与 `tests/fixtures/position_r_reference.json` 的 `dodge_horizontal` 同形。
    """
    table = ColumnTable(
        [
            ("x", float_column([1.0, 2.0, 3.0, 4.0])),
            ("y", float_column([1.0, 1.0, 2.0, 2.0])),
            ("PANEL", Column("str", np.full(4, "1", dtype=object))),
            ("group", Column("int", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("flipped_aes", Column("bool", np.ones(4, dtype=bool))),
            ("xmin", float_column([0.0, 0.0, 0.0, 0.0])),
            ("xmax", float_column([1.0, 2.0, 3.0, 4.0])),
            ("ymin", float_column([0.55, 0.55, 1.55, 1.55])),
            ("ymax", float_column([1.45, 1.45, 2.45, 2.45])),
        ]
    )
    dodged = position("dodge").compute_layer(table)
    assert flipped_aes(dodged) is True
    assert values_of(dodged, "x") == pytest.approx([1.0, 2.0, 3.0, 4.0], abs=TOLERANCE)
    assert values_of(dodged, "y") == pytest.approx([0.775, 1.225, 1.775, 2.225], abs=TOLERANCE)
    assert values_of(dodged, "ymin") == pytest.approx([0.55, 1.0, 1.55, 2.0], abs=TOLERANCE)
    assert values_of(dodged, "ymax") == pytest.approx([1.0, 1.45, 2.0, 2.45], abs=TOLERANCE)


def test_dodge_adds_the_order_column_that_upstream_uses() -> None:
    dodged = position("dodge").compute_layer(bar_table())
    assert "order" in dodged
    assert dodged.column("order").kind == "int"
    assert values_of(dodged, "order") == pytest.approx([1.0, 2.0, 1.0, 2.0], abs=TOLERANCE)


# ---------------------------------------------------------------------------
# dodge2
# ---------------------------------------------------------------------------


def test_dodge2_places_two_groups_with_padding() -> None:
    """R: padding = 0.1 → xmin = (0.5725, 1.0225, …)，x 与 dodge 相同。"""
    dodged = position("dodge2").compute_layer(bar_table())
    assert values_of(dodged, "x") == pytest.approx([0.775, 1.225, 1.775, 2.225], abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx(
        [0.5725, 1.0225, 1.5725, 2.0225], abs=TOLERANCE
    )
    assert values_of(dodged, "xmax") == pytest.approx(
        [0.9775, 1.4275, 1.9775, 2.4275], abs=TOLERANCE
    )
    assert isinstance(registry.position_dodge2(), PositionDodge2)


def test_dodge2_padding_param() -> None:
    """R: padding = 0.2 → 柱宽 0.9 * 0.8 = 0.72。"""
    dodged = position("dodge2", padding=0.2).compute_layer(bar_table())
    assert values_of(dodged, "xmin") == pytest.approx([0.595, 1.045, 1.595, 2.045], abs=TOLERANCE)
    assert values_of(dodged, "xmax") == pytest.approx([0.955, 1.405, 1.955, 2.405], abs=TOLERANCE)


def test_dodge2_with_one_bar_per_x_is_identity() -> None:
    """上游：xid 全不同时 `pos_dodge2()` 直接返回（不叠 padding）。"""
    table = bar_table(x=(1.0, 2.0, 3.0, 4.0), y=(1.0, 2.0, 3.0, 4.0), group=(1, 2, 3, 4))
    dodged = position("dodge2").compute_layer(table)
    assert values_of(dodged, "x") == pytest.approx([1.0, 2.0, 3.0, 4.0], abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx([0.55, 1.55, 2.55, 3.55], abs=TOLERANCE)
    assert values_of(dodged, "xmax") == pytest.approx([1.45, 2.45, 3.45, 4.45], abs=TOLERANCE)


def test_dodge2_does_not_add_the_ymax_copy_that_dodge_adds() -> None:
    table = ColumnTable(
        [
            ("x", float_column([1.0, 2.0, 1.0, 2.0])),
            ("y", float_column([1.0, 2.0, 3.0, 4.0])),
            ("group", Column("int", np.array([1.0, 2.0, 1.0, 2.0]))),
        ]
    )
    assert "ymax" not in position("dodge2").compute_layer(table)
    assert "ymax" in position("dodge").compute_layer(table)


def test_dodge2_preserve_single_without_x_uses_find_x_overlaps() -> None:
    """`setup_params()` 在补 x 之前分支：没有 x 时 n 取 find_x_overlaps 的组数。

    R（geom_rect + position_dodge2(preserve = "single")）：两簇重叠区间（2 行 +
    1 行）→ n = 2，x = (0.175, 0.425, 1.25)；若把补出来的中点 x 当成 `table(x)`
    就会得到 n = 1，x = (0.05, 0.55, 1.25)。
    """
    table = ColumnTable(
        [
            ("xmin", float_column([0.0, 0.1, 1.0])),
            ("xmax", float_column([0.5, 0.6, 1.5])),
            ("ymin", float_column([0.0, 0.0, 0.0])),
            ("ymax", float_column([1.0, 1.0, 1.0])),
            ("PANEL", Column("str", np.full(3, "1", dtype=object))),
            ("group", Column("int", np.array([1.0, 2.0, 1.0]))),
        ]
    )
    dodged = position("dodge2", preserve="single").compute_layer(table)
    assert values_of(dodged, "x") == pytest.approx([0.175, 0.425, 1.25], abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx([0.0625, 0.3125, 1.1375], abs=TOLERANCE)
    assert values_of(dodged, "xmax") == pytest.approx([0.2875, 0.5375, 1.3625], abs=TOLERANCE)


# ---------------------------------------------------------------------------
# jitter
# ---------------------------------------------------------------------------


def test_jitter_defaults_to_40_percent_of_the_resolution() -> None:
    table = bar_table()
    jittered = position("jitter", seed=7).compute_layer(table)
    x = np.asarray(values_of(jittered, "x"))
    y = np.asarray(values_of(jittered, "y"))
    assert np.all(np.abs(x - np.array([1.0, 1.0, 2.0, 2.0])) <= 0.4 + 1e-12)
    assert np.all(np.abs(y - np.array([1.0, 2.0, 3.0, 4.0])) <= 0.4 + 1e-12)
    assert isinstance(registry.position_jitter(), PositionJitter)


def test_jitter_seed_is_reproducible_and_does_not_touch_the_global_rng() -> None:
    table = bar_table()
    before = np.random.get_state()
    first = position("jitter", seed=42).compute_layer(table)
    second = position("jitter", seed=42).compute_layer(table)
    after = np.random.get_state()
    assert first == second
    # 没有动全局 RNG（legacy state 的键、缓冲与位置都没变）。
    assert before[0] == after[0]
    assert np.array_equal(before[1], after[1])
    assert before[2:] == after[2:]
    other = position("jitter", seed=43).compute_layer(table)
    assert values_of(other, "x") != values_of(first, "x")


def test_jitter_zero_width_and_height_is_a_no_op() -> None:
    table = bar_table()
    assert position("jitter", width=0.0, height=0.0).compute_layer(table) == table


def test_jitter_moves_the_whole_x_and_y_aesthetic_families() -> None:
    table = bar_table()
    jittered = position("jitter", width=0.4, height=0.4, seed=3).compute_layer(table)
    shift_x = np.asarray(values_of(jittered, "x")) - np.asarray(values_of(table, "x"))
    assert np.allclose(
        np.asarray(values_of(jittered, "xmin")) - np.asarray(values_of(table, "xmin")), shift_x
    )
    assert np.allclose(
        np.asarray(values_of(jittered, "xmax")) - np.asarray(values_of(table, "xmax")), shift_x
    )
    shift_y = np.asarray(values_of(jittered, "y")) - np.asarray(values_of(table, "y"))
    assert np.allclose(
        np.asarray(values_of(jittered, "ymax")) - np.asarray(values_of(table, "ymax")), shift_y
    )


# ---------------------------------------------------------------------------
# nudge
# ---------------------------------------------------------------------------


def test_nudge_translates_both_axes() -> None:
    nudged = position("nudge", x=0.2, y=1.0).compute_layer(bar_table())
    assert values_of(nudged, "x") == pytest.approx([1.2, 1.2, 2.2, 2.2], abs=TOLERANCE)
    assert values_of(nudged, "xmin") == pytest.approx([0.75, 0.75, 1.75, 1.75], abs=TOLERANCE)
    assert values_of(nudged, "xmax") == pytest.approx([1.65, 1.65, 2.65, 2.65], abs=TOLERANCE)
    assert values_of(nudged, "y") == pytest.approx([2.0, 3.0, 4.0, 5.0], abs=TOLERANCE)
    assert values_of(nudged, "ymin") == pytest.approx([1.0, 1.0, 1.0, 1.0], abs=TOLERANCE)
    assert isinstance(registry.position_nudge(), PositionNudge)


def test_nudge_without_params_is_a_no_op() -> None:
    table = bar_table()
    assert position("nudge").compute_layer(table) == table


def test_nudge_falls_back_to_the_nudge_aesthetic_columns() -> None:
    """上游 `setup_params()`：`self$x %||% data$nudge_x`（映射出来的量也能用）。"""
    table = bar_table()
    table = ColumnTable(
        [
            *zip(table.names, table.columns(), strict=True),
            ("nudge_x", float_column([0.0, 0.5, 0.0, 0.5])),
        ]
    )
    nudged = position("nudge").compute_layer(table)
    assert values_of(nudged, "x") == pytest.approx([1.0, 1.5, 2.0, 2.5], abs=TOLERANCE)


# ---------------------------------------------------------------------------
# 不变量：不删行、不改 nrows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", POSITION_NAMES)
def test_position_never_drops_or_reorders_rows(name: str) -> None:
    table = bar_table()
    out = position(name, **({"seed": 1} if name == "jitter" else {})).compute_layer(table)
    assert out.nrows == table.nrows == 4
    # 除 order 外，原有列都还在（顺序不变）；位置调整只改数值。
    for column_name in table.names:
        assert column_name in out
    assert list(out.names[: len(table.names)]) == list(table.names)


# ---------------------------------------------------------------------------
# 流水线接线
# ---------------------------------------------------------------------------


def test_end_to_end_dodge_matches_r_row_by_row() -> None:
    """验收片段：两组 `geom_col(position="dodge")`，xmin/xmax 与 R 逐值相等。"""
    data = ColumnTable(
        [
            ("x", float_column([1.0, 1.0, 2.0, 2.0])),
            ("y", float_column([1.0, 2.0, 3.0, 4.0])),
            ("g", Column("str", np.array(["p", "q", "p", "q"], dtype=object))),
        ]
    )
    built = build_plot(
        plot.ggplot(data, plot.aes(x="x", y="y", fill="g")) + plot.geom_col(position="dodge")
    ).layers[0]
    # R 4.0.3: xmin = (0.55, 1.00, 1.55, 2.00)，xmax = (1.00, 1.45, 2.00, 2.45)
    assert values_of(built.data, "xmin") == pytest.approx([0.55, 1.0, 1.55, 2.0], abs=TOLERANCE)
    assert values_of(built.data, "xmax") == pytest.approx([1.0, 1.45, 2.0, 2.45], abs=TOLERANCE)
    assert values_of(built.data, "x") == pytest.approx([0.775, 1.225, 1.775, 2.225], abs=TOLERANCE)
    assert built.position == "dodge"
    # 列序与 R 一致：order 在 xmin/xmax 之前、default_aes 之前。
    assert built.data.names.index("order") < built.data.names.index("colour")


def test_end_to_end_position_accepts_a_constructed_position_object() -> None:
    data = ColumnTable(
        [
            ("x", float_column([1.0, 1.0])),
            ("y", float_column([1.0, 2.0])),
            ("g", Column("str", np.array(["p", "q"], dtype=object))),
        ]
    )
    p = plot.ggplot(data, plot.aes(x="x", y="y", fill="g")) + plot.geom_col(
        position=plot.position_dodge(width=0.4)
    )
    built = build_plot(p).layers[0]
    assert built.position == "dodge"
    assert values_of(built.data, "x") == pytest.approx([0.9, 1.1], abs=TOLERANCE)


def test_bar_default_stack_still_works_after_the_refactor() -> None:
    data = ColumnTable(
        [
            ("x", float_column([1.0, 1.0, 2.0, 2.0])),
            ("y", float_column([1.0, 2.0, 3.0, 4.0])),
            ("g", Column("str", np.array(["p", "q", "p", "q"], dtype=object))),
        ]
    )
    built = build_plot(
        plot.ggplot(data, plot.aes(x="x", y="y", fill="g")) + plot.geom_col()
    ).layers[0]
    assert values_of(built.data, "y") == pytest.approx([3.0, 2.0, 7.0, 4.0], abs=TOLERANCE)
    assert values_of(built.data, "ymin") == pytest.approx([2.0, 0.0, 4.0, 0.0], abs=TOLERANCE)


def test_boxplot_default_dodge2_no_longer_raises() -> None:
    data = ColumnTable(
        [
            ("x", float_column([1.0, 1.0, 2.0, 2.0])),
            ("g", Column("str", np.array(["p", "q", "p", "q"], dtype=object))),
            ("lo", float_column([1.0, 2.0, 3.0, 4.0])),
            ("hi", float_column([2.0, 3.0, 4.0, 5.0])),
            ("mid", float_column([1.5, 2.5, 3.5, 4.5])),
            ("y0", float_column([0.5, 1.5, 2.5, 3.5])),
            ("y1", float_column([2.5, 3.5, 4.5, 5.5])),
        ]
    )
    layer = plot.geom_boxplot(
        stat="identity",
        mapping=plot.aes(lower="lo", upper="hi", middle="mid", ymin="y0", ymax="y1"),
    )
    built = build_plot(plot.ggplot(data, plot.aes(x="x", fill="g")) + layer).layers[0]
    assert built.position == "dodge2"
    assert built.data.nrows == 4
    assert values_of(built.data, "x") == pytest.approx([0.775, 1.225, 1.775, 2.225], abs=TOLERANCE)


def test_compute_position_is_still_the_documented_entry_point() -> None:
    data = ColumnTable(
        [
            ("x", float_column([1.0, 1.0, 2.0, 2.0])),
            ("y", float_column([1.0, 2.0, 3.0, 4.0])),
            ("g", Column("str", np.array(["p", "q", "p", "q"], dtype=object))),
        ]
    )
    p = plot.ggplot(data, plot.aes(x="x", y="y", fill="g")) + plot.geom_col(position="fill")
    layer = p.layers[0]
    aesthetics = compute_aesthetics(p, layer)
    mapped = map_statistic(layer, compute_stat(layer, aesthetics), aesthetics)
    positioned = compute_position(layer, mapped)
    assert values_of(positioned, "y") == pytest.approx([1.0, 2 / 3, 1.0, 4 / 7], abs=TOLERANCE)


# ---------------------------------------------------------------------------
# jitterdodge（SIL-734）
# ---------------------------------------------------------------------------


def points_table(
    x=(1.0, 1.0, 2.0, 2.0),
    y=(1.0, 2.0, 3.0, 4.0),
    group=(1, 2, 1, 2),
    panel=None,
) -> ColumnTable:
    """`geom_point(setup_data)` 之后的点表：只有 x / y / group / PANEL。"""
    x_values = np.asarray(x, dtype=np.float64)
    panels = (
        np.full(x_values.size, "1", dtype=object)
        if panel is None
        else np.asarray(panel, dtype=object)
    )
    return ColumnTable(
        [
            ("x", float_column(x_values)),
            ("y", float_column(np.asarray(y, dtype=np.float64))),
            ("PANEL", Column("str", panels)),
            ("group", Column("int", np.asarray(group, dtype=np.float64))),
        ]
    )


def test_jitterdodge_zero_jitter_is_a_dodge_with_its_own_width() -> None:
    """R: jitter.width = 0 时退化成 dodge(dodge.width = 0.75) → x = 0.8125, 1.1875, …"""
    table = points_table()
    dodged = position("jitterdodge", jitter_width=0.0, jitter_height=0.0, seed=42).compute_layer(
        table
    )
    assert isinstance(registry.position_jitterdodge(), PositionJitterdodge)
    assert values_of(dodged, "x") == pytest.approx([0.8125, 1.1875, 1.8125, 2.1875], abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx([0.625, 1.0, 1.625, 2.0], abs=TOLERANCE)
    assert values_of(dodged, "xmax") == pytest.approx([1.0, 1.375, 2.0, 2.375], abs=TOLERANCE)
    # 上游 collide() 的副作用：没有 ymax 时补一列（y 不动）。
    assert values_of(dodged, "ymax") == pytest.approx([1.0, 2.0, 3.0, 4.0], abs=TOLERANCE)
    # 没有 `order` 列：jitterdodge 不继承 PositionDodge$setup_data()。
    assert "order" not in dodged

    # 与 position_dodge(width = 0.75) 逐值相同（两者的 pos_dodge 相位一致）。
    reference = position("dodge", width=0.75).compute_layer(table)
    assert values_of(dodged, "x") == pytest.approx(values_of(reference, "x"), abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx(values_of(reference, "xmin"), abs=TOLERANCE)


def test_jitterdodge_dodge_width_param() -> None:
    """R: dodge.width = 0.4 → x = 0.9 / 1.1，xmin/xmax 各 0.2 宽。"""
    table = points_table()
    dodged = position(
        "jitterdodge", jitter_width=0.0, jitter_height=0.0, dodge_width=0.4, seed=42
    ).compute_layer(table)
    assert values_of(dodged, "x") == pytest.approx([0.9, 1.1, 1.9, 2.1], abs=TOLERANCE)
    assert values_of(dodged, "xmin") == pytest.approx([0.8, 1.0, 1.8, 2.0], abs=TOLERANCE)
    assert values_of(dodged, "xmax") == pytest.approx([1.0, 1.2, 2.0, 2.2], abs=TOLERANCE)


def test_jitterdodge_reverse_does_not_change_the_positions() -> None:
    """上游 `pos_dodge()` 只看 group 名次；`reverse` 只改行序，输出逐值相等。"""
    table = points_table()
    forward = position("jitterdodge", jitter_width=0.0, jitter_height=0.0, seed=42).compute_layer(
        table
    )
    reverse = position(
        "jitterdodge", jitter_width=0.0, jitter_height=0.0, seed=42, reverse=True
    ).compute_layer(table)
    assert values_of(forward, "x") == pytest.approx(values_of(reverse, "x"), abs=TOLERANCE)
    assert values_of(forward, "xmin") == pytest.approx(values_of(reverse, "xmin"), abs=TOLERANCE)


def test_jitterdodge_default_jitter_width_uses_resolution_and_ndodge() -> None:
    """R: jitter.width = 40% resolution / (ndodge + 2)；height 缺省 0。"""
    table = points_table()  # x 分辨率 1、每个 x 上 2 个 group → 0.4 / 4 = 0.1
    impl = position("jitterdodge", seed=42)
    resolved = impl.setup_params(table, dict(impl.params))
    assert resolved["jitter_width"] == pytest.approx(0.1, abs=TOLERANCE)
    assert resolved["jitter_height"] == 0
    assert resolved["dodge_width"] == pytest.approx(0.75, abs=TOLERANCE)

    # 3 个 group 的 x → 0.4 / 5 = 0.08。
    three = points_table(x=(1.0, 1.0, 1.0, 2.0), y=(1.0, 2.0, 3.0, 4.0), group=(1, 2, 3, 1))
    resolved = impl.setup_params(three, dict(impl.params))
    assert resolved["jitter_width"] == pytest.approx(0.08, abs=TOLERANCE)


def test_jitterdodge_seed_is_reproducible_and_per_panel() -> None:
    table = points_table(panel=("1", "1", "2", "2"))
    first = position("jitterdodge", seed=42).compute_layer(table)
    second = position("jitterdodge", seed=42).compute_layer(table)
    assert first == second
    assert not np.allclose(
        values_of(first, "x"),
        values_of(position("jitterdodge", seed=43).compute_layer(table), "x"),
    )
    # y 只在 jitter.height > 0 时抖；缺省 0 → y 逐值不变。
    assert values_of(first, "y") == pytest.approx(values_of(table, "y"), abs=TOLERANCE)


def test_jitterdodge_accepts_r_dotted_parameter_names() -> None:
    """R 的 `jitter.width` / `jitter.height` / `dodge.width` 两种写法都认。"""
    dotted = registry.position_jitterdodge(
        **{"jitter.width": 0.2, "jitter.height": 0.1, "dodge.width": 0.4}, seed=1
    )
    assert isinstance(dotted, PositionJitterdodge)
    assert dotted.params["jitter_width"] == pytest.approx(0.2)
    assert dotted.params["jitter_height"] == pytest.approx(0.1)
    assert dotted.params["dodge_width"] == pytest.approx(0.4)
    with pytest.raises(TypeError, match=r"jitter\.unknown"):
        registry.position_jitterdodge(**{"jitter.unknown": 1})


def test_jitterdodge_requires_x_and_y() -> None:
    table = ColumnTable([("x", float_column([1.0, 2.0]))])
    with pytest.raises(BuildError, match="x 与 y"):
        position("jitterdodge").compute_layer(table)


# ---------------------------------------------------------------------------
# 面板语义：setup_params / setup_data 整层，compute_panel 逐面板
# ---------------------------------------------------------------------------


def faceted_bar_table() -> ColumnTable:
    """两个面板的同构柱表（行按 PANEL 连续，与 R 的 dapply 输出同序）。"""
    return bar_table(
        x=(1.0, 1.0, 2.0, 2.0, 1.0, 1.0, 2.0, 2.0),
        y=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0),
        group=(1, 2, 1, 2, 1, 2, 1, 2),
    )


def with_panels(table: ColumnTable, panels) -> ColumnTable:
    """把表的 PANEL 列换成给定值（其余列不动）。"""
    columns = [
        (name, column)
        if name != "PANEL"
        else ("PANEL", Column("str", np.asarray(panels, dtype=object)))
        for name, column in zip(table.names, table.columns(), strict=True)
    ]
    return ColumnTable(columns, nrows=table.nrows)


def test_panelwise_positions_expose_compute_panel() -> None:
    """内置 position 的骨架：`compute_layer()` = 拆面板 + `compute_panel()`。"""
    for name in POSITION_NAMES:
        impl = position(name)
        if name in {"identity", "nudge"}:
            # 上游这两个是图层级实现（没有 compute_panel）。
            assert not isinstance(impl, PanelPosition), name
            continue
        assert isinstance(impl, PanelPosition), name
        assert callable(impl.compute_panel), name


def test_stack_does_not_stack_across_panels() -> None:
    """R: 面板 2 的 y = (11, 6, 15, 8)，各自从 0 累加。"""
    table = with_panels(faceted_bar_table(), ["1", "1", "1", "1", "2", "2", "2", "2"])
    stacked = position("stack").compute_layer(table)
    assert values_of(stacked, "y") == pytest.approx(
        [3.0, 2.0, 7.0, 4.0, 11.0, 6.0, 15.0, 8.0], abs=TOLERANCE
    )
    assert values_of(stacked, "ymin") == pytest.approx(
        [2.0, 0.0, 4.0, 0.0, 6.0, 0.0, 8.0, 0.0], abs=TOLERANCE
    )
    # 行序不因拆面板改变。
    assert stacked.column("PANEL").values.tolist() == table.column("PANEL").values.tolist()


def test_dodge_places_each_panel_independently() -> None:
    table = with_panels(faceted_bar_table(), ["1", "1", "1", "1", "2", "2", "2", "2"])
    dodged = position("dodge").compute_layer(table)
    expected = [0.775, 1.225, 1.775, 2.225]
    assert values_of(dodged, "x") == pytest.approx(expected + expected, abs=TOLERANCE)
    assert values_of(dodged, "order") == pytest.approx([1, 2, 1, 2, 1, 2, 1, 2], abs=TOLERANCE)


def test_dodge2_preserve_single_takes_n_across_panels() -> None:
    """R: 不均匀分面时 n = 全层最大组数 3；逐面板算会得到 n = 2 的另一组坐标。

    A 面板（x=1 只 1 组、x=2 两组）与 B 面板（x=1 三组、x=2 一组）：
    x = (1.0, 1.85, 2.15, 0.7, 1.0, 1.3, 2.0)。
    """
    table = bar_table(
        x=(1.0, 2.0, 2.0, 1.0, 1.0, 1.0, 2.0),
        y=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0),
        group=(1, 1, 2, 1, 2, 3, 1),
    )
    table = with_panels(table, ["1", "1", "1", "2", "2", "2", "2"])
    dodged = position("dodge2", preserve="single").compute_layer(table)
    assert values_of(dodged, "x") == pytest.approx(
        [1.0, 1.85, 2.15, 0.7, 1.0, 1.3, 2.0], abs=TOLERANCE
    )
    assert values_of(dodged, "xmin") == pytest.approx(
        [0.865, 1.715, 2.015, 0.565, 0.865, 1.165, 1.865], abs=TOLERANCE
    )
    assert values_of(dodged, "xmax") == pytest.approx(
        [1.135, 1.985, 2.285, 0.835, 1.135, 1.435, 2.135], abs=TOLERANCE
    )


def test_jitter_repeats_the_same_offsets_in_every_panel() -> None:
    """R 每个面板用同一个 seed 重抽 → 两面板的偏移相同（值与单一面板也相同）。"""
    table = points_table(panel=("1", "1", "2", "2"))
    jittered = position("jitter", seed=42, width=0.1, height=0.1).compute_layer(table)
    shift_x = np.asarray(values_of(jittered, "x")) - np.asarray(values_of(table, "x"))
    shift_y = np.asarray(values_of(jittered, "y")) - np.asarray(values_of(table, "y"))
    assert shift_x[0] == pytest.approx(shift_x[2], abs=TOLERANCE)
    assert shift_y[0] == pytest.approx(shift_y[2], abs=TOLERANCE)

    single = points_table(x=(1.0,), y=(1.0,), group=(1,), panel=("1",))
    once = position("jitter", seed=42, width=0.1, height=0.1).compute_layer(single)
    assert values_of(once, "x")[0] == pytest.approx(1.0 + shift_x[0], abs=TOLERANCE)


def test_nudge_is_layer_level_and_consumes_the_whole_vector() -> None:
    """nudge 在 R 里覆写 `compute_layer()`（不拆面板）；逐行向量按全层行号对齐。"""
    table = points_table(panel=("1", "1", "2", "2"))
    nudged = position("nudge", x=[0.1, 0.2, 0.3, 0.4]).compute_layer(table)
    assert values_of(nudged, "x") == pytest.approx([1.1, 1.2, 2.3, 2.4], abs=TOLERANCE)


# ---------------------------------------------------------------------------
# nudge：长度 1 的向量 / 图层参数（nudge_x / nudge_y）
# ---------------------------------------------------------------------------


def test_nudge_accepts_a_length_one_vector() -> None:
    """R 的 `position_nudge(x = c(0.2))` 与 `x = 0.2` 等价。"""
    assert position("nudge", x=[0.2], y=(1.0,)).compute_layer(bar_table()) == position(
        "nudge", x=0.2, y=1.0
    ).compute_layer(bar_table())


def test_nudge_rejects_a_vector_that_matches_neither_1_nor_nrow() -> None:
    with pytest.raises(BuildError, match="长度"):
        position("nudge", x=[0.1, 0.2, 0.3]).compute_layer(bar_table())


def test_nudge_layer_parameter_becomes_a_column() -> None:
    """R：`geom_col(nudge_x = 0.2, position = "nudge")` → x = 1.2 / 2.2。"""
    data = ColumnTable(
        [
            ("x", float_column([1.0, 2.0])),
            ("y", float_column([1.0, 2.0])),
        ]
    )
    built = build_plot(
        plot.ggplot(data, plot.aes(x="x", y="y")) + plot.geom_col(nudge_x=0.2, position="nudge")
    ).layers[0]
    assert values_of(built.data, "x") == pytest.approx([1.2, 2.2], abs=TOLERANCE)
    assert values_of(built.data, "xmin") == pytest.approx([0.75, 1.75], abs=TOLERANCE)
    assert "nudge_x" in built.data
    assert values_of(built.data, "nudge_x") == pytest.approx([0.2, 0.2], abs=TOLERANCE)


def test_pipeline_adds_the_nudge_default_aes_columns() -> None:
    """R：`geom_point(position = "nudge")` 的 `$data` 带 nudge_x = nudge_y = 0。"""
    data = ColumnTable(
        [
            ("x", float_column([1.0, 2.0])),
            ("y", float_column([1.0, 2.0])),
        ]
    )
    built = build_plot(
        plot.ggplot(data, plot.aes(x="x", y="y")) + plot.geom_point(position="nudge")
    ).layers[0]
    assert values_of(built.data, "nudge_x") == pytest.approx([0.0, 0.0], abs=TOLERANCE)
    assert values_of(built.data, "nudge_y") == pytest.approx([0.0, 0.0], abs=TOLERANCE)
    assert values_of(built.data, "x") == pytest.approx([1.0, 2.0], abs=TOLERANCE)


# ---------------------------------------------------------------------------
# dodge2 × geom_boxplot：varwidth 的 position 规则
# ---------------------------------------------------------------------------


def test_boxplot_varwidth_switches_to_dodge2_preserve_single() -> None:
    """R `geom_boxplot()`：`varwidth = TRUE` 时 position 换成 dodge2(preserve="single")。"""
    layer = plot.geom_boxplot(varwidth=True)
    assert layer.position.name == "dodge2"
    assert layer.position.params["preserve"] == "single"
    # 没写 varwidth 时仍是普通的 dodge2（preserve = "total"）。
    plain = plot.geom_boxplot()
    assert plain.position.name == "dodge2"
    assert plain.position.params.get("preserve", "total") == "total"


def test_boxplot_varwidth_warns_and_flips_an_explicit_preserve_total() -> None:
    layer = plot.position_dodge2(preserve="total")
    with pytest.warns(RuntimeWarning, match="varwidth"):
        built = plot.geom_boxplot(varwidth=True, position=layer)
    assert built.position.params["preserve"] == "single"
    # 显式给 preserve="single" 时不报警。
    explicit = plot.position_dodge2(preserve="single")
    assert (
        plot.geom_boxplot(varwidth=True, position=explicit).position.params["preserve"] == "single"
    )


def test_stack_with_mixed_panels_keeps_one_column_set() -> None:
    """A 面板 x 唯一、B 面板 x 重复：整层仍有 xmin/xmax，A 面板的值原样保留。"""
    table = bar_table(
        x=(1.0, 2.0, 1.0, 1.0),
        y=(1.0, 2.0, 3.0, 4.0),
        group=(1, 1, 1, 2),
    )
    table = with_panels(table, ["1", "1", "2", "2"])
    stacked = position("stack").compute_layer(table)
    # 两个面板都得有 xmin/xmax（上游 collide_setup() 对每个面板各补一次）。
    assert "xmin" in stacked and "xmax" in stacked
    assert values_of(stacked, "y") == pytest.approx([1.0, 2.0, 7.0, 4.0], abs=TOLERANCE)
    assert values_of(stacked, "ymin") == pytest.approx([0.0, 0.0, 4.0, 0.0], abs=TOLERANCE)
    assert values_of(stacked, "ymax") == pytest.approx([1.0, 2.0, 7.0, 4.0], abs=TOLERANCE)


def test_nudge_vector_stays_layer_level_in_the_pipeline() -> None:
    """nudge 是图层级实现：分面时逐行向量仍按全层行号对齐（R 同）。"""
    data = ColumnTable(
        [
            ("x", float_column([1.0, 2.0, 1.0, 2.0])),
            ("y", float_column([1.0, 2.0, 3.0, 4.0])),
            ("f", Column("str", np.array(["a", "a", "b", "b"], dtype=object))),
        ]
    )
    p = (
        plot.ggplot(data, plot.aes(x="x", y="y"))
        + plot.geom_point(position=plot.position_nudge(x=[0.1, 0.2, 0.3, 0.4]))
        + plot.facet_wrap(("f",))
    )
    built = build_plot(p).layers[0]
    assert values_of(built.data, "x") == pytest.approx([1.1, 2.2, 1.3, 2.4], abs=TOLERANCE)
    assert "nudge_x" in built.data


def test_dodge_orientation_y_accepts_a_table_without_x() -> None:
    """`orientation = "y"` 的必需美学校验看的是**翻转前**的 y 轴（上游同序）。"""
    table = ColumnTable(
        [
            ("y", float_column([1.0, 1.0, 2.0, 2.0])),
            ("PANEL", Column("str", np.full(4, "1", dtype=object))),
            ("group", Column("int", np.array([1.0, 2.0, 1.0, 2.0]))),
        ]
    )
    dodged = position("dodge", orientation="y").compute_layer(table)
    assert dodged.nrows == 4
    assert "order" in dodged
