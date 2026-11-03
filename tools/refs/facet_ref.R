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
# 2026-11（SIL-694 修回）追加 `extra` 段，覆盖此前缺口的 9 个 case：
#
#   wrap_numeric / wrap_logical / wrap_na_numeric / wrap_na_str
#       布局列保留原始类型（numeric / logical / character），NA 仍是 NA；
#       strip 文本走 label_value（逻辑值 TRUE/FALSE，NA 为 "NA"）。
#   grid_sparse              grid(drop = TRUE) 仍是两维水平的笛卡尔积（4 面板）。
#   wrap_drop_false_unused   factor 有 3 个 levels、数据只出现 2 个 → 3 面板。
#   grid_drop_false_unused   同上，grid 一行。
#   wrap_multirow            7 面板 3 行：每行自带 strip，行间有 panel.spacing。
#   grid_strip_text_y_20     strip.text.y 字号改变 → 右 strip 宽度跟着变。
#
# 只读不算：Python 侧 tests/test_facet_r_parity.py 用同一份数据逐值比。

suppressPackageStartupMessages({
  library(ggplot2)
  library(jsonlite)
  library(svglite)
})

# 度量设备与渲染产线一致：`refs:cases` 的 expected.svg 用 svglite 画，
# 所以 strip / 面板尺寸也要在 svglite 上读——pdf 设备的字面（Helvetica）比
# svglite（Arimo）高 1.4pt，混用会让 strip 行高对不上（SIL-715 #8）。
# 不要开默认绘图设备：否则 ggplot 会在 CWD 留下 Rplots.pdf（产物不可复现）。
invisible(svglite(tempfile(fileext = ".svg"), width = 4, height = 3))

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

# extra 段的数据自带类型：JSON 里数字 / 布尔 / 字符串分得开，factor 另给 levels。
data_payload <- function(df) {
  columns <- lapply(df, function(col) {
    if (is.factor(col)) as.character(col) else unname(col)
  })
  list(
    columns = columns,
    types = as.list(vapply(df, function(col) class(col)[1], "")),
    levels = lapply(df, function(col) if (is.factor(col)) levels(col) else NULL)
  )
}

# 布局列保留 R 的原始类型（numeric / logical / factor / character）；NA 写成 null。
typed_layout_records <- function(build) {
  layout <- build$layout$layout
  vars <- facet_vars(layout)
  lapply(seq_len(nrow(layout)), function(i) {
    record <- list(
      PANEL = as.integer(layout$PANEL[i]),
      ROW = as.integer(layout$ROW[i]),
      COL = as.integer(layout$COL[i])
    )
    for (name in vars) {
      record[[name]] <- layout[[name]][i]
    }
    record$SCALE_X <- as.integer(layout$SCALE_X[i])
    record$SCALE_Y <- as.integer(layout$SCALE_Y[i])
    record
  })
}

# label_value 的显示文本（strip 上真正写的字）。
label_records <- function(build) {
  layout <- build$layout$layout
  vars <- facet_vars(layout)
  labels <- build$layout$facet$params$labeller(layout[vars])
  lapply(seq_len(nrow(layout)), function(i) {
    record <- list()
    # 多变量 labeller（label_both / label_context）返回的是**无名**列表，
    # 只能按位置取；单变量时按名字取。
    for (j in seq_along(vars)) {
      name <- vars[[j]]
      value <- if (name %in% names(labels)) labels[[name]][i] else labels[[j]][i]
      # grid 把 NA 标签渲染成 "NA"（`grid::textGrob(label = NA)` 的显示）。
      record[[name]] <- if (length(value) == 0 || is.na(value)) "NA" else as.character(value)
    }
    record
  })
}

# wrap 多行 / strip.text.y 只记录结构关系（R 的 gtable 里还有 0cm 占位行，
# 绝对行号不能直接与 Python 比）：
#   - 每个面板行上方都有一条 top strip；
#   - 面板行之间有一条 panel.spacing 行（5.5points）；
#   - strip 的行高 / 列宽。
structure_summary <- function(plot) {
  grob <- ggplotGrob(plot)
  panels <- grob$layout[grepl("^panel", grob$layout$name), , drop = FALSE]
  strips <- grob$layout[grepl("^strip", grob$layout$name), , drop = FALSE]
  top <- strips[startsWith(as.character(strips$name), "strip-t"), , drop = FALSE]
  heights <- as.character(grob$heights)
  between <- seq_len(length(heights)) > min(panels$t) &
    seq_len(length(heights)) < max(panels$t)
  list(
    panel_row_count = length(unique(panels$t)),
    panel_rows = as.character(grob$heights[sort(unique(panels$t))]),
    top_strip_count = nrow(top),
    top_strip_rows_above_panels = all((top$t + 1L) %in% panels$t),
    strip_heights = unname(as.character(grob$heights[top$t])),
    panel_spacing_rows = sum(heights[between] == "5.5points"),
    strip_widths = unname(as.character(grob$widths[strips$l]))
  )
}

describe_extra <- function(name, plot, df, structure = FALSE) {
  build <- ggplot_build(plot)
  vars <- facet_vars(build$layout$layout)
  case <- list(
    name = name,
    data = data_payload(df),
    layout = typed_layout_records(build),
    layout_types = as.list(vapply(
      build$layout$layout[vars],
      function(col) class(col)[1],
      ""
    )),
    labels = label_records(build),
    panels = panel_params(build)
  )
  if (structure) {
    case$structure <- structure_summary(plot)
  }
  case
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

# --- extra：SIL-694 的缺口用例 -------------------------------------------

num_data <- data.frame(
  x = 1:4,
  y = 1:4,
  g = c(2, 2, 1, 1)
)
logical_data <- data.frame(
  x = 1:4,
  y = 1:4,
  g = c(TRUE, TRUE, FALSE, FALSE)
)
na_num_data <- data.frame(
  x = 1:4,
  y = 1:4,
  g = c(1, 1, NA, NA)
)
na_str_data <- data.frame(
  x = 1:4,
  y = 1:4,
  g = c("a", "a", NA, NA)
)
sparse_data <- data.frame(
  x = 1:3,
  y = 1:3,
  a = factor(c("p", "p", "q"), levels = c("q", "p")),
  b = factor(c("u", "v", "u"), levels = c("v", "u"))
)
unused_data <- data.frame(
  x = 1:3,
  y = 1:3,
  a = factor(c("a", "a", "b"), levels = c("a", "b", "c"))
)
multirow_data <- data.frame(
  x = 1:9,
  y = 1:9,
  g = factor(letters[1:9])
)

extra <- list(
  describe_extra(
    "wrap_numeric",
    ggplot(num_data, aes(x = x, y = y)) + geom_point() + facet_wrap(~g),
    num_data
  ),
  describe_extra(
    "wrap_logical",
    ggplot(logical_data, aes(x = x, y = y)) + geom_point() + facet_wrap(~g),
    logical_data
  ),
  describe_extra(
    "wrap_na_numeric",
    ggplot(na_num_data, aes(x = x, y = y)) + geom_point() + facet_wrap(~g),
    na_num_data
  ),
  describe_extra(
    "wrap_na_str",
    ggplot(na_str_data, aes(x = x, y = y)) + geom_point() + facet_wrap(~g),
    na_str_data
  ),
  describe_extra(
    "grid_sparse",
    ggplot(sparse_data, aes(x = x, y = y)) + geom_point() + facet_grid(b ~ a),
    sparse_data
  ),
  describe_extra(
    "wrap_drop_false_unused",
    ggplot(unused_data, aes(x = x, y = y)) +
      geom_point() +
      facet_wrap(~a, drop = FALSE),
    unused_data
  ),
  describe_extra(
    "grid_drop_false_unused",
    ggplot(unused_data, aes(x = x, y = y)) +
      geom_point() +
      facet_grid(. ~ a, drop = FALSE),
    unused_data
  ),
  describe_extra(
    "wrap_multirow",
    ggplot(multirow_data, aes(x = x, y = y)) + geom_point() + facet_wrap(~g),
    multirow_data,
    structure = TRUE
  ),
  describe_extra(
    "grid_strip_text_y_20",
    ggplot(sparse_data, aes(x = x, y = y)) +
      geom_point() +
      facet_grid(b ~ a) +
      theme(strip.text.y = element_text(size = 20)),
    sparse_data,
    structure = TRUE
  )
)

# --- full：M2-3 facet 全量（SIL-733）---------------------------------------
#
#   free scales 的逐面板 range、space = "free" 的面板 null 权重（宽高比）、
#   margins 的 (all) 面板、labeller 各形态（逐变量 strip）、strip 主题
#   （字号 / angle）、strip.placement、polar × facet。
#
# 记录 gtable 的 panel 列 / 行单位串（`1.1null` 这类）与每条 strip 的单元格
# 宽高（cm）—— Python 侧 `facet_table()` 用同一份数值逐项比。

# 离散 x：space = "free_x" 时列宽按水平数分配（连续 x 按 range 差）。
discrete_data <- data.frame(
  x = factor(c("a", "a", "b", "b", "c", "c", "a", "b", "c", "a"),
             levels = c("a", "b", "c")),
  y = c(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
  g = factor(c("p", "p", "p", "q", "q", "q", "r", "r", "r", "p"),
             levels = c("p", "q", "r")),
  h = factor(c("u", "u", "u", "u", "v", "v", "v", "v", "u", "v"),
             levels = c("v", "u"))
)

full_gtable <- function(plot) {
  grob <- ggplotGrob(plot)
  panels <- grob$layout[grepl("^panel", grob$layout$name), , drop = FALSE]
  strips <- grob$layout[grepl("^strip", grob$layout$name), , drop = FALSE]
  list(
    panel_columns = as.character(grob$widths[sort(unique(panels$l))]),
    panel_rows = as.character(grob$heights[sort(unique(panels$t))]),
    respect = isTRUE(grob$respect),
    strips = lapply(seq_len(nrow(strips)), function(i) {
      list(
        name = as.character(strips$name[i]),
        t = as.integer(strips$t[i]),
        l = as.integer(strips$l[i]),
        width = as.character(grob$widths[strips$l[i]]),
        height = as.character(grob$heights[strips$t[i]])
      )
    })
  )
}

describe_full <- function(name, plot, df) {
  cat("case:", name, "\n")
  build <- ggplot_build(plot)
  list(
    name = name,
    data = data_payload(df),
    layout = typed_layout_records(build),
    labels = label_records(build),
    panels = panel_params(build),
    gtable = full_gtable(plot)
  )
}

full <- list(
  describe_full(
    "wrap_free_x",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_wrap(~a, ncol = 2, scales = "free_x"),
    facet_data
  ),
  describe_full(
    "wrap_free_y",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_wrap(~a, ncol = 2, scales = "free_y"),
    facet_data
  ),
  describe_full(
    "grid_free_x",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_grid(b ~ a, scales = "free_x"),
    facet_data
  ),
  describe_full(
    "grid_free_y",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_grid(b ~ a, scales = "free_y"),
    facet_data
  ),
  describe_full(
    "wrap_space_free_x",
    ggplot(discrete_data, aes(x = x, y = y)) +
      geom_point() +
      facet_wrap(~g, space = "free_x", scales = "free"),
    discrete_data
  ),
  describe_full(
    "wrap_space_free_y",
    ggplot(discrete_data, aes(x = x, y = y)) +
      geom_point() +
      facet_wrap(~g, space = "free_y", scales = "free"),
    discrete_data
  ),
  describe_full(
    "grid_space_free",
    ggplot(discrete_data, aes(x = x, y = y)) +
      geom_point() +
      facet_grid(h ~ g, space = "free", scales = "free"),
    discrete_data
  ),
  describe_full(
    "grid_margins",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_grid(b ~ a, margins = TRUE),
    facet_data
  ),
  describe_full(
    "grid_margins_var",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_grid(b ~ a, margins = "a"),
    facet_data
  ),
  describe_full(
    "wrap_label_both",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_wrap(~a + b, labeller = "label_both"),
    facet_data
  ),
  describe_full(
    "wrap_label_context",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_wrap(~a, labeller = "label_context"),
    facet_data
  ),
  describe_full(
    "grid_label_both",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_grid(b ~ a, labeller = "label_both"),
    facet_data
  ),
  describe_full(
    "wrap_labeller_named",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_wrap(~a, labeller = labeller(a = c(q = "Q level", p = "P level"))),
    facet_data
  ),
  describe_full(
    "strip_y_angle0",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_grid(b ~ a) +
      theme(strip.text.y = element_text(angle = 0)),
    facet_data
  ),
  describe_full(
    "strip_x_size20",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_wrap(~a, ncol = 2) +
      theme(strip.text.x = element_text(size = 20)),
    facet_data
  ),
  describe_full(
    "strip_outside",
    ggplot(facet_data, aes(x = x, y = y)) +
      geom_point() +
      facet_wrap(~a, ncol = 2) +
      theme(strip.placement = "outside"),
    facet_data
  ),
  describe_full(
    "polar_facet",
    ggplot(facet_data, aes(x = a, y = y)) +
      geom_point() +
      coord_polar() +
      facet_wrap(~b, ncol = 2),
    facet_data
  )
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
  cases = cases,
  extra = extra,
  full = full
)

dir.create(dirname(out_path), recursive = TRUE, showWarnings = FALSE)
writeLines(
  toJSON(payload, auto_unbox = TRUE, digits = NA, pretty = TRUE, na = "null", null = "null"),
  out_path
)
cat("wrote", out_path, "with", length(cases), "cases\n")
