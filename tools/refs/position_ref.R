#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/position_r_reference.json —— M1-9 位置调整的 R 侧参考值。
#
#   pixi run -e refs refs:position
#
# 对每个 case：
#   1. 用一个「探针」Position 包住真正的 position_*()，在 `setup_data()` 的
#      入口把**位置调整之前**的图层数据（geom setup_data() 之后：x / y /
#      xmin / xmax / ymin / ymax / PANEL / group / flipped_aes）录下来；
#   2. 正常 `ggplot_build(p)$data[[1]]`，把位置调整之后的同名列逐行录下来；
#   3. 自检：探针包装不得改变输出（与直接 `position_*()` 的结果逐个 all.equal）。
#
# Python 侧（tests/test_position_r_parity.py）拿第 1 步的输入喂给
# `ggcore.position` 的同一实现，与第 2 步逐行对拍 —— 不重放整条流水线，
# 所以夹具只钉「位置调整」这一个阶段的语义（stat / geom / scale 各有自己的夹具）。
#
# 数值用 %.17g（double 可无损往返）；NA → null。jitter 的随机流在 R 与 Python
# 之间不可能一致（R 是 Mersenne-Twister + runif，ggcore 用 np.random.default_rng
# 的 PCG64），所以它的输出值只作为「R 的包络」记录，Python 侧比包络与可复现性；
# 这一点写在 docs/notes/position.md 的「差异面」里。

suppressPackageStartupMessages(library(ggplot2))

if (!isTRUE(l10n_info()[["UTF-8"]])) {
  stop("R 不在 UTF-8 locale 下：用 `LC_ALL=C.UTF-8 LANG=C.UTF-8` 重跑")
}

out_path <- "tests/fixtures/position_r_reference.json"

# ---------------------------------------------------------------------------
# 极简 JSON 输出（与 tools/refs/scales_ref.R 同一份）
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

# 向量 → JSON 数组（NA → null）。因子先转字符。
vector_json <- function(values) {
  if (is.factor(values)) {
    values <- as.character(values)
  }
  lapply(seq_along(values), function(i) {
    value <- values[[i]]
    if (length(value) == 0L || (length(value) == 1L && is.na(value))) NULL else unname(value)
  })
}

# 参数值：NULL 原样、长度 1 落成标量、其余落成数组。
param_json <- function(value) {
  if (is.null(value)) {
    return(NULL)
  }
  if (length(value) == 1L) {
    return(unname(value))
  }
  as.list(unname(value))
}

# 一列数据 → {name, kind, values}；kind 与 ggcore.data.Column 的语义类型对齐。
column_json <- function(name, values) {
  if (is.factor(values)) {
    kind <- "str"
    values <- as.character(values)
  } else if (is.logical(values)) {
    kind <- "bool"
  } else if (is.integer(values)) {
    kind <- "int"
  } else if (is.numeric(values)) {
    kind <- "float"
  } else {
    kind <- "str"
    values <- as.character(values)
  }
  list(name = name, kind = kind, values = vector_json(values))
}

# 位置相关的列（输入侧还要 PANEL / flipped_aes / group）。
POSITION_COLUMNS <- c(
  "x", "y", "xmin", "xmax", "ymin", "ymax", "PANEL", "group", "flipped_aes", "order"
)

columns_json <- function(data, wanted = POSITION_COLUMNS) {
  present <- intersect(wanted, colnames(data))
  lapply(present, function(name) column_json(name, data[[name]]))
}

#: `resolution()` 不在 ggplot2 的导出名单里（它是 compute_jitter() 的闭包伙伴），
#: 但 jitter 的缺省 width/height 就是 `resolution(x, zero = FALSE, discrete = TRUE) * 0.4`，
#: 所以直接从命名空间取同一个函数，保证夹具与上游同源。
resolution <- get("resolution", envir = asNamespace("ggplot2"))

# ---------------------------------------------------------------------------
# 探针 Position：记录 setup_data() 的输入与 setup_params() 的解析结果
# ---------------------------------------------------------------------------

probe_position <- function(inner, record_env) {
  probe <- ggproto(NULL, inner)
  probe$setup_params <- function(self, data) {
    params <- inner$setup_params(data)
    record_env$params <- params
    params
  }
  probe$setup_data <- function(self, data, params) {
    record_env$input <- data
    inner$setup_data(data, params)
  }
  probe$compute_panel <- function(self, data, params, scales) {
    record_env$panel_input <- data
    inner$compute_panel(data, params, scales)
  }
  probe
}

# ---------------------------------------------------------------------------
# case 记录
# ---------------------------------------------------------------------------

#: 每个 case 的（注册名, 标题, R 代码, 图, position 构造函数, 用户侧参数）。
#: `args` 是 Python 侧 `registry.construct("position", name, **args)` 的实参。
record <- function(id, name, title, code, plot_expr, position_expr, args = list()) {
  inner <- eval(position_expr, envir = globalenv())
  real_plot <- eval(plot_expr, list(position = inner), enclos = globalenv())

  record_env <- new.env(parent = emptyenv())
  probe <- probe_position(inner, record_env)
  probe_plot <- eval(plot_expr, list(position = probe), enclos = globalenv())
  probe_built <- suppressWarnings(ggplot_build(probe_plot))
  real_built <- suppressWarnings(ggplot_build(real_plot))

  # 自检：探针只记录，不改变任何一个值。
  if (!isTRUE(all.equal(probe_built$data[[1]], real_built$data[[1]]))) {
    stop("probe changed the output for case: ", id)
  }
  if (is.null(record_env$input)) {
    stop("probe did not see setup_data() for case: ", id)
  }

  output <- real_built$data[[1]]
  position_params <- lapply(args, param_json)
  if (is.null(names(position_params))) {
    # 空参数也落成 JSON 对象（而不是 []），Python 侧统一按 mapping 用。
    names(position_params) <- character(0)
  }
  # jitter 的 width / height 缺省值是 40% resolution（在 compute_jitter() 里才
  # 解析），随机流又不可能跨语言一致，所以单独把「包络」记下来：Python 侧只要
  # 保证每个抖动值都落在这个半宽内，就说明缺省分辨率算对了。
  envelope <- NULL
  if (name == "jitter") {
    envelope <- list(
      width = resolution(record_env$panel_input$x, zero = FALSE, discrete = TRUE) * 0.4,
      height = resolution(record_env$panel_input$y, zero = FALSE, discrete = TRUE) * 0.4
    )
  }
  list(
    id = id,
    title = title,
    code = code,
    position = name,
    position_params = position_params,
    flipped = isTRUE(record_env$params$flipped_aes),
    params = lapply(record_env$params, param_json),
    envelope = envelope,
    input = columns_json(record_env$input),
    output = columns_json(output),
    output_names = as.list(colnames(output))
  )
}

# ---------------------------------------------------------------------------
# 数据集
# ---------------------------------------------------------------------------

two_groups <- data.frame(
  x = c(1, 1, 2, 2),
  y = c(1, 2, 3, 4),
  g = c("p", "q", "p", "q")
)
uneven <- data.frame(
  x = c(1, 2, 2, 2, 3, 3),
  y = c(1, 2, 3, 4, 5, 6),
  g = c("p", "p", "q", "r", "p", "q")
)
negative <- data.frame(
  x = c(1, 1, 2, 2),
  y = c(2, -1, 3, -2),
  g = c("p", "q", "p", "q")
)
horizontal <- data.frame(
  cat = c("a", "a", "b", "b"),
  val = c(1, 2, 3, 4),
  g = c("p", "q", "p", "q")
)
points <- data.frame(x = c(1, 1, 2, 2), y = c(1, 2, 3, 4))

cases <- list(
  record(
    "stack_two_groups", "stack",
    "stack（默认）：组内按 -group 累加，第一个 group 在最上面",
    "ggplot(two_groups, aes(x, y, fill = g)) + geom_col()",
    quote(ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position)),
    quote(position_stack())
  ),
  record(
    "stack_reverse", "stack",
    "stack(reverse = TRUE)：组内按 group 正序累加",
    "ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position_stack(reverse = TRUE))",
    quote(ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position)),
    quote(position_stack(reverse = TRUE)),
    args = list(reverse = TRUE)
  ),
  record(
    "stack_negative", "stack",
    "stack：负值单独向下堆（ymin/ymax 是相邻累计高度的 min/max）",
    "ggplot(negative, aes(x, y, fill = g)) + geom_col()",
    quote(ggplot(negative, aes(x, y, fill = g)) + geom_col(position = position)),
    quote(position_stack())
  ),
  record(
    "fill_two_groups", "fill",
    "fill：stack 之后每个 x 归一到 0..1",
    "ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = 'fill')",
    quote(ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position)),
    quote(position_fill())
  ),
  record(
    "dodge_two_groups", "dodge",
    "dodge：两组柱并排（width 缺省取柱子宽度，xmin/xmax 由 d_width / n 决定）",
    "ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position_dodge())",
    quote(ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position)),
    quote(position_dodge())
  ),
  record(
    "dodge_preserve_single", "dodge",
    "dodge(preserve = 'single')：n 取所有 x 上的最大组数（不均匀分组）",
    "ggplot(uneven, aes(x, y, fill = g)) + geom_col(position = position_dodge(preserve = 'single'))",
    quote(ggplot(uneven, aes(x, y, fill = g)) + geom_col(position = position)),
    quote(position_dodge(preserve = "single")),
    args = list(preserve = "single")
  ),
  record(
    "dodge2_two_groups", "dodge2",
    "dodge2：按重叠的 x 区间分组 + padding（n 取自每个重叠组）",
    "ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position_dodge2())",
    quote(ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position)),
    quote(position_dodge2())
  ),
  record(
    "dodge2_padding", "dodge2",
    "dodge2(padding = 0.2)：柱宽按 (1 - padding) 缩进",
    "ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position_dodge2(padding = 0.2))",
    quote(ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position)),
    quote(position_dodge2(padding = 0.2)),
    args = list(padding = 0.2)
  ),
  record(
    "dodge_horizontal", "dodge",
    "横向 dodge（flipped_aes = TRUE）：位移作用在 y 上，x 是长度",
    "ggplot(horizontal, aes(x = val, y = cat, fill = g)) + geom_col(orientation = 'y', position = position_dodge())",
    quote(
      ggplot(horizontal, aes(x = val, y = cat, fill = g)) +
        geom_col(orientation = "y", position = position)
    ),
    quote(position_dodge())
  ),
  record(
    "jitter_seed", "jitter",
    "jitter(seed = 42)：缺省 width/height = 40% resolution（值依赖 R 的 RNG）",
    "ggplot(points, aes(x, y)) + geom_point(position = position_jitter(seed = 42))",
    quote(ggplot(points, aes(x, y)) + geom_point(position = position)),
    quote(position_jitter(seed = 42)),
    args = list(seed = 42)
  ),
  record(
    "nudge", "nudge",
    "nudge(x = 0.2, y = 1)：x / y 族整体平移",
    "ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position_nudge(x = 0.2, y = 1))",
    quote(ggplot(two_groups, aes(x, y, fill = g)) + geom_col(position = position)),
    quote(position_nudge(x = 0.2, y = 1)),
    args = list(x = 0.2, y = 1)
  )
)

document <- list(
  generated_by = "tools/refs/position_ref.R",
  r_version = R.version.string,
  ggplot2_version = as.character(packageVersion("ggplot2")),
  locale = "C.UTF-8",
  cases = cases
)

dir.create(dirname(out_path), recursive = TRUE, showWarnings = FALSE)
writeLines(to_json(document), out_path)
cat(sprintf(
  "wrote %s (%d cases, ggplot2 %s)\n",
  out_path, length(cases), document$ggplot2_version
))
