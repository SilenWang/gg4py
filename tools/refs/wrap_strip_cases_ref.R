#!/usr/bin/env Rscript
# SIL-871：`facet_wrap(strip.position = "bottom" / "left" / "right")` 的参考图。
#
#   pixi run -e refs refs:wrap-strip-cases
#   Rscript tools/refs/wrap_strip_cases_ref.R <case> ...   # 只重画点名的 case
#
# 与 `cases_battery_ref.R` 分开是刻意的：那个脚本会重写全部历史 expected.svg，
# 这里只新增这三条。三条 case 共用同一份数据与主题，只差 `strip.position`——
#
#   facet-wrap-strip-bottom   strip 在面板与 x 轴之间（轴标签 / 标题在 strip 外）
#   facet-wrap-strip-left     strip 在每个面板列的左侧（y 轴在 strip 外）
#   facet-wrap-strip-right    strip 在每个面板列的右侧（y 轴仍在 strip 外）
#
# 主题用 `theme_grey()`（ggplot2 默认）：轴标签 / 轴标题 / 面板网格都在，
# 「轴带贴着分面表外沿、strip 落在面板与轴之间」的口径才检得出来。

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

df <- data.frame(
  x = c(0.10, 0.35, 0.60, 0.85, 0.15, 0.40, 0.65, 0.90),
  y = c(0.25, 0.70, 0.40, 0.85, 0.30, 0.65, 0.20, 0.75),
  g = factor(rep(c("a", "b"), each = 4), levels = c("a", "b"))
)

for (position in c("bottom", "left", "right")) {
  save_case(
    paste0("facet-wrap-strip-", position),
    ggplot(df, aes(x, y)) +
      geom_point(shape = 19, size = 2.8, colour = "#4C78A8") +
      facet_wrap(~ g, ncol = 2, strip.position = position) +
      labs(x = "x value", y = "y value") +
      theme_grey()
  )
}
