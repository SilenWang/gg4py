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
  library(grid)
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

# ---------------------------------------------------------------------------
# SIL-1002：`guides="collect"` / `guide_area()` 的关系对拍
#
# 本仓字体度量与 R 不同，绝对 pt 同样不逐值比：夹具记录的是 patchwork 侧的
# **关系**，Python 侧断言同一组关系：
# - 同结构图例 keep 时 2 份、collect 时 1 份、主题不同不合并（2 份）；
# - collect 的顶层 `guide-box` 在 panel 块右侧第 5 列、纵向跨 panel 行；
# - `guide_area()` 占用普通 panel 格（与同格 patch 的矩形相同），图例不额外
#   占行列；
# - collect 后 panel 比 keep 宽（子图各自的图例列被清零，只剩顶层一份）。
# ---------------------------------------------------------------------------

legend_data <- transform(d, gear_f = factor(gear, labels = c("aa", "bb", "cc")))
legend_plot <- function(y, fill) {
  ggplot(legend_data, aes(wt, y, colour = gear_f)) +
    geom_point() +
    labs(colour = "gear") +
    theme(panel.background = element_rect(fill = fill, colour = NA))
}
l1 <- legend_plot(legend_data$mpg, "#CC0000")
l2 <- legend_plot(legend_data$disp, "#00CC00")
l3 <- legend_plot(legend_data$hp, "#0000CC") + theme(legend.text = element_text(size = 20))

count_guides <- function(gt) {
  n <- 0
  walk <- function(g) {
    if (inherits(g, "gtable")) {
      n <<- n + sum(grepl("^guides", g$layout$name))
      for (child in g$grobs) walk(child)
    } else if (inherits(g, "gTree")) {
      for (child in g$children) walk(child)
    }
  }
  walk(gt)
  n
}

# null 槽按剩余空间 / 权重分配，得到 gtable 在给定页面下的 pt 尺寸。
resolve_pt <- function(u, total, horizontal = TRUE) {
  v <- rep(NA_real_, length(u))
  for (i in seq_along(u)) {
    if (!identical(grid::unitType(u[i]), "null")) {
      v[i] <- if (horizontal) {
        convertWidth(u[i], "pt", valueOnly = TRUE)
      } else {
        convertHeight(u[i], "pt", valueOnly = TRUE)
      }
    }
  }
  is_null <- is.na(v)
  free <- total - sum(v, na.rm = TRUE)
  weights <- rep(0, length(u))
  for (i in which(is_null)) weights[i] <- as.numeric(u[i])
  v[is_null] <- free * weights[is_null] / sum(weights[is_null])
  v
}

legend_hits <- function(file, label) {
  lines <- readLines(file, warn = FALSE)
  texts <- unlist(regmatches(lines, gregexpr("<text[^>]*>[^<]*</text>", lines)))
  sum(grepl(paste0(">", label, "<"), texts, fixed = TRUE))
}

guide_probe <- function(plot, width, height, label) {
  file <- file.path(outdir, paste0("guides_", label, ".svg"))
  svglite(file, width = width, height = height)
  print(plot)
  dev.off()
  gt <- patchworkGrob(plot)
  loc <- gt$layout
  w <- resolve_pt(gt$widths, width * 72)
  h <- resolve_pt(gt$heights, height * 72, horizontal = FALSE)
  panel <- find_panel(gt)
  box <- which(grepl("^guide-box$", loc$name))
  area <- which(grepl("panel-guide_area", loc$name))
  patch <- which(grepl("^panel_patch", loc$name))
  out <- list(
    width_in = width,
    height_in = height,
    guide_count = count_guides(gt),
    legend_label_count = legend_hits(file, "aa"),
    panel = list(
      t = panel$t, l = panel$l, b = panel$b, r = panel$r,
      w = sum(w[panel$l:panel$r]), h = sum(h[panel$t:panel$b])
    )
  )
  if (length(box) == 1) {
    j <- loc[box, ]
    out$guide_box <- list(
      t = j$t, l = j$l, b = j$b, r = j$r,
      w = sum(w[j$l:j$r]), h = sum(h[j$t:j$b]),
      col_offset_from_panel = j$l - panel$r,
      spans_panel_rows = identical(as.integer(j$t), as.integer(panel$t)) &&
        identical(as.integer(j$b), as.integer(panel$b))
    )
  }
  if (length(area) == 1) {
    j <- loc[area, ]
    out$guide_area <- list(
      t = j$t, l = j$l, b = j$b, r = j$r,
      w = sum(w[j$l:j$r]), h = sum(h[j$t:j$b])
    )
    if (length(patch) >= 1) {
      same <- vapply(seq_len(nrow(loc[patch, ])), function(k) {
        p <- loc[patch, ][k, ]
        identical(as.integer(p$t), as.integer(j$t)) &&
          identical(as.integer(p$l), as.integer(j$l)) &&
          identical(as.integer(p$b), as.integer(j$b)) &&
          identical(as.integer(p$r), as.integer(j$r))
      }, logical(1))
      out$guide_area$matches_patch_cell <- any(same)
    }
  }
  out
}

# 注意 R 的运算符优先级：`+` 高于 `|`，`l1 | l2 + plot_layout()` 只会把设置加到
# 右半边；这里一律给组合加括号（与 `docs/notes/composition.md` 的 Python 口径
# 不同，Python 的 `+` 同样低于 `|`）。
# 「同结构」用**同一张图**两次：patchwork 1.3.2 的 `collapse_guides()` 比较的是
# 渲染后的 guide grob（`unname_grob()` + `all.equal()`），而 ggplot2 4.0.3 的
# guide grob 里带有随图层数据变化的字符串，所以换一张数据不同、结构相同的图
# 在 R 里**不会**合并（实测 2 份）。本实现按 SIL-1002 定义的 GuideKey（aesthetic
# + scale spec + breaks/labels + theme 指纹）去重，`different_data` 因此是已知
# 差异（见 docs/notes/composition.md）。
payload$guides <- list(
  keep = guide_probe((l1 | l1) + plot_layout(guides = "keep"), 7, 5, "keep"),
  collect = guide_probe((l1 | l1) + plot_layout(guides = "collect"), 7, 5, "collect"),
  different_theme = guide_probe(
    (l1 | l3) + plot_layout(guides = "collect"), 7, 5, "different-theme"
  ),
  different_data = guide_probe(
    (l1 | l2) + plot_layout(guides = "collect"), 7, 5, "different-data"
  ),
  area = guide_probe(
    l1 + guide_area() + plot_layout(ncol = 2, guides = "collect"), 7, 5, "area"
  )
)

target <- file.path("tests", "fixtures", "composition_r_reference.json")
writeLines(to_json(payload), target)
cat("wrote", target, "\n")
