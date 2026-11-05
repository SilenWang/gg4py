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

---

# 第二部（SIL-824 / M3-3）：ggcore 全量进 Pyodide + 页面自托管

第一部分把「核心能进浏览器」钉在**一份**手搓 scene 上。SIL-824 把这条线扩到
**案例库全量**，并把浏览器侧真的跑起来：一个只访问本站资产的页面，在 Pyodide 里
`import ggcore`、算出一张图、把 IR 交给零 wasm 的 TS 渲染器。

## 8. 全量 case 门禁（`gate:pyodide`）

```
pixi run gate:pyodide            # 冒烟 + 全部 case，两端逐条比 IR
pixi run gate:pyodide:selftest   # 负向对照：冒烟翻 1 字节 + 一条 case 的摘要翻 1 位
```

两个相位，各跑一遍两端：

| 相位 | 内容 | 判据 |
| --- | --- | --- |
| 冒烟（M0-10） | `plot.json` → IR、边角取值 scene、等值线（contourpy）产物 | 逐字节 |
| **全量 case**（SIL-824） | `docs/cases/*/plot.py` 的每一条：`load_plot()` → `build_scene()` → `ir.encode()` | IR 的 sha256 + 字节数 |

实测（本机 x86_64 容器，资产已在本地）：

| 项 | 值 |
| --- | --- |
| 纳管 case | **515 / 515**（`docs/cases/*/plot.py` 全量，`failed = 0`） |
| 两端 IR 总字节 | **4,489,324 B**，逐条 sha256 相同 |
| 全量摘要（`(case, sha256)` 排序后 sha256） | `10861690b3af35e6…` |
| CPython 侧耗时 | ≈ 9.3 s（`cbor2`） |
| Pyodide 侧耗时 | ≈ 20 s（`ggcore.ir._cbor`，含 515 次 build + encode） |
| 整个门禁 | ≈ 37 s（两个相位、两次 node 启动） |

**度量用哪一份**：两端都走 `ggcore.metrics.fallback.TableMetrics`——浏览器里没有
skia / HarfBuzz，宽度只能来自 ggcore 自带的兜底度量表。这一点是必须的，否则 7 条
纯 `textGrob` 快照（`geom-text-cjk`、`text-emoji`、`upstream-guide-axis-check-overlap`
…）在 Pyodide 侧直接 `GrobError`。`TableMetrics` 也顺带成了浏览器编辑器的度量实现
（M3-4 直接用），不是只为门禁写的。

### 这个门禁抓到的两个真问题

两条都是「CPython 绿、浏览器红」的移植缺陷，冒烟相位一辈子看不见：

1. **`geom_dotplot` 在 wasm32 上直接 `TypeError`**（36 条 case 全红）。
   `np.arange(n)` 在 32 位平台给的是 `int32`，而 `np.repeat()` 会把 `repeats`
   按 **safe** 规则转成索引 dtype——传 `int64` 数组就是
   `Cannot cast array data from dtype('int64') to dtype('int32')`。
   修法：索引数组一律 `np.intp`（两侧都是「索引该有的宽度」），
   见 `src/ggcore/geom/dist.py` 的 `setup_data()`。
2. **`upstream-geom-hex-polar` 的 theta 标签角度差 1 ULP**
   （`441.9999333333334` vs `441.99993333333333`，IR 同样长度、只差 1 字节）。
   原因是 `GuideAxisTheta` 拿标签位置反解 `atan2(x - 0.5, y - 0.5)`，而
   `atan2(sin θ, cos θ)` 只是 θ 的近似，glibc 与 emscripten 的 libm 在这里差 1 ULP。
   修法：`polar_theta_ticks()` 直接把 `theta_angle()` 算出的 θ 带出去，不再绕一圈
   （见 `docs/notes/guide.md` 的坐标口径，值本身不变，只去掉一次有损反解）。

### 8.1 返工（2026-11-05）：门禁必须与机器无关

PR #95 的 CI `check (dev)` 红了，main 用 #96 revert。红的原因不是逻辑错，而是**本机
复现不了**的差异：`gate:pyodide` 在本机 515/515 全绿，在 CI runner 上有 3 条 `coord_sf`
case 两端 IR 不一致（同长度、不同 sha256）。

| case | cpython（CI） | pyodide（CI） |
| --- | --- | --- |
| `upstream-coord-sf-coord-sf-with-custom-guides` | `f5400cbb766b0aa1…` | `77b62fbb0b32071d…` |
| `upstream-coord-sf-non-sf-geoms-using-long-lat` | `46ed41373d45bd6b…` | `b7a9c65492d34297…` |
| `upstream-coord-sf-non-sf-geoms-using-projected-coords` | `4b20225d91918feb…` | `ea18bc8757e0c92a…` |

根因：`coord_sf` 的 `1 / cos(lat)` 比例 → 面板版式 → `viewport.transform` 的平移量，
`cos` 来自**宿主** libm；glibc 版本 / CPU 不同就差 1 ULP。修法与全部细节见
`docs/notes/ir.md` §9「跨机器确定性」：进 IR 的浮点一律先量化到固定十进制网格
（参数 10 位、缓冲 1e-6、`coord_trans` 结果 1e-12），三处离散判定（`munch_steps` 的
段数、极坐标标签的 90° 翻转、sf 投影输出）单独处理。

新增门禁 **`pixi run gate:libm-noise`**（挂进 `check`）：把 `math` / `numpy` 的三角与
指数函数整体偏 ±1 ULP（`up` / `down` / `mixed` 三种方向），全量 515 条 case 的 IR 必须
逐条不变。它不需要第二台机器，是本机能对「换一台 runner」做的最接近的代理——这正是
上一次漏掉的那一层（`gate:pyodide` 只比同一台机器上的两个运行时）。

## 9. 浏览器运行时（页面 + 资产自托管）

`web/runtime/` 是一个静态页面：

| 文件 | 作用 |
| --- | --- |
| `index.html` | 进度条 / 阶段 / 三个示例 / 出图区 / 元数据面板 |
| `runtime.js` | 页面控制器：进度聚合、示例调度、IR → DOM SVG（懒加载 `web/viewer/dist`） |
| `worker.js` | Pyodide worker：boot、解包 ggcore、按 `needs` 懒加载包、build + encode |
| `sw.js` | Service Worker：只接管 `vendor/`，tee 响应体报字节数、顺带缓存（warm） |
| `demos/*.py` | 三个示例（同一份文件桌面端也在跑，用来对 IR 摘要） |

资产由 `pixi run pyodide:assets` 落到 `web/runtime/vendor/`（**不入库**）：

| 文件 | 字节 | 说明 |
| --- | --- | --- |
| `pyodide/pyodide.asm.wasm` | 9,598,218 | gzip 后 3.55 MB 上线 |
| `pyodide/python_stdlib.zip` | 2,545,637 | 已压缩，原样上线 |
| `pyodide/pyodide.asm.mjs` | 1,250,344 | gzip 后 0.26 MB |
| `pyodide/*.whl` | 2.96 + 4.18 + 0.12 + … | **按需**：numpy / pandas / contourpy 各自懒加载 |
| `gg4py.zip` | 716,699 | `src/{ggcore,ggio}` 的确定性 zip（82 个文件，条目从仓库根算起） |
| `fonts/*.ttf` | ≤ 2 MiB/字面 | 只有拉丁字面：Arimo / DejaVu / Noto Sans / Noto Emoji |

三条刻意设计：

1. **一个 CDN 都不碰**。页面、脚本、worker、运行时、轮子、字体全在同源 `vendor/`
   下；构建期（`spike:e1:assets`）才允许下一次网，且 sha256 由 pyodide-lock 固定。
2. **数值栈真懒加载**。boot 只到「pyodide 可用 + 源码解包完」，一个 `.whl` 都不下；
   每次跑示例先用 `ast` 静态读 `needs`（不执行示例代码），再 `loadPackage`，然后才
   `import ggcore`（ggcore 自己 import numpy，所以 numpy 的下载时机就是「第一次真要
   出图」）。`pixi run pyodide:runtime` 断言：`ready` 之前没有 `.whl` 请求、
   `ready` 时 `packages == []`。
3. **字体只带拉丁字面**。`viewer/fonts.css` 声明了 8 个受管字族，其中
   `NotoSansCJKsc-VF.ttf` 是 35 MB、`NotoColorEmoji.ttf` 是 9.5 MB——页面一渲染
   CJK 文本就会去下 35 MB（实测：一次加载光字体 36 MB，首访直接 40 s+）。
   `stage_assets.py` 按 ≤ 2 MiB 挑字面重写一份 `vendor/fonts.css`；CJK 文本回落到
   系统字体。**这是取舍不是遗漏**：CJK 子集化在 M3-4 之后单独做。

### 加载进度

进度不是估的：Service Worker 用 `response.body.tee()` 数**真实传输字节**（wasm /
stdlib 是 pyodide 自己 fetch 的，页面拿不到逐字节回调；SW 在中间就够了），分母是
`vendor/manifest.json` 里规划过的文件 + 每次跑示例时点名的包。页面把
`已下载 / 预计` 与阶段一起画在进度条上；`pixi run pyodide:runtime` 断言进度序列
覆盖 ≥3 个阶段、百分比单调上升且到过 90%+，并在 5%–99% 之间截一张图。

### 断网可用（无 CDN）

`pixi run pyodide:runtime` 的第二段把**所有站外请求** abort 掉再重载页面
（DevTools 的 offline 模式连 localhost 也断，静态页面本来就打不开，那不是这条
验收要问的问题）：页面照常出图，contour 示例照常算出与 CPython 相同的 IR。整轮
另有「任何请求的 host 必须是 127.0.0.1」的断言，实测站外请求 0 条。

## 10. 实测加载时间（Fast 4G，本机）

口径：服务端按 **9 Mbps / 170 ms** 限速（DevTools 的 Fast 4G 预置），每次冷启动
用**新浏览器**（Cache Storage / HTTP 缓存 / Service Worker 全空），warm 是同
浏览器重新导航一次；终点是「第一张图的 SVG 已合成」（两次 `requestAnimationFrame`）。

| 状态 | 3 次实测（ms） | 中位 | 线上字节 |
| --- | --- | --- | --- |
| 首访（冷，新浏览器） | 13438 / 13527 / 13546 | **13.5 s** | 10.11 MB |
| warm（同一浏览器重载） | 4116 / 4155 / 4201 | **4.2 s** | 0.04 MB |

冷启动的分段（取中间那次，单位 ms）：

| 段 | ms | 说明 |
| --- | --- | --- |
| 页面 + SW + `new Worker()` | 747 | 含 manifest、worker 模块与 SW 注册 |
| worker 内 pyodide boot | 7,709 | 含 wasm + stdlib 8.1 MB 的下载 |
| numpy 下载并安装 | 2,824 | 2.96 MB wheel |
| `import ggcore` | 1,069 | 60+ 个模块 + numpy |
| build + encode + 渲染 + 2 帧 | 391 | 到第一张图合成 |
| IR 到手（`result_in`） | 13,136 | |

warm 的 4.2 s 里：页面与 worker 启动 0.35 s、pyodide boot 1.46 s、包安装 0.28 s、
`import ggcore` 1.07 s、build/encode 0.22 s、渲染 0.36 s。

**这两个数字没有达到 12 s / 3 s，缺口是结构性的，写清楚留给 M3-9：**

- 载荷地板 = E1 的 9.06 MB（wasm 3.55 + stdlib 2.55 + numpy 2.96，三份都不可裁）
  + ggcore 源码 0.72 MB + `pyodide.asm.mjs` 0.26 MB ≈ 10.0 MB。9 Mbps 下就是
  9 s 的纯传输，E1 当年 9.35 MB 实测 11.16 s（CDP 节流更狠）。加上 ggcore 的
  import（1.09 s）与渲染，**12 s 在「全量 ggcore 也进浏览器」之后基本贴着地板**。
- warm 的 3 s 同理：pyodide boot 1.43 s + numpy 安装 0.27 s 已经 1.7 s，
  再叠加 `import ggcore` 1.04 s 就必然过 3 s。
- 能继续压的方向（都属 M3-9，不在本任务改造范围内）：把 ggcore 预编译成
  `.pyc` 只带字节码（预计省 0.5 s import）、在分片层面预载（worker 与页面并行起）、
  用 brotli 替代 gzip（wasm 3.55 → ≈3.1 MB）、以及 CJK 字体子集化。

工程上已经做了能做的：gg4py.zip 与运行时**并行**下载、渲染器按需 import（不占关键
路径）、warm 路径不等 Service Worker 的 `ready`、SW cache-first 让 warm 的线上
字节降到 0.04 MB。

## 11. 复现

```bash
pixi run pyodide:assets     # 运行时 + 源码 zip + 拉丁字面 → web/runtime/vendor/
pixi run pyodide:runtime    # 端到端验收：自托管 / 懒加载 / 进度 / 断网 / 三示例 IR 一致
pixi run pyodide:timing     # 12. 的实测（--measure，3 次；约 1 分钟）
pixi run gate:pyodide       # 全量 case 的逐字节门禁
```

产物都在 `.pyodide-runtime/`（`report.json` + 截图，不入库）。
