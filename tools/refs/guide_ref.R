#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/guide_r_reference.json —— guide（M1-11）的 R 侧参考值。
#
#   pixi run -e refs refs:guide
#
# 8 个 case，全部钉 ggplot2 4.0.3：
#
#   1. legend_colour_discrete   colour 映射离散变量（单图例）
#   2. legend_colour_fill       colour + fill 是**不同变量** → 两张图例竖排
#   3. legend_merged            colour + shape 映射**同一变量** → 合并成一张
#   4. colourbar                连续 colour → 色条 + 断点 / 标签
#   5. axis_continuous          连续 x / y：断点、标签、轴行列尺寸
#   6. axis_discrete            离散 x：断点 / 标签 / 轴行高
#   7. axis_log10               scale_x_log10：断点在变换后的空间
#   8. theme_void               轴消失；图例**仍然保留**（4.0.3 的行为）
#
# 记录两类东西：
#
#   - `ggplot_build(p)$layout$panel_params[[1]]$x/y` 的 `get_breaks()` /
#     `get_labels()` 与 `x.range` / `y.range`（Tick 位置在 Python 侧按同一公式算）；
#   - `ggplotGrob(p)` 画在 7×7in 的 pdf(NULL) 上以后，按 layout 名字读回的行高 /
#     列宽（cm）：axis-l / axis-b / ylab-l / xlab-b / title / guide-box-right，
#     以及每张图例 gtable 自己的宽高。量法与 tools/refs/gtable_ref.R 一致
#     （draw 之后 convertWidth/convertHeight，读 grid 真正分配出来的尺寸）。
#
# 图例的键（`.value` / `.label`）走 4.0.3 的 `get_guide_data()`，它把合并后的
# guide 的键值一并给出（colour + shape 同变量时会同时有两列）。

suppressPackageStartupMessages({
  library(ggplot2)
  library(jsonlite)
  library(grid)
})

# 不开默认绘图设备：否则 ggplot 会在 CWD 留下 Rplots.pdf。
invisible(pdf(NULL))

out_path <- "tests/fixtures/guide_r_reference.json"
page_in <- c(7, 7)

d <- data.frame(
  x = c(1.5, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6, 5.0, 5.3, 5.6),
  y = c(26.0, 25.0, 24.5, 23.0, 22.5, 21.0, 20.5, 19.5, 18.0, 17.5, 16.5, 15.0),
  cyl = factor(c(4, 4, 4, 6, 6, 6, 8, 8, 8, 4, 6, 8), levels = c(4, 6, 8)),
  gear = factor(c(3, 4, 5, 3, 4, 5, 3, 4, 5, 4, 5, 3), levels = c(3, 4, 5)),
  disp = c(120, 140, 160, 180, 200, 220, 240, 260, 280, 300, 320, 340)
)

num <- function(value) {
  if (is.null(value) || length(value) == 0) {
    return(NULL)
  }
  value <- as.numeric(value)
  unname(value)
}

# 一列 breaks + labels：NA（越界）照原样记下来，Python 侧自己过滤。
breaks_of <- function(view) {
  list(breaks = num(view$get_breaks()), labels = as.character(view$get_labels()))
}

range_of <- function(view, range) {
  list(range = num(range))
}

# 在 7×7in 的页面上画一遍，读回按名字查的 region 尺寸（cm）。
region_size <- function(g, name, kind) {
  row <- g$layout[g$layout$name == name, , drop = FALSE]
  if (nrow(row) == 0) {
    return(NULL)
  }
  if (kind == "height") {
    return(sum(convertHeight(g$heights[row$t:row$b], "cm", valueOnly = TRUE)))
  }
  sum(convertWidth(g$widths[row$l:row$r], "cm", valueOnly = TRUE))
}

measure_axes <- function(g) {
  list(
    axis_l = region_size(g, "axis-l", "width"),
    axis_b = region_size(g, "axis-b", "height"),
    ylab_l = region_size(g, "ylab-l", "width"),
    xlab_b = region_size(g, "xlab-b", "height"),
    title = region_size(g, "title", "height")
  )
}

grob_label <- function(grob) {
  if (!is.null(grob$label)) {
    return(paste(as.character(grob$label), collapse = " "))
  }
  if (!is.null(grob$children)) {
    return(paste(
      vapply(grob$children, grob_label, character(1)),
      collapse = ""
    ))
  }
  ""
}

measure_legends <- function(g) {
  # 4.0.3 的 gtable 对每个方位都留了 guide-box-* 槽；没图例的挂 zeroGrob。
  for (position in c("top", "right", "bottom", "left", "inside")) {
    name <- paste0("guide-box-", position)
    hit <- which(g$layout$name == name)
    if (length(hit) == 0) {
      next
    }
    wrapper <- g$grobs[[hit[1]]]
    if (!inherits(wrapper, "gtable")) {
      next
    }
    row <- g$layout[hit[1], , drop = FALSE]
    downViewport("layout")
    downViewport(paste0(name, ".", row$t, "-", row$r, "-", row$b, "-", row$l))
    cell_width <- convertWidth(unit(1, "npc"), "cm", valueOnly = TRUE)
    cell_height <- convertHeight(unit(1, "npc"), "cm", valueOnly = TRUE)
    downViewport(wrapper$name)
    widths <- convertWidth(wrapper$widths, "cm", valueOnly = TRUE)
    heights <- convertHeight(wrapper$heights, "cm", valueOnly = TRUE)
    guides <- Filter(function(item) inherits(item, "gtable"), wrapper$grobs)
    sizes <- lapply(guides, function(item) {
      item_widths <- convertWidth(item$widths, "cm", valueOnly = TRUE)
      item_heights <- convertHeight(item$heights, "cm", valueOnly = TRUE)
      title_idx <- which(item$layout$name == "title")
      title <- if (length(title_idx)) {
        grob_label(item$grobs[[title_idx[1]]])
      } else {
        NULL
      }
      label_idx <- grep("^label", item$layout$name)
      labels <- unname(unlist(lapply(
        label_idx,
        function(index) grob_label(item$grobs[[index]])
      )))
      list(
        title = title,
        labels = unname(labels),
        width = sum(item_widths),
        height = sum(item_heights),
        widths = num(item_widths),
        heights = num(item_heights)
      )
    })
    vp <- wrapper$vp
    out <- list(
      present = TRUE,
      position = position,
      width = sum(widths),
      height = sum(heights),
      widths = num(widths),
      heights = num(heights),
      cell_width = cell_width,
      cell_height = cell_height,
      x_npc = as.numeric(vp$x),
      y_npc = as.numeric(vp$y),
      just = num(vp$just),
      guides = sizes
    )
    upViewport(0)
    return(out)
  }
  list(present = FALSE)
}

guide_data <- function(plot, aesthetics) {
  out <- list()
  for (aesthetic in aesthetics) {
    key <- tryCatch(get_guide_data(plot, aesthetic), error = function(...) NULL)
    if (is.null(key)) {
      next
    }
    rows <- lapply(seq_len(nrow(key)), function(i) {
      record <- list(label = as.character(key$.label[i]), value = num(key$.value[i]))
      for (name in setdiff(names(key), c(".label", ".value"))) {
        item <- key[[name]][i]
        record[[name]] <- if (is.character(item)) as.character(item) else num(item)
      }
      record
    })
    out[[aesthetic]] <- rows
  }
  out
}

measure_case <- function(name, plot, aesthetics) {
  built <- ggplot_build(plot)
  params <- built$layout$panel_params[[1]]
  g <- ggplotGrob(plot)
  pdf(NULL, width = page_in[1], height = page_in[2])
  grid.newpage()
  grid.draw(g)
  downViewport("layout")
  axes <- measure_axes(g)
  upViewport(0)
  legends <- measure_legends(g)
  upViewport(0)
  list(
    name = name,
    structure = list(
      nrow = nrow(g),
      ncol = ncol(g),
      regions = sort(unique(g$layout$name))
    ),
    axes = axes,
    legends = legends,
    x = list(
      range = num(params$x.range),
      breaks = num(params$x$get_breaks()),
      labels = as.character(params$x$get_labels())
    ),
    y = list(
      range = num(params$y.range),
      breaks = num(params$y$get_breaks()),
      labels = as.character(params$y$get_labels())
    ),
    guides = guide_data(plot, aesthetics)
  )
}

base <- function(mapping) {
  ggplot(d, mapping) + geom_point() + labs(x = "X", y = "Y")
}

cases <- list(
  measure_case("legend_colour_discrete", base(aes(x, y, colour = cyl)), c("colour")),
  measure_case(
    "legend_colour_fill",
    base(aes(x, y, colour = cyl, fill = gear)) + geom_point(shape = 21, size = 2.5),
    c("colour", "fill")
  ),
  measure_case("legend_merged", base(aes(x, y, colour = cyl, shape = cyl)), c("colour", "shape")),
  measure_case("colourbar", base(aes(x, y, colour = disp)), c("colour")),
  measure_case("axis_continuous", base(aes(x, y)), character(0)),
  measure_case("axis_discrete", base(aes(cyl, y)), character(0)),
  measure_case("axis_log10", base(aes(x, y)) + scale_x_log10(), character(0)),
  measure_case(
    "theme_void",
    ggplot(d, aes(x, y, colour = cyl)) +
      geom_point() +
      labs(title = "T", x = "X", y = "Y") +
      theme_void(),
    c("colour")
  ),
  # --- M2-2（SIL-738）：合并 / 多美学 / override / 布局 ----------------------
  measure_case(
    "legend_colour_fill_same",
    base(aes(x, y, colour = cyl, fill = cyl)) + geom_point(shape = 21, size = 2.5),
    c("colour", "fill")
  ),
  measure_case(
    "legend_override",
    base(aes(x, y, colour = cyl)) +
      guides(colour = guide_legend(override.aes = list(alpha = 1, colour = "black"))),
    c("colour")
  ),
  measure_case(
    "legend_nrow2",
    base(aes(x, y, colour = cyl)) + guides(colour = guide_legend(nrow = 2)),
    c("colour")
  ),
  measure_case(
    "legend_label_left",
    base(aes(x, y, colour = cyl)) + guides(colour = guide_legend(label.position = "left")),
    c("colour")
  ),
  measure_case(
    "legend_top",
    base(aes(x, y, colour = cyl)) + theme(legend.position = "top"),
    c("colour")
  ),
  measure_case(
    "legend_inside",
    base(aes(x, y, colour = cyl)) +
      theme(legend.position = "inside", legend.position.inside = c(0.3, 0.7)),
    c("colour")
  ),
  measure_case(
    "legend_order",
    base(aes(x, y, colour = cyl, fill = gear)) +
      geom_point(shape = 21, size = 2.5) +
      guides(colour = guide_legend(order = 2), fill = guide_legend(order = 1)),
    c("colour", "fill")
  ),
  measure_case(
    "legend_two_bottom",
    base(aes(x, y, colour = cyl, fill = gear)) +
      geom_point(shape = 21, size = 2.5) +
      theme(legend.position = "bottom"),
    c("colour", "fill")
  )
)

names(cases) <- vapply(cases, `[[`, character(1), "name")

output <- list(
  generator = "tools/refs/guide_ref.R",
  ggplot2 = as.character(packageVersion("ggplot2")),
  size_in = page_in,
  data = list(
    x = d$x, y = d$y, disp = d$disp,
    cyl = as.character(d$cyl), cyl_levels = levels(d$cyl),
    gear = as.character(d$gear), gear_levels = levels(d$gear)
  ),
  cases = cases
)

writeLines(toJSON(output, auto_unbox = TRUE, digits = 17, na = "null", pretty = TRUE), out_path)
cat("wrote", out_path, "with", length(cases), "cases\n")
