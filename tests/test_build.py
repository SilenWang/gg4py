"""M1-3 图层流水线：六个阶段各一组单测 + 负向用例 + 空层 / 缺列 / 丢行。

口径见 `docs/notes/build.md`；R 对拍在 `tests/test_build_r_parity.py`。这里只
用内存里的小表，不依赖 R / pandas / ggplot2 数据。
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping

import numpy as np
import pytest

from ggcore.aes import after_stat
from ggcore.build import (
    STAGES,
    BuildError,
    BuildWarning,
    LayerBuild,
    MissingAesError,
    ScaleSet,
    build_layer,
    build_plot,
    compute_aesthetics,
    compute_position,
    compute_stat,
    map_statistic,
)
from ggcore.data import Column, ColumnTable
from ggcore.plot import aes, geom_bar, geom_histogram, geom_point, ggplot

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def table() -> ColumnTable:
    return ColumnTable(
        [
            ("displ", Column("float", np.array([1.8, 1.8, 2.0, 2.4, 3.0]))),
            ("hwy", Column("float", np.array([29.0, 29.0, 31.0, 30.0, 26.0]))),
            ("cyl", Column("float", np.array([4.0, 4.0, 4.0, 6.0, 8.0]))),
            (
                "class",
                Column("str", np.array(["compact", "compact", "compact", "midsize", "suv"])),
            ),
            ("drv", Column("str", np.array(["f", "f", "f", "f", "r"]))),
        ]
    )


def empty_table() -> ColumnTable:
    return ColumnTable(
        [
            ("displ", Column("float", np.zeros(0))),
            ("hwy", Column("float", np.zeros(0))),
        ],
        nrows=0,
    )


def layer_of(plot: ggplot) -> LayerBuild:
    return build_layer(plot, plot.layers[0], 0)


def values_of(table: ColumnTable, name: str) -> list:
    column = table.column(name)
    return column.values.tolist()


# ---------------------------------------------------------------------------
# 阶段 1：compute_aesthetics
# ---------------------------------------------------------------------------


def test_aesthetics_merge_layer_mapping_first_then_plot_mapping() -> None:
    plot = ggplot(table(), aes(x="displ")) + geom_point(mapping=aes(y="hwy", colour="class"))
    aesthetics = compute_aesthetics(plot, plot.layers[0]).table
    assert aesthetics.names == ("y", "colour", "x", "PANEL", "group")
    assert values_of(aesthetics, "PANEL") == ["1"] * 5
    assert values_of(aesthetics, "group") == [1.0, 1.0, 1.0, 2.0, 3.0]


def test_inherit_aes_false_uses_only_the_layer_mapping() -> None:
    plot = ggplot(table(), aes(x="displ")) + geom_point(aes(y="hwy"), inherit_aes=False)
    assert compute_aesthetics(plot, plot.layers[0]).table.names == ("y", "PANEL", "group")


def test_layer_data_takes_priority_over_plot_data() -> None:
    small = ColumnTable(
        [
            ("displ", Column("float", np.array([1.8, 2.0]))),
            ("hwy", Column("float", np.array([29.0, 31.0]))),
        ]
    )
    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point(data=small)
    assert compute_aesthetics(plot, plot.layers[0]).table.nrows == 2


def test_explicit_group_is_replaced_by_one_based_ids_in_place() -> None:
    plot = ggplot(table(), aes(x="displ", y="hwy", group="cyl")) + geom_point()
    aesthetics = compute_aesthetics(plot, plot.layers[0]).table
    assert aesthetics.names == ("x", "y", "group", "PANEL")
    assert values_of(aesthetics, "group") == [1.0, 1.0, 1.0, 2.0, 3.0]


def test_after_stat_is_deferred_not_evaluated() -> None:
    plot = ggplot(table(), aes(x="class", y=after_stat("count"))) + geom_bar()
    aesthetics = compute_aesthetics(plot, plot.layers[0])
    assert "y" not in aesthetics.table.names
    assert [name for name, _ in aesthetics.deferred] == ["y"]


def test_missing_column_in_layer_data_is_reported_by_name() -> None:
    plot = ggplot(table(), aes(x="nope")) + geom_point(aes(y="hwy"))
    with pytest.raises(ValueError, match="nope"):
        compute_aesthetics(plot, plot.layers[0])


# ---------------------------------------------------------------------------
# 阶段 2：compute_stat
# ---------------------------------------------------------------------------


def test_identity_stat_passes_aesthetics_through() -> None:
    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point()
    aesthetics = compute_aesthetics(plot, plot.layers[0])
    statistic = compute_stat(plot.layers[0], aesthetics)
    assert statistic == aesthetics.table
    assert statistic.names == ("x", "y", "PANEL", "group")


def test_count_stat_counts_per_x_and_order_is_fixed() -> None:
    plot = ggplot(table(), aes(x="class")) + geom_bar()
    statistics = compute_stat(plot.layers[0], compute_aesthetics(plot, plot.layers[0]))
    assert statistics.names == ("count", "prop", "x", "flipped_aes", "PANEL", "group")
    assert values_of(statistics, "count") == [3.0, 1.0, 1.0]
    assert values_of(statistics, "prop") == [1.0, 1.0, 1.0]
    assert values_of(statistics, "x") == ["compact", "midsize", "suv"]
    assert values_of(statistics, "flipped_aes") == [False, False, False]
    assert values_of(statistics, "group") == [1.0, 2.0, 3.0]


def test_count_stat_keeps_constant_aesthetics_and_orders_them_like_r() -> None:
    plot = ggplot(table(), aes(x="drv", fill="class")) + geom_bar()
    statistics = compute_stat(plot.layers[0], compute_aesthetics(plot, plot.layers[0]))
    assert statistics.names == (
        "count",
        "prop",
        "x",
        "flipped_aes",
        "fill",
        "PANEL",
        "group",
    )


def test_unimplemented_stat_is_rejected_not_silently_identity() -> None:
    plot = ggplot(table(), aes(x="displ")) + geom_histogram()
    aesthetics = compute_aesthetics(plot, plot.layers[0])
    with pytest.raises(BuildError, match="bin"):
        compute_stat(plot.layers[0], aesthetics)


# ---------------------------------------------------------------------------
# 阶段 3：map_statistic
# ---------------------------------------------------------------------------


def test_map_statistic_fills_y_from_count() -> None:
    plot = ggplot(table(), aes(x="class")) + geom_bar()
    aesthetics = compute_aesthetics(plot, plot.layers[0])
    mapped = map_statistic(plot.layers[0], compute_stat(plot.layers[0], aesthetics), aesthetics)
    assert mapped.names[-1] == "y"
    assert values_of(mapped, "y") == [3.0, 1.0, 1.0]


def test_user_after_stat_expression_wins_over_the_stat_default() -> None:
    from ggcore.aes import after_stat

    plot = ggplot(table(), aes(x="class", y=after_stat("count * 2"))) + geom_bar()
    aesthetics = compute_aesthetics(plot, plot.layers[0])
    mapped = map_statistic(plot.layers[0], compute_stat(plot.layers[0], aesthetics), aesthetics)
    assert values_of(mapped, "y") == [6.0, 2.0, 2.0]


def test_after_stat_with_unknown_variable_errors() -> None:
    from ggcore.aes import after_stat

    plot = ggplot(table(), aes(x="class", y=after_stat("nope"))) + geom_bar()
    aesthetics = compute_aesthetics(plot, plot.layers[0])
    with pytest.raises(BuildError, match="nope"):
        map_statistic(plot.layers[0], compute_stat(plot.layers[0], aesthetics), aesthetics)


# ---------------------------------------------------------------------------
# 阶段 4：compute_position
# ---------------------------------------------------------------------------


def test_identity_position_is_a_no_op() -> None:
    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point()
    layer = layer_of(plot)
    assert layer.positioned == layer.mapped


def test_stack_reverses_group_order_and_rewrites_y() -> None:
    plot = ggplot(table(), aes(x="drv", fill="class")) + geom_bar()
    layer = layer_of(plot)
    assert values_of(layer.positioned, "y") == [4.0, 1.0, 1.0]
    assert values_of(layer.positioned, "ymin") == [1.0, 0.0, 0.0]
    assert values_of(layer.positioned, "ymax") == [4.0, 1.0, 1.0]


def test_stack_without_duplicate_x_falls_back_to_identity() -> None:
    plot = ggplot(table(), aes(x="class")) + geom_bar()
    layer = layer_of(plot)
    assert layer.positioned.names == layer.mapped.names


def test_unimplemented_position_is_rejected() -> None:
    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point(position="dodge")
    aesthetics = compute_aesthetics(plot, plot.layers[0])
    mapped = map_statistic(plot.layers[0], compute_stat(plot.layers[0], aesthetics), aesthetics)
    with pytest.raises(BuildError, match="dodge"):
        compute_position(plot.layers[0], mapped)


# ---------------------------------------------------------------------------
# 阶段 5：map_scales
# ---------------------------------------------------------------------------


def test_discrete_position_maps_to_one_based_codes() -> None:
    plot = ggplot(table(), aes(x="class")) + geom_bar()
    layer = layer_of(plot)
    assert values_of(layer.scaled, "x") == [1.0, 2.0, 3.0]


def test_continuous_position_values_pass_through() -> None:
    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point()
    layer = layer_of(plot)
    assert values_of(layer.scaled, "x") == values_of(layer.aesthetics, "x")


def test_pipeline_calls_the_scale_set_instead_of_hardcoding() -> None:
    class Doubling(ScaleSet):
        def map(self, values, aesthetic):
            if aesthetic == "x":
                return np.asarray(values.values, dtype=np.float64) * 2.0
            return super().map(values, aesthetic)

    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point()
    layer = build_layer(plot, plot.layers[0], 0, Doubling())
    assert values_of(layer.scaled, "x") == [3.6, 3.6, 4.0, 4.8, 6.0]


def test_bad_scale_output_is_rejected() -> None:
    class Broken(ScaleSet):
        def map(self, values, aesthetic):
            if aesthetic == "x":
                return np.zeros((2, 2))
            return super().map(values, aesthetic)

    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point()
    with pytest.raises(BuildError, match="1 维"):
        build_layer(plot, plot.layers[0], 0, Broken())


def test_build_plot_trains_one_scale_set_for_all_layers() -> None:
    plot = ggplot(table(), aes(x="class")) + geom_bar() + geom_bar(aes(x="drv"))
    build = build_plot(plot)
    assert build.scales.trained["x"] == (
        "compact",
        "midsize",
        "suv",
        "f",
        "r",
    )
    assert values_of(build.layers[1].scaled, "x") == [4.0, 5.0]


# ---------------------------------------------------------------------------
# 阶段 6：finish
# ---------------------------------------------------------------------------


def test_defaults_are_appended_in_upstream_order() -> None:
    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point()
    assert layer_of(plot).data.names == (
        "x",
        "y",
        "PANEL",
        "group",
        "shape",
        "colour",
        "fill",
        "size",
        "alpha",
        "stroke",
    )


def test_bar_finish_derives_anchors_and_bounds() -> None:
    plot = ggplot(table(), aes(x="class")) + geom_bar()
    data = layer_of(plot).data
    assert data.names[:11] == (
        "count",
        "prop",
        "x",
        "flipped_aes",
        "PANEL",
        "group",
        "y",
        "ymin",
        "ymax",
        "xmin",
        "xmax",
    )
    assert values_of(data, "ymin") == [0.0, 0.0, 0.0]
    assert values_of(data, "ymax") == [3.0, 1.0, 1.0]
    assert values_of(data, "xmin") == [0.55, 1.55, 2.55]
    assert values_of(data, "xmax") == [1.45, 2.45, 3.45]


def test_missing_required_aes_errors_with_the_group_name() -> None:
    plot = ggplot(table(), aes(x="displ")) + geom_point()
    with pytest.raises(MissingAesError, match="y"):
        layer_of(plot)


def test_all_rows_dropped_is_an_empty_layer_with_counts() -> None:
    table_all_missing = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0]))),
            (
                "y",
                Column("float", np.array([0.0, 0.0]), na_mask=np.array([True, True])),
            ),
        ]
    )
    plot = ggplot(table_all_missing, aes(x="x", y="y")) + geom_point()
    with pytest.warns(BuildWarning, match="2 行"):
        build = build_plot(plot)
    assert build.empty_layers == (0,)
    assert build.layers[0].data.nrows == 0
    assert dict(build.layers[0].dropped_missing) == {"y": 2}


def test_non_column_table_data_points_at_the_boundary_converter() -> None:
    plot = ggplot({"x": [1.0, 2.0]}, aes(x="x", y="x")) + geom_point()
    with pytest.raises(BuildError, match=r"ggio\.frame\.to_column_table"):
        build_layer(plot, plot.layers[0])


def test_empty_layer_is_recorded_not_silently_dropped() -> None:
    plot = ggplot(empty_table(), aes(x="displ", y="hwy")) + geom_point()
    build = build_plot(plot)
    assert build.empty_layers == (0,)
    assert build.layers[0].empty is True
    assert build.layers[0].data.nrows == 0


# ---------------------------------------------------------------------------
# 跨阶段：缺失去重计数、确定性、阶段可枚举
# ---------------------------------------------------------------------------


def _table_with_missing() -> ColumnTable:
    return ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0]))),
            (
                "y",
                Column(
                    "float",
                    np.array([10.0, 0.0, 30.0]),
                    na_mask=np.array([False, True, False]),
                ),
            ),
        ]
    )


def test_missing_values_drop_rows_and_are_counted_per_column() -> None:
    plot = ggplot(_table_with_missing(), aes(x="x", y="y")) + geom_point()
    with pytest.warns(BuildWarning, match="1 行"):
        layer = layer_of(plot)
    assert layer.aesthetics.nrows == 2
    assert dict(layer.dropped_missing) == {"y": 1}
    assert values_of(layer.data, "y") == [10.0, 30.0]


def test_na_rm_true_is_silent_but_still_counted() -> None:
    plot = ggplot(_table_with_missing(), aes(x="x", y="y")) + geom_point(na_rm=True)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        layer = layer_of(plot)
    assert not [item for item in caught if issubclass(item.category, BuildWarning)]
    assert dict(layer.dropped_missing) == {"y": 1}


def test_build_is_deterministic() -> None:
    def digest(build: LayerBuild) -> tuple:
        return tuple(
            (name, column.kind, column.values.tobytes(), column.na_mask.tobytes(), column.levels)
            for name, column in zip(build.data.names, build.data.columns(), strict=True)
        )

    plot = ggplot(table(), aes(x="drv", fill="class")) + geom_bar()
    assert digest(layer_of(plot)) == digest(layer_of(plot))


def test_every_stage_is_separately_addressable() -> None:
    plot = ggplot(table(), aes(x="class")) + geom_bar()
    layer = layer_of(plot)
    assert tuple(layer.stages) == STAGES
    assert all(isinstance(item, ColumnTable) for item in layer.stages.values())
    assert isinstance(layer.dropped_missing, Mapping)
