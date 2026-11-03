"""M1-10 theme：元素树、继承、`None` vs `blank`、`rel()` 与四套完整主题（含 bw）。

数值口径与 ggplot2 4.0.3 的 `calc_element()` 对拍在
`tests/test_theme_r_parity.py`；这里守的是 API 契约和任务点名的语义。
"""

from __future__ import annotations

import pytest

from ggcore import plot
from ggcore.components import Theme
from ggcore.theme import (
    NA,
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
    element_polygon,
    element_rect,
    element_text,
    margin,
    merge_theme,
    rel,
    resolve_theme,
    theme,
    theme_bw,
    theme_grey,
    theme_minimal,
    theme_void,
)
from ggcore.units import Unit, unit


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


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"italic": "yes"}, "italic"),
        ({"italic": 1}, "italic"),
        ({"fontweight": True}, "fontweight"),
        ({"fontweight": ["bold"]}, "fontweight"),
        ({"fontwidth": object()}, "fontwidth"),
    ],
)
def test_element_text_rejects_wrongly_typed_font_fields(kwargs: dict, field: str) -> None:
    with pytest.raises(ThemeError, match=field):
        element_text(**kwargs)


def test_element_text_accepts_numeric_and_named_font_axes() -> None:
    # 数值 weight 走 systemfonts（1–1000），width 接受字体栈认的名字。
    text = element_text(italic=True, fontweight=700, fontwidth="condensed")
    assert (text.italic, text.fontweight, text.fontwidth) == (True, 700, "condensed")
    plain = element_text(italic=False, fontweight="bold", fontwidth=87.5)
    assert (plain.italic, plain.fontweight, plain.fontwidth) == (False, "bold", 87.5)


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


# ---------------------------------------------------------------------------
# 元素字段：全字段类型校验与解析（M2-5）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factory", "kwargs", "field"),
    [
        (element_rect, {"linetype": 1.5}, "linetype"),
        (element_rect, {"linetype": 7}, "linetype"),
        (element_rect, {"linetype": "dotted-line"}, "linetype"),
        (element_rect, {"linejoin": "miter"}, "linejoin"),
        (element_rect, {"fill": 42}, "fill"),
        (element_polygon, {"linetype": "wavy"}, "linetype"),
        (element_polygon, {"linejoin": "sharp"}, "linejoin"),
        (element_line, {"linetype": 9}, "linetype"),
        (element_line, {"arrow": 1}, "arrow"),
        (element_line, {"lineend": "rounding"}, "lineend"),
        (element_text, {"family": 12}, "family"),
        (element_text, {"debug": "yes"}, "debug"),
        (element_text, {"face": "heavy"}, "face"),
        (element_point, {"shape": 26}, "shape"),
        (element_point, {"shape": "ab"}, "shape"),
        (element_point, {"stroke": "thick"}, "stroke"),
        (element_point, {"fill": ["red"]}, "fill"),
        (element_geom, {"linetype": -1}, "linetype"),
        (element_geom, {"bordertype": 8}, "bordertype"),
        (element_geom, {"family": object()}, "family"),
        (element_geom, {"pointshape": 30}, "pointshape"),
    ],
)
def test_element_constructors_reject_wrongly_typed_fields(factory, kwargs, field) -> None:
    with pytest.raises(ThemeError, match=field):
        factory(**kwargs)


def test_element_fields_accept_their_r_domains() -> None:
    line = element_line(linetype="dotdash", lineend="butt", linejoin="round", arrow=True)
    assert (line.linetype, line.lineend, line.linejoin, line.arrow) == (
        "dotdash",
        "butt",
        "round",
        True,
    )
    # R 的 8 位十六进制自定义虚线模式。
    assert element_rect(linetype="#FF00FF00").linetype == "#FF00FF00"

    point = element_point(shape=15, size=2.5, stroke=0.5, fill="red")
    assert (point.shape, point.size, point.stroke, point.fill) == (15, 2.5, 0.5, "red")
    assert element_point(shape="A").shape == "A"

    geom = element_geom(linetype=1, bordertype="dashed", pointshape=19, family="sans")
    assert (geom.linetype, geom.bordertype, geom.pointshape, geom.family) == (
        1,
        "dashed",
        19,
        "sans",
    )


def test_every_element_field_survives_resolution() -> None:
    """解析后的元素保留构造时的每个字段（颜色规范化除外）。"""
    resolved = resolve_theme(
        merge_theme(
            theme_grey(),
            theme(
                **{
                    "panel.grid.major": element_line(
                        colour="red", linewidth=1.25, linetype="longdash", lineend="square"
                    ),
                    "strip.background": element_rect(
                        fill="grey90", colour="blue", linewidth=0.75, linetype="dotted"
                    ),
                    "panel.background": element_rect(fill="white", colour=NA, linejoin="mitre"),
                    "axis.text": element_text(
                        family="sans",
                        face="bold",
                        size=9,
                        colour="black",
                        hjust=1,
                        vjust=0,
                        angle=45,
                        lineheight=1.1,
                        debug=True,
                    ),
                    "point": element_point(
                        colour="black", shape=17, size=2, fill="red", stroke=0.4
                    ),
                }
            ),
        )
    )

    grid = resolved["panel.grid.major"]
    assert (grid.colour, grid.linewidth, grid.linetype, grid.lineend) == (
        "#FF0000",
        1.25,
        "longdash",
        "square",
    )
    strip = resolved["strip.background"]
    assert (strip.fill, strip.colour, strip.linewidth, strip.linetype) == (
        "#E5E5E5",
        "#0000FF",
        0.75,
        "dotted",
    )
    panel = resolved["panel.background"]
    assert (panel.fill, panel.colour, panel.linejoin) == ("#FFFFFF", None, "mitre")
    text = resolved["axis.text"]
    assert (
        text.family,
        text.face,
        text.size,
        text.hjust,
        text.vjust,
        text.angle,
        text.lineheight,
        text.debug,
    ) == ("sans", "bold", 9, 1, 0, 45, 1.1, True)
    point = resolved["point"]
    assert (point.colour, point.shape, point.size, point.fill, point.stroke) == (
        "#000000",
        17,
        2,
        "#FF0000",
        0.4,
    )


# ---------------------------------------------------------------------------
# 9 套主题、全局默认主题与 theme_sub_*（M2-5）
# ---------------------------------------------------------------------------


def test_theme_gray_is_an_alias_of_theme_grey() -> None:
    from ggcore.theme import theme_gray

    assert theme_gray is theme_grey
    # `gray` 也是注册表里的独立入口，构造出同一份完整主题。
    assert plot.theme_gray().elements == theme_grey().elements


def test_theme_classic_draws_axis_lines_and_no_grid() -> None:
    from ggcore.theme import theme_classic

    resolved = resolve_theme(theme_classic())
    assert resolved.is_blank("panel.grid.major")
    assert resolved.is_blank("panel.border")

    line = resolved["axis.line"]
    assert isinstance(line, ElementLine)
    assert (line.colour, line.lineend) == ("#000000", "square")
    # 轴线子元素沿 `skip_blank` 语义跳过 blank 的 axis.line.x…（树里没有它们时）
    # 也照样继承同一条线。
    assert resolved["axis.line.x"].colour == "#000000"


def test_theme_dark_and_light_differ_in_panel_fill() -> None:
    from ggcore.theme import theme_dark, theme_light

    dark = resolve_theme(theme_dark())
    light = resolve_theme(theme_light())
    assert dark["panel.background"].fill == "#7F7F7F"
    assert light["panel.background"].fill == "#FFFFFF"
    # dark 的网格是 mix(ink, paper, 0.42)，light 是 0.871。
    assert dark["panel.grid.major"].colour == "#6B6B6B"
    assert light["panel.grid.major"].colour == "#DEDEDE"


def test_theme_test_and_linedraw_panel_border() -> None:
    from ggcore.theme import theme_linedraw, theme_test

    test = resolve_theme(theme_test())
    assert test.is_blank("panel.grid.major")
    assert isinstance(test["panel.border"], ElementRect)
    assert test["panel.border"].colour == "#333333"

    linedraw = resolve_theme(theme_linedraw())
    assert linedraw["panel.border"].colour == "#000000"
    assert linedraw["panel.grid.major"].colour == "#000000"
    assert linedraw["strip.background"].fill == "#000000"
    assert linedraw["strip.text"].colour == "#FFFFFF"


@pytest.fixture
def keep_default_theme():
    """还原全局默认主题：`theme_set()` 是模块级状态，测试之间不能泄漏。"""
    from ggcore.theme import theme_get, theme_set

    previous = theme_get()
    try:
        yield
    finally:
        theme_set(previous)


def test_theme_set_get_update_replace(keep_default_theme) -> None:
    from ggcore.theme import (
        theme_get,
        theme_replace,
        theme_set,
        theme_update,
    )

    assert theme_get().name == "grey"

    old = theme_set(plot.theme_dark())
    assert old.name == "grey"
    assert theme_get().name == "dark"
    # 新建的图跟着全局默认走。
    p = plot.ggplot({"x": [1.0], "y": [2.0]})
    assert p.theme.name == "dark"

    # 无参 theme_set() 是「重置为内置默认」，不是读取（上游 set_theme(new = NULL)：
    # `new <- new %||% ggplot_global$theme_default`）。返回旧主题。
    previous = theme_set()
    assert previous.name == "dark"
    assert theme_get().name == "grey"

    theme_set(plot.theme_dark())
    previous = theme_update(**{"panel.background": element_rect(fill="red")})
    assert previous.name == "dark"
    updated = theme_get()
    assert updated.name == "dark"
    assert updated.complete is True
    assert updated.elements["panel.background"].fill == "red"
    # update 是逐元素合并：其余元素仍是 dark 的。
    assert resolve_theme(updated)["panel.grid.major"].colour == "#6B6B6B"

    theme_replace(**{"panel.grid.major": element_line(colour="blue")})
    replaced = theme_get()
    assert replaced.elements["panel.grid.major"].colour == "blue"
    # replace 整份换掉该元素（linewidth 回落到父元素 line，而不是 dark 的 rel(0.5)）。
    assert replaced.elements["panel.grid.major"].linewidth is None
    resolved = resolve_theme(replaced)
    assert resolved["panel.grid.major"].linewidth == 0.5


def test_theme_replace_keeps_inherit_blank_false_on_replaced_elements(
    keep_default_theme,
) -> None:
    """`theme_replace()` 是 `get_theme() %+replace% theme(...)`（R/theme-current.R）。

    `theme(...)` 不带 `complete`，换进来的元素保持构造值 `inherit.blank=FALSE`，
    解析时不会继承 `panel.grid`（`theme_void()` 里是 blank）；base 里的旧元素
    仍带 `inherit.blank=TRUE`。旧实现把换进来的元素也重标成 TRUE，这里会解析
    成 `ElementBlank`。
    """
    from ggcore.theme import theme_get, theme_replace, theme_set

    theme_set(theme_void())
    theme_replace(**{"panel.grid.major": element_line(colour="red")})

    replaced = theme_get()
    assert replaced.elements["panel.grid.major"].inherit_blank is False
    assert replaced.elements["text"].inherit_blank is True

    resolved = resolve_theme(replaced)["panel.grid.major"]
    assert isinstance(resolved, ElementLine), type(resolved).__name__
    assert resolved.colour == "#FF0000"


def test_theme_replace_keeps_existing_elements_inherit_blank_true(
    keep_default_theme,
) -> None:
    """旧元素不会被 `theme_replace()` 重新标记（`e1[names(e2)] <- e2` 只动同名项）。"""
    from ggcore.theme import theme_get, theme_replace, theme_set

    theme_set(theme_void())
    theme_replace(**{"panel.grid.major": element_line(colour="red")})

    replaced = theme_get()
    assert replaced.complete is True
    assert replaced.name == "void"
    # 没被替换的元素保持 `theme_void()` 构造时的 `inherit.blank=TRUE`。
    assert replaced.elements["plot.background"].inherit_blank is True
    assert isinstance(resolve_theme(replaced)["panel.background"], ElementBlank)


def test_theme_set_rejects_partial_and_non_theme(keep_default_theme) -> None:
    from ggcore.theme import theme_set

    with pytest.raises(ThemeError, match="完整主题"):
        theme_set(theme(**{"panel.background": element_rect(fill="red")}))
    with pytest.raises(TypeError, match="Theme"):
        theme_set("theme_dark")


def test_theme_sub_axis_maps_parameters_to_prefixed_elements() -> None:
    from ggcore.theme import (
        theme_sub_axis,
        theme_sub_axis_bottom,
        theme_sub_legend,
        theme_sub_strip,
    )

    axis = theme_sub_axis(text=element_text(size=9), ticks_length=unit(3, "pt"))
    assert set(axis.elements) == {"axis.text", "axis.ticks.length"}

    bottom = theme_sub_axis_bottom(minor_ticks=element_blank(), ticks_length=unit(4, "pt"))
    assert set(bottom.elements) == {
        "axis.minor.ticks.x.bottom",
        "axis.ticks.length.x.bottom",
    }

    legend = theme_sub_legend(key_size=unit(2, "cm"), box_margin=margin(1))
    assert set(legend.elements) == {"legend.key.size", "legend.box.margin"}

    strip = theme_sub_strip(text_x_top=element_text(angle=20), switch_pad_wrap=unit(1, "pt"))
    assert set(strip.elements) == {"strip.text.x.top", "strip.switch.pad.wrap"}


def test_theme_sub_unknown_argument_is_a_type_error() -> None:
    from ggcore.theme import theme_sub_panel

    with pytest.raises(TypeError):
        theme_sub_panel(panell=element_blank())


def test_theme_sub_none_deletes_the_element() -> None:
    from ggcore.theme import theme_sub_panel

    merged = merge_theme(theme_grey(), theme_sub_panel(background=None))
    assert merged.elements["panel.background"] is None
    # 删除后回落到父元素 rect（白底黑边）。
    assert resolve_theme(merged)["panel.background"].fill == "#FFFFFF"
