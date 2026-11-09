# gg4py 使用指南

面向「要用 gg4py 画图」的人：一页一个模块，**每段代码都能直接跑**。代码块由
`pixi run docs:guide` 逐块执行（新命名空间 + 临时目录），构图期才失败的示例同样
判红，所以这里出现的接口都是在仓库里跑通过的。

与 `docs/notes/` 的分工：

| 目录 | 回答什么 | 例子 |
| --- | --- | --- |
| `docs/guide/`（本目录） | **怎么用**：写什么代码、参数在哪、和 R 怎么对应 | `geom_point(size=3)` 是毫米还是像素 |
| `docs/notes/` | **为什么这样实现**：口径、差异、对拍账本 | `size` 为什么按 `mm × .pt` 折算 |

## 页面

| 页面 | 模块 | 内容 |
| --- | --- | --- |
| [`r-to-python.md`](r-to-python.md) | 迁移 | R → Python 对照表：函数、参数、写法、第三方扩展的等价写法 |
| [`browser.md`](browser.md) | 浏览器 | 在浏览器编辑器里写 `gg4py` 代码：代码契约、数据面板、导出 |
| [`aes.md`](aes.md) | `aes` | 映射：表达式、常量、`after_stat()`、分组、图层级映射 |
| [`data.md`](data.md) | 输入 | dict / pandas / Arrow → 一张列式表；类型、分类顺序、日期、缺失 |
| [`layers.md`](layers.md) | `ggplot` + `Layer` | 用 `+` 加图层、克隆语义、方法链别名、图层自带数据与映射 |
| [`geom.md`](geom.md) | `geom_*` | 51 个几何对象：点线面、区间、文本、2D 族、sf |
| [`stat.md`](stat.md) | `stat_*` | 统计变换：bin / count / boxplot / smooth / density / qq / summary … |
| [`position.md`](position.md) | `position_*` | 堆叠 / 填充 / 并排 / 抖动 / 微移 |
| [`scale.md`](scale.md) | `scale_*` | 位置与颜色标度：limits / breaks / labels / trans / 色板 |
| [`coord.md`](coord.md) | `coord_*` | 笛卡尔 / 等比例 / 翻转 / 变换 / 极坐标 / 放射 / sf / 地图 |
| [`facet.md`](facet.md) | `facet_*` | `facet_wrap` / `facet_grid`：布局、自由标度、标签 |
| [`guide.md`](guide.md) | `guide_*` | 图例与主轴：legend / colourbar / bins / axis / 无图例 |
| [`theme.md`](theme.md) | `theme_*` | 主题：元素树、`theme()`、`element_*()`、全局默认 |
| [`annotation.md`](annotation.md) | 注释 | `annotate()`、`annotation_logticks()`、`annotation_borders()` |
| [`sf.md`](sf.md) | 空间数据 | `geom_sf` 族、`coord_sf`、`coord_map`、CRS 与经纬网 |
| [`export.md`](export.md) | 导出 | `ggsave` → PNG / SVG / PDF、IR、脚本执行 |

## 十分钟：第一张图

```python
from gg4py import aes, geom_point, ggplot, ggsave, labs, theme_minimal, to_column_table

DATA = {
    "wt": [1.9, 2.6, 3.2, 3.5, 4.1],
    "mpg": [31.0, 26.0, 21.0, 18.0, 15.0],
}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="wt", y="mpg"))
    + geom_point(size=3)
    + labs(title="First plot", x="weight (1000 lbs)", y="miles per gallon")
    + theme_minimal()
)
ggsave(p, "first-plot.png", width=6, height=4, dpi=150)  # 900×600 px
```

`p` 是**语法对象**：它只记下数据、映射与组件，不出图。落盘走 `ggsave()`（按后缀
选设备：`.png` / `.svg` / `.pdf`），也可以从命令行画案例模块：

```bash
pixi run ggsave examples/heatmap/plot.py:plot my-first-plot.png
```

（上面那段 `ggsave` 在 `docs:guide` 里也会真跑一次，产物写在临时目录。）

三个必须先知道的约定：

1. **数据要先变成 `ColumnTable`**。`ggcore` 只认 `ggcore.data.ColumnTable`；
   dict / pandas / Arrow 用 `gg4py.to_column_table()` 转换（见
   [`data.md`](data.md)）。直接 `ggplot(dict, ...)` 能构造，但构图期会报错。
2. **`aes()` 的值是字符串表达式**，不是变量名：`aes(x="wt")`（R 的
   `aes(x = wt)`）。字符串常量要再包一层引号：`aes(colour="'red'")`。
3. **`+` 返回新对象**，`p` 本身不变。`p + geom_point()` 与 `p.geom_point()` 等价
   （同一个注册表，见 [`layers.md`](layers.md)）。

## 文档门禁

```bash
pixi run docs:guide          # 逐块执行 docs/guide 的示例，打印每块的结果
pixi run docs:guide:check    # 同上，只打汇总；挂在 `pixi run check` 里
```

判定标准：代码块执行不抛错；如果它定义了 `build()` 或留下 `plot` / `p` 变量，
还要走完 `ggcore.plotspec.build_scene()` → `ggcore.ir.encode()`（真构图、真编码），
否则算失败。刻意不执行的对照片段在代码块前一行写 `<!-- no-run: 原因 -->`。

## 兼容基线

语法、默认值与几何口径钉在 **ggplot2 4.0.3**（commit
`cc1444c10edb87650fbe0cb31d56f0da1a255634`）。已知未实现的接口与等价写法见
[`r-to-python.md`](r-to-python.md) 的「缺口」一节，以及
[`../notes/api-coverage.md`](../notes/api-coverage.md)。
