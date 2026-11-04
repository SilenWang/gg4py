#!/usr/bin/env Rscript
# G10a 的诊断脚手架：打印一张图的 gtable 行列尺寸与 layout（cm / pt）。
#
#   pixi run -e refs Rscript tools/upstream/g10_probe.R 'ggplot(mtcars, aes(wt, disp)) + geom_point()'
#
# 只用来看「R 的版面到底多大」，不产出任何入库资产。
suppressMessages({
  library(ggplot2)
  library(grid)
})

args <- commandArgs(trailingOnly = TRUE)
plot <- eval(parse(text = args[1]))
gt <- ggplotGrob(plot)

cm <- function(values) {
  round(as.numeric(convertWidth(values, "cm", valueOnly = TRUE)), 3)
}

cat("== widths (cm) ==\n")
print(data.frame(i = seq_along(gt$widths), cm = cm(gt$widths)))
cat("== heights (cm) ==\n")
print(data.frame(i = seq_along(gt$heights), cm = cm(gt$heights)))
cat("== layout ==\n")
print(gt$layout[, c("t", "l", "b", "r", "z", "clip", "name")])
cat("== grobs ==\n")
for (i in seq_along(gt$grobs)) {
  grob <- gt$grobs[[i]]
  label <- if (!is.null(grob$name)) grob$name else class(grob)[1]
  size <- tryCatch(
    paste(
      round(sum(convertWidth(grobWidth(grob), "cm", valueOnly = TRUE)), 3),
      "x",
      round(sum(convertHeight(grobHeight(grob), "cm", valueOnly = TRUE)), 3)
    ),
    error = function(e) "?"
  )
  cat(sprintf("%2d %-28s %-22s %s\n", i, substr(label, 1, 28), class(grob)[1], size))
}

walk <- function(grob, depth = 1) {
  indent <- strrep("  ", depth)
  if (inherits(grob, "gtable")) {
    cat(sprintf("%swidths: %s\n", indent, paste(cm(grob$widths), collapse = " ")))
    cat(sprintf("%sheights: %s\n", indent, paste(cm(grob$heights), collapse = " ")))
    for (i in seq_along(grob$grobs)) {
      walk(grob$grobs[[i]], depth + 1)
    }
  } else if (inherits(grob, "gTree")) {
    cat(sprintf("%sgTree %-24s %s\n", indent, substr(grob$name, 1, 24), class(grob)[1]))
    for (child in grob$children) walk(child, depth + 1)
  } else {
    cat(sprintf("%s%s %s\n", indent, class(grob)[1], if (!is.null(grob$name)) grob$name else ""))
  }
}
cat("== tree ==\n")
walk(gt)
