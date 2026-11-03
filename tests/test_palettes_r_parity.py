"""色板与 ggplot2 4.0.3 / scales 1.4.0 的逐色对拍（M2-4 B）。

夹具 `tests/fixtures/palettes_r_reference.json` 由
`pixi run -e refs refs:scales`（`tools/refs/palettes_ref.R`）生成。取值表本身
（`src/ggcore/palette_data.py`）也是同一个脚本生成的——**逐色入库，不靠近似公式**：

- RColorBrewer 的 `brewer.pal()` 是**逐 n 表**（`Blues` 的 3 色不是 9 色表的前 3 个），
  所以表里按 n 存整张；
- viridisLite 的 `viridis()` = 8 档 × 256 个量化色 → `colorRamp(space = "Lab",
  interpolate = "spline")` → 在 `seq(begin, end, length.out = n)` 上采样，
  `ggcore.palettes.viridis_pal()` 复刻了这条链路（含 R 的 convertColor 与 fmm 样条）。

口径见 `docs/notes/scales.md` §6。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ggcore.data import Column
from ggcore.palette_data import (
    BREWER_INFO,
    BREWER_PALETTES,
    GGPLOT2_VERSION,
    RCOLORBREWER_VERSION,
    VIRIDIS_MAP,
    VIRIDISLITE_VERSION,
)
from ggcore.palettes import (
    alpha_ordinal_pal,
    brewer_name,
    brewer_pal,
    grey_pal,
    hue_pal,
    linetype_pal,
    linewidth_ordinal_pal,
    shape_pal,
    size_ordinal_pal,
    viridis_pal,
)
from ggcore.scales import scale_type

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "palettes_r_reference.json"


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 来源与规模
# ---------------------------------------------------------------------------


def test_fixture_comes_from_pinned_versions(reference: dict) -> None:
    assert reference["generated_by"] == "tools/refs/palettes_ref.R"
    assert reference["ggplot2_version"] == "4.0.3"
    assert reference["locale"] == "C.UTF-8"
    # 取值表的来源版本必须与夹具一致（生成脚本一次写两份，漂移就是 bug）。
    assert reference["RColorBrewer_version"] == RCOLORBREWER_VERSION
    assert reference["viridisLite_version"] == VIRIDISLITE_VERSION
    assert reference["ggplot2_version"] == GGPLOT2_VERSION


def test_table_shape(reference: dict) -> None:
    """整表都在：35 个 brewer palette、8 档 viridis × 256 色。"""
    assert len(BREWER_PALETTES) == 35
    assert len(BREWER_INFO) == 35
    assert set(VIRIDIS_MAP) == set("ABCDEFGH")
    assert all(len(colors) == 256 for colors in VIRIDIS_MAP.values())
    for name, (max_n, kind) in BREWER_INFO.items():
        assert kind in ("div", "qual", "seq"), name
        assert sorted(BREWER_PALETTES[name]) == list(range(3, max_n + 1)), name


# ---------------------------------------------------------------------------
# brewer
# ---------------------------------------------------------------------------


def test_brewer_every_palette_first_mid_last(reference: dict) -> None:
    """每个 palette 在 maxcolors 下的首 / 中 / 尾色逐字节相同。"""
    assert len(reference["brewer"]) == 35
    for name, expected in reference["brewer"].items():
        palette = brewer_pal(type=expected["type"], palette=name)(expected["max"])
        assert palette == expected["all"], name
        assert palette[0] == expected["first"], name
        assert palette[(expected["max"] + 1) // 2 - 1] == expected["mid"], name
        assert palette[-1] == expected["last"], name


@pytest.mark.parametrize(
    "name", ["Blues", "Reds", "Set1", "Spectral", "Paired", "Greens", "Accent", "BrBG"]
)
def test_brewer_is_a_per_n_table_not_a_prefix(reference: dict, name: str) -> None:
    """`brewer.pal(n)` 不是「取最大表的前 n 个」——逐 n 表必须对得上。"""
    table = reference["brewer_n"][name]
    assert len(table) == len(BREWER_PALETTES[name])
    for n, expected in table.items():
        assert brewer_pal(palette=name)(int(n)) == expected, (name, n)
    # 序列 / 发散色板逐 n 重新插值，不是最大表的前缀——这条子断言防止把表
    # 生成成「截断」（qual 色板本来就是前缀，不参与）。
    if name in ("Blues", "Reds", "Spectral", "BrBG", "Greens"):
        largest = table[max(table, key=int)]
        assert any(table[n] != largest[: len(table[n])] for n in table), name


def test_brewer_type_and_number_map_to_palette_names() -> None:
    assert brewer_name(1, "seq") == "Blues"
    assert brewer_name(2, "qual") == "Dark2"
    assert brewer_name("Set3", "div") == "Set3"
    with pytest.warns(UserWarning):
        assert brewer_name("NotAPalette", "seq") == "Greens"


def test_brewer_n_below_three_falls_back_to_the_three_colour_table() -> None:
    """`brewer.pal(n < 3)` 会警告并回落 3 色表，再取前 n 个。"""
    assert brewer_pal(palette="Set1")(1) == ["#E41A1C"]
    assert brewer_pal(palette="Set1")(2) == ["#E41A1C", "#377EB8"]


def test_brewer_over_max_returns_na_tail() -> None:
    """`brewer.pal(n > maxcolors)` 只给 maxcolors 个，余下的索引是 NA。"""
    palette = brewer_pal(palette="Set1")(11)
    assert len(palette) == 11
    assert palette[-2:] == [None, None]


def test_brewer_direction_reverses() -> None:
    forward = brewer_pal(palette="Blues")(4)
    backward = brewer_pal(palette="Blues", direction=-1)(4)
    assert backward == forward[::-1]


# ---------------------------------------------------------------------------
# viridis
# ---------------------------------------------------------------------------


def test_viridis_every_option(reference: dict) -> None:
    """A–H 每档抽 n = 2/3/5/8 与 begin/end/direction/alpha 变体，逐字节相同。"""
    for option, samples in reference["viridis"].items():
        for key, expected in samples.items():
            if key == "begin_end":
                got = viridis_pal(begin=0.2, end=0.8, option=option)(5)
            elif key == "direction":
                got = viridis_pal(direction=-1, option=option)(5)
            elif key == "alpha":
                got = viridis_pal(alpha=0.5, option=option)(3)
            else:
                got = viridis_pal(option=option)(int(key))
            assert got == expected, (option, key)


def test_viridis_option_aliases() -> None:
    """`option` 也收 viridisLite 的名字（magma / inferno / …）。"""
    assert viridis_pal(option="magma")(5) == viridis_pal(option="A")(5)
    assert viridis_pal(option="viridis")(5) == viridis_pal(option="D")(5)
    assert viridis_pal(option="turbo")(5) == viridis_pal(option="H")(5)


def test_viridis_unknown_option_warns_and_falls_back() -> None:
    with pytest.warns(UserWarning):
        assert viridis_pal(option="nope")(3) == viridis_pal(option="D")(3)


def test_viridis_rejects_bad_arguments() -> None:
    from ggcore.palettes import PaletteError

    with pytest.raises(PaletteError):
        viridis_pal(begin=1.5)
    with pytest.raises(PaletteError):
        viridis_pal(direction=0)


def test_viridis_has_teeth(reference: dict) -> None:
    """改一位就红：viridis 不是「差不多」的公式。"""
    expected = reference["viridis"]["D"]["5"]
    got = viridis_pal(option="D")(5)
    assert got == expected
    mutated = list(got)
    mutated[2] = "#21908DFF" if mutated[2] != "#21908DFF" else "#000000"
    assert mutated != expected


# ---------------------------------------------------------------------------
# grey / hue / 数值型离散色板
# ---------------------------------------------------------------------------


def test_grey_matches_r(reference: dict) -> None:
    for n, expected in reference["grey"].items():
        assert grey_pal()(int(n)) == expected, n
    assert grey_pal(0.1, 0.9)(5) == reference["grey_custom"]["start01"]
    assert grey_pal(0.5, 1.0)(4) == reference["grey_custom"]["start05"]


def test_hue_matches_r(reference: dict) -> None:
    for n, expected in reference["hue"].items():
        assert hue_pal()(int(n)) == expected, n


def test_numeric_discrete_palettes_match_r(reference: dict) -> None:
    expected = reference["ordinal"]
    assert size_ordinal_pal()(6) == expected["size"]
    assert alpha_ordinal_pal()(6) == expected["alpha"]
    assert linewidth_ordinal_pal()(6) == expected["linewidth"]
    assert linetype_pal(6) == expected["linetype"]
    assert shape_pal(True)(6) == expected["shape"]
    assert shape_pal(False)(6) == expected["shape_open"]


def test_shape_palette_warns_above_six_levels() -> None:
    with pytest.warns(UserWarning):
        palette = shape_pal(True)(8)
    assert palette[:6] == [16, 17, 15, 3, 7, 8]
    assert palette[6:] == [None, None]


def test_linetype_palette_has_thirteen_levels() -> None:
    assert len(linetype_pal(13)) == 13
    from ggcore.palettes import PaletteError

    with pytest.raises(PaletteError):
        linetype_pal(14)


# ---------------------------------------------------------------------------
# scale_type
# ---------------------------------------------------------------------------


def test_scale_type_matches_r(reference: dict) -> None:
    """`scale_type()` 的 R 取值：character / factor / numeric / logical。

    R 还有两条非离散的：有序 factor → `("ordinal", "discrete")`、`Date` →
    `("date", "continuous")`。`ggcore.Column` 目前没有 ordered / date 标记
    （日期标度归 M2-4 A），所以这两项按 `docs/notes/scales.md` §9 记为未支持，
    这里只钉住能表达的那四类 + `datetime` 列。
    """
    assert scale_type(("a", "b")) == tuple(reference["scale_type"]["character"])
    assert scale_type(("a", "b", "c")) == tuple(reference["scale_type"]["factor"])
    assert scale_type((1, 2, 3)) == tuple(reference["scale_type"]["numeric"])
    assert scale_type((True, False)) == tuple(reference["scale_type"]["logical"])
    assert tuple(reference["scale_type"]["ordered"]) == ("ordinal", "discrete")
    assert tuple(reference["scale_type"]["date"]) == ("date", "continuous")


def test_scale_type_for_columns() -> None:
    import numpy as np

    assert scale_type(Column("float", np.array([1.0, 2.0]))) == ("continuous",)
    assert scale_type(Column("str", np.array(["a", "b"], dtype=object))) == ("discrete",)
    assert scale_type(Column("bool", np.array([True, False]))) == ("discrete",)
    categorical = Column("categorical", np.array([0, 1], dtype=np.int32), levels=("a", "b"))
    assert scale_type(categorical) == ("discrete",)
    assert scale_type(Column("datetime", np.array([0.0, 1.0]))) == ("datetime", "continuous")
    assert scale_type(Column("timedelta", np.array([0.0, 1.0]))) == ("continuous",)
