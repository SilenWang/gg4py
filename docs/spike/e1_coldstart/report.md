# E1 · Pyodide 冷启动（Worker）· 4G/3G 节流实测

**结论：两个 gated 档都没过。** 打开页面 → 首图绘制完成，Fast 4G 中位 **11,160 ms**（门槛 3,000 ms，超 3.7×），
Fast 3G 中位 **51,550 ms**（门槛 8,000 ms，超 6.4×）；Slow 3G 作为压力参考 199,040 ms。
根因是 **9.35 MB 的 gzip 后载荷**：把网络拿掉（warm cache）也要 **2.2 s**，所以即便 CDN 再快、字节再省一半，4G 也过不了 3 s。

| 判据 | 门槛 | 实测中位（5 次冷启动） | 结论 |
| --- | --- | --- | --- |
| Fast 4G（9 Mb/s ↓ / 1.5 Mb/s ↑ / RTT 170 ms） | < 3,000 ms | **11,160 ms** | ✗ 超 3.7× |
| Fast 3G（1.6 Mb/s / 750 kb/s / RTT 562 ms） | < 8,000 ms | **51,550 ms** | ✗ 超 6.4× |
| Slow 3G（400 kb/s / 400 kb/s / RTT 2,000 ms） | 仅压力参考 | 199,040 ms | — |

页面本身是「Worker 里跑 Pyodide + numpy → 主线程 canvas 画一条 4,000 点折线 + 一行 CJK 文本」，
不依赖任何既有绘图库，也不依赖 CDN：所有字节由本地静态服务给出（`static/` 由 `pixi run spike:e1:assets` 重建）。

## 口径

| 项 | 取值 |
| --- | --- |
| 起点 | 导航开始（`performance.timeOrigin`，页内 `performance.now()` 即「距导航毫秒」） |
| 终点 | **真正画出首图的那一帧**：worker 回传 → 主线程绘制 → 双 `requestAnimationFrame`（第一帧出图，第二帧证明已合成）读时钟；之后回读画布像素，空白帧不算数 |
| 计时源 | 页面时钟；worker 自报相位用 `worker.timeOrigin` 抬到同一条时间轴上 |
| 节流 | CDP `Network.emulateNetworkConditions`：Fast 4G = 170 ms / 1,125,000 B/s ↓ / 187,500 B/s ↑；Fast 3G = 562 ms / 200,000 B/s ↓ / 93,750 B/s ↑；Slow 3G = 2,000 ms / 50,000 B/s ↔ |
| 缓存 | 冷启动：每次新建 browser context + `Network.setCacheDisabled(true)`；warm 对照：同一 context 内二次导航，缓存打开 |
| `waitUntil` | 统一 `domcontentloaded` |
| 重复 | 每档 **5 次**冷启动（记中位与 p90）+ 5 次 warm；敏感度变体各 3 次 |
| p90 | nearest-rank，n=5 时即最大值；实测极差很小（4G 0.9%，3G 0.05%），中位与 p90 几乎重合 |
| 视口 | 1280×800 @1x，headless Chromium 156.0.8078.4 |

## 环境

- Chromium 156.0.8078.4（Playwright 1.64.1，headless）+ Pyodide **314.0.7**（CPython **3.14.2**, wasm32）+ numpy **2.4.6**
- 16 核 Linux x86_64；本地 `python http.server`（HTTP/1.1、gzip、`Cache-Control: max-age=3600`）
- 无 CJK webfont 下载：首图那行中文用系统字体（pixi 环境的 Noto Sans CJK）。把 36 MB 的 NotoSansCJKsc 塞进首屏不在本实验口径内，真实查看器也不该这么做

## 冷启动结果

**baseline（加载 numpy，用 numpy 算）**

| 档位 | 5 个原始样本 (ms) | 中位 | p90 | 请求数 | 真实传输 | 判据 |
| --- | --- | --- | --- | --- | --- | --- |
| Fast 4G | 11087 / 11139 / 11164 / 11181 / 11160 | **11,160** | 11,181 | 8 | 9,352,096 B（8.92 MiB） | 3,000 ms ✗ |
| Fast 3G | 51550 / 51553 / 51546 / 51568 / 51542 | **51,550** | 51,568 | 8 | 9,352,096 B | 8,000 ms ✗ |
| Slow 3G | 199010 / 199050 / 199040 / 199060 / 199007 | **199,040** | 199,060 | 8 | 9,352,096 B | 参考 |

有效吞吐：4G 838 KB/s（标称 1,125 KB/s 的 74%）、3G 181 KB/s（91%）、Slow 3G 47 KB/s（94%）。
4G 掉到 74% 是因为 8 次请求各带 170 ms RTT，而 wasm 下载完才轮到编译/加载 numpy，链路无法完全流水。

**分阶段耗时（中位，ms）** —— 判据是最后一行，前面四段是它花在哪里：

| 阶段 | Fast 4G | Fast 3G | Slow 3G |
| --- | --- | --- | --- |
| 导航 → worker 启动 | 183 | 586 | 2,072 |
| worker 脚本开始执行 | 542 | 1,765 | 6,243 |
| `pyodide.asm.wasm` 下载（3.55 MB gzip） | 5,845 | 32,470 | 129,625 |
| Pyodide init（含 wasm 下载+编译、stdlib 解包） | 7,160 → 结束于 7,700 | 33,761 → 35,526 | 130,937 → 137,181 |
| numpy 加载（2.96 MB 轮子） | 3,090 → 结束于 10,790 | 15,660 → 51,184 | 61,494 → 198,676 |
| 计算（20k 样本 → 4k 顶点） | 335 | 337 | 337 |
| worker 回传 + 主线程绘制（含双 rAF） | 20 + 8 | 21 + 6 | 21 + 6 |
| **首次绘制** | **11,160** | **51,550** | **199,040** |

下载占 4G 总时的 **80%**，Pyodide init 里的编译/解包是零网络也躲不掉的部分（见下）。

## warm cache 对照（同一 context 二次加载）

| 档位 | 5 个原始样本 (ms) | 中位 | p90 | 请求数 | 真实传输 |
| --- | --- | --- | --- | --- | --- |
| Fast 4G | 2172 / 2207 / 2274 / 2257 / 2177 | **2,207** | 2,274 | 1 | 3,546 B |
| Fast 3G | 2614 / 2601 / 2607 / 2609 / 2590 | **2,607** | 2,614 | 1 | 3,546 B |
| Slow 3G | 4070 / 4076 / 4056 / 4119 / 4127 | **4,076** | 4,127 | 1 | 3,546 B |

warm 4G 只剩 HTML 一个请求（3.5 KB），其余全是 CPU：Pyodide init 1,372 ms、numpy 加载 250 ms、计算 340 ms、启动与绘制约 240 ms。
**这 2.2 s 就是地板**：4G 门槛 3 s 减去它只剩约 0.8 s 的下载预算，折合 **≲0.9 MB** 载荷；
3G 侧 8 s − 2.6 s ≈ 5.4 s × 0.2 MB/s ≈ **≲1.05 MB**。实测载荷 9.35 MB，差 9 倍。

## 体积实测

| 文件 | 磁盘 | gzip 后 | **真实传输** | 说明 |
| --- | --- | --- | --- | --- |
| `pyodide.asm.wasm` | 9,598,218 | 3,546,122 | **3,546,122** | gzip −63%；4G 就吃掉 3.2 s |
| `python_stdlib.zip` | 2,545,637 | 2,503,167 | **2,545,637** | 已是 zip，按原样发 |
| `pyodide.asm.mjs` | 1,250,344 | 260,107 | **260,107** | |
| `numpy-2.4.6-…-wasm32.whl` | 2,960,568 | 2,924,358 | **2,960,568** | 已是 zip，按原样发 |
| `pyodide.mjs` | 17,931 | 7,156 | **7,156** | |
| `pyodide-lock.json` | 119,077 | 26,595 | **26,595** | 包索引 |
| `index.html` | 10,159 | 3,546 | **3,546** | |
| `worker.js` | 5,666 | 2,365 | **2,365** | |
| **baseline 合计** | **16,507,600** | — | **9,352,096** | 8 个请求，gzip 省 43% |
| `pandas-3.0.2-…-wasm32.whl` + 依赖 | 4,929,180 | — | **4,929,180** | 仅 +pandas 变体下载 |

静态目录里还有 `pyodide.js`（UMD 版，模块 worker 用不到）、`pandas`、`dateutil/pytz/six` 等共 21.4 MB，
它们不会在 baseline 冷启动里被请求——上表最后一列才是浏览器真实下载的字节，逐次采样记录在 `results/e1_results.json` 的 `runs[].bytes`。

## 敏感度：numpy 和 pandas 各值多少

| 变体 | Fast 4G 中位 | Δ vs baseline | Fast 3G 中位 | Δ vs baseline | 真实传输 |
| --- | --- | --- | --- | --- | --- |
| baseline（numpy） | 11,160 | — | 51,550 | — | 9,352,096 B |
| **去掉 numpy**（同一工作量改纯 Python） | **7,762** | −3,397（−30.4%） | **35,612** | −15,938（−30.9%） | 6,391,528 B（−2.96 MB） |
| **再加 pandas**（下载但不用于绘图） | **15,529** | +4,369（+39.1%） | **76,267** | +24,716（+47.9%） | 14,281,276 B（+4.93 MB） |

两边的「计算」相位：numpy 335 ms vs 纯 Python 38 ms。差别几乎全在 `import numpy` 的一次性成本（约 0.3 s），
2 万样本的循环本身纯 Python 只要 38 ms——也就是说**对这个首图工作量，numpy 买到的是 2.96 MB 下载 + 0.3 s 启动**，
它的价值要到数据规模大两个数量级才体现。pandas 更极端：多 4.93 MB、4G 多 4.4 s，而首图完全用不到。

## 这说明了什么

1. **不是网络配置问题，是载荷问题。** 9.35 MB 里 wasm 3.55 MB + stdlib 2.55 MB + numpy 2.96 MB，全是 CPython 生态的入场费。
2. **零网络地板 2.2 s** 已经吃掉 4G 门槛的 73%，剩下 0.8 s 只够约 0.9 MB。要达标必须同时做到「载荷 ≲1 MB」和「init 不涨」——保留 CPython 3.14 + Pyodide 做不到。
3. **回访是可行的**：warm 2,207 ms（4G）/ 2,607 ms（3G）都已过门槛，说明首访是这个方案唯一的死穴。
4. **首图与计算可以解耦**：绘制只花 20~30 ms，剩下全是 runtime 启动。

留给父 issue 的三条路（本 spike 不选型，只给数据支撑）：

- **首图不走 Pyodide**：服务端/构建期预生成 SVG，或纯 JS 渲染首图，Pyodide 在后台预温。首图时间立刻落到「网络 + DOM」，与 4G/3G 门槛同量级。
- **缩载荷**：去掉 numpy（−2.96 MB）、裁 stdlib（−2.5 MB 里挑）、wasm 上 brotli（未实测，gzip 已 −63%）、把首图渲染与数值计算拆开。目标 ≲1 MB，等于换一个运行时（MicroPython 级别），而不是省一省 Pyodide。
- **接受首访慢、优化回访**：Service Worker + 持久缓存让二次访问达标（已实测 2.2 s / 2.6 s），首访用低分辨率占位图或静态首图兜底。

## 复现

```bash
pixi install                     # 依赖（含 chromium 需要的 glib/nss/atk 等 conda 库）
pixi run spike:e1:browsers       # 首次需要：装 chromium。cdn.playwright.dev 不通时加
                                 #   PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
pixi run spike:e1                # 装 pyodide 资产 + 跑完整协议（本机约 30 分钟）
```

快速冒烟（约 40 秒，只跑 4G 一档一次）：

```bash
E1_PROFILES=fast4g E1_RUNS=1 E1_SENS_RUNS=0 pixi run spike:e1
```

产物：

- `results/e1_results.json` —— 每次原始样本、分阶段耗时、逐请求字节、汇总与判定（`summary` / `verdict` / `runs`）
- `results/first_paint_fast4g.png`、`results/first_paint_fast3g.png`、`results/first_paint_slow3g.png` —— 首图整页截图（1280×800 视口，画布 + 标题；三档内容一致所以字节相同）
- `static/`（git-ignored）—— pyodide 314.0.7 运行时 + numpy/pandas 轮子，由 `fetch_assets.py` 逐文件校验 sha256，来源写在 `static/manifest.json`

环境坑（都已在 `run_e1.py` / `pixi.toml` 里处理，换机器复现时会再遇到）：

- `$HOME` 只读 → `PLAYWRIGHT_BROWSERS_PATH` 指到仓库内 `.playwright-browsers/`
- 无 `$CONDA_PREFIX/lib` 在 `LD_LIBRARY_PATH` 上 → chromium 启动即 `libglib-2.0.so.0: cannot open shared object`
- 无 `/etc/fonts` → 不设 `FONTCONFIG_FILE` 时 `fillText()` 全零宽，中文标题会「画了但没字」
- `cdn.playwright.dev` / `storage.googleapis.com` 不通 → 用 npmmirror 的 playwright 镜像；Pyodide 轮子同理走 jsdelivr 镜像并在本地落盘，运行期不碰 CDN

## 方法上的局限

- 本地 HTTP/1.1 + gzip；真实部署会用 HTTP/2/3 + brotli，预估再省 10~20% 字节和一部分 RTT 开销（未实测）。以最乐观的 −20% 计，4G 仍是约 9 s，量级不变。
- headless Chromium + 软件 canvas；有 GPU 的桌面浏览器在绘制/合成上会更快，但绘制只占 20~30 ms，不影响结论。
- 未启 Service Worker、无 SSR、不含任何应用层代码：测的就是「Pyodide + numpy 入场」的净成本。
- 5 次冷启动的样本极差 0.9%（4G）/ 0.05%（3G），说明瓶颈稳定在带宽而非抖动；p90 等同最大值。
