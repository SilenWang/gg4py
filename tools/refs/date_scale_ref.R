#!/usr/bin/env Rscript
#
# SIL-800 的参考图产线：Date 列**不写** `scale_x_date()`，让 ggplot2 走它自己的
# 默认标度解析（`scale_type(Date)` → `scale_x_date()`）。
#
#   pixi run -e refs refs:date-default
#
# 对应 `docs/cases/scale-date-implicit-default-breaks/plot.py`：同一份数据、同一个
# 主题，Python 侧同样不写 `scale_x_date()`。参考图由 ggplot2 4.0.3 + svglite 生成，
# 与 `cases_battery_ref.R` 同口径（页面 10 × 8 in，只写 `expected.svg`）。
#
# 数据是 `scale_date/dates-along-x-default-breaks` 那条上游测试里的
# `set.seed(321)` 导出（`sample(100, 50)` + `runif(50)`）；这里只去掉显式标度，
# 正是 R 测试原本的写法。

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

# 不开默认绘图设备：否则 `ggplotGrob()` 会在 CWD 留下 Rplots.pdf（产物不可复现）。
invisible(pdf(NULL))

dx <- as.Date(c(
  "2012-02-29", "2012-03-03", "2012-03-06", "2012-03-07", "2012-03-08",
  "2012-03-10", "2012-03-12", "2012-03-14", "2012-03-16", "2012-03-17",
  "2012-03-19", "2012-03-22", "2012-03-24", "2012-03-28", "2012-03-29",
  "2012-03-30", "2012-04-02", "2012-04-03", "2012-04-04", "2012-04-09",
  "2012-04-13", "2012-04-14", "2012-04-15", "2012-04-16", "2012-04-17",
  "2012-04-19", "2012-04-22", "2012-04-26", "2012-04-27", "2012-04-28",
  "2012-04-30", "2012-05-01", "2012-05-02", "2012-05-05", "2012-05-11",
  "2012-05-13", "2012-05-15", "2012-05-16", "2012-05-17", "2012-05-18",
  "2012-05-19", "2012-05-20", "2012-05-22", "2012-05-26", "2012-05-27",
  "2012-05-28", "2012-05-29", "2012-06-03", "2012-06-06", "2012-06-07"
))

price <- c(
  0.9616501040, 0.1624869567, 0.0412904064, 0.1565073295, 0.5024147367,
  0.7918214588, 0.0852337643, 0.5842047508, 0.3109124061, 0.8940171362,
  0.6412378051, 0.9455218136, 0.7880687607, 0.2636332642, 0.1869768053,
  0.6517536691, 0.9137707094, 0.9281317706, 0.5269326805, 0.6258383121,
  0.1299404269, 0.7331085226, 0.5964183512, 0.4944653544, 0.4151498503,
  0.1815023392, 0.0621891215, 0.5988593667, 0.6920898366, 0.5219928171,
  0.2529071253, 0.1591295504, 0.5071416628, 0.6335240912, 0.5045890666,
  0.6020734545, 0.1328208803, 0.8721084816, 0.1653388974, 0.9785593627,
  0.4015488112, 0.6336023652, 0.6511391723, 0.5311487252, 0.9967931078,
  0.8299274566, 0.9569348753, 0.8791833892, 0.2694185616, 0.5792052438
)

df <- data.frame(dx = dx, price = price)

# 关键：**不写** `scale_x_date()`（R 的默认标度就是它）。主题用完整 grid：
# 主网格线的位置就是断点位置，断点选错时会整体挪位。
plot <- ggplot(df, aes(dx, price)) +
  geom_line() +
  theme_grey() +
  theme(panel.grid.major = element_line(colour = "grey30", linewidth = 1.6)) +
  labs(title = "dates along x, implicit date scale")

path <- file.path(cases_dir, "scale-date-implicit-default-breaks", "expected.svg")
dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
svglite(path, width = 8, height = 6)
print(plot)
grDevices::dev.off()
cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", path, fixed = TRUE)))
