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
from ggcore.plot import (
    aes,
    geom_bar,
    geom_col,
    geom_histogram,
    geom_line,
    geom_path,
    geom_point,
    ggplot,
)

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


def test_bin_stat_is_the_default_for_geom_histogram() -> None:
    # geom_histogram 的缺省 stat 就是 bin：数据只有 x，五个 count 类变量全由 stat 产。
    plot = ggplot(table(), aes(x="displ")) + geom_histogram(bins=5)
    statistics = compute_stat(plot.layers[0], compute_aesthetics(plot, plot.layers[0]))
    assert statistics.names[:8] == (
        "count",
        "x",
        "xmin",
        "xmax",
        "width",
        "density",
        "ncount",
        "ndensity",
    )
    assert statistics.names[-3:] == ("flipped_aes", "PANEL", "group")
    assert statistics.column("count").size == 5


def test_unimplemented_stat_is_rejected_not_silently_identity() -> None:
    # M1-8 / M2-6 之后 bin / boxplot / smooth / align / ecdf / contour … 都是真的；
    # 没登记过的 stat 名仍然报错并列出已实现的 stat，不静默当成 identity。
    # 用不存在的名字而不是「某个还没实现的 stat」：后者会随并行 PR 合入而假红。
    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point(stat="not_a_stat")
    aesthetics = compute_aesthetics(plot, plot.layers[0])
    with pytest.raises(BuildError, match="not_a_stat"):
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


def test_stack_without_duplicate_x_does_not_restack() -> None:
    plot = ggplot(table(), aes(x="class")) + geom_bar()
    layer = layer_of(plot)
    # 没有重复 x 时 position 不再累加；ymin/ymax 是 geom setup 的锚点（0 / y）。
    assert values_of(layer.positioned, "y") == values_of(layer.mapped, "y")
    assert values_of(layer.positioned, "ymin") == [0.0, 0.0, 0.0]
    assert values_of(layer.positioned, "ymax") == [3.0, 1.0, 1.0]


def test_unknown_position_is_rejected() -> None:
    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point(position="sparkle")
    aesthetics = compute_aesthetics(plot, plot.layers[0])
    mapped = map_statistic(plot.layers[0], compute_stat(plot.layers[0], aesthetics), aesthetics)
    with pytest.raises(BuildError, match="sparkle"):
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
    # 注意：`ScaleSet.map` 会被 `map_position()` 与阶段 5 各调一次，所以自定义
    # map **必须幂等**（这个常量映射就是幂等的；累加 / 有状态的映射不行）。
    class Constant(ScaleSet):
        def map(self, values, aesthetic):
            if aesthetic == "x":
                return np.full(values.size, 7.0)
            return super().map(values, aesthetic)

    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point()
    layer = build_layer(plot, plot.layers[0], 0, Constant())
    assert values_of(layer.scaled, "x") == [7.0] * 5
    assert values_of(layer.data, "x") == [7.0] * 5


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
    """多层离散 x 按上游口径**全局排序**，不是「先遇到先保留」。"""
    plot = ggplot(table(), aes(x="class")) + geom_bar() + geom_bar(aes(x="drv"))
    build = build_plot(plot)
    assert build.scales.trained["x"] == ("compact", "f", "midsize", "r", "suv")
    assert values_of(build.layers[0].scaled, "x") == [1.0, 3.0, 5.0]
    assert values_of(build.layers[1].scaled, "x") == [2.0, 4.0]


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


def test_all_missing_values_still_keep_every_row() -> None:
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
    layer = layer_of(plot)
    assert layer.empty is False
    assert layer.data.nrows == 2
    assert dict(layer.dropped_missing) == {"y": 2}
    assert layer.data.column("y").na_mask.tolist() == [True, True]


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


def test_missing_values_are_counted_but_rows_are_kept() -> None:
    """ggplot2 4.0.3 的 `$data` 保留 NA 行；删除在绘制期 `handle_na()`。"""
    plot = ggplot(_table_with_missing(), aes(x="x", y="y")) + geom_point()
    layer = layer_of(plot)
    assert layer.aesthetics.nrows == 3
    assert dict(layer.dropped_missing) == {"y": 1}
    assert layer.data.nrows == 3
    assert layer.data.column("y").na_mask.tolist() == [False, True, False]
    assert values_of(layer.data, "y") == [10.0, 0.0, 30.0]


def test_na_rm_does_not_change_the_built_data() -> None:
    plot = ggplot(_table_with_missing(), aes(x="x", y="y")) + geom_point(na_rm=True)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        layer = layer_of(plot)
    assert not [item for item in caught if issubclass(item.category, BuildWarning)]
    assert layer.data.nrows == 3
    assert dict(layer.dropped_missing) == {"y": 1}


def test_build_is_deterministic() -> None:
    def digest(build: LayerBuild) -> tuple:
        return tuple(
            (name, column.kind, column.values.tobytes(), column.na_mask.tobytes(), column.levels)
            for name, column in zip(build.data.names, build.data.columns(), strict=True)
        )

    plot = ggplot(table(), aes(x="drv", fill="class")) + geom_bar()
    assert digest(layer_of(plot)) == digest(layer_of(plot))


def test_na_colour_rows_are_kept_and_grouped_like_r() -> None:
    """`colour = NA` 的行保留、NA 也是一个 group 水平（R: group 1,2,3,1,2）。"""
    table_na = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0, 5.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0, 4.0, 5.0]))),
            (
                "g",
                Column(
                    "str",
                    np.array(["a", "b", "", "a", "b"]),
                    na_mask=np.array([False, False, True, False, False]),
                ),
            ),
        ]
    )
    plot = ggplot(table_na, aes(x="x", y="y", colour="g")) + geom_point()
    layer = layer_of(plot)
    assert layer.data.nrows == 5
    assert values_of(layer.data, "group") == [1.0, 2.0, 3.0, 1.0, 2.0]
    # M1-4 起 colour 走真实的离散标度：NA 落成 na.value（默认 "grey50"），
    # 与 R 的 `ggplot_build()$data[[1]]$colour` 一致（见 build fixture 的
    # point_na_colour）；行保留、缺失计数仍是 1。
    assert layer.data.column("colour").values.tolist() == [
        "#F8766D",
        "#00BFC4",
        "grey50",
        "#F8766D",
        "#00BFC4",
    ]
    assert not layer.data.column("colour").na_mask.any()
    assert dict(layer.dropped_missing) == {"colour": 1}


def test_discrete_na_gets_the_last_position() -> None:
    """离散位置的 NA 占最后一个水平（上游 sort(unique(), na.last = TRUE)）。"""
    table_na = ColumnTable(
        [
            (
                "xs",
                Column(
                    "str",
                    np.array(["a", "b", "a", "c", "", "b"]),
                    na_mask=np.array([False, False, False, False, True, False]),
                ),
            )
        ]
    )
    plot = ggplot(table_na, aes(x="xs")) + geom_bar()
    layer = layer_of(plot)
    assert values_of(layer.aesthetics, "x") == [1.0, 2.0, 1.0, 3.0, 4.0, 2.0]
    assert values_of(layer.data, "x") == [1.0, 2.0, 3.0, 4.0]


def test_count_stat_gives_na_x_its_own_bar() -> None:
    table_na = ColumnTable(
        [
            (
                "xs",
                Column(
                    "str",
                    np.array(["a", "b", "a", "c", "", "b"]),
                    na_mask=np.array([False, False, False, False, True, False]),
                ),
            )
        ]
    )
    plot = ggplot(table_na, aes(x="xs")) + geom_bar()
    data = layer_of(plot).data
    assert data.nrows == 4
    assert values_of(data, "count") == [2.0, 2.0, 1.0, 1.0]
    assert values_of(data, "x") == [1.0, 2.0, 3.0, 4.0]


def test_geom_params_override_default_aes() -> None:
    plot = ggplot(table(), aes(x="displ", y="hwy")) + geom_point(colour="red", size=3)
    data = layer_of(plot).data
    assert values_of(data, "colour") == ["red"] * 5
    assert values_of(data, "size") == [3.0] * 5
    # 参数不改变列序：default_aes 的键序仍然决定位置。
    assert data.names == (
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


def test_geom_width_param_reaches_data_and_anchors() -> None:
    plot = ggplot(table(), aes(x="class", y="displ")) + geom_col(width=0.3)
    data = layer_of(plot).data
    assert values_of(data, "width") == [0.3, 0.3, 0.3, 0.3, 0.3]
    assert values_of(data, "xmin") == [0.85, 0.85, 0.85, 1.85, 2.85]


def test_flipped_aes_and_anchors_are_added_before_position() -> None:
    """上游 setup_data() 在 compute_position() 之前：列序是 flipped_aes → 锚点。"""
    plot = ggplot(table(), aes(x="class", y="displ")) + geom_col()
    data = layer_of(plot).data
    assert data.names[:10] == (
        "x",
        "y",
        "PANEL",
        "group",
        "flipped_aes",
        "ymin",
        "ymax",
        "xmin",
        "xmax",
        "colour",
    )


def test_line_rows_are_sorted_by_panel_group_x() -> None:
    table_line = ColumnTable(
        [
            ("x", Column("float", np.array([3.0, 1.0, 2.0, 1.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("g", Column("str", np.array(["a", "a", "a", "b"]))),
        ]
    )
    plot = ggplot(table_line, aes(x="x", y="y", group="g")) + geom_line()
    layer = layer_of(plot)
    assert values_of(layer.positioned, "x") == [1.0, 2.0, 3.0, 1.0]
    assert values_of(layer.positioned, "y") == [2.0, 3.0, 1.0, 4.0]
    assert values_of(layer.positioned, "group") == [1.0, 1.0, 1.0, 2.0]
    assert "flipped_aes" in layer.positioned.names


def test_path_keeps_the_given_row_order() -> None:
    table_line = ColumnTable(
        [
            ("x", Column("float", np.array([3.0, 1.0, 2.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0]))),
        ]
    )
    plot = ggplot(table_line, aes(x="x", y="y")) + geom_path()
    layer = layer_of(plot)
    assert values_of(layer.positioned, "x") == [3.0, 1.0, 2.0]
    assert "flipped_aes" not in layer.positioned.names


def test_categorical_levels_drive_group_ids() -> None:
    """factor levels 反序时 group 跟 levels 走（R: group 1,2,1）。"""
    table_cat = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("g", Column("categorical", np.array([0, 1, 0]), levels=("b", "a"))),
        ]
    )
    plot = ggplot(table_cat, aes(x="x", y="y", colour="g")) + geom_point()
    assert values_of(layer_of(plot).data, "group") == [1.0, 2.0, 1.0]


def test_categorical_levels_drive_position_codes() -> None:
    table_cat = ColumnTable(
        [
            ("g", Column("categorical", np.array([1, 0, 1]), levels=("b", "a"))),
        ]
    )
    plot = ggplot(table_cat, aes(x="g")) + geom_bar()
    layer = layer_of(plot)
    # code 0 = "b"、1 = "a"；levels 是 ("b", "a")，所以 b → 1、a → 2。
    assert values_of(layer.aesthetics, "x") == [2.0, 1.0, 2.0]


def test_logical_position_uses_false_before_true() -> None:
    table_bool = ColumnTable(
        [
            ("x", Column("bool", np.array([True, False, True]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0]))),
        ]
    )
    plot = ggplot(table_bool, aes(x="x", y="y")) + geom_point()
    layer = layer_of(plot)
    assert values_of(layer.scaled, "x") == [2.0, 1.0, 2.0]
    assert layer.scaled.column("x").kind == "float"


@pytest.mark.parametrize(
    ("values", "levels"),
    [
        ([True, True], ("True",)),
        ([False, False], ("False",)),
    ],
)
def test_logical_position_single_level_maps_to_code_one(
    values: list[bool], levels: tuple[str, ...]
) -> None:
    """单水平 bool：水平只有它自己，map 全是 1（R: `scale_x_discrete()` train
    `c(TRUE, TRUE)` → limits `TRUE`、map `1, 1`；`c(FALSE, FALSE)` 同理）。

    区别只在**没有**把 `("False", "True")` 无条件 seed 进离散标度：一旦 seed，
    单水平 bool 也会变成两个水平、code 落在 2 上。
    """
    table_bool = ColumnTable(
        [
            ("x", Column("bool", np.array(values))),
            ("y", Column("float", np.arange(1.0, len(values) + 1))),
        ]
    )
    build = build_plot(ggplot(table_bool, aes(x="x", y="y")) + geom_point())
    assert build.scales.trained["x"] == levels
    assert build.scales.limits("x") == levels
    assert values_of(build.layers[0].scaled, "x") == [1.0] * len(values)


def test_categorical_levels_only_keep_observed_levels() -> None:
    """factor levels = ("c", "b", "a") 只出现 b / a：位置 1,2、trained ("b", "a")。"""
    table_partial = ColumnTable(
        [
            ("g", Column("categorical", np.array([1, 2]), levels=("c", "b", "a"))),
            ("y", Column("float", np.array([1.0, 2.0]))),
        ]
    )
    build = build_plot(ggplot(table_partial, aes(x="g", y="y")) + geom_point())
    assert values_of(build.layers[0].scaled, "x") == [1.0, 2.0]
    assert build.scales.trained["x"] == ("b", "a")
    assert build.scales.levels("x") == ("b", "a")


def test_constant_aes_params_materialize_required_columns() -> None:
    plot = ggplot(table()) + geom_point(x=1, y=2)
    data = layer_of(plot).data
    assert values_of(data, "x") == [1.0] * 5
    assert values_of(data, "y") == [2.0] * 5


def test_stack_negative_values_use_adjacent_cumulative_heights() -> None:
    """负值 stack：ymin/ymax 是相邻累计高度的 min/max（R pos_stack 口径）。"""
    table_neg = ColumnTable(
        [
            ("g", Column("str", np.array(["p", "p", "p", "p", "q", "q", "q", "q"]))),
            (
                "x",
                Column("str", np.array(["one", "two", "one", "two", "one", "two", "one", "two"])),
            ),
            ("y", Column("float", np.array([3.0, -2.0, 1.0, 4.0, -1.0, 2.0, 5.0, -3.0]))),
        ]
    )
    plot = ggplot(table_neg, aes(x="x", y="y", fill="g")) + geom_col()
    data = layer_of(plot).data
    assert values_of(data, "y") == [8.0, -3.0, 9.0, 6.0, 0.0, 2.0, 5.0, 0.0]
    assert values_of(data, "ymin") == [5.0, -5.0, 8.0, 2.0, -1.0, 0.0, 0.0, -3.0]
    assert values_of(data, "ymax") == [8.0, -3.0, 9.0, 6.0, 0.0, 2.0, 5.0, 0.0]
    assert values_of(data, "group") == [1.0, 3.0, 1.0, 3.0, 2.0, 4.0, 2.0, 4.0]


def test_stack_na_y_keeps_coordinates_and_zero_height() -> None:
    """NA y 行：保留 x / 坐标，ymin == ymax（零高度），不复制 R 的 x→NA artifact。"""
    table_na = ColumnTable(
        [
            ("xs", Column("str", np.array(["a", "b", "a"]))),
            (
                "ys",
                Column("float", np.array([1.0, 0.0, 3.0]), na_mask=np.array([False, True, False])),
            ),
        ]
    )
    plot = ggplot(table_na, aes(x="xs", y="ys")) + geom_col()
    data = layer_of(plot).data
    assert values_of(data, "x") == [1.0, 2.0, 1.0]
    assert values_of(data, "y") == [1.0, 0.0, 4.0]
    assert values_of(data, "ymin") == [0.0, 0.0, 1.0]
    assert values_of(data, "ymax") == [1.0, 0.0, 4.0]


def test_every_stage_is_separately_addressable() -> None:
    plot = ggplot(table(), aes(x="class")) + geom_bar()
    layer = layer_of(plot)
    assert tuple(layer.stages) == STAGES
    assert all(isinstance(item, ColumnTable) for item in layer.stages.values())
    assert isinstance(layer.dropped_missing, Mapping)
