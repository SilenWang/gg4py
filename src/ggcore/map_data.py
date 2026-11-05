"""`annotation_borders()` 的地图数据（最小可用）。

GG4Py 的 ggcore 只依赖 numpy（X1），不引入 R 的 `maps` 包；但上游快照
`annotate/annotation-borders-utah.svg` 的判据就是 `maps::map("state", "utah")`
那份多边形。这里把**这一份**数据按 `maps` 的 lon/lat 逐点内联（59 个点，闭合），
与 `map_data("state", "utah")` 的 `long` / `lat` 同值。

数据来源与口径：

- 上游 `maps` 包的 `state` 数据库（美国州界，Census 简化后的经纬度）；
- 数值从上游快照 `annotation-borders-utah.svg` 的 `<polygon points>` 反解：
  x 轴刻度 `-114..-109` 的刻度线位置给出 `lon = -114 + (x - 57.72) / 126.046`，
  y 轴 `37..42` 给出 `lat = 37 + (532.99 - y) / 97.11`（两组刻度都是直线映射，
  反解误差 < 1e-5 度，远低于一个像素）；
- 与 `maps::map("state", "utah")` 的逐点对拍见 `docs/notes/annotation.md`。

只内置这一份是**刻意的**：`maps` 是外部数据包，完整移植它属于 M3-2 的空间能力
（`coord_sf` / 投影）。其它 `database` / `regions` 直接报错，不做静默降级。
"""

from __future__ import annotations

from typing import Any

from ggcore.map_data_usa import USA as _USA

__all__ = ["STATE_UTAH", "map_frame"]

#: `maps::map("state", "utah")` 的 lon / lat（逐点，闭合）。
STATE_UTAH: dict[str, list[float]] = {
    "x": [
        -114.047284,
        -113.015915,
        -112.173683,
        -112.110690,
        -111.520508,
        -111.491868,
        -111.050680,
        -111.056392,
        -111.056392,
        -111.056392,
        -110.053742,
        -110.007886,
        -109.051013,
        -109.056805,
        -109.056805,
        -109.056805,
        -109.062517,
        -109.056805,
        -109.056805,
        -109.051013,
        -109.045301,
        -109.051013,
        -109.039589,
        -109.148438,
        -109.411992,
        -109.715691,
        -109.933389,
        -110.007886,
        -110.088095,
        -110.305793,
        -110.546499,
        -110.683988,
        -110.758485,
        -110.844406,
        -111.125177,
        -111.251242,
        -111.319947,
        -111.411659,
        -111.686718,
        -111.950272,
        -112.208035,
        -112.414309,
        -112.540374,
        -112.729432,
        -112.907066,
        -113.004490,
        -113.279549,
        -113.537391,
        -113.823794,
        -114.041572,
        -114.047284,
        -114.041572,
        -114.047284,
        -114.047284,
        -114.041572,
        -114.035860,
        -114.041572,
        -114.041572,
        -114.047284,
    ],
    "y": [
        42.003501,
        41.997838,
        41.997838,
        42.003501,
        42.003501,
        41.997838,
        41.997838,
        41.579549,
        41.230048,
        40.995160,
        41.000824,
        41.000824,
        40.995160,
        40.657090,
        40.221604,
        39.654413,
        39.499743,
        39.362167,
        38.508496,
        38.153228,
        37.866749,
        37.631861,
        36.995881,
        36.995881,
        36.995881,
        36.995881,
        36.995881,
        37.001648,
        37.001648,
        37.001648,
        36.995881,
        36.995881,
        36.995881,
        37.001648,
        36.995881,
        36.995881,
        37.001648,
        37.001648,
        37.001648,
        37.001648,
        36.995881,
        36.995881,
        36.995881,
        37.001648,
        36.995881,
        37.001648,
        37.001648,
        37.001648,
        36.995881,
        36.995881,
        37.608897,
        38.141798,
        38.588714,
        38.668932,
        39.539800,
        39.900731,
        40.129956,
        41.006590,
        42.003501,
    ],
}

#: `(database, regions)` → 内联的多边形（`group` 从 1 起，与 `map_data()` 同）。
#: 值可以是单多边形（`{"x": ..., "y": ...}`），也可以是多边形组
#: （`{"groups": (((x, y), ...), ...)}`，M3-2 的 `map("usa", fill = TRUE)`）。
_DATABASES: dict[tuple[str, str], Any] = {
    ("state", "utah"): STATE_UTAH,
    ("usa", "."): {"groups": _USA},
}


def map_frame(
    database: str,
    regions: str,
    *,
    xlim: Any = None,
    ylim: Any = None,
) -> dict[str, list[float]]:
    """`maps::map()` 的最小替身：返回 `{x, y, group}`（lon / lat）。

    `xlim` / `ylim` 只做**保留框内点**的裁剪（与 `maps::map()` 的取框语义一致：
    落在框外的点不画；本仓不做线段与框的求交，因为内置数据量只有一份）。
    """
    entry = _DATABASES.get((database, regions))
    if entry is None:
        known = ", ".join(f'("{db}", "{rg}")' for db, rg in sorted(_DATABASES))
        raise NotImplementedError(
            f"annotation_borders() 只内置了 {known} 这几份地图数据（maps 是外部数据包，"
            "完整移植归 M3-2 的空间能力）；需要别的区域请把 lon/lat 直接交给 "
            "annotate('polygon', x=..., y=..., group=...)"
        )
    if isinstance(entry, dict) and "groups" in entry:
        return _frame_from_groups(entry["groups"], xlim=xlim, ylim=ylim)

    polygon = entry
    xs: list[float] = []
    ys: list[float] = []
    inside: list[bool] = []
    for x, y in zip(polygon["x"], polygon["y"], strict=True):
        keep = True
        if xlim is not None:
            keep = keep and float(xlim[0]) <= x <= float(xlim[1])
        if ylim is not None:
            keep = keep and float(ylim[0]) <= y <= float(ylim[1])
        xs.append(x)
        ys.append(y)
        inside.append(keep)
    if not any(inside):
        return {"x": [], "y": [], "group": []}
    return {
        "x": [x for x, keep in zip(xs, inside, strict=True) if keep],
        "y": [y for y, keep in zip(ys, inside, strict=True) if keep],
        "group": [1.0] * sum(inside),
    }


def _frame_from_groups(
    groups: Any, *, xlim: Any = None, ylim: Any = None
) -> dict[str, list[float]]:
    """多多边形 → `{x, y, group}`（`group` 从 1 起，与 `map_data()` 同）。"""
    xs: list[float] = []
    ys: list[float] = []
    ids: list[float] = []
    for index, group in enumerate(groups, start=1):
        for x, y in group:
            if xlim is not None and not (float(xlim[0]) <= x <= float(xlim[1])):
                continue
            if ylim is not None and not (float(ylim[0]) <= y <= float(ylim[1])):
                continue
            xs.append(float(x))
            ys.append(float(y))
            ids.append(float(index))
    return {"x": xs, "y": ys, "group": ids}
