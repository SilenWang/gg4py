# Pyodide 冒烟：CPython 与 Pyodide 的 plot→IR 逐字节一致（M0-10）

「核心能进浏览器」这条产品前提的最小验证：同一份 plot 定义、同一份 `ggcore`
代码，在 CPython 与 Pyodide 上各跑一次，`ggcore.ir.encode()` 出来的字节必须完全
相同。门禁是 `pixi run gate:pyodide`，只跑 node，不需要浏览器。

## 1. 结论

| 项 | 实测值 |
| --- | --- |
| Pyodide | 314.0.7（CPython 3.14.2，wasm32，ABI `2026_0` / emscripten 5.0.3） |
| node | 22.23.4（pixi 的 `nodejs = "22.*"`） |
| Pyodide 侧 numpy | 2.4.6（`numpy-2.4.6-cp314-cp314-pyemscripten_2026_0_wasm32.whl`） |
| CPython 侧 numpy | 2.5.4 |
| contourpy（两端） | **1.3.3**（Pyodide 的 wasm 轮子 + 桌面端 `pixi.lock`，同一版本；SIL-758） |
| 等值线冒烟（SIL-758） | `stat_contour` 10 行、`stat_contour_filled` 37 行，两端摘要相同 |
| CPython 侧 CBOR | `cbor2` 6.1.5（Rust 扩展，canonical） |
| Pyodide 侧 CBOR | `ggcore.ir._cbor`（纯 Python，canonical） |
| IR 字节 | 两侧都是 **1848 B**，sha256 `0d1ca19c7214f35d98a10159f090df57365f99a133d3760e8b200c5ce593e89b` |
| 边角取值 IR（SIL-646） | 两侧都是 **477 B**，sha256 `51f5458855cc336232195e1644898f309f6ef80674f2253e14bdabef8b89c36d`（NaN / ±Inf / -0.0 缓冲 + `int 2**64-1` 参数） |
| 差异 | **无** |
| 解码回环（Pyodide 内） | 两份 scene 的 `decode(encode(scene))` 都与编码前逐位相同 |

输入是 `tools/gates/pyodide/plot.json`（17 个数据点 + 标题 + 6 个刻度标签 + 画布
480×320），转 IR 的代码是 `tools/gates/pyodide/mini_plot.py`，入口是
`tools/gates/pyodide/run_ir.py`——这个入口文件两侧跑的是同一份，不是「两边各写了
一份等价实现」。

## 2. Pyodide 下的依赖面（要写清的部分）

| 依赖 | 在 Pyodide 里 | 依据 |
| --- | --- | --- |
| numpy | **有**，官方 wasm 轮子 | pyodide-lock 里 `numpy 2.4.6`，`loadPackage("numpy")` 从本地目录加载，无需联网 |
| contourpy | **有**，官方 wasm 轮子（1.3.3） | pyodide-lock 里 `contourpy 1.3.3`（`contourpy-1.3.3-cp314-cp314-pyemscripten_2026_0_wasm32.whl`）；桌面端 `pixi.toml` 因此钉 `>=1.3.3, <1.4`，两边同一个版本（SIL-758） |
| cbor2 | **没有** | pyodide 314.0.7 的包索引共 357 个包，不含 `cbor2`（也没有任何 CBOR 编码库，只有 `cbor-diag` 诊断工具） |
| cbor2 的 PyPI 轮子 | **不能用于 wasm** | 6.2.0.post1 共 65 个文件（`cp310`–`cp314` × 各平台轮子 + 1 个 sdist），没有 `py3-none-any`；6.x 起是 **Rust**（PyO3）实现，sdist 需要 Rust 工具链交叉编译到 `wasm32-unknown-emscripten`。micropip 编译不了 |

所以走的是**纯 Python 编码器**这条路：

- `src/ggcore/ir/_cbor.py`：最小 canonical CBOR（205 行，`wc -l` 口径；只用
  `struct` / `math`）。支持 IR 实际用到的类型（dict / list / tuple / str /
  bytes / bytearray / int / float / bool / None），浮点写「能逐位还原的最短宽度」，
  NaN 一律写首选编码 `f97e00`，映射键按「编码长度 → 字节序」排序。
- `src/ggcore/ir/codec.py`：`import cbor2` 成功就继续用 `cbor2`（CPython），
  `ImportError` 时换成 `_cbor`（Pyodide）。`ggcore.ir.CBOR_BACKEND` 报告实际在跑
  哪一个。

两个决定值得记下来：

1. **编码器放在 ggcore，不放在门禁脚本里。** 浏览器里的查看器/编辑器要自己解 IR
   （`decode` 也是同一条回退路径），把编解码放在 harness 里等于给产品埋一个「只有
   测试能跑」的假象。`ggcore` 的白名单（X1）不受影响：`_cbor` 只 import 标准库。
2. **不为了跑通去改 IR 格式。** 线格式仍是 `cbor2` 的 canonical CBOR
   （`docs/notes/ir.md` §2），回退实现被要求逐字节对齐它——这是门禁真正守的东西。

## 3. 门禁怎么判

```
pixi run gate:pyodide            # 正片：差异为空才绿
pixi run gate:pyodide:selftest   # 负向对照：故意差 1 比特，门禁必须红
```

`tools/gates/check_pyodide_ir.py` 做的事：

1. CPython 侧跑 `run_ir.py` → `.gate-pyodide/cpython.ir` + `cpython.ir.edge`（走 `cbor2`）。
2. node 侧 `run_ir.mjs` 启动 Pyodide（资产来自 `pixi run spike:e1:assets`），把
   `src/ggcore` 挂进 wasm 文件系统，跑**同一个** `run_ir.py` →
   `.gate-pyodide/pyodide.ir` + `pyodide.ir.edge`（走 `_cbor`）。
3. 两份都逐字节比较；不一致时打印第一个差异的偏移与两侧上下文（各 25 字节）。
   第二份是 SIL-646 加的边角取值 scene：f32 缓冲里的 NaN 全部位型、±Inf、-0.0，
   以及取到 64 位上界的 `int` 参数——一份「正常」scene 相同证明不了这些边角
   两边写得一样（NaN 作为 CBOR 浮点时的 `f97e00` 归一化由 `gate:cbor` 守）。
4. 等值线冒烟（M2-6 / SIL-758）：`run_ir.py` 额外把 `stat_contour` /
   `stat_contour_filled` 的产物做摘要（列名 + kind + 逐值字节），两端必须相同，
   并且两端的 `contourpy` 版本必须一致（否则「一致」是两个实现的巧合）。这一步
   会把 `contourpy` 的 wasm 轮子装进 Pyodide——`ggcore` 里唯一的 C++ 扩展，
   也是「内核能进浏览器」最需要实测的依赖。
5. 前置断言：CPython 侧必须真的用上 `cbor2`、Pyodide 侧必须真的没有用它。否则
   「一致」只说明同一个实现跑了两遍，判定直接失败（退出码 2）。

两个任务都 `depends-on = ["spike:e1:assets"]`，所以 Pyodide 运行时与 numpy /
contourpy 轮子都从本地目录来（sha256 由 E1 的 manifest 固定），不碰 CDN。

一份 scene 相同证明不了 `_cbor` 是 canonical CBOR，所以另有一道
`pixi run gate:cbor`（`tools/gates/check_cbor_diff.py`）：9330 个取值逐个与
`cbor2.dumps(..., canonical=True)` 比字节再比解码，覆盖 NaN 的全部位型、±Inf、
负数分支、23/24/255/256/65535/65536 长度头、嵌套容器与 5000 条随机模糊。口径与
失败样例见 `docs/notes/gates.md`。

## 4. 负向对照（必须红）

`gate:pyodide:selftest` 让 node 侧把产出 IR 的第 512 个字节翻一位，再走一遍完整
比较。实测输出：

```
inject-diff: flipped bit 0 of byte 512 (negative control)
  diff    : first at byte 512
    cpython: @01f4 64 67 70 61 72 a2 63 63 6f 6c 84 18 c8 18 c8 18 c8 18 ff 63 6c 77 64 f9
    pyodide: @01f4 64 67 70 61 72 a2 63 63 6f 6c 84 18 c9 18 c8 18 c8 18 ff 63 6c 77 64 f9
gate:pyodide:selftest ok — 注入的 1 字节差异被判定为红（负向对照成立）
```

同一个差异（不加 `--expect-diff`）就是失败退出：

```
$ pixi run python tools/gates/check_pyodide_ir.py --inject-diff 512; echo $?
1
```

CI 里两步都跑：`pixi run check` 的 `depends-on` 挂着这两个任务，而
`.github/workflows/ci.yml` 的 `check` job 跑的就是 `pixi run check`——所以不需要
单独加一个 workflow job。正片绿 + 负向对照确认门禁能红；只跑正片的门禁无法排除
「比较函数永远返回相等」这种失效。

## 5. 加载耗时（M3-9 的基线）

`pixi run python tools/gates/check_pyodide_ir.py --repeat 5`，本机（x86_64 容器，
本地文件系统，无网络）：

| 阶段 | 中位数 | 说明 |
| --- | --- | --- |
| boot | 1391 ms | `loadPyodide()`：wasm 实例化 + CPython 启动 + stdlib |
| numpy | 291 ms | `loadPackage("numpy")`（2.96 MB 轮子，本地文件） |
| script | 564 ms | 挂载 `ggcore` + `import` + build + encode + decode 回环 |
| 合计 | 2249 ms | 进程启动到 IR 字节落盘 |

同一脚本在 GitHub Actions runner（`ubuntu-latest`）上 **boot ≈ 2608 ms**，比本机
x86_64 容器慢约 1.9×——差在 wasm 实例化拿到的 CPU，不在 ggcore 的代码。M3-9 对
预算时用 runner 这组数字：本机是下限，runner 更接近用户端。

这组数字是**CPU 地板**，不是用户可见的首图时间：E1 在 4G 网络下测得首访
11.16 s，差在 9.35 MB 载荷的下载，不在计算（`docs/spike/README.md`）。M3-9 的
口径（首访 4G ≤ 12 s、warm ≤ 3 s）里的计算部分可以参考这里的 2.2 s；浏览器里还
要加 worker 启动、DOM/Canvas 绘制与首帧合成。

## 6. 复现

```bash
pixi install
pixi run gate:pyodide                    # 约 3 s（资产已缓存时）
pixi run gate:pyodide:selftest           # 负向对照
pixi run python tools/gates/check_pyodide_ir.py --repeat 5   # 耗时基线
```

产物在 `.gate-pyodide/`（两侧 IR 字节 + 元数据 JSON，不入库）。元数据里有
`pyodide` / `numpy` / `python` 版本、CBOR 后端、`boot_ms` / `numpy_load_ms` /
`run_ms`，M3-9 直接用这份口径对比即可。

## 7. 边界

- **不解决首屏**：这是字节一致，不是加载体验；首屏优化归 M3-9。
- **不含 pandas**：pandas 在浏览器里是懒加载的可选依赖（E1 的 +pandas 变体），
  IR 的输入边界仍是 DataFrame-like，不由本门禁覆盖。
- **不含浏览器渲染**：TS DOM SVG / CanvasKit 与 skia-python 的渲染一致性归 M0-7 /
  M1-13，本任务只到 IR 字节。
- **numpy 版本不同**（2.5.4 vs 2.4.6）：IR 的 bulk 数据是 f32 原始字节，
  `f32()` 的舍入是 IEEE-754 的固定行为，实测逐位相同。哪天一边的 numpy 改了
  类型转换语义，本门禁会直接红——这正是它该做的事情。
- **NaN 只有一种写法**：canonical CBOR 把任何 NaN（符号位、payload 都算）归一成
  `f97e00`，`cbor2` 与 `_cbor` 一致。浮点**参数**仍须有限（`_finite`），NaN 只出现
  在 f32 缓冲里（缺失点、断线），所以这条影响的是缓冲字节，不是参数。
- **`int` 参数有 64 位上界**：超出 `[INT_MIN, INT_MAX]` 要 bignum tag，IR 线格式
  不写 tag，`_cbor` 也不实现它。上界放在 `_check_param`（编解码共用），所以
  「CPython 写得出来、Pyodide 写不出来」的 scene 根本构造不出来，而不是等两边分叉。
- **`memoryview` 不被接受**：`cbor2` 6.1.5 把 `memoryview` 编成整数数组，`_cbor`
  当成 byte string 的话就是另一个值。IR 编码路径从不传它，所以 `_cbor` 直接报错；
  `gate:cbor` 把这条断言成「必须抛 `CBORError`」，避免有人悄悄改成「认错」。
- **node 不是浏览器**：没有 DOM、没有 worker、没有网络节流；FS 挂载方式也和
  worker 里不同。但门禁比较的是 `encode()` 的输出，输入是同一份 JSON，这两处差异
  不改变字节；浏览器侧的真实差异（首帧、内存）由 E1 / M3-9 覆盖。
