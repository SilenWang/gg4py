# stat 口径（M1-8）

`ggcore.stat` 实现 ggplot2 4.0.3 的六个 stat：`identity` / `bin` / `count` /
`boxplot` / `smooth` / `align`。流水线位置没变（仍是一个阶段）：

```
compute_aesthetics → compute_stat → map_statistic → compute_position → map_scales → finish
```

- 代码：`src/ggcore/stat.py`；loess 两套面在 `src/ggcore/loess.py`；
  派发在 `src/ggcore/build.py::compute_stat()`；
- 夹具：`tests/fixtures/stat_r_reference.json`（30 个 case，`pixi run -e refs refs:stat`）；
- 对拍：`tests/test_stat_r_parity.py`（列名 + 列序 + kind + 逐值 + NA，30 个 case）；
- 端到端：`docs/cases/stat-{histogram-bin,histogram-horizontal,boxplot-stat,smooth-loess,area-align}`。

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

## 9. 长尾 B（M2-6）：实现一览

M2-6 的 14 个 stat 在 `src/ggcore/stat_longtail.py`，派发仍从
`ggcore.stat.compute_stat()` 进来（`_LONGTAIL` 里的名字转过去）。参数校验一律
**构造 / 计算时点名报错**，不静默退化。各 stat 的默认 geom 照 4.0.3 的
`stat_*` 构造器（`registry.STAT_GEOMS`）；`step` / `violin` / `pointrange` /
`quantile` / `function` / `abline` 这几个默认 geom 属于 M2-7，落地之前用它们做
缺省值的 `stat_*()` 会在**构造时**报错并点名可用的 `geom=`。

### 9.1 `stat_qq` / `stat_qq_line`

- 输入是 `sample` 美学；`quantiles` 缺省 `ppoints(n)`（n ≤ 10 用 `3/8`，否则
  `1/2`），长度必须等于样本数；样本**升序**输出（`sample` 列）。
- `distribution` 收字符串别名（`norm` / `t` / `unif` / `exp` / `logis` /
  `cauchy`，也认带 `q` 的名字）或任意 `p → 分位数` 的可调用；分布参数走
  `dparams`（`norm` 的 `mean`/`sd`、`t` 的 `df`、`unif` 的 `min`/`max`、
  `exp` 的 `rate`、`logis`/`cauchy` 的 `location`/`scale`），不认识的键点名报错。
- 正态分位数是 Acklam 近似 + 一步 Halley（`erfc`）修正，逐值差 ≤ 1e-15；
  t 分位数复用 `ggcore.stat.t_quantile()`（下尾按 `qt(p) = -qt(1-p)` 补）。
- `stat_qq_line` 过 `line.p`（缺省 `c(0.25, 0.75)`）两点：
  `slope = diff(y)/diff(x)`、`intercept = y[1] - slope·x[1]`，`x` 取
  `range(theoretical)`；`fullrange = TRUE` 时取 x 标度的 `dimension()`。
  输出 `x, y, slope, intercept`，`sample` 进 `dropped_aes`（不告警）。

### 9.2 `stat_ecdf`

- 网格：`n = NULL` 时用 `unique0(x)`（出现顺序），否则
  `seq(min, max, length.out = n)`；`pad = TRUE`（缺省）两端补 `-Inf` / `Inf`。
- 权重：`weight` 美学按上游 `wecdf()` 聚合到唯一值 → 阶梯函数
  （`approxfun(method = "constant", f = 0, yleft = 0, yright = 1)`）；非有限权重
  按 0 处理并告警，权重和为 0 报错。
- 输出 `x, y, ecdf, flipped_aes`；横向（只映射 y）时 `flipped_aes = TRUE` 并把
  两列换回去。±Inf 是列里真实的值（IR / SVG 侧照常表达）。

### 9.3 `stat_ellipse`

- `type = "t"`（缺省）/ `"norm"` / `"euclid"`；`level = 0.95`、`segments = 51`
  （输出 `segments + 1` 个点）。
- `"norm"` = `stats::cov.wt()`（权重先归一到和为 1，无偏分母
  `1 - Σw²`）；`"euclid"` 把协方差换成 `min(diag) · I`、半径用
  `level / max(chol)`；`"t"` 是 `MASS::cov.trob()` 的逐行移植（`nu = 5`、
  `maxit = 25`、`tol = 0.01`，注意 R 的 `X` 用的是**上一轮**的 `loc`，移植保持
  同一顺序），对拍逐值差 7.6e-15。
- 半径 `sqrt(2 · qf(level, 2, n-1))`；`qf` 用 `qbeta` 的二分反解（`_betai`），
  不引 scipy。协方差不是正定 / 点数 < 4 时按上游的口径告警并给 NA 行。
- 加权：`weight` 先归一到和为 1，再乘 `n` 传给 `cov.trob`（与 R 一致）。

### 9.4 `stat_quantile`

- `method` 只实现 `"rq"`（线性分位数回归，`quantreg::rq` 的 `y ~ x` 口径）；
  `"rqss"` / 其他 formula 明确报错并点名（上游 `check_installed("quantreg")`）。
- 求解用 Barrowman 的 IRLS：权重按 **tau 非对称**
  （`r ≥ 0` 用 `tau/|r|`，`r < 0` 用 `(1-tau)/|r|`），到 `1e-15` 收敛；对拍
  `quantreg` 6.1 的最大差 7.7e-13。`method.args` 只收 `max_iter` / `tol`。
- 预测网格 `xseq` 缺省 `seq(min, max, length.out = 100)`；每个分位数输出
  `x, y, quantile, group`，`group` **是字符**（上游
  `paste(group, quantile, sep = "-")`）——`geom/line.py` 的 `setup_data()` 因此
  按字符排序列（`_order_key()` / `_group_key()`），不再硬转 float。

### 9.5 `stat_summary` / `stat_summary_bin`

- `fun.data` 优先，其次 `fun` / `fun.min` / `fun.max`，都没有时按上游缺省
  `mean_se()`（并告警）。字符串别名：`mean` / `median` / `sd` / `var` / `min` /
  `max` / `sum` / `length` / `first` / `last`；`fun.data` 另有 `mean_se` /
  `mean_cl_normal` / `mean_sdl` / `median_hilow`（Hmisc 那四个包装的闭式口径）。
- `fun.args` 是映射，作为额外关键字参数传给汇总函数；点号参数在 Python 里也
  可以写成下划线（`fun_data` / `fun_min` / `fun_max` / `fun_args`）。
- `stat_summary` 按 `(group, x)` 汇总，x 升序；输出
  `x, group, y, ymin, ymax` + 组内恒定列 + `flipped_aes`。
- `stat_summary_bin` 先按 `bins` / `binwidth` / `breaks`（与 `stat_bin` 同一套
  `_compute_bins()`）分箱，`bin` 列是 R 的 `cut()` 区间文本（`dig.lab = 3`
  起跳，格式与 `formatC()` 一致），`x` 取箱中心、`width` 取箱宽。

### 9.6 `stat_sum` / `stat_unique`

- `stat_sum`：按 `(x, y, group, 其余映射美学)` 计数，`weight` 加权；输出
  `PANEL, x, y, group, …, n, prop`（`prop = n / 该 group 的 Σ|n|`，与
  `vec_ave(n, group, prop.table)` 一致）。`default_aes` 把 `size` 映射到
  `after_stat(n)`，这就是 `geom_count()` 的口径。
- `stat_unique`：`unique0(data)`（保留首次出现的行序），列与输入一致。

### 9.7 `stat_density` / `stat_ydensity`

- 密度**不是**直接核求和：`stats::density()` 在 R 4.5 里是「BinDist 线性分摊到
  2n 网格 + FFT + 线性插值」，直接求和与它的相对差有 7e-5。这里照
  `massdist.c` 的 `BinDist` 与 `density.default()` 的同一套参数
  （`ext = 4`、`n = max(n, 512)`、`n > 512` 时取 2 的幂、`kords` 的镜像、
  `pmax(0, ·)/length(y)`、`approx`）重写，逐值差 ≤ 1e-15。
- 带宽：`bw` 收 `"nrd0"`（缺省，`bw.nrd0` 的 `!(lo <- min(...))` 退化口径也照抄）
  / `"nrd"` 或正数；`adjust` 乘上去。`kernel` 只实现 `"gaussian"`（其余核是同一条
  FFT 路径的纯算术，按需再加）。`ucv` / `bcv` / `sj` 明确报错。
- `from` / `to`：`trim = FALSE` 取 x 标度的 `dimension()`，`trim = TRUE` 取数据
  范围。`bounds` 的有限端按上游 `reflect_density()` 折回界外的尾巴。
- 输出 `x, density, scaled, ndensity, count, wdensity, n`（`n` 是整数列）；
  `scaled = density/max`、`count = density·n`、`wdensity = density·Σw`。
- `stat_ydensity`：`trim = TRUE`（缺省）时 from/to 取数据范围，`FALSE` 时两端各
  扩 3 个带宽；`scale` 收 `area` / `count` / `width` → `violinwidth`；分位线
  （`quantiles = c(0.25, 0.5, 0.75)`，`NULL` 关闭）按 `approx()` 在密度网格上
  插值后追加行，此时 `n` 被抬成 double（上游 `vec_c()` 的结果）。

### 9.8 `stat_function` / `stat_connect` / `stat_manual` / `stat_spoke`

- `stat_function`：空数据补一行 `group = 1`（上游
  `ensure_nonempty_data()`），`fun` 收可调用或 `sin` / `cos` / `tan` / `exp` /
  `log` / `sqrt` / `abs` / `identity` 的字符串别名；网格 `seq(xlim 或 x 标度
  dimension, length.out = n)`（缺省 `n = 101`）。连续 x 标度先反变换再求值，连续
  y 标度再正变换；离散 x 标度直接用网格值。
- `stat_connect`：`connection` 收 `hv` / `vh` / `mid` / `linear` 或 2 列数值矩阵；
  按 x 排序后在每一对相邻点之间插 `m` 个点（`connection` 的每一行是一个
  (xjust, yjust) 对），首尾按 `connection[1, ] == c(0, 0)` / 末行 `== c(1, 1)`
  补原始端点。
- `stat_manual`：`fun` 收到「列名 → numpy 数组」的映射（NA 是 `nan` / `None`），
  返回映射或 `ColumnTable`；`args` 是映射；缺省是恒等。
- `stat_spoke`：4.0.3 里已是 `lifecycle::deprecate_stop()`，注册项保留但调用即
  报错并指向 `geom_spoke()`（角度 / 半径是 geom 的参数，归 M2-7）。

## 10. M2-6 的已知差异 / 未实现

| 能力 | 现状 | 去向 |
| --- | --- | --- |
| `stat_qq` 的 `distribution` 为任意 R 函数 | 只支持 6 个字符串别名与 Python 可调用 | 需要 R 函数桥接时再加 |
| `stat_ellipse(type = "t")` | `MASS::cov.trob()` 的移植（`nu = 5` 固定） | `nu` / `maxit` 还不是参数 |
| `stat_quantile(method = "rqss")` | `BuildError` 点名 | 需要 `quantreg::rqss` 的平滑样条 |
| `stat_quantile` 的其他 formula | `BuildError` 点名 | 需要完整设计矩阵 |
| `stat_density(kernel = …)` 非 gaussian | `BuildError` 点名 | 同一条 FFT 路径的纯算术 |
| `stat_density(bw = "ucv" / "bcv" / "sj")` | `BuildError` 点名 | 需要 R 的交叉验证实现 |
| `stat_summary` 的 Hmisc 四个包装 | 用闭式口径实现（`mean_se` / `mean_cl_normal` / `mean_sdl` / `median_hilow`），不依赖 Hmisc | — |
| `stat_ydensity` 的加权分位线 | 告警并按未加权分位计算（上游同样告警） | 需要加权分位 |
| `stat_spoke` | 与上游一致：`deprecate_stop()` | 用 `geom_spoke()`（M2-7） |

## 11. 验收口径

```bash
pixi run -e refs refs:stat             # 5 张 M1-8 的 expected.svg + 夹具
pixi run -e refs refs:stat-longtail    # 14 张 M2-6 的 expected.svg + 夹具
pixi run pytest tests/test_stat_r_parity.py tests/test_stat_longtail_r_parity.py -q
pixi run cases:matrix                  # stat case 逐张 render + diff
pixi run check                         # 全量门禁
```

`refs:stat-longtail` 依赖 refs 环境的 `r-mass`（`type = "t"`）与 `r-quantreg`
（`rq`）——两者只活在 refs 特性里，dev / prod 不会带上。夹具把 ±Inf 的位置记在
`pos_inf` / `neg_inf`（1 起），因为 JSON 的 `null` 既表示 NA 也表示非有限值。

夹具记录 `ggplot_build(p)$data[[1]]` 的列名、列序、kind、逐值（NA / NaN 写
`null`）与 build / draw 两段 warning。比较口径：列名与列序完全一致；数值
`allclose(rtol=0, atol=1e-9)`；字符串精确相等；NA 逐行一致；`kind` 相等——
只有 `outliers` 按「解析出的数值列表」比（list vs str）。主题色列（`fill` /
`colour`）在 M1-10 解析主题前只比列名与列序。
