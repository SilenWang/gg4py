#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/text_r_reference.json —— 文字度量对拍的 R 侧参考值。
#
#   pixi run -e refs refs:text
#
# 固定 svglite(4 × 3 in) + UTF-8 locale，逐个 (字族, font, 字号) 量
# `grid::stringWidth` / `stringHeight`。单位是 1/72 in（SVG 用户单位 = pt）。
# 逐条记录，Python 侧 `ggskia.text.ShaperMetrics` 用同一串、同一字号复量。
#
# 覆盖三件事（issue 的验收）：
# 1. 逐行宽度：中文、拉丁、中英混排各一条；
# 2. 真实字面：Noto Sans 的 regular / bold / italic / bold-italic；
# 3. 多行：每行单独量 + 整块 stringHeight（行距 = (height - 单行)/ (n-1)）。

suppressPackageStartupMessages({
  library(grid)
  library(svglite)
})

if (!isTRUE(l10n_info()[["UTF-8"]])) {
  stop("R 不在 UTF-8 locale 下：用 `LC_ALL=C.UTF-8 LANG=C.UTF-8` 重跑")
}

out_path <- "tests/fixtures/text_r_reference.json"

# ---------------------------------------------------------------------------
# 极简 JSON 输出（不引入 jsonlite，与 tools/refs/units_ref.R 同一份）
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
  if (is.null(x)) {
    return("null")
  }
  if (is.logical(x) && length(x) == 1L) {
    if (is.na(x)) {
      return("null")
    }
    return(if (isTRUE(x)) "true" else "false")
  }
  if (is.numeric(x) && length(x) == 1L) {
    return(fmt_num(x))
  }
  if (is.character(x) && length(x) == 1L) {
    return(json_escape(x))
  }
  if (is.list(x)) {
    nm <- names(x)
    if (!is.null(nm)) {
      if (length(x) == 0L) {
        return("{}")
      }
      items <- vapply(seq_along(x), function(i) {
        paste0(pad2, json_escape(nm[[i]]), ": ", to_json(x[[i]], indent + 1L))
      }, character(1))
      return(paste0("{\n", paste(items, collapse = ",\n"), "\n", pad, "}"))
    }
    if (length(x) == 0L) {
      return("[]")
    }
    items <- vapply(x, function(el) paste0(pad2, to_json(el, indent + 1L)), character(1))
    return(paste0("[\n", paste(items, collapse = ",\n"), "\n", pad, "]"))
  }
  if (length(x) == 0L) {
    return("[]")
  }
  items <- vapply(seq_along(x), function(i) {
    paste0(pad2, to_json(x[[i]], indent + 1L))
  }, character(1))
  paste0("[\n", paste(items, collapse = ",\n"), "\n", pad, "]")
}

# ---------------------------------------------------------------------------
# 量
# ---------------------------------------------------------------------------

measure <- function(text, family, font, size) {
  pushViewport(viewport(gp = gpar(fontsize = size, fontfamily = family, font = font)))
  width <- convertWidth(stringWidth(text), "points", valueOnly = TRUE)
  height <- convertHeight(stringHeight(text), "points", valueOnly = TRUE)
  popViewport()
  list(width = width, height = height)
}

svglite(tempfile(fileext = ".svg"), width = 4, height = 3)

samples <- list()
lines <- c("\u4e2d\u6587\u6807\u7b7e\u5bbd\u5ea6", "Latin width sample",
           "\u4e2d\u6587 mixed Latin \u6df7\u6392")
plan <- list(
  list(family = "Noto Sans CJK SC", font = 1L),
  list(family = "Noto Sans CJK SC", font = 2L),
  list(family = "Noto Sans", font = 1L),
  list(family = "Noto Sans", font = 2L),
  list(family = "Noto Sans", font = 3L),
  list(family = "Noto Sans", font = 4L)
)
for (item in plan) {
  for (size in c(10, 12)) {
    for (text in lines) {
      values <- measure(text, item$family, item$font, size)
      samples[[length(samples) + 1L]] <- list(
        family = item$family,
        font = item$font,
        size = size,
        text = text,
        width = values$width,
        height = values$height
      )
    }
  }
}

multiline <- list()
multi_plan <- list(
  list(family = "Noto Sans CJK SC", font = 1L, size = 10,
       text = "\u591a\u884c\u6587\u672c\u7b2c\u4e00\u884c\n\u7b2c\u4e8c\u884c mixed Latin \u6587\u5b57\n\u7b2c\u4e09\u884c"),
  list(family = "Noto Sans", font = 1L, size = 12, text = "one\ntwo\nthree"),
  list(family = "Noto Sans", font = 2L, size = 12, text = "one\ntwo\nthree")
)
for (item in multi_plan) {
  parts <- strsplit(item$text, "\n", fixed = TRUE)[[1]]
  values <- measure(item$text, item$family, item$font, item$size)
  single <- measure(parts[[1]], item$family, item$font, item$size)
  widths <- vapply(parts, function(part) {
    measure(part, item$family, item$font, item$size)$width
  }, numeric(1))
  multiline[[length(multiline) + 1L]] <- list(
    family = item$family,
    font = item$font,
    size = item$size,
    text = item$text,
    lines = as.list(parts),
    line_widths = as.list(unname(widths)),
    width = values$width,
    height = values$height,
    line_pitch = (values$height - single$height) / (length(parts) - 1L)
  )
}

dev.off()

document <- list(
  locale = "C.UTF-8",
  device = list(kind = "svglite", width_in = 4, height_in = 3, units = "pt@72dpi"),
  samples = samples,
  multiline = multiline
)

dir.create(dirname(out_path), recursive = TRUE, showWarnings = FALSE)
writeLines(to_json(document), out_path)
cat(sprintf("wrote %s (%d samples, %d multiline)\n", out_path, length(samples), length(multiline)))
