# R → Python 对照表

把 ggplot2 代码搬到 gg4py 时，**函数名基本原样**：`geom_*` / `stat_*` /
`scale_*` / `coord_*` / `facet_*` / `guide_*` 与上游 v4.0.3 的 `NAMESPACE` 同名。
真正要改的是「数据怎么进来」「`aes()` 写什么」「带点的参数名」「没有的那些」。

覆盖口径：本文按上游 `NAMESPACE` 的分类逐族列出；完整逐名清单与缺口归口以
[`../notes/api-coverage.md`](../notes/api-coverage.md)（生成物）为准。

## 1. 骨架对照

| R | gg4py | 说明 |
| --- | --- | --- |
| `library(ggplot2)` | `from ggcore.plot import *` 的显式版 | 没有 attach；按需 import，见每页示例 |
| `ggplot(mpg, aes(displ, hwy))` | `ggplot(to_column_table(df), aes(x="displ", y="hwy"))` | 数据先转 `ColumnTable`；aes 用**字符串** |
| `+ geom_point()` | `+ geom_point()` | 一样 |
| `ggplot(df) + geom_point(aes(...))` | 同 | 图层级映射一样 |
| `%>%` / `\|>` | 普通赋值 / 括号 | 没有管道；`p = p + ...` 或一行链 |
| `ggsave("x.png", p, width = 7, height = 5)` | `ggsave(p, "x.png", width=7, height=5)` | 参数顺序：图在前、路径在后 |
| `print(p)` / 顶层自动打印 | `ggsave(p, ...)` 或 `ggcore.plotspec.build_scene({"plot": p})` | Python 不自动出图 |
| `qplot()` | — | 上游 4.0.3 已移除；用 `ggplot()` |
| `aes_string()` / `aes_()` | — | 同样已移除；字符串写法就是现在的 `aes()` |

最小对照：

```r
ggplot(mpg, aes(displ, hwy, colour = class)) +
  geom_point(size = 2) +
  geom_smooth(method = "lm", se = FALSE) +
  facet_wrap(~ drv, ncol = 2) +
  labs(title = "mpg", x = "displacement", y = "highway") +
  theme_minimal()
```

```python
from ggcore.plot import aes, facet_wrap, geom_point, geom_smooth, ggplot, labs
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

# mpg 的等价数据（这里只取一小组，形状与列名保持一致）
DATA = {
    "displ": [1.8, 1.8, 2.0, 2.0, 2.4, 2.4, 3.0, 3.0, 4.0, 4.0, 5.3, 5.3],
    "hwy": [29.0, 31.0, 30.0, 28.0, 27.0, 26.0, 25.0, 24.0, 20.0, 19.0, 16.0, 15.0],
    "drv": ["f", "f", "f", "f", "f", "f", "r", "r", "4", "4", "4", "4"],
    "class": ["compact"] * 4 + ["midsize"] * 4 + ["suv"] * 4,
}

p = (
    ggplot(to_column_table(DATA), aes(x="displ", y="hwy", colour="class"))
    + geom_point(size=2)
    + geom_smooth(method="lm", se=False)
    + facet_wrap("drv", ncol=2)
    + labs(title="mpg", x="displacement", y="highway")
    + theme_minimal()
)
```

## 2. 数据入口

| R | gg4py |
| --- | --- |
| `ggplot(df, ...)`（data.frame） | `gio.frame.to_column_table(df)` 后传给 `ggplot()`；pandas.DataFrame / pyarrow.Table / dict 都收 |
| `Categorical` / `factor(x, levels=)` | pandas `Categorical` 保 categories 顺序；普通字符串列按升序去重（见 [`data.md`](data.md)） |
| `NA` | `None` / `numpy.nan` / `pandas.NA` / `NaT` 都落成缺失掩码 |
| `Date` / `POSIXct` | `datetime.date` / `datetime.datetime`（或 pandas 的 datetime64 列） |
| `sf` 对象 | `ggcore.sf.sf(data, geometry=[...], crs=...)`（见 [`sf.md`](sf.md)） |
| `read.csv()` | `ggio.csv.read_csv("x.csv")` 或自带 DataFrame |

## 3. `aes()` 与求值

| R | gg4py | 备注 |
| --- | --- | --- |
| `aes(x = displ)` | `aes(x="displ")` | 列名写成标识符字符串 |
| `aes(x = displ / cyl)` | `aes(x="displ / cyl")` | 白名单表达式（算术 / 比较 / 逻辑 / 条件 / 少量函数） |
| `aes(x = log(displ))` | `aes(x="log(displ)")` | `log` / `log10` / `sqrt` / `exp` / `abs` / `round` / `where` 等裸名可用 |
| `aes(x = \`my col\`)` | `aes(x='col("my col")')` | 列名不是合法标识符时用 `col()` |
| `aes(colour = "red")` | `aes(colour="'red'")` | 字符串常量要带内层引号；或写成 `geom_point(colour="red")` |
| `aes(y = ..count..)` | `aes(y=after_stat("count"))` | `..count..` 是旧写法，4.0 起用 `after_stat()` |
| `aes(group = a)` / `aes(group = interaction(a, b))` | `aes(group="a")` / `aes(group="a + b")` | 显式分组；离散列用 `+` 拼接，`interaction()` 不在白名单 |
| `aes(size = wt, colour = factor(cyl))` | `aes(size="wt", colour="cyl")` | 离散列自动当分类 |
| `aes(x = -density)` | `aes(x="-density")` | 一元负号在白名单里 |
| `aes(sample = y)` | `aes(sample="y")` | `stat_qq` / `stat_qq_line` |
| `aes(weight = w)` | `aes(weight="w")` | 支持的 stat 会消费 |

## 4. `geom_*`（53 个上游导出）

函数名与上游一致，逐族列出；「备注」只写差异，没写就是同名同义。

| 族 | 名字 |
| --- | --- |
| 点 / 线 / 路径 | `geom_point` `geom_jitter` `geom_line` `geom_path` `geom_step` `geom_segment` `geom_curve` `geom_spoke` `geom_rug` `geom_blank` |
| 柱 / 面 | `geom_bar` `geom_col` `geom_histogram` `geom_area` `geom_ribbon` `geom_rect` `geom_tile` `geom_raster` `geom_polygon` `geom_map` |
| 区间 / 分布 | `geom_boxplot` `geom_violin` `geom_dotplot` `geom_crossbar` `geom_errorbar` `geom_errorbarh` `geom_linerange` `geom_pointrange` |
| 文本 | `geom_text` `geom_label` |
| 2D / 密度 | `geom_bin2d` `geom_bin_2d` `geom_hex` `geom_contour` `geom_contour_filled` `geom_density` `geom_density2d` `geom_density_2d` `geom_density2d_filled` `geom_density_2d_filled` `geom_count` |
| 参考线 | `geom_abline` `geom_hline` `geom_vline` |
| 统计快捷 | `geom_smooth` `geom_quantile` `geom_function` `geom_qq` `geom_qq_line` |
| 空间 | `geom_sf` `geom_sf_text` `geom_sf_label` |
| **缺口** | `geom_freqpoly` → 写 `geom_line(stat="bin")`（同一个 stat，只是换 geom） |

常用参数差异：

| R 参数 | gg4py |
| --- | --- |
| `size = 3`（线的粗细，已弃用） | 线 / 边框用 `linewidth=1.2`；`size` 仍是点的大小 |
| `linewidth = 1.2` | `linewidth=1.2` |
| `colour = "red"` / `color =` | 两个都收；`color` 自动标准化成 `colour` |
| `na.rm = TRUE` | `na_rm=True` |
| `show.legend = FALSE` | `show_legend=False` |
| `inherit.aes = FALSE` | `inherit_aes=False` |
| `position = position_dodge(width = .9)` | `position=position_dodge(width=0.9)`，或 `position="dodge"` |
| `stat = "identity"` | `stat="identity"` |
| `data = other_df` | `data=to_column_table(other_df)` |
| `mapping = aes(...)`（位置参数 1） | `geom_point(aes(...))` |

## 5. `stat_*`（36 个上游导出）

| 族 | 名字 |
| --- | --- |
| 基础 | `stat_identity` `stat_manual` `stat_unique` `stat_align` |
| 分箱 / 计数 | `stat_bin` `stat_count` `stat_sum` `stat_summary_bin` |
| 分布 | `stat_boxplot` `stat_ydensity` `stat_density` `stat_ecdf` `stat_qq` `stat_qq_line` `stat_ellipse` `stat_quantile` `stat_function` `stat_connect` |
| 拟合 | `stat_smooth` |
| 汇总 | `stat_summary` |
| 2D | `stat_bin_2d` `stat_bin2d` `stat_bin_hex` `stat_binhex` `stat_summary_2d` `stat_summary2d` `stat_summary_hex` `stat_contour` `stat_contour_filled` `stat_density_2d` `stat_density2d` |
| 空间 | `stat_sf` `stat_sf_coordinates` |
| **缺口** | `stat_density2d_filled` → 写 `stat_density_2d_filled()`（上游它只是下划线的别名） |
| **废弃** | `stat_spoke`：上游 4.0.3 是 `deprecate_stop()`，调用即报错；改用 `geom_spoke()` |

stat 也有「快捷方式」写法：`stat_*(geom=)` 换绘制几何，`geom_*(stat=)` 换统计
变换。参数路由与上游一致：`stat_bin(bins=30)` 的参数进 stat，
`geom_histogram(bins=30)` 的参数进 geom 层（见 [`stat.md`](stat.md)）。

## 6. `scale_*`（131 个上游导出）

位置标度：

| R | gg4py | 备注 |
| --- | --- | --- |
| `scale_x_continuous` / `scale_y_continuous` | 同名 | `limits` / `breaks` / `labels` / `expand` / `oob` / `sec.axis`→`sec_axis` |
| `scale_x_discrete` / `scale_y_discrete` | 同名 | `limits` 给顺序；`labels` |
| `scale_x_binned` / `scale_y_binned` | 同名 | `n_breaks` |
| `scale_x_log10` / `scale_y_log10` / `scale_x_sqrt` / `scale_x_reverse` | 同名 | 都是 `trans` 的糖 |
| `scale_x_date` / `scale_x_datetime` / `scale_x_time` | 同名 | `date_breaks` / `date_labels`；`breaks` 给数值（日 / 秒） |
| `scale_x_continuous(trans = "log10")` | `trans="log10"` | 也收 `"reverse"` / `"sqrt"` / `"pseudo_log"` / 复合变换 |

颜色 / 填充 / 其它美学（`colour` 与 `color` 两套名字都在）：

| 族 | 名字（把 `colour_` 换成 `fill_` / `size_` / `alpha_` / `shape_` / `linetype_` / `linewidth_` 同类都在） |
| --- | --- |
| 连续渐变 | `scale_colour_continuous` `scale_colour_gradient` `scale_colour_gradient2` `scale_colour_gradientn` `scale_colour_steps` `scale_colour_steps2` `scale_colour_stepsn` |
| 离散色板 | `scale_colour_discrete` `scale_colour_hue` `scale_colour_grey` `scale_colour_brewer` `scale_colour_viridis_d` `scale_colour_ordinal` `scale_colour_manual` `scale_colour_identity` |
| 分箱 | `scale_colour_binned` `scale_colour_viridis_b` `scale_colour_fermenter` `scale_colour_distiller` |
| 日期时间 | `scale_colour_date` `scale_colour_datetime` |
| 大小 / 形状 | `scale_size` `scale_size_area` `scale_size_binned` `scale_size_binned_area` `scale_radius` `scale_shape` `scale_shape_manual` `scale_shape_identity` |
| 透明度 / 线型 | `scale_alpha` `scale_alpha_binned` `scale_linetype` `scale_linetype_manual` `scale_linetype_identity` `scale_linewidth` |
| 跨美学 | `scale_discrete_manual` `scale_discrete_identity` `scale_continuous_identity`（用 `aesthetics=` 选一个美学） |

参数名与 R 一致（`limits` / `breaks` / `labels` / `na.value` → `na_value` /
`values` / `range` / `palette` / `direction` / `option` / `n_bins`）。

## 7. 其它组件

| 类别 | R | gg4py |
| --- | --- | --- |
| 坐标 | `coord_cartesian` `coord_fixed` `coord_equal` `coord_flip` `coord_trans` `coord_transform` `coord_polar` `coord_radial` `coord_sf` `coord_map` `coord_quickmap` | 同名；`coord_munch()` 也在公开命名空间 |
| 分面 | `facet_wrap` `facet_grid` `facet_null` | 同名；`facet_wrap("~ x")` 的公式写法不支持，写 `facet_wrap("x")`；`as.table` / `strip.position` 这类带点参数用 `**{"as.table": False}` |
| 图例 | `guide_legend` `guide_colourbar` `guide_colorbar` `guide_bins` `guide_coloursteps` `guide_colorsteps` `guide_axis` `guide_axis_logticks` `guide_axis_stack` `guide_axis_theta` `guide_none` `guide_custom` | 同名；`guide_gengrob` / `guide_geom` / `guide_merge` / `guide_train` / `guide_transform` 是 guide 协议钩子，不直接用在图上 |
| 位置 | `position_identity` `position_stack` `position_fill` `position_dodge` `position_dodge2` `position_jitter` `position_jitterdodge` `position_nudge` | 同名；`width` / `height` 参数同上游，`position_nudge(x=, y=)` 也同名 |
| 主题 | `theme` `theme_grey` `theme_gray` `theme_bw` `theme_classic` `theme_light` `theme_dark` `theme_linedraw` `theme_minimal` `theme_test` `theme_void` `element_text` `element_line` `element_rect` `element_point` `element_polygon` `element_geom` `element_blank` `rel` `margin` | `theme()` 与 `element_*()` 从 `ggcore.theme` import；主题名从 `ggcore.plot` 或 `ggcore.theme` 取；`theme_sub_*` 简写与 `theme_get/set/update/replace` 在 `ggcore.plot` |
| 标签 | `labs` `ggtitle` `xlab` `ylab` `labs(x = NULL)` | 只有 `labs()`：`labs(title=, subtitle=, caption=, tag=, x=, y=, colour=)`；`NULL` 用 `None` |
| 注记 | `annotate` `annotation_logticks` `annotation_borders`（`borders` 已废弃） | 同名 |
| 映射入口 | `aes` `after_stat` `aes_` | `aes` / `after_stat`；`aes_` 已移除 |
| 箭头 / 图案 | `arrow` `linearGradient` `radialGradient` `pattern` | `arrow` `linear_gradient` `radial_gradient` `tile_pattern`（画进 `fill`） |
| 次轴 | `sec_axis` `dup_axis` | 同名（`scale_*(sec_axis=...)` 用） |
| 默认值 | `update_geom_defaults` | 同名（`update_geom_defaults("point", aes(colour="blue"))`） |
| 分面标签 | `label_value` `label_both` `label_context` `label_parsed` `labeller` | 同名 |

其中 `theme()` 的元素名带点（`panel.grid.major`），Python 关键字不能带点，所以
用 `**{...}` 传：

```python
from ggcore.plot import aes, geom_point, geom_smooth, ggplot, labs
from ggcore.theme import element_blank, element_text, theme, theme_minimal
from ggio.frame import to_column_table

DATA = {
    "displ": [1.8, 2.0, 2.4, 3.0, 4.0, 5.3],
    "hwy": [29.0, 30.0, 27.0, 25.0, 20.0, 16.0],
    "drv": ["f", "f", "f", "r", "4", "4"],
}

p = (
    ggplot(to_column_table(DATA), aes(x="displ", y="hwy"))
    + geom_point(size=2)
    + geom_smooth(method="lm", se=False, linewidth=1.2)
    + labs(title="mpg", x="displacement", y="highway")
    + theme_minimal()
    + theme(
        **{
            "panel.grid.minor": element_blank(),
            "axis.text": element_text(size=9, colour="#4D4D4D"),
            "legend.position": "none",
        }
    )
)
```

## 8. 缺口与等价写法

| 上游 | 现状 | 等价写法 |
| --- | --- | --- |
| `geom_freqpoly()` | 未登记（`geom` 52/53） | `geom_line(stat="bin")` |
| `stat_density2d_filled()` | 未登记 | `stat_density_2d_filled()` |
| `qplot()` / `aes_string()` / `aes_()` / `stat_spoke()` | 4.0.3 自身已移除或废弃 | `ggplot()` / `aes(x="col")` / `geom_spoke()` |

`../notes/api-coverage.md` 有逐条归口；两条缺口都登记在无法绕开的别名清理任务里。

## 9. 第三方扩展的等价写法（不做同名 API）

gg4py 只复刻 ggplot2 本体，**不提供**第三方扩展包的名字。下面这些需求用本体能力
拼出来（版面组合除外，见第一行）：

| 扩展包 | 需求 | 本体写法 |
| --- | --- | --- |
| `patchwork` / `cowplot` | 多图拼版 | 目前**不提供**版面组合 API；一张图一个文件，拼版在文档/报告层做（或后续另立项）。不要伪造 `wrap_plots()` |
| `ggrepel` | 标签避让 | `geom_text(check_overlap=True)`；或手动 `nudge_x` / `nudge_y` 调位置，必要时配合 `geom_label()` |
| `ggforce`（`geom_mark_*` / `facet_zoom`） | 圈注 / 局部放大 | `annotate("rect", ...)` 画框 + `annotate("text", ...)` 写注；放大用第二个 `ggplot()` 单独画，或 `coord_cartesian(xlim=, ylim=)` 裁窗 |
| `ggforce`（`geom_split_violin`） | 分组小提琴 | 用 `geom_violin(position=position_dodge(width=0.9))` 近似（两半合并成一个）；`position_dodge2(preserve="single")` 可让宽度对齐 |
| `ggforce`（`geom_stream`） | 流图 | 把每组的上下界算成列，用 `geom_ribbon(aes(ymin=, ymax=, fill=))` 叠 |
| `ggdendro` | 树状图 | 在 Python 里算好线段端点，用 `geom_segment()` + `geom_text()` 画；不实现 `dendro_data()` |
| `treemapify` | 矩形树图 | 在 Python 里算好每块的 `xmin/xmax/ymin/ymax`，用 `geom_rect()` + `geom_text()` |
| `ggraph` | 网络图 | 用任意布局算法（networkx 等，**不在 ggcore 依赖里**）算坐标，再用 `geom_segment()` + `geom_point()` + `geom_text()` |

## 10. 移植清单

1. 数据先过 `gio.frame.to_column_table()`；日期列用 `datetime.date` /
   `datetime.datetime`，不要用字符串。
2. `aes()` 的列名改成字符串；`..count..` 一律换 `after_stat("count")`。
3. `size`（线的粗细）换 `linewidth`；带点的参数名换下划线或用 `**{...}`。
4. `facet_wrap(~ a)` 换 `facet_wrap("a")`；`facet_grid(a ~ b)` 换
   `facet_grid(rows="a", cols="b")`。
5. `theme(element)` 从 `ggcore.theme` import；元素名用 `**{"panel.grid": ...}`。
6. `ggsave()` 改成 `ggsave(p, "x.png", ...)`；Python 不自动出图。
7. 跑一遍 `pixi run docs:guide`（本文的示例也在门禁里），再跑
   `pixi run check`。
