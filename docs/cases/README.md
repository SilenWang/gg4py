# 案例资产目录

一个 case = 一份 plot 定义 + 一份参考图 + 一份元数据。**新增 case 只需要放三个文件，
不改任何代码**：下一次 `pixi run cases:matrix` 会自动把它算进覆盖矩阵、案例清单和
CI 报告。

## 布局

```
docs/cases/
├── taxonomy.toml            # 覆盖矩阵的两条轴（族 / 特性），全仓一份
├── matrix.md                # 生成物：族 × 特性覆盖矩阵 + 清单 + 来源
├── <case-name>/             # 三文件 case（本文件的主角）
│   ├── plot.py              # 定义：build() 返回 plot 规格
│   ├── expected.svg         # 参考图（与 expected.png 二选一）
│   └── meta.toml            # 族、特性标签、容差、是否进 CI
├── <snapshot-case>/         # 历史快照（M0-4 / M0-6）：case.json + baseline/
└── <case-name>/current/     # 每次 render 的产物，不入库（.gitignore）
```

- `<case-name>` 用 `族-语义` 的短横线命名（`geom-point-basic`、`geom-bar-stacked`），
  全仓唯一；矩阵里直接用它定位。
- 历史快照目录（只有 `case.json`）不套三文件约定，由 `pixi run cases:viewport` /
  `pixi run cases:grob` 维护，只在矩阵的「其他来源」里登记。

## 三个文件

### `plot.py`：定义

模块级定义数据与映射，`build()` 返回一份 **plot 规格 dict**。M1-7 起有两种形态，
新 case 一律用第一种（走语法层与生产管线）：

```python
"""geom-point / discrete：离散 x + 分组着色。"""

from ggcore.plot import aes, geom_point, ggplot, scale_colour_discrete, theme_void
from ggio.frame import to_column_table

DATA = {"cls": ["a", "b", "c"], "y": [1.2, 2.4, 1.8], "g": ["p", "q", "p"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="y", colour="g"))
        + geom_point(size=3.2, shape=19)
        + scale_colour_discrete(values={"p": "#F8766D", "q": "#00BA38"})
        + theme_void()
    )
    return {"plot": p, "size": [4, 3]}
```

`{"plot": ggplot(...), "size": [...]}`：`plot` 必须是带非空 `layers` 的 ggplot 对象；
`build_scene()` 走 `build_plot()` + `ggcore.geom.scene.scene_from_plot()`，与
`pixi run render` 的生产路径完全相同。

M0-9 的最小适配层（只有老 case 用，`ggcore.plotspec` 直接画，不过语法层）：

```python
def build():
    return {
        "data": DATA,  # 必填：列名 → 数组
        "mapping": {"x": "x", "y": "y", "colour": "g"},  # 可选：aes 映射
        "layers": [{"geom": "point", "params": {"size": 2}}],  # 必填：非空
        "labels": {"title": "geom_point / basic"},  # 可选：其余键随便加
    }
```

`cases:matrix` 钉最小契约（再多的键都允许，留给 plot API 落地后扩展）：

| 键 | 必填 | 检查 |
| --- | --- | --- |
| `plot` | 二选一 | 带非空 `layers` 的 ggplot 对象（语法层形态） |
| `data` | 二选一 | 非空映射（DataFrame-like 也行）；不要在这里读文件 |
| `layers` | 二选一 | 非空数组，每项是 dict 且 `geom` 是非空字符串 |
| `mapping` | 否 | 若给，必须是 dict |
| `size` | 否 | `[宽 in, 高 in]`，缺省 `[4, 3]`（与 R 侧 `svglite(width=4, height=3)` 同纸） |
| `limits` | 否 | `{x = [lo, hi], y = [lo, hi]}`；缺省按数据范围加 ggplot2 的 5% 扩张 |
| `palette` | 否 | `{类别: "#RRGGBB"}`；`colour` / `fill` 映射到离散列时必须覆盖每个取值 |

`build()` 抛异常、返回非 dict、既没有 `plot` 也没有 `data` + `layers`，都会让该 case
在矩阵里标 `⛔ invalid` 并让 CI 红。适配层形态的 `size` / `limits` / `palette` 由
渲染期的 `ggcore.plotspec` 校验（语法层形态没有这三个键：尺寸写 `size`、标度写
`scale_*()`）；不合规时该 case 以 `render 退出 2` 判红，消息里带具体原因。

**适配层形态**当前支持的 `geom`（与 `tools/refs/cases_ref.R` 一一对应；语法层形态
支持注册表里的全部 29 个 geom）：

| geom | 参数 | R 侧等价物 |
| --- | --- | --- |
| `point` | `size_pt`（字号 pt，半径 = 0.375 × size_pt）、`alpha` | `geom_point(size = size_pt/.pt, stroke = 0)` |
| `bar` / `col` | `width`（数据单位）、`ymin` 映射 | `geom_col(width = …)` |
| `text` | `size_pt`、`hjust` / `vjust`（缺省 0.5） | `geom_text(size = size_pt/.pt, family = "Noto Sans CJK SC")` |
| `curve` | `curvature`、`angle`、`ncp`、`lwd`（pt） | `geom_curve(...)` |

颜色不做调色板推导：`palette` 写死，R 侧用同值的 `scale_*_manual()`。

### `expected.svg` / `expected.png`：参考

二选一，**必须有一个**。它是判定「我们画得像不像」的参考：

- 上游 ggplot2 v4.0.3 快照（`docs/notes/upstream.md` 钉的 commit）；
- 或 R + svglite 重新生成的参考（`pixi run -e refs refs:cases`，`tools/refs/cases_ref.R`）。

**`ci = true` 的 case 只能来自这两类外部来源**（`meta.source` 以 `upstream:` 或
`svglite:` 开头）；本仓库自录的 `source = "local"` 只允许配 `ci = false` 的探索
case——自录基线让「基线 == 当前输出」永远绿，等于没有判据（SIL-599 硬要求 1）。

参考图按 X4 的容差口径比对（`docs/notes/snapshot-policy.md`）。**所有 case 都按
像素比**：`expected.svg` 与 `expected.png` 都先由 resvg 光栅化成 PNG（72 dpi，
1 pt = 1 px）再比；渲染格式由 `expected.*` 的后缀决定，`tolerance.svg` 已删除
（写进 `meta.toml` 是契约错）。PNG 要有合法文件头，SVG 要有 XML 声明或 `<svg`
根——格式不对同样标 `⛔`。

### `meta.toml`：元数据

```toml
family = "geom-point"                 # 必填：矩阵的行
features = ["aes-mapping", "aes-grouping"]  # 必填：矩阵的列（可为空数组）
ci = true                             # 可选，缺省 true；false = 只登记，不跑 render/diff

title = "geom_point：基础散点 + 分组着色"   # 可选
source = "svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2)"  # ci = true 时必填且必须是外部来源
tolerance = { png = 0.02 }            # 可选：覆盖图级差异阈值（比例，[0, 1)）
notes = "…"                           # 可选：自由文本
```

- 必填只有 `family` / `features`；`ci` 可省略，**缺省 `true`**（照常进 render/diff）。
- **`ci = true` 时 `source` 必须以 `upstream:` / `svglite:` 开头**；缺省 `local` 只
  能和 `ci = false` 一起用（契约错会让 case 标 `⛔`）。
- `family` / `features` 的取值优先用 `taxonomy.toml` 里登记过的；没登记不会失败，
  矩阵会自动加行/列，并在「未登记的族 / 特性」一节点名。
- `ci = false` 用于「先登记、参考图后补」的草稿 case：矩阵里有它，CI 不跑它。
- `tolerance` 只认 `png`（所有 case 都按像素比）；它收紧的是**图级差异**上限，
  平均差异仍按 `docs/notes/snapshot-policy.md` 的 1%。
- 默认 2% 抓不住文字宽度这一级的偏差：文字类 case 要在 `tolerance` 里收紧
  （`geom-text-cjk` 用 `0.014`），理由与实测数字见 `docs/notes/snapshot-policy.md`
  §文字类 case。
- 未登记的键只报警告（不红），所以可以随手记 `notes`。

**忘写 `meta.toml` 不是「这个目录不存在」**：只要目录里有 `plot.py` 或 `expected.*`，
生成器就按半成品 case 收进来标 `⛔ invalid` 并让 CI 红（只有 `case.json` 的历史快照
目录除外）。

## 生成器：`pixi run cases:matrix`

```bash
pixi run cases:matrix            # 扫描 → 渲染/比对 → 写 matrix.md + 报告
pixi run cases:matrix --check    # 只校验 matrix.md 是否最新（CI 用）：
                                 # 不写矩阵 / 报告，也不跑 render/diff（隐含 --no-run）
pixi run cases:matrix --no-run   # 只做静态契约校验，不调 render / diff
pixi run cases:matrix --strict   # 把 pending（render/diff 未落地）也当失败
pixi run cases:matrix --summary  # 额外把短版本（≤60 行）打到 stdout，给 GHA step summary 用
pixi run cases:matrix --case geom-point-basic   # 只跑一个 case
```

产物分三类，生命周期不同：

| 产物 | 入库 | 内容 |
| --- | --- | --- |
| `docs/cases/matrix.md` | 是（生成物，`--check` 守新鲜度） | **静态**覆盖视图：族 × 特性、缺口、清单、来源 |
| `.cases-matrix/report.md` / `.json` | 否（`.gitignore`） | **运行时**结论：哪个 case 红、差多少、按族汇总、为什么待落地。**永远完整，不截断** |
| GHA step summary | —（CI 贴到 PR 页） | 报告（CI 目前直接贴 `report.md`）；想要 ≤60 行的短版本就用 `--summary` |

矩阵是静态的，只由仓库内容决定，所以能 `--check` 逐字节比对；红绿随渲染能力变化，
写进报告，由 CI 贴到 PR 的 step summary（失败 case 名同时以 `::error` 注解出现）。
族 × 特性的聚合视图只在 `matrix.md`（覆盖缺口、清单都在那里）；运行时报告给的是
红绿与「按族汇总」的 case 数 / 红数，并在开头直接指向 `matrix.md`。

`report.md` 不受行数限制：上游验收资产是 314 份 SVG，案例库必然超过几十个，按行数
截断会把逐 case 表和「需要修的 case」整节切掉，红名单就没人看得到。CI 的 publish
summary 步骤目前直接贴完整 `report.md`；需要 ≤60 行的短版本时用
`pixi run cases:matrix --summary`（`render_summary()`：结论 + 红名单，只截名单尾部并
指向完整报告）。

### 状态

| 状态 | 含义 | 红？ |
| --- | --- | --- |
| `✅ pass` | render + diff 都通过 | 否 |
| `❌ fail` | render 出错或 diff 超容差 | **是** |
| `⛔ invalid` | 三文件缺失（含**忘写 `meta.toml`** 的半成品）/ `meta.toml` 不合规 / `plot.py` 契约不满足 / 参考图格式不对 | **是** |
| `⏳ pending` | render / diff 报未实现（退出码 3） | 否（`--strict` 下是） |
| `⏭ skipped` | `meta.ci = false` 或 `--no-run` | 否 |

`pending` 不是「通过」：它表示 `pixi run render` / `pixi run diff` 报「未实现」
（退出码 3），矩阵什么都没比过。`report.md` / `--summary` 的结论因此写
**待落地（未判绿）**，`report.json` 的 `verdict` 是 `pending` 且 `ok = false`；
`--strict` 下直接计为失败，结论写红（SIL-644 S1 / S2）。

机读结论四态：`pass` / `empty`（0 个 case）/ `pending` / `fail`，`ok` 只在 `pass`
时为 true。下游脚本只看 `report.json`，不要解析人读文本。

## 接线点：render / diff

生成器**不另造命令**，只调用 `pixi.toml` 里已有的两个任务名：

```bash
# 渲染：退出码 0 = 写出产物；3 = 未实现；其余 = 失败
# 格式由 expected.* 的后缀决定（expected.svg → --format svg）
pixi run render <case-dir> --format <svg|png> --out <case-dir>/current

# 比对：退出码 0 = 通过；1 = 超容差；3 = 未实现；其余 = 失败
# --json 让矩阵稳定拿到两个百分比（不再截 stdout 末尾）
pixi run diff <case-dir> --report <case-dir>/current/diff_report.md --json [--tolerance <png 容差>]
```

这条契约只有一处实现（`tools/cases/matrix.py` 的 `TaskBackend`）。改入口参数时改
它一处即可。口径全文见 `docs/notes/diff.md`。

## 现在有什么

**七张带外部参考的基准图**（`ci = true`，来源全是 `svglite:`）：

| case | 演示什么 |
| --- | --- |
| `geom-point-basic/` | 25 个点的分组散点（`colour` 映射 + `palette`） |
| `geom-col-basic/` | 连续 x 上的四根柱子（宽度是数据单位） |
| `geom-text-cjk/` | 长中文标签（18 字左对齐 + 短标签，Noto Sans CJK SC）；文字宽度 +2% 会红，阈值按 case 收紧到 1.4% |
| `geom-curve-basic/` | 两条拐弯曲线；设备 curve 的 y 翻转镜像会让它红（SIL-636 回归） |
| `text-bold-italic/` | 同一字族的 regular / bold / italic / bold-italic 四个真实字面（可变字体 `wght` 轴） |
| `text-multiline/` | `\n` 三行标签 + 两行居中标签；行距 1.44 × fontsize、整块 vjust |
| `text-emoji/` | emoji 与中文/拉丁混排；矢量后端回落单色 Noto Emoji 轮廓 |

`pixi run cases:matrix` 对它们真跑 render + diff；`pixi run -e refs refs:cases`
重生成参考 SVG。正确实现全绿，人为平移 (2, 2) 像素则四张全红——数字与负向验证记录
见 `docs/notes/diff.md` §6。

### M1-15 首轮案例库（40 条）

M1-15 补的 40 条全部走语法层（`plot.py` 返回 `{"plot": ggplot(...) + ...}`），
参考图由 `pixi run -e refs refs:cases` 里的第二个脚本
`tools/refs/cases_battery_ref.R` 生成（与 `plot.py` 一一对应，改一边必须改另一边）。
按族：

| 族 | case |
| --- | --- |
| `geom-point` | `-discrete` / `-size` / `-alpha` / `-na` |
| `geom-line` | `-na` / `-width`（虚线） |
| `geom-path` | `-groups`（分组 + 保持行序） |
| `geom-bar` | `-dodge` / `-fill` / `-horizontal` |
| `geom-col` | `-horizontal` / `-dodge` / `-stack` |
| `geom-area` | `-stacked` / `-align`（x 不齐）/ `-single` |
| `geom-histogram` | `-bins` / `-binwidth` / `-horizontal` |
| `geom-boxplot` | `-outliers` / `-varwidth` / `-horizontal` |
| `geom-smooth` | `-default`（loess 默认口径）/ `-groups` / `-span` |
| `scale` | `x-log10` / `y-log10` / `-colour-default`（hue）/ `-colour-gradient` / `-limits-drop` |
| `facet` | `wrap-2x2` / `grid-ab` / `wrap-free-y` / `wrap-free-x` |
| `theme` | `grey` / `bw` / `classic` / `light` / `dark` / `linedraw` / `test` / `minimal` / `void` 各 `-basic`（同一份数据，只换主题） |
| `guide` | `legend-single` / `legend-merged`（colour + shape）/ `colourbar` |

SIL-723 在 M1 内结掉了 SIL-715 的 #1/#2/#3：这三条从 `ci = false` 翻成
`true`，61 条 case 现在全部进矩阵（“跳过”不是绿，只是不跑）：

| case | 原缺口 | 现状 | 图级 / 均值 |
| --- | --- | --- | --- |
| `theme-grey-basic` | `panel.grid.major/minor` 未绘制 | SIL-723 已修 | 1.87% / 0.16% |
| `theme-minimal-basic` | 同上（minimal 的视觉主体就是浅灰网格线） | SIL-723 已修 | 1.87% / 0.16% |
| `guide-colourbar` | 色条只覆盖断点色阶；细矩形在 resvg 下有白缝 | SIL-723 已修 | 1.74% / 0.31% |

另外两条**没有落地**的覆盖点（没有 case 目录，因为 R 侧给不出参考），同样归在
SIL-715（M2 缺口池）：

- **横向 `geom_area`**：ggplot2 4.0.3 的 `stat_align` 在 y 离散时输出 0 行，
  R 侧只能用 `coord_flip()` 表达同一张图。`coord_flip` 在 M2-1 已落地
  （`docs/notes/coord.md` §7，`coord-flip-*` 三条 case），但 R 侧的数据仍是
  「y 离散、stat_align 输出 0 行」。**M2-S2 结案口径**：上游
  `GeomArea$setup_params()` 与 `StatAlign$setup_params()` 都传
  `ambiguous = TRUE`，所以「没有 explicit `orientation` 时按列类型推断」对
  `area` **不成立**——横向面积在 R 里只能写 `orientation = "y"`（或
  `coord_flip()`）。补的 case 是 `geom-area-horizontal`（两侧同值，显式
  `orientation = "y"`、`stat = "identity"`），`tests/test_geom_r_parity.py` 的
  `area_horizontal` 逐列对拍；`tests/test_geom_longtail.py` 另钉了「不写
  orientation 时保持竖向」这一条上游规则。对应 **SIL-715 #4**。
- `geom_boxplot()` 的横向**自动探测**已接上：`stat_boxplot` 在
  `setup_params()` 里按列类型判 `flipped_aes`（y 离散、x 连续 → 横向），geom
  侧读同一列。新增 `geom-boxplot-horizontal-auto`（**两侧都不写**
  `orientation`），`boxplot_horizontal_auto` 逐列对拍。对应 **SIL-715 #5**。

### M2-1：coord 族（11 条）

参考图由 `tools/refs/coord_cases_ref.R` 生成（并入 `pixi run -e refs refs:cases`），
口径见 `docs/notes/coord.md`。全部 `ci = true`，几何（面板范围 / 角度 / 半径 /
次轴断点）另有 `tests/fixtures/coord_r_reference.json` 的逐值对拍。

| 族 | case |
| --- | --- |
| `coord` | `flip-points` / `flip-bar` / `trans-log10` / `trans-sqrt` / `equal` |
| `coord`（极坐标） | `polar-bar`（玫瑰图、munch 弧边）/ `polar-facet`（两块正圆面板）/ `polar-theta-y` |
| `coord`（径向） | `radial-partial`（半圆）/ `radial-inner`（内半径 0.3） |
| `coord`（次轴 / 近似投影） | `sec-axis`（右侧 `sec_axis(~ . * 2)`）/ `quickmap`（经纬度等距圆柱） |

### M2-S2：geom 长尾 A（18 条）

参考图由 `pixi run -e refs refs:geom` 生成（与 fixture 同一个脚本，`tools/refs/geom_ref.R`
的 M2-S2 段），全部 `ci = true`。逐列对拍在 `tests/test_geom_r_parity.py`（22 个新
case），定向断言在 `tests/test_geom_longtail.py`。

| 族 | case |
| --- | --- |
| 线段 | `segment-arrow`（两端闭合箭头）/ `curve-arrow`（弯曲 + 开口箭头）/ `spoke` |
| 参考线 | `abline-hline-vline`（一张图三条参考线 + 矩形底） |
| 矩形 / 位图 | `rect` / `tile`（默认 width/height = 1）/ `raster`（像素矩阵，`interpolate = FALSE`） |
| 多边形 | `polygon`（两个分组三角）/ `ribbon-outline`（`outline.type = "upper"`）/ `step` |
| 区间 | `errorbar` / `errorbarh`（横向）/ `linerange-pointrange` / `crossbar` |
| 标注 | `blank-rug`（`geom_blank` + `geom_rug(sides = "bl")`）/ `map`（最小可用） |
| 方向探测 | `boxplot-horizontal-auto`（不写 orientation，SIL-715 #5）/ `area-horizontal`（SIL-715 #4） |

历史快照（不计入 geom 矩阵）：

**viewport 快照**（M0-4）：规格字段 `"kind": "viewport"`，由
`tools/cases/viewport_cases.py` 直接读 `case.json` 画图：

| 目录 | 演示什么 |
| --- | --- |
| `viewport-nested-rotate/` | 三层嵌套视口，角度 15 / 25 / 50 累加成 90；native 曲线的映射；最内层 `clip="on"` 的裁剪框 |
| `viewport-clip/` | `clip` 三态对照：`inherit` 被父框截断、`off` 越界、`on` + 45° 退化成继承 |

```bash
pixi run cases:viewport          # 重画 baseline/viewport.png
pixi run cases:viewport --check  # 只和仓库里的 baseline 比对
```

**grob 快照**（M0-6）：规格字段 `"kind": "grob"`，一种原语一张，由
`tools/cases/grob_cases.py` 走 `grob → 场景遍历 → IR → 临时 skia 设备` 画图
（16 张：13 种可绘制原语各一张 `grob-rect` / `-circle` / `-lines` / `-segments` /
`-polyline` / `-polygon` / `-path` / `-points` / `-text` / `-raster` / `-xspline` /
`-bezier` / `-curve`，加 `-clip`（`clipPath`）、`-null`（`nullGrob` + gtable）与
`-text-rot`（视口旋转 + `rot` 的合成）。口径见 `docs/notes/grobs.md` §10。

`grob-text-rot` 是 SIL-634 的回归资产：`A`（视口 20° + `rot = 0`）与 `A'`
（无旋转视口 + `rot = 20`）必须同向，`B`（`rot = 40`）比它们再转 20°。

```bash
pixi run cases:grob               # 重画 docs/cases/grob-*/baseline/*.png
pixi run cases:grob --check       # 只和仓库里的 baseline 比对
pixi run cases:grob --case grob-text
```

**设备三路冒烟图**（M0-8）：没有 `case.json`，图在
`tools/cases/device_cases.py` 里用 grob 直接搭（矩形 + 折线 + 中文标签 + 旋转
视口里的文字），三路产物写到 `device-smoke/current/`。`pixi run cases:device`
写文件，`--check` 只验验收条目（PDF 无 `/Font`、SVG 含 `<path>`、CJK 转轮廓）。

这两类 `case.json` 是给各自的渲染器用的最小规格（视口脚本 / grob 规格树），
不是 M0-1 说的 plot 规格；plot 规格随语法层落地后再定。单一 IR 场景的渲染走
`pixi run render --scene <file.ggir.cbor> --out x.png|svg|pdf`（`docs/notes/device.md`）。

## 口径

- 容差与纳管策略：`docs/notes/snapshot-policy.md`。
- 上游 pin：`docs/notes/upstream.md`。
- 模块 ↔ 上游对照：`docs/notes/upstream-map.md`（加/改案例要同步对应模块行）。
- 矩阵的两条轴：`taxonomy.toml`（不登记不失败，但会点名）。
- 设备口径（页面尺寸、DPI、文字轮廓）：`docs/notes/device.md`。
