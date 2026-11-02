#!/usr/bin/env Rscript
#
# M1-7 的 R 对拍产线：生成
#   - tests/fixtures/geom_r_reference.json   （ggplot_build(p)$data[[1]] 的逐列值）
#   - docs/cases/geom-*/expected.svg         （9 个 theme_void 全页用例）
#
#   pixi run -e refs refs:geom
#
# 只在「换 pin」或「有意改口径」时重跑；产物入库，CI 不装 R。
#
# 夹具口径：
#   - 每个 case 记录 `ggplot_build(p)$data[[1]]` 的列名、列序、kind、逐值（NA → null）；
#   - 还记录 `layout$panel_params[[1]]` 的 x / y continuous_range（绘制期算 npc 用）；
#   - 还记录 `ggplotGrob(p)` 期间的 warning（`Geom$handle_na()` 的 "Removed N rows"）。
#
# 5 个 stat 已实现的 geom（point / line / path / bar / col）在 Python 侧重放整条流水线
# 逐列对拍；4 个 stat 未实现的 geom（area / histogram / boxplot / smooth）把这里的
# `$data` 当**绘制输入夹具**（stat 归 M1-8），另用 stat="identity" 的用例做端到端。

suppressPackageStartupMessages({
  library(ggplot2)
  library(svglite)
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
fixture_path <- file.path(repo, "tests", "fixtures", "geom_r_reference.json")
cases_dir <- file.path(repo, "docs", "cases")

# ---------------------------------------------------------------------------
# 极简 JSON 输出（与 tools/refs/build_ref.R 同一份，不引入 jsonlite）
# ---------------------------------------------------------------------------

json_escape <- function(text) {
  text <- gsub("\\", "\\\\", text, fixed = TRUE)
  text <- gsub("\"", "\\\"", text, fixed = TRUE)
  text <- gsub("\n", "\\n", text, fixed = TRUE)
  text <- gsub("\t", "\\t", text, fixed = TRUE)
  paste0("\"", text, "\"")
}

fmt_num <- function(value) {
  if (!is.finite(value)) stop("non-finite number in fixture: ", value)
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

# 向量 → JSON 数组（NA → null）。因子先转字符，保持 R 的水平顺序。
vector_json <- function(values) {
  if (is.factor(values)) {
    values <- as.character(values)
  }
  if (is.list(values)) {
    return(lapply(values, function(item) {
      if (length(item) == 0L) return(NULL)
      lapply(seq_along(item), function(i) {
        value <- item[[i]]
        if (length(value) == 1L && is.na(value)) NULL else value
      })
    }))
  }
  lapply(seq_along(values), function(i) {
    value <- values[[i]]
    if (length(value) == 0L || (length(value) == 1L && is.na(value))) NULL else value
  })
}

column_kind <- function(values) {
  if (is.logical(values)) return("bool")
  if (is.integer(values)) return("int")
  if (inherits(values, "mapped_discrete")) return("float")
  if (is.numeric(values)) return("float")
  if (is.factor(values) || is.character(values)) return("str")
  if (is.list(values)) return("list")
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
# case 数据集（Python 侧的 plot.py 用同一份数字）
# ---------------------------------------------------------------------------

df_point <- data.frame(
  x = rep(c(0.1, 0.35, 0.65, 0.9), 4),
  y = rep(c(0.15, 0.4, 0.6, 0.85), each = 4),
  g = rep(c("a", "b", "a", "b"), 4),
  # 数值 shape 列：R 直接把值当 pch（19 = 实心圆，15 = 实心方）。
  sh = rep(c(19, 15, 19, 15), 4),
  stringsAsFactors = FALSE
)

df_point_na <- data.frame(
  x = c(0.1, 0.3, 0.5, 0.7, 0.9),
  y = c(0.2, NA, 0.6, 0.8, NA),
  g = c("a", "a", "b", "b", "a"),
  stringsAsFactors = FALSE
)

df_line <- data.frame(
  x = c(0.1, 0.3, 0.5, 0.7, 0.9, 0.1, 0.3, 0.5, 0.7, 0.9),
  y = c(0.2, 0.5, 0.4, 0.7, 0.6, 0.8, 0.6, 0.7, 0.3, 0.4),
  g = rep(c("a", "b"), each = 5),
  stringsAsFactors = FALSE
)

df_path <- data.frame(
  x = c(0.15, 0.85, 0.25, 0.9, 0.1),
  y = c(0.2, 0.55, 0.8, 0.25, 0.6)
)

df_bar <- data.frame(
  cls = c("a", "b", "a", "c", "b", "a", "c", "c"),
  grp = c("p", "p", "q", "p", "q", "p", "p", "q"),
  stringsAsFactors = FALSE
)

df_col <- data.frame(
  x = c(0.5, 1.5, 2.5, 3.5),
  y = c(0.35, 0.75, 0.55, 0.9),
  g = c("a", "b", "a", "b"),
  stringsAsFactors = FALSE
)

# 横向 col 的类别必须互不相同：同一类别会走 stack，和「四根独立的横柱」不是一回事。
df_col_h <- data.frame(
  cls = c("a", "b", "c", "d"),
  v = c(0.3, 0.7, 0.5, 0.9),
  stringsAsFactors = FALSE
)

df_area <- data.frame(
  x = c(1, 2, 3, 4, 5),
  y = c(1, 3, 2, 4, 3)
)

df_hist <- data.frame(
  x = c(0.5, 1.5, 2.5, 3.5),
  y = c(0.2, 0.5, 0.75, 0.4),
  w = c(1, 1, 1, 1)
)

df_hist_raw <- data.frame(
  x = c(1, 1, 2, 2, 2, 3, 4, 4, 4, 4)
)

df_box <- data.frame(
  cls = c("a", "b"),
  lo = c(0.3, 0.35),
  mid = c(0.5, 0.5),
  hi = c(0.7, 0.65),
  y0 = c(0.1, 0.2),
  y1 = c(0.9, 0.8),
  stringsAsFactors = FALSE
)

df_box_raw <- data.frame(
  cls = rep(c("a", "b"), each = 9),
  v = c(1, 2, 3, 4, 5, 6, 7, 8, 20, 2, 3, 4, 5, 6, 7, 8, 9, 25),
  stringsAsFactors = FALSE
)

df_smooth <- data.frame(
  x = c(1, 2, 3, 4, 5, 6),
  y = c(1.0, 1.6, 2.1, 2.7, 3.1, 3.8),
  ymin = c(0.6, 1.2, 1.7, 2.3, 2.7, 3.4),
  ymax = c(1.4, 2.0, 2.5, 3.1, 3.5, 4.2)
)

df_smooth_raw <- data.frame(
  x = seq(0, 1, length.out = 11),
  y = c(0.1, 0.25, 0.35, 0.5, 0.62, 0.7, 0.75, 0.8, 0.86, 0.9, 0.95)
)

# ---------------------------------------------------------------------------
# case 定义：fixture 需要的数据 + 9 张要落 expected.svg 的图
# ---------------------------------------------------------------------------

theme_case <- function() {
  theme_void() + theme(legend.position = "none")
}
fixed_x <- function(limits) scale_x_continuous(limits = limits, expand = c(0, 0))
fixed_y <- function(limits) scale_y_continuous(limits = limits, expand = c(0, 0))

check_warnings <- function(plot) {
  messages <- character()
  withCallingHandlers(
    invisible(ggplotGrob(plot)),
    warning = function(w) {
      messages <<- c(messages, conditionMessage(w))
      invokeRestart("muffleWarning")
    }
  )
  messages
}

record_case <- function(name, plot, description, stat = "identity") {
  build <- ggplot_build(plot)
  data <- build$data[[1]]
  panel_params <- build$layout$panel_params[[1]]
  list(
    description = description,
    stat = stat,
    data = dataframe_json(data),
    panel_params = list(
      x_range = as.list(panel_params$x$continuous_range),
      y_range = as.list(panel_params$y$continuous_range),
      discrete_x = isTRUE(panel_params$x$scale_is_discrete),
      discrete_y = isTRUE(panel_params$y$scale_is_discrete)
    ),
    warnings = check_warnings(plot)
  )
}

save_case <- function(name, plot) {
  path <- file.path(cases_dir, name, "expected.svg")
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  svglite(path, width = 4, height = 3)
  print(plot)
  dev.off()
  cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", path, fixed = TRUE)))
}

cases <- list()
svg_cases <- list()

# 1. point：形状 + 颜色两个离散映射
# R 的 shape 只有离散标度（数值 shape aes 会直接报错），所以两种符号用两层
# 固定 shape 的 geom_point 表达；gg4py 侧同一份写法，绘制能力对等。
plot_point <- ggplot(df_point, aes(x, y, colour = g)) +
  geom_point(data = df_point[df_point$sh == 19, ], shape = 19, size = 9 / .pt, stroke = 0) +
  geom_point(data = df_point[df_point$sh == 15, ], shape = 15, size = 9 / .pt, stroke = 0) +
  scale_colour_manual(values = c(a = "#F8766D", b = "#00BA38")) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$point_shapes <- record_case("point_shapes", plot_point, "point：shape + colour 双离散映射")
svg_cases$`geom-point-shapes` <- plot_point

# 2. point：NA 删行（handle_na 的 "Removed N rows" 口径）
plot_point_na <- ggplot(df_point_na, aes(x, y, colour = g)) +
  geom_point(size = 8 / .pt, stroke = 0) +
  scale_colour_manual(values = c(a = "#F8766D", b = "#00BA38")) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$point_na <- record_case("point_na", plot_point_na, "point：y 有两处 NA（build 保留，draw 期删）")

# 3. line：两个 group、按 x 排序
plot_line <- ggplot(df_line, aes(x, y, colour = g, group = g)) +
  geom_line(linewidth = 1.2 / .pt) +
  scale_colour_manual(values = c(a = "#4C78A8", b = "#E45756")) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$line_groups <- record_case("line_groups", plot_line, "line：两个 group 各自成线")
svg_cases$`geom-line-groups` <- plot_line

# 4. path：保持给定行序
plot_path <- ggplot(df_path, aes(x, y)) +
  geom_path(colour = "#4C78A8", linewidth = 1.2 / .pt) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$path_basic <- record_case("path_basic", plot_path, "path：给定行序连接（不排序）")
svg_cases$`geom-path-order` <- plot_path

# 5. bar：stat_count + 堆叠 fill
plot_bar <- ggplot(df_bar, aes(cls, fill = grp)) +
  geom_bar() +
  scale_fill_manual(values = c(p = "#4C78A8", q = "#F58518")) +
  scale_y_continuous(limits = c(0, 4), expand = c(0, 0)) +
  theme_case()
cases$bar_stacked <- record_case("bar_stacked", plot_bar, "bar：stat_count + stack(fill)", "count")
svg_cases$`geom-bar-stacked` <- plot_bar

# 6. col：identity stat
plot_col <- ggplot(df_col, aes(x, y, fill = g)) +
  geom_col(width = 0.7) +
  scale_fill_manual(values = c(a = "#4C78A8", b = "#F58518")) +
  fixed_x(c(0, 4)) + fixed_y(c(0, 1)) + theme_case()
cases$col_identity <- record_case("col_identity", plot_col, "col：identity stat + 分组 fill")
svg_cases$`geom-col-identity` <- plot_col

# 7. col：横向（只映射 y，x 是数值）→ flipped_aes
plot_col_h <- ggplot(df_col_h, aes(y = cls, x = v)) +
  geom_col(width = 0.7) +
  fixed_x(c(0, 1)) + scale_y_discrete(expand = c(0.6, 0.6)) + theme_case()
cases$col_horizontal <- record_case("col_horizontal", plot_col_h, "横向 col：flipped_aes = TRUE")

# 8. area：identity stat
plot_area <- ggplot(df_area, aes(x, y)) +
  geom_area(stat = "identity", fill = "#4C78A8") +
  fixed_x(c(0, 6)) + fixed_y(c(0, 5)) + theme_case()
cases$area_identity <- record_case("area_identity", plot_area, "area：identity stat（ymin = 0）")
svg_cases$`geom-area-identity` <- plot_area

# 9. histogram：stat_bin 的 R 侧输出（绘制输入夹具）
plot_hist_stat <- ggplot(df_hist_raw, aes(x)) +
  geom_histogram(bins = 4, fill = "#4C78A8")
cases$histogram_stat <- record_case("histogram_stat", plot_hist_stat, "histogram：stat_bin 输出（M1-8）", "bin")

# 10. histogram：identity stat 端到端（x / y / width 都给好）
plot_hist <- ggplot(df_hist, aes(x, y, width = w)) +
  geom_histogram(stat = "identity", fill = "#4C78A8") +
  fixed_x(c(0, 4)) + fixed_y(c(0, 1)) + theme_case()
cases$histogram_identity <- record_case("histogram_identity", plot_hist, "histogram：identity stat + width 列")
svg_cases$`geom-histogram-identity` <- plot_hist

# 11. boxplot：stat_boxplot 的 R 侧输出（含 outliers 列表列）
plot_box_stat <- ggplot(df_box_raw, aes(cls, v)) +
  geom_boxplot(fill = "#4C78A8")
cases$boxplot_stat <- record_case("boxplot_stat", plot_box_stat, "boxplot：stat_boxplot 输出（含 outliers）", "boxplot")

# 12. boxplot：五数预计算
plot_box <- ggplot(df_box, aes(cls, ymin = y0, lower = lo, middle = mid, upper = hi, ymax = y1)) +
  geom_boxplot(stat = "identity", width = 0.6, fill = "#4C78A8") +
  scale_y_continuous(limits = c(0, 1), expand = c(0, 0)) + theme_case()
cases$boxplot_identity <- record_case("boxplot_identity", plot_box, "boxplot：五数预计算")
svg_cases$`geom-boxplot-precomputed` <- plot_box

# 13. smooth：stat_smooth（lm）的 R 侧输出（含 se 带）
plot_smooth_stat <- ggplot(df_smooth_raw, aes(x, y)) +
  geom_smooth(method = "lm", formula = y ~ x, se = TRUE)
cases$smooth_stat <- record_case("smooth_stat", plot_smooth_stat, "smooth：stat_smooth(lm) 输出（含 ymin/ymax）", "smooth")

# 14. smooth：se 带用 identity stat 端到端
plot_smooth <- ggplot(df_smooth, aes(x, y, ymin = ymin, ymax = ymax)) +
  geom_smooth(stat = "identity", colour = "#3366FF", fill = "grey60", alpha = 0.4) +
  fixed_x(c(0, 7)) + fixed_y(c(0, 5)) + theme_case()
cases$smooth_identity <- record_case("smooth_identity", plot_smooth, "smooth：identity stat + se 带")
svg_cases$`geom-smooth-se` <- plot_smooth

# ---------------------------------------------------------------------------
# 写盘
# ---------------------------------------------------------------------------

fixture <- list(
  r_version = paste(R.version$major, R.version$minor, sep = "."),
  ggplot2_version = as.character(packageVersion("ggplot2")),
  scale = paste0(
    "9 geom / ", length(cases), " case；data[[1]] 的列名+列序+kind+逐值；",
    "panel_params 的 continuous_range；handle_na 的 warning"
  ),
  cases = cases
)

writeLines(to_json(fixture), fixture_path)
cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", fixture_path, fixed = TRUE)))

for (name in names(svg_cases)) {
  save_case(name, svg_cases[[name]])
}
