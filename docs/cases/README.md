# 案例资产目录

一个案例 = 一份 plot 规格 + 一份参考图 + 一份自产基线。这是 `pixi run render` /
`pixi run diff` 的唯一输入目录。

## 布局

```
docs/cases/
├── <case-id>/
│   ├── case.json        # plot 规格（+ 语法方法链的形式，对标 ggplot2）
│   ├── expected/        # 上游 ggplot2 v4.0.3 的参考图，脚本拉取，不入库
│   └── baseline/        # 我们自己的基线图，入库，更新走 PR
└── <case-id>/current/   # 每次 render 的输出，不入库（.gitignore）
```

- `<case-id>` 用上游文档里的图名（`geom-bar/basic`、`scale/log10`），便于和上游
  快照对号。
- `case.json` 只写数据 + 映射 + 图层，不写渲染参数；渲染参数走默认值 + 覆盖项。
- 素材（CSV 等）放同目录，按需加载；不复制上游 `data/`。

## 现在有什么

目录先立起来，案例随渲染能力落地逐个加：`render` / `diff` 在 M0-1 是占位入口
（`pixi run render` 会显式报未实现并以退出码 3 退出），所以这里暂时没有案例。

## 口径

- 容差与纳管策略：`docs/notes/snapshot-policy.md`。
- 上游 pin：`docs/notes/upstream.md`。
- 加/改案例要同步 `docs/notes/upstream-map.md` 里对应的模块行。
