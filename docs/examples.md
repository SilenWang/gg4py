# 示例图

`examples/` 下每个目录是一张图：一个只依赖 gg4py 自己的 `plot.py`，加上它画出来的
PNG 与 SVG（都入库）。目录名就是任务名后缀：

```bash
pixi run examples:heatmap            # 重画 examples/heatmap/{heatmap.png,heatmap.svg}
```

约定：

- **只用本体能力**，不引入第三方绘图包（shapely / patchwork / ggrepel / circlize …）；
- 数据在脚本里生成或内联，不下载外部数据文件；
- 产物确定性：同一份输入重跑，PNG / SVG 逐字节相同（`sha256sum -c` 可验）；
- PNG 宽度 ≤ 1200 px、单张 ≤ 300 KB，供 README 引用；SVG 是同一张图的矢量版。

下面六张参考图都是 ggplot2 画的。规则是「现在能做到的画出来，做不到的写清缺什么」，
不做等价物之外的替代、不为了凑数放宽标准。

| # | 参考 | 结果 |
| --- | --- | --- |
| 1 | [Chord diagram](https://www.data-to-viz.com/graph/chord.html) | **跳过**：本体没有弦图布局（见 §2.1） |
| 2 | [Bump plot](https://r-graph-gallery.com/409-customize-bump-plot.html) | [`examples/bump-chart/`](../examples/bump-chart/) |
| 3 | [Circular barplot with groups](https://r-graph-gallery.com/297-circular-barplot-with-groups.html) | [`examples/circular-barplot/`](../examples/circular-barplot/) |
| 4 | [Heatmap](https://r-graph-gallery.com/215-the-heatmap-function.html) | [`examples/heatmap/`](../examples/heatmap/) |
| 5 | [Scatterplot matrix](https://r-graph-gallery.com/99-scatterplot-matrix-car-package.html) | **跳过**：`car::scatterplotMatrix` / patchwork 是第三方，facet 拼不成（见 §2.2） |
| 6 | [Mirrored density](https://r-graph-gallery.com/density_mirror_ggplot2.html) | [`examples/mirrored-density/`](../examples/mirrored-density/) |

## 1. 做出来的四张

### 1.1 热图（`geom_tile`）

`examples/heatmap/plot.py` —— 12 个月 × 8 年的合成气温：正弦季节曲线 + 每年
+0.45 °C + 固定种子噪声。`geom_tile(colour = "white")` 画格子，`scale_fill_viridis_c()`
上渐变，图例标题用 `labs(fill = "°C")`。参考图是 base R 的 `heatmap()`，这里对等的是
ggplot2 的写法。

用到：`geom_tile` / `scale_fill_viridis_c` / 离散 x、y 轴 / 图例。

### 1.2 排名变化图（bump chart）

`examples/bump-chart/plot.py` —— 六个对象六年的名次表（手写，不用随机数）。
`geom_line()` + `geom_point()`，`scale_y_reverse()` 把第 1 名翻到顶部，
`scale_x_continuous(breaks = )` 钉住年份刻度。

参考图用 `ggbump` 画弯头连线；弯头是那个包的几何，本体不提供，这里用直连线 ——
信息（谁超过谁、哪些线交叉）完全一致。

用到：`geom_line` / `geom_point` / `scale_y_reverse` / `scale_x_continuous` / 颜色图例。

### 1.3 分组环形柱状图（`coord_polar`）

`examples/circular-barplot/plot.py` —— 4 组 × 6 根柱子。柱子排在一条**连续**的 x 上，
组与组之间留一个空位，再整体 `coord_polar()` 卷成圆环；组间空位就是那个「gap」。
参考图还带一圈标签，标签要按角度算 `hjust`/`angle`，属于手工排版，这里不画。

用到：`geom_col` / `coord_polar` / `theme_void` / 填充图例。

### 1.4 镜像密度图（`after_stat` 取负）

`examples/mirrored-density/plot.py` —— 两段正态样本共用一条 y = 0 的基线：一组用
`aes(y = after_stat("density"))` 画在上方，另一组用 `after_stat("-density")` 画在
下方。负号在 aes 表达式里是合法的一元运算，所以不需要预计算密度。

用到：`geom_density` / `after_stat` / 一元负号 / `annotate("text")`。

## 2. 跳过的两张

### 2.1 Chord diagram

- **参考**：<https://www.data-to-viz.com/graph/chord.html>（`circlize::chordDiagram`）
- **缺什么**：弦图是一套**布局算法**，不是某个几何：按流量给每个类别分角度、
  算扇区内的顺序与 gap、把每对流量画成两端带弧度的 ribbon（贝塞尔带状区域）。
  本体只有直角坐标的 `geom_ribbon(ymin, ymax)` 和路径/多边形；`coord_polar` 能把
  弧与路径卷成圆，但「按流量分配角度 + 面积加权 ribbon」要自己算——那等于把
  `circlize` 抄一遍，不是本体能力。
- **实跑**：`dir(gg4py)` 里没有任何 chord 相关入口（只有 `geom_ribbon`）；
  用 `geom_path` 手算弧与贝塞尔弦，再 `coord_equal()` 能画出「一段弧 + 一条弦」的
  线，但弦的**带状**部分（两条贝塞尔之间围出的面积）需要手搓多边形顶点。
- **归口**：SIL-715（扩展 geom / 多图版式族，与 #10、#11 相邻）；M3 的组合布局项。
- **现在怎么写**：类别间的流量用 `geom_tile` 画关系矩阵；两组之间的一对一流向用
  `geom_curve(arrow = )` 画有向弧线（直角坐标下），信息在、圆环版式没有。

### 2.2 Scatterplot matrix

- **参考**：<https://r-graph-gallery.com/99-scatterplot-matrix-car-package.html>
  （`car::scatterplotMatrix`，或用 patchwork 拼）
- **缺什么**：一张 `p × p` 的矩阵版式：对角线放每个变量的密度、非对角线放两两散点，
  行列表头写在外侧，轴只留外圈。几何本身不难（两层数据各画一半），缺的是**版式**——
  本体没有多图组合入口（patchwork 的等价物），`facet_wrap` 只能给出「等宽等高的面板 +
  每面自带 strip 与刻度」。
- **实跑**（结论：能跑，但不是这张图）：把两两组合摊成长表，用
  `facet_wrap("panel", ncol = 3, scales = "free")` 让每个面板各有 x/y 标度，
  再用一个只含对角数据的 `geom_density(aes(y = after_stat("density")))` 图层补对角线——
  渲染是通过的（Scatterplot matrix 的对角密度、非对角散点都出来了）。问题在版式：
  面板标题只能是合成列的字面值（`"a|a"` 这种），没有行列外侧标签；面板顺序由分面列
  的 level 顺序决定（多图层时按层内出现顺序拼接，所以对角面被排到了最后一行），
  只能靠构造数据的顺序去凑；9 个面板各自带刻度，是一张「拼起来的小图」，不是
  `scatterplotMatrix`。按 2026-11-04 的裁定，仍归为跳过。
- **归口**：SIL-715 #10（多图版面组合）+ M3-1。
- **现在怎么写**：两个变量直接散点；要看多变量分布就 `facet_wrap` 按某个分组变量
  分面（每面一张小散点），不做矩阵版式。

## 3. 建示例时暴露的缺口

这两条不是本 issue 的修复范围（`src/` 不改），登记归口，示例里绕开。

1. **`theme_void()` + `legend.position = "bottom"` 会把面板压出页面**：版式没给
   底部图例留高度，图例叠在面板上、墨迹一直画到图片最后一行。
   复现：任一 `ggplot(...) + geom_col() + theme_void() + theme(**{"legend.position": "bottom"})`，
   出图后量墨迹包围盒（`ys.max()` 等于图片高度）。polar 与直角坐标都复现，右置图例
   正常。`examples/circular-barplot` 因此把图例放在右侧。
   归口：SIL-715（主题/版式族）。
2. **`facet_wrap` 的面板顺序取决于分面列的 level 顺序**：单个数据源时按升序，多图层
   时按层内出现顺序拼接，所以上面 §2.2 的矩阵排不出 `a|a, a|b …` 的行优先顺序，只能
   靠构造数据顺序去凑。归口：SIL-715 / facet 版式。
