# 差分管线（M0-9）

「对错可判」的那条流水线：R 侧出参考 → 统一栅格 → 像素 diff → 报告。红绿由阈值
决定，不靠人眼看图。

```
tools/refs/cases_ref.R          docs/cases/<case>/expected.svg
  (R 4.5.3 + ggplot2 4.0.3          │
   + svglite, UTF-8 locale)         │
                                    ▼
                     ggdiff.svgtext（<text> → 字形轮廓）
                                    │
        our side: plot.py → ggcore.plotspec → IR → ggskia SVG
                                    │
                                    ▼
                         resvg --dpi 72（两侧同一光栅器）
                                    │
                                    ▼
                 像素 diff → diff_report.md + diff_heatmap.png
                              + --json（矩阵与下游只认它）
```

## 1. 参考图只有 R 一个来源

`pixi run -e refs refs:cases` 跑 `tools/refs/cases_ref.R`：

- **ggplot2 必须 4.0.3**（与 `docs/notes/upstream.md` 的 pin 同版本），脚本里硬断言；
- **UTF-8 locale**（`LC_ALL=C.UTF-8`）：C locale 下 R 把中文当字节串，svglite 会画成
  一行 `.`——参考图会「看起来有字、实际是点」；
- 四张图：散点、柱状、中文标签、曲线。每张都是 `theme_void()` + 显式 limits +
  `expand = c(0, 0)`，面板就是整页；没有轴、图例、边距，位置与
  `src/ggcore/plotspec.py` 的适配层一一对应；
- 产物入库（`expected.svg`），CI 不装 R。换 pin / 改口径才重跑。

案例的 `meta.toml` 必须写清来源，例如
`source = "svglite:ggplot2 4.0.3 (R 4.5.3, svglite 2.2.2)"`。

`ci = true` 的 case **只认 `upstream:` / `svglite:` 前缀**：`source = local` 的自录
基线会让「基线 == 当前输出」自洽地永远绿，SIL-638 的 curve 镜像与 lwd 偏差就是
这么漏掉的。闸门在 `tools/cases/matrix.py` 的契约校验里（硬要求 1）。

## 2. 统一栅格：resvg，两侧同一套

参考图（svglite：`<text>` + `<circle>`）与实测图（skia SVG 设备：字形轮廓 + 路径）
结构不同，像素 diff 之前必须落到同一张位图上。**两侧都由 resvg 光栅化**：

```bash
resvg --dpi 72 --skip-system-fonts --use-fonts-dir $CONDA_PREFIX/fonts in.svg out.png
```

- `--dpi 72`：1 pt = 1 px。svglite 写 `width='288pt'`，我们的 SVG 写 `width='288'`
  用户单位（也按 pt 解释），两侧都是 288×216 px；
- `--skip-system-fonts` + pixi 受管字体目录：换机器不换字形。

### 为什么还要把 `<text>` 转成路径

resvg 0.47 **画不出** pixi 的 `NotoSansCJKsc-VF.ttf`（36 MB / 65535 字形）：同一份
SVG，`<text font-family="Noto Sans CJK SC">` 出来是**空白**，而 subset 过的同字体、
DejaVu、`Noto Sans SC`（静态 OTF）都正常。不处理的话，中文基准图的参考是白纸，
「比字」变成「比空白」——正是这条流水线要消灭的东西。

`ggdiff.svgtext.inline_text_paths()` 在光栅化前把 `<text>` 就地换成 `<path>`：

- `x` / `y` / `text-anchor` 决定起点，`y` 是 alphabetic 基线；
- `textLength` + `lengthAdjust="spacingAndGlyphs"` 按同一比例缩放字形与步进，
  **宽度与位置仍以 R 写下的值为准**；
- 字形轮廓来自 `ggskia.text.TextShaper`（与设备同一份字体栈、同一套 cmap/hinting），
  所以轮廓与实测图同源；两侧的度量差异不会被这一步掩盖（反而正是 diff 要比的）；
- 用内联 `style="fill: …; stroke: none"`：svglite 的 `<style>` 里
  `.svglite path { fill: none; stroke: #000 }` 优先级高于 `fill` 属性，只写 `fill`
  会把字形画成描边轮廓。

## 3. 判据：图级 2%，平均 1%

| 指标 | 定义 | 默认阈值 |
| --- | --- | --- |
| 图级差异 `image_diff_fraction` | 单像素**最大通道绝对差 > 4/255** 的像素 / 全部像素 | ≤ 2% |
| 平均差异 `mean_diff` | `mean(|a − b|) / 255`（全通道） | ≤ 1% |

两个都满足才判绿。前者抓「位置/结构错了」，后者抓「整片轻微偏色」——单像素阈值
以下的均匀偏差只有平均差异看得到。尺寸不一致直接判红（不缩放比对：缩放会把
「画错位置」变成「看着差不多」）。

与 X4 的关系（`docs/notes/snapshot-policy.md`）：X4 的 0.1% / 4-per-255 是**同一
管线自产基线**的回归口径（grob 快照等）；跨管线（R svglite → resvg vs 我们 → resvg）
的参考图用 **2% / 1%** 的门。两者都写进了 `snapshot-policy.md`，不混用。
案例可以在 `meta.toml` 里用 `tolerance = { png = 0.005 }` 收紧图级阈值（只会更严）。

**所有 case 都按像素比**：`tolerance.svg` 已删除（`meta.toml` 里出现即契约错）。
`expected.svg` 与 `expected.png` 都先落到 PNG 再比，渲染格式由 `expected.*` 的
后缀决定（硬要求 2）。

## 4. `pixi run diff`：契约与结构化输出

```bash
# 三文件 case：expected.* vs <case>/current/*
pixi run diff docs/cases/geom-point-basic --json \
    --report docs/cases/geom-point-basic/current/diff_report.md

# 两个文件
pixi run diff expected.svg current/geom-point-basic.svg --json
```

退出码：`0` 通过；`1` 超容差；`2` 用法 / IO / 光栅化错误。`--json` 时 stdout 只有
一份 JSON（人读摘要走 stderr）：

```json
{
  "verdict": "pass",
  "ok": true,
  "image_diff_fraction": 0.0011,
  "mean_diff": 0.0001,
  "diff_pixels": 69,
  "total_pixels": 62208,
  "width": 288,
  "height": 216,
  "max_channel_diff": 111,
  "thresholds": {"image_diff_fraction": 0.02, "mean_diff": 0.01, "pixel_threshold": 4},
  "reason": "",
  "reference": "...",
  "actual": "...",
  "heatmap": ".../diff_report_heatmap.png",
  "report": ".../diff_report.md"
}
```

错误也走同一形状（`{"verdict": "error", "ok": false, "reason": "..."}`），矩阵因此
不需要解析人读文本（硬要求 3）。

报告默认写在 `docs/cases/<case>/diff_report.md`，热图同目录 `diff_heatmap.png`
（不入库，`.gitignore` 已列）；矩阵显式传 `<case>/current/diff_report.md`，与渲染
产物放一起。热图把参考图压成 25% 灰，差异像素按差值强度着红。

## 5. 矩阵接线

`tools/cases/matrix.py` 的 `TaskBackend` 是唯一接线点：

```bash
pixi run render <case-dir> --format <expected 后缀> --out <case-dir>/current
pixi run diff <case-dir> --report <case-dir>/current/diff_report.md --json [--tolerance …]
```

- `render` 现在真的支持 case 目录：`plot.py` → `ggcore.plotspec` → IR → 设备，
  文件名 `<case>.<format>`（M0-8 的 `--scene` 入口不变）；
- `diff` 的百分比从 JSON 读，写进 `report.md` 的「差多少」与 `report.json` 的
  `cases[].metrics`。

`report.json` 的机读结论是四态（硬要求 5）：`pass` / `empty` / `pending` / `fail`，
`ok` 只在 `pass` 时为 true——0 个 case 的空跑与 pending 都不会被下游当成绿。
`--strict` 下 pending 计为失败，`report.md` / `--summary` 的结论文字同步写红，不会再
出现「退出 1 但写全部绿」（硬要求 6）。

## 6. 基准图与验收记录

| case | 正确实现 | 平移 (2,2) px |
| --- | --- | --- |
| `geom-point-basic` | 图级 1.12% / 均值 0.17% → 绿 | 2.33% → **红** |
| `geom-col-basic` | 0.00% / 0.00% → 绿 | 6.15% → **红** |
| `geom-text-cjk` | 1.47% / 0.25% → 绿 | 2.31% → **红** |
| `geom-curve-basic` | 0.02% / 0.00% → 绿 | 2.70% → **红** |

数字随字体/resvg 版本略有浮动；`pixi run cases:matrix` 是唯一入口。

**负向验证（集成级）**：把 `ggskia/skia.py::_draw_curve` 的 y 翻转改回「直喂页面
坐标」的镜像版，`geom-curve-basic` 的图级差异升到 **2.99%**，`pixi run cases:matrix`
判红并退出 1。这正是 SIL-636 的 curve 镜像 bug 在案例库这一层的回归保护。

## 7. 已知限制

- **图级差异的分母是整张画布**。稀疏图（几个点）平移 2 px 的差异本来就不到 2%，
  所以基准图要有足够的墨：散点铺满面板、文本 13 pt 五条、柱子占满宽度。这不是
  阈值松，是画面本来就没多少信息——真要放宽得改阈值（走 issue），不能调 case
  去凑。
- 文本的**竖直基线**来自两端的字体度量：R 的 systemfonts 与 skia 的 hinted
  metrics 差 0.3–0.5 px，这是 `geom-text-cjk` 那 1.47% 的主要来源，不是错位。
- `inline_text_paths` 只处理 svglite 会写的那几种属性；`<tspan>` 等复杂结构原样
  留给 resvg（画不出来就红，不静默忽略）。
- 渐变、图案、彩色 emoji 不在 M0 的判据里（设备本身也不支持，见
  `docs/notes/device.md` §9）。

## 8. 复现

```bash
pixi run -e refs refs:cases     # 重生成参考 SVG（只在换 pin / 改口径时）
pixi run cases:matrix           # 扫描 + 渲染 + diff + 报告（CI job 走这条）
pixi run cases:matrix --summary # ≤60 行的短版本（GHA step summary）
pixi run diff docs/cases/geom-point-basic --json
pixi run test                   # 含 tests/test_diff.py / tests/test_plotspec.py
```
