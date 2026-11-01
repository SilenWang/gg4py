"""units 的 API 契约（R 侧表达不了或用例太碎的部分）。

与 R 的逐条对拍在 `tests/test_units_r_parity.py`；这里守的是空单位列表、
度量注入、布局模式这些 R 4.5.3 里没有现成入口的行为（口径见
`docs/notes/units.md`）。
"""

from __future__ import annotations

import numpy as np
import pytest

from ggcore.units import (
    FixedMetrics,
    Unit,
    UnitContext,
    UnitElement,
    UnitError,
    convert_height,
    convert_unit,
    convert_width,
    convert_x,
    is_pure_null,
    is_simple_unit,
    is_unit,
    null_value,
    simple_unit_kind,
    str_width,
    unit,
    unit_c,
    unit_pmax,
    unit_pmin,
    unit_psum,
    unit_sum,
    unit_type,
)

CTX = UnitContext(width_cm=10.0, height_cm=5.0, xscale=(0.0, 100.0), yscale=(0.0, 50.0))


def test_unit_accepts_a_unit_name_per_element() -> None:
    mixed = unit([1.0, 3.0, 6.0], ["cm", "inch", "npc"])
    assert unit_type(mixed) == ["cm", "inches", "npc"]
    assert len(mixed) == 3


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [("pt", "points"), ("in", "inches"), ("millimetres", "mm"), ("centimeter", "cm")],
)
def test_unit_aliases_follow_the_r_table(alias: str, canonical: str) -> None:
    assert unit_type(unit(1, alias)) == [canonical]


def test_unknown_unit_name_is_rejected() -> None:
    with pytest.raises(UnitError):
        unit(1, "furlong")


def test_string_units_need_text_and_recycle_it() -> None:
    with pytest.raises(UnitError):
        unit(1, "strwidth")
    recycled = unit([1, 2], "strwidth", data="abc")
    assert [element.data for element in recycled] == ["abc", "abc"]
    # R 的 simpleUnit 是「没有 data 的数值向量」，带文本的单位不算。
    assert not is_simple_unit(recycled)


def test_is_unit_and_simple_unit_kind() -> None:
    assert is_unit(unit(1, "cm"))
    assert not is_unit(1)
    assert simple_unit_kind(unit([1, 2], "cm")) == "cm"
    assert simple_unit_kind(unit(1, "cm") + unit(1, "mm")) is None
    assert simple_unit_kind(Unit()) is None


def test_unit_c_flattens_nested_unit_lists() -> None:
    nested = unit_c(unit(1, "null"), unit_c(unit(2, "cm"), unit(3, "mm")))
    assert unit_type(nested) == ["null", "cm", "mm"]


def test_arithmetic_keeps_mixed_units_symbolic() -> None:
    summed = unit(1, "cm") + unit(2, "mm")
    assert str(summed) == "sum(1cm, 2mm)"
    assert str(2 * (unit(1, "cm") + unit(1, "mm"))) == "2*sum(1cm, 1mm)"
    assert str(unit_pmax(unit(1, "cm"), unit(2, "mm"))) == "max(1cm, 2mm)"


def test_psum_does_not_repeat_the_first_amount_like_r_does() -> None:
    # R 4.5.3 的 summaryUnits() 在非 simpleUnit 路径上把第一项加了两次：
    # unit.psum(a, a) 对两个 1strwidth 返回 3strwidth。我们按语义给 2。
    assert str(unit_psum(str_width("abc"), str_width("abc"))) == "2strwidth"


def test_compound_max_of_negative_units_is_not_r_s_dbl_min() -> None:
    # R 的复合 max 从 DBL_MIN（正的 2.2e-308）起步，max(-1cm, -20mm) 会算出
    # 5.65e-308 cm；我们用 -inf 起步，按语义给 -1cm。
    negative = unit_pmax(unit(-1, "cm"), unit(-20, "mm"))
    assert convert_x(negative, "cm", ctx=CTX).tolist() == pytest.approx([-1.0])


def test_arithmetic_rejects_two_units_or_non_numeric() -> None:
    with pytest.raises(UnitError):
        unit(1, "cm") * unit(2, "cm")
    with pytest.raises(UnitError):
        unit(1, "cm") + 1  # type: ignore[operator]


def test_empty_unit_list_contract() -> None:
    empty = unit_c()
    assert isinstance(empty, Unit)
    assert len(empty) == 0
    assert str(empty) == "<empty unit>"
    assert convert_x(empty, "cm", ctx=CTX).tolist() == []
    assert len(convert_x(empty, "cm", ctx=CTX, value_only=False)) == 0
    # 空列表在加法里是单位元（R 造不出空单位，这里是我们给 gtable 留的定义）。
    assert str(unit(1, "cm") + empty) == "1cm"
    assert str(empty + unit(1, "cm")) == "1cm"
    assert len(empty * 2) == 0
    # psum/pmax 丢空参数（与 R 的 lengths != 0 一致），全空时结果也是空。
    assert str(unit_psum(empty, unit(2, "cm"))) == "2cm"
    assert len(unit_pmax()) == 0
    assert len(unit_pmin()) == 0
    # 空 sum 元素求值为 0。
    assert convert_x(unit_sum(empty), "cm", ctx=CTX).tolist() == [0.0]


def test_metric_provider_receives_the_context_font_size() -> None:
    calls: list[tuple[str, float, float]] = []

    class Recording:
        def strwidth(self, text: str, *, fontsize: float, cex: float) -> float:
            calls.append((text, fontsize, cex))
            return 0.5

        def strheight(self, text: str, *, fontsize: float, cex: float) -> float:
            return 0.25

    ctx = UnitContext(width_cm=10, height_cm=5, fontsize=18, cex=1.5, metrics=Recording())
    assert convert_x(str_width("abc"), "inches", ctx=ctx).tolist() == [0.5]
    assert calls == [("abc", 18, 1.5)]


def test_string_units_without_a_provider_fail_loudly() -> None:
    with pytest.raises(UnitError):
        convert_x(str_width("abc"), "cm", ctx=CTX)


def test_fixed_metrics_is_used_verbatim() -> None:
    ctx = UnitContext(
        width_cm=10, height_cm=5, metrics=FixedMetrics(widths={"abc": 0.5}, heights={"abc": 0.1})
    )
    assert convert_x(str_width("abc"), "mm", ctx=ctx).tolist() == pytest.approx([12.7])


def test_null_value_is_per_element_like_r_s_layout_count() -> None:
    # R 的 pureNullUnitValue(unit, index) 是逐元素取值：gtable 逐列/逐行调用，
    # 不能把整个 unit 加起来（unit.c(1null, 2null) 应该是 1 和 2，不是 3）。
    widths = unit_c(unit(1, "null"), unit(2, "null"), unit(2, "cm"))
    assert [null_value(widths, index) for index in range(len(widths))] == [1.0, 2.0, 0.0]
    assert [is_pure_null(widths, index) for index in range(len(widths))] == [
        True,
        True,
        False,
    ]
    assert convert_x(unit(3, "null"), "cm", ctx=CTX).tolist() == [0.0]

    # 与 null 混合的复合元素不是纯 null：R 的 pureNullUnit 判 false，layout 给 0。
    mixed = unit(1, "null") + unit(2, "cm")
    assert not is_pure_null(mixed, 0)
    assert null_value(mixed, 0) == 0.0

    # 0 权重的 null 仍然是纯 null：gtable 的 sumWeight > 0 门禁靠这两个判断各自
    # 成立，把 is_pure_null 退化成 null_value > 0 就会漏掉 0 权重的 null 行/列。
    zero_null = unit(0, "null")
    assert is_pure_null(zero_null, 0) is True
    assert null_value(zero_null, 0) == 0.0

    # 纯 null 的复合元素按 R 的递归走：sum 展开累加，min / max 取子项最值，
    # 最后乘外层 amount。
    def compound(op: str, *amounts: float, outer: float = 1.0) -> Unit:
        children = tuple(UnitElement(amount, "null") for amount in amounts)
        return Unit((UnitElement(outer, op, children),))

    assert null_value(compound("sum", 1, 3, outer=2), 0) == 8.0
    assert null_value(compound("min", 1, 3), 0) == 1.0
    assert null_value(compound("max", 1, 3), 0) == 3.0
    assert is_pure_null(compound("sum", 1, 3), 0)
    # min / max 的外层 amount 也是整体乘数：漏乘就会退回 1.0 / 3.0。
    assert null_value(compound("min", 1, 3, outer=2), 0) == 2.0
    assert null_value(compound("max", 1, 3, outer=2), 0) == 6.0

    # 嵌套复合：(1null + 3null) * 2 再嵌进外层 sum，要逐层递归后再乘各自的
    # amount（2*(1+3) + 1 = 9）。R 的 `+` 会把同单位合并成 4null，所以这个
    # unit.arithmetic 形状直接按元素搭。
    inner = UnitElement(2.0, "sum", (UnitElement(1.0, "null"), UnitElement(3.0, "null")))
    nested = Unit((UnitElement(1.0, "sum", (inner, UnitElement(1.0, "null"))),))
    assert is_pure_null(nested, 0)
    assert null_value(nested, 0) == 9.0


def test_unit_recycles_amount_and_kind_like_r_construct_units() -> None:
    # R constructUnits(): n = max(length(x), length(units))，两者都按模回收。
    amount_recycled = unit(1, ["cm", "mm", "inches"])
    assert unit_type(amount_recycled) == ["cm", "mm", "inches"]
    assert [element.amount for element in amount_recycled] == [1.0, 1.0, 1.0]

    kind_recycled = unit([1, 2, 3], ["cm", "mm"])
    assert unit_type(kind_recycled) == ["cm", "mm", "cm"]
    assert [element.amount for element in kind_recycled] == [1.0, 2.0, 3.0]

    both = unit([1, 2, 3], ["cm", "mm", "npc", "lines"])
    assert unit_type(both) == ["cm", "mm", "npc", "lines"]
    assert [element.amount for element in both] == [1.0, 2.0, 3.0, 1.0]

    # data 长于单位数：取前 N 个（R 的 validData() 只拒绝比单位向量短的）。
    longer_data = unit([1, 2], "strwidth", data=["a", "b", "c"])
    assert [element.data for element in longer_data] == ["a", "b"]

    # 文案与 R 4.5.3 validData() 的原话一致（docs/notes/units.md 引用同一句）。
    with pytest.raises(
        UnitError,
        match="data must be either NULL, have length 1, "
        "or match the length of the final unit vector",
    ):
        unit([1, 2, 3], "strwidth", data=["a", "b"])


def test_summary_flattens_non_matching_units_before_nested_children() -> None:
    # R 的 Summary.unit 在 nMatches != 0 时写 c(x[-matchUnits], matchData)：
    # 非匹配单位在前、摊平的子项在后。普通量级等价，大数相消时才有差别。
    nested = unit(1e16, "cm") + unit(1, "mm")
    summed = unit_sum(nested, unit(-1e16, "cm"))
    assert [(child.kind, child.amount) for child in summed.elements[0].children] == [
        ("cm", -1e16),
        ("cm", 1e16),
        ("mm", 1.0),
    ]
    # R: 0.1 cm；保持原序的写法会得 0。
    assert convert_x(summed, "cm", ctx=CTX).tolist() == pytest.approx([0.1])

    # unit.psum 走另一条 C 路径（summaryUnits()），保持交错顺序，结果仍是 0。
    p_summed = unit_psum(nested, unit(-1e16, "cm"))
    assert convert_x(p_summed, "cm", ctx=CTX).tolist() == [0.0]


def test_value_only_false_returns_a_unit_in_the_target_unit() -> None:
    converted = convert_x(unit(1, "inches"), "mm", ctx=CTX, value_only=False)
    assert isinstance(converted, Unit)
    assert unit_type(converted) == ["mm"]
    assert converted.elements[0].amount == pytest.approx(25.4)


def test_conversion_target_list_is_recycled() -> None:
    got = convert_unit(unit([2.54, 25.4], "cm"), ["inches", "mm"], ctx=CTX)
    np.testing.assert_allclose(got, [1.0, 254.0], rtol=0, atol=1e-12)


def test_convert_helpers_pick_the_right_axis_and_type() -> None:
    # npc 在 x 上是 10cm，在 y 上是 5cm；dimension 与 location 对 npc 同值。
    assert convert_x(unit(0.5, "npc"), "cm", ctx=CTX).tolist() == [5.0]
    assert convert_unit(unit(0.5, "npc"), "cm", ctx=CTX, axis_from="y").tolist() == [2.5]
    assert convert_width(unit(0.5, "npc"), "cm", ctx=CTX).tolist() == [5.0]
    assert convert_height(unit(0.5, "npc"), "cm", ctx=CTX).tolist() == [2.5]


def test_conversion_round_trip_is_stable() -> None:
    once = convert_x(unit(7.5, "cm"), "mm", ctx=CTX)
    back = convert_x(unit(once, "mm"), "cm", ctx=CTX)
    np.testing.assert_allclose(back, [7.5], rtol=0, atol=1e-12)


def test_context_rejects_degenerate_scales() -> None:
    with pytest.raises(UnitError):
        UnitContext(xscale=(3.0, 3.0))
