# 多图合并：组合骨架与 panel 几何对齐（M3-1 / SIL-1001）

`ggcore.composition` 是 **pre-IR 层**：`build_plot() → plot_gtable() → composition →
Scene/IR`。它把多张图合并成一张 unit-based 的 gtable，再走 `scene([gtable], tree)` /
`plotspec.build_scene({"gtable": …})` 出 IR —— **IR 不改**，也不新增节点。

代码：`src/ggcore/composition.py`。测试：`tests/test_composition.py`（API / 表级 /
渲染）与 `tests/test_composition_r_parity.py`（与 patchwork 1.3.2 的关系对拍）。
R 夹具：`tests/fixtures/composition_r_reference.json`，生成命令
`pixi run -e refs refs:compose`（`tools/refs/compose_ref.R`）。

```
ggplot 对象们 ──wrap_plots() / + | /──▶ Patchwork ──gtable()──▶ GTable ──scene()──▶ IR
                                            │                    │
                                            └ plot_layout()      └ 18×15 子表 + panel null 权重
```

## 1. API

```python
import gg4py

p1 | p2  # 并排（一行）
p1 / p2  # 上下（一列）
p1 + p2 + p3  # 顺序追加（ncol / nrow 缺省时按 n2mfrow 近方形）
(p1 + p2 + p3 + p4) + gg4py.plot_layout(ncol=2, widths=[2, 1], heights=[1, 1])
gg4py.wrap_plots(p1, p2, p3, ncol=2, byrow=False)
gg4py.plot_spacer()  # 占位空格

pw = (p1 | p2) / p3
table = pw.gtable(metrics=metrics, width_in=7, height_in=5)  # GTable
scene = pw.to_scene(metrics=metrics, width_in=7, height_in=5)  # ir.Scene
gg4py.ggsave(pw, "out.png", width=7, height=5)  # PNG / SVG / PDF
```

- `wrap_plots()` 接受位置参数或一个列表；`ncol` / `nrow` / `byrow` / `widths` /
  `heights` 等同再 `+ plot_layout(...)`。
- `widths` / `heights` 是**相对权重**（大表 panel 列的 `unit(w, "null")`），长度不足
  时循环（patchwork 的 `rep(..., length.out=)`）；给了多列 `widths` 而没给 `ncol`
  时，长度就是列数。
- `p + theme()` / `p + geom_*()` / `p + labs()` 仍走 `gg_add` 的单图分派；只有
  `ggplot` / `Patchwork` / `plot_spacer()` / `plot_layout()` 才进组合层。

### 运算符优先级

Python 的优先级是 `/` / `*` > `+` > `|`，与 patchwork 的推荐写法一致：

| 写法 | 解析结果 |
| --- | --- |
| `p1 + p2 \| p3` | `(p1 + p2) \| p3` |
| `p1 \| p2 + p3` | `p1 \| (p2 + p3)` |
| `p1 / p2 + p3` | `(p1 / p2) + p3` |

`*` 未实现（patchwork 里它的语义是「把右侧应用到左侧每个子图」）；调用会报一条
说明改用 `|` / `/` 的错误。`/` 与 `*` 同级这件事只影响表达式解析，不影响本实现的
语义。

## 2. 18×15 规范化

patchwork 1.3.2 的 `plot_table()` = `ggplotGrob()` + `add_strips()`：单面板的
16×13 表在 panel 四条边各补一条 0mm 的 strip 行 / 列 → **18×15**，panel 落在
`(10, 8)`。带分面的表是多行多列，`simplify_gt()` 先把 panel 块**坍缩**成 1 行
1 列（块内行列求和），再补缺失的 strip —— 同样回到 18×15。
`R/aaa.R` 的常量就是 `TABLE_ROWS = 18`、`TABLE_COLS = 15`、`PANEL_ROW = 10`、
`PANEL_COL = 8`。

本实现在 `_sheet()` 里照做，但只保留**单位向量**：组合表的渲染不用原表的语义槽位
（`PanelSlot` / `PlotCell` 不带刻度、图例等绘制信息，见 `docs/notes/gtable.md`），
所以缩到「15 个列宽 + 18 个行高 + panel 位置」就够合并了。子表超出 18×15、
或找不到 panel 时显式报 `ComposeError`。

## 3. 合并：同列 / 同行取 max，panel 换 null

`build_patchwork()` 的语义（源码实测）：

1. design 是 `nrow × ncol` 的规则网格（`wrap_dims()` + `create_design()`，默认
   `byrow = TRUE`），每个子图占一格；
2. `table_dims()`：对**同一 layout 列**的所有子表逐槽位取 max 列宽，对**同一
   layout 行**的所有子表逐槽位取 max 行高；
3. `set_panel_dimensions()`：把这些列 / 行的 panel 槽位换成 `unit(权重, "null")`
   （权重来自 `plot_layout(widths/heights)`，缺省 1）；
4. 子表的 layout 记录按 design 的行列平移到对应块，z 顺序按子图顺序累加。

于是「同一列 x / w 相同、同一行 y / h 相同」是取 max + null 权重的直接结果，不需要
额外对齐步骤。

## 4. 渲染：一张表，逐块渲染树

组合表的每条子图记录放一棵**实际渲染树**（`geom.scene.page_grobs()`），不是
`plot_gtable()` 的语义槽位。渲染时：

- 表的 `resolve()` 给出每个块的 cm 矩形和块内 panel 的矩形；
- 子图用 `plot_layout(panel_box=…)` 以**组合表给的 panel 矩形**重算版式；
- 子图的页面尺寸 = 「自身固定槽位和 + 目标 panel 宽 / 高」，多出来的统一空间留在
  块的外侧 —— 这样同列不同槽位的子图 panel 起点 / 宽度也严格相等；
- 嵌套组合（`(p1 | p2) / p3`）的内层 panel 分配整体缩放到外层给的 slot，跨层与
  patchwork 一样**不保证**对齐。

`plot_layout(panel_box=…)` 与 `scene_from_build(panel_box=…)` 是新增的可选参数，
默认 `None` 时逐值保持旧行为（532 份 `expected.svg` 不受影响）。

## 5. 与 patchwork 1.3.2 对拍

`refs:compose` 用 patchwork 1.3.2 + svglite 2.2.2 渲染、按 `panel.background` 的
fill 从 SVG 里读回 panel 矩形。实测（6×6 in，pt）：

| case | panel 矩形 | 结论 |
| --- | --- | --- |
| 平铺 `p1+p2+p3+p4+plot_layout(ncol=2)` | (43.15, 10.96, 167.37, 174.15) ×4 | 同列 x/w、同行 y/h 全等 |
| `p1 \| p2`（7×5 in） | (38.26, 10.96, 205.81, 312.67)、(287.23, 10.96, 205.81, 312.67) | 同 y/h、x 递增 |
| 嵌套 `(p1 \| p2) / p3` | 上层 167.37、下层 377.89 | **跨层宽不同**（patchwork 已知行为） |

本仓字体度量与 R 不同，绝对 pt **不**逐值对拍；夹具记录的是这些**关系**，Python
侧断同一组关系（`tests/test_composition_r_parity.py`），并从我们自己的 SVG 里读回
panel 矩形验证渲染与表一致（容差 0.02pt）。

## 6. 已知差异 / 非范围

| 项 | 本实现 | patchwork | 去向 |
| --- | --- | --- | --- |
| 子图固定槽位（标题 / 轴 / 图例 / margin）的跨图统一 | 只统一 panel 几何；槽位按子图自身尺寸贴着 panel 摆 | 逐槽位取 max，标题在统一列里居中 | 视觉差异，留给后续 stage |
| `guides="collect"` / `guide_area()` | 未实现 | 有 | SIL-1002 |
| aplot 式 guide area / guide layout | 未实现 | aplot 独有 | SIL-1003 |
| `panel_spacing` / `insert_*` | 未实现 | aplot / patchwork 语法糖 | SIL-1004 |
| `&` / `-` / `design` / `area` / 重叠 / inset | 未实现 | 有 | 非本期 |
| `coord_fixed` 的 `respect` 矩阵 | 子图 panel 的绝对单位在表里保留并参与 max；组合表不设 `respect` | 逐格 respect | 组合层首期不做 |

`align_scales()` 的约束照旧：组合层要保证 tick 的页面坐标一致，调用方必须传
`expand="first"`（见 `docs/notes/align-scales.md` §4）；本实现不自动改写用户的
`expand`。

## 7. 性能与 IR 体积

4 / 9 个同构子图（200 点散点，7×7 in，3 列），`pixi run compose:report`：

| 子图数 | `gtable()`（构建 + resolve + 渲染树） | `to_scene()` | IR（CBOR） |
| --- | --- | --- | --- |
| 4（2 列） | 105 ms | 118 ms | 24,206 B |
| 9（3 列） | 217 ms | 245 ms | 54,332 B |

`gtable()` 是首次合并的完整成本（含每张子图的 `build_plot()` 与 grob 树）；重复
渲染同一组合时，`scene()` 的指令缓存（`ggcore.perf`）照常生效。IR 体积随子图数
线性增长，没有逐元素 JSON。
