"""`sf_graticule_labels()`：`CoordSf$labels(panel_params)` 的移植（SIL-839）。

上游那张表（`b$layout$coord$labels(pp)`）每行是
`x` / `y` / `label` / `angle_start` / `angle_end`，这里验证我们的选线与取点规则：

- 经线（type `E`）贴**上下**边、纬线（type `N`）贴**左右**边；
- 落在 `_start` 端还是 `_end` 端由边的位置决定（下/左取 start，上/右取 end）；
- 角度取该端点的切线方向（竖直经线 90°、水平纬线 0°）。
"""

from __future__ import annotations

import pytest

from ggcore.coord import sf_graticule_labels
from ggcore.sf import GraticuleLine

RANGES = {"x": (0.0, 1.0), "y": (0.0, 1.0)}

#: 一条竖直经线：从下边界走到上边界。
MERIDIAN = GraticuleLine(type="E", degree=-90.0, label="-90", coords=((0.5, 0.0), (0.5, 1.0)))
#: 一条水平纬线：从左边界走到右边界。
PARALLEL = GraticuleLine(type="N", degree=30.0, label="30", coords=((0.0, 0.5), (1.0, 0.5)))


def test_graticule_labels_bottom_and_top_take_meridians() -> None:
    rows = sf_graticule_labels([MERIDIAN], ("S", "N"), RANGES)
    assert [(row.x, row.y) for row in rows] == [(0.5, 0.0), (0.5, 1.0)]
    assert [row.label for row in rows] == ["-90", "-90"]
    assert [row.angle for row in rows] == [pytest.approx(90.0), pytest.approx(90.0)]


def test_graticule_labels_left_and_right_take_parallels() -> None:
    rows = sf_graticule_labels([PARALLEL], ("W", "E"), RANGES)
    assert [(row.x, row.y) for row in rows] == [(0.0, 0.5), (1.0, 0.5)]
    assert [row.label for row in rows] == ["30", "30"]
    assert [row.angle for row in rows] == [pytest.approx(0.0), pytest.approx(0.0)]


def test_graticule_labels_nswe_covers_all_four_sides() -> None:
    rows = sf_graticule_labels([MERIDIAN, PARALLEL], tuple("NSWE"), RANGES)
    coords = {(round(row.x, 6), round(row.y, 6)) for row in rows}
    # 经线的下/上端点 + 纬线的左/右端点，四条边各一个。
    assert coords == {(0.5, 0.0), (0.5, 1.0), (0.0, 0.5), (1.0, 0.5)}


def test_graticule_labels_empty_when_not_requested() -> None:
    assert sf_graticule_labels([MERIDIAN, PARALLEL], (), RANGES) == ()


def test_graticule_labels_only_start_side_when_single_letter() -> None:
    rows = sf_graticule_labels([MERIDIAN], ("S",), RANGES)
    assert len(rows) == 1
    assert (rows[0].x, rows[0].y) == (0.5, 0.0)
