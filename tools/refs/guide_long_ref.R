#!/usr/bin/env Rscript
#
# guides 长尾（M2-S2 / SIL-739）的 R 侧参考值。
#
#   pixi run -e refs refs:guide-long
#
# 三组输入，全部钉 ggplot2 4.0.3：
#
#   1. 色条 / 分箱图例（`guide_colourbar` / `guide_bins` / `guide_coloursteps`）
#      的键（`get_guide_data()`）与 `ggplotGrob()` 读回的图例 gtable 宽高；
#   2. 轴 guide（`guide_axis` / `guide_axis_logticks` / `guide_axis_stack` /
#      `guide_axis_theta`）的 `axis-l` / `axis-b` 行列尺寸与键（含 `.type`）；
#   3. 对数次刻度的纯函数取值：`minor_breaks_log()` 在若干区间上的位置与档位
#      （long / mid / short = 1 / 2 / 3），这是「逐段一致」的判据。
#
# 与 `guide_ref.R`（M1-11）分开：那份是 M1 的 8 个 case，本文件只增不改，
# 产物落 `tests/fixtures/guide_long_r_reference.json`。

suppressPackageStartupMessages({
  library(ggplot2)
  library(jsonlite)
  library(grid)
  library(svglite)
})

invisible(pdf(NULL))

out_path <- "tests/fixtures/guide_long_r_reference.json"
page_in <- c(7, 7)

d <- data.frame(
  x = c(1.5, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6, 5.0, 5.3, 5.6),
  y = c(26.0, 25.0, 24.5, 23.0, 22.5, 21.0, 20.5, 19.5, 18.0, 17.5, 16.5, 15.0),
  cyl = factor(c(4, 4, 4, 6, 6, 6, 8, 8, 8, 4, 6, 8), levels = c(4, 6, 8)),
  gear = factor(c(3, 4, 5, 3, 4, 5, 3, 4, 5, 4, 5, 3), levels = c(3, 4, 5)),
  disp = c(120, 140, 160, 180, 200, 220, 240, 260, 280, 300, 320, 340)
)

num <- function(value) {
  if (is.null(value) || length(value) == 0) return(NULL)
  unname(as.numeric(value))
}

region_size <- function(g, name, kind) {
  row <- g$layout[g$layout$name == name, , drop = FALSE]
  if (nrow(row) == 0) return(NULL)
  if (kind == "height") {
    return(sum(convertHeight(g$heights[row$t:row$b], "cm", valueOnly = TRUE)))
  }
  sum(convertWidth(g$widths[row$l:row$r], "cm", valueOnly = TRUE))
}

measure_axes <- function(g) {
  list(
    axis_l = region_size(g, "axis-l", "width"),
    axis_b = region_size(g, "axis-b", "height"),
    axis_t = region_size(g, "axis-t", "height"),
    axis_r = region_size(g, "axis-r", "width"),
    ylab_l = region_size(g, "ylab-l", "width"),
    xlab_b = region_size(g, "xlab-b", "height"),
    title = region_size(g, "title", "height")
  )
}

# 图例盒的位置不固定（right / bottom / left / top），逐个找 guide-box-* 再看
# 里面每张 guide gtable 自己的宽高。
measure_legends <- function(g) {
  idx <- which(grepl("^guide-box-", g$layout$name))
  if (length(idx) == 0) return(list(present = FALSE))
  # 五个 guide-box-* 槽位始终存在，只有真正放图例的那个挂着 gtable。
  chosen <- NULL
  for (i in idx) {
    item <- g$grobs[[i]]
    if (inherits(item, "gtable") && any(vapply(item$grobs, inherits, logical(1), "gtable"))) {
      chosen <- i
      break
    }
  }
  if (is.null(chosen)) return(list(present = FALSE))
  row <- g$layout[chosen, , drop = FALSE]
  side <- sub("^guide-box-", "", row$name)
  wrapper <- g$grobs[[chosen]]
  # 在页面上下文里量（进 guide-box 视口后 gtable 内部的 npc 高度会按该视口
  # 重新解析，colourbar 的 5×key 高会少算一份）。
  guides <- Filter(function(item) inherits(item, "gtable"), wrapper$grobs)
  sizes <- lapply(guides, function(item) {
    list(
      width = convertWidth(grobWidth(item), "cm", valueOnly = TRUE),
      height = convertHeight(grobHeight(item), "cm", valueOnly = TRUE)
    )
  })
  list(present = TRUE, side = side, guides = sizes)
}

guide_data <- function(plot, aesthetics) {
  out <- list()
  for (aesthetic in aesthetics) {
    key <- tryCatch(get_guide_data(plot, aesthetic), error = function(...) NULL)
    if (!is.data.frame(key) || nrow(key) == 0) next
    rows <- lapply(seq_len(nrow(key)), function(i) {
      record <- list()
      for (name in names(key)) {
        item <- key[[name]][i]
        if (is.factor(item)) item <- as.character(item)
        record[[name]] <- if (is.character(item)) {
          if (is.na(item)) NA_character_ else item
        } else if (is.logical(item)) {
          item
        } else if (is.na(item)) {
          NA
        } else {
          unname(as.numeric(item))
        }
      }
      record
    })
    out[[aesthetic]] <- rows
  }
  out
}

measure_case <- function(name, plot, aesthetics) {
  built <- ggplot_build(plot)
  # 用 svglite 量（与参考图产线同一设备）：轴带行高由设备的字体度量决定，
  # pdf(NULL) 回退 Helvetica（0.959em）会比 svglite / 本仓（0.8945em）高一截。
  # `ggplotGrob()` 必须在设备打开之后再建，否则文本尺寸按上一个设备算。
  svglite(tempfile(fileext = ".svg"), width = page_in[1], height = page_in[2])
  on.exit(dev.off(), add = TRUE)
  grid.newpage()
  g <- ggplotGrob(plot)
  grid.draw(g)
  axes <- measure_axes(g)
  legends <- measure_legends(g)
  list(
    name = name,
    axes = axes,
    legends = legends,
    guides = guide_data(plot, aesthetics)
  )
}

base <- function(mapping) ggplot(d, mapping) + geom_point() + labs(x = "X", y = "Y")
binned_base <- function(mapping) {
  ggplot(d, mapping) + geom_point() + scale_colour_steps() + labs(x = "X", y = "Y")
}

cases <- list()

add <- function(name, plot, aesthetics = character(0)) {
  cases[[name]] <<- measure_case(name, plot, aesthetics)
}

# --- 色条 ------------------------------------------------------------------
add(
  "colourbar_rectangles",
  base(aes(x, y, colour = disp)) + guides(colour = guide_colourbar(nbin = 8, display = "rectangles")),
  "colour"
)
add(
  "colourbar_gradient",
  base(aes(x, y, colour = disp)) + guides(colour = guide_colourbar(display = "gradient")),
  "colour"
)
add(
  "colourbar_no_llim",
  base(aes(x, y, colour = disp)) + guides(colour = guide_colourbar(draw.llim = FALSE)),
  "colour"
)
add(
  "colourbar_no_ulim",
  base(aes(x, y, colour = disp)) + guides(colour = guide_colourbar(draw.ulim = FALSE)),
  "colour"
)
add(
  "colourbar_title_left",
  base(aes(x, y, colour = disp)) + theme(legend.title.position = "left"),
  "colour"
)
add(
  "colourbar_horizontal",
  base(aes(x, y, colour = disp)) +
    theme(legend.position = "bottom") +
    guides(colour = guide_colourbar(direction = "horizontal")),
  "colour"
)
add(
  "colourbar_bar_size",
  base(aes(x, y, colour = disp)) +
    theme(legend.key.width = unit(2, "cm"), legend.key.height = unit(0.5, "cm")),
  "colour"
)

# --- bins / coloursteps ----------------------------------------------------
add("bins", base(aes(x, y, colour = disp)) + guides(colour = guide_bins()), "colour")
add(
  "bins_show_limits",
  base(aes(x, y, colour = disp)) + guides(colour = guide_bins(show.limits = TRUE)),
  "colour"
)
add("coloursteps", base(aes(x, y, colour = disp)) + guides(colour = guide_coloursteps()), "colour")
add(
  "coloursteps_uneven",
  base(aes(x, y, colour = disp)) + guides(colour = guide_coloursteps(even.steps = FALSE)),
  "colour"
)
add(
  "coloursteps_limits",
  base(aes(x, y, colour = disp)) + guides(colour = guide_coloursteps(show.limits = TRUE)),
  "colour"
)
add(
  "bins_binned_scale",
  binned_base(aes(x, y, colour = disp)) + guides(colour = guide_bins()),
  "colour"
)
add(
  "coloursteps_binned_scale",
  binned_base(aes(x, y, colour = disp)) + guides(colour = guide_coloursteps()),
  "colour"
)

# --- 轴 guide ---------------------------------------------------------------
add(
  "axis_angle45",
  base(aes(x, y)) + guides(x = guide_axis(angle = 45)),
  c("x", "y")
)
add(
  "axis_angle90",
  base(aes(x, y)) + guides(x = guide_axis(angle = 90)),
  c("x", "y")
)
add(
  "axis_y_angle45",
  base(aes(x, y)) + guides(y = guide_axis(angle = 45)),
  c("x", "y")
)
add(
  "axis_nodge2",
  base(aes(x, y)) + guides(x = guide_axis(n.dodge = 2)),
  c("x", "y")
)
add(
  "axis_nodge3",
  base(aes(x, y)) + guides(x = guide_axis(n.dodge = 3)),
  c("x", "y")
)
add(
  "axis_check_overlap",
  base(aes(x, y)) + guides(x = guide_axis(check.overlap = TRUE)),
  c("x", "y")
)
add(
  "axis_minor_ticks",
  base(aes(x, y)) + guides(x = guide_axis(minor.ticks = TRUE)),
  c("x", "y")
)
add(
  "axis_logticks",
  base(aes(x, y)) + scale_x_log10() + guides(x = guide_axis_logticks()),
  c("x", "y")
)
add(
  "axis_logticks_both",
  base(aes(x, y)) + scale_x_log10() + scale_y_log10() +
    guides(x = guide_axis_logticks(), y = guide_axis_logticks()),
  c("x", "y")
)
add(
  "axis_logticks_unexpanded",
  base(aes(x, y)) + scale_x_log10() +
    guides(x = guide_axis_logticks(expanded = FALSE)),
  c("x", "y")
)
add(
  "axis_stack",
  base(aes(x, y)) +
    guides(x = guide_axis_stack(guide_axis(), guide_axis(angle = 45))),
  c("x", "y")
)
add(
  "axis_stack_logticks",
  base(aes(x, y)) + scale_x_log10() +
    guides(x = guide_axis_stack(guide_axis(), guide_axis_logticks())),
  c("x", "y")
)
add(
  "axis_theta",
  ggplot(d, aes(cyl, y, fill = cyl)) + geom_col() + coord_polar() +
    guides(theta = guide_axis_theta()),
  c("x")
)

# --- 对数次刻度的纯函数 ------------------------------------------------------
log_ranges <- list(
  c(1, 100),
  c(0.01, 1000),
  c(-100, 100),
  c(2, 300),
  c(0.3, 30),
  c(1e-6, 1e6)
)
log_breaks <- lapply(log_ranges, function(rng) {
  ticks <- scales::minor_breaks_log()(rng)
  list(
    range = num(rng),
    detail = as.integer(attr(ticks, "detail")),
    ticks = num(ticks)
  )
})

# --- 输出 -------------------------------------------------------------------
output <- list(
  generator = "tools/refs/guide_long_ref.R",
  ggplot2 = as.character(packageVersion("ggplot2")),
  size_in = page_in,
  data = list(
    x = d$x, y = d$y, disp = d$disp,
    cyl = as.character(d$cyl), cyl_levels = levels(d$cyl),
    gear = as.character(d$gear), gear_levels = levels(d$gear)
  ),
  cases = cases,
  log_breaks = log_breaks
)

writeLines(
  toJSON(output, auto_unbox = TRUE, digits = 17, null = "null", na = "null", pretty = TRUE),
  out_path
)
cat("wrote", out_path, "with", length(cases), "cases\n")
