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

模块级定义数据与映射，`build()` 返回一份 **plot 规格 dict**：

```python
"""geom-point / basic：两列数值 + 一列分组。"""

DATA = {
    "x": [1, 2, 3, 4, 5],
    "y": [2.3, 4.1, 3.7, 5.2, 6.0],
    "g": ["a", "a", "b", "b", "b"],
}


def build():
    return {
        "data": DATA,  # 必填：列名 → 数组
        "mapping": {"x": "x", "y": "y", "colour": "g"},  # 可选：aes 映射
        "layers": [{"geom": "point", "params": {"size": 2}}],  # 必填：非空
        "labels": {"title": "geom_point / basic"},  # 可选：其余键随便加
    }
```

`cases:matrix` 只钉最小契约（再多的键都允许，留给 plot API 落地后扩展）：

| 键 | 必填 | 检查 |
| --- | --- | --- |
| `data` | 是 | 非空映射（DataFrame-like 也行）；不要在这里读文件 |
| `layers` | 是 | 非空数组，每项是 dict 且 `geom` 是非空字符串 |
| `mapping` | 否 | 若给，必须是 dict |

`build()` 抛异常、返回非 dict、缺 `data` / `layers` 都会让该 case 在矩阵里标 `⛔
invalid` 并让 CI 红。

### `expected.svg` / `expected.png`：参考

二选一，**必须有一个**。它是判定「我们画得像不像」的参考：

- 上游 ggplot2 v4.0.3 快照（`docs/notes/upstream.md` 钉的 commit）；
- 或 R + svglite 重新生成的参考（M0-9 的产线）；
- 或本仓库已人工核过、作为该 case 判据的基线。

参考图按 X4 的容差口径比对（`docs/notes/snapshot-policy.md`）。PNG 要有合法文件头，
SVG 要有 XML 声明或 `<svg` 根——格式不对同样标 `⛔`。

### `meta.toml`：元数据

```toml
family = "geom-point"                 # 必填：矩阵的行
features = ["aes-mapping", "aes-grouping"]  # 必填：矩阵的列（可为空数组）
ci = true                             # 可选，缺省 true；false = 只登记，不跑 render/diff

title = "geom_point：基础散点 + 分组着色"   # 可选
source = "upstream:ggplot2 v4.0.3 tests/testthat/_snaps/geom-point"  # 可选，缺省 local
tolerance = { png = 0.001 }           # 可选：覆盖 X4 默认容差（比例，[0, 1)）
notes = "…"                           # 可选：自由文本
```

- 必填只有 `family` / `features`；`ci` 可省略，**缺省 `true`**（照常进 render/diff）。
- `family` / `features` 的取值优先用 `taxonomy.toml` 里登记过的；没登记不会失败，
  矩阵会自动加行/列，并在「未登记的族 / 特性」一节点名。
- `ci = false` 用于「先登记、参考图后补」的草稿 case：矩阵里有它，CI 不跑它。
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

`pending` 不是「通过」：它表示 M0-8（`pixi run render`）/ M0-9（`pixi run diff`）
还没落地。两个入口落地后矩阵自动转真跑，不需要改本工具。

## 接线点：render / diff

生成器**不另造命令**，只调用 `pixi.toml` 里已有的两个任务名：

```bash
# 渲染：退出码 0 = 写出 PNG；3 = 未实现；其余 = 失败
pixi run render <case-dir> --format png --out <case-dir>/current

# 比对：退出码 0 = 通过；1 = 超容差；3 = 未实现；其余 = 失败
pixi run diff <case-dir> --report <case-dir>/current/diff_report.md --tolerance <png 容差>
```

这条契约只有一处实现（`tools/cases/matrix.py` 的 `TaskBackend`）。M0-8 / M0-9 改
入口参数时改它一处即可。

> **已知缺口（交给 SIL-599 差分管线定案，本阶段不生效）**：`TaskBackend` 目前固定
> `--format png`、只传 `tolerance.png`，而 `meta.toml` 接受 `tolerance.svg`、本文件
> 也允许 `expected.svg`——所以 **SVG 的文本级容差现在永远不会生效**。定案前不要把
> `tolerance.svg` 当判据：要么按 `expected.*` 后缀选格式，要么删掉 `tolerance.svg`
> 并明确全部按像素比。
>
> 同一条线上还有来源问题：`ci = true` 的 case 目前仍允许 `source = local`（本仓库
> 自录基线），等于让「基线自己录、自洽快照永远绿」的洞留在 CI 里。SIL-599 的硬要求
> 是 `ci = true` 的 case 必须 `source` 非 `local`；闸门随 M0-9 一起打开。

## 现在有什么

`render` / `diff` 仍是占位入口（`pixi run render` 显式报未实现、退出码 3），所以
三文件 case 目前全部是 `⏳ pending`；矩阵的骨架、缺口视图与 CI 报告已经可用。

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

## 口径

- 容差与纳管策略：`docs/notes/snapshot-policy.md`。
- 上游 pin：`docs/notes/upstream.md`。
- 模块 ↔ 上游对照：`docs/notes/upstream-map.md`（加/改案例要同步对应模块行）。
- 矩阵的两条轴：`taxonomy.toml`（不登记不失败，但会点名）。
