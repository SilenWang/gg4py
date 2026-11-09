# 导出：PNG / SVG / PDF 与 IR

一张图有三条出口：

| 出口 | 入口 | 在哪能用 |
| --- | --- | --- |
| PNG / SVG / PDF | `ggsave()`（`ggcore.io`，设备来自 `ggskia`） | 桌面 / 服务端 |
| IR（`.ggir.cbor`） | `save_ir()` / `ggcore.ir.encode()` | 桌面 / 服务端 / 浏览器（同一份字节） |
| 浏览器 PNG / JPG / SVG | 编辑器「导出」按钮（`web/editor/export.js`） | 浏览器（不经 skia，**不能出 PDF**） |

## 1. `ggsave()`

```python
from gg4py import aes, geom_point, ggplot, ggsave, labs, theme_minimal, to_column_table

DATA = {"x": [1, 2, 3, 4, 5], "y": [2.0, 1.5, 4.2, 3.1, 5.4]}

p = (
    ggplot(to_column_table(DATA), aes(x="x", y="y"))
    + geom_point(size=3, colour="#4C78A8")
    + labs(title="export me", x="x", y="y")
    + theme_minimal()
)

for suffix in ("png", "svg", "pdf"):
    result = ggsave(p, f"plot.{suffix}", width=6, height=4, dpi=150)
    print(result.path.name, result.format, (result.width_pt, result.height_pt), result.size_px)
```

| 参数 | 含义 | 缺省 |
| --- | --- | --- |
| `width` / `height` | 页面尺寸，按 `units` 解释 | 7 × 5 |
| `units` | `"in"` / `"cm"` / `"mm"` / `"pt"`（设备 pt，1/72 in） | `"in"` |
| `dpi` | 栅格化密度（只影响 PNG 像素，不改变几何） | 72 |
| `device` | 覆盖后缀：格式名 / `Device` 实例 / 工厂 | 由后缀决定 |
| `metrics` | 文本度量实现 | 后端注册的（HarfBuzz） |

返回 `SaveResult`：`path` / `format` / `width_pt` / `height_pt`（页面尺寸，pt）/
`size_px`（栅格化的像素，矢量与 IR 为 `None`）/ `dpi` / `units` / `bytes`。
后缀决定格式，`.png` / `.svg` / `.pdf` 之外会报错。SVG 是矢量、PDF 是页面文档；
PNG 的像素 = `round(pt / 72 × dpi)`。

命令行等价物（`pixi run` 里跑的就是同一条命令）：

```bash
pixi run ggsave examples/heatmap/plot.py:plot out.png
pixi run ggsave examples/heatmap/plot.py:plot out.svg --width 10 --units cm
pixi run ggsave examples/heatmap/plot.py:plot out.pdf --dpi 300
pixi run ggsave examples/heatmap/plot.py:plot out.ggir.cbor
```

第一个参数是 `<module:plot_fn>`（也可以是 `<路径/file.py:fn>`），`plot_fn` 不吃参数、
返回一个 `ggplot`。

## 2. IR：`.ggir.cbor`

IR 是「已解析几何」的唯一中间表示：float32 缓冲 + 节点树，canonical CBOR，
CPython 与 Pyodide 上逐字节相同。它的用途是**同一份字节喂所有渲染器**（桌面
skia、浏览器 DOM SVG、查看器）。

```python
from pathlib import Path

from gg4py import aes, geom_point, ggplot, to_column_table
from gg4py.ir import decode
from gg4py.io import export_ir_json, save_ir

DATA = {"x": [1.0, 2.0, 3.0], "y": [3.0, 1.0, 2.0]}
p = ggplot(to_column_table(DATA), aes(x="x", y="y")) + geom_point(size=3)

saved = save_ir(p, "plot.ggir.cbor", width=5, height=3.5)
print(saved.bytes, (saved.width_pt, saved.height_pt))  # 字节数、页面尺寸（pt）

scene = decode(Path("plot.ggir.cbor").read_bytes())
print(scene.size, scene.dpi)  # (360.0, 252.0) 72.0

debug = export_ir_json(p, "plot.ir.json")  # 调试视图：节点 id/kind/参数 + 缓冲摘要
print(debug.bytes)
```

`.ir.json` **不是**传输格式：bulk 缓冲只留 `dtype` / `shape` / `sha256`，画不出图，
只给浏览器调试与人眼核对。画图请用 `.ggir.cbor`。

渲染一份 IR：

```bash
pixi run render --scene plot.ggir.cbor --out plot.png --dpi 300
pixi run render --scene plot.ggir.cbor --out plot.svg
```

## 3. 脚本 → IR（与浏览器同一条路）

`ggcore.script.run_script()` 是浏览器编辑器用的执行契约，在桌面上也能用；它返回
的 `ir_bytes` 就是 `.ggir.cbor` 的内容：

```python
from pathlib import Path

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
Path("hello.ggir.cbor").write_bytes(result.ir_bytes)
print(result.meta["digest"], len(result.ir_bytes), result.meta["needs"])
```

同一段源码在 CPython 与 Pyodide 上产出的 `ir_bytes` 逐字节相同（`editor:check` 用
9 个示例的 sha256 钉住）。脚本形状见 [`browser.md`](browser.md) §2。

## 4. 浏览器导出

编辑器右栏的「导出」只走浏览器自带栅格化：`<svg>` → `<img>` → `<canvas>` →
`toBlob()`。

| 格式 | 尺寸 | 说明 |
| --- | --- | --- |
| SVG | `round(pt × 倍数)` | 独立文档，内嵌实际用到的字体 |
| PNG | 同上 | 透明底；1× = 72 dpi、2× = 144 dpi、4× = 288 dpi |
| JPG | 同上 | 白底，质量 0.4–1.0 |

**PDF 只能在桌面 / 服务端出**：CanvasKit 没有 PDF 后端（`docs/notes/device.md`
的结论）。浏览器 PNG 与桌面 skia PNG 是两个光栅器，像素不要求相同；现有 2% / 1%
阈值只定义在 resvg 统一栅格的口径下。

## 5. 边界

- `ggsave()` 要 `ggskia`（skia-python）：`ggcore` 本身不 import 它（X1 门禁），
  所以浏览器里没有 `ggsave()`。
- `save_ir()` 不带 `dpi`：IR 只承载几何，`Scene.dpi` 恒 72；分辨率由设备决定。
- 页面尺寸必须有限且为正；未知后缀 / 未知 `device` 报错并列出可选格式。
- 字体：SVG / PDF 写字形轮廓（`docs/notes/device.md`）；浏览器导出的 SVG 靠内嵌
  data URI 字体，跨机器打开才不掉字。
