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
  lapply(seq_along(values), function(i) {
    value <- values[[i]]
    if (length(value) == 0L || (length(value) == 1L && is.na(value))) NULL else unname(value)
  })
}

# 映射结果：NA → null；±Inf 落成字符串 "Inf" / "-Inf"。
# log10 的 0 在 R 里是 -Inf（censor 只 censor 有限值），JSON 没有 Infinity，
# 所以用字符串记下来，Python 侧按 docs/notes/scales.md 的口径明确处理。
mapped_json <- function(values) {
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
# `*_discrete` 在 4.0.3 里是 hue 的别名（`scale_colour_discrete()` 的 palette 由
# 主题给，实际回退到 pal_hue()）；`*_continuous` 是 gradient 的别名（回退到
# pal_seq_gradient("#132B43", "#56B1F7")）。这里直接用带调色板的
# `scale_colour_hue()` / `scale_colour_gradient()`，两者与别名的结果一致
# （见文件末尾的 selfcheck）。
# registry 名（ggcore 的 SCALE_SPECS）→ R 构造函数名。`color_*` 与 `colour_*`
# 是同一族（ggplot2 里后者是前者的别名）。R 侧一律取 ggplot2 命名空间里的函数，
# 这样别名与原型走的是同一份实现。
scale_constructor_name <- function(name) {
  switch(
    name,
    x_continuous = "scale_x_continuous",
    y_continuous = "scale_y_continuous",
    x_discrete = "scale_x_discrete",
    y_discrete = "scale_y_discrete",
    x_log10 = "scale_x_log10",
    y_log10 = "scale_y_log10",
    colour_continuous = "scale_colour_gradient",
    colour_gradient = "scale_colour_gradient",
    colour_discrete = "scale_colour_hue",
    colour_hue = "scale_colour_hue",
    color_hue = "scale_colour_hue",
    fill_continuous = "scale_fill_gradient",
    fill_gradient = "scale_fill_gradient",
    fill_discrete = "scale_fill_hue",
    fill_hue = "scale_fill_hue",
    colour_brewer = "scale_colour_brewer",
    color_brewer = "scale_colour_brewer",
    fill_brewer = "scale_fill_brewer",
    colour_distiller = "scale_colour_distiller",
    fill_distiller = "scale_fill_distiller",
    colour_grey = "scale_colour_grey",
    color_grey = "scale_colour_grey",
    fill_grey = "scale_fill_grey",
    colour_ordinal = "scale_colour_ordinal",
    fill_ordinal = "scale_fill_ordinal",
    colour_identity = "scale_colour_identity",
    fill_identity = "scale_fill_identity",
    colour_viridis_c = "scale_colour_viridis_c",
    colour_viridis_d = "scale_colour_viridis_d",
    colour_viridis_b = "scale_colour_viridis_b",
    fill_viridis_c = "scale_fill_viridis_c",
    fill_viridis_d = "scale_fill_viridis_d",
    fill_viridis_b = "scale_fill_viridis_b",
    size_continuous = "scale_size_continuous",
    size = "scale_size",
    size_discrete = "scale_size_discrete",
    size_ordinal = "scale_size_ordinal",
    size_area = "scale_size_area",
    size_binned_area = "scale_size_binned_area",
    size_identity = "scale_size_identity",
    alpha_continuous = "scale_alpha_continuous",
    alpha = "scale_alpha",
    alpha_discrete = "scale_alpha_discrete",
    alpha_ordinal = "scale_alpha_ordinal",
    alpha_identity = "scale_alpha_identity",
    shape_discrete = "scale_shape_discrete",
    shape = "scale_shape",
    shape_ordinal = "scale_shape_ordinal",
    shape_binned = "scale_shape_binned",
    shape_identity = "scale_shape_identity",
    linetype = "scale_linetype",
    linetype_discrete = "scale_linetype_discrete",
    linetype_binned = "scale_linetype_binned",
    linetype_identity = "scale_linetype_identity",
    linewidth = "scale_linewidth",
    linewidth_continuous = "scale_linewidth_continuous",
    linewidth_discrete = "scale_linewidth_discrete",
    linewidth_ordinal = "scale_linewidth_ordinal",
    linewidth_identity = "scale_linewidth_identity",
    linewidth_binned = "scale_linewidth_binned",
    radius = "scale_radius",
    NULL
  )
}

# 家族（colour / fill / shape / linetype / linewidth / size / alpha / x / y）。
scale_family <- function(name) {
  for (prefix in c("colour", "color", "fill", "shape", "linetype", "linewidth", "size", "alpha", "x", "y")) {
    if (identical(name, prefix) || startsWith(name, paste0(prefix, "_"))) {
      return(if (prefix == "color") "colour" else prefix)
    }
  }
  NULL
}

scale_constructor <- function(name, params) {
  family <- scale_family(name)
  manual <- !is.null(params$values) || grepl("_manual$", name)
  if (manual) {
    ctor_name <- paste0("scale_", family, "_manual")
    ctor <- get(ctor_name, envir = asNamespace("ggplot2"))
    return(do.call(ctor, params))
  }
  ctor_name <- scale_constructor_name(name)
  if (is.null(ctor_name)) {
    stop("unknown scale: ", name)
  }
  do.call(get(ctor_name, envir = asNamespace("ggplot2")), params)
}

# 主题解析出来的调色板：size / alpha / shape 的 palette 由 `set_palettes()` 从主题
# （缺省回退到 fallback_palette）注入，`scale_*()` 本身没有。为了拿到「真实图上
# 用的那一份」，这里建一张最小的图，从 build 结果里的标度对象上取。
palette_from_build <- function(aesthetic, discrete) {
  # linetype 没有连续标度（`scale_linetype_continuous()` 直接 abort），分箱的
  # linetype 也得用离散数据去取 fallback palette。
  discrete <- discrete || identical(aesthetic, "linetype")
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
    linetype = aes(linetype = v),
    linewidth = aes(linewidth = v),
    stop("no palette mapping for aesthetic: ", aesthetic)
  )
  # linetype / linewidth 只有线状 geom 会消费，用 geom_line；其余用 geom_point。
  geom <- if (aesthetic %in% c("linetype", "linewidth")) geom_line else geom_point
  plot <- ggplot(data, aes(x = x, y = y)) + geom(mapping)
  built <- suppressWarnings(ggplot_build(plot))
  built$plot$scales$get_scales(aesthetic)$palette
}

# 分箱标度的 fallback palette（`pal_binned(pal_linetype())`）只在 build 时注入；
# 拿它要建一张带**同一个**分箱标度的图——`pal_linetype()` 直接喂向量会 abort
# （`manual_pal` 只收标量 n），所以不能走 `palette_from_build()`。
palette_from_binned_build <- function(scale, aesthetic) {
  data <- data.frame(x = 1:4, y = 1:4, v = c(0, 0.3, 0.7, 1))
  mapping <- switch(
    aesthetic,
    colour = aes(colour = v),
    fill = aes(fill = v),
    size = aes(size = v),
    alpha = aes(alpha = v),
    shape = aes(shape = v),
    linetype = aes(linetype = v),
    linewidth = aes(linewidth = v),
    stop("no palette mapping for aesthetic: ", aesthetic)
  )
  geom <- if (aesthetic %in% c("linetype", "linewidth")) geom_line else geom_point
  plot <- ggplot(data, aes(x = x, y = y)) + geom(mapping) + scale$clone()
  built <- suppressWarnings(ggplot_build(plot))
  built$plot$scales$get_scales(aesthetic)$palette
}

ensure_palette <- function(scale, aesthetic) {
  if (is.null(scale$palette)) {
    if (inherits(scale, "ScaleBinned")) {
      scale$palette <- palette_from_binned_build(scale, aesthetic)
    } else {
      scale$palette <- palette_from_build(aesthetic, scale$is_discrete())
    }
  }
  scale
}

# ---------------------------------------------------------------------------
# case 记录
# ---------------------------------------------------------------------------

position_aesthetics <- c("x", "y", "xmin", "xmax", "ymin", "ymax", "xend", "yend")

record <- function(id, title, scale, params = list(), train, map) {
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
    expanded <- sc$dimension(expand = expand, limits = limits)
  }

  breaks <- NULL
  labels <- NULL
  # 位置标度的面板断点按 **expand 之后** 的范围算（ggplot_build 的 view scale 就是
  # 这么走的）；colour / size / alpha / shape 没有面板范围，按 limits 算（guide 的
  # 口径）。两种情况都走 view_scale_primary，所以越界项同样是 NA。
  view_range <- tryCatch(sc$dimension(limits = limits), error = function(e) NULL)
  if (is_position) view_range <- expanded
  view <- if (is.null(view_range)) {
    NULL
  } else {
    tryCatch(
      ggplot2:::view_scale_primary(sc, limits, view_range),
      error = function(e) NULL
    )
  }
  if (!is.null(view)) {
    breaks <- view$breaks
    if (is.factor(breaks)) {
      breaks <- as.character(breaks)
    }
    labels <- view$get_labels()
  } else {
    # 分箱标度不走 view_scale_primary（它的断点就是箱边界）；直接取标度自己的
    # get_breaks() / get_labels()，与 guide 看到的是同一份。
    breaks <- tryCatch(sc$get_breaks(), error = function(e) NULL)
    if (is.factor(breaks)) {
      breaks <- as.character(breaks)
    }
    labels <- tryCatch(sc$get_labels(), error = function(e) NULL)
  }

  mapped <- sc$map(map_values)

  list(
    id = id,
    title = title,
    scale = scale,
    aesthetic = aesthetic,
    trans = if (is.null(transformation)) "identity" else transformation$name,
    params = lapply(params, param_json),
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

  # --- M2-4 B：离散 / 调色板 / manual / identity --------------------------
  record(
    "colour_brewer_set1",
    "离散 colour：brewer Set1（5 个水平，逐 n 表）",
    "colour_brewer",
    params = list(palette = "Set1"),
    train = c("a", "b", "c", "d", "e"),
    map = c("a", "c", "e")
  ),
  record(
    "colour_brewer_qual_dark2",
    "离散 colour：brewer type = qual, palette = 2（Dark2）",
    "colour_brewer",
    params = list(type = "qual", palette = 2),
    train = LETTERS[1:6],
    map = c("A", "C", "F")
  ),
  record(
    "colour_brewer_direction",
    "离散 colour：brewer direction = -1（Blues 反序）",
    "colour_brewer",
    params = list(palette = "Blues", direction = -1),
    train = c("a", "b", "c", "d"),
    map = c("a", "d")
  ),
  record(
    "fill_brewer_set2",
    "离散 fill：brewer Set2（3 个水平）",
    "fill_brewer",
    params = list(palette = "Set2"),
    train = c("p", "q", "r"),
    map = c("p", "r", NA)
  ),
  record(
    "colour_viridis_d",
    "离散 colour：viridis option C",
    "colour_viridis_d",
    params = list(option = "C"),
    train = c("a", "b", "c", "d"),
    map = c("a", "b", "c", "d", NA)
  ),
  record(
    "colour_viridis_d_begin_end",
    "离散 colour：viridis begin / end / direction",
    "colour_viridis_d",
    params = list(option = "E", begin = 0.2, end = 0.8, direction = -1),
    train = c("a", "b", "c"),
    map = c("a", "b", "c")
  ),
  record(
    "colour_grey",
    "离散 colour：grey 色板（start / end）",
    "colour_grey",
    train = c("a", "b", "c", "d"),
    map = c("a", "d", NA)
  ),
  record(
    "colour_grey_custom",
    "离散 colour：grey start = 0.1, end = 0.9",
    "colour_grey",
    params = list(start = 0.1, end = 0.9),
    train = c("a", "b", "c"),
    map = c("a", "b", "c")
  ),
  record(
    "colour_ordinal",
    "离散 colour：ordinal（4.0.3 缺省走 viridis_d）",
    "colour_ordinal",
    train = c("a", "b", "c"),
    map = c("a", "c")
  ),
  record(
    "colour_identity",
    "colour identity：值原样通过（数据里已经是颜色）",
    "colour_identity",
    train = c("#FF0000", "#00FF00"),
    map = c("#FF0000", "#00FF00", NA)
  ),
  record(
    "colour_distiller",
    "连续 colour：distiller（brewer 7 色 + Lab 插值）",
    "colour_distiller",
    train = c(0, 1),
    map = c(0, 0.25, 0.5, 1, NA)
  ),
  record(
    "colour_viridis_c",
    "连续 colour：viridis option A（6 色 + Lab 插值）",
    "colour_viridis_c",
    params = list(option = "A"),
    train = c(0, 1),
    map = c(0, 0.5, 1)
  ),
  record(
    "colour_viridis_b",
    "分箱 colour：viridis_b（每箱一个色）",
    "colour_viridis_b",
    train = c(0, 1),
    map = c(0, 0.3, 0.8, 1)
  ),
  record(
    "shape_manual",
    "shape manual：values 按水平顺序",
    "shape_manual",
    params = list(values = c(19, 15, 17)),
    train = c("a", "b", "c"),
    map = c("a", "b", "c", NA)
  ),
  record(
    "shape_binned",
    "分箱 shape：数值 → 箱 → 形状码",
    "shape_binned",
    train = c(0, 1),
    map = c(0, 0.3, 0.8, 1)
  ),
  record(
    "linetype_discrete",
    "离散 linetype：pal_linetype 的 13 种线型",
    "linetype_discrete",
    train = c("a", "b", "c"),
    map = c("a", "b", "c", NA)
  ),
  record(
    "linetype_manual",
    "linetype manual：values 按水平顺序",
    "linetype_manual",
    params = list(values = c("solid", "dashed")),
    train = c("a", "b"),
    map = c("a", "b")
  ),
  record(
    "linetype_identity",
    "linetype identity：值原样通过",
    "linetype_identity",
    train = c("solid", "22"),
    map = c("solid", "22")
  ),
  record(
    "linetype_binned",
    "分箱 linetype",
    "linetype_binned",
    train = c(0, 1),
    map = c(0, 0.3, 0.8, 1)
  ),
  record(
    "linewidth_continuous",
    "连续 linewidth：range 1..6",
    "linewidth",
    train = c(1, 4),
    map = c(1, 2.5, 4)
  ),
  record(
    "linewidth_ordinal",
    "离散 linewidth：seq(2, 6, length.out = n)",
    "linewidth_ordinal",
    train = c("a", "b", "c"),
    map = c("a", "c", NA)
  ),
  record(
    "linewidth_manual",
    "linewidth manual：values 按水平顺序",
    "linewidth_manual",
    params = list(values = c(0.5, 1.5)),
    train = c("a", "b"),
    map = c("a", "b")
  ),
  record(
    "linewidth_binned",
    "分箱 linewidth",
    "linewidth_binned",
    train = c(0, 1),
    map = c(0, 0.3, 0.8, 1)
  ),
  record(
    "linewidth_identity",
    "linewidth identity：值原样通过",
    "linewidth_identity",
    train = c(0.5, 2),
    map = c(0.5, 2)
  ),
  record(
    "size_area",
    "连续 size：area（面积正比于值）",
    "size_area",
    train = c(0, 4),
    map = c(0, 1, 4)
  ),
  record(
    "size_binned_area",
    "分箱 size：binned + area",
    "size_binned_area",
    train = c(0, 1),
    map = c(0, 0.5, 1)
  ),
  record(
    "radius",
    "连续 size：radius（规模线性到 1..6）",
    "radius",
    train = c(0, 1),
    map = c(0, 0.5, 1)
  ),
  record(
    "size_ordinal",
    "离散 size：sqrt(seq(4, 36))",
    "size_ordinal",
    train = c("a", "b", "c", "d"),
    map = c("a", "d", NA)
  ),
  record(
    "alpha_ordinal",
    "离散 alpha：seq(0.1, 1)",
    "alpha_ordinal",
    train = c("a", "b", "c"),
    map = c("a", "c", NA)
  ),
  record(
    "alpha_manual",
    "alpha manual：values 按水平顺序",
    "alpha_manual",
    params = list(values = c(0.2, 0.8)),
    train = c("a", "b"),
    map = c("a", "b")
  ),
  record(
    "alpha_identity",
    "alpha identity：值原样通过",
    "alpha_identity",
    train = c(0.2, 0.8),
    map = c(0.2, 0.8)
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
