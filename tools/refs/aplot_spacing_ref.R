#!/usr/bin/env Rscript
# SIL-1004：aplot 0.3.2 panel spacing 与 insert_* 语法糖的结构对拍。
#
#     pixi run -e refs refs:aplot-spacing
#
# 产出 `tests/fixtures/aplot_spacing_r_reference.json`（入库；CI 不装 R）。
#
# 口径：
# - `panel_spacing`：aplot `.compute_panel_margins()` 是纯函数，直接按 layout
#   记录每格的 `(t, r, b, l)` 毫米值；另外渲染 spacing = 0 / 10 的 2×2，记录
#   panel 矩形，让 Python 侧比较「内部边 +10mm、外沿 +5mm」的增量（字体无关）。
# - `insert_*`：记录 aplot 自己的 layout 矩阵、width / height 权重与 main
#   row / col（aplot 的真实 spec），外加渲染后的 panel 矩形供关系断言。

suppressPackageStartupMessages({
  library(aplot)
  library(ggplot2)
  library(grid)
  library(patchwork)
  library(svglite)
})
pdf(NULL)

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
          paste0(
            strrep(" ", indent + 2), '"', json_escape(key), '": ',
            to_json(value[[key]], indent + 2)
          )
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
    if (length(value) != 1) {
      return(to_json(as.list(value), indent))
    }
    if (is.na(value)) {
      return("null")
    }
    return(format(value, digits = 15, scientific = FALSE, trim = TRUE))
  }
  paste0('"', json_escape(as.character(value)), '"')
}

layout_json <- function(layout) {
  lapply(seq_len(nrow(layout)), function(i) {
    lapply(seq_len(ncol(layout)), function(j) {
      value <- layout[i, j]
      if (is.na(value)) NULL else as.numeric(value)
    })
  })
}

margin_json <- function(margin) {
  if (is.null(margin)) {
    return(NULL)
  }
  list(
    t = as.numeric(margin[1]),
    r = as.numeric(margin[2]),
    b = as.numeric(margin[3]),
    l = as.numeric(margin[4]),
    unit = grid::unitType(margin[1])
  )
}

spacing_case <- function(layout, spacing) {
  margins <- aplot:::.compute_panel_margins(layout, spacing)
  list(
    spacing = spacing,
    layout = layout_json(layout),
    margins = lapply(margins, margin_json)
  )
}

outdir <- tempfile("sil1004-")
dir.create(outdir)

d <- mtcars
mk <- function(y, fill) {
  ggplot(d, aes(wt, y)) +
    geom_point() +
    theme(panel.background = element_rect(fill = fill, colour = NA))
}

colours <- c("#CC0000", "#00CC00", "#0000CC", "#CCCC00")
p1 <- mk(d$mpg, colours[1])
p2 <- mk(d$disp, colours[2])
p3 <- mk(d$hp, colours[3])
p4 <- mk(d$qsec, colours[4])

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

render_panels <- function(grob, name, width = 7, height = 5) {
  file <- file.path(outdir, paste0(name, ".svg"))
  svglite(file, width = width, height = height)
  grid::grid.newpage()
  grid::grid.draw(grob)
  dev.off()
  panel_rects(file, colours)
}

# ---------------------------------------------------------------------------
# panel spacing：aplot 的纯函数口径 + 渲染增量
# ---------------------------------------------------------------------------
grid_2x2 <- matrix(as.numeric(1:4), nrow = 2, ncol = 2, byrow = TRUE)
row_1x3 <- matrix(as.numeric(1:3), nrow = 1, ncol = 3)
# insert_left 造出来的洞：id 3 在左上，id 1 右上，左下是 NA，id 2 右下。
hole_left <- matrix(c(3, 1, NA, 2), nrow = 2, ncol = 2, byrow = TRUE)

spacing <- list(
  grid_2x2_10 = spacing_case(grid_2x2, 10),
  row_1x3_10 = spacing_case(row_1x3, 10),
  hole_left_10 = spacing_case(hole_left, 10),
  grid_2x2_zero = spacing_case(grid_2x2, 0),
  grid_2x2_asis = spacing_case(grid_2x2, "asis")
)

# aplot 对象本身：给它一个 2×2 layout（insert_* 只能长出 L 形，这里按 aplot 的
# 对象字段手工搭，测试的仍然是 as.patchwork() 的 spacing 应用）。
grid_aplot <- function(spacing_value) {
  x <- aplot:::as.aplot(p1)
  x$plotlist <- list(p1, p2, p3, p4)
  x$n <- 4
  x$layout <- grid_2x2
  x$width <- c(1, 1)
  x$height <- c(1, 1)
  x$spacing <- spacing_value
  x
}
spacing_panels <- list(
  zero = render_panels(patchworkGrob(as.patchwork(grid_aplot(0))), "spacing-zero"),
  ten = render_panels(patchworkGrob(as.patchwork(grid_aplot(10))), "spacing-ten")
)

# ---------------------------------------------------------------------------
# insert_*：aplot 的 layout / width / height 真值 + 渲染 panel
# ---------------------------------------------------------------------------
insert_case <- function(x, name, plot) {
  list(
    layout = layout_json(x$layout),
    width = as.numeric(x$width),
    height = as.numeric(x$height),
    main_row = as.numeric(x$main_row),
    main_col = as.numeric(x$main_col),
    panels = render_panels(plot, name)
  )
}

inserts <- list()

base <- aplot:::as.aplot(p1)
inserts$left_single_w2 <- insert_case(
  insert_left(base, p2, width = 2), "insert-left-w2",
  patchworkGrob(as.patchwork(insert_left(base, p2, width = 2)))
)
inserts$right_single_w3 <- insert_case(
  insert_right(base, p2, width = 3), "insert-right-w3",
  patchworkGrob(as.patchwork(insert_right(base, p2, width = 3)))
)
inserts$top_single_h2 <- insert_case(
  insert_top(base, p2, height = 2), "insert-top-h2",
  patchworkGrob(as.patchwork(insert_top(base, p2, height = 2)))
)
inserts$bottom_single_h2 <- insert_case(
  insert_bottom(base, p2, height = 2), "insert-bottom-h2",
  patchworkGrob(as.patchwork(insert_bottom(base, p2, height = 2)))
)

two_rows <- insert_bottom(aplot:::as.aplot(p1), p2)
inserts$left_two_rows <- insert_case(
  insert_left(two_rows, p3, width = 1), "insert-left-two-rows",
  patchworkGrob(as.patchwork(insert_left(two_rows, p3, width = 1)))
)

two_cols <- insert_right(aplot:::as.aplot(p1), p2)
inserts$top_two_cols <- insert_case(
  insert_top(two_cols, p3, height = 2), "insert-top-two-cols",
  patchworkGrob(as.patchwork(insert_top(two_cols, p3, height = 2)))
)

inserts$left_then_bottom <- local({
  x <- insert_left(aplot:::as.aplot(p1), p2, width = 2)
  x <- insert_bottom(x, p3, height = 3)
  insert_case(x, "insert-left-bottom", patchworkGrob(as.patchwork(x)))
})

inserts$right_then_top <- local({
  x <- insert_right(aplot:::as.aplot(p1), p2, width = 2)
  x <- insert_top(x, p3, height = 3)
  insert_case(x, "insert-right-top", patchworkGrob(as.patchwork(x)))
})

payload <- list(
  aplot = as.character(packageVersion("aplot")),
  patchwork = as.character(packageVersion("patchwork")),
  ggplot2 = as.character(packageVersion("ggplot2")),
  svglite = as.character(packageVersion("svglite")),
  spacing = spacing,
  spacing_panels = spacing_panels,
  inserts = inserts
)

target <- file.path("tests", "fixtures", "aplot_spacing_r_reference.json")
writeLines(to_json(payload), target)
cat("wrote", target, "\n")
