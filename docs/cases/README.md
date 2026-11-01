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

`render` / `diff` 仍是占位入口（`pixi run render` 显式报未实现、退出码 3），案例
随渲染能力落地逐个加。目前只有两套 **viewport 快照**（M0-4），规格字段
`"kind": "viewport"`，由 `tools/cases/viewport_cases.py` 直接读 `case.json` 画图：

| 目录 | 演示什么 |
| --- | --- |
| `viewport-nested-rotate/` | 三层嵌套视口，角度 15 / 25 / 50 累加成 90；native 曲线的映射；最内层 `clip="on"` 的裁剪框 |
| `viewport-clip/` | `clip` 三态对照：`inherit` 被父框截断、`off` 越界、`on` + 45° 退化成继承 |

```bash
pixi run cases:viewport          # 重画 baseline/viewport.png
pixi run cases:viewport --check  # 只和仓库里的 baseline 比对
```

这两套的 `case.json` 是给这个渲染器用的最小规格（步骤脚本 + 绘制原语，
见 `tools/cases/viewport_cases.py` 顶部表格），不是 M0-1 说的 plot 规格；
plot 规格随 `render` 实现落地后再定。

## 口径

- 容差与纳管策略：`docs/notes/snapshot-policy.md`。
- 上游 pin：`docs/notes/upstream.md`。
- 加/改案例要同步 `docs/notes/upstream-map.md` 里对应的模块行。
