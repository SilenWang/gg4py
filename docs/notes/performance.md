# 性能预算：降采样 / 度量缓存 / 增量重算（M3-5）

这张纸回答三件事：**10 万点的端到端是多少毫秒、量的是哪一段、慢的时候改哪一层**。
三条机制（降采样 / 度量缓存 / 增量重算）都在 `src/ggcore/perf.py` 里收口，没有在
几何、场景、IO 各自写一份。

## 1. 口径

「端到端」= 浏览器编辑器 worker 里跑的那一段，中间不换度量实现：

```
run_script(source)
  exec 用户代码            → ggplot 对象
  build_plot()            → 每层已算好的数据（aes / stat / position / scale）
  scene_from_plot()       → grob 树 → 扁平指令 → ir.Scene
  ir.encode()             → CBOR 字节（交给 TS 渲染器）
```

度量固定 `ggcore.metrics.fallback.default_metrics()`（`TableMetrics`）——浏览器里
没有 skia / HarfBuzz，桌面 skia 的 `ShaperMetrics` 不在这条路上（`docs/notes/pyodide.md`）。
**不含** TS 侧的 IR 解码 / DOM SVG 渲染与页面合成：那是另一条腿，数字在
`docs/notes/editor.md`（warm 重跑 ≤ 2 s 的口径包含它）。10 万点的 IR 只有 785 KiB，
DOM 侧真正的瓶颈是 10 万个 `<circle>`，与本文件的预算无关。

## 2. 实测（本机：linux-64，CPython 3.12.16，numpy 2.5.4，pixi 默认环境）

```bash
pixi run perf:100k          # 10 万点：cold / warm / 降采样 三组中位数
pixi run perf:100k --json   # 机器可读
pixi run perf:100k --check 300   # 预算门禁：cold 中位数 ≥ 300 ms 即非 0
```

数据：`rng.normal(size=n)` 的 x/y 两列，`geom_point()`，页面 5.0×3.5 in。

| 场景 | 前（`a449ad2`，M3-5 开工前） | 后 | 说明 |
| --- | --- | --- | --- |
| 10 万点 cold（首跑） | **810 ms**（build 800 + encode 0.8） | **203 ms**（build 199 + encode 0.6；5 次中位数，波动 ±3%） | 4.0×；两个数都在同一台机器、同一个脚本上取中位数 |
| 10 万点 warm（同内容重跑） | 810 ms | **57 ms** | 增量重算：图层绘制与场景指令全部命中 |
| 10 万点 + `max_points=20_000` | — | **79 ms** | 降采样打开（IR 从 785 KiB 降到 160 KiB） |
| 100 万点 cold | **8 433 ms**（build 8 396 + encode 3） | **2 183 ms**（build 2 149 + encode 4） | 3.9×；`build_plot` 是剩下的全部 |
| 100 万点 + `max_points=100_000` | — | **514 ms** | 降采样只约束绘制，见 §3 的边界 |

「前」的取法：`git checkout a449ad2`,同一段源码走 `ggcore.script.run_script`
（`/tmp` 里的探针，与 `tools/perf/bench_100k.py` 的 `_run_once` 同形状），取 3 次
中位数。缓存关掉的对照用 `pixi run perf:100k --no-cache`：10 万点 warm 会回到
177 ms，即缓存贡献的 120 ms。

拆开看 100 万点 cold 的 2.18 s：`build_plot` 2.15 s（逐行 aes / 标度 / 位置，全表
10 万×10 倍行数）、场景 0.03 s、编码 4 ms。所以**行数预算是 build 阶段的事**，
`max_points` 管不到——见 §3 末的边界。

## 3. 降采样

```python
p = ggplot(df, aes(x="x", y="y")) + geom_point(max_points=20_000)
```

- **缺省不降**（`max_points=None`）。ggplot2 的对等口径是「给多少点画多少点」，
  默认丢点是行为改变而不是优化；降采样是**显式**选择。
- 策略 `stride`：`round(linspace(0, n-1, max_points))` 去重后按行号取子集。
  确定性（无随机数，同一份数据每次同一张图，IR 才能逐字节比）、保持行序、
  对无序数据无偏；比「取前 N 行」在已排序数据上更不容易偏到一侧。
- **IR 语义不变**：还是同一个 `points` 节点、同样的节点序列，只是 `points` 缓冲
  行数变少（`tests/test_perf.py::test_max_points_only_changes_the_point_buffer`
  逐 kind 比节点序列）。快照 case 都没有 `max_points`，全量 515 条 case 的 IR
  sha256 与改动前逐条相同（见 §6）。
- 真的降了会给 `ggcore.perf.DownsampleWarning`（消息里写原行数与预算），
  不静默。
- 位置：`PointRenderer.draw()` 里对**本面板的行**取样（分面时预算按面板算），
  在 `npc_values()` 之前，所以后面的 grob 生成、单位换算、遍历、编码都只处理
  保留下来的行。

**边界**：降采样发生在绘制期。`build_plot()`（stat / 标度训练 / 位置调整）仍按
全表走，所以 100 万点开 `max_points` 也省不下那 2.1 s。真要在 100 万行上提速，
得在**数据层**先抽样（进 `ggplot()` 之前），那会改变标度范围与图例，属于产品
选择，不在这里偷偷做。

## 4. 度量缓存

两层，缺一不可：

1. `ggcore.metrics.MetricProvider` 的 LRU，键是 `(text, size, font_stack)`——
   同一段文字在同一份度量里只 shaping 一次（M0-7 已有，`benchmarks/test_metrics.py`
   守命中率）。
2. `ggcore.io.backend_metrics()`：**同一线程内复用一个后端度量实例**。
   之前 `_scene()` 每次调用 `_BACKEND.metrics()` 都新建一份 `ShaperMetrics`
   （连带新的 `TextShaper` 字形缓存），等于层 1 在每次 ggsave 时被清零。
   现在按线程缓存（`MetricProvider` 的缓存无锁，跨线程共用会互相踩），
   `reset_backend_metrics()` 可以主动丢弃。

读数字：`ggcore.perf.metric_cache_stats()` 给两份实例的
`entries / hits / misses / hit_rate`；`clear_metric_cache()` 清空（量冷启动用）。
浏览器路径的单例是 `default_metrics()`，编辑器重跑（同内容）不再走任何 shaping。

断言的形状（`tests/test_perf.py`）：第二张图 `misses` 不增长、`hits` 增长；
`clear_metric_cache()` 之后归零。

## 5. 增量重算

两级缓存，键都是**内容**（`blake2b-128` 指纹），不是对象 id：

| 级别 | 在哪 | 键 | 命中省掉什么 |
| --- | --- | --- | --- |
| 图层绘制 | `geom.scene._draw_layer()` | geom 名 + 面板号 + 图层数据指纹 + 图层参数指纹 + 面板参数指纹 + 主题指纹 | `geom.draw()`：10 万点要建 20 万个单位元素（约 120 ms） |
| 场景指令 | `grobs._Traverser._visit_leaf()` | grob 指纹 + 视口路径 + 页面仿射 + 裁剪框 + 生效 gpar | 单位换算 / 逐元素 gp 分组 / 文本度量解析（约 100 ms） |

两条命中的安全前提是同一件事：**内容相同 ⇒ 结果相同**。`geom.draw()` 只读
`build.data` / `build.params` / `metrics`（`src/ggcore/geom/*.py` 里没有别的字段
被读），`_resolve_*` 是纯函数，所以内容键直接对应结果。缓存里放的是不可变对象
（`frozen=True` 的 grob 与 `Instruction`），`to_node()` 之后仍然只读。
`tests/test_perf.py::test_cached_and_uncached_scenes_are_byte_identical`
用「开缓存 / 关缓存」两条路比 IR 字节做反向担保。

**什么会失效**（这是「改一行只重算受影响部分」的边界）：

- 改**数据** → 该图层的绘制与它的指令重算，别的图层照旧
  （`test_changing_one_layer_only_invalidates_that_layer`：两个图层改一个，
  只多 1 次命中 + 1 次未命中）。
- 改**图层参数**（`size` / `colour` / `max_points` …）→ 同上。
- 改**主题** → 所有图层重绘（主题是键的一部分，几何会读 `geom.<class>`）。
- 改**标题 / 图例文案导致面板位置或尺寸变化** → 面板视口变换进指令键，面板里的
  叶子全部重算（几何位置真的变了，不能复用）。文案不变只是内容变（同样行高）
  时仍然命中。
- 换**度量实例**（换后端 / `reset_backend_metrics()`）→ 全部重算。

容量与开关：图层绘制缓存 64 条 / 40 万行（存 grob，约 100 B/行），场景指令缓存
512 条 / 100 万行（存 float64 缓冲，约 16–32 B/行），LRU 按行数与条目数双向封顶
（`ggcore.perf.DEFAULT_*_CACHE_*`）。单条超过行数上限的图层不缓存（只重算，不占
内存）。关掉：`GG4PY_NO_SCENE_CACHE=1` 或 `ggcore.perf.disable_scene_cache()`——
实测「前 / 后」与排查「为什么复用了旧指令」都用它。命中率进
`ggcore.perf.cache_stats()`（`perf:100k` 会打印）。

## 6. 与快照的关系

- 容差一档没动：`docs/notes/snapshot-policy.md` 的 2% / 1% / `report` 5% 原样。
- 降采样缺省关闭，case 都不带 `max_points`；**515 条 case 的 IR sha256 与改动前
  逐条相同**（`PYTHONPATH=src pixi run python tools/gates/pyodide/run_cases.py`
  前后各跑一次，`cases[].sha256` 全等）。
- `pixi run check` 全绿（含 `gate:pyodide`、`gate:determinism`、`gate:libm-noise`
  与 `viewer:cases:ci`）。

## 7. 复现与排查

```bash
pixi run perf:100k                 # cold / warm / 降采样
pixi run perf:100k --no-cache      # 关缓存（「前」）
pixi run perf:100k --rows 1000000 --max-points 100000
pixi run perf:100k:check           # 预算门禁：cold ≥ 300 ms 即红
pixi run test -- -k perf           # 机制测试（不依赖时间的那些断言）
```

慢的时候先看 `cache_stats()`：`layers.hit_rate` 低说明图层输入真的变了，
`scene.hit_rate` 低但 `layers` 高说明版面（变换 / 裁剪）动了。两者都高而总时间仍
高，瓶颈就在 `build_plot`（逐行处理），此时该考虑数据层抽样，而不是继续加缓存。
