"""theme 元素解析与 ggplot2 4.0.3 的逐元素对拍（全部主题 + `theme_sub_*`）。

夹具由 `pixi run -e refs refs:theme` 生成（`tools/refs/theme_ref.R`）：对 9 套
完整主题（`grey` / `gray` / `bw` / `classic` / `light` / `dark` / `linedraw` /
`minimal` / `test` / `void`）与 11 个 `theme_sub_*` 组合的**每一个**元素跑
`calc_element()`，Python 侧用同一份规范形式比对（每套 146 个元素，前端只拦
`>= 100` 这条验收线）。

根元素上的 `rel()` 是唯一的刻意差异：R 的 `calc_element()` 保持 `rel` 原样
（渲染时才消费），ggcore 按 `base_size` 折成 pt（见 docs/notes/theme.md）。
夹具里的主题根元素没有 rel，所以不影响这份对拍。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ggcore import registry
from ggcore.theme import (
    ElementBlank,
    ElementGeom,
    ElementLine,
    ElementPoint,
    ElementPolygon,
    ElementRect,
    ElementText,
    Margin,
    Rel,
    ResolvedTheme,
    element_blank,
    element_line,
    element_rect,
    element_text,
    margin,
    merge_theme,
    rel,
    resolve_theme,
    theme_bw,
    theme_classic,
    theme_dark,
    theme_gray,
    theme_grey,
    theme_light,
    theme_linedraw,
    theme_minimal,
    theme_sub_axis,
    theme_sub_axis_bottom,
    theme_sub_axis_left,
    theme_sub_axis_right,
    theme_sub_axis_top,
    theme_sub_axis_x,
    theme_sub_axis_y,
    theme_sub_legend,
    theme_sub_panel,
    theme_sub_plot,
    theme_sub_strip,
    theme_test,
    theme_void,
)
from ggcore.units import Unit, unit

FIXTURE = Path(__file__).parent / "fixtures" / "theme_r_reference.json"

_KINDS = {
    ElementText: "text",
    ElementLine: "line",
    ElementRect: "rect",
    ElementPolygon: "polygon",
    ElementPoint: "point",
    ElementGeom: "geom",
}

#: 夹具里有、Python 侧刻意不建模的键（都恒为 null）。这份名单只能缩小。
_KNOWN_ONLY_IN_EXPECTED: set[tuple[str, str]] = set()

#: 每套主题至少要有这么多元素（M2-5 的验收线：元素树覆盖完整）。
MIN_ELEMENTS_PER_THEME = 100


def _unit(value: Unit) -> dict:
    return {
        "class": "unit",
        "amount": [element.amount for element in value.elements],
        "kind": [element.kind for element in value.elements],
    }


def _margin(value: Margin) -> dict:
    sides = []
    for side in value.as_tuple():
        if side is None:
            sides.append(None)
        else:
            sides.append({"amount": side.elements[0].amount, "kind": side.elements[0].kind})
    return {"class": "margin", "sides": sides}


def describe(value) -> dict | None:
    if value is None:
        return None
    if isinstance(value, ElementBlank):
        return {"class": "blank"}
    if isinstance(value, Rel):
        return {"class": "rel", "mult": value.mult}
    if isinstance(value, Unit):
        return _unit(value)
    if isinstance(value, Margin):
        return _margin(value)
    if isinstance(value, (str, bool, int, float)):
        return {"class": "value", "value": value}
    for kind, name in _KINDS.items():
        if isinstance(value, kind):
            out = {"class": name}
            for field in value.__dataclass_fields__:
                item = getattr(value, field)
                key = {
                    "arrow_fill": "arrow.fill",
                    "inherit_blank": "inherit.blank",
                }.get(field, field)
                out[key] = _margin(item) if isinstance(item, Margin) else item
            return out
    raise AssertionError(f"describe() 不认识 {type(value).__name__}")


# ---------------------------------------------------------------------------
# 与 tools/refs/theme_ref.R 一一对应的构造器
# ---------------------------------------------------------------------------


def _sub_axis():
    return merge_theme(
        theme_grey(),
        theme_sub_axis(
            title=element_text(size=rel(1.1), colour="red"),
            text=element_text(colour="blue", size=9),
            ticks=element_line(colour="green"),
            ticks_length=unit(3, "pt"),
            line=element_line(colour="black", linewidth=0.4),
            minor_ticks_length=rel(0.6),
        ),
    )


def _sub_axis_x():
    return merge_theme(
        theme_grey(),
        theme_sub_axis_x(
            title=element_text(hjust=1),
            text=element_text(vjust=0),
            ticks=element_line(colour="grey40"),
            ticks_length=unit(4, "pt"),
            line=element_line(lineend="square"),
            minor_ticks_length=rel(0.5),
        ),
    )


def _sub_axis_y():
    return merge_theme(
        theme_grey(),
        theme_sub_axis_y(
            title=element_text(angle=0),
            text=element_text(hjust=0.5),
            ticks=element_line(linetype="dashed"),
            ticks_length=unit(5, "pt"),
            line=element_line(linejoin="mitre"),
            minor_ticks_length=rel(0.4),
        ),
    )


def _sub_axis_top():
    return merge_theme(
        theme_grey(),
        theme_sub_axis_top(
            title=element_text(colour="grey10"),
            text=element_text(size=rel(0.6)),
            ticks=element_line(colour="grey30"),
            ticks_length=unit(2, "pt"),
            line=element_line(colour="grey50"),
            minor_ticks=element_line(colour="grey70"),
            minor_ticks_length=rel(0.3),
        ),
    )


def _sub_axis_bottom():
    return merge_theme(
        theme_grey(),
        theme_sub_axis_bottom(
            title=element_text(vjust=0),
            text=element_text(angle=30),
            ticks=element_line(colour="grey20"),
            ticks_length=unit(6, "pt"),
            line=element_line(linewidth=0.3),
            minor_ticks=element_line(linetype="dotted"),
            minor_ticks_length=unit(1.5, "pt"),
        ),
    )


def _sub_axis_left():
    return merge_theme(
        theme_grey(),
        theme_sub_axis_left(
            title=element_text(size=rel(0.9)),
            text=element_text(colour="grey40"),
            ticks=element_line(colour="grey60"),
            ticks_length=unit(2.5, "pt"),
            line=element_line(colour="grey80"),
            minor_ticks=element_line(colour="grey85"),
            minor_ticks_length=rel(0.2),
        ),
    )


def _sub_axis_right():
    return merge_theme(
        theme_grey(),
        theme_sub_axis_right(
            title=element_text(angle=-90),
            text=element_text(hjust=1),
            ticks=element_line(colour="grey15"),
            ticks_length=unit(3.5, "pt"),
            line=element_line(colour="grey25"),
            minor_ticks=element_blank(),
            minor_ticks_length=unit(1, "pt"),
        ),
    )


def _sub_legend():
    return merge_theme(
        theme_grey(),
        theme_sub_legend(
            text=element_text(colour="red", size=rel(0.7)),
            text_position="left",
            title=element_text(colour="blue"),
            title_position="top",
            background=element_rect(fill="grey95"),
            frame=element_blank(),
            ticks=element_line(colour="black"),
            ticks_length=rel(0.3),
            axis_line=element_line(colour="black", linewidth=0.3),
            spacing=rel(3),
            spacing_x=unit(2, "pt"),
            spacing_y=unit(3, "pt"),
            margin=margin(1, 2, 3, 4),
            key=element_rect(fill="white"),
            key_size=unit(1.5, "cm"),
            key_height=unit(0.8, "cm"),
            key_width=unit(0.9, "cm"),
            key_spacing=unit(2, "pt"),
            key_spacing_x=unit(1, "pt"),
            key_spacing_y=unit(1.5, "pt"),
            key_justification="left",
            byrow=True,
            position="bottom",
            direction="horizontal",
            location="top",
            justification=0,
            justification_top=0,
            justification_bottom=1,
            justification_left=0,
            justification_right=1,
            box="vertical",
            box_just="left",
            box_margin=margin(2, 2, 2, 2),
            box_background=element_rect(fill="grey90"),
            box_spacing=unit(4, "pt"),
        ),
    )


def _sub_panel():
    return merge_theme(
        theme_grey(),
        theme_sub_panel(
            background=element_rect(fill="grey98"),
            border=element_rect(colour="grey20"),
            widths=unit(1, "null"),
            heights=unit(1, "null"),
            spacing=unit(4, "pt"),
            spacing_x=unit(3, "pt"),
            spacing_y=unit(5, "pt"),
            grid=element_line(colour="grey90"),
            grid_major=element_line(linewidth=rel(0.4)),
            grid_minor=element_line(linewidth=rel(0.2)),
            grid_major_x=element_line(linetype="dashed"),
            grid_major_y=element_line(linetype="dotted"),
            grid_minor_x=element_line(colour="grey95"),
            grid_minor_y=element_line(colour="grey96"),
            ontop=True,
        ),
    )


def _sub_plot():
    return merge_theme(
        theme_grey(),
        theme_sub_plot(
            background=element_rect(fill="white", colour=None),
            title=element_text(hjust=0.5),
            title_position="plot",
            subtitle=element_text(colour="grey30"),
            caption=element_text(face="italic"),
            caption_position="plot",
            tag=element_text(size=rel(1.5)),
            tag_position="bottomright",
            tag_location="plot",
            margin=margin(6, 6, 6, 6),
        ),
    )


def _sub_strip():
    return merge_theme(
        theme_grey(),
        theme_sub_strip(
            background=element_rect(fill="grey80"),
            background_x=element_rect(fill="grey70"),
            background_y=element_rect(fill="grey60"),
            clip="off",
            placement="outside",
            text=element_text(colour="black"),
            text_x=element_text(angle=45),
            text_x_bottom=element_text(angle=10),
            text_x_top=element_text(angle=20),
            text_y=element_text(angle=-45),
            text_y_left=element_text(angle=30),
            text_y_right=element_text(angle=-30),
            switch_pad_grid=unit(4, "pt"),
            switch_pad_wrap=unit(5, "pt"),
        ),
    )


#: 夹具键 → 构造器。与 `tools/refs/theme_ref.R` 的 `themes` / `subthemes` 一一对应。
BUILDERS = {
    "grey": theme_grey,
    "gray": theme_gray,
    "bw": theme_bw,
    "classic": theme_classic,
    "light": theme_light,
    "dark": theme_dark,
    "linedraw": theme_linedraw,
    "minimal": theme_minimal,
    "test": theme_test,
    "void": theme_void,
    "sub_axis": _sub_axis,
    "sub_axis_x": _sub_axis_x,
    "sub_axis_y": _sub_axis_y,
    "sub_axis_top": _sub_axis_top,
    "sub_axis_bottom": _sub_axis_bottom,
    "sub_axis_left": _sub_axis_left,
    "sub_axis_right": _sub_axis_right,
    "sub_legend": _sub_legend,
    "sub_panel": _sub_panel,
    "sub_plot": _sub_plot,
    "sub_strip": _sub_strip,
}


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_covers_every_registered_theme(reference: dict) -> None:
    """注册表里每套主题都必须在夹具里（加主题忘了重跑 refs:theme 会红）。"""
    assert set(registry.THEME_NAMES) <= set(reference["themes"])
    assert set(BUILDERS) == set(reference["themes"])


def _same(got, want) -> bool:
    """数值（含 unit / margin 里的 `amount` 数组）按近似比，其余按相等比。"""
    if isinstance(got, list) and isinstance(want, list):
        return len(got) == len(want) and all(_same(a, b) for a, b in zip(got, want, strict=True))
    numeric = (int, float)
    if (
        isinstance(got, numeric)
        and isinstance(want, numeric)
        and not isinstance(got, bool)
        and not isinstance(want, bool)
    ):
        return math.isclose(float(got), float(want), rel_tol=1e-9, abs_tol=1e-9)
    return got == want


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_every_element_matches_ggplot2_4_0_3(reference: dict, name: str) -> None:
    assert reference["ggplot2_version"] == "4.0.3"
    resolved: ResolvedTheme = resolve_theme(BUILDERS[name]())
    expected_theme = reference["themes"][name]
    assert set(expected_theme) == set(resolved.elements)
    assert len(expected_theme) >= MIN_ELEMENTS_PER_THEME, name

    skipped: set[tuple[str, str]] = set()
    for element_name, expected in expected_theme.items():
        actual = describe(resolved[element_name])
        if expected is None:
            assert actual is None, element_name
            continue
        assert actual is not None, element_name
        assert actual["class"] == expected["class"], element_name
        for key, want in expected.items():
            if key == "class":
                continue
            if key not in actual:
                assert want is None, f"{element_name}.{key} 在夹具里非 null，Python 侧却没有这个键"
                skipped.add((element_name, key))
                continue
            got = actual.get(key)
            assert _same(got, want), f"{element_name}.{key}: {got!r} != {want!r}"

    # expected-only 的 null 键不许无限增长：必须与名单**完全相等**。
    # 子集断言（`<=`）只能防「新增」，白名单里的陈旧条目会一直躺着；`==`
    # 让「只能缩小」真正成立：字段建好了就必须从名单里删掉。
    assert skipped == _KNOWN_ONLY_IN_EXPECTED, sorted(skipped ^ _KNOWN_ONLY_IN_EXPECTED)
