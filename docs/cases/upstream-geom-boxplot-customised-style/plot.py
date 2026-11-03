"""上游快照复刻：customised style（geom-boxplot/customised-style.svg）。

源：`test-geom-boxplot.R` 的 "boxplot draws correctly"（vdiffr 名 `customised style`）。

R：

    ggplot(mpg, aes(class, displ, colour = class)) +
      geom_boxplot(outlier.shape = 6, whisker.linetype = 2, median.colour = "red",
                   box.colour = "black", staple.linewidth = 1, staplewidth = 0.25)

`mpg` 的 class / cty / hwy / displ 四列按 R 4.5.3 逐行内联（234 行；4.0.3 里
`class` 是 character，离散水平按字母序）。
"""

from ggcore.plot import aes, geom_boxplot, ggplot, labs
from ggcore.theme import theme_test
from ggio.frame import to_column_table

RAW = """\
compact 18 29 1.8
compact 21 29 1.8
compact 20 31 2
compact 21 30 2
compact 16 26 2.8
compact 18 26 2.8
compact 18 27 3.1
compact 18 26 1.8
compact 16 25 1.8
compact 20 28 2
compact 19 27 2
compact 15 25 2.8
compact 17 25 2.8
compact 17 25 3.1
compact 15 25 3.1
midsize 15 24 2.8
midsize 17 25 3.1
midsize 16 23 4.2
suv 14 20 5.3
suv 11 15 5.3
suv 14 20 5.3
suv 13 17 5.7
suv 12 17 6
2seater 16 26 5.7
2seater 15 23 5.7
2seater 16 26 6.2
2seater 15 25 6.2
2seater 15 24 7
suv 14 19 5.3
suv 11 14 5.3
suv 11 15 5.7
suv 14 17 6.5
midsize 19 27 2.4
midsize 22 30 2.4
midsize 18 26 3.1
midsize 18 29 3.5
midsize 17 26 3.6
minivan 18 24 2.4
minivan 17 24 3
minivan 16 22 3.3
minivan 16 22 3.3
minivan 17 24 3.3
minivan 17 24 3.3
minivan 11 17 3.3
minivan 15 22 3.8
minivan 15 21 3.8
minivan 16 23 3.8
minivan 16 23 4
pickup 15 19 3.7
pickup 14 18 3.7
pickup 13 17 3.9
pickup 14 17 3.9
pickup 14 19 4.7
pickup 14 19 4.7
pickup 9 12 4.7
pickup 11 17 5.2
pickup 11 15 5.2
suv 13 17 3.9
suv 13 17 4.7
suv 9 12 4.7
suv 13 17 4.7
suv 11 16 5.2
suv 13 18 5.7
suv 11 15 5.9
pickup 12 16 4.7
pickup 9 12 4.7
pickup 13 17 4.7
pickup 13 17 4.7
pickup 12 16 4.7
pickup 9 12 4.7
pickup 11 15 5.2
pickup 11 16 5.2
pickup 13 17 5.7
pickup 11 15 5.9
suv 11 17 4.6
suv 11 17 5.4
suv 12 18 5.4
suv 14 17 4
suv 15 19 4
suv 14 17 4
suv 13 19 4
suv 13 19 4.6
suv 13 17 5
pickup 14 17 4.2
pickup 14 17 4.2
pickup 13 16 4.6
pickup 13 16 4.6
pickup 13 17 4.6
pickup 11 15 5.4
pickup 13 17 5.4
subcompact 18 26 3.8
subcompact 18 25 3.8
subcompact 17 26 4
subcompact 16 24 4
subcompact 15 21 4.6
subcompact 15 22 4.6
subcompact 15 23 4.6
subcompact 15 22 4.6
subcompact 14 20 5.4
subcompact 28 33 1.6
subcompact 24 32 1.6
subcompact 25 32 1.6
subcompact 23 29 1.6
subcompact 24 32 1.6
subcompact 26 34 1.8
subcompact 25 36 1.8
subcompact 24 36 1.8
subcompact 21 29 2
midsize 18 26 2.4
midsize 18 27 2.4
midsize 21 30 2.4
midsize 21 31 2.4
midsize 18 26 2.5
midsize 18 26 2.5
midsize 19 28 3.3
subcompact 19 26 2
subcompact 19 29 2
subcompact 20 28 2
subcompact 20 27 2
subcompact 17 24 2.7
subcompact 16 24 2.7
subcompact 17 24 2.7
suv 17 22 3
suv 15 19 3.7
suv 15 20 4
suv 14 17 4.7
suv 9 12 4.7
suv 14 19 4.7
suv 13 18 5.7
suv 11 14 6.1
suv 11 15 4
suv 12 18 4.2
suv 12 18 4.4
suv 11 15 4.6
suv 11 17 5.4
suv 11 16 5.4
suv 12 18 5.4
suv 14 17 4
suv 13 19 4
suv 13 19 4.6
suv 13 17 5
compact 21 29 2.4
compact 19 27 2.4
midsize 23 31 2.5
midsize 23 32 2.5
midsize 19 27 3.5
midsize 19 26 3.5
midsize 18 26 3
midsize 19 25 3
midsize 19 25 3.5
suv 14 17 3.3
suv 15 17 3.3
suv 14 20 4
suv 12 18 5.6
midsize 18 26 3.1
midsize 16 26 3.8
midsize 17 27 3.8
midsize 18 28 3.8
midsize 16 25 5.3
suv 18 25 2.5
suv 18 24 2.5
suv 20 27 2.5
suv 19 25 2.5
suv 20 26 2.5
suv 18 23 2.5
subcompact 21 26 2.2
subcompact 19 26 2.2
subcompact 19 26 2.5
subcompact 19 26 2.5
compact 20 25 2.5
compact 20 27 2.5
compact 19 25 2.5
compact 20 27 2.5
suv 15 20 2.7
suv 16 20 2.7
suv 15 19 3.4
suv 15 17 3.4
suv 16 20 4
suv 14 17 4.7
midsize 21 29 2.2
midsize 21 27 2.2
midsize 21 31 2.4
midsize 21 31 2.4
midsize 18 26 3
midsize 18 26 3
midsize 19 28 3.5
compact 21 27 2.2
compact 21 29 2.2
compact 21 31 2.4
compact 22 31 2.4
compact 18 26 3
compact 18 26 3
compact 18 27 3.3
compact 24 30 1.8
compact 24 33 1.8
compact 26 35 1.8
compact 28 37 1.8
compact 26 35 1.8
suv 11 15 4.7
suv 13 18 5.7
pickup 15 20 2.7
pickup 16 20 2.7
pickup 17 22 2.7
pickup 15 17 3.4
pickup 15 19 3.4
pickup 15 18 4
pickup 16 20 4
compact 21 29 2
compact 19 26 2
compact 21 29 2
compact 22 29 2
compact 17 24 2.8
compact 33 44 1.9
compact 21 29 2
compact 19 26 2
compact 22 29 2
compact 21 29 2
compact 21 29 2.5
compact 21 29 2.5
compact 16 23 2.8
compact 17 24 2.8
subcompact 35 44 1.9
subcompact 29 41 1.9
subcompact 21 29 2
subcompact 19 26 2
subcompact 20 28 2.5
subcompact 20 29 2.5
midsize 21 29 1.8
midsize 18 29 1.8
midsize 19 28 2
midsize 21 29 2
midsize 16 26 2.8
midsize 18 26 2.8
midsize 17 26 3.6
"""

_ROWS = [line.split() for line in RAW.splitlines()]

DAT = {
    "cls": [row[0] for row in _ROWS],
    "displ": [float(row[3]) for row in _ROWS],
}


def build():
    p = (
        ggplot(to_column_table(DAT), aes(x="cls", y="displ", colour="cls"))
        + geom_boxplot(
            outlier_shape=6,
            whisker_linetype=2,
            median_colour="red",
            box_colour="black",
            staple_linewidth=1,
            staplewidth=0.25,
        )
        + theme_test()
        + labs(title="customised style")
    )
    return {"plot": p, "size": [10, 8]}
