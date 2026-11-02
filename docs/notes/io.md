# ggsave / IR 导出（M1-12）

一张 `ggplot` 对象落到磁盘的三个入口：PNG / SVG / PDF（走设备），`.ggir.cbor`
（浏览器端 / `pixi run render` 的输入），`.ir.json`（人眼与浏览器调试用的视图）。
上游对应物是 `R/save.R:92` 的 `ggsave()`。

- 代码：`src/ggcore/io.py`（设备无关的编排）、`src/ggskia/cli/ggsave.py`（CLI，
  入口在包外，见 §2）、`tools/examples/ggsave_demo.py`（验收用的分面 + 图例图）
- 用例：`tests/test_io.py`
- 设备契约：`docs/notes/device.md`；IR 线格式：`docs/notes/ir.md`

## 1. 三个入口

```python
from ggskia import ggsave, save_ir, export_ir_json  # 出图要 ggskia（§2）

ggsave(p, "out.png", width=7, height=5, dpi=150)  # 504×360 pt → 1050×750 px
ggsave(p, "out.svg", units="cm", width=18, height=12)
save_ir(p, "out.ggir.cbor")  # canonical CBOR
export_ir_json(p, "out.ir.json")  # 调试视图（§5）
```

三者都返回一份 `SaveResult`（`path` / `format` / `width_in` / `height_in` /
`width_pt` / `height_pt` / `dpi` / `units` / `size_px` / `bytes` / `device`），
测试直接断言它，不用读文件反推。`size_px` 只有栅格后端才有值（矢量后端与 IR
导出是 `None`）。

格式选择与覆盖：

| 情形 | 选中的设备 |
| --- | --- |
| `filename` 后缀 `.png` / `.svg` / `.pdf` | 对应设备（其余后缀报 `SaveError`） |
| `device="svg"`（格式名） | 忽略后缀里的格式，用 `svg`；后缀本身可以任意 |
| `device=SkiaSvgDevice(...)`（实例） | 用这个设备，但页面尺寸必须与场景一致，否则 `SaveError` |
| `device=callable` | 按 `(width_pt, height_pt, *, dpi)` 造设备 |

## 2. 分层：设备在包外，编排在内核

`src/ggcore/io.py` 只 import 标准库 / numpy / `ggcore`（X1 白名单），所以它
**不能** import `skia-python`。设备与字体度量通过注册口进来：

```python
from ggcore.io import Backend, register_backend

register_backend(Backend(device=device_for, metrics=ShaperMetrics, name="ggskia"))
```

`ggskia/__init__.py` 在 import 时做这一件事，所以 `from ggskia import ggsave`
就能一行出图。没注册后端时（纯 `ggcore` / Pyodide）：

- `save_ir()` / `export_ir_json()` **照常写** —— IR 不需要字体，`text.width`
  退回 `ggcore.geom.scene` 的估算（0.6 em/字符，`_FallbackMetrics`）；
- `ggsave()` 报一条能照做的 `SaveError`（`import ggskia`，或 `pixi run ggsave`）。

CLI 因此落在 `ggskia.cli.ggsave` 而不是 `ggcore.cli`：`render` 的入口在 M0-8
就按同一条规则放在包外（`docs/notes/gates.md`「包外后端的两个例证」）。
`pixi run ggsave` 与 `python -m ggskia.cli.ggsave` 是同一条命令：

```bash
pixi run ggsave <module:plot_fn> out.png|svg|pdf|ir.cbor|ir.json \
    [--width 7] [--height 5] [--units in|cm|mm|pt] [--dpi 72]
```

`<module:plot_fn>` 里的 `plot_fn` 不收参数、返回 `ggcore.plot.ggplot`；
`<path/to/file.py:plot_fn>` 直接按文件加载，不需要先建包。plot 的 `data` 是
`ggcore.data.ColumnTable` —— 从 pandas / Arrow / dict 进来时先过
`ggio.frame.to_column_table()`（`docs/notes/data.md`）。

## 3. 尺寸、单位与默认值

`width` / `height` 按 `units` 换算成英寸，页面尺寸再按 **72 pt/in** 交给设备
（与 IR / `ggcore.device` 同一把尺）：

| `units` | 1 单位的英寸数 | 说明 |
| --- | ---: | --- |
| `in` | 1 | 缺省 |
| `cm` | 1/2.54 | |
| `mm` | 1/25.4 | |
| `pt` | 1/72 | **设备 pt**（bigpts），不是 grid 的 `points`（1/72.27 in TeX pt，`docs/notes/units.md`） |

缺省值与上游 4.0.3 的差异（`R/save.R` 的 `ggsave()` / `plot_dim()` 是这份对照
的来源，**本任务是按 issue 钉死的口径实现**，不声称与上游逐项一致）：

| 参数 | gg4py（本任务） | ggplot2 4.0.3 | 备注 |
| --- | --- | --- | --- |
| `width` / `height` | `7` × `5` in | `NA`（没有开设备时按 `7 × 7` in 兜底） | 上游的「当前设备尺寸」在无状态的服务端没有意义，钉死更好测 |
| `dpi` | `72` | `300` | 72 是 pt 与 px 的 1:1 口径，改 `dpi` 只改像素密度 |
| `units` | `in` / `cm` / `mm` / `pt` | `in` / `cm` / `mm` / `px` | `px` 未实现：页宽绑到 dpi 与 IR 的 pt 尺寸重复表达，需要时再加 |
| `plot` | 必填 | `get_last_plot()` | 不做 `last_plot()` 全局状态 |
| `bg` / `scale` / `limitsize` / `path` / `create.dir` | 不支持 | 支持 | 背景走主题的 `plot.background`；目录不存在时自动创建（上游要 `create.dir = TRUE`） |

栅格尺寸就是 `round(width_pt / 72 × dpi) × round(height_pt / 72 × dpi)`
（`Device.size_px`），所以 `7 × 5 in @ 150 dpi` 是 **1050 × 750 px**，与
`width × dpi` 一致；矢量后端与 IR 的几何不受 `dpi` 影响。

## 4. 三路设备的能力差异

| 后端 | 文字 | 页面 / 画布 | 产物特征 |
| --- | --- | --- | --- |
| PNG（`SkiaRasterDevice`） | `TextBlob` 字形渲染 | `dpi` 决定的像素画布 | 白底；CJK 与 latin 都在同一张位图里 |
| SVG（`SkiaSvgDevice`） | 字形轮廓 `Font.getPath()` | 页面尺寸 pt，`viewBox` 同尺寸 | 没有 `<text>` / `font-family`，不依赖查看器字体 |
| PDF（`SkiaPdfDevice`） | 字形轮廓 | 单页 | 没有 `/Font`，CJK 不依赖阅读端字体 |

三条约束与 M0-8 相同（`docs/notes/device.md` §2–§3）：页面尺寸是显式参数（设备
不替场景改纸）、一次 `open → draw_scene → close`、设备只吃 `ir.Scene`。
**不做多页 PDF**（一份文件一页）；不做透明背景（`plot.background` 由主题决定）。

### 4.1 SVG 的 id 归一化

skia 的 SVG 序列化器给 `<clipPath>` 发的 id（`cl_0`、`cl_1`…）是**进程级递增**
的：同一进程里的第二个画布会从 `cl_3` 接着数，于是同一张图两次渲染的字节不同。
id 只是文档内部的引用名，所以 `SkiaSvgDevice._finish` 按出现顺序把它们重编号成
`cl_0…`，并同步改 `url(#…)` / `href="#…"`。这让 SVG 产物重新变成输入的纯函数
（「同一输入两次 `ggsave` 逐字节相等」靠它），也不影响像素。

## 5. `.ggir.cbor`：可复现的 IR

`scene_from_plot()` → `ir.encode()`（canonical CBOR，`docs/notes/ir.md` §2）。
`Scene.dpi` 恒为 `72`：IR 里只有几何，出图的分辨率是设备参数。读它的两条路：

```bash
pixi run render --scene out.ggir.cbor --out again.png --dpi 150
```

或者浏览器端（M1-13 的 TS 渲染器 / Pyodide 内核直接 `ir.decode`）。

`text.width` 来自注册后端的 `ShaperMetrics`（与设备同一份 shaping），所以在
`ggskia` 环境里 `.cbor` 的文本宽度与真机渲染一致；纯 `ggcore`（没有字体）用
兜底估算 —— 结构相同、宽度不同，`docs/notes/io.md` 这份差异是 IR 的已知口径
（`ggcore.ir` 的注释：宽度以设备为准）。

## 6. `.ir.json`：调试视图，不是传输格式

`export_ir_json()` 写的是 `ir_json_view(scene)` 的 JSON 文本：

```
{
  "magic": "ggir", "ir_version": "0.2",
  "size": [504.0, 360.0], "dpi": 72.0,
  "stats": {"node_count": 112, "buffer_bytes": 1776, "blob_count": 0, "blob_bytes": 0},
  "blobs": [{"id": "sha256:…", "mime": "image/png", "nbytes": …}],
  "root": {"id": "0", "kind": "viewport", "params": {"name": "page"},
           "bufs": [{"name": "clip_rect", "dtype": "f4", "shape": [1, 4],
                     "nbytes": 16, "sha256": "…"}],
           "children": [ … ]}
}
```

- 节点 `id` 是从根出发的索引路径（`0/3/1`），同一份场景永远是同一组 id；
- `gpar` / `params` 只写**非缺省**字段，与 CBOR 同一条规则；空容器不写；
- `bufs` / `blobs` 只留 `dtype` / `shape` / `nbytes` / `sha256`，**不展开 bulk**
  （X1 `gate:ir-json` 守的就是这条；`ggcore/io.py` 连 `json` 模块都不 import，
  文本是手写的确定性序列化）。

因为 bulk 只以摘要出现，`.ir.json` **画不出图**：它没有顶点、没有 blob 字节。
体积也因此与数据量脱钩，实测（同一份 `ggplot` + `geom_point`）：

| 场景 | `.ggir.cbor` | `.ir.json` | JSON / CBOR | 说明 |
| --- | ---: | ---: | ---: | --- |
| 100 点散点（22 节点） | 4,307 B | 19,697 B | 4.57× | 节点键名与 id 占主导 |
| 10,000 点散点（19 节点） | 83,115 B | 16,392 B | 0.20× | 缓冲被摘要成 ~200 B/缓冲，JSON 反而小 5 倍 |
| 7×5 分面 + 图例（112 节点，`tools/examples/ggsave_demo.py`） | 16,370 B | 91,194 B | 5.57× | 节点多、数据少 |

结论：JSON 的「大」或「小」都不说明它适合传输 —— 它**丢掉了唯一有体积的那部分**。
要一份能画出来的字节，用 `save_ir()`；要人眼核对节点树/参数/数据指纹，用
`.ir.json`。10k 点的体积账（IR vs 逐元素 JSON）见 `docs/notes/ir.md` §10。

## 7. 明确不做

- `last_plot()` 全局状态、`path=`、`scale=`、`limitsize`、`bg=`；
- 多页 PDF、`px` 单位；
- IR schema 的任何改动（本任务只消费 `ir.encode`）；
- 浏览器端 TS 渲染器（M1-13）与 Pyodide 画布。

## 8. 复现

```bash
pixi run test                                  # 含 tests/test_io.py
pixi run ggsave tools/examples/ggsave_demo.py:plot out.png --dpi 150
pixi run ggsave tools/examples/ggsave_demo.py:plot out.svg
pixi run ggsave tools/examples/ggsave_demo.py:plot out.pdf
pixi run ggsave tools/examples/ggsave_demo.py:plot out.ggir.cbor
pixi run ggsave tools/examples/ggsave_demo.py:plot out.ir.json
pixi run render --scene out.ggir.cbor --out from-ir.png   # 换个入口再出一张
```
