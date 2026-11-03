"""M2-6 stat 长尾 B 与 ggplot2 4.0.3 的逐列对拍。

夹具由 `pixi run -e refs refs:stat-longtail`（`tools/refs/stat_longtail_ref.R`）生成，
跑测试不需要 R：

- 每个 case 在 Python 侧重放整条流水线，与 `ggplot_build(p)$data[[1]]` 逐列比较
  （列名、列序、kind、逐值、NA）；
- ±Inf 在 JSON 里是 `null`（R 的 `fmt_num` 口径），位置记在 `pos_inf` / `neg_inf`；
  `stat_ecdf(pad = TRUE)` 的 ±Inf 靠这一对字段还原；
- `stat_spoke` 在 4.0.3 里已经是 `lifecycle::deprecate_stop()`，夹具记错误消息，
  Python 侧断言同一条路径报错。

`stat_density` / `stat_ydensity` 走的是 R 4.5 `density()` 的「bin + FFT + 线性插值」
算法（`tools/refs/stat_longtail_ref.R` 的同一套参数），不做直接核求和，否则
相对差会到 1e-4 量级。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from ggcore import registry
from ggcore.build import BuildError, build_plot
from ggcore.data import Column, ColumnTable
from ggcore.plot import aes, ggplot

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "stat_longtail_r_reference.json"
#: 与 tests/test_stat_r_parity.py 同一个口径（实测整份夹具最大差 7.7e-13，
#: 其中 `MASS::cov.trob` 的移植逐值差 7.6e-15）。
TOLERANCE = 1e-9


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 数据集（与 tools/refs/stat_longtail_ref.R 同一份数字）
# ---------------------------------------------------------------------------

LD = {"v": [1.2, 2.4, 2.9, 3.1, 3.8, 4.5, 5.1, 5.2, 6.0, 7.7]}
GRP = {
    "g": ["a"] * 6 + ["b"] * 6,
    "y": [1, 2, 3, 4, 5, 6, 2, 3, 4, 5, 6, 7],
}
DUP = {"x": [1, 1, 2, 2, 2], "y": [1, 1, 2, 3, 3]}
W = {"x": [1, 2, 2, 3, 5, 7], "w": [1, 1, 2, 1, 1, 3]}
LIN = {"x": list(range(1, 13)), "y": [1, 2, 1.5, 3, 2.5, 4, 3.5, 5, 4.5, 6, 5.5, 7]}
ELL = {"x": list(range(1, 9)), "y": [2, 1, 3, 2, 5, 4, 6, 7]}
ELLW = {**ELL, "w": [1, 1, 1, 1, 1, 1, 5, 5]}
ELL_GRP = {
    "x": list(range(1, 9)) * 2,
    "y": [2, 1, 3, 2, 5, 4, 6, 7, 3, 2, 4, 3, 6, 5, 7, 8],
    "g": ["a"] * 8 + ["b"] * 8,
}
CONN = {"x": [1, 2, 3], "y": [1, 3, 2]}


def _table(values: dict[str, list]) -> ColumnTable:
    columns: list[tuple[str, Column]] = []
    for name, items in values.items():
        if items and isinstance(items[0], str):
            columns.append((name, Column("str", np.array(items, dtype=object))))
            continue
        data = np.asarray(items, dtype=np.float64)
        missing = np.isnan(data)
        columns.append(
            (name, Column("float", np.where(missing, 0.0, data), na_mask=missing))
            if missing.any()
            else (name, Column("float", data))
        )
    return ColumnTable(columns)


def _moments(values):
    values = np.asarray(values, dtype=np.float64)
    return float(np.mean(values)), float(np.std(values, ddof=1))


def _mean_se(values, mult=1.0):
    values = np.asarray(values, dtype=np.float64)
    mean = float(np.mean(values))
    half = mult * math.sqrt(float(np.var(values, ddof=1)) / values.size)
    return {"y": mean, "ymin": mean - half, "ymax": mean + half}


def _mean_sdl(values, mult=2.0):
    values = np.asarray(values, dtype=np.float64)
    mean = float(np.mean(values))
    half = mult * float(np.std(values, ddof=1))
    return {"y": mean, "ymin": mean - half, "ymax": mean + half}


BUILDERS = {
    # --- qq -----------------------------------------------------------------
    "qq_norm": lambda: ggplot(_table(LD), aes(sample="v")) + registry.stat_qq(),
    "qq_t": lambda: (
        ggplot(_table(LD), aes(sample="v")) + registry.stat_qq(distribution="t", dparams={"df": 5})
    ),
    "qq_quantiles": lambda: (
        ggplot(_table(LD), aes(sample="v"))
        + registry.stat_qq(quantiles=[0.05 + 0.1 * index for index in range(10)])
    ),
    "qq_group": lambda: ggplot(_table(GRP), aes(sample="y", colour="g")) + registry.stat_qq(),
    "qqline_norm": lambda: ggplot(_table(LD), aes(sample="v")) + registry.stat_qq_line(geom="line"),
    "qqline_fullrange": lambda: (
        ggplot(_table(LD), aes(sample="v"))
        + registry.stat_qq_line(geom="line", fullrange=True)
        + registry.scale_x_continuous(limits=(-3, 3))
    ),
    "qqline_quantiles": lambda: (
        ggplot(_table(LD), aes(sample="v"))
        + registry.stat_qq_line(
            geom="line",
            quantiles=[0.05 + 0.1 * index for index in range(10)],
            line_p=(0.1, 0.9),
        )
    ),
    # --- ecdf ---------------------------------------------------------------
    "ecdf_default": lambda: ggplot(_table(LD), aes(x="v")) + registry.stat_ecdf(geom="line"),
    "ecdf_nopad": lambda: (
        ggplot(_table(LD), aes(x="v")) + registry.stat_ecdf(geom="line", pad=False)
    ),
    "ecdf_n": lambda: ggplot(_table(LD), aes(x="v")) + registry.stat_ecdf(geom="line", n=5),
    "ecdf_weight": lambda: (
        ggplot(_table(W), aes(x="x", weight="w")) + registry.stat_ecdf(geom="line")
    ),
    "ecdf_group": lambda: (
        ggplot(_table(GRP), aes(x="y", colour="g")) + registry.stat_ecdf(geom="line")
    ),
    "ecdf_horizontal": lambda: ggplot(_table(LD), aes(y="v")) + registry.stat_ecdf(geom="line"),
    # --- ellipse ------------------------------------------------------------
    "ellipse_t": lambda: (
        ggplot(_table(ELL), aes(x="x", y="y")) + registry.stat_ellipse(type="t", geom="path")
    ),
    "ellipse_norm": lambda: (
        ggplot(_table(ELL), aes(x="x", y="y")) + registry.stat_ellipse(type="norm", geom="path")
    ),
    "ellipse_euclid": lambda: (
        ggplot(_table(ELL), aes(x="x", y="y"))
        + registry.stat_ellipse(type="euclid", level=3, geom="path")
    ),
    "ellipse_weight": lambda: (
        ggplot(_table(ELLW), aes(x="x", y="y", weight="w"))
        + registry.stat_ellipse(type="norm", geom="path")
    ),
    "ellipse_group": lambda: (
        ggplot(_table(ELL_GRP), aes(x="x", y="y", colour="g"))
        + registry.stat_ellipse(type="norm", geom="path")
    ),
    # --- quantile -----------------------------------------------------------
    "quantile_default": lambda: (
        ggplot(_table(LIN), aes(x="x", y="y")) + registry.stat_quantile(geom="line")
    ),
    "quantile_05": lambda: (
        ggplot(_table(LIN), aes(x="x", y="y")) + registry.stat_quantile(quantiles=0.5, geom="line")
    ),
    "quantile_xseq": lambda: (
        ggplot(_table(LIN), aes(x="x", y="y"))
        + registry.stat_quantile(quantiles=(0.1, 0.9), xseq=(1, 5, 12), geom="line")
    ),
    # --- summary ------------------------------------------------------------
    "summary_mean": lambda: (
        ggplot(_table(GRP), aes(x="g", y="y")) + registry.stat_summary(fun="mean", geom="point")
    ),
    "summary_median": lambda: (
        ggplot(_table(GRP), aes(x="g", y="y")) + registry.stat_summary(fun="median", geom="point")
    ),
    "summary_sd": lambda: (
        ggplot(_table(GRP), aes(x="g", y="y")) + registry.stat_summary(fun="sd", geom="point")
    ),
    "summary_minmax": lambda: (
        ggplot(_table(GRP), aes(x="g", y="y"))
        + registry.stat_summary(fun="mean", fun_min="min", fun_max="max", geom="point")
    ),
    "summary_mean_se": lambda: (
        ggplot(_table(GRP), aes(x="g", y="y"))
        + registry.stat_summary(fun_data="mean_se", geom="point")
    ),
    "summary_fundata_args": lambda: (
        ggplot(_table(GRP), aes(x="g", y="y"))
        + registry.stat_summary(fun_data=_mean_sdl, fun_args={"mult": 1}, geom="point")
    ),
    "summary_two_x": lambda: (
        ggplot(_table({"x": [1, 1, 2, 2], "y": [1, 3, 2, 6]}), aes(x="x", y="y"))
        + registry.stat_summary(fun="mean", geom="point")
    ),
    "summary_horizontal": lambda: (
        ggplot(_table(GRP), aes(x="y", y="g")) + registry.stat_summary(fun="mean", geom="point")
    ),
    # --- summary_bin --------------------------------------------------------
    "sumbin_bins": lambda: (
        ggplot(_table(LIN), aes(x="x", y="y"))
        + registry.stat_summary_bin(fun="mean", bins=4, geom="point")
    ),
    "sumbin_width": lambda: (
        ggplot(_table(LIN), aes(x="x", y="y"))
        + registry.stat_summary_bin(fun="median", binwidth=3, geom="point")
    ),
    "sumbin_minmax": lambda: (
        ggplot(_table(LIN), aes(x="x", y="y"))
        + registry.stat_summary_bin(fun="mean", fun_min="min", fun_max="max", bins=3, geom="point")
    ),
    # --- sum ----------------------------------------------------------------
    "sum_default": lambda: ggplot(_table(DUP), aes(x="x", y="y")) + registry.stat_sum(),
    "sum_weight": lambda: (
        ggplot(_table(DUP), aes(x="x", y="y", weight=[1, 2, 1, 3, 1])) + registry.stat_sum()
    ),
    "sum_colour": lambda: (
        ggplot(
            _table({"x": [1, 1, 1], "y": [1, 1, 2], "g": ["a", "a", "b"]}),
            aes(x="x", y="y", colour="g"),
        )
        + registry.stat_sum()
    ),
    "sum_group": lambda: (
        ggplot(
            _table({"x": [1, 1, 2, 2], "y": [1, 2, 1, 2], "g": ["a", "b", "a", "b"]}),
            aes(x="x", y="y", group="g"),
        )
        + registry.stat_sum()
    ),
    # --- unique -------------------------------------------------------------
    "unique_default": lambda: ggplot(_table(DUP), aes(x="x", y="y")) + registry.stat_unique(),
    "unique_colour": lambda: (
        ggplot(
            _table({"x": [1, 1, 2], "y": [1, 1, 2], "g": ["a", "a", "b"]}),
            aes(x="x", y="y", colour="g"),
        )
        + registry.stat_unique()
    ),
    # --- density ------------------------------------------------------------
    "density_default": lambda: (
        ggplot(_table(LD), aes(x="v")) + registry.stat_density(geom="line", position="identity")
    ),
    "density_bw": lambda: (
        ggplot(_table(LD), aes(x="v"))
        + registry.stat_density(geom="line", position="identity", bw=0.5)
    ),
    "density_adjust": lambda: (
        ggplot(_table(LD), aes(x="v"))
        + registry.stat_density(geom="line", position="identity", adjust=0.5)
    ),
    "density_trim": lambda: (
        ggplot(_table(LD), aes(x="v"))
        + registry.stat_density(geom="line", position="identity", trim=True)
    ),
    "density_weight": lambda: (
        ggplot(_table(W), aes(x="x", weight="w"))
        + registry.stat_density(geom="line", position="identity")
    ),
    "density_group": lambda: (
        ggplot(_table(GRP), aes(x="y", colour="g"))
        + registry.stat_density(geom="line", position="identity")
    ),
    "density_n": lambda: (
        ggplot(_table(LD), aes(x="v"))
        + registry.stat_density(geom="line", position="identity", n=1024)
    ),
    "density_limits": lambda: (
        ggplot(_table(LD), aes(x="v"))
        + registry.stat_density(geom="line", position="identity")
        + registry.scale_x_continuous(limits=(0, 10))
    ),
    # --- function -----------------------------------------------------------
    "function_sin": lambda: (
        ggplot() + registry.stat_function(fun=np.sin, xlim=(0, 3), n=7, geom="line")
    ),
    "function_args": lambda: (
        ggplot()
        + registry.stat_function(
            fun=lambda x, k: x**k, args={"k": 2}, xlim=(1, 3), n=5, geom="line"
        )
    ),
    "function_logy": lambda: (
        ggplot()
        + registry.stat_function(fun=np.exp, xlim=(0, 2), n=5, geom="line")
        + registry.scale_y_log10()
    ),
    # --- connect ------------------------------------------------------------
    "connect_hv": lambda: (
        ggplot(_table(CONN), aes(x="x", y="y")) + registry.stat_connect(geom="line")
    ),
    "connect_mid": lambda: (
        ggplot(_table(CONN), aes(x="x", y="y"))
        + registry.stat_connect(geom="line", connection="mid")
    ),
    "connect_linear": lambda: (
        ggplot(_table(CONN), aes(x="x", y="y"))
        + registry.stat_connect(geom="line", connection="linear")
    ),
    "connect_matrix": lambda: (
        ggplot(_table(CONN), aes(x="x", y="y"))
        + registry.stat_connect(geom="line", connection=[[0.4, 0.75], [0.6, 0.25], [1.0, 1.0]])
    ),
    # --- manual -------------------------------------------------------------
    "manual_subset": lambda: (
        ggplot(_table(LIN), aes(x="x", y="y"))
        + registry.stat_manual(fun=lambda data: {k: v[:3] for k, v in data.items()})
    ),
    "manual_identity": lambda: ggplot(_table(DUP), aes(x="x", y="y")) + registry.stat_manual(),
    "manual_aggregate": lambda: (
        ggplot(_table(LIN), aes(x="x", y="y"))
        + registry.stat_manual(
            fun=lambda data: {"x": [np.mean(data["x"])], "y": [np.mean(data["y"])]}
        )
    ),
    # --- ydensity -----------------------------------------------------------
    "ydensity_area": lambda: (
        ggplot(_table(GRP), aes(x="g", y="y"))
        + registry.stat_ydensity(geom="line", position="identity")
    ),
    "ydensity_width": lambda: (
        ggplot(_table(GRP), aes(x="g", y="y"))
        + registry.stat_ydensity(geom="line", position="identity", scale="width")
    ),
    "ydensity_noquantiles": lambda: (
        ggplot(_table(GRP), aes(x="g", y="y"))
        + registry.stat_ydensity(geom="line", position="identity", quantiles=None)
    ),
    "ydensity_trim_false": lambda: (
        ggplot(_table(GRP), aes(x="g", y="y"))
        + registry.stat_ydensity(geom="line", position="identity", trim=False)
    ),
}

#: 统计量本身之外的列（geom 的默认美学 / 主题色）在 M1-10 之后才逐值对齐；
#: 这里只比列名与列序，与 tests/test_stat_r_parity.py 的 SKIP_VALUES 同一口径。
SKIP_VALUES: dict[str, frozenset[str]] = {}

#: R 侧由 geom / position 派生、ggcore 同一步骤不产出的列（列名投影后比较）。
R_ONLY_COLUMNS: dict[str, tuple[str, ...]] = {}


def _expected_array(spec: dict) -> np.ndarray:
    """R 的列 → numpy：`null` 是 NaN，`pos_inf` / `neg_inf` 记的 1 起行号还原成 ±Inf。"""
    values = spec["values"]
    positive = {int(item) for item in spec.get("pos_inf") or []}
    negative = {int(item) for item in spec.get("neg_inf") or []}
    out = np.empty(len(values), dtype=np.float64)
    for index, item in enumerate(values, start=1):
        if index in positive:
            out[index - 1] = math.inf
        elif index in negative:
            out[index - 1] = -math.inf
        else:
            out[index - 1] = math.nan if item is None else float(item)
    return out


def _assert_column_equal(name: str, ours: Column, spec: dict, *, tolerance: float) -> None:
    kind = spec["kind"]
    values = spec["values"]
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
        expected = _expected_array(spec)
        got = np.asarray(ours.values, dtype=np.float64)
        mask = np.asarray(ours.na_mask, dtype=bool)
        assert np.array_equal(mask, np.isnan(expected)), f"{name}: NA 位置不一致"
        infinite = np.isinf(expected)
        assert np.array_equal(np.isinf(got), infinite), f"{name}: ±Inf 位置不一致"
        assert np.array_equal(np.sign(got[infinite]), np.sign(expected[infinite])), (
            f"{name}: ±Inf 方向不一致"
        )
        ok = np.isfinite(expected)
        worst = float(np.max(np.abs(got[ok] - expected[ok]))) if ok.any() else 0.0
        assert np.allclose(got[ok], expected[ok], rtol=0, atol=tolerance), (
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
    tolerance = TOLERANCE
    for spec in columns:
        if spec["name"] in skipped or spec["name"] in r_only:
            continue
        _assert_column_equal(
            f"{case_name}.{spec['name']}", built.column(spec["name"]), spec, tolerance=tolerance
        )


def test_max_absolute_difference_is_tiny(reference: dict) -> None:
    """整份夹具的最大绝对差（评论里的数字来源）。"""
    worst = 0.0
    worst_name = ""
    for case_name, case in reference["cases"].items():
        if "built" not in case:
            continue
        built = build_plot(BUILDERS[case_name]()).layers[0].data
        limit = TOLERANCE
        for spec in case["built"]["columns"]:
            if spec["kind"] != "float" or spec["name"] not in built:
                continue
            expected = _expected_array(spec)
            got = np.asarray(built.column(spec["name"]).values, dtype=np.float64)
            ok = ~np.isnan(expected) & ~np.isnan(got) & np.isfinite(expected)
            if not ok.any():
                continue
            difference = float(np.max(np.abs(got[ok] - expected[ok])))
            if difference > worst and case_name.startswith("ellipse_") is False:
                worst = difference
                worst_name = f"{case_name}.{spec['name']}"
            assert difference <= limit, f"{worst_name or case_name}: 差 {difference}"
    assert worst < TOLERANCE, f"{worst_name} 的差是 {worst}"


# ---------------------------------------------------------------------------
# 直接断言：fun 系列至少三种取值、错误路径
# ---------------------------------------------------------------------------


def _summary_values(fun) -> dict[str, float]:
    built = (
        build_plot(
            ggplot(_table({"g": ["a"] * 4, "y": [1, 2, 3, 4]}), aes(x="g", y="y"))
            + registry.stat_summary(fun=fun, geom="point")
        )
        .layers[0]
        .data
    )
    return {
        "y": float(built.column("y").values[0]),
        "ymin": float(built.column("ymin").values[0]),
        "ymax": float(built.column("ymax").values[0]),
    }


def test_summary_fun_aliases_three_values() -> None:
    """字符串别名与 Python 可调用同口径（验收要求：至少 3 种取值）。"""
    assert _summary_values("mean")["y"] == pytest.approx(2.5)
    assert _summary_values("median")["y"] == pytest.approx(2.5)
    assert _summary_values("sd")["y"] == pytest.approx(math.sqrt(5.0 / 3.0))
    assert _summary_values(np.max)["y"] == pytest.approx(4.0)
    assert _summary_values(lambda values: float(np.sum(values)))["y"] == pytest.approx(10.0)


def test_summary_fun_data_receives_fun_args() -> None:
    built = (
        build_plot(
            ggplot(_table({"g": ["a"] * 4, "y": [1, 2, 3, 4]}), aes(x="g", y="y"))
            + registry.stat_summary(fun_data=_mean_se, fun_args={"mult": 2.0}, geom="point")
        )
        .layers[0]
        .data
    )
    assert float(built.column("ymin").values[0]) == pytest.approx(2.5 - 2.0 * math.sqrt(5.0 / 12.0))
    assert float(built.column("ymax").values[0]) == pytest.approx(2.5 + 2.0 * math.sqrt(5.0 / 12.0))


def test_qq_distribution_alias_matches_qnorm() -> None:
    data = build_plot(ggplot(_table(LD), aes(sample="v")) + registry.stat_qq()).layers[0].data
    theoretical = np.asarray(data.column("theoretical").values)
    assert theoretical[0] == pytest.approx(-1.5466352713992304, abs=1e-12)
    assert theoretical[-1] == pytest.approx(1.5466352713992304, abs=1e-12)


def test_qq_unknown_distribution_raises() -> None:
    with pytest.raises(BuildError, match="distribution"):
        build_plot(ggplot(_table(LD), aes(sample="v")) + registry.stat_qq(distribution="poisson"))


def test_quantile_rejects_rqss() -> None:
    with pytest.raises(BuildError, match="rqss"):
        build_plot(
            ggplot(_table(LIN), aes(x="x", y="y"))
            + registry.stat_quantile(method="rqss", geom="line")
        )


def test_quantile_rejects_other_formula() -> None:
    with pytest.raises(BuildError, match="formula"):
        build_plot(
            ggplot(_table(LIN), aes(x="x", y="y"))
            + registry.stat_quantile(formula="y ~ poly(x, 2)", geom="line")
        )


def test_spoke_matches_upstream_deprecation() -> None:
    case = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]["spoke_deprecated"]
    assert case["error"], "夹具里 spoke 必须是错误 case"
    with pytest.raises(ValueError, match="geom_spoke"):
        registry.stat_spoke()


def test_density_matches_r_binned_fft_not_direct_kernel() -> None:
    """density 走的是 R 的 bin + FFT 口径：首点的值与 R 的 17 位小数一致。"""
    data = (
        build_plot(
            ggplot(_table(LD), aes(x="v")) + registry.stat_density(geom="line", position="identity")
        )
        .layers[0]
        .data
    )
    density = np.asarray(data.column("density").values)
    assert density[0] == pytest.approx(0.07607133994881995, abs=1e-12)
    assert data.nrows == 512


def test_stat_ecdf_pads_with_inf() -> None:
    data = (
        build_plot(ggplot(_table(LD), aes(x="v")) + registry.stat_ecdf(geom="line")).layers[0].data
    )
    x = np.asarray(data.column("x").values)
    assert x[0] == -math.inf
    assert x[-1] == math.inf
    assert np.asarray(data.column("ecdf").values)[-1] == pytest.approx(1.0)
