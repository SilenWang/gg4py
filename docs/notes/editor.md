# 浏览器代码编辑器（M3-4 / SIL-826）

在浏览器里**写这个包的代码**，跑出图，改一行再跑。不是表单重算，也不是 spec 编辑器：
左栏是一段真的 Python（CodeMirror 6，Python 高亮 + 四空格缩进），右栏是 IR → DOM SVG
渲染出来的图，下面有 stdout / stderr 与 Python traceback。

- 页面：`web/editor/index.html`（一个静态页面 + 本地资产，无后端、无账号）
- 执行：`web/runtime/worker.js`（与运行时页**同一个** Pyodide worker）
- 出图：`web/viewer/dist`（TS 渲染器，零 wasm）
- 导出：`web/editor/export.js`（SVG / PNG / JPG）
- 验收：`pixi run editor:check`

## 1. 跑起来

```bash
pixi install
pixi run editor:serve      # 构建编辑器 + 本地资产，然后 http://127.0.0.1:8000/editor/
```

`editor:serve` 只是 `web/` 的一个静态服务（`tools/editor/serve.py`）。生产上随便一个
静态托管（`web/` 整个目录）都能跑；`file://` 不行——浏览器会拦 ES module 与 fetch。

首次访问要下载 Pyodide 运行时（≈ 5.5 MB 线上，brotli）+ `gg4py.tar`（1.02 MB，含预编译字节码）；numpy 轮子
（2.9 MB）在**第一次出图**时才下，pandas / contourpy 只在脚本用到时下（M3-3 的
懒加载口径不变）。之后靠浏览器 HTTP 缓存，重跑只花内核计算的时间。

## 2. 代码契约（两端共用一份）

编辑器不发明第二套 API：脚本就是 `docs/cases/*/plot.py`、`web/runtime/demos/*.py`
的同一形状——

```python
from ggcore.plot import aes, geom_point, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy"]  # 可选：静态扫描看不见的懒加载依赖

DATA = {"x": [1, 2, 3], "y": [3, 1, 2]}


def build():
    p = ggplot(to_column_table(DATA), aes(x="x", y="y")) + geom_point() + theme_minimal()
    return {"plot": p, "size": [5.0, 3.5]}  # size 单位是英寸
```

`build()` 也可以直接返回一个图对象（尺寸取 `ggcore.script.DEFAULT_SIZE`），或者
不写函数、把图放进模块级 `plot` 变量。三种写法都归一成同一条
`ggcore.plotspec.build_scene()`。

执行本身在 `ggcore/script.py`（`run_script()`），**桌面与浏览器调的是同一个函数**：
同一段源码在 CPython 与 Pyodide 上产出的 IR 逐字节相同（`editor:check` 用 9 个示例
的 sha256 钉住这条）。这比「两边各写一份等价实现」强的地方在于：任何一处口径
漂移都是红，而不是「大概一样」。

口径细节：

- 度量固定 `ggcore.metrics.fallback.default_metrics()`（TableMetrics）。浏览器里没有
  skia / HarfBuzz，桌面端要逐字节相同也只能用它。
- `needs` 与 `import` 都会被静态扫描（`ggcore.script.detect_needs`）；`contourpy` 只在
  `stat_contour*` 被调用时才 import，静态看不见，所以等值线脚本必须显式写进 `needs`。
- 用户代码抛错 → `ScriptError`：`message` 一行原因，`traceback_text` 只有**用户源文件**
  的栈帧（不出现 `ggcore/script.py` 的内部行），编辑器把它原样回显。
- 数据面板：CSV 写进虚拟文件系统 `/app/data.csv`（cwd 就是 `/app`），脚本用
  `ggio.csv.read_csv("data.csv")` 读；「内联数据」是一段 Python 字面量，作为 `DATA`
  变量注入（不改源码，traceback 行号与编辑器里看到的一致）。`read_csv()` 只用标准库，
  贴一段 CSV 不需要 pandas。

## 3. 耗时（本机实测，`pixi run editor:check`）

| 项 | 实测 | 口径 |
| --- | --- | --- |
| 首次出图 | 3.5–3.7 s | 页面加载到第一张图（含运行时启动 + numpy 轮子 + ggcore import） |
| 改一行重跑（warm） | **64–130 ms** | 点运行 → worker exec + build + encode → 页面 decode + 渲染 → 第二帧合成 |
| 其中 worker | ≈ 100 ms | `run_script()` 全流程（含 9 个示例里最重的 facets） |
| 其中页面渲染 | ≈ 30 ms | `decodeScene` + DOM SVG |

验收预算是 2 s（warm），实测差两个数量级。机器差异见 `docs/notes/pyodide.md` §5：
跑分以 CI runner 为下限而不是本机。

这里的 warm 数字**包含** M3-5 的增量重算（`docs/notes/performance.md`）：worker 是长
驻解释器，图层绘制与场景指令两条内容键缓存跨重跑生效，所以「改一行」只重算真变了
的那部分。缓存可以用 `GG4PY_NO_SCENE_CACHE=1` 关掉做对照。

## 4. 导出

`web/editor/export.js` 只走浏览器自带的栅格化：`<svg>` → Blob → `<img>` → `<canvas>`
→ `toBlob()`。没有 wasm，也没有 skia（PDF 仍然只在桌面 / 服务端，见
`docs/notes/device.md`）。

| 格式 | 尺寸 | 说明 |
| --- | --- | --- |
| SVG | `round(pt × 倍数)` | 独立文档：`width`/`height` 是像素，`viewBox` 是 pt；**内嵌字体**（data URI） |
| PNG | 同上 | 透明底；1× = 72 dpi |
| JPG | 同上 | 白底，质量可调（0.4–1.0） |

两条约定让「导出的 PNG 与屏幕所见一致」成为可判定的而不是形容词：

1. **屏幕就是 1×**。IR 的单位是 pt，页面按 1 pt = 1 px 显示；`handleResult()` 还会
   把居中之后的半像素偏移补掉（`snapSvg()`），否则浏览器会把整张图重采样一次。
   导出第 n 倍 = `round(pt × n)`，与屏幕同一个取整。DPI 是同一件事的另一种写法：
   1× = 72 dpi、2× = 144 dpi、4× = 288 dpi。
2. **字体必须内嵌**。`<img>` 加载的 SVG 是独立文档，拿不到页面的 `@font-face`；
   不内嵌就会掉到系统字体。`export.js` 按「实际用到的真实字族」（跳过 `sans` 这类
   CSS 通用族）× 粗细 × 斜体，从 `web/viewer/fonts.css` 里取字面转 data URI。
   只带主字族的字面，不把 CJK 35 MB 拖进每一张图。

`editor:check` 比的是两件事，容差都是 0（RGBA 四个通道全部相等）：

- **1×**：导出的 PNG 与 `svg.gg-svg` 的元素截图逐像素相同；
- **2×**：另开一个 `device_scale_factor = 2` 的浏览器上下文（CSS 尺寸不变、物理
  像素翻倍），屏幕上的 720×504 与 2× 导出的 PNG 逐像素相同。

跨浏览器栅格化器／跨 skia 的像素对比是另一套口径，不在这里下结论。

## 5. 状态与错误

- 代码按示例分键存 localStorage（`gg4py.editor.v1`），防抖 350 ms 写一次；
  切换示例、改数据面板、导出设置都记在里面。刷新页面回来还是上次的代码。
- 出错不白屏：上一张图保留并置灰，`#traceback` 里是用户源文件形状的 Python
  traceback（运行时错误与语法错误都是），状态行红字给一行原因。
- 页面公开 `window.__ggEditor`（`state()` / `run()` / `setSource()` / `selectExample()` /
  `export()`），`tools/editor/check_editor.py` 只用这个接口，不依赖 DOM 细节——除了
  「CodeMirror 挂载 + 有高亮 token」那一条。

## 6. 示例库

`web/editor/examples/` 9 个一页代码，`index.json` 是清单（label / note / 可选的内置数据）。
每个都必须能在浏览器里直接跑出图，`editor:check` 逐个跑并比 IR 摘要：

| 示例 | 展示什么 | 依赖 |
| --- | --- | --- |
| `hello` | 最小散点 | numpy |
| `line` | 折线 + `colour` 映射 + 图例 | numpy |
| `bars` | `geom_col` + `position_dodge` | numpy |
| `boxplot` | 五数 + 离群点 | numpy |
| `facets` | `facet_wrap` + `geom_smooth` | numpy |
| `polar` | `coord_polar` 玫瑰图 | numpy |
| `contour` | 等值线填充 | numpy + contourpy |
| `pandas` | DataFrame 输入 | numpy + pandas |
| `csv` | 数据面板的 CSV | numpy |

新增示例只要放进 `examples/` 并在 `index.json` 登记；`editor:check` 会自动把它加进
「逐个跑通 + 两端 IR 一致」的清单，不需要另写测试。

## 7. 边界（明确不做）

- 不做文件树 / 多文件工程 / 浏览器内包管理：一页代码 + 一页输出。
- 不做账号、云保存、分享链接托管：代码只在 localStorage。
- 不做浏览器内 PDF。
- 不把 UI 做成「应用」：没有安装引导、没有首启向导。PWA 是 M3-9 / 附带能力，
  不是这一页的验收项。
- 首屏优化（Worker 预载、资源分片、CJK 子集）归 M3-9；这一页只保证「能写、能跑、
  能导出」，`editor:check` 不设首访耗时门禁（口径在 M3-9）。
