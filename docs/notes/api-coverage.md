# API 覆盖率（v4.0.3 NAMESPACE → 注册表 / 公开命名空间）

<!-- 生成物：`pixi run api:coverage`；`pixi run api:coverage:check` 校验阈值、
     缺口归口与本文是否最新。不要手改本文件。 -->

- 参考实现：`tidyverse/ggplot2` `v4.0.3` @ `cc1444c10edb87650fbe0cb31d56f0da1a255634`
- 分母：上游 `NAMESPACE` 里按前缀分类的导出（快照 `tools/gates/upstream_api.json`，CI 不联网）
- 门禁阈值：每个分类 ≥ 90%，整体 ≥ 90%
- 分子（判据，`public`）：注册表条目 **或** `ggcore.plot` 里的同名可调用对象；`registry` 列只数注册表，差额是那些不是组件的导出（全局主题状态、`theme_sub_*`、guide 协议钩子、`scale_type`）

| 分类 | 上游 | registry | public | 覆盖率（public） | registry 口径 | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `coord` | 12 | 11 | 12 | 100.0% | 91.7% | ✅ |
| `facet` | 3 | 3 | 3 | 100.0% | 100.0% | ✅ |
| `geom` | 53 | 49 | 49 | 92.5% | 92.5% | ✅ |
| `guide` | 17 | 12 | 17 | 100.0% | 70.6% | ✅ |
| `position` | 8 | 8 | 8 | 100.0% | 100.0% | ✅ |
| `scale` | 131 | 130 | 131 | 100.0% | 99.2% | ✅ |
| `stat` | 36 | 33 | 33 | 91.7% | 91.7% | ✅ |
| `theme` | 25 | 10 | 25 | 100.0% | 40.0% | ✅ |
| **合计** | **285** | **256** | **278** | **97.5%** | 89.8% | ✅ |

## 缺口清单

每一条都必须有 issue 归口，否则 `api:coverage:check` 直接红。

| 导出 | 归口 | 原因 |
| --- | --- | --- |
| `geom_freqpoly` | SIL-715 | `geom_freqpoly()` 是 `geom_line(stat = "bin")` 的形状；`Geom` 目前还不带「换默认 stat」的入口，登记它会让 `registered_renderers() == registered("geom")` 的不变量要求多写一个渲染器（SIL-779 钉的口径）。 |
| `geom_sf` | SIL-715 | 空间几何（M3-2）：需要 sf 数据的 *list-column* 解析与 geom_sf 的 grob 路径；M2 只做注册会破坏「注册即绘制」的不变量。 |
| `geom_sf_label` | SIL-715 | 同 `geom_sf`：M3-2 空间能力。 |
| `geom_sf_text` | SIL-715 | 同 `geom_sf`：M3-2 空间能力。 |
| `stat_density2d_filled` | SIL-715 | 上游只是 `stat_density_2d_filled` 的别名；`STAT_GEOMS` 是「一个 stat 一个默认 geom」，加别名要先决定它挂哪个 geom，排进 SIL-715 的别名清理。 |
| `stat_sf` | SIL-715 | 同 `geom_sf`：M3-2 空间能力。 |
| `stat_sf_coordinates` | SIL-715 | 同 `geom_sf`：M3-2 空间能力。 |

## 只在公开命名空间、不在注册表的导出

这些是上游导出，但不是「能加到图上的组件」，所以放在 `ggcore.plot` 的命名空间里（与上游同名同义），而不是注册表：

```text
coord_munch
guide_gengrob
guide_geom
guide_merge
guide_train
guide_transform
scale_type
theme_get
theme_replace
theme_set
theme_sub_axis
theme_sub_axis_bottom
theme_sub_axis_left
theme_sub_axis_right
theme_sub_axis_top
theme_sub_axis_x
theme_sub_axis_y
theme_sub_legend
theme_sub_panel
theme_sub_plot
theme_sub_strip
theme_update
```

## 口径边界

- 覆盖率证明的是**入口存在**，不是行为对等：行为由 `tests/` 的 R 对拍夹具与 `docs/cases/` 的快照守着。新增注册名必须同时带测试（X5 的案例层要求）。
- 换 pin 时：`pixi run api:coverage --refresh <ggplot2 源码目录>/NAMESPACE`，把 JSON 与本文一起提交。
