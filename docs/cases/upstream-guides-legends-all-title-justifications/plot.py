from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_legend,
    guides,
    labs,
    scale_alpha,
)
from ggcore.theme import element_text, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2], "z": ["1", "2"]}


def build():
    p = (
        ggplot(
            to_column_table(DATA),
            aes(x="x", y="x", colour="z", fill="z", shape="z", alpha="x"),
        )
        + geom_point()
        + scale_alpha(breaks=(1, 2))
        + guides(
            colour=guide_legend(
                "colour title with hjust = 0",
                order=1,
                theme=theme(**{"legend.title": element_text(hjust=0)}),
            ),
            fill=guide_legend(
                "fill title with hjust = 1",
                order=2,
                theme=theme(
                    **{
                        "legend.title": element_text(hjust=1),
                        "legend.title.position": "bottom",
                    }
                ),
                override_aes={"shape": 21},
            ),
            alpha=guide_legend(
                "Title\nfor\nalpha\nwith\nvjust=0",
                order=3,
                theme=theme(
                    **{
                        "legend.title": element_text(vjust=0),
                        "legend.title.position": "left",
                    }
                ),
            ),
            shape=guide_legend(
                "Title\nfor\nshape\nwith\nvjust=1",
                order=4,
                theme=theme(
                    **{
                        "legend.title": element_text(vjust=1),
                        "legend.title.position": "right",
                    }
                ),
            ),
        )
        + theme_test()
        + labs(title="legends with all title justifications")
    )
    return {"plot": p, "size": [10, 8]}
