"""图例键的覆盖点（SIL-810）：`key_glyph=`、逐键尺寸、逐美学 show.legend。"""

from __future__ import annotations

import pytest

from ggcore.build import build_plot
from ggcore.geom.scene import plot_layout
from ggcore.guide import build_guides, legend_layout
from ggcore.legend_draw import KEY_GLYPHS, KeyGlyph, draw_key
from ggcore.plot import aes, geom_line, geom_point, ggplot, scale_size_continuous
from ggcore.theme import resolve_theme
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0.0, 1.0, 2.0]}


def test_every_upstream_key_glyph_is_registered() -> None:
    expected = {
        "point",
        "abline",
        "rect",
        "polygon",
        "blank",
        "boxplot",
        "crossbar",
        "path",
        "vpath",
        "dotplot",
        "linerange",
        "pointrange",
        "smooth",
        "text",
        "label",
        "vline",
        "timeseries",
    }
    assert expected <= set(KEY_GLYPHS)


def test_key_glyph_name_and_callable() -> None:
    values = {"colour": "black", "linewidth": 1.0}
    assert draw_key("timeseries", values, {}, 6.0) is not None

    def custom(data, params, size):
        del data, params, size
        from ggcore.grobs import circle_grob

        return KeyGlyph(circle_grob(r=unit(1.0, "cm")), width_cm=2.0, height_cm=2.0)

    glyph = draw_key(custom, values, {}, 6.0)
    assert isinstance(glyph, KeyGlyph)
    assert (glyph.width_cm, glyph.height_cm) == (2.0, 2.0)


def test_key_size_follows_size_scale() -> None:
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", size="x"))
        + geom_point()
        + scale_size_continuous(range=(1.0, 12.0))
    )
    build = build_plot(p)
    guide = build_guides(build)[0]
    layout = legend_layout(guide, resolve_theme(build.theme), "right")
    heights = [cell.box.height_cm for cell in layout.keys]
    assert heights == sorted(heights)
    assert heights[-1] > heights[0]


def test_show_legend_can_hide_one_aesthetic() -> None:
    data = {"x": [0.0, 1.0], "alpha": ["a", "a"]}
    p = (
        ggplot(to_column_table(data), aes(x="x", y="x"))
        + geom_point(
            aes(alpha="alpha"),
            **{"show.legend": {"alpha": False}},
        )
        + geom_line(aes(colour="alpha"), **{"show.legend": {"colour": None}})
    )
    build = build_plot(p)
    aesthetics = {name for guide in build_guides(build) for name in guide.aesthetics}
    assert "alpha" not in aesthetics
    assert "colour" in aesthetics


def test_empty_plot_keeps_panel_inside_margin() -> None:
    layout = plot_layout(build_plot(ggplot()))
    panel = layout.panel_area
    assert panel.x_cm == pytest.approx(layout.margin_cm[3])
    assert panel.y_cm == pytest.approx(layout.margin_cm[2])
