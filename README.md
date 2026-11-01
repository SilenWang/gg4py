# gg4py

ggplot2 4.0.3 的 Python 对等复刻：语法核心（`ggcore`，纯 Python + numpy）可跑在
CPython 与浏览器（Pyodide）里，渲染后端在包外。

## 快速开始

依赖、任务、环境变量全在 `pixi.toml` 里，不要用 pip/npm 手动装东西。

```bash
pixi install          # 装 dev 环境（默认环境）
pixi run check        # lint + 测试 + 横切门禁，一条命令全绿
```

| 任务 | 作用 |
| --- | --- |
| `pixi run check` | `lint` + `test` + `gate:*`，CI 跑的就是它 |
| `pixi run lint` | `ruff check` + `ruff format --check` |
| `pixi run test` | `pytest`（`tests/`） |
| `pixi run bench` | pytest-benchmark 基线（`.benchmarks/`，不入库） |
| `pixi run render` | M0-8 · `--scene <file.ggir.cbor> --out x.png\|svg\|pdf` 出图 |
| `pixi run diff` | 案例比对入口（同上） |
| `pixi run ir:size` | 10k 点 path 的 IR vs 逐元素 JSON 体积（`docs/notes/ir.md` §10） |
| `pixi run gate:imports` | X1 · ggcore import 白名单 |
| `pixi run gate:ir-json` | X1 · IR 禁止逐元素 JSON |
| `pixi run gate:determinism` | X1 · 同输入同字节 |
| `pixi run gate:metrics` | X5 · 双端文本度量一致性（uharfbuzz × CanvasKit，M0-7） |
| `pixi run metrics:table` | M0-7 · 重新生成兜底度量表（改字体或规则后） |
| `pixi run metrics:check-table` | M0-7 · 校验兜底表与当前字体/规则一致 |
| `pixi run upstream:diff` | X2 · 上游 `R/` 周 diff |
| `pixi run cases:viewport` | M0-4 · 重画 `docs/cases/viewport-*` 的 PNG 快照（`--check` 只比对） |
| `pixi run cases:grob` | M0-6 · 重画 `docs/cases/grob-*` 的 PNG 快照（一种原语一张） |
| `pixi run cases:device` | M0-8 · 一张手搓图三路出图到 `docs/cases/device-smoke/current/`（`--check` 只验验收） |
| `pixi run spike:*` | M-1 可行性实验，见 `docs/spike/README.md` |
| `pixi run -e refs refs:units` | 用 R 4.5.3 重新生成 units 对拍夹具 |
| `pixi run -e refs refs:gtable` | 用 R 4.5.3 + gtable 0.3.6 重新生成 gtable 对拍夹具 |
| `pixi run -e refs refs:viewport` | 用 R 4.5.3 重新生成 viewport 对拍夹具 |
| `pixi run -e refs refs:device` | 用 R 4.5.3 重新生成 xspline / curve 对拍夹具 |

## 环境

- `default` / `dev`：运行期依赖 + pytest / pytest-benchmark / ruff / playwright
- `prod`：只留运行期依赖（无 pytest、无 ruff、无 playwright）

两个环境共用同一个 solve-group，锁文件里只有一套 numpy/skia 版本。CI 的
`prod-env` job 会断言测试与 lint 工具没有泄漏进 prod。

## 布局

```
pixi.toml            # 唯一依赖与任务声明（+ pixi.lock）
pytest.ini           # src 布局：pythonpath = src
src/ggcore/          # 语法核心，纯 Python + numpy（X1 门禁守着这条边界）
  ir/                # IR v0：节点类型表 + CBOR 编解码（docs/notes/ir.md）
  units.py           # grid::unit 对等单位系统（M0-3）
  gtable.py          # 表格布局 + null 分配（M0-5）
  viewport.py        # grid 视口栈：push/pop、变换、裁剪、gpar 继承（M0-4）
  grobs.py           # grob 模型：18 个构造器 + 场景遍历 → IR（M0-6）
  metrics/           # 文本度量：run 切分 + MetricProvider + 兜底表（M0-7）
  device.py          # 设备协议：open / draw_scene / close（M0-8）
  cli/               # diff 命令行入口（render 跟 skia 后端一起在包外）
src/ggshape/         # 形状后端（HarfBuzz），在 ggcore 之外：X1 白名单不允许 uharfbuzz
src/ggskia/          # skia 设备（PNG / SVG / PDF）与 `pixi run render`（M0-8）
tools/gates/         # 横切门禁脚本（X1）
tools/refs/          # R 侧参考值生成（units / gtable / viewport）
tools/cases/         # 可视化快照渲染（viewport 快照 M0-4 / grob 快照 M0-6）
tools/metrics/       # 兜底表生成 + CanvasKit 度量脚本（门禁复用）
tools/upstream_diff.py  # 上游 R/ 周 diff（X2）
benchmarks/          # pytest-benchmark 基线
tests/               # 单元测试 + 门禁自测
docs/notes/          # 口径与对照表：upstream / upstream-map / snapshot-policy / gates
docs/cases/          # 案例资产（规格 / 参考图 / 基线）
docs/spike/          # M-1 可行性实验与结论
```

`src/` 布局没有引入构建后端：`pytest.ini` 的 `pythonpath = src` 与任务里的
`PYTHONPATH=src` 负责把包放上路径。

## 口径文档

- 上游钉版与周 diff：`docs/notes/upstream.md`
- Python 模块 ↔ 上游 `file:line`：`docs/notes/upstream-map.md`
- 快照容差与参考图纳管：`docs/notes/snapshot-policy.md`
- 门禁口径：`docs/notes/gates.md`
- IR 口径（节点表 / blob / 版本 / 体积）：`docs/notes/ir.md`
- 度量口径账本：`docs/notes/metrics-ledger.md`
- 单位口径账本：`docs/notes/units.md`
- 表格布局口径账本：`docs/notes/gtable.md`
- 视口口径账本：`docs/notes/viewport.md`
- grob 口径账本：`docs/notes/grobs.md`
- 设备口径账本（pt/DPI、文字轮廓、pch 表、曲线求值）：`docs/notes/device.md`
