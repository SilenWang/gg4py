# 快照容差与参考图纳管（X4）

M0 的比对对象有三类，用途不同，**不能混用容差**：

| 类别 | 来源 | 入库 | 用途 |
| --- | --- | --- | --- |
| 上游参考图 | ggplot2 `v4.0.3` 的 314 份 SVG 快照 | 否（脚本按需拉取） | 判定“我们画得像不像” |
| 自产基线 | 我们自己的渲染产物 | 是（`docs/cases/<case>/baseline/`） | 判定“我们有没有改坏” |
| 临时产物 | 每次 `pixi run render` 的输出 | 否（`.gitignore`） | 人眼看图 |

## 为什么上游快照不入库

SVG 是派生资产：上游一换 pin 就整批失效，进 git 只会制造大 diff 和冲突。拉取
由脚本按 `docs/notes/upstream.md` 的 commit 取，落到 `docs/cases/<case>/expected/`
（已在 `.gitignore` 里忽略），CI 不依赖它。自产基线相反：它就是回归判据，必须
跟着代码走，更新走 PR 且 PR 里贴出 diff 截图。

目录约定见 `docs/cases/README.md`。

## 案例库的 `expected.svg|png`（M0-11）

三文件 case（`plot.py` + `expected.svg|png` + `meta.toml`）里那一张 `expected.*`
与上面的 314 份批量快照**不是一回事**：

- 每个 case 只留一张，是该 case 的判据，**允许入库**（它和生产代码一样要被 review）；
- 来源写在 `meta.toml` 的 `source`（`upstream:<路径>` / `svglite:<R + 版本>`），
  换 pin 时随同 PR 换掉这一张；
- 314 份批量快照仍按上面的策略按需拉取，`docs/cases/*/expected/` 继续忽略。

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

### PDF

- 不比对字节流（含压缩流）；只断言结构：无 `/Font`、内容流里有路径算子（度量账本 L2），
  以及页数/页面尺寸一致。

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
- 314 份批量快照里有多少属于我们尚未实现的 geom：未实现的部分默认 `skip`，不让它
  变成“容差放水”的借口。
- 文本：`<text>` 在光栅化前转成字形轮廓（resvg 0.47 画不出 Noto CJK VF），宽度与
  位置仍取 R 写下的值；见 `docs/notes/diff.md` §2。
