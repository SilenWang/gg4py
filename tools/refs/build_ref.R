#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/build_r_reference.json —— M1-3 图层流水线的 R 侧参考值。
#
#   pixi run -e refs refs:build
#
# 对每张图调 `ggplot_build(p)$data[[i]]`，把内置数据的**列名、列序、类型、
# 每一行的值**原样落进 JSON；Python 侧 `ggcore.build.build_plot()` 产出的
# `LayerBuild.data` 用同一套列名/列序/值对拍（tests/test_build_r_parity.py）。
#
# 覆盖 17 张图（前 5 张是 issue 的验收清单，其余 12 张见 docs/notes/build.md §9）：
#   1. point_computed        mpg / cyl 计算列
#   2. count_bar             stat = "count" 的柱
#   3. box_precomputed       boxplot 预计算（stat = "identity"，列全部给好）
#   4. stacked_bar_interaction  双离散 aes（x=drv, fill=class）的 interaction + stack
#   5. layer_data_override   层级 data 覆盖 plot data
#
# 数值用 %.17g（double 可无损往返）；NA → null；因子按字符串、logical 按布尔。
# 数据集本身也一起落进 JSON，Python 侧不依赖 R / mpg 包即可重放。

suppressPackageStartupMessages(library(ggplot2))

if (!isTRUE(l10n_info()[["UTF-8"]])) {
  stop("R 不在 UTF-8 locale 下：用 `LC_ALL=C.UTF-8 LANG=C.UTF-8` 重跑")
}

out_path <- "tests/fixtures/build_r_reference.json"

# ---------------------------------------------------------------------------
# 极简 JSON 输出（不引入 jsonlite，与 tools/refs/text_ref.R 同一份）
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
  stop("to_json: unsupported value")
}

# 向量 → JSON 数组（NA → null）。因子先转字符，保持 R 的水平顺序。
vector_json <- function(values) {
  if (is.factor(values)) {
    values <- as.character(values)
  }
  lapply(seq_along(values), function(i) {
    value <- values[[i]]
    if (length(value) == 0L || (length(value) == 1L && is.na(value))) NULL else value
  })
}

column_kind <- function(values) {
  if (is.logical(values)) return("bool")
  if (is.integer(values)) return("int")
  if (inherits(values, "mapped_discrete")) return("float")
  if (is.numeric(values)) return("float")
  if (is.factor(values) || is.character(values)) return("str")
  stop("column_kind: unsupported column class ", class(values)[1])
}

dataframe_json <- function(data) {
  rows <- nrow(data)
  columns <- lapply(names(data), function(name) {
    values <- data[[name]]
    column <- list(name = name, kind = column_kind(values), values = vector_json(values))
    # categorical（factor）的顺序是标度顺序，Python 侧要能重建同一列。
    if (is.factor(values)) {
      column$levels <- as.list(levels(values))
    }
    column
  })
  names(columns) <- NULL
  list(rows = rows, columns = columns)
}

# ---------------------------------------------------------------------------
# 数据集（Python 侧重建同一张 ColumnTable）
# ---------------------------------------------------------------------------

boxes <- data.frame(
  g = c("a", "b", "c", "d"),
  lo = c(1, 2, 3, 4),
  hi = c(5, 6, 7, 8),
  mid = c(3, 4, 5, 6),
  y0 = c(0, 1, 2, 3),
  y1 = c(9, 10, 11, 12),
  stringsAsFactors = FALSE
)

mpg_data <- data.frame(
  displ = mpg$displ,
  hwy = mpg$hwy,
  cyl = mpg$cyl,
  class = as.character(mpg$class),
  drv = as.character(mpg$drv),
  stringsAsFactors = FALSE
)

# 夹具外 5 类的补充数据（NA / 参数 / 行序 / aes 名称序）。
na_point <- data.frame(
  x = 1:5,
  y = 1:5,
  g = c("a", "b", NA, "a", "b"),
  stringsAsFactors = FALSE
)
na_x <- data.frame(
  xs = c("a", "b", "a", "c", NA, "b"),
  stringsAsFactors = FALSE
)
col_data <- data.frame(
  xs = c("a", "b", "a", "c", NA, "b"),
  ys = 1:6,
  stringsAsFactors = FALSE
)
line_data <- data.frame(
  x = c(3, 1, 2, 1),
  y = c(1, 2, 3, 4),
  g = c("a", "a", "a", "b"),
  stringsAsFactors = FALSE
)
categorical_data <- data.frame(
  x = 1:3,
  y = 1:3,
  g = factor(c("b", "a", "b"), levels = c("b", "a"))
)
bool_data <- data.frame(
  x = c(TRUE, FALSE, TRUE),
  y = 1:3
)
multi_data <- data.frame(
  cls = c("compact", "compact", "compact", "midsize", "suv"),
  drv = c("f", "f", "f", "f", "r"),
  stringsAsFactors = FALSE
)
neg_data <- data.frame(
  g = rep(c("p", "q"), each = 4),
  x = rep(c("one", "two"), 4),
  y = c(3, -2, 1, 4, -1, 2, 5, -3),
  stringsAsFactors = FALSE
)

datasets <- list(
  mpg = dataframe_json(mpg_data),
  boxes = dataframe_json(boxes),
  na_point = dataframe_json(na_point),
  na_x = dataframe_json(na_x),
  col_data = dataframe_json(col_data),
  line_data = dataframe_json(line_data),
  categorical_data = dataframe_json(categorical_data),
  bool_data = dataframe_json(bool_data),
  multi_data = dataframe_json(multi_data),
  neg_data = dataframe_json(neg_data)
)

# ---------------------------------------------------------------------------
# 17 张图
# ---------------------------------------------------------------------------

mpg_cyl4 <- mpg_data[mpg_data$cyl == 4, , drop = FALSE]

plots <- list(
  list(
    id = "point_computed",
    title = "mpg/cyl 计算列（point）",
    dataset = "mpg",
    code = 'ggplot(mpg, aes(x = displ, y = hwy / cyl)) + geom_point()',
    plot = ggplot(mpg_data, aes(x = displ, y = hwy / cyl)) + geom_point()
  ),
  list(
    id = "count_bar",
    title = "stat = count 的柱（离散 x）",
    dataset = "mpg",
    code = 'ggplot(mpg, aes(x = class)) + geom_bar()',
    plot = ggplot(mpg_data, aes(x = class)) + geom_bar()
  ),
  list(
    id = "box_precomputed",
    title = "boxplot 预计算（stat = identity + 显式五数）",
    dataset = "boxes",
    code = paste0(
      'ggplot(boxes, aes(x = g)) + geom_boxplot(stat = "identity", position = "identity",',
      ' aes(lower = lo, upper = hi, middle = mid, ymin = y0, ymax = y1))'
    ),
    plot = ggplot(boxes, aes(x = g)) +
      geom_boxplot(
        stat = "identity",
        position = "identity",
        aes(lower = lo, upper = hi, middle = mid, ymin = y0, ymax = y1)
      )
  ),
  list(
    id = "stacked_bar_interaction",
    title = "双离散 aes（x = drv, fill = class）的 interaction + stack",
    dataset = "mpg",
    code = 'ggplot(mpg, aes(x = drv, fill = class)) + geom_bar()',
    plot = ggplot(mpg_data, aes(x = drv, fill = class)) + geom_bar()
  ),
  list(
    id = "layer_data_override",
    title = "层级 data 覆盖 plot data（mpg[cyl == 4, ]）",
    dataset = "mpg",
    code = paste0(
      'ggplot(mpg, aes(x = displ, y = hwy)) + ',
      'geom_point(data = mpg[mpg$cyl == 4, ])'
    ),
    plot = ggplot(mpg_data, aes(x = displ, y = hwy)) + geom_point(data = mpg_cyl4)
  ),
  list(
    id = "point_na_colour",
    title = "缺失值保留（colour = NA 的点，NA 也是一个 group 水平）",
    dataset = "na_point",
    code = 'ggplot(na_point, aes(x, y, colour = g)) + geom_point()',
    plot = ggplot(na_point, aes(x, y, colour = g)) + geom_point()
  ),
  list(
    id = "count_na_x",
    title = "stat = count 的 NA x 是一根独立的柱",
    dataset = "na_x",
    code = 'ggplot(na_x, aes(xs)) + geom_bar()',
    plot = ggplot(na_x, aes(xs)) + geom_bar()
  ),
  list(
    id = "col_identity",
    title = "geom_col()：identity stat + flipped_aes / 锚点列序（含 x = NA 行）",
    dataset = "col_data",
    code = 'ggplot(col_data, aes(xs, ys)) + geom_col()',
    plot = ggplot(col_data, aes(xs, ys)) + geom_col()
  ),
  list(
    id = "col_width_param",
    title = "geom_col(width = 0.3)：层参数写进 data，xmin/xmax 跟着变",
    dataset = "col_data",
    code = 'ggplot(col_data, aes(xs, ys)) + geom_col(width = 0.3)',
    plot = ggplot(col_data, aes(xs, ys)) + geom_col(width = 0.3)
  ),
  list(
    id = "line_unsorted",
    title = "geom_line()：按 (PANEL, group, x) 重排行序 + flipped_aes",
    dataset = "line_data",
    code = 'ggplot(line_data, aes(x, y, group = g)) + geom_line()',
    plot = ggplot(line_data, aes(x, y, group = g)) + geom_line()
  ),
  list(
    id = "point_params",
    title = 'geom_point(colour = "red", size = 3)：字面参数覆盖 default_aes',
    dataset = "mpg",
    code = 'ggplot(mpg, aes(displ, hwy)) + geom_point(colour = "red", size = 3)',
    plot = ggplot(mpg_data, aes(displ, hwy)) + geom_point(colour = "red", size = 3)
  ),
  list(
    id = "bar_fill_param",
    title = 'geom_bar(fill = "steelblue")：fill 参数写进 data',
    dataset = "mpg",
    code = 'ggplot(mpg, aes(class)) + geom_bar(fill = "steelblue")',
    plot = ggplot(mpg_data, aes(class)) + geom_bar(fill = "steelblue")
  ),
  list(
    id = "aes_reordered",
    title = "aes(y =, x =)：列序仍为 x, y（上游 aes() 把 x/y 放最前）",
    dataset = "mpg",
    code = 'ggplot(mpg, aes(y = hwy, x = displ)) + geom_point()',
    plot = ggplot(mpg_data, aes(y = hwy, x = displ)) + geom_point()
  ),
  list(
    id = "categorical_group",
    title = "categorical（factor levels 反序）的 group 编号按 levels，不按字母序",
    dataset = "categorical_data",
    code = 'ggplot(categorical_data, aes(x, y, colour = g)) + geom_point()',
    plot = ggplot(categorical_data, aes(x, y, colour = g)) + geom_point()
  ),
  list(
    id = "bool_discrete_x",
    title = "逻辑 x：默认离散位置标度编码成 1/2（FALSE 先）",
    dataset = "bool_data",
    code = 'ggplot(bool_data, aes(x, y)) + geom_point()',
    plot = ggplot(bool_data, aes(x, y)) + geom_point()
  ),
  list(
    id = "multi_layer_levels",
    title = "多层离散 x：跨层水平全局排序后编码",
    dataset = "multi_data",
    code = 'ggplot(multi_data, aes(x = cls)) + geom_bar() + geom_bar(aes(x = drv))',
    plot = ggplot(multi_data, aes(x = cls)) + geom_bar() + geom_bar(aes(x = drv))
  ),
  list(
    id = "col_negative_stack",
    title = "负值 stack：ymin/ymax 是相邻累计高度的 min/max（正负分开堆）",
    dataset = "neg_data",
    code = 'ggplot(neg_data, aes(x, y, fill = g)) + geom_col()',
    plot = ggplot(neg_data, aes(x, y, fill = g)) + geom_col()
  )
)

cases <- list()
for (item in plots) {
  build <- suppressWarnings(ggplot_build(item$plot))
  if (length(build$data) < 1L) {
    stop(item$id, ": expected at least one layer")
  }
  layer_records <- lapply(build$data, dataframe_json)
  record <- list(
    id = item$id,
    title = item$title,
    dataset = item$dataset,
    code = item$code,
    layer = 1L,
    rows = layer_records[[1]]$rows,
    columns = layer_records[[1]]$columns
  )
  if (length(layer_records) > 1L) {
    record$layers <- layer_records
  }
  labels <- tryCatch(
    build$layout$panel_params[[1]]$x$get_labels(),
    error = function(e) NULL
  )
  if (!is.null(labels)) {
    record$x_labels <- as.list(labels)
  }
  cases[[length(cases) + 1L]] <- record
}

document <- list(
  generated_by = "tools/refs/build_ref.R",
  r_version = R.version.string,
  ggplot2_version = as.character(packageVersion("ggplot2")),
  locale = "C.UTF-8",
  datasets = datasets,
  cases = cases
)

dir.create(dirname(out_path), recursive = TRUE, showWarnings = FALSE)
writeLines(to_json(document), out_path)
cat(sprintf(
  "wrote %s (%d cases, %d datasets, ggplot2 %s)\n",
  out_path, length(cases), length(datasets), document$ggplot2_version
))
