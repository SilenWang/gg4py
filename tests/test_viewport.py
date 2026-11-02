"""viewport 的行为契约（SIL-596 / M0-4）。

与 R 4.5.3 的逐条对拍在 `tests/test_viewport_r_parity.py`（夹具由
`tools/refs/viewport_ref.R` 生成）；这里守的是**手算**与 R 里没有现成入口的
部分：仿射代数、嵌套旋转的数值、clip 三态、gpar 的两种继承语义、导航语义、
IR 桥接。口径见 `docs/notes/viewport.md`。

数值断言全部独立重算：期望值在测试里用**列向量** 3×3 矩阵（numpy）另写一遍，
和被测算术里的**行向量** 2×3 走不同路径，能抓出合成顺序、旋转符号一类的错误。
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

from ggcore.units import UnitError, unit
from ggcore.viewport import (
    IDENTITY,
    NA,
    Affine,
    Clip,
    Device,
    Gpar,
    ResolvedGpar,
    RotatedClipWarning,
    Viewport,
    ViewportError,
    ViewportTree,
    VpNode,
    VpPath,
    device_loc,
    gpar,
    normalize_just,
    viewport,
    vp_path,
)

DEVICE = Device(6.0, 4.0)
NPC = "npc"


# ---------------------------------------------------------------------------
# 独立的参考实现：列向量 3×3
# ---------------------------------------------------------------------------


def _translate(tx: float, ty: float) -> np.ndarray:
    return np.array([[1.0, 0.0, tx], [0.0, 1.0, ty], [0.0, 0.0, 1.0]])


def _rotate(degrees: float) -> np.ndarray:
    theta = math.radians(degrees)
    cos, sin = math.cos(theta), math.sin(theta)
    return np.array([[cos, -sin, 0.0], [sin, cos, 0.0], [0.0, 0.0, 1.0]])


def _local_matrix(
    x: float, y: float, width: float, height: float, hjust: float, vjust: float, angle: float
) -> np.ndarray:
    """一个视口在父坐标系里的矩阵：先对齐、再旋转、最后定位（列向量口径）。"""
    return _translate(x, y) @ _rotate(angle) @ _translate(-width * hjust, -height * vjust)


def _apply(matrix: np.ndarray, x: float, y: float) -> tuple[float, float]:
    out = matrix @ np.array([x, y, 1.0])
    return (float(out[0]), float(out[1]))


# ---------------------------------------------------------------------------
# 仿射代数
# ---------------------------------------------------------------------------


def test_affine_rotation_is_counter_clockwise_in_y_up_space() -> None:
    quarter = Affine.rotation(90.0)
    assert quarter.map(1.0, 0.0) == pytest.approx((0.0, 1.0), abs=1e-15)
    assert quarter.map(0.0, 1.0) == pytest.approx((-1.0, 0.0), abs=1e-15)


def test_affine_then_applies_self_first() -> None:
    rotate = Affine.rotation(90.0)
    shift = Affine.translation(1.0, 2.0)
    # 先转再移： (1, 0) --旋转--> (0, 1) --平移--> (1, 3)
    assert rotate.then(shift).map(1.0, 0.0) == pytest.approx((1.0, 3.0), abs=1e-15)
    # 反过来： (1, 0) --平移--> (2, 2) --旋转--> (-2, 2)
    assert shift.then(rotate).map(1.0, 0.0) == pytest.approx((-2.0, 2.0), abs=1e-15)


def test_affine_inverse_round_trips() -> None:
    matrix = Affine(a=2.0, b=0.3, c=-0.4, d=1.7, e=3.0, f=-2.0)
    for x, y in ((0.37, -1.21), (0.0, 0.0), (12.5, 9.25)):
        u, v = matrix.map(x, y)
        assert matrix.inverse().map(u, v) == pytest.approx((x, y), abs=1e-12)


def test_affine_inverse_rejects_singular() -> None:
    with pytest.raises(ViewportError, match="singular"):
        Affine(a=1.0, b=2.0, c=2.0, d=4.0).inverse()


def test_affine_matches_column_vector_reference() -> None:
    ours = Affine(a=0.8, b=0.6, c=-0.6, d=0.8, e=1.5, f=-0.5)
    reference = np.array([[0.8, -0.6, 1.5], [0.6, 0.8, -0.5], [0.0, 0.0, 1.0]])
    assert ours.map(0.25, -0.75) == pytest.approx(_apply(reference, 0.25, -0.75), abs=1e-12)


# ---------------------------------------------------------------------------
# 单层变换：手算
# ---------------------------------------------------------------------------


def test_root_viewport_is_identity_and_covers_the_device() -> None:
    tree = ViewportTree(DEVICE)
    root = tree.root
    assert root.name == "ROOT"
    assert root.depth == 0
    assert root.transform.as_tuple() == pytest.approx(IDENTITY.as_tuple(), abs=0.0)
    # R 的 top-level 特例：裁剪框是设备的 -0.5..1.5 倍
    assert root.clip_rect == pytest.approx((-3.0, -2.0, 9.0, 6.0), abs=1e-15)
    assert root.device_loc(unit(0.0, NPC), unit(0.0, NPC)) == pytest.approx((0.0, 0.0))
    assert root.device_loc(unit(1.0, NPC), unit(1.0, NPC)) == pytest.approx((6.0, 4.0))


def test_location_and_size_are_in_parent_units() -> None:
    tree = ViewportTree(DEVICE)
    node = tree.push(
        viewport("cm", x=1, y=2, width=3, height=1, default_units="cm", just=("left", "bottom"))
    )
    cm = 1 / 2.54
    assert node.width_in == pytest.approx(3 * cm, abs=1e-15)
    assert node.height_in == pytest.approx(1 * cm, abs=1e-15)
    assert node.device_loc(unit(0.0, NPC), unit(0.0, NPC)) == pytest.approx(
        (1 * cm, 2 * cm), abs=1e-15
    )
    assert node.device_loc(unit(1.0, NPC), unit(1.0, NPC)) == pytest.approx(
        (4 * cm, 3 * cm), abs=1e-15
    )


def test_justification_moves_the_anchor_corner() -> None:
    tree = ViewportTree(DEVICE)
    box = {"x": 0.5, "y": 0.5, "width": 0.5, "height": 0.5}
    centre = tree.push(viewport("centre", **box, just="centre"))
    tree.pop(1)
    bottom_left = tree.push(viewport("bl", **box, just=("left", "bottom")))
    tree.pop(1)
    top_right = tree.push(viewport("tr", **box, just=("right", "top")))
    assert centre.device_loc(unit(0.0, NPC), unit(0.0, NPC)) == pytest.approx((1.5, 1.0), abs=1e-12)
    assert bottom_left.device_loc(unit(0.0, NPC), unit(0.0, NPC)) == pytest.approx(
        (3.0, 2.0), abs=1e-12
    )
    assert top_right.device_loc(unit(1.0, NPC), unit(1.0, NPC)) == pytest.approx(
        (3.0, 2.0), abs=1e-12
    )


def test_native_scale_and_reversed_scale() -> None:
    tree = ViewportTree(DEVICE)
    node = tree.push(
        viewport(
            "native",
            x=0.0,
            y=0.0,
            width=1.0,
            height=1.0,
            just=("left", "bottom"),
            xscale=(10.0, 0.0),
            yscale=(5.0, 1.0),
        )
    )
    # 反向 xscale：native 10 在左边缘，native 0 在右边缘
    assert node.device_loc(unit(10.0, "native"), unit(5.0, "native")) == pytest.approx(
        (0.0, 0.0), abs=1e-12
    )
    assert node.device_loc(unit(0.0, "native"), unit(1.0, "native")) == pytest.approx(
        (6.0, 4.0), abs=1e-12
    )
    assert node.device_loc(unit(5.0, "native"), unit(3.0, "native")) == pytest.approx(
        (3.0, 2.0), abs=1e-12
    )


def test_units_are_converted_with_the_parent_gpar() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("ps10", gp={"fontsize": 10}))
    lines_node = tree.push(
        viewport("two-lines", width=unit(2.0, "lines"), height=unit(2.0, "lines"))
    )
    tree.pop(2)
    tree.push(viewport("ps20", gp={"fontsize": 20}))
    bigger = tree.push(viewport("two-lines", width=unit(2.0, "lines"), height=unit(2.0, "lines")))
    # 1 line = ps * cex * lineheight / 72 英寸
    assert lines_node.width_in == pytest.approx(2 * 10 * 1.2 / 72, abs=1e-15)
    assert bigger.width_in == pytest.approx(2 * 20 * 1.2 / 72, abs=1e-15)
    assert bigger.width_in == pytest.approx(2 * lines_node.width_in, abs=1e-15)


def test_units_see_the_temporary_gpar_of_a_g_tree() -> None:
    """gTree 临时 gp 下 push 子视口：`lines` 几何用**那时**的 gpar。

    对等 R 的 `gTree(gp = gpar(fontsize = 20), childrenvp = viewport(width =
    unit(2, "lines")))`：`preDraw.gTree()` 先 `pushvpgp()`（把 gTree 的 `gp`
    设进当前 gpar），再 `pushViewport(childrenvp)`；`calcViewportTransform()`
    对子视口取 `viewportParentGPar(child)`，即 push 那一刻的 gpar。R 4.5.3
    真 gTree 实测 `width = 0.6667 in`；若改用父视口自己的 gpar（ps12）会得
    `0.4`，而且**不报错**——所以这条路径必须单独钉住。
    """
    tree = ViewportTree(DEVICE)
    parent = tree.push(viewport("parent", gp=gpar(fontsize=12)))
    with tree.temporary_gpar(gpar(fontsize=20)):
        assert tree.gpar.fontsize == 20
        child = tree.push(
            viewport("childrenvp", width=unit(2.0, "lines"), height=unit(2.0, "lines"))
        )
    # push 时捕获的临时 gpar；父视口自己的 gpar 没变
    assert child.parent_gpar.fontsize == 20
    assert parent.gpar.fontsize == 12
    # 1 line = ps * cex * lineheight / 72 英寸
    assert child.width_in == pytest.approx(2 * 20 * 1.2 / 72, abs=1e-15)  # 0.6667
    assert child.height_in == pytest.approx(2 * 20 * 1.2 / 72, abs=1e-15)
    assert child.width_in != pytest.approx(2 * 12 * 1.2 / 72, abs=1e-9)
    # 尺寸/scale 仍取父视口：子视口居中在父视口中心（0.5 npc, 0.5 npc）
    assert child.device_loc(unit(0.5, NPC), unit(0.5, NPC)) == pytest.approx((3.0, 2.0), abs=1e-12)


def test_temporary_gpar_restores_the_previous_gpar() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("outer", gp=gpar(cex=0.5, col="red")))
    with tree.temporary_gpar(gpar(cex=0.5)):
        # R 的 set.gpar() 累积 cex：0.5 * 0.5
        assert tree.gpar.cex == pytest.approx(0.25)
        assert tree.gpar.col == "red"
    assert tree.gpar.cex == pytest.approx(0.5)
    assert tree.gpar.col == "red"
    with pytest.raises(ViewportError, match="gp"):
        with tree.temporary_gpar("bold"):  # type: ignore[arg-type]
            pass  # pragma: no cover - 进入上下文时就该报错


def test_temporary_gpar_restores_after_an_exception() -> None:
    """块内抛异常也要复原（退出路径只有 `finally`，没有别的收尾）。

    R 那边 `set.gpar()` 的恢复挂在 `on.exit()` 上，异常同样会走到；这条钉住
    gg4py 的等价保证，免得以后把 `finally` 改成正常退出的分支。
    """
    tree = ViewportTree(DEVICE)
    tree.push(viewport("outer", gp=gpar(cex=0.5, col="red")))
    before = tree.gpar
    with pytest.raises(RuntimeError, match="boom"):
        with tree.temporary_gpar(gpar(cex=0.5, fontsize=20)):
            assert tree.gpar.cex == pytest.approx(0.25)
            assert tree.gpar.fontsize == pytest.approx(20.0)
            raise RuntimeError("boom")
    assert tree.gpar == before
    assert tree.gpar.cex == pytest.approx(0.5)
    assert tree.gpar.col == "red"
    assert tree.gpar.fontsize == pytest.approx(12.0)


def test_temporary_gpar_exception_leaves_the_child_viewport_on_the_stack() -> None:
    """块内 push 了子视口再抛异常：gpar 复原，视口栈**不**替调用方 pop。

    `finally` 只管 gpar。R 里 `childrenvp` 的 `upViewport(depth(childrenvp))`
    是 `preDraw.gTree()` 自己的责任，不在这条恢复路径上；异常退出后当前视口
    仍停在 push 进去的子视口，调用方（M0-6 的绘制循环）必须先自己 up 回来。
    """
    tree = ViewportTree(DEVICE)
    gtree = tree.push(viewport("gtree"))
    before = tree.gpar
    with pytest.raises(RuntimeError, match="boom"):
        with tree.temporary_gpar(gpar(cex=0.5)):
            child = tree.push(viewport("children"))
            raise RuntimeError("boom")
    assert tree.gpar == before
    assert tree.gpar.cex == pytest.approx(1.0)
    assert tree.current is child
    assert tree.depth() == gtree.depth + 1


# ---------------------------------------------------------------------------
# 旋转：数值断言（接受判据：与手算差 < 1e-9）
# ---------------------------------------------------------------------------


def test_rotated_viewport_device_location_matches_hand_calculation() -> None:
    device = Device(8.0, 5.0)
    tree = ViewportTree(device)
    spec = viewport(
        "rotated",
        x=0.3,
        y=0.6,
        width=0.4,
        height=0.5,
        just="centre",
        angle=37.5,
    )
    node = tree.push(spec)

    width_in = 0.4 * 8.0
    height_in = 0.5 * 5.0
    anchor_x = 0.3 * 8.0
    anchor_y = 0.6 * 5.0
    for px, py in ((0.25, 0.75), (0.0, 0.0), (1.0, 1.0), (0.5, 0.5)):
        local_x = px * width_in - width_in / 2
        local_y = py * height_in - height_in / 2
        # 手算：复数乘法就是绕原点旋转
        rotated = complex(local_x, local_y) * complex(
            math.cos(math.radians(37.5)), math.sin(math.radians(37.5))
        )
        expected = (rotated.real + anchor_x, rotated.imag + anchor_y)
        assert node.device_loc(unit(px, NPC), unit(py, NPC)) == pytest.approx(expected, abs=1e-9)


def test_just_and_angle_combine_so_rotation_is_about_the_anchor() -> None:
    tree = ViewportTree(DEVICE)
    node = tree.push(
        viewport(
            "anchor",
            x=1.0,
            y=1.0,
            width=2.0,
            height=1.0,
            default_units="inches",
            just=("left", "bottom"),
            angle=30.0,
        )
    )
    # 左下角是对齐点：旋不旋转它都停在 (1, 1)
    assert node.device_loc(unit(0.0, NPC), unit(0.0, NPC)) == pytest.approx((1.0, 1.0), abs=1e-12)
    reference = _local_matrix(1.0, 1.0, 2.0, 1.0, 0.0, 0.0, 30.0)
    assert node.device_loc(unit(1.0, NPC), unit(1.0, NPC)) == pytest.approx(
        _apply(reference, 2.0, 1.0), abs=1e-12
    )


def test_three_nested_viewports_with_stacked_rotation() -> None:
    tree = ViewportTree(DEVICE)

    def push(
        name: str, x: float, y: float, w: float, h: float, angle: float, just: str = "centre"
    ) -> VpNode:
        return tree.push(viewport(name, x=x, y=y, width=w, height=h, just=just, angle=angle))

    first = push("a", 0.2, 0.2, 0.6, 0.6, 15.0)
    second = push("b", 0.5, 0.5, 0.8, 0.5, 25.0)
    third = push("c", 0.5, 0.5, 1.0, 1.0, 50.0, just="centre")

    assert (first.rotation, second.rotation, third.rotation) == (15.0, 40.0, 90.0)

    # 独立性检验：三级都按列向量矩阵重新合成一遍
    abs_a = _local_matrix(0.2 * 6, 0.2 * 4, 0.6 * 6, 0.6 * 4, 0.5, 0.5, 15.0)
    abs_b = abs_a @ _local_matrix(
        0.5 * first.width_in,
        0.5 * first.height_in,
        0.8 * first.width_in,
        0.5 * first.height_in,
        0.5,
        0.5,
        25.0,
    )
    abs_c = abs_b @ _local_matrix(
        0.5 * second.width_in,
        0.5 * second.height_in,
        second.width_in,
        second.height_in,
        0.5,
        0.5,
        50.0,
    )

    for px, py in ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.25, 0.8)):
        local = (px * third.width_in, py * third.height_in)
        expected = _apply(abs_c, *local)
        assert third.device_loc(unit(px, NPC), unit(py, NPC)) == pytest.approx(expected, abs=1e-9)
    # 第三级的坐标轴确实转了 90°：本地 +x 指向设备 +y
    origin = third.device_loc(unit(0.0, NPC), unit(0.0, NPC))
    ahead = third.device_loc(unit(1.0, NPC), unit(0.0, NPC))
    assert (ahead[0] - origin[0]) == pytest.approx(0.0, abs=1e-9)
    assert (ahead[1] - origin[1]) == pytest.approx(third.width_in, abs=1e-9)


def test_reduced_angle_stays_negative() -> None:
    tree = ViewportTree(DEVICE)
    node = tree.push(viewport("ccw", width=0.5, height=0.5, angle=-90.0))
    assert node.rotation == -90.0
    origin = node.device_loc(unit(0.0, NPC), unit(0.0, NPC))
    ahead = node.device_loc(unit(1.0, NPC), unit(0.0, NPC))
    assert (ahead[1] - origin[1]) == pytest.approx(-node.width_in, abs=1e-9)


# ---------------------------------------------------------------------------
# 裁剪：on / off / inherit
# ---------------------------------------------------------------------------


def test_clip_defaults_to_inherit_like_r_4_5() -> None:
    assert viewport("v").clip is Clip.INHERIT
    assert set(Clip.__members__) == {"ON", "OFF", "INHERIT"}


def test_clip_on_uses_the_viewport_box() -> None:
    tree = ViewportTree(DEVICE)
    node = tree.push(
        viewport("on", x=0.25, y=0.25, width=0.5, height=0.5, just=("left", "bottom"), clip="on")
    )
    assert node.clip_rect == pytest.approx((1.5, 1.0, 4.5, 3.0), abs=1e-12)


def test_clip_off_uses_the_whole_device_with_margin() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("parent", x=0.25, y=0.25, width=0.5, height=0.5, clip="on"))
    node = tree.push(viewport("off", x=0.5, y=0.5, width=0.5, height=0.5, clip="off"))
    assert node.clip_rect == pytest.approx((-3.0, -2.0, 9.0, 6.0), abs=1e-12)


def test_clip_inherit_keeps_the_parent_box() -> None:
    tree = ViewportTree(DEVICE)
    parent = tree.push(viewport("parent", x=0.25, y=0.25, width=0.5, height=0.5, clip="on"))
    child = tree.push(viewport("child", x=0.5, y=0.5, width=2.0, height=2.0, clip="inherit"))
    assert child.clip_rect == parent.clip_rect


def test_clip_on_falls_back_to_parent_when_rotation_cannot_be_axis_aligned() -> None:
    tree = ViewportTree(DEVICE)
    parent = tree.push(viewport("parent", x=0.25, y=0.25, width=0.5, height=0.5, clip="on"))
    with pytest.warns(RotatedClipWarning, match="cannot clip to rotated viewport"):
        rotated = tree.push(
            viewport("rot", x=0.5, y=0.5, width=1.0, height=1.0, angle=45.0, clip="on")
        )
    assert rotated.clip_rect == parent.clip_rect
    # R 连 180° 都不算可裁剪（角点顺序会翻转），同样退化成继承
    tree.pop(1)
    with pytest.warns(RotatedClipWarning):
        flipped = tree.push(
            viewport("flip", x=0.5, y=0.5, width=1.0, height=1.0, angle=180.0, clip="on")
        )
    assert flipped.clip_rect == parent.clip_rect


def test_clip_on_allows_ninety_and_two_seventy() -> None:
    tree = ViewportTree(DEVICE)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RotatedClipWarning)
        quarter = tree.push(
            viewport("q", x=0.5, y=0.5, width=0.5, height=0.5, angle=90.0, clip="on")
        )
    # 视口 3×2 in、中心 (3, 2)，绕中心转 90°： (0,0) → (4.0, 0.5)，(3,2) → (2.0, 3.5)
    assert quarter.clip_rect == pytest.approx((4.0, 0.5, 2.0, 3.5), abs=1e-12)
    # R 存的是未规范化的四元组（角点顺序可能翻转），渲染端要自己排序
    assert quarter.clip_box == pytest.approx((2.0, 0.5, 4.0, 3.5), abs=1e-12)
    tree.pop(1)
    tree.push(viewport("r", x=0.5, y=0.5, width=0.5, height=0.5, angle=270.0, clip="on"))
    tree.pop(1)
    tree.push(viewport("full", x=0.5, y=0.5, width=0.5, height=0.5, angle=360.0, clip="on"))


def test_cumulative_rotation_decides_clip_not_own_angle() -> None:
    tree = ViewportTree(DEVICE)
    # 30 + 30 = 60：累计角不是 90 的倍数 → 警告并继承
    tree.push(viewport("base", x=0.5, y=0.5, width=0.5, height=0.5, angle=30.0))
    with pytest.warns(RotatedClipWarning):
        tree.push(viewport("child", x=0.5, y=0.5, width=1.0, height=1.0, angle=30.0, clip="on"))
    # 45 + 45 = 90：自己两级都不是轴对齐，但累计角是 → 可以裁剪，不报警
    tree.pop(2)
    tree.push(viewport("other", x=0.5, y=0.5, width=0.5, height=0.5, angle=45.0))
    with warnings.catch_warnings():
        warnings.simplefilter("error", RotatedClipWarning)
        tree.push(viewport("grand", x=0.5, y=0.5, width=1.0, height=1.0, angle=45.0, clip="on"))


# ---------------------------------------------------------------------------
# gpar 继承
# ---------------------------------------------------------------------------


def test_unset_gpar_fields_do_not_override() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("parent", gp=gpar(col="red", fontsize=20, lwd=2)))
    child = tree.push(viewport("child", gp=gpar(lwd=3)))
    assert child.gpar.col == "red"
    assert child.gpar.fontsize == 20
    assert child.gpar.lwd == 3
    assert child.gpar.lineend == "round"  # 缺省值仍在
    assert child.parent_gpar.col == "red"


def test_explicit_none_clears_the_inherited_field() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("parent", gp=gpar(col="red", fill="blue", fontsize=20)))
    inheriting = tree.push(viewport("inherits"))
    cleared = tree.push(viewport("clears", gp=Gpar(col=None, fill=None, fontsize=None)))
    assert inheriting.gpar.col == "red"
    assert inheriting.gpar.fill == "blue"
    assert cleared.gpar.col == "black"  # 回到 grid 缺省
    assert cleared.gpar.fill == "transparent"
    assert cleared.gpar.fontsize == 12.0


def test_empty_delta_is_inherit_and_unset_is_not_none() -> None:
    delta = Gpar()
    assert delta.as_dict() == {}
    assert Gpar(col=None).as_dict() == {"col": None}
    base = ResolvedGpar.defaults().merge(gpar(col="red"))
    assert base.merge(Gpar()) == base
    assert base.merge(Gpar(col=None)).col == "black"


def test_cex_alpha_lex_are_cumulative() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("a", gp=gpar(cex=0.5, alpha=0.5, lex=2)))
    child = tree.push(viewport("b", gp=gpar(cex=0.5, alpha=0.2, lex=3)))
    assert child.gpar.cex == pytest.approx(0.25)
    assert child.gpar.alpha == pytest.approx(0.1)
    assert child.gpar.lex == pytest.approx(6.0)
    # 显式清空不参与乘法：直接回 1.0
    cleared = tree.push(viewport("c", gp=Gpar(cex=None, alpha=None)))
    assert cleared.gpar.cex == 1.0
    assert cleared.gpar.alpha == 1.0


def test_gpar_is_restored_on_pop_and_replaced_on_down() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("outer", gp=gpar(col="red", cex=0.5)))
    tree.push(viewport("inner", gp=gpar(lwd=3)))
    assert tree.gpar.lwd == 3
    tree.up(1)
    assert tree.gpar.lwd == 1  # 回到 outer 的解析值
    assert tree.gpar.col == "red"
    tree.down("inner")
    assert tree.gpar.lwd == 3
    assert tree.gpar.cex == 0.5  # down 用目标视口的解析值，不累积
    tree.pop(2)
    assert tree.gpar == ResolvedGpar.defaults()


def test_na_is_kept_apart_from_none() -> None:
    """`NA`（不画）与 `None`（清空回缺省）是两件事，解析后必须还分得清。"""
    base = ResolvedGpar.defaults().merge(gpar(col="red"))
    assert base.merge(Gpar(col=NA)).col is NA
    assert base.merge(Gpar(col=None)).col == "black"
    assert base.merge(Gpar(col=NA)).fill == "transparent"
    with pytest.raises(TypeError):
        bool(NA)


def test_lty_accepts_r_codes_and_style_names() -> None:
    for value in (0, 1, 2, 6, "dashed", "blank", "44", (1.0, 2.0), NA):
        assert Gpar(lty=value).lty is value
    for value in (-1, 7, True, 2.5):
        with pytest.raises(ViewportError, match="lty"):
            Gpar(lty=value)


def test_gpar_validation() -> None:
    with pytest.raises(ViewportError, match="alpha"):
        gpar(alpha=1.5)
    with pytest.raises(ViewportError, match="linemitre"):
        gpar(linemitre=0.5)
    with pytest.raises(ViewportError, match="不认识"):
        gpar(colour="red")
    with pytest.raises(ViewportError, match="lineend"):
        gpar(lineend="pointy")
    with pytest.raises(ViewportError, match="font"):
        gpar(font=9)
    with pytest.raises(ViewportError, match="必须是颜色"):
        gpar(col=42)


# ---------------------------------------------------------------------------
# 导航：push / pop / up / down / seek
# ---------------------------------------------------------------------------


def test_push_pop_track_path_and_depth() -> None:
    tree = ViewportTree(DEVICE)
    assert tree.vp_path() is None
    assert tree.depth() == 0
    tree.push(viewport("a"))
    tree.push(viewport("b"))
    assert str(tree.vp_path()) == "a::b"
    assert tree.depth() == 2
    assert list(tree.current.path.names) == ["a", "b"]
    tree.pop(1)
    assert str(tree.vp_path()) == "a"
    tree.pop(0)
    assert tree.vp_path() is None
    with pytest.raises(ViewportError, match="top-level"):
        tree.pop(1)


def test_push_returns_nodes_and_reports_multiple() -> None:
    tree = ViewportTree(DEVICE)
    node = tree.push(viewport("a"))
    assert node.name == "a"
    pair = tree.push(viewport("b"), viewport("c"))
    assert isinstance(pair, tuple) and [item.name for item in pair] == ["b", "c"]
    assert str(tree.vp_path()) == "a::b::c"


def test_up_keeps_the_tree_and_returns_the_path() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("a"))
    tree.push(viewport("b"))
    up = tree.up(1)
    assert up is not None and str(up) == "b"
    assert tree.vp_path().names == ("a",)
    tree.down("b")
    assert str(tree.vp_path()) == "a::b"
    assert tree.up(0) is not None
    assert tree.vp_path() is None
    # 已经回到根，再往上就是错误
    with pytest.raises(ViewportError, match="top-level"):
        tree.up(1)


def test_down_finds_descendants_by_suffix_path() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("a"))
    tree.push(viewport("b"))
    tree.push(viewport("c"))
    tree.up(0)
    assert tree.down("c") == 3
    tree.up(0)
    assert tree.down("b::c") == 3
    tree.up(0)
    assert tree.down(vp_path("a", "b", "c")) == 3
    tree.up(0)
    with pytest.raises(ViewportError, match="was not found"):
        tree.down("nope")


def test_down_strict_only_looks_at_direct_children() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("a"))
    tree.push(viewport("b"))
    tree.up(0)
    with pytest.raises(ViewportError, match="was not found"):
        tree.down("b", strict=True)
    assert tree.down("a", strict=True) == 1


def test_non_strict_path_matching_is_segment_exact_where_r_uses_a_regex() -> None:
    """非 strict 匹配按段精确（比 R 更严），口径见 `docs/notes/viewport.md` §6。

    R 是 `grepl(paste0(path, "$"), pathsofar)`（`R/grid.R:119` 的 `pathMatch()`）：
    最后一段按名字精确查，前面的部分当**正则**、只锚定末尾；所以 `xxa/b` 树里
    R 的 `down("a::b")` 能命中（`"a::b$"` 匹配 `"xxa::b"`）。gg4py 在段边界上
    比较，不跨段命中。两条都钉住：别让行为悄悄变成 R 的，也别把文档再写反。
    """
    tree = ViewportTree(DEVICE)
    tree.push(viewport("xxa"))
    tree.push(viewport("b"))
    tree.up(0)
    assert tree.find("a::b") is None
    with pytest.raises(ViewportError, match="was not found"):
        tree.down("a::b")
    assert tree.down("xxa::b") == 2


def test_down_returns_depth_and_seek_starts_from_the_root() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("a"))
    tree.push(viewport("b"))
    tree.push(viewport("c"))
    tree.up(0)
    tree.push(viewport("d"))
    tree.up(0)
    assert tree.down("a::b") == 2
    assert tree.seek("c") == 3
    with pytest.raises(ViewportError):
        tree.down("")


def test_search_order_is_sorted_by_name_like_r_environments() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("b"))
    tree.push(viewport("x", gp=gpar(col="blue")))
    tree.up(1)
    tree.push(viewport("a"))
    tree.push(viewport("x", gp=gpar(col="red")))
    tree.up(2)
    node, depth = tree.find("x")
    assert depth == 2
    assert node.parent.name == "a"  # 'a' 排在 'b' 前面
    assert node.gpar.col == "red"


def test_pop_removes_the_child_from_the_parent() -> None:
    tree = ViewportTree(DEVICE)
    first = tree.push(viewport("dup", gp=gpar(col="red")))
    tree.pop(1)
    second = tree.push(viewport("dup", gp=gpar(col="blue")))
    assert list(tree.root.children) == ["dup"]
    assert tree.root.children["dup"] is second
    assert first is not second
    assert second.gpar.col == "blue"


def test_viewport_specs_can_be_pushed_more_than_once() -> None:
    tree = ViewportTree(DEVICE)
    spec = viewport("reused", width=0.5, height=0.5)
    first = tree.push(spec)
    tree.pop(1)
    second = tree.push(spec)
    assert first is not second
    assert first.spec is second.spec
    assert first.parent is second.parent
    assert first.transform == second.transform


def test_vp_path_parsing() -> None:
    assert VpPath.parse("a").names == ("a",)
    assert VpPath.parse("a::b::c").names == ("a", "b", "c")
    assert vp_path("a", vp_path("b", "c")).names == ("a", "b", "c")
    assert str(vp_path("a::b")) == "a::b"
    assert len(vp_path("a::b")) == 2
    with pytest.raises(ViewportError):
        VpPath(())
    with pytest.raises(ViewportError):
        VpPath.parse(3)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 写 IR
# ---------------------------------------------------------------------------


def test_ir_transform_of_the_root_is_identity() -> None:
    tree = ViewportTree(DEVICE)
    assert tree.root.ir_transform().as_tuple() == pytest.approx(IDENTITY.as_tuple(), abs=0.0)


def test_ir_transform_maps_local_points_into_the_parent() -> None:
    tree = ViewportTree(DEVICE)
    node = tree.push(
        viewport("box", x=0.25, y=0.25, width=0.5, height=0.5, just=("left", "bottom"))
    )
    matrix = node.ir_transform()
    # 子坐标 (0, 0) 是视口左上角：父坐标里 y 向下，所以要从父高度减去
    assert matrix.map(0.0, 0.0) == pytest.approx((1.5 * 72, (4 - 1 - 2) * 72), abs=1e-9)
    # 子坐标 (w*72, h*72) 是右下角
    assert matrix.map(node.width_in * 72, node.height_in * 72) == pytest.approx(
        (4.5 * 72, (4 - 1) * 72), abs=1e-9
    )


def _expected_ir_loc(node, px: float, py: float) -> tuple[float, float]:
    """独立路径：子坐标（pt，y 向下）→ 本地英寸 → 设备英寸 → 父/设备 pt（y 向下）。"""
    device_x, device_y = node.device_loc(
        unit(px / 72.0, "inches"), unit(node.height_in - py / 72.0, "inches")
    )
    return (device_x * 72.0, (node.device.height_in - device_y) * 72.0)


def test_ir_transform_carries_rotation_into_the_y_down_frame() -> None:
    tree = ViewportTree(DEVICE)
    rotated = tree.push(viewport("rot", width=0.5, height=0.5, angle=90.0))
    for px, py in ((0.0, 0.0), (rotated.width_in * 72, 0.0), (0.0, rotated.height_in * 72)):
        assert rotated.ir_transform().map(px, py) == pytest.approx(
            _expected_ir_loc(rotated, px, py), abs=1e-9
        )
    # 旋转进了 y 向下的坐标系：本地 +x 指向设备 -y（而不是 +y）
    origin = rotated.ir_transform().map(0.0, 0.0)
    ahead = rotated.ir_transform().map(72.0, 0.0)
    assert ahead[0] == pytest.approx(origin[0], abs=1e-9)
    assert ahead[1] - origin[1] == pytest.approx(-72.0, abs=1e-9)


def test_ir_transform_composes_across_nesting() -> None:
    tree = ViewportTree(DEVICE)
    tree.push(viewport("outer", width=0.6, height=0.4, angle=20.0))
    inner = tree.push(viewport("inner", x=0.3, y=0.7, width=0.4, height=0.3, angle=-15.0))
    # 子 → 父；父 → 根 再拼起来要和“子 → 根”一致
    to_parent = inner.ir_transform()
    parent_to_root = inner.parent.ir_transform()
    px, py = 12.0, 34.0
    chained = parent_to_root.map(*to_parent.map(px, py))
    assert chained == pytest.approx(_expected_ir_loc(inner, px, py), abs=1e-9)


def test_ir_clip_rect_is_page_space_pt() -> None:
    """`clip_rect` 是**页面绝对坐标**（pt、y 向下），不是子坐标。

    IR v0.2 的口径（`docs/notes/ir.md` §4）：M0-8 合成页面变换后在页面空间裁剪。
    反例：6×4 in 设备、视口 `x=y=0.25`、`w=h=0.5`、`clip="on"`，本地帧 216×144 pt。
    页面坐标是 `(108, 72, 324, 216)`；若按子坐标解释，交集只有
    `(108..216, 72..144)`，**右边和下边会被误裁**。
    """
    tree = ViewportTree(DEVICE)
    node = tree.push(
        viewport("clip", x=0.25, y=0.25, width=0.5, height=0.5, just=("left", "bottom"), clip="on")
    )
    rect = node.ir_clip_rect()
    # 页面 6×4 in = 432×288 pt：视口左上角 (0.25*432, 0.25*288)，本地帧 216×144 pt
    assert rect == pytest.approx((0.25 * 432.0, 0.25 * 288.0, 0.75 * 432.0, 0.75 * 288.0), abs=1e-9)
    assert rect == pytest.approx((108.0, 72.0, 324.0, 216.0), abs=1e-9)
    assert rect[2] - rect[0] == pytest.approx(node.width_in * 72.0)  # 216
    assert rect[3] - rect[1] == pytest.approx(node.height_in * 72.0)  # 144
    # 和设备英寸里的生效裁剪框一致（只是翻了 y、换了单位）
    x0, y0 = node.device_loc(unit(0.0, NPC), unit(0.0, NPC))
    x1, y1 = node.device_loc(unit(1.0, NPC), unit(1.0, NPC))
    assert rect == pytest.approx(
        (x0 * 72.0, (DEVICE.height_in - y1) * 72.0, x1 * 72.0, (DEVICE.height_in - y0) * 72.0),
        abs=1e-9,
    )

    # 页面框 ∩ 本地帧 = (108, 72, 216, 144)（上边、左边重合，右边、下边被切掉）：
    # 这个点在视口里，但会被它裁掉
    def inside(box: tuple[float, float, float, float], x: float, y: float) -> bool:
        return box[0] <= x <= box[2] and box[1] <= y <= box[3]

    child_space = (108.0, 72.0, 216.0, 144.0)
    assert inside(rect, 300.0, 200.0)
    assert not inside(child_space, 300.0, 200.0)


def test_ir_clip_rect_is_page_space_under_a_non_root_parent() -> None:
    """父视口不是 `ROOT` 时，`clip_rect` 仍是**页面**坐标，不是父坐标。

    上一个用例的父视口就是铺满整页的 `ROOT`，页面坐标与父坐标数值相同，
    `ir_clip_rect()` 误返回父坐标也能绿。这里让父视口只占页面 2×1.5 in（6×4 in
    设备：平移 1 in、npc 帧缩到 1/3 × 3/8），子视口再往里落一段，两个口径就分开了。

    M0-8 的做法是“自下而上合成页面变换后在页面空间裁剪”（`docs/notes/ir.md` §4），
    所以页面坐标还必须等于子 → 父 → 页面合成后框住的两个角。
    """
    tree = ViewportTree(DEVICE)  # 6×4 in = 432×288 pt
    parent = tree.push(
        viewport(
            "panel",
            x=unit(1.0, "inches"),
            y=unit(1.0, "inches"),
            width=unit(2.0, "inches"),
            height=unit(1.5, "inches"),
            just=("left", "bottom"),
            clip="on",
        )
    )
    node = tree.push(
        viewport("clip", x=0.25, y=0.25, width=0.5, height=0.5, just=("left", "bottom"), clip="on")
    )
    # 父视口：设备英寸 x 1..3、y 1..2.5 → 页面 pt (72, 108, 216, 216)
    assert parent.ir_clip_rect() == pytest.approx((72.0, 108.0, 216.0, 216.0), abs=1e-9)
    # 子视口：父帧 1/3 × 3/8 缩放后落在 x 1.5..2.5、y 1.375..2.125 in
    assert (node.width_in, node.height_in) == pytest.approx((1.0, 0.75), abs=1e-12)
    rect = node.ir_clip_rect()
    assert rect == pytest.approx((108.0, 135.0, 180.0, 189.0), abs=1e-9)
    # 返回父坐标会得到 (108-72, 135-108, 180-72, 189-108)，框被挪到父视口左上角
    assert rect != pytest.approx((36.0, 27.0, 108.0, 81.0), abs=1e-9)

    # 与 M0-8 的消费方式一致：子 → 父 → 页面，两个对角点合成后就是页面框
    to_parent = node.ir_transform()
    to_page = node.parent.ir_transform()
    corners = [
        to_page.map(*to_parent.map(px, py))
        for px, py in ((0.0, 0.0), (node.width_in * 72.0, node.height_in * 72.0))
    ]
    xs = sorted(corner[0] for corner in corners)
    ys = sorted(corner[1] for corner in corners)
    assert rect == pytest.approx((xs[0], ys[0], xs[1], ys[1]), abs=1e-9)


# ---------------------------------------------------------------------------
# 设备尺寸变化 / 批量换算 / 校验
# ---------------------------------------------------------------------------


def test_resize_recomputes_transforms() -> None:
    tree = ViewportTree(DEVICE)
    node = tree.push(viewport("half", x=0.0, y=0.0, width=0.5, height=0.5, just=("left", "bottom")))
    assert node.device_loc(unit(1.0, NPC), unit(1.0, NPC)) == pytest.approx((3.0, 2.0), abs=1e-12)
    tree.resize(Device(4.0, 8.0))
    assert node.device_loc(unit(1.0, NPC), unit(1.0, NPC)) == pytest.approx((2.0, 4.0), abs=1e-12)
    assert node.device.height_in == 8.0


def test_device_points_vectorises_and_recycles() -> None:
    tree = ViewportTree(DEVICE)
    node = tree.push(viewport("box", x=0.0, y=0.0, width=1.0, height=1.0, just=("left", "bottom")))
    points = node.device_points(unit([0.0, 0.5, 1.0], NPC), unit(0.0, NPC))
    assert points.shape == (3, 2)
    assert points[:, 1] == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)
    assert points[:, 0] == pytest.approx([0.0, 3.0, 6.0], abs=1e-12)
    single = device_loc(tree, unit(0.5, NPC), unit(0.5, NPC))
    assert single.shape == (1, 2)


def test_convert_uses_the_viewport_context() -> None:
    tree = ViewportTree(DEVICE)
    node = tree.push(viewport("box", width=0.5, height=0.5, xscale=(0.0, 100.0)))
    assert node.convert(unit(100.0, "native"), "npc") == pytest.approx([1.0], abs=1e-12)
    assert node.convert(unit(1.0, "npc"), "inches", measure="dimension") == pytest.approx(
        [3.0], abs=1e-12
    )
    with pytest.raises(UnitError):
        node.convert(unit(1.0, "npc"), "snpc")


def test_scale_accepts_numpy_and_other_non_sequence_iterables() -> None:
    """`xscale` / `yscale` 收任意非字符串可迭代对象：panel 数据范围常是 numpy。"""
    node = viewport("panel", xscale=np.array([0.0, 10.0]), yscale=np.linspace(1.0, 5.0, 2))
    assert node.xscale == (0.0, 10.0)
    assert node.yscale == pytest.approx((1.0, 5.0))
    pushed = ViewportTree(DEVICE).push(node)
    assert pushed.device_loc(unit(10.0, "native"), unit(5.0, "native")) == pytest.approx(
        (6.0, 4.0), abs=1e-12
    )
    for bad in (np.array([[0.0, 1.0]]), np.array(1.0), 3.0, "ab"):
        with pytest.raises(ViewportError, match="xscale"):
            viewport("bad", xscale=bad)


def test_root_scale_is_device_inches() -> None:
    """根视口的 `xscale` / `yscale` 定死为设备英寸（§9 差异表）。"""
    tree = ViewportTree(DEVICE)
    assert tree.root.xscale == pytest.approx((0.0, 6.0))
    assert tree.root.yscale == pytest.approx((0.0, 4.0))
    assert tree.current.device_loc(unit(6.0, "native"), unit(4.0, "native")) == pytest.approx(
        (6.0, 4.0), abs=1e-12
    )


def test_root_native_units_are_device_inches() -> None:
    """M0 交接的遗留口径：根级 `native` = 设备原生单位 = 英寸（M1-5 钉住）。

    R 的根视口 `xscale`/`yscale` 是设备原生单位（pdf 下 0..504 点）；本模块的
    `Device` 以英寸计量，所以 `unit(1, "native")` 在根视口上就是 1 英寸。
    子视口不改语义：仍按自己的 `xscale` / `yscale` 换算。
    """
    tree = ViewportTree(DEVICE)  # 6 × 4 in
    root = tree.root
    assert root.convert(unit(1.0, "native"), "inches", axis="x") == pytest.approx([1.0])
    assert root.convert(unit(1.0, "native"), "inches", axis="y") == pytest.approx([1.0])
    # 位置与尺寸都成立：1 native 的位置是 1in，1 native 的宽度也是 1in。
    assert root.device_loc(unit(1.0, "native"), unit(1.0, "native")) == pytest.approx(
        (1.0, 1.0), abs=1e-12
    )
    assert root.device_loc(unit(6.0, "native"), unit(4.0, "native")) == pytest.approx(
        (6.0, 4.0), abs=1e-12
    )
    assert root.convert(unit(1.0, "native"), "inches", axis="x", measure="dimension") == (
        pytest.approx([1.0])
    )
    # 子视口：xscale 0..10 铺满 6in → 1 native = 0.6in（与 R 的口径一致）
    child = tree.push(
        viewport(
            "panel",
            width=unit(1.0, "npc"),
            height=unit(1.0, "npc"),
            just=("left", "bottom"),
            xscale=(0.0, 10.0),
            yscale=(0.0, 5.0),
        )
    )
    assert child.convert(unit(1.0, "native"), "inches", axis="x") == pytest.approx([0.6])
    assert child.convert(unit(10.0, "native"), "inches", axis="x") == pytest.approx([6.0])
    assert child.convert(unit(1.0, "native"), "inches", axis="y") == pytest.approx([0.8])


def test_viewport_validation() -> None:
    with pytest.raises(ViewportError, match="xscale"):
        viewport("bad", xscale=(1.0, 1.0))
    with pytest.raises(ViewportError, match="xscale"):
        viewport("bad", xscale=(0.0, 1.0, 2.0))
    with pytest.raises(ViewportError, match="clip"):
        viewport("bad", clip=True)
    with pytest.raises(ViewportError, match="clip"):
        viewport("bad", clip="sometimes")
    with pytest.raises(ViewportError, match="length 1"):
        Viewport(x=unit([1.0, 2.0], "npc"))
    with pytest.raises(ViewportError, match="angle"):
        viewport("bad", angle=float("nan"))
    with pytest.raises(ViewportError, match="justification"):
        viewport("bad", just="middle")
    with pytest.raises(ViewportError, match="gp 与 gpar"):
        viewport("bad", gp=gpar(col="red"), gpar=gpar(col="blue"))
    with pytest.raises(ViewportError, match="ROOT"):
        ViewportTree(DEVICE, root=viewport("not-root"))
    with pytest.raises(ViewportError, match="at least one"):
        ViewportTree(DEVICE).push()


def test_normalize_just_covers_r_forms() -> None:
    assert normalize_just(None) == (0.5, 0.5)
    assert normalize_just("left") == (0.0, 0.5)
    assert normalize_just("top") == (0.5, 1.0)
    assert normalize_just(("right", "bottom")) == (1.0, 0.0)
    assert normalize_just([0.25, 0.75]) == (0.25, 0.75)
    assert normalize_just(0.3) == (0.3, 0.5)
    assert normalize_just(np.array([0.1, 0.2])) == (0.1, 0.2)


def test_viewport_factory_defaults_and_auto_names() -> None:
    first = viewport()
    second = viewport()
    assert first.name.startswith("GRID.VP.")
    assert first.name != second.name
    assert first.width == unit(1.0, NPC)
    assert first.clip is Clip.INHERIT
    assert viewport("named", width=unit(2.0, "cm")).width == unit(2.0, "cm")
    assert isinstance(viewport("gp", gp={"col": "red"}).gpar, Gpar)


def test_siblings_and_descendants_walk_the_tree() -> None:
    tree = ViewportTree(DEVICE)
    a = tree.push(viewport("a"))
    tree.push(viewport("a1"))
    tree.up(2)
    b = tree.push(viewport("b"))
    assert [node.name for node in a.siblings()] == ["a", "b"]
    assert [node.name for node in tree.root.descendants()] == ["a", "a1", "b"]
    assert [node.name for node in tree.nodes()] == ["ROOT", "a", "a1", "b"]
    assert b.depth == 1
