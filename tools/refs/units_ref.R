#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/units_r_reference.json —— units 对拍的 R 侧参考值。
#
#   pixi run -e refs refs:units
#
# 每条用例都带：R 侧表达式（`r`）、Python 侧的构造 spec、换算上下文、
# R 算出的期望值，以及（可选）单位结构快照。设备固定成 10x10 in 的 pdf(NULL)，
# 视口按用例 push，所以结果只取决于这里的输入，与机器字体无关——只有
# strwidth/strheight 依赖设备度量，夹具里把那次的实测宽度/高度一并记下来
# 当作注入值（真实度量是 M0-7 的事）。

library(grid)

out_path <- "tests/fixtures/units_r_reference.json"

# ---------------------------------------------------------------------------
# 极简 JSON 输出（不引入 jsonlite）
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
# 单位结构快照（与 Python `Unit.to_structure()` 同构）
# ---------------------------------------------------------------------------

element_struct <- function(element) {
  kind <- grid:::units[[as.character(element[[3]])]]
  node <- list(kind = kind, amount = element[[1]])
  if (kind %in% c("sum", "min", "max")) {
    node$children <- lapply(unclass(element[[2]]), element_struct)
  } else if (!is.null(element[[2]])) {
    node$text <- element[[2]]
  }
  node
}

unit_struct <- function(u) {
  lapply(unclass(grid:::as.unit(u)), element_struct)
}

# ---------------------------------------------------------------------------
# 用例定义
# ---------------------------------------------------------------------------

case <- function(id, r, spec, u, to = "cm", axis_from = "x", type_from = "location",
                 axis_to = NULL, type_to = NULL,
                 width_cm = 10, height_cm = 5,
                 xscale = c(0, 100), yscale = c(0, 50),
                 fontsize = 12, cex = 1, lineheight = 1.2,
                 tolerance = 1e-12, structure = FALSE, strings = character(),
                 expect_error = FALSE, python_only = FALSE, python_expect = NULL,
                 note = NULL) {
  list(
    id = id, r = r, spec = spec, unit = u, to = to,
    axis_from = axis_from, type_from = type_from,
    axis_to = if (is.null(axis_to)) axis_from else axis_to,
    type_to = if (is.null(type_to)) type_from else type_to,
    width_cm = width_cm, height_cm = height_cm,
    xscale = xscale, yscale = yscale,
    fontsize = fontsize, cex = cex, lineheight = lineheight,
    tolerance = tolerance, structure = structure, strings = strings,
    expect_error = expect_error, python_only = python_only,
    python_expect = python_expect, note = note
  )
}

rev_x <- c(100, 0)

cases <- list(
  # ---- 基本换算：x / y / location / dimension -----------------------------
  case("npc-to-cm-x", "convertUnit(unit(0.25, 'npc'), 'cm', valueOnly=TRUE)",
       '{"kind":"npc","amount":0.25}', unit(0.25, "npc")),
  case("npc-to-cm-y", "convertUnit(unit(0.25, 'npc'), 'cm', axisFrom='y', axisTo='y', valueOnly=TRUE)",
       '{"kind":"npc","amount":0.25}', unit(0.25, "npc"), axis_from = "y"),
  case("npc-x-to-y-npc", "convertUnit(unit(0.25, 'npc'), 'npc', axisFrom='x', axisTo='y', valueOnly=TRUE)",
       '{"kind":"npc","amount":0.25}', unit(0.25, "npc"), to = "npc", axis_to = "y"),
  case("npc-x-dimension-to-cm", "convertUnit(unit(0.5, 'npc'), 'cm', typeFrom='dimension', typeTo='dimension', valueOnly=TRUE)",
       '{"kind":"npc","amount":0.5}', unit(0.5, "npc"), type_from = "dimension"),
  case("npc-x-to-native-location", "convertUnit(unit(0.5, 'npc'), 'native', valueOnly=TRUE)",
       '{"kind":"npc","amount":0.5}', unit(0.5, "npc"), to = "native"),
  case("npc-location-to-dimension", "convertUnit(unit(0.25, 'npc'), 'npc', typeFrom='location', typeTo='dimension', valueOnly=TRUE)",
       '{"kind":"npc","amount":0.25}', unit(0.25, "npc"), to = "npc", type_to = "dimension"),
  case("npc-x-dim-to-y-dim", "convertUnit(unit(0.5, 'npc'), 'npc', typeFrom='dimension', typeTo='dimension', axisFrom='x', axisTo='y', valueOnly=TRUE)",
       '{"kind":"npc","amount":0.5}', unit(0.5, "npc"), to = "npc",
       type_from = "dimension", axis_to = "y", type_to = "dimension"),
  case("native-x-to-cm", "convertUnit(unit(25, 'native'), 'cm', valueOnly=TRUE)",
       '{"kind":"native","amount":25}', unit(25, "native")),
  case("native-y-to-cm", "convertUnit(unit(25, 'native'), 'cm', axisFrom='y', axisTo='y', valueOnly=TRUE)",
       '{"kind":"native","amount":25}', unit(25, "native"), axis_from = "y"),
  case("native-dimension-to-npc", "convertUnit(unit(50, 'native'), 'npc', typeFrom='dimension', typeTo='dimension', valueOnly=TRUE)",
       '{"kind":"native","amount":50}', unit(50, "native"),
       to = "npc", type_from = "dimension"),
  case("native-to-native-dimension", "convertUnit(unit(2.54, 'cm'), 'native', typeFrom='dimension', typeTo='dimension', valueOnly=TRUE)",
       '{"kind":"cm","amount":2.54}', unit(2.54, "cm"),
       to = "native", type_from = "dimension"),
  case("native-reversed-scale-location", "convertUnit(unit(25, 'native'), 'cm', valueOnly=TRUE)  # xscale=c(100,0)",
       '{"kind":"native","amount":25}', unit(25, "native"), xscale = rev_x),
  case("native-reversed-scale-dimension", "convertUnit(unit(50, 'native'), 'cm', typeFrom='dimension', typeTo='dimension', valueOnly=TRUE)  # xscale=c(100,0)",
       '{"kind":"native","amount":50}', unit(50, "native"), type_from = "dimension",
       xscale = rev_x),

  # ---- 绝对单位 -----------------------------------------------------------
  case("mm-to-inches", "convertUnit(unit(25.4, 'mm'), 'inches', valueOnly=TRUE)",
       '{"kind":"mm","amount":25.4}', unit(25.4, "mm"), to = "inches"),
  case("mm-to-cm", "convertUnit(unit(10, 'mm'), 'cm', valueOnly=TRUE)",
       '{"kind":"mm","amount":10}', unit(10, "mm")),
  case("mm-to-pt", "convertUnit(unit(10, 'mm'), 'pt', valueOnly=TRUE)",
       '{"kind":"mm","amount":10}', unit(10, "mm"), to = "pt"),
  case("cm-to-inches", "convertUnit(unit(2.54, 'cm'), 'inches', valueOnly=TRUE)",
       '{"kind":"cm","amount":2.54}', unit(2.54, "cm"), to = "inches"),
  case("inches-to-mm", "convertUnit(unit(1, 'inches'), 'mm', valueOnly=TRUE)",
       '{"kind":"inches","amount":1}', unit(1, "inches"), to = "mm"),
  case("pt-to-mm", "convertUnit(unit(72.27, 'pt'), 'mm', valueOnly=TRUE)",
       '{"kind":"pt","amount":72.27}', unit(72.27, "pt"), to = "mm"),
  case("bigpts-to-mm", "convertUnit(unit(72, 'bigpts'), 'mm', valueOnly=TRUE)",
       '{"kind":"bigpts","amount":72}', unit(72, "bigpts"), to = "mm"),
  case("picas-to-pt", "convertUnit(unit(1, 'picas'), 'pt', valueOnly=TRUE)",
       '{"kind":"picas","amount":1}', unit(1, "picas"), to = "pt"),
  case("dida-to-pt", "convertUnit(unit(1, 'dida'), 'pt', valueOnly=TRUE)",
       '{"kind":"dida","amount":1}', unit(1, "dida"), to = "pt"),
  case("cicero-to-pt", "convertUnit(unit(1, 'cicero'), 'pt', valueOnly=TRUE)",
       '{"kind":"cicero","amount":1}', unit(1, "cicero"), to = "pt"),
  case("scaledpts-to-pt", "convertUnit(unit(65536, 'scaledpts'), 'pt', valueOnly=TRUE)",
       '{"kind":"scaledpts","amount":65536}', unit(65536, "scaledpts"), to = "pt"),
  case("inch-alias-in", "convertUnit(unit(2.54, 'cm'), 'in', valueOnly=TRUE)",
       '{"kind":"cm","amount":2.54}', unit(2.54, "cm"), to = "in"),
  case("millimetre-alias", "convertUnit(unit(2.54, 'cm'), 'millimetres', valueOnly=TRUE)",
       '{"kind":"cm","amount":2.54}', unit(2.54, "cm"), to = "millimetres"),

  # ---- 字号相关：lines / char --------------------------------------------
  case("lines-to-inches", "convertUnit(unit(1, 'lines'), 'inches', valueOnly=TRUE)",
       '{"kind":"lines","amount":1}', unit(1, "lines"), to = "inches"),
  case("lines-big-font", "convertUnit(unit(1, 'lines'), 'inches', valueOnly=TRUE)  # fontsize=24, cex=1.5, lineheight=2",
       '{"kind":"lines","amount":1}', unit(1, "lines"), to = "inches",
       fontsize = 24, cex = 1.5, lineheight = 2),
  case("lines-to-pt", "convertUnit(unit(2, 'lines'), 'pt', valueOnly=TRUE)",
       '{"kind":"lines","amount":2}', unit(2, "lines"), to = "pt"),
  case("char-to-mm", "convertUnit(unit(3, 'char'), 'mm', valueOnly=TRUE)",
       '{"kind":"char","amount":3}', unit(3, "char"), to = "mm"),
  case("char-big-font", "convertUnit(unit(1, 'char'), 'inches', valueOnly=TRUE)  # fontsize=24, cex=1.5",
       '{"kind":"char","amount":1}', unit(1, "char"), to = "inches",
       fontsize = 24, cex = 1.5),

  # ---- snpc ---------------------------------------------------------------
  case("snpc-to-cm", "convertUnit(unit(0.5, 'snpc'), 'cm', valueOnly=TRUE)",
       '{"kind":"snpc","amount":0.5}', unit(0.5, "snpc")),
  case("snpc-y-to-cm", "convertUnit(unit(0.5, 'snpc'), 'cm', axisFrom='y', axisTo='y', valueOnly=TRUE)",
       '{"kind":"snpc","amount":0.5}', unit(0.5, "snpc"), axis_from = "y"),
  case("snpc-dimension-to-cm", "convertUnit(unit(0.5, 'snpc'), 'cm', typeFrom='dimension', typeTo='dimension', valueOnly=TRUE)",
       '{"kind":"snpc","amount":0.5}', unit(0.5, "snpc"), type_from = "dimension"),

  # ---- strwidth / strheight（度量由夹具注入） -----------------------------
  case("strwidth-to-inches", "convertUnit(stringWidth('abc'), 'inches', valueOnly=TRUE)",
       '{"op":"str_width","text":"abc"}', stringWidth("abc"), to = "inches",
       strings = "abc"),
  case("strheight-to-inches", "convertUnit(stringHeight('abc'), 'inches', valueOnly=TRUE)",
       '{"op":"str_height","text":"abc"}', stringHeight("abc"), to = "inches",
       strings = "abc"),
  case("strwidth-double-to-cm", "convertUnit(unit(2, 'strwidth', data='abc'), 'cm', valueOnly=TRUE)",
       '{"kind":"strwidth","amount":2,"text":"abc"}', unit(2, "strwidth", data = "abc"),
       strings = "abc"),
  case("strwidth-big-font", "convertUnit(stringWidth('abc'), 'inches', valueOnly=TRUE)  # fontsize=24, cex=1.5",
       '{"op":"str_width","text":"abc"}', stringWidth("abc"), to = "inches",
       fontsize = 24, cex = 1.5, strings = "abc"),
  case("strheight-WWW-to-mm", "convertUnit(stringHeight('WWW'), 'mm', valueOnly=TRUE)",
       '{"op":"str_height","text":"WWW"}', stringHeight("WWW"), to = "mm",
       strings = "WWW"),
  case("strwidth-plus-cm", "convertUnit(stringWidth('abc') + unit(1, 'cm'), 'cm', valueOnly=TRUE)",
       '{"op":"add","args":[{"op":"str_width","text":"abc"},{"kind":"cm","amount":1}]}',
       stringWidth("abc") + unit(1, "cm"), strings = "abc"),
  case("sum-two-strwidth", "convertUnit(sum(stringWidth('abc'), stringWidth('abc')), 'cm', valueOnly=TRUE)",
       '{"op":"sum","args":[{"op":"str_width","text":"abc"},{"op":"str_width","text":"abc"}]}',
       sum(stringWidth("abc"), stringWidth("abc")), structure = TRUE, strings = "abc"),
  case("pmax-strwidth-same", "convertUnit(unit.pmax(stringWidth('abc'), stringWidth('abc')), 'inches', valueOnly=TRUE)",
       '{"op":"pmax","args":[{"op":"str_width","text":"abc"},{"op":"str_width","text":"abc"}]}',
       unit.pmax(stringWidth("abc"), stringWidth("abc")), to = "inches",
       structure = TRUE, strings = "abc"),
  case("pmax-strwidth-different", "convertUnit(unit.pmax(stringWidth('abc'), stringWidth('def')), 'inches', valueOnly=TRUE)",
       '{"op":"pmax","args":[{"op":"str_width","text":"abc"},{"op":"str_width","text":"def"}]}',
       unit.pmax(stringWidth("abc"), stringWidth("def")), to = "inches",
       structure = TRUE, strings = c("abc", "def")),

  # ---- null ---------------------------------------------------------------
  case("null-to-cm", "convertUnit(unit(1, 'null'), 'cm', valueOnly=TRUE)",
       '{"kind":"null","amount":1}', unit(1, "null")),
  case("null-dimension-to-cm", "convertUnit(unit(1, 'null'), 'cm', typeFrom='dimension', typeTo='dimension', valueOnly=TRUE)",
       '{"kind":"null","amount":1}', unit(1, "null"), type_from = "dimension"),
  case("null-plus-cm", "convertUnit(unit(1, 'null') + unit(2, 'cm'), 'cm', valueOnly=TRUE)",
       '{"op":"add","args":[{"kind":"null","amount":1},{"kind":"cm","amount":2}]}',
       unit(1, "null") + unit(2, "cm")),
  case("pmin-null-cm", "convertUnit(unit.pmin(unit(1, 'null'), unit(2, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"pmin","args":[{"kind":"null","amount":1},{"kind":"cm","amount":2}]}',
       unit.pmin(unit(1, "null"), unit(2, "cm"))),
  case("pmax-null-cm", "convertUnit(unit.pmax(unit(1, 'null'), unit(2, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"pmax","args":[{"kind":"null","amount":1},{"kind":"cm","amount":2}]}',
       unit.pmax(unit(1, "null"), unit(2, "cm"))),
  case("pmin-null-inches", "convertUnit(unit.pmin(unit(1, 'null'), unit(5, 'inches')), 'inches', valueOnly=TRUE)",
       '{"op":"pmin","args":[{"kind":"null","amount":1},{"kind":"inches","amount":5}]}',
       unit.pmin(unit(1, "null"), unit(5, "inches")), to = "inches"),

  # ---- 算术：+ / - / * / / / 负号 ------------------------------------------
  case("cm-plus-mm", "convertUnit(unit(1, 'cm') + unit(2, 'mm'), 'cm', valueOnly=TRUE)",
       '{"op":"add","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":2}]}',
       unit(1, "cm") + unit(2, "mm"), structure = TRUE),
  case("cm-plus-mm-vector", "convertUnit(unit(1:2, 'cm') + unit(3:4, 'mm'), 'cm', valueOnly=TRUE)",
       '{"op":"add","args":[{"kind":"cm","amount":[1,2]},{"kind":"mm","amount":[3,4]}]}',
       unit(1:2, "cm") + unit(3:4, "mm"), structure = TRUE),
  case("cm-plus-mm-recycle", "convertUnit(unit(1:3, 'cm') + unit(2, 'mm'), 'cm', valueOnly=TRUE)",
       '{"op":"add","args":[{"kind":"cm","amount":[1,2,3]},{"kind":"mm","amount":2}]}',
       unit(1:3, "cm") + unit(2, "mm")),
  case("cm-plus-cm-vector", "convertUnit(unit(1:2, 'cm') + unit(10, 'cm'), 'cm', valueOnly=TRUE)",
       '{"op":"add","args":[{"kind":"cm","amount":[1,2]},{"kind":"cm","amount":10}]}',
       unit(1:2, "cm") + unit(10, "cm"), structure = TRUE),
  case("cm-minus-cm", "convertUnit(unit(3, 'cm') - unit(1, 'cm'), 'cm', valueOnly=TRUE)",
       '{"op":"sub","args":[{"kind":"cm","amount":3},{"kind":"cm","amount":1}]}',
       unit(3, "cm") - unit(1, "cm"), structure = TRUE),
  case("cm-minus-mm", "convertUnit(unit(3, 'cm') - unit(1, 'mm'), 'cm', valueOnly=TRUE)",
       '{"op":"sub","args":[{"kind":"cm","amount":3},{"kind":"mm","amount":1}]}',
       unit(3, "cm") - unit(1, "mm"), structure = TRUE),
  case("cm-times-2.5", "convertUnit(unit(1:2, 'cm') * 2.5, 'cm', valueOnly=TRUE)",
       '{"op":"mul","scalar":2.5,"arg":{"kind":"cm","amount":[1,2]}}',
       unit(1:2, "cm") * 2.5),
  case("cm-div-4", "convertUnit(unit(2, 'cm') / 4, 'cm', valueOnly=TRUE)",
       '{"op":"div","scalar":4,"arg":{"kind":"cm","amount":2}}',
       unit(2, "cm") / 4, structure = TRUE),
  case("cm-times-vector", "convertUnit(unit(1:3, 'cm') * c(1, 2), 'cm', valueOnly=TRUE)",
       '{"op":"mul","scalar":[1,2],"arg":{"kind":"cm","amount":[1,2,3]}}',
       unit(1:3, "cm") * c(1, 2)),
  case("neg-unit", "convertUnit(-unit(1, 'cm'), 'cm', valueOnly=TRUE)",
       '{"op":"neg","arg":{"kind":"cm","amount":1}}', -unit(1, "cm")),
  case("neg-sum", "convertUnit(-(unit(1, 'cm') + unit(1, 'mm')), 'cm', valueOnly=TRUE)",
       '{"op":"neg","arg":{"op":"add","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":1}]}}',
       -(unit(1, "cm") + unit(1, "mm")), structure = TRUE),
  case("zero-times-unit", "convertUnit(unit(1, 'cm') * 0, 'cm', valueOnly=TRUE)",
       '{"op":"mul","scalar":0,"arg":{"kind":"cm","amount":1}}', unit(1, "cm") * 0),

  # ---- pmax / pmin / psum --------------------------------------------------
  case("pmax-same-kind", "convertUnit(unit.pmax(unit(1, 'cm'), unit(2, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"pmax","args":[{"kind":"cm","amount":1},{"kind":"cm","amount":2}]}',
       unit.pmax(unit(1, "cm"), unit(2, "cm")), structure = TRUE),
  case("pmax-mixed", "convertUnit(unit.pmax(unit(1, 'cm'), unit(2, 'mm')), 'cm', valueOnly=TRUE)",
       '{"op":"pmax","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":2}]}',
       unit.pmax(unit(1, "cm"), unit(2, "mm")), structure = TRUE),
  case("pmax-three-units", "convertUnit(unit.pmax(unit(1, 'cm'), unit(2, 'mm'), unit(0.5, 'inches')), 'cm', valueOnly=TRUE)",
       '{"op":"pmax","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":2},{"kind":"inches","amount":0.5}]}',
       unit.pmax(unit(1, "cm"), unit(2, "mm"), unit(0.5, "inches")), structure = TRUE),
  case("pmax-vector", "convertUnit(unit.pmax(unit(1:3, 'cm'), unit(2, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"pmax","args":[{"kind":"cm","amount":[1,2,3]},{"kind":"cm","amount":2}]}',
       unit.pmax(unit(1:3, "cm"), unit(2, "cm")), structure = TRUE),
  case("pmax-with-sum-child", "convertUnit(unit.pmax(unit(1, 'cm') + unit(1, 'mm'), unit(0.5, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"pmax","args":[{"op":"add","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":1}]},{"kind":"cm","amount":0.5}]}',
       unit.pmax(unit(1, "cm") + unit(1, "mm"), unit(0.5, "cm")), structure = TRUE),
  case("psum-mixed", "convertUnit(unit.psum(unit(1, 'cm'), unit(2, 'mm')), 'cm', valueOnly=TRUE)",
       '{"op":"psum","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":2}]}',
       unit.psum(unit(1, "cm"), unit(2, "mm")), structure = TRUE),
  case("psum-same-kind", "convertUnit(unit.psum(unit(1, 'cm'), unit(2, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"psum","args":[{"kind":"cm","amount":1},{"kind":"cm","amount":2}]}',
       unit.psum(unit(1, "cm"), unit(2, "cm")), structure = TRUE),
  case("psum-with-sum-child", "convertUnit(unit.psum(unit(1, 'cm') + unit(1, 'mm'), unit(0.5, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"psum","args":[{"op":"add","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":1}]},{"kind":"cm","amount":0.5}]}',
       unit.psum(unit(1, "cm") + unit(1, "mm"), unit(0.5, "cm")), structure = TRUE),
  case("pmax-scaled-sum-child", "convertUnit(unit.pmax(2 * (unit(1, 'cm') + unit(1, 'mm')), unit(0.5, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"pmax","args":[{"op":"mul","scalar":2,"arg":{"op":"add","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":1}]}},{"kind":"cm","amount":0.5}]}',
       unit.pmax(2 * (unit(1, "cm") + unit(1, "mm")), unit(0.5, "cm")), structure = TRUE),

  # ---- sum / min / max（塌成一个元素） ------------------------------------
  case("sum-mixed", "convertUnit(sum(unit(1, 'cm'), unit(2, 'mm')), 'cm', valueOnly=TRUE)",
       '{"op":"sum","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":2}]}',
       sum(unit(1, "cm"), unit(2, "mm")), structure = TRUE),
  case("sum-same-kind", "convertUnit(sum(unit(1, 'cm'), unit(2, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"sum","args":[{"kind":"cm","amount":1},{"kind":"cm","amount":2}]}',
       sum(unit(1, "cm"), unit(2, "cm")), structure = TRUE),
  case("max-same-kind", "convertUnit(max(unit(1, 'cm'), unit(2, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"max","args":[{"kind":"cm","amount":1},{"kind":"cm","amount":2}]}',
       max(unit(1, "cm"), unit(2, "cm")), structure = TRUE),
  case("min-mixed", "convertUnit(min(unit(1, 'cm'), unit(2, 'mm')), 'cm', valueOnly=TRUE)",
       '{"op":"min","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":2}]}',
       min(unit(1, "cm"), unit(2, "mm")), structure = TRUE),

  # ---- unit.c：拼接 / 摊平 ------------------------------------------------
  case("unit-c-same-kind", "convertUnit(unit.c(unit(1, 'cm'), unit(2, 'cm')), 'mm', valueOnly=TRUE)",
       '{"op":"unit_c","args":[{"kind":"cm","amount":1},{"kind":"cm","amount":2}]}',
       unit.c(unit(1, "cm"), unit(2, "cm")), to = "mm", structure = TRUE),
  case("unit-c-mixed", "convertUnit(unit.c(unit(1:2, 'cm'), unit(3, 'mm')), 'cm', valueOnly=TRUE)",
       '{"op":"unit_c","args":[{"kind":"cm","amount":[1,2]},{"kind":"mm","amount":3}]}',
       unit.c(unit(1:2, "cm"), unit(3, "mm")), structure = TRUE),
  case("unit-c-flatten", "convertUnit(unit.c(unit(1, 'null'), unit.c(unit(2, 'cm'), unit(3, 'mm'))), 'cm', valueOnly=TRUE)",
       '{"op":"unit_c","args":[{"kind":"null","amount":1},{"op":"unit_c","args":[{"kind":"cm","amount":2},{"kind":"mm","amount":3}]}]}',
       unit.c(unit(1, "null"), unit.c(unit(2, "cm"), unit(3, "mm"))), structure = TRUE),
  case("unit-c-compound", "convertUnit(unit.c(unit(1, 'cm') + unit(1, 'mm'), unit(2, 'cm')), 'cm', valueOnly=TRUE)",
       '{"op":"unit_c","args":[{"op":"add","args":[{"kind":"cm","amount":1},{"kind":"mm","amount":1}]},{"kind":"cm","amount":2}]}',
       unit.c(unit(1, "cm") + unit(1, "mm"), unit(2, "cm")), structure = TRUE),
  case("npc-vector", "convertUnit(unit(1:3, 'npc'), 'cm', valueOnly=TRUE)",
       '{"kind":"npc","amount":[1,2,3]}', unit(1:3, "npc"), structure = TRUE),
  case("pmax-no-args", "convertUnit(unit.pmax(), 'cm', valueOnly=TRUE)",
       '{"op":"pmax","args":[]}', unit.pmax(), structure = TRUE),
  case("psum-no-args", "convertUnit(unit.psum(), 'cm', valueOnly=TRUE)",
       '{"op":"psum","args":[]}', unit.psum(), structure = TRUE),

  # ---- 浮点边界（tolerance = 0：逐位一致） -------------------------------
  case("rounding-cm-sum-to-mm", "convertUnit(unit(0.1, 'cm') + unit(0.2, 'cm'), 'mm', valueOnly=TRUE)",
       '{"op":"add","args":[{"kind":"cm","amount":0.1},{"kind":"cm","amount":0.2}]}',
       unit(0.1, "cm") + unit(0.2, "cm"), to = "mm", tolerance = 0),
  case("rounding-third-npc", "convertUnit(unit(1/3, 'npc'), 'cm', valueOnly=TRUE)",
       '{"kind":"npc","amount":0.3333333333333333}', unit(1 / 3, "npc"), tolerance = 0),
  case("rounding-division-mm-pt", "convertUnit(unit(1, 'mm') / 3, 'pt', valueOnly=TRUE)",
       '{"op":"div","scalar":3,"arg":{"kind":"mm","amount":1}}',
       unit(1, "mm") / 3, to = "pt", tolerance = 0),

  # ---- 不该支持的目标单位（R 抛错，Python 也抛错） -----------------------
  case("to-strwidth-errors", "convertUnit(unit(1, 'cm'), 'strwidth', valueOnly=TRUE)",
       '{"kind":"cm","amount":1}', unit(1, "cm"), to = "strwidth", expect_error = TRUE),
  case("to-strheight-errors", "convertUnit(unit(1, 'cm'), 'strheight', valueOnly=TRUE)",
       '{"kind":"cm","amount":1}', unit(1, "cm"), to = "strheight", expect_error = TRUE),
  case("to-null-errors", "convertUnit(unit(1, 'cm'), 'null', valueOnly=TRUE)",
       '{"kind":"cm","amount":1}', unit(1, "cm"), to = "null", expect_error = TRUE),
  case("to-snpc-errors", "convertUnit(unit(2.54, 'cm'), 'snpc', valueOnly=TRUE)",
       '{"kind":"cm","amount":2.54}', unit(2.54, "cm"), to = "snpc", expect_error = TRUE),

  # ---- 空单位：R 4.5.3 造不出来，Python 侧有定义 -------------------------
  case("empty-unit-python-only", "unit.c()",
       '{"op":"empty"}', NULL, python_only = TRUE,
       python_expect = list(length = 0, convert_to_cm = numeric(0)),
       note = "R 4.5.3: unit.c() -> attempt to set an attribute on NULL"),

  # ---- 零尺寸视口：相对单位直通，绝对单位报错 ----------------------------
  case("zero-dimension-npc-to-npc", "convertUnit(unit(0.5, 'npc'), 'npc', valueOnly=TRUE)  # width=0cm",
       '{"kind":"npc","amount":0.5}', unit(0.5, "npc"), to = "npc", width_cm = 0),
  case("zero-dimension-zero-cm-to-npc", "convertUnit(unit(0, 'cm'), 'npc', valueOnly=TRUE)  # width=0cm",
       '{"kind":"cm","amount":0}', unit(0, "cm"), to = "npc", width_cm = 0),
  case("zero-dimension-zero-native-to-npc", "convertUnit(unit(0, 'native'), 'npc', valueOnly=TRUE)  # width=0cm",
       '{"kind":"native","amount":0}', unit(0, "native"), to = "npc", width_cm = 0),
  case("zero-dimension-cm-to-npc-errors", "convertUnit(unit(1, 'cm'), 'npc', valueOnly=TRUE)  # width=0cm",
       '{"kind":"cm","amount":1}', unit(1, "cm"), to = "npc", width_cm = 0,
       expect_error = TRUE)
)

# ---------------------------------------------------------------------------
# 跑用例
# ---------------------------------------------------------------------------

pdf(NULL, width = 10, height = 10)

records <- lapply(cases, function(c) {
  pushViewport(viewport(
    width = unit(c$width_cm, "cm"), height = unit(c$height_cm, "cm"),
    xscale = c$xscale, yscale = c$yscale,
    gp = gpar(fontsize = c$fontsize, cex = c$cex, lineheight = c$lineheight)
  ))
  on.exit(popViewport(), add = TRUE)

  metrics <- list()
  for (txt in c$strings) {
    metrics[[txt]] <- list(
      width = convertUnit(stringWidth(txt), "inches", valueOnly = TRUE),
      height = convertUnit(stringHeight(txt), "inches", valueOnly = TRUE)
    )
  }

  if (c$python_only) {
    err <- tryCatch({
      eval(parse(text = c$r))
      NULL
    }, error = function(e) conditionMessage(e))
    return(list(
      id = c$id, r = c$r, spec = c$spec, python_only = TRUE,
      context = list(
        width_cm = c$width_cm, height_cm = c$height_cm,
        xscale = c$xscale, yscale = c$yscale,
        fontsize = c$fontsize, cex = c$cex, lineheight = c$lineheight,
        metrics = metrics
      ),
      convert = list(
        axis_from = c$axis_from, type_from = c$type_from,
        axis_to = c$axis_to, type_to = c$type_to, unit_to = c$to
      ),
      expected = NULL, r_error = err, tolerance = c$tolerance,
      structure = NULL, length = NULL, simple = NULL, types = NULL,
      python_expect = c$python_expect, note = c$note
    ))
  }

  u <- force(c$unit)
  err <- NULL
  values <- tryCatch(
    convertUnit(
      u, c$to,
      axisFrom = c$axis_from, typeFrom = c$type_from,
      axisTo = c$axis_to, typeTo = c$type_to,
      valueOnly = TRUE
    ),
    error = function(e) {
      err <<- conditionMessage(e)
      NULL
    }
  )
  if (is.null(err) && c$expect_error) {
    stop(c$id, ": R did not fail but the case expects an error")
  }
  if (!is.null(err) && !c$expect_error) {
    stop(c$id, ": unexpected R error: ", err)
  }

  list(
    id = c$id, r = c$r, spec = c$spec, python_only = FALSE,
    context = list(
      width_cm = c$width_cm, height_cm = c$height_cm,
      xscale = c$xscale, yscale = c$yscale,
      fontsize = c$fontsize, cex = c$cex, lineheight = c$lineheight,
      metrics = metrics
    ),
    convert = list(
      axis_from = c$axis_from, type_from = c$type_from,
      axis_to = c$axis_to, type_to = c$type_to, unit_to = c$to
    ),
    expected = values, r_error = err, tolerance = c$tolerance,
    structure = if (c$structure) unit_struct(u) else NULL,
    length = if (c$structure) length(u) else NULL,
    simple = if (c$structure) grid:::is.simpleUnit(u) else NULL,
    types = if (c$structure) as.list(unitType(u)) else NULL,
    python_expect = NULL, note = c$note
  )
})

dev.off()

document <- list(
  r_version = R.version.string,
  generated_by = "tools/refs/units_ref.R",
  device = list(type = "pdf(NULL)", width_in = 10, height_in = 10),
  cases = records
)

dir.create(dirname(out_path), showWarnings = FALSE, recursive = TRUE)
writeLines(to_json(document), out_path)
cat("wrote ", out_path, " (", length(records), " cases, ", R.version.string, ")\n", sep = "")
