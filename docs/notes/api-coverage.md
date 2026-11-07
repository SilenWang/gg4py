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
| `geom` | 53 | 51 | 53 | 100.0% | 96.2% | ✅ |
| `guide` | 17 | 12 | 17 | 100.0% | 70.6% | ✅ |
| `position` | 8 | 8 | 8 | 100.0% | 100.0% | ✅ |
| `scale` | 131 | 130 | 131 | 100.0% | 99.2% | ✅ |
| `stat` | 36 | 36 | 36 | 100.0% | 100.0% | ✅ |
| `theme` | 25 | 10 | 25 | 100.0% | 40.0% | ✅ |
| **合计** | **285** | **261** | **285** | **100.0%** | 91.6% | ✅ |

## 缺口清单

无缺口：上游每个导出都能在注册表或公开命名空间里找到。

## 只在公开命名空间、不在注册表的导出

这些是上游导出，但不是「能加到图上的组件」，所以放在 `ggcore.plot` 的命名空间里（与上游同名同义），而不是注册表：

```text
coord_munch
geom_sf_label
geom_sf_text
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
