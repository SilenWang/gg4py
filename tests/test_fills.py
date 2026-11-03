"""渐变 / pattern 的**写方**口径（SIL-751，`ggcore.fills`）。

三层：

1. 单位解析：`npc` 是「被填充对象包围盒的比例」，`pt` 是节点局部坐标直通；
2. 图案的 tile 以 `(x, y)` 为中心（R `pattern(just = "centre")`）；
3. 端到端：`geom_col(fill = 渐变)` 与 `theme(panel.background = element_rect(填渐变))`
   都能落到 IR 的最终几何上，且 `Node` 拒绝「还没解析的规格」。
"""

from __future__ import annotations

import pytest

from ggcore.build import build_plot
from ggcore.fills import (
    linear_gradient,
    node_bbox,
    pattern_rect,
    radial_gradient,
    tile_pattern,
)
from ggcore.ir import IRValidationError, LinearGradient, Node, TilePattern, f32
from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    scale_x_discrete,
    scale_y_continuous,
    theme_void,
)
from ggcore.plot import (
    linear_gradient as plot_linear_gradient,
)
from ggcore.plotspec import build_scene
from ggcore.theme import element_rect, theme
from ggio.frame import to_column_table

BOX = (10.0, 20.0, 110.0, 220.0)  # 100 × 200


def test_linear_npc_resolves_against_the_bbox() -> None:
    fill = linear_gradient(["#FF0000", "#0000FF"], x1=0.0, y1=0.0, x2=1.0, y2=1.0)
    resolved = fill.resolve(BOX)
    assert isinstance(resolved, LinearGradient)
    # npc 的 y 向上（grid 口径）：npc 0 = 包围盒底边 220，npc 1 = 顶边 20
    assert resolved.start == (10.0, 220.0)
    assert resolved.end == (110.0, 20.0)


def test_linear_pt_is_taken_verbatim() -> None:
    fill = linear_gradient(["#FF0000", "#0000FF"], x1=1.0, y1=2.0, x2=3.0, y2=4.0, units="pt")
    resolved = fill.resolve(BOX)
    assert (resolved.start, resolved.end) == ((1.0, 2.0), (3.0, 4.0))


def test_radial_npc_radius_uses_the_short_side() -> None:
    fill = radial_gradient(["#FFFFFF", "#000000"], cx=0.5, cy=0.5, r=0.5)
    resolved = fill.resolve(BOX)
    assert resolved.center == (60.0, 120.0)
    assert resolved.radius == pytest.approx(50.0)  # min(100, 200) × 0.5


def test_radial_focal_point_is_resolved_too() -> None:
    fill = radial_gradient(["#FFFFFF", "#000000"], cx=0.5, cy=0.5, r=0.5, fx=0.25, fy=0.5, fr=0.1)
    resolved = fill.resolve(BOX)
    assert resolved.focal is not None
    assert resolved.focal[0] == pytest.approx(35.0)
    assert resolved.focal[2] == pytest.approx(10.0)


def test_pattern_tile_is_centred_on_the_nominal_point() -> None:
    seen: list[tuple[float, float, float, float]] = []

    def draw(tile: tuple[float, float, float, float]) -> list[Node]:
        seen.append(tile)
        return [pattern_rect(tile, "#E45756")]

    fill = tile_pattern(draw, width=0.2, height=0.1)
    resolved = fill.resolve(BOX)
    assert isinstance(resolved, TilePattern)
    # 中心 (60, 120)，tile 20 × 20 → 左上角 (50, 110)
    assert resolved.size == pytest.approx((20.0, 20.0))
    assert resolved.origin == pytest.approx((50.0, 110.0))
    assert seen == [(50.0, 110.0, 70.0, 130.0)]
    assert resolved.content[0].bufs["rect"].tolist() == [[50.0, 110.0, 70.0, 130.0]]


def test_pattern_pt_size_and_origin() -> None:
    """`units="pt"` 时 x / y / width / height 都是 pt 绝对坐标（R 的 `default.units`）。"""
    fill = tile_pattern(
        lambda tile: [pattern_rect(tile, "#000000")],
        width=8.0,
        height=8.0,
        x=60.0,
        y=120.0,
        units="pt",
    )
    resolved = fill.resolve(BOX)
    assert resolved.size == pytest.approx((8.0, 8.0))
    assert resolved.origin == pytest.approx((56.0, 116.0))


def test_node_bbox_reads_each_primitive() -> None:
    assert node_bbox("rect", {"rect": f32([[10.0, 20.0, 30.0, 40.0]])}, {}) == (10, 20, 30, 40)
    assert node_bbox("circle", {"circle": f32([[5.0, 5.0, 2.0]])}, {}) == (3, 3, 7, 7)
    assert node_bbox("path", {"points": f32([[0.0, 0.0], [4.0, 6.0]])}, {}) == (0, 0, 4, 6)


def test_node_rejects_an_unresolved_fill_spec() -> None:
    spec = linear_gradient(["#FF0000", "#0000FF"])
    from ggcore.ir import Gpar

    with pytest.raises(IRValidationError):
        Node("rect", gpar=Gpar(fill=spec), bufs={"rect": f32([[0.0, 0.0, 1.0, 1.0]])})


# --- 端到端：语法层 → IR ----------------------------------------------------

DATA = {"cls": ["a", "b", "c"], "v": [0.3, 0.6, 0.9]}


def _fills(scene: object) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []

    def walk(node: object) -> None:
        gpar = getattr(node, "gpar", None)
        if gpar is not None and gpar.fill is not None and not isinstance(gpar.fill, tuple):
            out.append((node.kind.value, gpar.fill))
        for child in node.children:
            walk(child)

    walk(scene.root)
    return out


def test_geom_col_fill_reaches_the_ir_as_final_geometry() -> None:
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_col(
            fill=plot_linear_gradient(["#E45756", "#4C78A8"], x1=0, y1=0, x2=1, y2=0), colour=None
        )
        + scale_x_discrete()
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    scene = build_scene({"plot": p, "size": [4, 3]})
    found = _fills(scene)
    assert found, "渐变没有进 IR"
    kind, fill = found[0]
    assert kind == "rect"
    assert isinstance(fill, LinearGradient)
    # npc 0..1 解析成整层 bbox 的两个端点（与 R 多行 grob 的口径一致）
    assert fill.start[0] < fill.end[0]
    assert fill.start[1] == pytest.approx(fill.end[1])


def test_panel_background_gradient_reaches_the_ir() -> None:
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_col(fill="#4C78A8", colour=None)
        + scale_x_discrete()
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(
            **{
                "legend.position": "none",
                "panel.background": element_rect(
                    fill=plot_linear_gradient(["#FFFFFF", "#DDEBF7"], x1=0, y1=0, x2=0, y2=1),
                    colour=None,
                ),
            }
        )
    )
    scene = build_scene({"plot": p, "size": [4, 3]})
    fills = [fill for _, fill in _fills(scene)]
    assert any(isinstance(fill, LinearGradient) and fill.start[1] != fill.end[1] for fill in fills)


def test_build_keeps_the_fill_spec_out_of_the_data_columns() -> None:
    """渐变是**整层一个对象**，不该变成逐行数据列（`Column` 没有 object kind）。"""
    spec = plot_linear_gradient(["#E45756", "#4C78A8"], x1=0, y1=0, x2=1, y2=0)
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_col(fill=spec, colour=None)
        + scale_x_discrete()
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
    )
    build = build_plot(p)
    assert build.layers[0].params["fill"] is spec
    column = build.layers[0].data.column("fill")
    assert all(isinstance(value, str) for value in column.values.tolist())
