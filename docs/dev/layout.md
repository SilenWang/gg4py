# 仓库布局、环境与任务

这份文档承接原 `README.md` 里面向开发者的部分：目录职责、pixi 环境、全部任务。
读代码前先看这里；口径本身在 `docs/notes/*.md`，索引见 [`docs/README.md`](../README.md)。

## 1. 目录

```
pixi.toml            # 唯一依赖与任务声明（+ pixi.lock，入库）
pytest.ini           # src 布局：pythonpath = src
ruff.toml            # lint 规则（E/F/W/I/UP/B/RUF，行长 100）
src/ggcore/          # 语法核心，纯 Python + numpy（X1 门禁守着这条边界）
  ir/                # IR v0：节点类型表 + CBOR 编解码（docs/notes/ir.md）
  aes.py eval.py     # aes 表达式：解析 / 白名单求值 / 数据掩码（docs/notes/aes.md）
  data.py            # 列式表 ColumnTable / Column：三种输入的归一结果（docs/notes/data.md）
  build.py layer.py  # 图层流水线：ggplot + Layer → 每层已算好的数据（docs/notes/build.md）
  scales*.py palettes.py palette_data.py   # 标度与色板（docs/notes/scales.md）
  stat*.py           # stat：identity / bin / density / boxplot / smooth / 2D 族 …
  geom/              # geom 绘制：grob 生成、hjust/na.rm 契约（docs/notes/geom.md）
  position.py        # 位置调整：identity / stack / fill / dodge / jitter …（docs/notes/position.md）
  coord.py           # 坐标系：cartesian / fixed / flip / polar / radial / trans / sf / map
  facet.py           # 分面：null / wrap / grid（docs/notes/facet.md）
  guide.py axis*.py legend_draw.py         # 图例与主轴（docs/notes/guide.md）
  theme.py components.py                   # 主题、扩展基类（docs/notes/theme.md / extension.md）
  units.py           # grid::unit 对等单位系统（docs/notes/units.md）
  gtable.py          # 表格布局 + null 分配（docs/notes/gtable.md）
  viewport.py        # grid 视口栈：push/pop、变换、裁剪、gpar 继承（docs/notes/viewport.md）
  grobs.py           # grob 模型：18 个构造器 + 场景遍历 → IR（docs/notes/grobs.md）
  metrics/           # 文本度量：run 切分 + MetricProvider + 兜底表（docs/notes/metrics-ledger.md）
  device.py          # 设备协议：open / draw_scene / close（docs/notes/device.md）
  io.py              # ggsave / save_ir / export_ir_json：落盘编排（docs/notes/io.md）
  plot.py            # 公开命名空间：ggplot()、geom_*、stat_*、scale_*、theme_* 都在这里导出
  sf.py sf_stat.py   # 空间数据（docs/notes/sf.md）
src/ggio/            # 输入适配层：pandas / Arrow / dict → ColumnTable
src/gg4py/           # 面向用户的顶层入口：ggcore.plot 注册表的投影 + 惰性 ggsave（docs/notes/public-api.md）
src/ggshape/         # 形状后端（HarfBuzz），在 ggcore 之外：X1 白名单不允许 uharfbuzz
src/ggskia/          # skia 设备（PNG / SVG / PDF）与 render / ggsave 的 CLI
src/ggdiff/          # 差分：resvg 统一栅格 + 像素判据 + 报告
web/viewer/          # 浏览器查看器：TS + DOM SVG，零 wasm（docs/notes/viewer.md）
tools/gates/         # 横切门禁脚本（X1 / X5，见 docs/notes/gates.md）
tools/refs/          # R 侧参考值生成（units / gtable / viewport / 各 case 的 expected.svg）
tools/cases/         # 可视化快照渲染（viewport / grob / 设备冒烟 / 阈值分档）
tools/upstream/      # 上游快照纳管与清单（snapshots.toml、import_snapshot_cases.py）
tools/metrics/       # 兜底度量表生成 + CanvasKit 度量脚本（门禁复用）
tools/examples/      # 文档与验收用的 plot 模块（`ggsave` 的示例）
tools/audit/         # r-graph-gallery 35 图核对（docs/notes/gallery-audit.md）
tools/docs/          # 文档生成 / 校验（theme 派生区块、docs/guide 示例执行）
examples/            # 面向读者的示例：一图一目录，脚本 + PNG + SVG（docs/examples.md）
scripts/             # 出口复现件：exit_report.py / exit_report.R（同一张报告图）
benchmarks/          # pytest-benchmark 基线
tests/               # 单元测试 + 门禁自测
docs/guide/          # 用户指南：一页一个模块，代码块由 `docs:guide` 执行
docs/notes/          # 口径与对照表（索引：docs/README.md）
docs/cases/          # 案例资产（规格 / 参考图 / 基线，约定见 docs/cases/README.md）
docs/spike/          # M-1 可行性实验与结论
```

`src/` 布局没有引入构建后端：`pytest.ini` 的 `pythonpath = src` 与任务里的
`PYTHONPATH=src` 负责把包放上路径。要跑一段临时代码时用 `pixi run python -c ...`
之前先拼上 `PYTHONPATH=src`（例如 `PYTHONPATH=src pixi run python -c ...`）。

## 2. 环境

| 环境 | 内容 | 用途 |
| --- | --- | --- |
| `default` / `dev` | 运行期依赖 + pytest / pytest-benchmark / ruff / playwright / pandas / pyarrow | `pixi run check` 的解析对象 |
| `prod` | 只留运行期依赖（无 pytest、无 ruff、无 playwright） | 发布侧冒烟；CI 断言测试与 lint 工具没漏进来 |
| `refs` | R 4.5.3 + ggplot2 4.0.3 + svglite（独立 solve-group） | 生成上游参考值与参考图，CI 不装 R |

`default` / `dev` / `prod` 共用同一个 solve-group，锁文件里只有一套
numpy / skia 版本；只有包集合不同。

## 3. 任务

任务名一律 `pixi run <name>`；`refs:*` 要带 `-e refs`。全部任务都定义在
`pixi.toml` 的 `[tasks]` 里，这里是索引。

### 3.1 日常

| 任务 | 作用 |
| --- | --- |
| `check` | `lint` + `test` + 全部门禁 + 查看器对拍；CI 跑的就是它 |
| `lint` | `ruff check . && ruff format --check .` |
| `test` | `pytest`（`tests/`） |
| `bench` | pytest-benchmark 基线（`.benchmarks/`，不入库） |

### 3.2 出图与诊断

| 任务 | 作用 |
| --- | --- |
| `ggsave` | `<module:plot_fn> out.png\|svg\|pdf\|ir.cbor\|ir.json`，`--width/--height/--units/--dpi`（`docs/notes/io.md`） |
| `render` | `--scene <file.ggir.cbor> --out x.png\|svg\|pdf`，或 `render <case-dir> --format svg --out <case>/current` |
| `diff` | 参考图 × 实测图：图级差异 + 平均差异 + 热图 + `--json`（`docs/notes/diff.md`） |
| `ir:size` | 10k 点 path 的 IR vs 逐元素 JSON 体积（`docs/notes/ir.md`） |
| `examples:<slug>` | 重画 `examples/<slug>/` 的 PNG + SVG（`docs/examples.md`） |
| `perf:100k` | 10 万点端到端实测（cold / warm / 降采样 + 缓存命中率，`docs/notes/performance.md`） |
| `perf:100k:check` | 同上，但 cold 中位数 ≥ 300 ms 即非 0（预算门禁，不挂进 `check`） |

### 3.3 横切门禁（X1 / X5）

逐条口径见 [`docs/notes/gates.md`](../notes/gates.md)。

| 任务 | 拦截什么 |
| --- | --- |
| `gate:imports` | `src/ggcore/` 里出现白名单外的 import |
| `gate:contourpy-lazy` | contourpy 泄漏到非等值线路径 |
| `gate:ir-json` | ggcore 里出现逐元素 JSON 序列化 |
| `gate:determinism` | 同输入序列化出不同字节 |
| `gate:metrics` | 双端文本度量不一致（uharfbuzz × CanvasKit，X5） |
| `gate:pyodide` | CPython 与 Pyodide 的 plot→IR 字节不一致 |
| `gate:pyodide:selftest` | 负向对照：故意差 1 比特，门禁必须红 |
| `gate:cbor` | `_cbor` 与 cbor2 canonical 不等价 |
| `api:coverage:check` | v4.0.3 的 NAMESPACE 导出掉到 90% 以下，或有缺口没登记 |
| `snapshots:check` | 上游 311 份 SVG 快照有未处置条目，或已纳管 case 与上游不再逐字节相同 |
| `snapshots:report:check` | 清单没重生成，或三处口径对不上 |
| `tiers:check` | 某个 case 声明的容差超过它所在文本负载档位的上限 |

### 3.4 案例与快照

| 任务 | 作用 |
| --- | --- |
| `cases:viewport` | 重画 `docs/cases/viewport-*` 的 PNG 快照（`--check` 只比对） |
| `cases:grob` | 重画 `docs/cases/grob-*` 的 PNG 快照 |
| `cases:device` | 一张手搓图三路出图到 `docs/cases/device-smoke/current/` |
| `cases:coord` | 等比例验证：量面板像素宽高比，产物进 `.coord-aspect/`（不入库） |
| `cases:matrix` | 扫三文件 case，真跑 render + diff，写 `docs/cases/matrix.md` |
| `cases:matrix:check` | 只做静态校验：契约错或矩阵过期即非 0 |
| `snapshots:fetch` / `refresh` / `import` | 按 pin 拉上游快照、刷新清单、导入成 case |
| `snapshots:report` | 重写快照清单与 burndown（`docs/notes/snapshot-inventory.md`） |
| `tiers:measure` | 量 text_load / 墨量并重写 `docs/notes/snapshot-tiers.md` |
| `api:coverage` | 重写 `docs/notes/api-coverage.md` |
| `docs:theme` / `docs:theme:check` | 主题文档的两个派生区块（生成 / 守新鲜度） |
| `docs:guide` / `docs:guide:check` | 执行 `docs/guide/*.md` 的 Python 示例（逐块打印 / 只打汇总，挂在 `check` 里） |

### 3.5 浏览器查看器与 Pyodide

| 任务 | 作用 |
| --- | --- |
| `viewer:build` | 导字体 + `tsc` 编译 `web/viewer`（产物不入库） |
| `viewer:browsers` | 把 Chromium 装进仓库（`$HOME` 只读） |
| `viewer:sample` / `viewer:shot` | 生成手测场景 / 截图 |
| `viewer:cases` / `viewer:cases:ci` | case → IR → DOM SVG → 与 expected.svg 像素对拍；CI 跑 12 条 |
| `gallery:check` | 先 `viewer:cases` 生成 gallery，再逐条请求 gallery.html 的链接（含 scene IR）并核对卡片 ↔ case |
| `viewer:parity` / `viewer:parity:ci` | skia SVG 与 DOM SVG 两条腿的语义对拍（`docs/notes/viewer-parity.md`） |
| `spike:corpus` / `spike:e1` / `e2` / `e3` | M-1 可行性实验，见 `docs/spike/README.md` |
| `assets:canvaskit` / `spike:assets` | 取 CanvasKit（npm，wasm） |

### 3.6 R 参考值（`pixi run -e refs <task>`）

| 任务 | 生成什么 |
| --- | --- |
| `refs:cases` / `refs:viewer-cases` / `refs:gradient-cases` / `refs:matrix-cases` / `refs:date-default` | `docs/cases/*/expected.svg`（ggplot2 4.0.3 + svglite） |
| `refs:units` / `refs:gtable` / `refs:viewport` / `refs:device` / `refs:device-render` | grid 单位、gtable 行列尺寸、视口、曲线求值、设备级渲染夹具 |
| `refs:text` / `refs:build` / `refs:theme` / `refs:coord` / `refs:scales` | 文字度量、图层流水线、主题解析、坐标面板参数、标度与色板 |
| `refs:facet` / `refs:position` / `refs:geom` / `refs:guide` / `refs:guide-long` | 分面布局、位置调整、geom 绘制、guide 键与尺寸 |
| `refs:stat` / `refs:stat-longtail` | stat 的逐列值与端到端参考图 |

只在换 pin 或有意改口径时重跑；产物入库，CI 不装 R。

### 3.7 上游与度量

| 任务 | 作用 |
| --- | --- |
| `upstream:diff` | 上游 `R/` 周 diff（X2） |
| `metrics:table` / `metrics:check-table` | 重新生成 / 校验兜底度量表（M0-7） |
| `metrics:advance` | 现有 case 的 hinted vs linear/HarfBuzz 推进差 |
| `audit:gallery` | r-graph-gallery 35 图核对（只写 `.gallery-audit/`，不挂进 check） |
