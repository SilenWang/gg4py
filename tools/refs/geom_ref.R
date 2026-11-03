#!/usr/bin/env Rscript
#
# M1-7 / M2-S2 的 R 对拍产线：生成
#   - tests/fixtures/geom_r_reference.json   （ggplot_build(p)$data[[1]] 的逐列值）
#   - docs/cases/geom-*/expected.svg         （26 个 theme_void 全页用例：M1-7 的 9 个
#     + M2-S2 长尾 A 的 17 个，含两条横向自动探测 case）
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
# stat 已实现的 geom 在 Python 侧重放整条流水线逐列对拍；stat 未实现的 geom
# 把这里的 `$data` 当**绘制输入夹具**，另用 stat="identity" 的用例做端到端。
# M2-S2 的 20 个长尾 geom 都走 identity stat，全部整条流水线对拍；其中
# `boxplot_horizontal_auto` / `area_horizontal` 两条专门钉 SIL-715 #4 / #5。

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

# 连续 x、不传 width：默认宽度走 compute_data_size(default = 0.9) =
# resolution(x, zero = FALSE) * 0.9（这里 = 10 * 0.9 = 9）。
df_col_default <- data.frame(
  x = c(0, 10, 20),
  y = c(1, 2, 3)
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
  # `ggplotGrob()` 会打开默认设备（pdf() → 仓库根目录的 Rplots.pdf）。显式开一个
  # 临时 pdf 设备并在 on.exit 里关掉，产线跑完不留未跟踪文件（SIL-698 #6）。
  grDevices::pdf(file = tempfile(fileext = ".pdf"))
  on.exit(grDevices::dev.off(), add = TRUE)
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

# 7b. col：连续 x、不传 width → 默认宽度 = resolution(x, zero = FALSE) * 0.9
# 用 coord limits（不是 scale limits）：scale limits 会把 xmin/xmax 越界值 censor 成 NA，
# 这里要对拍的是 setup_data 算出来的宽度本身。
plot_col_default <- ggplot(df_col_default, aes(x, y)) +
  geom_col() +
  coord_cartesian(xlim = c(0, 20), expand = c(0, 0)) + theme_case()
cases$col_default_width <- record_case(
  "col_default_width", plot_col_default,
  "col：连续 x 的默认宽度 = resolution(x) * 0.9"
)

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
# M2-S2：长尾 A（线段 / 矩形 / 区间 / 标注族）+ 两条横向自动探测 case
# ---------------------------------------------------------------------------

df_seg <- data.frame(
  x = c(0.1, 0.5), y = c(0.2, 0.55),
  xend = c(0.8, 0.9), yend = c(0.7, 0.25),
  g = c("a", "b"), stringsAsFactors = FALSE
)
df_spoke <- data.frame(
  x = c(0.3, 0.6), y = c(0.3, 0.6),
  ang = c(0, pi / 4), rad = c(0.2, 0.25)
)
df_rect <- data.frame(
  xmin = c(0.1, 0.5), xmax = c(0.4, 0.8),
  ymin = c(0.1, 0.2), ymax = c(0.5, 0.6)
)
df_tile <- data.frame(
  x = c(0.25, 0.75, 0.25, 0.75), y = c(0.25, 0.25, 0.75, 0.75),
  f = c("p", "q", "q", "p"), stringsAsFactors = FALSE
)
df_poly <- data.frame(
  x = c(0.1, 0.4, 0.35, 0.7, 0.85, 0.5),
  y = c(0.1, 0.15, 0.5, 0.55, 0.9, 0.6),
  g = c(rep("a", 3), rep("b", 3)), stringsAsFactors = FALSE
)
df_ribbon <- data.frame(
  x = c(0.1, 0.3, 0.5, 0.7, 0.9),
  lo = c(0.1, 0.2, 0.15, 0.3, 0.25),
  hi = c(0.4, 0.5, 0.45, 0.6, 0.55)
)
df_step <- data.frame(
  x = c(0.1, 0.3, 0.5, 0.7, 0.9),
  y = c(0.2, 0.5, 0.35, 0.7, 0.6)
)
df_int <- data.frame(
  x = c(0.3, 0.7), y = c(0.5, 0.45),
  lo = c(0.2, 0.3), hi = c(0.8, 0.7)
)
df_rug <- data.frame(x = c(0.2, 0.5, 0.8), y = c(0.3, 0.6, 0.9))
df_map <- data.frame(map_id = c("a", "b"), stringsAsFactors = FALSE)
map_tbl <- data.frame(
  x = c(0, 0.4, 0.4, 0, 0.5, 0.9, 0.9, 0.5),
  y = c(0, 0, 0.4, 0.4, 0.5, 0.5, 0.9, 0.9),
  id = rep(c("a", "b"), each = 4), stringsAsFactors = FALSE
)

# 15. segment：两端闭合箭头
plot_segment <- ggplot(df_seg, aes(x, y, xend = xend, yend = yend, colour = g)) +
  geom_segment(
    linewidth = 1.1 / .pt,
    arrow = arrow(length = unit(0.15, "inches"), ends = "both", type = "closed")
  ) +
  scale_colour_manual(values = c(a = "#4C78A8", b = "#E45756")) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$segment_arrow <- record_case("segment_arrow", plot_segment, "segment：两端闭合箭头")
svg_cases$`geom-segment-arrow` <- plot_segment

# 16. curve：弯曲 + 单端箭头
plot_curve <- ggplot(df_seg, aes(x, y, xend = xend, yend = yend)) +
  geom_curve(
    curvature = -0.4, angle = 90, ncp = 5, linewidth = 1.1 / .pt,
    colour = "#4C78A8",
    arrow = arrow(length = unit(0.12, "inches"), ends = "last", type = "open")
  ) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$curve_arrow <- record_case("curve_arrow", plot_curve, "curve：curvature = -0.4 + 单端箭头")
svg_cases$`geom-curve-arrow` <- plot_curve

# 17. spoke：角度 / 半径映射
plot_spoke <- ggplot(df_spoke, aes(x, y, angle = ang, radius = rad)) +
  geom_spoke(linewidth = 1.2 / .pt, colour = "#4C78A8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$spoke_basic <- record_case("spoke_basic", plot_spoke, "spoke：angle / radius 映射")
svg_cases$`geom-spoke` <- plot_spoke

# 18. rect：两个矩形
plot_rect <- ggplot(df_rect, aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax)) +
  geom_rect(fill = "#4C78A8", colour = "#333333", linewidth = 0.8 / .pt, alpha = 0.6) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$rect_basic <- record_case("rect_basic", plot_rect, "rect：两个带 alpha 的矩形")
svg_cases$`geom-rect` <- plot_rect

# 19. abline / hline / vline：参考线（各自一条独立 fixture case）
plot_abline <- ggplot(df_rect) +
  geom_abline(slope = 1, intercept = 0.1, linewidth = 1.0 / .pt, colour = "#4C78A8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$abline_basic <- record_case("abline_basic", plot_abline, "abline：y = x + 0.1")
plot_hline <- ggplot(df_rect) +
  geom_hline(yintercept = 0.75, linetype = "dashed", linewidth = 0.9 / .pt, colour = "#E45756") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$hline_basic <- record_case("hline_basic", plot_hline, "hline：y = 0.75")
plot_vline <- ggplot(df_rect) +
  geom_vline(xintercept = 0.6, linewidth = 0.9 / .pt, colour = "#54A24B") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$vline_basic <- record_case("vline_basic", plot_vline, "vline：x = 0.6")

# 一张组合图：矩形 + 三条参考线（expected.svg 用）
plot_refs <- ggplot(df_rect, aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax)) +
  geom_rect(fill = "#DDDDDD", colour = "#333333", linewidth = 0.6 / .pt) +
  geom_abline(slope = 1, intercept = 0.1, linewidth = 1.0 / .pt, colour = "#4C78A8") +
  geom_hline(yintercept = 0.75, linetype = "dashed", linewidth = 0.9 / .pt, colour = "#E45756") +
  geom_vline(xintercept = 0.6, linewidth = 0.9 / .pt, colour = "#54A24B") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
svg_cases$`geom-abline-hline-vline` <- plot_refs

# 20. tile：2×2 小方块 + fill 映射
plot_tile <- ggplot(df_tile, aes(x, y, fill = f)) +
  geom_tile() +
  scale_fill_manual(values = c(p = "#4C78A8", q = "#F58518")) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$tile_basic <- record_case("tile_basic", plot_tile, "tile：默认 width / height = 1")
svg_cases$`geom-tile` <- plot_tile

# 21. raster：同一份数据走位图路径（interpolate = FALSE）
plot_raster <- ggplot(df_tile, aes(x, y, fill = f)) +
  geom_raster(interpolate = FALSE) +
  scale_fill_manual(values = c(p = "#4C78A8", q = "#F58518")) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$raster_basic <- record_case("raster_basic", plot_raster, "raster：像素矩阵 + 不插值")
svg_cases$`geom-raster` <- plot_raster

# 22. polygon：两个三角形
plot_poly <- ggplot(df_poly, aes(x, y, group = g, fill = g)) +
  geom_polygon(colour = "#333333", linewidth = 0.8 / .pt, alpha = 0.8) +
  scale_fill_manual(values = c(a = "#4C78A8", b = "#F58518")) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$polygon_basic <- record_case("polygon_basic", plot_poly, "polygon：两个分组三角")
svg_cases$`geom-polygon` <- plot_poly

# 23. ribbon：outline.type = "upper"
plot_ribbon <- ggplot(df_ribbon, aes(x, ymin = lo, ymax = hi)) +
  geom_ribbon(
    fill = "#4C78A8", colour = "#333333", alpha = 0.5,
    linewidth = 0.9 / .pt, outline.type = "upper"
  ) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$ribbon_upper <- record_case("ribbon_upper", plot_ribbon, "ribbon：outline.type = upper")
svg_cases$`geom-ribbon-outline` <- plot_ribbon

# 24. step：direction = "hv"
plot_step <- ggplot(df_step, aes(x, y)) +
  geom_step(direction = "hv", linewidth = 1.2 / .pt, colour = "#4C78A8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$step_basic <- record_case("step_basic", plot_step, "step：direction = hv")
svg_cases$`geom-step` <- plot_step

# 25. errorbar：两根误差棒
plot_errorbar <- ggplot(df_int, aes(x, y, ymin = lo, ymax = hi)) +
  geom_errorbar(width = 0.2, linewidth = 0.9 / .pt, colour = "#4C78A8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$errorbar_basic <- record_case("errorbar_basic", plot_errorbar, "errorbar：width = 0.2")
svg_cases$`geom-errorbar` <- plot_errorbar

# 26. errorbarh：横向误差棒（xmin / xmax 映射，height 换名成 width）
plot_errorbarh <- ggplot(df_int, aes(y = x, x = y, xmin = lo, xmax = hi)) +
  geom_errorbarh(height = 0.2, linewidth = 0.9 / .pt, colour = "#E45756") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$errorbarh_basic <- record_case("errorbarh_basic", plot_errorbarh, "errorbarh：height → width")
svg_cases$`geom-errorbarh` <- plot_errorbarh

# 27. linerange + pointrange（各自一条 fixture case，共用一张 expected.svg）
plot_linerange <- ggplot(df_int, aes(x, y, ymin = lo, ymax = hi)) +
  geom_linerange(linewidth = 1.5 / .pt, colour = "#54A24B") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$linerange_basic <- record_case("linerange_basic", plot_linerange, "linerange：竖线")
plot_pointrange <- ggplot(df_int, aes(x, y, ymin = lo, ymax = hi)) +
  geom_pointrange(size = 1.4, linewidth = 0.9 / .pt, colour = "#333333") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$pointrange_basic <- record_case("pointrange_basic", plot_pointrange, "pointrange：竖线 + 中点")
plot_ranges <- ggplot(df_int, aes(x, y, ymin = lo, ymax = hi)) +
  geom_linerange(linewidth = 1.5 / .pt, colour = "#54A24B") +
  geom_pointrange(size = 1.4, linewidth = 0.9 / .pt, colour = "#333333") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
svg_cases$`geom-linerange-pointrange` <- plot_ranges

# 28. crossbar：箱体 + 中位线
plot_crossbar <- ggplot(df_int, aes(x, y, ymin = lo, ymax = hi)) +
  geom_crossbar(width = 0.3, fill = "#F58518", colour = "#333333", linewidth = 0.8 / .pt) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$crossbar_basic <- record_case("crossbar_basic", plot_crossbar, "crossbar：箱体 + 中位线")
svg_cases$`geom-crossbar` <- plot_crossbar

# 29. blank / rug（blank 只训练标度，rug 画短刻度）
plot_rug <- ggplot(df_rug, aes(x, y)) +
  geom_rug(sides = "bl", length = unit(0.04, "npc"), linewidth = 0.8 / .pt, colour = "#4C78A8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$rug_basic <- record_case("rug_basic", plot_rug, "rug：bl 三条短刻度")
plot_blank_rug <- ggplot(df_rug, aes(x, y)) +
  geom_blank() +
  geom_rug(sides = "bl", length = unit(0.04, "npc"), linewidth = 0.8 / .pt, colour = "#4C78A8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
svg_cases$`geom-blank-rug` <- plot_blank_rug

# 30. map：map 表 + map_id
plot_map <- ggplot(df_map, aes(map_id = map_id)) +
  geom_map(map = map_tbl, fill = "#4C78A8", colour = "#333333", linewidth = 0.8 / .pt) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$map_basic <- record_case("map_basic", plot_map, "map：两份 map 多边形")
svg_cases$`geom-map` <- plot_map

# 31. SIL-715 #5：boxplot 横向自动方向探测（两边都不写 orientation）
df_box_auto <- data.frame(
  cls = rep(c("a", "b"), each = 6),
  v = c(1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 0.5, 1.0, 1.5, 2.0, 2.5, 5.0),
  stringsAsFactors = FALSE
)
plot_box_auto <- ggplot(df_box_auto, aes(y = cls, x = v)) +
  geom_boxplot(fill = "#F58518", colour = "#333333", width = 0.6) +
  scale_x_continuous(limits = c(0, 6), expand = c(0, 0)) + theme_case()
cases$boxplot_horizontal_auto <- record_case(
  "boxplot_horizontal_auto", plot_box_auto,
  "boxplot：y 离散、x 连续，未写 orientation（自动 flipped_aes）", "boxplot"
)
svg_cases$`geom-boxplot-horizontal-auto` <- plot_box_auto

# 32. SIL-715 #4：横向 area（上游 `has_flipped_aes(ambiguous = TRUE)` 不自动探测，
#     横向必须写 orientation = "y"；R 的 stat_align 在 y 离散时输出 0 行）
df_area_h <- data.frame(
  cls = c("a", "b", "c", "d", "e"),
  v = c(1.0, 2.5, 1.8, 3.2, 2.2),
  stringsAsFactors = FALSE
)
plot_area_h <- ggplot(df_area_h, aes(y = cls, x = v)) +
  geom_area(stat = "identity", orientation = "y", fill = "#4C78A8") +
  scale_x_continuous(limits = c(0, 4), expand = c(0, 0)) + theme_case()
cases$area_horizontal <- record_case(
  "area_horizontal", plot_area_h,
  "area：横向（orientation = y，上游 area 不做自动探测）"
)
svg_cases$`geom-area-horizontal` <- plot_area_h

# ---------------------------------------------------------------------------
# M2-7 长尾 B：文本 / 点 / 分布 / 2D 族（SIL-735）
#
# 统计量侧（stat_density / stat_ydensity / stat_bindot / stat_bin_2d /
# stat_bin_hex / stat_contour / stat_density_2d / stat_qq / stat_quantile /
# stat_function / stat_sum）归兄弟任务；这一段的 case 全部用
# `stat = "identity"` + **stat 形状的列**喂给绘制层，R 与 Python 两侧同一份
# 数字、同一组 limits / 标度 / 主题，比的是绘制口径本身。
# ---------------------------------------------------------------------------

# 15. text：hjust 三态（左 / 中 / 右）
df_text_align <- data.frame(
  x = c(0.5, 0.5, 0.5),
  y = c(0.2, 0.5, 0.8),
  label = c("left", "centre", "right"),
  hj = c(0, 0.5, 1)
)
plot_text_align <- ggplot(df_text_align, aes(x, y, label = label, hjust = hj)) +
  geom_text(size = 5) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$text_align <- record_case("text_align", plot_text_align, "text：hjust 0 / 0.5 / 1")
svg_cases$`geom-text-align` <- plot_text_align

# 16. text：逐行旋转角（0 / 45 / 90）
df_text_rotate <- data.frame(
  x = c(0.3, 0.5, 0.7),
  y = c(0.35, 0.6, 0.65),
  label = c("a", "b", "c"),
  ang = c(0, 45, 90)
)
plot_text_rotate <- ggplot(df_text_rotate, aes(x, y, label = label, angle = ang)) +
  geom_text(size = 5) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$text_rotate <- record_case("text_rotate", plot_text_rotate, "text：逐行 angle（0/45/90）")
svg_cases$`geom-text-rotate` <- plot_text_rotate

# 17. text：多行（`\n`）与 lineheight
df_text_wrap <- data.frame(
  x = c(0.3, 0.7),
  y = c(0.5, 0.5),
  label = c("first\nsecond", "alpha\nbeta\ngamma")
)
plot_text_wrap <- ggplot(df_text_wrap, aes(x, y, label = label)) +
  geom_text(size = 4.5, lineheight = 1.2) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$text_wrap <- record_case("text_wrap", plot_text_wrap, "text：多行标签（\\n）")
svg_cases$`geom-text-wrap` <- plot_text_wrap

# 18. label：圆角矩形背景 + 内边距
df_label <- data.frame(x = c(0.3, 0.7), y = c(0.5, 0.5), label = c("A", "BB"))
plot_label <- ggplot(df_label, aes(x, y, label = label)) +
  geom_label(size = 5, colour = "white", fill = "#4C78A8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$label_basic <- record_case("label_basic", plot_label, "label：背景框 + 内边距")
svg_cases$`geom-label-basic` <- plot_label

# 19. jitter：抖动后的坐标（抖动在 position 阶段，这里用预抖动数据）
df_jitter <- data.frame(
  x = c(0.2, 0.25, 0.3, 0.6, 0.65, 0.9),
  y = c(0.3, 0.35, 0.28, 0.7, 0.75, 0.6)
)
plot_jitter <- ggplot(df_jitter, aes(x, y)) +
  geom_jitter(stat = "identity", position = "identity", size = 3, colour = "#4C78A8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$jitter_basic <- record_case("jitter_basic", plot_jitter, "jitter：点绘制（抖动在 position）")
svg_cases$`geom-jitter-basic` <- plot_jitter

# 20. count：stat_sum 的 n → size（面积标度）
df_count <- data.frame(
  x = c(0.2, 0.2, 0.5, 0.8, 0.8, 0.8),
  y = c(0.3, 0.3, 0.5, 0.7, 0.7, 0.7),
  n = c(2, 2, 1, 3, 3, 3)
)
plot_count <- ggplot(df_count, aes(x, y, size = n)) +
  geom_count(stat = "identity", colour = "#4C78A8") +
  scale_size_area(max_size = 7) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$count_basic <- record_case("count_basic", plot_count, "count：n → size（面积标度）")
svg_cases$`geom-count-basic` <- plot_count

# 21. bin2d：stat_bin_2d 形状（x/y/width/height/count）
df_bin2d <- data.frame(
  x = c(0.166667, 0.5, 0.833333, 0.166667, 0.5, 0.833333),
  y = c(0.25, 0.25, 0.25, 0.75, 0.75, 0.75),
  width = 0.333333,
  height = 0.5,
  count = c(1, 4, 2, 3, 5, 2)
)
plot_bin2d <- ggplot(df_bin2d, aes(x, y, fill = count, width = width, height = height)) +
  geom_bin2d(stat = "identity") +
  scale_fill_gradient(low = "#EBEDF0", high = "#2C7FB8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$bin2d_basic <- record_case("bin2d_basic", plot_bin2d, "bin2d：stat_bin_2d 形状的矩形")
svg_cases$`geom-bin2d-basic` <- plot_bin2d

# 22. bin_2d 别名：同一形状、固定填充
plot_bin_2d <- ggplot(df_bin2d, aes(x, y, width = width, height = height)) +
  geom_bin_2d(stat = "identity", fill = "#4C78A8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$bin_2d_alias <- record_case("bin_2d_alias", plot_bin_2d, "bin_2d 别名")
svg_cases$`geom-bin-2d-alias` <- plot_bin_2d

# 23. hex：stat_bin_hex 形状（x/y/width/height/count）
df_hex <- data.frame(
  x = c(0.25, 0.55, 0.8),
  y = c(0.35, 0.6, 0.35),
  width = 0.3,
  height = 0.26,
  count = c(2, 5, 3)
)
plot_hex <- ggplot(df_hex, aes(x, y, fill = count, width = width, height = height)) +
  geom_hex(stat = "identity") +
  scale_fill_gradient(low = "#EBEDF0", high = "#2C7FB8") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$hex_basic <- record_case("hex_basic", plot_hex, "hex：六边形 bin")
svg_cases$`geom-hex-basic` <- plot_hex

# 24. density：stat_density 形状（x / y=density），只描上沿
df_density <- data.frame(
  x = c(0.05, 0.14, 0.23, 0.32, 0.41, 0.5, 0.59, 0.68, 0.77, 0.86, 0.95),
  y = c(0.05, 0.12, 0.3, 0.55, 0.78, 0.9, 0.85, 0.65, 0.38, 0.15, 0.04)
)
plot_density <- ggplot(df_density, aes(x, y)) +
  geom_density(stat = "identity", fill = "grey35", colour = "black") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$density_basic <- record_case("density_basic", plot_density, "density：密度多边形 + 上沿")
svg_cases$`geom-density-basic` <- plot_density

# 25/26. density_2d：两条等值线（stat_density_2d 形状的 level / x / y / group）
df_density2d <- data.frame(
  x = c(
    0.85, 0.747487, 0.5, 0.252513, 0.15, 0.252513, 0.5, 0.747487, 0.85,
    0.68, 0.627279, 0.5, 0.372721, 0.32, 0.372721, 0.5, 0.627279, 0.68
  ),
  y = c(
    0.5, 0.747487, 0.85, 0.747487, 0.5, 0.252513, 0.15, 0.252513, 0.5,
    0.5, 0.627279, 0.68, 0.627279, 0.5, 0.372721, 0.32, 0.372721, 0.5
  ),
  level = c(rep(0.2, 9), rep(0.4, 9)),
  grp = c(rep("c1", 9), rep("c2", 9)),
  stringsAsFactors = FALSE
)
plot_density2d <- ggplot(df_density2d, aes(x, y, group = grp)) +
  geom_density2d(stat = "identity", colour = "#3366FF") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$density2d_basic <- record_case("density2d_basic", plot_density2d, "density2d：两条等值线")
svg_cases$`geom-density2d-basic` <- plot_density2d

plot_density_2d <- ggplot(df_density2d, aes(x, y, group = grp)) +
  geom_density_2d(stat = "identity", colour = "#E45756") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$density_2d_alias <- record_case("density_2d_alias", plot_density_2d, "density_2d 别名")
svg_cases$`geom-density-2d-alias` <- plot_density_2d

# 27/28. density_2d_filled：分段色带（外带带洞 + 内带）
df_bands <- data.frame(
  x = c(
    0.15, 0.85, 0.85, 0.15, 0.15,
    0.35, 0.65, 0.65, 0.35, 0.35,
    0.35, 0.65, 0.65, 0.35, 0.35
  ),
  y = c(
    0.15, 0.15, 0.85, 0.85, 0.15,
    0.35, 0.35, 0.65, 0.65, 0.35,
    0.35, 0.35, 0.65, 0.65, 0.35
  ),
  level = c(rep("(0.2, 0.4]", 10), rep("(0.4, 0.6]", 5)),
  grp = c(rep("b1", 10), rep("b2", 5)),
  subgroup = c(rep("s1", 5), rep("s2", 5), rep("s1", 5)),
  stringsAsFactors = FALSE
)
band_fills <- c("(0.2, 0.4]" = "#A6CEE3", "(0.4, 0.6]" = "#1F78B4")
plot_density2d_filled <- ggplot(df_bands, aes(x, y, fill = level, group = grp, subgroup = subgroup)) +
  geom_density2d_filled(stat = "identity") +
  scale_fill_manual(values = band_fills) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$density2d_filled <- record_case(
  "density2d_filled", plot_density2d_filled, "density2d_filled：分段色带（含洞）"
)
svg_cases$`geom-density2d-filled` <- plot_density2d_filled

plot_density_2d_filled <- ggplot(
  df_bands, aes(x, y, fill = level, group = grp, subgroup = subgroup)
) +
  geom_density_2d_filled(stat = "identity") +
  scale_fill_manual(values = band_fills) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$density_2d_filled_alias <- record_case(
  "density_2d_filled_alias", plot_density_2d_filled, "density_2d_filled 别名"
)
svg_cases$`geom-density-2d-filled-alias` <- plot_density_2d_filled

# 29. contour：两条等值线（stat_contour 形状的 level / x / y / piece / group）
df_contour <- data.frame(
  x = c(0.1, 0.3, 0.5, 0.7, 0.9, 0.1, 0.3, 0.5, 0.7, 0.9),
  y = c(0.2, 0.6, 0.75, 0.6, 0.2, 0.35, 0.7, 0.85, 0.7, 0.35),
  level = c(rep(0.5, 5), rep(1.5, 5)),
  grp = c(rep("g1", 5), rep("g2", 5)),
  stringsAsFactors = FALSE
)
plot_contour <- ggplot(df_contour, aes(x, y, group = grp)) +
  geom_contour(stat = "identity", colour = "#3366FF") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$contour_basic <- record_case("contour_basic", plot_contour, "contour：两条等值线")
svg_cases$`geom-contour-basic` <- plot_contour

# 30. contour_filled：分段色带（同一份 band 数据）
plot_contour_filled <- ggplot(df_bands, aes(x, y, fill = level, group = grp, subgroup = subgroup)) +
  geom_contour_filled(stat = "identity") +
  scale_fill_manual(values = band_fills) +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$contour_filled <- record_case("contour_filled", plot_contour_filled, "contour_filled：分段色带")
svg_cases$`geom-contour-filled` <- plot_contour_filled

# 31. dotplot：真实 stat_bindot（geom_dotplot 的构造器不接受 stat=，R 侧走
# 真实统计；Python 侧把 stat 输出当绘制输入，stat="identity"）。
df_dotplot_raw <- data.frame(x = c(0.15, 0.35, 0.6, 0.6, 0.6, 0.8, 0.8))
plot_dotplot <- ggplot(df_dotplot_raw, aes(x)) +
  geom_dotplot(binwidth = 0.1, fill = "#4C78A8", colour = "black", dotsize = 1) +
  scale_x_continuous(limits = c(0.0625, 0.8875), expand = c(0, 0)) +
  scale_y_continuous(limits = c(-0.05, 1.05), expand = c(0, 0)) +
  theme_case()
cases$dotplot_stat <- record_case("dotplot_stat", plot_dotplot, "dotplot：stat_bindot 输出", "bindot")
svg_cases$`geom-dotplot-basic` <- plot_dotplot

# 32. violin：stat_ydensity 形状（violinwidth 收窄边界）
violin_y <- c(0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
df_violin <- data.frame(
  x = c(rep(1, 7), rep(2, 7)),
  y = c(violin_y, violin_y + 0.05),
  violinwidth = c(0, 0.35, 0.7, 1, 0.7, 0.35, 0, 0, 0.3, 0.65, 0.9, 0.65, 0.3, 0),
  grp = c(rep("a", 7), rep("b", 7)),
  stringsAsFactors = FALSE
)
plot_violin <- ggplot(df_violin, aes(x, y, violinwidth = violinwidth, group = grp)) +
  geom_violin(stat = "identity", width = 0.6, fill = "#4C78A8", colour = "black") +
  scale_x_continuous(limits = c(0.3, 2.7), expand = c(0, 0)) +
  scale_y_continuous(limits = c(0, 1), expand = c(0, 0)) +
  theme_case()
cases$violin_basic <- record_case("violin_basic", plot_violin, "violin：violinwidth 收窄的闭合多边形")
svg_cases$`geom-violin-basic` <- plot_violin

# 33. qq：真实 stat_qq（geom_qq 的构造器不接受 stat=，R 侧走真实统计）
df_qq_raw <- data.frame(sample = c(0.12, 0.3, 0.42, 0.55, 0.68, 0.88))
plot_qq <- ggplot(df_qq_raw, aes(sample = sample)) +
  geom_qq(size = 3, colour = "#4C78A8") +
  scale_x_continuous(limits = c(-1.409707, 1.409707), expand = c(0, 0)) +
  scale_y_continuous(limits = c(0.082, 0.918), expand = c(0, 0)) +
  theme_case()
cases$qq_stat <- record_case("qq_stat", plot_qq, "qq：stat_qq 输出（theoretical / sample）", "qq")
svg_cases$`geom-qq-basic` <- plot_qq

# 34. qq_line：真实 stat_qq_line（两端点）
plot_qq_line <- ggplot(df_qq_raw, aes(sample = sample)) +
  geom_qq_line(colour = "#3366FF") +
  scale_x_continuous(limits = c(-1.409707, 1.409707), expand = c(0, 0)) +
  scale_y_continuous(limits = c(0.1569571, 0.8205429), expand = c(0, 0)) +
  theme_case()
cases$qq_line_stat <- record_case(
  "qq_line_stat", plot_qq_line, "qq_line：stat_qq_line 输出（两端点）", "qq_line"
)
svg_cases$`geom-qq-line-basic` <- plot_qq_line

# 35. quantile：stat_quantile 形状的三条分位线
df_quantile <- data.frame(
  x = c(0.1, 0.5, 0.9, 0.1, 0.5, 0.9, 0.1, 0.5, 0.9),
  y = c(0.15, 0.3, 0.4, 0.3, 0.5, 0.65, 0.45, 0.7, 0.9),
  grp = c(rep("q1", 3), rep("q2", 3), rep("q3", 3)),
  stringsAsFactors = FALSE
)
plot_quantile <- ggplot(df_quantile, aes(x, y, group = grp)) +
  geom_quantile(stat = "identity", colour = "#3366FF") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$quantile_basic <- record_case("quantile_basic", plot_quantile, "quantile：三条分位线")
svg_cases$`geom-quantile-basic` <- plot_quantile

# 36. function：stat_function 形状的 x / y 网格
df_function <- data.frame(
  x = c(0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1),
  y = c(0.1, 0.22, 0.35, 0.48, 0.6, 0.68, 0.72, 0.68, 0.58, 0.45, 0.3)
)
plot_function <- ggplot(df_function, aes(x, y)) +
  geom_function(stat = "identity", colour = "black") +
  fixed_x(c(0, 1)) + fixed_y(c(0, 1)) + theme_case()
cases$function_basic <- record_case("function_basic", plot_function, "function：x / y 网格折线")
svg_cases$`geom-function-basic` <- plot_function

# ---------------------------------------------------------------------------
# 写盘
# ---------------------------------------------------------------------------

fixture <- list(
  r_version = paste(R.version$major, R.version$minor, sep = "."),
  ggplot2_version = as.character(packageVersion("ggplot2")),
  scale = paste0(
    "29 geom / ", length(cases), " case；data[[1]] 的列名+列序+kind+逐值；",
    "panel_params 的 continuous_range；handle_na 的 warning"
  ),
  cases = cases
)

writeLines(to_json(fixture), fixture_path)
cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", fixture_path, fixed = TRUE)))

for (name in names(svg_cases)) {
  save_case(name, svg_cases[[name]])
}
