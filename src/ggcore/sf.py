"""空间数据（M3-2）：几何对象、CRS、投影、graticule。

这个模块是 ggplot2 4.0.3 空间能力的**纯 Python 内核**（X1：只 import 标准库 +
numpy），不依赖 sf / PROJ / pyproj：

- :class:`Geometry`：Simple Features 的几何（POINT / MULTIPOINT / LINESTRING /
  MULTILINESTRING / POLYGON / MULTIPOLYGON / GEOMETRYCOLLECTION），坐标是
  `(x, y)` 元组，`crs` 挂在几何上（与 sf 的 `sfc` 同口径：一列几何共享一个 CRS）。
- :func:`st_crs` / :class:`CRS`：本仓实现 EPSG:4326（经纬度）、EPSG:3857
  （Web Mercator）、EPSG:3347（NAD83 / Statistics Canada Lambert）。其它 CRS 报
  :class:`SfError` 并列出支持范围——不静默当 identity 画错图。
- :func:`st_graticule`：`sf::st_graticule()` 的移植（经纬网 + 起止点 / 角度 /
  度数标签），`coord_sf()` 的轴标签与面板网格都吃它。
- :func:`st_transform_xy` / :func:`st_transform_geometry`：投影变换。
- :func:`point_on_surface`：`stat_sf_coordinates()` 的缺省位置（多边形取面积
  重心；点/线各取自身的一个代表点）。

R 侧口径见 `R/coord-sf.R`、`R/stat-sf.R`、`R/geom-sf.R` 与 sf 包的
`R/graticule.R`；对应说明写在 `docs/notes/sf.md`。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.data import Column, ColumnTable

__all__ = [
    "CRS",
    "Geometry",
    "GraticuleLine",
    "SfError",
    "bbox_of",
    "calc_limits_bbox",
    "degree_label_ew",
    "degree_label_ns",
    "format_vector",
    "parse_wkt",
    "point_on_surface",
    "pretty",
    "sf",
    "st_crs",
    "st_geometrycollection",
    "st_graticule",
    "st_linestring",
    "st_multilinestring",
    "st_multipoint",
    "st_multipolygon",
    "st_point",
    "st_polygon",
    "st_sfc",
    "st_transform_geometry",
    "st_transform_xy",
    "transform_geometry",
]

#: `sf_types`（R/geom-sf.R）：几何类型 → geom_sf 的缺省美学分组。
SF_TYPES: dict[str, str] = {
    "GEOMETRY": "other",
    "POINT": "point",
    "LINESTRING": "line",
    "POLYGON": "other",
    "MULTIPOINT": "point",
    "MULTILINESTRING": "line",
    "MULTIPOLYGON": "other",
    "GEOMETRYCOLLECTION": "collection",
}

_GEOMETRY_KINDS = (
    "point",
    "multipoint",
    "linestring",
    "multilinestring",
    "polygon",
    "multipolygon",
    "geometrycollection",
)

_WGS84_A = 6378137.0
_WGS84_F = 1.0 / 298.257223563
_GRS80_F = 1.0 / 298.257222101


class SfError(ValueError):
    """空间数据的显式错误（不支持的 CRS / 几何 / 空 bbox）。"""


# ---------------------------------------------------------------------------
# CRS
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CRS:
    """坐标参考系：`spec` 是本模块认得的那几个规范名。

    `kind` 只有三档：`longlat`（经纬度，identity）、`merc`（球面 Web Mercator）、
    `lcc3347`（NAD83 / Statistics Canada Lambert）。`code` 是给报错文案看的
    原文（`"EPSG:3347"` 这类）。
    """

    spec: str
    code: str = ""

    @property
    def is_longlat(self) -> bool:
        return self.spec in ("longlat", "crs84")

    @property
    def is_projected(self) -> bool:
        return not self.is_longlat

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"CRS({self.code or self.spec!r})"


_LONG_LAT_ALIASES = frozenset(
    {
        "4326",
        "epsg:4326",
        "4269",
        "epsg:4269",
        "4267",
        "epsg:4267",
        "crs84",
        "ogc:crs84",
        "wgs84",
        "nad83",
    }
)
_MERC_ALIASES = frozenset({"3857", "epsg:3857", "900913", "epsg:900913", "webmercator"})
_LCC3347_ALIASES = frozenset(
    {"3347", "epsg:3347", "statcan-lcc", "nad83 / statistics canada lambert"}
)


def st_crs(value: Any) -> CRS | None:
    """`sf::st_crs()` 的极小子集：EPSG 号 / `"EPSG:xxxx"` / `+proj=` 字符串。"""
    if value is None:
        return None
    if isinstance(value, CRS):
        return value
    if isinstance(value, bool):
        raise SfError(f"CRS 不接受布尔值：{value!r}")
    if isinstance(value, (int, np.integer)):
        return st_crs(str(int(value)))
    if isinstance(value, float) and math.isfinite(value) and value == int(value):
        return st_crs(str(int(value)))
    if not isinstance(value, str):
        raise SfError(f"CRS 只接受 EPSG 号 / 字符串 / CRS，收到 {type(value).__name__}")
    text = value.strip()
    key = text.lower()
    if key in _LONG_LAT_ALIASES:
        return CRS("longlat" if key not in ("crs84", "ogc:crs84") else "crs84", text)
    if key in _MERC_ALIASES:
        return CRS("merc", text)
    if key in _LCC3347_ALIASES:
        return CRS("lcc3347", text)
    if key.startswith("+proj"):
        lowered = key.replace(" ", "")
        if "+proj=longlat" in lowered:
            return CRS("longlat", text)
        if "+proj=merc" in lowered:
            return CRS("merc", text)
        if "+proj=lcc" in lowered:
            # 只认 EPSG:3347 这一组参数（本仓唯一需要的小比例尺 LCC）。
            if "+lat_1=49" in lowered and "+lat_2=77" in lowered and "+lon_0=-95" in lowered:
                return CRS("lcc3347", text)
    raise SfError(
        f"不支持的 CRS {value!r}：M3-2 实现了 EPSG:4326 / OGC:CRS84 / EPSG:3857 / "
        "EPSG:3347（+proj=lcc +lat_1=49 +lat_2=77 +lon_0=-95）；其余投影需要 PROJ，"
        "本仓不引入（X1），见 docs/notes/sf.md"
    )


# ---------------------------------------------------------------------------
# 几何
# ---------------------------------------------------------------------------


def _point(pair: Sequence[Any]) -> tuple[float, float]:
    values = tuple(pair)
    if len(values) < 2:
        raise SfError(f"坐标至少要有 x / y 两维，收到 {values!r}")
    return (float(values[0]), float(values[1]))


def _ring(points: Iterable[Sequence[Any]]) -> tuple[tuple[float, float], ...]:
    out = tuple(_point(item) for item in points)
    if len(out) < 3:
        raise SfError(f"多边形环至少要 3 个点，收到 {len(out)}")
    return out


@dataclass(frozen=True, slots=True)
class Geometry:
    """一个 Simple Feature 几何。`parts` 的嵌套层次由 `kind` 决定。"""

    kind: str
    parts: tuple[Any, ...]
    crs: CRS | None = None

    def __post_init__(self) -> None:
        if self.kind not in _GEOMETRY_KINDS:
            raise SfError(f"未知的几何类型 {self.kind!r}（支持：{', '.join(_GEOMETRY_KINDS)}）")

    # -- 元信息 -----------------------------------------------------------

    @property
    def geometry_type(self) -> str:
        return self.kind.upper()

    @property
    def sf_type(self) -> str:
        """`sf_types[st_geometry_type(x)]`：point / line / other / collection。"""
        return SF_TYPES.get(self.geometry_type, "other")

    @property
    def is_empty(self) -> bool:
        return len(self.parts) == 0

    def with_crs(self, crs: Any) -> Geometry:
        resolved = st_crs(crs)
        if self.kind == "geometrycollection":
            return replace(
                self,
                parts=tuple(
                    item.with_crs(resolved) if item.crs is None else item for item in self.parts
                ),
                crs=resolved,
            )
        return replace(self, crs=resolved)

    # -- 坐标 -------------------------------------------------------------

    def vertices(self) -> list[tuple[float, float]]:
        """全部 (x, y) 顶点（拍平；collection 递归）。"""
        out: list[tuple[float, float]] = []
        if self.kind in ("point", "multipoint"):
            out.extend(self.parts)
        elif self.kind == "linestring":
            out.extend(self.parts)
        elif self.kind == "multilinestring":
            for part in self.parts:
                out.extend(part)
        elif self.kind == "polygon":
            for ring in self.parts:
                out.extend(ring)
        elif self.kind == "multipolygon":
            for polygon in self.parts:
                for ring in polygon:
                    out.extend(ring)
        else:
            for item in self.parts:
                out.extend(item.vertices())
        return out

    def bbox(self) -> tuple[float, float, float, float]:
        """`(xmin, ymin, xmax, ymax)`；全是非有限值时抛 :class:`SfError`。"""
        points = [(x, y) for x, y in self.vertices() if math.isfinite(x) and math.isfinite(y)]
        if not points:
            raise SfError("几何没有有限坐标，无法计算 bbox")
        xs = [item[0] for item in points]
        ys = [item[1] for item in points]
        return (min(xs), min(ys), max(xs), max(ys))

    def map_coords(self, func: Any) -> Geometry:
        """逐顶点变换坐标（`func(x, y) -> (x, y)`，可以是 numpy 批量版）。"""
        if self.kind == "geometrycollection":
            return replace(self, parts=tuple(item.map_coords(func) for item in self.parts))
        if self.kind == "point":
            x, y = self.parts[0]
            tx, ty = func(np.array([x]), np.array([y]))
            return replace(self, parts=((float(tx[0]), float(ty[0])),))
        return replace(self, parts=_map_nested(self.parts, func))

    def transform(self, crs: Any) -> Geometry:
        target = st_crs(crs)
        if target is None or self.crs == target:
            return self
        if self.crs is None:
            raise SfError("几何没有 CRS，无法投影；先用 st_sfc(..., crs=...) 或 .with_crs()")
        if self.kind == "geometrycollection":
            return replace(
                self, parts=tuple(item.transform(target) for item in self.parts), crs=target
            )
        return replace(
            self, parts=_map_nested(self.parts, _transformer(self.crs, target)), crs=target
        )


def _map_nested(parts: Any, func: Any) -> Any:
    """对嵌套坐标结构逐顶点套 `func`（返回 numpy 数组的 (x, y) 两元组）。"""
    if not parts:
        return ()
    first = parts[0]
    if (
        isinstance(first, tuple)
        and len(first) == 2
        and all(isinstance(value, (int, float, np.floating)) for value in first)
    ):
        xs = np.array([item[0] for item in parts], dtype=np.float64)
        ys = np.array([item[1] for item in parts], dtype=np.float64)
        tx, ty = func(xs, ys)
        return tuple((float(a), float(b)) for a, b in zip(tx, ty, strict=True))
    return tuple(_map_nested(item, func) for item in parts)


def _transformer(source: CRS, target: CRS) -> Any:
    def apply(xs: Any, ys: Any) -> tuple[np.ndarray, np.ndarray]:
        return st_transform_xy(xs, ys, target, source)

    return apply


def st_point(x: Any, y: Any, crs: Any = None) -> Geometry:
    return Geometry("point", ((float(x), float(y)),), st_crs(crs))


def st_multipoint(points: Iterable[Sequence[Any]], crs: Any = None) -> Geometry:
    return Geometry("multipoint", tuple(_point(item) for item in points), st_crs(crs))


def st_linestring(points: Iterable[Sequence[Any]], crs: Any = None) -> Geometry:
    return Geometry("linestring", tuple(_point(item) for item in points), st_crs(crs))


def st_multilinestring(lines: Iterable[Iterable[Sequence[Any]]], crs: Any = None) -> Geometry:
    return Geometry(
        "multilinestring",
        tuple(tuple(_point(item) for item in line) for line in lines),
        st_crs(crs),
    )


def st_polygon(rings: Any, crs: Any = None) -> Geometry:
    """一个多边形：`rings` 是环的列表（第一个是外环）；也接受单个环的点列。"""
    items = list(rings)
    if items and not _looks_like_ring(items[0]):
        parsed = (_ring(items),)
    else:
        parsed = tuple(_ring(ring) for ring in items)
    return Geometry("polygon", parsed, st_crs(crs))


def _looks_like_ring(value: Any) -> bool:
    first = value[0] if len(value) else None
    return (
        isinstance(first, (tuple, list))
        and len(first) >= 2
        and isinstance(first[0], (int, float, np.floating))
    )


def st_multipolygon(polygons: Iterable[Any], crs: Any = None) -> Geometry:
    parsed: list[Any] = []
    for polygon in polygons:
        rings = list(polygon)
        if rings and _looks_like_ring(rings[0]):
            parsed.append((_ring(rings),))
        else:
            parsed.append(tuple(_ring(ring) for ring in rings))
    return Geometry("multipolygon", tuple(parsed), st_crs(crs))


def st_geometrycollection(geometries: Iterable[Geometry], crs: Any = None) -> Geometry:
    return Geometry("geometrycollection", tuple(geometries), st_crs(crs))


def st_sfc(geometries: Iterable[Geometry], crs: Any = None) -> tuple[Geometry, ...]:
    resolved = st_crs(crs)
    out: list[Geometry] = []
    for item in geometries:
        if not isinstance(item, Geometry):
            raise SfError(f"st_sfc() 只收 Geometry，收到 {type(item).__name__}")
        out.append(item if resolved is None else item.with_crs(resolved))
    return tuple(out)


# ---------------------------------------------------------------------------
# WKT
# ---------------------------------------------------------------------------

_WKT_NAMES = {
    "POINT": "point",
    "MULTIPOINT": "multipoint",
    "LINESTRING": "linestring",
    "MULTILINESTRING": "multilinestring",
    "POLYGON": "polygon",
    "MULTIPOLYGON": "multipolygon",
    "GEOMETRYCOLLECTION": "geometrycollection",
}


class _WktReader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def error(self, message: str) -> SfError:
        raise SfError(f"WKT 解析失败（位置 {self.pos}）：{message}；原文 {self.text!r}")

    def skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def peek(self) -> str:
        self.skip()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def take(self, char: str) -> None:
        if self.peek() != char:
            self.error(f"期望 {char!r}")
        self.pos += 1

    def word(self) -> str:
        self.skip()
        start = self.pos
        while self.pos < len(self.text) and (
            self.text[self.pos].isalnum() or self.text[self.pos] == "_"
        ):
            self.pos += 1
        return self.text[start : self.pos].upper()

    def number(self) -> float:
        self.skip()
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] in "+-0123456789.eE":
            self.pos += 1
        try:
            return float(self.text[start : self.pos])
        except ValueError:
            self.error("期望数字")

    def coords(self) -> tuple[float, float]:
        x = self.number()
        y = self.number()
        # 可选 Z / M 维度：忽略
        while self.peek() not in (",", ")", ""):
            self.number()
        return (x, y)

    def sequence(self) -> tuple[tuple[float, float], ...]:
        self.take("(")
        points = [self.coords()]
        while self.peek() == ",":
            self.pos += 1
            points.append(self.coords())
        self.take(")")
        return tuple(points)

    def geometry(self) -> Geometry:
        name = self.word()
        kind = _WKT_NAMES.get(name)
        if kind is None:
            self.error(f"不认识的几何类型 {name!r}")
        # 跳过 Z / M / ZM
        while self.peek().isalpha():
            self.word()
        if (
            self.peek() == "("
            and self.text[self.pos : self.pos + 8].upper().replace(" ", "") == "(EMPTY)"
        ):
            self.pos += 7
            self.take(")")
            return Geometry(kind, ())
        if self.peek() == "" and self.text.upper().rstrip().endswith("EMPTY"):
            return Geometry(kind, ())
        line = self.sequence()
        if kind == "point":
            if len(line) != 1:
                self.error("POINT 只能有一个坐标")
            parts: Any = line
        elif kind in ("multipoint", "linestring"):
            parts = line
        elif kind == "multilinestring":
            parts = tuple(line)
        elif kind == "polygon":
            parts = (line,)
        else:
            parts = tuple(line)
        return Geometry(kind, parts)


def parse_wkt(text: str, crs: Any = None) -> Geometry:
    """解析 WKT（POINT / LINESTRING / POLYGON / MULTI* / GEOMETRYCOLLECTION）。"""
    reader = _WktReader(text)
    return reader.geometry().with_crs(crs)


def as_geometry(value: Any, crs: Any = None) -> Geometry:
    """任意输入 → Geometry：Geometry 原样，字符串按 WKT。"""
    if isinstance(value, Geometry):
        return value if crs is None else value.with_crs(crs)
    if isinstance(value, str):
        return parse_wkt(value, crs)
    raise SfError(f"无法把 {type(value).__name__} 当成几何（支持 Geometry / WKT 字符串）")


# ---------------------------------------------------------------------------
# 投影
# ---------------------------------------------------------------------------


def _ellipsoid(f: float) -> tuple[float, float]:
    e2 = 2.0 * f - f * f
    return math.sqrt(e2), e2


def _lcc3347_forward(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # EPSG:3347 = NAD83 / Statistics Canada Lambert
    # +proj=lcc +lat_0=63.390675 +lon_0=-91.8666666666667 +lat_1=49 +lat_2=77
    # +x_0=6200000 +y_0=3000000 +ellps=GRS80
    a = _WGS84_A
    e, e2 = _ellipsoid(_GRS80_F)
    lon0 = math.radians(-91.8666666666667)
    lat0 = math.radians(63.390675)
    lat1 = math.radians(49.0)
    lat2 = math.radians(77.0)
    x0 = 6200000.0
    y0 = 3000000.0
    phi = np.radians(lat)
    lam = np.radians(lon)

    def m(p: Any) -> Any:
        return np.cos(p) / np.sqrt(1.0 - e2 * np.sin(p) ** 2)

    def t(p: Any) -> Any:
        return np.tan(math.pi / 4.0 - p / 2.0) / (
            (1.0 - e * np.sin(p)) / (1.0 + e * np.sin(p))
        ) ** (e / 2.0)

    n = (np.log(m(lat1)) - np.log(m(lat2))) / (np.log(t(lat1)) - np.log(t(lat2)))
    f_const = m(lat1) / (n * t(lat1) ** n)
    rho0 = a * f_const * t(lat0) ** n
    rho = a * f_const * t(phi) ** n
    theta = n * (lam - lon0)
    out_x = x0 + rho * np.sin(theta)
    out_y = y0 + rho0 - rho * np.cos(theta)
    return out_x, out_y


def _lcc3347_inverse(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = _WGS84_A
    e, e2 = _ellipsoid(_GRS80_F)
    lon0 = math.radians(-91.8666666666667)
    lat0 = math.radians(63.390675)
    lat1 = math.radians(49.0)
    lat2 = math.radians(77.0)
    x0 = 6200000.0
    y0 = 3000000.0

    def m(p: Any) -> Any:
        return np.cos(p) / np.sqrt(1.0 - e2 * np.sin(p) ** 2)

    def t(p: Any) -> Any:
        return np.tan(math.pi / 4.0 - p / 2.0) / (
            (1.0 - e * np.sin(p)) / (1.0 + e * np.sin(p))
        ) ** (e / 2.0)

    n = (np.log(m(lat1)) - np.log(m(lat2))) / (np.log(t(lat1)) - np.log(t(lat2)))
    f_const = m(lat1) / (n * t(lat1) ** n)
    rho0 = a * f_const * t(lat0) ** n
    dx = x - x0
    dy = rho0 - (y - y0)
    rho = np.hypot(dx, dy) * np.sign(n)
    theta = np.arctan2(dx, dy)
    tt = (rho / (a * f_const)) ** (1.0 / n)
    phi = np.pi / 2.0 - 2.0 * np.arctan(tt)
    for _ in range(12):
        es = e * np.sin(phi)
        phi = np.pi / 2.0 - 2.0 * np.arctan(tt * ((1.0 - es) / (1.0 + es)) ** (e / 2.0))
    lon = lon0 + theta / n
    return np.degrees(lon), np.degrees(phi)


def _merc_forward(lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = _WGS84_A * np.radians(lon)
    y = _WGS84_A * np.log(np.tan(math.pi / 4.0 + np.radians(lat) / 2.0))
    return x, y


def _merc_inverse(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon = np.degrees(x / _WGS84_A)
    lat = np.degrees(2.0 * np.arctan(np.exp(y / _WGS84_A)) - math.pi / 2.0)
    return lon, lat


def _project(crs: CRS, lon: Any, lat: Any) -> tuple[np.ndarray, np.ndarray]:
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    if crs.spec in ("longlat", "crs84"):
        return lon, lat
    if crs.spec == "merc":
        return _merc_forward(lon, lat)
    if crs.spec == "lcc3347":
        return _lcc3347_forward(lon, lat)
    raise SfError(f"不支持的目标 CRS {crs!r}")


def _unproject(crs: CRS, x: Any, y: Any) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if crs.spec in ("longlat", "crs84"):
        return x, y
    if crs.spec == "merc":
        return _merc_inverse(x, y)
    if crs.spec == "lcc3347":
        return _lcc3347_inverse(x, y)
    raise SfError(f"不支持的源 CRS {crs!r}")


#: 投影坐标（米）写进几何之前的量化位数：1e-5 m（0.01 mm）。地图数据没有比这更细
#: 的精度，而 1 ULP 级的 libm 噪声（`log` / `tan` / `sqrt` 的末位）被投影公式放大
#: 到 1e-8 m 量级后，落在窄面板范围（单点几何的 range 只有 0.1 m）上会变成可见的
#: 位置差、进而翻过 float32 的舍入边界（SIL-824 返工：nc 标签在另一台机器上漂）。
#: 上限由 `tests/test_sf.py` 的投影恒等断言给出：1e-5 m 的量化误差（5e-6 m）仍小于
#: 它对 `111319.49079327358 × lon` 的 1e-12 相对容差。
PROJECTED_DECIMALS = 5
#: 经纬度（度）的量化位数：1e-7 度 ≈ 1 cm。
GEOGRAPHIC_DECIMALS = 7


def _quantise_projected(values: np.ndarray, decimals: int) -> np.ndarray:
    """把投影结果舍到固定十进制网格（纯 IEEE 运算，不经过 libm/版本相关的 round）。

    NaN / ±Inf 原样保留：投影的边界语义（`|lat| > 90` 落成 NaN）不能被改写。
    """
    arr = np.asarray(values, dtype=np.float64)
    scale = float(10**decimals)
    finite = np.isfinite(arr)
    return np.where(finite, np.rint(arr * scale) / scale, arr)


def st_transform_xy(x: Any, y: Any, target: Any, source: Any) -> tuple[np.ndarray, np.ndarray]:
    """`sf_transform_xy()`：`source` → `target`；任一为 None 时原样返回。

    与上游一致的边界：非有限值原样保留（NaN 传播），`|lat| > 90` 的墨卡托输入
    落成 NaN（PROJ 的行为）。
    """
    target_crs = st_crs(target)
    source_crs = st_crs(source)
    xs = np.asarray(x, dtype=np.float64)
    ys = np.asarray(y, dtype=np.float64)
    if target_crs is None or source_crs is None or target_crs == source_crs:
        return xs, ys
    lon, lat = _unproject(source_crs, xs, ys)
    out_x, out_y = _project(target_crs, lon, lat)
    decimals = GEOGRAPHIC_DECIMALS if target_crs.is_longlat else PROJECTED_DECIMALS
    out_x = _quantise_projected(out_x, decimals)
    out_y = _quantise_projected(out_y, decimals)
    finite = np.isfinite(out_x) & np.isfinite(out_y)
    out_x = np.where(finite, out_x, np.nan)
    out_y = np.where(finite, out_y, np.nan)
    return out_x, out_y


def st_transform_geometry(geometry: Geometry, target: Any) -> Geometry:
    return geometry.transform(target)


transform_geometry = st_transform_geometry


def bbox_of(geometries: Iterable[Geometry]) -> tuple[float, float, float, float]:
    boxes = [item.bbox() for item in geometries if not item.is_empty]
    if not boxes:
        raise SfError("几何集合为空，无法计算 bbox")
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def calc_limits_bbox(
    xlim: Sequence[float],
    ylim: Sequence[float],
    crs: Any,
    default_crs: Any,
    method: str = "cross",
) -> tuple[np.ndarray, np.ndarray]:
    """`CoordSf$setup_panel_params()` 的 `calc_limits_bbox()`。"""
    target = st_crs(crs)
    source = st_crs(default_crs)
    if target is None or source is None or target == source:
        if method == "orthogonal":
            return np.asarray(xlim, dtype=np.float64), np.asarray(ylim, dtype=np.float64)
    x0, x1 = float(xlim[0]), float(xlim[1])
    y0, y1 = float(ylim[0]), float(ylim[1])
    if method == "geometry_bbox":
        return np.array([math.nan, math.nan]), np.array([math.nan, math.nan])
    if method == "orthogonal":
        return np.asarray([x0, x1], dtype=float), np.asarray([y0, y1], dtype=float)
    if method == "box":
        xs = np.concatenate(
            [
                np.full(20, x0),
                np.linspace(x0, x1, 20),
                np.full(20, x1),
                np.linspace(x1, x0, 20),
            ]
        )
        ys = np.concatenate(
            [
                np.linspace(y0, y1, 20),
                np.full(20, y1),
                np.linspace(y1, y0, 20),
                np.full(20, y0),
            ]
        )
    else:  # cross
        xs = np.concatenate([np.full(20, (x0 + x1) / 2.0), np.linspace(x0, x1, 20)])
        ys = np.concatenate([np.linspace(y0, y1, 20), np.full(20, (y0 + y1) / 2.0)])
    return st_transform_xy(xs, ys, target, source)


# ---------------------------------------------------------------------------
# R 的 pretty() / format()
# ---------------------------------------------------------------------------


def pretty(x_min: float, x_max: float, n: int = 5) -> list[float]:
    """`base::pretty()`（R `src/appl/pretty.c` 的常用分支）。

    本仓只用来给 graticule 选经纬度断点：`n = 6`，范围是面板 bbox 的经纬度
    跨度。算法与 R 一致（`high.u.bias = 1.5`、`u5.bias = 2.75`、`shrink.sml =
    0.75`），差值只在 R 的 `eps.correct` 分支上——那一支要用到 1e-10 的浮点
    校正，这里用 1e-10 的相对容差代替。
    """
    lo = float(x_min)
    up = float(x_max)
    if not (math.isfinite(lo) and math.isfinite(up)):
        raise SfError(f"pretty() 需要有限范围，收到 ({lo!r}, {up!r})")
    if lo > up:
        lo, up = up, lo
    dx = up - lo
    if dx == 0:
        if lo == 0:
            return [0.0, 1.0]
        cell = abs(lo)
        base = 10.0 ** math.floor(math.log10(cell))
        step = base
        return [lo - step / 2.0, lo, lo + step / 2.0]
    n = max(1, int(n))
    cell = dx / n
    base = 10.0 ** math.floor(math.log10(cell))
    high_bias = 1.5
    u5_bias = 2.75
    unit = 1.0
    if 2.0 * base - cell < high_bias * (cell - base):
        unit = 2.0
        if 5.0 * base - cell < u5_bias * (cell - 2.0 * base):
            unit = 5.0
            if 10.0 * base - cell < high_bias * (cell - 5.0 * base):
                unit = 10.0
        elif 10.0 * base - cell < high_bias * (cell - 2.0 * base):
            unit = 10.0
    step = unit * base
    # R 对过密的结果会把步长放大一档（shrink.sml）。
    while True:
        first = math.floor(lo / step + 1e-10) * step
        last = math.ceil(up / step - 1e-10) * step
        count = round((last - first) / step) + 1
        if count <= 3 * n or step > 1e12:
            break
        step *= 10.0
    values: list[float] = []
    value = first
    # 浮点累加会漂，按步长乘序号构造
    steps = round((last - first) / step)
    for index in range(steps + 1):
        value = first + index * step
        values.append(round(value, 12))
    return values


def format_vector(values: Sequence[Any], digits: int = 7) -> list[str]:
    """`format()` 的数值分支（共同小数位 + 前导空格补齐）。

    R 的口径：先按 `digits` 位有效数字求每个值的**最短**十进制表示，再取所有
    值里最多的小数位统一格式化；宽度不足的在左边补空格（所以 `format(-0.2..1.2)`
    会给正数带一个前导空格，graticule 的 `" 0.0"` 就是这么来的）。
    """
    numbers = [float(value) for value in values]
    decimals = 0
    for number in numbers:
        decimals = max(decimals, _decimals_for(number, digits))
    texts = [f"{number:.{decimals}f}" for number in numbers]
    width = max((len(text) for text in texts), default=0)
    return [text.rjust(width) for text in texts]


def _decimals_for(value: float, digits: int) -> int:
    if not math.isfinite(value):
        return 0
    if value == 0.0:
        return 0
    magnitude = math.floor(math.log10(abs(value)))
    max_decimals = max(0, min(digits - 1 - magnitude, 12))
    for decimals in range(max_decimals + 1):
        scaled = round(value, decimals)
        if abs(scaled - value) <= 1e-12 * max(1.0, abs(value)):
            return decimals
    return max_decimals


def degree_label_ns(values: Sequence[float], digits: int = 10) -> list[str]:
    """sf 的 `degreeLabelsNS()`：`36.25°N`（本仓不做 plotmath，直接给文本）。"""
    texts = format_vector([abs(float(value)) for value in values], digits=digits)
    out: list[str] = []
    for text, value in zip(texts, values, strict=True):
        suffix = "S" if float(value) < 0 else ("N" if float(value) > 0 else "")
        out.append(f"{text}°{suffix}" if suffix else f"{text}°")
    return out


def degree_label_ew(values: Sequence[float], digits: int = 10) -> list[str]:
    """sf 的 `degreeLabelsEW()`：`81.7°W`。"""
    adjusted = [float(value) - 360.0 if float(value) > 180.0 else float(value) for value in values]
    texts = format_vector([abs(value) for value in adjusted], digits=digits)
    out: list[str] = []
    for text, value in zip(texts, adjusted, strict=True):
        if value == -180.0 or value == 180.0:
            out.append(f"{text}°")
        elif value < 0:
            out.append(f"{text}°W")
        elif value > 0:
            out.append(f"{text}°E")
        else:
            out.append(f"{text}°")
    return out


# ---------------------------------------------------------------------------
# graticule
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraticuleLine:
    """一条经纬网线（已裁剪到面板 bbox，坐标在目标 CRS 里）。"""

    type: str  # "E"（经线）/ "N"（纬线）
    degree: float
    label: str
    coords: tuple[tuple[float, float], ...]

    @property
    def x_start(self) -> float:
        return self.coords[0][0]

    @property
    def y_start(self) -> float:
        return self.coords[0][1]

    @property
    def x_end(self) -> float:
        return self.coords[-1][0]

    @property
    def y_end(self) -> float:
        return self.coords[-1][1]

    @property
    def angle_start(self) -> float:
        (x0, y0), (x1, y1) = self.coords[0], self.coords[1]
        return math.degrees(math.atan2(y1 - y0, x1 - x0))

    @property
    def angle_end(self) -> float:
        (x0, y0), (x1, y1) = self.coords[-2], self.coords[-1]
        return math.degrees(math.atan2(y1 - y0, x1 - x0))


def _clip_polyline(
    points: Sequence[tuple[float, float]], bbox: tuple[float, float, float, float]
) -> list[tuple[tuple[float, float], ...]]:
    """折线 × 矩形 → 若干段（Liang–Barsky，逐段裁剪并合并连续段）。"""
    xmin, ymin, xmax, ymax = bbox
    runs: list[tuple[tuple[float, float], ...]] = []
    current: list[tuple[float, float]] = []
    for index in range(len(points) - 1):
        (x0, y0), (x1, y1) = points[index], points[index + 1]
        clipped = _clip_segment(x0, y0, x1, y1, xmin, ymin, xmax, ymax)
        if clipped is None:
            if len(current) >= 2:
                runs.append(tuple(current))
            current = []
            continue
        (cx0, cy0), (cx1, cy1) = clipped
        if not current or not _close(current[-1], (cx0, cy0)):
            if len(current) >= 2:
                runs.append(tuple(current))
            current = [(cx0, cy0)]
        current.append((cx1, cy1))
    if len(current) >= 2:
        runs.append(tuple(current))
    return runs


def _close(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) <= 1e-9 * max(1.0, abs(a[0])) and abs(a[1] - b[1]) <= 1e-9 * max(
        1.0, abs(a[1])
    )


def _clip_segment(
    x0: float, y0: float, x1: float, y1: float, xmin: float, ymin: float, xmax: float, ymax: float
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    dx = x1 - x0
    dy = y1 - y0
    p = (-dx, dx, -dy, dy)
    q = (x0 - xmin, xmax - x0, y0 - ymin, ymax - y0)
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q, strict=True):
        if pi == 0:
            if qi < 0:
                return None
            continue
        t = qi / pi
        if pi < 0:
            u1 = max(u1, t)
        else:
            u2 = min(u2, t)
        if u1 > u2:
            return None
    return (
        (x0 + u1 * dx, y0 + u1 * dy),
        (x0 + u2 * dx, y0 + u2 * dy),
    )


def _sample_box(
    bbox: tuple[float, float, float, float], crs: CRS | None, datum: CRS, ndiscr: int
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """sf 的 `box`：外框与两条对角线，平面细分后投影到 `datum`。

    返回两组点（都已在 datum 坐标系）：外框与对角线。拆成两条是照
    `st_graticule()` 的两个 linestring——bbox 取两者的并集。
    """
    xmin, ymin, xmax, ymax = bbox
    corners = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]

    def sample_line(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
        lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
        total = sum(lengths)
        if total == 0:
            return list(points)
        segment = total / max(1, ndiscr)
        out: list[tuple[float, float]] = []
        for index in range(len(points) - 1):
            (x0, y0), (x1, y1) = points[index], points[index + 1]
            steps = max(1, math.ceil(lengths[index] / segment))
            for step in range(steps + 1):
                t = step / steps
                out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        return out

    def project(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
        if crs is None or crs == datum:
            return list(points)
        xs = np.array([item[0] for item in points], dtype=float)
        ys = np.array([item[1] for item in points], dtype=float)
        tx, ty = st_transform_xy(xs, ys, datum, crs)
        return [(float(a), float(b)) for a, b in zip(tx, ty, strict=True)]

    perimeter = sample_line([*corners, corners[0]])
    diagonals = sample_line([corners[0], corners[2], corners[1], corners[3], corners[0]])
    return project(perimeter), project(diagonals)


def st_graticule(
    bbox: Sequence[float],
    crs: Any = None,
    *,
    datum: Any = 4326,
    lon: Sequence[float] | None = None,
    lat: Sequence[float] | None = None,
    ndiscr: int = 100,
) -> list[GraticuleLine]:
    """`sf::st_graticule()`：面板 bbox 内的经纬网。

    `crs` 是显示坐标系；`datum` 是经纬度所在的 CRS（缺省 WGS84）。`crs=None`
    时按 sf 的 `NA_crs_` 分支：经纬网直接在数据坐标里画，标签是 `format()` 出来
    的数值（没有 °）。
    """
    xmin, ymin, xmax, ymax = (float(value) for value in bbox)
    target = st_crs(crs)
    datum_crs = st_crs(datum) or st_crs(4326)
    assert datum_crs is not None
    planar = target is None

    if planar:
        # sf: crs 是 NA_crs_ → 不投影；datum 被覆盖成 NA，标签走 format()
        unit = None
        bb = (xmin, ymin, xmax, ymax)
    else:
        assert target is not None
        perimeter, diagonals = _sample_box((xmin, ymin, xmax, ymax), target, datum_crs, ndiscr)
        samples = [item for item in (*perimeter, *diagonals) if all(map(math.isfinite, item))]
        if not samples:
            return []
        bb = (
            min(item[0] for item in samples),
            min(item[1] for item in samples),
            max(item[0] for item in samples),
            max(item[1] for item in samples),
        )
        unit = datum_crs

    lon_values = list(lon) if lon is not None else pretty(bb[0], bb[2], 6)
    lat_values = list(lat) if lat is not None else pretty(bb[1], bb[3], 6)
    if unit is not None and unit.is_longlat:
        # sf 的 sanity：经度落在 [-180,180]（或 [0,360]），纬度落在 (-90,90)
        if lon_values and min(lon_values) >= -15 and max(lon_values) > 195:
            lon_values = [value for value in lon_values if 0 <= value <= 360]
        else:
            lon_values = [value for value in lon_values if -180 <= value <= 180]
        lat_values = [value for value in lat_values if -90 < value < 90]
    if not lon_values and not lat_values:
        return []

    wide = (
        min(bb[0], min(lon_values) if lon_values else bb[0]),
        min(bb[1], min(lat_values) if lat_values else bb[1]),
        max(bb[2], max(lon_values) if lon_values else bb[2]),
        max(bb[3], max(lat_values) if lat_values else bb[3]),
    )

    if planar:
        lon_labels = format_vector(lon_values)
        lat_labels = format_vector(lat_values)
    else:
        lon_labels = degree_label_ew(lon_values)
        lat_labels = degree_label_ns(lat_values)

    lines: list[GraticuleLine] = []
    samples = max(2, int(ndiscr))
    for value, label in zip(lon_values, lon_labels, strict=True):
        xs = np.full(samples, float(value))
        ys = np.linspace(wide[1], wide[3], samples)
        lines.extend(_build_lines("E", float(value), label, xs, ys, target, xmin, ymin, xmax, ymax))
    for value, label in zip(lat_values, lat_labels, strict=True):
        xs = np.linspace(wide[0], wide[2], samples)
        ys = np.full(samples, float(value))
        lines.extend(_build_lines("N", float(value), label, xs, ys, target, xmin, ymin, xmax, ymax))
    return lines


def _build_lines(
    kind: str,
    degree: float,
    label: str,
    xs: np.ndarray,
    ys: np.ndarray,
    target: CRS | None,
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
) -> list[GraticuleLine]:
    if target is not None:
        xs, ys = st_transform_xy(xs, ys, target, st_crs(4326))
    points = [(float(x), float(y)) for x, y in zip(xs, ys, strict=True)]
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in points):
        points = [(x, y) for x, y in points if math.isfinite(x) and math.isfinite(y)]
        if len(points) < 2:
            return []
    runs = _clip_polyline(points, (xmin, ymin, xmax, ymax))
    out: list[GraticuleLine] = []
    for run in runs:
        if len(run) >= 2:
            out.append(GraticuleLine(kind, degree, label, tuple(run)))
    return out


# ---------------------------------------------------------------------------
# mapproj（`coord_map()`）
# ---------------------------------------------------------------------------

_RAD = math.pi / 180.0


def _cirmod(theta: float) -> float:
    while theta >= 180.0:
        theta -= 360.0
    while theta < -180.0:
        theta += 360.0
    return theta


def _place(lat: float, lon: float) -> tuple[float, float, float, float, float, float]:
    """mapproj 的 `struct place`：`(nlat_s, nlat_c, nlat_l, wlon_s, wlon_c, wlon_l)`。"""
    lat = _cirmod(lat)
    if lat > 90.0:
        lat = 180.0 - lat
        lon -= 180.0
    elif lat < -90.0:
        lat = -180.0 - lat
        lon -= 180.0
    nlat = lat * _RAD
    wlon = _cirmod(lon) * _RAD
    return (math.sin(nlat), math.cos(nlat), nlat, math.sin(wlon), math.cos(wlon), wlon)


def _orient(lat: float, lon: float, theta: float) -> tuple[Any, float]:
    """mapproj 的 `orient()`：返回 `(pole, twist)`，`pole` 是 6 元组。"""
    lat = _cirmod(lat)
    if lat > 90.0:
        lat = 180.0 - lat
        lon -= 180.0
        theta -= 180.0
    elif lat < -90.0:
        lat = -180.0 - lat
        lon -= 180.0
        theta -= 180.0
    pole = _place(lat, lon)
    return pole, _cirmod(theta) * _RAD


@dataclass(frozen=True, slots=True)
class _Place:
    """mapproj 的 `struct place`（已旋到投影极点的球面坐标，弧度）。"""

    nlat_l: np.ndarray
    nlat_s: np.ndarray
    nlat_c: np.ndarray
    wlon_l: np.ndarray
    wlon_s: np.ndarray
    wlon_c: np.ndarray


def _norm_place(x: np.ndarray, y: np.ndarray, pole: tuple[float, ...], twist: float) -> _Place:
    """mapproj 的 `norm()`：把地理坐标旋转到以 `pole` 为极点的坐标系。

    与 `src/zcoord.c` 同序：先按极点旋转，再 `trig(&g->wlon)` 用最终的
    `wlon.l` 重算 `wlon.s` / `wlon.c`（`azequalarea` 的 `x/y` 吃的正是这两个值，
    用旋转中间量会差一个 `twist`），最后把 `wlon.l` 折回 `[-π, π]`。
    """
    lon = x * _RAD
    lat = y * _RAD
    wlon_s = np.sin(-lon)
    wlon_c = np.cos(-lon)
    nlat_s = np.sin(lat)
    nlat_c = np.cos(lat)
    p_nlat_s, p_nlat_c, _, _, _, p_wlon_l = pole
    if p_nlat_s == 1.0:
        # 极点就在北极：只平移经度
        m_wlon_l = -lon - (p_wlon_l + twist)
        m_nlat_l = lat
        m_nlat_s = nlat_s
        m_nlat_c = nlat_c
    else:
        if p_wlon_l != 0.0:
            wlon_l = -lon - p_wlon_l
            wlon_s = np.sin(wlon_l)
            wlon_c = np.cos(wlon_l)
        m_nlat_s = p_nlat_s * nlat_s + p_nlat_c * nlat_c * wlon_c
        m_nlat_c = np.sqrt(np.maximum(0.0, 1.0 - m_nlat_s * m_nlat_s))
        m_nlat_l = np.arctan2(m_nlat_s, m_nlat_c)
        m_wlon_s = nlat_c * wlon_s
        m_wlon_c = p_nlat_c * nlat_s - p_nlat_s * nlat_c * wlon_c
        m_wlon_l = np.arctan2(m_wlon_s, -m_wlon_c) - twist
    m_wlon_l = np.where(m_wlon_l > math.pi, m_wlon_l - 2.0 * math.pi, m_wlon_l)
    m_wlon_l = np.where(m_wlon_l < -math.pi, m_wlon_l + 2.0 * math.pi, m_wlon_l)
    return _Place(
        nlat_l=m_nlat_l,
        nlat_s=m_nlat_s,
        nlat_c=m_nlat_c,
        wlon_l=m_wlon_l,
        wlon_s=np.sin(m_wlon_l),
        wlon_c=np.cos(m_wlon_l),
    )


def _xmercator(place: _Place) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`Xmercator`：`x = -wlon`、`y = atanh(sin lat)`；`|lat| > 80°` 返回 NA。"""
    sin_lat = place.nlat_s
    with np.errstate(divide="ignore", invalid="ignore"):
        py = 0.5 * np.log((1.0 + sin_lat) / (1.0 - sin_lat))
    px = -place.wlon_l
    ok = (np.abs(place.nlat_l) <= 80.0 * _RAD) & np.isfinite(py)
    return px, py, ok


def _xazequalarea(place: _Place) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`Xazequalarea`（Lambert 方位等积投影）。

    `r = sqrt(1 - sin lat)`、`(x, y) = -r·(wlon.s, wlon.c)`。与 mercator 不同，
    它在南北极都有定义（极点处 `r = 0` / `sqrt 2`），没有 ±80° 截断，所以
    `ok` 只剔除浮点上的非有限值。
    """
    with np.errstate(invalid="ignore"):
        radius = np.sqrt(1.0 - place.nlat_s)
    px = -radius * place.wlon_s
    py = -radius * place.wlon_c
    ok = np.isfinite(px) & np.isfinite(py)
    return px, py, ok


#: 已移植的 mapproj 投影 → 需要的 `parameters` 个数（`mapindex[]` 的 `npar`）。
#: 只实现挣得出来的投影；其余显式报错，不拿 identity 顶替。
_MAPPROJ_PARAMS: Mapping[str, int] = MappingProxyType({"mercator": 0, "azequalarea": 0})

_MAPPROJ_FUNCS: Mapping[str, Any] = MappingProxyType(
    {"mercator": _xmercator, "azequalarea": _xazequalarea}
)


def mapproj_projections() -> tuple[str, ...]:
    """已移植的 mapproj 投影名（`coord_map(projection=)` 接受的就是这些）。"""
    return tuple(_MAPPROJ_PARAMS)


def mapproject(
    xs: Any,
    ys: Any,
    *,
    projection: str = "mercator",
    params: Sequence[float] = (),
    orientation: Sequence[float] = (90.0, 0.0, 0.0),
) -> tuple[np.ndarray, np.ndarray]:
    """`mapproj::mapproject()` 的球面投影核（`R/coord-map.R` 唯一依赖）。

    上游 `setproj()` 用 `orient(o[0], -o[1], -o[2])` 旋球，再交给投影函数：

    - `mercator`：`x = -wlon`、`y = 0.5*log((1+sin lat)/(1-sin lat))`；
    - `azequalarea`：`r = sqrt(1 - sin lat)`、`(x, y) = -r·(wlon.s, wlon.c)`。

    定义域外的点返回 NA（mercator 的 `|lat| > 80°`，以及任何非有限结果）。
    """
    x = np.asarray(xs, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)
    name = str(projection)
    if name in ("identity", "none"):
        return x, y
    func = _MAPPROJ_FUNCS.get(name)
    if func is None:
        implemented = " / ".join(f'"{item}"' for item in _MAPPROJ_PARAMS)
        raise SfError(
            f"coord_map(projection = {projection!r}) 尚未实现：本仓只移植了 mapproj 的 "
            f"{implemented}（其余投影需要 mapproj 全量）"
        )
    given = tuple(params)
    required = _MAPPROJ_PARAMS[name]
    if len(given) != required:
        plural = "" if required == 1 else "s"
        raise SfError(
            f"mapproj 的 {name} 需要 {required} 个投影参数{plural}，"
            f"收到 {len(given)} 个（parameters = {given!r}）"
        )
    items = tuple(float(item) for item in tuple(orientation))
    if len(items) != 3:
        raise SfError(f"orientation 必须是 (latitude, longitude, rotation) 三元组，收到 {items!r}")
    lat0, lon0, theta = items
    pole, twist = _orient(lat0, -lon0, -theta)
    place = _norm_place(x, y, pole, twist)
    px, py, ok = func(place)
    return np.where(ok, px, np.nan), np.where(ok, py, np.nan)


# ---------------------------------------------------------------------------
# 其它 sf 工具
# ---------------------------------------------------------------------------


def point_on_surface(geometry: Geometry) -> tuple[float, float]:
    """`sf::st_point_on_surface()` 的近似：多边形取面积重心，线/点取代表点。

    GEOS 的 InteriorPointArea 是「极值内点」算法；对凸多边形两者一致，对凹多边形
    可能差几个像素——`stat_sf_coordinates()` 的标签位置因此有已知差异，见
    `docs/notes/sf.md`。
    """
    if geometry.kind == "point":
        return geometry.parts[0]
    if geometry.kind == "multipoint":
        points = geometry.parts
        return (
            sum(item[0] for item in points) / len(points),
            sum(item[1] for item in points) / len(points),
        )
    if geometry.kind == "linestring":
        points = geometry.parts
        return points[len(points) // 2]
    if geometry.kind == "multilinestring":
        line = geometry.parts[len(geometry.parts) // 2]
        return line[len(line) // 2]
    if geometry.kind == "polygon":
        return _polygon_centroid(geometry.parts[0])
    if geometry.kind == "multipolygon":
        polygon = max(geometry.parts, key=lambda item: abs(_ring_area(item[0])))
        return _polygon_centroid(polygon[0])
    if geometry.kind == "geometrycollection":
        for item in geometry.parts:
            if item.kind == "polygon":
                return _polygon_centroid(item.parts[0])
        for item in geometry.parts:
            return point_on_surface(item)
    raise SfError(f"point_on_surface 不支持 {geometry.kind}")


def _ring_area(ring: Sequence[tuple[float, float]]) -> float:
    total = 0.0
    for index, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(index + 1) % len(ring)]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def _polygon_centroid(ring: Sequence[tuple[float, float]]) -> tuple[float, float]:
    area = _ring_area(ring)
    if abs(area) < 1e-15:
        return ring[0]
    cx = 0.0
    cy = 0.0
    for index, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(index + 1) % len(ring)]
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    return (cx / (6.0 * area), cy / (6.0 * area))


# ---------------------------------------------------------------------------
# 输入适配：`sf()` 便捷构造
# ---------------------------------------------------------------------------


def sf(data: Any = None, geometry: Any = None, crs: Any = None) -> ColumnTable:
    """构造一份带 `geometry` 列的 ``ColumnTable``（ggcore 的 DataFrame-like）。

    ```python
    from ggcore.sf import sf, st_point

    data = sf({"name": ["a", "b"]}, geometry=[st_point(0, 1), st_point(1, 2)])
    ggplot(data) + geom_sf()
    ```

    `geometry` 也接受 WKT 字符串列表；`data` 是已有 mapping 时原列保留。
    """
    resolved = st_crs(crs)
    columns: dict[str, Any] = dict(data or {})
    if geometry is not None:
        columns["geometry"] = [
            as_geometry(item, resolved) if resolved is not None else as_geometry(item)
            for item in geometry
        ]
    if "geometry" not in columns:
        raise SfError("sf() 需要 geometry=（或 data 里带 geometry 列）")
    pairs: list[tuple[str, Column]] = []
    for name, values in columns.items():
        pairs.append((name, _column(name, values)))
    return ColumnTable(pairs)


def _column(name: str, values: Any) -> Column:
    if isinstance(values, Column):
        return values
    items = list(values) if not isinstance(values, np.ndarray) else values.tolist()
    if not items:
        if name == "geometry":
            return Column("geometry", np.empty(0, dtype=object))
        return Column("float", np.empty(0, dtype=np.float64))
    if name == "geometry" or all(isinstance(item, Geometry) or item is None for item in items):
        mask = np.array([item is None for item in items], dtype=bool)
        data = np.empty(len(items), dtype=object)
        for index, item in enumerate(items):
            data[index] = Geometry("point", ()) if item is None else item
        return Column("geometry", data, na_mask=mask)
    first = next(item for item in items if item is not None)
    if isinstance(first, str):
        data = np.array(["" if item is None else str(item) for item in items], dtype=object)
        mask = np.array([item is None for item in items], dtype=bool)
        levels = tuple(sorted({item for item in items if item is not None}))
        return Column("str", data, levels=levels, na_mask=mask)
    if isinstance(first, bool):
        data = np.array([bool(item) for item in items], dtype=bool)
        return Column("bool", data, na_mask=np.array([item is None for item in items], dtype=bool))
    numbers = np.array(
        [np.nan if item is None else float(item) for item in items], dtype=np.float64
    )
    mask = np.isnan(numbers)
    if mask.any():
        return Column("float", np.where(mask, 0.0, numbers), na_mask=mask)
    if all(isinstance(item, (int, np.integer)) and not isinstance(item, bool) for item in items):
        return Column("int", numbers)
    return Column("float", numbers)
