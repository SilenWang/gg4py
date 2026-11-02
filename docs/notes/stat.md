# stat 口径（M1-8）

`ggcore.stat` 实现 ggplot2 4.0.3 的六个 stat：`identity` / `bin` / `count` /
`boxplot` / `smooth` / `align`。流水线位置没变（仍是一个阶段）：

```
compute_aesthetics → compute_stat → map_statistic → compute_position → map_scales → finish
```

- 代码：`src/ggcore/stat.py`；派发在 `src/ggcore/build.py::compute_stat()`；
- 夹具：`tests/fixtures/stat_r_reference.json`（27 个 case，`pixi run -e refs refs:stat`）；
- 对拍：`tests/test_stat_r_parity.py`（列名 + 列序 + kind + 逐值 + NA，27 个 case）；
- 端到端：`docs/cases/stat-{histogram-bin,boxplot-stat,smooth-loess,area-align}`。

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
  组内的 min/max。
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
`n = 80`、`se = TRUE`、`level = 0.95`、`fullrange = FALSE`、`na.rm`。

- 纯 numpy 的局域多项式回归（Cleveland 的 loess，"direct" 口径）：
  - 邻域 `q = floor(span · n_group)`（至少 1）；
  - 带宽 `d = 第 q 近的观测距离`；tricube 权重 `w = (1 - |u|³)³`，`u = |x - x₀| / d`；
  - 局域权 `w_i × 观测权重`，对 `[1, x-x₀, (x-x₀)²]` 做加权最小二乘，取截距。
  这一组数（`q` 的取整、带宽不乘 0.999、设计矩阵不缩放）是用 R 的
  `loess(..., surface = "direct")` 逐个探出来的，实测逐值差 ≤ 1.4e-15。
- `se = TRUE` 时：
  `s = sqrt(Σ w·r² / δ₁)`、`se.fit = s · sqrt(Σ L²/w)`、`df = δ₁²/δ₂`，
  其中 `δ₁ = ‖I - L‖²_F`、`δ₂ = ‖(I-L)(I-L)′‖²_F`（`loessf.f` 的 `lowesc()`），
  `ymin/ymax = y ∓ qt(0.975, df) · se.fit`。`qt()` 用不完全 Beta 反解（自带实现，
  不引 scipy）。
- 输出列序：`x, y, [ymin, ymax, se], flipped_aes`；`se = FALSE` 时**不产**
  `ymin/ymax/se`。
- `method = "lm"`：加权最小二乘 + `predict.lm(interval = "confidence")` 的口径
  （`sigma² = Σ w·r²/df.residual`，`se = sqrt(diag(X₀ (X′WX)⁻¹ X₀′)·sigma²)`）。
- `gam` / `glm` / 其他 formula / `method.args` 明确报错并点名后续任务。

### 与 R 默认的差异（重要）

R 的 `loess()` 默认 `surface = "interpolate"`：先在 kd 树的顶点上算局域拟合，
再对预测点做插值（C 实现，`loessf.f` 的 `ifit`）。gg4py 实现的是
**direct** 口径，两者在 `n = 15, span = 0.75` 上逐值可差到 **2.1e-3**
（另一个 8 点样本上是 5.2e-3）；这不是浮点误差，是算法差异。

因此：

- `refs:stat` 里的 smooth case 显式传
  `method.args = list(control = loess.control(surface = "direct", statistics =
  "exact", trace.hat = "exact"))`，与 gg4py 的口径对齐后才逐值对拍到 1e-15；
- `docs/cases/stat-smooth-loess` 的 `expected.svg` 用同一口径生成；
- 用户如果拿 R 的默认输出逐像素比，smooth 的曲线会差 ≤ 0.5% 面板高度（本仓的
  `pixi run diff` 实测 0.03% 图级差异，因为差值落在 1–2 px 的抗锯齿带里）。

后续若要复刻 interpolate 面，需要移植 cloess 的 kd 树 + `ifit` 插值。

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
| loess 的 `surface = "interpolate"` | 未实现（direct 口径，差 ≤ 5.2e-3） | 需要移植 cloess 的 kd 树插值 |
| `stat_smooth(method = "gam" / "glm")` | `BuildError` 点名 | 后续 |
| `stat_smooth` 的其他 formula / `method.args` | `BuildError` 点名 | 后续 |
| `stat_bin(weight = …)` | 支持（缺失权重按 0） | — |
| `stat_boxplot` 的加权分位（`quantreg::rq`） | 不支持；有 `weight` 列时报错 | 后续（需要 quantreg 等价实现） |
| `stat_bin` 的 `breaks` 只认数值序列 | 函数 / lambda 未实现 | 后续 |
| `stat_count` 的连续 x 宽度 | 沿用 geom 的 `resolution(x) × 0.9`（R 用 `discrete = TRUE`，差异只在连续 x 且非唯一值时出现） | 后续 |
| `outliers` 的 list 列 | 用 `str` + `c(...)` 文本 | `ColumnTable` 加 list kind 时改 |

## 9. 验收口径

```bash
pixi run -e refs refs:stat        # 夹具 + 4 张 expected.svg（R 4.5.3 / ggplot2 4.0.3）
pixi run pytest tests/test_stat_r_parity.py -q
pixi run cases:matrix             # 4 张 stat case 逐张 render + diff
pixi run check                    # 全量门禁
```

夹具记录 `ggplot_build(p)$data[[1]]` 的列名、列序、kind、逐值（NA / NaN 写
`null`）与 build / draw 两段 warning。比较口径：列名与列序完全一致；数值
`allclose(rtol=0, atol=1e-9)`；字符串精确相等；NA 逐行一致；`kind` 相等——
只有 `outliers` 按「解析出的数值列表」比（list vs str）。主题色列（`fill` /
`colour`）在 M1-10 解析主题前只比列名与列序。
