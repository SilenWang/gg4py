"""上游快照复刻：`axis guides, check overlap`（裸 gtable，grid 直画）。

源：`guide-axis/axis-guides-check-overlap.svg`

R：

    theme_test_axis <- theme_test() + theme(axis.line = element_line(linewidth = 0.5))
    axes <- lapply(c("top", "right", "bottom", "left"), function(position) {
      draw_axis(seq_len(20) / 21, comma(seq_len(20) * 1e9),
                axis_position = position, theme = theme_test_axis,
                check.overlap = TRUE)
    })
    gt <- gtable(widths = unit(c(0.05, 0.9, 0.05), "npc"),
                 heights = unit(c(0.05, 0.9, 0.05), "npc"))
    gt <- gtable_add_grob(gt, list(gTree(children = do.call(gList, axes))), 2, 2, clip = "off")
    plot(gt)

`plot(gt)` 不是 ggplot 对象，页面就是 10 × 8 in 的设备，四条轴画在中间那格
（页面的 5%..95%）。`draw_axis()` 的 `check.overlap` 按标签的**真实字宽**决定
保留哪些标签，所以 `build()` 走 `metrics=` 拿设备的字体度量。
"""

from ggcore.axis_guide import draw_axis
from ggcore.grobs import g_tree
from ggcore.gtable import CellBox, gtable, gtable_add_grob
from ggcore.theme import element_line, merge_theme, resolve_theme, theme, theme_test
from ggcore.units import CM_PER_INCH, unit

SIZE_IN = (10.0, 8.0)
BREAKS = tuple(index / 21 for index in range(1, 21))
LABELS = tuple(f"{index * 1_000_000_000:,}" for index in range(1, 21))
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
    # 中间那格（R 的 2,2）就是四条轴的视口；在单元格自己的坐标里从左下角起算。
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
            check_overlap=True,
            metrics=metrics,
            name=f"axis-{side}",
        )
    ]
    gt = gtable_add_grob(gt, g_tree(*grobs), 2, 2, clip="off")
    return {"gtable": gt, "size": list(SIZE_IN)}
