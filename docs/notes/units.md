# 单位口径账本（units）

`ggcore.units` 是 `grid::unit` 的 Python 对等物，是 viewport / gtable / grob 尺寸
计算的底座。这里只记「与 R 对齐但结论不明显」的口径，以及刻意不复制的行为。

参考实现：R 4.5.3 的 `grid`（`src/library/grid/R/unit.R`、`src/library/grid/src/unit.c`、
`src/library/grid/src/grid.c` 的 `L_convert()`）。R 版本由 `pixi.toml` 的
`[feature.refs]` 钉住，对拍夹具由它生成。

## 模型：单位是一个列表，不是一次折算

`Unit` 是元素的有序列表，每个元素是 `(amount, kind, data)`，对应 R `unit` 对象。
`unit(1, "npc") + unit(2, "mm")` 得到 `sum(1npc, 2mm)`——**保留两个单位**，
只有求值时才逐项换算。`unit.c()` 是拼接 + 摊平（长度相加），`sum` / `min` /
`max` 是复合元素，`length()` 是元素个数。

`unit.pmax` / `unit.pmin` / `unit.psum` 是**逐元素**归约（R `summaryUnits()`）：
同一位置的单位同名同数据时直接归约 amount；混合单位时生成
`max(sum(...), ...)` 这样的复合元素，嵌套的 `sum` 会被摊进 `psum`。
R 的 `sum()` / `min()` / `max()`（`Summary.unit`）不同：它们塌成**一个**元素。

## 构造：`unit()` 的长度回收

`unit(amount, kind)` 按 R `constructUnits()`（`grid/src/unit.c`）的规则把两个参数
**按模回收**到 `max(len(amount), len(kind))`：

| 调用 | 结果 |
| --- | --- |
| `unit(1, ["cm", "mm", "inches"])` | `1cm 1mm 1inches`（amount 回收） |
| `unit([1, 2, 3], ["cm", "mm"])` | `1cm 2mm 3cm`（kind 回收） |
| `unit([1, 2, 3], ["cm", "mm", "npc", "lines"])` | `1cm 2mm 3npc 1lines`（两边都收） |

R 不在这里做整除检查，也不发 R 惯常的 recycling warning——`constructUnits()`
直接对两个下标取模，ggcore 照抄。

`data`（`strwidth` / `strheight` 的文本）按 R `validData()`：长度为 1 时复用，
**长于**单位数时取前 N 个，短于单位数且不为 1 时报
`data must be either NULL, have length 1, or match the length of the final unit vector`。

注意 R 会把 character 向量整体包成**一个** data 元素（`data <- list(data)`），所以
R 侧 `unit(1:3, "strwidth", data=c("a","b"))` 不报错、只有 `data=list("a","b")` 才报；
ggcore 的「一元素一 data」模型是下面列的主动窄化，这句文案在它的触发面上自洽。

主动窄化的两点（ggplot2 4.0.3 与 gtable 0.3.6 的调用面都没有命中）：

- 一次 `unit()` 里不能同时出现字符串单位与普通单位（R 允许按元素混搭）；
- `data` 只接受一个字符串或「一个元素一段文字」的列表。R 允许把多个字符串塞进
  **单个**元素（`unit(1, "strwidth", data = c("a", "b"))` 在 R 里是长度 1、
  data 为长度 2 的字符向量），ggcore 的「一元素一 data」模型表达不了。

## 换算链：一律经英寸

R `transform()` 先把源单位换算成**英寸**，再由 `transformFromINCHES()` 换算到目标
单位。`ggcore.units` 照做，所以两次换算的顺序、常数与 R 逐位一致（见下面的浮点
边界）。`points` / `picas` / `dida` / `cicero` / `scaledpts` 用的是 TeX pt。

| 单位 | 到英寸 | 从英寸回来 | 备注 |
| --- | --- | --- | --- |
| `npc` | `v * thisCM / 2.54` | `v / (thisCM / 2.54)` | `thisCM` 是当前轴（x 宽 / y 高） |
| `native` (location) | `((v - min) / (max - min)) * thisCM / 2.54` | `min + (v / (thisCM / 2.54)) * (max - min)` | 需要 `xscale` / `yscale` |
| `native` (dimension) | `(v / (max - min)) * thisCM / 2.54` | `(v / (thisCM / 2.54)) * (max - min)` | 尺寸不减去 `min` |
| `snpc` | `v * min(thisCM, otherCM) / 2.54` | 不支持（见下） | 取视口两边的较小值 |
| `mm` | `v / 10 / 2.54` | `v * 2.54 * 10` | 写成 `/10/2.54` 是为了和 C 的运算顺序一致 |
| `cm` / `inches` | `v / 2.54` / `v` | `v * 2.54` / `v` | |
| `points` / `pt` | `v / 72.27` | `v * 72.27` | **TeX pt**，不是 1/72 in |
| `picas` | `v * 12 / 72.27` | `v / 12 * 72.27` | |
| `bigpts` | `v / 72` | `v * 72` | 只有它是 1/72 in |
| `dida` | `v / 1157 * 1238 / 72.27` | `v / 1238 * 1157 * 72.27` | |
| `cicero` | `v * 12 / 1157 * 1238 / 72.27` | `v / 1238 * 1157 * 72.27 / 12` | |
| `scaledpts` | `v / 65536 / 72.27` | `v * 65536 * 72.27` | |
| `char` | `v * ps * cex / 72` | `v * 72 / (ps * cex)` | `ps` 是 `gpar(fontsize=)` |
| `lines` | `v * ps * cex * lineheight / 72` | `v * 72 / (ps * cex * lineheight)` | 见下 |
| `strwidth` | `v * 度量宽度(英寸)` | 不支持 | 度量由 `UnitContext.metrics` 注入 |
| `strheight` | `v * 度量高度(英寸)` | 不支持 | 同上 |
| `null` | 0（求和/取 max）；取 min 时是 `thisCM` | 不支持 | 见下 |

别名按 R 的 `UnitTable`：`pt`/`point` → `points`，`in`/`inch` → `inches`，
`line` → `lines`，`centimetre(s)`/`centimeter(s)` → `cm`，
`millimetre(s)`/`millimeter(s)` → `mm`。注意 **`pt` 是 72.27 的 points**，
不是 `bigpts`。

## 不明显的口径

### `lines` 带行高，不是字号

R 里 1 line = `ps * cex * lineheight / 72` 英寸；`lineheight` 默认 1.2，
所以 12pt 下 1 line = 0.2 in，而不是 12pt = 0.1667 in。`char` 才是不带行高的
`ps * cex`。`ggcore.units` 的 `UnitContext.lineheight` 默认 1.2，与
`get.gpar()$lineheight` 一致。

### `strwidth` / `strheight` 是上下文相关的

R 在设备上用当前 `gpar` 的字体测得宽度/高度（`GEStrWidth`），`ps * cex` 已经在
度量里。`ggcore.units` 不硬编码字体：`UnitContext.metrics` 提供
`strwidth(text, fontsize=, cex=)` / `strheight(...)`，返回英寸；没有 provider
时换算直接报错，不静默给 0。对拍夹具把 R 在该上下文测得的宽度/高度作为注入值
记录下来，测的是单位代数；真实字体度量是 M0-7 的交付物。

### `null`

- 换算是 0（位置、尺寸、求和、取 max 都是），所以**null 不进总和**：
  `unit(1, "null") + unit(2, "cm")` 是 2cm。
- 取 min 时 R `evaluateNullUnit()` 返回 `thisCM`（视口宽/高的厘米**数值**，
  未换算成英寸），比任何正常尺寸都大，因此 null 永远不会赢 min。这个数被当作
  英寸继续参与运算，是 R 的既有行为；我们照抄以保证对拍一致。
- 布局阶段（gtable 分配剩余空间）要的是 null 的**逐元素计数**，不走换算：
  `is_pure_null(unit, index)` / `null_value(unit, index)` 对应 R 的
  `pureNullUnit(unit, index)` / `pureNullUnitValue(unit, index)`
  （`grid/src/unit.c`，前者是后者的前置门，两者都按索引取值）。

  **不是**对整个 unit 求和：一整列宽可以是一个长度 N 的 unit 向量，
  `unit_c(unit(1, "null"), unit(2, "null"))` 的第 0 / 1 元素分别是 `1` / `2`。

  | unit | `is_pure_null(u, 0)` | `null_value(u, 0)` | `null_value(u, 1)` |
  | --- | --- | --- | --- |
  | `unit_c(unit(1, "null"), unit(2, "null"))` | `True` | `1` | `2` |
  | `unit(1, "null") + unit(2, "cm")` | `False` | `0` | 越界 |

  嵌套的 `sum` 按 R 递归：展开累加子项、`min` / `max` 取子项最值，最后乘外层
  `amount`。

  gtable（M0-5）逐列/逐行取权重，写法与 `grid/src/layout.c` 的
  `findRelWidths()` 一致：

  ```python
  widths = ...  # 每列一个元素的 unit 向量
  relative = [is_pure_null(widths, i) for i in range(len(widths))]
  weights = [null_value(widths, i) for i in range(len(widths))]
  # relative[i] 为真的列按 weights 归一化分剩余空间，其余列走固定尺寸。
  ```

  `null_value` 对非纯 null 元素直接给 0（R 的 layout 用 `pureNullUnit` 门挡住
  这类元素），所以即使不写 `relative` 一层，`unit(1, "null") + unit(2, "cm")`
  也不会被当成 1 份权重。`unit(0, "null")` 是纯 null 但权重为 0：两个判断不重复。

### 浮点边界：不提前取整

全程 double，运算顺序与 C 一致，所以这些结果逐位相同：

- `unit(0.1, "cm") + unit(0.2, "cm")` → `3.0000000000000004` mm；
- `unit(1/3, "npc")` → `3.333333333333333` cm；
- `unit(1, "mm") / 3` → `0.9484251968503936` pt。

除法按 R `Ops.unit` 的写法先取 `1 / x` 再乘，和直接除的浮点结果不一定相同。
这三条在对拍里用 `tolerance = 0`（逐位相等）守着。

`sum()` / `min()` / `max()` 的子项顺序也照抄 R `Summary.unit`：只要有一个顶层
元素是 `sum`/`min`/`max`，非匹配单位就排在前面、被摊平的子项排在后面
（`c(x[-matchUnits], matchData)`）。普通量级两种顺序等价，大数相消时才分叉：
`unit_sum(unit(1e16, "cm") + unit(1, "mm"), unit(-1e16, "cm"))` 在对拍里是
`0.1` cm（保持交错顺序会得 `0`）。`unit.psum` 走另一条 C 路径
（`summaryUnits()`），保持交错顺序，同一输入得 `0`——两条路径的差别也有用例守着。

### 空单位列表

R 4.5.3 **造不出**空单位：`unit.c()` 报 `attempt to set an attribute on NULL`，
`unit(numeric(0), "cm")` 与零长度子集也报错。gg4py 允许 `Unit()` / `unit_c()`：

- `len()` 为 0，换算返回空数组；
- 加法里是单位元（`u + 空 == u`），缩放为空；
- `unit_pmax()` / `unit_psum()` 无参数时为空（与 R 的零长度结果一致），
  `unit_psum(空, unit(2, "cm"))` 丢掉空参数后等价于 `2cm`（R `pSummary` 的
  `lengths != 0`）；
- `unit_sum(空)` 是一个没有子元素的 `sum`，求值为 0。

`tests/test_units_r_parity.py` 里 `empty-unit-python-only` 这条用例同时记录了
R 侧的报错信息，避免以后误以为这是 R 的行为。

## 刻意不复制 / 不支持

| 行为 | R | gg4py |
| --- | --- | --- |
| 换算目标为 `strwidth` / `strheight` / `null` | 报 `invalid unit or not yet implemented` | 同样报 `UnitError` |
| 换算目标为 `snpc` | R 4.5.3 报错（`transformFromINCHES` 里没有该分支） | 同样报错；`snpc` 只作源单位 |
| `unit.pmax` 的 `all_type` 累积 bug | `summaryUnits()` 的 `all_type` 不按位置重置：`unit.pmax(unit(c(1, 2), c("cm", "cm")), unit(c(3, 4), c("mm", "cm")))` 的结构是 `max, max` | 按位置判定，同例结构是 `max, cm`（见下） |
| `unit.psum` 对非 simpleUnit 参数的重复计数 | `summaryUnits()` 先把 `amount` 初始化为第一项，循环里又加一遍，所以 `unit.psum(a, a)`（`a` 是 `1strwidth`）返回 `3strwidth` | 返回 `2strwidth`（`tests/test_units.py` 守着） |
| 复合 `max` 全负值 | 初值是 `DBL_MIN`（正的 2.2e-308），`max(-1cm, -20mm)` 求值得到 `5.65e-308` cm | 用 `-inf` 起步，得到 `-1` cm（`min` 的 `DBL_MAX` 初值与语义一致） |
| 空单位 | 无法构造 | 允许（见上） |
| `strascent` / `strdescent` / `grob*` 单位 | 支持 | 未实现（M0-6 之后按需补） |

### 三处未复制的差异：为什么，以及为何没有影响

三处都是 R 实现里的 bug，不是语义（前两处在 `summaryUnits()`，第三处在复合
`max` 的求值初值）；复刻它们只会把位置相关的行为带进布局。审核给了调用面
证据，这里记下来，便于以后复核：

| 差异 | 为什么不复制 | 对 ggplot2 / gtable 调用面 |
| --- | --- | --- |
| `unit.pmax` 的 `all_type` 累积 | `all_type` 声明在位置循环**外**且从不重置，等于「前面出现过混合类型，后面同类型的位置也不再归约」。这是 C 的作用域失误，复刻等于让第 N 列受第 N-1 列影响 | `unit.pmax` 在 ggplot2 4.0.3 只有 `geom-label.R:164-165`（`padding` 与 `descent`），gtable 0.3.6 只有 `compare_unit()` 的 `rbind`/`cbind` 宽高匹配（`rbind-cbind.R:93-94`、`142-143`）。两处每个位置都是同类型非负量，R 里 `all_type` 也恒为真，bug 不显形 |
| `unit.psum` 的重复计数 | 同一个函数先把 `amount` 初始化成第一项、循环里又加一遍，是笔误 | `unit.psum` 在 ggplot2 4.0.3 与 gtable 0.3.6 中**均无调用** |
| 复合 `max` 从 `DBL_MIN` 起步 | `DBL_MIN` 是**正**的最小规格化数，`max(-1cm, -20mm)` 得 `5.65e-308` cm，结果符号都不对；`min` 用 `DBL_MAX` 才是自洽的 | 布局里没有负长度；`unit.pmax` 的调用点传的是非负 padding/descent，复合 `max` 不会出现全负子项 |

### 零尺寸视口

与 R 的 `relConvert` 一致：源与目标都是 `npc`/`native`、且是同轴
（或同轴 location↔dimension）时，视口该轴小于 `1e-6 cm` 也直接换算，不经过
英寸；其余情况（如 `cm` → `npc`）报 `Viewport has zero dimension(s)`。

## 参考值怎么来

```bash
pixi run -e refs refs:units     # Rscript tools/refs/units_ref.R
```

- `[feature.refs]` 里有 `r-base = "4.5.*"`（独立 solve-group，不进 dev/prod，
  CI 不装）。`grid` 随 r-base，不需要额外包。
- 脚本在 `pdf(NULL, width = 10, height = 10)` 上逐条 push 视口
  （`width` / `height` / `xscale` / `yscale` / `gpar(fontsize, cex, lineheight)`），
  调 `convertUnit(...)` 取 `valueOnly = TRUE`，连同 `length` / `unitType` /
  `grid:::is.simpleUnit` 和单位结构快照写进
  `tests/fixtures/units_r_reference.json`。
- 每条用例都带 R 表达式（`r`）、Python 构造 spec、上下文和期望值；夹具里
  `r_error` 非空表示 R 侧本来就报错，Python 侧也会报错（空单位那条除外）。
- 现在 99 条用例，覆盖任务要求的全部单位类型、`±*/`、`pmax`/`pmin`/`psum`、
  `unit.c` 摊平、`unit()` 长度回收（amount / kind / data 三个方向）、`sum` 与
  `psum` 的子项顺序、`null` 不进总和、空列表与三条逐位舍入边界。

## 与后续模块的接口

- **viewport（M0-4）**：`UnitContext(width_cm, height_cm, xscale, yscale)` 就是
  viewport 需要提供的那部分；换算用 `convert_x` / `convert_y` /
  `convert_width` / `convert_height`，或带轴参数的 `convert_unit`。
- **gtable（M0-5）**：列/行宽用 `unit_pmax` / `unit_psum` 组合；剩余空间用
  `null_value(widths, i)` 逐列/逐行取权重，`is_pure_null(widths, i)` 判该列
  是否参与分配（见「`null`」一节）。
- **grob / 设备（M0-6 / M0-8）**：`lines` / `char` 依赖 `fontsize * cex`；
  `strwidth` / `strheight` 等 M0-7 的 `Metrics` 实现，单位系统只负责乘。
