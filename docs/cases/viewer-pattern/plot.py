"""SVG 渲染器：**平铺图案**填充（SIL-751）。

pattern 的 tile 是 12% × 12% 的包围盒（npc 口径，以包围盒中心对齐），内容为
「浅底 + 左侧 40% 红色竖条」。竖条在 x 方向不对称，相位错一点点就会在像素上
看出来，所以这条 case 同时守 tile 尺寸、原点与内容坐标。
"""

from ggcore.fills import pattern_rect
from ggcore.plot import (
    aes,
    geom_col,
    ggplot,
    scale_x_discrete,
    scale_y_continuous,
    theme_void,
    tile_pattern,
)
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {"cls": ["a", "b", "c"], "v": [0.35, 0.65, 0.90]}

SIZE = [4, 3]


def draw(tile: tuple[float, float, float, float]) -> list:
    """tile 窗口在节点局部坐标里；内容按同一个坐标系摆（`userSpaceOnUse`）。"""
    x0, y0, x1, y1 = tile
    stripe = x0 + 0.4 * (x1 - x0)
    return [
        pattern_rect(tile, "#F4F1EA"),
        pattern_rect((x0, y0, stripe, y1), "#E45756"),
    ]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_col(
            fill=tile_pattern(draw, width=30 / 261, height=0.12, x=0.5, y=0.5, extend="repeat"),
            colour=None,
        )
        + scale_x_discrete()
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}
