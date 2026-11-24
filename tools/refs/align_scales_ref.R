#!/usr/bin/env Rscript
# SIL-1000：`align_scales()` 与 aplot 0.3.2 的 `xlim2()` / `ylim2()` /
# `adjust_coord()` 对拍夹具。
#
#     pixi run -e refs refs:align
#
# 产出 `tests/fixtures/align_scales_r_reference.json`（入库；CI 不装 R）。
# 口径与 aplot 的源码一致：
#
# - `xlim2(gg)` 无 `limits=` 时取 `ggfun::xrange(gg, region = "plot")`
#   = `panel_params[[1]]$x$limits`（**标度空间**、不含 expand）；
# - 应用到目标图时 `set_scale_limits()` 保留原 scale 的 `expand`；
# - 离散轴上 aplot 还会写 `continuous_limits` 并把 `expand` 改成 `c(0, 0)`；
# - 裁剪行数**不**读 "Removed N rows" 消息（`ggplot_build()` 只 censor 不断行、
#   也不打印它）：数 `data[[1]]` 里由 censor 新增的 NA；双轴 case 取 x / y 的
#   行级并集。
#
# 本脚本不重算任何公式：夹具里的每个数都是 R 跑出来的，Python 侧只比夹具。

suppressPackageStartupMessages({
  library(ggplot2)
  library(aplot)
})

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
        function(key) paste0(strrep(" ", indent + 2), '"', json_escape(key), '": ',
                             to_json(value[[key]], indent + 2)),
        character(1)
      )
      return(paste0("{\n", paste(items, collapse = ",\n"), "\n", pad, "}"))
    }
    items <- vapply(value, function(item) to_json(item, indent + 2), character(1))
    return(paste0("[\n", paste0(strrep(" ", indent + 2), items, collapse = ",\n"), "\n", pad, "]"))
  }
  if (is.character(value)) {
    if (length(value) == 1) return(paste0('"', json_escape(value), '"'))
    return(to_json(as.list(value), indent))
  }
  if (is.logical(value)) {
    if (length(value) == 1) return(if (is.na(value)) "null" else if (value) "true" else "false")
    return(to_json(as.list(value), indent))
  }
  if (is.numeric(value) || is.integer(value)) {
    values <- ifelse(is.na(value), "null", format(value, digits = 17, scientific = FALSE))
    if (length(values) == 1) return(trimws(values))
    return(paste0("[", paste(trimws(values), collapse = ", "), "]"))
  }
  paste0('"', json_escape(as.character(value)), '"')
}

# 捕获 ggplot_build() 的 "Removed N rows" 消息，返回值和行数之和。
with_removed <- function(thunk) {
  messages <- character()
  value <- withCallingHandlers(
    thunk(),
    message = function(condition) {
      messages <<- c(messages, conditionMessage(condition))
      invokeRestart("muffleMessage")
    }
  )
  hits <- regmatches(messages, regexpr("Removed [0-9]+ rows", messages))
  total <- 0
  for (hit in hits) {
    total <- total + as.integer(sub("Removed ([0-9]+) rows", "\\1", hit))
  }
  list(value = value, removed = total)
}

axis_view <- function(panel_params, axis) {
  view <- panel_params[[axis]]
  limits <- view$limits
  breaks <- tryCatch(view$get_breaks(), error = function(error) NULL)
  labels <- tryCatch(view$get_labels(breaks), error = function(error) NULL)
  list(
    limits = if (is.character(limits)) as.list(limits) else as.numeric(limits),
    discrete = is.character(limits),
    panel_range = as.numeric(panel_params[[paste0(axis, ".range")]]),
    breaks = if (is.null(breaks)) {
      NULL
    } else if (is.character(breaks)) {
      as.list(breaks)
    } else {
      as.numeric(breaks)
    },
    labels = if (is.null(labels)) NULL else as.list(as.character(labels)),
    expand = as.numeric(view$expand %||% c(0, 0))
  )
}

`%||%` <- function(left, right) if (is.null(left)) right else left

numeric_data <- function(x, y = x) data.frame(x = x, y = y)

discrete_data <- function(g) data.frame(g = g)

point_plot <- function(data, mapping = aes(x = x, y = y)) {
  ggplot(data, mapping) + geom_point()
}

base_case <- function(main, child, axis = "x", limits = NULL, prune_axis = axis) {
  aligner <- if (axis == "x") xlim2 else ylim2
  main_build <- ggplot_build(main)
  child_build <- ggplot_build(child)
  aligned <- child + aligner(main, limits = limits)
  built <- with_removed(function() ggplot_build(aligned))
  panel_params <- built$value$layout$panel_params[[1]]
  # `ggplot_build()` 不打印 "Removed N rows"（那是绘制期 `remove_missing()` 的事）：
  # 裁剪量直接数 `data[[1]]` 里由 censor 新产生的 NA。
  child_values <- child_build$data[[1]][[prune_axis]]
  aligned_values <- built$value$data[[1]][[prune_axis]]
  # 行数可能变（`stat_count()` 在统计前就丢掉越界行），所以按「非 NA 值的减少量」
  # 统计，而不是逐位置比较 NA。
  added_na <- sum(!is.na(child_values)) - sum(!is.na(aligned_values))
  list(
    axis = axis,
    prune_axis = prune_axis,
    main = axis_view(main_build$layout$panel_params[[1]], axis),
    aligned = axis_view(panel_params, axis),
    removed = as.integer(added_na),
    coord = class(aligned$coordinates)[1]
  )
}

cases <- list()

# --- 连续：first（aplot 的唯一默认口径） ------------------------------------
main <- point_plot(numeric_data(c(1, 2, 3)))
child <- point_plot(numeric_data(c(1, 2, 4, 5)))
cases[[length(cases) + 1]] <- c(list(name = "continuous_first"), base_case(main, child))

# --- 连续：显式 limits ------------------------------------------------------
cases[[length(cases) + 1]] <- c(
  list(name = "continuous_explicit"),
  base_case(main, child, limits = c(-1, 6))
)

# --- 离散 ------------------------------------------------------------------
main_bar <- ggplot(discrete_data(c("a", "b")), aes(x = g)) + geom_bar()
child_bar <- ggplot(discrete_data(c("a", "b", "c")), aes(x = g)) + geom_bar()
cases[[length(cases) + 1]] <- c(list(name = "discrete_first"), base_case(main_bar, child_bar))

# --- log10（记录 aplot 二次变换的实际值） ----------------------------------
main_log <- point_plot(numeric_data(c(1, 10))) + scale_x_log10()
child_log <- point_plot(numeric_data(c(1, 100, 1000))) + scale_x_log10()
cases[[length(cases) + 1]] <- c(list(name = "log10_first"), base_case(main_log, child_log))

# --- reverse ---------------------------------------------------------------
main_rev <- point_plot(numeric_data(c(1, 2))) + scale_x_reverse()
child_rev <- point_plot(numeric_data(c(3, 4))) + scale_x_reverse()
cases[[length(cases) + 1]] <- c(list(name = "reverse_first"), base_case(main_rev, child_rev))

# --- Date -----------------------------------------------------------------
days <- as.Date(c("2020-01-01", "2020-06-01"))
later <- as.Date(c("2020-06-01", "2021-01-01"))
main_date <- point_plot(data.frame(x = days, y = c(1, 2)))
child_date <- point_plot(data.frame(x = later, y = c(2, 3)))
cases[[length(cases) + 1]] <- c(list(name = "date_first"), base_case(main_date, child_date))

# --- coord_flip（aplot 的 axis 是视觉轴；x/y 取值故意不同） -----------------
main_flip <- point_plot(data.frame(x = c(1, 2), y = c(10, 20))) + coord_flip()
child_flip <- point_plot(data.frame(x = c(1, 2), y = c(5, 25))) + coord_flip()
cases[[length(cases) + 1]] <- c(
  list(name = "flip_first"),
  base_case(main_flip, child_flip, prune_axis = "y")
)

# --- 双轴同时裁剪（xlim2 + ylim2） -----------------------------------------
dual_case <- function(name, main, child) {
  main_build <- ggplot_build(main)
  child_build <- ggplot_build(child)
  aligned <- child + xlim2(main) + ylim2(main)
  built <- with_removed(function() ggplot_build(aligned))
  panel_params <- built$value$layout$panel_params[[1]]
  child_data <- child_build$data[[1]]
  aligned_data <- built$value$data[[1]]
  removed_axis <- function(axis) {
    as.integer(sum(!is.na(child_data[[axis]])) - sum(!is.na(aligned_data[[axis]])))
  }
  row_missing <- function(data) is.na(data$x) | is.na(data$y)
  list(
    name = name,
    axis = "xy",
    main = list(
      x = axis_view(main_build$layout$panel_params[[1]], "x"),
      y = axis_view(main_build$layout$panel_params[[1]], "y")
    ),
    aligned = list(
      x = axis_view(panel_params, "x"),
      y = axis_view(panel_params, "y")
    ),
    removed = as.integer(sum(row_missing(aligned_data)) - sum(row_missing(child_data))),
    removed_x = removed_axis("x"),
    removed_y = removed_axis("y"),
    coord = class(aligned$coordinates)[1]
  )
}

# x 越界在第 3、4 行、y 越界在第 2、3 行 → 行级并集 3 行（不是 2 + 2）。
cases[[length(cases) + 1]] <- dual_case(
  "dual_axis_first",
  point_plot(numeric_data(c(1, 2, 3), c(1, 2, 3))),
  point_plot(numeric_data(c(1, 2, 4, 5), c(1, 5, 4, 2)))
)

# --- adjust_coord：主图 coord_fixed、子图 cartesian ------------------------
main_fixed <- point_plot(numeric_data(c(0, 10), c(0, 5))) + coord_fixed()
child_plain <- point_plot(numeric_data(c(0, 10), c(0, 5)))
aligned_child <- child_plain + xlim2(main_fixed)
# `as.aplot()` 不导出；结构照 `aplot/R/aplot.R` 手工搭（`adjust_coord()` 只读
# plotlist / height / layout 这几个字段）。
aplot_object <- structure(
  list(
    plotlist = list(main_fixed, aligned_child),
    width = c(1, 1),
    height = c(1, 1),
    layout = matrix(c(1, 2), ncol = 1),
    n = 2,
    main_col = 1,
    main_row = 1,
    spacing = NULL,
    guide_area = NULL,
    guide_layout = NULL
  ),
  class = c("aplot", "ggplot")
)
adjusted <- aplot:::adjust_coord(aplot_object, 2, 1, type = "height")
cases[[length(cases) + 1]] <- list(
  name = "adjust_coord_ratio",
  axis = "xy",
  ratio = as.numeric(adjusted$plotlist[[2]]$coordinates$ratio),
  main_was_fixed = !is.null(main_fixed$coordinates$ratio)
)

fixture <- list(
  aplot = as.character(packageVersion("aplot")),
  ggplot2 = as.character(packageVersion("ggplot2")),
  patchwork = as.character(packageVersion("patchwork")),
  cases = cases
)

target <- file.path("tests", "fixtures", "align_scales_r_reference.json")
writeLines(to_json(fixture), target, useBytes = TRUE)
message("wrote ", target, " (", length(cases), " cases)")
