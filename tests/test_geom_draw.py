"""M1-7 绘制契约与 9 个 geom 的绘制口径。

三组断言：

1. **契约**：`Geom.draw()` / `handle_na()` / `setup_data()` / `setup_params()`
   的签名与注册表；未实现的 geom 名点名报错，不静默降级；
2. **handle_na**：绘制期删行的 warning 文案与计数（`na_rm=True` 静默），
   与 build 的 `dropped_missing`（只计数）分开；
3. **几何**：point / line / path / bar / col / area / histogram / boxplot / smooth
   的 grob 形状与 npc 坐标；clip 三态与多面板各自裁剪。
"""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import replace

import numpy as np
import pytest

from ggcore import ir, registry
from ggcore.build import BuildWarning, build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom import GeomError, registered_renderers, renderer_for
from ggcore.geom.scene import scene_from_plot
from ggcore.plot import aes, ggplot

SIZE = dict(width_in=4.0, height_in=3.0)


#: 场景里的 strip / 文本需要度量；测试不关心真实字体，给一个稳定的假度量。
class FakeMetrics:
    def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        return 0.05 * len(text) * fontsize / 72.0

    def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        return fontsize / 72.0


METRICS = FakeMetrics()


def _table(**columns: list) -> ColumnTable:
    built = []
    for name, values in columns.items():
        if values and isinstance(values[0], str):
            built.append((name, Column("str", np.array(values, dtype=object))))
        else:
            built.append((name, Column("float", np.array(values, dtype=float))))
    return ColumnTable(built)


def _column(values: list[float], missing: list[int]) -> Column:
    mask = np.zeros(len(values), dtype=bool)
    mask[missing] = True
    return Column("float", np.array(values, dtype=float), na_mask=mask)


def _nodes(ir_scene) -> list:
    out = []

    def walk(node):
        out.append(node)
        for child in node.children:
            walk(child)

    walk(ir_scene.root)
    return out


def _clips_for(ir_scene, kind: str) -> list[tuple[float, float, float, float]]:
    """每个 `kind` 叶子节点**实际生效**的裁剪矩形（取自祖先 viewport）。

    IR 是扁平指令：`Instruction.clip` 在 `to_ir_scene()` 时折进 viewport 的
    `clip_rect`，叶子节点自己不带宽高。
    """
    out: list[tuple[float, float, float, float]] = []

    def walk(node, current):
        if node.kind.value == "viewport" and "clip_rect" in node.bufs:
            rect = np.asarray(node.bufs["clip_rect"]).ravel().tolist()
            current = tuple(round(value, 3) for value in rect)
        if node.kind.value == kind and current is not None:
            out.append(current)
        for child in node.children:
            walk(child, current)

    walk(ir_scene.root, None)
    return out


def _clips(ir_scene) -> list[tuple[float, float, float, float]]:
    rects = []
    for node in _nodes(ir_scene):
        if node.kind.value == "viewport" and "clip_rect" in node.bufs:
            rect = np.asarray(node.bufs["clip_rect"]).ravel().tolist()
            rects.append(tuple(round(value, 3) for value in rect))
    return rects


def test_renderer_registry_covers_the_nine_geoms() -> None:
    assert registered_renderers() == (
        "point",
        "line",
        "path",
        "bar",
        "col",
        "area",
        "histogram",
        "boxplot",
        "smooth",
    )
    assert renderer_for("col").name == "col"
    with pytest.raises(GeomError, match="没有绘制实现"):
        renderer_for("violin")


def test_geom_contract_fields_match_ggplot2() -> None:
    point = registry.geom_point().geom
    assert point.non_missing_aes == ("size", "shape", "colour")
    assert point.optional_aes == ()
    assert registry.geom_smooth().geom.optional_aes == ("ymin", "ymax")
    assert registry.geom_line().geom.non_missing_aes == ("linewidth", "colour", "linetype")
    assert registry.geom_col().geom.non_missing_aes == ("xmin", "xmax", "ymin", "ymax")


def test_setup_params_detects_flipped_only_where_r_does() -> None:
    vertical = _table(x=["a", "b"], y=[1.0, 2.0])
    horizontal = _table(x=[1.0, 2.0], y=["a", "b"])
    # point / line / path 的 R 实现不调 has_flipped_aes()。
    assert (
        registry.geom_point().geom.setup_params(horizontal, {}, raw=horizontal)["flipped_aes"]
        is False
    )
    # bar / col 会：x 连续、y 离散 → 横向；反过来是竖向。
    assert registry.geom_col().geom.setup_params(vertical, {}, raw=vertical)["flipped_aes"] is False
    assert (
        registry.geom_col().geom.setup_params(horizontal, {}, raw=horizontal)["flipped_aes"] is True
    )
    assert (
        registry.geom_col().geom.setup_params(horizontal, {"orientation": "x"}, raw=horizontal)[
            "flipped_aes"
        ]
        is False
    )
    # smooth / area 是 ambiguous：没有显式 orientation 时不猜横向。
    assert (
        registry.geom_smooth().geom.setup_params(horizontal, {}, raw=horizontal)["flipped_aes"]
        is False
    )


def test_handle_na_warns_with_r_wording_and_count() -> None:
    source = ColumnTable(
        [("x", Column("float", np.array([0.1, 0.3, 0.5]))), ("y", _column([0.2, 0.0, 0.6], [1]))]
    )
    geom = registry.geom_point().geom
    with pytest.warns(BuildWarning, match=r"Removed 1 row containing missing values") as record:
        kept = geom.handle_na(source, na_rm=False)
    assert kept.nrows == 2
    assert "(`geom_point()`)" in str(record[0].message)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert geom.handle_na(source, na_rm=True).nrows == 2


def test_line_keeps_internal_na_and_breaks_the_path() -> None:
    table = ColumnTable(
        [
            ("x", Column("float", np.array([0.1, 0.3, 0.5, 0.7, 0.9]))),
            ("y", _column([0.2, 0.3, 0.0, 0.5, 0.6], [2])),
        ]
    )
    plot = ggplot(table, aes(x="x", y="y")) + registry.geom_line()
    build = build_plot(plot)
    assert build.layers[0].data.nrows == 5  # build 不删行
    geom = build.layers[0].geom_object
    assert geom.handle_na(build.layers[0].data, na_rm=False).nrows == 5  # 中间 NA 保留（断线）
    scene = scene_from_plot(plot, **SIZE)
    polylines = [node for node in _nodes(scene) if node.kind.value == "polyline"]
    assert len(polylines) == 1
    # 断成两段：IR 的 id 按出现顺序编号（0 起）。
    assert sorted(set(np.asarray(polylines[0].bufs["id"]).tolist())) == [0, 1]


def _facet_plot() -> ggplot:
    table = _table(
        x=[0.1, 0.5, 0.9, 0.2, 0.8, 0.4],
        y=[0.2, 0.5, 0.8, 0.3, 0.7, 0.6],
        f=["a", "b", "a", "b", "a", "b"],
    )
    return (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point()
        + registry.facet_wrap(facets="f", ncol=2)
        + registry.theme_grey()
    )


def test_coord_clip_inherit_is_accepted_from_the_user_entry() -> None:
    """`coord_cartesian(clip = "inherit")` 构建期合法，原样进 panel params。"""
    table = _table(x=[0.1, 0.5], y=[0.2, 0.6])
    base = ggplot(table, aes(x="x", y="y")) + registry.geom_point()
    for value in ("on", "off", "inherit"):
        params = build_plot(base + registry.coord_cartesian(clip=value)).panel_params
        assert params is not None
        assert params.clip == value


def test_clip_on_off_and_inherit() -> None:
    page = (0.0, 0.0, 288.0, 216.0)
    on = scene_from_plot(
        _facet_plot() + registry.coord_cartesian(clip="on"), metrics=METRICS, **SIZE
    )
    rects = _clips(on)
    assert page in rects
    panels = sorted({rect for rect in rects if rect != page and 0 <= rect[0] < 288})
    assert len(panels) == 2  # 2×2 里的两个面板，各自一块裁剪矩形

    off = scene_from_plot(
        _facet_plot() + registry.coord_cartesian(clip="off"), metrics=METRICS, **SIZE
    )
    outer = [rect for rect in _clips(off) if rect[2] - rect[0] > 288.0]
    assert outer  # R 的 clip = NA 是设备外包框（1.5×）

    # clip = "inherit" 是 gtable 的第三态：面板视口沿用父视口（页面）的裁剪，
    # 既不额外生成面板矩形，也不像 "off" 那样在图层上另开设备外包框。
    inherit = scene_from_plot(
        _facet_plot() + registry.coord_cartesian(clip="inherit"), metrics=METRICS, **SIZE
    )
    inherit_clips = _clips_for(inherit, "points")
    assert inherit_clips
    assert all(rect[2] - rect[0] >= 288.0 for rect in inherit_clips)
    assert inherit_clips == _clips_for(off, "points")

    # clip = "on" 的图层节点被面板矩形收窄；"off" 时只剩设备外包框。
    on_clips = _clips_for(on, "points")
    off_clips = _clips_for(off, "points")
    assert on_clips and all(rect != page for rect in on_clips)
    assert off_clips and all(rect[2] - rect[0] >= 288.0 for rect in off_clips)


def test_each_facet_panel_has_its_own_clip_rect() -> None:
    scene = scene_from_plot(_facet_plot(), metrics=METRICS, **SIZE)
    clips = _clips_for(scene, "points")
    assert len(clips) == 2
    assert clips[0] != clips[1]


def test_point_shapes_alpha_and_size() -> None:
    table = _table(x=[0.2, 0.6], y=[0.3, 0.7], g=["a", "b"])
    plot = (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_point(data=_table(x=[0.2], y=[0.3]), shape=19, size=4.0, stroke=0.0)
        + registry.geom_point(
            data=_table(x=[0.6], y=[0.7]), shape=15, size=4.0, stroke=0.0, alpha=0.5
        )
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    )
    scene = scene_from_plot(plot, **SIZE)
    points = [node for node in _nodes(scene) if node.kind.value == "points"]
    assert sorted(int(node.params["pch"]) for node in points) == [15, 19]
    # size = 4mm → 4 * .pt pt（stroke = 0）。
    assert all(abs(float(node.params["size"]) - 4.0 * 72.27 / 25.4) < 1e-6 for node in points)
    # alpha = 0.5 折进颜色（半透明方块的 fill alpha < 255）。
    half = next(node for node in points if int(node.params["pch"]) == 15)
    assert half.gpar.col is not None and half.gpar.col[3] < 255


def test_bar_uses_the_position_columns_not_the_raw_values() -> None:
    table = _table(x=[0.5, 1.5, 2.5], y=[1.0, 2.0, 3.0], g=["p", "p", "q"])
    plot = (
        ggplot(table, aes(x="x", y="y", fill="g"))
        + registry.geom_col(width=0.5)
        + registry.scale_fill_discrete(values={"p": "#4C78A8", "q": "#F58518"})
        + registry.scale_x_continuous(limits=(0, 3), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 3), expand=(0, 0))
        + registry.theme_void()
    )
    scene = scene_from_plot(plot, **SIZE)
    rects = [node for node in _nodes(scene) if node.kind.value == "rect"]
    rows = sum(int(np.asarray(node.bufs["rect"]).shape[0]) for node in rects)
    assert rows == 3  # IR 按 gp 分组，一个节点可能带多根柱
    width = float(np.asarray(rects[0].bufs["rect"])[0][2]) - float(
        np.asarray(rects[0].bufs["rect"])[0][0]
    )
    assert width == pytest.approx(0.5 / 3.0 * 288.0, abs=1e-3)


def test_bar_default_width_scales_with_the_x_resolution() -> None:
    """R 的 `compute_data_size(default = 0.9)`：宽度 = `resolution(x, zero = FALSE) * 0.9`。

    连续 x `[0, 10, 20]` 的 resolution 是 10，默认宽度 9（不是常数 0.9）。
    """
    table = _table(x=[0, 10, 20], y=[1, 2, 3])
    plot = ggplot(table, aes(x="x", y="y")) + registry.geom_col()
    built = build_plot(plot).layers[0].data
    assert built.column("xmin").values.tolist() == pytest.approx([-4.5, 5.5, 15.5])
    assert built.column("xmax").values.tolist() == pytest.approx([4.5, 14.5, 24.5])

    # 显式 width 参数原样使用（R 的 `data$width %||% params$width`），不再乘分辨率。
    explicit = (
        build_plot(ggplot(table, aes(x="x", y="y")) + registry.geom_col(width=2.0)).layers[0].data
    )
    assert explicit.column("xmin").values.tolist() == pytest.approx([-1.0, 9.0, 19.0])
    assert explicit.column("xmax").values.tolist() == pytest.approx([1.0, 11.0, 21.0])

    # 映射出来的 width 列同样优先于分辨率，也不缩放。
    mapped = (
        build_plot(
            ggplot(_table(x=[0, 10, 20], y=[1, 2, 3], w=[2, 2, 2]), aes(x="x", y="y", width="w"))
            + registry.geom_col()
        )
        .layers[0]
        .data
    )
    assert mapped.column("xmax").values.tolist() == pytest.approx([1.0, 11.0, 21.0])


def test_boxplot_default_width_scales_with_the_x_resolution() -> None:
    table = _table(
        x=[0.0, 10.0, 20.0],
        ymin=[0.0, 0.0, 0.0],
        lower=[1.0, 1.0, 1.0],
        middle=[2.0, 2.0, 2.0],
        upper=[3.0, 3.0, 3.0],
        ymax=[4.0, 4.0, 4.0],
    )
    frame = renderer_for("boxplot").setup_data(table, {"flipped_aes": False})
    assert frame.column("xmin").values.tolist() == pytest.approx([-4.5, 5.5, 15.5])
    assert frame.column("xmax").values.tolist() == pytest.approx([4.5, 14.5, 24.5])


def test_boxplot_whiskers_do_not_fold_in_alpha() -> None:
    """R 的须线显式 `alpha = NA`：映射了 alpha 时须线保持原色，箱体才吃 alpha。"""
    table = ColumnTable(
        [
            ("x", Column("str", np.array(["a", "b"], dtype=object))),
            ("ymin", Column("float", np.array([0.1, 0.2]))),
            ("lower", Column("float", np.array([0.3, 0.35]))),
            ("middle", Column("float", np.array([0.5, 0.5]))),
            ("upper", Column("float", np.array([0.7, 0.65]))),
            ("ymax", Column("float", np.array([0.9, 0.8]))),
        ]
    )
    plot = (
        ggplot(
            table,
            aes(x="x", ymin="ymin", lower="lower", middle="middle", upper="upper", ymax="ymax"),
        )
        + registry.geom_boxplot(
            stat="identity", colour="#4C78A8", fill="#4C78A8", alpha=0.4, width=0.6
        )
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    )
    scene = scene_from_plot(plot, **SIZE)
    nodes = _nodes(scene)
    segments = [node for node in nodes if node.kind.value == "segments"]
    polygons = [node for node in nodes if node.kind.value == "polygon"]
    assert len(segments) == 2  # 须线 + 中位线
    assert len(polygons) == 2
    # alpha = 0.4 → 箱体是 #4C78A8 + 0x66；须线 / 中位线仍是全不透明的 #4C78A8。
    assert all(tuple(node.gpar.col)[3] == 255 for node in segments)
    assert all(tuple(node.gpar.col)[3] < 255 for node in polygons)
    assert all(tuple(node.gpar.fill)[3] < 255 for node in polygons)


def test_line_handle_na_groups_by_panel_like_r() -> None:
    """`GeomPath$handle_na()` 按 `interaction(group, PANEL)` 做 `keep_mid_true()`。"""
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 1.0, 2.0, 3.0]))),
            ("y", _column([0.0, 2.0, 3.0, 0.0, 5.0, 6.0], [0, 3])),
            ("f", Column("str", np.array(["a", "a", "a", "b", "b", "b"], dtype=object))),
        ]
    )
    plot = (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_line()
        + registry.facet_wrap(facets="f", ncol=2)
        + registry.theme_void()
    )
    layer = build_plot(plot).layers[0]
    # 两个面板各有一个首行 NA：按 PANEL 分开算 → 两行都删（合并成一组只会删一行）。
    with pytest.warns(BuildWarning, match=r"Removed 2 rows containing missing values"):
        kept = layer.geom_object.handle_na(layer.data, na_rm=False)
    assert kept.nrows == 4


def test_boxplot_segments_polygons_and_median() -> None:
    table = ColumnTable(
        [
            ("x", Column("str", np.array(["a", "b"], dtype=object))),
            ("ymin", Column("float", np.array([0.1, 0.2]))),
            ("lower", Column("float", np.array([0.3, 0.35]))),
            ("middle", Column("float", np.array([0.5, 0.5]))),
            ("upper", Column("float", np.array([0.7, 0.65]))),
            ("ymax", Column("float", np.array([0.9, 0.8]))),
        ]
    )
    plot = (
        ggplot(
            table,
            aes(x="x", ymin="ymin", lower="lower", middle="middle", upper="upper", ymax="ymax"),
        )
        + registry.geom_boxplot(stat="identity", width=0.6)
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    )
    scene = scene_from_plot(plot, **SIZE)
    polygons = [node for node in _nodes(scene) if node.kind.value == "polygon"]
    segments = [node for node in _nodes(scene) if node.kind.value == "segments"]
    assert len(polygons) == 2  # 每只箱一个 polygon（IR 的 polygon 只带一份 gp）
    assert len(segments) == 2  # 须线（4 段）+ 中位线（2 段）
    box = np.asarray(polygons[0].bufs["points"])
    assert box.shape[0] == 5  # 闭合五边形
    assert box[:, 1].max() - box[:, 1].min() == pytest.approx(0.4 / 1.0 * 216.0, abs=1e-2)


def test_area_draws_fill_polygon_and_outline() -> None:
    table = _table(x=[1, 2, 3], y=[1, 3, 2])
    plot = (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_area(stat="identity", colour="#4C78A8", fill="#999999")
        + registry.scale_x_continuous(limits=(0, 4), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 4), expand=(0, 0))
        + registry.theme_void()
    )
    scene = scene_from_plot(plot, **SIZE)
    polygons = [node for node in _nodes(scene) if node.kind.value == "polygon"]
    polylines = [node for node in _nodes(scene) if node.kind.value == "polyline"]
    assert len(polygons) == 1
    # 上沿 3 点 + 下沿 3 点，同一组 id → 一个闭合多边形。
    assert np.asarray(polygons[0].bufs["points"]).shape[0] == 6
    assert len(polylines) == 2  # outline.type = "both"


def test_smooth_ribbon_and_line() -> None:
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("y", Column("float", np.array([1.0, 2.0, 3.0]))),
            ("ymin", Column("float", np.array([0.5, 1.5, 2.5]))),
            ("ymax", Column("float", np.array([1.5, 2.5, 3.5]))),
        ]
    )
    mapping = aes(x="x", y="y", ymin="ymin", ymax="ymax")
    x_scale = registry.scale_x_continuous(limits=(0, 4), expand=(0, 0))
    y_scale = registry.scale_y_continuous(limits=(0, 4), expand=(0, 0))
    with_se = scene_from_plot(
        ggplot(table, mapping)
        + registry.geom_smooth(stat="identity")
        + x_scale
        + y_scale
        + registry.theme_void(),
        **SIZE,
    )
    assert len([node for node in _nodes(with_se) if node.kind.value == "polygon"]) == 1
    assert len([node for node in _nodes(with_se) if node.kind.value == "polyline"]) == 1

    without_se = scene_from_plot(
        ggplot(table, mapping)
        + registry.geom_smooth(stat="identity", se=False)
        + x_scale
        + y_scale
        + registry.theme_void(),
        **SIZE,
    )
    assert not [node for node in _nodes(without_se) if node.kind.value == "polygon"]
    assert len([node for node in _nodes(without_se) if node.kind.value == "polyline"]) == 1


def test_empty_layer_does_not_emit_grobs() -> None:
    table = _table(x=[0.1, 0.5], y=[0.2, 0.6])
    plot = ggplot(table, aes(x="x", y="y")) + registry.geom_point() + registry.theme_void()
    build = build_plot(plot)
    empty = replace(build.layers[0], data=ColumnTable([], nrows=0))
    grob = build.layers[0].geom_object.draw(empty, build.panel_params, build.coord, None, None)
    assert isinstance(grob, (type(None),)) or grob.__class__.__name__ in ("NullGrob",)
    scene = scene_from_plot(plot, **SIZE)
    assert [node for node in _nodes(scene) if node.kind.value == "points"]


# ---------------------------------------------------------------------------
# 字节稳定性：同一份输入构建两次 → `ir.encode` 逐字节相等
# ---------------------------------------------------------------------------

#: 9 个 geom 各一张最小图（stat 全部用 identity，不依赖 M1-8 的 stat）。
BYTE_STABLE_PLOTS = {
    "point": lambda: (
        ggplot(_table(x=[0.2, 0.6], y=[0.3, 0.7], g=["a", "b"]), aes(x="x", y="y", colour="g"))
        + registry.geom_point()
        + registry.scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "line": lambda: (
        ggplot(_table(x=[1, 2, 3], y=[1, 3, 2]), aes(x="x", y="y"))
        + registry.geom_line()
        + registry.theme_void()
    ),
    "path": lambda: (
        ggplot(_table(x=[1, 2, 3], y=[2, 1, 3]), aes(x="x", y="y"))
        + registry.geom_path()
        + registry.theme_void()
    ),
    "bar": lambda: (
        ggplot(_table(cls=["a", "b", "a", "c"]), aes(x="cls"))
        + registry.geom_bar()
        + registry.theme_void()
    ),
    "col": lambda: (
        ggplot(_table(x=[0.5, 1.5, 2.5], y=[1, 2, 3]), aes(x="x", y="y"))
        + registry.geom_col()
        + registry.theme_void()
    ),
    "area": lambda: (
        ggplot(_table(x=[1, 2, 3], y=[1, 3, 2]), aes(x="x", y="y"))
        + registry.geom_area(stat="identity")
        + registry.theme_void()
    ),
    "histogram": lambda: (
        ggplot(
            _table(x=[0.5, 1.5, 2.5], y=[0.2, 0.5, 0.7], w=[1, 1, 1]),
            aes(x="x", y="y", width="w"),
        )
        + registry.geom_histogram(stat="identity")
        + registry.theme_void()
    ),
    "boxplot": lambda: (
        ggplot(
            ColumnTable(
                [
                    ("x", Column("str", np.array(["a", "b"], dtype=object))),
                    ("ymin", Column("float", np.array([0.1, 0.2]))),
                    ("lower", Column("float", np.array([0.3, 0.35]))),
                    ("middle", Column("float", np.array([0.5, 0.5]))),
                    ("upper", Column("float", np.array([0.7, 0.65]))),
                    ("ymax", Column("float", np.array([0.9, 0.8]))),
                ]
            ),
            aes(x="x", ymin="ymin", lower="lower", middle="middle", upper="upper", ymax="ymax"),
        )
        + registry.geom_boxplot(stat="identity")
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    ),
    "smooth": lambda: (
        ggplot(
            _table(
                x=[1, 2, 3],
                y=[1, 2, 3],
                ymin=[0.5, 1.5, 2.5],
                ymax=[1.5, 2.5, 3.5],
            ),
            aes(x="x", y="y", ymin="ymin", ymax="ymax"),
        )
        + registry.geom_smooth(stat="identity")
        + registry.theme_void()
    ),
}


@pytest.mark.parametrize("geom_name", list(BYTE_STABLE_PLOTS))
def test_geom_scene_is_byte_stable_across_two_builds(geom_name: str) -> None:
    """同一输入构建两次 → `ir.encode` 逐字节相等（9 个 geom 各一条）。"""
    first = ir.encode(scene_from_plot(BYTE_STABLE_PLOTS[geom_name](), **SIZE))
    second = ir.encode(scene_from_plot(BYTE_STABLE_PLOTS[geom_name](), **SIZE))
    assert first == second, f"geom_{geom_name}: 两次构建的 IR 字节不同"
    assert hashlib.sha256(first).digest() == hashlib.sha256(second).digest()
