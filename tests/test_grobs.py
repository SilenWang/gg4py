"""grob 模型与场景遍历（SIL-594 / M0-6）。

分三块：

1. **原语**：13 种可绘制原语各自的几何、单位参数、IR 种类（`clipPath` /
   `nullGrob` / `zeroGrob` 的容器与布局语义在 §5）；
2. **遍历语义**：深度优先顺序、gpar 继承（含 `NA` 与 `None` 的区别）、
   `clip` 的消解、向量 gp 的展开、`gTree` + `childrenvp` + 临时 gpar；
3. **下游契约**：`zeroGrob` 参与布局、gtable 单元格视口、`to_ir_scene()` 可编码。

数值全部手算（npc / cm / lines / strwidth 在 6×4in 的根视口里换算），
与 `docs/notes/grobs.md` 的口径一一对应。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ggcore.grobs import (
    DEFAULT_FONT_KEY,
    GrobError,
    bezier_grob,
    circle_grob,
    clip_path,
    curve_grob,
    g_tree,
    height_details,
    lines_grob,
    null_grob,
    parse_colour,
    path_grob,
    points_grob,
    polygon_grob,
    polyline_grob,
    raster_grob,
    rect_grob,
    scene,
    segments_grob,
    text_grob,
    width_details,
    xspline_grob,
    zero_grob,
)
from ggcore.gtable import gtable, gtable_add_grob
from ggcore.ir import Anchor, Baseline, NodeKind, decode, encode
from ggcore.units import FixedMetrics, convert_height, convert_width, unit
from ggcore.viewport import NA, Device, ViewportTree, gpar, viewport

# 6×4 in：页面 432×288 pt，根视口铺满且 transform 是单位阵，所以局部坐标 = 页面坐标。
WIDTH_PT = 6.0 * 72.0
HEIGHT_PT = 4.0 * 72.0


def make_tree(
    *, metrics: FixedMetrics | None = None, width_in: float = 6.0, height_in: float = 4.0
) -> ViewportTree:
    return ViewportTree(Device(width_in, height_in), metrics=metrics)


def texts(**widths: float) -> FixedMetrics:
    return FixedMetrics(widths=widths, heights={name: 0.1 for name in widths})


def only(scene_object, kind: NodeKind | None = None):
    instructions = scene_object.instructions
    if kind is not None:
        instructions = tuple(item for item in instructions if item.kind is kind)
    assert len(instructions) == 1, instructions
    return instructions[0]


# ---------------------------------------------------------------------------
# 1. 原语：几何与 IR 种类
# ---------------------------------------------------------------------------


def test_rect_geometry_follows_just_and_npc() -> None:
    tree = make_tree()
    result = scene(rect_grob(x=0.5, y=0.75, width=0.5, height=0.5, just="centre"), tree)
    instruction = only(result)
    assert instruction.kind is NodeKind.RECT
    # 局部坐标 y 向下：y = 0.75 npc → 距顶 0.25 * 288 = 72pt
    np.testing.assert_allclose(instruction.bufs["rect"], [[108.0, 0.0, 324.0, 144.0]], atol=1e-9)
    assert instruction.transform == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def test_rect_just_left_bottom_puts_the_origin_at_xy() -> None:
    tree = make_tree()
    instruction = only(
        scene(
            rect_grob(
                x=1.0, y=1.0, width=2.0, height=0.5, just=("left", "bottom"), default_units="cm"
            ),
            tree,
        )
    )
    # 1cm = 72/2.54 pt；y 向上 1cm = 28.346pt，翻成 y 向下是 288 - 28.346
    x = 72.0 / 2.54
    y_down = HEIGHT_PT - x
    np.testing.assert_allclose(
        instruction.bufs["rect"], [[x, y_down - 0.5 * x, x + 2 * x, y_down]], atol=1e-6
    )


def test_unit_parameters_use_lines_and_strwidth() -> None:
    tree = make_tree(metrics=texts(ab=0.2))
    instruction = only(
        scene(
            rect_grob(
                x=0.0,
                y=0.0,
                width=unit(2, "lines"),
                height=unit(1, "strwidth", data="ab"),
                just=("left", "bottom"),
            ),
            tree,
        )
    )
    # lines：fontsize 12 × cex 1 × lineheight 1.2 / 72 in = 0.4 in = 28.8 pt
    # strwidth：0.2 in = 14.4 pt
    x0, y0, x1, y1 = instruction.bufs["rect"][0]
    assert x1 - x0 == pytest.approx(28.8)
    assert y1 - y0 == pytest.approx(14.4)


def test_a_grob_gpar_drives_its_own_unit_conversion() -> None:
    """`width = unit(2, "lines")` 用的是**这个 grob 的 gp**，不是视口缺省值。"""
    tree = make_tree()
    plain = only(scene(rect_grob(x=0, y=0, width=unit(2, "lines"), height=1), tree))
    scaled = only(
        scene(
            rect_grob(x=0, y=0, width=unit(2, "lines"), height=1, gp=gpar(fontsize=20)),
            tree,
        )
    )
    assert plain.bufs["rect"][0][2] - plain.bufs["rect"][0][0] == pytest.approx(28.8)
    assert scaled.bufs["rect"][0][2] - scaled.bufs["rect"][0][0] == pytest.approx(48.0)


@pytest.mark.parametrize(
    "factory,kind",
    [
        (lambda: rect_grob(), NodeKind.RECT),
        (lambda: circle_grob(), NodeKind.CIRCLE),
        (lambda: lines_grob([0.0, 1.0], [0.0, 1.0]), NodeKind.LINES),
        (lambda: segments_grob(0.0, 0.0, 1.0, 1.0), NodeKind.SEGMENTS),
        (lambda: polyline_grob([0.0, 1.0], [0.0, 1.0]), NodeKind.POLYLINE),
        (lambda: polygon_grob([0.0, 1.0, 0.5], [0.0, 0.0, 1.0]), NodeKind.POLYGON),
        (lambda: path_grob([0.0, 1.0, 0.5], [0.0, 0.0, 1.0]), NodeKind.PATH),
        (lambda: points_grob([0.5], [0.5]), NodeKind.POINTS),
        (lambda: text_grob("hi"), NodeKind.TEXT),
        (
            lambda: raster_grob(b"\x89PNG", 1, 1),
            NodeKind.RASTER,
        ),
        (lambda: xspline_grob([0.0, 1.0], [0.0, 1.0]), NodeKind.XSPLINE),
        (lambda: bezier_grob([0.0, 0.3, 0.7, 1.0], [0.0, 1.0, 1.0, 0.0]), NodeKind.BEZIER),
        (lambda: curve_grob(0.0, 0.0, 1.0, 1.0), NodeKind.CURVE),
    ],
    ids=[
        "rect",
        "circle",
        "lines",
        "segments",
        "polyline",
        "polygon",
        "path",
        "points",
        "text",
        "raster",
        "xspline",
        "bezier",
        "curve",
    ],
)
def test_each_primitive_lands_on_its_ir_kind(factory, kind) -> None:
    tree = make_tree(metrics=texts(hi=0.1))
    instruction = only(scene(factory(), tree))
    assert instruction.kind is kind
    assert instruction.to_node().kind is kind


def test_the_thirteen_primitives_are_all_reachable() -> None:
    """名单固定：13 种可绘制原语 + clipPath / nullGrob / zeroGrob / gTree 四个容器。

    计数口径只有一份（`docs/notes/grobs.md` §1）：18 个 grob 构造器 = 13 种
    可绘制原语 + 这 4 个容器 + gtable 的 grob 视图。
    """
    tree = make_tree(metrics=texts(hi=0.1))
    leaves = [
        rect_grob(),
        circle_grob(),
        lines_grob([0.0, 1.0], [0.0, 1.0]),
        segments_grob(0.0, 0.0, 1.0, 1.0),
        polyline_grob([0.0, 1.0], [0.0, 1.0]),
        polygon_grob([0.0, 1.0, 0.5], [0.0, 0.0, 1.0]),
        path_grob([0.0, 1.0, 0.5], [0.0, 0.0, 1.0]),
        points_grob([0.5], [0.5]),
        text_grob("hi"),
        raster_grob(b"\x89PNG", 1, 1),
        xspline_grob([0.0, 1.0], [0.0, 1.0]),
        bezier_grob([0.0, 0.3, 0.7, 1.0], [0.0, 1.0, 1.0, 0.0]),
        curve_grob(0.0, 0.0, 1.0, 1.0),
    ]
    kinds = {item.kind for item in scene(leaves, tree).instructions}
    assert kinds == {
        NodeKind.RECT,
        NodeKind.CIRCLE,
        NodeKind.LINES,
        NodeKind.SEGMENTS,
        NodeKind.POLYLINE,
        NodeKind.POLYGON,
        NodeKind.PATH,
        NodeKind.POINTS,
        NodeKind.TEXT,
        NodeKind.RASTER,
        NodeKind.XSPLINE,
        NodeKind.BEZIER,
        NodeKind.CURVE,
    }
    # clipPath 只是容器：子节点原样出现，自己不产出节点
    clipped = scene(clip_path(rect_grob(), x=0.1, y=0.1, width=0.5, height=0.5), tree)
    assert [item.kind for item in clipped.instructions] == [NodeKind.RECT]
    # nullGrob / zeroGrob 不画
    assert scene([null_grob(), zero_grob()], tree).instructions == ()
    # gTree 不画，只按顺序摊开子节点
    grouped = scene(g_tree(rect_grob(), circle_grob()), tree)
    assert [item.kind for item in grouped.instructions] == [NodeKind.RECT, NodeKind.CIRCLE]


def test_circle_and_points_geometry() -> None:
    tree = make_tree()
    circle = only(scene(circle_grob(x=0.25, y=0.5, r=0.1), tree))
    np.testing.assert_allclose(circle.bufs["circle"], [[108.0, 144.0, 43.2]], atol=1e-9)
    points = only(scene(points_grob([0.0, 1.0], [0.0, 1.0], pch=16, size=unit(4, "bigpts")), tree))
    np.testing.assert_allclose(points.bufs["points"], [[0.0, 288.0], [432.0, 0.0]], atol=1e-9)
    assert points.params["pch"] == 16
    assert points.params["size"] == pytest.approx(4.0)


def test_segments_and_bezier_carry_their_frame() -> None:
    tree = make_tree()
    segments = only(
        scene(
            segments_grob(x0=[0.0, 0.5], y0=[0.0, 0.5], x1=[1.0, 1.0], y1=[1.0, 1.0]),
            tree,
        )
    )
    np.testing.assert_allclose(
        segments.bufs["segments"],
        [[0.0, 288.0, 432.0, 0.0], [216.0, 144.0, 432.0, 0.0]],
        atol=1e-9,
    )
    bezier = only(scene(bezier_grob([0.0, 0.3, 0.7, 1.0], [0.0, 1.0, 1.0, 0.0]), tree))
    assert bezier.bufs["control"].shape == (4, 2)
    assert bezier.bufs["control"][1].tolist() == pytest.approx([129.6, 0.0])


def test_bezier_needs_a_multiple_of_four_control_points() -> None:
    with pytest.raises(GrobError):
        bezier_grob([0.0, 0.5, 1.0], [0.0, 1.0, 0.0])


def test_curve_rejects_multiple_curves_for_now() -> None:
    with pytest.raises(GrobError):
        curve_grob([0.0, 0.5], [0.0, 0.5], [1.0, 1.0], [1.0, 1.0])


# ---------------------------------------------------------------------------
# 2. 遍历：顺序、gpar、clip、向量 gp
# ---------------------------------------------------------------------------


def test_depth_first_order_and_draw_order() -> None:
    tree = make_tree()
    nested = g_tree(rect_grob(name="c"), circle_grob(name="d"), name="inner")
    result = scene(g_tree(rect_grob(name="a"), nested, points_grob([0.5], [0.5], name="b")), tree)
    assert [item.source for item in result.instructions] == ["a", "c", "d", "b"]


def test_gpar_inheritance_is_resolved_before_ir() -> None:
    tree = make_tree()
    tree.push(viewport("panel", gp=gpar(cex=2, fill="#010203")))
    result = scene(
        g_tree(
            rect_grob(gp=gpar(col="#102030")),
            g_tree(rect_grob(), gp=gpar(cex=0.5)),
            gp=gpar(fontsize=20),
        ),
        tree,
    )
    first, second = result.instructions
    assert first.resolved.fill == "#010203"
    assert first.resolved.col == "#102030"
    assert first.resolved.fontsize == 20.0
    # cex 是累积的：视口 2 × gTree 0.5 = 1.0（不是 0.5）
    assert second.resolved.cex == pytest.approx(1.0)
    assert first.gpar.fill == (1, 2, 3, 255)
    assert first.gpar.col == (16, 32, 48, 255)


def test_na_and_none_are_two_different_things() -> None:
    tree = make_tree()
    transparent = only(scene(rect_grob(gp=gpar(col=NA, fill=NA)), tree))
    cleared = only(scene(rect_grob(gp=gpar(col=None, fill=None)), tree))
    # NA：解析后仍是 NA，写 IR 时折成“不画”
    assert transparent.resolved.col is NA
    assert transparent.resolved.fill is NA
    assert transparent.gpar.col is None
    assert transparent.gpar.fill is None
    # None：清回 grid 缺省值（col=black、fill=transparent），所以 col 会画
    assert cleared.resolved.col == "black"
    assert cleared.resolved.fill == "transparent"
    assert cleared.gpar.col == (0, 0, 0, 255)
    assert cleared.gpar.fill is None


def test_na_survives_the_parent_chain_but_none_does_not() -> None:
    tree = make_tree()
    tree.push(viewport("v", gp=gpar(col="#ff0000")))
    keep = only(scene(rect_grob(gp=gpar(col=NA)), tree))
    reset = only(scene(rect_grob(gp=gpar(col=None)), tree))
    assert keep.resolved.col is NA
    assert reset.resolved.col == "black"


def test_clip_inherit_takes_the_parent_box_and_off_does_not() -> None:
    tree = make_tree()
    # just 缺省 "centre"：中心落在 (0.5, 0.5) npc → 盒子是 0.25..0.75 npc
    parent = tree.push(viewport("panel", x=0.5, y=0.5, width=0.5, height=0.5, clip="on"))
    expected_parent = parent.ir_clip_rect()
    assert expected_parent == (108.0, 72.0, 324.0, 216.0)

    inherited = only(
        scene(
            rect_grob(vp=viewport("child", x=0.5, y=0.5, width=2, height=2, clip="inherit")),
            tree,
        )
    )
    assert inherited.clip == expected_parent

    off = only(
        scene(
            rect_grob(vp=viewport("loose", x=0.5, y=0.5, width=2, height=2, clip="off")),
            tree,
        )
    )
    assert off.clip == (-216.0, -144.0, 648.0, 432.0)

    on = only(
        scene(
            rect_grob(vp=viewport("tight", x=0.5, y=0.5, width=0.5, height=0.5, clip="on")),
            tree,
        )
    )
    assert on.clip == (162.0, 108.0, 270.0, 180.0)


def test_clip_path_intersects_with_the_viewport_clip() -> None:
    tree = make_tree()
    tree.push(viewport("panel", x=0.5, y=0.5, width=0.5, height=0.5, clip="on"))
    result = scene(
        clip_path(rect_grob(), x=0.0, y=0.0, width=0.25, height=0.25, default_units="npc"),
        tree,
    )
    instruction = only(result)
    # 视口框是 0.25..0.75 npc = (108..324, 72..216) 页面 pt。clipPath 缺省
    # just=("left","bottom")，0.25 npc 宽 × 0.25 npc 高 = 54 × 36 pt，落在视口左下角，
    # 页面坐标就是 (108, 180)-(162, 216)——交集即它自己。
    assert instruction.clip == (108.0, 180.0, 162.0, 216.0)


def test_vector_gp_expands_into_one_node_per_run_of_equal_values() -> None:
    tree = make_tree()
    result = scene(
        points_grob(
            [0.1, 0.2, 0.3, 0.4],
            [0.5, 0.5, 0.5, 0.5],
            gp={"col": ["#ff0000", "#ff0000", "#0000ff", NA]},
        ),
        tree,
    )
    assert len(result.instructions) == 3
    first, second, third = result.instructions
    assert first.rows == 2 and second.rows == 1 and third.rows == 1
    assert first.gpar.col == (255, 0, 0, 255)
    assert second.gpar.col == (0, 0, 255, 255)
    assert third.gpar.col is None  # NA：不画
    assert third.resolved.col is NA
    # 顺序与 R 一致：第 0、1 个点红，第 2 个蓝，第 3 个 NA
    np.testing.assert_allclose(first.bufs["points"][:, 0], [43.2, 86.4])
    assert second.bufs["points"][0, 0] == pytest.approx(129.6)
    assert third.bufs["points"][0, 0] == pytest.approx(172.8)


def test_vector_gp_recycles_and_groups_only_consecutive_runs() -> None:
    tree = make_tree()
    result = scene(
        points_grob(
            [0.1, 0.2, 0.3, 0.4],
            [0.5, 0.5, 0.5, 0.5],
            gp={"col": ["#ff0000", "#0000ff"]},
        ),
        tree,
    )
    assert [item.rows for item in result.instructions] == [1, 1, 1, 1]


def test_vector_gp_on_path_like_grobs_is_refused() -> None:
    tree = make_tree()
    with pytest.raises(GrobError, match="路径型原语"):
        scene(
            lines_grob(
                [0.0, 0.5, 1.0],
                [0.0, 1.0, 0.0],
                gp={"col": ["#ff0000", "#00ff00", "#0000ff"]},
            ),
            tree,
        )


def test_vector_gp_length_must_recycle_to_the_element_count() -> None:
    with pytest.raises(GrobError, match="does not recycle"):
        points_grob([0.1, 0.2, 0.3], [0.5, 0.5, 0.5], gp={"col": ["#ff0000", "#00ff00"]})


def test_traversal_leaves_the_viewport_tree_untouched() -> None:
    tree = make_tree(metrics=texts(hi=0.1))
    parent = tree.push(viewport("panel", x=0.5, y=0.5, width=0.5, height=0.5))
    before_gpar = tree.gpar
    before_children = dict(tree.current.children)
    scene(
        g_tree(
            text_grob("hi", vp=viewport("child", width=0.5, height=0.5)),
            childrenvp=viewport("tree-vp", width=0.5, height=0.5),
            gp=gpar(cex=3),
        ),
        tree,
    )
    assert tree.current is parent
    assert tree.gpar == before_gpar
    assert dict(tree.current.children) == before_children


# ---------------------------------------------------------------------------
# 3. gTree + childrenvp + 临时 gpar（SIL-624 那条路径）
# ---------------------------------------------------------------------------


def test_childrenvp_geometry_uses_the_g_tree_gpar() -> None:
    tree = make_tree()
    child = viewport(
        "child",
        x=0.0,
        y=0.0,
        width=unit(2, "lines"),
        height=unit(2, "lines"),
        just=("left", "bottom"),
    )
    result = scene(
        g_tree(rect_grob(width=1, height=1), childrenvp=child, gp=gpar(fontsize=20)),
        tree,
    )
    x0, y0, x1, y1 = only(result).bufs["rect"][0]
    # 2 lines @ fontsize 20, lineheight 1.2 = 48pt；用视口的 ps=12 会得 28.8
    assert (x1 - x0, y1 - y0) == pytest.approx((48.0, 48.0))
    assert only(result).vp == "child"


def test_childrenvp_without_a_gp_uses_the_viewport_gpar() -> None:
    tree = make_tree()
    child = viewport(
        "child", width=unit(2, "lines"), height=unit(2, "lines"), just=("left", "bottom")
    )
    result = scene(g_tree(rect_grob(width=1, height=1), childrenvp=child), tree)
    x0, _, x1, _ = only(result).bufs["rect"][0]
    assert x1 - x0 == pytest.approx(28.8)


def test_gpar_is_restored_only_after_leaving_the_children_viewports() -> None:
    """R `preDraw.gTree()` 的顺序：先退回 gTree 层，再恢复 gpar。"""
    tree = make_tree()
    seen: list[tuple[str, float]] = []

    original_visit = tree.push

    def spy(*specs):
        node = original_visit(*specs)
        seen.append((node.name, tree.gpar.fontsize))
        return node

    tree.push = spy  # type: ignore[method-assign]
    result = scene(
        g_tree(
            rect_grob(width=1, height=1),
            childrenvp=viewport("child", width=unit(1, "lines"), height=unit(1, "lines")),
            gp=gpar(fontsize=20),
        ),
        tree,
    )
    # push 子视口时 gpar 已经叠上了 gTree 的 fontsize=20
    assert seen == [("child", 20.0)]
    # 画完之后当前视口回到根，gpar 也回到进来时的值
    assert tree.current is tree.root
    assert tree.gpar.fontsize == 12.0
    assert only(result).resolved.fontsize == 20.0


def test_nested_g_trees_stack_their_gpar() -> None:
    tree = make_tree()
    result = scene(
        g_tree(
            g_tree(rect_grob(), gp=gpar(cex=0.5, col="#00ff00")),
            gp=gpar(cex=2, col="#ff0000"),
        ),
        tree,
    )
    instruction = only(result)
    assert instruction.resolved.cex == pytest.approx(1.0)
    assert instruction.gpar.col == (0, 255, 0, 255)


# ---------------------------------------------------------------------------
# 4. 文本、位图、颜色、虚实线
# ---------------------------------------------------------------------------


def test_text_width_comes_from_the_metric_provider() -> None:
    tree = make_tree(metrics=texts(hello=0.5))
    instruction = only(scene(text_grob("hello"), tree))
    assert float(instruction.bufs["width"][0]) == pytest.approx(36.0)  # 0.5 in = 36 pt
    assert instruction.params["font"] == DEFAULT_FONT_KEY
    assert instruction.params["size"] == pytest.approx(12.0)
    assert instruction.params["anchor"] == Anchor.CENTER.value
    assert instruction.params["baseline"] == Baseline.MIDDLE.value


def test_text_just_is_folded_into_pos() -> None:
    tree = make_tree(metrics=texts(ab=0.2))  # 14.4pt 宽
    left = only(scene(text_grob("ab", x=0.5, y=0.5, just=("left", "centre")), tree))
    assert left.params["anchor"] == Anchor.LEFT.value
    assert float(left.bufs["pos"][0, 0]) == pytest.approx(216.0)

    odd = only(scene(text_grob("ab", x=0.5, y=0.5, just=(0.3, "centre")), tree))
    # 最近的是 centre（0.5；hjust=0.25 与 0/0.5 等距，按“小者优先”取 left），
    # pos 平移 (0.5 - 0.3) * 14.4 = +2.88
    assert odd.params["anchor"] == Anchor.CENTER.value
    assert float(odd.bufs["pos"][0, 0]) == pytest.approx(216.0 + 2.88)

    bottom = only(scene(text_grob("ab", x=0.5, y=0.5, just=("centre", "bottom")), tree))
    assert bottom.params["baseline"] == Baseline.BOTTOM.value


def test_text_angle_is_the_local_rotation_only() -> None:
    """`params["angle"]` 只放 `rot`；视口旋转在 `transform` 里（SIL-634）。"""
    tree = make_tree(metrics=texts(ab=0.2))
    tree.push(viewport("rot", angle=30))
    instruction = only(scene(text_grob("ab", rot=15), tree))
    assert instruction.params["angle"] == pytest.approx(15.0)
    # 视口 30° 在仿射的线性部分（y 向下：a=cos, b=-sin, c=sin, d=cos）
    a, b, c, d, _, _ = instruction.transform
    radius = math.radians(30.0)
    assert (a, b, c, d) == pytest.approx(
        (math.cos(radius), -math.sin(radius), math.sin(radius), math.cos(radius))
    )


def _page_text_direction(instruction) -> float:
    """文字基线在页面里的方向（度，逆时针）= 视口旋转 ∘ 局部 `rot`。"""
    a, b, c, d, _, _ = instruction.transform
    angle = math.radians(float(instruction.params["angle"]))
    # 局部坐标 y 向下，IR 的 `angle` 是逆时针：局部 x 轴转 `angle` 后是 (cos, -sin)
    vx, vy = math.cos(angle), -math.sin(angle)
    px, py = a * vx + c * vy, b * vx + d * vy
    return math.degrees(math.atan2(-py, px))


def test_text_rotation_is_not_applied_twice() -> None:
    """SIL-634 的阻塞：A 视口 20° + `rot=0` 画成 20°，B 无旋转视口 + `rot=40` 画成 40°。

    修之前 A 与 B 都是 40°（`angle` 里已经含了一份视口旋转，`transform` 里又一份）。
    A/B 两份的 `params["angle"]` 与页面方向都钉在这里；渲染结果由 `grob-text`
    与 `grob-text-rot` 两张快照兜住。
    """
    tree_a = make_tree(metrics=texts(ab=0.2))
    tree_a.push(viewport("rot20", angle=20))
    a = only(scene(text_grob("ab", rot=0), tree_a))
    b = only(scene(text_grob("ab", rot=40), make_tree(metrics=texts(ab=0.2))))
    assert a.params["angle"] == pytest.approx(0.0)
    assert b.params["angle"] == pytest.approx(40.0)
    assert _page_text_direction(a) == pytest.approx(20.0)
    assert _page_text_direction(b) == pytest.approx(40.0)

    # 两个都写：视口 20° + rot 20 → 页面 40°，与 B 同向
    tree_ab = make_tree(metrics=texts(ab=0.2))
    tree_ab.push(viewport("rot20", angle=20))
    both = only(scene(text_grob("ab", rot=20), tree_ab))
    assert both.params["angle"] == pytest.approx(20.0)
    assert _page_text_direction(both) == pytest.approx(40.0)


def test_text_without_metrics_is_an_error() -> None:
    tree = make_tree()
    with pytest.raises(GrobError, match="度量"):
        scene(text_grob("hello"), tree)


def test_raster_collects_blobs_and_references_them() -> None:
    tree = make_tree()
    result = scene(raster_grob(b"\x89PNG\r\n", 2, 3, x=0.5, y=0.5, width=0.5, height=0.5), tree)
    instruction = only(result)
    blob_id = instruction.params["blob"]
    assert blob_id in result.blobs
    assert result.blobs[blob_id].data == b"\x89PNG\r\n"
    assert instruction.params["width"] == 2
    assert instruction.params["height"] == 3
    assert instruction.bufs["rect"].shape == (1, 4)


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("#fff", (255, 255, 255, 255)),
        ("#102030", (16, 32, 48, 255)),
        ("#10203040", (16, 32, 48, 64)),
        ("red", (255, 0, 0, 255)),
        ("grey50", (128, 128, 128, 255)),
        ("grey92", (235, 235, 235, 255)),
        ("gray0", (0, 0, 0, 255)),
        ((1, 2, 3), (1, 2, 3, 255)),
        ([4, 5, 6, 7], (4, 5, 6, 7)),
    ],
)
def test_colour_parsing_matches_col2rgb(spec, expected) -> None:
    assert parse_colour(spec) == expected


def test_unknown_colour_names_are_rejected() -> None:
    with pytest.raises(GrobError, match="unknown colour"):
        parse_colour("notacolour")


def test_transparent_and_na_paint_nothing() -> None:
    tree = make_tree()
    transparent = only(scene(rect_grob(gp=gpar(fill="transparent", col="transparent")), tree))
    assert transparent.gpar.fill is None
    assert transparent.gpar.col is None
    assert transparent.resolved.fill == "transparent"


@pytest.mark.parametrize(
    "lty,expected",
    [
        (1, ()),
        # dashed (4,4) × max(lwd, 1)：R 的参考产线（svglite）按 gpar 的 lwd 换算段长，
        # 小于 1 的 lwd 记作 1（细线的虚线不会退化成实线）。lwd = 2 → 8pt。
        (2, (8.0, 8.0)),
        ("dashed", (8.0, 8.0)),
        ("44", (8.0, 8.0)),
        ((1, 2, 3), (2.0, 4.0, 6.0)),
    ],
)
def test_lty_is_folded_into_pt_dashes(lty, expected) -> None:
    tree = make_tree()
    instruction = only(scene(lines_grob([0.0, 1.0], [0.0, 1.0], gp=gpar(lty=lty, lwd=2)), tree))
    assert instruction.gpar.lty == expected


def test_lwd_is_converted_from_r_units_to_pt() -> None:
    """R 的 `gpar$lwd` 是 1/96 inch，IR 的 `lwd` 是 pt：折算因子 72/96 = 0.75。"""
    tree = make_tree()
    instruction = only(scene(lines_grob([0.0, 1.0], [0.0, 1.0], gp=gpar(lwd=6)), tree))
    assert instruction.gpar.lwd == pytest.approx(4.5)


def test_blank_line_types_paint_nothing() -> None:
    tree = make_tree()
    instruction = only(scene(lines_grob([0.0, 1.0], [0.0, 1.0], gp=gpar(lty="blank")), tree))
    assert instruction.gpar.col is None
    assert instruction.gpar.fill is None


# ---------------------------------------------------------------------------
# 5. 布局：zeroGrob / nullGrob / gTree 的 widthDetails
# ---------------------------------------------------------------------------


def test_zero_and_null_grobs_have_zero_size_and_no_instructions() -> None:
    tree = make_tree()
    node = tree.current
    for grob in (zero_grob(), null_grob()):
        assert scene(grob, tree).instructions == ()
        assert convert_width(width_details(grob, node), "cm", ctx=node.unit_context())[0] == 0.0
        assert convert_width(height_details(grob, node), "cm", ctx=node.unit_context())[0] == 0.0


def test_zero_grob_participates_in_a_g_tree_extent() -> None:
    tree = make_tree()
    node = tree.current
    tree_grob = g_tree(
        rect_grob(width=unit(2, "cm"), height=unit(1, "cm")),
        zero_grob(),
        g_tree(rect_grob(width=unit(3, "cm"), height=unit(4, "cm"))),
    )
    width = convert_width(width_details(tree_grob, node), "cm", ctx=node.unit_context())[0]
    height = convert_width(height_details(tree_grob, node), "cm", ctx=node.unit_context())[0]
    assert width == pytest.approx(3.0)
    assert height == pytest.approx(4.0)
    assert scene(tree_grob, tree).instructions.__len__() == 2


def test_text_extent_uses_the_metric_provider() -> None:
    tree = make_tree(metrics=texts(hello=0.5))
    node = tree.current
    width = convert_width(width_details(text_grob("hello"), node), "cm", ctx=node.unit_context())[0]
    assert width == pytest.approx(1.27)


def test_width_details_follows_the_inherited_gp() -> None:
    """`widthDetails` 的 `lines` / `char` 按**继承后**的 gp 换算（SIL-634）。

    `gTree(gp = gpar(fontsize = 20))` 里的 `rect_grob(width = unit(2, "lines"))`
    是 2 × 20pt × 1.2 = 48pt = 1.693 cm；用视口的 ps=12 会得 28.8pt（1.016 cm）。
    """
    tree = make_tree()
    node = tree.current
    tree_grob = g_tree(
        rect_grob(width=unit(2, "lines"), height=unit(1, "lines")),
        g_tree(rect_grob(width=unit(1, "lines"), height=unit(4, "lines")), gp=gpar(fontsize=24)),
        gp=gpar(fontsize=20),
    )
    width = convert_width(width_details(tree_grob, node), "cm", ctx=node.unit_context())[0]
    height = convert_height(height_details(tree_grob, node), "cm", ctx=node.unit_context())[0]
    # 子节点的 gp 叠在外层之上：内层 gTree fontsize=24 → 4 × 24 × 1.2 = 115.2pt
    assert height == pytest.approx(115.2 / 72.0 * 2.54)
    # 宽度取 unit_max：外层 48pt，内层 1 × 24 × 1.2 = 28.8pt
    assert width == pytest.approx(48.0 / 72.0 * 2.54)

    # 同一份结果换一个上下文求值不变：单位在这一层已经折成绝对 pt
    absolute = convert_width(width_details(tree_grob, node), "bigpts", ctx=node.unit_context())[0]
    assert absolute == pytest.approx(48.0)


def test_text_extent_follows_the_inherited_gp() -> None:
    """`text_grob` 子节点的 `gp.fontsize = 20` 在量宽高时生效（不是视口的 12）。"""
    seen: list[float] = []

    class SpyMetrics:
        def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
            seen.append(float(fontsize))
            return 0.5

        def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
            return 0.1

    tree = ViewportTree(Device(6.0, 4.0), metrics=SpyMetrics())
    node = tree.current
    tree_grob = g_tree(text_grob("hello", gp=gpar(fontsize=20)), gp=gpar(fontsize=20))
    height = convert_height(height_details(tree_grob, node), "bigpts", ctx=node.unit_context())[0]
    assert height == pytest.approx(20.0 * 1.2)
    assert seen == [20.0]


def test_points_extent_in_char_units_follows_the_inherited_gp() -> None:
    tree = make_tree()
    node = tree.current
    inside = g_tree(points_grob([0.5], [0.5], size=unit(1, "char")), gp=gpar(fontsize=20))
    outside = points_grob([0.5], [0.5], size=unit(1, "char"))
    context = node.unit_context()
    inside_width = convert_width(width_details(inside, node), "bigpts", ctx=context)[0]
    outside_width = convert_width(width_details(outside, node), "bigpts", ctx=context)[0]
    assert inside_width == pytest.approx(20.0)  # gTree 的 fontsize=20 → 1 char = 20pt
    assert outside_width == pytest.approx(12.0)  # 视口缺省 ps=12


# ---------------------------------------------------------------------------
# 6. gtable：单元格视口、clip 三态、嵌套与 z 序
# ---------------------------------------------------------------------------


def build_table() -> object:
    table = gtable(widths=[unit(1, "null"), unit(1, "null")], heights=[unit(1, "null")])
    table = gtable_add_grob(
        table, rect_grob(gp=gpar(fill="#ff0000")), t=1, l=1, z=2, clip="on", name="left"
    )
    table = gtable_add_grob(
        table, circle_grob(gp=gpar(fill="#00ff00")), t=1, l=2, z=1, clip="inherit", name="right"
    )
    return table


def test_gtable_cells_get_their_own_viewports_in_drawing_order() -> None:
    tree = make_tree()
    result = scene(build_table(), tree)
    # z 序：z=1 的圆先画，z=2 的矩形后画（同 z 保持添加顺序）
    assert [item.source for item in result.instructions] == ["circle", "rect"]
    assert [item.vp for item in result.instructions] == [
        "right.1-2-1-2",
        "left.1-1-1-1",
    ]
    left, right = result.instructions[1], result.instructions[0]
    # 两列各 216pt；clip="on" 的格子裁剪框就是自己的盒子
    assert left.clip == (0.0, 0.0, 216.0, 288.0)
    # clip="inherit" 取父视口（这里是根视口）的裁剪框，不是 off
    assert right.clip == tree.root.ir_clip_rect()


def test_gtable_clip_off_uses_the_device_box() -> None:
    tree = make_tree()
    table = gtable(widths=[unit(1, "null")], heights=[unit(1, "null")])
    table = gtable_add_grob(table, rect_grob(), t=1, l=1, clip="off")
    assert only(scene(table, tree)).clip == (-216.0, -144.0, 648.0, 432.0)


def test_nested_gtable_is_drawn_in_the_cell_viewport() -> None:
    inner = gtable(widths=[unit(1, "null")], heights=[unit(1, "null")], name="inner")
    inner = gtable_add_grob(inner, rect_grob(name="deep", gp=gpar(fill="#123456")), t=1, l=1)
    outer = gtable(widths=[unit(1, "null")], heights=[unit(1, "null")], name="outer")
    outer = gtable_add_grob(outer, inner, t=1, l=1, name="cell")
    tree = make_tree()
    instruction = only(scene(outer, tree))
    assert instruction.source == "deep"
    assert instruction.vp == "cell.1-1-1-1::inner.1-1-1-1"
    assert instruction.gpar.fill == (0x12, 0x34, 0x56, 255)


# ---------------------------------------------------------------------------
# 7. 写 IR：每种原语都能编码 / 解码
# ---------------------------------------------------------------------------


def test_scene_converts_to_an_ir_scene_that_round_trips() -> None:
    tree = make_tree(metrics=texts(hello=0.5))
    tree.push(viewport("panel", x=0.5, y=0.5, width=0.8, height=0.8, angle=10))
    grobs = [
        rect_grob(gp=gpar(fill="#4C78A8")),
        circle_grob(r=0.2),
        lines_grob([0.0, 0.5, 1.0], [0.0, 1.0, 0.0]),
        segments_grob(0.0, 0.0, 1.0, 1.0),
        polyline_grob([0.0, 0.5, 1.0], [0.0, 1.0, 0.0], id=[1, 1, 2]),
        polygon_grob([0.0, 1.0, 0.5], [0.0, 0.0, 1.0]),
        path_grob([0.0, 1.0, 0.5], [0.0, 0.0, 1.0], rule="evenodd"),
        points_grob([0.1, 0.2], [0.1, 0.2], pch=19, size=3),
        text_grob("hello"),
        raster_grob(b"\x89PNG", 2, 2),
        xspline_grob([0.0, 0.4, 1.0], [0.0, 1.0, 0.0], shape=0.25),
        bezier_grob([0.0, 0.3, 0.7, 1.0], [0.0, 1.0, 1.0, 0.0]),
        curve_grob(0.1, 0.1, 0.9, 0.9, curvature=0.5),
    ]
    result = scene(grobs, tree)
    ir_scene = result.to_ir_scene()
    assert ir_scene.size == (WIDTH_PT, HEIGHT_PT)
    data = encode(ir_scene)
    assert decode(data) == ir_scene
    kinds = {node.kind for node in _walk(ir_scene.root)}
    # 恰好 14 种：13 种可绘制原语 + `viewport`（`docs/notes/grobs.md` §1 的计数口径）
    assert kinds == {
        NodeKind.VIEWPORT,
        NodeKind.RECT,
        NodeKind.CIRCLE,
        NodeKind.LINES,
        NodeKind.SEGMENTS,
        NodeKind.POLYLINE,
        NodeKind.POLYGON,
        NodeKind.PATH,
        NodeKind.POINTS,
        NodeKind.TEXT,
        NodeKind.RASTER,
        NodeKind.XSPLINE,
        NodeKind.BEZIER,
        NodeKind.CURVE,
    }
    # 变换已累积到指令上：旋转视口里的指令不再是单位阵
    assert result.instructions[0].transform != (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def test_null_zero_and_containers_never_reach_ir_from_the_grob_path() -> None:
    """`null` / `zero` / `gtree` / `clip` 不从 grob 路径进 IR（SIL-634 的口径）。

    `null` / `zero` 只有布局语义，`gTree` / `clipPath` 是遍历期容器：摊平之后
    设备只看得到可绘制原语与 `viewport`。
    """
    tree = make_tree()
    grobs = [
        null_grob(),
        zero_grob(),
        g_tree(rect_grob(), gp=gpar(col="#ff0000")),
        clip_path(rect_grob(), width=0.5, height=0.5),
    ]
    ir_scene = scene(grobs, tree).to_ir_scene()
    kinds = {node.kind for node in _walk(ir_scene.root)}
    assert kinds == {NodeKind.VIEWPORT, NodeKind.RECT}


def test_instructions_share_a_viewport_when_transform_and_clip_agree() -> None:
    tree = make_tree()
    result = scene([rect_grob(), circle_grob()], tree)
    ir_scene = result.to_ir_scene()
    assert len(ir_scene.root.children) == 1
    assert [child.kind for child in ir_scene.root.children[0].children] == [
        NodeKind.RECT,
        NodeKind.CIRCLE,
    ]


def test_ir_text_node_carries_width_anchor_and_angle() -> None:
    tree = make_tree(metrics=texts(hello=0.5))
    tree.push(viewport("rot", angle=20))
    node = only(scene(text_grob("hello", rot=10, just=("left", "top")), tree)).to_node()
    assert node.kind is NodeKind.TEXT
    assert node.texts == ("hello",)
    assert node.params["anchor"] == "left"
    assert node.params["baseline"] == "top"
    # 视口旋转在 viewport 节点的 transform 里，text 的 angle 只是局部 rot（SIL-634）
    assert node.params["angle"] == pytest.approx(10.0)
    assert float(node.bufs["width"][0]) == pytest.approx(36.0)


def test_points_size_must_be_a_single_value() -> None:
    tree = make_tree()
    with pytest.raises(GrobError, match="单值"):
        scene(
            points_grob([0.1, 0.2], [0.5, 0.5], size=unit([1.0, 4.0], "char")),
            tree,
        )


def test_rotated_viewport_transform_is_accumulated_and_invertible() -> None:
    tree = make_tree()
    tree.push(viewport("rot", x=0.5, y=0.5, width=0.5, height=0.5, angle=90))
    instruction = only(scene(rect_grob(width=1, height=1), tree))
    a, b, c, d, e, f = instruction.transform
    # 纯旋转（y 向上 90°，翻成页面 y 向下后是 -90°）：对角元为 0，|b| = |c| = 1
    assert a == pytest.approx(0.0) and d == pytest.approx(0.0)
    assert abs(b) == pytest.approx(1.0) and abs(c) == pytest.approx(1.0)
    assert math.isclose(a * d - b * c, 1.0)

    def to_page(x: float, y: float) -> tuple[float, float]:
        return (a * x + c * y + e, b * x + d * y + f)

    # 视口是 0.5 npc = 216 × 144 pt 的盒子，中心在页面 (216, 144)；绕中心转 90° 后
    # 是 144 × 216 的盒子。局部四个角（y 向下：(0,0) 是左上）必须落到它的四个页面上。
    corners = {
        tuple(round(value, 6) for value in to_page(0.0, 0.0)),
        tuple(round(value, 6) for value in to_page(216.0, 0.0)),
        tuple(round(value, 6) for value in to_page(216.0, 144.0)),
        tuple(round(value, 6) for value in to_page(0.0, 144.0)),
    }
    expected = {(144.0, 36.0), (288.0, 36.0), (288.0, 252.0), (144.0, 252.0)}
    assert {tuple(round(v, 6) for v in corner) for corner in corners} == expected
