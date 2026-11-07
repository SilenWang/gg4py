# 收尾账（SIL-865）

> 这是一份**人能读的收尾账**：M0–M3 收口之后，哪些东西确实交付了、哪些缺陷是我们
> 明确接受的、哪些上游能力刻意不做、哪些还缺且指向任务。每条结论都附了可复现的
> 命令与输出片段；复核时不必读 issue 历史。
>
> 台账口径：上游 pin `cc1444c1`（ggplot2 4.0.3）的 311 份 SVG 快照；案例阈值
> 图级 2% / 均值 1%（`report` 档 5% / 1%，白名单 `matrix-report-*`）；不放宽阈值、
> 不删既有 case。

## 0. 一键复核

```bash
pixi run snapshots:check        # snapshots total=311 imported=311 gaps=0
pixi run api:coverage:check     # TOTAL 283/285 public 99.3%  gaps (2): geom_freqpoly, stat_density2d_filled
pixi run tiers:check            # 声明容差不超过档位上限
pixi run cases:matrix:check     # 案例契约 + 矩阵新鲜度
pixi run audit:gallery          # 35/35 符合登记
pixi run check                  # 全量门禁
```

## 1. 已交付

| 资产 | 现状 | 证据 |
| --- | --- | --- |
| 上游快照 | **311/311 纳管，缺口 0** | `pixi run snapshots:check` → `snapshots total=311 imported=311 gaps=0` |
| API 覆盖 | **283/285 = 99.3%**（registry 90.9%） | `pixi run api:coverage:check` → `gaps (2): geom_freqpoly, stat_density2d_filled` |
| 案例库 | `docs/cases` 下 548 个目录，矩阵识别 **529 条合法 case**；`ci = false` **0 条**（SIL-870 删掉重复目录后） | `git ls-tree -d --name-only HEAD docs/cases/ \| wc -l` = 548（干净树；`ls -d docs/cases/*/` 会多数出跑过用例后生成的 `__pycache__/`）；`pixi run cases:matrix` → `529 case(s)`；`grep -l '^ci = false' docs/cases/*/meta.toml \| wc -l` = 0 |
| gallery 35 图 | 27 ✅ + 2 ⚠️ = 29/35 可画；6 张第三方扩展（刻意不做） | `pixi run audit:gallery` → `35/35 符合登记`；逐张见 `docs/notes/gallery-audit.md` |
| 三条曾经的 `ci = false` | **两条已转绿**，第三条是重复目录、已删（SIL-870） | 见下方实测 |
| SIL-715 缺口池 | 28 条全部定性：20 已修/已落地、5 刻意不做、3 仍缺 | 见 §5 |

三条 `ci = false` 的复查（都是本仓当前代码实测）：

```bash
pixi run render docs/cases/upstream-facet-wrap-omitted-inner-axis-labels --format svg --out /tmp/aud
pixi run diff docs/cases/upstream-facet-wrap-omitted-inner-axis-labels/expected.svg /tmp/aud/*.svg
# 图级 1.3549% / 平均 0.1876%（阈值 2% / 1%）→ ci = true，已进 CI

pixi run render docs/cases/upstream-theme-legends-all-sides --format svg --out /tmp/aud2
pixi run diff docs/cases/upstream-theme-legends-all-sides/expected.svg /tmp/aud2/*.svg
# 图级 1.4482% / 平均 0.6476% → ci = true，已进 CI
```

第三条 `upstream-guide-legend-legend-key-justification` 是 SIL-820 留下的旧 scratch
复现，与纳管 case `upstream-guide-legend-key-justification` 同源；后者 **0.9035% /
0.1122%** 且 `ci = true`，前者仍是 **10.2474% / 1.8273%**。它不指向
`snapshots.toml` 里的任何条目，属于重复目录——SIL-870 已把它删掉（`expected.svg`
与纳管 case 同字节，未丢参考图；它单独占用的 `guide-legend` 族登记一并撤掉，
`legend-key-justification` 特性改由纳管 case 标注，矩阵缺口仍为 0）。

`matrix-report-facet-polar-grey` 也已进 CI：SIL-839 把 r/theta 断点改走面板范围后
从 8.54% / 1.30% 收到 **4.45% / 0.94%**（report 档 5% / 1%）。

## 2. 已知缺陷（接受）

这些是当前**接受**的差异，不排修复任务；触发条件写清楚，换口径时回来复看。

| 缺陷 | 量级 / 现状 | 为什么接受 | 依据 |
| --- | --- | --- | --- |
| 文本竖直基线 | R 的 `strheight` 与 skia ascent/descent 差 0.032 em（10 pt ≈ 0.32 px，13 pt ≈ 0.42 px） | 低于 2% / 1% 判据；逐 case 偏移补偿属于掩盖 | `docs/notes/diff.md` §7 |
| 字符间 kerning | 线性推进，不建模 kerning，差 <0.25% | 与 R 的 grid 同口径（R 也不做 kerning） | `docs/notes/device.md` §9 · M1-e |
| 稀疏图的判据盲区 | 几个点的 2 px 平移不到 2% | 判据分母是整张画布；基准图改用「墨量足够」的图 | `docs/notes/diff.md` §7 |
| 彩色 emoji | 矢量后端回落单色 Noto Emoji 轮廓；栅格用彩色位图 | 上游 svglite 也是单色；彩色位图只在 PNG 需要 | `docs/notes/device.md` §9 · M1-c |
| `geom_text(check_overlap=)` 无独立像素 case | 实现存在（`src/ggcore/geom/text.py:534`），轴标题的 `check_overlap` 有 case | 行为已被轴 guide 的 `upstream-guide-axis-check-overlap` 间接覆盖 | `pixi run render docs/cases/text-multiline` → 1.3391% / 0.2964% |
| `scripts/exit_report.py` 的手工对拍图 | 旧记录 20.98% / 3.78%，不是 CI case | 同类 2×2 facet + legend + labs + `theme_grey` 的图已由 `matrix-report-facet-wrap-grey` 覆盖（1.95% / 0.38%）；手工图文本节点已从 34 降到 **22**（与 R 相同） | `pixi run python scripts/exit_report.py` + IR 遍历 |

## 3. 刻意不做（含依据）

| 项 | 依据 |
| --- | --- |
| patchwork / cowplot / ggrepel / ggforce / ggstream / ggExtra / ggraph / treemapify 的同名 API | 2026-11-04 决策：只复刻 ggplot2 本体；gallery 的 6 张图给本体等价写法，见 `docs/notes/gallery-audit.md` §4 / §6。覆盖 SIL-715 #10 / #11 / #12 |
| PROJ 全量投影 | `coord_sf` 只做 4326 / CRS84 / 3857 / 3347 + graticule；其余投影需要 PROJ，X1 不引入。SIL-715 #14 |
| `geom_area` 无 `orientation` 时的横向推断 | R 4.0.3 的 `GeomArea$setup_params()` 传 `ambiguous = TRUE`，没有显式 orientation 时**永远竖向**；本仓与上游一致。SIL-715 #4 |
| `xlim()` / `ylim()` / `lims()` 简写 | 上游有；本仓走 `coord_cartesian(xlim=, ylim=)` 或 `scale_*_continuous(limits=)`，迁移写法在 `docs/guide/r-to-python.md`。SIL-715 #15 |
| `gtable_row` / `gtable_col` / `gtable_matrix` / `gtable_filter` / `gtable_trim` / `rbind` / `cbind` | 这些是 gtable 包的公共 API，不在 ggplot2 的调用面；本仓只实现 ggplot2 用到的 gtable 子集 | `docs/notes/gtable.md` §「刻意不复制 / 不支持」 |
| `ggsave(units="px")`、`bg=`、`scale=`、`limitsize`、`path=` | 服务端无状态口径：背景走 `theme(plot.background=)`，目录自动创建，尺寸显式给 | `docs/notes/io.md` §3 / §7 |
| `Decimal` 输入 | 输入契约只认 `numbers.Real`；报错点名列与类型：`TypeError: 列 'x'：不支持的取值类型 Decimal(...)` | `docs/notes/data.md` §7，实测同上 |
| `palette.*` 主题元素 | 4.0.3 的内部调色板元素，不进元素树；`Theme(palette.colour.discrete=...)` 直接 `TypeError` | `docs/notes/theme.md` §「与 ggplot2 的刻意差异」第 5 条 |
| 非 hex 颜色名不全 | 只认 122 个常用名 + hex + 灰阶；其余报错不猜 | `src/ggcore/grobs.py` 的 `_NAMED_COLOURS`（122 项） |
| `clip = grob` / 任意形状 mask | `clip_path` 只做矩形；311 份快照没有覆盖 | `docs/notes/grobs.md` §11 |
| `grobWidth` / `grobHeight` 的完整泛型 | 本仓只有 18 个 grob 构造器，泛型只覆盖它们 | `docs/notes/grobs.md` §11 |
| 多页 PDF / 透明背景 / `last_plot()` 全局状态 | 一台设备一页、页面白底、无全局状态 | `docs/notes/io.md` §7、`docs/notes/device.md` §9 |

## 4. 仍缺（指向任务）

按影响面排序。7 条全部有独立任务，预估合计 **6.5–9 人日**。

| 排序 | 缺口 | 影响 | 任务 | 预估 |
| ---: | --- | --- | --- | ---: |
| 1 | 浏览器查看器 13 条 case 像素对拍失败（`geom-raster` 12 + `matrix-report-facet-polar-grey`）；`viewer:cases:ci` 抽样恰好绕开 | gallery 13 张卡片红；设备腿同 case 全过 | **SIL-867** | 2–3 人日 |
| 2 | skia SVG 后端不写 `stroke-dasharray`（SIL-715 #28） | 虚线退化成实线；dotplot lty case 与图例 key 7→2 | **SIL-868** | 0.5–1 人日 |
| 3 | `geom_freqpoly` / `stat_density2d_filled` 两个上游导出名缺失（SIL-715 #18 / #22） | API 覆盖 283/285，迁移时 ImportError | **SIL-866** | 1 人日 |
| 4 | `docs/notes/upstream-map.md`（X3）整体停在 M1 口径 | 读者会以为大量模块没做；review 误用 | **SIL-872** | 1 人日 |
| 5 | `facet_wrap(strip.position = bottom/left/right)` 直接报错 | 上游 API 面缺失；311 快照未覆盖 | **SIL-871** | 1–2 人日 |
| 6 | ~~`legend-key-justification` 重复 case（唯一 `ci = false`）~~ | ✅ 已收口（SIL-870 删除重复目录，529 条 case / 0 条 `ci = false`） | **SIL-870** | 0.5 人日 |
| 7 | viewer 不消费 `text.lineheight`（IR 已有字段） | 非缺省行距在 DOM SVG 丢失 | **SIL-869** | 0.5 人日 |

## 5. SIL-715 28 条逐条定性

「状态」只有四档：`已修`（指明 SIL/PR/commit）、`已随 M3 落地`、`裁定不做`（写依据）、
`仍缺`（必须指向 §4 的任务）。这张表与 SIL-715 的「状态总表」逐行一致。

| # | 缺口 | 状态 | 依据 |
| ---: | --- | --- | --- |
| 1 | `theme_grey()` 网格线 | 已修 | SIL-723 / PR #49 / `9643424`，1.8695% / 0.1597%，`ci = true` |
| 2 | `theme_minimal()` 网格线 | 已修 | 同上，1.8727% / 0.1623%，`ci = true` |
| 3 | 连续 colourbar 色阶 | 已修 | 同上，1.7409% / 0.3143%，`ci = true` |
| 4 | 横向 `geom_area` 自动方向 | 裁定不做 | R 4.0.3 传 `ambiguous = TRUE`，无 orientation 时永远竖向（`docs/notes/geom.md` §「横向推断」） |
| 5 | 横向 boxplot 自动方向 | 已修 | `GeomRenderer.setup_params()` 的离散分支（`src/ggcore/geom/base.py:346`）+ `BoxplotRenderer.detect_flipped = True` |
| 6 | 密集报告图 AA / 字体度量 | 已随 M3 落地 | 同类图由 `matrix-report-facet-wrap-grey` 1.95% / 0.38%、`-grid-grey` 1.75% / 0.38% 覆盖；`exit_report` 文本节点 34→22 = R |
| 7 | facet + 竖图例 + `labs` + 默认 expand 无 case | 已随 M3 落地 | `matrix-report-default-expand` / `matrix-report-facet-wrap-grey`（`docs/notes/snapshot-tiers.md`） |
| 8 | row-strip 列宽用文本高度近似 | 已修 | `_strip_extent()` 改真实 `stringWidth`，docstring 记 SIL-715 #8（`src/ggcore/facet.py:1909`） |
| 9 | `annotate()` 未实现 | 已随 M3 落地 | SIL-825：`annotate()` / `annotation_borders()` / `borders()`；`from ggcore.plot import annotate` 可用 |
| 10 | 多图版面组合（patchwork / ggExtra / inset） | 裁定不做 | 2026-11-04 决策 + `docs/notes/gallery-audit.md` §4 / §6 |
| 11 | 扩展 geom 生态（split violin / stream / dendrogram / treemap / network） | 裁定不做 | 同上 |
| 12 | 标签避让（ggrepel） | 裁定不做 | 同上；本体只有 `check_overlap` |
| 13 | 单水平离散 r 轴的 `coord_polar(theta="y")` | 已修 | M3-1：`fig16` 转 ✅（`docs/notes/gallery-audit.md` G5） |
| 14 | `coord_sf()` 真实投影 | 已随 M3 落地（PROJ 不做） | SIL-823/849：4326 / CRS84 / 3857 / 3347 + graticule，9/9 快照；其余投影需 PROJ |
| 15 | `xlim()` / `ylim()` 简写 | 裁定不做 | 迁移对照表给 `coord_cartesian(xlim=, ylim=)`（gallery-audit G7） |
| 16 | report 分面图网格线/文字 1px AA | 已随 M3 落地 | `matrix-report-facet-wrap-grey` 1.95% / 0.38%、`-grid-grey` 1.75% / 0.38%，进 CI |
| 17 | `theme_grey` 下极坐标面板尺寸 | 已随 M3 落地 | 23.99% → 8.54%（SIL-820）→ 4.45% / 0.94%（SIL-839，report 档，`ci = true`） |
| 18 | `geom_freqpoly` | 仍缺 | `pixi run api:coverage:check` → `gaps: geom_freqpoly`；`from ggcore.plot import geom_freqpoly` ImportError → SIL-866 |
| 19 | `geom_sf` | 已随 M3 落地 | `from ggcore.plot import geom_sf` 可用；M3-2，见 `docs/notes/sf.md` |
| 20 | `geom_sf_label` | 已随 M3 落地 | 同上 |
| 21 | `geom_sf_text` | 已随 M3 落地 | 同上 |
| 22 | `stat_density2d_filled` | 仍缺 | `registered("stat")` 里只有 base name `density_2d_filled`；导出名 `stat_density2d_filled` 不存在（`stat_density_2d_filled` 有）→ SIL-866 |
| 23 | `stat_sf` | 已随 M3 落地 | `from ggcore.plot import stat_sf` 可用 |
| 24 | `stat_sf_coordinates` | 已随 M3 落地 | `from ggcore.plot import stat_sf_coordinates` 可用 |
| 25 | `from_theme()` | 已随 M3 落地 | `src/ggcore/build.py:777` 的 `eval_from_theme`；`theme_*_large` 全部 ≤1.52% 进 CI |
| 26 | dotplot 的 bin 对齐 | 已修 | SIL-787 / PR #71，35 条 dotplot 全部纳管 |
| 27 | `theme(aspect.ratio=)` 版式 | 已随 M3 落地 | SIL-792：折进面板行权重 + `respect`，见 `docs/notes/facet.md` §7 |
| 28 | skia SVG 不序列化 dashed stroke | 仍缺 | 实测 expected 27 `<circle>` / 11 `stroke-dasharray`，实际 0 / 0 → SIL-868 |

统计：**已修 7**（#1 #2 #3 #5 #8 #13 #26）+ **已随 M3 落地 13**
（#6 #7 #9 #14 #16 #17 #19 #20 #21 #23 #24 #25 #27）= 20 条；
**裁定不做 5**（#4 #10 #11 #12 #15）；**仍缺 3**（#18 #22 #28）。合计 28。

## 6. 还剩什么

**一句话：内核与两条渲染腿已经对等收口（311/311、API 99.3%、案例 0 个未登记缺口），
剩下的是 13 张浏览器卡片的像素差、SVG 虚线、2 个 API 别名，以及 3 条版式/文档债。**

对应 §4 的任务（6 条在办，第 6 条已由 SIL-870 收口）；全部做完后重跑 §0 的命令即可复核，
不需要再读 issue 历史。
