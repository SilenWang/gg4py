#!/usr/bin/env Rscript
#
# M2-6 的 stat 长尾 B 对拍产线：生成
#   tests/fixtures/stat_longtail_r_reference.json
#   docs/cases/stat-*/expected.svg（每个 stat 一条端到端 case）
#
#   pixi run -e refs refs:stat-longtail
#
# 只在「换 pin」或「有意改口径」时重跑；产物入库，CI 不装 R。
#
# 夹具口径与 tools/refs/stat_ref.R 相同（`ggplot_build(p)$data[[1]]` 的列名、
# 列序、kind、逐值 + build / draw 两段 warning），另加两条 M2-6 才需要的东西：
#   - `pos_inf` / `neg_inf`：非有限值在 JSON 里写 null（`fmt_num` 的口径），
#     ±Inf 的位置单独记一份 1 起的行号，`stat_ecdf(pad = TRUE)` 的 ±Inf 才对得上；
#   - `error`：`stat_spoke()` 在 4.0.3 里是 `deprecate_stop()`，记录错误消息而不是数据。

suppressPackageStartupMessages({
  library(ggplot2)
})

if (!identical(as.character(packageVersion("ggplot2")), "4.0.3")) {
  stop(sprintf(
    "ggplot2 必须是 4.0.3（上游 pin），当前是 %s",
    as.character(packageVersion("ggplot2"))
  ))
}
if (!isTRUE(l10n_info()[["UTF-8"]])) {
  stop("R 不在 UTF-8 locale 下：用 `LC_ALL=C.UTF-8 LANG=C.UTF-8` 重跑")
}
for (pkg in c("MASS", "quantreg")) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    stop(sprintf("%s 缺失：refs 环境要装 r-%s（见 pixi.toml 的 feature.refs）", pkg, tolower(pkg)))
  }
}

repo <- normalizePath(".")
fixture_path <- file.path(repo, "tests", "fixtures", "stat_longtail_r_reference.json")

# ---------------------------------------------------------------------------
# 极简 JSON 输出（与 tools/refs/stat_ref.R 同一份，不引入 jsonlite）
# ---------------------------------------------------------------------------

json_escape <- function(text) {
  text <- gsub("\\", "\\\\", text, fixed = TRUE)
  text <- gsub("\"", "\\\"", text, fixed = TRUE)
  text <- gsub("\n", "\\n", text, fixed = TRUE)
  text <- gsub("\t", "\\t", text, fixed = TRUE)
  paste0("\"", text, "\"")
}

fmt_num <- function(value) {
  if (!is.finite(value)) {
    return("null")
  }
  sprintf("%.17g", value)
}

to_json <- function(x, indent = 0L) {
  pad <- strrep("  ", indent)
  pad2 <- strrep("  ", indent + 1L)
  if (is.null(x)) {
    return("null")
  }
  if (is.atomic(x) && length(x) == 1L && is.na(x)) {
    return("null")
  }
  if (is.atomic(x) && length(x) > 1L) {
    items <- vapply(seq_along(x), function(i) to_json(x[[i]], indent), character(1))
    return(paste0("[", paste(items, collapse = ", "), "]"))
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

vector_json <- function(values) {
  if (is.factor(values)) {
    values <- as.character(values)
  }
  lapply(seq_along(values), function(i) values[[i]])
}

column_kind <- function(values) {
  if (is.list(values)) return("list")
  if (is.logical(values)) return("bool")
  if (is.integer(values)) return("int")
  if (inherits(values, "mapped_discrete")) return("float")
  if (is.numeric(values)) return("float")
  if (is.factor(values) || is.character(values)) return("str")
  stop("column_kind: unsupported column class ", class(values)[1])
}

dataframe_json <- function(data) {
  columns <- lapply(names(data), function(name) {
    values <- data[[name]]
    column <- list(name = name, kind = column_kind(values), values = vector_json(values))
    if (is.factor(values)) {
      column$levels <- as.list(levels(values))
    }
    if (is.numeric(values) || inherits(values, "mapped_discrete")) {
      # ±Inf 在 JSON 里只能是 null；位置单独记（1 起），Python 侧还原成 ±Inf。
      column$pos_inf <- as.list(which(is.infinite(values) & values > 0))
      column$neg_inf <- as.list(which(is.infinite(values) & values < 0))
    }
    column
  })
  names(columns) <- NULL
  list(rows = nrow(data), columns = columns)
}

# ---------------------------------------------------------------------------
# 采集：build + draw 两段的 warning 都记下来（不留下设备文件）
# ---------------------------------------------------------------------------

collect <- function(expr) {
  messages <- character()
  grDevices::pdf(file = tempfile(fileext = ".pdf"))
  on.exit(grDevices::dev.off(), add = TRUE)
  value <- withCallingHandlers(
    expr,
    warning = function(w) {
      messages <<- c(messages, conditionMessage(w))
      invokeRestart("muffleWarning")
    }
  )
  list(value = value, warnings = messages)
}

record_case <- function(name, plot, description, stat) {
  built <- collect(ggplot_build(plot))
  drawn <- collect(invisible(ggplotGrob(plot)))
  list(
    description = description,
    stat = stat,
    built = dataframe_json(built$value$data[[1]]),
    warnings = as.list(unique(c(built$warnings, drawn$warnings)))
  )
}

record_error <- function(name, expr, description, stat) {
  message <- tryCatch(
    {
      force(expr)
      NA_character_
    },
    error = function(e) conditionMessage(e)
  )
  list(description = description, stat = stat, error = message)
}

# ---------------------------------------------------------------------------
# 数据集（Python 侧的 tests/test_stat_longtail_r_parity.py 用同一份数字）
# ---------------------------------------------------------------------------

df_ld <- data.frame(v = c(1.2, 2.4, 2.9, 3.1, 3.8, 4.5, 5.1, 5.2, 6.0, 7.7))
df_grp <- data.frame(
  g = rep(c("a", "b"), each = 6),
  y = c(1, 2, 3, 4, 5, 6, 2, 3, 4, 5, 6, 7),
  stringsAsFactors = FALSE
)
df_dup <- data.frame(
  x = c(1, 1, 2, 2, 2),
  y = c(1, 1, 2, 3, 3)
)
df_w <- data.frame(x = c(1, 2, 2, 3, 5, 7), w = c(1, 1, 2, 1, 1, 3))
df_lin <- data.frame(x = 1:12, y = c(1, 2, 1.5, 3, 2.5, 4, 3.5, 5, 4.5, 6, 5.5, 7))
df_ell <- data.frame(x = 1:8, y = c(2, 1, 3, 2, 5, 4, 6, 7))
df_ellw <- data.frame(x = 1:8, y = c(2, 1, 3, 2, 5, 4, 6, 7), w = c(1, 1, 1, 1, 1, 1, 5, 5))
df_ell_grp <- data.frame(
  x = rep(1:8, 2),
  y = c(2, 1, 3, 2, 5, 4, 6, 7, 3, 2, 4, 3, 6, 5, 7, 8),
  g = rep(c("a", "b"), each = 8),
  stringsAsFactors = FALSE
)

# ---------------------------------------------------------------------------
# case
# ---------------------------------------------------------------------------

cases <- list()

# --- stat_qq / stat_qq_line -------------------------------------------------
cases$qq_norm <- record_case(
  "qq_norm",
  ggplot(df_ld, aes(sample = v)) + stat_qq(),
  "qq：默认正态理论分位数（ppoints + qnorm）", "qq"
)
cases$qq_t <- record_case(
  "qq_t",
  ggplot(df_ld, aes(sample = v)) + stat_qq(distribution = qt, dparams = list(df = 5)),
  "qq：distribution = qt、dparams = list(df = 5)", "qq"
)
cases$qq_quantiles <- record_case(
  "qq_quantiles",
  ggplot(df_ld, aes(sample = v)) +
    stat_qq(quantiles = seq(0.05, 0.95, length.out = 10)),
  "qq：显式 quantiles（长度必须等于样本数）", "qq"
)
cases$qq_group <- record_case(
  "qq_group",
  ggplot(df_grp, aes(sample = y, colour = g)) + stat_qq(),
  "qq：两个 group 各自画一条 qq", "qq"
)
cases$qqline_norm <- record_case(
  "qqline_norm",
  ggplot(df_ld, aes(sample = v)) + stat_qq_line(geom = "line"),
  "qq_line：line.p = c(0.25, 0.75) 的默认口径", "qq_line"
)
cases$qqline_fullrange <- record_case(
  "qqline_fullrange",
  ggplot(df_ld, aes(sample = v)) +
    stat_qq_line(geom = "line", fullrange = TRUE) +
    scale_x_continuous(limits = c(-3, 3)),
  "qq_line：fullrange = TRUE（x 取标度范围）", "qq_line"
)
cases$qqline_quantiles <- record_case(
  "qqline_quantiles",
  ggplot(df_ld, aes(sample = v)) +
    stat_qq_line(geom = "line", quantiles = seq(0.05, 0.95, length.out = 10), line.p = c(0.1, 0.9)),
  "qq_line：显式 quantiles + line.p", "qq_line"
)

# --- stat_ecdf --------------------------------------------------------------
cases$ecdf_default <- record_case(
  "ecdf_default",
  ggplot(df_ld, aes(x = v)) + stat_ecdf(geom = "line"),
  "ecdf：默认 pad = TRUE（±Inf 两端）", "ecdf"
)
cases$ecdf_nopad <- record_case(
  "ecdf_nopad",
  ggplot(df_ld, aes(x = v)) + stat_ecdf(geom = "line", pad = FALSE),
  "ecdf：pad = FALSE", "ecdf"
)
cases$ecdf_n <- record_case(
  "ecdf_n",
  ggplot(df_ld, aes(x = v)) + stat_ecdf(geom = "line", n = 5),
  "ecdf：n = 5（等距插值网格）", "ecdf"
)
cases$ecdf_weight <- record_case(
  "ecdf_weight",
  ggplot(df_w, aes(x = x, weight = w)) + stat_ecdf(geom = "line"),
  "ecdf：weight 美学（按权重增量）", "ecdf"
)
cases$ecdf_group <- record_case(
  "ecdf_group",
  ggplot(df_grp, aes(x = y, colour = g)) + stat_ecdf(geom = "line"),
  "ecdf：两个 group 各自的阶梯", "ecdf"
)
cases$ecdf_horizontal <- record_case(
  "ecdf_horizontal",
  ggplot(df_ld, aes(y = v)) + stat_ecdf(geom = "line"),
  "ecdf：横向（只映射 y，flipped_aes = TRUE）", "ecdf"
)

# --- stat_ellipse -----------------------------------------------------------
cases$ellipse_t <- record_case(
  "ellipse_t",
  ggplot(df_ell, aes(x, y)) + stat_ellipse(type = "t", geom = "path"),
  "ellipse：type = 't'（MASS::cov.trob）", "ellipse"
)
cases$ellipse_norm <- record_case(
  "ellipse_norm",
  ggplot(df_ell, aes(x, y)) + stat_ellipse(type = "norm", geom = "path"),
  "ellipse：type = 'norm'（cov.wt）", "ellipse"
)
cases$ellipse_euclid <- record_case(
  "ellipse_euclid",
  ggplot(df_ell, aes(x, y)) + stat_ellipse(type = "euclid", level = 3, geom = "path"),
  "ellipse：type = 'euclid'、level = 3（半径口径）", "ellipse"
)
cases$ellipse_weight <- record_case(
  "ellipse_weight",
  ggplot(df_ellw, aes(x, y, weight = w)) +
    stat_ellipse(type = "norm", geom = "path"),
  "ellipse：weight 美学 + type = 'norm'", "ellipse"
)
cases$ellipse_group <- record_case(
  "ellipse_group",
  ggplot(df_ell_grp, aes(x, y, colour = g)) +
    stat_ellipse(type = "norm", geom = "path"),
  "ellipse：两个 group 各自一条椭圆", "ellipse"
)

# --- stat_quantile ----------------------------------------------------------
quiet <- function(expr) {
  suppressMessages(expr)
}
cases$quantile_default <- record_case(
  "quantile_default",
  quiet(ggplot(df_lin, aes(x, y)) + stat_quantile(geom = "line")),
  "quantile：默认 quantiles = c(0.25, 0.5, 0.75)", "quantile"
)
cases$quantile_05 <- record_case(
  "quantile_05",
  quiet(ggplot(df_lin, aes(x, y)) + stat_quantile(quantiles = 0.5, geom = "line")),
  "quantile：单个分位数 0.5", "quantile"
)
cases$quantile_xseq <- record_case(
  "quantile_xseq",
  quiet(ggplot(df_lin, aes(x, y)) +
    stat_quantile(quantiles = c(0.1, 0.9), xseq = c(1, 5, 12), geom = "line")),
  "quantile：xseq 指定预测网格", "quantile"
)

# --- stat_summary -----------------------------------------------------------
cases$summary_mean <- record_case(
  "summary_mean",
  ggplot(df_grp, aes(x = g, y = y)) + stat_summary(fun = "mean", geom = "point"),
  "summary：fun = 'mean'（返回 NA 的 ymin / ymax）", "summary"
)
cases$summary_median <- record_case(
  "summary_median",
  ggplot(df_grp, aes(x = g, y = y)) + stat_summary(fun = "median", geom = "point"),
  "summary：fun = 'median'", "summary"
)
cases$summary_sd <- record_case(
  "summary_sd",
  ggplot(df_grp, aes(x = g, y = y)) + stat_summary(fun = "sd", geom = "point"),
  "summary：fun = 'sd'（n-1 方差）", "summary"
)
cases$summary_minmax <- record_case(
  "summary_minmax",
  ggplot(df_grp, aes(x = g, y = y)) +
    stat_summary(fun = "mean", fun.min = "min", fun.max = "max", geom = "point"),
  "summary：fun + fun.min + fun.max", "summary"
)
cases$summary_mean_se <- record_case(
  "summary_mean_se",
  ggplot(df_grp, aes(x = g, y = y)) +
    stat_summary(fun.data = mean_se, geom = "point"),
  "summary：fun.data = mean_se", "summary"
)
# `mean_sdl` / `mean_cl_boot` / `median_hilow` 是 Hmisc 的包装（ggplot2 4.0.3 只做
# `requireNamespace()`），refs 环境不装 Hmisc，这里用同一公式的内联函数覆盖
# `fun.data` + `fun.args` 两条路径。
sdl <- function(x, mult) {
  data.frame(y = mean(x), ymin = mean(x) - mult * sd(x), ymax = mean(x) + mult * sd(x))
}
cases$summary_fundata_args <- record_case(
  "summary_fundata_args",
  ggplot(df_grp, aes(x = g, y = y)) +
    stat_summary(fun.data = sdl, fun.args = list(mult = 1), geom = "point"),
  "summary：fun.data 可调用 + fun.args", "summary"
)
cases$summary_two_x <- record_case(
  "summary_two_x",
  ggplot(
    data.frame(x = c(1, 1, 2, 2), y = c(1, 3, 2, 6)),
    aes(x, y)
  ) + stat_summary(fun = "mean", geom = "point"),
  "summary：连续 x 的两个取值", "summary"
)
cases$summary_horizontal <- record_case(
  "summary_horizontal",
  ggplot(df_grp, aes(x = y, y = g)) + stat_summary(fun = "mean", geom = "point"),
  "summary：横向（flipped_aes = TRUE）", "summary"
)

# --- stat_summary_bin -------------------------------------------------------
cases$sumbin_bins <- record_case(
  "sumbin_bins",
  ggplot(df_lin, aes(x, y)) +
    stat_summary_bin(fun = "mean", bins = 4, geom = "point"),
  "summary_bin：bins = 4", "summary_bin"
)
cases$sumbin_width <- record_case(
  "sumbin_width",
  ggplot(df_lin, aes(x, y)) +
    stat_summary_bin(fun = "median", binwidth = 3, geom = "point"),
  "summary_bin：binwidth = 3", "summary_bin"
)
cases$sumbin_minmax <- record_case(
  "sumbin_minmax",
  ggplot(df_lin, aes(x, y)) +
    stat_summary_bin(fun = "mean", fun.min = "min", fun.max = "max", bins = 3, geom = "point"),
  "summary_bin：fun + fun.min + fun.max", "summary_bin"
)

# --- stat_sum ---------------------------------------------------------------
cases$sum_default <- record_case(
  "sum_default",
  ggplot(df_dup, aes(x, y)) + stat_sum(),
  "sum：按 (x, y) 计数 + prop", "sum"
)
cases$sum_weight <- record_case(
  "sum_weight",
  ggplot(df_dup, aes(x, y, weight = c(1, 2, 1, 3, 1))) + stat_sum(),
  "sum：weight 美学", "sum"
)
cases$sum_colour <- record_case(
  "sum_colour",
  ggplot(
    data.frame(x = c(1, 1, 1), y = c(1, 1, 2), g = c("a", "a", "b")),
    aes(x, y, colour = g)
  ) + stat_sum(),
  "sum：colour 也参与分组键", "sum"
)
cases$sum_group <- record_case(
  "sum_group",
  ggplot(
    data.frame(x = c(1, 1, 2, 2), y = c(1, 2, 1, 2), g = c("a", "b", "a", "b")),
    aes(x, y, group = g)
  ) + stat_sum(),
  "sum：显式 group 的分母（prop）", "sum"
)

# --- stat_unique ------------------------------------------------------------
cases$unique_default <- record_case(
  "unique_default",
  ggplot(data.frame(x = c(1, 1, 2, 2, 2), y = c(1, 1, 2, 3, 3)), aes(x, y)) +
    stat_unique(),
  "unique：去重行", "unique"
)
cases$unique_colour <- record_case(
  "unique_colour",
  ggplot(
    data.frame(x = c(1, 1, 2), y = c(1, 1, 2), g = c("a", "a", "b")),
    aes(x, y, colour = g)
  ) + stat_unique(),
  "unique：colour 参与去重判断", "unique"
)

# --- stat_density -----------------------------------------------------------
cases$density_default <- record_case(
  "density_default",
  ggplot(df_ld, aes(x = v)) + stat_density(geom = "line", position = "identity"),
  "density：默认 bw = 'nrd0'、n = 512", "density"
)
cases$density_bw <- record_case(
  "density_bw",
  ggplot(df_ld, aes(x = v)) +
    stat_density(geom = "line", position = "identity", bw = 0.5),
  "density：显式 bw = 0.5", "density"
)
cases$density_adjust <- record_case(
  "density_adjust",
  ggplot(df_ld, aes(x = v)) +
    stat_density(geom = "line", position = "identity", adjust = 0.5),
  "density：adjust = 0.5", "density"
)
cases$density_trim <- record_case(
  "density_trim",
  ggplot(df_ld, aes(x = v)) +
    stat_density(geom = "line", position = "identity", trim = TRUE),
  "density：trim = TRUE（from/to 取数据范围）", "density"
)
cases$density_weight <- record_case(
  "density_weight",
  ggplot(df_w, aes(x = x, weight = w)) +
    stat_density(geom = "line", position = "identity"),
  "density：weight 美学", "density"
)
cases$density_group <- record_case(
  "density_group",
  ggplot(df_grp, aes(x = y, colour = g)) +
    stat_density(geom = "line", position = "identity"),
  "density：两个 group 各自一条密度", "density"
)
cases$density_n <- record_case(
  "density_n",
  ggplot(df_ld, aes(x = v)) +
    stat_density(geom = "line", position = "identity", n = 1024),
  "density：n = 1024（R 里取 2 的幂）", "density"
)
cases$density_limits <- record_case(
  "density_limits",
  ggplot(df_ld, aes(x = v)) +
    stat_density(geom = "line", position = "identity") +
    scale_x_continuous(limits = c(0, 10)),
  "density：from/to 取 x 标度的 dimension", "density"
)

# --- stat_function ----------------------------------------------------------
cases$function_sin <- record_case(
  "function_sin",
  ggplot() + stat_function(fun = sin, xlim = c(0, 3), n = 7, geom = "line"),
  "function：fun = sin、xlim = c(0, 3)、n = 7", "function"
)
cases$function_args <- record_case(
  "function_args",
  ggplot() +
    stat_function(fun = function(x, k) x^k, args = list(k = 2), xlim = c(1, 3), n = 5,
                  geom = "line"),
  "function：args = list(k = 2)", "function"
)
cases$function_logy <- record_case(
  "function_logy",
  ggplot() +
    stat_function(fun = exp, xlim = c(0, 2), n = 5, geom = "line") +
    scale_y_log10(),
  "function：y 标度 log10 的变换", "function"
)

# --- stat_connect -----------------------------------------------------------
df_conn <- data.frame(x = c(1, 2, 3), y = c(1, 3, 2))
cases$connect_hv <- record_case(
  "connect_hv",
  ggplot(df_conn, aes(x, y)) + stat_connect(geom = "line"),
  "connect：默认 connection = 'hv'", "connect"
)
cases$connect_mid <- record_case(
  "connect_mid",
  ggplot(df_conn, aes(x, y)) + stat_connect(geom = "line", connection = "mid"),
  "connect：connection = 'mid'", "connect"
)
cases$connect_linear <- record_case(
  "connect_linear",
  ggplot(df_conn, aes(x, y)) + stat_connect(geom = "line", connection = "linear"),
  "connect：connection = 'linear'", "connect"
)
cases$connect_matrix <- record_case(
  "connect_matrix",
  ggplot(df_conn, aes(x, y)) +
    stat_connect(geom = "line", connection = matrix(c(0.4, 0.6, 1, 0.75, 0.25, 1), 3, 2)),
  "connect：自定义 connection 矩阵", "connect"
)

# --- stat_manual ------------------------------------------------------------
cases$manual_subset <- record_case(
  "manual_subset",
  ggplot(df_lin, aes(x, y)) + stat_manual(fun = function(d) d[1:3, ]),
  "manual：fun 只留前 3 行", "manual"
)
cases$manual_identity <- record_case(
  "manual_identity",
  ggplot(df_dup, aes(x, y)) + stat_manual(),
  "manual：缺省 fun = identity", "manual"
)
cases$manual_aggregate <- record_case(
  "manual_aggregate",
  ggplot(df_lin, aes(x, y)) +
    stat_manual(fun = function(d) data.frame(x = mean(d$x), y = mean(d$y))),
  "manual：fun 聚合成一行", "manual"
)

# --- stat_ydensity ----------------------------------------------------------
cases$ydensity_area <- record_case(
  "ydensity_area",
  ggplot(df_grp, aes(x = g, y = y)) +
    stat_ydensity(geom = "line", position = "identity"),
  "ydensity：area 缩放 + 默认分位线", "ydensity"
)
cases$ydensity_width <- record_case(
  "ydensity_width",
  ggplot(df_grp, aes(x = g, y = y)) +
    stat_ydensity(geom = "line", position = "identity", scale = "width"),
  "ydensity：scale = 'width'", "ydensity"
)
cases$ydensity_noquantiles <- record_case(
  "ydensity_noquantiles",
  ggplot(df_grp, aes(x = g, y = y)) +
    stat_ydensity(geom = "line", position = "identity", quantiles = NULL),
  "ydensity：quantiles = NULL（不插分位线）", "ydensity"
)
cases$ydensity_trim_false <- record_case(
  "ydensity_trim_false",
  ggplot(df_grp, aes(x = g, y = y)) +
    stat_ydensity(geom = "line", position = "identity", trim = FALSE),
  "ydensity：trim = FALSE（两端各扩 3 个带宽）", "ydensity"
)

# --- stat_spoke（4.0.3 里是 deprecate_stop） --------------------------------
cases$spoke_deprecated <- record_error(
  "spoke_deprecated",
  ggplot(df_ld, aes(x = v, y = v)) +
    stat_spoke(mapping = aes(angle = v, radius = v)),
  "spoke：4.0.3 已弃用，调用即报错并指向 geom_spoke()", "spoke"
)

# ---------------------------------------------------------------------------
# docs/cases 的端到端参考图（theme_void 整页，svglite 4×3 in）
# ---------------------------------------------------------------------------

theme_case <- function() {
  theme_void() + theme(legend.position = "none")
}
fixed_x <- function(limits) scale_x_continuous(limits = limits, expand = c(0, 0))
fixed_y <- function(limits) scale_y_continuous(limits = limits, expand = c(0, 0))

save_case <- function(name, plot) {
  path <- file.path(repo, "docs", "cases", name, "expected.svg")
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  svglite::svglite(path, width = 4, height = 3)
  on.exit(grDevices::dev.off(), add = TRUE)
  print(plot)
  cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", path, fixed = TRUE)))
}

# 1. qq point
save_case(
  "stat-qq-point",
  ggplot(df_ld, aes(sample = v)) +
    geom_qq() +
    fixed_x(c(-1.8, 1.8)) + fixed_y(c(0.5, 8.5)) + theme_case()
)

# 2. qq + qq_line（两层）
save_case(
  "stat-qq-line",
  ggplot(df_ld, aes(sample = v)) +
    stat_qq() +
    stat_qq_line(geom = "line", colour = "#4C78A8") +
    fixed_x(c(-1.8, 1.8)) + fixed_y(c(0.5, 8.5)) + theme_case()
)

# 3. ecdf
save_case(
  "stat-ecdf-line",
  ggplot(df_ld, aes(x = v)) +
    stat_ecdf(geom = "line") +
    fixed_x(c(0, 9)) + fixed_y(c(-0.05, 1.05)) + theme_case()
)

# 4. ellipse
save_case(
  "stat-ellipse-path",
  ggplot(df_ell, aes(x, y)) +
    geom_point(size = 2, colour = "#4C78A8") +
    stat_ellipse(type = "norm", geom = "path") +
    fixed_x(c(0, 9)) + fixed_y(c(0, 8)) + theme_case()
)

# 5. quantile
save_case(
  "stat-quantile-line",
  suppressMessages(
    ggplot(df_lin, aes(x, y)) +
      geom_point(size = 2, colour = "#4C78A8") +
      stat_quantile(quantiles = c(0.25, 0.5, 0.75), geom = "line")
  ) +
    fixed_x(c(0.5, 12.5)) + fixed_y(c(0, 8)) + theme_case()
)

# 6. summary（两层都是 point：pointrange 是 M2-7 的另一组）
save_case(
  "stat-summary-point",
  ggplot(df_grp, aes(x = g, y = y)) +
    geom_point(size = 2, colour = "#B0B0B0") +
    stat_summary(fun = "mean", fun.min = "min", fun.max = "max",
                 geom = "point", colour = "#4C78A8") +
    fixed_y(c(0, 8)) + theme_case()
)

# 7. summary_bin
save_case(
  "stat-summary-bin-point",
  ggplot(df_lin, aes(x, y)) +
    geom_point(size = 2, colour = "#B0B0B0") +
    stat_summary_bin(fun = "mean", bins = 4, geom = "point",
                     colour = "#4C78A8", size = 3) +
    fixed_x(c(0.5, 12.5)) + fixed_y(c(0, 8)) + theme_case()
)

# 8. sum（geom_count 的 stat 口径，用点的大小承载 n）
save_case(
  "stat-sum-count",
  ggplot(df_dup, aes(x, y)) +
    stat_sum() +
    fixed_x(c(0.5, 2.5)) + fixed_y(c(0.5, 3.5)) + theme_case()
)

# 9. unique
save_case(
  "stat-unique-point",
  ggplot(
    data.frame(x = c(1, 1, 2, 2, 2), y = c(1, 1, 2, 3, 3)),
    aes(x, y)
  ) +
    stat_unique() +
    fixed_x(c(0.5, 2.5)) + fixed_y(c(0.5, 3.5)) + theme_case()
)

# 10. density
save_case(
  "stat-density-area",
  ggplot(df_ld, aes(x = v)) +
    stat_density(geom = "area", fill = "#4C78A8", colour = NA) +
    fixed_x(c(0, 9)) + fixed_y(c(0, 0.25)) + theme_case()
)

# 11. function（`fun` 走 `geom_line(stat = "function", …)` 的层参数）
save_case(
  "stat-function-line",
  ggplot() +
    geom_line(stat = "function", fun = function(x) sin(x) + 1, xlim = c(0, 6),
              n = 25, colour = "#4C78A8") +
    fixed_x(c(0, 6)) + fixed_y(c(0, 2.2)) + theme_case()
)

# 12. connect
save_case(
  "stat-connect-line",
  ggplot(df_conn, aes(x, y)) +
    geom_line(stat = "connect", connection = "hv", colour = "#4C78A8") +
    fixed_x(c(0.5, 3.5)) + fixed_y(c(0.5, 3.5)) + theme_case()
)

# 13. manual
save_case(
  "stat-manual-point",
  ggplot(df_lin, aes(x, y)) +
    geom_point(stat = "manual", fun = function(d) d[1:4, ]) +
    fixed_x(c(0.5, 4.5)) + fixed_y(c(0.5, 4.5)) + theme_case()
)

# 14. ydensity（geom = point：小提琴是 M2-7 的另一组，这里让每组 512 点的密度
#     网格直接落成点，画面能看出两组密度的形状；quantiles = NULL 去掉分位线）
save_case(
  "stat-ydensity-point",
  ggplot(df_grp, aes(x = g, y = y)) +
    geom_point(stat = "ydensity", position = "identity", colour = "#4C78A8",
               size = 0.6, quantiles = NULL) +
    fixed_y(c(0.5, 7.5)) + theme_case()
)

# ---------------------------------------------------------------------------
# 写盘
# ---------------------------------------------------------------------------

fixture <- list(
  r_version = paste(R.version$major, R.version$minor, sep = "."),
  ggplot2_version = as.character(packageVersion("ggplot2")),
  mass_version = as.character(packageVersion("MASS")),
  quantreg_version = as.character(packageVersion("quantreg")),
  note = paste0(
    "M2-6 stat 长尾 B：qq / qq_line / ecdf / ellipse / quantile / summary / ",
    "summary_bin / sum / unique / density / function / connect / manual / ",
    "spoke / ydensity。±Inf 写 null，位置在 pos_inf / neg_inf（1 起）。"
  ),
  cases = cases
)

writeLines(to_json(fixture), fixture_path)
cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", fixture_path, fixed = TRUE)))
