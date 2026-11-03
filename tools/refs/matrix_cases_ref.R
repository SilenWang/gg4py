#!/usr/bin/env Rscript
#
# M2-11 组合矩阵（matrix-*）的参考图产线：ggplot2 4.0.3 + svglite，4 × 3 in。
#
#   pixi run -e refs refs:matrix-cases            # 全量
#   Rscript tools/refs/matrix_cases_ref.R <case>  # 只重画点名的 case
#
# 每个 case 与 `docs/cases/<case>/plot.py` 一一对应：同一份数据、同一组组件，
# 只是把分面 / 坐标 / 图例位置 / 排布方向 / 图例个数逐格组合。改一边必须改另一边，
# 再重跑 `pixi run -e refs refs:matrix-cases`。
#
# 与 `cases_battery_ref.R` / `coord_cases_ref.R` 分开：那两个是单点 case，
# 这里只产组合矩阵。产物只写 `expected.svg`，不重写任何历史参考图。

suppressPackageStartupMessages({
  library(ggplot2)
  library(svglite)
  library(jsonlite)
  library(grid)
})

if (!identical(as.character(packageVersion("ggplot2")), "4.0.3")) {
  stop(sprintf(
    "ggplot2 必须是 4.0.3（上游 pin），当前是 %s",
    as.character(packageVersion("ggplot2"))
  ))
}
if (!isTRUE(l10n_info()[["UTF-8"]])) {
  stop("R 不在 UTF-8 locale 下：用 LC_ALL=C.UTF-8 LANG=C.UTF-8 重跑")
}

repo <- normalizePath(".")
cases_dir <- file.path(repo, "docs", "cases")
only <- commandArgs(trailingOnly = TRUE)

# 不开默认绘图设备：否则 `ggplotGrob()` 会在 CWD 留下 Rplots.pdf（产物不可复现）。
invisible(pdf(NULL))

# --- 数据（与 plot.py 的 DATA 逐值相同） ------------------------------------

data_base <- data.frame(
  x = c(0.15, 0.45, 0.75, 0.20, 0.50, 0.80, 0.25, 0.55, 0.85, 0.30, 0.60, 0.90),
  y = c(0.35, 0.70, 0.50, 0.60, 0.25, 0.75, 0.40, 0.80, 0.55, 0.65, 0.30, 0.70),
  f = rep(c("a", "b", "c", "d"), each = 3),
  r = rep(c("t", "u"), each = 6),
  c = c("l", "l", "r", "r", "l", "l", "l", "l", "r", "r", "l", "r"),
  g = rep(c("p", "q"), 6),
  s = c("u", "u", "v", "v", "u", "v", "u", "v", "u", "v", "u", "v")
)

# 自由标度用：每个分面的 x / y 量级不同。
data_wide <- data.frame(
  x = c(0.10, 0.30, 0.60, 0.40, 0.70, 0.90, 10.0, 20.0, 30.0, 12.0, 25.0, 35.0),
  y = c(1.0, 3.0, 2.0, 2.0, 5.0, 4.0, 100.0, 300.0, 200.0, 150.0, 250.0, 180.0),
  f = data_base$f, r = data_base$r, c = data_base$c,
  g = data_base$g, s = data_base$s
)

COLOURS <- c(p = "#F8766D", q = "#00BA38")
SHAPES <- c(u = 16, v = 17)

# --- 组合器：与 plot.py 的 `build()` 同一条链 --------------------------------

build_plot <- function(spec) {
  df <- if (identical(spec$data, "wide")) data_wide else data_base
  if (spec$legends == 2L) {
    p <- ggplot(df, aes(x, y, colour = g, shape = s)) +
      geom_point(size = 2.4) +
      scale_colour_manual(values = COLOURS) +
      scale_shape_manual(values = SHAPES)
  } else {
    p <- ggplot(df, aes(x, y, colour = g)) +
      geom_point(shape = 19, size = 2.4) +
      scale_colour_manual(values = COLOURS)
  }
  if (identical(spec$expand, "fixed")) {
    p <- p +
      scale_x_continuous(limits = c(0, 1), expand = c(0, 0)) +
      scale_y_continuous(limits = c(0, 1), expand = c(0, 0))
  }
  p <- p + switch(spec$facet,
    none = NULL,
    wrap = facet_wrap(~ f, ncol = 2),
    grid = facet_grid(r ~ c),
    wrap_free_x = facet_wrap(~ f, ncol = 2, scales = "free_x"),
    wrap_free_y = facet_wrap(~ f, ncol = 2, scales = "free_y"),
    grid_free = facet_grid(r ~ c, scales = "free", space = "free"),
    grid_margins = facet_grid(r ~ c, margins = TRUE),
    grid_rows = facet_grid(r ~ .),
    stop(sprintf("未知 facet：%s", spec$facet))
  )
  if (!identical(spec$direction, "auto")) {
    dir <- spec$direction
    p <- if (spec$legends == 2L) {
      p + guides(colour = guide_legend(direction = dir),
                 shape = guide_legend(direction = dir))
    } else {
      p + guides(colour = guide_legend(direction = dir))
    }
  }
  p <- p + switch(spec$coord,
    cartesian = coord_cartesian(),
    flip = coord_flip(),
    polar = coord_polar(),
    trans = coord_trans(y = "sqrt"),
    radial = coord_radial(),
    stop(sprintf("未知 coord：%s", spec$coord))
  )
  if (isTRUE(spec$labs)) {
    p <- p + labs(title = "matrix", x = "x label", y = "y label")
  }
  p <- p + if (identical(spec$theme, "grey")) theme_grey() else theme_void()
  if (!identical(spec$legend, "none")) {
    p <- p + theme(legend.position = spec$legend)
  }
  p
}

# --- 规格表（与 docs/cases/matrix-*/plot.py 逐一对应） -----------------------

CASES <- list(
  list(
    name = "matrix-facet-wrap-coord-cartesian",
    coord = "cartesian", facet = "wrap", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-wrap-coord-flip",
    coord = "flip", facet = "wrap", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-wrap-coord-polar",
    coord = "polar", facet = "wrap", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-wrap-coord-trans",
    coord = "trans", facet = "wrap", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-wrap-coord-radial",
    coord = "radial", facet = "wrap", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-grid-coord-cartesian",
    coord = "cartesian", facet = "grid", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-grid-coord-flip",
    coord = "flip", facet = "grid", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-grid-coord-polar",
    coord = "polar", facet = "grid", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-grid-coord-trans",
    coord = "trans", facet = "grid", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-grid-coord-radial",
    coord = "radial", facet = "grid", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-right-vertical-single",
    coord = "cartesian", facet = "none", legend = "right",
    direction = "vertical", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-right-vertical-double",
    coord = "cartesian", facet = "none", legend = "right",
    direction = "vertical", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-right-horizontal-single",
    coord = "cartesian", facet = "none", legend = "right",
    direction = "horizontal", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-right-horizontal-double",
    coord = "cartesian", facet = "none", legend = "right",
    direction = "horizontal", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-left-vertical-single",
    coord = "cartesian", facet = "none", legend = "left",
    direction = "vertical", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-left-vertical-double",
    coord = "cartesian", facet = "none", legend = "left",
    direction = "vertical", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-left-horizontal-single",
    coord = "cartesian", facet = "none", legend = "left",
    direction = "horizontal", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-left-horizontal-double",
    coord = "cartesian", facet = "none", legend = "left",
    direction = "horizontal", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-top-vertical-single",
    coord = "cartesian", facet = "none", legend = "top",
    direction = "vertical", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-top-vertical-double",
    coord = "cartesian", facet = "none", legend = "top",
    direction = "vertical", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-top-horizontal-single",
    coord = "cartesian", facet = "none", legend = "top",
    direction = "horizontal", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-top-horizontal-double",
    coord = "cartesian", facet = "none", legend = "top",
    direction = "horizontal", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-bottom-vertical-single",
    coord = "cartesian", facet = "none", legend = "bottom",
    direction = "vertical", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-bottom-vertical-double",
    coord = "cartesian", facet = "none", legend = "bottom",
    direction = "vertical", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-bottom-horizontal-single",
    coord = "cartesian", facet = "none", legend = "bottom",
    direction = "horizontal", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-legend-bottom-horizontal-double",
    coord = "cartesian", facet = "none", legend = "bottom",
    direction = "horizontal", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-report-facet-wrap-grey",
    coord = "cartesian", facet = "wrap", legend = "right",
    direction = "auto", legends = 1L, labs = TRUE, theme = "grey",
    expand = "default", data = "base"
  ),
  list(
    name = "matrix-report-facet-grid-grey",
    coord = "cartesian", facet = "grid", legend = "right",
    direction = "auto", legends = 1L, labs = TRUE, theme = "grey",
    expand = "default", data = "base"
  ),
  list(
    name = "matrix-report-facet-polar-grey",
    coord = "polar", facet = "wrap", legend = "right",
    direction = "auto", legends = 1L, labs = TRUE, theme = "grey",
    expand = "default", data = "base"
  ),
  list(
    name = "matrix-report-default-expand",
    coord = "cartesian", facet = "none", legend = "right",
    direction = "auto", legends = 1L, labs = TRUE, theme = "grey",
    expand = "default", data = "base"
  ),
  list(
    name = "matrix-facet-polar-legend-right",
    coord = "polar", facet = "wrap", legend = "right",
    direction = "auto", legends = 1L, labs = TRUE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-polar-legend-bottom",
    coord = "polar", facet = "wrap", legend = "bottom",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-polar-legend-left",
    coord = "polar", facet = "grid", legend = "left",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-polar-legend-top-double",
    coord = "polar", facet = "wrap", legend = "top",
    direction = "horizontal", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-coord-flip-legend-top",
    coord = "flip", facet = "none", legend = "top",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-coord-flip-legend-right-double",
    coord = "flip", facet = "none", legend = "right",
    direction = "vertical", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-coord-trans-legend-bottom",
    coord = "trans", facet = "none", legend = "bottom",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-coord-trans-legend-left-horizontal",
    coord = "trans", facet = "none", legend = "left",
    direction = "horizontal", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-coord-radial-legend-bottom",
    coord = "radial", facet = "none", legend = "bottom",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-coord-radial-legend-right-double",
    coord = "radial", facet = "none", legend = "right",
    direction = "auto", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-coord-polar-legend-left",
    coord = "polar", facet = "none", legend = "left",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-coord-polar-legend-bottom-horizontal",
    coord = "polar", facet = "none", legend = "bottom",
    direction = "horizontal", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-wrap-free-x-flip-legend-right",
    coord = "flip", facet = "wrap_free_x", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "default", data = "wide"
  ),
  list(
    name = "matrix-facet-wrap-free-y-trans-legend-bottom",
    coord = "trans", facet = "wrap_free_y", legend = "bottom",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "default", data = "wide"
  ),
  list(
    name = "matrix-facet-wrap-free-y-polar-legend-bottom",
    coord = "polar", facet = "wrap_free_y", legend = "bottom",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "default", data = "wide"
  ),
  list(
    name = "matrix-facet-grid-margins-cartesian-legend-bottom",
    coord = "cartesian", facet = "grid_margins", legend = "bottom",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-grid-rows-polar-legend-right",
    coord = "polar", facet = "grid_rows", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-wrap-trans-legend-top-double",
    coord = "trans", facet = "wrap", legend = "top",
    direction = "horizontal", legends = 2L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-grid-flip-legend-left-horizontal",
    coord = "flip", facet = "grid", legend = "left",
    direction = "horizontal", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-wrap-radial-legend-bottom",
    coord = "radial", facet = "wrap", legend = "bottom",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "fixed", data = "base"
  ),
  list(
    name = "matrix-facet-grid-space-free-flip-legend-right",
    coord = "flip", facet = "grid_free", legend = "right",
    direction = "auto", legends = 1L, labs = FALSE, theme = "void",
    expand = "default", data = "wide"
  )
)

# --- 渲染 ------------------------------------------------------------------

save_case <- function(name, plot) {
  if (length(only) > 0 && !(name %in% only)) {
    return(invisible(NULL))
  }
  path <- file.path(cases_dir, name, "expected.svg")
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  svglite(path, width = 4, height = 3)
  on.exit(grDevices::dev.off(), add = TRUE)
  print(plot)
  cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", path, fixed = TRUE)))
}

for (spec in CASES) {
  save_case(spec$name, build_plot(spec))
}

# --- 夹具：默认 expand 的断点位置 + 极坐标组合的图例排版 --------------------
#
#   tests/fixtures/matrix_r_reference.json
#
# 两件事：
#
# 1. `report_*` —— 单面板与 2×2 分面在**默认 expand** 下的面板范围与断点位置
#    （npc）。M1 的 61 条 case 里 `labs()` 出现 0 次、几乎都显式
#    `expand = (0, 0)`，所以「默认 expand 下断点落在哪」这件事此前没有被钉住
#    （SIL-715 #7）。Python 侧 `tests/test_cases_matrix_report.py` 逐值对拍。
# 2. `facet_polar_legend_right` —— 2×2 分面 × 极坐标 × 右竖排图例的 guide-box
#    行高（cm）与键间距。M1 复验抓到过「分面竖向图例上移」，这里是它的回归钉：
#    键行高与键间距对 R 逐值，图例块的中心必须与 panel 行的中心重合。

num <- function(value) {
  if (is.null(value) || length(value) == 0) {
    return(NULL)
  }
  unname(as.numeric(value))
}

# 一条轴实际会画的刻度位置（npc）+ 一一对应的标签（口径同 coord_ref.R：
# 有 `x.major` / `y.major` 时用面板顶层的，否则用 ViewScale$break_positions()）。
axis_positions <- function(panel, axis) {
  direct <- panel[[paste0(axis, ".major")]]
  if (!is.null(direct)) {
    values <- num(direct)
    labels <- as.character(panel[[paste0(axis, ".labels")]])
    keep <- !is.na(values)
    return(list(positions = values[keep], labels = labels[keep]))
  }
  view <- panel[[axis]]
  if (is.null(view)) {
    return(NULL)
  }
  values <- num(view$break_positions())
  labels <- as.character(view$get_labels())
  keep <- !is.na(values)
  list(positions = values[keep], labels = labels[keep])
}

report_panels <- function(plot) {
  build <- ggplot_build(plot)
  panels <- build$layout$panel_params
  lapply(seq_along(panels), function(i) {
    pp <- panels[[i]]
    x <- axis_positions(pp, "x")
    y <- axis_positions(pp, "y")
    list(
      panel = i,
      x_range = num(pp$x.range),
      y_range = num(pp$y.range),
      x_positions = if (is.null(x)) NULL else x$positions,
      x_labels = if (is.null(x)) NULL else x$labels,
      y_positions = if (is.null(y)) NULL else y$positions,
      y_labels = if (is.null(y)) NULL else y$labels
    )
  })
}

# 首个面板单元格的物理尺寸（cm）：页面尺寸减去其余固定行列（同 coord_ref.R）。
first_panel_size <- function(plot, width_in = 4, height_in = 3) {
  g <- ggplotGrob(plot)
  panel <- g$layout[grepl("^panel-", g$layout$name), ]
  cols <- seq(panel$l[1], panel$r[1])
  rows <- seq(panel$t[1], panel$b[1])
  list(
    width_cm = width_in * 2.54 - sum(convertWidth(g$widths[-cols], "cm", valueOnly = TRUE)),
    height_cm = height_in * 2.54 - sum(convertHeight(g$heights[-rows], "cm", valueOnly = TRUE))
  )
}

legend_layout <- function(plot) {
  g <- ggplotGrob(plot)
  wrapper <- g$grobs[[which(g$layout$name == "guide-box-right")]]
  guides <- wrapper$grobs[[which(wrapper$layout$name == "guides")]]
  panel <- g$layout[grepl("^panel-", g$layout$name), ]
  box <- g$layout[g$layout$name == "guide-box-right", ]
  # 7×7in 与 Python 侧 `plot_layout(build)` 的缺省页面同一口径（guide_ref.R 同）。
  size <- first_panel_size(plot, width_in = 7, height_in = 7)
  list(
    panel_width_cm = size$width_cm,
    panel_height_cm = size$height_cm,
    guide_box_top = box$t,
    guide_box_bottom = box$b,
    panel_row_top = min(c(panel$t, panel$b)),
    panel_row_bottom = max(c(panel$t, panel$b)),
    heights_cm = num(convertHeight(guides$heights, "cm", valueOnly = TRUE)),
    widths_cm = num(convertWidth(guides$widths, "cm", valueOnly = TRUE)),
    legend_height_cm = sum(convertHeight(wrapper$heights, "cm", valueOnly = TRUE)),
    legend_width_cm = sum(convertWidth(wrapper$widths, "cm", valueOnly = TRUE))
  )
}

spec_of <- function(name) {
  for (spec in CASES) {
    if (identical(spec$name, name)) {
      return(spec)
    }
  }
  stop(sprintf("CASES 里没有 %s", name))
}

payload <- list(
  ggplot2 = as.character(packageVersion("ggplot2")),
  report_cases = list(
    list(
      name = "report_default_expand",
      panels = report_panels(build_plot(spec_of("matrix-report-default-expand")))
    ),
    list(
      name = "report_facet_wrap_grey",
      panels = report_panels(build_plot(spec_of("matrix-report-facet-wrap-grey")))
    )
  ),
  legend = c(
    list(case = "matrix-facet-polar-legend-right"),
    legend_layout(build_plot(spec_of("matrix-facet-polar-legend-right")))
  )
)

fixture_path <- file.path(repo, "tests", "fixtures", "matrix_r_reference.json")
dir.create(dirname(fixture_path), recursive = TRUE, showWarnings = FALSE)
writeLines(
  toJSON(payload, auto_unbox = TRUE, digits = NA, pretty = TRUE, null = "null"),
  fixture_path
)
cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", fixture_path, fixed = TRUE)))
