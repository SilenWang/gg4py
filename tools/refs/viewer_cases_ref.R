#!/usr/bin/env Rscript
# M2-12 的参考图产线：只生成查看器渲染器专项的 4 条 case 的 expected.svg
# （ggplot2 4.0.3 + svglite，4 × 3 in）。
#
#   pixi run -e refs refs:viewer-cases
#   Rscript tools/refs/viewer_cases_ref.R viewer-pch-all      # 只重画点名的
#
# 与 `cases_battery_ref.R` 分开是有意的：那份脚本会重写全部 40 张历史参考图，
# 本 issue 只**新增** case，不能碰任何已有 `expected.svg`（X4）。
#
# 三条硬约束与 battery 相同：ggplot2 必须 4.0.3、UTF-8 locale、页面 4 × 3 in。
# 数据与 `docs/cases/<case>/plot.py` 逐值相同，改一边必须同步另一边。

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

theme_case <- function() theme_void() + theme(legend.position = "none")
fx <- function(lo, hi) scale_x_continuous(limits = c(lo, hi), expand = c(0, 0))
fy <- function(lo, hi) scale_y_continuous(limits = c(lo, hi), expand = c(0, 0))

# --- lty 全量 --------------------------------------------------------------

save_case("viewer-linetype-all", local({
  xs <- c(0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95)
  zig <- c(0.00, 0.03, -0.02, 0.04, -0.03, 0.02, -0.04, 0.03, -0.01, 0.02)
  base <- c(0.08, 0.22, 0.36, 0.50, 0.64, 0.78, 0.92)
  lt <- c("solid", "dashed", "dotted", "dotdash", "longdash", "twodash", "blank")
  # 组名取 l1..l7：ggplot2 对字符列按 sort(unique(x)) 排水平，字典序即想要
  # 的顺序（用 factor 的插入序会与 python 侧不一致）。
  levels <- paste0("l", seq_along(lt))
  df <- data.frame(
    x = rep(xs, times = length(base)),
    y = rep(base, each = length(xs)) + rep(zig, times = length(base)),
    lt = rep(levels, each = length(xs))
  )
  ggplot(df, aes(x, y, linetype = lt, group = lt)) +
    geom_line(linewidth = 1) +
    scale_linetype_manual(values = lt) +
    fx(0, 1) + fy(0, 1) + theme_case()
}))

# --- pch 0..25 -------------------------------------------------------------

save_case("viewer-pch-all", local({
  cols <- c(0.08, 0.22, 0.36, 0.50, 0.64, 0.78, 0.92)
  rows <- c(0.82, 0.60, 0.38, 0.16)
  sh <- 0:25
  df <- data.frame(x = cols[sh %% 7 + 1], y = rows[sh %/% 7 + 1], sh = sh)
  p <- ggplot(df, aes(x, y))
  for (s in 0:25) {
    p <- p + geom_point(
      data = df[df$sh == s, ], shape = s, size = 6,
      colour = "#1F2937", fill = "#7FB3D5"
    )
  }
  p + fx(0, 1) + fy(0, 1) + theme_case()
}))

# --- alpha：映射到 fill -----------------------------------------------------

save_case("viewer-alpha-fill", local({
  df <- data.frame(
    cls = c("a", "b", "c", "d"),
    v = c(0.40, 0.70, 0.50, 0.90),
    a = c(0.20, 0.40, 0.60, 0.80)
  )
  ggplot(df, aes(cls, v, alpha = a)) +
    geom_col(fill = "#4C78A8", colour = NA) +
    scale_alpha_continuous(limits = c(0, 1)) +
    scale_x_discrete() +
    fy(0, 1) + theme_case()
}))

# --- alpha：两层重叠的合成顺序 ---------------------------------------------

save_case("viewer-alpha-overlap", local({
  df <- data.frame(x = c(0.25, 0.75), x2 = c(0.40, 0.72), y = c(0.70, 0.50))
  ggplot(df, aes(x, y)) +
    geom_col(width = 0.40, fill = "#E45756", alpha = 0.55, colour = NA) +
    geom_col(aes(x = x2, y = y), width = 0.40, fill = "#4C78A8",
             alpha = 0.55, colour = NA) +
    fx(0, 1) + fy(0, 1) + theme_case()
}))
