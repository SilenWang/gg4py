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
- 布局阶段（gtable 分配剩余空间）要的是 null 的**计数**，不走换算：
  `null_value(unit)` 对应 R 的 `pureNullUnitValue()`，只累加 `null`（含嵌套
  `sum`），其它单位计 0。

### 浮点边界：不提前取整

全程 double，运算顺序与 C 一致，所以这些结果逐位相同：

- `unit(0.1, "cm") + unit(0.2, "cm")` → `3.0000000000000004` mm；
- `unit(1/3, "npc")` → `3.333333333333333` cm；
- `unit(1, "mm") / 3` → `0.9484251968503936` pt。

除法按 R `Ops.unit` 的写法先取 `1 / x` 再乘，和直接除的浮点结果不一定相同。
这三条在对拍里用 `tolerance = 0`（逐位相等）守着。

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
| `unit.pmax` 的 `all_type` 累积 bug | `summaryUnits()` 的 `all_type` 不按位置重置，前面出现混合类型后，后面同类型的位置也不会塌成简单单位 | 按位置判定，不受前面位置影响 |
| `unit.psum` 对非 simpleUnit 参数的重复计数 | `summaryUnits()` 先把 `amount` 初始化为第一项，循环里又加一遍，所以 `unit.psum(a, a)`（`a` 是 `1strwidth`）返回 `3strwidth` | 返回 `2strwidth`（`tests/test_units.py` 守着） |
| 复合 `max` 全负值 | 初值是 `DBL_MIN`（正的 2.2e-308），`max(-1cm, -20mm)` 求值得到 `5.65e-308` cm | 用 `-inf` 起步，得到 `-1` cm（`min` 的 `DBL_MAX` 初值与语义一致） |
| 空单位 | 无法构造 | 允许（见上） |
| `strascent` / `strdescent` / `grob*` 单位 | 支持 | 未实现（M0-6 之后按需补） |

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
- 现在 93 条用例，覆盖任务要求的全部单位类型、`±*/`、`pmax`/`pmin`/`psum`、
  `unit.c` 摊平、`null` 不进总和、空列表与三条逐位舍入边界。

## 与后续模块的接口

- **viewport（M0-4）**：`UnitContext(width_cm, height_cm, xscale, yscale)` 就是
  viewport 需要提供的那部分；换算用 `convert_x` / `convert_y` /
  `convert_width` / `convert_height`，或带轴参数的 `convert_unit`。
- **gtable（M0-5）**：列/行宽用 `unit_pmax` / `unit_psum` 组合，剩余空间用
  `null_value()`。
- **grob / 设备（M0-6 / M0-8）**：`lines` / `char` 依赖 `fontsize * cex`；
  `strwidth` / `strheight` 等 M0-7 的 `Metrics` 实现，单位系统只负责乘。
