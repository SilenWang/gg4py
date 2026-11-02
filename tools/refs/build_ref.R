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
# 覆盖五张图（issue 的验收清单）：
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
    list(name = name, kind = column_kind(values), values = vector_json(values))
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

datasets <- list(
  mpg = dataframe_json(mpg_data),
  boxes = dataframe_json(boxes)
)

# ---------------------------------------------------------------------------
# 五张图
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
  )
)

cases <- list()
for (item in plots) {
  build <- suppressWarnings(ggplot_build(item$plot))
  if (length(build$data) != 1L) {
    stop(item$id, ": expected exactly one layer, got ", length(build$data))
  }
  data <- build$data[[1]]
  cases[[length(cases) + 1L]] <- list(
    id = item$id,
    title = item$title,
    dataset = item$dataset,
    code = item$code,
    layer = 1L,
    rows = nrow(data),
    columns = dataframe_json(data)$columns
  )
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
