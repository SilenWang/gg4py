"""M1-7 与 ggplot2 4.0.3 的对拍。

夹具由 `pixi run -e refs refs:geom`（`tools/refs/geom_ref.R`）生成，跑测试不需要 R：

- **identity / count stat 的 7 个 case**（point / point_na / line / path / bar /
  col / 横向 col）：在 Python 侧重放整条流水线，与 `ggplot_build(p)$data[[1]]`
  逐列对拍（列名、列序、kind、值、NA）；
- **4 个绘制输入 case**（histogram / boxplot / smooth）：把 R 的 `$data` 当
  **绘制输入**喂给 `Geom.draw()`，比节点数与几何（stat 自己的对拍在
  `tests/test_stat_r_parity.py`）；
- **handle_na**：R 的 "Removed N rows" 文案与我们的 warning 逐字对齐。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from ggcore import registry
from ggcore.build import BuildWarning, LayerBuild, build_plot
from ggcore.coord import PanelParams
from ggcore.data import Column, ColumnTable
from ggcore.geom import renderer_for
from ggcore.grobs import ViewportTree, scene, viewport
from ggcore.plot import aes, arrow, ggplot
from ggcore.theme import Theme, resolve_theme
from ggcore.viewport import Device

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "geom_r_reference.json"
#: 参数换算（9/.pt mm ↔ pt）会有 ~1e-7 的十进制往返误差；其余列仍是 1e-9。
TOLERANCE = 1e-6

#: 主题色列：`Geom.default_aes` 里存的是语义名（`grey35`），解析后的主题色是
#: M1-10 的事（与 tests/test_build_r_parity.py 的 SKIP_VALUES 同一口径）。
SKIP_VALUES: dict[str, frozenset[str]] = {
    # `ColumnTable` 没有 list kind：`outliers` 在两边是各自的文本表示
    # （R 的 `c(5)` vs 我们的 `5.0`），绘制层两种都能解析（docs/notes/stat.md §4）。
    "boxplot_horizontal_auto": frozenset({"outliers"}),
    "col_horizontal": frozenset({"fill"}),
    "col_default_width": frozenset({"fill"}),
    "boxplot_identity": frozenset({"colour"}),
}

#: R 在 identity stat 下仍带着 position_dodge2 的中间列（`stat_boxplot` 路径才产它们）；
#: 我们的列序 = R 列序去掉这几列的投影。
R_ONLY_COLUMNS: dict[str, tuple[str, ...]] = {
    "boxplot_identity": ("xid", "newx", "new_width"),
    "boxplot_horizontal_auto": ("xid", "newx", "new_width"),
}


@pytest.fixture(scope="module")
def reference() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 夹具 → ColumnTable
# ---------------------------------------------------------------------------


def _column(spec: dict) -> Column:
    values = spec["values"]
    kind = spec["kind"]
    if kind == "list":
        # 列表列（outliers）目前没有 bulk 表示；绘制层接受 `;` 分隔的文本。
        text = [
            ";".join("" if item is None else repr(float(item)) for item in row) if row else None
            for row in values
        ]
        mask = np.array([item is None for item in text], dtype=bool)
        return Column(
            "str",
            np.array(["" if item is None else item for item in text], dtype=object),
            na_mask=mask,
        )
    mask = np.array([value is None for value in values], dtype=bool)
    if kind == "float":
        data = np.array([0.0 if value is None else float(value) for value in values])
        return Column("float", data, na_mask=mask)
    if kind == "int":
        data = np.array([0 if value is None else int(value) for value in values], dtype=np.int64)
        return Column("int", data, na_mask=mask)
    if kind == "bool":
        return Column(
            "bool",
            np.array([False if value is None else bool(value) for value in values]),
            na_mask=mask,
        )
    data = np.array(["" if value is None else str(value) for value in values], dtype=object)
    return Column("str", data, na_mask=mask)


def _table(case: dict) -> ColumnTable:
    data = case["data"]
    return ColumnTable(
        [(spec["name"], _column(spec)) for spec in data["columns"]], nrows=data["rows"]
    )


def _panel(case: dict) -> PanelParams:
    params = case["panel_params"]
    return PanelParams(
        x_range=tuple(params["x_range"]),
        y_range=tuple(params["y_range"]),
        x_limits=tuple(params["x_range"]),
        y_limits=tuple(params["y_range"]),
        discrete={"x": bool(params["discrete_x"]), "y": bool(params["discrete_y"])},
    )


def _layer_build(geom_name: str, case: dict) -> LayerBuild:
    empty = ColumnTable([], nrows=0)
    layer = registry.construct("geom", geom_name)
    return LayerBuild(
        index=0,
        geom=layer.geom.name,
        stat=case["stat"],
        position="identity",
        aesthetics=empty,
        statistic=empty,
        mapped=empty,
        positioned=empty,
        scaled=empty,
        data=_table(case),
        dropped_missing={},
        empty=False,
        notes=(),
        params=layer.params,
        geom_object=layer.geom,
    )


_CASE_GEOM = {
    "point_shapes": "point",
    "point_na": "point",
    "line_groups": "line",
    "path_basic": "path",
    "bar_stacked": "bar",
    "col_identity": "col",
    "col_horizontal": "col",
    "col_default_width": "col",
    "area_identity": "area",
    "histogram_stat": "histogram",
    "histogram_identity": "histogram",
    "boxplot_stat": "boxplot",
    "boxplot_identity": "boxplot",
    "smooth_stat": "smooth",
    "smooth_identity": "smooth",
}


# ---------------------------------------------------------------------------
# 1. stat 已实现的 case：整条流水线逐列对拍
# ---------------------------------------------------------------------------


def _float(**columns: list) -> ColumnTable:
    built: list[tuple[str, Column]] = []
    for name, values in columns.items():
        if values and isinstance(values[0], str):
            built.append((name, Column("str", np.array(values, dtype=object))))
        else:
            built.append((name, Column("float", np.array(values, dtype=float))))
    return ColumnTable(built)


POINT = dict(
    x=[0.1, 0.35, 0.65, 0.9] * 4,
    y=[0.15] * 4 + [0.4] * 4 + [0.6] * 4 + [0.85] * 4,
    g=["a", "b", "a", "b"] * 4,
    sh=[19, 15, 19, 15] * 4,
)


def _point_rows(shape: int) -> ColumnTable:
    keep = [value == shape for value in POINT["sh"]]
    return _float(
        **{
            name: [item for item, flag in zip(values, keep, strict=True) if flag]
            for name, values in POINT.items()
        }
    )


BUILDERS = {
    "point_shapes": lambda: (
        ggplot(
            _point_rows(19),
            aes(x="x", y="y", colour="g"),
        )
        + registry.geom_point(shape=19, size=9 / 2.845276, stroke=0)
        + registry.scale_colour_discrete(values={"a": "#F8766D", "b": "#00BA38"})
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "point_na": lambda: (
        ggplot(
            ColumnTable(
                [
                    ("x", Column("float", np.array([0.1, 0.3, 0.5, 0.7, 0.9]))),
                    (
                        "y",
                        Column(
                            "float",
                            np.array([0.2, 0.0, 0.6, 0.8, 0.0]),
                            na_mask=np.array([False, True, False, False, True]),
                        ),
                    ),
                    ("g", Column("str", np.array(["a", "a", "b", "b", "a"], dtype=object))),
                ]
            ),
            aes(x="x", y="y", colour="g"),
        )
        + registry.geom_point(size=8 / 2.845276, stroke=0)
        + registry.scale_colour_discrete(values={"a": "#F8766D", "b": "#00BA38"})
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "line_groups": lambda: (
        ggplot(
            _float(
                x=[0.1, 0.3, 0.5, 0.7, 0.9, 0.1, 0.3, 0.5, 0.7, 0.9],
                y=[0.2, 0.5, 0.4, 0.7, 0.6, 0.8, 0.6, 0.7, 0.3, 0.4],
                g=["a"] * 5 + ["b"] * 5,
            ),
            aes(x="x", y="y", colour="g", group="g"),
        )
        + registry.geom_line(linewidth=1.2 / 2.845276)
        + registry.scale_colour_discrete(values={"a": "#4C78A8", "b": "#E45756"})
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "path_basic": lambda: (
        ggplot(
            _float(x=[0.15, 0.85, 0.25, 0.9, 0.1], y=[0.2, 0.55, 0.8, 0.25, 0.6]),
            aes(x="x", y="y"),
        )
        + registry.geom_path(colour="#4C78A8", linewidth=1.2 / 2.845276)
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "bar_stacked": lambda: (
        ggplot(
            _float(
                cls=["a", "b", "a", "c", "b", "a", "c", "c"],
                grp=["p", "p", "q", "p", "q", "p", "p", "q"],
            ),
            aes(x="cls", fill="grp"),
        )
        + registry.geom_bar()
        + registry.scale_fill_discrete(values={"p": "#4C78A8", "q": "#F58518"})
        + registry.scale_y_continuous(limits=(0, 4), expand=(0, 0))
        + registry.theme_void()
    ),
    "col_identity": lambda: (
        ggplot(
            _float(x=[0.5, 1.5, 2.5, 3.5], y=[0.35, 0.75, 0.55, 0.9], g=["a", "b", "a", "b"]),
            aes(x="x", y="y", fill="g"),
        )
        + registry.geom_col(width=0.7)
        + registry.scale_fill_discrete(values={"a": "#4C78A8", "b": "#F58518"})
        + registry.scale_x_continuous(limits=(0, 4), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "col_horizontal": lambda: (
        ggplot(
            _float(cls=["a", "b", "c", "d"], v=[0.3, 0.7, 0.5, 0.9]),
            aes(y="cls", x="v"),
        )
        + registry.geom_col(width=0.7)
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_discrete(expand=(0.6, 0.6))
        + registry.theme_void()
    ),
    "col_default_width": lambda: (
        ggplot(_float(x=[0, 10, 20], y=[1, 2, 3]), aes(x="x", y="y"))
        + registry.geom_col()
        + registry.coord_cartesian(xlim=(0, 20), expand=(0, 0))
        + registry.theme_void()
    ),
    "area_identity": lambda: (
        ggplot(_float(x=[1, 2, 3, 4, 5], y=[1, 3, 2, 4, 3]), aes(x="x", y="y"))
        + registry.geom_area(stat="identity", fill="#4C78A8")
        + registry.scale_x_continuous(limits=(0, 6), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 5), expand=(0, 0))
        + registry.theme_void()
    ),
    "histogram_identity": lambda: (
        ggplot(
            _float(x=[0.5, 1.5, 2.5, 3.5], y=[0.2, 0.5, 0.75, 0.4], w=[1, 1, 1, 1]),
            aes(x="x", y="y", width="w"),
        )
        + registry.geom_histogram(stat="identity", fill="#4C78A8")
        + registry.scale_x_continuous(limits=(0, 4), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "boxplot_identity": lambda: (
        ggplot(
            _float(
                cls=["a", "b"],
                y0=[0.1, 0.2],
                lo=[0.3, 0.35],
                mid=[0.5, 0.5],
                hi=[0.7, 0.65],
                y1=[0.9, 0.8],
            ),
            aes(x="cls", ymin="y0", lower="lo", middle="mid", upper="hi", ymax="y1"),
        )
        + registry.geom_boxplot(stat="identity", width=0.6, fill="#4C78A8")
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "smooth_identity": lambda: (
        ggplot(
            _float(
                x=[1, 2, 3, 4, 5, 6],
                y=[1.0, 1.6, 2.1, 2.7, 3.1, 3.8],
                ymin=[0.6, 1.2, 1.7, 2.3, 2.7, 3.4],
                ymax=[1.4, 2.0, 2.5, 3.1, 3.5, 4.2],
            ),
            aes(x="x", y="y", ymin="ymin", ymax="ymax"),
        )
        + registry.geom_smooth(stat="identity", colour="#3366FF", fill="grey60", alpha=0.4)
        + registry.scale_x_continuous(limits=(0, 7), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 5), expand=(0, 0))
        + registry.theme_void()
    ),
}


# --- M2-S2：长尾 A（线段 / 矩形 / 区间 / 标注族）的整条流水线对拍 -----------

_PT = 2.845276  # `.pt`：mm → pt 的换算（R 的 72.27/25.4）


def _simple(**columns: list) -> ColumnTable:
    return _float(**columns)


NEW_BUILDERS = {
    "segment_arrow": lambda: (
        ggplot(
            _simple(
                x=[0.1, 0.5],
                y=[0.2, 0.55],
                xend=[0.8, 0.9],
                yend=[0.7, 0.25],
                g=["a", "b"],
            ),
            aes(x="x", y="y", xend="xend", yend="yend", colour="g"),
        )
        + registry.geom_segment(
            linewidth=1.1 / _PT,
            arrow=arrow(length=0.15 * 72.0, ends="both", type="closed"),
        )
        + registry.scale_colour_discrete(values={"a": "#4C78A8", "b": "#E45756"})
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "curve_arrow": lambda: (
        ggplot(
            _simple(x=[0.1, 0.5], y=[0.2, 0.55], xend=[0.8, 0.9], yend=[0.7, 0.25]),
            aes(x="x", y="y", xend="xend", yend="yend"),
        )
        + registry.geom_curve(
            curvature=-0.4,
            angle=90,
            ncp=5,
            linewidth=1.1 / _PT,
            colour="#4C78A8",
            arrow=arrow(length=0.12 * 72.0, ends="last", type="open"),
        )
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "spoke_basic": lambda: (
        ggplot(
            _simple(x=[0.3, 0.6], y=[0.3, 0.6], ang=[0.0, math.pi / 4], rad=[0.2, 0.25]),
            aes(x="x", y="y", angle="ang", radius="rad"),
        )
        + registry.geom_spoke(linewidth=1.2 / _PT, colour="#4C78A8")
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "rect_basic": lambda: (
        ggplot(
            _simple(
                xmin=[0.1, 0.5],
                xmax=[0.4, 0.8],
                ymin=[0.1, 0.2],
                ymax=[0.5, 0.6],
            ),
            aes(xmin="xmin", xmax="xmax", ymin="ymin", ymax="ymax"),
        )
        + registry.geom_rect(fill="#4C78A8", colour="#333333", linewidth=0.8 / _PT, alpha=0.6)
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "abline_basic": lambda: (
        ggplot(
            _simple(
                xmin=[0.1, 0.5],
                xmax=[0.4, 0.8],
                ymin=[0.1, 0.2],
                ymax=[0.5, 0.6],
            )
        )
        + registry.geom_abline(slope=1, intercept=0.1, linewidth=1.0 / _PT, colour="#4C78A8")
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "hline_basic": lambda: (
        ggplot(
            _simple(
                xmin=[0.1, 0.5],
                xmax=[0.4, 0.8],
                ymin=[0.1, 0.2],
                ymax=[0.5, 0.6],
            )
        )
        + registry.geom_hline(
            yintercept=0.75, linetype="dashed", linewidth=0.9 / _PT, colour="#E45756"
        )
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "vline_basic": lambda: (
        ggplot(
            _simple(
                xmin=[0.1, 0.5],
                xmax=[0.4, 0.8],
                ymin=[0.1, 0.2],
                ymax=[0.5, 0.6],
            )
        )
        + registry.geom_vline(xintercept=0.6, linewidth=0.9 / _PT, colour="#54A24B")
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "tile_basic": lambda: (
        ggplot(
            _simple(
                x=[0.25, 0.75, 0.25, 0.75],
                y=[0.25, 0.25, 0.75, 0.75],
                f=["p", "q", "q", "p"],
            ),
            aes(x="x", y="y", fill="f"),
        )
        + registry.geom_tile()
        + registry.scale_fill_discrete(values={"p": "#4C78A8", "q": "#F58518"})
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "raster_basic": lambda: (
        ggplot(
            _simple(
                x=[0.25, 0.75, 0.25, 0.75],
                y=[0.25, 0.25, 0.75, 0.75],
                f=["p", "q", "q", "p"],
            ),
            aes(x="x", y="y", fill="f"),
        )
        + registry.geom_raster(interpolate=False)
        + registry.scale_fill_discrete(values={"p": "#4C78A8", "q": "#F58518"})
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "polygon_basic": lambda: (
        ggplot(
            _simple(
                x=[0.1, 0.4, 0.35, 0.7, 0.85, 0.5],
                y=[0.1, 0.15, 0.5, 0.55, 0.9, 0.6],
                g=["a", "a", "a", "b", "b", "b"],
            ),
            aes(x="x", y="y", group="g", fill="g"),
        )
        + registry.geom_polygon(colour="#333333", linewidth=0.8 / _PT, alpha=0.8)
        + registry.scale_fill_discrete(values={"a": "#4C78A8", "b": "#F58518"})
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "ribbon_upper": lambda: (
        ggplot(
            _simple(
                x=[0.1, 0.3, 0.5, 0.7, 0.9],
                lo=[0.1, 0.2, 0.15, 0.3, 0.25],
                hi=[0.4, 0.5, 0.45, 0.6, 0.55],
            ),
            aes(x="x", ymin="lo", ymax="hi"),
        )
        + registry.geom_ribbon(
            fill="#4C78A8",
            colour="#333333",
            alpha=0.5,
            linewidth=0.9 / _PT,
            **{"outline.type": "upper"},
        )
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "step_basic": lambda: (
        ggplot(
            _simple(
                x=[0.1, 0.3, 0.5, 0.7, 0.9],
                y=[0.2, 0.5, 0.35, 0.7, 0.6],
            ),
            aes(x="x", y="y"),
        )
        + registry.geom_step(direction="hv", linewidth=1.2 / _PT, colour="#4C78A8")
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "errorbar_basic": lambda: (
        ggplot(
            _simple(x=[0.3, 0.7], y=[0.5, 0.45], lo=[0.2, 0.3], hi=[0.8, 0.7]),
            aes(x="x", y="y", ymin="lo", ymax="hi"),
        )
        + registry.geom_errorbar(width=0.2, linewidth=0.9 / _PT, colour="#4C78A8")
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "errorbarh_basic": lambda: (
        ggplot(
            _simple(x=[0.5, 0.45], y=[0.3, 0.7], lo=[0.2, 0.3], hi=[0.8, 0.7]),
            aes(y="y", x="x", xmin="lo", xmax="hi"),
        )
        + registry.geom_errorbarh(height=0.2, linewidth=0.9 / _PT, colour="#E45756")
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "linerange_basic": lambda: (
        ggplot(
            _simple(x=[0.3, 0.7], y=[0.5, 0.45], lo=[0.2, 0.3], hi=[0.8, 0.7]),
            aes(x="x", y="y", ymin="lo", ymax="hi"),
        )
        + registry.geom_linerange(linewidth=1.5 / _PT, colour="#54A24B")
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "pointrange_basic": lambda: (
        ggplot(
            _simple(x=[0.3, 0.7], y=[0.5, 0.45], lo=[0.2, 0.3], hi=[0.8, 0.7]),
            aes(x="x", y="y", ymin="lo", ymax="hi"),
        )
        + registry.geom_pointrange(size=1.4, linewidth=0.9 / _PT, colour="#333333")
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "crossbar_basic": lambda: (
        ggplot(
            _simple(x=[0.3, 0.7], y=[0.5, 0.45], lo=[0.2, 0.3], hi=[0.8, 0.7]),
            aes(x="x", y="y", ymin="lo", ymax="hi"),
        )
        + registry.geom_crossbar(width=0.3, fill="#F58518", colour="#333333", linewidth=0.8 / _PT)
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "rug_basic": lambda: (
        ggplot(_simple(x=[0.2, 0.5, 0.8], y=[0.3, 0.6, 0.9]), aes(x="x", y="y"))
        + registry.geom_rug(sides="bl", length=0.04, linewidth=0.8 / _PT, colour="#4C78A8")
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "map_basic": lambda: (
        ggplot(_simple(map_id=["a", "b"]), aes(map_id="map_id"))
        + registry.geom_map(
            map={
                "x": [0.0, 0.4, 0.4, 0.0, 0.5, 0.9, 0.9, 0.5],
                "y": [0.0, 0.0, 0.4, 0.4, 0.5, 0.5, 0.9, 0.9],
                "id": ["a", "a", "a", "a", "b", "b", "b", "b"],
            },
            fill="#4C78A8",
            colour="#333333",
            linewidth=0.8 / _PT,
        )
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "boxplot_horizontal_auto": lambda: (
        ggplot(
            _simple(
                cls=["a"] * 6 + ["b"] * 6,
                v=[1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 0.5, 1.0, 1.5, 2.0, 2.5, 5.0],
            ),
            aes(y="cls", x="v"),
        )
        + registry.geom_boxplot(fill="#F58518", colour="#333333", width=0.6)
        + registry.scale_x_continuous(limits=(0, 6), expand=(0, 0))
        + registry.theme_void()
    ),
    "area_horizontal": lambda: (
        ggplot(
            _simple(
                cls=["a", "b", "c", "d", "e"],
                v=[1.0, 2.5, 1.8, 3.2, 2.2],
            ),
            aes(y="cls", x="v"),
        )
        + registry.geom_area(stat="identity", orientation="y", fill="#4C78A8")
        + registry.scale_x_continuous(limits=(0, 4), expand=(0, 0))
        + registry.theme_void()
    ),
}

BUILDERS.update(NEW_BUILDERS)


def _assert_column_equal(name: str, ours: Column, expected: Column) -> None:
    assert ours.kind == expected.kind, f"{name}: kind {ours.kind} != {expected.kind}"
    ours_values = np.asarray(ours.values)
    expected_values = np.asarray(expected.values)
    if ours.kind in ("float", "int"):
        assert np.shape(ours_values) == np.shape(expected_values)
        assert np.allclose(ours_values, expected_values, rtol=0, atol=TOLERANCE), name
    else:
        assert ours_values.tolist() == expected_values.tolist(), name
    assert np.asarray(ours.na_mask).tolist() == np.asarray(expected.na_mask).tolist(), name


@pytest.mark.parametrize(
    "case_name",
    [
        "point_shapes",
        "point_na",
        "line_groups",
        "path_basic",
        "bar_stacked",
        "col_identity",
        "col_horizontal",
        "col_default_width",
        "area_identity",
        "histogram_identity",
        "boxplot_identity",
        "smooth_identity",
        # M2-S2：长尾 A + 两条横向 case
        "segment_arrow",
        "curve_arrow",
        "spoke_basic",
        "rect_basic",
        "abline_basic",
        "hline_basic",
        "vline_basic",
        "tile_basic",
        "raster_basic",
        "polygon_basic",
        "ribbon_upper",
        "step_basic",
        "errorbar_basic",
        "errorbarh_basic",
        "linerange_basic",
        "pointrange_basic",
        "crossbar_basic",
        "rug_basic",
        "map_basic",
        "boxplot_horizontal_auto",
        "area_horizontal",
    ],
)
def test_build_matches_r_column_by_column(reference: dict, case_name: str) -> None:
    case = reference["cases"][case_name]
    expected = _table(case)
    built = build_plot(BUILDERS[case_name]()).layers[0].data
    r_only = R_ONLY_COLUMNS.get(case_name, ())
    assert built.names == tuple(name for name in expected.names if name not in r_only), (
        f"{case_name}: 列名/列序不一致"
    )
    skipped = SKIP_VALUES.get(case_name, frozenset())
    for name in built.names:
        if name in skipped:
            continue
        _assert_column_equal(f"{case_name}.{name}", built.column(name), expected.column(name))


def test_handle_na_warning_matches_r(reference: dict) -> None:
    case = reference["cases"]["point_na"]
    raw = case["warnings"]
    expected_message = " ".join((raw if isinstance(raw, str) else raw[0]).split())
    layer = build_plot(BUILDERS["point_na"]()).layers[0]
    with pytest.warns(BuildWarning) as record:
        layer.geom_object.handle_na(layer.data, na_rm=False)
    ours = " ".join(str(record[0].message).split())
    assert ours == expected_message


# ---------------------------------------------------------------------------
# 2. stat 未实现的 case：R 的 $data 当绘制输入
# ---------------------------------------------------------------------------


def _drawn_nodes(case_name: str, case: dict) -> list:
    build = _layer_build(_CASE_GEOM[case_name], case)
    geom = renderer_for(_CASE_GEOM[case_name])
    grob = geom.draw(build.geom_object, build, _panel(case), None, resolve_theme(Theme()), None)
    tree = ViewportTree(Device(4.0, 3.0))
    tree.push(viewport("panel", x=0.5, y=0.5, width=1.0, height=1.0, xscale=(0, 1), yscale=(0, 1)))
    return list(scene(grob, tree).instructions)


def _counts(nodes: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node.kind.value] = counts.get(node.kind.value, 0) + 1
    return counts


def test_histogram_stat_fixture_draws_four_bins(reference: dict) -> None:
    case = reference["cases"]["histogram_stat"]
    nodes = _drawn_nodes("histogram_stat", case)
    rects = [node for node in nodes if node.kind.value == "rect"]
    total = sum(int(np.asarray(node.bufs["rect"]).shape[0]) for node in rects)
    assert total == case["data"]["rows"] == 4
    # 第一箱的宽度来自 R 的 xmin/xmax（bin 宽度 1），面板 288pt 宽、x 范围 0.3..4.7。
    rect = np.asarray(rects[0].bufs["rect"])[0]
    width = float(rect[2]) - float(rect[0])
    assert width == pytest.approx(1.0 / (4.7 - 0.3) * 288.0, rel=1e-4)


def test_boxplot_stat_fixture_draws_box_whiskers_and_outliers(reference: dict) -> None:
    case = reference["cases"]["boxplot_stat"]
    nodes = _drawn_nodes("boxplot_stat", case)
    counts = _counts(nodes)
    assert counts["polygon"] == 2  # 两只箱
    assert counts["segments"] == 2  # 须线 + 中位线
    # 离群点：R 的两组各 1 个（20 / 25）→ 逐行一个 points 节点，共 2 个点。
    points = [node for node in nodes if node.kind.value == "points"]
    assert sum(int(np.asarray(node.bufs["points"]).shape[0]) for node in points) == 2


def test_smooth_stat_fixture_draws_ribbon_and_line(reference: dict) -> None:
    case = reference["cases"]["smooth_stat"]
    nodes = _drawn_nodes("smooth_stat", case)
    counts = _counts(nodes)
    assert counts["polygon"] == 1
    assert counts["polyline"] == 1
    polygon = next(node for node in nodes if node.kind.value == "polygon")
    assert np.asarray(polygon.bufs["points"]).shape[0] == 2 * case["data"]["rows"]


def test_boxplot_identity_centres_the_box_on_the_discrete_axis(reference: dict) -> None:
    case = reference["cases"]["boxplot_identity"]
    nodes = _drawn_nodes("boxplot_identity", case)
    polygons = [node for node in nodes if node.kind.value == "polygon"]
    assert len(polygons) == 2
    box = np.asarray(polygons[0].bufs["points"])
    # 第一只箱的 x 中心：R 的 x = 1（离散编码），面板 x 范围 0.4..2.6，
    # npc = (1 - 0.4) / 2.2 → 页面 288pt 里的 78.545pt。
    centre = float((box[:, 0].min() + box[:, 0].max()) / 2.0)
    assert centre == pytest.approx((1.0 - 0.4) / (2.6 - 0.4) * 288.0, abs=1e-3)
