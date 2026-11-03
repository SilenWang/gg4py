# 横切门禁（X1 / X5）

几道门都是普通脚本，退出码可判定，既能在 `pixi run check` 里跑，也能单独跑。

| 任务 | 脚本 | 拦截什么 | 失败样例 |
| --- | --- | --- | --- |
| `pixi run gate:imports` | `tools/gates/check_import_whitelist.py` | `src/ggcore/` 里出现白名单外的 import | `import pandas` |
| `pixi run gate:contourpy-lazy` | `tools/gates/check_contourpy_lazy.py` | 非等值线的 2D stat 依赖 contourpy（缺包就炸） | `bin_2d` 在缺 contourpy 时 `ImportError` |
| `pixi run gate:ir-json` | `tools/gates/check_ir_json.py` | ggcore 里出现 JSON 序列化调用 | `json.dumps(scene)` |
| `pixi run gate:determinism` | `tools/gates/check_determinism.py` | 同输入序列化出不同字节 | 两个进程摘要不一致 |
| `pixi run gate:metrics` | `tools/gates/check_metrics.py` | 双端文本度量不一致（M0-7，X5） | CanvasKit 把整串按主字族排版 |
| `pixi run gate:pyodide` | `tools/gates/check_pyodide_ir.py` | CPython 与 Pyodide 的 IR 字节不一致（M0-10） | 两个 CBOR 实现写出的字节不同 |
| `pixi run gate:cbor` | `tools/gates/check_cbor_diff.py` | `_cbor` 与 `cbor2` canonical 不等价（M0-10/SIL-646） | NaN 不归一成 `f97e00`、长度头写错 |

`pixi run check` = `lint` + `test` + 几道门全部。

### X5 只有一个含义：双端度量一致性

X5 指的就是上表第 4 行（`gate:metrics`）：HarfBuzz 与 CanvasKit 对同一串标签
量出来的 advance 必须一致（细节见本文末「双端度量一致性」）。

**「新原语必须带 case」不是 X5。** 那条要求住在案例库：`docs/cases/` 的覆盖
矩阵（M0-11 生成器）加 `pixi run cases:*` 的快照。两层都写清是因为父任务曾按
「X5」指后者——名字一样、守的东西不一样，于是有人去 `check_metrics.py` 里找
「新原语」的检查，找不到还以为门禁漏了。

## import 白名单

允许的顶层模块：

- 标准库（`sys.stdlib_module_names`，外加 `__future__`）
- `numpy`（计算内核）
- `cbor2`（IR 的二进制编码；目前未引入，先放行）
- `contourpy`（等值线 / 等值带的 marching-squares 内核，M2-6 起；见下节）
- `ggcore` 自身

其余一律失败，包括 pandas / pyarrow / polars / skia / matplotlib。理由：ggcore 是
Pyodide 里也要跑的纯 Python 内核，DataFrame-like 输入在边界处转成 IR，渲染后端在
包外。门禁只做 AST 扫描，不执行被检查的代码。

### 为什么放行 contourpy（M2-6）

`stat_contour` / `stat_contour_filled` / `stat_density_2d` 的等值线要在
`ggcore` 里算（它属于 stat，不是设备）。上游用 `isoband`，M2 排期已定用
`contourpy`：纯 C++ 扩展 + numpy，无绘图库依赖，能在 Pyodide 里装。

- **依赖声明**：`pixi.toml` 的 `[pypi-dependencies]` 声明 `contourpy = ">=1.3.3, <1.4"`
  （`pixi add --pypi contourpy`），`pixi.lock` 一并提交。上界 `<1.4` 是**版本对齐**
  而不是保守：浏览器侧 pin 的 `pyodide@314.0.7` 只提供 contourpy **1.3.3** 的 wasm
  轮子（PyPI 的 contourpy 不发布 wasm 构建），桌面端如果解析到 1.4，两边就是两套
  marching-squares 实现——「CPython 上对拍的几何」证明不了浏览器里的几何。见
  SIL-758。
- **Pyodide 可用性**：`pyodide@314.0.7` 的包索引里有 `contourpy` **1.3.3**
  （`contourpy-1.3.3-cp314-cp314-pyemscripten_2026_0_wasm32.whl`），浏览器端走
  `loadPackage("contourpy")` 从本地目录装，不需要退回自实现 marching squares。
  复核命令打印的是**版本**，不是包名出现次数：

  ```bash
  # 本地 staged 的那份索引（`pixi run spike:e1:assets` 从 npm pyodide@314.0.7 取，
  # sha256 记在 static/manifest.json）：打印版本 + 轮子文件名。
  pixi run python -c "import json; p=json.load(open('docs/spike/e1_coldstart/static/pyodide/pyodide-lock.json'))['packages']['contourpy']; print(p['version'], p['file_name'])"
  # 同一条口径对 CDN 上的 v314.0.7 交叉核对（联网时用）：
  curl -sS https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide-lock.json \
    | pixi run python -c "import json,sys; p=json.load(sys.stdin)['packages']['contourpy']; print(p['version'], p['file_name'])"
  ```

  1.3.3 上本实现依赖的行为已实测一致：`contour_generator(..., name="serial",
  corner_mask=False)` 的 `line_type = Separate`、`fill_type = OuterOffset`（`filled()`
  的缺省填充类型）与 1.4.0 相同，三张网格（线性 / 三角 / 带 NAN）的 `lines()` /
  `filled()` 顶点字节摘要逐位相同；`pixi run gate:pyodide` 里 CPython 与 Pyodide
  （wasm）的 `stat_contour` / `stat_contour_filled` 产物摘要也相同。
- **惰性加载**：`ggcore/contour.py` 顶层不 import contourpy，只有 `_generator()`
  （等值线几何）才加载；`ggcore/stat2d.py` 也不在顶层导入 `ggcore.contour`，只有
  contour 族与 `density_2d` 的 contour 分支才导入。所以缺 contourpy 时
  `bin_2d` / `bin_hex` / `summary_2d` / `summary_hex` 与
  `density_2d(contour = FALSE)` 照常可用。回归由 `pixi run gate:contourpy-lazy`
  （`tools/gates/check_contourpy_lazy.py`，挂在 `pixi run check` 里）与
  `tests/test_stat2d_lazy_contourpy.py` 两层守着（SIL-758）。
- **门禁覆盖**：`gate:pyodide` 现在会在 Pyodide 里真的跑一遍等值线——`run_ir.py`
  额外产出 `stat_contour` / `stat_contour_filled` 的列摘要，两端（同版本 contourpy）
  必须逐字节相同，并打印两端的 contourpy 版本；版本不同也算红。
- **口径边界**：contourpy 与 isoband 在鞍点单元 / 闭合环拆分上不同，所以
  `contour` 族的 R 对拍只钉「层级边界」（level / level_low / level_high /
  level_mid），几何用自洽断言（顶点落在同一层级的线性插值上），不逐行比顶点。
  详见 `docs/notes/stat.md` §9。

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
scene，比较 stdout（`digest` / `bytes` / `plot_digest`）。两份载荷：

- `ggcore.ir.demo_scene()`：嵌套视口 + path + text + raster blob + zeroGrob；
- M1-11 的整页场景（`plot_scene()`）：2×2 分面 + colour 图例 + 标题 + 主轴——
  图例 key 走 `Geom.draw()`、轴 / 图例尺寸来自主题与内置度量。

子进程同时自检 `encode(decode(data)) == data`，所以“编码 + 解码”合起来也要字节
稳定；同一进程内重复调用、两次 `build_plot()` 的字节也都检查。

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
| 兜底表 | `TableBackend` vs HarfBuzz | run 切分 0 不一致；**声明支持**的文字 < 1%（M2-S1 起表建模字对 kerning，实测 0） |
| 灵敏度 | 字体栈砍成单字族后的双端比较 | 必须判红（否则门禁失效） |
| 表新鲜度 | `tools/metrics/build_table.py --check` | 重新生成的表与提交的表逐字节相同 |

实测量级与口径推导见 `docs/notes/metrics-ledger.md` · M0-7。报告落在
`.gate-metrics/metrics_gate.json`（不入库）。

### 兜底表 1% 判据（M2-S1 起）

M0-7 的表只做逐码点 advance，这份语料上最大差 2.374%（判据 5%）；M2-S1 给表加了
字对 kerning（`metrics_table_v2`），同一份语料逐条与 HarfBuzz 相同，判据收到 **1%**，
留的是一两条没枚举到的字对（`U+0000–U+2FFF` 之外）的余量。口径与推导见
`docs/notes/metrics-ledger.md` · M2-b。

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
pixi run gate:metrics        # 期望 exit 1：每档 51 条超阈 + 58 条 run-mismatch，最差 289%
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

## 双端 IR 字节一致（M0-10）

`gate:pyodide` 让同一份 `tools/gates/pyodide/run_ir.py` 在两个运行时各跑一次：
CPython 走 `cbor2`（Rust 扩展），Pyodide 走 `ggcore.ir._cbor`（纯 Python，因为
Pyodide 包索引里没有 `cbor2`）。两个实现写出的字节必须完全相同——这是「内核能进
浏览器」的最小证据。它只跑 node，不需要浏览器；资产复用
`pixi run spike:e1:assets`。

前置断言也是判据的一部分：CPython 侧没用到 `cbor2`、或 Pyodide 侧居然用上了，
都直接判失败——否则「一致」只说明同一个实现跑了两遍。

负向对照走 `pixi run gate:pyodide:selftest`：让 Pyodide 侧产出差 1 个比特，门禁
必须红；CI 里正负两步都跑。细节、版本与加载耗时基线见 `docs/notes/pyodide.md`。

门禁比的是**两份** scene：`plot.json` 那份，加一份边角取值 scene（f32 缓冲里的
NaN 全部位型 / ±Inf / -0.0，以及取到 64 位上界的 `int` 参数，477 B）。第二份是
SIL-646 加的——超 64 位整数曾经让 Pyodide 直接抛 `CBORError`，而一份正常 scene
永远走不到那个分支。

`gate:pyodide` 只比**一份** scene，证明不了 `_cbor` 是 canonical CBOR——边角取值
没有输入就永远走不到。`gate:cbor` 补的就是这一层：9330 个取值（NaN 的全部位型、
±Inf、负数分支、23/24/255/256/65535/65536 长度头、嵌套容器、5000 条随机模糊）
逐个与 `cbor2.dumps(..., canonical=True)` 比字节，解码方向也比。两类**按设计不写**
的取值在这里断言「必须抛 `CBORError`」，而不是静默放过：

- 超 64 位整数要 bignum tag，IR 线格式不写 tag → 由 `ggcore.ir.INT_MIN/INT_MAX`
  在构造节点时就把 `int` 参数收进 64 位；
- `memoryview` 在 `cbor2` 里是整数数组、不是 byte string → `_cbor` 拒绝，不认错。
