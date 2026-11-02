# 图层流水线口径（M1-3）

`ggcore.build` 把 `ggplot` + `Layer` 变成「每层已算好的数据」：六个阶段各自产出
一张可单独取出的表，最后一张（`finish`）与 ggplot2 4.0.3 的
`ggplot_build(p)$data[[i]]` 逐列对齐。**本任务不产出 gtable、不出图**；IR 在
M1-7 才接。

代码：`src/ggcore/build.py`。测试：`tests/test_build.py`（阶段 / 负向）、
`tests/test_build_r_parity.py`（R 对拍）。

```
compute_aesthetics → compute_stat → map_statistic → compute_position → map_scales → finish
```

| 阶段 | 产出（`LayerBuild` 字段） | 做什么 |
| --- | --- | --- |
| `compute_aesthetics` | `.aesthetics` | 合并 mapping、求值数据美学、补 `PANEL` / `group`、删缺失行 |
| `compute_stat` | `.statistic` | 按 `layer.stat.name` 算统计量（`identity` / `count`） |
| `map_statistic` | `.mapped` | `after_stat(...)` 与 stat 缺省映射落成美学列 |
| `compute_position` | `.positioned` | 位置调整（`identity` / `stack`） |
| `map_scales` | `.scaled` | 逐列过 `ScaleSet.map`（identity；离散位置 → 1..n） |
| `finish` | `.data` | geom 派生坐标列 + `default_aes`，得到内置数据的最终列序 |

`build_layer(plot, layer, index, scales=None)` 单层构建；`build_plot(plot)` 按层
顺序构建，并先在所有层上训练同一套 `ScaleSet` 再统一映射。

## 1. 数据优先级与 mapping 合并

- **数据**：`layer.data` 非 `None` 时用它，否则用 `plot.data`。两者都没有 → 空表
  （0 行），走「空层」路径（见 §7）。
- **mapping**：层 mapping 在前，plot mapping 补缺；`inherit_aes=False` 时只用层
  mapping。这与上游 `Layer$computed_mapping`（`defaults(self$mapping,
  plot$mapping)`）一致，**列序也按合并后的顺序走**。
- 输入必须是 `ggcore.data.ColumnTable`。`ggcore` 不 import pandas / Arrow（X1），
  DataFrame-like 请在包外 `ggio.frame.to_column_table(df)`，否则 `BuildError`
  会给出这条指引。

## 2. 缺省 aes 与必需 aes

- `Geom.default_aes` 按 **spec 的键顺序**把缺失列追加到末尾（上游
  `Geom$use_defaults()`）。为此 `registry.GEOM_SPECS` 的 `default_aes` 键序与
  4.0.3 的 `aes(...)` 书写顺序一致——这是对拍列序的一部分，别随手重排。
- 缺省值 `None` 落成整列 `NA`（`na_mask` 全真），字符串 / 数字 / 布尔按标量广播。
- `required_aes` 在 `finish` 开头校验（上游 `compute_geom_1` 的位置），每组的
  `"x|y"` 备选写法按 `required_aes_groups()` 拆开：组里一个都没有就抛
  `MissingAesError`，消息里列出缺的组与已有列。`bar` / `col` / `histogram` 的
  `y` 由 `stat_count` 产出，所以在 stat 之后校验，不要求数据里有 `y`。

## 3. 缺失值

参与计算的 aes（除 `PANEL` / `group` 外的全部数据美学）逐列数 `na_mask`，然后
**整行删除**：

- `LayerBuild.dropped_missing` 记「列名 → 该列缺失的行数」；
- `na_rm=False`（缺省）时发 `BuildWarning`，消息带层下标、geom 名、被删行数与
  逐列计数，例如 `layer[0]（geom_point）删除了 1 行含缺失值的观测（y: 1）`；
- `geom_*(na_rm=True)`（落在 `Layer.params["na_rm"]`）只计数不告警。

分组 id 在删行**之前**算（与上游先 `add_group()`、stat 里再 `remove_missing()`
的顺序一致），删行不会重编号。

## 4. 分组

- 用 M1-2 的 `compute_groups(mapping, table)`：显式 `aes(group=…)` 优先，否则
  离散 aes 做 interaction；NA 行是 `NO_GROUP`。
- M1-2 的 id 从 **0** 起；ggplot2 内置数据从 **1** 起。`compute_aesthetics` 统一
  `+1`，`NO_GROUP = -1` 原样保留，所以对拍的是同一套编号。
- 分组编号口径在 M1-3 对拍时修正过：上游 `id()` 是
  `match(x, sort(unique(x)))`，**不是首次出现顺序**，且第一个 aes 变化最慢。
  `ggcore.eval` 的 `_value_codes` / `_ids_from_keys` 已按此实现，
  `docs/notes/aes.md` §6 同步更新。

## 5. stat 与 position

`stat` 名来自 `Layer.stat`（构造器已按 `GEOM_SPECS[geom].stat` / `STAT_GEOMS`
填好缺省，`geom_*(stat=...)` 覆盖）：

- `identity`：数据美学原样通过；
- `count`：每个 group 内按 x 汇总 `count`、`prop = count / sum(abs(count))`，输出
  列序 `count, prop, x, flipped_aes, <组内恒定的其余列（含 PANEL / group）>`；
  组内变化的列丢弃并发 `BuildWarning`（上游同样丢弃）。
- 其它（`bin` / `boxplot` / `smooth` / `align`）→ `BuildError`，消息点名「M1-8」，
  不静默当成 identity。

`position`：

- `identity`：不做任何事；
- `stack`：按 x 分组，组内按 group **降序**累加（上游 `collide(reverse =
  FALSE)`：第一个 group 在最上面），写 `ymin` / `ymax` 并把 `y` 设为 `ymax`；
  正负值分开堆。x 没有重复值时退化为 identity（上游 `var = NULL` 分支），
  bar 的 `ymin/ymax` 锚点由 `finish` 的 geom setup 补。
- `dodge` / `dodge2` / `jitter` / `fill` → `BuildError`（boxplot 的缺省 `dodge2`
  目前需要显式 `position="identity"`）。

## 6. ScaleSet（scale 接口先行）

`ScaleSet.train(values, aesthetic)` / `ScaleSet.map(values, aesthetic)` 是流水线
接触标度的**唯一**入口，所以 M1-4 换真实现时不需要动 `build.py`（测试用自定义
子类把 x 乘 2，证明没有写死的线性映射）。

本任务的 identity 口径：

- 非位置美学：原样返回（不做调色板、不做连续变换）；
- 位置美学（`x/y/xmin/xmax/ymin/ymax/xend/yend`）上的**离散**值：按水平顺序
  编码成 `1..n`——这是 ggplot2 缺省离散位置标度的行为，不是线性映射；
- `dodge2` / 颜色 / 形状等进入内置数据前的值由 M1-4 负责。
- 跨层训练：`build_plot` 先在所有层上 `train`，再统一 `map`；离散水平按「先遇到
  先保留」合并（同一列跨层时与 R 的排序一致）。

## 7. 空层

0 行的图层不报错：`Aesthetics.empty = True`，后续阶段给空表，`LayerBuild.data`
是 0 行；`PlotBuild.empty_layers` 留下下标，`build_plot` 的 `warnings` 也会带出
缺失值提示。空层**不静默消失**。

## 8. 确定性

同样的 `plot` 构建两次，列名、列序、`kind`、`values` 字节、`na_mask`、`levels`
完全一致（`tests/test_build.py::test_build_is_deterministic`）。实现上只用了有序
容器（`ColumnTable` 的顺序、`dict` 插入序、`np.argsort(kind="stable")`）。

## 9. 与 R 对拍

夹具：`tests/fixtures/build_r_reference.json`，由
`pixi run -e refs refs:build`（`tools/refs/build_ref.R`）生成；产物入库，CI 不装
R。R 侧记录 `ggplot_build(p)$data[[1]]` 的列名、列序、类型与逐行值，数据集也一起
落盘，所以 Python 测试不需要 mpg / R。

五张图：

| id | 图 | 覆盖 |
| --- | --- | --- |
| `point_computed` | `ggplot(mpg, aes(displ, hwy/cyl)) + geom_point()` | 计算列、连续位置、缺省 aes |
| `count_bar` | `ggplot(mpg, aes(class)) + geom_bar()` | `stat_count`、离散 x → 1..7、geom setup |
| `box_precomputed` | `geom_boxplot(stat="identity", position="identity", aes(lower=…))` | 五数预计算、boxplot 的 setup + 缺省 aes |
| `stacked_bar_interaction` | `ggplot(mpg, aes(drv, fill=class)) + geom_bar()` | 双离散 interaction + stack |
| `layer_data_override` | `ggplot(mpg, aes(displ, hwy)) + geom_point(data=mpg[cyl==4,])` | 层数据覆盖 plot 数据 |

比较口径：列名与列序必须完全一致；数值 `allclose(rtol=0, atol=1e-9)`；字符串
精确相等；缺失逐行一致。规模钉死为 **74 列 / 71 列比值 / 3530 个值**。

三列只比列名与位置、不比值的列，原因都在本任务边界之外：

| 列 | 为什么 |
| --- | --- |
| `count_bar.fill` | theme_grey 的 `col_mix(ink, paper, 0.35)` = `#595959FF`；M1-10 才解析主题色，spec 里存语义名 `grey35` |
| `box_precomputed.colour` | `col_mix(ink, paper, 0.2)` = `#333333FF`；同上，spec 存 `grey20` |
| `stacked_bar_interaction.fill` | 离散 `fill` 的调色板（M1-4）；identity scale 不做颜色映射 |

## 10. 不做 / 后续

- 真 scale（M1-4）、coord（M1-5）、gtable / 主题装配（M1-10）、geom 绘制（M1-7）、
  其余 stat（M1-8）、facet（M1-6）都不在这里。
- `position` 只到 `identity` / `stack`；`dodge2` 是 boxplot 缺省，暂需显式覆盖。
- `GeomBoxplot` 的 `outliers` / `varwidth` 分支未实现（预计算路径不需要）。
- 不碰 IR 版本；产物留到 M1-7 再进 IR。
