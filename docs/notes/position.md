# 位置调整口径（M1-9）

`ggcore.position` 把 stage 4（`compute_position`）的数据从「每个 group 各自一个
x」变成「同 x 的多行互不重叠」：stack / fill / dodge / dodge2 / jitter / nudge。
对标 ggplot2 4.0.3 的 `R/position-*.R`；代码 `src/ggcore/position.py`。

```
Layer.position (名字 + 参数)
  → registry.construct("position", name, **params)   # 注册表分派
  → Position*.compute_layer(table, params=None)      # 统一执行接口
```

测试：`tests/test_position.py`（语义 / 接线 / 负向）、
`tests/test_position_r_parity.py`（R 逐值对拍）。

## 1. 接口与注册表

- `KINDS` 里新增 `position`（紧跟 `stat`），`PREFIXES["position"] = "position_"`。
  因此 `position_dodge()`（模块级）与 `p.position_dodge()`（`ggplot` 方法）都是
  同一个注册表项的入口。
- 注册项是构造器：`position_identity()` / `position_stack(vjust, reverse)` /
  `position_fill(vjust, reverse)` / `position_dodge(width, preserve,
  orientation, reverse)` / `position_dodge2(width, preserve, padding, reverse)` /
  `position_jitter(width, height, seed)` / `position_nudge(x, y)`。返回
  `ggcore.layer.Position` 的子类实例（`PositionStack` / `PositionDodge` /
  …），子类只多一个 `compute_layer()`，**没有第二套实现**。
- `compute_position()` 不再硬编码分支：它把 `Layer.position` 的名字 + 参数再
  过一次注册表（`registry.construct("position", name, **params)`），所以
  `geom_col(position="dodge")` 与 `p + position_dodge()` 走同一条路；测试
  `test_compute_position_dispatches_through_the_registry` 换掉注册项后，两边的
  输出同时变。
- `Position` 的 `.params` 是用户参数的完整记录（构造器把缺省值也写进去），
  例：`position_dodge().params == {"width": None, "preserve": "total",
  "orientation": "x", "reverse": False}`。直接写
  `Position("dodge", {"preserve": "single"})` 也可以，流水线按注册表补齐缺省。
- 未知名字 / 参数不对 → `BuildError`（消息里列出可用名字）；构造器本身对
  `preserve` / `orientation` 用 `arg_match0` 的口径（`ValueError`），`reverse`
  必须是布尔（`TypeError`）。

`p + position_dodge()` 在 gg4py 里是合法的：`ggplot._add_component` 把它记进
`plot.position`（M1-1 预留的 plot 级默认位置调整字段）。上游 4.0.3 会直接报
「Can't add `position_dodge()` to a <ggplot> object」；流水线读取的仍是
`Layer.position`。

## 2. 共同约定

输入是 stage 4 的 `ColumnTable`：`x / y / xmin / xmax / ymin / ymax / PANEL /
group`，`bar` / `col` / `histogram` / `boxplot` 还带 `flipped_aes`（geom
`setup_data()` 的产物）。位移量在**位置空间**（离散 x 已经编码成 1..n），所以
所有实现都是纯数值运算。

- **不删行、不改 `nrows`**：行序保持输入顺序。上游 `collide()` 会先排序再在
  末尾用 `match(seq_along(ord), ord)` 还原，这里直接写回原行号。
- **不删列**：只改 `x / y / xmin / xmax / ymin / ymax`，需要时追加
  `order` / `xmin` / `xmax` / `ymax`（追加位置照 R 的 `data$col <- …`）。
- **`flipped_aes`**：`flipped_aes()` 取该列第一个非缺失值（上游
  `has_flipped_aes()`）。为 TRUE 时先按 `switch_orientation()` 把 x 族与 y 族
  列名对调（`ggplot_global$x_aes` / `y_aes` 的同一份名单），算完再对调回来；
  stack / fill / dodge / dodge2 都走这条路。**写入发生在翻转坐标里**：横向的
  stack / fill 把累计值写进 `ymin/ymax/y`（翻回来就是 `xmin/xmax/x`，长度轴），
  类别轴（原来的 `y` 族）原样保留——与上游 `flip_data()` 包住整段计算的顺序
  一致。`jitter` / `nudge` 照上游直接作用在 x / y 上。
- **PANEL**：分组键是 `(位置值, PANEL)`；没有 `PANEL` 列时当作单面板。
- 位置值用 `repr(float)` 作分组键，所以 `NA`（NaN）自成一个水平，与 vctrs 把
  NA 当同一个值的口径一致。

## 3. 各调整

### identity

不做任何事，原表返回。

### stack

上游 `PositionStack$compute_panel()` + `collide(pos_stack)`：

- 每个 x 取组内行，按 **`-group`** 稳定排序（`position_stack(reverse = TRUE)`
  时按 `group` 正序）：`vjust = 1` 时第一个 group 在最上面。
- 正值与负值分开各堆一次：`heights = c(0, cumsum(y))`，
  `ymin/ymax = pmin/pmax(heights[-n], heights[-1])`，再
  `y = (1 - vjust) * ymin + vjust * ymax`。
- `NA` 的 y 当 0 高度：该行 `ymin == ymax`，x 坐标保留（不复刻上游 `collide`
  按 `xmin` 分组时把整行坐标抹成 NA 的副作用）。
- x 没有重复值且 `fill = FALSE`、`vjust == 1` 时退化成 identity（上游
  `setup_params()` 里 `var = NULL` 的分支）；`vjust != 1` 时仍会重写
  y/ymin/ymax。

R 对照（`two_groups`：x = 1,1,2,2；y = 1,2,3,4；group 1,2,1,2）：

| | y | ymin | ymax |
| --- | --- | --- | --- |
| `position_stack()` | 3, 2, 7, 4 | 2, 0, 4, 0 | 3, 2, 7, 4 |
| `position_stack(reverse = TRUE)` | 1, 3, 3, 7 | 0, 1, 0, 3 | 1, 3, 3, 7 |

### fill

`PositionFill$compute_panel()`：与 stack 同一套 collide，只把
`pos_stack(fill = TRUE)` 打开——每段 heights 除以 `abs(heights[最后])`（该 x 上
同符号累计总量），得到 0..1；`vjust` 仍生效。x 只有一组时该组顶到 1。

R 对照（同上数据）：y = `1, 2/3, 1, 4/7`，ymin = `2/3, 0, 4/7, 0`。
横向（`flipped_aes = TRUE`，同一份数据画 `geom_col(orientation = "y")`）时，
这些值落在 x 族：x = `1, 2/3, 1, 4/7`、xmin = `2/3, 0, 4/7, 0`，y = `1, 1, 2, 2`
（类别轴）不动。

### dodge

`PositionDodge$setup_data()` / `setup_params()` + `collide(pos_dodge)`：

- **`width`**：默认 `NULL`，此时取第一个非缺失的 `(xmax - xmin)`（柱宽 0.9）。
  显式给 `width` 只影响位移量，柱宽仍按数据里的 `d_width / n`。
- **`n`**：`preserve = "total"`（默认）按每个 x 上的不同 group 数；
  `preserve = "single"` 取所有 x 上的最大组数（不均匀分组时也能对齐）。
- **并排**：`d_width = max(xmax - xmin)`（组内），
  `x = x + width * ((order - 0.5) / n - 0.5)`，
  `xmin = x - d_width / n / 2`，`xmax = x + d_width / n / 2`。
  `order` 列就是上游 `setup_data()` 的产物（整数）：组内 group 升序名次；
  `reverse = TRUE` 取负后再排名次，因此 group 1 跑到右边。
- 单组（`n == 1`）直接返回该组，不做位移。
- 没有 `xmin/xmax` 时补 `xmin = xmax = x`（`width = NULL`）或
  `x ± width/2`（显式 width）；没有 `ymax` 时补 `ymax = y`（上游 `collide()`
  的副作用，柱图本来就有 ymax，点图会多这一列）。
- `orientation = "y"`：没有 `flipped_aes` 列时的默认朝向（上游
  `has_flipped_aes(data, default = self$orientation == "y")`）。

R 对照（同上数据，`position_dodge()`）：

| 列 | 值 |
| --- | --- |
| `x` | 0.775, 1.225, 1.775, 2.225 |
| `xmin` | 0.55, 1.0, 1.55, 2.0 |
| `xmax` | 1.0, 1.45, 2.0, 2.45 |
| `order` | 1, 2, 1, 2 |

### dodge2

`PositionDodge2$setup_data()` / `setup_params()` + `collide2(pos_dodge2)`：

- 先按 `(x, group)`（`reverse = TRUE` 时 `(x, -group)`）稳定排序，再用
  `find_x_overlaps()` 把**重叠或相接**的 x 区间划成一组（`xmin`/`xmax` 缺失时
  按 `downup` 填充、重叠组重新编号）。
- `newx = (min(xmin) + max(xmax)) / 2`；`n` 缺省（`preserve = "total"`）取每个
  重叠组的行数，`preserve = "single"` 取所有 x 上的最大行数。
  `preserve = "single"` 的「最大行数」按上游 `setup_params()` 在**补 x 之前**
  决定：data 有 `x` 时是 `table(panel$x)`，只有 `xmin`/`xmax` 时是逐面板
  `find_x_overlaps()` 的重叠组数（`geom_rect` 这类没有 x 的图层因此得到 ≥ 2）。
  `new_width = (xmax - xmin) / n`，再按 `newx` 把各组的 `new_width` 累加、从
  `newx - size/2` 起依次切分 → 新的 `xmin/xmax`，`x = (xmin + xmax) / 2`。
- 多个重叠组时再叠 `padding`：`pad_width = new_width * (1 - padding)`，
  `xmin/xmax = x ∓ pad_width/2`（默认 `padding = 0.1`，即柱宽缩 10%）。
- 每个 x 只有一根柱（`xid` 全不同）时上游直接返回、不叠 padding：**退化成
  identity**（不抛错）。

R 对照（同上数据）：`x` 与 dodge 相同；`padding = 0.1` 时
`xmin = 0.5725, 1.0225, 1.5725, 2.0225`，`padding = 0.2` 时
`xmin = 0.595, 1.045, 1.595, 2.045`。

### jitter

上游 `compute_jitter()`：

- `width` / `height` 缺省 = `resolution(x, zero = FALSE, discrete = TRUE) * 0.4`
  ——即最小非零间隔（全等 / 单一水平时为 1）的 40%。离散位置在 ggplot2 里本来
  就是 1..n，所以 R 的 `is_mapped_discrete()` 分支与这里的 `resolution` 同值。
- `seed` 给定时用 `np.random.default_rng(seed)`，**不碰全局 RNG**；同一个 seed
  两次调用逐位相同，不同 seed 不同。`seed = None`（R 的 `NA`）每次重新抽。
- 抖动偏移量作用在整个 x 族（`x / xmin / xmax / xend / …`）与 y 族上；
  `width <= 0`（`height <= 0`）那一轴不动；`±Inf` 的位置不抖（上游
  `x_jit[is.infinite(x)] <- 0`）。

### nudge

上游 `PositionNudge$compute_layer()`：`x` / `y` 平移整个 x 族 / y 族；
`x` / `y` 为 `NULL` 时回退到数据里的 `nudge_x` / `nudge_y` 列（逐行位移），
两者都没有就是 0（恒等）。零位移不触碰数据。

## 4. 默认值与 geom 的默认 position

| 注册名 | 参数（缺省） |
| --- | --- |
| `position_identity` | — |
| `position_stack` | `vjust = 1`, `reverse = FALSE` |
| `position_fill` | `vjust = 1`, `reverse = FALSE` |
| `position_dodge` | `width = NULL`, `preserve = "total"`, `orientation = "x"`, `reverse = FALSE` |
| `position_dodge2` | `width = NULL`, `preserve = "total"`, `padding = 0.1`, `reverse = FALSE` |
| `position_jitter` | `width = NULL`（40% resolution）, `height = NULL`, `seed = NULL` |
| `position_nudge` | `x = NULL`, `y = NULL` |

geom 缺省（`GEOM_SPECS`，M1-1 起就钉住）：bar / col / histogram / area =
`stack`，boxplot = `dodge2`，其余 = `identity`。`geom_*(position=...)` 覆盖。

## 5. 与 R 的差异面

1. **jitter 的随机流不同**：R 用 Mersenne-Twister + `runif(n, -amount, amount)`，
   gg4py 用 `np.random.default_rng()` 的 PCG64。同一个 `seed` 两边都可复现，
   但**值不相等**；对拍只比包络（每个偏移 ≤ `width` / `height`）与可复现性。
2. **`dodge2` 单组时会漏内部列**：上游在「每根柱各自一个重叠组」的早退分支里
   把 `xid / newx / new_width` 一起返回进了 `$data`；gg4py 不保留这三个内部列
   （位置列的值仍与 R 逐值相等）。
3. **`nudge_x` / `nudge_y` 缺省列**：上游 `PositionNudge$default_aes` 会把这两列
   补进 `$data`（值为 0）。gg4py 的 `finish` 只处理 geom 的 `default_aes`，
   所以 `$data` 里还没有这两列；位置调整本身支持读取它们（见 §3 nudge）。
4. **`stack` 的 NA x**：上游 `collide()` 按 `xmin` 分组时会把含 NA 的整行坐标
   抹成 NA；gg4py 保留有效坐标、把 NA y 当零高度（这是 M1-3 起的既有口径）。
5. **横向（`flipped_aes`）只到位置层**：position 完全支持 flipped 表；但
   `geom_col(orientation="y")` 的 orientation 检测属于 geom `setup_data()`，
   M1-7 之前恒为 FALSE。横向用例因此用直接构造的 flipped 表对拍。
6. **`p + position_dodge()`**：上游报错，gg4py 记进 `plot.position`
   （注册表「两个入口」的契约要求）；流水线不消费这个字段。
7. **width 警告**：上游 `position_dodge()` / `position_dodge2()` 在没有
   `xmin/xmax` 且没有 `width` 时发 `Width not defined` 警告；gg4py 静默按
   `width = 0` 处理（位置列结果与 R 相同）。

## 6. 夹具与测试

- `pixi run -e refs refs:position`（`tools/refs/position_ref.R`）生成
  `tests/fixtures/position_r_reference.json`：11 个 case，每个记
  `input`（geom setup_data 之后、position 之前的表）与 `output`
  （`ggplot_build(p)$data[[1]]` 的同名列），并自检「探针包装不改变输出」。
  产物入库，CI 不装 R。
- case：`stack_two_groups` / `stack_reverse` / `stack_negative` /
  `fill_two_groups` / `dodge_two_groups` / `dodge_preserve_single` /
  `dodge2_two_groups` / `dodge2_padding` / `dodge_horizontal` /
  `jitter_seed`（只比包络）/ `nudge`。
- 数值 `atol = 1e-12`；`order` 列出现时要逐值相等（类型也按 R 的 integer）。
- 红测试：`test_parity_has_teeth` 把 `dodge_two_groups` 的 `xmin[0]` 挪
  `1e-3`，逐值比较必须红；`tests/test_position.py` 里的期望值都取自同一份夹具。

## 7. 实现对照

| `ggcore.position` | ggplot2 4.0.3 |
| --- | --- |
| `PositionIdentity.compute_layer` | `PositionIdentity$compute_layer()` |
| `_collide_stack()` | `PositionStack/Fill$compute_panel()` + `collide()` + `pos_stack()` |
| `_dodge()` / `_dodge_panel()` | `PositionDodge$setup_data()/setup_params()` + `collide()` + `pos_dodge()` |
| `_dodge2_panel()` / `_find_x_overlaps()` | `PositionDodge2$setup_*()` + `collide2()` + `pos_dodge2()` + `find_x_overlaps()` |
| `_jitter()` / `_resolution()` | `PositionJitter$compute_panel()` + `compute_jitter()` + `resolution()` |
| `_nudge()` | `PositionNudge$setup_params()` + `compute_layer()` |
| `_frame_flip` / `_Frame.flip()` | `has_flipped_aes()` / `flip_data()` / `switch_orientation()` |
| `_dodge_order()` / `_match_sorted()` / `_ave_match_sorted()` | `vec_ave(..., match_sorted)` / `match_sorted()` / `xtfrm()` |
