#!/usr/bin/env Rscript
#
# M2-1 的 coord 案例参考图产线（ggplot2 4.0.3 + svglite，4 × 3 in）。
#
#   pixi run -e refs refs:cases      # 全量（本文件由 `[feature.refs.tasks]` 串起来）
#   Rscript tools/refs/coord_cases_ref.R <case> ...
#
# 与 `cases_battery_ref.R` 分开：那是 M1-15 的 geom / scale / theme 案例，
# 这里是 coord 家族（flip / trans / equal / polar / radial / sec_axis）。
# 每个 case 与 `docs/cases/<case>/plot.py` 一一对应；改一边必须改另一边。

suppressPackageStartupMessages({
  library(ggplot2)
  library(svglite)
})

if (!identical(as.character(packageVersion("ggplot2")), "4.0.3")) {
  stop(sprintf(
    "ggplot2 必须是 4.0.3（上游 pin），当前是 %s",
    as.character(packageVersion("ggplot2"))
  ))
}
if (!isTRUE(l10n_info()[["UTF-8"]])) {
  stop("R 不在 UTF-8 locale 下：用 LC_ALL=C.UTF-8 LANG=C.UTF-8 重跑")
}

repo <- normalizePath(".")
cases_dir <- file.path(repo, "docs", "cases")
only <- commandArgs(trailingOnly = TRUE)

save_case <- function(name, plot) {
  if (length(only) > 0 && !(name %in% only)) {
    return(invisible(NULL))
  }
  path <- file.path(cases_dir, name, "expected.svg")
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  svglite(path, width = 4, height = 3)
  on.exit(grDevices::dev.off(), add = TRUE)
  print(plot)
  cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", path, fixed = TRUE)))
}

theme_case <- function() theme_void() + theme(legend.position = "none")

# --- flip ------------------------------------------------------------------

flip_data <- data.frame(
  cls = c("a", "b", "c", "d", "e"),
  v = c(1.0, 2.5, 1.8, 3.0, 2.2)
)

save_case("coord-flip-points", {
  ggplot(flip_data, aes(cls, v)) +
    geom_point(size = 3, colour = "#4C78A8") +
    coord_flip() +
    theme_case()
})

save_case("coord-flip-bar", {
  ggplot(flip_data, aes(cls, v)) +
    geom_col(fill = "#4C78A8", width = 0.6) +
    coord_flip() +
    theme_case()
})

# --- trans -----------------------------------------------------------------

save_case("coord-trans-log10", {
  trans_data <- data.frame(
    x = c(1, 3, 10, 30, 100, 300),
    y = c(0.10, 0.25, 0.35, 0.50, 0.60, 0.75)
  )
  ggplot(trans_data, aes(x, y)) +
    geom_point(size = 3, colour = "#4C78A8") +
    coord_trans(x = "log10") +
    theme_case()
})

save_case("coord-trans-sqrt", {
  ggplot(flip_data, aes(cls, v)) +
    geom_point(size = 3, colour = "#4C78A8") +
    coord_trans(y = "sqrt") +
    theme_case()
})

# --- equal / polar / radial ------------------------------------------------

save_case("coord-equal", {
  equal_data <- data.frame(x = c(1, 2, 3, 4), y = c(2, 5, 3, 6))
  ggplot(equal_data, aes(x, y)) +
    geom_point(size = 3, colour = "#4C78A8") +
    coord_equal() +
    theme_case()
})

save_case("coord-polar-bar", {
  ggplot(flip_data, aes(cls, v)) +
    geom_col(fill = "#4C78A8", width = 0.8) +
    coord_polar() +
    theme_case()
})

save_case("coord-polar-facet", {
  polar_data <- data.frame(
    cls = c("a", "b", "c", "d", "e"),
    v = c(1.0, 2.5, 1.8, 3.0, 2.2),
    g = c("p", "p", "p", "q", "q")
  )
  ggplot(polar_data, aes(cls, v)) +
    geom_point(size = 3, colour = "#4C78A8") +
    coord_polar() +
    facet_wrap(~ g) +
    theme_case()
})

save_case("coord-polar-theta-y", {
  ggplot(flip_data, aes(cls, v)) +
    geom_point(size = 3, colour = "#4C78A8") +
    coord_polar(theta = "y") +
    theme_case()
})

save_case("coord-radial-partial", {
  ggplot(flip_data, aes(cls, v)) +
    geom_point(size = 3, colour = "#4C78A8") +
    coord_radial(start = -0.5 * pi, end = 0.5 * pi) +
    theme_case()
})

save_case("coord-radial-inner", {
  ggplot(flip_data, aes(cls, v)) +
    geom_point(size = 3, colour = "#4C78A8") +
    coord_radial(inner.radius = 0.3) +
    theme_case()
})

save_case("coord-quickmap", {
  map_data <- data.frame(
    lon = c(-10, -4, 0, 6, 12),
    lat = c(35, 41, 39, 44, 37)
  )
  ggplot(map_data, aes(lon, lat)) +
    geom_point(size = 3, colour = "#4C78A8") +
    coord_quickmap() +
    theme_case()
})

# --- secondary axis --------------------------------------------------------

save_case("coord-sec-axis", {
  ggplot(flip_data, aes(cls, v)) +
    geom_point(size = 3, colour = "#4C78A8") +
    scale_y_continuous(sec.axis = sec_axis(~ . * 2, name = "double")) +
    theme(panel.grid = element_blank(), panel.background = element_blank())
})
