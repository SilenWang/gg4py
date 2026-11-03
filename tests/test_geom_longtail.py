"""M2-S2 长尾 A：线段 / 矩形 / 区间 / 标注族的定向断言。

逐列对拍在 `tests/test_geom_r_parity.py`（R 夹具），像素对拍在
`docs/cases/geom-*`（`pixi run cases:matrix`）。这里只钉那些**只有实现细节才能
证明**的口径：

- `arrow` 的 IR 标记属性（节点参数，不是新节点种类）；
- `geom_boxplot` / `geom_area` 的横向自动探测（SIL-715 #4 / #5）；
- `geom_raster` 的位图（PNG blob + interpolate）；
- ribbon 的多边形是一个环（上沿 + 下沿，同 id）；
- `geom_blank` 不产出叶子；`geom_map` 按 id 分组。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ggcore import ir
from ggcore.arrow import arrow, head_geometry
from ggcore.build import build_plot
from ggcore.data import Column, ColumnTable
from ggcore.geom import renderer_for
from ggcore.grobs import ViewportTree, scene
from ggcore.plot import (
    aes,
    geom_abline,
    geom_area,
    geom_blank,
    geom_boxplot,
    geom_errorbar,
    geom_map,
    geom_raster,
    geom_ribbon,
    geom_rug,
    geom_segment,
    ggplot,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.plot import (
    arrow as arrow_export,
)
from ggcore.theme import Theme, resolve_theme
from ggcore.viewport import Device, viewport

SIZE = (4.0, 3.0)


def _table(**columns: list) -> ColumnTable:
    built: list[tuple[str, Column]] = []
    for name, values in columns.items():
        if values and isinstance(values[0], str):
            built.append((name, Column("str", np.array(values, dtype=object))))
        else:
            built.append((name, Column("float", np.array(values, dtype=float))))
    return ColumnTable(built)


def _draw(plot) -> list:
    build = build_plot(plot + theme_void())
    tree = ViewportTree(Device(*SIZE))
    nodes: list = []
    for layer in build.layers:
        grob = layer.geom_object.draw(
            layer, build.panel_params, build.coord, resolve_theme(Theme()), None
        )
        tree.push(
            viewport("panel", x=0.5, y=0.5, width=1.0, height=1.0, xscale=(0, 1), yscale=(0, 1))
        )
        nodes.extend(scene(grob, tree).instructions)
        tree.pop()
    return [node for node in nodes if node.kind.value != "viewport"]


# ---------------------------------------------------------------------------
# arrow：IR 标记属性
# ---------------------------------------------------------------------------


def test_arrow_export_is_the_same_object_as_ggcore_arrow() -> None:
    assert arrow_export is arrow


def test_arrow_node_params_are_written_only_when_used() -> None:
    plain = _draw(
        ggplot(
            _table(x=[0.1], y=[0.2], xend=[0.8], yend=[0.9]),
            aes(x="x", y="y", xend="xend", yend="yend"),
        )
        + geom_segment()
    )
    assert plain[0].params == {}


def test_segment_arrow_lands_on_the_segments_node() -> None:
    nodes = _draw(
        ggplot(
            _table(x=[0.1], y=[0.2], xend=[0.8], yend=[0.9]),
            aes(x="x", y="y", xend="xend", yend="yend"),
        )
        + geom_segment(arrow=arrow(length=0.15 * 72.0, ends="both", type="closed"))
    )
    params = nodes[0].params
    assert params["arrow"] == "both"
    assert params["arrow_length"] == pytest.approx(0.15 * 72.0)
    assert params["arrow_angle"] == pytest.approx(30.0)
    assert params["arrow_type"] == "closed"


def test_arrow_length_accepts_a_unit() -> None:
    from ggcore.units import unit

    assert arrow(length=unit(0.25, "inches")).length_pt == pytest.approx(18.0)
    assert arrow(length=unit(2.54, "cm")).length_pt == pytest.approx(72.0, rel=1e-3)


def test_arrow_rejects_unknown_ends_and_bad_angles() -> None:
    with pytest.raises(ValueError, match="ends"):
        arrow(ends="middle")
    with pytest.raises(ValueError, match="type"):
        arrow(type="hollow")
    with pytest.raises(ValueError, match=r"0\.\.90"):
        arrow(angle=120)


def test_arrow_head_geometry_is_symmetric_about_the_shaft() -> None:
    tip = (10.0, 10.0)
    back = (0.0, 10.0)  # 切向朝 +x
    b1, b2 = head_geometry(*tip, *back, length_pt=4.0, angle=30.0)
    assert b1[1] != b2[1]
    # 两支对称于轴线 y = 10，且到 tip 的距离都是 length。
    assert (b1[1] - 10.0) == pytest.approx(-(b2[1] - 10.0))
    for point in (b1, b2):
        assert math.hypot(point[0] - tip[0], point[1] - tip[1]) == pytest.approx(4.0)


def test_tech_arrow_params_are_part_of_the_ir_wire_format() -> None:
    # 参数进了 NODE_SPECS：校验、编码、解码都从这张表派生。
    for kind in (ir.NodeKind.SEGMENTS, ir.NodeKind.POLYLINE, ir.NodeKind.CURVE):
        names = {spec.name for spec in ir.NODE_SPECS[kind].params}
        assert {"arrow", "arrow_length", "arrow_angle", "arrow_type"} <= names
    node = ir.Node(
        ir.NodeKind.SEGMENTS,
        bufs={"segments": ir.f32([[0.0, 0.0, 1.0, 1.0]])},
        params={"arrow": "last", "arrow_length": 12.0},
    )
    assert node.params["arrow"] == ir.ArrowEnds.LAST
    with pytest.raises(ir.IRValidationError, match="不认识"):
        ir.Node(
            ir.NodeKind.SEGMENTS,
            bufs={"segments": ir.f32([[0.0, 0.0, 1.0, 1.0]])},
            params={"arrow": "middle"},
        )


# ---------------------------------------------------------------------------
# 横向自动探测（SIL-715 #4 / #5）
# ---------------------------------------------------------------------------


def test_boxplot_infers_horizontal_from_column_types() -> None:
    nodes = _draw(
        ggplot(
            _table(cls=["a", "a", "b", "b"], v=[1.0, 2.0, 3.0, 4.0]),
            aes(y="cls", x="v"),
        )
        + geom_boxplot()
    )
    build = build_plot(
        ggplot(_table(cls=["a", "a", "b", "b"], v=[1.0, 2.0, 3.0, 4.0]), aes(y="cls", x="v"))
        + geom_boxplot()
    )
    assert bool(np.all(np.asarray(build.layers[0].data.column("flipped_aes").values)))
    polygons = [node for node in nodes if node.kind.value == "polygon"]
    assert polygons
    box = np.asarray(polygons[0].bufs["points"])
    # 横向：长度轴在 x（1..2 的箱比 3..4 的箱靠左），类别轴在 y。
    assert box[:, 0].min() != box[:, 0].max()


def test_area_does_not_infer_horizontal_upstream_rule() -> None:
    # 上游 `GeomArea` / `StatAlign` 都传 `ambiguous = TRUE`：没有 explicit
    # orientation 时永远竖向（README 的 SIL-715 #4 口径）。
    build = build_plot(
        ggplot(_table(cls=["a", "b", "c"], v=[1.0, 3.0, 2.0]), aes(y="cls", x="v"))
        + geom_area(stat="identity")
    )
    data = build.layers[0].data
    if "flipped_aes" in data:
        assert not bool(np.any(np.asarray(data.column("flipped_aes").values)))


def test_area_horizontal_requires_explicit_orientation() -> None:
    build = build_plot(
        ggplot(_table(cls=["a", "b", "c"], v=[1.0, 3.0, 2.0]), aes(y="cls", x="v"))
        + geom_area(stat="identity", orientation="y")
    )
    data = build.layers[0].data
    assert bool(np.all(np.asarray(data.column("flipped_aes").values)))


# ---------------------------------------------------------------------------
# raster / PNG
# ---------------------------------------------------------------------------


def test_raster_draws_one_bmp_node_with_blob_and_interpolate_flag() -> None:
    nodes = _draw(
        ggplot(
            _table(
                x=[0.25, 0.75, 0.25, 0.75],
                y=[0.25, 0.25, 0.75, 0.75],
                f=["p", "q", "q", "p"],
            ),
            aes(x="x", y="y", fill="f"),
        )
        + geom_raster(interpolate=False)
    )
    raster = [node for node in nodes if node.kind.value == "raster"]
    assert len(raster) == 1
    assert raster[0].params["interpolate"] is False
    assert raster[0].params["width"] == 2
    assert raster[0].params["height"] == 2


def test_png_encoder_is_a_valid_deterministic_rgba_png() -> None:
    from ggcore.png import encode_rgba

    pixels = np.zeros((2, 3, 4), dtype=np.uint8)
    pixels[..., 3] = 255
    first = encode_rgba(3, 2, pixels)
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    assert encode_rgba(3, 2, pixels) == first
    with pytest.raises(ValueError, match="形状"):
        encode_rgba(2, 2, pixels)


def test_raster_requires_even_spacing_and_warns() -> None:
    from ggcore.build import BuildWarning

    with pytest.warns(BuildWarning, match="uneven"):
        build_plot(
            ggplot(_table(x=[0.1, 0.3, 0.8], y=[0.5, 0.5, 0.5]), aes(x="x", y="y")) + geom_raster()
        )


# ---------------------------------------------------------------------------
# ribbon / blank / map / errorbar / rug
# ---------------------------------------------------------------------------


def test_ribbon_polygon_is_a_single_ring() -> None:
    nodes = _draw(
        ggplot(
            _table(
                x=[0.1, 0.3, 0.5],
                lo=[0.1, 0.2, 0.15],
                hi=[0.4, 0.5, 0.45],
            ),
            aes(x="x", ymin="lo", ymax="hi"),
        )
        + geom_ribbon(colour="#333333")
    )
    polygon = next(node for node in nodes if node.kind.value == "polygon")
    ids = np.asarray(polygon.bufs["id"])
    # 上沿 3 点 + 下沿 3 点，同一个 id → 一条闭合环（不是两条子路径）。
    assert len(set(ids.tolist())) == 1
    assert int(np.asarray(polygon.bufs["points"]).shape[0]) == 6


def test_blank_draws_nothing() -> None:
    assert _draw(ggplot(_table(x=[0.1, 0.9], y=[0.2, 0.8]), aes(x="x", y="y")) + geom_blank()) == []


def test_map_draws_one_polygon_per_id() -> None:
    nodes = _draw(
        ggplot(_table(map_id=["a", "b"]), aes(map_id="map_id"))
        + geom_map(
            map={
                "x": [0.0, 0.4, 0.4, 0.0, 0.5, 0.9, 0.9, 0.5],
                "y": [0.0, 0.0, 0.4, 0.4, 0.5, 0.5, 0.9, 0.9],
                "id": ["a", "a", "a", "a", "b", "b", "b", "b"],
            }
        )
    )
    assert len([node for node in nodes if node.kind.value == "polygon"]) == 2


def test_errorbar_is_one_polyline_per_row_with_nan_gaps() -> None:
    nodes = _draw(
        ggplot(
            _table(x=[0.3, 0.7], y=[0.5, 0.45], lo=[0.2, 0.3], hi=[0.8, 0.7]),
            aes(x="x", y="y", ymin="lo", ymax="hi"),
        )
        + geom_errorbar(width=0.2)
    )
    lines = [node for node in nodes if node.kind.value == "polyline"]
    assert len(lines) == 2
    points = np.asarray(lines[0].bufs["points"])
    assert points.shape[0] == 8
    assert np.isnan(points[2]).all() and np.isnan(points[5]).all()


def test_rug_draws_one_segment_group_per_side() -> None:
    nodes = _draw(
        ggplot(_table(x=[0.2, 0.8], y=[0.3, 0.9]), aes(x="x", y="y"))
        + geom_rug(sides="bl", length=0.04)
    )
    segs = [node for node in nodes if node.kind.value == "segments"]
    assert len(segs) == 2


def test_abline_draws_one_segment_per_unique_intercept() -> None:
    nodes = _draw(ggplot() + geom_abline(slope=1, intercept=0.1))
    segments = np.asarray(nodes[0].bufs["segments"])
    # R 的 `unique0(data)`：一条斜率/截距只画一遍。
    assert segments.shape[0] == 1
    assert segments[0][0] < segments[0][2]


def test_abline_accepts_a_vector_of_slopes() -> None:
    nodes = _draw(ggplot() + geom_abline(slope=[1, -1], intercept=[0.0, 0.5]))
    assert np.asarray(nodes[0].bufs["segments"]).shape[0] == 2


def test_normalised_line_does_not_depend_on_layer_data_size() -> None:
    plot = ggplot(_table(xmin=[0.1, 0.5], xmax=[0.4, 0.8], ymin=[0.1, 0.2], ymax=[0.5, 0.6]))
    first = _draw(plot + geom_abline(slope=1, intercept=0.1))
    assert np.asarray(first[0].bufs["segments"]).shape[0] == 1


def test_every_new_geom_has_a_renderer() -> None:
    for name in (
        "abline",
        "hline",
        "vline",
        "segment",
        "curve",
        "spoke",
        "rect",
        "tile",
        "raster",
        "polygon",
        "ribbon",
        "step",
        "errorbar",
        "errorbarh",
        "linerange",
        "pointrange",
        "crossbar",
        "blank",
        "rug",
        "map",
    ):
        assert renderer_for(name).name == name


@pytest.mark.parametrize(
    "name,mapping",
    [
        ("segment", {"x": "x", "y": "y", "xend": "xend", "yend": "yend", "colour": "g"}),
        ("rect", {"xmin": "xmin", "xmax": "xmax", "ymin": "ymin", "ymax": "ymax", "fill": "g"}),
        ("polygon", {"x": "x", "y": "y", "group": "g", "fill": "g"}),
        ("tile", {"x": "x", "y": "y", "fill": "g"}),
        ("raster", {"x": "x", "y": "y", "fill": "g"}),
        ("linerange", {"x": "x", "ymin": "lo", "ymax": "hi", "colour": "g"}),
        ("errorbar", {"x": "x", "y": "y", "ymin": "lo", "ymax": "hi", "colour": "g"}),
        ("crossbar", {"x": "x", "y": "y", "ymin": "lo", "ymax": "hi", "fill": "g"}),
        ("rug", {"x": "x", "y": "y", "colour": "g"}),
        ("blank", {"x": "x", "y": "y", "colour": "g"}),
    ],
)
def test_legend_keys_exist_for_the_new_geoms(name, mapping) -> None:
    """图例 key 的假数据必须能被各自的 `draw()` 吃下（R 的 `draw_key_*`）。

    映射一个离散美学就会触发 guide 的 `key_table()` 模板；模板 / 绘制缺一块都会在
    这里抛异常（SIL-737 的手测发现：polygon 缺 `project_xy`、raster 缺 x/y）。
    """
    import ggcore.plot as gg_plot
    from ggcore.geom.scene import scene_from_plot

    table = _table(
        x=[0.5],
        y=[0.5],
        xend=[0.9],
        yend=[0.9],
        xmin=[0.1],
        xmax=[0.4],
        ymin=[0.1],
        ymax=[0.9],
        lo=[0.1],
        hi=[0.9],
        g=["a"],
    )
    plot = ggplot(table, aes(**mapping)) + getattr(gg_plot, f"geom_{name}")()
    assert scene_from_plot(plot, width_in=4.0, height_in=3.0) is not None


def test_scales_are_registered_for_the_new_cases() -> None:
    # 只是防呆：这些 case 依赖的连续标度别在重构里丢掉。
    from ggcore import registry

    for name in ("x_continuous", "y_continuous", "fill_discrete", "colour_discrete"):
        assert name in registry.registered("scale")


_ = scale_x_continuous, scale_y_continuous
