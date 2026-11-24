#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/plot_gtable_r_reference.json —— `plot_gtable()`（SIL-999）
# 的 R 侧参考值，钉 R 4.5.3 + ggplot2 4.0.3。
#
#   pixi run -e refs refs:plot-gtable
#
# 7×5in 的 svglite 页面上画一遍 `ggplotGrob()`（与 facet 参考值同一设备口径：
# svglite 的字面 Arimo 与 Python 侧 ShaperMetrics 同源），记录：
#
#   - `nrow` / `ncol`：整页表的行列数；
#   - 每条 layout 记录：`name` / `t` / `l` / `b` / `r`；
#   - 每条记录在设备上**解析后**的宽高（cm）：`downViewport()` 进
#     `<name>.<t>-<r>-<b>-<l>` 读 `1npc`。`null` 行列在这里拿到真实分配值
#     （`convertWidth(g$widths)` 对 null 只会给 0，不能用于对拍）；
#   - `widths` / `heights` 的单位字符串：用来断言 panel 行列确实是 `1null`。
#
# 六个 case：
#
#   1. plain                普通图（geom_point + labs x/y）
#   2. facet_wrap           2 列分面（strip + 每面板轴槽）
#   3. facet_grid           2×2 分面（一条轴列 / 一条 strip 列）
#   4. legend_title_tag     legend 右 + title / subtitle / caption / tag + 自定义 margin
#   5. legend_bottom        legend 换到下方
#   6. wrap_legend_titles   分面 + legend + title / caption

suppressPackageStartupMessages({
  library(ggplot2)
  library(grid)
  library(svglite)
  library(jsonlite)
})

out_path <- "tests/fixtures/plot_gtable_r_reference.json"
page_in <- c(7, 5)

d <- data.frame(
  x = c(1.5, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6, 5.0, 5.3, 5.6),
  y = c(26.0, 25.0, 24.5, 23.0, 22.5, 21.0, 20.5, 19.5, 18.0, 17.5, 16.5, 15.0),
  cyl = factor(c(4, 4, 4, 6, 6, 6, 8, 8, 8, 4, 6, 8), levels = c(4, 6, 8)),
  a = factor(c("p", "p", "p", "q", "q", "q", "p", "p", "q", "q", "p", "q"),
             levels = c("q", "p")),
  b = factor(c("u", "u", "u", "u", "v", "v", "v", "v", "u", "u", "v", "v"),
             levels = c("v", "u"))
)

num <- function(value) {
  if (is.null(value) || length(value) == 0) {
    return(NULL)
  }
  unname(as.numeric(value))
}

# 一条 layout 记录在设备上解析后的宽高（cm）：进它的单元格包装视口读 1npc。
measure_record <- function(index) {
  lay <- get("lay", envir = parent.frame())
  name <- paste0(lay$name[index], ".", lay$t[index], "-", lay$r[index], "-", lay$b[index], "-", lay$l[index])
  ok <- tryCatch({
    downViewport("layout")
    downViewport(name)
    TRUE
  }, error = function(...) FALSE)
  if (!ok) {
    upViewport(0)
    return(NULL)
  }
  width <- convertWidth(unit(1, "npc"), "cm", valueOnly = TRUE)
  height <- convertHeight(unit(1, "npc"), "cm", valueOnly = TRUE)
  upViewport(0)
  list(width = width, height = height)
}

measure_case <- function(name, plot) {
  device <- tempfile(fileext = ".svg")
  svglite(device, width = page_in[1], height = page_in[2])
  g <- ggplotGrob(plot)
  grid.newpage()
  grid.draw(g)
  lay <- g$layout
  records <- lapply(seq_len(nrow(lay)), function(index) {
    size <- measure_record(index)
    if (is.null(size)) {
      return(NULL)
    }
    list(
      name = as.character(lay$name[index]),
      t = as.integer(lay$t[index]),
      l = as.integer(lay$l[index]),
      b = as.integer(lay$b[index]),
      r = as.integer(lay$r[index]),
      width = size$width,
      height = size$height
    )
  })
  upViewport(0)
  dev.off()
  list(
    name = name,
    nrow = nrow(g),
    ncol = ncol(g),
    widths = as.character(g$widths),
    heights = as.character(g$heights),
    records = Filter(Negate(is.null), records)
  )
}

base <- function(mapping = aes(x, y)) {
  ggplot(d, mapping) + geom_point() + labs(x = "X", y = "Y")
}

cases <- list(
  measure_case("plain", base()),
  measure_case(
    "facet_wrap",
    base() + facet_wrap(~a, ncol = 2) + labs(x = "X", y = "Y")
  ),
  measure_case(
    "facet_grid",
    base() + facet_grid(b ~ a) + labs(x = "X", y = "Y")
  ),
  measure_case(
    "legend_title_tag",
    base(aes(x, y, colour = cyl)) +
      labs(title = "T", subtitle = "S", caption = "C", tag = "A") +
      theme(plot.margin = margin(6, 7, 8, 9, "pt"))
  ),
  measure_case(
    "legend_bottom",
    base(aes(x, y, colour = cyl)) + theme(legend.position = "bottom")
  ),
  measure_case(
    "wrap_legend_titles",
    base(aes(x, y, colour = cyl)) +
      facet_wrap(~a, ncol = 2) +
      labs(title = "T", caption = "C")
  )
)

names(cases) <- vapply(cases, `[[`, character(1), "name")

output <- list(
  generator = "tools/refs/plot_gtable_ref.R",
  ggplot2 = as.character(packageVersion("ggplot2")),
  r_version = R.version.string,
  size_in = page_in,
  cases = cases
)

writeLines(
  toJSON(output, auto_unbox = TRUE, digits = 17, na = "null", pretty = TRUE),
  out_path
)
cat("wrote", out_path, "with", length(cases), "cases\n")
