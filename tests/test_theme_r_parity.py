"""theme 元素解析与 ggplot2 4.0.3 的逐元素对拍。

夹具由 `pixi run -e refs refs:theme` 生成（`tools/refs/theme_ref.R`）：对
`theme_grey()` / `theme_minimal()` / `theme_void()` 的每一个元素跑
`calc_element()`，Python 侧用同一份规范形式比对。

根元素上的 `rel()` 是唯一的刻意差异：R 的 `calc_element()` 保持 `rel` 原样
（渲染时才消费），ggcore 按 `base_size` 折成 pt（见 docs/notes/theme.md）。
夹具里三套主题的根元素没有 rel，所以不影响这份对拍。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    resolve_theme,
    theme_grey,
    theme_minimal,
    theme_void,
)
from ggcore.units import Unit

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
_KNOWN_ONLY_IN_EXPECTED = {
    ("geom", "colour"),
    ("geom", "fill"),
}


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


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("name", "builder"),
    [
        ("grey", theme_grey),
        ("minimal", theme_minimal),
        ("void", theme_void),
    ],
)
def test_every_element_matches_ggplot2_4_0_3(reference: dict, name: str, builder) -> None:
    assert reference["ggplot2_version"] == "4.0.3"
    resolved: ResolvedTheme = resolve_theme(builder())
    expected_theme = reference["themes"][name]
    assert set(expected_theme) == set(resolved.elements)

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
            if isinstance(want, float) or isinstance(got, float):
                assert got == pytest.approx(want), f"{element_name}.{key}"
            else:
                assert got == want, f"{element_name}.{key}"

    # expected-only 的 null 键不许无限增长：超出现有名单就说明少建模了字段。
    assert len(skipped) <= len(_KNOWN_ONLY_IN_EXPECTED), sorted(skipped)
    assert skipped <= _KNOWN_ONLY_IN_EXPECTED, sorted(skipped - _KNOWN_ONLY_IN_EXPECTED)
