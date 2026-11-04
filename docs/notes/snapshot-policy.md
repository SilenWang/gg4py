# 快照容差与参考图纳管（X4）

M0 的比对对象有三类，用途不同，**不能混用容差**：

| 类别 | 来源 | 入库 | 用途 |
| --- | --- | --- | --- |
| 上游参考图 | ggplot2 `v4.0.3` 的 **311** 份 SVG 快照 | 否（脚本按需拉取） | 判定“我们画得像不像” |
| 自产基线 | 我们自己的渲染产物 | 是（`docs/cases/<case>/baseline/`） | 判定“我们有没有改坏” |
| 临时产物 | 每次 `pixi run render` 的输出 | 否（`.gitignore`） | 人眼看图 |

> **数量口径（SIL-745）**：计划里写的是 314，钉住的 commit
> `cc1444c1` 上 `tests/testthat/_snaps/**/*.svg` 实际是 **311** 份。以 pin 为准
> （X2），差 3 的来历查不到（不是被忽略的目录：`_snaps/4.0`、`4.4`、`4.5` 里没有
> SVG）。逐条清单与处置见 `docs/notes/snapshot-inventory.md`。

> **缺口归属（SIL-786）**：`snapshots.toml` 的每个 group 必须写
> `owner = "m2-closeout"`（M2 已宣称但没做到对等，M3 开工前归零）或
> `owner = "m3"`（`geom_sf` / `coord_sf` / `coord_map` / `annotate` / 版面组合，
> 移交 M3）。owner 是**按簇**声明：单条 `[snapshots."…"]` 的 owner 覆盖必须与
> 所属 group 一致，否则 `snapshots:check` 判红。按簇的 burndown 表由
> `pixi run snapshots:report` 生成在同一份清单里，不另维护；`pixi run
> snapshots:report:check` 挂在 CI 上守两件事：清单新鲜度，以及三处口径一致
> ——清单表头、burndown 逐簇相加、`snapshots.toml` 的 group owner 与
> `docs/cases/matrix.md` 的同一张数（SIL-822）。

## 为什么上游快照不入库

SVG 是派生资产：上游一换 pin 就整批失效，进 git 只会制造大 diff 和冲突。拉取
由脚本按 `docs/notes/upstream.md` 的 commit 取，落到 `docs/cases/<case>/expected/`
（已在 `.gitignore` 里忽略），CI 不依赖它。自产基线相反：它就是回归判据，必须
跟着代码走，更新走 PR 且 PR 里贴出 diff 截图。

目录约定见 `docs/cases/README.md`。

## 案例库的 `expected.svg|png`（M0-11）

三文件 case（`plot.py` + `expected.svg|png` + `meta.toml`）里那一张 `expected.*`
与上面的 311 份批量快照**不是一回事**：

- 每个 case 只留一张，是该 case 的判据，**允许入库**（它和生产代码一样要被 review）；
- 来源写在 `meta.toml` 的 `source`（`upstream:<路径>` / `svglite:<R + 版本>`），
  换 pin 时随同 PR 换掉这一张；
- 311 份批量快照仍按上面的策略按需拉取，`docs/cases/*/expected/` 继续忽略。

**硬要求（SIL-599 已生效）**：`ci = true` 的三文件 case 必须来自外部参考——
`source` 以 `upstream:` / `svglite:` 开头。`source = local`（本仓库自录基线）只允许
和 `ci = false` 的探索 case 一起用：自录基线让「基线 == 当前输出」永远绿，SIL-638
的 curve 镜像 / lwd 单位偏差就是这么漏掉的。闸门在 `tools/cases/matrix.py` 的
契约校验里，矩阵会把它标成 `⛔ invalid` 并让 CI 红。

参考图的产线是 `pixi run -e refs refs:cases`（R 4.5.3 + ggplot2 4.0.3 + svglite，
UTF-8 locale），口径见 `docs/notes/diff.md`。

这样新增 case 只需要三个文件，不需要先跑一次网络拉取才能进矩阵。

## 容差口径

### SVG（文本级）

1. 先规范化再比：XML 属性按名字排序、数字统一格式（`%.4f` 去尾零）、去掉生成器
   注释与 `id` 前缀、合并多余空白。
2. 规范化后**逐字节相等**才算通过；不等时按“第一个差异属性的行号”报，不做模糊匹配。
3. 不比较：`<title>` / `<desc>`、时间戳、随机 `id`、`style` 里的属性顺序。

### 位图（PNG，像素级）

两条门，用途不同，**不要混用**：

**A. 同一管线的自产基线**（grob / viewport 快照等，`pixi run cases:*`）：

1. 默认阈值：**不一致像素 ≤ 0.1%**，且**单通道最大绝对误差 ≤ 4/255**（抗锯齿
   边缘的舍入）。
2. 差异像素必须能整块解释成“边缘/半透明叠加”：离散的孤立像素点视为失败。
3. 文字区域单独统计：见下一条。

**B. 跨管线的外部参考**（M0-9 的 `expected.svg|png`，R svglite → resvg vs 我们）：

1. **图级差异 ≤ 2%**：单像素最大通道差 > 4/255 的像素占比；
2. **平均差异 ≤ 1%**：全通道平均绝对差 / 255；
3. 两条同时满足才判绿；尺寸不一致直接红。
4. 两侧都先由 **resvg**（同一版本、pixi 受管字体、`--dpi 72`）光栅化，见
   `docs/notes/diff.md` §2。

B 比 A 宽，是因为 R 与我们的文字度量（hinted vs linear）、抗锯齿实现本就不同；
A 的 0.1% 是「同一条管线有没有改坏」的回归口径。把 B 的阈值套到 A 上会放过回归，
把 A 的阈值套到 B 上会让 CI 永远红——所以两栏都写死在这里。

### 文字与度量

- 文本宽度来自**实际渲染端**，不在 Python 端算完跨端复用（度量账本 L1）。因此
  含 emoji 的区域允许 **0.5% 绝对容差**；纯汉字/拉丁文本 0.1%。
- 字形差异（不同机器同一字体文件的版本不同）不靠调宽容差掩盖：字体由 pixi 固定
  （`font-ttf-dejavu` / `font-ttf-noto` / `font-ttf-noto-cjk` / `font-ttf-noto-emoji`），
  换字体版本要整批重生基线并在 PR 里说明。

### 文字类 case：按 case 收紧阈值（SIL-649）

`geom-text-cjk` 的 `tolerance = { png = 0.014 }`：**比默认 2% 更紧**，因为它要抓
的是「文字宽度算错」这类最常见的 ggplot2 差异，而默认阈值对这个量级不敏感。

实测（本仓库 + pixi 锁定环境，扰动方式是保持字形、只把每个字形的步进与位置按比例
缩放，等价于度量端把宽度算错）：

| 扰动（实测侧） | 图级差异 | 1.4% 阈值下 |
| --- | --- | --- |
| 无（基线） | 1.15% | 绿 |
| 文字宽度 +1% | 1.59% | **红** |
| 文字宽度 +2% | 1.78% | **红** |
| 文字宽度 +5% | 1.86% | **红** |

为什么不能靠「把字放大 / 画布缩小」：

- 跨管线的像素噪声主要来自**垂直**度量差——R 的 `strheight` 与 skia 的
  ascent/descent 不同源，两边基线差 0.032 em（10 pt ≈ 0.32 px，13 pt ≈ 0.42 px）。
  它落在每个字形的上下边缘上，**与字号成正比**，放大字号噪声跟着放大，信噪比不变
  （实测 20 pt / 26 pt 长标签的比值反而更差：1.09×、1.08×）。
- 宽度误差则是**沿字符串累积**的：左对齐时第 i 个字偏移 ≈ 2% × i × 字号。所以
  「更长的左对齐标签」才是把信号做大的正确方向：短标签（改之前的五条居中 13 pt）
  在 +2% 下只有 1.47% → 1.50%，压根进不了红区；本 case（18 字 + 4 字、左对齐、
  10 pt）是 1.15% → 1.78%。
- 字号取 10 pt 而不是更大：宽度误差与标签总宽（受画布限制）相关，基线噪声与字号
  成正比，10 pt 上下是实测的最优区（8 pt 退化到 1.51×，13 pt 1.45×，10 pt 1.55×）。

阈值取在两组数之间、两侧各留 ~24% 余量：基线 1.15% < 1.4% < 1.78%。回归由
`tests/test_diff.py::test_two_percent_text_width_error_is_red` 守着，扰动方式与上表
一致（脚本为一次性验证，不进仓库）。

### PDF

- 不比对字节流（含压缩流）；只断言结构：无 `/Font`、内容流里有路径算子（度量账本 L2），
  以及页数/页面尺寸一致。

## 阈值分档（SIL-745 #3）

分档的**先量后定**过程是可复现的：`pixi run tiers:measure` 逐 case 量
`text_load`、墨量与实测差异，写 `docs/notes/snapshot-tiers.md`；
`pixi run tiers:check` 校验「声明的容差不超过所属档位上限」。

### 自变量：文本负载

```
text_load = Σ  len(text_i) × (font_size_i / 11px)²
```

它同时编码「文本节点数」与「字号相对默认 11pt 的倍数」，静态从 `expected.svg`
就能算出来（`tiers:check` 因此不需要光栅化，能挂进 `pixi run check`）。墨量
（非白像素占比）是同一件事的像素级观测，只作旁证写进表里。

选它的理由不是拍脑袋：M2-S1 把默认字面对齐到参考产线后，剩下的跨管线差异主要
落在**字形边缘**，边缘像素随「文字面积」增长；而几何差异与文字面积无关。所以
文字越多、字号越大的图，允许的图级差异才需要更宽。

### 档位

| 档位 | `text_load` | 图级上限 | 均值上限 | 当前 case 数 | 实测最大图级 | 实测最大均值 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `text-light` | ≤ 20 | **2.0%** | **1.0%** | 160 | 1.98% | 0.43% |
| `text-medium` | ≤ 200 | **2.0%** | **1.0%** | 22 | 1.69% | 0.53% |
| `text-heavy` | > 200 | 2.5% | 1.2% | 5 | 1.77% | 0.33% |

**这次不放宽任何东西**，三个数字说的就是这件事：

1. 187 条 case 里有 182 条落在 light / medium，实测最大 1.98%——2% 这个上限
   刚好够用，再宽就是放水；
2. 5 条 heavy（`base_size = 33` 的主题变体）实测最大 1.77%，按 2% 判也是绿，
   所以它们的 `tolerance` 仍写 `0.02`，没有用 2.5% 那一档；
3. 2.5% 只是 heavy 档的**上限**，留给将来字号更大的图；曾经需要它的三条
   实测 2.09–2.27% 的 `base_size = 33` 快照（`theme-bw-large` / `theme-classic-large`
   / `theme-linedraw-large`）超阈的原因是**实现缺口**——geom 缺省尺寸没跟
   `theme$pointsize` 走（4.0 的 `from_theme()`）。SIL-792 补上 `from_theme()` 后
   三条实测 0.86%–1.50%，按 2% 判绿，**没有**用分档把它们放绿。

### 硬约束

- 档位是上限，不是目标：每个 case 仍按 `meta.toml` 的 `tolerance` 判红。
- **均值门 1% 在所有档位都不放宽**（heavy 档的 1.2% 只是未启用的上限）。
- M1 的 61 条 case 全部在 light / medium，上限仍是 2% / 1%；`tiers:check` 会拦
  「声明超过档位上限」。
- 调档位本身是 PR：要同时更新 `tools/cases/snapshot_tiers.py` 的 `BANDS`、本节
  与 `docs/notes/snapshot-tiers.md`，并在 PR 里贴出 `tiers:measure` 前后两组数。

## 基线更新规则

- 只在“上游换 pin”或“渲染实现有意的口径变更”时更新，PR 描述里写清原因，附
  `pixi run diff` 报表与新旧图对照。
- 不允许为了让 CI 变绿而调大容差：容差改动本身是一个 PR，要写进本文件。
- 基线文件放 `docs/cases/<case>/baseline/`，命名 `<case>.<format>`，一个文件一个
  case，避免同名覆盖。

## 已定的事（M0-9 定案）

- 上游 SVG 是 grid 产物、我们是 skia SVG 设备产物，结构本就不同：**只比视觉**
  （两侧都光栅化成 PNG 后再比像素，`docs/notes/diff.md` §2）。结构 diff 不做——
  它只会把「同一张图、不同序列化」判红。
- **所有三文件 case 都按像素比**，`tolerance.svg` 删除。
- 311 份批量快照里有多少属于我们尚未实现的 geom：未实现的部分默认 `skip`，不让它
  变成“容差放水”的借口。
- 文本：`<text>` 在光栅化前转成字形轮廓（resvg 0.47 画不出 Noto CJK VF），宽度与
  位置仍取 R 写下的值；见 `docs/notes/diff.md` §2。
