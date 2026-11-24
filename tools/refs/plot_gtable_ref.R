#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/plot_gtable_r_reference.json —— `plot_gtable()`（SIL-999）
# 与 ggplot2 4.0.3 `ggplotGrob()` 的结构对拍参考值。
#
#   pixi run -e refs refs:plot-gtable
#
# 参考值分两部分：
#   1. 结构：行列数 + 每条 layout 记录的 (name, t, l, b, r)；
#   2. 单位向量：`widths` / `heights` 的 `as.character()`。测试只解析其中**可静态
#      求值**的元素（`5.5points` / `0.350502602739725cm` / `0cm` …），跳过
#      `1grobwidth` / `1grobheight` / `sum(...)` / `1null` —— 前三个要设备度量，
#      最后一个由 gtable 按面板比例分配，两边各算各的。
#
# 为什么不用设备测量：整页表的 null 单位是给多图合并用的权重，解析值取决于页面
# 尺寸；真正要对拍的是「哪些行列、多宽多高、叫什么名字」。

suppressPackageStartupMessages({
  library(ggplot2)
  library(grid)
})

# 不开默认绘图设备：否则 `ggplotGrob()` 会在 CWD 留下 Rplots.pdf。
invisible(pdf(NULL))

out_path <- "tests/fixtures/plot_gtable_r_reference.json"

# ---------------------------------------------------------------------------
# 极简 JSON 输出（与 tools/refs/gtable_ref.R 同一份）
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
  if (is.null(x)) return("null")
  if (is.logical(x) && length(x) == 1L) {
    if (is.na(x)) return("null")
    return(if (isTRUE(x)) "true" else "false")
  }
  if (is.numeric(x) && length(x) == 1L) return(fmt_num(x))
  if (is.character(x) && length(x) == 1L) return(json_escape(x))
  if (is.list(x)) {
    nm <- names(x)
    if (!is.null(nm)) {
      if (length(x) == 0L) return("{}")
      items <- vapply(seq_along(x), function(i) {
        paste0(pad2, json_escape(nm[[i]]), ": ", to_json(x[[i]], indent + 1L))
      }, character(1))
      return(paste0("{\n", paste(items, collapse = ",\n"), "\n", pad, "}"))
    }
    if (length(x) == 0L) return("[]")
    items <- vapply(x, function(el) paste0(pad2, to_json(el, indent + 1L)), character(1))
    return(paste0("[\n", paste(items, collapse = ",\n"), "\n", pad, "]"))
  }
  if (length(x) == 0L) return("[]")
  items <- vapply(seq_along(x), function(i) {
    paste0(pad2, to_json(x[[i]], indent + 1L))
  }, character(1))
  paste0("[\n", paste(items, collapse = ",\n"), "\n", pad, "]")
}

# ---------------------------------------------------------------------------
# 采集
# ---------------------------------------------------------------------------

measure_case <- function(name, plot) {
  grob <- ggplotGrob(plot)
  lay <- grob$layout
  placements <- lapply(seq_len(nrow(lay)), function(i) {
    list(
      name = lay$name[i],
      t = as.integer(lay$t[i]),
      l = as.integer(lay$l[i]),
      b = as.integer(lay$b[i]),
      r = as.integer(lay$r[i])
    )
  })
  list(
    name = name,
    nrow = as.integer(nrow(grob)),
    ncol = as.integer(ncol(grob)),
    respect = isTRUE(grob$respect),
    widths = vapply(as.character(grob$widths), identity, character(1), USE.NAMES = FALSE),
    heights = vapply(as.character(grob$heights), identity, character(1), USE.NAMES = FALSE),
    layout = placements
  )
}

data <- data.frame(
  x = c(1, 2, 3, 4, 5, 6, 7, 8),
  y = c(2, 4, 3, 5, 6, 3, 4, 7),
  g = factor(c("a", "b", "a", "b", "a", "b", "a", "b"), levels = c("a", "b")),
  h = factor(c("u", "u", "u", "u", "v", "v", "v", "v"), levels = c("u", "v")),
  four = factor(c("p", "q", "r", "s", "p", "q", "r", "s"),
                levels = c("p", "q", "r", "s"))
)

base <- ggplot(data, aes(x, y)) + geom_point()

cases <- list(
  measure_case("plain", base + labs(x = "XX", y = "YY")),
  measure_case(
    "titled",
    base + labs(title = "TT", subtitle = "SS", caption = "CC", tag = "A", x = "XX", y = "YY")
  ),
  measure_case(
    "legend",
    ggplot(data, aes(x, y, colour = g)) + geom_point() + labs(title = "TT", x = "XX", y = "YY")
  ),
  measure_case("facet_wrap", base + facet_wrap(~g)),
  measure_case("facet_grid", base + facet_grid(g ~ .)),
  measure_case("coord_fixed", base + coord_fixed(ratio = 2)),
  # SIL-999 审计补的 4 个 shape：多行 / 多列分面的展开规则与 R 对拍。
  measure_case("wrap_ncol1", base + facet_wrap(~g, ncol = 1)),
  measure_case("wrap_2x2", base + facet_wrap(~four)),
  measure_case("grid_1x2", base + facet_grid(. ~ g)),
  measure_case("grid_2x2", base + facet_grid(h ~ g)),
  # `plot.title.position = "plot"`：title / subtitle 的跨列范围。
  measure_case(
    "title_plot_position",
    ggplot(data, aes(x, y, colour = g)) +
      geom_point() +
      labs(title = "TT", subtitle = "SS", x = "XX", y = "YY") +
      theme(plot.title.position = "plot")
  )
)

doc <- list(
  generator = "tools/refs/plot_gtable_ref.R",
  ggplot2 = as.character(packageVersion("ggplot2")),
  size_in = c(7, 7),
  cases = cases
)

writeLines(paste0(to_json(doc), "\n"), out_path)
cat("wrote", out_path, "with", length(cases), "cases\n")
