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
