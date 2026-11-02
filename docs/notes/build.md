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
| `compute_aesthetics` | `.aesthetics` | 合并 mapping、求值数据美学、补 `PANEL` / `group`、统计缺失（**不删行**） |
| `compute_stat` | `.statistic` | 按 `layer.stat.name` 算统计量（`identity` / `count`） |
| `map_statistic` | `.mapped` | `after_stat(...)` 与 stat 缺省映射落成美学列 |
| `compute_position` | `.positioned` | `Geom$setup_data()`（锚点 / `flipped_aes` / line 排序）+ 位置调整 |
| `map_scales` | `.scaled` | 逐列过 `ScaleSet.map`（identity；离散位置 → 1..n） |
| `finish` | `.data` | `default_aes` + geom 字面参数，得到内置数据的最终列序 |

`build_layer(plot, layer, index, scales=None)` 单层构建；`build_plot(plot)` 按层
顺序构建，并先在所有层上训练同一套 `ScaleSet` 再统一映射。

**阶段 1 与阶段 2 之间还有一次位置标度编码**：上游 `build_ggplot()` 在
`compute_aesthetics()` 之后立刻 `layout$train_position()` + `layout$map_position()`，
stat 拿到的 x/y 已经是位置值。`build` 用 `ggcore.build.map_position()` 复现这一步，
所以 `LayerBuild.aesthetics` / `.statistic` 里的离散 x 已经是 `1..n`（与 R 的
`$data` 同口径）。

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
- `required_aes` 在 `compute_position` 开头校验（上游 `compute_geom_1` 的位置，
  即 `setup_data()` 之前），每组的 `"x|y"` 备选写法按 `required_aes_groups()`
  拆开：组里一个都没有就抛 `MissingAesError`，消息里列出缺的组与已有列。
  「参数能当美学用」的集合是 `required_aes` 展开 + `default_aes` 名字 + `group`
  （上游还有 `optional_aes`；`Geom` 目前没有这个字段，M1-7 加时同步
  `_geom_aesthetics()`）。
  `bar` / `col` / `histogram` 的 `y` 由 `stat_count` 产出，所以在 stat 之后
  校验，不要求数据里有 `y`。
- `geom_*(colour=, fill=, size=, width=, ...)` 的**字面参数**在 `finish` 里按
  上游 `use_defaults()` 的顺序写回 data：先补 `default_aes` 缺失列（列序由它
  决定），再把 `intersect(geom$aesthetics(), names(params))` 的值覆盖上去。
  参数优先于 `default_aes`，`geom_col(width = 0.3)` 同时改 `xmin/xmax`。

## 3. 缺失值

**行保留，只计数。** ggplot2 4.0.3 的 `$data` 不删 NA 行：删除发生在绘制期的
`Geom$handle_na()`，而且只看 `required_aes` + `non_missing_aes`，不看全部美学；
`na.rm = TRUE` 也不改变 `$data`（实测：`colour = NA` 的 5 行仍是 5 行）。

- 参与计算的 aes（除 `PANEL` / `group` 外的全部数据美学）逐列数 `na_mask`，
  记进 `LayerBuild.dropped_missing`（列名 → 缺失行数）；字段名是历史包袱，
  语义是「计数」，不是「已删除」。这是**全部**美学列的原始计数；M1-7 的
  `handle_na()` 要按 `required_aes` + `non_missing_aes` 过滤后再发 warning。
- `build` **不发** `Removed N rows` 的 warning——那句由 M1-7 的 `handle_na()`
  在 draw 前发。
- `na_rm` 参数对 `$data` 没有影响；M1-3 不读它。
- 离散位置的 NA 会被位置标度编码成「最后一个水平」（见 §6），所以
  `geom_bar(aes(x = c("a", NA)))` 的 NA 是一根独立的柱（4 组 → 4 根），
  `geom_col()` 则保留 `x = NA` 的那一行并给它位置。

## 4. 分组

- 用 M1-2 的 `compute_groups(mapping, table)`：显式 `aes(group=…)` 优先，否则
  离散 aes 做 interaction。**NA 也是一个水平**（上游 `id_var()` 用
  `sort(unique0(x), na.last = TRUE)`），不再是 `NO_GROUP`；只有「没有任何离散
  aes」时才全是 `NO_GROUP`。
- 水平顺序：普通字符列升序；**categorical 按 `Column.levels`**（`compute_groups`
  对裸列读源列的 levels）；逻辑值 `False` 在 `True` 前。
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

`compute_position` 先做上游 `Geom$setup_data()`（这一步在位置调整**之前**，
所以列序与 R 一致）：

- `bar` / `col` / `histogram`：追加 `flipped_aes`、`ymin = pmin(y, 0)`、
  `ymax = pmax(y, 0)`、`xmin = x - width*just`、`xmax = x + width*(1-just)`，
  然后去掉 `width` / `just`（缺省 `width` 由 `finish` 补回末尾）；
- `boxplot`：追加 `flipped_aes`、`xmin/xmax`（`width / 2`）；
- `line`：追加 `flipped_aes`，并按 `(PANEL, group, x)` 重排行序（上游
  `GeomLine$setup_data()`；`geom_path` 保持给定顺序、也没有 `flipped_aes`）。

位置调整：

- `identity`：不做任何事；
- `stack`：按 x 分组，组内按 group **降序**累加（上游 `collide(reverse =
  FALSE)`：第一个 group 在最上面），覆盖 `ymin` / `ymax` 并把 `y` 设为 `ymax`；
  正负值分开堆。x 没有重复值时退化为 identity（上游 `var = NULL` 分支）。
- `dodge` / `dodge2` / `jitter` / `fill` → `BuildError`（boxplot 的缺省 `dodge2`
  目前需要显式 `position="identity"`）。

## 6. ScaleSet（scale 接口先行）

`ScaleSet.train(values, aesthetic)` / `ScaleSet.map(values, aesthetic)` 是流水线
接触标度的**唯一**入口，所以 M1-4 换真实现时不需要动 `build.py`（测试用自定义
子类把 x 乘 2，证明没有写死的线性映射）。

本任务的 identity 口径：

- 非位置美学：原样返回（不做调色板、不做连续变换）；
- 位置美学（`x/y/xmin/xmax/ymin/ymax/xend/yend`）上的**离散**值：按水平顺序
  编码成 `1..n`；**NA 占最后一个水平**（`n + 1`），与上游
  `sort(unique(x), na.last = TRUE)` 一致——所以离散位置的 NA 在内置数据里是
  一个位置，不是 NA；
- 离散水平跨层**全局排序**：普通字符列全部升序（不是「先遇到先保留」）；
  categorical 以第一个 categorical 列的 `Column.levels` 为基底，其余水平升序
  追加；逻辑值 `False < True`；
- 连续位置列（含 int / bool 被当作连续时）统一落成 `float`，与 R 的
  `map_position()` 输出 double 一致；`group` 等非位置美学不动；
- `dodge2` / 颜色 / 形状等进入内置数据前的值由 M1-4 负责。
- **两段训练**：上游在 `compute_aesthetics` 之后训练一次、在 `compute_position`
  之后再训练一次；`build` 也保留了第二段（`build_layer` / `build_plot` 里各
  调一次 `_train`）。identity 下是幂等的；M1-4 接连续标度时 limits / expand
  需要第二段数据范围。

## 7. 空层

0 行的图层不报错：`Aesthetics.empty = True`，后续阶段给空表，`LayerBuild.data`
是 0 行；`PlotBuild.empty_layers` 留下下标。空层**不静默消失**。

## 8. 确定性

同样的 `plot` 构建两次，列名、列序、`kind`、`values` 字节、`na_mask`、`levels`
完全一致（`tests/test_build.py::test_build_is_deterministic`）。实现上只用了有序
容器（`ColumnTable` 的顺序、`dict` 插入序、`np.argsort(kind="stable")`）。

## 9. 与 R 对拍

夹具：`tests/fixtures/build_r_reference.json`，由
`pixi run -e refs refs:build`（`tools/refs/build_ref.R`）生成；产物入库，CI 不装
R。R 侧记录 `ggplot_build(p)$data[[1]]` 的列名、列序、类型与逐行值，数据集也一起
落盘，所以 Python 测试不需要 mpg / R。

16 张图（覆盖 5 类夹具外形态 + SIL-667 的 multi-layer / categorical / bool）：

| id | 图 | 覆盖 |
| --- | --- | --- |
| `point_computed` | `ggplot(mpg, aes(displ, hwy/cyl)) + geom_point()` | 计算列、连续位置、缺省 aes |
| `count_bar` | `ggplot(mpg, aes(class)) + geom_bar()` | `stat_count`、离散 x → 1..7、geom setup |
| `box_precomputed` | `geom_boxplot(stat="identity", position="identity", aes(lower=…))` | 五数预计算、boxplot 的 setup + 缺省 aes |
| `stacked_bar_interaction` | `ggplot(mpg, aes(drv, fill=class)) + geom_bar()` | 双离散 interaction + stack |
| `layer_data_override` | `ggplot(mpg, aes(displ, hwy)) + geom_point(data=mpg[cyl==4,])` | 层数据覆盖 plot 数据 |
| `point_na_colour` | `ggplot(na_point, aes(x, y, colour = g)) + geom_point()` | NA 行保留、NA 自有 group |
| `count_na_x` | `ggplot(na_x, aes(xs)) + geom_bar()` | NA x 一根独立柱（4 组 → 4 根） |
| `col_identity` | `ggplot(col_data, aes(xs, ys)) + geom_col()` | identity stat、`flipped_aes` 列序、NA x 行 |
| `col_width_param` | `… + geom_col(width = 0.3)` | 层参数写进 data、`xmin/xmax` 跟着变 |
| `line_unsorted` | `ggplot(line_data, aes(x, y, group = g)) + geom_line()` | 行序 `(PANEL, group, x)`、`flipped_aes` |
| `point_params` | `… + geom_point(colour = "red", size = 3)` | 字面参数覆盖 `default_aes` |
| `bar_fill_param` | `… + geom_bar(fill = "steelblue")` | `fill` 参数写进 data |
| `aes_reordered` | `ggplot(mpg, aes(y = hwy, x = displ)) + geom_point()` | `aes()` 名称序（x, y 最前） |
| `categorical_group` | factor levels 反序（`c("b","a")`）的 colour | group 按 levels，不按字母序 |
| `bool_discrete_x` | `x = c(TRUE, FALSE, TRUE)` | 逻辑位置 → `mapped_discrete`（FALSE=1） |
| `multi_layer_levels` | 两层 `x = cls` / `x = drv` | 跨层水平全局排序；两层 x 各自编码 |

比较口径：列名与列序必须完全一致；数值 `allclose(rtol=0, atol=1e-9)`；字符串
精确相等；缺失逐行一致；`column.kind` 与夹具的 `kind` 相等（`float` / `int` /
`bool` / `str`）——跳过值的列也比 kind，唯一例外是 `categorical_group.colour`
（我们保留 categorical code，R 的 `$data` 是 character）。规模钉死为 **214 列 / 205 列比值 /
8747 个值**；`multi_layer_levels` 的第二层另比 17 列 × 3 行。

九列只比列名与位置、不比值的列，原因都在本任务边界之外：

| 列 | 为什么 |
| --- | --- |
| `count_bar.fill` / `count_na_x.fill` / `col_identity.fill` / `col_width_param.fill` | theme_grey 的 `col_mix(ink, paper, 0.35)` = `#595959FF`；M1-10 才解析主题色，spec 里存语义名 `grey35` |
| `box_precomputed.colour` | `col_mix(ink, paper, 0.2)` = `#333333FF`；同上，spec 存 `grey20` |
| `stacked_bar_interaction.fill` | 离散 `fill` 的调色板（M1-4）；identity scale 不做颜色映射 |
| `point_na_colour.colour` | 离散 `colour` 的调色板 + NA 的 `na.value = "grey50"`（M1-4） |
| `categorical_group.colour` | 离散 `colour` 的调色板（M1-4）；我们的列保留 categorical code |
| `multi_layer_levels.fill` | 同上（theme_grey 的默认 fill） |

## 10. 不做 / 后续

- 真 scale（M1-4）、coord（M1-5）、gtable / 主题装配（M1-10）、geom 绘制（M1-7）、
  其余 stat（M1-8）、facet（M1-6）都不在这里。
- `position` 只到 `identity` / `stack`；`dodge2` 是 boxplot 缺省，暂需显式覆盖。
- `GeomBoxplot` 的 `outliers` / `varwidth` 分支未实现（预计算路径不需要）。
- 横向柱状图（只映射 `y`、由 `orientation` 推断）不在本任务范围：`stat_count`
  与 bar 的 `setup_data` 都假定有 `x`；M1-7 接 orientation 时再补。
- `geom_*(x = 1, y = 2)` 这种常量美学参数会在 `finish` 里 materialize 成列
  （required 校验也把它们算通过）；空数据框的常量参数不保证与 R 的
  `empty(data)` 分支一致。
- `y` 上的 NA 在 `stack` 下的精确列值（R 会把 `y` 归 0、`ymin/ymax` 留 NA）
  没有对拍；`na_mask` 与行数保留，绘制期口径留给 M1-7 的 `handle_na()`。
- 不碰 IR 版本；产物留到 M1-7 再进 IR。
