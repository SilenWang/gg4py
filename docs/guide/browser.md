# 在浏览器里写 gg4py 代码

编辑器是**一个静态页面**：左边写 Python，右边出图，改一行再跑。不用装东西、不用
账号、没有后端；`ggcore` 本体以 Pyodide（wasm）的形式跑在页面上，出图走 TS 的 DOM
SVG 渲染器（零 wasm）。

- 页面：`web/editor/index.html`
- 跑起来：`pixi run editor:serve` → <http://127.0.0.1:8000/editor/>
- 实现与验收细节：[`../notes/editor.md`](../notes/editor.md)、
  [`../notes/pyodide.md`](../notes/pyodide.md)

## 1. 跑起来

```bash
pixi install
pixi run editor:serve            # 构建编辑器 + 落本地资产，再起静态服务
# 浏览器打开 http://127.0.0.1:8000/editor/
```

`editor:serve` 只是 `web/` 的静态服务（`tools/editor/serve.py`）。换端口用
`pixi run editor:serve -- --port 9000`。**不要用 `file://` 打开**：浏览器会拦 ES
module 与 `fetch`。生产部署就是把 `web/` 整个目录交给任意静态托管。

首访要下载运行时（Pyodide + `gg4py.tar`），numpy 轮子在第一次出图时下载；
pandas / pyarrow / contourpy 只在脚本声明用到时才下载。之后靠浏览器 HTTP 缓存。

## 2. 代码契约：一段脚本就是一张图

编辑器不发明第二套 API——你写的就是 `ggcore`：

```python
from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

needs = ["numpy"]  # 可选：这段脚本要用的 Pyodide 包

DATA = {"x": [1, 2, 3, 4, 5], "y": [3.1, 1.4, 4.8, 2.2, 5.6]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point(size=2.6)
        + labs(title="hello from the browser", x="x", y="y")
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.5]}  # size 单位是英寸
```

三种写法都认（与 `docs/cases/*/plot.py`、桌面端 `run_script()` 同一套）：

| 写法 | 结果 |
| --- | --- |
| `def build(): return {"plot": p, "size": [5.0, 3.5]}` | 最完整：显式尺寸 |
| `def build(): return p` | 尺寸取 `ggcore.script.DEFAULT_SIZE`（5.0×3.5 in） |
| 模块级 `plot = p`（不写函数） | 同上；第一段代码可以短到只有五行 |

三条路径最后都走 `ggcore.plotspec.build_scene()`，所以**同一段源码在桌面与浏览器
产出的 IR 逐字节相同**（`pixi run editor:check` 用 9 个示例的 sha256 钉住这条）。

### `needs`：按需加载的包

静态扫描 `import` 与 `needs` 决定下载哪些轮子。`contourpy` 只在 `stat_contour*`
真正被调用时才 import，静态看不见，所以**画等值线必须显式写**：

```python
from ggcore.plot import aes, geom_contour_filled, ggplot, labs
from ggio.frame import to_column_table

needs = ["numpy", "contourpy"]

GRID = {
    "x": [x for _ in range(1, 6) for x in range(1, 6)],
    "y": [y for y in range(1, 6) for _ in range(1, 6)],
    "z": [x * 0.5 + y for y in range(1, 6) for x in range(1, 6)],
}


def build():
    p = (
        ggplot(to_column_table(GRID), aes(x="x", y="y", z="z"))
        + geom_contour_filled()
        + labs(title="contour filled", x="x", y="y")
    )
    return {"plot": p, "size": [5.0, 3.6]}
```

可用的包：`numpy`（默认）、`pandas`、`pyarrow`、`contourpy`。标准库随运行时一起
到，不需要声明。

## 3. 数据从哪来

| 入口 | 用法 |
| --- | --- |
| 内联数据 | 直接写在脚本里（上面的 `DATA`），最省事，也最推荐先这样试 |
| 数据面板 · CSV | 展开左侧「数据输入」，粘贴 CSV；运行时会把它写成虚拟文件系统的 `data.csv`（cwd 是 `/app`） |
| 内置示例数据 | 选示例时一起带进来（例如 `csv` 示例自带一段数据） |

CSV 用 `ggio.csv.read_csv()` 读，**不需要 pandas**（标准库解析，零轮子下载）：

```python
from ggcore.plot import aes, geom_col, geom_point, ggplot, labs
from ggio.csv import read_csv
from ggcore.theme import theme_minimal

needs = ["numpy"]

CSV_TEXT = "class,value\na,3.2\nb,4.8\nc,2.1\nd,5.6\ne,4.1\nf,3.0\n"


def build():
    # 编辑器里数据面板会把 CSV 写进 data.csv：read_csv("data.csv")
    table = read_csv(CSV_TEXT)
    p = (
        ggplot(table, aes(x="class", y="value"))
        + geom_col(fill="#4C78A8", width=0.7)
        + geom_point(size=2.0, colour="#1a202c")
        + labs(title="CSV input", x="class", y="value")
        + theme_minimal()
    )
    return {"plot": p, "size": [5.0, 3.5]}
```

CSV 口径：首行表头（去空白、重名报错）、空单元格与 `NA`/`NaN`/`null` 算缺失、
全整数列 → `int`、其余数值列 → `float`、其它 → 字符串。分隔符默认逗号，`;` /
制表符显式传 `delimiter=`。

pandas 的 DataFrame 也能直接进（`needs` 里要写 `pandas`）：

```python
import pandas as pd

from ggcore.plot import aes, geom_point, ggplot, labs
from ggio.frame import from_pandas

needs = ["numpy", "pandas"]

FRAME = pd.DataFrame({"size": [1.2, 2.4, 3.6, 4.8], "price": [3.1, 5.0, 7.2, 9.1]})


def build():
    p = (
        ggplot(from_pandas(FRAME), aes(x="size", y="price"))
        + geom_point(size=3.0)
        + labs(title="pandas input", x="size", y="price")
    )
    return {"plot": p, "size": [5.0, 3.5]}
```

## 4. 运行、报错、状态

| 操作 | 结果 |
| --- | --- |
| 点「运行」 / `Ctrl`+`Enter` | 执行当前脚本并出图 |
| 控制台 | 脚本的 `stdout` / `stderr` 原样显示 |
| 出错 | 不白屏：上一张图保留并置灰，控制台里是**用户源文件形状**的 Python traceback（语法错误与运行时错误都有），状态行给一行原因 |
| 冷启动 | 首次出图 3–4 s（运行时 + 字体 + numpy + `ggcore` import） |
| 改一行重跑 | 本机实测 64–130 ms（warm），预算 2 s |

traceback 里只保留用户脚本的栈帧（不出 `ggcore/script.py` 的内部行），行号与左边
编辑器一致。`print()` 走控制台，不影响出图。

## 5. 导出

右栏「导出」把当前图写成文件——只走浏览器自带栅格化（`<svg>` → `<img>` →
`<canvas>` → `toBlob()`），没有额外 wasm：

| 格式 | 说明 |
| --- | --- |
| SVG | 独立文档（内嵌用到的字体），`width`/`height` 是像素、`viewBox` 是 pt |
| PNG | 透明底；1× = 72 dpi |
| JPG | 白底，质量可调（0.4–1.0） |

缩放倍数与 DPI 是同一件事的两种写法：1× = 72 dpi、2× = 144 dpi、4× = 288 dpi。
**屏幕所见就是 1×**，导出 n 倍 = `round(pt × n)`，所以 1× PNG 与元素截图逐像素相同
（`editor:check` 用全零容差比这一条）。

浏览器侧**不能出 PDF**：CanvasKit 没有 PDF 后端，PDF 只在桌面 / 服务端由 skia 出
（见 [`export.md`](export.md)）。浏览器 PNG 与桌面 skia PNG 走的是不同光栅器，
两者像素**不要求相同**——这是两套口径，不要拿对拍的 2% / 1% 阈值套它。

## 6. 代码留在本地

代码按示例分键保存在 `localStorage` 的 `gg4py.editor.v1`（防抖 350 ms 写一次）；
刷新页面回来还是上次的代码，切示例也不会丢。「重置」把当前示例恢复成原文。
清浏览器数据就没了——没有云端保存，也没打算做。

## 7. 内置示例库

左侧下拉里 9 个一页代码，都在浏览器里直接跑通（`editor:check` 逐个跑并比 IR 摘要）：

| 示例 | 展示什么 | 依赖 |
| --- | --- | --- |
| 最小散点图 | `ggplot` + `geom_point` + `theme_minimal` | numpy |
| 折线 + 分组颜色 | `colour` 映射到离散列，自动出图例 | numpy |
| 柱状图 | `geom_col` + 分组 | numpy |
| 箱线图 | 五数 + 离群点 | numpy |
| 分面 | `facet_wrap` + `geom_smooth` | numpy |
| 极坐标 | `coord_polar` 玫瑰图 | numpy |
| 等值线填充 | `geom_contour_filled` | numpy + contourpy |
| pandas 输入 | DataFrame → `from_pandas` | numpy + pandas |
| CSV 数据 | `read_csv("data.csv")` | numpy |

## 8. 边界

- **不做**文件树、多文件工程、浏览器内包管理：一页代码 + 一页输出。
- **不做** PDF；**不做**账号 / 云保存 / 分享链接托管。
- 只用 `numpy` / `pandas` / `pyarrow` / `contourpy` 四个轮子；其它第三方包不能
  `import`（见 [`r-to-python.md`](r-to-python.md) 第 9 节的等价写法）。
- 首屏字体是拉丁字面（CJK 字面 35 MB，不进首屏）；中文文本会回落到系统字体，
  度量与桌面不完全一致。要精确对拍中文排版请用 `pixi run viewer:cases` 的像素口径。
- `ggsave()` 在浏览器里不可用（它要 skia）；浏览器侧请用「导出」按钮。
- 页面公开 `window.__ggEditor`（`state()` / `run()` / `setSource()` /
  `selectExample()` / `export()`）供自动化用，`tools/editor/check_editor.py` 就是
  只走这个接口的。

## 9. 桌面端也能跑同一段脚本

脚本契约定在 `ggcore.script` 里，所以「浏览器里跑的那段代码」在命令行也能跑，
产出的 IR 与浏览器逐字节相同：

```python
from ggcore.script import run_script

SOURCE = """
from ggcore.plot import aes, geom_point, ggplot, labs
from ggio.frame import to_column_table

needs = ["numpy"]
DATA = {"x": [1, 2, 3], "y": [3, 1, 2]}

def build():
    p = ggplot(to_column_table(DATA), aes(x="x", y="y")) + geom_point() + labs(title="hello")
    return {"plot": p, "size": [5.0, 3.5]}
"""

result = run_script(SOURCE, filename="hello.py")
print(result.meta["digest"], len(result.ir_bytes))  # sha256 + 字节数
```

`run_script()` 的返回值里 `ir_bytes` 就是 `.ggir.cbor` 的内容，`meta` 带
`digest` / `bytes` / `build_ms` / `nodes` 等，`meta["needs"]` 是静态扫描出的包名。
用 `pixi run ggsave` 或 `pixi run render` 把它画成 PNG / SVG / PDF。
