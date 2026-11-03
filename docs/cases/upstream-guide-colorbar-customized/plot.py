from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    labs,
    scale_colour_gradient,
)
from ggcore.theme import element_line, element_rect, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0, 1, 2]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", colour="x"))
        + geom_point()
        + scale_colour_gradient(
            low="white",
            high="red",
            guide=guide_colourbar(
                theme=theme(
                    **{
                        "legend.frame": element_rect(colour="green", linewidth=1.5 / 2.845276),
                        "legend.ticks": element_line("black", linewidth=2.5 / 2.845276),
                        "legend.ticks.length": unit((0.2, 0.4), "npc"),
                    }
                ),
                alpha=0.75,
            ),
        )
        + theme_test()
        + labs(
            title="customized colorbar",
            subtitle="white-to-red semitransparent colorbar, long thick black ticks, green frame",
        )
    )
    return {"plot": p, "size": [10, 8]}
