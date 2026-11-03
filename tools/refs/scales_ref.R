#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/scales_r_reference.json —— M1-4 标度的 R 侧参考值。
#
#   pixi run -e refs refs:scales
#
# 对每个 case：构造一个 ggplot2 4.0.3 的标度对象、`$train()`、再取
#
#   scale$get_limits()                      训练后的数据范围（未 expand）
#   default_expansion(scale)                解析后的 expand（4 个数：mult/add × 两端）
#   scale$dimension(expand = …, limits = …) 面板范围（expand 之后）
#   view_scale_primary(scale, …)$breaks     面板断点（越界 → NA，与图上一致）
#   view_scale_primary(scale, …)$get_labels()  面板标签
#   scale$map(values)                       映射后的值（NA → na.value）
#
# Python 侧 `ggcore.scales` 的 `limits()` / `breaks()` / `labels()` /
# `expanded_limits()` / `map()` 用同一套值对拍（tests/test_scales_r_parity.py）。
#
# 为什么用 view_scale_primary：ggplot2 4.0.3 的 `ggplot_build()` 走
# `view_scales_from_scale()`，面板上的断点/标签就是 ViewScale 上的那一份
# （连续标度按 expand 后的范围算 breaks，再把越界项 censor 成 NA）。直接取
# `panel_params$x$breaks` 也是同一份数据，这里用标度对象是为了不依赖整张图。
#
# 色板（hue / gradient）另记在 `palettes` 里：hue 的十六进制值必须逐字节相同，
# 所以 n = 2 / 3 / 6 各记一次。
#
# 数值用 %.17g（double 可无损往返）；NA → null。

suppressPackageStartupMessages(library(ggplot2))

if (!isTRUE(l10n_info()[["UTF-8"]])) {
  stop("R 不在 UTF-8 locale 下：用 `LC_ALL=C.UTF-8 LANG=C.UTF-8` 重跑")
}

out_path <- "tests/fixtures/scales_r_reference.json"

# ---------------------------------------------------------------------------
# 极简 JSON 输出（与 tools/refs/build_ref.R 同一份）
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
  # ggcore 的日期时间列是「自 epoch 起的天 / 秒」，夹具也按数值记录。
  if (inherits(values, c("Date", "POSIXct", "POSIXt", "difftime", "hms"))) {
    values <- as.numeric(values)
  }
  lapply(seq_along(values), function(i) {
    value <- values[[i]]
    if (length(value) == 0L || (length(value) == 1L && is.na(value))) NULL else unname(value)
  })
}

# 映射结果：NA → null；±Inf 落成字符串 "Inf" / "-Inf"。
# log10 的 0 在 R 里是 -Inf（censor 只 censor 有限值），JSON 没有 Infinity，
# 所以用字符串记下来，Python 侧按 docs/notes/scales.md 的口径明确处理。
mapped_json <- function(values) {
  if (inherits(values, c("Date", "POSIXct", "POSIXt", "difftime", "hms"))) {
    values <- as.numeric(values)
  }
  lapply(seq_along(values), function(i) {
    value <- values[[i]]
    if (length(value) == 0L || (length(value) == 1L && is.na(value))) {
      return(NULL)
    }
    if (is.numeric(value) && is.infinite(value)) {
      return(if (value > 0) "Inf" else "-Inf")
    }
    unname(value)
  })
}

# 参数值：长度 1 落成标量，其余落成数组（Python 侧按同名参数收）。
param_json <- function(value) {
  if (is.null(value)) {
    return(NULL)
  }
  if (length(value) == 1L) {
    return(unname(value))
  }
  as.list(unname(value))
}

# ---------------------------------------------------------------------------
# 标度构造 / 色板
# ---------------------------------------------------------------------------

# registry 名（ggcore 的 SCALE_SPECS）→ R 的构造函数。
# M2-4 A 段起，名字与导出名一一对应（`scale_<name>`），所以直接按名字找；
# 只有 `values =` 的 manual 形态需要换成 `scale_*_manual()`（与 M1-4 相同）。
scale_constructor <- function(name, params) {
  # `values` 是字符向量才是 manual；gradientn / stepsn 的 values 是颜色停靠位置。
  manual <- is.character(params$values)
  if (manual && grepl("^(colour|color|fill)_", name)) {
    aesthetic <- if (startsWith(name, "fill")) "fill" else "colour"
    return(do.call(
      if (aesthetic == "fill") scale_fill_manual else scale_colour_manual,
      params
    ))
  }
  ctor_name <- paste0("scale_", name)
  namespace <- asNamespace("ggplot2")
  if (!exists(ctor_name, envir = namespace, inherits = FALSE)) {
    stop("unknown scale: ", name)
  }
  do.call(get(ctor_name, envir = namespace), params)
}

# 主题解析出来的调色板：size / alpha / shape 的 palette 由 `set_palettes()` 从主题
# （缺省回退到 fallback_palette）注入，`scale_*()` 本身没有。为了拿到「真实图上
# 用的那一份」，这里建一张最小的图，从 build 结果里的标度对象上取。
palette_from_build <- function(aesthetic, discrete) {
  data <- if (discrete) {
    data.frame(x = 1:4, y = 1:4, v = factor(c("a", "b", "c", "d")))
  } else {
    data.frame(x = 1:4, y = 1:4, v = c(1, 2, 3, 4))
  }
  mapping <- switch(
    aesthetic,
    colour = aes(colour = v),
    fill = aes(fill = v),
    size = aes(size = v),
    alpha = aes(alpha = v),
    shape = aes(shape = v),
    linewidth = aes(linewidth = v),
    stop("no palette mapping for aesthetic: ", aesthetic)
  )
  plot <- ggplot(data, aes(x = x, y = y)) + geom_point(mapping)
  built <- suppressWarnings(ggplot_build(plot))
  built$plot$scales$get_scales(aesthetic)$palette
}

ensure_palette <- function(scale, aesthetic) {
  if (is.null(scale$palette)) {
    scale$palette <- palette_from_build(aesthetic, scale$is_discrete())
  }
  scale
}

# ---------------------------------------------------------------------------
# case 记录
# ---------------------------------------------------------------------------

position_aesthetics <- c("x", "y", "xmin", "xmax", "ymin", "ymax", "xend", "yend")

record <- function(id, title, scale, params = list(), train, map, json_params = NULL) {
  sc <- scale_constructor(scale, params)
  aesthetic <- sc$aesthetics[[1]]
  # ggplot2 4.0.3 在训练前先过 `scales$transform_df()`：位置数据先做变换，
  # `train()` / `map()` 拿到的都是**变换后**的值（`$data$x` 也是）。所以这里
  # 复现同一步，否则 log10 标度训练出来的会是原始范围。
  transformation <- tryCatch(sc$get_transformation(), error = function(e) NULL)
  transform_value <- function(values) {
    if (is.null(transformation) || identical(transformation$transform, identity)) {
      return(values)
    }
    suppressWarnings(transformation$transform(values))
  }
  train_values <- transform_value(train)
  map_values <- transform_value(map)
  if (length(train_values) > 0L) {
    sc$train(train_values)
  }
  sc <- ensure_palette(sc, aesthetic)

  limits <- sc$get_limits()
  is_position <- aesthetic %in% position_aesthetics

  expand <- NULL
  expanded <- NULL
  if (is_position) {
    expand <- ggplot2:::default_expansion(sc)
    # ScaleBinned$dimension() 只收 expand（没有 limits 参数），与
    # ScaleContinuous$dimension(expand, limits) 的签名不同。
    expanded <- tryCatch(
      sc$dimension(expand = expand, limits = limits),
      error = function(e) sc$dimension(expand = expand)
    )
  }

  breaks <- NULL
  labels <- NULL
  # 位置标度的面板断点按 **expand 之后** 的范围算（ggplot_build 的 view scale 就是
  # 这么走的）；colour / size / alpha / shape 没有面板范围，按 limits 算（guide 的
  # 口径）。两种情况都走 view_scale_primary，所以越界项同样是 NA。
  view_range <- if (is_position) {
    expanded
  } else {
    tryCatch(sc$dimension(limits = limits), error = function(e) sc$dimension())
  }
  view <- tryCatch(
    ggplot2:::view_scale_primary(sc, limits, view_range),
    error = function(e) NULL
  )
  if (!is.null(view)) {
    breaks <- view$breaks
    if (is.factor(breaks)) {
      breaks <- as.character(breaks)
    }
    labels <- view$get_labels()
  }

  mapped <- sc$map(map_values)

  list(
    id = id,
    title = title,
    scale = scale,
    aesthetic = aesthetic,
    trans = if (is.null(transformation)) "identity" else transformation$name,
    params = lapply(if (is.null(json_params)) params else json_params, param_json),
    train = vector_json(train),
    map = vector_json(map),
    limits = vector_json(limits),
    expand = if (is.null(expand)) NULL else vector_json(expand),
    expanded_limits = if (is.null(expanded)) NULL else vector_json(expanded),
    breaks = if (is.null(breaks)) NULL else vector_json(breaks),
    labels = if (is.null(labels)) NULL else vector_json(labels),
    mapped = mapped_json(mapped)
  )
}

# ---------------------------------------------------------------------------
# 23 个 case
# ---------------------------------------------------------------------------

cases <- list(
  # --- 连续位置 ----------------------------------------------------------
  record(
    "continuous_default_expand",
    "连续 x：默认 expansion(mult = 0.05)",
    "x_continuous",
    train = 1:7,
    map = c(1, 3, 7)
  ),
  record(
    "continuous_expand_zero",
    "连续 x：expand = c(0, 0) 不扩边",
    "x_continuous",
    params = list(expand = c(0, 0)),
    train = 1:7,
    map = c(1, 3, 7)
  ),
  record(
    "continuous_limits_censor",
    "连续 x：显式 limits，越界 → NA（oob = censor）",
    "x_continuous",
    params = list(limits = c(2, 6)),
    train = 1:7,
    map = c(1, 3, 7)
  ),
  record(
    "continuous_manual_breaks_labels",
    "连续 x：手动 breaks + labels",
    "x_continuous",
    params = list(breaks = c(2, 4, 6), labels = c("low", "mid", "high")),
    train = 1:7,
    map = c(2, 4, 6)
  ),
  record(
    "continuous_nbreaks",
    "连续 x：n.breaks = 3（breaks 函数拿 n）",
    "x_continuous",
    params = list(n.breaks = 3),
    train = c(0, 100),
    map = c(0, 50, 100)
  ),
  record(
    "x_log10",
    "log10 x：0 / 负值 → NA；映射后是 log10 空间的值",
    "x_log10",
    train = c(1, 10, 100),
    map = c(1, 10, 100, 0, -1)
  ),
  record(
    "y_log10",
    "log10 y（同一套口径，覆盖 y 通道）",
    "y_log10",
    train = c(0.1, 1, 10),
    map = c(0.1, 1, 10)
  ),
  record(
    "x_log10_limits",
    "log10 x：显式 limits 先过变换（limits 1..100 → 0..2，越界 → NA）",
    "x_log10",
    params = list(limits = c(1, 100)),
    train = c(1, 10, 100),
    map = c(0.5, 1, 10, 100, 200)
  ),

  # --- 离散位置 ----------------------------------------------------------
  record(
    "discrete_levels",
    "离散 x：水平升序，未在 limits 里的值 → NA",
    "x_discrete",
    train = c("b", "a", "c", "a"),
    map = c("a", "b", "c", "z")
  ),
  record(
    "discrete_limits",
    "离散 x：显式 limits（含未出现的水平 z）",
    "x_discrete",
    params = list(limits = c("b", "a", "z")),
    train = c("a", "b", "c"),
    map = c("a", "b", "c")
  ),
  record(
    "discrete_drop_false",
    "离散 x：drop = FALSE 保留未出现的 factor 水平",
    "x_discrete",
    params = list(drop = FALSE),
    train = factor("a", levels = c("b", "a", "c")),
    map = c("a", "b", "c")
  ),
  record(
    "discrete_na_level",
    "离散 x：NA 也是一个水平（排在最后）",
    "x_discrete",
    train = c("a", NA, "b"),
    map = c("a", NA, "b")
  ),
  record(
    "discrete_reverse_limits",
    "离散 x：limits 反序，编码按 limits 顺序",
    "x_discrete",
    params = list(limits = c("c", "b", "a")),
    train = c("a", "b", "c"),
    map = c("a", "b", "c")
  ),

  # --- colour / fill ----------------------------------------------------
  record(
    "colour_hue",
    "离散 colour：hue_pal 色板（3 个水平），NA → na.value",
    "colour_discrete",
    train = c("a", "b", "c", "a"),
    map = c("a", "b", "c", NA)
  ),
  record(
    "colour_hue_na_value",
    "离散 colour：自定义 na.value",
    "colour_discrete",
    params = list(na.value = "red"),
    train = c("a", "b"),
    map = c("a", NA)
  ),
  record(
    "colour_hue_limits",
    "离散 colour：显式 limits 之外的取值 → na.value",
    "colour_discrete",
    params = list(limits = c("b", "a")),
    train = c("a", "b", "c"),
    map = c("a", "b", "c")
  ),
  record(
    "colour_manual",
    "离散 colour：values = 手动色板（按水平顺序，长度必须够）",
    "colour_discrete",
    params = list(values = c("red", "#00FF00", "blue")),
    train = c("a", "b", "c"),
    map = c("a", "b", "c")
  ),
  record(
    "fill_hue",
    "离散 fill：与 colour 同一套 hue 口径",
    "fill_discrete",
    train = c("p", "q"),
    map = c("p", "q")
  ),
  record(
    "colour_gradient",
    "连续 colour：gradient 默认 low/high，Lab 插值",
    "colour_continuous",
    train = c(0, 1),
    map = c(0, 0.5, 1, NA)
  ),
  record(
    "colour_gradient_limits",
    "连续 colour：显式 limits，越界 → na.value",
    "colour_continuous",
    params = list(limits = c(0.25, 0.75)),
    train = c(0, 0.5, 1),
    map = c(0, 0.5, 1)
  ),
  record(
    "size_continuous",
    "连续 size：area 标度（sqrt 后线性映射到 1..6）",
    "size_continuous",
    train = c(1, 2, 3, 4),
    map = c(1, 2, 2, 4)
  ),
  record(
    "alpha_continuous",
    "连续 alpha：0..1 映射到 0.1..1",
    "alpha_continuous",
    train = c(1, 2, 3),
    map = c(1, 2, 3)
  ),
  record(
    "shape_discrete",
    "离散 shape：默认实心形状 16/17/15/3/7/8",
    "shape_discrete",
    train = c("a", "b", "c"),
    map = c("a", "b", "c")
  ),

  # --- M2-4 A：sqrt / reverse / 分箱 / 日期时间 --------------------------
  record(
    "x_sqrt",
    "sqrt x：负值 → NA，断点在数据空间",
    "x_sqrt",
    train = c(0, 1, 4, 9, 16),
    map = c(0, 1, 4, 9, 16, -1)
  ),
  record(
    "x_reverse",
    "reverse x：x → -x，断点在变换后空间倒序",
    "x_reverse",
    train = 1:7,
    map = c(1, 3, 7)
  ),
  record(
    "x_binned",
    "分箱 x：默认 10 个箱，OOB → 箱号",
    "x_binned",
    train = c(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    map = c(1, 3.4, 7, 10, 12, -1)
  ),
  record(
    "x_binned_breaks",
    "分箱 x：显式 breaks（箱边界就是断点）",
    "x_binned",
    params = list(breaks = c(2, 4, 6, 8)),
    train = c(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    map = c(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
  ),
  record(
    "x_date_default",
    "date x：默认 pretty 断点 + ISO 标签",
    "x_date",
    train = as.Date(c("2020-01-05", "2021-06-20")),
    map = as.Date(c("2020-01-05", "2020-06-01", "2021-06-20"))
  ),
  record(
    "x_date_breaks",
    "date x：date_breaks = 2 months + date_labels",
    "x_date",
    params = list(date_breaks = "2 months", date_labels = "%Y-%m", expand = c(0, 0)),
    train = as.Date(c("2020-01-15", "2020-12-03")),
    map = as.Date(c("2020-01-15", "2020-07-01", "2020-12-03"))
  ),
  record(
    "x_datetime_breaks",
    "datetime x：date_breaks = 2 hours",
    "x_datetime",
    params = list(date_breaks = "2 hours", date_labels = "%H:%M", expand = c(0, 0)),
    train = as.POSIXct(c("2020-01-01 00:13:00", "2020-01-01 07:47:00"), tz = "UTC"),
    map = as.POSIXct(c("2020-01-01 00:13:00", "2020-01-01 03:00:00"), tz = "UTC")
  ),
  record(
    "x_time_breaks",
    "time x（hms）：date_breaks = 15 min",
    "x_time",
    params = list(date_breaks = "15 min", date_labels = "%H:%M:%S", expand = c(0, 0)),
    train = hms::as_hms(c(0, 3600)),
    map = hms::as_hms(c(0, 1800, 3600))
  ),

  # --- M2-4 A：颜色连续 / 分箱 / 渐变 ------------------------------------
  record(
    "colour_gradient2",
    "gradient2：midpoint = 0 落在 0.5，Lab 双向插值",
    "colour_gradient2",
    train = c(-1, 0, 1),
    map = c(-1, -0.5, 0, 0.5, 1)
  ),
  record(
    "colour_gradientn",
    "gradientn：三色 + values 停靠点",
    "colour_gradientn",
    params = list(colours = c("#0000FF", "#FFFFFF", "#FF0000"), values = c(0, 0.4, 1)),
    train = c(0, 1),
    map = c(0, 0.2, 0.5, 1)
  ),
  record(
    "colour_steps",
    "steps：分箱渐变（默认 oob = squish）",
    "colour_steps",
    train = c(0, 1),
    map = c(0, 0.2, 0.5, 1)
  ),
  record(
    "colour_steps_oob",
    "steps：limits 之外 squish 到端点箱",
    "colour_steps",
    params = list(limits = c(0.25, 0.75)),
    train = c(0, 1),
    map = c(0, 0.5, 1)
  ),
  record(
    "colour_steps2",
    "steps2：分箱发散渐变",
    "colour_steps2",
    train = c(-1, 1),
    map = c(-1, -0.5, 0, 0.5, 1)
  ),
  record(
    "colour_stepsn",
    "stepsn：分箱 n 色渐变",
    "colour_stepsn",
    params = list(colours = c("#0000FF", "#FFFFFF", "#FF0000"), breaks = c(0.25, 0.5, 0.75)),
    train = c(0, 1),
    map = c(0, 0.2, 0.5, 0.8, 1)
  ),
  record(
    "colour_binned",
    "colour_binned：默认调色板的分箱色",
    "colour_binned",
    train = c(0, 1),
    map = c(0, 0.25, 0.5, 0.75, 1)
  ),
  record(
    "colour_distiller",
    "distiller：Brewer Spectral（7 色）→ 连续渐变",
    "colour_distiller",
    params = list(palette = "Spectral"),
    train = c(0, 1),
    map = c(0, 0.25, 0.5, 0.75, 1)
  ),
  record(
    "colour_fermenter",
    "fermenter：Brewer 分箱（按箱数取色）",
    "colour_fermenter",
    params = list(palette = "Spectral", n.breaks = 4),
    train = c(0, 1),
    map = c(0, 0.2, 0.5, 0.8, 1)
  ),
  record(
    "colour_date",
    "colour_date：日期渐变 + date_breaks",
    "colour_date",
    params = list(date_breaks = "1 month", date_labels = "%b", expand = c(0, 0)),
    train = as.Date(c("2020-01-01", "2020-04-01")),
    map = as.Date(c("2020-01-01", "2020-02-15", "2020-04-01"))
  ),

  # --- M2-4 A：alpha / size / linewidth 连续侧 --------------------------
  record(
    "alpha_binned",
    "alpha_binned：分箱 alpha 0.1..1",
    "alpha_binned",
    train = c(0, 1),
    map = c(0, 0.25, 0.5, 0.75, 1)
  ),
  record(
    "size_area",
    "size_area：rescale_max + abs_area(max_size = 8)",
    "size_area",
    params = list(max_size = 8),
    train = c(1, 2, 3, 4),
    map = c(1, 2, 3, 4)
  ),
  record(
    "size_binned",
    "size_binned：分箱面积标度",
    "size_binned",
    train = c(0, 4),
    map = c(0, 1, 2, 3, 4)
  ),
  record(
    "size_binned_area",
    "size_binned_area：分箱 + rescale_max",
    "size_binned_area",
    train = c(0, 4),
    map = c(0, 1, 2, 3, 4)
  ),
  record(
    "radius",
    "radius：线性 size 1..6",
    "radius",
    train = c(1, 4),
    map = c(1, 2, 4)
  ),
  record(
    "size_date",
    "size_date：日期输入的连续 area 标度",
    "size_date",
    params = list(date_breaks = "1 year", date_labels = "%Y", expand = c(0, 0)),
    train = as.Date(c("2019-01-01", "2021-01-01")),
    map = as.Date(c("2019-01-01", "2020-01-01", "2021-01-01"))
  ),
  record(
    "linewidth_continuous",
    "linewidth：线性 1..6",
    "linewidth_continuous",
    train = c(1, 4),
    map = c(1, 2, 4)
  ),
  record(
    "linewidth_binned",
    "linewidth_binned：分箱线性",
    "linewidth_binned",
    train = c(1, 4),
    map = c(1, 2, 3, 4)
  ),
  record(
    "linewidth_date",
    "linewidth_date：日期输入的线性标度",
    "linewidth_date",
    params = list(date_breaks = "1 year", date_labels = "%Y", expand = c(0, 0)),
    train = as.Date(c("2019-01-01", "2021-01-01")),
    map = as.Date(c("2019-01-01", "2020-01-01", "2021-01-01"))
  ),

  # --- M2-4 A：oob 三态 --------------------------------------------------
  record(
    "x_oob_squish",
    "oob = squish：越界值钳到 limits",
    "x_continuous",
    params = list(limits = c(2, 6), oob = scales::squish),
    json_params = list(limits = c(2, 6), oob = "squish"),
    train = 1:7,
    map = c(1, 3, 7)
  ),
  record(
    "x_oob_keep",
    "oob = keep：越界值原样保留",
    "x_continuous",
    params = list(limits = c(2, 6), oob = scales::oob_keep),
    json_params = list(limits = c(2, 6), oob = "keep"),
    train = 1:7,
    map = c(1, 3, 7)
  ),
  record(
    "x_oob_squish_infinite",
    "oob = squish_infinite：只钳 ±Inf，有限越界保留",
    "x_continuous",
    params = list(limits = c(2, 6), oob = scales::squish_infinite),
    json_params = list(limits = c(2, 6), oob = "squish_infinite"),
    train = 1:7,
    map = c(1, 3, 7)
  )
)

# ---------------------------------------------------------------------------
# 色板夹具
# ---------------------------------------------------------------------------

hue_palette <- get("hue_pal", envir = asNamespace("ggplot2"))
hue <- lapply(c(2, 3, 6), function(n) {
  list(n = n, values = vector_json(hue_palette()(n)))
})

gradient_positions <- c(0, 0.25, 0.5, 0.75, 1)
gradient_scale <- scale_colour_gradient()
gradient <- list(
  low = "#132B43",
  high = "#56B1F7",
  positions = vector_json(gradient_positions),
  values = vector_json(gradient_scale$palette(gradient_positions))
)

# ---------------------------------------------------------------------------
# 自检：别名（scale_colour_continuous / scale_colour_discrete）与这里用的
# hue/gradient 构造函数结果一致 —— 否则夹具的口径就换人了。
# ---------------------------------------------------------------------------

check_alias <- function(plot, expected) {
  got <- ggplot_build(plot)$data[[1]]$colour
  if (!identical(got, expected)) {
    stop("alias check failed: ", paste(got, collapse = " "), " != ",
         paste(expected, collapse = " "))
  }
}
probe <- data.frame(x = 1:3, y = 1:3, z = c(0, 0.5, 1), g = factor(c("a", "b", "c")))
check_alias(
  ggplot(probe, aes(x, y, colour = z)) + geom_point() + scale_colour_continuous(),
  scale_colour_gradient()$palette(c(0, 0.5, 1))
)
check_alias(
  ggplot(probe, aes(x, y, colour = g)) + geom_point() + scale_colour_discrete(),
  hue_palette()(3)
)

document <- list(
  generated_by = "tools/refs/scales_ref.R",
  r_version = R.version.string,
  ggplot2_version = as.character(packageVersion("ggplot2")),
  locale = "C.UTF-8",
  palettes = list(hue = hue, gradient = gradient),
  cases = cases
)

dir.create(dirname(out_path), recursive = TRUE, showWarnings = FALSE)
writeLines(to_json(document), out_path)
cat(sprintf(
  "wrote %s (%d cases, ggplot2 %s)\n",
  out_path, length(cases), document$ggplot2_version
))
