# M-1 可行性闸门：三个未知点的实测结论

这一步决定「Python 核心进浏览器」这条路是否成立。三个实验全部通过才继续投后面的 400 人日。

## 决策表

| 编号 | 实验 | 结论 | 关键依据 | 对后续的影响 |
|---|---|---|---|---|
| E1 | Pyodide 冷启动（4G < 3 s，3G < 8 s） | **不通过** | 5 次冷启动中位：Fast 4G **11,160 ms**（3.7×）、Fast 3G **51,550 ms**（6.4×）；gzip 后真实传输 **9.35 MB**（wasm 3.55 + stdlib 2.55 + numpy 2.96），warm 缓存地板 **2,207 ms** → 4G 只剩 ≲0.9 MB 下载预算 | 原判据不可达；**产品决定按「接受首访慢」落地**（见下文「决定与验收口径」）。首图 SSR / 纯 JS 转为可选加速，不再是前置条件；详见 `docs/spike/e1_coldstart/report.md` |
| E2 | uharfbuzz vs CanvasKit.Paragraph 度量一致性（< 0.5%） | **通过** | 200 条标签 × 4 个字号（10/12/16/24 px），最差 0.241%、均值 0.02%、0 条超阈；双端 run 切分 100% 一致 | 度量表不必随 IR 打包；但**必须由 TS 侧显式按字体切 run**（132/200 条标签依赖这一点） |
| E3 | 浏览器导出缺口 | **通过（缺口确认，非阻塞）** | CanvasKit 0.42.0 只有 raster surface：`MakeSurface`/`makeImageSnapshot` 可出 PNG，无 PDF 文档、无 SVG canvas；skia-python 144.1 出 PDF（1 页、无 `/Font` 依赖、342 条路径算子）与可解析 SVG | SVG 走 TS 序列化器（零 wasm），PDF 只在桌面/服务端；浏览器侧导出格式限于 PNG |

## 决定与验收口径（2026-11-01，产品负责人）

闸门结论：E2、E3 通过；E1 未达原判据（4G < 3 s），但差距来自载荷体积，不是可调优的实现问题。产品负责人据此定了方向：

- **浏览器定位：能画图**（不是「只看图」）。
- **接受首访慢**：首次访问 ~11 s（4G，9.35 MB 载荷，必须给加载进度），回访 ~2.2 s（Service Worker 预缓存后）。
- 因此 **M3-9 的验收改为：首访 4G ≤ 12 s 且 warm ≤ 3 s**。「首访 < 3 s」不再是本路径的目标——要做到只能换运行时（wasm 裁剪与压缩补不上 9 倍差距）。
- 首图 SSR / 纯 JS 渲染降级为**可选加速**，不作为前置条件；pandas 维持懒加载（+4.93 MB，按需下载）。

## 复现

全部通过 pixi 驱动，干净机器上：

```
pixi install
pixi run spike:e2     # E2：双端度量一致性（含自动下载 canvaskit-wasm）
pixi run spike:e3     # E3：导出缺口
pixi run spike:e1     # E1：Pyodide 冷启动（约 30 分钟；冒烟：E1_PROFILES=fast4g E1_RUNS=1 E1_SENS_RUNS=0）
```

产物：`docs/spike/{e1_coldstart,e2_metrics,e3_export}/results/`。语料是冻结的：
`docs/spike/corpus/labels_200.json`，sha256 `6c93e414…bedfb1`，由 `pixi run spike:corpus` 可重现。

CI 侧只跑 `pixi run check`（M0-1 起 `.github/workflows/ci.yml` 已接入）。E2 的门禁版本
是 `pixi run gate:metrics`（M0-7），它复用同一份语料与同一个 CanvasKit 度量脚本
（`tools/metrics/measure_canvaskit.cjs`），本目录的 `measure_canvaskit.cjs` 只是它的薄壳。

## 环境与版本（实测记录）

| 项 | 值 |
|---|---|
| HarfBuzz（uharfbuzz 0.57.0） | 15.0.0 |
| CanvasKit（canvaskit-wasm） | 0.42.0 |
| skia-python | 144.1 |
| Node | 22.x |
| 字体 | conda-forge `font-ttf-dejavu` / `font-ttf-noto` / `font-ttf-noto-cjk` / `font-ttf-noto-emoji`，即 `$CONDA_PREFIX/fonts` |

## 体积基线（2026-11 本机实测）

| 文件 | 磁盘 | 传输（gzip） |
|---|---|---|
| `pyodide.asm.wasm` | 9.37 MB | 3.46 MB |
| `python_stdlib.zip` | 2.49 MB | 2.44 MB |
| numpy wheel | 2.89 MB | 2.89 MB |
| pandas wheel | 4.08 MB | 4.08 MB |

E1 的实测结论以真实网络传输字节为准（Playwright 网络事件统计），上表只作对照。

## 对 M0 的直接结论

1. **M0-7（双端度量一致）可以照原计划做**，但门禁必须包含「显式 run 切分」这一条：只把整串丢给主字族会得到 `.notdef` 盒子（见 E2 报告）。语料直接复用 `docs/spike/corpus`。
2. **M0-8（skia 设备）的文本必须走轮廓**：桌面 PDF 里的文字是几何而非字体引用（`/Font` 不存在），这对 CJK 是必须的；顺带发现 skia-python 的 `SkFont` 文本 API 依赖宿主 fontconfig，容器里没有时会段错误，轮廓路径反而是更稳的实现。
3. **M1-13/M2-12 的 SVG 渲染器是唯一 SVG 出口**，不存在「CanvasKit 顺手导出 SVG」的捷径；IR 必须带着最终宽度与锚点（与 M0-2 的约定一致）。
4. **E1 不通过（闸门未过）**：冷启动首图不能由 Pyodide 产出，载荷与 CPU 地板两项都超出 3 s / 8 s 门槛一个数量级。三个实验未全部通过，按闸门规则需要产品定位判定（浏览器画图 vs 浏览器只看图），已交 Sylens Wong 决定，暂不推进后续排期。
