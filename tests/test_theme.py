"""M1-10 theme：元素树、继承、`None` vs `blank`、`rel()` 与三套完整主题。

数值口径与 ggplot2 4.0.3 的 `calc_element()` 对拍在
`tests/test_theme_r_parity.py`；这里守的是 API 契约和任务点名的语义。
"""

from __future__ import annotations

import pytest

from ggcore import plot
from ggcore.components import Theme
from ggcore.theme import (
    ElementBlank,
    ElementLine,
    ElementRect,
    ElementText,
    Rel,
    ThemeError,
    element_blank,
    element_geom,
    element_line,
    element_point,
    element_text,
    merge_theme,
    rel,
    resolve_theme,
    theme,
    theme_bw,
    theme_grey,
    theme_minimal,
    theme_void,
)
from ggcore.units import Unit


def margin_pt(value) -> tuple[float | None, ...]:
    return tuple(
        None if side is None else float(side.elements[0].amount) for side in value.as_tuple()
    )


def test_theme_grey_elements_are_resolved_to_concrete_values() -> None:
    resolved = resolve_theme(theme_grey())

    background = resolved["plot.background"]
    assert isinstance(background, ElementRect)
    assert (background.fill, background.colour, background.linewidth) == (
        "#FFFFFF",
        "#FFFFFF",
        0.5,
    )

    panel = resolved["panel.background"]
    assert (panel.fill, panel.colour) == ("#EBEBEB", None)

    grid_major = resolved["panel.grid.major"]
    assert isinstance(grid_major, ElementLine)
    assert (grid_major.colour, grid_major.linewidth) == ("#FFFFFF", 0.5)
    assert resolved["panel.grid.minor"].linewidth == 0.25

    axis_text = resolved["axis.text"]
    assert (axis_text.size, axis_text.colour) == (8.8, "#4D4D4D")
    assert resolved.size_pt("axis.text") == pytest.approx(8.8)

    axis_title = resolved["axis.title"]
    assert (axis_title.size, axis_title.colour) == (11, "#000000")

    title = resolved["plot.title"]
    assert (title.size, title.hjust, title.vjust) == (13.2, 0, 1)
    assert margin_pt(title.margin) == (0, 0, 5.5, 0)

    legend_text = resolved["legend.text"]
    assert (legend_text.size, legend_text.colour) == (8.8, "#000000")

    legend_key = resolved["legend.key"]
    assert (legend_key.fill, legend_key.colour) == ("#EBEBEB", None)

    # 单位：spacing = 5.5pt，主刻度 0.5 * spacing = 2.75pt。
    assert resolved["spacing"].elements[0].amount == 5.5
    assert resolved["axis.ticks.length"].elements[0].amount == 2.75


def test_theme_minimal_elements_are_resolved_to_concrete_values() -> None:
    resolved = resolve_theme(theme_minimal())

    assert resolved["panel.background"].__class__ is ElementBlank
    assert resolved["panel.border"].__class__ is ElementBlank
    assert resolved["legend.key"].__class__ is ElementBlank
    assert resolved["legend.background"].__class__ is ElementBlank
    assert resolved["axis.ticks"].__class__ is ElementBlank

    background = resolved["plot.background"]
    assert (background.fill, background.colour) == ("#FFFFFF", None)

    grid_major = resolved["panel.grid.major"]
    assert (grid_major.colour, grid_major.linewidth) == ("#EBEBEB", 0.5)
    assert resolved["panel.grid.minor"].linewidth == 0.25

    assert resolved["axis.text"].size == pytest.approx(8.8)
    assert resolved["axis.title"].size == pytest.approx(11)
    assert resolved["plot.title"].size == pytest.approx(13.2)
    assert resolved["legend.text"].size == pytest.approx(8.8)

    # theme_minimal 把 x 轴文字的下边距换成 0.45 * base_size = 4.95pt。
    assert margin_pt(resolved["axis.text.x.bottom"].margin) == (4.95, 0, 0, 0)


def test_theme_void_elements_are_resolved_to_concrete_values() -> None:
    resolved = resolve_theme(theme_void())

    for name in (
        "panel.background",
        "panel.border",
        "panel.grid",
        "panel.grid.major",
        "panel.grid.minor",
        "axis.text",
        "axis.title",
        "axis.ticks",
        "legend.key",
        "legend.background",
        "strip.background",
    ):
        assert resolved.is_blank(name), name

    background = resolved["plot.background"]
    assert (background.fill, background.colour, background.linewidth) == (
        "#00000000",
        None,
        0,
    )

    title = resolved["plot.title"]
    assert (title.size, title.hjust) == (13.2, 0)
    assert margin_pt(title.margin) == (5.5, 0, 0, 0)
    assert resolved["legend.text"].size == pytest.approx(8.8)
    assert resolved["legend.text"].colour == "#000000"


def test_theme_grey_base_size_scales_every_relative_size() -> None:
    resolved = resolve_theme(theme_grey(base_size=16))

    assert resolved.size_pt("text") == pytest.approx(16)
    assert resolved.size_pt("axis.text") == pytest.approx(12.8)
    assert resolved.size_pt("plot.title") == pytest.approx(19.2)
    assert resolved["spacing"].elements[0].amount == 8
    assert margin_pt(resolved["axis.text.x"].margin) == (3.2, 0, 0, 0)


def test_rel_on_root_text_is_resolved_once_against_base_size() -> None:
    grey = theme_grey()
    scaled = merge_theme(grey, theme(text=element_text(size=rel(1.5))))
    resolved = resolve_theme(scaled)

    assert resolved.size_pt("text") == pytest.approx(11 * 1.5)
    assert resolved.size_pt("axis.text") == pytest.approx(11 * 1.5 * 0.8)
    assert resolved.size_pt("plot.title") == pytest.approx(11 * 1.5 * 1.2)
    # 原主题不受影响。
    assert grey.elements["text"].size == 11


def test_nested_rel_is_multiplied_once_not_per_merge_step() -> None:
    merged = merge_theme(
        theme_grey(),
        theme(
            text=element_text(size=rel(1.5)),
            **{"axis.text": element_text(size=rel(0.5))},
        ),
    )
    resolved = resolve_theme(merged)

    # 0.5 * (1.5 * 11) = 8.25；不是 0.5 * 0.5 * 1.5 * 11 或 0.5 * 0.8 * 1.5 * 11。
    assert resolved.size_pt("axis.text") == pytest.approx(8.25)


def test_none_deletes_and_blank_draws_nothing() -> None:
    grey = theme_grey()
    deleted = merge_theme(grey, theme(**{"panel.background": None}))
    blanked = merge_theme(grey, theme(**{"panel.background": element_blank()}))

    assert deleted.elements["panel.background"] is None
    # None → 回落到父元素 rect（白底黑边）。
    fallback = resolve_theme(deleted)["panel.background"]
    assert isinstance(fallback, ElementRect)
    assert (fallback.fill, fallback.colour, fallback.linewidth) == ("#FFFFFF", "#000000", 0.5)

    # element_blank() → 明确画空白，不从父元素继承。
    assert isinstance(resolve_theme(blanked)["panel.background"], ElementBlank)


def test_blank_parent_blanks_children_that_inherit_blank() -> None:
    blanked = merge_theme(
        theme_grey(),
        theme(**{"panel.grid": element_blank()}),
    )
    assert resolve_theme(blanked).is_blank("panel.grid.major")

    # 子元素显式 inherit_blank=False 时忽略 blank 父元素。
    kept = merge_theme(
        theme_grey(),
        theme(
            **{
                "panel.grid": element_blank(),
                "panel.grid.major": element_line(colour="red", inherit_blank=False),
            }
        ),
    )
    resolved = resolve_theme(kept)["panel.grid.major"]
    assert isinstance(resolved, ElementLine)
    assert resolved.colour == "#FF0000"


def test_unknown_element_name_lists_available_elements() -> None:
    with pytest.raises(ThemeError) as caught:
        theme(**{"axis.txt": element_text()})

    message = str(caught.value)
    assert "axis.txt" in message
    assert "可用元素" in message
    assert "axis.text" in message
    assert "plot.background" in message


def test_element_type_must_match_the_tree() -> None:
    with pytest.raises(ThemeError, match="ElementText"):
        theme(**{"axis.text": element_line()})
    with pytest.raises(ThemeError, match="Unit"):
        theme(**{"spacing": "wide"})


def test_ggplot_default_theme_is_theme_grey() -> None:
    p = plot.ggplot({"x": [1.0], "y": [2.0]})
    assert p.theme.name == "grey"
    assert p.theme.complete is True
    assert resolve_theme(p.theme).size_pt("axis.text") == pytest.approx(8.8)


def test_complete_theme_replaces_and_partial_merges_on_the_plot() -> None:
    p = plot.ggplot({"x": [1.0], "y": [2.0]})
    grey = p + plot.theme_grey()
    assert grey.theme.name == "grey"

    voided = grey + plot.theme_void()
    assert voided.theme.name == "void"
    assert resolve_theme(voided.theme).is_blank("panel.background")
    # 原对象没被就地改。
    assert resolve_theme(grey.theme)["panel.background"].__class__ is ElementRect

    tweaked = grey + theme(text=element_text(size=rel(2)))
    assert tweaked.theme.name == "grey"
    assert resolve_theme(tweaked.theme).size_pt("text") == pytest.approx(22)


def test_theme_objects_are_immutable_and_merge_returns_new_objects() -> None:
    base = theme_grey()
    merged = merge_theme(base, theme(text=element_text(size=rel(2))))

    assert isinstance(merged, Theme)
    assert merged is not base
    assert base.elements["text"].size == 11
    assert merged.elements["text"].size.mult == 2


def test_theme_bw_is_registered_on_the_plot() -> None:
    p = plot.ggplot({"x": [1.0], "y": [2.0]})

    for bw in (p + theme_bw(), p.theme_bw(), p + plot.theme_bw()):
        assert bw.theme.name == "bw"
        assert bw.theme.complete is True

    resolved = resolve_theme((p + theme_bw()).theme)
    assert resolved["panel.background"].fill == "#FFFFFF"
    assert resolved["panel.background"].colour is None
    assert resolved["panel.border"].colour == "#333333"
    assert resolved["panel.grid.major"].colour == "#EBEBEB"
    assert resolved["panel.grid.minor"].linewidth == pytest.approx(0.25)
    assert resolved["strip.background"].fill == "#D9D9D9"


def test_element_text_carries_italic_fontweight_fontwidth() -> None:
    fields = ElementText.__dataclass_fields__
    assert {"italic", "fontweight", "fontwidth"} <= set(fields)

    merged = merge_theme(
        theme_grey(),
        theme(**{"plot.title": element_text(fontweight="bold", italic=True)}),
    )
    title = resolve_theme(merged)["plot.title"]
    assert isinstance(title, ElementText)
    assert (title.italic, title.fontweight, title.fontwidth) == (True, "bold", None)

    # 完整主题里这三项没设置，保持 None（R 侧同样是 null）。
    plain = resolve_theme(theme_grey())["axis.text"]
    assert (plain.italic, plain.fontweight, plain.fontwidth) == (None, None, None)


_REL_WHITELIST = {
    ("point", "stroke"),
    ("geom", "borderwidth"),
    ("geom", "fontsize"),
    ("geom", "pointsize"),
}


def _rel_sites(resolved) -> set[tuple[str, str | None]]:
    sites: set[tuple[str, str | None]] = set()
    for name, value in resolved.elements.items():
        if isinstance(value, Rel) or (
            isinstance(value, Unit) and any(part.kind == "rel" for part in value.elements)
        ):
            sites.add((name, None))
            continue
        for field_name in getattr(value, "__dataclass_fields__", ()):
            if isinstance(getattr(value, field_name), Rel):
                sites.add((name, field_name))
    return sites


def test_no_rel_survives_outside_the_whitelist() -> None:
    themed = merge_theme(
        theme_grey(),
        theme(
            text=element_text(size=rel(2)),
            line=element_line(linewidth=rel(2)),
            point=element_point(size=rel(2), stroke=rel(2)),
            **{
                "geom": element_geom(
                    linewidth=rel(2),
                    borderwidth=rel(2),
                    fontsize=rel(1.5),
                    pointsize=rel(2),
                )
            },
        ),
    )
    resolved = resolve_theme(themed)

    # size / linewidth 即使在根元素上也折成具体值。
    assert resolved["text"].size == pytest.approx(22)
    assert resolved["point"].size == pytest.approx(3)
    assert resolved["geom"].linewidth == pytest.approx(1.0)
    # 白名单里的字段原样保留。
    assert resolved["point"].stroke == rel(2)
    assert resolved["geom"].fontsize == rel(1.5)
    assert resolved["axis.minor.ticks.length"] == rel(0.75)

    leftovers = {
        site
        for site in _rel_sites(resolved)
        if site not in _REL_WHITELIST and not site[0].startswith("axis.minor.ticks.length")
    }
    assert leftovers == set()
