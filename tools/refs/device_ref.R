#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/device_r_reference.json —— 设备侧曲线求值的 R 侧参考值。
#
#   pixi run -e refs refs:device
#
# 两条链路各一条：
#
# - `xspline`：`xsplineGrob()` → `grid:::xsplinePoints()`，即 R 的
#   `src/main/xspline.c`（Xfig X-spline）采样出来的折线；
# - `curve`：`curveGrob()` → `grid:::calcCurveGrob()`（就是 `grid:::curveGrob`
#   的 makeContent）→ 子 xspline 的 `xsplinePoints()`。
#
# 坐标一律英寸，页面 7×7 in（步长公式要用页面对角线，所以页面尺寸也写进夹具）；
# Python 侧乘 72 折成 pt，再和 `ggskia.curves` 的输出逐点比。
# 口径见 docs/notes/device.md。

library(grid)

out_path <- "tests/fixtures/device_r_reference.json"
width_in <- 7
height_in <- 7

json_escape <- function(text) {
  text <- gsub("\\", "\\\\", text, fixed = TRUE)
  text <- gsub("\"", "\\\"", text, fixed = TRUE)
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

points_json <- function(x, y) {
  lapply(seq_along(x), function(i) list(x[[i]], y[[i]]))
}

as_pairs <- function(trace) {
  points_json(as.numeric(trace$x), as.numeric(trace$y))
}

# ---------------------------------------------------------------------------
# xspline 用例
# ---------------------------------------------------------------------------

xspline_cases <- list(
  list(id = "xspline-open-4", x = c(1, 2.5, 4, 5.5), y = c(1.5, 3, 1, 2.5),
       shape = 0.5, open = TRUE),
  list(id = "xspline-open-5-negative", x = c(1, 2, 3, 4, 5), y = c(1, 3, 1, 3, 1),
       shape = -0.5, open = TRUE),
  list(id = "xspline-closed-5", x = c(2, 4, 5, 3.5, 1.5), y = c(2, 2, 4, 5.5, 4),
       shape = 0.5, open = FALSE),
  list(id = "xspline-open-3-round", x = c(1, 3, 5), y = c(1, 4, 1),
       shape = 1, open = TRUE),
  list(id = "xspline-open-6-linear", x = c(1, 2, 3, 4, 5, 6), y = c(2, 2.5, 2, 2.5, 2, 2.5),
       shape = 0, open = TRUE),
  list(id = "xspline-open-2", x = c(1, 5), y = c(1, 3),
       shape = 0.5, open = TRUE),
  list(id = "xspline-closed-4-staircase", x = c(2, 5, 5, 2), y = c(2, 2, 5, 5),
       shape = -1, open = FALSE),
  list(id = "xspline-open-mixed-shapes",
       x = c(1, 2.2, 3.1, 4.4, 5.2, 6), y = c(2, 3.5, 1.2, 2.8, 1.5, 3.2),
       shape = c(1, 0.5, -0.5, 0.7, 0, 0.3), open = TRUE)
)

run_xspline <- function(case) {
  shapes <- rep(case$shape, length.out = length(case$x))
  grob <- xsplineGrob(
    x = unit(case$x, "inches"), y = unit(case$y, "inches"),
    shape = shapes,
    id = rep(1L, length(case$x)), open = case$open
  )
  trace <- grid:::xsplinePoints(grob)
  list(
    id = case$id,
    points = points_json(case$x, case$y),
    shapes = shapes,
    open = case$open,
    polyline = as_pairs(trace)
  )
}

# ---------------------------------------------------------------------------
# curve 用例
# ---------------------------------------------------------------------------

curve_cases <- list(
  list(id = "curve-square-default", x1 = 1, y1 = 1, x2 = 4, y2 = 3,
       curvature = 1, angle = 90, ncp = 1, shape = 0.5, square = TRUE, inflect = FALSE,
       open = TRUE),
  list(id = "curve-square-ncp2", x1 = 1, y1 = 1, x2 = 4, y2 = 3,
       curvature = 1, angle = 90, ncp = 2, shape = 0.5, square = TRUE, inflect = FALSE,
       open = TRUE),
  list(id = "curve-curved-angle90", x1 = 1, y1 = 1, x2 = 4, y2 = 3,
       curvature = 1, angle = 90, ncp = 1, shape = 0.5, square = FALSE, inflect = FALSE,
       open = TRUE),
  list(id = "curve-angle60-negative", x1 = 1, y1 = 1, x2 = 4, y2 = 3,
       curvature = -1, angle = 60, ncp = 1, shape = 0.5, square = FALSE, inflect = FALSE,
       open = TRUE),
  list(id = "curve-angle45-curvature2", x1 = 4, y1 = 1, x2 = 1, y2 = 4,
       curvature = 2, angle = 45, ncp = 1, shape = 0.5, square = FALSE, inflect = FALSE,
       open = TRUE),
  list(id = "curve-inflect", x1 = 1, y1 = 1, x2 = 5, y2 = 3,
       curvature = 1, angle = 90, ncp = 1, shape = 0.5, square = FALSE, inflect = TRUE,
       open = TRUE),
  list(id = "curve-inflect-square", x1 = 1, y1 = 1, x2 = 5, y2 = 4,
       curvature = 1, angle = 90, ncp = 1, shape = 0.5, square = TRUE, inflect = TRUE,
       open = TRUE),
  list(id = "curve-closed", x1 = 2, y1 = 2, x2 = 5, y2 = 6,
       curvature = 1, angle = 90, ncp = 2, shape = 0.5, square = FALSE, inflect = FALSE,
       open = FALSE),
  list(id = "curve-aligned-straight", x1 = 2, y1 = 2, x2 = 2, y2 = 5,
       curvature = 1, angle = 90, ncp = 1, shape = 0.5, square = TRUE, inflect = FALSE,
       open = TRUE)
)

run_curve <- function(case) {
  grob <- curveGrob(
    x1 = unit(case$x1, "inches"), y1 = unit(case$y1, "inches"),
    x2 = unit(case$x2, "inches"), y2 = unit(case$y2, "inches"),
    curvature = case$curvature, angle = case$angle, ncp = case$ncp,
    shape = case$shape, square = case$square, inflect = case$inflect, open = case$open
  )
  content <- grid:::calcCurveGrob(grob, FALSE)
  child <- content$children[[length(content$children)]]
  if (is.null(child)) {
    polyline <- list(list(case$x1, case$y1), list(case$x2, case$y2))
  } else if (inherits(child, "xspline")) {
    polyline <- as_pairs(grid:::xsplinePoints(child))
  } else {
    polyline <- list(list(case$x1, case$y1), list(case$x2, case$y2))
  }
  list(
    id = case$id,
    ends = c(case$x1, case$y1, case$x2, case$y2),
    curvature = case$curvature, angle = case$angle, ncp = case$ncp,
    shape = case$shape, square = case$square, inflect = case$inflect, open = case$open,
    polyline = polyline
  )
}

pdf(NULL, width = width_in, height = height_in)
xsplines <- lapply(xspline_cases, run_xspline)
curves <- lapply(curve_cases, run_curve)
invisible(dev.off())

document <- list(
  r_version = R.version.string,
  generated_by = "tools/refs/device_ref.R",
  page_in = c(width_in, height_in),
  units = "inches",
  xspline = xsplines,
  curve = curves
)

dir.create(dirname(out_path), showWarnings = FALSE, recursive = TRUE)
writeLines(to_json(document), out_path)
cat("wrote ", out_path, " (", length(xsplines), " xspline + ", length(curves), " curve cases)\n",
    sep = "")
