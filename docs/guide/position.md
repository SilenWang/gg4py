# `position_*`：位置调整

position 在 stat 之后、标度映射之前改坐标：堆叠、填充、并排、抖动、微移。图层上用
`position=` 指定，也可以用字符串简写。

| position | 字符串简写 | 作用 |
| --- | --- | --- |
| `position_identity()` | `"identity"` | 不动（点、线、文本的缺省） |
| `position_stack()` | `"stack"` | 堆叠（柱、面积的缺省） |
| `position_fill()` | `"fill"` | 堆叠并归一化到 1（百分比） |
| `position_dodge()` | `"dodge"` | 并排；`width=0.9`、`preserve="total"` |
| `position_dodge2()` | `"dodge2"` | 并排且居中；`padding=`、`preserve="single"`（箱线缺省） |
| `position_jitter()` | `"jitter"` | 随机抖动；`width=` / `height=` / `seed=` |
| `position_jitterdodge()` | `"jitterdodge"` | 并排 + 抖动；`jitter_width=` / `jitter_height=` / `dodge_width=` |
| `position_nudge()` | `"nudge"` | 固定微移；`x=` / `y=`（文本缺省） |

## 1. 堆叠与百分比

```python
from ggcore.plot import aes, geom_col, ggplot, labs, position_fill, position_stack
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "year": ["2019", "2019", "2019", "2020", "2020", "2020"],
    "kind": ["a", "b", "c", "a", "b", "c"],
    "n": [12.0, 8.0, 5.0, 15.0, 10.0, 9.0],
}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="year", y="n", fill="kind"))
    + geom_col(position=position_stack(), width=0.7)
    + labs(title="position_stack()", x="year", y="n")
    + theme_minimal()
)
```

```python
from ggcore.plot import aes, geom_col, ggplot, labs, position_fill
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "year": ["2019", "2019", "2019", "2020", "2020", "2020"],
    "kind": ["a", "b", "c", "a", "b", "c"],
    "n": [12.0, 8.0, 5.0, 15.0, 10.0, 9.0],
}

p = (
    ggplot(to_column_table(DATA), aes(x="year", y="n", fill="kind"))
    + geom_col(position="fill", width=0.7)
    + labs(title="position = 'fill'（每根柱归一到 1）", x="year", y="proportion")
    + theme_minimal()
)
```

`position_stack(vjust=)` 能调标签位置；堆叠顺序由分组水平的顺序决定（离散列的
levels，见 [`data.md`](data.md) §2）。

## 2. 并排

```python
from ggcore.plot import aes, geom_col, ggplot, labs, position_dodge
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "class": ["compact", "compact", "midsize", "midsize", "suv", "suv"],
    "year": ["1999", "2008", "1999", "2008", "1999", "2008"],
    "n": [12.0, 14.0, 9.0, 11.0, 15.0, 18.0],
}

p = (
    ggplot(to_column_table(DATA), aes(x="class", y="n", fill="year"))
    + geom_col(position=position_dodge(width=0.85), width=0.8)
    + labs(title="position_dodge(width = 0.85)", x="class", y="n")
    + theme_minimal()
)
```

`position_dodge2()` 与 `position_dodge()` 的差别与上游一致：`dodge2` 在组宽不等时
把每个柱**居中**在自己的槽里，`padding=` 控制槽内留白；`geom_boxplot()` 的缺省
position 就是 `position_dodge2()`。

## 3. 抖动

`geom_jitter()` 是 `geom_point(position=position_jitter(...))` 的简写：

```python
from ggcore.plot import aes, geom_jitter, geom_point, ggplot, labs, position_jitter
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {
    "class": ["compact"] * 6 + ["midsize"] * 6,
    "value": [1.9, 2.1, 2.4, 2.2, 2.6, 2.3, 2.6, 3.0, 3.2, 2.9, 3.4, 3.1],
}

data = to_column_table(DATA)
p = (
    ggplot(data, aes(x="class", y="value"))
    + geom_point(size=2.2, colour="#4C78A8", alpha=0.5)
    + geom_jitter(width=0.12, height=0.02, size=1.6, colour="#E45756")
    + labs(title="geom_jitter(width, height)", x="class", y="value")
    + theme_minimal()
)
```

要可复现就给 `position_jitter(seed=42)`；`geom_jitter(width=, height=)` 与
`position=` 同时给是显式错误（上游同样报错）。

`position_jitterdodge()` 把点按 `fill` 分组并排后再抖动，常用于柱 + 点的叠加：

```python
from ggcore.plot import aes, geom_col, geom_point, ggplot, labs, position_jitterdodge
from ggio.frame import to_column_table

DATA = {
    "class": ["compact", "compact", "midsize", "midsize"],
    "kind": ["a", "b", "a", "b"],
    "value": [2.4, 1.9, 3.2, 2.6],
}

p = (
    ggplot(to_column_table(DATA), aes(x="class", y="value", fill="kind"))
    + geom_col(position="dodge", width=0.7, alpha=0.6)
    + geom_point(position=position_jitterdodge(jitter_width=0.08, dodge_width=0.7), size=2.4)
    + labs(title="position_jitterdodge()", x="class", y="value")
)
```

## 4. 微移

`position_nudge()` 按数据坐标平移（文本 / 标签的缺省 position，所以
`geom_text(nudge_x=, nudge_y=)` 直接可用）：

```python
from ggcore.plot import aes, geom_col, geom_text, ggplot, labs, position_nudge
from ggcore.theme import theme_minimal
from ggio.frame import to_column_table

DATA = {"class": ["a", "b", "c"], "n": [3.0, 5.0, 4.0]}

p = (
    ggplot(to_column_table(DATA), aes(x="class", y="n", label="n"))
    + geom_col(fill="#4C78A8", width=0.6)
    + geom_text(position=position_nudge(y=0.25), size=3.6)
    + labs(title="position_nudge(y = 0.25)", x="class", y="n")
    + theme_minimal()
)
```

## 5. 与上游的差异

- `p + position_dodge()`（把 position 直接加到图对象上）在 gg4py 里记录成 plot 级
  默认位置，**不改已有图层的 `Layer.position`**——真正被流水线读取的是图层自己
  的那一份。上游 4.0.3 对这种写法直接报错。
- `position_jitterdodge()` 的参数名把 R 的点号换成下划线（`jitter.width` →
  `jitter_width`，`dodge.width` → `dodge_width`）。
- 抖动的随机源是 numpy 的 `Generator`；要用固定序列就给 `seed=`。
