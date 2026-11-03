"""`stat_bindot` / `geom_dotplot` 的 R 对拍（SIL-787）。

期望值来自 ggplot2 4.0.3 的 `ggplot_build(p)$data[[1]]`（R 4.5.3，同一份
`set.seed(112)` 数据），只保留绘制期真正用到的列；容差按 IR 的 float32 缓冲
（1e-6）而不是 R 的双精度。
"""

from __future__ import annotations

import numpy as np

from ggcore.build import build_plot
from ggcore.plot import aes, geom_dotplot, ggplot
from ggio.frame import to_column_table

#: `test-geom-dotplot.R` 视觉测试块的 `dat`（`set.seed(112); rnorm(20)`）。
D1_X = [
    -0.31423169595047251,
    2.4033750787787032,
    -0.71826396266405201,
    -1.7606109629935416,
    -1.1252811743977724,
    -0.71954056575150671,
    1.310223977253826,
    0.45189845282321606,
    0.15217740702295823,
    0.65337078277679583,
    -0.94733553853243446,
    -1.071086252558543,
    -0.17605937002612163,
    1.8720502082968995,
    -0.51033837959979045,
    1.4388904417981778,
    1.1531709539424315,
    -0.15483976358124263,
    -0.2599055202700481,
    0.47136677086213369,
]


def _layer(plot: object, name: str) -> np.ndarray:
    build = build_plot(plot)  # type: ignore[arg-type]
    column = build.layers[0].data.column(name)
    return np.asarray(column.values, dtype=np.float64)


def _bins(plot: object) -> list[tuple[float, int]]:
    """`(bin 中心, 该 bin 的点数)`，按中心升序（R 的 `split()` 顺序）。"""
    x = _layer(plot, "x")
    counts: dict[float, int] = {}
    for value in x.tolist():
        key = round(value, 6)
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items())


def _stackpos(plot: object, center: float) -> list[float]:
    x = _layer(plot, "x")
    stackpos = _layer(plot, "stackpos")
    return sorted(stackpos[np.isclose(x, center, atol=1e-6)].tolist())


def test_dotdensity_bins_match_r() -> None:
    # 断点扫描口径：从 -Inf 起，`x >= binend` 开新 bin（半开区间）。
    expected = [
        (-1.760610963, 1),
        (-1.0363083565, 3),
        (-0.6149394727, 3),
        (-0.2345357298, 4),
        (0.3117720889, 3),
        (0.6533707828, 1),
        (1.2960306979, 3),
        (1.8720502083, 1),
        (2.4033750788, 1),
    ]
    plot = ggplot(to_column_table({"x": D1_X}), aes(x="x")) + geom_dotplot(binwidth=0.4)
    bins = _bins(plot)
    assert [count for _center, count in bins] == [count for _center, count in expected]
    centers = [center for center, _ in bins]
    assert np.allclose(centers, [center for center, _ in expected], atol=1e-6)


def test_histodot_bins_are_fixed_width() -> None:
    expected = [
        (-1.6, 1),
        (-1.2, 2),
        (-0.8, 3),
        (-0.4, 3),
        (0.0, 3),
        (0.4, 2),
        (0.8, 1),
        (1.2, 2),
        (1.6, 1),
        (2.0, 1),
        (2.4, 1),
    ]
    plot = ggplot(to_column_table({"x": D1_X}), aes(x="x")) + geom_dotplot(
        binwidth=0.4, method="histodot"
    )
    bins = _bins(plot)
    assert [count for _center, count in bins] == [count for _center, count in expected]
    centers = [center for center, _ in bins]
    assert np.allclose(centers, [center for center, _ in expected], atol=1e-6)


def test_binpositions_all_matches_the_dotdensity_bins() -> None:
    # `binpositions = "all"` 让所有组的 bin 中心取自整份数据（等价于单组），
    # 与默认的 bygroup 各自切 bin 不同。
    data = {"x": D1_X, "g": ["A", "B"] * 10}
    bygroup = ggplot(to_column_table(data), aes(x="x", fill="g")) + geom_dotplot(
        binwidth=0.4, alpha=0.4
    )
    aligned = ggplot(to_column_table(data), aes(x="x", fill="g")) + geom_dotplot(
        binwidth=0.4, alpha=0.4, binpositions="all"
    )
    dotdensity = ggplot(to_column_table({"x": D1_X}), aes(x="x")) + geom_dotplot(binwidth=0.4)
    aligned_centers = {center for center, _ in _bins(aligned)}
    assert aligned_centers == {center for center, _ in _bins(dotdensity)}
    assert aligned_centers != {center for center, _ in _bins(bygroup)}


def test_stackgroups_stacks_across_groups() -> None:
    data = {
        "x": ["A", "B", "C"] * 30,
        "y": [
            0.24887993672252107,
            2.3002587881560244,
            0.34407357929885268,
            -1.4977663208912044,
            -0.58758433165675328,
            -0.58469279265297269,
            -1.1205990348021924,
            0.49205171983606183,
            1.2326162706873334,
            0.51884209877988796,
            1.6653289953379988,
            0.15217428819980339,
            1.3330088320699756,
            -0.11312635979024291,
            0.29079286186156633,
            -0.56103860173402187,
            0.96620329329702181,
            1.0207828051246959,
            1.2033974143403428,
            0.15250668702484685,
            0.91859055286948732,
            -0.029472936987090824,
            -0.277222037705809,
            0.038432098256917215,
            2.2870604490585174,
            0.20185010496763192,
            0.96792349861687998,
            -1.4306470899384824,
            1.3768411527543938,
            1.2529906517770286,
            0.073561027835354897,
            0.34287107097199809,
            -0.3253027856738302,
            0.25177040639006176,
            -1.3042283750768202,
            -0.3665697778995598,
            -0.91310616144283874,
            0.0017302910206192952,
            -0.90483180613342473,
            -0.60076354316502056,
            -0.40462358365121154,
            -0.55942185906755659,
            -0.80847594259646705,
            1.2927839383260777,
            0.7841626812249084,
            0.47720927110228795,
            -0.63108789207386851,
            -0.6649123756098646,
            0.19511465527684818,
            0.48073563793413515,
            0.9059704504506777,
            1.5672244142183465,
            1.2909991406466983,
            -2.0718711119335711,
            0.7996848469058162,
            -0.7419642349815968,
            -1.363265798747116,
            0.053080729537229421,
            1.1405448007541588,
            0.30858454632943755,
            0.13576902412912278,
            -0.64194299702134505,
            -0.19982378816207119,
            0.33887515900166387,
            -0.97398280434253104,
            1.0951809442480671,
            -0.077863136718800449,
            2.5029410662844982,
            0.8879866230663479,
            1.2036485337845353,
            0.64555647411025319,
            -0.25234371565020092,
            -0.96069143361769982,
            0.16674026253659979,
            -0.07538117981102184,
            0.69172324326952639,
            -0.90270234513384051,
            -0.59476760948903695,
            -1.0515527530041857,
            -0.065724062725264293,
            1.111791472905175,
            0.077596463762945295,
            0.80506399888452185,
            -0.71034094097585454,
            0.46817656820136311,
            0.27655628660026388,
            -0.26463335737326671,
            -0.59256402592468982,
            0.85964675688526526,
            -0.34167750873657976,
        ],
        "g": ["A", "B"] * 45,
    }
    plot = ggplot(to_column_table(data), aes(x="y", fill="x")) + geom_dotplot(
        binwidth=0.25, stackgroups=True, method="histodot", alpha=0.5
    )
    bins = _bins(plot)
    expected_counts = [1, 2, 2, 7, 6, 8, 7, 10, 14, 5, 6, 8, 8, 2, 1, 2, 1]
    assert [count for _center, count in bins] == expected_counts
    # `stackgroups = TRUE` 时 countidx 跨组连续：每个 bin 的最大堆叠序号 == 点数。
    for center, count in bins:
        assert _stackpos(plot, center)[-1] == count - 0.5


def test_stackdir_center_and_centerwhole_offsets() -> None:
    data = {"x": D1_X}
    center = ggplot(to_column_table(data), aes(x="x")) + geom_dotplot(
        binwidth=0.4, stackdir="center"
    )
    whole = ggplot(to_column_table(data), aes(x="x")) + geom_dotplot(
        binwidth=0.4, stackdir="centerwhole"
    )
    # 点数最多的 bin 是 4（中心 -0.2345357298）：center 以 0 为中心，
    # centerwhole 的下缘贴齐。两者都由 `GeomDotplot$setup_data()` 的
    # `stackdots()` 决定。
    assert np.allclose(_stackpos(center, -0.23453573), [-1.5, -0.5, 0.5, 1.5])
    assert np.allclose(_stackpos(whole, -0.23453573), [-1.0, 0.0, 1.0, 2.0])
