# 空间数据（M3-2）

`geom_sf` 族 / `stat_sf` / `coord_sf` / `coord_map` 的纯 Python 实现。口径钉在
ggplot2 4.0.3（`R/geom-sf.R`、`R/stat-sf.R`、`R/stat-sf-coordinates.R`、
`R/coord-sf.R`、`R/coord-map.R`）与 sf / mapproj 的对应算法上。

代码：

| 模块 | 内容 |
| --- | --- |
| `src/ggcore/sf.py` | `Geometry` / `CRS` / 投影（EPSG:4326 · 3857 · 3347 与 mapproj 球面 mercator）/ `st_graticule()` / `pretty()` / `format()` / `point_on_surface()` |
| `src/ggcore/sf_stat.py` | `stat_sf`（bbox → `xmin/xmax/ymin/ymax`）与 `stat_sf_coordinates`（几何 → 代表点） |
| `src/ggcore/geom/sf.py` | `geom_sf` 的绘制（点 / 线 / 面 / 几何集合按类型分派） |
| `src/ggcore/coord.py` | `SfCoord`（graticule / 度数标签 / 面板比例）与 `MapCoord`（mapproj） |
| `src/ggcore/map_data_usa.py` | `maps::map("usa", fill = TRUE)` 的 10 个多边形（逐点内联） |

## 1. 几何与 CRS

几何是 `Geometry(kind, parts, crs)`，kind 覆盖 Simple Features 的七种类型；
`parts` 的嵌套与 WKT 一致。`Column` 增加了 `kind = "geometry"`（object 数组，
NA 位放空几何），所以 `ggio.frame` 的三条输入路径都能直接收几何列。

CRS 只实现了三档（`st_crs()` 认识 EPSG:4326 / OGC:CRS84 / EPSG:3857 /
EPSG:3347 与 `+proj=longlat|merc|lcc` 的等价写法），其余**显式报错**——本仓
不引入 PROJ（X1），也不拿 identity 顶替：

```
+proj=lcc +lat_0=63.390675 +lon_0=-91.8666666666667
  +lat_1=49 +lat_2=77 +x_0=6200000 +y_0=3000000 +ellps=GRS80
```

EPSG:3347 的这组参数由 `tests/fixtures` 之外的 R 夹具核对：`sf_transform_xy()`
对 Charlotte / Raleigh / Greensboro 的返回值与 `test-coord_sf.R` 的期望值
（7275499 / 7474260 / 7357835 与 -60169 / 44384 / 57438）逐值一致（< 1e-3 m）。

## 2. `coord_sf()`

`SfCoord.panel_params()` 复刻 `CoordSf$setup_panel_params()`：

1. 数据 CRS = 第一层带 CRS 的几何（`determine_crs()`）；`crs` 显式给出时优先；
2. 标度 limits（`stat_sf` 已把 bbox 变换到 `default_crs`）与 coord limits
   先按 `lims_method`（cross / box / orthogonal / geometry_bbox）投到 `crs`；
3. 没有显式 limits 时**并上几何 bbox**（投影后的范围只是近似，bbox 四条边在
   非线性变换下不是直线）；
4. 5% expand；经纬度数据的面板比例是 `1 / cos(中心纬度)`（`CoordSf$aspect()`）；
5. `st_graticule()` 的经纬网既画面板网格（`panel.grid.major` 不是 blank 时），
   也通过 `view_scales_from_graticule()` 的贴边判定给四边轴提供位置与度数标签。

**度数标签**：上游是 `"36.25"*degree*N` 的 plotmath 表达式，本仓不做完整
plotmath，轴标签是单段文本 `36.25°N`。宽度折算按上游 `degree` 符号的 0.376em
（`ggcore.axis._PLOTMATH_DEGREE_EM`），否则 8.8px 字号下每个标签会差 0.2pt，
面板整体平移 0.2pt。

`label_axes`（缺省 `"--EN"`）与 `label_graticule`（`"NSWE"`）两套来源**相加**；
`scale_x_continuous(breaks = NULL)` 时该方向的经纬线全部清空。

## 3. `coord_map()`

`CoordMap$setup_panel_params()` 的移植：在数据范围上铺 50×50 网格，
`mapproj::mapproject()` 投影，投影后范围的宽高比就是面板比例；`transform()`
把投影值 rescale 到 `x.proj` / `y.proj`。只实现球面 `mercator`
（`x = -wlon`、`y = atanh(sin lat)`，`orientation` 缺省 `c(90, 0, mean(lon))`），
其它投影显式报错。

`map_data("usa")` 的坐标按 `maps` 3.4.2.1 的 `map("usa", fill = TRUE)` 内联在
`ggcore.map_data_usa`（10 个多边形、7243 个点）。

## 4. 图例与 `geom_sf_text/label`

- 图例 key 由**几何类型**决定（`detect_sf_type()`）：全点 → point，全线 →
  line，其余 → polygon；`geom_sf(aes(colour = ...))` 不需要用户指定
  `show.legend = "point"`。
- `geom_sf_text()` / `geom_sf_label()` 不是独立几何，是 `GeomText` /
  `GeomLabel` + `stat_sf_coordinates` + `position_nudge` 的组合（与上游
  `layer_sf()` 一致）。它们**不会**自动加 `coord_sf()`——上游的
  `geom_sf_text()` 只用默认 `coord_cartesian()`，标签坐标就是投影坐标。

## 5. 已知差异

- **`coord-sf-with-custom-guides` 未纳管**：`label_graticule = "NSWE"` +
  `guide_none()` / `guide_axis(angle=45)` / `n.dodge = 2` 的组合，图级差
  2.85%（> 2% 阈值）。面板位置与刻度集合一致，差异集中在旋转后的度数标签与
  自定义 guide 的文字排布；其余 20 条空间快照全部纳管。
- `point_on_surface()` 用面积重心近似 GEOS 的极值内点算法；对凹多边形标签
  位置最多差几个像素（`texts/labels-for-north-carolina` 实测 0.9%）。
- `format()` 只实现数值分支（共同小数位 + 前导空格补齐），足够覆盖 graticule
  的 `pretty()` 结果。
