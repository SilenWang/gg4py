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
| `compute_stat` | `.statistic` | 按 `layer.stat.name` 算统计量（六个 stat 都在 `ggcore.stat`，见 `stat.md`） |
| `map_statistic` | `.mapped` | `after_stat(...)` 与 stat 缺省映射落成美学列 |
| `compute_position` | `.positioned` | `Geom$setup_data()`（锚点 / `flipped_aes` / line 排序）+ 位置调整 |
| `map_scales` | `.scaled` | 逐列过 `ScaleSet.map`（M1-4 真实标度：离散位置 → 1..n、连续位置 → 变换后的值、colour/fill/size/shape/alpha → 调色板 / rescale） |
| `finish` | `.data` | `default_aes` + geom 字面参数，得到内置数据的最终列序 |

`build_layer(plot, layer, index, scales=None)` 单层构建；`build_plot(plot)` 按层
顺序构建，并先在所有层上训练同一套 `ScaleSet` 再统一映射。

**阶段 1 与阶段 2 之间还有一次位置标度编码**：上游 `build_ggplot()` 在
`compute_aesthetics()` 之后先 `scales$transform_df()`、再
`layout$train_position()` + `layout$map_position()`，stat 拿到的 x/y 已经是位置值
（离散 → `1..n`，连续 → 变换后的值）。`build` 用 `transform_scales()` +
`map_position()` 复现这两步，所以 `LayerBuild.aesthetics` / `.statistic` 里的
离散 x 已经是 `1..n`、`scale_x_log10()` 的 x 已经是 log10 空间（与 R 的 `$data`
同口径）。

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
填好缺省，`geom_*(stat=...)` 覆盖）。**六个 stat 全部在 `ggcore.stat`（M1-8）**，
口径全文见 `docs/notes/stat.md`，这里只记与本模块的接线：

- `identity`：数据美学原样通过（`compute_stat()` 直接返回 `.table`）；
- `count`：每个 group 内按 x（横向按 y）汇总 `count`、`prop = count / sum(abs(count))`，
  输出列序 `count, prop, x, flipped_aes, <组内恒定的其余列（含 PANEL / group）>`；
  组内变化的列丢弃并发 `BuildWarning`（上游同样丢弃）；
- `bin` / `boxplot` / `smooth` / `align`：`compute_stat(layer, aesthetics,
  scales=…, raw=…)` 交给 `ggcore.stat.compute_stat()`。`scales` 是这一面板的
  `ScaleSet`（`bin` 的断点、`smooth(fullrange = TRUE)` 要用），`raw` 是位置
  映射前的美学表（横向判定）。分面时逐面板取 `PanelScales.for_panel(panel)`；
- 不认识的名字 → `BuildError`，消息里列出已实现的 stat，不静默当成 identity。

`stat` 自己补的缺省美学（上游 `Stat$default_aes`）在 `map_statistic()` 里落成
列：`count` / `bin` 的 `x`、`y` 都指向 `after_stat(count)`（缺哪个补哪个），
所以 `geom_histogram(aes(x))` 不需要写 `y`。用户显式写的 `after_stat(...)` 优先。

`compute_position` 先做上游 `Geom$setup_data()`（这一步在位置调整**之前**，
所以列序与 R 一致）：

- `bar` / `col` / `histogram`：追加 `flipped_aes`、`ymin = pmin(y, 0)`、
  `ymax = pmax(y, 0)`、`xmin = x - width*just`、`xmax = x + width*(1-just)`，
  然后去掉 `width` / `just`（缺省 `width` 由 `finish` 补回末尾）；
- `boxplot`：追加 `flipped_aes`、`xmin/xmax`（`width / 2`）；
- `line`：追加 `flipped_aes`，并按 `(PANEL, group, x)` 重排行序（上游
  `GeomLine$setup_data()`；`geom_path` 保持给定顺序、也没有 `flipped_aes`）。

位置调整（M1-9 起全部在 `ggcore.position`，口径见 `docs/notes/position.md`）：

- `identity`：不做任何事；
- `stack`：按 x 分组，组内按 group **降序**（上游 `collide(reverse = FALSE)`：
  第一个 group 在最上面）；区间用上游 `pos_stack()` 的口径——
  `heights = c(0, cumsum(y))`，`ymin/ymax = pmin/pmax(heights[-n], heights[-1])`，
  再 `y = (1-vjust)*ymin + vjust*ymax`（不要用 `height - y`，负值段会反）。
  正负值分开堆；x 没有重复值时退化为 identity（上游 `var = NULL` 分支）。
- `stack` 下 **y = NA** 的行：我们保留有效坐标（x / xmin / xmax 不抹掉），把
  该行当零高度参与累计（`ymin == ymax`，绘制效果与 R 一致）；不复刻上游
  `collide` 按 `xmin` 走 `dapply` 时把整行坐标抹成 `NA` 的副作用。
- `fill` / `dodge` / `dodge2` / `jitter` / `nudge`：`compute_position()` 按名字
  查注册表分派（`registry.construct("position", …)`），与 `position_*()` /
  `p.position_*()` 同源。boxplot 的缺省 `dodge2` 现在开箱可用。

## 6. ScaleSet（M1-4 起是真实标度）

`ScaleSet.train(values, aesthetic)` / `ScaleSet.map(values, aesthetic)` 仍是流水线
接触标度的**唯一**入口（`tests/test_build.py` 用自定义子类把 x 乘 2，证明六阶段
没有写死线性映射）。M1-4 起 `ggcore.build` 里的 `ScaleSet` 就是
`ggcore.scales.ScaleSet`，口径全文见 `docs/notes/scales.md`，这里只记与本模块的
接线：

- `build_plot()` / `build_layer()` 用 `ScaleSet(plot.scales)`：`p + scale_*()`
  的显式标度优先，其余按列类型解析默认标度；
- `transform_scales()`（新增）= 上游 `scales$transform_df()`：位置数据在训练前
  先做变换（`scale_x_log10()` 的 x 因此在 log10 空间）；
- **两段训练**：`compute_aesthetics` 之后一次，`compute_position` 之后再一次；
  第二段用 **positioned** 数据（含 `xmin/xmax/ymin/ymax`），否则柱子的锚点会被
  stage 5 的 oob censor 成 NA；
- `map_position()` 只映射位置美学（上游 `layout$map_position()` 的口径）；
- 阶段 5 `map_scales()` 映射全部美学：位置 → censor（幂等），
  colour / fill / size / shape / alpha → 调色板 / rescale；
- `xmin/xmax/xend` 共用 x 标度、`ymin/ymax/yend` 共用 y 标度；数值列进离散位置
  标度时原样通过；
- `ScaleSet.trained` 仍然给「美学 → 离散水平」（M1-3 的测试与夹具在用）。

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

17 张图（覆盖 5 类夹具外形态 + SIL-667 的 multi-layer / categorical / bool +
负值 stack）：

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
| `col_negative_stack` | 8 行正负混合的 `geom_col()` | 负值 stack 的 `ymin/ymax`（相邻累计 min/max） |

比较口径：列名与列序必须完全一致；数值 `allclose(rtol=0, atol=1e-9)`；字符串
精确相等；缺失逐行一致；`column.kind` 与夹具的 `kind` 相等（`float` / `int` /
`bool` / `str`）——跳过值的列也比 kind。规模钉死为 **229 列 / 223 列比值 /
8887 个值**；`multi_layer_levels` 的第二层另比 17 列 × 3 行。

M1-4 起 colour / fill 走真实标度，原先跳过的四列（`stacked_bar_interaction.fill`、
`point_na_colour.colour`、`categorical_group.colour`、`col_negative_stack.fill`）
已经与 R 逐值相等，不再跳过。只剩主题色那六列只比列名与位置：

| 列 | 为什么 |
| --- | --- |
| `count_bar.fill` / `count_na_x.fill` / `col_identity.fill` / `col_width_param.fill` | theme_grey 的 `col_mix(ink, paper, 0.35)` = `#595959FF`；M1-10 才解析主题色，spec 里存语义名 `grey35` |
| `box_precomputed.colour` | `col_mix(ink, paper, 0.2)` = `#333333FF`；同上，spec 存 `grey20` |
| `multi_layer_levels.fill` | 同上（theme_grey 的默认 fill） |

## 10. 不做 / 后续

- geom 绘制（M1-7）与 stat 实现（M1-8，`src/ggcore/stat.py`）都不在这里；stat 的
  参数 / 列口径 / 与 R 的已知差异见 `docs/notes/stat.md`。标度见
  `docs/notes/scales.md`（M1-4 已接上），分面布局 / 逐面板流水线见
  `docs/notes/facet.md`（M1-6：`build_plot()` 已接线，单面板路径保持逐字节不变），
  position 的七种调整见 `docs/notes/position.md`（M1-9）。
- 横向（`orientation = "y"`）的 `flipped_aes` 检测：stat 侧在
  `ggcore.stat._has_flipped_aes()`，geom 侧在 `GeomRenderer.setup_params()`
  （`Geom$setup_params()`），后者**先读 stat 产出的 `data$flipped_aes` 列**
  （上游 `has_flipped_aes()` 的第一分支），读不到才按 `orientation` / 映射前的
  列类型推断。横向柱状图（`geom_bar` / `stat_count`）、横向箱线图、横向
  `geom_area`、横向 `geom_histogram`（`aes(y = <连续>)`，断点取 y 标度）都已
  端到端可用；横向 `geom_smooth` 见 `docs/notes/stat.md` §5（`fullrange` 的
  `xseq` 仍取 x 标度，与 R 一致）。
- `GeomBoxplot` 的 `outliers` / `varwidth` 分支：M1-8 的 `stat_boxplot` 已产出
  `outliers`（`str` 文本）与 `relvarwidth`，geom 的 `setup_data()` 直接消费。
- `geom_*(x = 1, y = 2)` 这种常量美学参数会在 `finish` 里 materialize 成列
  （required 校验也把它们算通过）；空数据框的常量参数不保证与 R 的
  `empty(data)` 分支一致。
- `y` 上的 NA 在 `stack` 下按「保留坐标 + 零高度」处理（§5），不与 R 的
  `x → NA` artifact 对拍；绘制期口径留给 M1-7 的 `handle_na()`。
- `stat` 的输入删除（NA / 非有限行 + warning）发生在 `compute_stat()` 里，不在
  `compute_aesthetics()`；所以 `.aesthetics` 仍是「行保留、只计数」的原表。
- 不碰 IR 版本；产物留到 M1-7 再进 IR。
