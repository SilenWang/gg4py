"""上游快照复刻：lines, changed order, should have same appearance。

源：`geom-path/lines-changed-order-should-have-same-appearance.svg`。`test-geom-path.R` 的
"geom_path draws correctly"（vdiffr 名 `lines, changed order, should have same appearance`）。

R：

    set.seed(1)
    df <- data_frame(category = rep(LETTERS[1:5], 1, each = 6),
                     item = paste("Item#", rep(1:6, 5, each = 1), sep = ''),
                     value = rep(1:6, 5, each = 1) + runif(30) * 0.8)
    df2 <- df[c(1, 2, 7, 8, 13, 14, 3:6, 9:12, 15:nrow(df)), ]
    ggplot(df2) + geom_path(aes(x = value, y = category, group = item))
"""

from ggcore.plot import aes, geom_path, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

#: R 4.5.3 `set.seed(1); rep(1:6, 5, each = 1) + runif(30) * 0.8` 的逐值结果。
VALUE = [
    1.21240693051368,
    2.2976991197094323,
    3.4582826906815169,
    4.7265662319958208,
    5.161345544829965,
    6.7187117479741572,
    1.7557402148842813,
    2.5286382339894771,
    3.5032912351191046,
    4.0494290163740514,
    5.1647796599194411,
    6.1412454020231966,
    1.5496182773262261,
    2.3072829745709895,
    3.6158731359988452,
    4.3981593936681751,
    5.5740948066115381,
    6.7935248758643869,
    1.3040281435474754,
    2.6219561770558357,
    3.7477641848847272,
    4.1697140170261262,
    5.5213390128687028,
    6.1004440767690538,
    1.2137765349820255,
    2.308891274034977,
    3.0107122665271162,
    4.3059103656560183,
    5.695752676576376,
    6.2722791973501444,
]

_ORDER = [0, 1, 6, 7, 12, 13, 2, 3, 4, 5, 8, 9, 10, 11, *range(14, 30)]
_CATEGORY = [letter for letter in "ABCDE" for _ in range(6)]
_ITEM = [f"Item#{index}" for index in range(1, 7)] * 5
DAT = {
    "category": [_CATEGORY[index] for index in _ORDER],
    "item": [_ITEM[index] for index in _ORDER],
    "value": [VALUE[index] for index in _ORDER],
}


def build():
    p = (
        ggplot(
            to_column_table(DAT),
            aes(x="value", y="category", group="item"),
        )
        + geom_path()
        + theme_test()
        + labs(title="lines, changed order, should have same appearance")
    )
    return {"plot": p, "size": [10, 8]}
