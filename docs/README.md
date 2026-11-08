# 文档索引

主 README 只讲「这是什么、怎么装、跑第一张图、长什么样」。实现口径、门禁、对拍
账本都在这里。**标了「生成物」的文件不要手改**——改它的输入再跑对应任务。

## 0. 使用指南（[`guide/`](guide/index.md)）

面向使用者：一页一个模块，**每段代码都能跑**（`pixi run docs:guide` 逐块执行）。

| 文档 | 内容 |
| --- | --- |
| [`guide/index.md`](guide/index.md) | 索引、十分钟上手、文档门禁 |
| [`guide/r-to-python.md`](guide/r-to-python.md) | R → Python 对照表（geom / stat / scale / 参数 / 第三方扩展等价写法） |
| [`guide/browser.md`](guide/browser.md) | 在浏览器编辑器里写 ggcore 代码：脚本契约、数据面板、导出 |
| 模块页 | `aes` / `data` / `layers` / `geom` / `stat` / `position` / `scale` / `coord` / `facet` / `guide` / `theme` / `annotation` / `sf` / `export` |

## 1. 先读这几份

| 文档 | 内容 |
| --- | --- |
| [`dev/layout.md`](dev/layout.md) | 目录职责、pixi 环境、全部任务索引（原 README 的开发部分） |
| [`examples.md`](examples.md) | `examples/` 的六张参考图：做了什么、跳过了什么、缺口归口 |
| [`notes/gates.md`](notes/gates.md) | 横切门禁 X1 / X5：`pixi run check` 由什么组成、每道门拦什么 |
| [`notes/upstream.md`](notes/upstream.md) | 上游钉版（ggplot2 4.0.3 @ `cc1444c1`）与周 diff 口径 |
| [`notes/upstream-map.md`](notes/upstream-map.md) | Python 模块 ↔ 上游 `file:line` 对照 |
| [`notes/extension.md`](notes/extension.md) | 写一个自定义 geom / stat / scale：组件类怎么写、布局不用碰 |

## 2. 语法核心（`ggcore`）

| 文档 | 内容 |
| --- | --- |
| [`notes/aes.md`](notes/aes.md) | aes 表达式：解析、白名单求值、数据掩码、自动分组 |
| [`notes/data.md`](notes/data.md) | 三种输入（pandas / Arrow / dict）→ 一张列式表；dtype、分类顺序、时间、缺失 |
| [`notes/build.md`](notes/build.md) | 图层流水线：`ggplot` + `Layer` → 每层已算好的数据 |
| [`notes/scales.md`](notes/scales.md) | 标度：limits / expand / breaks / labels / map，色板与渐变 |
| [`notes/stat.md`](notes/stat.md) | stat：bin / count / boxplot / smooth / density / 2D 族 … |
| [`notes/geom.md`](notes/geom.md) | geom 绘制：grob 生成、`handle_na` / `setup_data` / `setup_params` 契约 |
| [`notes/position.md`](notes/position.md) | 位置调整：identity / stack / fill / dodge / dodge2 / jitter / nudge |
| [`notes/coord.md`](notes/coord.md) | 坐标：面板范围、expand、clip、等比例、极坐标 |
| [`notes/facet.md`](notes/facet.md) | 分面：`facet_null` / `facet_wrap` / `facet_grid` 的布局与标度 |
| [`notes/guide.md`](notes/guide.md) | 图例与主轴：legend / colourbar / bins / axis guide |
| [`notes/theme.md`](notes/theme.md) | 主题：元素树、继承、`rel()`、四套内置主题的逐元素解析值 |
| [`notes/sf.md`](notes/sf.md) | 空间数据：`geom_sf` 族 / `stat_sf` / `coord_sf` / `coord_map` |

## 3. 渲染与设备

| 文档 | 内容 |
| --- | --- |
| [`notes/ir.md`](notes/ir.md) | IR v0：节点类型表、blob、版本、体积 |
| [`notes/io.md`](notes/io.md) | `ggsave`：单位、缺省值、三路设备差异、IR 与 JSON 视图 |
| [`notes/device.md`](notes/device.md) | 设备接口与 skia 三路出图：pt/DPI、文字轮廓、pch 表、曲线求值 |
| [`notes/diff.md`](notes/diff.md) | 差分管线：R 参考、resvg 统一栅格、判据、JSON 契约 |
| [`notes/grobs.md`](notes/grobs.md) | grob 模型与场景遍历（18 个构造器 → IR） |
| [`notes/viewport.md`](notes/viewport.md) | 视口栈：push/pop、仿射变换、裁剪、gpar 继承 |
| [`notes/gtable.md`](notes/gtable.md) | 表格布局与 null 分配（行高列宽怎么定） |
| [`notes/units.md`](notes/units.md) | `grid::unit` 对等单位系统 |
| [`notes/metrics-ledger.md`](notes/metrics-ledger.md) | 度量账本：两端 / 两实现之间的差异决定 |

## 4. 门禁、跨端与结论

| 文档 | 内容 |
| --- | --- |
| [`notes/performance.md`](notes/performance.md) | 性能预算：降采样 / 度量缓存 / 增量重算，10 万点端到端口径与实测（M3-5） |
| [`notes/pyodide.md`](notes/pyodide.md) | CPython 与 Pyodide 的 plot→IR 逐字节一致（M0-10） |
| [`notes/viewer.md`](notes/viewer.md) | 浏览器查看器：IR → DOM SVG，零 wasm |
| [`notes/gallery.md`](notes/gallery.md) | 画廊的三种看法：静态 gallery（`viewer:gallery`，不要 Chromium）/ 本地服务 / 像素验证 |
| [`notes/editor.md`](notes/editor.md) | 浏览器代码编辑器：CodeMirror + Pyodide 执行 + 导出（M3-4） |
| [`notes/viewer-parity.md`](notes/viewer-parity.md) | 两条渲染腿的语义对拍（生成物：`pixi run viewer:parity`） |
| [`notes/gallery-audit.md`](notes/gallery-audit.md) | r-graph-gallery 35 图人工核对与逐张归因 |

## 5. 快照与覆盖率

| 文档 | 内容 |
| --- | --- |
| [`notes/snapshot-policy.md`](notes/snapshot-policy.md) | 快照容差与参考图纳管（三类资产不能混用容差） |
| [`notes/snapshot-inventory.md`](notes/snapshot-inventory.md) | 上游 311 份 SVG 快照清单与 burndown（生成物：`pixi run snapshots:report`） |
| [`notes/snapshot-tiers.md`](notes/snapshot-tiers.md) | 阈值分档（生成物：`pixi run tiers:measure`） |
| [`notes/snapshot-closeout.md`](notes/snapshot-closeout.md) | M2 缺口收口的分组推进计划 |
| [`notes/closeout.md`](notes/closeout.md) | **总收尾账（SIL-865）**：已交付 / 已知缺陷（接受）/ 刻意不做 / 仍缺（指向任务），含 SIL-715 28 条逐条状态 |
| [`notes/api-coverage.md`](notes/api-coverage.md) | v4.0.3 NAMESPACE 的 API 覆盖率与缺口（生成物：`pixi run api:coverage`） |
| [`notes/licenses.md`](notes/licenses.md) | 许可与第三方资产盘点 |

## 6. 案例资产与实验

| 文档 | 内容 |
| --- | --- |
| [`cases/README.md`](cases/README.md) | 案例目录的三文件约定（`plot.py` / `meta.toml` / `expected.svg`） |
| [`cases/matrix.md`](cases/matrix.md) | 案例覆盖矩阵（生成物：`pixi run cases:matrix`） |
| [`spike/README.md`](spike/README.md) | M-1 可行性实验（E1 冷启动 / E2 度量 / E3 导出）与结论 |
