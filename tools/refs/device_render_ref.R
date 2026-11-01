#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/device_render_r/ —— 设备级（真渲染）R 侧参考值。
#
#   pixi run -e refs refs:device-render
#
# `tools/refs/device_ref.R` 钉的是**纯函数**：把夹具喂给 `curve_points()` 逐点比。
# 那条对拍对「函数对、集成错」是瞎的——`_draw_curve` 漏掉 y 翻转时它全绿
# （SIL-636）。这里换成设备级：同一张 4×3 in / 150 ppi 的页面上，R 真画一遍，
# 产物是
#
# - `<id>.png`：R 的渲染结果（网格线，白底），Python 侧渲染同一条曲线比墨迹 IoU；
# - `<id>.svg` 不需要：折线从 `index.json` 的 `polyline` 读——那是 R **设备坐标**
#   （pt，y 向下）里的采样点，Python 侧从自己吐的 SVG 的 `d` 里解析出来逐点比。
#
# 用例刻意只有一条图元：IoU 没有别的墨迹干扰，折线也就是那一条。

library(grid)

out_dir <- "tests/fixtures/device_render_r"
width_in <- 4
height_in <- 3
res <- 150
pt_per_in <- 72

json_escape <- function(text) {
  text <- gsub("\\", "\\\\", text, fixed = TRUE)
  text <- gsub("\"", "\\\"", text, fixed = TRUE)
  paste0("\"", text, "\"")
}

fmt_num <- function(value) sprintf("%.10g", value)

to_json <- function(x, indent = 0L) {
  pad <- strrep("  ", indent)
  pad2 <- strrep("  ", indent + 1L)
  if (is.null(x)) return("null")
  if (is.logical(x) && length(x) == 1L) return(if (isTRUE(x)) "true" else "false")
  if (is.numeric(x) && length(x) == 1L) return(fmt_num(x))
  if (is.numeric(x)) return(to_json(as.list(x), indent))
  if (is.character(x) && length(x) == 1L) return(json_escape(x))
  if (is.list(x)) {
    nm <- names(x)
    if (!is.null(nm) && all(nzchar(nm))) {
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
  stop("cannot serialise: ", paste(class(x), collapse = "/"))
}

# `grid:::xsplinePoints()` 返回**英寸**（y 向上，设备原点在左下）→ 设备 pt（y 向下，
# 原点在左上）。页面 pt 尺寸与 Python 侧一致。
to_device_pt <- function(x_in, y_in) {
  list(
    x = as.numeric(x_in) * pt_per_in,
    y = (height_in - as.numeric(y_in)) * pt_per_in
  )
}

points_json <- function(px, py) {
  lapply(seq_along(px), function(i) list(px[[i]], py[[i]]))
}

new_page <- function(id) {
  png(file.path(out_dir, paste0(id, ".png")),
      width = width_in, height = height_in, units = "in", res = res, bg = "white")
  grid.newpage()
}

curve_case <- function(id, x1, y1, x2, y2, ...) {
  grob <- curveGrob(
    x1 = unit(x1, "npc"), y1 = unit(y1, "npc"),
    x2 = unit(x2, "npc"), y2 = unit(y2, "npc"),
    gp = gpar(col = "black", lwd = 2.5), ...
  )
  new_page(id)
  grid.draw(grob)
  content <- grid:::calcCurveGrob(grob, FALSE)
  child <- content$children[[length(content$children)]]
  polyline <- grid:::xsplinePoints(child)
  device <- to_device_pt(polyline$x, polyline$y)
  invisible(dev.off())
  list(
    id = id,
    kind = "curve",
    params = list(x1 = x1, y1 = y1, x2 = x2, y2 = y2),
    polyline = points_json(device$x, device$y)
  )
}

xspline_case <- function(id, x, y, shape, open = TRUE) {
  grob <- xsplineGrob(
    x = unit(x, "npc"), y = unit(y, "npc"), shape = shape, open = open,
    gp = gpar(col = "black", lwd = 2.5)
  )
  new_page(id)
  grid.draw(grob)
  polyline <- grid:::xsplinePoints(grob)
  device <- to_device_pt(polyline$x, polyline$y)
  invisible(dev.off())
  list(
    id = id,
    kind = "xspline",
    params = list(x = x, y = y, shape = shape, open = open),
    polyline = points_json(device$x, device$y)
  )
}

line_case <- function(id, lwd) {
  new_page(id)
  grid.segments(unit(0.1, "npc"), unit(0.5, "npc"),
                unit(0.9, "npc"), unit(0.5, "npc"),
                gp = gpar(col = "black", lwd = lwd, lineend = "butt"))
  invisible(dev.off())
  list(id = id, kind = "segments", params = list(lwd = lwd))
}

dot_case <- function(id, pch, cex = 1) {
  new_page(id)
  grid.points(unit(0.5, "npc"), unit(0.5, "npc"), pch = pch,
              size = unit(cex, "char"), gp = gpar(col = "black"))
  invisible(dev.off())
  list(id = id, kind = "points", params = list(pch = pch, cex = cex))
}

dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

cases <- list(
  curve_case("curve-square-angle90", 0.1, 0.75, 0.5, 0.5,
             square = TRUE, angle = 90),
  curve_case("curve-curved-angle45", 0.1, 0.75, 0.5, 0.5,
             square = FALSE, angle = 45, curvature = 0.6),
  xspline_case("xspline-open-4", c(0.1, 0.35, 0.6, 0.85), c(0.2, 0.8, 0.25, 0.75), 0.5),
  line_case("lwd-6-line", 6),
  dot_case("pch-46-dot", 46)
)

document <- list(
  r_version = R.version.string,
  generated_by = "tools/refs/device_render_ref.R",
  page_in = c(width_in, height_in),
  res = res,
  units = "pt, y down (device space)",
  cases = cases
)

writeLines(to_json(document), file.path(out_dir, "index.json"))
cat("wrote ", out_dir, " (", length(cases), " rendered cases)\n", sep = "")
