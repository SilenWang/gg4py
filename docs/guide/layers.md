# 图层：`ggplot()` 与 `+`

一张图 = `ggplot(data, mapping)` + 一串组件（图层、标度、坐标、分面、图例、主题、
标签）。`+` 是**纯函数**：返回新对象，原对象不变。所有字段可以直接读。

## 1. 构造

| 参数 | 含义 | 缺省 |
| --- | --- | --- |
| `data` | `ColumnTable`（见 [`data.md`](data.md)） | `None`（图层自带数据时必须给） |
| `mapping` | `aes(...)`，被所有图层继承 | 空 |
| `layers` / `scales` / `guides` / `theme` / `coordinates` / `facet` / `labels` | 组件容器 | 空 / `theme_get()` / `coord_cartesian()` / `facet_null()` |
| `position` | plot 级默认位置调整（gg4py 保留字段） | `None` |

不认识的 kwarg 直接报错（拼错字段名不会带着空字段一路走到深层）。

## 2. `+` 的克隆语义

```python
from gg4py import aes, geom_line, geom_point, ggplot, labs, theme_minimal, to_column_table

DATA = {"x": [1, 2, 3, 4], "y": [1.0, 2.5, 2.0, 4.0], "g": ["a", "a", "b", "b"]}

base = ggplot(to_column_table(DATA), aes(x="x", y="y"))
points = base + geom_point(size=2.5)
full = points + geom_line(aes(colour="g")) + labs(title="+ returns a new plot")

print(len(base.layers), len(points.layers), len(full.layers))  # 0 1 2
print(repr(full))  # <ggplot: data=4×3, layers=2, mapping=[x, y]>
```

- 可变容器（`layers` / `scales` / `guides` / `labels`）复制一份；不可变值
  （`data` 引用、`Aes`、组件对象）原样共享。
- `p + None` 是空操作（仍返回新对象），用于条件式拼装。
- 图层按**添加顺序**绘制：后加的画在上面。

## 3. 方法链别名

注册表里的每个组件函数同时也是 `ggplot` 的方法，二者查同一张注册表：

```python
from gg4py import aes, geom_point, ggplot, labs, to_column_table

DATA = {"x": [1, 2, 3], "y": [3, 1, 2]}
data = to_column_table(DATA)

a = ggplot(data, aes(x="x", y="y")) + geom_point(size=3) + labs(title="operators")
p = ggplot(data, aes(x="x", y="y")).geom_point(size=3).labs(title="methods")

print(type(a) is type(p), len(a.layers) == len(p.layers))  # True True
```

推荐 `+`（与 ggplot2 写法一致，也是本项目规定的规范写法）；方法链是同一注册表的
别名，适合动态拼接。

## 4. 一次加多张图

```python
from gg4py import aes, geom_point, geom_smooth, ggplot, labs, theme_minimal, to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6],
    "y": [1.0, 2.6, 2.1, 4.2, 3.9, 5.4],
    "g": ["a", "a", "b", "b", "c", "c"],
}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="x", y="y"))
    + geom_point(size=2.5)
    + geom_smooth(method="lm", se=True)  # 拟合线 + 置信带
    + geom_point(aes(colour="g"), size=1.8, data=to_column_table(DATA))  # 再叠一层
    + labs(title="several layers, added in order", x="x", y="y")
    + theme_minimal()
)
```

同一层加两次是允许的（比如「先画大点做底、再画小点做高光」）；组件的 `+` 顺序
决定 z 序，也决定图例合并顺序。

## 5. 组件类别

| 加到图上的东西 | 类型 | 生效方式 |
| --- | --- | --- |
| `geom_*()` / `stat_*()` / `Layer` | 图层 | 追加到 `layers` |
| `scale_*()` | 标度 | 按美学键覆盖 `scales[键]` |
| `theme_*()` / `theme()` | 主题 | 完整主题整份替换；局部主题逐元素合并 |
| `coord_*()` | 坐标 | 替换 `coordinates`（只留一个） |
| `facet_*()` | 分面 | 替换 `facet` |
| `guide_*()` / `guides()` | 图例 | 覆盖/更新 `guides` |
| `labs()` | 标签 | 合并进 `labels` |
| `annotate()` / `annotation_logticks()` | 注记 | 追加到 `annotations`（不走图层流水线） |
| `position_*()` | 位置 | 记成 plot 级默认，真正的层位置在 `Layer.position` |

`+` 不认识的类型会报错并列可用类别；`p + 3` 这类拼错不会静默成功。

## 6. 逐 geom 改缺省值

`update_geom_defaults()` 改的是**注册表里的缺省**，之后新建的图层都跟着变：

```python
from gg4py import aes, geom_point, ggplot, labs, to_column_table, update_geom_defaults

DATA = {"x": [1, 2, 3], "y": [3, 1, 2]}

update_geom_defaults("point", aes(colour="#E45756", size=4))
try:
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + labs(title="new point defaults")
    )
finally:
    update_geom_defaults("point", None)  # 恢复内置缺省（示例不污染后面的图）
```

传 `None` 恢复内置缺省；未知美学名或未知 geom 名直接报错。
