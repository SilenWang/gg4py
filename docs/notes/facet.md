# 分面口径（M1-6）

`ggcore.facet` 是 ggplot2 4.0.3 分面的对等物：`facet_null()` /
`facet_wrap()` / `facet_grid()`。它只回答三件事：

1. **布局**——分面变量 → `PANEL / ROW / COL / SCALE_X / SCALE_Y`；
2. **面板标度**——`scales = "fixed" | "free" | "free_x" | "free_y"` 时，
   哪几个面板共用一套位置标度；
3. **数据归属**——每行数据落在哪个 PANEL（1 起）。

代码：`src/ggcore/facet.py` + `src/ggcore/build.py` 的 `_build_plot_facets()`。
测试：`tests/test_facet.py`（口径 / 负向）、`tests/test_facet_r_parity.py`
（R 逐值对拍）。R 夹具：`tests/fixtures/facet_r_reference.json`，
生成命令 `pixi run -e refs refs:facet`。

```
plot.facet (components.Facet：name + params)
        │  facet_from_component()
        ▼
FacetNull / FacetWrap / FacetGrid
        │  compute_layout(各层原始数据)
        ▼
FacetLayout ── map_data(layer) ──▶ 每行 PANEL
        │
        └── init_scales：固定刻度共 1 套；free 时 wrap 每面板一套、grid x 按列 / y 按行
                │
                ▼
        build_plot()：按 PANEL 切数据跑六阶段 → PlotBuild.panels（每面板 PanelParams）
```

## 1. 布局顺序 = levels，不是出现顺序

分面值的水平表按下面的顺序建立（`FacetVar.explicit_levels()` / `_Levels`）：

1. 源列是 categorical（或带显式 levels 的离散列）→ 用 `Column.levels` 的顺序；
2. 普通字符串列 → 升序去重（与 `ggcore.data` 的离散 levels 同一口径）；
3. 数值列 → 数值升序；
4. NA 排在最后（NA 本身也是一个水平，`drop` 取两种值都一样）。

`drop = TRUE`（默认）只保留**数据里出现过的组合**，然后按上面的 levels 排序
编号；`drop = FALSE` 取所有水平的笛卡尔积（上游 `unique_combs()`）。显式
levels 里没有出现的 factor level 在 `drop = FALSE` 时也会得到一个空面板。

两种分面的「缺失组合」口径不同：

- `facet_wrap` 的 `drop = TRUE` = 所有分面变量**联合**出现过的组合；
- `facet_grid` 的 `drop = TRUE` = 每一维（rows / cols 各自）出现过的组合，
  再取两维的笛卡尔积——缺数据的格子保留为空面板（面板数可以多于数据里
  实际出现的组合数）。

布局表 `FacetLayout.table` 的分面变量列保留**原始类型**（numeric → `float`，
logical → `bool`，字符串 / 因子 → `str`；NA 进 `na_mask`）；显示文本在
`FacetLayout.label_table` 的同类列里（`label_value` 口径：逻辑值
`TRUE` / `FALSE`，NA → `"NA"`）。`map_data()` 只用原始值匹配，所以字符串
`"NA"` 不会和真正的缺失值撞键。

## 2. facet_wrap：一维面板流折成行列

参数：`facets`（列名 / 列名序列 / `aes(...)`）、`ncol` / `nrow`、
`dir`、`as.table`、`drop`、`labeller`、`scales`、`space`。

- **列名**：`facet_wrap("a")` 与 `facet_wrap(("a", "b"))` 都行；`aes(grp="a")`
  用 `grp` 做布局里的变量名、`a` 做取值列。
- **行列数**（上游 `wrap_dims()`）：两边都不给时用
  `n2mfrow(n) = (ceil(sqrt(n)), ceil(n / ceil(sqrt(n))))` 再交换
  （3 个面板 → 1 行 3 列；5 个 → 2 行 3 列；13 个 → 4 × 4；20 个 → 4 × 5，
  与 R 1..20 全对）；只给一边时另一边取 `ceiling(n / 给定边)`；放不下直接报错。
- **方向**：`dir = "h"`（默认）→ `as.table` 为真时 `"lt"`（左上起、行优先），
  假时 `"lb"`（左下起）；`dir = "v"` → `tl` / `tr`。也接受上游的 8 个方向
  `lt / tl / lb / bl / rt / tr / rb / br`。
- **`space`**：只有 `"fixed"`（默认）/ `"free_x"` / `"free_y"`（上游不接受
  `"free"`）。`free_x` 强制**一行**、列宽按各面板 x 范围差分配；`free_y`
  强制一列。给 `nrow` / `ncol` 也会被覆盖（R 同样是覆盖 + warning）。
- 例：4 个水平 `d, c, b, a` + `ncol = 2` + `as.table = FALSE` 得到
  PANEL 1=`d`(ROW 2, COL 1)、2=`c`(2, 2)、3=`b`(1, 1)、4=`a`(1, 2)。

## 3. facet_grid：行 × 列

参数：`rows` / `cols`（都可为空）、`margins = False`、`space = "fixed"`、
`as.table`、`drop`、`labeller`、`scales`。

- 行变量、列变量不能重复（上游同样报错）。
- PANEL 按「行优先、行内按列」编号；ROW / COL 从 1 起。
- `as.table = FALSE` **只倒行**（上游 `rev_order()`），列顺序不变。
- 只有 `rows` 或只有 `cols` 时另一维固定为 1 行 / 1 列。
- **`margins`**：`True` 给两维都加 `(all)` 边际面板；字符串 / 序列只给点名
  的变量加（`margins="a"` → 只多一列）。多变量的部分 margin 是**后缀**组合
  （上游 `reshape_margins()`：`rows=(a,b)`、`margins=True` → `(a,b)` 与 `(b)`
  两组），布局里 `(all)` 排在每个变量的水平末尾；`map_data()` 把一行数据同时
  复制进普通面板与它所属的每个 margin 面板。
- **`space`**：`"fixed"` / `"free"` / `"free_x"` / `"free_y"`。非 fixed 时
  面板列 / 行的 null 权重 = 该列（`ROW == 1`）/ 行（`COL == 1`）面板的范围差
  （上游 `Facet$init_gtable()`）；离散标度因此按水平数、连续标度按数据跨度分配。
- **`respect`**：`coord_fixed` / `coord_polar` 等有物理比例的坐标把 aspect
  **折进行权重**（`heights × |aspect|`）并开 `respect`（null 宽 = null 高），
  所以 `space = "free"` 与 `coord_fixed(ratio)` 同时存在时每个面板的高/宽
  仍是 `ratio × yspan / xspan`，不会再把范围乘第二次（SIL-759）。

## 4. 自由刻度的分配

| 分面 | `free_x` | `free_y` |
| --- | --- | --- |
| `facet_wrap` | 每个面板一套（`SCALE_X = PANEL`） | 每个面板一套（`SCALE_Y = PANEL`） |
| `facet_grid` | 每列一套（`SCALE_X = COL`） | 每行一套（`SCALE_Y = ROW`） |

- 固定刻度时 `SCALE_X = SCALE_Y = 1`，所有面板共用一套 `ScaleSet`——这与
  M1-5 的单面板路径完全等价。
- free 的位置标度**只在该面板/列/行的数据上训练**（上游
  `Facet$train_scales()`），所以 `panel_params[[i]]$x.range` 各自不同；
  非位置标度（colour / fill / size / shape / alpha）仍然全局训练一份，
  避免同一离散值在不同面板里换颜色。
- 实现：`PanelScaleSet` 把位置美学转发到面板槽位、其余转发到共享
  `ScaleSet`。`build_plot()` 先训练全部面板，再统一 `map_position`；
  `compute_position` 之后按上游口径再训练一次。
- 自由刻度 + `coord_fixed(ratio=…)`：**只有** `facet_grid(space = "free")`（两维
  都 free）允许（R 4.0.3 实测）；`space = "free_x"` / `"free_y"`、`facet_wrap()`
  的自由刻度都会报 `can't use free scales with coord_cartesian() with a fixed
  ratio argument`。允许的组合里 `ratio` 折进**行权重**（`heights × ratio`），
  面板高/宽 = `ratio × yspan / xspan`。

## 5. 逐面板流水线

`build_plot()` 对 wrap / grid：

1. `compute_layout()` 得到布局；
2. 每层 `map_data()` 得到 PANEL（层里缺分面变量时按布局水平复制行，
   与上游 `map_data()` 的 `missing_facets` 分支一致）；
3. 按 PANEL 切数据跑**同一套六阶段**：
   - `compute_aesthetics` 的 PANEL 列写真实面板号；
   - `transform_scales` / `map_position` 用该面板的标度；
   - `compute_stat` / `compute_position`：`identity` 是上游的快路径
     （行序不变），`count` / `stack` 走通用分支（按 PANEL 分组，结果
     面板优先拼接）；
   - `map_scales` / `finish` 逐面板映射，再按原行序拼回；
4. 每面板一份 `PanelParams`（`PlotBuild.panels[i].panel_params`）；
   `PlotBuild.panel_params` 保留为**第一个**面板，兼容 M1-5 的调用方。

`facet_null` 不走上面的循环：`build_plot()` 保留 M1-5 的单面板代码路径，
输出逐字节不变。`tests/test_facet.py::test_facet_null_build_is_byte_identical_to_m1_5`
把 main@`efdb65c` 与分支的六张图摘要钉进测试。

## 6. gtable：面板矩形 + strip + spacing

`PlotBuild.facet_table()`（`ggcore.facet.facet_table()`）给出
`FacetTable`：

- `gtable`：panel 行列（`1null`）、strip 行/列（固定 cm）、
  `panel.spacing.x` / `panel.spacing.y` 分隔行列；
- `panels`：`(PANEL, t, l, b, r)`，名字沿用上游 `panel-<col>-<row>`；
- `strips`：`FacetStrip(name, side, text, panel, row, col, fill)`；wrap 的
  `side = "top"`（每个面板行一条），grid 列 strip = `"top"`、行 strip =
  `"right"`；
- `panel_boxes(width_cm, height_cm)`：从 gtable 行/列解析出的面板矩形
  （cm），可直接断言等宽等高。

元素来源（全部走 `ggcore.theme` 的解析值）：

| 东西 | 主题元素 |
| --- | --- |
| strip 文字 | `strip.text` / `strip.text.x` / `strip.text.y`（`ElementText`） |
| strip 背景 | `strip.background` / `strip.background.x` / `strip.background.y` |
| 面板间距 | `panel.spacing` → `panel.spacing.x` / `.y`（默认 5.5pt） |
| 裁剪 | `strip.clip`（默认 `"on"`） |

strip 的行高 / 列宽 = 文字的外向尺寸 + 对应 margin。顶部 strip 读
`strip.text.x`，右侧 strip 读 `strip.text.y`（字号改大时右 strip 变宽，
顶部高度不变）；背景读 `strip.background.x` / `.y`（继承
`strip.background`），落在 `FacetStrip.fill`，`element_blank()` 时为 None。

尺寸口径照 grid 的 `widthDetails()` / `heightDetails()`（`_strip_extent()`）：

| 文字角度 | 宽（列宽） | 高（行高） |
| --- | --- | --- |
| 0 / 180 | 最宽一行的 `stringWidth` | 行高 × 行数 |
| ±90 / 270 | 行高 × 行数 | 最宽一行的 `stringWidth` |

行高 = `TEXT_LINE_EM`（0.8945em = R 的 `stringHeight()` + descent，见
`docs/notes/guide.md`）；宽度走 `text_width_cm()`：有 `metrics` 时是真实
`stringWidth`（缺省 sans 与 svglite 的 Arimo 同度量），没有时按
`FALLBACK_CHAR_EM` 估。**没有**「无度量时用 0.955em 近似」的分支了——
SIL-715 #8：旧实现把 `strip.text.y` 的列宽也当成行高（7.87pt），而
`.facet-grid-ab`（`theme_void()`，angle 0）的 R 值只有 `stringWidth("u")` =
4.909pt（R 4.0.3 + svglite；`t` 只有 2.45pt），右 strip 列因此宽 3pt、
面板整体左移。

**逐变量 strip**：多变量分面在 R 里是每个变量一条 strip（顶部自上而下堆叠、
右侧自左向右并排），不是一条多行文本。`FacetStrip.parts` 保留变量粒度，
`strip_height_cm` / `strip_width_cm` 是整块的总尺寸；`label_both` 的两个变量
因此是 2 × 0.5877cm = 1.1753cm（与 R 逐值一致）。

**变量顺序**：顶部与右侧都是**最后一个变量最靠近面板**。R 的
`build_strip(horizontal = FALSE)` 对右侧先 `rev()` 行变量再
`weave_tables_col()`，所以 `facet_grid(a + b ~ ., labeller = "label_both")`
的 `strip-r-1` 从左到右是 `b: … | a: …`（`b` 贴着面板）；顶部堆叠不反转，
`a` 在上、`b` 在下。`FacetStrip.parts` 按绘制顺序存放（右侧即逆序）。

**`strip.placement`**：`"inside"`（默认）strip 在面板与轴之间；`"outside"`
时 `FacetStrip.outside = True`，strip 块不占 facet gtable 行列，由
`plot_layout()` 在轴带之外另行留位（`PlotLayout.top_strip_band` /
`right_strip_band`），有轴的一侧再留 `strip.switch.pad.grid/wrap` 间隙。

wrap 有多个面板行时，行结构是
`strip / panel / panel.spacing.y / strip / panel / …`——每个面板行上方都有
自己的 strip；grid 只有最上面一行有 `strip-t-<col>`，行 strip
`strip-r-<row>` 在右侧与面板行同高。`FacetTable.strip_height_cm` /
`strip_width_cm` 分别给顶部 strip 块总高与右侧 strip 块总宽。

**`facet_grid(switch =)`**（SIL-811）：`"both"` / `"x"` 把列 strip 换到面板**下方**，
`"both"` / `"y"` 把行 strip 换到**左侧**（`FacetTable.switched_sides` → 名字前缀
`strip-b-*` / `strip-l-*`）。换边后文本元素按边解析：`strip.text.x.bottom` /
`strip.text.y.left`（后者角度 90，与右侧的 -90 互为镜像）。轴带贴着**整张分面表**
的外沿画（`_axis_grobs()` 读 `FacetTable.inside_strip_sides`），所以底部轴标签落在
strip 之下、左侧轴标签落在 strip 右侧，与 R 的 `attach_strips()` 一致；换边 +
`strip.placement = "outside"` 目前按 inside 画（`plot_layout()` 的轴带只有
top / right 两条）。

**labeller**：`"label_value"`（默认）/ `"label_both"`（`变量: 值`）/
`"label_context"`（单变量同 value，多变量同 both）/ `"label_parsed"`（值当
plotmath 表达式，SIL-855）、`labeller(a={...})`（逐变量覆盖，未覆盖的走
`.default`）、`{值: 标签}` 简写与任意 `f(labels) -> labels` 函数。
`FacetBase.strip_labels()` 给逐变量标签。

`label_parsed` 的返回值是 `plotmath.MathText`（`str` 子类）：strip 的量宽 / 行高
走 `plotmath.extent()`（8.8pt 的 `alpha ^ beta` 比纯文本高 2.77pt），落字时拆成
「底数 + 上标」两段（字号 8.8 / 6.16、上标抬 0.502em）各一个 IR text 节点——
IR 的 text 节点没有「段」字段，多段就是多节点。解析不了的标签回退普通文本
（`parse_safe()` 口径），不整列报错。上游 `facet-labels/parsed-facet-labels`
0.15% / 0.02%。

完整 grob 绘制（面板背景、网格线、geom 墨迹、坐标轴、图例）不在 M1-6，
留给 M1-7；这里的占位 grob 只携带 `kind / name / text / panel / side / fill`。

## 7. 不支持清单

| 能力 | 现状 | 计划 |
| --- | --- | --- |
| `facet_wrap(strip.position = "bottom"/"left"/"right")` | 报 `FacetError`（只支持 top） | **仍缺**，SIL-871（`facet_grid(switch=)` 已能换边，`facet_wrap` 不能） |
| 右侧 strip 的 `strip.placement = "outside"` + 次轴 | **刻意回退 inside**（strip 占 gtable 列、落在面板与次轴之间，不再压住次轴标签）；无右轴时仍按 outside 外置 | 保留：次轴带与 outside strip 同时存在时 R 的排法会叠字，这里选不叠字的版式 |
| 自由刻度 + `coord_fixed(ratio=…)` | 只允许 `facet_grid(space = "free")`（两维 free）；`space="free_x"/"free_y"` 与 `facet_wrap()` 报错（与 R 4.0.3 实测一致） | — |
| `coord_polar()` / `coord_radial()` + `space = "free…"` | 报错：R 4.0.3 自己在 `init_gtable()` 里报 `values must be length 1`（上游 bug），gg4py 不再静默出非正圆面板 | 上游修复后再对齐 |
| `theme(aspect.ratio)` | **已参与版式**（SIL-792）：折进面板行权重并开 `respect`，面板高/宽 = `|aspect.ratio|`，多出来的空间居中（单面板与 `facet_wrap` / `facet_grid` 一致）；`space` 非 fixed 时报 R 同样的 `Free scales cannot be mixed with a fixed aspect ratio.` | — |
| 完整 grob / 坐标轴 / 图例 | 已实现（面板背景、网格线、geom 墨迹、轴、guide 都进 gtable） | — |

## 8. 验收命令

```bash
pixi run check                         # 全量门禁（imports / determinism / cbor）
pixi run -e refs refs:facet            # 重新生成 R 夹具（产物入库）
pixi run test -q tests/test_facet.py tests/test_facet_r_parity.py
```
