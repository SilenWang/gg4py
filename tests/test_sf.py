"""M3-2：空间数据（`ggcore.sf` / `stat_sf` / `coord_sf` / `coord_map`）。

对拍口径：

- EPSG:3347 的期望值来自上游 `test-coord_sf.R` 的 `sf_transform_xy()` 断言
  （Charlotte / Raleigh / Greensboro）；
- `pretty()` / `format()` 的期望值来自 sf 的 `R/graticule.R`（`degreeLabelsEW` /
  `degreeLabelsNS`）与 `coord_sf/sf-polygons.svg` 的实际标签；
- 端到端的面板范围 / 比例用 `build_plot()` 断言，与 R 的 `panel_params` 同口径。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ggcore import registry
from ggcore.build import build_plot
from ggcore.coord import CoordError, MapCoord, SfCoord, coord_from_component
from ggcore.geom.sf import sf_legend_type, sf_type_of_rows
from ggcore.plot import aes, coord_cartesian, coord_map, coord_sf, geom_sf, ggplot
from ggcore.sf import (
    CRS,
    Geometry,
    SfError,
    bbox_of,
    format_vector,
    parse_wkt,
    point_on_surface,
    pretty,
    sf,
    st_crs,
    st_geometrycollection,
    st_graticule,
    st_linestring,
    st_multilinestring,
    st_multipoint,
    st_point,
    st_polygon,
    st_transform_xy,
)


def _nc_polygon(crs: object = 4326) -> Geometry:
    ring = [
        (-81.473, 36.234),
        (-81.741, 36.392),
        (-81.67, 36.59),
        (-81.345, 36.573),
        (-81.266, 36.437),
        (-81.24, 36.365),
        (-81.473, 36.234),
    ]
    return st_polygon(ring, crs=crs)


# ---------------------------------------------------------------------------
# CRS 与投影
# ---------------------------------------------------------------------------


def test_st_crs_accepts_the_ported_systems() -> None:
    assert st_crs(4326) == CRS("longlat", "4326")
    assert st_crs("OGC:CRS84") == CRS("crs84", "OGC:CRS84")
    assert st_crs("EPSG:3857") == CRS("merc", "EPSG:3857")
    assert st_crs("EPSG:3347") == CRS("lcc3347", "EPSG:3347")
    assert st_crs(None) is None


def test_st_crs_rejects_unsupported_systems() -> None:
    with pytest.raises(SfError, match="不支持的 CRS"):
        st_crs("EPSG:27700")
    with pytest.raises(SfError, match="只接受"):
        st_crs(object())


def test_epsg3347_matches_the_r_fixture() -> None:
    # test-coord_sf.R: sf_transform_xy(data, 3347, 4326)
    cities_x = [-80.843, -78.639, -79.792]
    cities_y = [35.227, 35.772, 36.073]
    out_x, out_y = st_transform_xy(cities_x, cities_y, 3347, 4326)
    assert np.allclose(out_x, [7275499, 7474260, 7357835], atol=10)
    assert np.allclose(out_y, [-60169, 44384, 57438], atol=10)
    # 反变换回经纬度
    back_x, back_y = st_transform_xy(out_x, out_y, 4326, 3347)
    assert np.allclose(back_x, cities_x, atol=1e-6)
    assert np.allclose(back_y, cities_y, atol=1e-6)


def test_web_mercator_roundtrip_and_identity() -> None:
    lon = np.array([-81.5, 0.0, 12.0])
    lat = np.array([36.4, 0.0, -33.0])
    x, y = st_transform_xy(lon, lat, 3857, 4326)
    assert np.allclose(x, lon * 111319.49079327358, rtol=1e-12)
    back_x, back_y = st_transform_xy(x, y, 4326, 3857)
    assert np.allclose(back_x, lon, atol=1e-9)
    assert np.allclose(back_y, lat, atol=1e-9)
    same_x, same_y = st_transform_xy(lon, lat, 4326, 4326)
    assert np.array_equal(same_x, lon) and np.array_equal(same_y, lat)


# ---------------------------------------------------------------------------
# 几何
# ---------------------------------------------------------------------------


def test_geometry_bbox_and_transform() -> None:
    polygon = _nc_polygon()
    xmin, ymin, xmax, ymax = polygon.bbox()
    assert (xmin, ymin) == pytest.approx((-81.741, 36.234))
    assert (xmax, ymax) == pytest.approx((-81.24, 36.59))
    projected = polygon.transform(3857)
    assert projected.crs == st_crs(3857)
    assert projected.bbox()[0] < -9_000_000
    points = st_multipoint([(0, 0), (1, 1)])
    assert bbox_of([points, st_point(2, 3)]) == (0.0, 0.0, 2.0, 3.0)


def test_geometry_types_map_to_sf_groups() -> None:
    assert st_point(0, 0).sf_type == "point"
    assert st_multipoint([(0, 0)]).sf_type == "point"
    assert st_linestring([(0, 0), (1, 1)]).sf_type == "line"
    assert st_multilinestring([[(0, 0), (1, 1)]]).sf_type == "line"
    assert _nc_polygon().sf_type == "other"
    collection = st_geometrycollection([st_point(0, 0), st_point(1, 1)])
    assert collection.sf_type == "collection"
    assert collection.geometry_type == "GEOMETRYCOLLECTION"


def test_wkt_parsing() -> None:
    point = parse_wkt("POINT (1 2)", crs=4326)
    assert point.kind == "point" and point.parts == ((1.0, 2.0),)
    line = parse_wkt("LINESTRING (0 0, 1 1, 2 2)")
    assert line.kind == "linestring" and len(line.parts) == 3


def test_wkt_polygon_rings_and_holes() -> None:
    """SIL-860：`POLYGON` 的环是「点的序列」，不是一维数字序列。"""
    polygon = parse_wkt("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 2 1, 2 2, 1 2, 1 1))")
    assert polygon.kind == "polygon"
    assert len(polygon.parts) == 2  # 外环 + 洞
    assert polygon.parts[0] == ((0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0))
    assert polygon.parts[1][0] == (1.0, 1.0)
    # 与 `st_polygon()` 造出来的几何同构（两条入口口径一致）
    assert (
        polygon.parts
        == st_polygon(
            [
                [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)],
                [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)],
            ]
        ).parts
    )


def test_wkt_multipolygon_nests_rings_per_polygon() -> None:
    multipolygon = parse_wkt(
        "MULTIPOLYGON (((0 0, 1 0, 1 1, 0 0)), ((2 2, 3 2, 3 3, 2 2), (2.2 2.2, 2.4 2.2, 2.4 2.4, "
        "2.2 2.2)))"
    )
    assert multipolygon.kind == "multipolygon"
    assert len(multipolygon.parts) == 2
    assert [len(polygon) for polygon in multipolygon.parts] == [1, 2]
    assert multipolygon.parts[1][1][0] == (2.2, 2.2)
    assert multipolygon.bbox() == pytest.approx((0.0, 0.0, 3.0, 3.0))


def test_wkt_parses_every_supported_kind() -> None:
    multipoint = parse_wkt("MULTIPOINT (1 2, 3 4)")
    assert multipoint.parts == ((1.0, 2.0), (3.0, 4.0))
    # WKT 也允许每个点各自带括号
    assert parse_wkt("MULTIPOINT ((1 2), (3 4))").parts == multipoint.parts
    multilinestring = parse_wkt("MULTILINESTRING ((0 0, 1 1), (2 2, 3 3))")
    assert multilinestring.parts == (((0.0, 0.0), (1.0, 1.0)), ((2.0, 2.0), (3.0, 3.0)))
    collection = parse_wkt("GEOMETRYCOLLECTION (POINT (1 2), LINESTRING (0 0, 1 1))")
    assert collection.kind == "geometrycollection"
    assert [item.kind for item in collection.parts] == ["point", "linestring"]
    assert parse_wkt("POLYGON EMPTY").is_empty


def test_wkt_degenerate_ring_is_an_explicit_error() -> None:
    with pytest.raises(SfError, match="至少要 3 个点"):
        parse_wkt("POLYGON ((0 0, 1 1))")
    with pytest.raises(SfError, match="至少要 3 个点"):
        parse_wkt("MULTIPOLYGON (((0 0, 1 1)))")


def test_sf_accepts_wkt_geometry_and_attaches_the_crs() -> None:
    data = sf({}, geometry=["POLYGON ((0 0, 1 0, 1 1, 0 0))", "POINT (2 3)"], crs=4326)
    polygon, point = data.column("geometry").values.tolist()
    assert polygon.kind == "polygon" and polygon.crs == st_crs(4326)
    assert point.kind == "point" and point.crs == st_crs(4326)


def test_point_on_surface_of_a_polygon_is_inside() -> None:
    polygon = _nc_polygon()
    x, y = point_on_surface(polygon)
    # 多边形是凸的（除闭合点外按顺序围成），重心落在 bbox 内且靠近中部
    assert -81.741 < x < -81.24
    assert 36.234 < y < 36.59


# ---------------------------------------------------------------------------
# R 的 pretty() / format()
# ---------------------------------------------------------------------------


def test_pretty_matches_r_for_the_graticule_boxes() -> None:
    assert pretty(-0.05, 1.05, 6) == pytest.approx([-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2])
    assert pretty(36.2162, 36.6078, 6) == pytest.approx(
        [36.2, 36.25, 36.3, 36.35, 36.4, 36.45, 36.5, 36.55, 36.6, 36.65]
    )


def test_format_vector_pads_with_leading_spaces() -> None:
    assert format_vector([-0.2, 0.0, 0.2, 1.0]) == ["-0.2", " 0.0", " 0.2", " 1.0"]
    assert format_vector([36.25, 36.3], digits=10) == ["36.25", "36.30"]


# ---------------------------------------------------------------------------
# graticule
# ---------------------------------------------------------------------------


def test_graticule_labels_and_clipping_for_longlat() -> None:
    lines = st_graticule((-81.76605, 36.2162, -81.21495, 36.6078), 4326)
    y_labels = [line.label for line in lines if line.type == "N"]
    assert "36.25°N" in y_labels and "36.60°N" in y_labels
    assert "36.20°N" not in y_labels  # 被裁剪在面板外
    x_labels = [line.label for line in lines if line.type == "E"]
    assert "81.7°W" in x_labels and "81.3°W" in x_labels
    assert all(line.degree for line in lines if line.type == "E")


def test_planar_graticule_uses_plain_numbers() -> None:
    lines = st_graticule((-0.05, 0.95, 1.05, 2.05), None)
    assert any(line.label == " 0.0" for line in lines if line.type == "E")
    assert any(line.label == "1.0" for line in lines if line.type == "N")


# ---------------------------------------------------------------------------
# coord_sf
# ---------------------------------------------------------------------------


def test_coord_sf_panel_params_match_the_r_bbox() -> None:
    data = sf({"NAME": ["ashe"]}, geometry=[_nc_polygon()])
    plot = ggplot(data) + geom_sf() + coord_sf()
    build = build_plot(plot)
    params = build.panel_params
    assert isinstance(build.coord, SfCoord)
    assert params.sf.crs == st_crs(4326)
    # R: x 范围 -81.741..-81.24 与 36.234..36.59 各 5% expand
    assert params.x_range == pytest.approx((-81.76605, -81.21495))
    assert params.y_range == pytest.approx((36.2162, 36.6078))
    # 经纬度的比例是 1/cos(中心纬度)：aspect = ratio × y 跨度 / x 跨度
    mid = (params.y_range[0] + params.y_range[1]) / 2.0
    assert params.aspect_ratio == pytest.approx(
        (params.y_range[1] - params.y_range[0])
        / (params.x_range[1] - params.x_range[0])
        / math.cos(math.radians(mid))
    )
    labels = dict(params.sf.ticks["left"]).values()
    assert "36.25°N" in labels


def test_coord_sf_labels_follow_label_graticule() -> None:
    data = sf({}, geometry=[_nc_polygon(4326).transform(3347)])
    plot = ggplot(data) + geom_sf() + coord_sf(label_graticule="NSWE")
    params = build_plot(plot).panel_params
    assert params.sf.ticks["top"]
    assert params.sf.ticks["right"]
    assert params.sf.ticks["bottom"]
    assert params.sf.ticks["left"]


def test_coord_sf_breaks_null_removes_the_axis() -> None:
    data = sf({}, geometry=[_nc_polygon()])
    plot = ggplot(data) + geom_sf() + coord_sf() + registry.scale_x_continuous(breaks=None)
    ticks = build_plot(plot).panel_params.sf.ticks
    assert ticks["bottom"] == ()


def test_geom_sf_requires_coord_sf() -> None:
    data = sf({}, geometry=[st_point(0, 0)])
    from ggcore.geom.scene import scene_from_plot

    plot = ggplot(data) + geom_sf() + coord_cartesian()
    with pytest.raises(Exception, match="coord_sf"):
        scene_from_plot(plot)


@pytest.mark.parametrize(
    "geometry",
    [
        st_point(-81.5, 36.3, crs=4326),
        st_multipoint([(-81.5, 36.3), (-80.5, 36.8)], crs=4326),
        st_geometrycollection([st_point(-81.5, 36.3), st_point(-80.5, 36.8)], crs=4326),
    ],
    ids=["point", "multipoint", "geometrycollection"],
)
def test_geom_sf_draws_points_that_carry_a_crs(geometry: Geometry) -> None:
    """SIL-860：`_draw_points()` 重建 multipoint 时不能丢几何的 CRS。"""
    from ggcore import ir
    from ggcore.geom.scene import scene_from_plot

    plot = ggplot(sf({}, geometry=[geometry])) + geom_sf() + coord_sf()
    scene = scene_from_plot(plot, width_in=4, height_in=3)
    ir.encode(scene)  # `ir.encode()` 正常
    points = [node for node in ir.walk(scene.root) if node.kind is ir.NodeKind.POINTS]
    assert points, "点层应当产出 points 节点"
    assert sum(node.bufs["points"].shape[0] for node in points) == len(geometry.vertices())


def test_unsupported_projection_is_an_explicit_error() -> None:
    with pytest.raises(CoordError, match="尚未实现"):
        coord_from_component(coord_map("gilbert"))


# ---------------------------------------------------------------------------
# stat_sf / stat_sf_coordinates 与图例类型
# ---------------------------------------------------------------------------


def test_stat_sf_writes_the_bbox_columns() -> None:
    from ggcore.build import compute_aesthetics
    from ggcore.sf_stat import compute_sf

    data = sf({"NAME": ["ashe"]}, geometry=[_nc_polygon()])
    plot = ggplot(data) + geom_sf()
    layer = plot.layers[0]
    aesthetics = compute_aesthetics(plot, layer)
    table = compute_sf(aesthetics.table)
    assert table.column("xmin").values[0] == pytest.approx(-81.741)
    assert table.column("ymax").values[0] == pytest.approx(36.59)


def test_sf_coordinates_puts_one_point_per_geometry() -> None:
    from ggcore.sf_stat import compute_sf_coordinates

    data = sf({}, geometry=[_nc_polygon(), st_point(0, 0)])
    table = compute_sf_coordinates(data)
    assert table.nrows == 2
    x = table.column("x").values
    y = table.column("y").values
    assert -81.741 < float(x[0]) < -81.24
    assert (float(x[1]), float(y[1])) == (0.0, 0.0)


def test_legend_type_follows_the_geometry_type() -> None:
    points = sf({}, geometry=[st_point(0, 0), st_point(1, 1)])
    lines = sf({}, geometry=[st_linestring([(0, 0), (1, 1)])])
    polygons = sf({}, geometry=[_nc_polygon()])
    mixed = sf({}, geometry=[st_point(0, 0), _nc_polygon()])
    assert sf_type_of_rows(points) == "point"
    assert sf_type_of_rows(lines) == "line"
    assert sf_type_of_rows(polygons) == "other"
    assert sf_type_of_rows(mixed) == "other"
    assert sf_legend_type(points) == "point"
    assert sf_legend_type(lines) == "line"
    assert sf_legend_type(polygons) == "other"


def test_coord_map_uses_the_projected_aspect() -> None:
    from ggcore.map_data import map_frame
    from ggcore.plot import geom_polygon, labs
    from ggio.frame import to_column_table

    data = to_column_table(map_frame("usa", "."))
    plot = (
        ggplot(data, aes(x="x", y="y", group="group"))
        + geom_polygon(fill=None)
        + coord_map("mercator")
        + labs(title="usa")
    )
    build = build_plot(plot)
    assert isinstance(build.coord, MapCoord)
    assert build.coord.name == "map"
    # 美国本土的 mercator 投影：高/宽约 0.54（R 的 usa-mercator 快照同量级）
    assert 0.3 < build.panel_params.aspect_ratio < 0.8


# ---------------------------------------------------------------------------
# mapproj 投影核（SIL-857）：mercator / azequalarea
# ---------------------------------------------------------------------------
#
# 期望值全部由 `mapproj` 1.2.12（CRAN，R 4.5.3）的 `mapproject()` 逐点导出：
#
#     mapproject(x, y, projection = "mercator", orientation = c(90, 0, 175.6))
#     mapproject(x, y, projection = "azequalarea", orientation = c(-36.92, 174.6, 0))
#
# 面板比例是 `CoordMap$setup_panel_params()` 同一套 50×50 网格在 nz 的范围上
# 投影后的 `diff(y.proj) / diff(x.proj)`。

_MAPPROJ_LON = np.array([174.6, 176.0, 178.0, 172.7433, 179.5])
_MAPPROJ_LAT = np.array([-36.92, -38.6, -41.63587, -34.39895, -40.5])


def test_mapproject_mercator_matches_mapproj() -> None:
    from ggcore.sf import mapproject

    px, py = mapproject(
        _MAPPROJ_LON, _MAPPROJ_LAT, projection="mercator", orientation=(90.0, 0.0, 175.6)
    )
    np.testing.assert_allclose(
        px,
        [-0.0174532925, 0.0069813170, 0.0418879020, -0.0498588207, 0.0680678408],
        rtol=0,
        atol=1e-9,
    )
    np.testing.assert_allclose(
        py,
        [-0.6942406031, -0.7313320322, -0.8006396915, -0.6400768580, -0.7743435388],
        rtol=0,
        atol=1e-9,
    )


def test_mapproject_azequalarea_matches_mapproj() -> None:
    from ggcore.sf import mapproject

    px, py = mapproject(
        _MAPPROJ_LON,
        _MAPPROJ_LAT,
        projection="azequalarea",
        orientation=(-36.92, 174.6, 0.0),
    )
    np.testing.assert_allclose(
        px,
        [0.0, 0.0135037528, 0.0313770030, -0.0189099322, 0.0459756644],
        rtol=0,
        atol=1e-9,
    )
    np.testing.assert_allclose(
        py,
        [0.0, -0.0208327860, -0.0587584655, 0.0309292582, -0.0453810594],
        rtol=0,
        atol=1e-9,
    )


def test_mapproject_orientation_puts_the_pole_at_the_origin() -> None:
    from ggcore.sf import mapproject

    # `orientation = c(lat, lon, 0)`：该经纬度就是投影平面原点（`azequalarea`）。
    px, py = mapproject(
        np.array([174.6]),
        np.array([-36.92]),
        projection="azequalarea",
        orientation=(-36.92, 174.6, 0),
    )
    assert px[0] == pytest.approx(0.0, abs=1e-12)
    assert py[0] == pytest.approx(0.0, abs=1e-12)
    # mercator 的缺省极点在北：`orientation[2]` 只平移经度，纬度方向仍是 atanh。
    centered, _ = mapproject(
        np.array([174.6, 175.6]),
        np.array([-38.6, -38.6]),
        projection="mercator",
        orientation=(90.0, 0.0, 175.6),
    )
    assert centered[1] == pytest.approx(0.0, abs=1e-12)
    assert centered[0] < 0.0


def test_mapproject_clips_at_the_projection_domain() -> None:
    from ggcore.sf import mapproject

    # mercator：`|lat| > 80°` 返回 NA（`Xmercator` 的截断），80° 以内照常。
    lats = np.array([0.0, 45.0, 85.0, -85.0, 80.0])
    _, py = mapproject(np.zeros(5), lats, projection="mercator", orientation=(90.0, 0.0, 0.0))
    assert np.isnan(py[2]) and np.isnan(py[3])
    assert np.isfinite(py[[0, 1, 4]]).all()
    assert py[1] == pytest.approx(0.8813735870, abs=1e-9)
    # azequalarea 在两个极区都有定义（南极为 sqrt 2 的半径），不按 80° 截断。
    px, py = mapproject(
        np.array([0.0, 0.0, 0.0, 180.0]),
        np.array([0.0, 90.0, -90.0, 0.0]),
        projection="azequalarea",
        orientation=(90.0, 0.0, 0.0),
    )
    np.testing.assert_allclose(px, 0.0, atol=1e-12)
    np.testing.assert_allclose(py, [-1.0, 0.0, -math.sqrt(2.0), 1.0], atol=1e-9)


def test_mapproject_rejects_unknown_projections_and_bad_parameters() -> None:
    from ggcore.sf import mapproj_projections, mapproject

    assert mapproj_projections() == ("mercator", "azequalarea")
    with pytest.raises(SfError, match="尚未实现"):
        mapproject(np.array([0.0]), np.array([0.0]), projection="gilbert")
    with pytest.raises(SfError, match="需要 0 个投影参数"):
        mapproject(np.array([0.0]), np.array([0.0]), projection="azequalarea", params=(1.0,))
    with pytest.raises(SfError, match="orientation"):
        mapproject(np.array([0.0]), np.array([0.0]), orientation=(90.0, 0.0))


def test_coord_map_panel_aspect_matches_the_projection() -> None:
    from ggcore.sf import mapproject

    # nz 的 5% 展开范围（R：expand_range(range(nz$long/lat))）。
    x_range = (172.3964073181, 178.8565071106)
    y_range = (-41.9977178574, -34.0371065140)
    grid = np.linspace(0.0, 1.0, 50)
    xs = x_range[0] + (x_range[1] - x_range[0]) * np.repeat(grid, 50)
    ys = y_range[0] + (y_range[1] - y_range[0]) * np.tile(grid, 50)

    def aspect(projection: str, orientation: tuple[float, float, float]) -> float:
        px, py = mapproject(xs, ys, projection=projection, orientation=orientation)
        return float(np.nanmax(py) - np.nanmin(py)) / float(np.nanmax(px) - np.nanmin(px))

    assert aspect("mercator", (90.0, 0.0, (x_range[0] + x_range[1]) / 2.0)) == pytest.approx(
        1.566954678373, abs=1e-9
    )
    assert aspect("azequalarea", (-36.92, 174.6, 0.0)) == pytest.approx(1.500304927084, abs=1e-9)


def test_coord_map_azequalarea_is_non_linear_and_builds() -> None:
    from ggcore.plot import geom_hline, geom_path, labs
    from ggio.frame import to_column_table

    data = to_column_table({"x": [174.0, 176.0, 178.0], "y": [-35.0, -38.0, -41.0]})
    plot = (
        ggplot(data, aes(x="x", y="y"))
        + geom_path()
        + geom_hline(yintercept=-38.6)
        + coord_map(projection="azequalarea", orientation=(-36.92, 174.6, 0))
        + labs(title="nz")
    )
    build = build_plot(plot)
    assert build.panel_params.map_geom is not None
    assert build.panel_params.map_geom.projection == "azequalarea"
    # `CoordMap$is_linear()` 是 FALSE：路径 / 参考线必须走 `coord_munch()`。
    assert build.panel_params.is_linear is False
    assert build.panel_params.aspect_ratio > 0
