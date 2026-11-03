#!/usr/bin/env Rscript
#
# M1-8 的 stat 对拍产线：生成 tests/fixtures/stat_r_reference.json
#
#   pixi run -e refs refs:stat
#
# 只在「换 pin」或「有意改口径」时重跑；产物入库，CI 不装 R。
#
# 夹具口径：
#   - 每个 case 记录 `ggplot_build(p)$data[[1]]` 的列名、列序、kind、逐值
#     （NA / NaN / Inf 一律写 null，见 fmt_num）；
#   - `ggplot_build()` 与 `ggplotGrob()` 期间的 warning 逐条记录（stat 的
#     remove_missing 与 geom 的 handle_na 都会发）；
#   - stat_smooth 的 loess 两种面都覆盖：`smooth_se` / `smooth_no_se` /
#     `smooth_span` / `smooth_n` / `smooth_group` 显式用 `surface = "direct"`、
#     `statistics = "exact"`、`trace.hat = "exact"`（gg4py 的 direct 实现口径）；
#     `smooth_default` / `smooth_horizontal_fullrange` 走 R 的默认
#     `surface = "interpolate"`（kd 树 + Hermite 插值），gg4py 逐值对齐到 1e-6。
#
# `ggplotGrob()` 会打开默认设备（pdf() → 仓库根目录的 Rplots.pdf）。显式开一个
# 临时 pdf 设备并在 on.exit 里关掉，产线跑完不留未跟踪文件（SIL-698 #6）。

suppressPackageStartupMessages({
  library(ggplot2)
})

if (!identical(as.character(packageVersion("ggplot2")), "4.0.3")) {
  stop(sprintf(
    "ggplot2 必须是 4.0.3（上游 pin），当前是 %s",
    as.character(packageVersion("ggplot2"))
  ))
}
if (!isTRUE(l10n_info()[["UTF-8"]])) {
  stop("R 不在 UTF-8 locale 下：用 `LC_ALL=C.UTF-8 LANG=C.UTF-8` 重跑")
}

repo <- normalizePath(".")
fixture_path <- file.path(repo, "tests", "fixtures", "stat_r_reference.json")

# ---------------------------------------------------------------------------
# 极简 JSON 输出（与 tools/refs/geom_ref.R 同一份，不引入 jsonlite）
# ---------------------------------------------------------------------------

json_escape <- function(text) {
  text <- gsub("\\", "\\\\", text, fixed = TRUE)
  text <- gsub("\"", "\\\"", text, fixed = TRUE)
  text <- gsub("\n", "\\n", text, fixed = TRUE)
  text <- gsub("\t", "\\t", text, fixed = TRUE)
  paste0("\"", text, "\"")
}

# 非有限值（NA / NaN / Inf）统一写 null：ggcore 的 float 列用 na_mask 表达 NA，
# ColumnTable 不能表达 Inf，夹具里也不出现 Inf（Inf 观测在 stat 里会被删掉）。
fmt_num <- function(value) {
  if (!is.finite(value)) {
    return("null")
  }
  sprintf("%.17g", value)
}

to_json <- function(x, indent = 0L) {
  pad <- strrep("  ", indent)
  pad2 <- strrep("  ", indent + 1L)
  if (is.null(x)) {
    return("null")
  }
  if (is.atomic(x) && length(x) == 1L && is.na(x)) {
    return("null")
  }
  if (is.atomic(x) && length(x) > 1L) {
    items <- vapply(seq_along(x), function(i) to_json(x[[i]], indent), character(1))
    return(paste0("[", paste(items, collapse = ", "), "]"))
  }
  if (is.logical(x) && length(x) == 1L) {
    if (is.na(x)) {
      return("null")
    }
    return(if (isTRUE(x)) "true" else "false")
  }
  if (is.numeric(x) && length(x) == 1L) {
    return(fmt_num(x))
  }
  if (is.character(x) && length(x) == 1L) {
    return(json_escape(x))
  }
  if (is.list(x)) {
    nm <- names(x)
    if (!is.null(nm)) {
      if (length(x) == 0L) {
        return("{}")
      }
      items <- vapply(seq_along(x), function(i) {
        paste0(pad2, json_escape(nm[[i]]), ": ", to_json(x[[i]], indent + 1L))
      }, character(1))
      return(paste0("{\n", paste(items, collapse = ",\n"), "\n", pad, "}"))
    }
    if (length(x) == 0L) {
      return("[]")
    }
    items <- vapply(x, function(el) paste0(pad2, to_json(el, indent + 1L)), character(1))
    return(paste0("[\n", paste(items, collapse = ",\n"), "\n", pad, "]"))
  }
  if (length(x) == 0L) {
    return("[]")
  }
  stop("to_json: unsupported value")
}

# 向量 → JSON 数组（NA / NaN → null）。因子先转字符，保持 R 的水平顺序。
vector_json <- function(values) {
  if (is.factor(values)) {
    values <- as.character(values)
  }
  if (is.list(values)) {
    return(lapply(values, function(item) {
      if (length(item) == 0L) return(NULL)
      lapply(seq_along(item), function(i) item[[i]])
    }))
  }
  lapply(seq_along(values), function(i) values[[i]])
}

column_kind <- function(values) {
  if (is.list(values)) return("list")
  if (is.logical(values)) return("bool")
  if (is.integer(values)) return("int")
  if (inherits(values, "mapped_discrete")) return("float")
  if (is.numeric(values)) return("float")
  if (is.factor(values) || is.character(values)) return("str")
  stop("column_kind: unsupported column class ", class(values)[1])
}

dataframe_json <- function(data) {
  columns <- lapply(names(data), function(name) {
    values <- data[[name]]
    column <- list(name = name, kind = column_kind(values), values = vector_json(values))
    if (is.factor(values)) {
      column$levels <- as.list(levels(values))
    }
    column
  })
  names(columns) <- NULL
  list(rows = nrow(data), columns = columns)
}

# ---------------------------------------------------------------------------
# 采集：build + draw 两段的 warning 都记下来（不留下设备文件）
# ---------------------------------------------------------------------------

collect <- function(expr) {
  messages <- character()
  grDevices::pdf(file = tempfile(fileext = ".pdf"))
  on.exit(grDevices::dev.off(), add = TRUE)
  value <- withCallingHandlers(
    expr,
    warning = function(w) {
      messages <<- c(messages, conditionMessage(w))
      invokeRestart("muffleWarning")
    }
  )
  list(value = value, warnings = messages)
}

record_case <- function(name, plot, description, stat = "identity") {
  built <- collect(ggplot_build(plot))
  drawn <- collect(invisible(ggplotGrob(plot)))
  list(
    description = description,
    stat = stat,
    built = dataframe_json(built$value$data[[1]]),
    warnings = as.list(unique(c(built$warnings, drawn$warnings)))
  )
}

# ---------------------------------------------------------------------------
# 数据集（Python 侧的 tests/test_stat_r_parity.py 用同一份数字）
# ---------------------------------------------------------------------------

df_bin <- data.frame(x = c(1, 1, 2, 2, 2, 3, 4, 4, 4, 4))
df_bin_grp <- data.frame(
  x = c(1, 2, 3, 1.5, 2.5, 3.5, 2, 4),
  g = rep(c("a", "b"), each = 4),
  stringsAsFactors = FALSE
)
df_cnt <- data.frame(
  cls = c("a", "b", "a", "c", "b", "a", "c", "c"),
  grp = c("p", "p", "q", "p", "q", "p", "p", "q"),
  stringsAsFactors = FALSE
)
df_cnt_h <- data.frame(
  cls = c("a", "b", "a", "c", "b"),
  v = c(0.3, 0.7, 0.5, 0.9, 0.2),
  stringsAsFactors = FALSE
)
df_box <- data.frame(
  cls = rep(c("a", "b"), each = 9),
  v = c(1, 2, 3, 4, 5, 6, 7, 8, 20, 2, 3, 4, 5, 6, 7, 8, 9, 25),
  stringsAsFactors = FALSE
)
df_box_none <- data.frame(
  cls = rep(c("a", "b"), each = 6),
  v = c(1, 2, 3, 4, 5, 6, 2, 3, 4, 5, 6, 7),
  stringsAsFactors = FALSE
)
df_box_var <- data.frame(
  cls = rep(c("a", "b", "c"), times = c(4, 8, 6)),
  v = c(1, 2, 3, 4, 1, 2, 3, 4, 5, 6, 7, 8, 2, 3, 4, 5, 6, 7),
  stringsAsFactors = FALSE
)
df_box_inf <- data.frame(
  cls = rep(c("a", "b"), each = 6),
  v = c(1, 2, 3, 4, 5, 100, 2, 3, 4, 5, 6, Inf),
  stringsAsFactors = FALSE
)
df_box_h <- data.frame(
  cls = c("a", "a", "a", "b", "b", "b"),
  v = c(1, 2, 3, 2, 3, 10),
  stringsAsFactors = FALSE
)
df_smooth <- data.frame(
  x = seq(0, 1, length.out = 15),
  y = c(0.1, 0.35, 0.32, 0.45, 0.5, 0.48, 0.62, 0.6,
        0.7, 0.68, 0.78, 0.82, 0.8, 0.9, 0.95)
)
# 横向 smooth：x 是响应、y 是预测变量；fullrange 的 xseq 取的是 **x 标度**
# （0..10），落在预测变量（1..12）之外的点按 R 的 `predLoess()` 给 NA。
df_smooth_h <- data.frame(
  v = seq(0, 10, length.out = 12),
  cls = seq_len(12)
)
df_align <- data.frame(
  x = c(1, 2, 3, 4, 2, 3, 4, 5),
  y = c(1, 2, 1, 2, 2, 1, 2, 1),
  g = rep(c("a", "b"), each = 4),
  stringsAsFactors = FALSE
)
df_align_dup <- data.frame(
  x = c(1, 1, 2, 3, 1, 2, 2, 3),
  y = c(1, 2, 3, 1, 2, 1, 3, 2),
  g = rep(c("a", "b"), each = 4),
  stringsAsFactors = FALSE
)
df_area_negative <- data.frame(
  x = c(1, 2, 3, 1, 2, 3),
  y = c(2, -1, 2, -1, 2, -1),
  g = rep(c("a", "b"), each = 3),
  stringsAsFactors = FALSE
)

# --- M2-6：2D 统计（bin_2d / bin_hex / summary_2d / summary_hex / contour /
#     contour_filled / density_2d / density_2d_filled）----------------------
df_2d <- data.frame(
  x = c(1, 1, 2, 2, 2, 3, 4, 4, 4, 4),
  y = c(1, 2, 2, 3, 4, 4, 1, 3, 4, 5),
  z = c(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
)
# x / y 各一行 NA：`Stat$compute_layer()` 在分箱前删掉（带 "Removed N rows" 警告）。
df_2d_na <- rbind(
  df_2d[1:8, ],
  data.frame(x = NA_real_, y = 1, z = 11),
  data.frame(x = 2, y = NA_real_, z = 12),
  df_2d[9:10, ]
)
df_2d_grp <- cbind(df_2d, g = rep(c("a", "b"), each = 5))
# z 有 NA：summary_2d 的 required_aes 含 z，删行后发警告。
df_2d_zna <- df_2d
df_2d_zna$z[c(2, 7)] <- NA_real_
# 等值线用的规则网格：z = x/2 + y（无重复坐标，等值线顶点落在网格边上）。
grid_contour <- expand.grid(x = 1:5, y = 1:4)
grid_contour$z <- grid_contour$x * 0.5 + grid_contour$y
grid_contour_na <- rbind(grid_contour[1:15, ], data.frame(x = 2, y = 2, z = NA_real_),
                         grid_contour[17:20, ])
# 2D 密度的散点（13 个观测：默认带宽走 MASS::bandwidth.nrd）。
df_density2d <- data.frame(
  x = c(1, 2, 3, 4, 5, 2, 3, 4, 5, 6, 1.5, 2.5, 3.5),
  y = c(2, 3, 2, 4, 3, 5, 4, 5, 3, 2, 3.2, 4.1, 2.8)
)
df_density2d_na <- rbind(
  df_density2d[1:10, ],
  data.frame(x = NA_real_, y = 3),
  df_density2d[11:13, ]
)

# ---------------------------------------------------------------------------
# case
# ---------------------------------------------------------------------------

cases <- list()

# --- stat_bin --------------------------------------------------------------
cases$bin_default <- record_case(
  "bin_default",
  ggplot(df_bin, aes(x)) + geom_histogram(),
  "bin：默认 bins = 30（含空箱）", "bin"
)
cases$bin_width <- record_case(
  "bin_width",
  ggplot(df_bin, aes(x)) + geom_histogram(binwidth = 0.5),
  "bin：指定 binwidth = 0.5", "bin"
)
cases$bin_center <- record_case(
  "bin_center",
  ggplot(df_bin, aes(x)) + geom_histogram(bins = 6, center = 2),
  "bin：center = 2 平移半个箱", "bin"
)
cases$bin_boundary <- record_case(
  "bin_boundary",
  ggplot(df_bin, aes(x)) + geom_histogram(binwidth = 1, boundary = 0),
  "bin：boundary = 0（断点落在整数上）", "bin"
)
cases$bin_closed_left <- record_case(
  "bin_closed_left",
  ggplot(df_bin, aes(x)) + geom_histogram(bins = 5, closed = "left"),
  "bin：closed = left（左闭右开）", "bin"
)
cases$bin_pad <- record_case(
  "bin_pad",
  ggplot(df_bin, aes(x)) + geom_histogram(bins = 4, pad = TRUE),
  "bin：pad = TRUE（两端各补一个空箱）", "bin"
)
cases$bin_group <- record_case(
  "bin_group",
  ggplot(df_bin_grp, aes(x, fill = g)) +
    geom_histogram(bins = 5, position = "identity", alpha = 0.5),
  "bin：两个 group 各自的计数（PANEL × group 分组）", "bin"
)
cases$bin_density <- record_case(
  "bin_density",
  ggplot(df_bin, aes(x, y = after_stat(density))) + geom_histogram(bins = 4),
  "bin + after_stat(density)", "bin"
)
cases$bin_horizontal <- record_case(
  "bin_horizontal",
  # 只映射 y（连续）：断点取 y 标度的 dimension，输出翻回横向
  # （`StatBin$compute_group()` 的 `flipped_names(flipped_aes)$x`）。
  ggplot(df_bin, aes(y = x)) + geom_histogram(binwidth = 1, boundary = 0),
  "bin：横向（没有 x 美学，断点取 y 轴）", "bin"
)

# --- stat_count ------------------------------------------------------------
cases$count_default <- record_case(
  "count_default",
  ggplot(df_cnt, aes(cls, fill = grp)) + geom_bar(),
  "count：竖向柱 + stack(fill)", "count"
)
cases$count_horizontal <- record_case(
  "count_horizontal",
  ggplot(df_cnt_h, aes(y = cls)) + geom_bar(),
  "count：横向（orientation = y，flipped_aes = TRUE）", "count"
)
cases$count_prop <- record_case(
  "count_prop",
  ggplot(df_cnt, aes(cls, group = 1, y = after_stat(prop))) + geom_bar(),
  "count + after_stat(prop)（group = 1 时 prop 才有意义）", "count"
)
cases$count_after_count <- record_case(
  "count_after_count",
  ggplot(df_cnt, aes(cls, y = after_stat(count))) + geom_bar(),
  "count + after_stat(count)", "count"
)

# --- stat_boxplot ----------------------------------------------------------
cases$box_outliers <- record_case(
  "box_outliers",
  ggplot(df_box, aes(cls, v)) + geom_boxplot(),
  "boxplot：每组 1 个离群点", "boxplot"
)
cases$box_none <- record_case(
  "box_none",
  ggplot(df_box_none, aes(cls, v)) + geom_boxplot(position = "identity"),
  "boxplot：没有离群点", "boxplot"
)
cases$box_varwidth <- record_case(
  "box_varwidth",
  # `position = "identity"`（字符串）在 varwidth = TRUE 时会被 ggplot2 4.0.3
  # 换成 dodge2；用 `position_identity()` 对象才是真的 identity。
  ggplot(df_box_var, aes(cls, v)) +
    geom_boxplot(varwidth = TRUE, position = position_identity()),
  "boxplot：varwidth = TRUE（relvarwidth = sqrt(n)）", "boxplot"
)
cases$box_inf <- record_case(
  "box_inf",
  ggplot(df_box_inf, aes(cls, v)) + geom_boxplot(),
  "boxplot：含 Inf 观测（stat 里按非有限值删行）", "boxplot"
)
cases$box_horizontal <- record_case(
  "box_horizontal",
  ggplot(df_box_h, aes(y = cls, x = v)) + geom_boxplot(position = "identity"),
  "boxplot：横向（flipped_aes = TRUE）", "boxplot"
)

# --- stat_smooth -----------------------------------------------------------
smooth_control <- list(
  control = loess.control(surface = "direct", statistics = "exact", trace.hat = "exact")
)
cases$smooth_se <- record_case(
  "smooth_se",
  ggplot(df_smooth, aes(x, y)) +
    geom_smooth(method = "loess", formula = y ~ x, method.args = smooth_control),
  "smooth：loess + se = TRUE（默认 span 0.75、n 80）", "smooth"
)
cases$smooth_no_se <- record_case(
  "smooth_no_se",
  ggplot(df_smooth, aes(x, y)) +
    geom_smooth(method = "loess", formula = y ~ x, se = FALSE, method.args = smooth_control),
  "smooth：se = FALSE（不产 ymin / ymax / se）", "smooth"
)
cases$smooth_span <- record_case(
  "smooth_span",
  ggplot(df_smooth, aes(x, y)) +
    geom_smooth(span = 0.5, method = "loess", formula = y ~ x, method.args = smooth_control),
  "smooth：span = 0.5", "smooth"
)
cases$smooth_n <- record_case(
  "smooth_n",
  ggplot(df_smooth, aes(x, y)) +
    geom_smooth(n = 20, method = "loess", formula = y ~ x, method.args = smooth_control),
  "smooth：n = 20（预测点数）", "smooth"
)
cases$smooth_lm <- record_case(
  "smooth_lm",
  ggplot(df_smooth, aes(x, y)) + geom_smooth(method = "lm", formula = y ~ x),
  "smooth：method = lm", "smooth"
)
cases$smooth_group <- record_case(
  "smooth_group",
  ggplot(
    data.frame(
      x = c(seq(0, 1, length.out = 8), seq(0, 1, length.out = 8)),
      y = c(0.1, 0.2, 0.35, 0.4, 0.55, 0.6, 0.7, 0.8,
            0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1),
      g = rep(c("a", "b"), each = 8),
      stringsAsFactors = FALSE
    ),
    aes(x, y, colour = g)
  ) + geom_smooth(method = "loess", formula = y ~ x, se = FALSE, method.args = smooth_control),
  "smooth：两个 group 各自拟合", "smooth"
)
cases$smooth_default <- record_case(
  "smooth_default",
  # 不传 method.args：R 的默认口径（surface = "interpolate"、
  # statistics = "approximate"、trace.hat = "exact"，cell = 0.2）。
  ggplot(df_smooth, aes(x, y)) + geom_smooth(),
  "smooth：默认参数（R 默认的 interpolate 面）", "smooth"
)
cases$smooth_horizontal_fullrange <- record_case(
  "smooth_horizontal_fullrange",
  # 横向 + fullrange：`StatSmooth$compute_group()` 的 `scales$x$dimension()`
  # 取的仍是 **x 标度**（0..10），预测变量的实际范围是 1..12，所以数据范围外
  # 的点按 `predLoess()` 的 `inside` 判定给 NA。
  ggplot(df_smooth_h, aes(x = v, y = cls)) +
    geom_smooth(orientation = "y", fullrange = TRUE),
  "smooth：横向 + fullrange（xseq 取 x 标度，范围外 NA）", "smooth"
)

# --- stat_align ------------------------------------------------------------
cases$align_unaligned <- record_case(
  "align_unaligned",
  ggplot(df_align, aes(x, y, fill = g)) + geom_area(position = "stack"),
  "align：组间 x 不齐（并集 + 线性插值）", "align"
)
cases$align_duplicate <- record_case(
  "align_duplicate",
  ggplot(df_align_dup, aes(x, y, fill = g)) + geom_area(position = "stack"),
  "align：同一组里 x 有重复（首尾两行 + adjust 让位）", "align"
)
cases$align_negative <- record_case(
  "align_negative",
  ggplot(df_area_negative, aes(x, y, fill = g)) + geom_area(position = "stack"),
  "align：y 有正有负（符号切换处插零点）", "align"
)
cases$align_single <- record_case(
  "align_single",
  ggplot(df_align, aes(x, y)) + geom_area(),
  "align：只有一组时原样通过（is_unique(group)）", "align"
)

# --- M2-6：2D 统计 ---------------------------------------------------------

# bin_2d：默认 bins = 30（4.0.3 的 boundary 缺省 list(x = 0, y = 0)）。
cases$bin2d_default <- record_case(
  "bin2d_default",
  ggplot(df_2d, aes(x, y)) + geom_bin_2d(),
  "bin_2d：默认 bins = 30、boundary = 0", "bin_2d"
)
cases$bin2d_binwidth <- record_case(
  "bin2d_binwidth",
  ggplot(df_2d, aes(x, y)) + geom_bin_2d(binwidth = c(1, 1)),
  "bin_2d：显式 binwidth = c(1, 1)", "bin_2d"
)
cases$bin2d_bins <- record_case(
  "bin2d_bins",
  ggplot(df_2d, aes(x, y)) + geom_bin_2d(bins = 4),
  "bin_2d：bins = 4（x / y 各 4 箱）", "bin_2d"
)
cases$bin2d_na <- record_case(
  "bin2d_na",
  ggplot(df_2d_na, aes(x, y)) + geom_bin_2d(binwidth = c(1, 1)),
  "bin_2d：x / y 各有一行 NA（stat 前删行）", "bin_2d"
)
cases$bin2d_group <- record_case(
  "bin2d_group",
  ggplot(df_2d_grp, aes(x, y, fill = g)) + geom_bin_2d(binwidth = c(1, 1)),
  "bin_2d：两个 group 各自分箱", "bin_2d"
)

# bin_hex：默认 binwidth = diff(scale$dimension()) / 30。
cases$bin_hex_default <- record_case(
  "bin_hex_default",
  ggplot(df_2d, aes(x, y)) + geom_hex(),
  "bin_hex：默认 bins = 30（binwidth 由 scale 的 dimension 推）", "bin_hex"
)
cases$bin_hex_binwidth <- record_case(
  "bin_hex_binwidth",
  ggplot(df_2d, aes(x, y)) + geom_hex(binwidth = c(1, 1)),
  "bin_hex：显式 binwidth = c(1, 1)", "bin_hex"
)
cases$bin_hex_na <- record_case(
  "bin_hex_na",
  ggplot(df_2d_na, aes(x, y)) + geom_hex(binwidth = c(1, 1)),
  "bin_hex：x / y 各有一行 NA", "bin_hex"
)

# summary_2d / summary_hex：fun = mean（默认）/ sum。
cases$summary2d_default <- record_case(
  "summary2d_default",
  ggplot(df_2d, aes(x, y, z = z)) + stat_summary_2d(),
  "summary_2d：默认 bins = 30、fun = mean", "summary_2d"
)
cases$summary2d_binwidth <- record_case(
  "summary2d_binwidth",
  ggplot(df_2d, aes(x, y, z = z)) + stat_summary_2d(binwidth = c(1, 1)),
  "summary_2d：显式 binwidth = c(1, 1)", "summary_2d"
)
cases$summary2d_sum <- record_case(
  "summary2d_sum",
  ggplot(df_2d, aes(x, y, z = z)) +
    stat_summary_2d(binwidth = c(1, 1), fun = "sum"),
  "summary_2d：fun = sum", "summary_2d"
)
cases$summary2d_na <- record_case(
  "summary2d_na",
  ggplot(df_2d_zna, aes(x, y, z = z)) + stat_summary_2d(binwidth = c(1, 1)),
  "summary_2d：z 有 NA（required_aes 含 z，删行）", "summary_2d"
)
cases$summary_hex_default <- record_case(
  "summary_hex_default",
  ggplot(df_2d, aes(x, y, z = z)) + stat_summary_hex(),
  "summary_hex：默认 bins = 30、fun = mean", "summary_hex"
)
cases$summary_hex_binwidth <- record_case(
  "summary_hex_binwidth",
  ggplot(df_2d, aes(x, y, z = z)) + stat_summary_hex(binwidth = c(1, 1)),
  "summary_hex：显式 binwidth = c(1, 1)", "summary_hex"
)

# contour / contour_filled：等值带用 contourpy；对拍口径只钉层级边界。
cases$contour_default <- record_case(
  "contour_default",
  ggplot(grid_contour, aes(x, y, z = z)) + geom_contour(),
  "contour：默认 breaks（R 的 pretty(z_range, 10)）", "contour"
)
cases$contour_bins <- record_case(
  "contour_bins",
  ggplot(grid_contour, aes(x, y, z = z)) + geom_contour(bins = 4),
  "contour：bins = 4", "contour"
)
cases$contour_binwidth <- record_case(
  "contour_binwidth",
  ggplot(grid_contour, aes(x, y, z = z)) + geom_contour(binwidth = 1),
  "contour：binwidth = 1", "contour"
)
cases$contour_breaks <- record_case(
  "contour_breaks",
  ggplot(grid_contour, aes(x, y, z = z)) + geom_contour(breaks = c(2, 4, 6)),
  "contour：显式 breaks = c(2, 4, 6)", "contour"
)
cases$contour_na <- record_case(
  "contour_na",
  ggplot(grid_contour_na, aes(x, y, z = z)) + geom_contour(bins = 4),
  "contour：z 有 NA（required_aes 含 z，删行）", "contour"
)
cases$contour_filled <- record_case(
  "contour_filled",
  ggplot(grid_contour, aes(x, y, z = z)) + geom_contour_filled(bins = 4),
  "contour_filled：bins = 4（level 是有序因子）", "contour_filled"
)

# density_2d / density_2d_filled：MASS::kde2d + 再走 contour。
cases$density2d_default <- record_case(
  "density2d_default",
  ggplot(df_density2d, aes(x, y)) + geom_density_2d(),
  "density_2d：默认 h（bandwidth.nrd）+ contour", "density_2d"
)
cases$density2d_h <- record_case(
  "density2d_h",
  ggplot(df_density2d, aes(x, y)) + geom_density_2d(h = c(1, 1), bins = 4),
  "density_2d：显式 h = c(1, 1)、bins = 4", "density_2d"
)
cases$density2d_grid <- record_case(
  "density2d_grid",
  # contour = FALSE：只出密度网格（n = 20 让夹具小一些）。
  ggplot(df_density2d, aes(x, y)) + stat_density_2d(contour = FALSE, n = 20),
  "density_2d：contour = FALSE（密度网格本身）", "density_2d"
)
cases$density2d_na <- record_case(
  "density2d_na",
  ggplot(df_density2d_na, aes(x, y)) + stat_density_2d(contour = FALSE, n = 20),
  "density_2d：x 有 NA（required_aes 含 x / y，删行）", "density_2d"
)
cases$density2d_filled <- record_case(
  "density2d_filled",
  ggplot(df_density2d, aes(x, y)) + geom_density_2d_filled(n = 30),
  "density_2d_filled：填充等值带（n = 30）", "density_2d_filled"
)


# ---------------------------------------------------------------------------
# docs/cases 的 5 张端到端参考图（theme_void 整页，svglite 4×3 in）
# ---------------------------------------------------------------------------

theme_case <- function() {
  theme_void() + theme(legend.position = "none")
}
fixed_x <- function(limits) scale_x_continuous(limits = limits, expand = c(0, 0))
fixed_y <- function(limits) scale_y_continuous(limits = limits, expand = c(0, 0))

save_case <- function(name, plot) {
  path <- file.path(repo, "docs", "cases", name, "expected.svg")
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  svglite::svglite(path, width = 4, height = 3)
  on.exit(grDevices::dev.off(), add = TRUE)
  print(plot)
  cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", path, fixed = TRUE)))
}

# 1. histogram：原始数据 + 默认 stat_bin（binwidth / boundary 指定，箱好对）
save_case(
  "stat-histogram-bin",
  ggplot(df_bin, aes(x)) +
    geom_histogram(binwidth = 1, boundary = 0, fill = "#4C78A8") +
    fixed_x(c(0, 5)) + fixed_y(c(0, 4.5)) + theme_case()
)

# 2. boxplot：原始数据 + stat_boxplot（两组各 1 个离群点）
save_case(
  "stat-boxplot-stat",
  ggplot(df_box, aes(cls, v)) +
    geom_boxplot(fill = "#4C78A8", width = 0.6) +
    fixed_y(c(0, 26)) + theme_case()
)

# 3. smooth：原始数据 + stat_smooth(loess)。R 侧用 direct 口径（与 gg4py 实现一致）
save_case(
  "stat-smooth-loess",
  ggplot(df_smooth, aes(x, y)) +
    geom_smooth(
      method = "loess", formula = y ~ x, se = TRUE,
      fill = "grey60", method.args = smooth_control
    ) +
    fixed_x(c(0, 1)) + fixed_y(c(0, 1.1)) + theme_case()
)

# 4. area：默认 stat_align + position stack（组间 x 不齐）
save_case(
  "stat-area-align",
  ggplot(df_align, aes(x, y, fill = g)) +
    geom_area(position = "stack") +
    scale_fill_manual(values = c(a = "#4C78A8", b = "#F58518")) +
    fixed_x(c(0.5, 5.5)) + fixed_y(c(0, 4)) + theme_case()
)

# 5. 横向 histogram：只映射 y（连续），断点取 y 标度（count 在 x 轴上）
#    y 不设 limits：断点仍按数据范围（1..4）算，3 个箱正好铺满面板。
save_case(
  "stat-histogram-horizontal",
  ggplot(df_bin, aes(y = x)) +
    geom_histogram(binwidth = 1, boundary = 0, fill = "#4C78A8") +
    fixed_x(c(0, 5)) + scale_y_continuous(expand = c(0, 0)) + theme_case()
)

# ---------------------------------------------------------------------------
# 写盘
# ---------------------------------------------------------------------------

fixture <- list(
  r_version = paste(R.version$major, R.version$minor, sep = "."),
  ggplot2_version = as.character(packageVersion("ggplot2")),
  loess = paste0(
    "默认 surface=interpolate / statistics=approximate / trace.hat=exact；",
    "显式 case 用 surface=direct / statistics=exact / trace.hat=exact",
    "（见 docs/notes/stat.md）"
  ),
  scale = paste0(
    length(cases), " case；data[[1]] 的列名+列序+kind+逐值；",
    "ggplot_build() / ggplotGrob() 的 warning"
  ),
  cases = cases
)

writeLines(to_json(fixture), fixture_path)
cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", fixture_path, fixed = TRUE)))
