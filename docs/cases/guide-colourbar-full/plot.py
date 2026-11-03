"""guide：colourbar 全量参数（nbin=8 rectangles、标题在左、刻度/边框颜色、draw.ulim=FALSE）。"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    scale_x_continuous,
    scale_y_continuous,
    theme_void,
)
from ggcore.theme import element_line, element_rect, theme
from ggio.frame import to_column_table

DATA = {
    "x": [0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75],
    "y": [0.20, 0.50, 0.35, 0.70, 0.45, 0.80, 0.60, 0.85, 0.15],
    "v": [0.00, 0.12, 0.25, 0.38, 0.50, 0.62, 0.75, 0.88, 1.00],
}
SIZE = [4, 3]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="v"))
        + geom_point(shape=19, size=3.2)
        + guide_colourbar(
            "colour",
            nbin=8,
            display="rectangles",
            draw_ulim=False,
            title_position="left",
            ticks_colour="#3366CC",
            frame_colour="#666666",
        )
        + theme_void()
        + theme(
            **{
                "legend.frame": element_rect(colour="#666666", linewidth=0.5),
                "legend.ticks": element_line(colour="#3366CC"),
            }
        )
        + scale_x_continuous(limits=(0, 1), expand=(0, 0))
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
    )
    return {"plot": p, "size": SIZE}
