#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/coord_r_reference.json —— 坐标面板参数的 R 侧参考值（M1-5）。
#
#   pixi run -e refs refs:coord
#
# 对 10 个 case 跑真正的 ggplot2 4.0.3：
#
#   1. cartesian_default     默认连续坐标
#   2. cartesian_expand_false coord_cartesian(expand = FALSE)
#   3. cartesian_xlim        coord_cartesian(xlim = c(2, 5))
#   4. scale_x_limits        scale_x_continuous(limits = c(2, 5))（越界点被删）
#   5. discrete_default      离散 x
#   6. discrete_xlim_levels  scale_x_discrete(limits = c("a", "b", "d"))（含越界水平）
#   7. fixed_ratio_1         coord_fixed(ratio = 1)
#   8. fixed_ratio_2         coord_fixed(ratio = 2)
#   9. log10_coord_xlim      scale_x_log10() + coord_cartesian(xlim = c(1, 100))
#  10. log10_scale_limits_coord
#                            scale_x_log10(limits = c(1, 100)) +
#                            coord_cartesian(xlim = c(1, 10))
#
# 9 / 10 守的是 `expand_limits_scale()` 的第一步：coord limits 是数据空间的值，
# 连续标度上先过 `transformation$transform()` 再 expand
# （`scale_x_log10() + xlim = c(1, 100)` → base `0..2`，面板 `-0.1..2.1`）。
#
# 记录 `ggplot_build(p)$layout$panel_params[[1]]` 的 `x.range` / `y.range`
# （含 expand）、expand 前的数值范围（连续取 get_limits()，离散取 1..n）、
# coord limits 原值与**变换后**的值、`CoordFixed$aspect()`，以及 R 自己报的
# "Removed N rows" 行数。
# Python 侧 `tests/test_coord_r_parity.py` 用同一份数据逐值比对（容差 1e-12）。

suppressPackageStartupMessages({
  library(ggplot2)
  library(jsonlite)
  library(svglite)
})

# 不开默认绘图设备：否则某些 ggplot 调用会在 CWD 留下 Rplots.pdf（产物不可复现）。
invisible(pdf(NULL))

out_path <- "tests/fixtures/coord_r_reference.json"

coord_data <- data.frame(
  x = c(1.513, 2.0, 2.5, 3.2, 4.7, 5.424),
  y = c(9.225, 12.0, 18.5, 22.1, 30.0, 35.075),
  g = c("a", "b", "c", "c", "a", "b"),
  stringsAsFactors = FALSE
)

# log10 case 的数据：整十次幂，数据空间 1..100 / 面板空间 0..2。
log_data <- data.frame(x = c(1, 10, 100), y = c(1, 2, 3))

num <- function(value) {
  if (is.null(value)) {
    return(NULL)
  }
  value <- as.numeric(value)
  if (all(is.na(value))) {
    return(NULL)
  }
  unname(value)
}

removed_rows <- function(messages) {
  total <- 0L
  for (message in unique(messages)) {
    if (!grepl("Removed [0-9]+ rows", message)) {
      next
    }
    hit <- regmatches(message, regexpr("Removed [0-9]+ rows", message))
    total <- total + as.integer(gsub("[^0-9]", "", hit))
  }
  total
}

# coord limits 是数据空间的值；`expand_limits_scale()` 在连续标度上先把它
# `transformation$transform()` 到标度空间。这里记录同一件事的结果，供 Python
# 侧逐值对拍（identity 标度上就是原值）。
transformed_coord_limits <- function(build, aesthetic, limits) {
  if (is.null(limits)) {
    return(NULL)
  }
  scale <- build$plot$scales$get_scales(aesthetic)
  if (is.null(scale) || isTRUE(scale$is_discrete())) {
    return(num(limits))
  }
  num(scale$get_transformation()$transform(as.numeric(limits)))
}

# --- M2-1 扩展：范围 / theta / r / 断点位置 / 面板几何 ---------------------

# 极坐标的 theta 位置（弧度）：直接调用 ggplot2 自己的 theta_rescale()。
theta_positions <- function(coord, panel) {
  if (is.null(panel$theta.range) || is.null(panel$theta.major)) {
    return(NULL)
  }
  values <- panel$theta.major
  values <- values[!is.na(values)]
  if (length(values) == 0) {
    return(NULL)
  }
  arc <- if (!is.null(panel$arc)) panel$arc else coord$start + c(0, 2 * pi)
  dir <- if (!is.null(coord$direction)) coord$direction else 1
  num(ggplot2:::theta_rescale(values, panel$theta.range, arc, dir))
}

# 极坐标 r 轴的位置（npc，0.5 是圆心）：r_rescale() + 0.5（与 render_axis_v 同式）。
r_positions <- function(panel) {
  values <- panel$r.major
  values <- values[!is.na(values)]
  if (is.null(panel$r.range) || length(values) == 0) {
    return(NULL)
  }
  # donut 用面板自己的 inner_radius（radial 的内半径；polar 是默认 0..0.4）。
  donut <- panel$inner_radius %||% c(0, 0.4)
  num(ggplot2:::r_rescale(values, panel$r.range, donut) + 0.5)
}

# 次轴（sec_axis）的位置 / 标签；没有 sec.axis 时给 NULL。
sec_info <- function(build, aesthetic) {
  scale <- build$plot$scales$get_scales(aesthetic)
  sa <- if (is.null(scale)) NULL else scale$secondary.axis
  if (is.null(sa) || inherits(sa, "waiver")) {
    return(NULL)
  }
  pp <- build$layout$panel_params[[1L]]
  view <- if (aesthetic == "x") pp$x.sec else pp$y.sec
  list(
    positions = num(view$break_positions()),
    labels = as.character(view$get_labels()),
    continuous_range = num(view$continuous_range)
  )
}

# `ggplotGrob()` 的面板几何（cm）：画到临时 svglite 设备上，再用 grid 的
# convertWidth / convertHeight 把 null 单元解析成实际尺寸。
panel_geometry <- function(plot, width_in = 4, height_in = 3) {
  g <- ggplotGrob(plot)
  panel <- g$layout[g$layout$name == "panel", ]
  if (nrow(panel) == 0) {
    return(NULL)
  }
  cols <- seq(panel$l[1], panel$r[1])
  rows <- seq(panel$t[1], panel$b[1])
  # null 单元在根视口外换算成 0，所以面板尺寸 = 页面尺寸 − 其余行列的固定尺寸。
  width <- width_in * 2.54 - grid::convertWidth(sum(g$widths[-cols]), "cm", valueOnly = TRUE)
  height <- height_in * 2.54 - grid::convertHeight(sum(g$heights[-rows]), "cm", valueOnly = TRUE)
  left <- grid::convertWidth(sum(g$widths[seq_len(panel$l[1] - 1L)]), "cm", valueOnly = TRUE)
  top <- grid::convertHeight(sum(g$heights[seq_len(panel$t[1] - 1L)]), "cm", valueOnly = TRUE)
  list(width = width, height = height, left = left, top = top)
}

# `reverse = "x"` 只翻转映射；R 画轴时用 `view$reverse()` 后的位置（实测 2 出现在
# 右侧），所以夹具里要把位置翻成 1 - p，不能直接用 ViewScale$break_positions()。
axis_reversed <- function(panel, axis) {
  rv <- panel$reverse %||% "none"
  rv %in% c("xy", "yx", axis)
}

# 一条轴**实际会画**的刻度位置（npc）+ 与位置一一对应的标签。
#
# - `coord_trans` / `coord_transform`：R 用面板顶层的 `x.major` / `x.labels`
#   （已经过逐轴变换），不是 `pp$x$break_positions()`——后者按标度空间的线性
#   位置重算，和实际渲染差 0.11（SIL-729 用 SVG 里 "2" 的 x 坐标核实：
#   `pp$x.major` 才是画出来的位置）。
# - 其余坐标：`ViewScale$break_positions()`，越界断点是 NA，标签只对应非 NA。
# - `reverse = "x"` 只翻转映射，R 画轴用的是翻转后的位置（1 - p），所以这里翻。
axis_positions <- function(panel, axis) {
  direct <- panel[[paste0(axis, ".major")]]
  if (!is.null(direct)) {
    values <- num(direct)
    labels <- as.character(panel[[paste0(axis, ".labels")]])
    keep <- !is.na(values)
    return(list(positions = values[keep], labels = labels[keep]))
  }
  view <- panel[[axis]]
  if (is.null(view) || !is.function(tryCatch(view$break_positions, error = function(e) NULL))) {
    return(NULL)
  }
  values <- num(view$break_positions())
  labels <- as.character(view$get_labels())
  keep <- !is.na(values)
  values <- values[keep]
  if (axis_reversed(panel, axis)) {
    values <- 1 - values
  }
  list(positions = values, labels = labels[keep])
}

# 面板某条维度的「展开前范围」：优先用面板自己的 ViewScale（flip 已经交换过），
# 极坐标没有 x / y 时退回标度。
panel_limits <- function(view, scale) {
  if (!is.null(view) && is.function(view$get_limits)) {
    limits <- view$get_limits()
    if (isTRUE(view$is_discrete())) {
      return(c(1, length(limits)))
    }
    return(num(limits))
  }
  limits <- scale$get_limits()
  if (isTRUE(scale$is_discrete())) {
    return(c(1, length(limits)))
  }
  num(limits)
}

view_labels <- function(view) {
  if (is.null(view)) {
    return(NULL)
  }
  f <- tryCatch(view$get_labels, error = function(e) NULL)
  if (!is.function(f)) {
    return(NULL)
  }
  as.character(f())
}

describe <- function(name, plot) {
  messages <- character()
  build <- withCallingHandlers(
    ggplot_build(plot),
    warning = function(w) {
      messages <<- c(messages, conditionMessage(w))
      invokeRestart("muffleWarning")
    }
  )
  withCallingHandlers(
    invisible(ggplot_gtable(build)),
    warning = function(w) {
      messages <<- c(messages, conditionMessage(w))
      invokeRestart("muffleWarning")
    }
  )
  panel <- build$layout$panel_params[[1L]]
  coord <- build$plot$coordinates
  # 极坐标的 panel_params 用 theta./r. 命名，没有 x/y 那对 ViewScale；标度本身
  # 仍可从 layout$panel_scales_x/y 取（flip 已按 SCALE_X / SCALE_Y 交换过）。
  scale_x <- build$layout$panel_scales_x[[1L]]
  scale_y <- build$layout$panel_scales_y[[1L]]
  x_discrete <- isTRUE(scale_x$is_discrete())
  y_discrete <- isTRUE(scale_y$is_discrete())
  x_limits <- panel_limits(panel$x, scale_x)
  y_limits <- panel_limits(panel$y, scale_y)

  data <- build$data[[1L]]
  geometry <- panel_geometry(plot)
  list(
    name = name,
    coord = class(coord)[1L],
    ratio = num(coord$ratio),
    clip = if (is.null(coord$clip)) "on" else coord$clip,
    x_discrete = x_discrete,
    y_discrete = y_discrete,
    x_range = num(panel$x.range),
    y_range = num(panel$y.range),
    x_limits = num(x_limits),
    y_limits = num(y_limits),
    coord_xlim = num(coord$limits$x),
    coord_ylim = num(coord$limits$y),
    coord_xlim_transformed = transformed_coord_limits(build, "x", coord$limits$x),
    coord_ylim_transformed = transformed_coord_limits(build, "y", coord$limits$y),
    aspect = num(coord$aspect(panel)),
    n_rows = nrow(data),
    na_x = sum(is.na(data$x)),
    na_y = sum(is.na(data$y)),
    removed = removed_rows(messages),
    # --- M2-1 扩展（旧 case 里这些字段为 NULL，Python 侧按需取） ---
    x_positions = if (is.null(axis_positions(panel, "x"))) NULL else axis_positions(panel, "x")$positions,
    y_positions = if (is.null(axis_positions(panel, "y"))) NULL else axis_positions(panel, "y")$positions,
    x_position_labels = if (is.null(axis_positions(panel, "x"))) NULL else axis_positions(panel, "x")$labels,
    y_position_labels = if (is.null(axis_positions(panel, "y"))) NULL else axis_positions(panel, "y")$labels,
    x_labels = view_labels(panel$x),
    y_labels = view_labels(panel$y),
    theta_range = num(panel$theta.range),
    r_range = num(panel$r.range),
    theta_major = num(panel$theta.major),
    r_major = num(panel$r.major),
    theta_positions = theta_positions(coord, panel),
    r_positions = r_positions(panel),
    bbox = if (is.null(panel$bbox)) NULL else list(x = num(panel$bbox$x), y = num(panel$bbox$y)),
    arc = num(panel$arc),
    inner_radius = num(panel$inner_radius),
    panel_width_cm = if (is.null(geometry)) NULL else geometry$width,
    panel_height_cm = if (is.null(geometry)) NULL else geometry$height,
    panel_left_cm = if (is.null(geometry)) NULL else geometry$left,
    panel_top_cm = if (is.null(geometry)) NULL else geometry$top,
    sec_x = sec_info(build, "x"),
    sec_y = sec_info(build, "y")
  )
}

# M2-1 的新 case 统一 `theme_void()`：面板几何（宽高 / 位置）不受文字度量影响，
# Python 侧可以对拍到 1e-6 cm。
void <- function(plot) plot + theme_void() + theme(legend.position = "none")

base_plot <- ggplot(coord_data, aes(x = x, y = y)) + geom_point()
discrete_plot <- ggplot(coord_data, aes(x = g, y = y)) + geom_point()
log_plot <- ggplot(log_data, aes(x = x, y = y)) + geom_point() + scale_x_log10()
log_limit_plot <- ggplot(log_data, aes(x = x, y = y)) +
  geom_point() +
  scale_x_log10(limits = c(1, 100))

cases <- list(
  describe("cartesian_default", base_plot),
  describe("cartesian_expand_false", base_plot + coord_cartesian(expand = FALSE)),
  describe("cartesian_xlim", base_plot + coord_cartesian(xlim = c(2, 5))),
  describe("scale_x_limits", base_plot + scale_x_continuous(limits = c(2, 5))),
  describe("discrete_default", discrete_plot),
  describe("discrete_xlim_levels", discrete_plot + scale_x_discrete(limits = c("a", "b", "d"))),
  describe("fixed_ratio_1", base_plot + coord_fixed(ratio = 1)),
  describe("fixed_ratio_2", base_plot + coord_fixed(ratio = 2)),
  # coord limits 必须先过 log10 变换：base 0..2，面板 -0.1..2.1
  describe("log10_coord_xlim", log_plot + coord_cartesian(xlim = c(1, 100))),
  # 标度 limits（已变换 0..2）与 coord limits（1..10 → 0..1）同时存在时，
  # coord limits 覆盖标度 limits；x_limits 仍是标度的 get_limits()
  describe("log10_scale_limits_coord", log_limit_plot + coord_cartesian(xlim = c(1, 10))),
  # --- M2-1：coord 全量 ---
  describe("flip_continuous", void(base_plot + coord_flip())),
  describe("flip_discrete", void(discrete_plot + coord_flip())),
  describe("flip_ratio", void(base_plot + coord_flip(ylim = c(0, 40)))),
  describe("trans_log10_x", void(base_plot + coord_transform(x = "log10"))),
  describe("trans_sqrt_y", void(base_plot + coord_transform(y = "sqrt"))),
  describe("trans_reverse_x", void(base_plot + coord_transform(x = "reverse"))),
  describe("equal", void(base_plot + coord_equal())),
  describe("reverse_x", void(base_plot + coord_cartesian(reverse = "x"))),
  # 极坐标：离散 theta（add = 0.5 的展开）+ 连续 r（不展开）
  describe("polar_x", void(discrete_plot + coord_polar())),
  describe("polar_y", void(discrete_plot + coord_polar(theta = "y"))),
  describe("radial_full", void(discrete_plot + coord_radial())),
  describe("radial_partial", void(discrete_plot + coord_radial(start = -0.5 * pi, end = 0.5 * pi))),
  describe("radial_inner", void(discrete_plot + coord_radial(inner.radius = 0.3))),
  describe("polar_start_dir", void(discrete_plot + coord_polar(start = 0.5 * pi, direction = -1))),
  # 次轴：`sec_axis(~ . * 2)` 的断点 / 标签 / 位置
  describe("sec_axis_y", void(base_plot + scale_y_continuous(sec.axis = sec_axis(~ . * 2)))),
  describe("dup_axis_y", void(base_plot + scale_y_continuous(sec.axis = dup_axis())))
)

payload <- list(
  ggplot2 = as.character(packageVersion("ggplot2")),
  data = list(x = coord_data$x, y = coord_data$y, g = coord_data$g),
  log_data = list(x = log_data$x, y = log_data$y),
  cases = cases
)

dir.create(dirname(out_path), recursive = TRUE, showWarnings = FALSE)
writeLines(
  toJSON(payload, auto_unbox = TRUE, digits = NA, pretty = TRUE, null = "null"),
  out_path
)
cat("wrote", out_path, "with", length(cases), "cases\n")
