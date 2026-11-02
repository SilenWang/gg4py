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
  x_discrete <- isTRUE(panel$x$scale_is_discrete)
  y_discrete <- isTRUE(panel$y$scale_is_discrete)
  x_limits <- if (x_discrete) c(1, length(panel$x$get_limits())) else num(panel$x$get_limits())
  y_limits <- if (y_discrete) c(1, length(panel$y$get_limits())) else num(panel$y$get_limits())

  data <- build$data[[1L]]
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
    removed = removed_rows(messages)
  )
}

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
  describe("log10_scale_limits_coord", log_limit_plot + coord_cartesian(xlim = c(1, 10)))
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
