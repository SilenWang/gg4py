# CI 触发范围（SIL-835）

`.github/workflows/ci.yml` 的改动**没有**随本目录一起提交：当前仓库令牌没有
`workflow` scope，任何包含 `.github/workflows/**` 的 push 都会被拒。所以这里放的是
改好的全文（`ci.yml.proposed`）与说明，由人手动覆盖合入。

- `ci.yml.proposed` —— 改完的 workflow 全文，与现在的 `ci.yml` 只差两处（见下）。
- 合入成功后请删除 `ci.yml.proposed`，只保留本文件。

## 为什么

`ci.yml` 对**所有** `pull_request` 触发。改一行 README、加一张示例图也要跑
`pixi run check`（20 个依赖任务，含 Chromium 渲染对拍）和全量 `cases matrix`。
这是 CI 分钟消耗的大头，也是 PR 反馈慢的主因。

收窄的只有**触发范围**：三个 job 的内容、`pixi run check` 的依赖任务一个都没删。

## 改了什么

1. **`on.pull_request` 增加 `paths`**（30 行，含注释）。`push: branches: [main]` 与
   `workflow_dispatch` 原样保留——合入 main 之后仍然跑全量，只有 PR 才过滤。
2. **`cases-matrix` job 增加一个 `scope` step**（`id: scope`，跑 `git diff --name-only`
   判断改动是否可能影响渲染），并给该 job 原有的 5 个 step 加上 `if:`，让最慢的这个
   job 在没有 `src` / `docs/cases` / `tools` / `web` / pixi 改动时整段跳过。没有引入
   第三方 action。

`check (dev)` 与 `prod env stays clean` 两个 job **逐字未动**。

## 触发矩阵

| 改动（PR） | `check (dev)` | `prod env stays clean` | `cases matrix` |
| --- | --- | --- | --- |
| 纯 prose 文档（`docs/notes/ir.md` 等） | 不跑 | 不跑 | 不跑 |
| 根目录 `README.md` / `LICENSE` | 不跑 | 不跑 | 不跑 |
| 示例图（`docs/**` 下的非 case 图片） | 不跑 | 不跑 | 不跑 |
| `src/**` | 跑 | 跑 | 跑 |
| `docs/cases/**`（含 `expected.svg`、`matrix.md`） | 跑 | 跑 | 跑 |
| `pixi.toml` / `pixi.lock` | 跑 | 跑 | 跑 |
| `tests/**` | 跑 | 跑 | **跳过**（改了测试不改渲染产物） |
| `tools/**` / `web/**` / `.github/workflows/**` | 跑 | 跑 | 跑 |
| `docs/notes/snapshot-inventory.md` 等受门禁约束的生成物 | 跑 | 跑 | 跳过 |
| `docs/spike/**` | 跑 | 跑 | 跑 |

## 为什么 `docs/` 里还有例外

几个文件名字像文档，实际被 `pixi run check` 读取或校验；把它们排除掉，等于给「文档漂移」
开了一条绕过门禁的路（11-04 已经踩过一次）。依据是 `rg -n 'docs/' tools/ tests/ src/`，
不是拍脑袋：

| 路径 | 谁在读 |
| --- | --- |
| `docs/cases/**` | `cases:matrix:check`、`viewer:cases:ci`、`gate:pyodide`、`snapshots:check` 等一切渲染门禁；`plot.py` 同时被 `ruff check .` 管 |
| `docs/spike/corpus/labels_200.json` | `gate:metrics`（X5 双端度量语料）、`tests/test_corpus.py`、`tests/test_metrics.py` |
| `docs/spike/**` 其余 | `spike:e1:assets` → `gate:pyodide`；`tests/test_run_split_rules.py` 读 E2 的两份脚本；脚本本身被 ruff 管 |
| `docs/notes/snapshot-inventory.md` | `snapshots:report:check`（台账新鲜度）、`tests/test_snapshot_inventory.py` |
| `docs/notes/api-coverage.md` | `api:coverage:check`（文档新鲜度） |
| `docs/notes/theme.md` | `docs:theme:check`（派生区块新鲜度） |
| `docs/notes/upstream.md` | `tests/test_api_coverage.py` / `tests/test_snapshot_inventory.py` 校验 `- commit:` 行 |
| `docs/notes/extension.md` | `tests/test_extension.py` 直接执行文档里的代码块（doctest） |

对照：`docs/notes/snapshot-tiers.md` **没有**进例外——`tiers:check` 只校验 `meta.toml`
里声明的档位，不读这份生成物。将来若给它加新鲜度门禁，记得把它加进 `paths`。

## 怎么合入

1. 用有 `workflow` 权限的方式打开 `.github/workflows/ci.yml`：GitHub 网页编辑器直接改
   （仓库写权限即可），或用带 `workflow` scope 的令牌推送。
2. 用本目录的 `ci.yml.proposed` **全文覆盖**，不要手工摘抄——文件首行是同一个
   `# .github/workflows/ci.yml`，覆盖即可。
3. 提交信息：

   ```text
   ci: scope triggers to code and generated docs
   ```

4. 合入后删除 `docs/ci/ci.yml.proposed`（本文件保留）。

## 怎么验证

合入后的第一次 PR 就可以验收：

1. **改一个纯文档 PR**（`docs/notes/ir.md` 加一行）：PR 上**三个 job 全不出现**——
   workflow 根本没被触发。这是预期，不是配置错误。
2. **改 `src/` 的 PR**：三个 job 全跑，与现在完全一致（`check (dev)` 的 20 个依赖任务
   一个不少）。
3. **改 `docs/cases/<case>/expected.svg` 的 PR**：`check` 与 `cases matrix` 都跑，
   后者仍然执行 `pixi run cases:matrix` + `git diff --exit-code -- docs/cases/matrix.md`。
4. 补充一条：**只改 `tests/` 的 PR** 会跑 `check` + `prod-env`，但 `cases matrix`
   的 `scope` step 输出 `run=false`，job 显示 skipped（`::notice` 里会写明原因）。

本地校验 workflow 能解析（pixi 受管环境，不额外装东西）：

```bash
pixi exec --spec pyyaml --spec python=3.12 python -c \
  "import yaml; yaml.safe_load(open('docs/ci/ci.yml.proposed')); print('ok')"
```

## 风险：将来加分支保护会踩坑

现在仓库没有分支保护、没有 ruleset，所以 workflow 级 `paths` 不会造成死锁。

**一旦给 `main` 加分支保护、把某个 job 设为 required check**，workflow 级 `paths`
就会出问题：只改文档的 PR 根本不触发这个 workflow，于是 required check 永远停在
「Expected — Waiting for status to be reported」，PR 无法合并——没有红叉，也没有出路。

到那时必须换成「**常驻 gate job + 路径判断**」的写法：

- 去掉 workflow 级 `paths`，让 workflow 对所有 PR 触发；
- 新增一个几秒钟的 `gate` job（`runs-on: ubuntu-latest`，只做 `git diff` 判断），把
  **它**设为唯一的 required check；
- 真正重的 job 用 job 级 `if` 跳过——本文件里 `cases matrix` 的 `scope` step 就是这套
  写法的雏形，可以直接推广到 `check` 与 `prod-env`。

## 维护约定

新增/重命名任何「被 CI 读取的 `docs/` 文件」时，必须同时把它加进 `on.pull_request.paths`
的例外，否则那些门禁会静默失效。判断依据只有一条：它是否出现在 `pixi run check`（或
`~/.github/workflows/ci.yml` 里 `cases matrix`）读到的路径集合中，用
`rg -n 'docs/' tools/ tests/ src/` 核对，不要凭文件名猜。
