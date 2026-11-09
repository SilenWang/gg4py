# 公开 API：`gg4py` 顶层入口的提升策略（SIL-911）

`library(ggplot2)` 之后，`ggplot()` / `aes()` / `geom_*()` / `stat_*()` … 都直接在
全局可用。gg4py 以前要分三处 import：

```python
from ggcore.plot import aes, geom_point, ggplot, labs
from ggio.frame import from_dict
from ggskia import ggsave
```

现在一条就够：

```python
import gg4py

df = gg4py.from_dict({"wt": [1.9, 2.6, 3.2], "mpg": [31, 26, 21]})
p = gg4py.ggplot(df, gg4py.aes(x="wt", y="mpg")) + gg4py.geom_point()
gg4py.ggsave(p, "first-plot.png", width=6, height=4, dpi=150)
```

`from gg4py import ggplot, aes, geom_point, labs, from_dict, ggsave` 同样可用。
旧路径（`ggcore.*` / `ggio` / `ggskia.*` / `ggshape.*` / `ggdiff.*`）一个字没动，
现有 README、示例与扩展文档里的写法继续有效。

## 1. 三层边界

| 层 | 入口 | 内容 | 理由 |
| --- | --- | --- | --- |
| **顶层** | `gg4py` | `ggplot` / `aes` / `labs` / `guides`、全部 `geom_*` / `stat_*` / `position_*` / `scale_*` / `coord_*` / `facet_*` / `guide_*` / `theme_*`、输入适配 `from_*` / `to_column_table`、`ggsave`、`__version__` | ggplot2 里 `library(ggplot2)` 就能用的那批名字；画一张图不需要第二个 import |
| **子命名空间** | `gg4py.io` / `gg4py.ir` / `gg4py.diff` | IR 编解码（`encode` / `decode` / `Scene` / `Node` …）、IR 落盘与后端注册（`save_ir` / `export_ir_json` / `register_backend` …）、差分（`compare_images` / `rasterize_svg` …） | 开发者 API：写渲染器、对拍、调试 IR 时才用；首次访问才导入 |
| **内部包** | `ggcore.*` / `ggio` / `ggshape` / `ggskia` / `ggdiff` | 原样保留 | 高级入口、扩展写法、既有文档与 `pixi run` 任务都按这些路径写 |

`gg4py` 本身不实现任何东西：它只是 `ggcore.plot` 注册表的一层投影，加上两个
`__getattr__` 钩子（惰性 `ggsave`、惰性子命名空间）。

## 2. 单一事实源：清单是算出来的，不是抄的

注册表 → 公开名字的链条只有一条：

1. `ggcore.registry.KINDS` 固定九族（geom / stat / position / scale / coord /
   facet / guide / theme / label），`PREFIXES` 给出每族的前缀（label 无前缀，
   所以是 `labs` 而不是 `label_*`）；
2. `ggcore.plot` 导入时 `_export_registry_entries()` 把注册表每一项写进模块
   globals，并据此构造 `ggcore.plot.__all__`；
3. 运行期 `registry.register()` / `unregister()` 通过 `_refresh_entry()` 同步
   `ggcore.plot` 的 globals 与 `__all__`；
4. `gg4py` **不复制**这份清单：`__getattr__("__all__")` 每次从
   `ggcore.plot.__all__` 现算，属性访问也转发到 `ggcore.plot`。

因此加一个组件只改注册表一处：

```python
from ggcore import registry
import gg4py

registry.register("geom", "mygeom", my_constructor)

"geom_mygeom" in gg4py.__all__  # True
p + gg4py.geom_mygeom()  # 顶层就能用，不需要改 gg4py 的代码
```

`tests/test_public_api.py` 有两条断言守着这件事：

- `test_every_registry_entry_is_the_same_object_at_the_top_level`：注册表每一项
  都在 `gg4py.__all__` 里，且 `getattr(gg4py, entry) is getattr(ggcore.plot, entry)`；
- `test_newly_registered_component_appears_at_the_top_level_without_edits`：临时
  注册一个 geom，断言它出现在 `__all__`、能构图、能当方法用；注销后立刻消失。

顶层清单的构成（2026-11-09 实测）：`ggcore.plot.__all__` 275 项 +
`ggio.frame.__all__` 中的可调用入口 4 项（`from_arrow` / `from_dict` /
`from_pandas` / `to_column_table`）+ `ggsave` + `__version__` = **281** 项。
`SUPPORTED_INPUTS` 是说明性字符串，不提升。

**刻意不做过滤清单。** `ggcore.plot.__all__` 里也有 `draw_key_*` /
`guide_gengrob` / `coord_munch` / `theme_sub_*` 这类偏底层的名字——它们同样是
ggplot2 4.0.3 NAMESPACE 的导出项，且由同一张注册表生成。为它们手写一张
「不进顶层」的排除表，等于把已经消灭的第二个事实源又建回来：每加一个组件仍要
回来改两处。底层 API 的正确去处是子命名空间或内部包，不是排除表。

## 3. X1 与 `ggsave` 的惰性

`ggcore` 不能 import `ggskia`（X1 门禁 `pixi run gate:imports`），而 `ggsave`
真正出图需要 skia 设备。所以顶层 `ggsave` 走模块级 `__getattr__`：

| 场景 | `import gg4py` | `gg4py.__all__` | `gg4py.ggsave` |
| --- | --- | --- | --- |
| 有 skia-python | 成功，**不**导入 `ggskia` | 含 `ggsave` | `ggskia.ggsave`（`ggskia` 导入时已注册后端） |
| 没有 skia-python | 成功，`ggcore` 照常可用 | 含 `ggsave` | 回落到 `ggcore.io.ggsave`，写 `.ggir.cbor` / `.ir.json` 仍可用，PNG/SVG/PDF 调用时才报「没有注册后端」 |

回落只兜「渲染栈不在这台机器上」（`ModuleNotFoundError` 的 `name` 是
`ggskia` / `skia`）；`ggskia` 内部别的导入错误照旧抛出，不会被吞掉。

`gg4py.ggsave is ggskia.ggsave is ggcore.io.ggsave` 是同一个函数对象，不是包装。

`from gg4py import *` 会触发 `ggsave` 的惰性导入（`__all__` 里每个名字都要能
取到）；无 skia 环境里它落到回落分支，仍然成功。生产代码建议写
`import gg4py`，把后端加载交给第一次 `ggsave`。

## 4. 冲突与重名的取舍规则

1. **注册表优先，补充名不覆盖。** `_public_names()` 先放 `ggcore.plot.__all__`，
   再追加 `from_*` / `ggsave` / `__version__`，已存在的名字不重复追加。
2. **子命名空间优先于同名顶层名。** `__getattr__` 的判定顺序是
   `ggsave` → `io` / `ir` / `diff` → `from_*` → `ggcore.plot`。所以
   `gg4py.io` 永远是子模块；将来若有组件的入口恰好叫 `io`（label 族无前缀，
   理论可能），它只能从 `ggcore.plot.io` 取，`gg4py` 顶层不给这个名字。
3. **`colour` / `color` 各留各的。** 注册表里两个拼写都登记，顶层两个都有，
   不做别名合并（与 ggplot2 4.0.3 的 NAMESPACE 一致）。
4. **`ggsave` 只有一个。** 顶层 = 渲染后端版（惰性）；设备无关的编排在
   `gg4py.io.ggsave`。两者是同一个函数对象，区别只在「后端有没有注册」。
5. **`__all__` 里每个名字都必须可取到。** 动态清单的回落到 `ggcore.plot` 保证
   这一条；审核新补充名时以此为准。

## 5. 迁移示例

| 旧写法（仍然有效） | 新写法 |
| --- | --- |
| `from ggcore.plot import aes, geom_point, ggplot, labs` | `import gg4py`（`gg4py.aes` / `gg4py.geom_point` / …） |
| `from ggio.frame import from_dict, from_pandas, from_arrow` | `gg4py.from_dict` / `gg4py.from_pandas` / `gg4py.from_arrow` |
| `from ggskia import ggsave` | `gg4py.ggsave`（惰性；无 skia 时可写 IR） |
| `from ggcore.ir import encode, decode` | `gg4py.ir.encode` / `gg4py.ir.decode` |
| `from ggcore.io import save_ir, export_ir_json` | `gg4py.io.save_ir` / `gg4py.io.export_ir_json` |
| `from ggdiff import compare_images` | `gg4py.diff.compare_images` |

想保留显式名字时也可以直接 `from gg4py import ggplot, aes, geom_point, labs`。
扩展作者继续按 [`extension.md`](extension.md) 写组件类并 `registry.register_*()`，
顶层会自动出现；不需要碰 `gg4py` 包。

## 6. 验收

```bash
pixi run test            # 含 tests/test_public_api.py
pixi run gate:imports    # X1：ggcore 仍不 import ggskia
pixi run lint            # ruff check + ruff format --check
```

`tests/test_public_api.py` 覆盖八件事：顶层是 `ggcore.plot.__all__` 的投影、
注册表逐项同对象、适配器来自 `ggio.frame`、新注册组件自动可见、`ggsave` 惰性且
与 `ggcore.io` 同一对象、无 skia 环境可 import、子命名空间转发正确、`from gg4py
import *` 完整。

## 7. 刻意不做

- 不把 `ggio` / `ggshape` / `ggskia` 的实现搬进 `gg4py`——那会破坏 X1 与
  「内核只依赖 numpy」的边界。
- 不在 `ggcore` 里 import `gg4py`（反向依赖会把顶层包变成内核的一部分）。投影
  靠 `__getattr__`，注册表不需要知道顶层包存在。
- 不在 `__init__.py` 里给 `__all__` 赋静态快照：快照会让运行期新登记的组件
  漏掉，正是这条 issue 要避免的「改两处」。
