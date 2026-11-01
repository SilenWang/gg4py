# 上游钉版（X2）

参考实现只认一个 commit。所有 `R/` 的文件与行号、SVG 快照、测试基线都以它为
准；`docs/notes/upstream-map.md` 里的 `file:line` 只对这个 commit 有效。

- repo: tidyverse/ggplot2
- tag: `v4.0.3`
- commit: cc1444c10edb87650fbe0cb31d56f0da1a255634
- 参考资产：上游 314 份 SVG 快照 + 146 个测试
- 取数校验：`git ls-remote https://github.com/tidyverse/ggplot2.git 'refs/tags/v4.0.3*'`

## 为什么钉 commit 而不是 tag

`v4.0.3` 是 lightweight tag（`git ls-remote` 直接给出 commit），没有 tag 对象可
校验；tag 名可以被移动，commit 不会。升级只发生在“换 pin”这一个动作里。

## 周 diff `R/`

入口是 `pixi run upstream:diff`（`tools/upstream_diff.py`），基线从本文件的
`- commit:` 行读，不需要额外参数：

```bash
# 默认：GitHub compare API（GITHUB_TOKEN / GH_TOKEN 可选，未认证也能跑但受速率限制）
pixi run upstream:diff

# 落成报表，方便贴进 issue / PR
pixi run upstream:diff -- --ref main --output docs/notes/upstream-diff-$(date +%Y%m%d).md

# 离线：本地 clone 一份 ggplot2 后直接 git diff
pixi run upstream:diff -- --repo-dir ../ggplot2
```

报表按语法分层（geom / stat / scale / coord / facet / guide / annotation /
theme / position / core）分组，只看 `R/`，`tests/`、`man/`、`NEWS.md` 不列。

## 判读口径

| 变更 | 处理 |
| --- | --- |
| `R/` 中我们已实现的文件 | 记为差异项，进 PR 或记 `docs/notes/metrics-ledger.md` |
| 新增 `R/geom-*.R` 等语法文件 | 排进后续阶段，本阶段不追 |
| 只改文档 / 测试 / vignette | 不跟 |

周 diff 的结论不直接改验收标准：验收标准在父任务里，口径调整走 issue。

## 升级流程

1. 换 pin：更新本文件的 tag + commit 两行，PR 标题写清“上游 4.0.x → 4.0.y”。
2. 跑 `pixi run upstream:diff -- --repo-dir <新 clone>`，把报表作为 PR 附件。
3. 用新 commit 复核 `docs/notes/upstream-map.md` 的行号（行号会漂）。
4. 参考快照按 `docs/notes/snapshot-policy.md` 重新纳管，旧基线同 PR 里删掉。
