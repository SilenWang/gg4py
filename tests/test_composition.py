"""组合骨架与 panel 几何对齐（M3-1 / SIL-1001）。

三层断言：

1. **API 与分派**：`wrap_plots()` / `+` / `|` / `/` / `plot_layout()` /
   `plot_spacer()`，以及 `p + theme()` / `p + geom_*()` 仍然走单图路径；
2. **18×15 规范化与表级 panel 矩形**：单面板补 strip 行 / 列、facet 的 panel
   块坍缩；平铺时同一 layout 列 x/w 相同、同一 layout 行 y/h 相同；
3. **渲染与表一致**：组合表 → `scene([gtable], tree)` → IR → PNG / SVG / PDF，
   从 SVG 读回的 panel 矩形与表级逐值相等（同列 / 同行因此也严格对齐）。

与 patchwork 1.3.2 的关系对拍在 `tests/test_composition_r_parity.py`。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

import gg4py
from ggcore import composition, plotspec
from ggcore.composition import (
    PANEL_COL,
    PANEL_ROW,
    TABLE_COLS,
    TABLE_ROWS,
    ComposeError,
    Patchwork,
    Spacer,
    guide_area,
    plot_layout,
    plot_spacer,
    wrap_plots,
)
from ggcore.guide import guide_bins
from ggcore.plot import (
    aes,
    facet_wrap,
    geom_line,
    geom_point,
    ggplot,
    guides,
    labs,
    theme_void,
)
from ggcore.theme import element_rect, element_text, theme
from ggcore.units import UnitContext, null_value
from ggio.frame import from_dict
from ggskia.text import ShaperMetrics

METRICS = ShaperMetrics()
CTX = UnitContext(metrics=METRICS)
CM_PER_PT = 2.54 / 72.0


def data() -> Any:
    return from_dict(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            "y": [2.0, 4.0, 3.0, 5.0, 6.0, 3.0, 4.0, 7.0],
            "g": ["a", "b", "a", "b", "a", "b", "a", "b"],
        }
    )


def base() -> ggplot:
    return ggplot(data(), aes(x="x", y="y")) + geom_point()


def panelled(fill: str, xlab: str = "x") -> ggplot:
    """一个面板背景带 fill 的图（SVG 对拍用；用非标准色，SVG 会原样写 hex）。"""
    return (
        base() + theme(**{"panel.background": element_rect(fill=fill, colour=None)}) + labs(x=xlab)
    )


def panel_boxes(
    plot: Patchwork, *, width_in: float = 7.0, height_in: float = 6.0
) -> dict[str, tuple[float, float, float, float]]:
    """表级 panel 矩形（pt，y 从下往上），按 `panel-area-<row>-<col>` 取名。

    design 的行号从**上**往下、页面坐标从下往上：第 `t` 行的底部 = 总高 - 前
    `t` 行之和。表级与 SVG（y 向下）比较时用 :func:`to_svg_y` 换算。
    """
    table = plot.gtable(metrics=METRICS, width_in=width_in, height_in=height_in)
    sizes = table.resolve(width_in * 2.54, height_in * 2.54, ctx=CTX)
    total_height = sum(sizes.heights_cm)
    out: dict[str, tuple[float, float, float, float]] = {}
    for row in table.layout:
        if not row.name.startswith("panel-area-"):
            continue
        out[row.name] = (
            sum(sizes.widths_cm[: row.l - 1]) * 72.0 / 2.54,
            (total_height - sum(sizes.heights_cm[: row.t])) * 72.0 / 2.54,
            sizes.widths_cm[row.l - 1] * 72.0 / 2.54,
            sizes.heights_cm[row.t - 1] * 72.0 / 2.54,
        )
    return out


def to_svg_y(box: tuple[float, float, float, float], height_in: float) -> tuple[float, ...]:
    """表级矩形（y 向上）→ SVG 的 y 向下。"""
    page_height = height_in * 72.0
    return (box[0], page_height - (box[1] + box[3]), box[2], box[3])


# ---------------------------------------------------------------------------
# API 与分派
# ---------------------------------------------------------------------------


def test_wrap_plots_returns_patchwork() -> None:
    p = base()
    combined = wrap_plots(p, p, p, ncol=2)
    assert isinstance(combined, Patchwork)
    assert len(combined.plots) == 3
    assert combined.layout.ncol == 2


def test_wrap_plots_accepts_a_list() -> None:
    p = base()
    assert len(wrap_plots([p, p, p]).plots) == 3


def test_plus_between_ggplots_enters_composition() -> None:
    p = base()
    combined = p + p
    assert isinstance(combined, Patchwork)
    assert len(combined.plots) == 2
    # 左侧对象没被改（与 `gg_add` 的克隆语义一致）。
    assert isinstance(p, ggplot)


def test_plus_plot_layout_updates_the_grid() -> None:
    p = base()
    combined = (p + p + p) + plot_layout(ncol=3, widths=[2.0, 1.0, 1.0])
    assert combined.layout.ncol == 3
    assert combined.layout.widths == (2.0, 1.0, 1.0)


def test_plus_theme_and_geom_stay_single_plot() -> None:
    """`p + theme()` / `p + geom_*()` 仍走原来的 `gg_add` 分派（SIL-1001 兼容项）。"""
    p = base()
    assert isinstance(p + theme_void(), ggplot)
    assert isinstance(p + geom_line(), ggplot)
    assert isinstance(p + labs(title="t"), ggplot)


def test_plus_none_is_still_a_clone() -> None:
    p = base()
    clone = p + None
    assert isinstance(clone, ggplot)
    assert clone is not p


def test_pipe_is_one_row() -> None:
    p = base()
    combined = p | p
    assert isinstance(combined, Patchwork)
    assert combined.layout.nrow == 1
    # `p1 | p2 | p3` 继续平铺成 1×3（patchwork 的 `|.ggplot` 同义）。
    again = combined | p
    assert len(again.plots) == 3
    assert again.layout.nrow == 1


def test_slash_is_one_column() -> None:
    p = base()
    combined = p / p
    assert isinstance(combined, Patchwork)
    assert combined.layout.ncol == 1


def test_parenthesised_layouts_nest() -> None:
    p = base()
    nested = (p | p) / (p | p)
    assert len(nested.plots) == 2
    assert all(isinstance(item, Patchwork) for item in nested.plots)


def test_plot_spacer_is_a_composable_placeholder() -> None:
    p = base()
    combined = p | plot_spacer() | p
    assert isinstance(combined.plots[1], Spacer)


def test_star_is_rejected_with_a_hint() -> None:
    p = base()
    with pytest.raises(TypeError, match="暂不支持"):
        p * p


def test_too_many_plots_for_the_grid() -> None:
    p = base()
    with pytest.raises(ComposeError, match="需要 3 个格子"):
        wrap_plots(p, p, p, ncol=2, nrow=1).gtable(metrics=METRICS)


def test_unknown_plot_layout_keyword() -> None:
    with pytest.raises(ComposeError, match="不认识"):
        wrap_plots(base(), nonsense=True)


# ---------------------------------------------------------------------------
# 18×15 规范化
# ---------------------------------------------------------------------------


def test_single_panel_sheet_is_18_by_15() -> None:
    sheet = composition._sheet(base(), METRICS)
    assert len(sheet.widths) == TABLE_COLS
    assert len(sheet.heights) == TABLE_ROWS
    # panel 行 / 列是 null（组合时会被换成大表的 null 权重）。
    assert "null" in str(sheet.widths[PANEL_COL - 1])
    assert "null" in str(sheet.heights[PANEL_ROW - 1])


def test_faceted_sheet_is_collapsed_to_18_by_15() -> None:
    faceted = base() + facet_wrap("g")
    sheet = composition._sheet(faceted, METRICS)
    assert len(sheet.widths) == TABLE_COLS
    assert len(sheet.heights) == TABLE_ROWS
    # 抹掉分面后与单面板占同样的结构位置。
    plain = composition._sheet(base(), METRICS)
    assert len(sheet.widths) == len(plain.widths)


def test_spacer_sheet_has_no_fixed_size() -> None:
    sheet = composition._spacer_sheet()
    assert all("null" in str(unit) or "0cm" in str(unit) for unit in sheet.widths)
    assert "null" in str(sheet.widths[PANEL_COL - 1])


# ---------------------------------------------------------------------------
# 表级 panel 矩形
# ---------------------------------------------------------------------------


def test_one_by_two_panels_share_vertical_geometry() -> None:
    p1, p2 = panelled("#CC0000"), panelled("#00CC00", "a-considerably-longer-x-label")
    boxes = panel_boxes(p1 | p2)
    assert set(boxes) == {"panel-area-1-1", "panel-area-1-2"}
    left, right = boxes["panel-area-1-1"], boxes["panel-area-1-2"]
    assert left[1] == pytest.approx(right[1], abs=1e-9)
    assert left[3] == pytest.approx(right[3], abs=1e-9)
    assert left[2] == pytest.approx(right[2], abs=1e-9)
    assert right[0] > left[0]


def test_flat_2x2_panels_align_by_column_and_row() -> None:
    p = [panelled("#CC0000"), panelled("#00CC00"), panelled("#0000CC"), panelled("#CCCC00")]
    combined = (p[0] + p[1] + p[2] + p[3]) + plot_layout(ncol=2)
    boxes = panel_boxes(combined)
    assert set(boxes) == {
        "panel-area-1-1",
        "panel-area-1-2",
        "panel-area-2-1",
        "panel-area-2-2",
    }
    # 同一列：x / w 相同。
    for col in ("1", "2"):
        assert boxes[f"panel-area-1-{col}"][0] == pytest.approx(
            boxes[f"panel-area-2-{col}"][0], abs=1e-9
        )
        assert boxes[f"panel-area-1-{col}"][2] == pytest.approx(
            boxes[f"panel-area-2-{col}"][2], abs=1e-9
        )
    # 同一行：y / h 相同。
    for row in ("1", "2"):
        assert boxes[f"panel-area-{row}-1"][1] == pytest.approx(
            boxes[f"panel-area-{row}-2"][1], abs=1e-9
        )
        assert boxes[f"panel-area-{row}-1"][3] == pytest.approx(
            boxes[f"panel-area-{row}-2"][3], abs=1e-9
        )


def test_plot_layout_widths_become_panel_weights() -> None:
    p = base()
    combined = (p + p) + plot_layout(widths=[2.0, 1.0])
    boxes = panel_boxes(combined)
    ratio = boxes["panel-area-1-1"][2] / boxes["panel-area-1-2"][2]
    # 两列除了 panel 之外的固定槽位不同，比例只是近似 2:1。
    assert 1.6 < ratio < 2.4


def test_byrow_false_fills_columns_first() -> None:
    p = [panelled("#CC0000"), panelled("#00CC00"), panelled("#0000CC")]
    by_row = panel_boxes(wrap_plots(*p, ncol=2, byrow=True))
    by_col = panel_boxes(wrap_plots(*p, ncol=2, byrow=False))
    assert set(by_row) == set(by_col) == {"panel-area-1-1", "panel-area-1-2", "panel-area-2-1"}
    # byrow=False 时第三张图落在下一行第一列：它的 panel 与 1-1 同列。
    assert by_col["panel-area-2-1"][0] == pytest.approx(by_col["panel-area-1-1"][0], abs=1e-9)
    assert by_row["panel-area-2-1"][0] == pytest.approx(by_row["panel-area-1-1"][0], abs=1e-9)


def test_nested_layouts_do_not_share_panels_across_layers(tmp_path: Path) -> None:
    """嵌套把每个内层组合当**一个** panel 槽位：跨层不共享列（patchwork 同义）。

    表级只能看到外层的槽位；差异在渲染层：上层的两个 panel 由内层 layout 分配，
    各自只有下层单 panel 的一半左右。
    """
    p = [panelled("#CC0000"), panelled("#00CC00"), panelled("#0000CC")]
    nested = (p[0] | p[1]) / p[2]
    boxes = panel_boxes(nested, width_in=6.0, height_in=6.0)
    assert set(boxes) == {"panel-area-1-1", "panel-area-2-1"}
    svg = _svg_panel_rects(nested, tmp_path / "nested.svg", width_in=6.0, height_in=6.0)
    top_left, top_right, bottom = svg["#CC0000"], svg["#00CC00"], svg["#0000CC"]
    assert bottom[2] > top_left[2] * 1.5
    assert bottom[2] > top_right[2] * 1.5
    # 内层的两个 panel 与下层的单 panel 在同一个外层槽位宽度里。
    assert top_left[2] + top_right[2] <= bottom[2] + 0.01


# ---------------------------------------------------------------------------
# 渲染：与表一致
# ---------------------------------------------------------------------------


#: SVG 设备会把 `#CC0000` 压成 `#C00`（svglite/skia 都做过 CSS 颜色归一化），
#: 所以匹配时把两种写法都算上。
_SVG_COLOURS: dict[str, tuple[str, ...]] = {
    "#CC0000": ("#CC0000", "#C00", "#cc0000", "#c00"),
    "#00CC00": ("#00CC00", "#0C0", "#00cc00", "#0c0"),
    "#0000CC": ("#0000CC", "#00C", "#0000cc", "#00c"),
    "#CCCC00": ("#CCCC00", "#CC0", "#cccc00", "#cc0"),
}


def _svg_panel_rects(plot: Patchwork, path: Path, *, width_in: float, height_in: float) -> dict:
    gg4py.ggsave(plot, path, width=width_in, height=height_in)
    text = path.read_text()
    out: dict[str, tuple[float, float, float, float]] = {}
    for colour, spellings in _SVG_COLOURS.items():
        for match in re.finditer(r"<rect[^>]*/?>", text):
            line = match.group(0)
            if not any(spelling in line for spelling in spellings):
                continue
            translate = re.search(r"translate\(([0-9.eE+-]+) ([0-9.eE+-]+)\)", line)
            dx = float(translate.group(1)) if translate else 0.0
            dy = float(translate.group(2)) if translate else 0.0

            def number(attr: str, text: str = line) -> float:
                found = re.search(attr + r'="([0-9.eE+-]+)"', text)
                return float(found.group(1)) if found else 0.0

            out[colour] = (
                dx + number("x"),
                dy + number("y"),
                number("width"),
                number("height"),
            )
    return out


def test_scene_goes_through_plotspec_gtable(tmp_path: Path) -> None:
    p1, p2 = panelled("#CC0000"), panelled("#00CC00")
    combined = p1 | p2
    table = combined.gtable(metrics=METRICS, width_in=7.0, height_in=5.0)
    from_table = plotspec.build_scene({"gtable": table, "size": [7.0, 5.0]}, metrics=METRICS)
    direct = combined.to_scene(metrics=METRICS, width_in=7.0, height_in=5.0)
    assert from_table.size == direct.size
    assert from_table.root.kind == direct.root.kind
    # IR 不改：组合结果就是普通 Scene（root viewport + 子节点）。
    assert direct.size == (7.0 * 72.0, 5.0 * 72.0)


def test_svg_panels_match_the_table(tmp_path: Path) -> None:
    p = [panelled("#CC0000"), panelled("#00CC00", "a-much-longer-x-label")]
    combined = p[0] | p[1]
    table_boxes = panel_boxes(combined, width_in=7.0, height_in=5.0)
    svg = _svg_panel_rects(combined, tmp_path / "compose.svg", width_in=7.0, height_in=5.0)
    assert set(svg) == {"#CC0000", "#00CC00"}
    assert svg["#CC0000"] == pytest.approx(to_svg_y(table_boxes["panel-area-1-1"], 5.0), abs=0.02)
    assert svg["#00CC00"] == pytest.approx(to_svg_y(table_boxes["panel-area-1-2"], 5.0), abs=0.02)


def test_three_devices_agree_on_the_composition(tmp_path: Path) -> None:
    p1, p2 = panelled("#CC0000"), panelled("#00CC00")
    combined = p1 | p2
    for suffix in ("png", "svg", "pdf"):
        path = tmp_path / f"out.{suffix}"
        result = gg4py.ggsave(combined, path, width=6.0, height=4.0)
        assert path.exists() and path.stat().st_size > 0
        assert result.width_pt == pytest.approx(6.0 * 72.0)
        assert result.height_pt == pytest.approx(4.0 * 72.0)
        if suffix == "png":
            assert result.size_px == (432, 288)


def test_composition_ir_round_trips() -> None:
    from ggcore import ir

    scene = (base() | base()).to_scene(metrics=METRICS, width_in=6.0, height_in=4.0)
    encoded = ir.encode(scene)
    decoded = ir.decode(encoded)
    assert decoded.size == scene.size
    assert decoded.root.kind == scene.root.kind


def test_spacer_block_only_contributes_space() -> None:
    boxes = panel_boxes(base() | plot_spacer(), width_in=7.0, height_in=5.0)
    assert "panel-area-1-2" in boxes
    assert boxes["panel-area-1-2"][2] > 0


# ---------------------------------------------------------------------------
# 默认网格与不同槽位宽度（审计缺口 1 / 2）
# ---------------------------------------------------------------------------


def test_default_grid_matches_wrap_dims() -> None:
    """`n2mfrow()` 的默认网格（不是「近方形」）：`n <= 3` 固定一行。"""
    expected = {
        1: (1, 1),
        2: (1, 2),
        3: (1, 3),
        4: (2, 2),
        5: (2, 3),
        6: (2, 3),
        7: (3, 3),
        8: (3, 3),
        9: (3, 3),
        10: (3, 4),
        11: (3, 4),
        12: (3, 4),
        13: (4, 4),
        14: (4, 4),
        15: (4, 4),
        16: (4, 4),
    }
    for count, (rows, cols) in expected.items():
        table = wrap_plots(*[base() for _ in range(count)]).gtable(metrics=METRICS)
        assert (table.nrow // TABLE_ROWS, table.ncol // TABLE_COLS) == (rows, cols), count


def test_plus_two_plots_is_one_row() -> None:
    """`p1 + p2` 是并排一行（patchwork 的 `+` 默认 n2mfrow），不是上下两行。"""
    boxes = panel_boxes(base() + base())
    assert set(boxes) == {"panel-area-1-1", "panel-area-1-2"}
    left, right = boxes["panel-area-1-1"], boxes["panel-area-1-2"]
    assert left[1] == pytest.approx(right[1], abs=1e-9)
    assert left[3] == pytest.approx(right[3], abs=1e-9)
    assert right[0] > left[0]


def test_plus_three_plots_is_one_row() -> None:
    boxes = panel_boxes(base() + base() + base())
    assert set(boxes) == {"panel-area-1-1", "panel-area-1-2", "panel-area-1-3"}
    for name in ("panel-area-1-2", "panel-area-1-3"):
        assert boxes[name][1] == pytest.approx(boxes["panel-area-1-1"][1], abs=1e-9)


def test_panels_align_with_different_axis_slot_widths(tmp_path: Path) -> None:
    """审计缺口 2：同列两块 y 轴刻度位宽不同时，panel 原点与表级仍逐值一致。

    左列上方是 `y ∈ 1..8`，下方是 `y ∈ 1e6..8e6`（刻度标签宽得多）；表级左槽位
    取两行的 max，渲染必须把 panel 放在同一个 x，而不是各自贴自己的左槽位。
    """
    data = from_dict(
        {
            "x": [1.0, 2.0, 3.0, 4.0],
            "y": [1.0, 3.0, 5.0, 8.0],
            "ybig": [1e6, 3e6, 5e6, 8e6],
        }
    )

    def make(fill: str, y: str) -> ggplot:
        return (
            ggplot(data, aes(x="x", y=y))
            + geom_point()
            + theme(**{"panel.background": element_rect(fill=fill, colour=None)})
        )

    plots = [
        make("#CC0000", "y"),
        make("#00CC00", "y"),
        make("#0000CC", "ybig"),
        make("#CCCC00", "y"),
    ]
    combined = (plots[0] + plots[1] + plots[2] + plots[3]) + plot_layout(ncol=2)
    boxes = panel_boxes(combined, width_in=6.0, height_in=6.0)
    svg = _svg_panel_rects(combined, tmp_path / "slots.svg", width_in=6.0, height_in=6.0)
    assert set(svg) == set(_SVG_COLOURS)
    mapping = {
        "#CC0000": "panel-area-1-1",
        "#00CC00": "panel-area-1-2",
        "#0000CC": "panel-area-2-1",
        "#CCCC00": "panel-area-2-2",
    }
    for colour, name in mapping.items():
        assert svg[colour] == pytest.approx(to_svg_y(boxes[name], 6.0), abs=0.02), name
    # 同一列的两块 panel 的 x / w 相同（渲染级，不只是表里相等）。
    assert svg["#CC0000"][0] == pytest.approx(svg["#0000CC"][0], abs=1e-6)
    assert svg["#CC0000"][2] == pytest.approx(svg["#0000CC"][2], abs=1e-6)
    assert svg["#00CC00"][0] == pytest.approx(svg["#CCCC00"][0], abs=1e-6)


# ---------------------------------------------------------------------------
# guides="collect" / guide_area()（SIL-1002）
# ---------------------------------------------------------------------------


def legend_data() -> Any:
    return from_dict(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "y": [2.0, 4.0, 3.0, 5.0, 6.0, 3.0],
            "g": ["a", "b", "a", "b", "a", "b"],
        }
    )


def legend_plot() -> ggplot:
    return ggplot(legend_data(), aes(x="x", y="y", colour="g")) + geom_point()


def _compose(tf: tuple[float, ...], other: tuple[float, ...]) -> tuple[float, ...]:
    """两个 IR `viewport.transform`（2×3）的合成：父 ∘ 子。"""
    a1, b1, c1, d1, e1, f1 = tf
    a2, b2, c2, d2, e2, f2 = other
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def ir_texts(scene: Any) -> list[tuple[str, float, float]]:
    """IR 里所有文本的页面坐标（pt，y 向下）。"""
    out: list[tuple[str, float, float]] = []

    def walk(node: Any, tf: tuple[float, ...]) -> None:
        transform = node.params.get("transform")
        if transform is not None:
            tf = _compose(tf, tuple(float(value) for value in transform))
        if node.texts:
            a, b, c, d, e, f = tf
            for label, (x, y) in zip(node.texts, node.bufs["pos"], strict=True):
                out.append((label, float(a * x + c * y + e), float(b * x + d * y + f)))
        for child in node.children or ():
            walk(child, tf)

    walk(scene.root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    return out


def legend_labels(plot: Patchwork) -> list[tuple[str, float, float]]:
    """组合渲染后**图例**里的文本（键 a/b 与标题 g）。"""
    scene = plot.to_scene(metrics=METRICS, width_in=7.0, height_in=5.0)
    return [item for item in ir_texts(scene) if item[0] in ("a", "b", "g")]


def test_guides_keep_draws_each_legend() -> None:
    labels = legend_labels(wrap_plots(legend_plot(), legend_plot(), guides="keep"))
    assert [item[0] for item in labels].count("a") == 2
    assert [item[0] for item in labels].count("g") == 2


def test_guides_collect_draws_one_legend() -> None:
    """同结构图例在 `collect` 下只出现一次（patchwork `collapse_guides()`）。"""
    labels = legend_labels(wrap_plots(legend_plot(), legend_plot(), guides="collect"))
    assert [item[0] for item in labels].count("a") == 1
    assert [item[0] for item in labels].count("g") == 1


def test_guides_auto_matches_keep() -> None:
    auto = legend_labels(wrap_plots(legend_plot(), legend_plot()))
    keep = legend_labels(wrap_plots(legend_plot(), legend_plot(), guides="keep"))
    assert [item[0] for item in auto].count("a") == 2
    assert len(auto) == len(keep)


def test_guides_collect_does_not_merge_different_themes() -> None:
    """主题不同不合并（patchwork 比较的是渲染后的 guide grob）。"""
    other = legend_plot() + theme(**{"legend.text": element_text(size=20)})
    labels = legend_labels(wrap_plots(legend_plot(), other, guides="collect"))
    assert [item[0] for item in labels].count("a") == 2
    assert [item[0] for item in labels].count("g") == 2


def test_guides_collect_uses_the_top_level_legend_position() -> None:
    """手工 `legend.position` 作用于顶层（patchwork 的 annotation theme）。"""
    page_width, page_height = 7.0 * 72.0, 5.0 * 72.0
    for position, inside in (
        ("right", lambda x, y: x > page_width * 0.6),
        ("left", lambda x, y: x < page_width * 0.4),
        ("top", lambda x, y: y < page_height * 0.4),
        ("bottom", lambda x, y: y > page_height * 0.6),
    ):
        combined = wrap_plots(legend_plot(), legend_plot(), guides="collect") + theme(
            **{"legend.position": position}
        )
        labels = legend_labels(combined)
        assert [item[0] for item in labels].count("a") == 1, position
        title = next(item for item in labels if item[0] == "g")
        assert inside(title[1], title[2]), (position, title)


def test_guides_collect_adds_one_outer_guide_box() -> None:
    combined = wrap_plots(legend_plot(), legend_plot(), guides="collect")
    table = combined.gtable(metrics=METRICS, width_in=7.0, height_in=5.0)
    names = [row.name for row in table.layout]
    assert names.count("collected-guide-box") == 1
    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None
    assert units.guide.position == "right"
    # 盒在高表最右块的 guide-box 槽里、跨 panel 行。槽位从 `plot_gtable()`
    # 的 `guide-box-right` 抓（本仓的槽比 ggplot2 4.0.3 少一列，见 SIL-999
    # 的已知差异），所以断言「在 panel 右侧的图例槽、跨 panel 行」这组关系。
    t, left, b, right = units.guide.area
    assert left == right
    assert left > TABLE_COLS + PANEL_COL
    assert (t, b) == (PANEL_ROW, PANEL_ROW)
    assert units.guide.layout.width_cm > 0


def test_guides_collect_leaves_more_room_for_panels() -> None:
    """子图各自的图例列被清零后，panel 分到更多宽度（patchwork 同义）。"""
    keep = panel_boxes(wrap_plots(legend_plot(), legend_plot(), guides="keep"))
    collect = panel_boxes(wrap_plots(legend_plot(), legend_plot(), guides="collect"))
    assert collect["panel-area-1-1"][2] > keep["panel-area-1-1"][2]


def test_guide_area_cell_is_a_normal_panel_cell() -> None:
    """`guide_area()` 是一格普通 panel：图例放进去、不额外占行列。"""
    combined = wrap_plots(legend_plot(), guide_area(), guides="collect")
    boxes = panel_boxes(combined)
    area_cell = boxes["panel-area-1-2"]
    # 与左边的 panel 同高、同宽（同一行的 null 权重）。
    assert area_cell[1] == pytest.approx(boxes["panel-area-1-1"][1], abs=1e-9)
    assert area_cell[3] == pytest.approx(boxes["panel-area-1-1"][3], abs=1e-9)
    assert area_cell[2] == pytest.approx(boxes["panel-area-1-1"][2], abs=1e-9)
    # 顶层 guide 盒就落在这一格。
    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None and units.guide.guide_area
    cell = (PANEL_ROW, TABLE_COLS + PANEL_COL, PANEL_ROW, TABLE_COLS + PANEL_COL)
    assert units.guide.area == cell
    # 图例文本在这一格的水平范围内（居中），不在右外侧。
    labels = legend_labels(combined)
    assert [item[0] for item in labels].count("a") == 1
    x_positions = [item[1] for item in labels]
    assert min(x_positions) > 7.0 * 72.0 * 0.5


def test_guides_collect_without_legend_keeps_the_grid() -> None:
    plain = (base() | base()) + plot_layout(guides="collect")
    table = plain.gtable(metrics=METRICS)
    assert not [row for row in table.layout if row.name == "collected-guide-box"]


def test_guides_collect_with_legend_position_none_drops_the_legend() -> None:
    """`legend.position = "none"` 时收集到的图例不往外侧放（patchwork 同义）。"""
    combined = (legend_plot() | legend_plot()) + plot_layout(guides="collect")
    combined = combined + theme(**{"legend.position": "none"})
    labels = legend_labels(combined)
    assert [item[0] for item in labels].count("a") == 0
    table = combined.gtable(metrics=METRICS)
    assert not [row for row in table.layout if row.name == "collected-guide-box"]


def test_guides_collect_nested_layers_do_not_merge() -> None:
    """嵌套层各自收集（patchwork `plot_table.patchwork()` 的传递语义）。"""
    nested = wrap_plots(wrap_plots(legend_plot(), legend_plot()), legend_plot(), guides="collect")
    labels = legend_labels(nested)
    assert [item[0] for item in labels].count("a") == 2


def test_guides_mode_is_validated() -> None:
    with pytest.raises(ComposeError, match="guides"):
        plot_layout(guides="everywhere")


def test_aplot_guide_area_uses_empty_corner_region() -> None:
    """三个子图的 2×2 layout 右下角为空：guide area 落在那一格。"""
    combined = gg4py.set_guide_area(
        wrap_plots(legend_plot(), legend_plot(), legend_plot(), ncol=2, guides="collect"),
        "bottom-right",
    )
    units = composition._build_units(combined, metrics=METRICS)
    assert (units.nrow, units.ncol) == (2, 2)
    assert units.guide is not None and units.guide.guide_area
    assert units.guide.area == (
        TABLE_ROWS + PANEL_ROW,
        TABLE_COLS + PANEL_COL,
        TABLE_ROWS + PANEL_ROW,
        TABLE_COLS + PANEL_COL,
    )
    assert [item[0] for item in legend_labels(combined)].count("a") == 1


def test_aplot_guide_area_rejects_a_full_corner() -> None:
    combined = gg4py.set_guide_area(
        wrap_plots(legend_plot(), legend_plot(), ncol=2, guides="collect"),
        "top-right",
    )
    with pytest.raises(ComposeError, match="没有连续空区"):
        composition._build_units(combined, metrics=METRICS)


def test_aplot_guide_area_right_strip_has_twenty_percent_panel_weight() -> None:
    combined = gg4py.set_guide_area(
        wrap_plots(legend_plot(), legend_plot(), ncol=2, guides="collect"),
        "right",
    )
    units = composition._build_units(combined, metrics=METRICS)
    assert units.ncol == 3
    panel_col = 2 * TABLE_COLS + PANEL_COL - 1
    assert null_value(units.widths, panel_col) == pytest.approx(0.2)
    assert units.guide is not None and units.guide.guide_area
    assert units.guide.area[1] == units.guide.area[3] == 2 * TABLE_COLS + PANEL_COL

    table = combined.gtable(metrics=METRICS, width_in=7.0, height_in=5.0)
    sizes = table.resolve(7.0 * 2.54, 5.0 * 2.54, ctx=CTX)
    guide_cell = next(row for row in table.layout if row.name == "panel-area-guide")
    guide_width = sum(sizes.widths_cm[guide_cell.l - 1 : guide_cell.r])
    panel_cells = [row for row in table.layout if row.name.startswith("panel-area-1-")]
    panel_width = sum(sum(sizes.widths_cm[row.l - 1 : row.r]) for row in panel_cells)
    assert guide_width / (guide_width + panel_width) == pytest.approx(0.2 / 2.2, abs=1e-9)


def test_aplot_guide_area_even_corner_uses_aplot_ceiling_anchor() -> None:
    """偶数长度空区取 `ceiling(n/2)`，即 Python 的 `(n - 1) // 2`。"""
    combined = gg4py.set_guide_area(
        wrap_plots(legend_plot(), legend_plot(), nrow=3, ncol=2, guides="collect"),
        "bottom-right",
    )
    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None
    anchor_row = (units.guide.area[0] - PANEL_ROW) // TABLE_ROWS + 1
    anchor_col = (units.guide.area[1] - PANEL_COL) // TABLE_COLS + 1
    assert (anchor_row, anchor_col) == (2, 1)


def test_aplot_guide_area_left_and_top_preserve_explicit_panel_weights() -> None:
    combined = wrap_plots(
        legend_plot(),
        legend_plot(),
        legend_plot(),
        ncol=3,
        widths=[3.0, 2.0, 1.0],
        guides="collect",
    )
    left = composition._build_units(
        gg4py.set_guide_area(combined, "left"),
        metrics=METRICS,
    )
    left_weights = [
        null_value(left.widths, (col - 1) * TABLE_COLS + PANEL_COL - 1)
        for col in range(1, left.ncol + 1)
    ]
    assert left_weights == [0.2, 3.0, 2.0, 1.0]

    tall = wrap_plots(
        legend_plot(),
        legend_plot(),
        nrow=2,
        heights=[3.0, 1.0],
        guides="collect",
    )
    top = composition._build_units(
        gg4py.set_guide_area(tall, "top"),
        metrics=METRICS,
    )
    top_weights = [
        null_value(top.heights, (row - 1) * TABLE_ROWS + PANEL_ROW - 1)
        for row in range(1, top.nrow + 1)
    ]
    assert top_weights == [0.2, 3.0, 1.0]


def test_aplot_guide_area_requires_collect() -> None:
    combined = gg4py.set_guide_area(wrap_plots(legend_plot(), legend_plot()), "right")
    with pytest.raises(ComposeError, match="guides='collect'"):
        composition._build_units(combined, metrics=METRICS)


def _three_guide_plot() -> ggplot:
    values = from_dict(
        {
            "x": [1.0, 2.0, 3.0],
            "y": [1.0, 2.0, 3.0],
            "g": ["a", "b", "a"],
            "h": ["c", "c", "d"],
            "s": [1.0, 2.0, 3.0],
        }
    )
    return (
        ggplot(
            values,
            aes(x="x", y="y", colour="g", shape="h", size="s"),
        )
        + geom_point()
    )


def test_aplot_guide_layout_stacks_guides_in_columns() -> None:
    combined = gg4py.set_guide_layout(
        wrap_plots(_three_guide_plot(), guides="collect"),
        guides_ncol=2,
        guides_direction="vertical",
    )
    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None
    boxes = units.guide.layout.boxes
    assert len(boxes) == 3
    assert boxes[0].y_cm == pytest.approx(boxes[2].y_cm)
    assert boxes[1].y_cm < boxes[0].y_cm
    assert boxes[0].x_cm < boxes[2].x_cm


def test_aplot_guide_layout_byrow_fills_guides_across_first() -> None:
    combined = gg4py.set_guide_layout(
        wrap_plots(_three_guide_plot(), guides="collect"),
        guides_ncol=2,
        guides_byrow=True,
    )
    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None
    boxes = units.guide.layout.boxes
    # byrow：前两张图例占第一行两列，第三张回到第二行第一列。
    assert boxes[0].x_cm == pytest.approx(boxes[2].x_cm)
    assert boxes[0].x_cm < boxes[1].x_cm
    assert boxes[2].y_cm < boxes[0].y_cm


def test_aplot_guide_layout_configures_individual_legend_keys() -> None:
    combined = gg4py.set_guide_layout(
        wrap_plots(legend_plot(), guides="collect"),
        legend_ncol=2,
        legend_byrow=True,
        legend_direction="horizontal",
        legend_keywidth=8,
        legend_keyheight=5,
        legend_spacing_x=3,
        legend_spacing_y=4,
    )
    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None
    legend = units.guide.entries[0].legend
    assert legend.direction == "horizontal"
    assert legend.width_cm > legend.height_cm


def _continuous_guide_plot() -> ggplot:
    values = from_dict(
        {
            "x": [1.0, 2.0, 3.0, 4.0],
            "y": [1.0, 2.0, 3.0, 4.0],
            "z": [0.1, 0.5, 0.9, 1.0],
        }
    )
    return ggplot(values, aes(x="x", y="y", colour="z")) + geom_point()


@pytest.mark.parametrize(
    "layout",
    [
        {"legend_spacing_x": 3},
        {"legend_keywidth": 8},
        {"legend_title_position": "top"},
    ],
)
def test_aplot_legend_layout_does_not_replace_continuous_colourbar(
    layout: dict[str, Any],
) -> None:
    baseline = composition._build_units(
        wrap_plots(_continuous_guide_plot(), guides="collect"),
        metrics=METRICS,
    ).guide
    combined = gg4py.set_guide_layout(
        wrap_plots(_continuous_guide_plot(), guides="collect"),
        **layout,
    )
    units = composition._build_units(combined, metrics=METRICS)
    assert baseline is not None and units.guide is not None
    before = baseline.entries[0]
    entry = units.guide.entries[0]
    assert entry.guide_build.guide.kind == "colourbar"
    assert entry.legend.bar is not None
    assert not entry.legend.keys
    assert entry.legend.width_cm == pytest.approx(before.legend.width_cm)
    assert entry.legend.height_cm == pytest.approx(before.legend.height_cm)


def test_aplot_legend_layout_does_not_replace_guide_bins() -> None:
    plot = _continuous_guide_plot() + guides(colour=guide_bins())
    combined = gg4py.set_guide_layout(
        wrap_plots(plot, guides="collect"),
        legend_ncol=2,
    )
    units = composition._build_units(combined, metrics=METRICS)
    assert units.guide is not None
    entry = units.guide.entries[0]
    assert entry.guide_build.guide.kind == "bins"


def test_aplot_guide_layout_validation() -> None:
    combined = wrap_plots(legend_plot(), guides="collect")
    with pytest.raises(ComposeError, match="guides_ncol"):
        gg4py.set_guide_layout(combined, guides_ncol=0)
    with pytest.raises(ComposeError, match="legend_direction"):
        gg4py.set_guide_layout(combined, legend_direction="diagonal")
    with pytest.raises(ComposeError, match="Patchwork"):
        gg4py.set_guide_area(legend_plot(), "right")


def test_patchwork_plus_theme_is_the_annotation_theme() -> None:
    """`Patchwork + theme()` 只影响顶层图例排布，不改子图外观。"""
    combined = (legend_plot() | legend_plot()) + theme(**{"legend.position": "bottom"})
    assert isinstance(combined, Patchwork)
    labels = legend_labels(combined + plot_layout(guides="collect"))
    title = next(item for item in labels if item[0] == "g")
    assert title[2] > 5.0 * 72.0 * 0.6
