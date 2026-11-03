#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/theme_r_reference.json —— theme 元素解析的 R 侧参考值。
#
#   pixi run -e refs refs:theme
#
# 对 theme_grey() / theme_bw() / theme_minimal() / theme_void() 的**每一个**
# 元素跑 calc_element()，把继承 + rel() + inherit.blank 都交给 ggplot2 4.0.3
# 算，结果按 ggcore 的规范形式落盘（字号 pt、线宽 mm、颜色 #RRGGBB、边距 pt）。
# `bw` 是 grey 的白底变体（minimal 的底），单独列一套才能守住它的数值漂移。
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

# --- 10 个主题名：9 套完整主题 + `theme_gray()` 的美式拼写别名 -------------
# `gray` 与 `grey` 是同一套数值，单独列一套才能证明别名没有漂移。
themes <- list(
  grey = theme_grey(),
  gray = theme_gray(),
  bw = theme_bw(),
  classic = theme_classic(),
  light = theme_light(),
  dark = theme_dark(),
  linedraw = theme_linedraw(),
  minimal = theme_minimal(),
  test = theme_test(),
  void = theme_void()
)

# --- theme_sub_*（4.0）：前缀简写 → 元素名 ---------------------------------
# 每一条都挂在 theme_grey() 上，只覆盖各自子树；`calc_element()` 会把没覆盖
# 的元素照常算出来，所以下面 146 个元素逐个比对时，两边看到的都是同一棵树的
# 解析值。参数取值刻意覆盖四种元素类型（text / line / rect / unit / margin /
# 标量），确保 `theme_sub_*` 的「参数名 → 元素名」映射没有拼错。
subthemes <- list(
  sub_axis = theme_grey() + theme_sub_axis(
    title = element_text(size = rel(1.1), colour = "red"),
    text = element_text(colour = "blue", size = 9),
    ticks = element_line(colour = "green"),
    ticks.length = unit(3, "pt"),
    line = element_line(colour = "black", linewidth = 0.4),
    minor.ticks.length = rel(0.6)
  ),
  sub_axis_x = theme_grey() + theme_sub_axis_x(
    title = element_text(hjust = 1),
    text = element_text(vjust = 0),
    ticks = element_line(colour = "grey40"),
    ticks.length = unit(4, "pt"),
    line = element_line(lineend = "square"),
    minor.ticks.length = rel(0.5)
  ),
  sub_axis_y = theme_grey() + theme_sub_axis_y(
    title = element_text(angle = 0),
    text = element_text(hjust = 0.5),
    ticks = element_line(linetype = "dashed"),
    ticks.length = unit(5, "pt"),
    line = element_line(linejoin = "mitre"),
    minor.ticks.length = rel(0.4)
  ),
  sub_axis_top = theme_grey() + theme_sub_axis_top(
    title = element_text(colour = "grey10"),
    text = element_text(size = rel(0.6)),
    ticks = element_line(colour = "grey30"),
    ticks.length = unit(2, "pt"),
    line = element_line(colour = "grey50"),
    minor.ticks = element_line(colour = "grey70"),
    minor.ticks.length = rel(0.3)
  ),
  sub_axis_bottom = theme_grey() + theme_sub_axis_bottom(
    title = element_text(vjust = 0),
    text = element_text(angle = 30),
    ticks = element_line(colour = "grey20"),
    ticks.length = unit(6, "pt"),
    line = element_line(linewidth = 0.3),
    minor.ticks = element_line(linetype = "dotted"),
    minor.ticks.length = unit(1.5, "pt")
  ),
  sub_axis_left = theme_grey() + theme_sub_axis_left(
    title = element_text(size = rel(0.9)),
    text = element_text(colour = "grey40"),
    ticks = element_line(colour = "grey60"),
    ticks.length = unit(2.5, "pt"),
    line = element_line(colour = "grey80"),
    minor.ticks = element_line(colour = "grey85"),
    minor.ticks.length = rel(0.2)
  ),
  sub_axis_right = theme_grey() + theme_sub_axis_right(
    title = element_text(angle = -90),
    text = element_text(hjust = 1),
    ticks = element_line(colour = "grey15"),
    ticks.length = unit(3.5, "pt"),
    line = element_line(colour = "grey25"),
    minor.ticks = element_blank(),
    minor.ticks.length = unit(1, "pt")
  ),
  sub_legend = theme_grey() + theme_sub_legend(
    text = element_text(colour = "red", size = rel(0.7)),
    text.position = "left",
    title = element_text(colour = "blue"),
    title.position = "top",
    background = element_rect(fill = "grey95"),
    frame = element_blank(),
    ticks = element_line(colour = "black"),
    ticks.length = rel(0.3),
    axis.line = element_line(colour = "black", linewidth = 0.3),
    spacing = rel(3),
    spacing.x = unit(2, "pt"),
    spacing.y = unit(3, "pt"),
    margin = margin(1, 2, 3, 4),
    key = element_rect(fill = "white"),
    key.size = unit(1.5, "cm"),
    key.height = unit(0.8, "cm"),
    key.width = unit(0.9, "cm"),
    key.spacing = unit(2, "pt"),
    key.spacing.x = unit(1, "pt"),
    key.spacing.y = unit(1.5, "pt"),
    key.justification = "left",
    byrow = TRUE,
    position = "bottom",
    direction = "horizontal",
    location = "top",
    justification = 0,
    justification.top = 0,
    justification.bottom = 1,
    justification.left = 0,
    justification.right = 1,
    box = "vertical",
    box.just = "left",
    box.margin = margin(2, 2, 2, 2),
    box.background = element_rect(fill = "grey90"),
    box.spacing = unit(4, "pt")
  ),
  sub_panel = theme_grey() + theme_sub_panel(
    background = element_rect(fill = "grey98"),
    border = element_rect(colour = "grey20"),
    widths = unit(1, "null"),
    heights = unit(1, "null"),
    spacing = unit(4, "pt"),
    spacing.x = unit(3, "pt"),
    spacing.y = unit(5, "pt"),
    grid = element_line(colour = "grey90"),
    grid.major = element_line(linewidth = rel(0.4)),
    grid.minor = element_line(linewidth = rel(0.2)),
    grid.major.x = element_line(linetype = "dashed"),
    grid.major.y = element_line(linetype = "dotted"),
    grid.minor.x = element_line(colour = "grey95"),
    grid.minor.y = element_line(colour = "grey96"),
    ontop = TRUE
  ),
  sub_plot = theme_grey() + theme_sub_plot(
    background = element_rect(fill = "white", colour = NA),
    title = element_text(hjust = 0.5),
    title.position = "plot",
    subtitle = element_text(colour = "grey30"),
    caption = element_text(face = "italic"),
    caption.position = "plot",
    tag = element_text(size = rel(1.5)),
    tag.position = "bottomright",
    tag.location = "plot",
    margin = margin(6, 6, 6, 6)
  ),
  sub_strip = theme_grey() + theme_sub_strip(
    background = element_rect(fill = "grey80"),
    background.x = element_rect(fill = "grey70"),
    background.y = element_rect(fill = "grey60"),
    clip = "off",
    placement = "outside",
    text = element_text(colour = "black"),
    text.x = element_text(angle = 45),
    text.x.bottom = element_text(angle = 10),
    text.x.top = element_text(angle = 20),
    text.y = element_text(angle = -45),
    text.y.left = element_text(angle = 30),
    text.y.right = element_text(angle = -30),
    switch.pad.grid = unit(4, "pt"),
    switch.pad.wrap = unit(5, "pt")
  )
)

themes <- c(themes, subthemes)
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
