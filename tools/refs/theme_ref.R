#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/theme_r_reference.json —— theme 元素解析的 R 侧参考值。
#
#   pixi run -e refs refs:theme
#
# 对 theme_grey() / theme_minimal() / theme_void() 的**每一个**元素跑
# calc_element()，把继承 + rel() + inherit.blank 都交给 ggplot2 4.0.3 算，
# 结果按 ggcore 的规范形式落盘（字号 pt、线宽 mm、颜色 #RRGGBB、边距 pt）。
# Python 侧 `tests/test_theme_r_parity.py` 用同一份口径逐项比对。

library(ggplot2)
library(jsonlite)

out_path <- "tests/fixtures/theme_r_reference.json"

canon_colour <- function(x) {
  if (length(x) == 0L || is.na(x)) {
    return(NULL)
  }
  rgba <- col2rgb(x, alpha = TRUE)
  if (rgba[4L] == 255L) {
    sprintf("#%02X%02X%02X", rgba[1L], rgba[2L], rgba[3L])
  } else {
    sprintf("#%02X%02X%02X%02X", rgba[1L], rgba[2L], rgba[3L], rgba[4L])
  }
}

canon_unit <- function(u) {
  amounts <- as.numeric(u)
  kinds <- as.character(grid::unitType(u))
  list(
    class = "unit",
    amount = I(amounts),
    kind = I(kinds)
  )
}

canon_margin <- function(m) {
  sides <- lapply(seq_len(4L), function(i) {
    side <- m[i]
    if (is.na(side)) {
      return(NULL)
    }
    list(amount = as.numeric(side), kind = as.character(grid::unitType(side)))
  })
  list(class = "margin", sides = sides)
}

prop_list <- function(props) {
  lapply(props, function(value) {
    if (is.null(value) || length(value) == 0L) {
      return(NULL)
    }
    if (length(value) == 1L && is.atomic(value) && is.na(value)) {
      return(NULL)
    }
    if (grid::is.unit(value) && is_margin(value)) {
      return(canon_margin(value))
    }
    if (grid::is.unit(value)) {
      return(canon_unit(value))
    }
    if (is.character(value) && length(value) == 1L) {
      return(value)
    }
    if (is.logical(value) && length(value) == 1L) {
      return(value)
    }
    if (is.numeric(value) && length(value) == 1L) {
      return(value)
    }
    NULL
  })
}

describe_element <- function(el) {
  if (is_theme_element(el, "blank")) {
    return(list(class = "blank"))
  }
  if (!is_theme_element(el)) {
    if (inherits(el, "rel")) {
      return(list(class = "rel", mult = unclass(el)))
    }
    if (grid::is.unit(el) && is_margin(el)) {
      return(canon_margin(el))
    }
    if (grid::is.unit(el)) {
      return(canon_unit(el))
    }
    if (is.character(el) || is.logical(el) || is.numeric(el)) {
      return(list(class = "value", value = unname(el)))
    }
    return(NULL)
  }
  props <- S7::props(el)
  if (is_theme_element(el, "geom") && !is.null(props$fontsize)) {
    props$fontsize <- props$fontsize * ggplot2:::.pt
  }
  colour_names <- c("colour", "fill", "arrow.fill", "ink", "paper", "accent")
  for (name in intersect(colour_names, names(props))) {
    if (!is.null(props[[name]])) {
      props[[name]] <- canon_colour(props[[name]])
    }
  }
  out <- prop_list(props)
  kind <- c("text", "line", "rect", "polygon", "point", "geom")
  kind <- kind[vapply(kind, function(k) is_theme_element(el, k), logical(1))]
  c(list(class = kind[[1L]]), out)
}

themes <- list(
  grey = theme_grey(),
  minimal = theme_minimal(),
  void = theme_void()
)
element_names <- names(ggplot2:::get_element_tree())
element_names <- element_names[!grepl("^palette\\.", element_names)]

result <- lapply(themes, function(t) {
  stats::setNames(
    lapply(element_names, function(name) describe_element(calc_element(name, t))),
    element_names
  )
})

payload <- list(
  r_version = R.version.string,
  ggplot2_version = as.character(packageVersion("ggplot2")),
  generated_by = "tools/refs/theme_ref.R",
  themes = result
)

writeLines(
  jsonlite::toJSON(payload, auto_unbox = TRUE, pretty = TRUE, digits = NA, null = "null"),
  out_path
)
cat("wrote", out_path, "\n")
