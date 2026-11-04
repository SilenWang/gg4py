"""上游快照复刻：`all legend keys`（裸 gtable）。

源：`legend-draw/all-legend-keys.svg`

R：

    size <- convertUnit(calc_element("legend.key.size", theme_gray()), "cm") * 10  # mm
    keys <- list(point = draw_key_point(GeomPoint$use_defaults(NULL), list(), size), ...)
    template <- gtable(widths = unit(size, "mm"),
                       heights = unit(c(1, size), c("lines", "mm")))
    keys <- Map(function(key, name)
        gtable_add_grob(template, list(textGrob(name, gp = gpar(fontsize = 8)), key),
                        t = 1:2, l = 1, clip = "off"), key = keys, name = names(keys))
    mtx <- matrix(list(zeroGrob()), nrow = 4, ncol = 5)
    mtx[seq_along(keys)] <- keys
    gt <- gtable_matrix("layout", mtx, widths = unit(rep(size, 5), "mm"),
                        heights = unit(rep(size, 4), "mm") + unit(1, "lines"), clip = "off")
    gt <- gtable_add_col_space(gt, unit(1, "cm"))
    gt <- gtable_add_row_space(gt, unit(1, "cm"))
    plot(gt)

17 枚键按列优先填 4×5 的矩阵（第 5 列只剩 `timeseries` 一枚）。`plot(gt)` 不是
ggplot 对象，所以走 `{"gtable": …}` 契约；矩阵与 1cm 间隔在这里直接展开成
gtable 的行列（R 的 `gtable_matrix()` + `gtable_add_*_space()` 是同构的）。
"""

import math

from ggcore.grobs import text_grob
from ggcore.gtable import gtable, gtable_add_grob
from ggcore.legend_draw import (
    KeyGlyph,
    draw_key_abline,
    draw_key_blank,
    draw_key_boxplot,
    draw_key_crossbar,
    draw_key_dotplot,
    draw_key_label,
    draw_key_linerange,
    draw_key_path,
    draw_key_point,
    draw_key_pointrange,
    draw_key_polygon,
    draw_key_rect,
    draw_key_smooth,
    draw_key_text,
    draw_key_timeseries,
    draw_key_vline,
    draw_key_vpath,
)
from ggcore.theme import resolve_theme, theme_gray
from ggcore.units import UnitContext, convert_width, unit
from ggcore.viewport import gpar

SIZE_IN = (10.0, 8.0)
KEYS = (
    ("point", draw_key_point),
    ("abline", draw_key_abline),
    ("rect", draw_key_rect),
    ("polygon", draw_key_polygon),
    ("blank", draw_key_blank),
    ("boxplot", draw_key_boxplot),
    ("crossbar", draw_key_crossbar),
    ("path", draw_key_path),
    ("vpath", draw_key_vpath),
    ("dotplot", draw_key_dotplot),
    ("linerange", draw_key_linerange),
    ("pointrange", draw_key_pointrange),
    ("smooth", draw_key_smooth),
    ("text", draw_key_text),
    ("label", draw_key_label),
    ("vline", draw_key_vline),
    ("timeseries", draw_key_timeseries),
)
NCOL = 5


def _key_size_mm() -> float:
    """`convertUnit(calc_element("legend.key.size", theme_gray()), "cm") * 10`。"""
    theme = resolve_theme(theme_gray())
    return float(convert_width(theme.get("legend.key.size"), "cm", ctx=UnitContext())[0]) * 10.0


def build(metrics=None):
    size_mm = _key_size_mm()
    template = gtable(widths=[unit(size_mm, "mm")], heights=[unit(1, "lines"), unit(size_mm, "mm")])
    tiles = []
    for name, draw in KEYS:
        glyph = draw({}, {}, size_mm)
        grob = glyph.grob if isinstance(glyph, KeyGlyph) else glyph
        tiles.append(
            gtable_add_grob(
                template,
                [text_grob(name, 0.5, 0.5, gp=gpar(fontsize=8.0)), grob],
                t=[1, 2],
                l=[1, 1],
                clip="off",
            )
        )

    nrow = math.ceil(len(tiles) / NCOL)
    ncol = math.ceil(len(tiles) / nrow)
    widths = []
    for column in range(ncol):
        if column:
            widths.append(unit(1.0, "cm"))
        widths.append(unit(size_mm, "mm"))
    heights = []
    for row in range(nrow):
        if row:
            heights.append(unit(1.0, "cm"))
        heights.append(unit(size_mm, "mm") + unit(1, "lines"))
    gt = gtable(widths=widths, heights=heights, name="layout")
    # R 的 `matrix()` 按列优先填格：第 0 列放前 nrow 枚键。
    for index, tile in enumerate(tiles):
        row, column = index % nrow, index // nrow
        gt = gtable_add_grob(gt, tile, 2 * row + 1, 2 * column + 1, clip="off")
    return {"gtable": gt, "size": list(SIZE_IN)}
