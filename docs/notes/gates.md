# 横切门禁（X1）

三道门都是普通脚本，退出码可判定，既能在 `pixi run check` 里跑，也能单独跑。

| 任务 | 脚本 | 拦截什么 | 失败样例 |
| --- | --- | --- | --- |
| `pixi run gate:imports` | `tools/gates/check_import_whitelist.py` | `src/ggcore/` 里出现白名单外的 import | `import pandas` |
| `pixi run gate:ir-json` | `tools/gates/check_ir_json.py` | ggcore 里出现 JSON 序列化调用 | `json.dumps(scene)` |
| `pixi run gate:determinism` | `tools/gates/check_determinism.py` | 同输入序列化出不同字节 | 两个进程摘要不一致 |

`pixi run check` = `lint` + `test` + 三道门。

## import 白名单

允许的顶层模块：

- 标准库（`sys.stdlib_module_names`，外加 `__future__`）
- `numpy`（计算内核）
- `cbor2`（IR 的二进制编码；目前未引入，先放行）
- `ggcore` 自身

其余一律失败，包括 pandas / pyarrow / polars / skia / matplotlib。理由：ggcore 是
Pyodide 里也要跑的纯 Python 内核，DataFrame-like 输入在边界处转成 IR，渲染后端在
包外。门禁只做 AST 扫描，不执行被检查的代码。

包内相对导入（`from .scene import Scene`）不越界，直接跳过。

动态导入（`importlib.import_module("pandas")`、`__import__("pandas")`，含
`import importlib as il` 的别名）同样拦：参数是字符串字面量时按同一份白名单判
定，不是字面量（`importlib.import_module(name)`）则直接失败——门禁离线核对不了
它到底导入了什么。

## IR 禁止逐元素 JSON

`src/ggcore/` 里禁止 `json.dumps` / `json.dump` / `json.JSONEncoder` /
`from json import dumps` / `orjson.dumps` / `.to_json()`。IR 的 bulk 数据必须是
float32 缓冲 + CBOR：314 份快照的规模下，逐元素 JSON 的体积与耗时都不达标。
需要 JSON 的地方（例如 web 端读取配置）放在包外。

模块别名算同一个东西：`import json as j` 之后 `j.dumps(...)` /
`j.JSONEncoder` 一样拦（`orjson` / `ujson` / `simplejson` / `rapidjson` 同理）。

## 同输入同字节

`check_determinism.py` 用两个不同 `PYTHONHASHSEED` 的解释器进程各序列化一次占位
scene（`ggcore.scene.placeholder_scene()`），比较 stdout。真 IR 落地后把载荷换成
真实 scene，判定方式不变。同一进程内重复调用也在子进程里自检。

## 手测一次门禁是否真的会拦

```bash
printf 'import pandas\n' > src/ggcore/_probe.py
pixi run gate:imports          # 期望 exit 1，且报 src/ggcore/_probe.py:1
rm src/ggcore/_probe.py
```

违规样例的自动化版本在 `tests/test_gates.py`（种到 tmp 目录里跑真实脚本），所以
不需要靠“记得手测”来保证门禁还活着。
