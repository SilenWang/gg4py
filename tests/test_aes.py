"""`ggcore.aes` 的解析结果容器（M1-2）。

`aes()` 本身仍然只存原样表达式（M1-1 的契约），这里守的是 `AesSpec`：
语法树、引用到的列名、`after_stat` 阶段标记，以及常量与 `AesSpec` 的入参归一。
求值口径在 `tests/test_aes_eval.py`。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from ggcore.aes import (
    Aes,
    AesSpec,
    AfterStat,
    aes,
    after_stat,
    as_aes,
    standardise_aes_names,
)
from ggcore.eval import parse_aes

# ---------------------------------------------------------------------------
# aes() 仍然保存原样表达式
# ---------------------------------------------------------------------------


def test_aes_keeps_the_raw_string_expression() -> None:
    mapping = aes(x="mpg / cyl", y=after_stat("count"), colour="class")
    assert mapping["x"] == "mpg / cyl"  # 没有被解析成 AesSpec
    assert isinstance(mapping["y"], AfterStat)
    assert isinstance(mapping, Aes)


# ---------------------------------------------------------------------------
# aes 名标准化（上游 standardise_aes_names）
# ---------------------------------------------------------------------------


def test_aes_names_are_standardised_like_upstream() -> None:
    assert dict(aes(color="class")) == {"colour": "class"}
    assert dict(aes(pch="shape", cex=3)) == {"shape": "shape", "size": 3}
    assert dict(aes(lty="dashed", lwd=2, srt=45, adj=0, bg="white", fg="black")) == {
        "linetype": "dashed",
        "linewidth": 2,
        "angle": 45,
        "hjust": 0,
        "fill": "white",
        "colour": "black",
    }
    # 上游是子串替换：point_color → point_colour。
    assert dict(aes(point_color="x")) == {"point_colour": "x"}
    assert standardise_aes_names(["color", "pch", "x"]) == ("colour", "shape", "x")


def test_aes_name_standardisation_applies_through_as_aes() -> None:
    assert dict(as_aes({"color": "class"})) == {"colour": "class"}


def test_standardised_duplicate_aes_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="重复"):
        aes(color="a", colour="b")


def test_aes_keys_must_be_strings() -> None:
    with pytest.raises(TypeError, match="aes 名"):
        Aes({1: "x"})


# ---------------------------------------------------------------------------
# parse_aes → AesSpec
# ---------------------------------------------------------------------------


def test_parse_collects_referenced_columns_in_first_appearance_order() -> None:
    spec = parse_aes("mpg / cyl + mpg")
    assert isinstance(spec, AesSpec)
    assert spec.columns == ("mpg", "cyl")
    assert spec.source == "mpg / cyl + mpg"
    assert spec.after_stat is False
    assert spec.constant is False
    assert spec.tree is not None


def test_parse_does_not_count_function_names_as_columns() -> None:
    spec = parse_aes("np.log(mpg) + log10(cyl) + abs(-1)")
    # `np.log` / `log10` / `abs` 是白名单函数，不是列。
    assert spec.columns == ("mpg", "cyl")


def test_parse_keeps_the_after_stat_stage_flag() -> None:
    marker = after_stat("count")
    spec = parse_aes(marker)
    assert spec.after_stat is True
    assert spec.columns == ("count",)
    assert isinstance(spec.expr, AfterStat)
    assert spec.constant is False


def test_parse_after_stat_accepts_a_constant_too() -> None:
    spec = parse_aes(after_stat(2))
    assert spec.after_stat is True
    assert spec.constant is True
    assert spec.constant_value == 2


def test_parse_turns_non_strings_into_constants() -> None:
    spec = parse_aes(2.5)
    assert spec.constant is True
    assert spec.tree is None
    assert spec.columns == ()
    assert spec.constant_value == 2.5
    assert spec.source == "2.5"

    array = np.array([1.0, 2.0])
    array_spec = parse_aes(array)
    assert array_spec.constant is True
    assert "ndarray" in array_spec.source
    assert array_spec.constant_value is array


def test_parse_is_idempotent_for_a_spec() -> None:
    spec = parse_aes("mpg")
    assert parse_aes(spec) is spec


def test_aes_spec_equality_is_structural_not_identity_of_the_ast() -> None:
    # 两次解析得到的是两棵不同的语法树，但解析口径相同 → 相等。
    assert parse_aes("mpg / cyl") == parse_aes("mpg / cyl")
    assert parse_aes("mpg / cyl") != parse_aes("mpg * cyl")
    assert parse_aes("mpg") != parse_aes(after_stat("mpg"))


def test_aes_spec_repr_shows_the_stage() -> None:
    assert "after_stat" in repr(parse_aes(after_stat("count")))
    assert "data" in repr(parse_aes("mpg"))


def test_aes_spec_is_immutable() -> None:
    spec = parse_aes("mpg")
    with pytest.raises(FrozenInstanceError):
        spec.source = "cyl"  # type: ignore[misc]
