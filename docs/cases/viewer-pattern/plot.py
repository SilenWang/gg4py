"""SVG 渲染器：**平铺图案**填充（SIL-751）。

pattern 的 tile 是 12% × 12% 的包围盒（npc 口径，以包围盒中心对齐），内容为
「浅底 + 左侧 40% 红色竖条」。竖条在 x 方向不对称，相位错一点点就会在像素上
看出来，所以这条 case 同时守 tile 尺寸、原点与内容坐标。

内容按**包围盒 npc** 摆（SIL-833）：R 的 `pattern()` 内容以被填充 grob 的 bbox
折 npc，tile 只决定裁剪窗口与重复周期。
"""

from ggcore.fills import Box, pattern_npc_rect
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

#: tile 宽 = 30 pt（= 包围盒宽 261 pt 的 30/261）、高 = 包围盒的 12%。
TW = 30 / 261
TH = 0.12


def draw(bbox: Box) -> list:
    """`rectGrob(x = 0.5, y = 0.5, width = tw, height = th)` + 左侧 40% 竖条。"""
    return [
        pattern_npc_rect(bbox, 0.5, 0.5, TW, TH, "#F4F1EA"),
        pattern_npc_rect(bbox, 0.5 - TW / 2 + 0.4 * TW / 2, 0.5, 0.4 * TW, TH, "#E45756"),
    ]


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cls", y="v"))
        + geom_col(
            fill=tile_pattern(draw, width=TW, height=TH, x=0.5, y=0.5, extend="repeat"),
            colour=None,
        )
        + scale_x_discrete()
        + scale_y_continuous(limits=(0, 1), expand=(0, 0))
        + theme_void()
        + theme(**{"legend.position": "none"})
    )
    return {"plot": p, "size": SIZE}
