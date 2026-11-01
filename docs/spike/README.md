# M-1 可行性闸门：三个未知点的实测结论

这一步决定「Python 核心进浏览器」这条路是否成立。三个实验全部通过才继续投后面的 400 人日。

## 决策表

| 编号 | 实验 | 结论 | 关键依据 | 对后续的影响 |
|---|---|---|---|---|
| E1 | Pyodide 冷启动（4G < 3 s，3G < 8 s） | 待测（SIL-588） | — | 决定 M3-9 首屏优化是否要改架构（IR 预渲染 / 服务端出图） |
| E2 | uharfbuzz vs CanvasKit.Paragraph 度量一致性（< 0.5%） | **通过** | 200 条标签 × 4 个字号（10/12/16/24 px），最差 0.241%、均值 0.02%、0 条超阈；双端 run 切分 100% 一致 | 度量表不必随 IR 打包；但**必须由 TS 侧显式按字体切 run**（132/200 条标签依赖这一点） |
| E3 | 浏览器导出缺口 | **通过（缺口确认，非阻塞）** | CanvasKit 0.42.0 只有 raster surface：`MakeSurface`/`makeImageSnapshot` 可出 PNG，无 PDF 文档、无 SVG canvas；skia-python 144.1 出 PDF（1 页、无 `/Font` 依赖、342 条路径算子）与可解析 SVG | SVG 走 TS 序列化器（零 wasm），PDF 只在桌面/服务端；浏览器侧导出格式限于 PNG |

## 复现

全部通过 pixi 驱动，干净机器上：

```
pixi install
pixi run spike:e2     # E2：双端度量一致性（含自动下载 canvaskit-wasm）
pixi run spike:e3     # E3：导出缺口
pixi run spike:e1     # E1：Pyodide 冷启动（任务由 SIL-588 落地，此任务与目录当前尚不存在）
```

产物：`docs/spike/{e1_coldstart,e2_metrics,e3_export}/results/`。语料是冻结的：
`docs/spike/corpus/labels_200.json`，sha256 `6c93e414…bedfb1`，由 `pixi run spike:corpus` 可重现。

CI 侧只需要三条命令：`pixi run lint`、`pixi run test`、`pixi run spike:e2`（后者就是 M0-7 门禁的雏形）。
`.github/workflows/ci.yml` 暂未入库：本任务使用的 GitHub token 缺 `workflow` scope，推送被拒；M0-1 落地时补上。

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
