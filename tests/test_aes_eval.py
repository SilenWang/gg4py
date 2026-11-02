"""`ggcore.eval` 的求值口径（M1-2）：白名单、数据掩码、长度语义、自动分组。

安全断言是重点：负向用例不是「设计上不会执行」，而是**真的调用一次**并确认
报错、文件没被创建。求值器本身没有 `eval` / `exec` / `compile`，手搓的
`AesSpec` 也绕不过白名单。
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from ggcore.aes import AesSpec, aes, after_stat
from ggcore.data import Column, ColumnTable
from ggcore.eval import (
    NO_GROUP,
    AesEvalError,
    AesParseError,
    AesWhitelistError,
    compute_groups,
    eval_aes,
    eval_after_stat,
    has_groups,
    parse_aes,
)

MPG = np.array([21.0, 22.5, 18.0, 30.0, 27.0])
CYL = np.array([4.0, 4.0, 6.0, 4.0, 8.0])


def table() -> ColumnTable:
    """一份小号 mpg：数值列 + 两个离散列（class / drv）。"""
    return ColumnTable(
        [
            ("mpg", Column("float", MPG)),
            ("cyl", Column("float", CYL)),
            (
                "class",
                Column("str", np.array(["compact", "compact", "midsize", "compact", "suv"])),
            ),
            ("drv", Column("str", np.array(["f", "f", "f", "r", "r"]))),
        ]
    )


# ---------------------------------------------------------------------------
# 正向：真实列上的求值
# ---------------------------------------------------------------------------


def test_aes_mapping_evaluates_on_real_columns() -> None:
    mapping = aes(x="mpg/cyl", y="cyl")
    np.testing.assert_allclose(eval_aes(mapping["x"], table()), MPG / CYL)
    np.testing.assert_allclose(eval_aes(mapping["y"], table()), CYL)


def test_arithmetic_comparisons_and_elementwise_condition() -> None:
    t = table()
    np.testing.assert_allclose(eval_aes("(mpg - 20) * 2 / cyl + 1", t), (MPG - 20) * 2 / CYL + 1)
    np.testing.assert_array_equal(
        eval_aes("(mpg > 20) & (cyl < 8)", t), [True, True, False, True, False]
    )
    np.testing.assert_array_equal(eval_aes("1 if mpg > 20 else 0", t), [1, 1, 0, 1, 1])
    # 链式比较按 `a < b < c` 的语义。
    np.testing.assert_array_equal(eval_aes("18 <= mpg < 27", t), [True, True, True, False, False])


def test_whitelisted_functions_are_callable_by_dotted_and_bare_name() -> None:
    t = table()
    expected = np.log(MPG) + np.sqrt(CYL)
    np.testing.assert_allclose(eval_aes("np.log(mpg) + sqrt(cyl)", t), expected)
    np.testing.assert_allclose(eval_aes("log10(mpg) * 2", t), np.log10(MPG) * 2)


def test_power_is_double_like_r_and_huge_exponents_cannot_hang() -> None:
    t = table()
    result = eval_aes("2 ** 3", t)
    assert result.dtype == np.float64  # R 的 `^` 总是 double
    np.testing.assert_allclose(result, 8.0)
    np.testing.assert_allclose(eval_aes("2 ** 0.5", t), np.sqrt(2.0))
    # Python 的整数幂会把 `10 ** 10 ** 10` 算成十亿位大整数（求值线程挂死）；
    # R 给 Inf。这里必须立刻返回 Inf。
    assert np.isinf(eval_aes("10 ** 10 ** 10", t)).all()


def test_np_where_and_np_isnan_work_on_missing_values() -> None:
    t = ColumnTable(
        [
            (
                "x",
                Column("float", np.array([1.0, 0.0, 3.0]), na_mask=np.array([False, True, False])),
            )
        ]
    )
    result = eval_aes("where(isnan(x), 0, x)", t)
    np.testing.assert_allclose(result, [1.0, 0.0, 3.0])


def test_categorical_column_evaluates_to_its_levels() -> None:
    categorical = Column("categorical", np.array([0, 1, 0], dtype=np.int32), levels=("b", "a"))
    t = ColumnTable([("cls", categorical)])
    result = eval_aes("cls", t)
    assert result.tolist() == ["b", "a", "b"]


def test_python_keyword_column_names_are_still_referenceable() -> None:
    # mpg 的 `class` 列：整串是标识符但撞上关键字，按列名处理。
    assert parse_aes("class").columns == ("class",)
    assert eval_aes("class", table()).tolist() == [
        "compact",
        "compact",
        "midsize",
        "compact",
        "suv",
    ]
    with pytest.raises(AesEvalError, match="没有列 'class'"):
        eval_aes("class", ColumnTable([("other", Column("float", np.array([1.0])))]))


def test_col_helper_references_names_that_are_not_identifiers() -> None:
    t = ColumnTable([("mpg class", Column("float", np.array([1.0, 2.0])))])
    spec = parse_aes('col("mpg class") * 2')
    assert spec.columns == ("mpg class",)
    np.testing.assert_allclose(eval_aes(spec, t), [2.0, 4.0])


def test_col_helper_requires_a_string_literal() -> None:
    with pytest.raises(AesWhitelistError, match="字符串字面量"):
        parse_aes("col(mpg)")
    with pytest.raises(AesWhitelistError, match="字符串字面量"):
        parse_aes('col("a", "b")')


def test_na_is_nan_for_numbers_and_none_for_strings() -> None:
    t = ColumnTable(
        [
            (
                "x",
                Column("float", np.array([1.0, 0.0, 3.0]), na_mask=np.array([False, True, False])),
            ),
            (
                "s",
                Column("str", np.array(["a", "", "c"]), na_mask=np.array([False, True, False])),
            ),
        ]
    )
    numbers = eval_aes("x * 2", t)
    assert numbers[0] == 2.0 and np.isnan(numbers[1]) and numbers[2] == 6.0
    assert eval_aes("s", t).tolist() == ["a", None, "c"]


# ---------------------------------------------------------------------------
# 长度语义
# ---------------------------------------------------------------------------


def test_scalar_constant_broadcasts_to_nrows() -> None:
    np.testing.assert_allclose(eval_aes(2.5, table()), np.full(5, 2.5))


def test_constant_string_expression_broadcasts() -> None:
    result = eval_aes("'red'", table())
    assert result.tolist() == ["red"] * 5


def test_length_one_array_broadcasts() -> None:
    np.testing.assert_allclose(eval_aes(np.array([4.0]), table()), np.full(5, 4.0))


def test_other_lengths_are_rejected_not_truncated() -> None:
    with pytest.raises(AesEvalError, match="长度为 2，与数据行数 5 不符"):
        eval_aes(np.array([1.0, 2.0]), table())


# ---------------------------------------------------------------------------
# 报错：表达式 + 行列位置
# ---------------------------------------------------------------------------


def test_unknown_column_lists_the_available_columns() -> None:
    with pytest.raises(AesEvalError) as excinfo:
        eval_aes(parse_aes("mpg / zzz"), table())
    message = str(excinfo.value)
    assert "aes 表达式 `mpg / zzz`" in message
    assert "第 1 行第 7 列" in message
    assert "没有列 'zzz'" in message
    assert "mpg, cyl, class, drv" in message
    assert "^" in message


def test_unknown_column_error_is_raised_on_every_evaluation_path() -> None:
    # 直接传字符串（内部先 parse）与先 parse 再 eval 的行为一致。
    with pytest.raises(AesEvalError, match="zzz"):
        eval_aes("mpg / zzz", table())
    with pytest.raises(AesEvalError, match="zzz"):
        compute_groups(aes(x="zzz"), table())


def test_syntax_error_carries_the_expression_and_position() -> None:
    with pytest.raises(AesParseError) as excinfo:
        parse_aes("mpg +")
    message = str(excinfo.value)
    assert "aes 表达式 `mpg +`" in message
    assert "第 1 行" in message
    assert "语法错误" in message


def test_unparseable_source_is_wrapped_as_a_parse_error() -> None:
    # NUL 字节会让 ast.parse 直接报 SyntaxError；无论哪种底层异常，都收成 AesParseError。
    with pytest.raises(AesParseError, match="null bytes"):
        parse_aes("mpg\x00+ 1")


def test_eval_aes_requires_a_column_table() -> None:
    with pytest.raises(TypeError, match="ColumnTable"):
        eval_aes("mpg", {"mpg": [1.0, 2.0]})


# ---------------------------------------------------------------------------
# 白名单负向用例（每一条都真的执行，确认报错可读）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "needle"),
    [
        ('__import__("os")', "__import__"),
        ('open("/tmp/gg4py-eval-should-not-exist", "w")', "open"),
        ("mpg.__class__", "__class__"),
        ("mpg[0]", "下标"),
        ("lambda value: value", "lambda"),
        ("[c for c in mpg]", "推导式"),
        ('exec("x = 1")', "exec"),
        ('eval("1 + 1")', "eval"),
    ],
)
def test_whitelist_rejects_code_execution_and_introspection(expr: str, needle: str) -> None:
    with pytest.raises(AesWhitelistError) as excinfo:
        eval_aes(expr, table())
    message = str(excinfo.value)
    assert needle in message
    assert "aes 表达式" in message
    assert "第 1 行" in message


def test_attribute_access_is_only_allowed_as_a_whitelisted_call() -> None:
    # 非调用位置：`np.pi` 是属性访问，拒绝。
    with pytest.raises(AesWhitelistError, match="属性访问"):
        parse_aes("np.pi * mpg")
    # 调用位置但不是白名单函数：`mpg.__class__()` 拒绝。
    with pytest.raises(AesWhitelistError, match="__class__"):
        parse_aes("mpg.__class__()")
    # 白名单函数的点分写法放行。
    assert parse_aes("np.log(mpg)").columns == ("mpg",)


def test_a_file_writing_expression_is_rejected_and_creates_nothing(tmp_path: Path) -> None:
    target = tmp_path / "pwned.txt"
    expr = f'__import__("pathlib").Path({str(target)!r}).write_text("x")'
    with pytest.raises(AesWhitelistError) as excinfo:
        eval_aes(expr, table())
    message = str(excinfo.value)
    assert "__import__" in message
    assert "aes 表达式" in message
    assert "第 1 行第 1 列" in message
    assert not target.exists()


def test_a_hand_built_spec_cannot_bypass_the_whitelist() -> None:
    # parse_aes 之外还有一道：解释器本身只认识白名单节点/函数。
    source = '__import__("os").system("echo x")'
    spec = AesSpec(expr=source, source=source, tree=ast.parse(source, mode="eval"))
    with pytest.raises(AesWhitelistError, match="__import__"):
        eval_aes(spec, table())


# ---------------------------------------------------------------------------
# after_stat
# ---------------------------------------------------------------------------


def test_after_stat_is_a_marker_not_a_data_stage_expression() -> None:
    spec = parse_aes(after_stat("count"))
    assert spec.after_stat is True
    with pytest.raises(AesEvalError) as excinfo:
        eval_aes(spec, table())
    assert "after_stat" in str(excinfo.value)
    assert "eval_after_stat" in str(excinfo.value)


def test_eval_after_stat_computes_from_the_stat_outputs() -> None:
    spec = parse_aes(after_stat("count / 2 + 1"))
    result = eval_after_stat(spec, {"count": np.array([2.0, 4.0, 6.0])})
    np.testing.assert_allclose(result, [2.0, 3.0, 4.0])


def test_eval_after_stat_broadcasts_scalars_and_infers_nrows() -> None:
    result = eval_after_stat(parse_aes(after_stat("count * 2")), {"count": 3.0}, nrows=3)
    np.testing.assert_allclose(result, [6.0, 6.0, 6.0])


def test_eval_after_stat_lists_available_variables() -> None:
    with pytest.raises(AesEvalError) as excinfo:
        eval_after_stat(parse_aes(after_stat("count")), {"density": np.array([1.0])})
    message = str(excinfo.value)
    assert "count" in message
    assert "density" in message
    assert "可用变量" in message


def test_eval_after_stat_rejects_inconsistent_lengths() -> None:
    with pytest.raises(AesEvalError, match="长度不一致"):
        eval_after_stat(
            parse_aes(after_stat("a + b")),
            {"a": np.arange(3.0), "b": np.arange(2.0)},
        )
    with pytest.raises(AesEvalError, match="nrows=3"):
        eval_after_stat(
            parse_aes(after_stat("a + b")),
            {"a": np.arange(2.0), "b": np.arange(2.0)},
            nrows=3,
        )


# ---------------------------------------------------------------------------
# 自动分组（ggplot2 add_group 口径）
# ---------------------------------------------------------------------------


def test_one_discrete_aes_gives_one_group_per_level() -> None:
    ids = compute_groups(aes(colour="class"), table())
    assert ids.tolist() == [0, 0, 1, 0, 2]
    assert has_groups(ids)


def test_two_discrete_aes_are_cartesian_interaction() -> None:
    t = ColumnTable(
        [
            ("a", Column("str", np.array(["u", "u", "v", "v"]))),
            ("b", Column("str", np.array(["p", "q", "p", "q"]))),
        ]
    )
    ids = compute_groups(aes(colour="a", shape="b"), t)
    # 2×2 = 4 个观测到的组合；第一个 aes 变化最慢、按组合码升序编号。
    assert ids.tolist() == [0, 1, 2, 3]

    # 只出现 3 个组合时，未出现的组合不占 id（drop=TRUE）。
    partial = ColumnTable(
        [
            ("a", Column("str", np.array(["u", "u", "v"]))),
            ("b", Column("str", np.array(["p", "q", "p"]))),
        ]
    )
    assert compute_groups(aes(colour="a", shape="b"), partial).tolist() == [0, 1, 2]


def test_group_ids_follow_sorted_levels() -> None:
    # 上游 id() 是 match(x, sort(unique(x)))，不是首次出现顺序。
    t = ColumnTable([("g", Column("str", np.array(["b", "a", "b", "c", "a"])))])
    assert compute_groups(aes(group="g"), t).tolist() == [1, 0, 1, 2, 0]


def test_two_discrete_aes_ids_are_ordered_by_the_first_aesthetic() -> None:
    # R 的 id() 把第一个变量当慢速位：colour 先分组，shape 在组内变化。
    t = ColumnTable(
        [
            ("colour", Column("str", np.array(["b", "a", "b", "c", "a"]))),
            ("shape", Column("str", np.array(["y", "y", "x", "x", "y"]))),
        ]
    )
    # R: ggplot2:::id(data.frame(c("b","a","b","c","a"), c("y","y","x","x","y")))
    #    == 3 1 2 4 1（1 起）；这里减 1。
    assert compute_groups(aes(colour="colour", shape="shape"), t).tolist() == [2, 0, 1, 3, 0]


def test_explicit_group_overrides_automatic_grouping() -> None:
    ids = compute_groups(aes(colour="class", group="cyl"), table())
    assert ids.tolist() == [0, 0, 1, 0, 2]


def test_no_discrete_aes_means_no_groups() -> None:
    ids = compute_groups(aes(x="mpg", y="cyl"), table())
    assert (ids == NO_GROUP).all()
    assert not has_groups(ids)


def test_constant_colour_does_not_change_grouping() -> None:
    base = compute_groups(aes(shape="class"), table())
    numeric = compute_groups(aes(shape="class", colour=1), table())
    textual = compute_groups(aes(shape="class", colour="'red'"), table())
    assert base.tolist() == numeric.tolist() == textual.tolist() == [0, 0, 1, 0, 2]


def test_rows_with_na_in_a_grouping_column_get_no_group() -> None:
    t = ColumnTable(
        [
            (
                "g",
                Column("str", np.array(["a", "", "b"]), na_mask=np.array([False, True, False])),
            )
        ]
    )
    ids = compute_groups(aes(colour="g"), t)
    assert ids.tolist() == [0, NO_GROUP, 1]


def test_after_stat_aes_does_not_participate_in_grouping() -> None:
    ids = compute_groups(aes(shape="class", y=after_stat("count")), table())
    assert ids.tolist() == [0, 0, 1, 0, 2]


def test_grouping_uses_standardised_aes_names() -> None:
    # `color` 在 aes() 里标准化成 `colour`，分组行为一致。
    assert compute_groups(aes(color="class"), table()).tolist() == [0, 0, 1, 0, 2]


def test_logical_aes_participates_in_grouping() -> None:
    # 上游 is_discrete() 是 factor / character / logical：bool 列也是离散。
    # 逻辑值按 FALSE < TRUE 排序编号（id() 的 sort(unique())）。
    t = ColumnTable([("flag", Column("bool", np.array([True, True, False, True])))])
    assert compute_groups(aes(colour="flag"), t).tolist() == [1, 1, 0, 1]
    # 算出来的逻辑值同样参与分组（mpg > 20 → [True, True, False, True, True]）。
    assert compute_groups(aes(colour="mpg > 20"), table()).tolist() == [1, 1, 0, 1, 1]
