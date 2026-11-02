#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/facet_r_reference.json —— 分面（M1-6）的 R 侧参考值。
#
#   pixi run -e refs refs:facet
#
# 对 6 个 case 跑真正的 ggplot2 4.0.3：
#
#   1. wrap_ncol2            facet_wrap(~a, ncol = 2)：2 列面板
#   2. wrap_as_table_false   facet_wrap(~c, ncol = 2, as.table = FALSE)：2×2，从下往上
#   3. grid_2x2              facet_grid(b ~ a)：2×2 行列
#   4. grid_as_table_false   facet_grid(b ~ a, as.table = FALSE)：行变量倒序
#   5. grid_free             facet_grid(b ~ a, scales = "free")：x 按列、y 按行
#   6. wrap_free             facet_wrap(~a, ncol = 2, scales = "free")：每面板一套
#
# 记录：
#   - ggplot_build(p)$layout$layout 的 PANEL / ROW / COL / SCALE_X / SCALE_Y
#     与分面变量（顺序按 factor levels，不是出现顺序）；
#   - 每个面板的 panel_params[[i]]$x.range / y.range（含 expand）；
#   - ggplotGrob(p) 的 panel 宽高单位（`1null`）+ panel / strip 的布局名字。
#
# 只读不算：Python 侧 tests/test_facet_r_parity.py 用同一份数据逐值比。

suppressPackageStartupMessages({
  library(ggplot2)
  library(jsonlite)
})

# 不开默认绘图设备：否则 ggplot 会在 CWD 留下 Rplots.pdf（产物不可复现）。
invisible(pdf(NULL))

out_path <- "tests/fixtures/facet_r_reference.json"

# factor 的 levels 故意与出现顺序不同：分面顺序必须按 levels。
facet_data <- data.frame(
  x = c(1, 2, 3, 4, 10, 20, 30, 40),
  y = c(10, 20, 30, 40, 100, 200, 300, 400),
  a = factor(c("p", "p", "q", "q", "p", "p", "q", "q"), levels = c("q", "p")),
  b = factor(c("u", "u", "u", "u", "v", "v", "v", "v"), levels = c("v", "u")),
  c = factor(c("d", "d", "c", "c", "b", "b", "a", "a"), levels = c("d", "c", "b", "a"))
)

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

facet_vars <- function(layout) {
  setdiff(names(layout), c("PANEL", "ROW", "COL", "SCALE_X", "SCALE_Y", "COORD"))
}

layout_records <- function(build) {
  layout <- build$layout$layout
  vars <- facet_vars(layout)
  lapply(seq_len(nrow(layout)), function(i) {
    record <- list(
      PANEL = as.integer(layout$PANEL[i]),
      ROW = as.integer(layout$ROW[i]),
      COL = as.integer(layout$COL[i]),
      SCALE_X = as.integer(layout$SCALE_X[i]),
      SCALE_Y = as.integer(layout$SCALE_Y[i])
    )
    for (name in vars) {
      record[[name]] <- as.character(layout[[name]][i])
    }
    record
  })
}

panel_params <- function(build) {
  params <- build$layout$panel_params
  lapply(seq_along(params), function(i) {
    list(
      PANEL = as.integer(i),
      x_range = num(params[[i]]$x.range),
      y_range = num(params[[i]]$y.range)
    )
  })
}

gtable_summary <- function(plot) {
  grob <- ggplotGrob(plot)
  panels <- grob$layout[grepl("^panel", grob$layout$name), , drop = FALSE]
  strips <- grob$layout[grepl("^strip", grob$layout$name), , drop = FALSE]
  columns <- sort(unique(panels$l))
  rows <- sort(unique(panels$t))
  list(
    panel_columns = as.character(grob$widths[columns]),
    panel_rows = as.character(grob$heights[rows]),
    panel_names = sort(as.character(panels$name)),
    strip_names = sort(as.character(strips$name)),
    strip_sizes = lapply(seq_len(nrow(strips)), function(i) {
      list(
        name = as.character(strips$name[i]),
        width = as.character(grob$widths[strips$l[i]]),
        height = as.character(grob$heights[strips$t[i]])
      )
    }),
    strip_positions = lapply(seq_len(nrow(strips)), function(i) {
      list(
        name = as.character(strips$name[i]),
        t = as.integer(strips$t[i]),
        l = as.integer(strips$l[i]),
        b = as.integer(strips$b[i]),
        r = as.integer(strips$r[i])
      )
    })
  )
}

describe <- function(name, plot, with_gtable = FALSE) {
  build <- ggplot_build(plot)
  case <- list(
    name = name,
    layout = layout_records(build),
    panels = panel_params(build)
  )
  if (with_gtable) {
    case$gtable <- gtable_summary(plot)
  }
  case
}

base_plot <- ggplot(facet_data, aes(x = x, y = y)) + geom_point()

cases <- list(
  describe("wrap_ncol2", base_plot + facet_wrap(~a, ncol = 2), with_gtable = TRUE),
  describe("wrap_as_table_false", base_plot + facet_wrap(~c, ncol = 2, as.table = FALSE)),
  describe("grid_2x2", base_plot + facet_grid(b ~ a), with_gtable = TRUE),
  describe("grid_as_table_false", base_plot + facet_grid(b ~ a, as.table = FALSE)),
  describe("grid_free", base_plot + facet_grid(b ~ a, scales = "free")),
  describe("wrap_free", base_plot + facet_wrap(~a, ncol = 2, scales = "free"))
)

payload <- list(
  ggplot2 = as.character(packageVersion("ggplot2")),
  data = list(
    x = facet_data$x,
    y = facet_data$y,
    a = as.character(facet_data$a),
    b = as.character(facet_data$b),
    c = as.character(facet_data$c),
    a_levels = levels(facet_data$a),
    b_levels = levels(facet_data$b),
    c_levels = levels(facet_data$c)
  ),
  cases = cases
)

dir.create(dirname(out_path), recursive = TRUE, showWarnings = FALSE)
writeLines(
  toJSON(payload, auto_unbox = TRUE, digits = NA, pretty = TRUE, null = "null"),
  out_path
)
cat("wrote", out_path, "with", length(cases), "cases\n")
