"""`plot_gtable()` 与 ggplot2 4.0.3 `ggplotGrob()` 的结构对拍（SIL-999）。

夹具 `tests/fixtures/plot_gtable_r_reference.json` 由
`pixi run -e refs refs:plot-gtable`（`tools/refs/plot_gtable_ref.R`）生成。
两条断言线：

1. **结构与命名**：行列数、`respect`、每条 layout 的 `(name, t, l, b, r)` 与 R
   完全相同（`facet_wrap` 17×17、`facet_grid` 18×14、`coord_fixed` 的
   `respect = TRUE` 都在内）；
2. **可静态求值的单位**：R 侧 `as.character(widths/heights)` 里能直接换算的项
   （`5.5points` / `0.350502602739725cm` / `0cm` …）与我们的 `resolve(7×7in)`
   逐项比较，容差 0.05cm。`1grobwidth` / `1grobheight` / `sum(...)` / `1null`
   跳过：前三个要设备度量，最后一个由 gtable 按面板比例分配。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ggcore.geom.scene import plot_layout
from ggcore.plot import (
    aes,
    coord_fixed,
    facet_grid,
    facet_wrap,
    geom_point,
    ggplot,
    labs,
    plot_gtable,
)
from ggcore.theme import theme
from ggcore.units import CM_PER_INCH, UnitContext
from ggio.frame import from_dict
from ggskia.text import ShaperMetrics

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "plot_gtable_r_reference.json"
DOCUMENT = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = DOCUMENT["cases"]
METRICS = ShaperMetrics()
CTX = UnitContext(metrics=METRICS)
SIZE_IN = 7.0
TOLERANCE_CM = 0.05
#: 逐条 layout 记录的**实测** cm（R 按 7×7 视口解析 null 后读回）。结构类错误
#: （比如 ragged 的内部 `axis-b` 带凭空满高）是 0.45cm 级；这里留 0.105cm 是因为
#: 文字行高与 R 有 0.017em 的既有口径差（`docs/notes/guide.md`），在整页表里按
#: 行数累计到 0.1013cm（`titled` 的 panel / span 记录）。实测数字见
#: `docs/notes/gtable.md`。
TOLERANCE_RECORD_CM = 0.105

#: 与 `tools/refs/plot_gtable_ref.R` 的 `data` 同一份（8 行、4 个 facet 水平）。
_DATA = from_dict(
    {
        "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        "y": [2.0, 4.0, 3.0, 5.0, 6.0, 3.0, 4.0, 7.0],
        "g": ["a", "b", "a", "b", "a", "b", "a", "b"],
        "h": ["u", "u", "u", "u", "v", "v", "v", "v"],
        "four": ["p", "q", "r", "s", "p", "q", "r", "s"],
        "five": ["p", "q", "r", "s", "t", "p", "q", "r"],
    }
)


def _build(name: str) -> ggplot:
    base = ggplot(_DATA, aes(x="x", y="y")) + geom_point()
    builders = {
        "plain": lambda: base + labs(x="XX", y="YY"),
        "titled": lambda: (
            base + labs(title="TT", subtitle="SS", caption="CC", tag="A", x="XX", y="YY")
        ),
        "legend": lambda: (
            ggplot(_DATA, aes(x="x", y="y", colour="g"))
            + geom_point()
            + labs(title="TT", x="XX", y="YY")
        ),
        "facet_wrap": lambda: base + facet_wrap("g"),
        "facet_grid": lambda: base + facet_grid("g"),
        "coord_fixed": lambda: base + coord_fixed(ratio=2),
        # SIL-999 审计补的 4 个 shape：多行 / 多列分面的展开规则。
        "wrap_ncol1": lambda: base + facet_wrap("g", ncol=1),
        "wrap_2x2": lambda: base + facet_wrap("four"),
        "grid_1x2": lambda: base + facet_grid(None, "g"),
        "grid_2x2": lambda: base + facet_grid("h", "g"),
        "wrap_ragged_ncol3": lambda: base + facet_wrap("five", ncol=3),
        "wrap_ragged_ncol2": lambda: base + facet_wrap("five", ncol=2),
        "wrap_dir_v_ncol2": lambda: base + facet_wrap("five", ncol=2, dir="v"),
        "title_plot_position": lambda: (
            ggplot(_DATA, aes(x="x", y="y", colour="g"))
            + geom_point()
            + labs(title="TT", subtitle="SS", x="XX", y="YY")
            + theme(**{"plot.title.position": "plot"})
        ),
    }
    return builders[name]()


def _literal_cm(text: str) -> float | None:
    """R 侧单位字符串里能静态求值的项；其余返回 `None`。"""
    if text.endswith("cm"):
        return float(text.removesuffix("cm"))
    if text.endswith("points"):
        return float(text.removesuffix("points")) * 2.54 / 72.0
    if text.endswith("mm"):
        return float(text.removesuffix("mm")) / 10.0
    return None


def test_fixture_pin() -> None:
    assert DOCUMENT["ggplot2"] == "4.0.3"
    assert DOCUMENT["size_in"] == [7, 7]
    assert {case["name"] for case in CASES} == {
        "plain",
        "titled",
        "legend",
        "facet_wrap",
        "facet_grid",
        "coord_fixed",
        "wrap_ncol1",
        "wrap_2x2",
        "grid_1x2",
        "grid_2x2",
        "wrap_ragged_ncol3",
        "wrap_ragged_ncol2",
        "wrap_dir_v_ncol2",
        "title_plot_position",
    }


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_shape_and_layout_names_match_r(case: dict[str, Any]) -> None:
    table = plot_gtable(_build(case["name"]), metrics=METRICS)
    assert (table.nrow, table.ncol) == (case["nrow"], case["ncol"])
    assert table.respect is case["respect"]
    ours = {(item.name, item.t, item.l, item.b, item.r) for item in table.layout}
    reference = {
        (item["name"], item["t"], item["l"], item["b"], item["r"]) for item in case["layout"]
    }
    assert ours == reference
    # 审计缺口 1：`GTable.grob(name)` / `placements(name)` 取第一个匹配，重名会让
    # 组合层静默拿到错格。单面板的 4 个 `spacer` 在 R 里就是同名（它们靠 t/l/b/r
    # 区分），其余 layout 名必须唯一。
    names = [item.name for item in table.layout if item.name != "spacer"]
    assert len(names) == len(set(names)), f"{case['name']}: 重复的 layout 名"


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_literal_dimensions_match_r(case: dict[str, Any]) -> None:
    table = plot_gtable(_build(case["name"]), metrics=METRICS)
    sizes = table.resolve(SIZE_IN * CM_PER_INCH, SIZE_IN * CM_PER_INCH, ctx=CTX)
    checked = 0
    for index, text in enumerate(case["widths"]):
        expected = _literal_cm(text)
        if expected is None:
            continue
        assert sizes.widths_cm[index] == pytest.approx(expected, abs=TOLERANCE_CM), (
            f"column {index + 1}: R {text!r}"
        )
        checked += 1
    for index, text in enumerate(case["heights"]):
        expected = _literal_cm(text)
        if expected is None:
            continue
        assert sizes.heights_cm[index] == pytest.approx(expected, abs=TOLERANCE_CM), (
            f"row {index + 1}: R {text!r}"
        )
        checked += 1
    assert checked > 0


def test_plain_case_checks_the_axis_and_margin_rows() -> None:
    """至少这些项必须在比较里（避免夹具退化成「全部跳过」）。"""
    case = next(item for item in CASES if item["name"] == "plain")
    literal = [_literal_cm(text) for text in (*case["widths"], *case["heights"])]
    assert sum(value is not None for value in literal) >= 6


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_resolved_records_match_r(case: dict[str, Any]) -> None:
    """按 7×7 视口逐条记录比 cm：null 行 / 列（panel、strip、axis 带）也在这里断言。

    R 侧用 `downViewport("<name>.<t>-<r>-<b>-<l>")` 读 `1npc`（见
    `tools/refs/plot_gtable_ref.R`），所以 `1null` 行 / 列拿到的是**分配后**的
    真实 cm，不是 `convertWidth()` 对 null 给的 0。
    """
    records = case.get("records") or []
    assert records, f"{case['name']}: 夹具缺 records"
    table = plot_gtable(_build(case["name"]), metrics=METRICS)
    boxes = {
        (row.name, row.t, row.l, row.b, row.r): box
        for row, box in zip(
            table.layout,
            table.boxes(SIZE_IN * CM_PER_INCH, SIZE_IN * CM_PER_INCH, ctx=CTX),
            strict=True,
        )
    }
    for record in records:
        key = (record["name"], record["t"], record["l"], record["b"], record["r"])
        assert key in boxes, f"{case['name']}: 缺记录 {key}"
        box = boxes[key]
        assert box.width_cm == pytest.approx(record["width"], abs=TOLERANCE_RECORD_CM), (
            f"{case['name']}: {key} 宽 {box.width_cm:.4f} vs R {record['width']:.4f}"
        )
        assert box.height_cm == pytest.approx(record["height"], abs=TOLERANCE_RECORD_CM), (
            f"{case['name']}: {key} 高 {box.height_cm:.4f} vs R {record['height']:.4f}"
        )


def test_legend_column_is_measured_against_r() -> None:
    """`legend.box.spacing` 在 R 里是独立的 spacer 列（列 10 = 11points）。"""
    case = next(item for item in CASES if item["name"] == "legend")
    table = plot_gtable(_build("legend"), metrics=METRICS)
    sizes = table.resolve(SIZE_IN * CM_PER_INCH, SIZE_IN * CM_PER_INCH, ctx=CTX)
    assert case["widths"][9] == "11points"
    # 主题的 pt → cm 与 R 的 `convertWidth` 在这位小数上有 0.0015cm 的口径差，
    # 用与其它尺寸相同的 0.5mm 容差。
    assert sizes.widths_cm[9] == pytest.approx(11 * 2.54 / 72, abs=TOLERANCE_CM)


def test_facet_panel_names_follow_r_order() -> None:
    """R 的 panel 名是 `panel-{col}-{row}`，不是 `panel-{row}-{col}`。"""
    case = next(item for item in CASES if item["name"] == "facet_wrap")
    names = {item["name"] for item in case["layout"]}
    assert {"panel-1-1", "panel-2-1"} <= names
    ours = {item.name for item in plot_gtable(_build("facet_wrap"), metrics=METRICS).layout}
    assert {"panel-1-1", "panel-2-1"} <= ours


def test_resolved_panel_matches_plot_layout_for_every_case() -> None:
    """面板区的物理尺寸与单图版式一致（两条路径不各算各的）。"""
    for case in CASES:
        if case["name"] in (
            "facet_wrap",
            "facet_grid",
            "wrap_ncol1",
            "wrap_2x2",
            "grid_1x2",
            "grid_2x2",
            "wrap_ragged_ncol3",
            "wrap_ragged_ncol2",
            "wrap_dir_v_ncol2",
        ):
            continue  # 分面的面板区在 FacetTable 里，另有 facet 对拍
        plot = _build(case["name"])
        table = plot_gtable(plot, metrics=METRICS)
        layout = plot_layout(build_plot_of(plot), metrics=METRICS)
        box = table.region_box(
            9, 7, 9, 7, width_cm=SIZE_IN * CM_PER_INCH, height_cm=SIZE_IN * CM_PER_INCH, ctx=CTX
        )
        assert box.width_cm == pytest.approx(layout.panel_area.width_cm, abs=0.02)
        assert box.height_cm == pytest.approx(layout.panel_area.height_cm, abs=0.02)


def build_plot_of(plot: ggplot):
    from ggcore.build import build_plot

    return build_plot(plot)
