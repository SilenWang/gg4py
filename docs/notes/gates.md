# 横切门禁（X1 / X5）

四道门都是普通脚本，退出码可判定，既能在 `pixi run check` 里跑，也能单独跑。

| 任务 | 脚本 | 拦截什么 | 失败样例 |
| --- | --- | --- | --- |
| `pixi run gate:imports` | `tools/gates/check_import_whitelist.py` | `src/ggcore/` 里出现白名单外的 import | `import pandas` |
| `pixi run gate:ir-json` | `tools/gates/check_ir_json.py` | ggcore 里出现 JSON 序列化调用 | `json.dumps(scene)` |
| `pixi run gate:determinism` | `tools/gates/check_determinism.py` | 同输入序列化出不同字节 | 两个进程摘要不一致 |
| `pixi run gate:metrics` | `tools/gates/check_metrics.py` | 双端文本度量不一致（M0-7，X5） | CanvasKit 把整串按主字族排版 |

`pixi run check` = `lint` + `test` + 四道门。

## import 白名单

允许的顶层模块：

- 标准库（`sys.stdlib_module_names`，外加 `__future__`）
- `numpy`（计算内核）
- `cbor2`（IR 的二进制编码；目前未引入，先放行）
- `ggcore` 自身

其余一律失败，包括 pandas / pyarrow / polars / skia / matplotlib。理由：ggcore 是
Pyodide 里也要跑的纯 Python 内核，DataFrame-like 输入在边界处转成 IR，渲染后端在
包外。门禁只做 AST 扫描，不执行被检查的代码。

包外后端的两个例证：`ggshape`（HarfBuzz 形状后端，M0-7）与 `ggskia`
（PNG / SVG / PDF 设备，M0-8）。它们依赖 `uharfbuzz` / `skia-python`，协议留在
`ggcore`（`ggcore.metrics` / `ggcore.device`），实现与 CLI 在包外——所以内核
永远不需要加载 skia。

包内相对导入（`from .scene import Scene`）不越界，直接跳过。

动态导入（`importlib.import_module("pandas")`、`__import__("pandas")`，含
`import importlib as il` 的别名）同样拦：参数是字符串字面量时按同一份白名单判
定，不是字面量（`importlib.import_module(name)`）则直接失败——门禁离线核对不了它
到底导入了什么。

赋值别名与字面量取属性按同一条规则判：`f = importlib.import_module` 之后的
`f("pandas")`、`getattr(importlib, "import_module")("pandas")` 都拦；别名可以成
链（`g = f`），门禁迭代到不动点。

`.__call__` 不算「再间接一层」：`f.__call__(...)` 调用的就是 `f`，所以还原调用
目标时把尾部的 `.__call__` 剥掉（可连写 `f.__call__.__call__`），归约到同一条路径。
`f.__call__("pandas")`、`getattr(f, "__call__")("pandas")`、
`getattr(getattr(importlib, "import_module"), "__call__")("pandas")` 都在拦截范围内；
属性链（`importlib.import_module.__call__`）与 `g = f.__call__` 这类别名同样还原。

**保证范围**（AST 静态扫描，不是沙箱）：覆盖 `import` / `import … as` /
`from … import`、非字面量动态导入、赋值别名、`getattr(<可还原>, "字面量")`、
属性链与经 `.__call__` 的调用。
**不覆盖**再间接一层的写法——`operator.attrgetter("import_module")` 之后再调用、
`functools.partial`、`eval` / `exec` 里的代码、运行时拼接的属性名
（`getattr(importlib, name)`）、`importlib.__dict__[...]`。静态分析不可能完备，
这些属于 review 的职责；`tests/test_gates.py` 里的
`test_import_gate_documented_boundary_still_passes` 把这几类钉成“已知漏口”，
不假装它们被覆盖。

## IR 禁止逐元素 JSON

`src/ggcore/` 里禁止 `json.dumps` / `json.dump` / `json.JSONEncoder` /
`from json import dumps` / `orjson.dumps` / `.to_json()`。IR 的 bulk 数据必须是
float32 缓冲 + CBOR：314 份快照的规模下，逐元素 JSON 的体积与耗时都不达标。
需要 JSON 的地方（例如 web 端读取配置）放在包外。

模块别名算同一个东西：`import json as j` 之后 `j.dumps(...)` /
`j.JSONEncoder` 一样拦（`orjson` / `ujson` / `simplejson` / `rapidjson` 同理）。

## 同输入同字节

`check_determinism.py` 用三个不同 `PYTHONHASHSEED` 的解释器进程各编码一次真实
scene（`ggcore.ir.demo_scene()`：嵌套视口 + path + text + raster blob + zeroGrob），
比较 stdout（`digest` / `bytes`）。子进程同时自检 `encode(decode(data)) == data`，
所以“编码 + 解码”合起来也要字节稳定。同一进程内重复调用也在子进程里检查。

## 手测一次门禁是否真的会拦

```bash
printf 'import pandas\n' > src/ggcore/_probe.py
pixi run gate:imports          # 期望 exit 1，且报 src/ggcore/_probe.py:1
rm src/ggcore/_probe.py
```

违规样例的自动化版本在 `tests/test_gates.py`（种到 tmp 目录里跑真实脚本），所以
不需要靠“记得手测”来保证门禁还活着。

## 双端度量一致性（X5，M0-7）

`gate:metrics` 把 200 条冻结语料（`docs/spike/corpus/labels_200.json`）在四个字号
（10/12/16/24 px）下同时量四遍，判据如下：

| 腿 | 比较对象 | 判据 |
| --- | --- | --- |
| 双端 | `MetricProvider`（HarfBuzz）vs CanvasKit `SkParagraph`（node） | 逐标签相对差 < 0.5%，run 切分布局 0 不一致 |
| 桌面端 | skia-python 逐字形 advance vs HarfBuzz（同一 glyph id） | < 0.5% |
| 兜底表 | `TableBackend` vs HarfBuzz | run 切分 0 不一致；**声明支持**的文字 < 5%（仅对本 200 条冻结语料成立，见下） |
| 灵敏度 | 字体栈砍成单字族后的双端比较 | 必须判红（否则门禁失效） |
| 表新鲜度 | `tools/metrics/build_table.py --check` | 重新生成的表与提交的表逐字节相同 |

实测量级与口径推导见 `docs/notes/metrics-ledger.md` · M0-7。报告落在
`.gate-metrics/metrics_gate.json`（不入库）。

### 兜底表 5% 判据只对这份语料成立

3.59% 与 5% 这组数是**这份 200 条冻结语料上的测量结果**，不是兜底表的误差上界：

- 最差标签 `'#️⃣ Total'` 相对差 **3.5876%**，绝对差 **+2.71875 px @16px**（表偏宽）；
- 这 2.72 px 全部来自 `To` 字对的 kerning（兜底表不建模 kern）：单独量 `'To'`
  相对差 **16.14%**、`'Total'` **7.28%**，是标签前面约 38 px 的 emoji 前缀把标签级
  相对差稀释到 3.59%；
- 绝对值恒定：`'#️⃣ Total'`、`'🏳️‍🌈🏳️‍🌈 Total'`、`'Total: #️⃣ (40%)'` 的偏差都是
  +2.71875 px，只有相对差随标签变长而变小——**短 kerning 标签的相对误差可达 16%**，
  换一份语料 3.59% 立刻不成立。

结论不变：兜底表不是权威宽度，布局必须走渲染端实测（L1）；`MetricProvider.supports()`
为 False 时换引擎。

**为什么 skia 腿比逐字形而不是整段**：`SkFont.getWidths` 不做 kerning/ligature
shaping，整段比会把 kern 差算成实现差异（`Width` 的 `Wi` 能差 2%，阿拉伯文能差
30%）。桌面端的整段宽度来自 HarfBuzz（L2 的轮廓路径），skia 只负责字形。

### 手测一次门禁是否真的会拦

```bash
# 1) 关掉字族回退：让 run 切分只看主字族（等价于「只把整串丢给主字族」）
sed -i 's/for candidate in range(font_count):/for candidate in range(1):/' \
  src/ggcore/metrics/runs.py
pixi run gate:metrics        # 期望 exit 1：每档 132 条超阈 + 132 条 run-mismatch，最差 51.9%
git checkout src/ggcore/metrics/runs.py

# 2) 改一字节字体以外的数据，让兜底表过期（例如把 ascent +1），门禁应报 STALE
pixi run metrics:check-table # 期望 exit 1
pixi run metrics:table        # 重新生成

# 3) CanvasKit 资源没装时给出可执行的提示，而不是只有 node 的栈
mv node_modules /tmp/nm && pixi run python tools/gates/check_metrics.py
#   期望首行是：run `pixi run assets:canvaskit` first
mv /tmp/nm node_modules
```

第 1 种情况门禁自己也会自动验：每次运行都把字体栈砍成单字族再比一遍（灵敏度
自检）。`tests/test_metrics_gate.py` 另用合成数据守住比较逻辑本身。
