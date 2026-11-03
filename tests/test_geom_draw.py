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
from ggcore.geom import (
    GeomError,
    build_only_renderers,
    registered_renderers,
    renderer_for,
)
from ggcore.geom.scene import scene_from_build, scene_from_plot
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


def test_renderer_registry_covers_every_registered_geom() -> None:
    # M2-S2：注册表里的每一个 geom 都必须有绘制实现（M1-7 的 9 个 + 长尾 A 的
    # 20 个），或者明确登记在 build-only 表里（M2-6 的 5 个 2D 族；`tile` 已由
    # 长尾 A 实现）。两边顺序一致，缺一个就红。
    build_only = set(build_only_renderers())
    assert registered_renderers() == tuple(
        name for name in registry.registered("geom") if name not in build_only
    )
    assert build_only <= set(registry.registered("geom"))
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


def test_setup_params_prefers_the_flipped_aes_column_from_the_stat() -> None:
    """`has_flipped_aes()` 的第一分支：`data$flipped_aes` 优先于列类型推断。

    横向 `geom_histogram()` 的 stat 产出 `flipped_aes = TRUE`，但映射前的
    `raw` 里只有连续的 y（推断不出横向）——geom 必须消费 stat 的结论，否则
    `setup_data()` 会按竖向把长度轴与类别轴对调。
    """
    # 映射前的美学表：只有连续的 y，按列类型推断只会得到「竖向」。
    raw = _table(y=[1.0, 1.0, 2.0, 2.0])
    # stat 之后的数据：带 flipped_aes 列（stat_bin 的横向输出），x/y 都连续。
    stat_table = ColumnTable(
        [
            ("x", Column("float", np.array([2.0, 1.0]))),
            ("y", Column("float", np.array([1.5, 2.5]))),
            ("flipped_aes", Column("bool", np.array([True, True]))),
        ]
    )
    for geom in (registry.geom_histogram(), registry.geom_bar(), registry.geom_boxplot()):
        resolved = geom.geom.setup_params(stat_table, {}, raw=raw)
        assert resolved["flipped_aes"] is True

    # 反过来：stat 说竖向时不能被 raw 的离散类型带偏。
    vertical = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0]))),
            ("y", Column("float", np.array([2.0, 2.0]))),
            ("flipped_aes", Column("bool", np.array([False, False]))),
        ]
    )
    discrete_raw = _table(x=["a", "b"], y=[1.0, 2.0])
    assert (
        registry.geom_col().geom.setup_params(vertical, {}, raw=discrete_raw)["flipped_aes"]
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

    # clip = "on" 的图层节点被面板矩形收窄；"off" 时只剩设备外包框。
    on_clips = _clips_for(on, "points")
    off_clips = _clips_for(off, "points")
    assert on_clips and all(rect != page for rect in on_clips)
    assert off_clips and all(rect[2] - rect[0] >= 288.0 for rect in off_clips)

    # clip = "inherit" 从用户入口可用：panel_params 原样记三态，场景沿用父视口
    # （页面是 clip = "off"，所以与 "off" 一样落在设备外包框上、不裁到面板）。
    inherit_plot = _facet_plot() + registry.coord_cartesian(clip="inherit")
    assert build_plot(inherit_plot).panel_params.clip == "inherit"
    inherit = scene_from_plot(inherit_plot, metrics=METRICS, **SIZE)
    inherit_clips = _clips_for(inherit, "points")
    assert inherit_clips
    assert sorted(inherit_clips) == sorted(off_clips)


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
        + registry.guide_none("fill")  # M1-11：图例也画矩形，这里只数面板里的柱
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


def test_horizontal_boxplot_puts_length_on_x_and_category_on_y() -> None:
    """SIL-709 修的横向箱线图方向：flip 时 x 是长度轴、y 是类别轴。

    修前须线 / 箱体 / 中位线都用（类别, 长度）拼坐标，横向时整只箱被摆成竖向
    （只有离群点已经对换）。这里把两侧的**实际绘制坐标**换算回数据值断言，
    而不是只看 `geom-boxplot-horizontal` 的图级 diff。
    """
    data = _table(
        cls=["a"] * 6 + ["b"] * 6,
        v=[1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 0.5, 1.0, 1.5, 2.0, 2.5, 5.0],
    )
    width = 0.6

    def drawn(plot) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
        build = build_plot(plot)
        params = build.panels[0].panel_params
        x_unit = SIZE["width_in"] * 72.0 / (params.x_range[1] - params.x_range[0])
        y_unit = SIZE["height_in"] * 72.0 / (params.y_range[1] - params.y_range[0])
        scene = scene_from_build(build, **SIZE)
        polygon = next(node for node in _nodes(scene) if node.kind.value == "polygon")
        segments = [node for node in _nodes(scene) if node.kind.value == "segments"]
        median = next(node for node in segments if np.asarray(node.bufs["segments"]).shape[0] == 2)
        return (
            np.asarray(polygon.bufs["points"]),
            np.asarray(median.bufs["segments"]),
            build.layers[0].data,
            x_unit,
            y_unit,
        )

    # 横向：x 是长度（lower..upper），y 是类别轴上 0.6 宽的箱体。
    horizontal_plot = (
        ggplot(data, aes(y="cls", x="v"))
        + registry.geom_boxplot(width=width, orientation="y")
        + registry.scale_x_continuous(limits=(0, 6), expand=(0, 0))
        + registry.theme_void()
    )
    box, median, layer, x_unit, y_unit = drawn(horizontal_plot)
    length_span = float(layer.column("xupper").values[0] - layer.column("xlower").values[0])
    assert box[:, 0].max() - box[:, 0].min() == pytest.approx(length_span * x_unit, abs=1e-2)
    assert box[:, 1].max() - box[:, 1].min() == pytest.approx(width * y_unit, abs=1e-2)
    # 横向的中位线是竖线：每只箱的 x 两端相同（中位数），y 跨过箱体厚度。
    assert np.allclose(median[:, 0], median[:, 2])
    assert np.abs(median[:, 3] - median[:, 1]) == pytest.approx(
        np.full(median.shape[0], width * y_unit), abs=1e-2
    )

    # 纵向保持原样：x 是箱体厚度（类别轴），y 是长度。
    vertical_plot = (
        ggplot(data, aes(x="cls", y="v"))
        + registry.geom_boxplot(width=width, orientation="x")
        + registry.scale_y_continuous(limits=(0, 6), expand=(0, 0))
        + registry.theme_void()
    )
    box, median, layer, x_unit, y_unit = drawn(vertical_plot)
    length_span = float(layer.column("upper").values[0] - layer.column("lower").values[0])
    assert box[:, 1].max() - box[:, 1].min() == pytest.approx(length_span * y_unit, abs=1e-2)
    assert box[:, 0].max() - box[:, 0].min() == pytest.approx(width * x_unit, abs=1e-2)
    assert np.allclose(median[:, 1], median[:, 3])
    assert np.abs(median[:, 2] - median[:, 0]) == pytest.approx(
        np.full(median.shape[0], width * x_unit), abs=1e-2
    )


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


def test_boxplot_outlier_size_includes_stroke() -> None:
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0]))),
            ("ymin", Column("float", np.array([0.1]))),
            ("lower", Column("float", np.array([0.3]))),
            ("middle", Column("float", np.array([0.5]))),
            ("upper", Column("float", np.array([0.7]))),
            ("ymax", Column("float", np.array([0.9]))),
            ("outliers", Column("str", np.array(["20"], dtype=object))),
        ]
    )
    plot = (
        ggplot(
            table,
            aes(
                x="x",
                ymin="ymin",
                lower="lower",
                middle="middle",
                upper="upper",
                ymax="ymax",
                outliers="outliers",
            ),
        )
        + registry.geom_boxplot(stat="identity")
        + registry.theme_void()
    )
    scene = scene_from_plot(plot, **SIZE)
    points = [node for node in _nodes(scene) if node.kind.value == "points"]
    assert len(points) == 1
    # GeomPoint$draw_panel()：fontsize = size * .pt + stroke * .stroke / 2。
    # R 4.0.3 同图 ggplotGrob() 的 points grob gp$fontsize = 5.212795。
    expected = 1.5 * 72.27 / 25.4 + 0.5 * (96.0 / 25.4) / 2.0
    assert float(points[0].params["size"]) == pytest.approx(expected, abs=1e-9)
    assert float(points[0].params["size"]) == pytest.approx(5.212795, abs=1e-6)


def test_default_bar_width_scales_with_resolution() -> None:
    table = _table(x=[0.0, 10.0, 20.0], y=[1.0, 2.0, 3.0])
    plot = (
        ggplot(table, aes(x="x", y="y"))
        + registry.geom_col()
        + registry.coord_cartesian(xlim=(0, 20), expand=(0, 0))
        + registry.theme_void()
    )
    data = build_plot(plot).layers[0].data
    # R 4.0.3：width = resolution(x, zero = FALSE) * 0.9 = 10 * 0.9。
    assert data.column("xmin").values.tolist() == pytest.approx([-4.5, 5.5, 15.5])
    assert data.column("xmax").values.tolist() == pytest.approx([4.5, 14.5, 24.5])


def test_default_boxplot_width_scales_with_resolution() -> None:
    table = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 5.0]))),
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
        + registry.geom_boxplot(stat="identity")
        + registry.scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + registry.theme_void()
    )
    data = build_plot(plot).layers[0].data
    # 同上：resolution(c(1, 5)) * 0.9 = 3.6 → 箱宽 ±1.8。
    assert data.column("xmin").values.tolist() == pytest.approx([-0.8, 3.2])
    assert data.column("xmax").values.tolist() == pytest.approx([2.8, 6.8])


def test_horizontal_area_spans_the_length_axis_and_keeps_categories() -> None:
    table = _table(cls=["a", "b", "c"], v=[1.0, 2.0, 3.0])
    plot = (
        ggplot(table, aes(x="v", y="cls"))
        + registry.geom_area(stat="identity", orientation="y")
        + registry.theme_void()
    )
    build = build_plot(plot)
    data = build.layers[0].data
    # R 4.0.3 的同一张图：x = 类别编码、y = 长度值；xmin = 0、xmax = value。
    assert data.column("x").values.tolist() == [1.0, 2.0, 3.0]
    assert data.column("y").values.tolist() == [1.0, 2.0, 3.0]
    assert data.column("xmin").values.tolist() == [0.0, 0.0, 0.0]
    assert data.column("xmax").values.tolist() == [1.0, 2.0, 3.0]
    assert data.column("flipped_aes").values.tolist() == [True, True, True]

    scene = scene_from_plot(plot, **SIZE)
    polygons = [node for node in _nodes(scene) if node.kind.value == "polygon"]
    # 每个类别一组（每组一行），R 同样出 3 个 2 点退化多边形。
    assert len(polygons) == 3
    x_range = build.panel_params.x_range
    y_range = build.panel_params.y_range

    def x_npc(value: float) -> float:
        return (value - x_range[0]) / (x_range[1] - x_range[0])

    for index, node in enumerate(polygons, start=1):
        points = np.asarray(node.bufs["points"])
        assert points.shape[0] == 2
        # 长度轴在 x 上：从 0 铺到 value（不是把类别轴当 x）。
        assert points[:, 0].tolist() == pytest.approx(
            [x_npc(float(index)) * 288.0, x_npc(0.0) * 288.0]
        )
        # 类别轴在 y 上：面板 npc 0.1875 / 0.5 / 0.8125（IR 的 y 向下）。
        centre = (float(index) - y_range[0]) / (y_range[1] - y_range[0])
        assert points[:, 1].tolist() == pytest.approx([(1.0 - centre) * 216.0] * 2)


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
# 字节稳定：同一输入两次 `scene_from_plot()` → `ir.encode` 的 sha256 相等
# ---------------------------------------------------------------------------


#: 9 个 geom 各一张图（都走 theme_void，避免文字度量引入外部依赖）。
#: `geom_map` 的 `map` 参数：两份 4 顶点的小方块（x / y / id）。
MAP_TABLE = {
    "x": [0.0, 0.4, 0.4, 0.0, 0.5, 0.9, 0.9, 0.5],
    "y": [0.0, 0.0, 0.4, 0.4, 0.5, 0.5, 0.9, 0.9],
    "id": ["a", "a", "a", "a", "b", "b", "b", "b"],
}


def _digest_plots() -> dict[str, object]:
    point = _table(x=[0.2, 0.6], y=[0.3, 0.7], g=["a", "b"])
    line = _table(
        x=[0.1, 0.3, 0.5, 0.7, 0.9, 0.1, 0.3, 0.5, 0.7, 0.9],
        y=[0.2, 0.5, 0.4, 0.7, 0.6, 0.8, 0.6, 0.7, 0.3, 0.4],
        g=["a"] * 5 + ["b"] * 5,
    )
    path = _table(x=[0.15, 0.85, 0.25, 0.9, 0.1], y=[0.2, 0.55, 0.8, 0.25, 0.6])
    bar = _table(cls=["a", "b", "a", "b"], g=["p", "q", "q", "p"])
    col = _table(x=[0.5, 1.5, 2.5], y=[0.35, 0.75, 0.55])
    area = _table(x=[1.0, 2.0, 3.0, 4.0, 5.0], y=[1.0, 3.0, 2.0, 4.0, 3.0])
    histogram = _table(x=[0.5, 1.5, 2.5], y=[0.2, 0.5, 0.75])
    boxplot = ColumnTable(
        [
            ("x", Column("str", np.array(["a", "b"], dtype=object))),
            ("ymin", Column("float", np.array([0.1, 0.2]))),
            ("lower", Column("float", np.array([0.3, 0.35]))),
            ("middle", Column("float", np.array([0.5, 0.5]))),
            ("upper", Column("float", np.array([0.7, 0.65]))),
            ("ymax", Column("float", np.array([0.9, 0.8]))),
        ]
    )
    smooth = ColumnTable(
        [
            ("x", Column("float", np.array([1.0, 2.0, 3.0, 4.0]))),
            ("y", Column("float", np.array([1.0, 1.6, 2.1, 2.7]))),
            ("ymin", Column("float", np.array([0.6, 1.2, 1.7, 2.3]))),
            ("ymax", Column("float", np.array([1.4, 2.0, 2.5, 3.1]))),
        ]
    )
    segment = _table(x=[0.1, 0.5], y=[0.2, 0.6], xend=[0.8, 0.9], yend=[0.7, 0.3])
    spoke = _table(x=[0.3, 0.6], y=[0.3, 0.6], angle=[0.0, 1.0], radius=[0.2, 0.25])
    rect = _table(xmin=[0.1, 0.5], xmax=[0.4, 0.8], ymin=[0.1, 0.2], ymax=[0.5, 0.6])
    tile = _table(x=[0.25, 0.75, 0.25, 0.75], y=[0.25, 0.25, 0.75, 0.75])
    polygon = _table(x=[0.1, 0.4, 0.3, 0.7, 0.8, 0.5], y=[0.1, 0.15, 0.5, 0.55, 0.9, 0.6])
    ribbon = _table(
        x=[0.1, 0.3, 0.5, 0.7, 0.9],
        ymin=[0.1, 0.2, 0.15, 0.3, 0.25],
        ymax=[0.4, 0.5, 0.45, 0.6, 0.55],
    )
    step = _table(x=[0.1, 0.3, 0.5, 0.7, 0.9], y=[0.2, 0.5, 0.35, 0.7, 0.6])
    interval = _table(
        x=[0.3, 0.7],
        y=[0.5, 0.5],
        xmin=[0.2, 0.3],
        xmax=[0.8, 0.7],
        ymin=[0.2, 0.3],
        ymax=[0.8, 0.7],
    )
    return {
        "point": ggplot(point, aes(x="x", y="y", colour="g")) + registry.geom_point(),
        "line": ggplot(line, aes(x="x", y="y", colour="g")) + registry.geom_line(),
        "path": ggplot(path, aes(x="x", y="y")) + registry.geom_path(),
        "bar": ggplot(bar, aes(x="cls", fill="g")) + registry.geom_bar(),
        "col": ggplot(col, aes(x="x", y="y")) + registry.geom_col(),
        "area": ggplot(area, aes(x="x", y="y")) + registry.geom_area(stat="identity"),
        "histogram": ggplot(histogram, aes(x="x", y="y"))
        + registry.geom_histogram(stat="identity"),
        "boxplot": ggplot(
            boxplot,
            aes(x="x", ymin="ymin", lower="lower", middle="middle", upper="upper", ymax="ymax"),
        )
        + registry.geom_boxplot(stat="identity"),
        "smooth": ggplot(smooth, aes(x="x", y="y", ymin="ymin", ymax="ymax"))
        + registry.geom_smooth(stat="identity"),
        # --- M2-S2 长尾 A ---------------------------------------------------
        "abline": ggplot(point, aes(x="x", y="y")) + registry.geom_abline(slope=1, intercept=0),
        "hline": ggplot(point, aes(x="x", y="y")) + registry.geom_hline(yintercept=0.5),
        "vline": ggplot(point, aes(x="x", y="y")) + registry.geom_vline(xintercept=0.5),
        "segment": ggplot(segment, aes(x="x", y="y", xend="xend", yend="yend"))
        + registry.geom_segment(),
        "curve": ggplot(segment, aes(x="x", y="y", xend="xend", yend="yend"))
        + registry.geom_curve(),
        "spoke": ggplot(spoke, aes(x="x", y="y", angle="angle", radius="radius"))
        + registry.geom_spoke(),
        "rect": ggplot(rect, aes(xmin="xmin", xmax="xmax", ymin="ymin", ymax="ymax"))
        + registry.geom_rect(),
        "tile": ggplot(tile, aes(x="x", y="y")) + registry.geom_tile(),
        "raster": ggplot(tile, aes(x="x", y="y")) + registry.geom_raster(),
        "polygon": ggplot(polygon, aes(x="x", y="y")) + registry.geom_polygon(),
        "ribbon": ggplot(ribbon, aes(x="x", ymin="ymin", ymax="ymax")) + registry.geom_ribbon(),
        "step": ggplot(step, aes(x="x", y="y")) + registry.geom_step(),
        "errorbar": ggplot(interval, aes(x="x", y="y", ymin="ymin", ymax="ymax"))
        + registry.geom_errorbar(),
        "errorbarh": ggplot(interval, aes(y="y", x="x", xmin="xmin", xmax="xmax"))
        + registry.geom_errorbarh(),
        "linerange": ggplot(interval, aes(x="x", ymin="ymin", ymax="ymax"))
        + registry.geom_linerange(),
        "pointrange": ggplot(interval, aes(x="x", y="y", ymin="ymin", ymax="ymax"))
        + registry.geom_pointrange(),
        "crossbar": ggplot(interval, aes(x="x", y="y", ymin="ymin", ymax="ymax"))
        + registry.geom_crossbar(),
        "blank": ggplot(point, aes(x="x", y="y")) + registry.geom_blank(),
        "rug": ggplot(point, aes(x="x", y="y")) + registry.geom_rug(),
        "map": ggplot(_table(map_id=["a", "b"]), aes(map_id="map_id"))
        + registry.geom_map(map=MAP_TABLE),
    }


def test_digest_plots_cover_every_geom() -> None:
    assert set(_digest_plots()) == set(registered_renderers())


@pytest.mark.parametrize("geom_name", sorted(_digest_plots()))
def test_scene_encoding_is_byte_stable(geom_name: str) -> None:
    plot = _digest_plots()[geom_name] + registry.theme_void()
    first = scene_from_plot(plot, **SIZE)
    # 图不是空的：除了 viewport 还有实际的几何叶子节点。
    # `geom_blank` 是唯一例外——它只参与标度 / 布局，`nullGrob()` 不产出叶子。
    if geom_name != "blank":
        assert [node for node in _nodes(first) if node.kind.value != "viewport"]
    one = hashlib.sha256(ir.encode(first)).hexdigest()
    two = hashlib.sha256(ir.encode(scene_from_plot(plot, **SIZE))).hexdigest()
    assert one == two
