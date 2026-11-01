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
| `pixi run render` | 案例渲染入口（M0-1 占位，未实现时退出码 3） |
| `pixi run diff` | 案例比对入口（同上） |
| `pixi run gate:imports` | X1 · ggcore import 白名单 |
| `pixi run gate:ir-json` | X1 · IR 禁止逐元素 JSON |
| `pixi run gate:determinism` | X1 · 同输入同字节 |
| `pixi run upstream:diff` | X2 · 上游 `R/` 周 diff |
| `pixi run spike:*` | M-1 可行性实验，见 `docs/spike/README.md` |

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
  scene.py           # 占位 IR（真 IR 后续阶段落地）
  cli/               # render / diff 命令行入口
tools/gates/         # 横切门禁脚本（X1）
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
- 度量口径账本：`docs/notes/metrics-ledger.md`
