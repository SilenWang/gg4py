#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/gtable_r_reference.json —— gtable 布局对拍的 R 侧参考值。
#
#   pixi run -e refs refs:gtable
#
# gtable 自己不解析尺寸：行高列宽交给 grid，真正的分配发生在
# `grid/src/layout.c` 的 `calcViewportLayout()` 里。所以这里用**设备测量**当
# 参考值：把表画在 10×10 cm 的 pdf(NULL) 上，再逐个视口读回单元格的宽高，以及
# 左下角的设备坐标（grid:::deviceLoc）。这样拿到的是 grid 真实分配的几何，
# 而不是我们自己的推导。
#
# 每个单元格先填一个 nullGrob，视口才会存在（grob 才创建 layout 位置视口）；
# nullGrob 尺寸为 0，不影响布局。

library(grid)
library(gtable)

out_path <- "tests/fixtures/gtable_r_reference.json"

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
# 测量：每个单元格一个 nullGrob，画出来以后按视口路径读回几何
# ---------------------------------------------------------------------------

fill_cells <- function(gt, prefix) {
  for (i in seq_along(gt$heights)) {
    for (j in seq_along(gt$widths)) {
      gt <- gtable_add_grob(gt, nullGrob(), t = i, l = j,
                            name = sprintf("%s%d_%d", prefix, i, j))
    }
  }
  gt
}

cell_name <- function(prefix, i, j) {
  sprintf("%s%d_%d.%d-%d-%d-%d", prefix, i, j, i, j, i, j)
}

probe_box <- function(path) {
  downViewport(vpPath(path))
  width <- convertWidth(unit(1, "npc"), "cm", valueOnly = TRUE)
  height <- convertHeight(unit(1, "npc"), "cm", valueOnly = TRUE)
  origin <- grid:::deviceLoc(unit(0, "npc"), unit(0, "npc"), valueOnly = TRUE)
  upViewport(length(path))
  list(w = width, h = height, x = origin$x * 2.54, y = origin$y * 2.54)
}

cell_records <- function(path, prefix, nrow, ncol) {
  out <- list()
  for (i in seq_len(nrow)) {
    for (j in seq_len(ncol)) {
      box <- probe_box(c(path, cell_name(prefix, i, j)))
      out[[length(out) + 1L]] <- list(
        t = i, l = j, b = i, r = j,
        x = box$x, y = box$y, w = box$w, h = box$h
      )
    }
  }
  out
}

# 子 gtable：路径 = 包装视口（name.t-r-b-l）→ 子表自己的 layout 视口（$name）
nested_records <- function(gt, path, prefix, depth = 1L) {
  out <- list()
  for (k in seq_len(nrow(gt$layout))) {
    row <- gt$layout[k, ]
    grob <- gt$grobs[[k]]
    if (!inherits(grob, "gtable")) next
    wrapper <- paste0(row$name, ".", row$t, "-", row$r, "-", row$b, "-", row$l)
    child_path <- c(path, wrapper, grob$name)
    child_prefix <- paste0("n", depth, "_")
    out[[length(out) + 1L]] <- list(
      name = row$name, t = row$t, l = row$l, b = row$b, r = row$r,
      box = probe_box(c(path, wrapper)),
      cells = cell_records(child_path, child_prefix,
                           length(grob$heights), length(grob$widths)),
      nested = nested_records(grob, child_path, child_prefix, depth + 1L)
    )
  }
  out
}

measure <- function(case) {
  gt <- fill_cells(case$gt, "c")
  for (k in seq_along(case$regions)) {
    region <- case$regions[[k]]
    gt <- gtable_add_grob(gt, nullGrob(), t = region$t, l = region$l,
                          b = region$b, r = region$r, name = sprintf("region%d", k))
  }
  vp_w <- case$width_cm
  vp_h <- case$height_cm
  pdf(NULL, width = vp_w / 2.54, height = vp_h / 2.54)
  pushViewport(viewport(
    width = unit(vp_w, "cm"), height = unit(vp_h, "cm"),
    xscale = case$xscale, yscale = case$yscale, name = "root",
    gp = gpar(fontsize = case$fontsize, cex = case$cex, lineheight = case$lineheight)
  ))
  grid.draw(gt)
  path <- c(gt$name)
  cells <- cell_records(path, "c", length(gt$heights), length(gt$widths))
  regions <- list()
  for (k in seq_along(case$regions)) {
    region <- case$regions[[k]]
    box <- probe_box(c(path, sprintf("region%d.%d-%d-%d-%d",
                                     k, region$t, region$r, region$b, region$l)))
    regions[[length(regions) + 1L]] <- list(
      name = sprintf("region%d", k), t = region$t, l = region$l,
      b = region$b, r = region$r, x = box$x, y = box$y, w = box$w, h = box$h
    )
  }
  nested <- nested_records(gt, path, "c")
  upViewport()
  dev.off()
  list(cells = cells, regions = regions, nested = nested)
}

# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------

case <- function(id, r, spec, gt, regions = list(), note = NULL,
                 width_cm = 10, height_cm = 10,
                 fontsize = 12, cex = 1, lineheight = 1.2,
                 xscale = c(0, 100), yscale = c(0, 50)) {
  list(id = id, r = r, spec = spec, gt = gt, regions = regions, note = note,
       width_cm = width_cm, height_cm = height_cm,
       fontsize = fontsize, cex = cex, lineheight = lineheight,
       xscale = xscale, yscale = yscale)
}

null1 <- function(n) unit(rep(1, n), "null")

inner_two_by_two <- fill_cells(
  gtable(widths = unit(c(1, 3), "null"), heights = unit(c(1, 1), "null"), name = "inner"),
  "n1_"
)
inner_wide <- fill_cells(
  gtable(widths = unit(c(1, 1), "null"), heights = unit(1, "null"), name = "side"),
  "n1_"
)

cases <- list(
  # ---- 纯 null：等权 / 不等权 ---------------------------------------------
  case("pure-null-equal",
       "gtable(widths = unit(c(1,1,1), 'null'), heights = unit(c(1,1), 'null'))",
       '{"op":"gtable","widths":{"kind":"null","amount":[1,1,1]},"heights":{"kind":"null","amount":[1,1]}}',
       gtable(widths = null1(3), heights = null1(2))),
  case("pure-null-uneven",
       "gtable(widths = unit.c(unit(1,'null'), unit(3,'null')), heights = unit.c(unit(2,'null'), unit(1,'null')))",
       paste0('{"op":"gtable","widths":{"kind":"null","amount":[1,3]},',
              '"heights":{"kind":"null","amount":[2,1]}}'),
       gtable(widths = unit(c(1, 3), "null"), heights = unit(c(2, 1), "null"))),

  # ---- 任务点名的三组 -----------------------------------------------------
  case("zero-null-zero-null",
       "gtable(widths = unit(c(0,0), 'null'), heights = unit(1,'null'))",
       '{"op":"gtable","widths":{"kind":"null","amount":[0,0]},"heights":{"kind":"null","amount":1}}',
       gtable(widths = unit(c(0, 0), "null"), heights = null1(1)),
       note = "权重和为 0：R 给 0,0（不除零）"),
  case("zero-null-one-null",
       "gtable(widths = unit(c(0,1), 'null'), heights = unit(1,'null'))",
       '{"op":"gtable","widths":{"kind":"null","amount":[0,1]},"heights":{"kind":"null","amount":1}}',
       gtable(widths = unit(c(0, 1), "null"), heights = null1(1))),
  case("mixed-element-not-null",
       "gtable(widths = unit.c(unit(1,'null') + unit(2,'cm'), unit(1,'null')), heights = unit(1,'null'))",
       paste0('{"op":"gtable","widths":{"op":"unit_c","args":[',
              '{"op":"add","args":[{"kind":"null","amount":1},{"kind":"cm","amount":2}]},',
              '{"kind":"null","amount":1}]},"heights":{"kind":"null","amount":1}}'),
       gtable(widths = unit.c(unit(1, "null") + unit(2, "cm"), unit(1, "null")),
              heights = null1(1)),
       note = "1null+2cm 是混合元素：按 2cm 固定，剩余 8cm 归真正的 null"),

  # ---- 固定 + null、纯固定、单格、0 宽列 ---------------------------------
  case("fixed-plus-null",
       "gtable(widths = unit.c(unit(2,'cm'), unit(1,'null'), unit(3,'cm')), heights = unit.c(unit(1,'cm'), unit(1,'null')))",
       paste0('{"op":"gtable","widths":{"op":"unit_c","args":[{"kind":"cm","amount":2},',
              '{"kind":"null","amount":1},{"kind":"cm","amount":3}]},',
              '"heights":{"op":"unit_c","args":[{"kind":"cm","amount":1},',
              '{"kind":"null","amount":1}]}}'),
       gtable(widths = unit.c(unit(2, "cm"), unit(1, "null"), unit(3, "cm")),
              heights = unit.c(unit(1, "cm"), unit(1, "null")))),
  case("fixed-only-centred",
       "gtable(widths = unit.c(unit(2,'cm'), unit(3,'cm')), heights = unit.c(unit(1,'cm'), unit(4,'cm')))",
       paste0('{"op":"gtable","widths":{"op":"unit_c","args":[{"kind":"cm","amount":2},',
              '{"kind":"cm","amount":3}]},"heights":{"op":"unit_c","args":[',
              '{"kind":"cm","amount":1},{"kind":"cm","amount":4}]}}'),
       gtable(widths = unit.c(unit(2, "cm"), unit(3, "cm")),
              heights = unit.c(unit(1, "cm"), unit(4, "cm"))),
       note = "没有 null：单元格保持固定尺寸，剩余空间由 just='centre' 摊在外面"),
  case("single-cell",
       "gtable(widths = unit(1,'null'), heights = unit(1,'null'))",
       '{"op":"gtable","widths":{"kind":"null","amount":1},"heights":{"kind":"null","amount":1}}',
       gtable(widths = null1(1), heights = null1(1))),
  case("zero-width-fixed-col",
       "gtable(widths = unit.c(unit(0,'cm'), unit(1,'null')), heights = unit(1,'null'))",
       paste0('{"op":"gtable","widths":{"op":"unit_c","args":[{"kind":"cm","amount":0},',
              '{"kind":"null","amount":1}]},"heights":{"kind":"null","amount":1}}'),
       gtable(widths = unit.c(unit(0, "cm"), unit(1, "null")), heights = null1(1))),
  case("fixed-overflow-eats-null",
       "gtable(widths = unit.c(unit(6,'cm'), unit(6,'cm'), unit(1,'null')), heights = unit(1,'null'))",
       paste0('{"op":"gtable","widths":{"op":"unit_c","args":[{"kind":"cm","amount":6},',
              '{"kind":"cm","amount":6},{"kind":"null","amount":1}]},',
              '"heights":{"kind":"null","amount":1}}'),
       gtable(widths = unit.c(unit(6, "cm"), unit(6, "cm"), unit(1, "null")),
              heights = null1(1)),
       note = "固定部分超宽：剩余为负，null 列归 0（allocationRemaining() 的假分支）"),

  # ---- respect ------------------------------------------------------------
  case("respect-square-cells",
       "gtable(widths = unit(c(1,1),'null'), heights = unit(1,'null'), respect = TRUE)",
       paste0('{"op":"gtable","widths":{"kind":"null","amount":[1,1]},',
              '"heights":{"kind":"null","amount":1},"respect":true}'),
       gtable(widths = unit(c(1, 1), "null"), heights = null1(1), respect = TRUE),
       note = "respect：一个 null 单位的宽 = 高，表整体退到 10x5"),
  case("respect-with-fixed",
       "gtable(widths = unit.c(unit(2,'cm'), unit(1,'null')), heights = unit.c(unit(2,'cm'), unit(1,'null')), respect = TRUE)",
       paste0('{"op":"gtable","widths":{"op":"unit_c","args":[{"kind":"cm","amount":2},',
              '{"kind":"null","amount":1}]},"heights":{"op":"unit_c","args":[',
              '{"kind":"cm","amount":2},{"kind":"null","amount":1}]},"respect":true}'),
       gtable(widths = unit.c(unit(2, "cm"), unit(1, "null")),
              heights = unit.c(unit(2, "cm"), unit(1, "null")), respect = TRUE)),

  # ---- 其它单位（lines / pt / mm / npc）与 padding ------------------------
  case("mixed-units",
       paste0("gtable(widths = unit.c(unit(1,'lines'), unit(2,'pt'), unit(5,'mm'), unit(1,'null')), ",
              "heights = unit.c(unit(1,'lines'), unit(1,'null')))"),
       paste0('{"op":"gtable","widths":{"op":"unit_c","args":[{"kind":"lines","amount":1},',
              '{"kind":"points","amount":2},{"kind":"mm","amount":5},',
              '{"kind":"null","amount":1}]},"heights":{"op":"unit_c","args":[',
              '{"kind":"lines","amount":1},{"kind":"null","amount":1}]}}'),
       gtable(widths = unit.c(unit(1, "lines"), unit(2, "pt"), unit(5, "mm"), unit(1, "null")),
              heights = unit.c(unit(1, "lines"), unit(1, "null")))),
  case("padding-mm-stack",
       paste0("gtable_add_padding(gtable(widths = unit(1,'null'), heights = unit(1,'null')), ",
              "unit.c(unit(1,'mm'), unit(2,'mm'), unit(3,'mm'), unit(4,'mm')))"),
       paste0('{"op":"padding","x":{"op":"gtable","widths":{"kind":"null","amount":1},',
              '"heights":{"kind":"null","amount":1}},"padding":{"op":"unit_c","args":[',
              '{"kind":"mm","amount":1},{"kind":"mm","amount":2},',
              '{"kind":"mm","amount":3},{"kind":"mm","amount":4}]}}'),
       gtable_add_padding(gtable(widths = null1(1), heights = null1(1)),
                          unit.c(unit(1, "mm"), unit(2, "mm"),
                                 unit(3, "mm"), unit(4, "mm"))),
       note = "padding 顺序 top/right/bottom/left：行 0.1,9.6,0.3；列 0.4,9.4,0.2"),
  case("padding-pt-null",
       paste0("gtable_add_padding(gtable(widths = unit(1,'null'), heights = unit(1,'null')), ",
              "unit.c(unit(1,'null'), unit(3,'pt'), unit(1,'null'), unit(3,'pt')))"),
       paste0('{"op":"padding","x":{"op":"gtable","widths":{"kind":"null","amount":1},',
              '"heights":{"kind":"null","amount":1}},"padding":{"op":"unit_c","args":[',
              '{"kind":"null","amount":1},{"kind":"points","amount":3},',
              '{"kind":"null","amount":1},{"kind":"points","amount":3}]}}'),
       gtable_add_padding(gtable(widths = null1(1), heights = null1(1)),
                          unit.c(unit(1, "null"), unit(3, "pt"),
                                 unit(1, "null"), unit(3, "pt"))),
       note = "null 边距与表内 null 一起按权重分剩余空间"),
  case("padding-mixed-units",
       paste0("gtable_add_padding(gtable(widths = unit(1,'null'), heights = unit(1,'null')), ",
              "unit.c(unit(1,'mm'), unit(2,'pt'), unit(1,'null'), unit(3,'mm')))"),
       paste0('{"op":"padding","x":{"op":"gtable","widths":{"kind":"null","amount":1},',
              '"heights":{"kind":"null","amount":1}},"padding":{"op":"unit_c","args":[',
              '{"kind":"mm","amount":1},{"kind":"points","amount":2},',
              '{"kind":"null","amount":1},{"kind":"mm","amount":3}]}}'),
       gtable_add_padding(gtable(widths = null1(1), heights = null1(1)),
                          unit.c(unit(1, "mm"), unit(2, "pt"),
                                 unit(1, "null"), unit(3, "mm"))),
       note = "mm / pt / null 三种单位混在 padding 里：固定边距先扣，剩下的归 null"),

  # ---- 嵌套 + span -------------------------------------------------------
  case("nested-two-levels",
       paste0("outer <- gtable(widths = unit.c(unit(4,'cm'), unit(1,'null')), heights = unit(1,'null')); ",
              "gtable_add_grob(outer, inner, t = 1, l = 2, name = 'inner')"),
       paste0('{"op":"add_grob","x":{"op":"gtable","widths":{"op":"unit_c","args":[',
              '{"kind":"cm","amount":4},{"kind":"null","amount":1}]},',
              '"heights":{"kind":"null","amount":1}},"t":1,"l":2,"name":"inner",',
              '"grob":{"op":"gtable","name":"inner","widths":{"kind":"null","amount":[1,3]},',
              '"heights":{"kind":"null","amount":[1,1]}}}'),
       gtable_add_grob(gtable(widths = unit.c(unit(4, "cm"), unit(1, "null")),
                             heights = null1(1)),
                       inner_two_by_two, t = 1, l = 2, name = "inner"),
       note = "子表在 6cm 宽的单元格里解析：1:3 分成 1.5 / 4.5"),
  case("nested-and-span",
       paste0("outer <- gtable(widths = unit.c(unit(1,'null'), unit(3,'null')), ",
              "heights = unit.c(unit(1,'null'), unit(2,'null'))); ",
              "outer <- gtable_add_grob(outer, inner, t = 2, l = 2, name = 'side'); ",
              "gtable_add_grob(outer, nullGrob(), t = 1, l = 1, r = 2, name = 'header')"),
       paste0('{"op":"add_grob","x":{"op":"add_grob","x":{"op":"gtable",',
              '"widths":{"kind":"null","amount":[1,3]},"heights":{"kind":"null","amount":[1,2]}},',
              '"t":2,"l":2,"name":"side","grob":{"op":"gtable","name":"side",',
              '"widths":{"kind":"null","amount":[1,1]},"heights":{"kind":"null","amount":1}}},',
              '"t":1,"l":1,"r":2,"name":"header","grob":"probe"}'),
       gtable_add_grob(
         gtable_add_grob(
           gtable(widths = unit(c(1, 3), "null"), heights = unit(c(1, 2), "null")),
           inner_wide, t = 2, l = 2, name = "side"),
         nullGrob(), t = 1, l = 1, r = 2, name = "header"),
       regions = list(list(t = 1, l = 1, b = 1, r = 2), list(t = 1, l = 1, b = 2, r = 2))),

  # ---- 加行 / 加列（含插入位置） -----------------------------------------
  case("add-rows-cols-positions",
       paste0("g <- gtable(widths = unit(1,'null'), heights = unit(1,'null')); ",
              "g <- gtable_add_cols(g, unit(2,'cm'), pos = 0); ",
              "g <- gtable_add_rows(g, unit(1,'null'), pos = 0); ",
              "gtable_add_cols(gtable_add_rows(g, unit(5,'mm'), pos = -1), unit(3,'mm'), pos = -1)"),
       paste0('{"op":"add_cols","x":{"op":"add_rows","x":{"op":"add_cols","x":',
              '{"op":"add_rows","x":{"op":"gtable","widths":{"kind":"null","amount":1},',
              '"heights":{"kind":"null","amount":1}},"heights":{"kind":"null","amount":1},"pos":0},',
              '"widths":{"kind":"cm","amount":2},"pos":0},"heights":{"kind":"mm","amount":5},',
              '"pos":-1},"widths":{"kind":"mm","amount":3},"pos":-1}'),
       gtable_add_cols(
         gtable_add_rows(
           gtable_add_cols(
             gtable_add_rows(gtable(widths = null1(1), heights = null1(1)),
                             null1(1), pos = 0),
             unit(2, "cm"), pos = 0),
           unit(5, "mm"), pos = -1),
         unit(3, "mm"), pos = -1)),

  # ---- 边界 --------------------------------------------------------------
  case("zero-viewport",
       "gtable(widths = unit(1,'null'), heights = unit(1,'null'))  # 0x0 cm 视口",
       '{"op":"gtable","widths":{"kind":"null","amount":1},"heights":{"kind":"null","amount":1}}',
       gtable(widths = null1(1), heights = null1(1)),
       width_cm = 0, height_cm = 0),
  case("small-viewport",
       "gtable(widths = unit.c(unit(4,'cm'), unit(1,'null')), heights = unit(1,'null'))  # 3x3 cm 视口",
       paste0('{"op":"gtable","widths":{"op":"unit_c","args":[{"kind":"cm","amount":4},',
              '{"kind":"null","amount":1}]},"heights":{"kind":"null","amount":1}}'),
       gtable(widths = unit.c(unit(4, "cm"), unit(1, "null")), heights = null1(1)),
       width_cm = 3, height_cm = 3,
       note = "固定列比视口还宽：null 列归 0，单元格照旧溢出"),
  case("zero-viewport-fixed-col",
       "gtable(widths = unit.c(unit(2,'cm'), unit(1,'null')), heights = unit(1,'null'))  # 0x10 cm 视口",
       paste0('{"op":"gtable","widths":{"op":"unit_c","args":[{"kind":"cm","amount":2},',
              '{"kind":"null","amount":1}]},"heights":{"kind":"null","amount":1}}'),
       gtable(widths = unit.c(unit(2, "cm"), unit(1, "null")), heights = null1(1)),
       width_cm = 0, height_cm = 10,
       note = paste0("R 4.5.3 的 allocationRemaining(initial == 0) 返回 TRUE：",
                     "视口宽 0、固定列 2cm 时剩余 -2cm 全给 null 列，得到 2, -2；",
                     "纯 null 的零视口才是 0, 0"))
)

# ---------------------------------------------------------------------------
# 跑用例
# ---------------------------------------------------------------------------

records <- lapply(cases, function(c) {
  measured <- measure(c)
  list(
    id = c$id, r = c$r, spec = c$spec, note = c$note,
    viewport = list(
      width_cm = c$width_cm, height_cm = c$height_cm,
      fontsize = c$fontsize, cex = c$cex, lineheight = c$lineheight,
      xscale = c$xscale, yscale = c$yscale
    ),
    cells = measured$cells,
    regions = measured$regions,
    nested = measured$nested
  )
})

document <- list(
  r_version = R.version.string,
  gtable_version = as.character(packageVersion("gtable")),
  generated_by = "tools/refs/gtable_ref.R",
  device = list(type = "pdf(NULL)", page = "与视口同尺寸"),
  position_oracle = "grid:::deviceLoc(unit(0,'npc'), unit(0,'npc')) * 2.54（cm，左下原点）",
  cases = records
)

dir.create(dirname(out_path), showWarnings = FALSE, recursive = TRUE)
writeLines(to_json(document), out_path)
cat("wrote ", out_path, " (", length(records), " cases, gtable ",
    document$gtable_version, ", ", R.version.string, ")\n", sep = "")
