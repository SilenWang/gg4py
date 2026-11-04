"""上游快照复刻：`axis guides, text dodged into rows/cols`（裸 gtable）。

源：`guide-axis/axis-guides-text-dodged-into-rows-cols.svg`

R：

    test_draw_axis(10, labels = function(b) comma(b * 1e9), n.dodge = 2)

`test_draw_axis()` 用 `draw_axis()` 拼四条轴，塞进 `gtable(widths = c(0.05, 0.9,
0.05) npc)` 的 (2,2) 格再 `plot()`——不是 ggplot 对象，所以 case 走 `{"gtable": …}`
契约。`n.dodge = 2` 让 10 个标签分两行（奇数下、偶数上一行）。
"""

from ggcore.axis_guide import draw_axis
from ggcore.grobs import g_tree
from ggcore.gtable import CellBox, gtable, gtable_add_grob
from ggcore.theme import element_line, merge_theme, resolve_theme, theme, theme_test
from ggcore.units import CM_PER_INCH, unit

SIZE_IN = (10.0, 8.0)
BREAKS = tuple(index / 11 for index in range(1, 11))
LABELS = tuple(f"{index * 1_000_000_000:,}" for index in range(1, 11))
SIDES = ("top", "right", "bottom", "left")


def build(metrics=None):
    resolved = resolve_theme(
        merge_theme(theme_test(), theme(**{"axis.line": element_line(linewidth=0.5)}))
    )
    page_cm = (SIZE_IN[0] * CM_PER_INCH, SIZE_IN[1] * CM_PER_INCH)
    gt = gtable(
        widths=[unit(0.05, "npc"), unit(0.9, "npc"), unit(0.05, "npc")],
        heights=[unit(0.05, "npc"), unit(0.9, "npc"), unit(0.05, "npc")],
    )
    region = gt.region_box(2, 2, 2, 2, width_cm=page_cm[0], height_cm=page_cm[1])
    cell = CellBox(2, 2, 2, 2, 0.0, 0.0, region.width_cm, region.height_cm)
    grobs = [
        grob
        for side in SIDES
        for grob in draw_axis(
            resolved,
            side,
            BREAKS,
            LABELS,
            box=cell,
            n_dodge=2,
            metrics=metrics,
            name=f"axis-{side}",
        )
    ]
    gt = gtable_add_grob(gt, g_tree(*grobs), 2, 2, clip="off")
    return {"gtable": gt, "size": list(SIZE_IN)}
