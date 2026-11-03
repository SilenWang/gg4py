#!/usr/bin/env Rscript
# M1-15 首轮案例库（40 条）的参考图产线：ggplot2 4.0.3 + svglite 出
# docs/cases/<case>/expected.svg（4 × 3 in）。
#
#   pixi run -e refs refs:cases                 # 全量（含 M0-9 的 7 张）
#   Rscript tools/refs/cases_battery_ref.R <case> ...   # 只重画点名的 case
#
# 与 `tools/refs/cases_ref.R`（M0-9，plot 规格适配层的 7 张）分开：本文件对应
# M1 的语法层（`plot.py` 返回 `{"plot": ggplot(...) + ...}`），每个 case 与
# `docs/cases/<case>/plot.py` 一一对应——数据、映射、标度、主题、分面、guide
# 全部同值。改 plot.py 时必须同步改这里，再重跑生成本 case 的 expected.svg。
#
# 三条硬约束：
#
# 1. **ggplot2 版本钉死 4.0.3**（`docs/notes/upstream.md` 的 pin）；不符直接退出。
# 2. **UTF-8 locale**：SVG 里的中文原样落字（`pixi` 任务已带 LC_ALL=C.UTF-8）。
# 3. 页面固定 4 × 3 in；`limits` 一律 `expand = c(0, 0)`，与 plot.py 的
#    `scale_*_continuous(limits = ..., expand = (0, 0))` 一字不差。
#
# 产物只写 `expected.svg`；不生成 `expected.png`（一个 case 只留一张）。

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
  stop("R 不在 UTF-8 locale 下：用 LC_ALL=C.UTF-8 LANG=C.UTF-8 重跑")
}

repo <- normalizePath(".")
cases_dir <- file.path(repo, "docs", "cases")
only <- commandArgs(trailingOnly = TRUE)

save_case <- function(name, plot) {
  if (length(only) > 0 && !(name %in% only)) {
    return(invisible(NULL))
  }
  path <- file.path(cases_dir, name, "expected.svg")
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  svglite(path, width = 4, height = 3)
  on.exit(grDevices::dev.off(), add = TRUE)
  print(plot)
  cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", path, fixed = TRUE)))
}

# 与 `ggcore.plot` 的 `theme_void() + theme(**{"legend.position": "none"})` 同义。
theme_case <- function() theme_void() + theme(legend.position = "none")
fx <- function(lo, hi) scale_x_continuous(limits = c(lo, hi), expand = c(0, 0))
fy <- function(lo, hi) scale_y_continuous(limits = c(lo, hi), expand = c(0, 0))

# --- geom-point ------------------------------------------------------------

save_case("geom-point-discrete", local({
  df <- data.frame(
    cls = c("a", "b", "c", "a", "b", "c", "a", "b", "c"),
    y = c(1.2, 2.4, 1.8, 1.6, 2.8, 2.2, 1.0, 2.0, 2.6),
    g = c("p", "p", "p", "q", "q", "q", "p", "q", "p")
  )
  ggplot(df, aes(cls, y, colour = g)) +
    geom_point(size = 3.2, shape = 19) +
    scale_colour_manual(values = c(p = "#F8766D", q = "#00BA38")) +
    fy(0, 3) + theme_case()
}))

.x_size <- c(0.10, 0.25, 0.40, 0.55, 0.70, 0.85, 0.18, 0.62, 0.90)
.y_size <- c(0.20, 0.55, 0.35, 0.70, 0.45, 0.80, 0.75, 0.15, 0.60)

save_case("geom-point-size", local({
  df <- data.frame(x = .x_size, y = .y_size,
                   v = c(0.00, 0.25, 0.50, 0.75, 1.00, 0.35, 0.65, 0.15, 0.85))
  ggplot(df, aes(x, y, size = v)) +
    geom_point(shape = 19, colour = "#4C78A8") +
    scale_size_continuous(limits = c(0, 1)) +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

save_case("geom-point-alpha", local({
  df <- data.frame(x = .x_size, y = .y_size,
                   v = c(0.00, 0.20, 0.40, 0.60, 0.80, 1.00, 0.30, 0.50, 0.70))
  ggplot(df, aes(x, y, alpha = v)) +
    geom_point(shape = 19, size = 4.2, colour = "#E45756") +
    scale_alpha_continuous(limits = c(0, 1)) +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

save_case("geom-point-na", local({
  df <- data.frame(
    x = c(0.10, 0.20, NA, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90),
    y = c(0.20, 0.45, 0.30, 0.55, NA, 0.70, 0.40, 0.80, 0.60)
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 3.2, colour = "#4C78A8") +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

# --- geom-line / geom-path -------------------------------------------------

save_case("geom-line-na", local({
  df <- data.frame(
    x = c(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
    y = c(0.20, 0.35, NA, 0.55, 0.60, NA, NA, 0.75, 0.85)
  )
  ggplot(df, aes(x, y)) +
    geom_line(colour = "#4C78A8") +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

save_case("geom-line-width", local({
  df <- data.frame(
    x = c(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
    y = c(0.15, 0.40, 0.30, 0.65, 0.50, 0.75, 0.45, 0.85, 0.70)
  )
  ggplot(df, aes(x, y)) +
    geom_line(colour = "#2C7FB8", linewidth = 0.9, linetype = "dashed") +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

save_case("geom-path-groups", local({
  df <- data.frame(
    x = c(0.10, 0.50, 0.20, 0.60, 0.30, 0.70, 0.40, 0.80),
    y = c(0.20, 0.75, 0.45, 0.30, 0.70, 0.50, 0.25, 0.65),
    g = c("a", "b", "a", "b", "a", "b", "a", "b")
  )
  ggplot(df, aes(x, y, colour = g, group = g)) +
    geom_path(linewidth = 0.50) +
    scale_colour_manual(values = c(a = "#4C78A8", b = "#E45756")) +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

# --- geom-bar / geom-col ---------------------------------------------------

.collide_cls <- c("a", "a", "a", "b", "b", "c")
.collide_grp <- c("p", "p", "q", "p", "q", "p")

save_case("geom-bar-dodge", local({
  df <- data.frame(cls = .collide_cls, grp = .collide_grp)
  ggplot(df, aes(cls, fill = grp)) +
    geom_bar(position = position_dodge(width = 0.9)) +
    scale_fill_manual(values = c(p = "#4C78A8", q = "#F58518")) +
    fy(0, 3) + theme_case()
}))

save_case("geom-bar-fill", local({
  df <- data.frame(cls = .collide_cls, grp = .collide_grp)
  ggplot(df, aes(cls, fill = grp)) +
    geom_bar(position = position_fill()) +
    scale_fill_manual(values = c(p = "#4C78A8", q = "#F58518")) +
    fy(0, 1) + theme_case()
}))

save_case("geom-bar-horizontal", local({
  df <- data.frame(
    cls = c("a", "a", "a", "b", "b", "c"),
    grp = c("p", "q", "p", "p", "q", "p")
  )
  ggplot(df, aes(y = cls, fill = grp)) +
    geom_bar(orientation = "y") +
    scale_fill_manual(values = c(p = "#4C78A8", q = "#F58518")) +
    fx(0, 4) + theme_case()
}))

save_case("geom-col-horizontal", local({
  df <- data.frame(cls = c("a", "b", "c"), v = c(1.4, 2.6, 0.8),
                   grp = c("p", "q", "p"))
  ggplot(df, aes(y = cls, x = v, fill = grp)) +
    geom_col(orientation = "y", width = 0.6) +
    scale_fill_manual(values = c(p = "#4C78A8", q = "#F58518")) +
    fx(0, 3) + theme_case()
}))

save_case("geom-col-dodge", local({
  df <- data.frame(
    cls = c("a", "a", "b", "b", "c", "c"),
    y = c(2.0, 3.0, 2.5, 1.5, 1.0, 2.8),
    grp = c("p", "q", "p", "q", "p", "q")
  )
  ggplot(df, aes(cls, y, fill = grp)) +
    geom_col(position = position_dodge(width = 0.8), width = 0.6) +
    scale_fill_manual(values = c(p = "#4C78A8", q = "#F58518")) +
    fy(0, 4) + theme_case()
}))

save_case("geom-col-stack", local({
  df <- data.frame(
    cls = c("a", "a", "b", "b", "c", "c"),
    y = c(1.5, 2.0, 2.4, 1.2, 0.8, 2.6),
    grp = c("p", "q", "p", "q", "p", "q")
  )
  ggplot(df, aes(cls, y, fill = grp)) +
    geom_col(position = position_stack(), width = 0.7) +
    scale_fill_manual(values = c(p = "#4C78A8", q = "#F58518")) +
    fy(0, 5) + theme_case()
}))

# --- geom-area -------------------------------------------------------------

save_case("geom-area-stacked", local({
  df <- data.frame(
    x = c(1, 2, 3, 4, 1, 2, 3, 4),
    y = c(1.0, 1.5, 1.2, 1.8, 0.8, 0.6, 1.1, 0.9),
    g = rep(c("a", "b"), each = 4)
  )
  ggplot(df, aes(x, y, fill = g)) +
    geom_area(position = position_stack()) +
    scale_fill_manual(values = c(a = "#4C78A8", b = "#F58518")) +
    fx(0.5, 4.5) + fy(0, 4) + theme_case()
}))

# 单组：stat_align 的 is_unique(group) 分支原样通过。
save_case("geom-area-single", local({
  df <- data.frame(
    x = c(1.0, 1.8, 2.9, 3.4, 4.6, 5.0),
    y = c(0.8, 1.4, 1.1, 1.9, 1.5, 2.2)
  )
  ggplot(df, aes(x, y)) +
    geom_area(fill = "#4C78A8") +
    fx(0.5, 5.5) + fy(0, 3) + theme_case()
}))

# 注：**横向 area** 没有参考图——ggplot2 4.0.3 的 stat_align 在 y 为离散时
# 产出 0 行（`geom_area(aes(x = v, y = cls), orientation = "y")` 的
# `ggplot_build()` 是空表），R 侧只能用 `coord_flip()` 表达同一张图，而 coord_flip
# 不在 gg4py 的 coord 注册表里（只有 cartesian / fixed）。横向 area 的用例因此
# 没有落地，缺口见 SIL-709 的评论（M2 输入）。

save_case("geom-area-align", local({
  df <- data.frame(
    x = c(1, 2, 4, 1, 3, 4, 2, 3, 4),
    y = c(1.0, 1.6, 1.2, 0.8, 1.0, 0.6, 0.5, 0.9, 0.7),
    g = rep(c("a", "b", "c"), each = 3)
  )
  ggplot(df, aes(x, y, fill = g)) +
    geom_area(position = position_stack()) +
    scale_fill_manual(values = c(a = "#4C78A8", b = "#F58518", c = "#54A24B")) +
    fx(0.5, 4.5) + fy(0, 5) + theme_case()
}))

# --- geom-histogram --------------------------------------------------------

save_case("geom-histogram-bins", local({
  df <- data.frame(x = c(
    0.02, 0.06, 0.11, 0.14, 0.19, 0.22, 0.27, 0.31, 0.34, 0.38,
    0.41, 0.45, 0.48, 0.52, 0.55, 0.58, 0.62, 0.66, 0.69, 0.72,
    0.75, 0.78, 0.81, 0.84, 0.87, 0.90, 0.93, 0.96, 0.98, 0.99
  ))
  ggplot(df, aes(x)) +
    geom_histogram(bins = 8, fill = "#4C78A8") +
    fx(0, 1) + fy(0, 8) + theme_case()
}))

save_case("geom-histogram-binwidth", local({
  df <- data.frame(x = c(
    0.05, 0.12, 0.18, 0.22, 0.28, 0.31, 0.35, 0.38, 0.42, 0.46,
    0.52, 0.58, 0.61, 0.66, 0.71, 0.75, 0.82, 0.88, 0.92, 0.97
  ))
  ggplot(df, aes(x)) +
    geom_histogram(binwidth = 0.2, boundary = 0, fill = "#4C78A8") +
    fx(0, 1) + fy(0, 8) + theme_case()
}))

save_case("geom-histogram-horizontal", local({
  df <- data.frame(x = c(
    0.05, 0.08, 0.12, 0.15, 0.18, 0.22, 0.25, 0.28, 0.35, 0.38,
    0.42, 0.45, 0.48, 0.55, 0.58, 0.62, 0.65, 0.72, 0.75, 0.82,
    0.85, 0.88, 0.92, 0.95
  ))
  ggplot(df, aes(y = x)) +
    geom_histogram(bins = 6, fill = "#4C78A8") +
    fx(0, 10) + fy(0, 1) + theme_case()
}))

# --- geom-boxplot ----------------------------------------------------------

save_case("geom-boxplot-outliers", local({
  df <- data.frame(
    cls = c(rep("a", 5), rep("b", 6), rep("c", 6)),
    v = c(2.0, 3.0, 4.0, 5.0, 6.0,
          2.0, 3.0, 3.5, 4.0, 4.5, 9.0,
          1.0, 1.5, 2.0, 2.5, 3.0, 8.5)
  )
  ggplot(df, aes(cls, v)) +
    geom_boxplot(fill = "#4C78A8", colour = "#333333", width = 0.6) +
    fy(0, 10) + theme_case()
}))

save_case("geom-boxplot-varwidth", local({
  df <- data.frame(
    cls = c(rep("a", 8), rep("b", 4), rep("c", 6)),
    v = c(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0,
          2.0, 3.0, 4.0, 5.0,
          1.5, 2.5, 3.5, 4.5, 5.5, 6.5)
  )
  ggplot(df, aes(cls, v)) +
    geom_boxplot(fill = "#4C78A8", colour = "#333333", varwidth = TRUE, width = 0.8) +
    fy(0, 9) + theme_case()
}))

save_case("geom-boxplot-horizontal", local({
  df <- data.frame(
    cls = c(rep("a", 6), rep("b", 6)),
    v = c(1.5, 2.0, 2.5, 3.0, 3.5, 4.0,
          0.5, 1.0, 1.5, 2.0, 2.5, 5.0)
  )
  ggplot(df, aes(y = cls, x = v)) +
    geom_boxplot(fill = "#F58518", colour = "#333333", width = 0.6, orientation = "y") +
    fx(0, 6) + theme_case()
}))

# --- geom-smooth -----------------------------------------------------------

.y_smooth <- c(0.10, 0.32, 0.28, 0.45, 0.52, 0.48, 0.63, 0.70, 0.66, 0.82, 0.95)

save_case("geom-smooth-default", local({
  df <- data.frame(x = c(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0), y = .y_smooth)
  ggplot(df, aes(x, y)) +
    geom_smooth(fill = "black") +
    fx(0, 1) + fy(0, 1.1) + theme_case()
}))

save_case("geom-smooth-groups", local({
  df <- data.frame(
    x = c(0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9,
          0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9),
    y = c(0.10, 0.22, 0.35, 0.40, 0.52, 0.60, 0.72,
          0.80, 0.72, 0.60, 0.55, 0.42, 0.30, 0.20),
    g = rep(c("a", "b"), each = 7)
  )
  ggplot(df, aes(x, y, colour = g, group = g)) +
    geom_smooth(method = "loess", formula = y ~ x, se = FALSE) +
    scale_colour_manual(values = c(a = "#3366FF", b = "#E45756")) +
    fx(0, 0.9) + fy(0, 1) + theme_case()
}))

save_case("geom-smooth-span", local({
  df <- data.frame(
    x = c(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
    y = c(0.20, 0.55, 0.30, 0.60, 0.35, 0.65, 0.40, 0.70, 0.45, 0.75, 0.50)
  )
  ggplot(df, aes(x, y)) +
    geom_smooth(method = "loess", span = 0.4, fill = "black") +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

# --- scale -----------------------------------------------------------------

save_case("scale-x-log10", local({
  df <- data.frame(
    x = c(1, 3, 10, 30, 100, 300, 1000, 2, 20, 200),
    y = c(0.10, 0.25, 0.35, 0.50, 0.60, 0.75, 0.90, 0.18, 0.42, 0.68)
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 3.2, colour = "#4C78A8") +
    scale_x_log10(limits = c(1, 1000), expand = c(0, 0)) +
    fy(0, 1) + theme_case()
}))

save_case("scale-y-log10", local({
  df <- data.frame(
    x = c(0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75),
    y = c(1, 3, 10, 30, 100, 300, 1000, 2, 200)
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 3.2, colour = "#F58518") +
    fx(0, 1) +
    scale_y_log10(limits = c(1, 1000), expand = c(0, 0)) +
    theme_case()
}))

save_case("scale-colour-default", local({
  df <- data.frame(
    x = c(0.15, 0.35, 0.55, 0.75, 0.25, 0.45, 0.65, 0.85, 0.10, 0.60),
    y = c(0.20, 0.45, 0.30, 0.60, 0.75, 0.55, 0.80, 0.40, 0.50, 0.15),
    g = c("a", "a", "b", "b", "c", "c", "a", "b", "c", "a")
  )
  ggplot(df, aes(x, y, colour = g)) +
    geom_point(shape = 19, size = 3.6) +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

save_case("scale-colour-gradient", local({
  df <- data.frame(
    x = c(0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75),
    y = c(0.20, 0.50, 0.35, 0.70, 0.45, 0.80, 0.60, 0.85, 0.15),
    v = c(0.00, 0.12, 0.25, 0.38, 0.50, 0.62, 0.75, 0.88, 1.00)
  )
  ggplot(df, aes(x, y, colour = v)) +
    geom_point(shape = 19, size = 3.8) +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

save_case("scale-limits-drop", local({
  df <- data.frame(
    x = c(0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75),
    y = c(0.20, 0.95, 0.35, 0.70, 0.05, 0.80, 0.60, 0.85, 0.15)
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 3.2, colour = "#54A24B") +
    fx(0.2, 0.9) + fy(0.2, 0.9) + theme_case()
}))

# --- scale（M2-4 B：调色板 / manual / identity / 线型 / 面积）-----------------

# viridis 离散色板 + 完整图例（4 个水平）。颜色逐点由 viridis() 给，不是手写表。
save_case("scale-colour-viridis-d", local({
  df <- data.frame(
    x = c(0.12, 0.30, 0.52, 0.74, 0.22, 0.44, 0.66, 0.88, 0.18, 0.40, 0.60, 0.82),
    y = c(0.22, 0.48, 0.32, 0.66, 0.78, 0.56, 0.84, 0.42, 0.60, 0.28, 0.74, 0.50),
    g = c("a", "a", "a", "b", "b", "b", "c", "c", "c", "d", "d", "d")
  )
  ggplot(df, aes(x, y, colour = g)) +
    geom_point(shape = 19, size = 3.0) +
    scale_colour_viridis_d(option = "D") +
    fx(0, 1) + fy(0, 1) + theme_void()
}))

# brewer 填充 + 完整图例（3 个水平，Set2 逐 n 表的 3 色）。
save_case("scale-fill-brewer", local({
  df <- data.frame(
    cls = c("a", "b", "c", "a", "b", "c"),
    y = c(1.2, 2.1, 1.6, 0.9, 1.5, 2.3),
    grp = c("p", "p", "p", "q", "q", "q")
  )
  ggplot(df, aes(cls, y, fill = grp)) +
    geom_col(width = 0.7, position = position_dodge()) +
    scale_fill_brewer(palette = "Set2") +
    fy(0, 3.2) + theme_void()
}))

# 离散 linetype + 完整图例：默认 pal_linetype（solid / 22 / 42）。
save_case("scale-linetype-discrete", local({
  df <- data.frame(
    x = c(0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65),
    y = c(0.2, 0.5, 0.3, 0.6, 0.4, 0.7, 0.35, 0.65, 0.45, 0.75, 0.5, 0.8),
    g = rep(c("a", "b", "c"), each = 4)
  )
  ggplot(df, aes(x, y, linetype = g)) +
    geom_line(linewidth = 1.1) +
    fx(0, 0.7) + fy(0, 1) + theme_void() +
    theme(legend.position = "none")
}))

# size_area：面积正比于值（散点）+ 完整图例。
save_case("scale-size-area", local({
  df <- data.frame(
    x = c(0.12, 0.30, 0.52, 0.74, 0.22, 0.44, 0.66, 0.88),
    y = c(0.22, 0.48, 0.32, 0.66, 0.78, 0.56, 0.84, 0.42),
    v = c(0.0, 1.0, 2.0, 3.0, 4.0, 1.5, 2.5, 3.5)
  )
  ggplot(df, aes(x, y, size = v)) +
    geom_point(shape = 19, colour = "#4C78A8") +
    scale_size_area(max_size = 6) +
    fx(0, 1) + fy(0, 1) + theme_void()
}))

# identity：数据里已经是颜色值，映射原样通过（不产生图例）。
save_case("scale-colour-identity", local({
  df <- data.frame(
    x = c(0.12, 0.30, 0.52, 0.74, 0.22, 0.44, 0.66, 0.88, 0.18, 0.40),
    y = c(0.22, 0.48, 0.32, 0.66, 0.78, 0.56, 0.84, 0.42, 0.60, 0.28),
    col = rep(c("#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2"), each = 2)
  )
  ggplot(df, aes(x, y, colour = col)) +
    geom_point(shape = 19, size = 3.2) +
    scale_colour_identity() +
    fx(0, 1) + fy(0, 1) + theme_void()
}))

# --- facet -----------------------------------------------------------------

save_case("facet-wrap-2x2", local({
  df <- data.frame(
    x = c(0.2, 0.5, 0.8, 0.3, 0.6, 0.9, 0.15, 0.45, 0.75, 0.25, 0.55, 0.85),
    y = c(0.3, 0.6, 0.4, 0.7, 0.2, 0.8, 0.5, 0.65, 0.35, 0.45, 0.75, 0.55),
    g = rep(c("a", "b", "c", "d"), each = 3)
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 2.8, colour = "#4C78A8") +
    facet_wrap(~ g, ncol = 2) +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

save_case("facet-grid-ab", local({
  df <- data.frame(
    x = c(0.2, 0.6, 0.3, 0.7, 0.25, 0.65, 0.35, 0.75),
    y = c(0.3, 0.5, 0.6, 0.4, 0.55, 0.25, 0.45, 0.8),
    r = c("t", "t", "t", "t", "u", "u", "u", "u"),
    c = c("l", "l", "r", "r", "l", "l", "r", "r")
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 2.8, colour = "#F58518") +
    facet_grid(r ~ c) +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

save_case("facet-wrap-free-y", local({
  df <- data.frame(
    x = c(0.2, 0.5, 0.8, 0.3, 0.6, 0.9, 0.15, 0.45),
    y = c(1.0, 1.5, 1.2, 1.8, 10.0, 15.0, 12.0, 18.0),
    g = rep(c("a", "b"), each = 4)
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 2.8, colour = "#4C78A8") +
    facet_wrap(~ g, ncol = 2, scales = "free_y") +
    fx(0.1, 0.9) + theme_case()
}))

save_case("facet-wrap-free-x", local({
  df <- data.frame(
    x = c(0.10, 0.20, 0.30, 0.15, 1.0, 1.4, 1.8, 2.2),
    y = c(0.2, 0.5, 0.35, 0.7, 0.3, 0.6, 0.45, 0.8),
    g = rep(c("a", "b"), each = 4)
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 2.8, colour = "#54A24B") +
    facet_wrap(~ g, ncol = 2, scales = "free_x") +
    fy(0, 1) + theme_case()
}))

# M2-3：space = "free" 的面板宽高按该列 / 行的水平数（离散）或范围差分配。
save_case("facet-grid-space-free", local({
  df <- data.frame(
    x = c("a", "b", "a", "b", "c", "a", "b", "c",
          "a", "b", "a", "b", "c", "a", "b", "c"),
    y = c(0.2, 0.5, 0.35, 0.7, 0.45, 0.3, 0.6, 0.25,
          0.65, 0.4, 0.55, 0.2, 0.75, 0.5, 0.3, 0.8),
    r = rep(c("t", "u"), each = 8),
    c = c("l", "l", "l", "l", "l", "r", "r", "r",
          "l", "r", "l", "r", "l", "r", "l", "r")
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 2.8, colour = "#54A24B") +
    facet_grid(r ~ c, space = "free", scales = "free") +
    theme_case()
}))

# M2-3：margins = TRUE 追加 (all) 行 / 列边际面板。
save_case("facet-grid-margins", local({
  df <- data.frame(
    x = c(0.2, 0.6, 0.3, 0.7, 0.25, 0.65, 0.35, 0.75),
    y = c(0.3, 0.5, 0.6, 0.4, 0.55, 0.25, 0.45, 0.8),
    r = c("t", "t", "t", "t", "u", "u", "u", "u"),
    c = c("l", "l", "r", "r", "l", "l", "r", "r")
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 2.8, colour = "#F58518") +
    facet_grid(r ~ c, margins = TRUE) +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

# SIL-759：space = "free" × coord_fixed(ratio)：ratio 折进行权重（R init_gtable()），
# 面板高/宽 = ratio × yspan / xspan。
save_case("facet-grid-free-fixed", local({
  df <- data.frame(
    x = c("a", "b", "a", "b", "c", "a", "b", "c",
          "a", "b", "a", "b", "c", "a", "b", "c"),
    y = c(0.2, 0.5, 0.35, 0.7, 0.45, 0.3, 0.6, 0.25,
          0.65, 0.4, 0.55, 0.2, 0.75, 0.5, 0.3, 0.8),
    r = rep(c("t", "u"), each = 8),
    c = c("l", "l", "l", "l", "l", "r", "r", "r",
          "l", "r", "l", "r", "l", "r", "l", "r")
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 2.8, colour = "#4C78A8") +
    facet_grid(r ~ c, space = "free") +
    coord_fixed(2) +
    theme_case()
}))

# SIL-759：多行变量的右侧 strip —— 最后一个变量最靠近面板（R 先 rev() 再 weave）。
save_case("facet-grid-rows-label-both", local({
  df <- data.frame(
    x = c(0.2, 0.6, 0.3, 0.7, 0.25, 0.65, 0.35, 0.75, 0.15, 0.55, 0.4, 0.8),
    y = c(0.3, 0.5, 0.6, 0.4, 0.55, 0.25, 0.45, 0.8, 0.35, 0.65, 0.2, 0.7),
    r1 = rep(c("t", "u"), each = 6),
    r2 = rep(c("a", "b"), 6)
  )
  ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 2.8, colour = "#F58518") +
    facet_grid(r1 + r2 ~ ., labeller = "label_both") +
    theme_case()
}))

# --- theme -----------------------------------------------------------------

.x_theme <- c(1.0, 2.0, 3.0, 4.0, 5.0, 1.5, 2.5, 3.5, 4.5, 5.5)
.y_theme <- c(2.1, 2.8, 3.2, 3.9, 4.5, 3.4, 4.1, 2.6, 4.8, 3.0)

.save_theme_case <- function(name, theme_obj, colour) {
  df <- data.frame(x = .x_theme, y = .y_theme)
  save_case(name, ggplot(df, aes(x, y)) +
    geom_point(shape = 19, size = 2.4, colour = colour) +
    fx(0, 6) + fy(1.5, 5.5) + theme_obj +
    theme(legend.position = "none"))
}

# ci = false 的两条：当前渲染器不画 panel.grid.*，网格线整片缺失。
.save_theme_case("theme-grey-basic", theme_grey(), "#F8766D")
.save_theme_case("theme-minimal-basic", theme_minimal(), "#00BA38")
.save_theme_case("theme-void-basic", theme_void(), "#619CFF")

# --- guide -----------------------------------------------------------------

save_case("guide-legend-single", local({
  df <- data.frame(x = .x_theme, y = .y_theme, g = rep(c("a", "b"), each = 5))
  ggplot(df, aes(x, y, colour = g)) +
    geom_point(shape = 19, size = 2.4) +
    scale_colour_manual(values = c(a = "#F8766D", b = "#00BA38")) +
    fx(0, 6) + fy(1.5, 5.5) + theme_void()
}))

save_case("guide-legend-merged", local({
  df <- data.frame(
    x = c(0.15, 0.35, 0.55, 0.75, 0.25, 0.45, 0.65, 0.85),
    y = c(0.20, 0.45, 0.30, 0.60, 0.75, 0.55, 0.80, 0.40),
    g = c("a", "a", "b", "b", "a", "a", "b", "b"),
    sh = c("s1", "s2", "s1", "s2", "s1", "s2", "s1", "s2")
  )
  ggplot(df, aes(x, y, colour = g, shape = sh)) +
    geom_point(size = 2.8) +
    scale_colour_manual(values = c(a = "#F8766D", b = "#00BA38")) +
    scale_shape_manual(values = c(s1 = 19, s2 = 15)) +
    fx(0, 1) + fy(0, 1) + theme_void()
}))

# ci = false：渐变条在 gg4py 的 SVG 里是 256 条细矩形，resvg 下偏白。
save_case("guide-colourbar", local({
  df <- data.frame(
    x = c(0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.90, 0.25, 0.75),
    y = c(0.20, 0.50, 0.35, 0.70, 0.45, 0.80, 0.60, 0.85, 0.15),
    v = c(0.00, 0.12, 0.25, 0.38, 0.50, 0.62, 0.75, 0.88, 1.00)
  )
  ggplot(df, aes(x, y, colour = v)) +
    geom_point(shape = 19, size = 3.2) +
    fx(0, 1) + fy(0, 1) + theme_void()
}))

# --- extension -------------------------------------------------------------

# `ext-custom-geom` 的 gg4py 侧只实现一个 `GeomMySegment` 子类；R 侧没有同名
# geom，用等价的 geom_segment()（同数据、颜色、线宽、limits）作为外部参考。
save_case("ext-custom-geom", local({
  df <- data.frame(
    x = c(0.08, 0.18, 0.28, 0.42, 0.56, 0.70),
    y = c(0.20, 0.72, 0.42, 0.86, 0.16, 0.60),
    xend = c(0.24, 0.34, 0.48, 0.66, 0.76, 0.92),
    yend = c(0.78, 0.28, 0.64, 0.20, 0.58, 0.88)
  )
  ggplot(df, aes(x, y, xend = xend, yend = yend)) +
    geom_segment(colour = "#4C78A8", linewidth = 0.8, lineend = "butt") +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

# --- guide（M2-2，SIL-738）：合并 / override / 方位 / 多图例 ------------------

.save_guide_data <- function() {
  data.frame(
    x = c(0.12, 0.28, 0.44, 0.60, 0.76, 0.88, 0.22, 0.38, 0.54, 0.70),
    y = c(0.18, 0.42, 0.30, 0.66, 0.50, 0.80, 0.74, 0.56, 0.86, 0.24),
    g = c("a", "b", "c", "a", "b", "c", "a", "b", "c", "a"),
    h = c("p", "q", "p", "q", "p", "q", "p", "q", "p", "q")
  )
}

save_case("guide-legend-merge-fill", local({
  df <- .save_guide_data()
  ggplot(df, aes(x, y, colour = g, fill = g)) +
    geom_point(shape = 21, size = 2.8) +
    scale_colour_manual(values = c(a = "#F8766D", b = "#00BA38", c = "#619CFF")) +
    scale_fill_manual(values = c(a = "#F8766D", b = "#00BA38", c = "#619CFF")) +
    guides(colour = "legend", fill = "legend") +
    fx(0, 1) + fy(0, 1) + theme_void()
}))

save_case("guide-legend-override", local({
  df <- .save_guide_data()
  ggplot(df, aes(x, y, colour = g)) +
    geom_point(size = 2.4) +
    scale_colour_manual(values = c(a = "#F8766D", b = "#00BA38", c = "#619CFF")) +
    guides(colour = guide_legend(override.aes = list(colour = "black", shape = 17))) +
    fx(0, 1) + fy(0, 1) + theme_void()
}))

save_case("guide-legend-top", local({
  df <- .save_guide_data()
  df$y <- c(0.42, 0.66, 0.50, 0.80, 0.74, 0.56, 0.86, 0.24, 0.18, 0.30)
  ggplot(df, aes(x, y, colour = g)) +
    geom_point(size = 2.4) +
    scale_colour_manual(values = c(a = "#F8766D", b = "#00BA38", c = "#619CFF")) +
    fx(0, 1) + fy(0, 1) + theme_void() +
    theme(legend.position = "top")
}))

save_case("guide-legend-inside", local({
  df <- .save_guide_data()
  ggplot(df, aes(x, y, colour = g)) +
    geom_point(size = 2.4) +
    scale_colour_manual(values = c(a = "#F8766D", b = "#00BA38", c = "#619CFF")) +
    fx(0, 1) + fy(0, 1) + theme_void() +
    theme(
      legend.position = "inside",
      legend.position.inside = c(0.72, 0.78)
    )
}))

save_case("guide-legend-two", local({
  df <- .save_guide_data()
  ggplot(df, aes(x, y, colour = g, fill = h)) +
    geom_point(shape = 21, size = 2.8) +
    scale_colour_manual(values = c(a = "#F8766D", b = "#00BA38", c = "#619CFF")) +
    scale_fill_manual(values = c(p = "#F8766D", q = "#00BA38")) +
    guides(
      fill = guide_legend(order = 1),
      colour = guide_legend(order = 2)
    ) +
    fx(0, 1) + fy(0, 1) + theme_void()
}))
