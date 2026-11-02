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
4. NA 排在最后（`drop = TRUE` 时 NA 本身也是一个水平）。

`drop = TRUE`（默认）只保留**数据里出现过的组合**，然后按上面的 levels 排序
编号；`drop = FALSE` 取所有水平的笛卡尔积（上游 `unique_combs()`）。

## 2. facet_wrap：一维面板流折成行列

参数：`facets`（列名 / 列名序列 / `aes(...)`）、`ncol` / `nrow`、
`dir`、`as.table`、`drop`、`labeller`、`scales`。

- **列名**：`facet_wrap("a")` 与 `facet_wrap(("a", "b"))` 都行；`aes(grp="a")`
  用 `grp` 做布局里的变量名、`a` 做取值列。
- **行列数**（上游 `wrap_dims()`）：两边都不给时用 `n2mfrow(n)` 再交换
  （3 个面板 → 1 行 3 列；5 个 → 2 行 3 列）；只给一边时另一边取
  `ceiling(n / 给定边)`；放不下直接报错。
- **方向**：`dir = "h"`（默认）→ `as.table` 为真时 `"lt"`（左上起、行优先），
  假时 `"lb"`（左下起）；`dir = "v"` → `tl` / `tr`。也接受上游的 8 个方向
  `lt / tl / lb / bl / rt / tr / rb / br`。
- 例：4 个水平 `d, c, b, a` + `ncol = 2` + `as.table = FALSE` 得到
  PANEL 1=`d`(ROW 2, COL 1)、2=`c`(2, 2)、3=`b`(1, 1)、4=`a`(1, 2)。

## 3. facet_grid：行 × 列

参数：`rows` / `cols`（都可为空）、`margins = False`、`space = "fixed"`、
`as.table`、`drop`、`labeller`、`scales`。

- 行变量、列变量不能重复（上游同样报错）。
- PANEL 按「行优先、行内按列」编号；ROW / COL 从 1 起。
- `as.table = FALSE` **只倒行**（上游 `rev_order()`），列顺序不变。
- 只有 `rows` 或只有 `cols` 时另一维固定为 1 行 / 1 列。
- `margins = TRUE` 与 `space = "free"` **尚未实现**：参数能进 `Facet.params`，
  但 `facet_from_component()` 会报明确的 `FacetError`（TODO 在
  `FacetGrid.__post_init__`）。这样不会静默画出一张与 R 不同的图。

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
- 自由刻度 + `coord_fixed(ratio=…)` 直接报错（上游同样报错：每个面板范围
  不同，无法共用一个物理比例）。

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
- `strips`：`FacetStrip(name, side, text, panel, row, col)`；wrap 的
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

strip 的行高 / 列宽 = 文本高度 + 上下（左右）margin。M1-6 用
`0.955em × strip.text.size + margin` 近似 grid 的 `stringHeight()`（R 在
8.8pt 下量到 8.4pt / 0.6071cm；我们 0.6058cm，差 0.2%）。M1-7 接上
`MetricProvider.strheight()` 后替换这个常量，测试容差同时收紧。

完整 grob 绘制（面板背景、网格线、geom 墨迹、坐标轴、图例）不在 M1-6，
留给 M1-7；这里的占位 grob 只携带 `kind / name / text / panel / side`。

## 7. 不支持清单

| 能力 | 现状 | 计划 |
| --- | --- | --- |
| `facet_grid(margins = TRUE)` | 报 `FacetError` | M1-6+ |
| `space = "free_x" / "free_y"` | 报 `FacetError` | 需要真实面板尺寸约束 |
| `facet_wrap(strip.position = "bottom"/"left"/"right")` | 报 `FacetError`（只支持 top） | M1-7 |
| 自由刻度 + `coord_fixed(ratio=…)` | 报错（与上游一致） | — |
| 完整 grob / 坐标轴 / 图例 | 只给结构 | M1-7 / M1-11 |
| NA 分面值落在 `drop = FALSE` 的组合之外 | 报 `FacetError` | 上游会落 PANEL=NA 后由 `handle_na` 丢弃 |

## 8. 验收命令

```bash
pixi run check                         # 全量门禁（imports / determinism / cbor）
pixi run -e refs refs:facet            # 重新生成 R 夹具（产物入库）
pixi run test -q tests/test_facet.py tests/test_facet_r_parity.py
```
