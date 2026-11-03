#!/usr/bin/env Rscript
# M1 出口复现件（R 侧）：与 scripts/exit_report.py 同一份数据、同一段绘图代码。
#
#   pixi run -e refs Rscript scripts/exit_report.R
#
# 产物默认落 dist/exit-report/（不入库）：
#
#   report-r.svg   svglite，4×3 in，跟 Python 侧同一页面尺寸
#   report-r.png   同一张图的位图版（base png device，失败时只提示、不影响 SVG）
#
# 用 ggplot2 4.0.3（仓库钉的版本）+ svglite，与 cases 的 expected.svg 同一条产线。
# 不进 `cases:matrix`：没有期望文件、没有容差，只是出口验收时跟 Python 侧并排看。

suppressPackageStartupMessages({
  library(ggplot2)
  library(svglite)
})

stopifnot(
  "需要 ggplot2 4.0.3（pixi run -e refs ...）" =
    identical(as.character(packageVersion("ggplot2")), "4.0.3")
)

args <- commandArgs(FALSE)
script_path <- sub("^--file=", "", args[grep("^--file=", args)][1])
script_dir <- dirname(normalizePath(script_path))
repo <- dirname(script_dir)
out_dir <- file.path(repo, "dist", "exit-report")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

# 与 exit_report.py 的 report_data() 逐个数值相同：分面 × 系列 × 15 个点。
facets <- c("Alpha", "Beta", "Gamma", "Delta")
series_levels <- c("control", "treated")
rows <- list()
for (fi in seq_along(facets)) {
  for (si in seq_along(series_levels)) {
    phase <- (fi - 1) * 0.9 + (si - 1) * 1.3
    x <- seq_len(15) * 2
    y <- 3.0 + 0.05 * x + 0.9 * sin(x / 4.0 + phase) + 0.15 * ((seq_len(15) + (fi - 1) + (si - 1)) %% 3)
    rows[[length(rows) + 1]] <- data.frame(
      facet = facets[fi],
      series = series_levels[si],
      x = as.numeric(x),
      y = as.numeric(y),
      stringsAsFactors = FALSE
    )
  }
}
df <- do.call(rbind, rows)

p <- ggplot(df, aes(x = x, y = y, colour = series, group = series)) +
  geom_line(linewidth = 0.6) +
  geom_point(size = 1.6) +
  facet_wrap(~facet, ncol = 2) +
  labs(
    title = "M1 report: seasonal response by site",
    x = "Elapsed time (days)",
    y = "Response (arb. units)",
    colour = "Series"
  ) +
  theme_grey()

svg_path <- file.path(out_dir, "report-r.svg")
svglite(svg_path, width = 4, height = 3)
print(p)
invisible(dev.off())
cat("wrote", svg_path, "\n")

png_path <- file.path(out_dir, "report-r.png")
ok <- tryCatch(
  {
    png(png_path, width = 4, height = 3, units = "in", res = 150)
    print(p)
    invisible(dev.off())
    TRUE
  },
  error = function(error) {
    message("PNG 未生成（", conditionMessage(error), "）；SVG 已就绪，不影响对拍")
    FALSE
  }
)
if (ok) cat("wrote", png_path, "\n")
