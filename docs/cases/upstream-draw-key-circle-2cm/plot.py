"""Scratch: draw-key/circle-glyphs-of-2cm-size."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _fixtures import mtcars

from ggcore.grobs import circle_grob
from ggcore.legend_draw import KeyGlyph
from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {
    "mpg": mtcars["mpg"],
    "wt": mtcars["wt"],
    "cyl": [str(value) for value in mtcars["cyl"]],
}


def draw_key_dummy(values, params, size):
    del values, params, size
    return KeyGlyph(circle_grob(r=unit(1.0, "cm")), width_cm=2.0, height_cm=2.0)


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="mpg", y="wt", colour="cyl"))
        + geom_point(key_glyph=draw_key_dummy)
        + theme_test()
        + labs(title="circle glyphs of 2cm size")
    )
    return {"plot": p, "size": [10, 8]}
