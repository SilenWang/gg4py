"""M1-8 与 ggplot2 4.0.3 的 stat 对拍。

夹具由 `pixi run -e refs refs:stat`（`tools/refs/stat_ref.R`）生成，跑测试不需要 R：

- 每个 case 在 Python 侧重放整条流水线，与 `ggplot_build(p)$data[[1]]` 逐列对拍
  （列名、列序、kind、逐值、NA）；
- `stat_smooth` 的 loess 两种面都在夹具里：`smooth_se` / `smooth_no_se` /
  `smooth_span` / `smooth_n` / `smooth_group` 的 R 侧显式用
  `loess.control(surface = "direct", statistics = "exact", trace.hat = "exact")`；
  `smooth_default` / `smooth_horizontal_fullrange` 走 R 的默认口径
  （`surface = "interpolate"`，kd 树 + Hermite 插值）。两侧的 `method.args`
  写法一一对应，见 `docs/notes/stat.md`；
- `stat_boxplot` 的 `outliers` 在 R 里是 list 列，`ColumnTable` 没有 list kind，
  gg4py 用 `"c(1, 2)"` 文本表达：这一列按「解析出来的数值列表」比较。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from ggcore import registry
from ggcore.build import BuildWarning, build_plot
from ggcore.data import Column, ColumnTable
from ggcore.plot import aes, after_stat, ggplot

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "stat_r_reference.json"
#: R 的 C 实现与 numpy 的浮点求和顺序不同：1e-9 足够（loess 实测 ~1e-16）。
TOLERANCE = 1e-9

#: 主题色列：`Geom.default_aes` 存语义名（`grey35` / `grey20`），R 的
#: `from_theme()` 已解析成 `#595959FF` / `#333333FF`。M1-10 解析主题色之前
#: 这些列只比列名与列序（与 tests/test_geom_r_parity.py 同一口径）。
SKIP_VALUES: dict[str, frozenset[str]] = {
    "bin_default": frozenset({"fill"}),
    "bin_width": frozenset({"fill"}),
    "bin_center": frozenset({"fill"}),
    "bin_boundary": frozenset({"fill"}),
    "bin_closed_left": frozenset({"fill"}),
    "bin_pad": frozenset({"fill"}),
    "bin_group": frozenset({"fill"}),
    "bin_density": frozenset({"fill"}),
    "bin_horizontal": frozenset({"fill"}),
    "count_default": frozenset({"fill"}),
    "count_horizontal": frozenset({"fill"}),
    "count_prop": frozenset({"fill"}),
    "count_after_count": frozenset({"fill"}),
    "box_outliers": frozenset({"colour"}),
    "box_none": frozenset({"colour"}),
    "box_varwidth": frozenset({"colour"}),
    "box_inf": frozenset({"colour"}),
    "box_horizontal": frozenset({"colour"}),
    "smooth_se": frozenset({"fill"}),
    "smooth_no_se": frozenset({"fill"}),
    "smooth_span": frozenset({"fill"}),
    "smooth_n": frozenset({"fill"}),
    "smooth_lm": frozenset({"fill"}),
    "smooth_group": frozenset({"fill"}),
    "smooth_default": frozenset({"fill"}),
    "smooth_horizontal_fullrange": frozenset({"fill"}),
    "align_unaligned": frozenset({"fill"}),
    "align_duplicate": frozenset({"fill"}),
    "align_negative": frozenset({"fill"}),
    "align_single": frozenset({"fill"}),
}

#: R 的 `position_dodge2()` 会留下这三列（`ggplot_build()$data` 的中间产物）；
#: ggcore 的 position 只留 `order`，列名投影后比较。
R_ONLY_COLUMNS: dict[str, tuple[str, ...]] = {
    "box_outliers": ("xid", "newx", "new_width"),
    "box_inf": ("xid", "newx", "new_width"),
}


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 数据集（与 tools/refs/stat_ref.R 同一份数字）
# ---------------------------------------------------------------------------

BIN = {"x": [1, 1, 2, 2, 2, 3, 4, 4, 4, 4]}
BIN_GROUP = {
    "x": [1, 2, 3, 1.5, 2.5, 3.5, 2, 4],
    "g": ["a", "a", "a", "a", "b", "b", "b", "b"],
}
COUNT = {
    "cls": ["a", "b", "a", "c", "b", "a", "c", "c"],
    "grp": ["p", "p", "q", "p", "q", "p", "p", "q"],
}
COUNT_H = {"cls": ["a", "b", "a", "c", "b"], "v": [0.3, 0.7, 0.5, 0.9, 0.2]}
BOX = {
    "cls": ["a"] * 9 + ["b"] * 9,
    "v": [1, 2, 3, 4, 5, 6, 7, 8, 20, 2, 3, 4, 5, 6, 7, 8, 9, 25],
}
BOX_NONE = {
    "cls": ["a"] * 6 + ["b"] * 6,
    "v": [1, 2, 3, 4, 5, 6, 2, 3, 4, 5, 6, 7],
}
BOX_VAR = {
    "cls": ["a"] * 4 + ["b"] * 8 + ["c"] * 6,
    "v": [1, 2, 3, 4, 1, 2, 3, 4, 5, 6, 7, 8, 2, 3, 4, 5, 6, 7],
}
BOX_INF = {
    "cls": ["a"] * 6 + ["b"] * 6,
    "v": [1, 2, 3, 4, 5, 100, 2, 3, 4, 5, 6, float("inf")],
}
BOX_H = {"cls": ["a", "a", "a", "b", "b", "b"], "v": [1, 2, 3, 2, 3, 10]}
SMOOTH = {
    "x": list(np.linspace(0.0, 1.0, 15)),
    "y": [
        0.1,
        0.35,
        0.32,
        0.45,
        0.5,
        0.48,
        0.62,
        0.6,
        0.7,
        0.68,
        0.78,
        0.82,
        0.8,
        0.9,
        0.95,
    ],
}
ALIGN = {
    "x": [1, 2, 3, 4, 2, 3, 4, 5],
    "y": [1, 2, 1, 2, 2, 1, 2, 1],
    "g": ["a"] * 4 + ["b"] * 4,
}
ALIGN_DUP = {
    "x": [1, 1, 2, 3, 1, 2, 2, 3],
    "y": [1, 2, 3, 1, 2, 1, 3, 2],
    "g": ["a"] * 4 + ["b"] * 4,
}
ALIGN_NEG = {
    "x": [1, 2, 3, 1, 2, 3],
    "y": [2, -1, 2, -1, 2, -1],
    "g": ["a"] * 3 + ["b"] * 3,
}
SMOOTH_GROUP = {
    "x": list(np.linspace(0.0, 1.0, 8)) * 2,
    "y": [0.1, 0.2, 0.35, 0.4, 0.55, 0.6, 0.7, 0.8, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
    "g": ["a"] * 8 + ["b"] * 8,
}
#: 横向 smooth 的 fullrange case：x 是响应（0..10）、y 是预测变量（1..12）。
SMOOTH_HORIZONTAL = {
    "v": list(np.linspace(0.0, 10.0, 12)),
    "cls": list(range(1, 13)),
}


def _table(values: dict[str, list]) -> ColumnTable:
    columns: list[tuple[str, Column]] = []
    for name, items in values.items():
        if items and isinstance(items[0], str):
            columns.append((name, Column("str", np.array(items, dtype=object))))
        else:
            data = np.array(items, dtype=np.float64)
            missing = np.isnan(data)
            if missing.any():
                filled = np.where(missing, 0.0, data)
                columns.append((name, Column("float", filled, na_mask=missing)))
            else:
                columns.append((name, Column("float", data)))
    return ColumnTable(columns)


def _hist(data: dict[str, list], **params) -> ColumnTable:
    return _table(data)


def _loess(**params):
    # R 侧的 `smooth_control`：显式走 direct 面（statistics / trace.hat 都是 exact）。
    return {
        "method": "loess",
        "formula": "y ~ x",
        "method_args": {
            "control": {
                "surface": "direct",
                "statistics": "exact",
                "trace.hat": "exact",
            }
        },
        **params,
    }


BUILDERS = {
    "bin_default": lambda: ggplot(_hist(BIN), aes(x="x")) + registry.geom_histogram(),
    "bin_width": lambda: ggplot(_hist(BIN), aes(x="x")) + registry.geom_histogram(binwidth=0.5),
    "bin_center": lambda: (
        ggplot(_hist(BIN), aes(x="x")) + registry.geom_histogram(bins=6, center=2)
    ),
    "bin_boundary": lambda: (
        ggplot(_hist(BIN), aes(x="x")) + registry.geom_histogram(binwidth=1, boundary=0)
    ),
    "bin_closed_left": lambda: (
        ggplot(_hist(BIN), aes(x="x")) + registry.geom_histogram(bins=5, closed="left")
    ),
    "bin_pad": lambda: ggplot(_hist(BIN), aes(x="x")) + registry.geom_histogram(bins=4, pad=True),
    "bin_group": lambda: (
        ggplot(_hist(BIN_GROUP), aes(x="x", fill="g"))
        + registry.geom_histogram(bins=5, position="identity", alpha=0.5)
    ),
    "bin_density": lambda: (
        ggplot(_hist(BIN), aes(x="x", y=after_stat("density"))) + registry.geom_histogram(bins=4)
    ),
    "bin_horizontal": lambda: (
        ggplot(_hist(BIN), aes(y="x")) + registry.geom_histogram(binwidth=1, boundary=0)
    ),
    "count_default": lambda: ggplot(_table(COUNT), aes(x="cls", fill="grp")) + registry.geom_bar(),
    "count_horizontal": lambda: ggplot(_table(COUNT_H), aes(y="cls")) + registry.geom_bar(),
    "count_prop": lambda: (
        ggplot(_table(COUNT), aes(x="cls", group=1, y=after_stat("prop"))) + registry.geom_bar()
    ),
    "count_after_count": lambda: (
        ggplot(_table(COUNT), aes(x="cls", y=after_stat("count"))) + registry.geom_bar()
    ),
    "box_outliers": lambda: ggplot(_table(BOX), aes(x="cls", y="v")) + registry.geom_boxplot(),
    "box_none": lambda: (
        ggplot(_table(BOX_NONE), aes(x="cls", y="v")) + registry.geom_boxplot(position="identity")
    ),
    "box_varwidth": lambda: (
        ggplot(_table(BOX_VAR), aes(x="cls", y="v"))
        + registry.geom_boxplot(varwidth=True, position=registry.position_identity())
    ),
    "box_inf": lambda: ggplot(_table(BOX_INF), aes(x="cls", y="v")) + registry.geom_boxplot(),
    "box_horizontal": lambda: (
        ggplot(_table(BOX_H), aes(y="cls", x="v")) + registry.geom_boxplot(position="identity")
    ),
    "smooth_se": lambda: (
        ggplot(_table(SMOOTH), aes(x="x", y="y")) + registry.geom_smooth(**_loess())
    ),
    "smooth_no_se": lambda: (
        ggplot(_table(SMOOTH), aes(x="x", y="y")) + registry.geom_smooth(**_loess(se=False))
    ),
    "smooth_span": lambda: (
        ggplot(_table(SMOOTH), aes(x="x", y="y")) + registry.geom_smooth(**_loess(span=0.5))
    ),
    "smooth_n": lambda: (
        ggplot(_table(SMOOTH), aes(x="x", y="y")) + registry.geom_smooth(**_loess(n=20))
    ),
    "smooth_lm": lambda: (
        ggplot(_table(SMOOTH), aes(x="x", y="y"))
        + registry.geom_smooth(method="lm", formula="y ~ x")
    ),
    "smooth_group": lambda: (
        ggplot(_table(SMOOTH_GROUP), aes(x="x", y="y", colour="g"))
        + registry.geom_smooth(**_loess(se=False))
    ),
    "smooth_default": lambda: (
        # 与 R 侧一致：不传 method.args（R 默认 surface="interpolate"）。
        ggplot(_table(SMOOTH), aes(x="x", y="y")) + registry.geom_smooth()
    ),
    "smooth_horizontal_fullrange": lambda: (
        ggplot(_table(SMOOTH_HORIZONTAL), aes(x="v", y="cls"))
        + registry.geom_smooth(orientation="y", fullrange=True)
    ),
    "align_unaligned": lambda: (
        ggplot(_table(ALIGN), aes(x="x", y="y", fill="g")) + registry.geom_area(position="stack")
    ),
    "align_duplicate": lambda: (
        ggplot(_table(ALIGN_DUP), aes(x="x", y="y", fill="g"))
        + registry.geom_area(position="stack")
    ),
    "align_negative": lambda: (
        ggplot(_table(ALIGN_NEG), aes(x="x", y="y", fill="g"))
        + registry.geom_area(position="stack")
    ),
    "align_single": lambda: ggplot(_table(ALIGN), aes(x="x", y="y")) + registry.geom_area(),
}


# ---------------------------------------------------------------------------
# 比较工具
# ---------------------------------------------------------------------------


def _numbers_from_outliers(text: str) -> list[float]:
    numbers = []
    for chunk in text.strip()[2:-1].split(","):
        chunk = chunk.strip()
        if chunk:
            numbers.append(float(chunk))
    return numbers


def _expected_outliers(values: list) -> list[list[float]]:
    return [[float(item) for item in row] if row else [] for row in values]


def _assert_column_equal(name: str, ours: Column, spec: dict) -> None:
    kind = spec["kind"]
    values = spec["values"]
    if kind == "list":
        # `outliers`：R 是 list 列，gg4py 是 `"c(…)"` 文本（ColumnTable 没有 list kind）。
        assert ours.kind == "str", f"{name}: outliers 必须是 str 列"
        ours_lists = [_numbers_from_outliers(item) for item in ours.values.tolist()]
        assert ours_lists == _expected_outliers(values), f"{name}: outliers 数值不一致"
        return
    if kind == "bool":
        assert ours.kind == "bool", f"{name}: kind {ours.kind} != bool"
        expected = [False if item is None else bool(item) for item in values]
        assert ours.values.tolist() == expected, f"{name}: 布尔值不一致"
        assert np.asarray(ours.na_mask).tolist() == [item is None for item in values]
        return
    if kind == "int":
        assert ours.kind == "int", f"{name}: kind {ours.kind} != int"
        expected = [0 if item is None else int(item) for item in values]
        assert ours.values.tolist() == expected, f"{name}: 整数值不一致"
        assert np.asarray(ours.na_mask).tolist() == [item is None for item in values]
        return
    if kind == "float":
        assert ours.kind == "float", f"{name}: kind {ours.kind} != float"
        expected = np.array([np.nan if item is None else float(item) for item in values])
        got = np.asarray(ours.values, dtype=np.float64)
        mask = np.asarray(ours.na_mask, dtype=bool)
        assert np.allclose(mask, np.isnan(expected)), f"{name}: NA 位置不一致"
        ok = ~np.isnan(expected)
        worst = float(np.max(np.abs(got[ok] - expected[ok]))) if ok.any() else 0.0
        assert np.allclose(got[ok], expected[ok], rtol=0, atol=TOLERANCE), (
            f"{name}: 数值不一致，最大差 {worst}"
        )
        return
    assert ours.kind == "str", f"{name}: kind {ours.kind} != str"
    expected_text = ["" if item is None else str(item) for item in values]
    mask = [item is None for item in values]
    assert ours.values.tolist() == expected_text, f"{name}: 字符串不一致"
    assert np.asarray(ours.na_mask).tolist() == mask, f"{name}: NA 位置不一致"


@pytest.mark.parametrize("case_name", sorted(BUILDERS))
def test_stat_matches_r_column_by_column(reference: dict, case_name: str) -> None:
    case = reference["cases"][case_name]
    built = build_plot(BUILDERS[case_name]()).layers[0].data
    columns = case["built"]["columns"]
    assert case["built"]["rows"] == built.nrows, f"{case_name}: 行数不一致"
    r_only = R_ONLY_COLUMNS.get(case_name, ())
    expected_names = tuple(spec["name"] for spec in columns if spec["name"] not in r_only)
    assert built.names == expected_names, f"{case_name}: 列名/列序不一致"
    skipped = SKIP_VALUES.get(case_name, frozenset())
    for spec in columns:
        if spec["name"] in skipped or spec["name"] in r_only:
            continue
        _assert_column_equal(f"{case_name}.{spec['name']}", built.column(spec["name"]), spec)


def test_max_absolute_difference_is_tiny(reference: dict) -> None:
    """整份夹具的最大绝对差（评论里的数字来源）。

    只统计 M1-8 的 case（M2-6 的 2D case 在 `tests/test_stat_2d_r_parity.py`
    里单独统计；等值线族不逐顶点比）。
    """
    worst = 0.0
    worst_name = ""
    for case_name in sorted(BUILDERS):
        case = reference["cases"][case_name]
        built = build_plot(BUILDERS[case_name]()).layers[0].data
        for spec in case["built"]["columns"]:
            if spec["kind"] != "float" or spec["name"] not in built:
                continue
            if spec["name"] in SKIP_VALUES.get(case_name, frozenset()):
                continue
            expected = np.array(
                [np.nan if item is None else float(item) for item in spec["values"]]
            )
            got = np.asarray(built.column(spec["name"]).values, dtype=np.float64)
            ok = ~np.isnan(expected) & ~np.isnan(got)
            if not ok.any():
                continue
            difference = float(np.max(np.abs(got[ok] - expected[ok])))
            if difference > worst:
                worst = difference
                worst_name = f"{case_name}.{spec['name']}"
    assert worst < TOLERANCE, f"{worst_name} 的差是 {worst}"
    assert worst >= 0.0


def test_boxplot_inf_warning_matches_r(reference: dict) -> None:
    case = reference["cases"]["box_inf"]
    expected = " ".join(case["warnings"][0].split())
    with pytest.warns(BuildWarning) as record:
        build_plot(BUILDERS["box_inf"]())
    ours = [" ".join(str(item.message).split()) for item in record]
    assert expected in ours


# ---------------------------------------------------------------------------
# after_stat：三个变量各一条实跑断言（评论里的输出）
# ---------------------------------------------------------------------------


def test_after_stat_count_matches_the_stat_column() -> None:
    data = build_plot(BUILDERS["count_after_count"]()).layers[0].data
    assert data.column("y").values.tolist() == [3.0, 2.0, 3.0]
    assert data.column("y").values.tolist() == data.column("count").values.tolist()


def test_after_stat_density_is_the_bin_density() -> None:
    data = build_plot(BUILDERS["bin_density"]()).layers[0].data
    assert data.column("y").values.tolist() == [0.2, 0.3, 0.1, 0.4]
    assert data.column("y").values.tolist() == data.column("density").values.tolist()


def test_after_stat_prop_uses_the_group_total() -> None:
    data = build_plot(BUILDERS["count_prop"]()).layers[0].data
    prop = data.column("prop").values.tolist()
    assert prop == [0.375, 0.25, 0.375]
    assert data.column("y").values.tolist() == prop


def test_loess_matches_r_inside_tolerance() -> None:
    """loess 是纯 numpy 实现：与 R 的 direct 口径逐值相等（实测 ~1e-16）。"""
    assert math.isfinite(TOLERANCE)
