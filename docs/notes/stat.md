# stat 口径（M1-8 / M2-6）

`ggcore.stat` 实现 ggplot2 4.0.3 的十四个 stat：M1-8 的六个（`identity` /
`bin` / `count` / `boxplot` / `smooth` / `align`）与 M2-6 的八个 2D 族
（`bin_2d` / `bin_hex` / `summary_2d` / `summary_hex` / `contour` /
`contour_filled` / `density_2d` / `density_2d_filled`）。流水线位置没变（仍是
一个阶段）：

```
compute_aesthetics → compute_stat → map_statistic → compute_position → map_scales → finish
```

- 代码：`src/ggcore/stat.py`（M1-8 六个 + 派发）、`src/ggcore/stat2d.py`（M2-6
  八个）、`src/ggcore/kde2d.py` / `hexbin.py` / `contour.py`（数值内核）；
  loess 两套面在 `src/ggcore/loess.py`；
  派发在 `src/ggcore/build.py::compute_stat()`；
- 夹具：`tests/fixtures/stat_r_reference.json`（52 个 case，`pixi run -e refs refs:stat`）；
- 对拍：`tests/test_stat_r_parity.py`（M1-8 的 30 个 case）与
  `tests/test_stat_2d_r_parity.py`（M2-6 的 22 个 case）；
- 端到端：`docs/cases/stat-{histogram-bin,histogram-horizontal,boxplot-stat,smooth-loess,area-align}`
  （M1-8 的 5 张 SVG）；M2-6 的 2D 族目前是 build 级端到端（见 §10）。

`compute_stat(layer, aesthetics, scales=…, raw=…)` 多出两个可选入参：

| 入参 | 用途 |
| --- | --- |
| `scales` | 这一面板的 `ScaleSet`。`stat_bin` 的断点来自 `scale$dimension()`（训练后的范围），`stat_smooth(fullrange = TRUE)` 也用它 |
| `raw` | 位置标度映射**之前**的美学表。横向判定要复现 R 的 `is_mapped_discrete()`（映射后 x 已经是 1..n 的 float） |

分面时 `_compute_panel_stages()` 逐面板取 `PanelScales.for_panel(panel)` 传进去，
所以 free scales 的 `stat_bin` 断点是逐面板的（与 R 的 `layout$get_scales()` 一致）。

## 1. 公共口径

### 1.1 `Stat$compute_panel()`：分组与恒定列

每个 stat 都按 `group` 拆组，组内跑一次 `compute_group()`，再拼回一张表
（`_compute_panel()`）：

- 组内**恒定**的旧列各取一行，按原列序追加在 stat 输出列后面（`PANEL` /
  `group` / `fill` 这些就是这么留下来的）；
- 组内**变化**的列丢弃；在 `Stat*$dropped_aes` 里的（`bin`/`count`/`smooth`
  的 `weight`、`boxplot` 的 `x`/`y`/`weight`）静默丢，其余发一条
  :class:`BuildWarning`；
- 组函数返回空 → 这一组没有输出（上游 `data_frame0()`），整层空时 `.data` 是
  0 行。

### 1.2 缺失值

`Stat$compute_layer()` 在算之前先 `remove_missing(required_aes + non_missing_aes,
finite = TRUE)`：NA 与 `±Inf` 都删，`na.rm = FALSE` 时发 R 同文案的警告：

```
Removed 2 rows containing non-finite outside the scale range (`stat_boxplot()`).
```

这条与 `build` 的「`$data` 保留 NA 行」不冲突：保留的是 geom 阶段拿到的数据，
stat 本来就要吃掉自己的输入行。`docs/notes/build.md` §3 的「行保留、只计数」
说的是 stat **之后**的表。

### 1.3 横向（`flipped_aes`）

`_has_flipped_aes()` 是上游同名函数的 1 维版本：

1. 表里已有 `flipped_aes` 列 → 取第一个非 NA 的值；
2. `params$orientation` → `"y"` 为横向；
3. 否则按「x / y 哪个是离散」判（`raw` 表里的 `str` / `categorical` / `bool`
   列 = `is_mapped_discrete()`）；`boxplot` 还会用 `group_has_equal`
   （每组 x 都只有一个不同值时算竖向）；
4. `smooth` / `align` 传 `ambiguous = TRUE`：没有显式 orientation 时永远竖向。

判定为横向后，stat 在 `_flip_table()` 过的表上算（`switch_orientation()` 的
x↔y 表：`x↔y`、`xmin↔ymin`、`xmax↔ymax`、`xlower↔lower`、`xmiddle↔middle`、
`xupper↔upper`、`xmin_final↔ymin_final`、`xmax_final↔ymax_final`），输出再翻回来。

### 1.4 参数从哪来

R 的图层只有一个 `params` 字典，stat 与 geom 各取自己认识的名字。所以
`geom_histogram(bins = 5)` 与 `stat_bin(bins = 5)` 等价：`_stat_params()` 合并
`layer.params`（geom 侧）与 `layer.stat.params`（`stat_*()` 侧），后者优先。

## 2. `stat_bin`

参数（对齐 R `StatBin`）：`bins = 30`、`binwidth`、`center`、`boundary`、
`closed = "right"|"left"`、`pad = FALSE`、`drop = "none"|"all"|"extremes"|TRUE|FALSE`、
`breaks`、`na.rm`。

- `center` / `boundary` 互斥，都给报错（R 同款报错）。
- 断点走 `bin_breaks_width()` / `bin_breaks_bins()`，与 R 逐行对应：
  `bins` 个箱时 `width = range / (bins - 1)`，`boundary` 缺省由
  `x_range[1] - width/2` 推；`center` 先平移半个 bin；`x %% width` 的比较用 R 的
  `%%` 口径（`x - floor(x/y)*y`，不是 numpy 的 `fmod`）。
- 浮点端点用 R 的 `fuzz`：`1e-8 * median(diff(breaks))`，右闭时
  `fuzzy = c(-fuzz, fuzz, …)`、左闭时 `c(…, -fuzz, fuzz)`；落箱用
  `cut(x, fuzzy, right = closed == "right", include.lowest = TRUE)` 的等价实现
  （`searchsorted`），**不是** `arange` + 比较。
- 断点范围是 `scale$dimension()`（这一面板训练后的范围，含显式 limits），不是
  组内的 min/max。横轴取哪一条由 `flipped_aes` 决定：上游
  `StatBin$compute_group()` 用 `flipped_names(flipped_aes)$x`，横向
  （`aes(y = <连续>)`）取的是 **y 标度**的范围；竖向才是 x 标度。
- 输出列序照 `bin_out()`：`count, x, xmin, xmax, width, density, ncount,
  ndensity`，然后是 `flipped_aes` 与组内恒定的旧列。`pad = TRUE` 两端各补一个
  0 计数箱；`drop = "all"` 去掉 0 计数箱、`"extremes"` 只去两端的连续 0 箱。
- `weight` 美学走真权重（缺失权重按 0），不是静默当 count。
- `x`（横向时 `y`）必须是连续位置；离散时报错并提示 `stat = "count"`。

`geom_histogram()` 的默认 stat 就是 `bin`：数据只需 `x`，`y =
after_stat(count)` 由 `_STAT_DEFAULT_AES` 补。

## 3. `stat_count`

沿用 M1-3 的实现，补了两件事：

- 横向（`flipped_aes = TRUE`）在翻转后的 `x`（原 `y`）上计数，输出列名跟着翻
  成 `count, prop, y, flipped_aes, …`；
- `after_stat(count)` / `after_stat(prop)` 可用（见 §6）。`prop =
  count / sum(abs(count))`，是**组内**占比——`aes(group = 1)` 时才是全局占比。

列序：`count, prop, x, flipped_aes, <组内恒定的旧列>`（与 R 一致；`width` 是
`setup_params()` 的产物，geom 会在 `setup_data()` 里吃掉，最终 `$data` 里没有）。

## 4. `stat_boxplot`

参数：`coef = 1.5`、`quantile.type = 7`、`width`、`varwidth`、`na.rm`。

- 四分位用 R 的 type 7（线性插值）= `np.quantile(..., method="linear")`；
  `fivenum` 同口径（`qs = c(0, .25, .5, .75, 1)`）。
- 离群点：`y < lower - coef*IQR` 或 `y > upper + coef*IQR`；有离群点时须线端点
  改成 `range(c(lower, middle, upper, 非离群观测))`。
- `notchupper/notchlower = middle ± 1.58 * IQR / sqrt(n)`（`n` = 非缺失观测数）。
- `width`：映射的 `width` 列 > 组内 x 变化的 `0.9 × 极差` > `resolution(x) * 0.75`
  （离散位置时 `resolution = 1`，所以缺省是 0.75，与 R 的 `setup_params()` 一致）。
- `relvarwidth = sqrt(n)`；`varwidth = TRUE` 时由 geom 的 `setup_data()` 归一化
  到 `relvarwidth / max(relvarwidth)`。
- 输出列序（`compute_group()` 的 `data_frame0()` 顺序）：
  `ymin, lower, middle, upper, ymax, outliers, notchupper, notchlower, x, width,
  relvarwidth, flipped_aes`，之后是 `PANEL` / `group` 等恒定列。
- **`outliers` 的表达**：R 是 list 列，`ColumnTable` 没有 list kind，这里用
  `str` 列 + R 风格文本（`c(20)` / `c()`）。绘制层的 `_outliers()` 直接解析这个
  文本，对拍测试按「解析出来的数值列表」比较（见
  `tests/test_stat_r_parity.py::_assert_column_equal`）。
- `±Inf` 观测在 stat 里按非有限值删掉（R 的 `remove_missing(finite = TRUE)`），
  并发出 §1.2 的警告。

## 5. `stat_smooth`（loess / lm）

参数：`method = "loess"`、`formula = y ~ x`、`span = 0.75`、`degree = 2`、
`n = 80`、`se = TRUE`、`level = 0.95`、`fullrange = FALSE`、`na.rm`、
`method_args`。

loess 的两套实现在 `src/ggcore/loess.py`（`stat_smooth` 只是选面 + 组列）：

- **`surface = "interpolate"`（缺省，R 的默认口径）**
  - 一维 k-d 树：包围盒外扩 0.5%，叶单元不超过
    `floor(n · span · cell)` 个观测（`cell = 0.2`，R 传给 C 的是 `span · cell`），
    每个内部结点在切分值处加一个顶点（`ehg126` / `ehg124` / `ehg106` / `ehg125`）；
  - 每个顶点做一次局域二次拟合，留下**值**与**一阶导**（`ehg139` / `ehg127`）；
  - 预测点落在哪个叶单元，就用两端顶点的 (值, 导) 做三次 Hermite 插值
    （`ehg128`），这就是 `lowese()`；
  - 标准误：每个顶点的「局域拟合行」同法插值（`ehg191`），
    `se = s · sqrt(Σ L²/w)`；`trL = tr(L)`，`s`、`df` 用 R 的近似公式
    （`ehg141` / `lowesa`，`statistics = "approximate"`）；
  - 数据范围外的预测点是 **NA**（`predLoess()` 的 `inside` 判定）——
    `fullrange = TRUE` 时也会出现整段 NA；
  - 实测与 R 4.0.3 逐值差 ≤ 1.0e-14（默认口径的 `y/ymin/ymax/se` 全部达标）。
- **`surface = "direct"`（显式选项）**
  - 纯 numpy 的局域多项式回归：
    邻域 `q = floor(span · n_group)`（至少 1）；带宽 = 第 q 近的观测距离；
    tricube 权重 `w = (1 - |u|³)³`，`u = |x - x₀| / d`；局域权 `w_i × 观测权重`，
    对 `[1, x-x₀, (x-x₀)²]` 做加权最小二乘，取截距。可外推；
  - `se = TRUE` 时 `s = sqrt(Σ w·r² / δ₁)`、`se.fit = s · sqrt(Σ L²/w)`、
    `df = δ₁²/δ₂`，其中 `δ₁ = ‖I - L‖²_F`、`δ₂ = ‖(I-L)(I-L)′‖²_F`
    （`loessf.f` 的 `lowesc()`，即 R 的 `statistics = "exact"`）；
  - 与 R 的 `loess(..., surface = "direct", statistics = "exact",
    trace.hat = "exact")` 逐值差 ≤ 1.4e-15。
- `method_args` 写法（对应 R 的 `list(...)`）：
  `method_args = {"control": {"surface": "direct", "statistics": "exact",
  "trace.hat": "exact"}}`。缺省 = R 缺省（`interpolate` / `approximate` /
  `exact` / `cell = 0.2`）。只实现两种组合：`interpolate + approximate`（R 默认）
  与 `direct + exact`；其余组合与 `iterations > 1`（稳健迭代）明确报错。
  `degree` 只从 `method_args` 取（R 的 `geom_smooth()` 没有 `degree` 形参），
  `span` 恒取 stat 的 `span`（上游 `StatSmooth$setup_params()` 会用
  `params$span` 覆盖 `method.args$span`）。
- `ymin/ymax = y ∓ qt(0.975, df) · se.fit`。`qt()` 用不完全 Beta 反解
  （自带实现，不引 scipy）。
- 输出列序：`x, y, [ymin, ymax, se], flipped_aes`；`se = FALSE` 时**不产**
  `ymin/ymax/se`。
- `method = "lm"`：加权最小二乘 + `predict.lm(interval = "confidence")` 的口径
  （`sigma² = Σ w·r²/df.residual`，`se = sqrt(diag(X₀ (X′WX)⁻¹ X₀′)·sigma²)`）。
- `gam` / `glm` / 其他 formula 明确报错并点名后续任务。

横向（`orientation = "y"`）时 `fullrange = TRUE` 的 `xseq` 取的仍是
**x 标度**（`StatSmooth$compute_group()` 里写死 `scales$x$dimension()`），不是
翻转后的 y 轴；夹具 `smooth_horizontal_fullrange` 守着这条（数据范围外给 NA）。

`stat_bin` 横向断点取 y 标度那一条同理，见 §2。

### 与 R 默认的差异

无（默认路径已对齐）。`docs/cases/stat-smooth-loess` 的 `expected.svg` 仍用
`smooth_control`（direct / exact）生成，因为它是既有验收资产；夹具里另有
`smooth_default` / `smooth_horizontal_fullrange` 两个走 R 默认 interpolate 的
case，把默认口径也钉住。

## 6. `stat_align`

`geom_area()` 的默认 stat。照 `StatAlign` 的 `compute_panel()` + `compute_group()`：

- 只有一组（`is_unique(group)`）时**原样返回**数据（不产 `align_padding`）；
- 面板级 x 并集：所有组的 `x` 加上「组内 y 变号处」的零点
  （`-y[p]·(x[p+1]-x[p])/(y[p+1]-y[p]) + x[p]`，p 是每组内符号连续段的末行）；
- `adjust = 0.001 × range(unique_loc)`，再夹到 `min(diff)/3`；并集向两侧各扩
  `±adjust`（避免插值端点落在半开区间外）；
- 每个组：`approxfun(x, y)` 在并集上线性插值（区间外 NA → 丢弃），两端各补一个
  0，`align_padding = TRUE`；同一组里 x 有重复时只留首尾两行，并给首行的 x 减
  `adjust`（上游 `dapply(data, "x", …)`）；
- 输出列序：`x, y, <该组其余列（PANEL / group / fill …）>, align_padding,
  flipped_aes`。

端到端还要 position stack 配合：`collide()` 会补 `xmin/xmax`（面积没有宽度信息
时按 0 算，`xmin = xmax = x`），负段的 `ymax < ymin` 朝向也会保留
（`pos_stack()` 的 `max_is_lower`）。

## 7. `after_stat()`

`map_statistic()` 把 M1-2 解析出来的 `after_stat(expr)` 用
`eval_after_stat(spec, stat_values)` 求值（AST 白名单，不碰 `eval` / `exec`）：

```python
ggplot(tbl, aes(x="cls", group=1, y=after_stat("prop"))) + geom_bar()
```

可用的变量就是 stat 输出列：`bin` 的 `count/density/ncount/ndensity/width`、
`count` 的 `count/prop`、`boxplot` 的 `lower/upper/middle/…`、`smooth` 的
`y/ymin/ymax/se`。基础列（`x`、`group`、`PANEL`、`fill` …）在 stat 之后仍然可以
直接引用（它们本来就在表里）。

`Stat$default_aes` 也走同一条路：`count` / `bin` 的 `x`、`y` 都映射到
`after_stat(count)`，缺哪个补哪个（用户显式写的 `after_stat(...)` 优先）。

## 8. 与 R 的已知差异 / 未实现

| 能力 | 现状 | 去向 |
| --- | --- | --- |
| loess `surface="direct"` + `statistics="approximate"` / `trace.hat="trL-1"` | `BuildError` 点名（direct 只实现 exact 口径） | 需要 `ehg196` 的 trL 近似 |
| loess `surface="interpolate"` + `statistics="exact"` | `BuildError` 点名（默认只实现 approximate） | 需要 n×n 帽子矩阵（`lowesc`） |
| loess 的稳健迭代（`iterations > 1` / `family="symmetric"`） | `BuildError` 点名 | 需要 `lowesw` / `lowesp` |
| `stat_smooth(method = "gam" / "glm")` | `BuildError` 点名 | 后续 |
| `stat_smooth` 的其他 formula | `BuildError` 点名 | 后续 |
| `stat_bin(weight = …)` | 支持（缺失权重按 0） | — |
| `stat_boxplot` 的加权分位（`quantreg::rq`） | 不支持；有 `weight` 列时报错 | 后续（需要 quantreg 等价实现） |
| `stat_bin` 的 `breaks` 只认数值序列 | 函数 / lambda 未实现 | 后续 |
| `stat_count` 的连续 x 宽度 | 沿用 geom 的 `resolution(x) × 0.9`（R 用 `discrete = TRUE`，差异只在连续 x 且非唯一值时出现） | 后续 |
| `outliers` 的 list 列 | 用 `str` + `c(...)` 文本 | `ColumnTable` 加 list kind 时改 |

## 9. 验收口径

```bash
pixi run -e refs refs:stat        # 夹具 + 5 张 expected.svg（R 4.5.3 / ggplot2 4.0.3）
pixi run pytest tests/test_stat_r_parity.py -q
pixi run cases:matrix             # 5 张 stat case 逐张 render + diff
pixi run check                    # 全量门禁
```

夹具记录 `ggplot_build(p)$data[[1]]` 的列名、列序、kind、逐值（NA / NaN 写
`null`）与 build / draw 两段 warning。比较口径：列名与列序完全一致；数值
`allclose(rtol=0, atol=1e-9)`；字符串精确相等；NA 逐行一致；`kind` 相等——
只有 `outliers` 按「解析出的数值列表」比（list vs str）。主题色列（`fill` /
`colour`）在 M1-10 解析主题前只比列名与列序。

## 10. 2D 统计（M2-6）

八个 stat 在 `src/ggcore/stat2d.py`，公共流程（`remove_missing()` /
`Stat$compute_panel()` 的分组与恒定列）仍复用 `ggcore.stat`。数值内核三份：

| 模块 | 复刻对象 | 覆盖 |
| --- | --- | --- |
| `ggcore/kde2d.py` | `MASS::kde2d()` / `bandwidth.nrd()` / `bw.nrd0()` | `stat_density_2d` 的网格与带宽 |
| `ggcore/hexbin.py` | `hexbin::hexbin()` 的 `hbin.f` / `hcell2xy()` + ggplot2 的 `hexBinSummarise()` | `stat_bin_hex` / `stat_summary_hex` |
| `ggcore/contour.py` | `contour_breaks()`（含 R `pretty.c` 的移植）/ `isoband` 的输入网格 / `pretty_isoband_levels()` | `stat_contour[ _filled]` 与密度族的第二段 |

### 10.1 分箱参数（`bins` / `binwidth` / `breaks` / `center` / `boundary` / `closed`）

`bin_2d` / `summary_2d` 的这六个参数都走上游的 `dual_param()`：标量 → 两轴同值；
长度 2 的序列（或命名 list）→ `x` / `y` 各一个；更长的序列（`breaks`）→ 两轴同一
份。`bins` 的缺省是 30（`fix_bin_params()`），`boundary` 的缺省是 **0**：

- `summary_2d` 的 `compute_group()` 形参就是 `boundary = 0`，`make_constructor()`
  把它带进 params；
- `bin_2d` 用 `boundary %||% if (is.null(center)) list(x = 0, y = 0)` 补同一份缺省。

所以 `stat_bin_2d(binwidth = 1)` 的箱边界是 `1, 2, 3, …`（不是 `0.5, 1.5, …`），
这条容易与 `stat_bin()` 的 `width / 2` 混淆，`tests/test_stat_2d_r_parity.py::
test_bin_2d_boundary_defaults_to_zero` 钉住。

`breaks` 只认显式数值序列（函数 / lambda 归后续任务，`BuildError` 点名）。

### 10.2 `stat_bin_2d` / `stat_summary_2d`

列序：`xbin, ybin, value, x, width, y, height`（`tapply_df()` + `bin_loc()`），
`bin_2d` 再追加 `count, ncount, density, ndensity`。`xbin` / `ybin` 是 `cut()` 的
1 起编码；`x` / `y` 是箱中点，`width` / `height` 是箱宽高。

- `drop = TRUE` 去掉空单元格（缺省）；`drop = "none"` 保留。
- `stat_bin_2d` 的 `z` 来自 `weight`（没有映射时是 1），`count = sum(z)`；
  `ncount = count / max(count)`、`density = count / sum(count)`、
  `ndensity = density / max(density)`。
- `stat_summary_2d` 的 `fun` 缺省 `"mean"`，支持 `mean / sum / median / min /
  max / var / sd` 与 Python 可调用对象（上游 `as_function()` 的可用子集）。
- 两个 stat 的 `dropped_aes`：`z`；`bin_2d` 的 `weight` 在计算前就被吃掉了。

### 10.3 `stat_bin_hex` / `stat_summary_hex`

`hexbin.py` 逐行复刻 hexbin 包的 Fortran `hbin.f`：坐标缩放到单元格单位后按
「到最近两个候选中心的平方距离（y 向 ×3）」判定编号，压缩后按编号升序输出；
中心由 `hcell2xy()` 反算（不是逐点均值）。`hex_binwidth()` 取
`diff(scale$dimension()) / bins`，`hex_bounds()` 先按 binwidth 取整再留 1e-6。

- 输出列：`x, y, width, height, density, ndensity, count, ncount`
  （`bin_hex`）/ `x, y, value, width, height`（`summary_hex`）。
- `stat_bin_hex` 的 `count` 是整数（权重缺省是 `rep(1L, n)`，`sum` 仍是 integer），
  与 `stat_bin_2d` 的 `count`（float，权重缺省是数值 1）不同——夹具里 `kind`
  分别钉住。
- `stat_summary_hex(fun = "mean")` 等与 2D 版同口径。

### 10.4 `stat_contour` / `stat_contour_filled`

层级：

- `breaks` 显式数值序列原样用；
- 只给 `bins` / `binwidth` 时走 `scales::fullseq()`（`contour_breaks()`），
  `bins` 先用 `signif(diff(z_range), 1) / 10` 把范围夹到整数倍；
- 都不给时走 R 的 `pretty(z_range, 10)`（`contour.py::pretty()` 是
  `src/appl/pretty.c` 的移植，缺省 `min.n = n %/% 3`、`shrink.sml = .75`、
  `high.u.bias = 1.5`、`u5.bias = 2.75`）。

几何用 contourpy（`corner_mask = False`，与 isoband「四角有 NA 的单元整块不算」
一致）。**它与 isoband 的顶点拓扑不保证相同**：

- 鞍点单元的解析、闭合环的拆分与方向都可能不同，所以顶点数 / 行数不逐行相等；
- `level == max(z)` 时 isoband 会吐一段两点重合的退化线，contourpy 不给线——
  这是几何差异，不是层级边界差异；对拍测试会把这种退化层级从 R 侧剔除，层级本身
  由 `contour_breaks()` 的独立断言钉住。

输出列：

- 线：`level, x, y, piece, group, nlevel`；`level` 是数值，`group` 是
  `"<原 group>-<break 序号:03d>-<线段序号:03d>"` 的因子（`piece` 是其 1 起编码），
  `nlevel = level / max(level)`。
- 带：`level, x, y, piece, group, subgroup, level_low, level_high, level_mid,
  nlevel`；`level` 是有序因子（`"(low, high]"`，`dig.lab` 从 3 起按重复自动加宽），
  `nlevel = level_high / max(level_high)`。

`setup_data()` 会按 `(x, y, group, PANEL)` 去重（保留最后一行）并发 R 同文案的
警告；`z` NA 行在 stat 之前由 `remove_missing()` 删掉。

### 10.5 `stat_density_2d[ _filled]`

两段式（上游 `StatDensity2d$compute_layer()`）：

1. `compute_group()` 算密度网格：`h` 缺省是
   `c(bandwidth.nrd(x), bandwidth.nrd(y))`（某维为 0 且 n > 1 时换
   `bw.nrd0(x) * 4`），乘 `adjust`；`kde2d()` 内部再把 `h` 除以 4；
   `n` 缺省 100；`lims` 取这一面板的 `scales$x$dimension()` /
   `scales$y$dimension()`。输出 `x, y, density, group, ndensity, count, n,
   level, piece`（x 变化最快）。
2. `contour = TRUE`（缺省）时把整张网格交给 `StatContour` / `StatContourFilled`
   的 `compute_panel()`，`contour_var` 选 `density` / `ndensity` / `count` 之一
   作为 `z`。链式调用**不经过** `map_statistic()`，所以密度族即使做了等值线
   也没有 `order` 列；`density` / `ndensity` / `count` 按 `dropped_aes` 静默丢弃，
   `n` / `PANEL` / 主题色等恒定列保留。

`contour = FALSE` 时直接返回密度网格（列序见上，末尾是 `PANEL` 与 geom 默认美学）。

### 10.6 geom 侧（build 级）

2D 族的六个 geom（`tile` / `hex` / `contour` / `contour_filled` /
`density_2d` / `density_2d_filled`）在 `src/ggcore/geom/stat2d.py` 里只有
**build 级**实现：

- `geom_tile` 的 `setup_data()` 派生 `xmin/xmax/ymin/ymax` 并去掉 `width/height`
  （`bin_2d` / `summary_2d` 的列序靠它）；
- `contour` / `density_2d` 沿用 stat 给的行序（`GeomPath` 不排序，只有
  `geom_line` 会按 `(PANEL, group, x)` 重排）；
- `draw()` 明确报 `GeomError` 并点名 SIL-735（M2-7 geom 长尾 B · 2D 族）。

所以本任务的「端到端 case」是 **build 级**：`ggplot() + stat_*()` 走完整条
`ggplot_build()` 流水线，`$data` 的统计列完整（`tests/test_stat_2d_r_parity.py`
§4 的 `test_every_2d_stat_has_an_end_to_end_case`）。SVG 快照 case 要等
`geom_{tile,hex,contour,...}()` 的绘制落地，随 SIL-735 补进 `docs/cases/`。

### 10.7 验收

```bash
pixi run -e refs refs:stat                     # 52 case 夹具（旧 30 个零 diff）
pixi run pytest tests/test_stat_2d_r_parity.py -q
pixi run check                                 # 全量门禁（含 gate:imports 的 contourpy 放行）
```

对拍分两层：

- **逐列**（`bin_2d` / `bin_hex` / `summary_2d` / `summary_hex` /
  `density_2d(contour = FALSE)`）：列名 + 列序 + kind + 逐值 + NA，
  `atol = 1e-9`；
- **层级边界**（contour 族）：`level` / `level_low` / `level_high` /
  `level_mid` 的取值集合与等值带标签逐一相等；再加一条几何自洽断言——每个顶点
  处的双线性插值必须等于自己的层级（带的外边界允许落在数据域四条边上）。

### 10.8 已知差异

| 能力 | 现状 | 去向 |
| --- | --- | --- |
| 2D geom 的绘制 | `draw()` 报 `GeomError` 并点名 SIL-735；build 级完整 | SIL-735 |
| contour 顶点拓扑 | contourpy 与 isoband 不同（鞍点 / 环拆分） | 按层级对拍，不逐顶点比 |
| `level == max(z)` 的退化线 | isoband 给重合点，contourpy 不给 | 记录为几何差异 |
| `stat_contour(breaks = <函数>)` | `BuildError` 点名 | 后续 |
| `stat_summary_*` 的任意 R 函数 | 支持 Python 可调用对象与常用名字 | 后续（不做 R 表达式求值） |
| `stat_bin_hex` / `summary_hex` 的 `hexbin` 细节（erode / cAtt） | 不需要（ggplot2 只用编号 + 中心） | — |
