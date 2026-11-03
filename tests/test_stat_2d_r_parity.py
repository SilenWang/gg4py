"""M2-6 与 ggplot2 4.0.3 的 2D stat 对拍。

夹具由 `pixi run -e refs refs:stat`（`tools/refs/stat_ref.R`）生成，跑测试不需要 R。

对拍分两层（口径见 `docs/notes/stat.md` §9）：

1. **逐列对拍**（`bin_2d` / `bin_hex` / `summary_2d` / `summary_hex` /
   `density_2d(contour = FALSE)`）：列名、列序、kind、逐值、NA 与
   `ggplot_build(p)$data[[1]]` 一致，浮点 `atol = 1e-9`。
2. **层级边界对拍**（`contour` / `contour_filled` / `density_2d` /
   `density_2d_filled`）：上游用 isoband、我们用 contourpy，鞍点单元与闭合环
   的拆分不同，顶点数本来就不会相等；所以只钉层级数值（`level` /
   `level_low` / `level_high` / `level_mid` / 标签），几何另加一条自洽断言
   （每个顶点落回同一层级的线性插值上）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ggcore import registry
from ggcore.build import BuildWarning, build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom import GeomError, build_only_renderers, renderer_for
from ggcore.plot import aes, ggplot

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "stat_r_reference.json"
TOLERANCE = 1e-9

#: 几何顶点不会与 R 逐行相同（isoband vs contourpy），只比层级的两族。
CONTOUR_CASES = frozenset(
    {
        "contour_default",
        "contour_bins",
        "contour_binwidth",
        "contour_breaks",
        "contour_na",
        "contour_filled",
        "density2d_default",
        "density2d_h",
        "density2d_filled",
    }
)


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 数据集（与 tools/refs/stat_ref.R 同一份数字）
# ---------------------------------------------------------------------------

FLAT = {
    "x": [1, 1, 2, 2, 2, 3, 4, 4, 4, 4],
    "y": [1, 2, 2, 3, 4, 4, 1, 3, 4, 5],
    "z": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
}
FLAT_NA = {
    "x": [*FLAT["x"][:8], np.nan, 2.0, *FLAT["x"][8:]],
    "y": [*FLAT["y"][:8], 1.0, np.nan, *FLAT["y"][8:]],
    "z": [*FLAT["z"][:8], 11.0, 12.0, *FLAT["z"][8:]],
}
FLAT_ZNA = {
    **FLAT,
    "z": [np.nan if index in (1, 6) else value for index, value in enumerate(FLAT["z"])],
}
FLAT_GROUP = {**FLAT, "g": ["a"] * 5 + ["b"] * 5}
GRID = {
    "x": [x for _ in range(1, 5) for x in range(1, 6)],
    "y": [y for y in range(1, 5) for _ in range(1, 6)],
    "z": [x * 0.5 + y for y in range(1, 5) for x in range(1, 6)],
}
GRID_NA = {**GRID, "z": [np.nan if index == 6 else value for index, value in enumerate(GRID["z"])]}
POINTS = {
    "x": [1, 2, 3, 4, 5, 2, 3, 4, 5, 6, 1.5, 2.5, 3.5],
    "y": [2, 3, 2, 4, 3, 5, 4, 5, 3, 2, 3.2, 4.1, 2.8],
}
POINTS_NA = {
    "x": [*POINTS["x"][:10], np.nan, *POINTS["x"][10:]],
    "y": [*POINTS["y"][:10], 3.0, *POINTS["y"][10:]],
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
                columns.append(
                    (name, Column("float", np.where(missing, 0.0, data), na_mask=missing))
                )
            else:
                columns.append((name, Column("float", data)))
    return ColumnTable(columns)


BUILDERS = {
    "bin2d_default": lambda: ggplot(_table(FLAT), aes(x="x", y="y")) + registry.stat_bin_2d(),
    "bin2d_binwidth": lambda: (
        ggplot(_table(FLAT), aes(x="x", y="y")) + registry.stat_bin_2d(binwidth=[1, 1])
    ),
    "bin2d_bins": lambda: ggplot(_table(FLAT), aes(x="x", y="y")) + registry.stat_bin_2d(bins=4),
    "bin2d_na": lambda: (
        ggplot(_table(FLAT_NA), aes(x="x", y="y")) + registry.stat_bin_2d(binwidth=[1, 1])
    ),
    "bin2d_group": lambda: (
        ggplot(_table(FLAT_GROUP), aes(x="x", y="y", fill="g"))
        + registry.stat_bin_2d(binwidth=[1, 1])
    ),
    "bin_hex_default": lambda: ggplot(_table(FLAT), aes(x="x", y="y")) + registry.stat_bin_hex(),
    "bin_hex_binwidth": lambda: (
        ggplot(_table(FLAT), aes(x="x", y="y")) + registry.stat_bin_hex(binwidth=[1, 1])
    ),
    "bin_hex_na": lambda: (
        ggplot(_table(FLAT_NA), aes(x="x", y="y")) + registry.stat_bin_hex(binwidth=[1, 1])
    ),
    "summary2d_default": lambda: (
        ggplot(_table(FLAT), aes(x="x", y="y", z="z")) + registry.stat_summary_2d()
    ),
    "summary2d_binwidth": lambda: (
        ggplot(_table(FLAT), aes(x="x", y="y", z="z")) + registry.stat_summary_2d(binwidth=[1, 1])
    ),
    "summary2d_sum": lambda: (
        ggplot(_table(FLAT), aes(x="x", y="y", z="z"))
        + registry.stat_summary_2d(binwidth=[1, 1], fun="sum")
    ),
    "summary2d_na": lambda: (
        ggplot(_table(FLAT_ZNA), aes(x="x", y="y", z="z"))
        + registry.stat_summary_2d(binwidth=[1, 1])
    ),
    "summary_hex_default": lambda: (
        ggplot(_table(FLAT), aes(x="x", y="y", z="z")) + registry.stat_summary_hex()
    ),
    "summary_hex_binwidth": lambda: (
        ggplot(_table(FLAT), aes(x="x", y="y", z="z")) + registry.stat_summary_hex(binwidth=[1, 1])
    ),
    "contour_default": lambda: (
        ggplot(_table(GRID), aes(x="x", y="y", z="z")) + registry.stat_contour()
    ),
    "contour_bins": lambda: (
        ggplot(_table(GRID), aes(x="x", y="y", z="z")) + registry.stat_contour(bins=4)
    ),
    "contour_binwidth": lambda: (
        ggplot(_table(GRID), aes(x="x", y="y", z="z")) + registry.stat_contour(binwidth=1)
    ),
    "contour_breaks": lambda: (
        ggplot(_table(GRID), aes(x="x", y="y", z="z")) + registry.stat_contour(breaks=[2, 4, 6])
    ),
    "contour_na": lambda: (
        ggplot(_table(GRID_NA), aes(x="x", y="y", z="z")) + registry.stat_contour(bins=4)
    ),
    "contour_filled": lambda: (
        ggplot(_table(GRID), aes(x="x", y="y", z="z")) + registry.stat_contour_filled(bins=4)
    ),
    "density2d_default": lambda: (
        ggplot(_table(POINTS), aes(x="x", y="y")) + registry.stat_density_2d()
    ),
    "density2d_h": lambda: (
        ggplot(_table(POINTS), aes(x="x", y="y")) + registry.stat_density_2d(h=[1, 1], bins=4)
    ),
    "density2d_grid": lambda: (
        ggplot(_table(POINTS), aes(x="x", y="y")) + registry.stat_density_2d(contour=False, n=20)
    ),
    "density2d_na": lambda: (
        ggplot(_table(POINTS_NA), aes(x="x", y="y")) + registry.stat_density_2d(contour=False, n=20)
    ),
    "density2d_filled": lambda: (
        ggplot(_table(POINTS), aes(x="x", y="y")) + registry.stat_density_2d_filled(n=30)
    ),
}


def _built(case_name: str) -> ColumnTable:
    return build_plot(BUILDERS[case_name]()).layers[0].data


# ---------------------------------------------------------------------------
# 1. 逐列对拍（非 contour 族）
# ---------------------------------------------------------------------------


def _assert_column_equal(name: str, ours: Column, spec: dict) -> None:
    kind = spec["kind"]
    values = spec["values"]
    if kind == "int":
        assert ours.kind == "int", f"{name}: kind {ours.kind} != int"
        expected = np.array([np.nan if item is None else float(item) for item in values])
        got = np.asarray(ours.values, dtype=np.float64)
        mask = np.asarray(ours.na_mask, dtype=bool)
        assert np.array_equal(mask, np.isnan(expected)), f"{name}: NA 位置不一致"
        assert np.allclose(got[~mask], expected[~mask], rtol=0, atol=TOLERANCE), (
            f"{name}: 整数值不一致"
        )
        return
    if kind == "float":
        assert ours.kind == "float", f"{name}: kind {ours.kind} != float"
        expected = np.array([np.nan if item is None else float(item) for item in values])
        got = np.asarray(ours.values, dtype=np.float64)
        mask = np.asarray(ours.na_mask, dtype=bool)
        assert np.array_equal(mask, np.isnan(expected)), f"{name}: NA 位置不一致"
        ok = ~mask
        assert np.allclose(got[ok], expected[ok], rtol=0, atol=TOLERANCE), f"{name}: 数值不一致"
        return
    if kind == "bool":
        assert ours.kind == "bool", f"{name}: kind {ours.kind} != bool"
        expected = np.array([False if item is None else bool(item) for item in values])
        assert np.asarray(ours.values, dtype=bool).tolist() == expected.tolist(), (
            f"{name}: 布尔值不一致"
        )
        assert np.asarray(ours.na_mask, dtype=bool).tolist() == [item is None for item in values]
        return
    assert ours.kind == "str", f"{name}: kind {ours.kind} != str"
    expected_text = ["" if item is None else str(item) for item in values]
    assert ours.values.tolist() == expected_text, f"{name}: 字符串不一致"
    assert np.asarray(ours.na_mask, dtype=bool).tolist() == [item is None for item in values]


@pytest.mark.parametrize("case_name", sorted(set(BUILDERS) - CONTOUR_CASES))
def test_stat_matches_r_column_by_column(reference: dict, case_name: str) -> None:
    case = reference["cases"][case_name]
    built = _built(case_name)
    columns = case["built"]["columns"]
    assert case["built"]["rows"] == built.nrows, f"{case_name}: 行数不一致"
    assert built.names == tuple(spec["name"] for spec in columns), f"{case_name}: 列名/列序不一致"
    for spec in columns:
        _assert_column_equal(f"{case_name}.{spec['name']}", built.column(spec["name"]), spec)


# ---------------------------------------------------------------------------
# 2. 层级边界对拍（contour 族）
# ---------------------------------------------------------------------------


def _levels_from(case: dict, name: str) -> np.ndarray:
    for spec in case["built"]["columns"]:
        if spec["name"] == name:
            return np.array([float(item) for item in spec["values"] if item is not None])
    raise AssertionError(f"{name} 不在夹具列里")


def _levels_without_degenerate_lines(case: dict) -> np.ndarray:
    """R 的等值线层级，去掉「整条线只有重合点」的退化层级。

    isoband 在 level == max(z) 时会吐一段两点重合的退化线（`contour_default`
    的 6.5），contourpy 在同样输入下不给线。这是几何实现的差异，不是层级边界
    的差异；层级本身由 `test_contour_breaks_match_r_defaults` 单独钉住。
    """
    columns = {spec["name"]: spec["values"] for spec in case["built"]["columns"]}
    levels = np.array([float(item) for item in columns["level"]])
    xs = np.array([float(item) for item in columns["x"]])
    ys = np.array([float(item) for item in columns["y"]])
    kept: list[float] = []
    for level in np.unique(levels):
        rows = levels == level
        degenerate = bool(np.all(xs[rows] == xs[rows][0]) and np.all(ys[rows] == ys[rows][0]))
        if not degenerate:
            kept.append(float(level))
    return np.array(kept)


def test_contour_breaks_match_r_defaults() -> None:
    """`contour_breaks()` 的三种缺省（pretty / bins / binwidth）与 R 一致。"""
    from ggcore.contour import contour_breaks

    # 网格 z 的范围是 1.5..6.5：默认 pretty(z, 10) → 1.5, 2, …, 6.5。
    assert contour_breaks((1.5, 6.5)).tolist() == pytest.approx(
        [1.5 + 0.5 * index for index in range(11)]
    )
    # bins = 4：accuracy = signif(5, 1) / 10 = 0.5，再用 fullseq 把 1.5..6.5
    # 向外扩到 0..6.6667（与 R 的 `contour_breaks()` 同值）。
    assert contour_breaks((1.5, 6.5), bins=4).tolist() == pytest.approx(
        [0.0, 5 / 3, 10 / 3, 5.0, 20 / 3]
    )
    # binwidth = 1：fullseq 把范围向外扩到 1..7。
    assert contour_breaks((1.5, 6.5), binwidth=1).tolist() == pytest.approx(
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    )


@pytest.mark.parametrize("case_name", sorted(CONTOUR_CASES))
def test_contour_levels_match_r(reference: dict, case_name: str) -> None:
    case = reference["cases"][case_name]
    built = _built(case_name)
    if "level_low" in built:
        for name in ("level_low", "level_high", "level_mid"):
            ours = np.unique(np.asarray(built.column(name).values, dtype=np.float64))
            expected = np.unique(_levels_from(case, name))
            assert ours.shape == expected.shape, f"{case_name}.{name}: 层级数不一致"
            assert np.allclose(ours, expected, rtol=0, atol=TOLERANCE), (
                f"{case_name}.{name}: 层级边界不一致"
            )
        # level 是有序因子：标签集合与 R 的 levels 一致。
        ours_levels = tuple(built.column("level").levels)
        expected_levels = next(
            spec["levels"] for spec in case["built"]["columns"] if spec["name"] == "level"
        )
        assert ours_levels == tuple(expected_levels), f"{case_name}: 等值带标签不一致"
    else:
        ours = np.unique(np.asarray(built.column("level").values, dtype=np.float64))
        expected = _levels_without_degenerate_lines(case)
        assert ours.shape == expected.shape, (
            f"{case_name}: 层级数不一致（ours={ours.tolist()}，R={expected.tolist()}）"
        )
        assert np.allclose(ours, expected, rtol=0, atol=TOLERANCE), f"{case_name}: 层级数值不一致"
    # nlevel 是组内 rescale：等值线按 level、等值带按 level_high；逐行自洽。
    base = "level_high" if "level_high" in built else "level"
    values = np.asarray(built.column(base).values, dtype=np.float64)
    nlevel = np.asarray(built.column("nlevel").values, dtype=np.float64)
    assert np.allclose(nlevel, values / values.max(), rtol=0, atol=TOLERANCE), (
        f"{case_name}: nlevel 不是 rescale_max({base})"
    )


def _bilinear(grid: dict[str, list], x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """规则网格上的双线性插值（等值线顶点都落在网格边上，插值即精确值）。"""
    xs = np.unique(np.asarray(grid["x"], dtype=np.float64))
    ys = np.unique(np.asarray(grid["y"], dtype=np.float64))
    z = np.asarray(grid["z"], dtype=np.float64)
    raster = np.full((ys.size, xs.size), np.nan)
    raster[np.searchsorted(ys, grid["y"]), np.searchsorted(xs, grid["x"])] = z
    i = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, xs.size - 2)
    j = np.clip(np.searchsorted(ys, y, side="right") - 1, 0, ys.size - 2)
    x0, x1 = xs[i], xs[i + 1]
    y0, y1 = ys[j], ys[j + 1]
    z00, z01 = raster[j, i], raster[j, i + 1]
    z10, z11 = raster[j + 1, i], raster[j + 1, i + 1]
    tx = (x - x0) / (x1 - x0)
    ty = (y - y0) / (y1 - y0)
    return (1 - tx) * (1 - ty) * z00 + tx * (1 - ty) * z01 + (1 - tx) * ty * z10 + tx * ty * z11


@pytest.mark.parametrize(
    ("case_name", "grid"),
    [
        ("contour_default", GRID),
        ("contour_bins", GRID),
        ("contour_binwidth", GRID),
        ("contour_breaks", GRID),
        ("contour_filled", GRID),
    ],
)
def test_contour_vertices_sit_on_their_level_grid(case_name: str, grid: dict) -> None:
    """顶点必须落在自己层级上（双线性插值 == level，允许 1e-7 的浮点差）。

    等值带的**外边界顶点**在数据范围的四条边上，那里的 z 可以在带内任意位置
    （多边形沿数据域闭合），所以只对内部顶点断言「落在 low / high 上」。
    """
    built = _built(case_name)
    x = np.asarray(built.column("x").values, dtype=np.float64)
    y = np.asarray(built.column("y").values, dtype=np.float64)
    values = _bilinear(grid, x, y)
    xs = np.unique(np.asarray(grid["x"], dtype=np.float64))
    ys = np.unique(np.asarray(grid["y"], dtype=np.float64))
    on_boundary = (
        np.isclose(x, xs.min())
        | np.isclose(x, xs.max())
        | np.isclose(y, ys.min())
        | np.isclose(y, ys.max())
    )
    if "level_low" in built:
        low = np.asarray(built.column("level_low").values, dtype=np.float64)
        high = np.asarray(built.column("level_high").values, dtype=np.float64)
        distance = np.minimum(np.abs(values - low), np.abs(values - high))
        inside = ~on_boundary
    else:
        level = np.asarray(built.column("level").values, dtype=np.float64)
        distance = np.abs(values - level)
        inside = np.ones(distance.shape, dtype=bool)
    worst = np.nanmax(distance[inside]) if inside.any() else 0.0
    assert worst < 1e-7, f"{case_name}: 最大偏离 {worst:.3g}"


@pytest.mark.parametrize(
    ("case_name", "grid_params"),
    [
        ("density2d_default", {"n": 100}),
        ("density2d_h", {"h": [1, 1], "n": 100}),
        ("density2d_filled", {"n": 30}),
    ],
)
def test_density_contour_vertices_sit_on_their_level(case_name: str, grid_params: dict) -> None:
    """密度网格上的等值线：顶点处的双线性密度等于层级。

    密度网格由同一个 stat 以 `contour = FALSE` 再跑一遍得到（同一个 `h` / `n`
    / 标度范围），所以不需要在测试里重算 lims。
    """
    built = _built(case_name)
    companion = (
        build_plot(
            ggplot(_table(POINTS), aes(x="x", y="y"))
            + registry.stat_density_2d(contour=False, **grid_params)
        )
        .layers[0]
        .data
    )
    raster = {
        "x": np.asarray(companion.column("x").values, dtype=np.float64).tolist(),
        "y": np.asarray(companion.column("y").values, dtype=np.float64).tolist(),
        "z": np.asarray(companion.column("density").values, dtype=np.float64).tolist(),
    }
    dx = np.asarray(built.column("x").values, dtype=np.float64)
    dy = np.asarray(built.column("y").values, dtype=np.float64)
    values = _bilinear(raster, dx, dy)
    if "level_low" in built:
        low = np.asarray(built.column("level_low").values, dtype=np.float64)
        high = np.asarray(built.column("level_high").values, dtype=np.float64)
        distance = np.minimum(np.abs(values - low), np.abs(values - high))
        xs = np.unique(np.asarray(companion.column("x").values, dtype=np.float64))
        ys = np.unique(np.asarray(companion.column("y").values, dtype=np.float64))
        inside = ~(
            np.isclose(dx, xs.min())
            | np.isclose(dx, xs.max())
            | np.isclose(dy, ys.min())
            | np.isclose(dy, ys.max())
        )
        distance = distance[inside]
    else:
        level = np.asarray(built.column("level").values, dtype=np.float64)
        distance = np.abs(values - level)
    # 密度值的量级在 1e-2，1e-7 的绝对容差足够。
    assert np.nanmax(distance) < 1e-7


# ---------------------------------------------------------------------------
# 3. 行为断言（参数、别名、绘图边界、警告）
# ---------------------------------------------------------------------------


def test_default_number_of_bins_is_thirty(reference: dict) -> None:
    """`stat_bin_2d()` / `stat_summary_2d()` 缺省 bins = 30（不是 10 / 100）。"""
    for name in ("bin2d_default", "summary2d_default"):
        case = reference["cases"][name]
        rows = case["built"]["rows"]
        assert rows > 0
        assert _built(name).nrows == rows


def test_bin_2d_boundary_defaults_to_zero(reference: dict) -> None:
    """`stat_bin_2d` 的 boundary 缺省是 0（4.0.3 的向后兼容），不是 width / 2。"""
    built = _built("bin2d_binwidth")
    centers = np.asarray(built.column("x").values, dtype=np.float64).tolist()
    # x 范围 1..4、binwidth 1、boundary 0 → 箱边界 1..5，非空箱中心 1.5 / 2.5 / 3.5
    # （4.5 那箱没有观测，drop = TRUE 后不出现）。
    assert set(round(value, 6) for value in centers) == {1.5, 2.5, 3.5}


def test_aliases_map_to_the_canonical_stat() -> None:
    assert registry.stat_bin2d().stat.name == "bin_2d"
    assert registry.stat_binhex().stat.name == "bin_hex"
    assert registry.stat_summary2d().stat.name == "summary_2d"
    assert registry.stat_density2d().stat.name == "density_2d"


def test_na_rows_are_removed_before_the_stat() -> None:
    with pytest.warns(BuildWarning, match="Removed 2 rows"):
        _built("bin2d_na")
    # summary_2d 的 required_aes 含 z：两行 z = NA 一起删。
    with pytest.warns(BuildWarning, match="Removed 2 rows"):
        _built("summary2d_na")


def test_contour_deduplicates_duplicate_grid_points() -> None:
    duplicated = {
        "x": [1, 1, 2, 2, 1],
        "y": [1, 2, 1, 2, 1],
        "z": [1, 2, 3, 4, 5],
    }
    with pytest.warns(BuildWarning, match="duplicated"):
        build_plot(
            ggplot(_table(duplicated), aes(x="x", y="y", z="z")) + registry.stat_contour(bins=2)
        )


def test_2d_geoms_are_build_only_and_name_the_followup() -> None:
    assert build_only_renderers() == (
        "tile",
        "hex",
        "contour",
        "contour_filled",
        "density_2d",
        "density_2d_filled",
    )
    # 绘制归属要准确：`geom_tile` 已在 SIL-737 落地，其余 5 个归 SIL-735
    # （SIL-758 第 4 条；之前 6 个一律点名 SIL-735）。
    with pytest.raises(GeomError, match="SIL-737"):
        renderer_for("tile").draw(None, None, None, None, None, None)
    for name in ("hex", "contour", "contour_filled", "density_2d", "density_2d_filled"):
        with pytest.raises(GeomError, match="SIL-735") as raised:
            renderer_for(name).draw(None, None, None, None, None, None)
        assert "SIL-737" not in str(raised.value)


def test_density2d_contour_false_returns_the_grid() -> None:
    built = _built("density2d_grid")
    assert built.nrows == 400  # n = 20 ²
    assert {"density", "ndensity", "count", "n"}.issubset(set(built.names))


def test_bin_2d_counts_follow_the_weight_aesthetic() -> None:
    weighted = {**FLAT, "w": [1.0] * 5 + [2.0] * 5}
    built = (
        build_plot(
            ggplot(_table(weighted), aes(x="x", y="y", weight="w"))
            + registry.stat_bin_2d(binwidth=[1, 1])
        )
        .layers[0]
        .data
    )
    counts = np.asarray(built.column("count").values, dtype=np.float64)
    assert float(counts.sum()) == pytest.approx(15.0)
    assert float(built.column("density").values.sum()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4. 端到端（每个 stat 至少一条 ggplot() → build 的完整流水线）
# ---------------------------------------------------------------------------

#: 8 个 2D stat → 代表 case + 该族必须出现的统计列。
#:
#: M2-6 的 2D geom 只有 build 级实现（绘制归 SIL-737 的 `tile` 与 SIL-735 的其余
#: 5 个），所以端到端 case 的判据是「`ggplot() + stat_*()` 能走完整条
#: ggplot_build 流水线，且 `$data` 的统计列完整」；SVG 快照 case 等 geom 绘制
#: 落地后补（见 docs/notes/stat.md §10）。
END_TO_END: dict[str, tuple[str, frozenset[str]]] = {
    "bin_2d": ("bin2d_binwidth", frozenset({"count", "ncount", "density", "ndensity"})),
    "bin_hex": ("bin_hex_binwidth", frozenset({"count", "ncount", "density", "ndensity"})),
    "summary_2d": ("summary2d_binwidth", frozenset({"value", "xbin", "ybin"})),
    "summary_hex": ("summary_hex_binwidth", frozenset({"value"})),
    "contour": ("contour_bins", frozenset({"level", "nlevel", "piece", "group"})),
    "contour_filled": (
        "contour_filled",
        frozenset({"level", "level_low", "level_high", "level_mid", "nlevel"}),
    ),
    "density_2d": ("density2d_default", frozenset({"level", "nlevel"})),
    "density_2d_filled": (
        "density2d_filled",
        frozenset({"level", "level_low", "level_high", "level_mid"}),
    ),
}


@pytest.mark.parametrize("stat_name", sorted(END_TO_END))
def test_every_2d_stat_has_an_end_to_end_case(stat_name: str) -> None:
    case_name, required = END_TO_END[stat_name]
    build = build_plot(BUILDERS[case_name]())
    layer = build.layers[0]
    assert layer.stat == stat_name
    # 默认 geom 与 tbl(...) 的映射一致（stat_*() 的快捷方式）。
    assert layer.geom == registry.STAT_GEOMS[stat_name]
    data = layer.data
    assert data.nrows > 0, f"{stat_name}: 端到端 case 没有产出数据"
    missing = required - set(data.names)
    assert not missing, f"{stat_name}: 缺少统计列 {sorted(missing)}"
