# 空间数据：`geom_sf` / `coord_sf` / `coord_map`

空间数据的 API 与 sf 对齐：`st_*()` 造几何、`sf()` 造表、`geom_sf()` 画、
`coord_sf()` 定投影与边界。代码在 `ggcore.sf`（几何 / CRS / 投影）、
`ggcore.sf_stat`（`stat_sf*`）与 `ggcore.geom.sf`（绘制）。

## 1. 几何与数据

| 函数 | 说明 |
| --- | --- |
| `st_point(x, y, crs=None)` | 点 |
| `st_multipoint(points, crs=None)` | 多点 |
| `st_linestring(points, crs=None)` | 线（点的序列） |
| `st_multilinestring(lines, crs=None)` | 多线 |
| `st_polygon(rings, crs=None)` | 面（环的序列，首尾要闭合） |
| `st_multipolygon(polygons, crs=None)` | 多面 |
| `st_geometrycollection(geometries)` | 几何集合 |
| `st_sfc(geometries, crs=None)` | 一组几何 |
| `st_crs(value)` | 解析 CRS（EPSG 号 / `"EPSG:4326"` / `+proj=...`） |
| `parse_wkt(text, crs=None)` | WKT → 几何（点 / 线；面的 WKT 目前解析失败，见 §6） |
| `sf(data, geometry, crs=None)` | 组一份带 `geometry` 列的 `ColumnTable` |

几何是 `Geometry(kind, parts, crs)`，落在列的 `kind="geometry"` 上，所以三种输入
（dict / pandas / Arrow）都能直接带几何列。

```python
from ggcore.plot import aes, coord_sf, geom_sf, ggplot, labs
from ggcore.sf import sf, st_polygon
from ggcore.theme import theme_minimal

RING = [(-81.0, 36.0), (-79.0, 36.0), (-80.0, 37.0), (-81.0, 36.0)]
DATA = sf({"name": ["ashe"]}, geometry=[st_polygon(RING, crs=4326)])

p = (
    ggplot(DATA, aes(fill="name"))
    + geom_sf(colour="white", linewidth=0.6)
    + coord_sf()
    + labs(title="geom_sf() + coord_sf()", x=None, y=None)
    + theme_minimal()
)
```

`geom_sf()` 按几何类型分派：点用点层、线/多用线层、面/多用面层，缺省美学逐类型取
（点 `shape/size/stroke`、线 `linewidth/linetype`、面 `fill/colour`）。

## 2. CRS 与 `coord_sf()`

只支持三档 CRS（其余显式报错，不拿 identity 顶替）：

| CRS | 说明 |
| --- | --- |
| `4326` / `"EPSG:4326"` / `"OGC:CRS84"` / `+proj=longlat` | 经纬度 |
| `3857` / `"EPSG:3857"` / `+proj=merc` | Web 墨卡托 |
| `3347` / `+proj=lcc +lat_0=63.39 …` | Statistics Canada Lambert |

`coord_sf()` 的关键参数：

| 参数 | 含义 |
| --- | --- |
| `crs` | 面板的目标投影（缺省用数据自己的 CRS） |
| `default_crs` | 没有 CRS 的图层按哪个 CRS 解释（缺省 4326） |
| `xlim` / `ylim` | 面板范围（在 `crs` 空间） |
| `label_axes` | 四边轴标签（缺省 `"--EN"`：上 / 右空，下 E-W、左 N-S） |
| `label_graticule` | 经纬度标签来源（`"NSWE"`） |
| `lims_method` | limits 投到 `crs` 的方法：`"cross"` / `"box"` / `"orthogonal"` / `"geometry_bbox"` |

```python
from ggcore.plot import aes, coord_sf, geom_sf, ggplot, labs
from ggcore.sf import sf, st_polygon
from ggcore.theme import theme_void

RING = [(-81.0, 36.0), (-79.0, 36.0), (-80.0, 37.0), (-81.0, 36.0)]
DATA = sf({"name": ["ashe"]}, geometry=[st_polygon(RING, crs=4326)])

p = (
    ggplot(DATA)
    + geom_sf(fill="#4C78A8", colour="white")
    + coord_sf(crs=3857)  # 面板改用 Web 墨卡托
    + labs(title="coord_sf(crs = 3857)")
    + theme_void()
)
```

经纬网（graticule）默认画在 `panel.grid.major` 上；关掉它就是普通背景：

```python
from ggcore.plot import aes, coord_sf, geom_sf, ggplot, labs
from ggcore.sf import sf, st_polygon
from ggcore.theme import element_blank, theme, theme_minimal

RING = [(-81.0, 36.0), (-79.0, 36.0), (-80.0, 37.0), (-81.0, 36.0)]
DATA = sf({"name": ["ashe"]}, geometry=[st_polygon(RING, crs=4326)])

p = (
    ggplot(DATA)
    + geom_sf(fill="#4C78A8", colour="white")
    + coord_sf(label_axes="--EN")
    + labs(title="coord_sf(label_axes = '--EN')", x=None, y=None)
    + theme_minimal()
    + theme(**{"panel.grid.major": element_blank()})
)
```

## 3. 文本与标签

`geom_sf_text()` / `geom_sf_label()` 不是独立几何：它们是
`geom_text(stat="sf_coordinates")` / `geom_label(stat="sf_coordinates")` 的包装，
代表点来自 `stat_sf_coordinates`（面的点取在面上，线的点取在中点）。

```python
from ggcore.plot import aes, geom_sf, geom_sf_text, ggplot, labs
from ggcore.sf import sf, st_point
from ggcore.theme import theme_minimal

DATA = {
    "name": ["ashe", "surry", "wilkes"],
    "geometry": [st_point(-80.5, 36.2), st_point(-79.5, 36.6), st_point(-78.5, 36.9)],
}
POINTS = sf({"name": DATA["name"]}, geometry=DATA["geometry"])

p = (
    ggplot(POINTS, aes(label="name"))
    + geom_sf(size=3, colour="#E45756")
    + geom_sf_text(size=3.6, nudge_y=0.12, colour="#2F4B7C")
    + labs(title="geom_sf_text()", x=None, y=None)
    + theme_minimal()
)
```

`stat="sf_coordinates"` 也可以手写：`geom_text(stat="sf_coordinates")`。名字用它
自己的 `geom=` 参数（`geom_sf_text(geom="text")` 默认就是）。

## 4. 经纬度 + `coord_map()` / `coord_quickmap()`

不是 sf 对象、只有 `lon` / `lat` 列的数据，用两个老坐标：

```python
from ggcore.plot import aes, coord_map, geom_point, ggplot, labs
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "lon": [-80.5, -79.5, -78.5, -77.5],
    "lat": [35.5, 36.2, 37.0, 35.8],
    "value": [1.0, 2.0, 3.0, 2.5],
}

p = (
    ggplot(to_column_table(DATA), aes(x="lon", y="lat", colour="value"))
    + geom_point(size=3.2)
    + coord_map("mercator")
    + labs(title='coord_map("mercator")', x="longitude", y="latitude")
    + theme_minimal()
)
```

| 坐标 | 口径 |
| --- | --- |
| `coord_quickmap()` | 按中心纬度算纵横比（快，不投影坐标） |
| `coord_map(projection)` | 用 mapproj 的球面投影核（当前实现 `"mercator"` 与 `"azequalarea"`），投影后范围决定面板比例；`orientation=` 缺省 `(90, 0, mean(lon))` |

`geom_sf()` 只能配 `coord_sf()`；`coord_map()` / `coord_quickmap()` 不认 sf 几何
（上游同样如此）。

## 5. `stat_sf` 与 `stat_sf_coordinates`

- `stat_sf()`：把几何压成 `xmin` / `xmax` / `ymin` / `ymax`（配 `geom_rect()` 或
  `geom_sf()` 的图例）；
- `stat_sf_coordinates()`：几何 → 代表点（`x` / `y` 列），配文本 / 标签层。

## 6. 已知边界

- **点几何带 CRS 时会报错**：`sf(..., crs=4326)` / `st_point(..., crs=4326)` +
  `coord_sf()` 在绘制点层时抛 `SfError: 几何没有 CRS，无法投影`（`_draw_points`
  重建 multipoint 时丢了 crs）。面与线不受影响；点在**不带** CRS 时正常（面板按
  `default_crs` 解释）。这是写这份文档时按示例验证出来的缺口，另行归口修复。
- WKT 解析只覆盖点与线；`POLYGON` / `MULTIPOLYGON` 的 WKT 目前会失败，用
  `st_polygon([...], crs=...)` 直接造。
- `annotation_borders()` 只内置 `("state", "utah")` 与 `("usa", ".")` 两份地图数据。
- 投影只实现了 4326 / 3857 / 3347 与 mapproj 的 mercator / azequalarea；其余 CRS
  与投影显式报错（不引入 PROJ）。
