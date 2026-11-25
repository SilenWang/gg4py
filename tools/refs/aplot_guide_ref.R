#!/usr/bin/env Rscript
# SIL-1003：aplot 0.3.2 guide area / guide layout 的结构对拍。
#
#     pixi run -e refs refs:aplot-guide
#
# 产出 tests/fixtures/aplot_guide_r_reference.json。绝对字体尺寸不跨引擎比较；
# 夹具记录 aplot 自己的 layout 矩阵、guide-box 行列和 guide-cell 相对尺寸。

suppressPackageStartupMessages({
  library(aplot)
  library(ggplot2)
  library(grid)
  library(patchwork)
})
pdf(NULL)

json_escape <- function(text) {
  text <- gsub("\\\\", "\\\\\\\\", text)
  gsub('"', '\\\\"', text)
}

to_json <- function(value, indent = 0) {
  pad <- strrep(" ", indent)
  if (is.null(value)) {
    return("null")
  }
  if (is.list(value)) {
    if (!is.null(names(value))) {
      items <- vapply(
        names(value),
        function(key) {
          paste0(
            strrep(" ", indent + 2), '"', json_escape(key), '": ',
            to_json(value[[key]], indent + 2)
          )
        },
        character(1)
      )
      return(paste0("{\n", paste(items, collapse = ",\n"), "\n", pad, "}"))
    }
    items <- vapply(value, to_json, character(1), indent = indent + 2)
    return(paste0("[\n", paste(items, collapse = ",\n"), "\n", pad, "]"))
  }
  if (is.character(value)) {
    return(paste0('"', json_escape(value), '"'))
  }
  if (is.logical(value)) {
    return(if (value) "true" else "false")
  }
  if (is.numeric(value)) {
    if (length(value) != 1) {
      return(to_json(as.list(value), indent))
    }
    return(format(value, digits = 15, scientific = FALSE, trim = TRUE))
  }
  paste0('"', json_escape(as.character(value)), '"')
}

resolve_pt <- function(units, total, horizontal = TRUE) {
  values <- rep(NA_real_, length(units))
  for (i in seq_along(units)) {
    if (!identical(grid::unitType(units[i]), "null")) {
      values[i] <- if (horizontal) {
        convertWidth(units[i], "pt", valueOnly = TRUE)
      } else {
        convertHeight(units[i], "pt", valueOnly = TRUE)
      }
    }
  }
  is_null <- is.na(values)
  free <- total - sum(values, na.rm = TRUE)
  weights <- rep(0, length(units))
  for (i in which(is_null)) {
    weights[i] <- as.numeric(units[i])
  }
  values[is_null] <- free * weights[is_null] / sum(weights[is_null])
  values
}

cell_rect <- function(gt, name, width_in, height_in) {
  row <- gt$layout[gt$layout$name == name, ][1, ]
  widths <- resolve_pt(gt$widths, width_in * 72)
  heights <- resolve_pt(gt$heights, height_in * 72, horizontal = FALSE)
  list(
    t = row$t,
    l = row$l,
    b = row$b,
    r = row$r,
    x = sum(widths[seq_len(row$l - 1)]),
    y = sum(heights) - sum(heights[seq_len(row$b)]),
    w = sum(widths[row$l:row$r]),
    h = sum(heights[row$t:row$b])
  )
}

d <- transform(mtcars, gear_f = factor(gear), cyl_f = factor(cyl))
plot_data <- function(y, fill) {
  ggplot(
    d,
    aes(wt, y, colour = gear_f, shape = cyl_f, size = wt)
  ) +
    geom_point() +
    labs(colour = "gear", shape = "cyl", size = "gear") +
    theme(panel.background = element_rect(fill = fill, colour = NA))
}

p1 <- plot_data(d$mpg, "#CC0000")
p2 <- plot_data(d$disp, "#00CC00")
p3 <- plot_data(d$hp, "#0000CC")

side <- aplot:::as.aplot(p1)
side <- insert_bottom(side, p2)
side <- set_guide_area(side, "right")
side_spec <- aplot:::.resolve_guide_area(side)
side_gt <- patchworkGrob(as.patchwork(side))
side_guide <- cell_rect(side_gt, "panel_patch-3", 7, 5)
side_panel <- cell_rect(side_gt, "panel-1", 7, 5)

corner <- aplot:::as.aplot(p1)
corner$plotlist <- list(p1, p2, p3)
corner$layout <- matrix(c(1, 2, 3, NA), nrow = 2, byrow = TRUE)
corner$n <- 3
corner$main_row <- 1
corner$main_col <- 1
corner$width <- c(1, 1)
corner$height <- c(1, 1)
corner <- set_guide_area(corner, "bottom-right")
corner_spec <- aplot:::.resolve_guide_area(corner)
corner_gt <- patchworkGrob(as.patchwork(corner))
corner_guide <- cell_rect(corner_gt, "panel_patch-4", 7, 6)
corner_panel <- cell_rect(corner_gt, "panel-1", 7, 6)

even_corner <- aplot:::as.aplot(p1)
even_corner$plotlist <- list(p1, p2)
even_corner$layout <- matrix(c(1, 2, NA, NA, NA, NA), nrow = 3, byrow = TRUE)
even_corner$n <- 2
even_corner$main_row <- 1
even_corner$main_col <- 1
even_corner$width <- c(1, 1)
even_corner$height <- c(1, 1, 1)
even_corner <- set_guide_area(even_corner, "bottom-right")
even_corner_spec <- aplot:::.resolve_guide_area(even_corner)

wide <- aplot:::as.aplot(p1)
wide <- insert_right(insert_right(wide, p2), p3)
wide$width <- c(3, 2, 1)
left_widths <- as.numeric(as.patchwork(set_guide_area(wide, "left"))$patches$layout$widths)
right_widths <- as.numeric(as.patchwork(set_guide_area(wide, "right"))$patches$layout$widths)

tall <- aplot:::as.aplot(p1)
tall <- insert_bottom(tall, p2)
tall$height <- c(3, 1)
top_heights <- as.numeric(as.patchwork(set_guide_area(tall, "top"))$patches$layout$heights)
bottom_heights <- as.numeric(as.patchwork(set_guide_area(tall, "bottom"))$patches$layout$heights)

continuous_plot <- ggplot(mtcars, aes(wt, mpg, colour = qsec)) + geom_point()
continuous_targets <- aplot:::.guide_layout_targets(continuous_plot)
guide_box_size <- function(plot) {
  grob <- ggplotGrob(plot)
  index <- which(grob$layout$name == "guide-box-right")[1]
  c(
    convertWidth(gtable::gtable_width(grob$grobs[[index]]), "cm", valueOnly = TRUE),
    convertHeight(gtable::gtable_height(grob$grobs[[index]]), "cm", valueOnly = TRUE)
  )
}
continuous_baseline <- guide_box_size(continuous_plot)
continuous_ncol <- guide_box_size(
  aplot:::.apply_legend_layout(
    list(continuous_plot),
    list(ncol = 2)
  )[[1]]
)
bins_plot <- ggplot(mtcars, aes(wt, mpg, colour = qsec)) +
  geom_point() +
  guides(colour = guide_bins())
bins_targets <- aplot:::.guide_layout_targets(bins_plot)

# SIL-1011：连续 colour 上显式 guide_legend() —— ggplot2 会画出 legend，
# 但 scale$guide 仍是默认的 "colourbar"，aplot 的 targets 为空、legend_* 不生效。
explicit_plot <- ggplot(mtcars, aes(wt, mpg, colour = qsec)) +
  geom_point() +
  guides(colour = guide_legend())
explicit_targets <- aplot:::.guide_layout_targets(explicit_plot)
explicit_class <- class(
  suppressMessages(ggplot_build(explicit_plot))$plot@guides$guides[[1]]
)[1]
explicit_baseline <- guide_box_size(explicit_plot)
explicit_ncol <- guide_box_size(
  aplot:::.apply_legend_layout(list(explicit_plot), list(ncol = 2))[[1]]
)

# 对照：离散 colour 的 GuideLegend 仍会被 legend_* 改写。
discrete_plot <- ggplot(mtcars, aes(wt, mpg, colour = factor(cyl))) +
  geom_point() +
  guides(colour = guide_legend())
discrete_targets <- aplot:::.guide_layout_targets(discrete_plot)
discrete_class <- class(
  suppressMessages(ggplot_build(discrete_plot))$plot@guides$guides[[1]]
)[1]
discrete_baseline <- guide_box_size(discrete_plot)
discrete_ncol <- guide_box_size(
  aplot:::.apply_legend_layout(list(discrete_plot), list(ncol = 2))[[1]]
)

# 对照：guide 写在 scale 上（scale$guide 就是 GuideLegend）时 aplot 会命中。
scale_legend_plot <- ggplot(mtcars, aes(wt, mpg, colour = qsec)) +
  geom_point() +
  scale_colour_continuous(guide = guide_legend())
scale_legend_targets <- aplot:::.guide_layout_targets(scale_legend_plot)
scale_legend_baseline <- guide_box_size(scale_legend_plot)
scale_legend_ncol <- guide_box_size(
  aplot:::.apply_legend_layout(list(scale_legend_plot), list(ncol = 2))[[1]]
)

# 对照：分箱 scale 的默认 guide 是 "coloursteps"，同样不在 legend 目标里。
binned_plot <- ggplot(mtcars, aes(wt, mpg, colour = qsec)) +
  geom_point() +
  scale_colour_binned()
binned_targets <- aplot:::.guide_layout_targets(binned_plot)
binned_baseline <- guide_box_size(binned_plot)
binned_ncol <- guide_box_size(
  aplot:::.apply_legend_layout(list(binned_plot), list(ncol = 2))[[1]]
)

guide_plot <- plot_data(d$mpg, "#CC0000")
guide_aplot <- set_guide_layout(
  aplot:::as.aplot(guide_plot),
  legend_ncol = 2,
  legend_byrow = TRUE,
  legend_direction = "horizontal",
  legend_keywidth = 8,
  legend_keyheight = 5,
  legend_spacing_x = 3,
  legend_spacing_y = 4,
  guides_ncol = 2,
  guides_direction = "vertical"
)
guide_spec <- aplot:::.resolve_guide_layout(guide_aplot)
guide_plots <- aplot:::.apply_guide_layout(list(guide_plot), guide_spec$legend)
guides <- aplot:::.collapse_plot_guides(aplot:::.collect_plot_guides(guide_plots))
guide_layout <- aplot:::.guides_layout_matrix(length(guides), guide_spec$guides)
guide_box <- aplot:::.build_guides_gtable(guides, guide_layout, ggplot2::theme_get())
guide_rows <- which(guide_box$layout$name == "guides")

payload <- list(
  aplot = as.character(packageVersion("aplot")),
  patchwork = as.character(packageVersion("patchwork")),
  ggplot2 = as.character(packageVersion("ggplot2")),
  side_right = list(
    mode = side_spec$mode,
    position = side_spec$position,
    strip_width = side_spec$width,
    rows = side_spec$rows,
    cols = side_spec$cols,
    guide_indices = side_spec$guide_indices,
    region_indices = side_spec$region_indices,
    guide_cell = side_guide,
    panel_cell = side_panel,
    width_to_panel = side_guide$w / side_panel$w,
    height_to_panel = side_guide$h / side_panel$h
  ),
  corner_bottom_right = list(
    mode = corner_spec$mode,
    position = corner_spec$position,
    row = corner_spec$row,
    col = corner_spec$col,
    rows = corner_spec$rows,
    cols = corner_spec$cols,
    guide_indices = corner_spec$guide_indices,
    region_indices = corner_spec$region_indices,
    guide_cell = corner_guide,
    panel_cell = corner_panel,
    width_to_panel = corner_guide$w / corner_panel$w,
    height_to_panel = corner_guide$h / corner_panel$h
  ),
  even_corner_bottom_right = list(
    mode = even_corner_spec$mode,
    position = even_corner_spec$position,
    row = even_corner_spec$row,
    col = even_corner_spec$col,
    rows = even_corner_spec$rows,
    cols = even_corner_spec$cols
  ),
  side_strips = list(
    left_widths = left_widths,
    right_widths = right_widths,
    top_heights = top_heights,
    bottom_heights = bottom_heights
  ),
  continuous_legend_layout = list(
    targets = continuous_targets,
    baseline_box_cm = continuous_baseline,
    ncol_box_cm = continuous_ncol
  ),
  guide_bins_targets = bins_targets,
  continuous_explicit_legend = list(
    targets = paste(explicit_targets, collapse = ","),
    final_guide_class = explicit_class,
    baseline_box_cm = explicit_baseline,
    ncol_box_cm = explicit_ncol,
    ncol_changes_box = !isTRUE(all.equal(explicit_baseline, explicit_ncol))
  ),
  discrete_explicit_legend = list(
    targets = paste(discrete_targets, collapse = ","),
    final_guide_class = discrete_class,
    baseline_box_cm = discrete_baseline,
    ncol_box_cm = discrete_ncol,
    ncol_changes_box = !isTRUE(all.equal(discrete_baseline, discrete_ncol))
  ),
  continuous_scale_guide_legend = list(
    targets = paste(scale_legend_targets, collapse = ","),
    baseline_box_cm = scale_legend_baseline,
    ncol_box_cm = scale_legend_ncol,
    ncol_changes_box = !isTRUE(all.equal(scale_legend_baseline, scale_legend_ncol))
  ),
  continuous_binned_default = list(
    targets = paste(binned_targets, collapse = ","),
    baseline_box_cm = binned_baseline,
    ncol_box_cm = binned_ncol,
    ncol_changes_box = !isTRUE(all.equal(binned_baseline, binned_ncol))
  ),
  guide_box = list(
    legend_ncol = guide_spec$legend$ncol,
    legend_byrow = guide_spec$legend$byrow,
    legend_direction = guide_spec$legend$direction,
    legend_keywidth_mm = guide_spec$legend$keywidth,
    legend_keyheight_mm = guide_spec$legend$keyheight,
    legend_spacing_x_mm = guide_spec$legend$spacing.x,
    legend_spacing_y_mm = guide_spec$legend$spacing.y,
    guides_ncol = guide_spec$guides$ncol,
    guides_direction = guide_spec$guides$direction,
    count = length(guides),
    nrow = guide_layout$nrow,
    ncol = guide_layout$ncol,
    row = guide_layout$row,
    col = guide_layout$col,
    widths_cm = convertWidth(guide_box$widths, "cm", valueOnly = TRUE),
    heights_cm = convertHeight(guide_box$heights, "cm", valueOnly = TRUE),
    guide_cells = guide_box$layout[guide_rows, c("t", "l", "b", "r")]
  )
)

target <- file.path("tests", "fixtures", "aplot_guide_r_reference.json")
writeLines(to_json(payload), target)
dev.off()
cat("wrote", target, "\n")
