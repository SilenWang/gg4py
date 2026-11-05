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
