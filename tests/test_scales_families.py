"""M2-4 A：连续 / 分箱 / 渐变 / 日期时间标度的族级回归。

R 对拍在 `tests/test_scales_r_parity.py`（夹具 53 个 case）；这里守三件夹具
覆盖不到的事：

1. **导出齐全**：A 段的 70 个 `scale_*` 全部在注册表里，`color_*` 是
   `colour_*` 的别名；
2. **每个导出都能进入 build**（issue 验收第一条）——`p.scale_<name>()` 后
   `build_plot()` 不炸、不静默丢映射；
3. 分箱族的三件套（分箱边界 / 每箱颜色 / 图例断点）与日期时间的
   `date_breaks` / `date_labels` / `date_minor_breaks` 的语义。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ggcore.build import build_plot
from ggcore.components import Scale
from ggcore.data import Column, ColumnTable
from ggcore.plot import aes, ggplot
from ggcore.registry import geom_point, registered, scale_x_binned
from ggcore.scales import brewer_pal, colour_ramp, pretty_breaks, scale_from_component
from ggcore.scales_date import parse_unit_spec, pretty_date

A_EXPORTS = frozenset(
    # 位置：continuous / log10 / sqrt / reverse / binned / date / datetime / time
    {
        f"{axis}_{kind}"
        for axis in ("x", "y")
        for kind in (
            "continuous",
            "log10",
            "sqrt",
            "reverse",
            "binned",
            "date",
            "datetime",
            "time",
        )
    }
    # colour / color / fill：12 个族 × 3 个名字
    | {
        f"{prefix}_{kind}"
        for prefix in ("colour", "color", "fill")
        for kind in (
            "continuous",
            "binned",
            "gradient",
            "gradient2",
            "gradientn",
            "steps",
            "steps2",
            "stepsn",
            "date",
            "datetime",
            "distiller",
            "fermenter",
        )
    }
    # 其它美学的连续侧
    | {
        "alpha",
        "alpha_continuous",
        "alpha_binned",
        "alpha_date",
        "alpha_datetime",
        "size",
        "size_continuous",
        "size_area",
        "size_binned",
        "size_binned_area",
        "size_date",
        "size_datetime",
        "radius",
        "linewidth",
        "linewidth_continuous",
        "linewidth_binned",
        "linewidth_date",
        "linewidth_datetime",
    }
)

#: `gradientn` / `stepsn` 在上游没有默认 colours（构造时报错是对的）。
REQUIRED = {"colours": ("#0000FF", "#FFFFFF", "#FF0000")}


def _required(name: str) -> dict:
    return dict(REQUIRED) if name.endswith(("gradientn", "stepsn")) else {}


def _build(name: str, aesthetic: str = "colour", **params):
    merged = {**_required(name), **params}
    return scale_from_component(Scale(name, aesthetic, merged))


def _column(values) -> Column:
    missing = np.array([value is None for value in values], dtype=bool)
    data = np.array([0.0 if value is None else float(value) for value in values])
    return Column("float", data, na_mask=missing)


def _trained(name: str, inputs, aesthetic: str = "colour", **params):
    scale = _build(name, aesthetic, **params)
    scale.train(scale.transform(_column(inputs)))
    return scale


def _table() -> ColumnTable:
    return ColumnTable(
        [
            ("x", Column("float", np.arange(1.0, 13.0))),
            ("y", Column("float", np.arange(2.0, 14.0))),
            ("v", Column("float", np.linspace(0.0, 1.0, 12))),
        ]
    )


# ---------------------------------------------------------------------------
# 导出齐全 + 别名
# ---------------------------------------------------------------------------


def test_scope_a_exports_are_registered() -> None:
    registered_scales = set(registered("scale"))
    assert len(A_EXPORTS) == 70
    assert A_EXPORTS <= registered_scales
    # A 段新增 64 个名字（M1-4 的 15 个里 10 个属于 A、5 个属于 B）。
    # 合并 M2-4 B 段（#53）后注册表是 A ∪ B：129 个名字，无重复、无丢失。
    assert len(registered_scales) == 129


def test_color_alias_matches_colour() -> None:
    for suffix in ("continuous", "binned", "gradient2", "steps", "distiller"):
        colour = _trained(f"colour_{suffix}", [0.0, 0.5, 1.0])
        color = _trained(f"color_{suffix}", [0.0, 0.5, 1.0])
        assert (
            colour.map(_column([0.0, 0.5, 1.0])).values.tolist()
            == color.map(_column([0.0, 0.5, 1.0])).values.tolist()
        )
        assert type(colour) is type(color)


@pytest.mark.parametrize("name", sorted(A_EXPORTS))
def test_every_export_enters_build(name: str) -> None:
    """每个 A 导出都能 `p.scale_<name>()` 并跑完 build（不画图）。"""
    plot = ggplot(_table(), aes(x="x", y="y", colour="v", fill="v")) + geom_point()
    method = getattr(plot, f"scale_{name}")
    plot = method(**_required(name))
    built = build_plot(plot)
    assert built.layers, name
    assert built.panels, name


# ---------------------------------------------------------------------------
# 分箱族：边界 / 每箱颜色 / 图例断点
# ---------------------------------------------------------------------------


def test_binned_colour_exposes_edges_bin_values_and_breaks() -> None:
    scale = _trained("colour_steps", [0.0, 1.0], breaks=[0.25, 0.5, 0.75])
    info = scale.bins()
    assert info["edges"] == (0.0, 0.25, 0.5, 0.75, 1.0)
    assert info["breaks"] == (0.25, 0.5, 0.75)
    assert len(info["values"]) == 4  # 4 箱
    assert all(str(value).startswith("#") for value in info["values"])

    mapped = scale.map(_column([0.0, 0.2, 0.5, 1.0])).values.tolist()
    values = list(info["values"])
    assert mapped == [values[0], values[0], values[1], values[3]]


def test_binned_position_maps_to_bin_centres_after_stat() -> None:
    """第一次 map 是箱号（stat 用），build 的第二段换回箱中心。"""
    scale = _trained("x_binned", list(range(1, 11)), aesthetic="x")
    codes = scale.map(_column([1.0, 2.0, 3.0, 10.0])).values.tolist()
    assert codes == [1.0, 1.0, 2.0, 9.0]

    table = ColumnTable(
        [
            ("x", Column("float", np.arange(1.0, 11.0))),
            ("y", Column("float", np.arange(10.0))),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y")) + geom_point() + scale_x_binned()
    built = build_plot(plot)
    assert built.layers[0].aesthetics.column("x").values.tolist()[:3] == [1.0, 1.0, 2.0]
    assert built.layers[0].data.column("x").values.tolist()[:3] == [1.5, 1.5, 2.5]


def test_binned_scale_default_oob_is_squish() -> None:
    scale = _trained("colour_steps", [0.0, 1.0], limits=[0.25, 0.75])
    # limits 之外的 0 / 1 被 squish 进最外两箱，不是 NA。
    mapped = scale.map(_column([0.0, 0.5, 1.0]))
    assert not mapped.na_mask.any()


def test_binned_size_and_alpha_are_monotone() -> None:
    size = _trained("size_binned", [0.0, 4.0], aesthetic="size")
    values = size.map(_column([0.0, 1.0, 2.0, 3.0, 4.0])).values.tolist()
    assert values == sorted(values)
    assert all(1.0 <= value <= 6.0 for value in values)

    alpha = _trained("alpha_binned", [0.0, 1.0], aesthetic="alpha")
    alphas = alpha.map(_column([0.0, 0.5, 1.0])).values.tolist()
    assert alphas == sorted(alphas)
    assert all(0.1 <= value <= 1.0 for value in alphas)


# ---------------------------------------------------------------------------
# 渐变族
# ---------------------------------------------------------------------------


def test_gradient2_puts_midpoint_at_half() -> None:
    scale = _trained("colour_gradient2", [-1.0, 1.0])
    assert scale.map(_column([0.0])).values.tolist() == ["#FFFFFF"]
    low = scale.map(_column([-1.0])).values.tolist()[0]
    high = scale.map(_column([1.0])).values.tolist()[0]
    assert low == "#832424"  # scales::muted("red")
    assert high == "#3A3A98"  # scales::muted("blue")


def test_gradientn_values_place_colour_stops() -> None:
    scale = _trained(
        "colour_gradientn",
        [0.0, 1.0],
        colours=("#0000FF", "#FFFFFF", "#FF0000"),
        values=(0.0, 0.4, 1.0),
    )
    assert scale.map(_column([0.0])).values.tolist() == ["#0000FF"]
    assert scale.map(_column([0.4])).values.tolist() == ["#FFFFFF"]
    assert scale.map(_column([1.0])).values.tolist() == ["#FF0000"]


def test_distiller_and_fermenter_use_brewer_tables() -> None:
    distiller = _trained("colour_distiller", [0.0, 1.0], palette="Spectral")
    spectral = list(brewer_pal("div", "Spectral", -1)(7))
    assert distiller.map(_column([0.0])).values.tolist() == [spectral[0]]  # direction = -1
    assert distiller.map(_column([1.0])).values.tolist() == [spectral[-1]]

    fermenter = _trained("colour_fermenter", [0.0, 1.0], palette="Spectral", n_breaks=4)
    info = fermenter.bins()
    assert all(str(value).startswith("#") for value in info["values"])
    assert len(info["values"]) == len(info["edges"]) - 1


def test_brewer_pal_matches_r_direction_and_overflow() -> None:
    assert brewer_pal("seq", "Blues", 1)(3) == ["#DEEBF7", "#9ECAE1", "#3182BD"]
    assert brewer_pal("seq", "Blues", -1)(3) == ["#3182BD", "#9ECAE1", "#DEEBF7"]
    # n 超过 maxcolors：RColorBrewer 只给 maxcolors 个，多出来的是 NA。
    overflow = brewer_pal("seq", "Blues", 1)(10)
    assert len(overflow) == 10
    assert overflow[-1] is None  # Blues 的 maxcolors = 9


# ---------------------------------------------------------------------------
# 日期时间
# ---------------------------------------------------------------------------


def test_date_breaks_and_labels_follow_strftime() -> None:
    scale = _trained(
        "x_date",
        [18276.0, 18599.0],  # 2020-01-15 .. 2020-12-03
        aesthetic="x",
        date_breaks="2 months",
        date_labels="%Y-%m",
        expand=[0, 0],
    )
    assert scale.labels() == (
        None,
        "2020-03",
        "2020-05",
        "2020-07",
        "2020-09",
        "2020-11",
        None,
    )


def test_date_minor_breaks() -> None:
    scale = _trained(
        "x_date",
        [18262.0, 18444.0],  # 2020-01-01 .. 2020-07-01
        aesthetic="x",
        date_breaks="2 months",
        date_minor_breaks="1 month",
        expand=[0, 0],
    )
    minor = scale.minor_breaks()
    assert minor, "date_minor_breaks 没生成次断点"
    assert minor == tuple(sorted(minor))


def test_time_scale_uses_hms_labels() -> None:
    scale = _trained(
        "x_time",
        [0.0, 3600.0],
        aesthetic="x",
        date_breaks="15 min",
        date_labels="%H:%M:%S",
        expand=[0, 0],
    )
    assert scale.breaks() == (0.0, 900.0, 1800.0, 2700.0, 3600.0)
    assert scale.labels() == (
        "00:00:00",
        "00:15:00",
        "00:30:00",
        "00:45:00",
        "01:00:00",
    )


def test_pretty_date_matches_r_calendar_steps() -> None:
    values, fmt = pretty_date([18239.4, 18824.6])
    assert values == [18078.0, 18262.0, 18444.0, 18628.0, 18809.0, 18993.0]
    assert fmt == "%Y-%m"
    assert pretty_breaks(1, 7) == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)


def test_parse_unit_spec_shapes() -> None:
    assert parse_unit_spec("2 months") == (2.0, "month")
    assert parse_unit_spec("week") == (1.0, "week")
    with pytest.raises(ValueError):
        parse_unit_spec("")


# ---------------------------------------------------------------------------
# size / alpha / linewidth 连续侧
# ---------------------------------------------------------------------------


def test_size_area_uses_max_size_and_absolute_scale() -> None:
    area = _trained("size_area", [1.0, 2.0, 3.0, 4.0], aesthetic="size", max_size=8)
    assert area.map(_column([1.0, 4.0])).values.tolist() == pytest.approx([4.0, 8.0])

    radius = _trained("radius", [1.0, 4.0], aesthetic="size")
    assert radius.map(_column([1.0, 2.0, 4.0])).values.tolist() == pytest.approx(
        [1.0, 1.0 + 5.0 / 3.0, 6.0]
    )


def test_linewidth_default_range_is_one_to_six() -> None:
    scale = _trained("linewidth_continuous", [1.0, 4.0], aesthetic="linewidth")
    assert scale.map(_column([1.0, 4.0])).values.tolist() == pytest.approx([1.0, 6.0])

    binned = _trained("linewidth_binned", [1.0, 4.0], aesthetic="linewidth")
    values = binned.map(_column([1.0, 2.0, 3.0, 4.0])).values.tolist()
    assert values == sorted(values)
    assert all(1.0 <= value <= 6.0 for value in values)


def test_colour_ramp_is_lab_piecewise() -> None:
    ramp = colour_ramp(["#000000", "#FFFFFF"])
    assert ramp([0.0, 1.0]) == ["#000000", "#FFFFFF"]
    assert ramp([math.nan]) == ["grey50"]
