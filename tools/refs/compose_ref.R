#!/usr/bin/env Rscript
# SIL-1001：组合层（patchwork 骨架 / panel 几何对齐）与 patchwork 1.3.2 的对拍夹具。
#
#     pixi run -e refs refs:compose
#
# 产出 `tests/fixtures/composition_r_reference.json`（入库；CI 不装 R）。
#
# 口径：本仓的字体度量与 R 不同，**绝对 pt 不可逐值对拍**。所以夹具记录的是
# 可比较的**关系**，Python 侧断言同一组关系：
#
# - 平铺（`p1 + p2 + p3 + p4 + plot_layout(ncol = 2)`）：同一列 panel 的 x / w
#   相等、同一行 panel 的 y / h 相等；
# - 一列两行（`p1 | p2`）：两个 panel 的 y / h 相等、x 递增；
# - 嵌套（`(p1 | p2) / p3`）：跨嵌套层的 panel **不保证**对齐 —— 上层的两个
#   panel 由内层 layout 分配，与下层的单个 panel 宽度不同（patchwork 官方
#   vignette 的已知行为，SIL-909 实测复现）；
# - 默认网格（`p1 + p2 + p3`，不带 `plot_layout()`）：`wrap_dims()` 的 n2mfrow
#   规则是 `n <= 3` 固定一行，所以三张图是 1×3 而不是 2×2。
#
# panel 矩形从 svglite 的 SVG 里按 `panel.background` 的 fill 颜色读回（pt）。

suppressPackageStartupMessages({
  library(ggplot2)
  library(patchwork)
  library(svglite)
})

json_escape <- function(text) {
  text <- gsub("\\\\", "\\\\\\\\", text)
  gsub('"', '\\\\"', text)
}

to_json <- function(value, indent = 0) {
  pad <- strrep(" ", indent)
  if (is.null(value)) {
    return("null")
  }
  if (is.list(value)) {
    if (!is.null(names(value))) {
      items <- vapply(
        names(value),
        function(key) {
          paste0(strrep(" ", indent + 2), '"', json_escape(key), '": ',
                 to_json(value[[key]], indent + 2))
        },
        character(1)
      )
      return(paste0("{\n", paste(items, collapse = ",\n"), "\n", pad, "}"))
    }
    items <- vapply(value, to_json, character(1), indent = indent + 2)
    return(paste0("[\n", paste(items, collapse = ",\n"), "\n", pad, "]"))
  }
  if (is.character(value)) {
    return(paste0('"', json_escape(value), '"'))
  }
  if (is.logical(value)) {
    return(if (value) "true" else "false")
  }
  if (is.numeric(value)) {
    return(format(value, digits = 15, scientific = FALSE, trim = TRUE))
  }
  paste0('"', json_escape(as.character(value)), '"')
}

outdir <- tempfile("sil1001-")
dir.create(outdir)

d <- mtcars
# 每个面板一个非标准 fill：SVG 会原样写 hex（标准色会被 svglite 换成颜色名）。
mk <- function(y, fill, label = "wt") {
  ggplot(d, aes(wt, y)) +
    geom_point() +
    labs(x = label) +
    theme(panel.background = element_rect(fill = fill, colour = NA))
}

p1 <- mk(d$mpg, "#CC0000", "wt")
p2 <- mk(d$disp, "#00CC00", "a-considerably-longer-x-label")
p3 <- mk(d$hp, "#0000CC", "wt")
p4 <- mk(d$qsec, "#CCCC00", "wt")

panel_rects <- function(file, colours) {
  lines <- readLines(file, warn = FALSE)
  out <- list()
  for (colour in colours) {
    # svglite 把属性写成单引号、颜色写在 style='... fill: #RRGGBB;' 里。
    hits <- grep(paste0("fill: ", colour), lines, value = TRUE)
    hits <- hits[grepl("<rect", hits, fixed = TRUE)]
    for (line in hits) {
      num <- function(attr, default = 0) {
        m <- regmatches(line, regexpr(paste0(attr, "='[0-9.eE+-]+'"), line))
        if (length(m) == 0) {
          return(default)
        }
        as.numeric(sub(paste0(attr, "='([0-9.eE+-]+)'"), "\\1", m))
      }
      translate <- regmatches(line, regexpr("translate\\([0-9.eE+-]+ [0-9.eE+-]+\\)", line))
      dx <- 0
      dy <- 0
      if (length(translate) == 1) {
        parts <- as.numeric(strsplit(gsub("[^0-9.eE+-]+", " ", translate), " +")[[1]])
        parts <- parts[!is.na(parts)]
        dx <- parts[1]
        dy <- parts[2]
      }
      out[[length(out) + 1]] <- list(
        fill = colour,
        x = num("x") + dx,
        y = num("y") + dy,
        w = num("width"),
        h = num("height")
      )
    }
  }
  out
}

colours <- c("#CC0000", "#00CC00", "#0000CC", "#CCCC00")
cases <- list(
  flat_2x2 = list(plot = p1 + p2 + p3 + p4 + plot_layout(ncol = 2), width = 6, height = 6),
  one_by_two = list(plot = p1 | p2, width = 7, height = 5),
  nested = list(plot = (p1 | p2) / p3, width = 6, height = 6),
  # 不带 plot_layout()：patchwork 的默认网格（ggplot2::wrap_dims() / n2mfrow()）
  # 对 3 张图是 1×3（不是「近方形」的 2×2）。
  default_three = list(plot = p1 + p2 + p3, width = 6, height = 6)
)

payload <- list(
  patchwork = as.character(packageVersion("patchwork")),
  ggplot2 = as.character(packageVersion("ggplot2")),
  svglite = as.character(packageVersion("svglite")),
  cases = list()
)
for (name in names(cases)) {
  case <- cases[[name]]
  file <- file.path(outdir, paste0(name, ".svg"))
  svglite(file, width = case$width, height = case$height)
  print(case$plot)
  dev.off()
  payload$cases[[name]] <- list(
    width_in = case$width,
    height_in = case$height,
    panels = panel_rects(file, colours)
  )
}

target <- file.path("tests", "fixtures", "composition_r_reference.json")
writeLines(to_json(payload), target)
cat("wrote", target, "\n")
