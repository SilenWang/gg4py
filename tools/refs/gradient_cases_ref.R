#!/usr/bin/env Rscript
# SIL-751 的参考图产线：渐变 / 图案填充的 4 条 case（ggplot2 4.0.3 + svglite，4 × 3 in）。
#
#   pixi run -e refs refs:gradient-cases
#   Rscript tools/refs/gradient_cases_ref.R viewer-pattern            # 只重画点名的
#
# 与 `viewer_cases_ref.R` 分开是有意的：那份脚本会重写 M2-12 的 4 张参考图，
# 本 issue 只**新增** case，不能碰任何已有 `expected.svg`。
#
# 三条硬约束与 battery 相同：ggplot2 必须 4.0.3、UTF-8 locale、页面 4 × 3 in。
# 数据与 `docs/cases/<case>/plot.py` 逐值相同，改一边必须同步另一边。
#
# 口径提示（`docs/notes/ir.md` §6.1）：
# - 渐变 / 图案的 npc 坐标按**被填充对象**的包围盒解析；ggplot 的 geom_col 把
#   三行数据画成**一个**多行 rectGrob，所以整层只有一条 `<linearGradient>`；
# - tile 以 `(x, y) = (0.5, 0.5)` 为中心（R 的 `just = "centre"`）；
# - 图案内容用包围盒 npc 写，竖条在 tile 左侧 40%。

suppressPackageStartupMessages({
  library(grid)
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
fy <- function(lo, hi) scale_y_continuous(limits = c(lo, hi), expand = c(0, 0))

df <- data.frame(cls = c("a", "b", "c"), v = c(0.35, 0.65, 0.90))

# --- 线性渐变 --------------------------------------------------------------

save_case("viewer-gradient-linear",
  ggplot(df, aes(cls, v)) +
    geom_col(
      fill = linearGradient(c("#132B43", "#56B1F7"), stops = c(0, 1),
                            x1 = 0, y1 = 0, x2 = 1, y2 = 0),
      colour = NA
    ) +
    scale_x_discrete() + fy(0, 1) + theme_case()
)

# --- 线性渐变：4 档 + 中间档带 alpha ------------------------------------------

# 现有三条都是「2 档、无 alpha」。这条守两件容易被写死掉的事：
# - 档数 > 2 时 stop 表按 offset 排序、中间档真的插在中间；
# - 单档的 alpha（#56B1F780 → 0.50）落在 stop-opacity 上，不是整条渐变的
#   fill-opacity——所以同一根柱子上能同时看到「半透明的中段」与「不透明的两端」。
save_case("viewer-gradient-stops-alpha",
  ggplot(df, aes(cls, v)) +
    geom_col(
      fill = linearGradient(c("#132B43", "#56B1F780", "#F4A582", "#B31D28"),
                            stops = c(0, 0.3, 0.7, 1),
                            x1 = 0, y1 = 0, x2 = 1, y2 = 0),
      colour = NA
    ) +
    scale_x_discrete() + fy(0, 1) + theme_case()
)

# --- 径向渐变 --------------------------------------------------------------

save_case("viewer-gradient-radial",
  ggplot(df, aes(cls, v)) +
    geom_col(
      fill = radialGradient(c("#FDE7E9", "#B31D28"), stops = c(0, 1),
                            cx1 = 0.5, cy1 = 0.5, r1 = 0,
                            cx2 = 0.5, cy2 = 0.5, r2 = 0.5),
      colour = NA
    ) +
    scale_x_discrete() + fy(0, 1) + theme_case()
)

# --- 平铺图案 --------------------------------------------------------------

# tile 宽 = 30 pt（= 包围盒宽 261 pt 的 30/261）、高 = 包围盒的 12%，以中心对齐；
# 内容坐标是**包围盒的 npc**（与 `docs/cases/viewer-pattern/plot.py` 的 tile 窗口
# 一致）。tile 宽取整数 pt 是有意的：resvg 的 `<pattern>` 平铺按整数像素步进，
# 小数周期会在多块之后累积出 1 px 以上的相位差（SIL-751 的两腿对拍抓到过）。
tw <- 30 / 261
th <- 0.12
save_case("viewer-pattern",
  ggplot(df, aes(cls, v)) +
    geom_col(
      fill = pattern(
        gTree(children = gList(
          rectGrob(x = 0.5, y = 0.5, width = tw, height = th,
                   gp = gpar(fill = "#F4F1EA", col = NA)),
          rectGrob(x = 0.5 - tw / 2 + 0.4 * tw / 2, y = 0.5, width = 0.4 * tw, height = th,
                   gp = gpar(fill = "#E45756", col = NA))
        )),
        x = 0.5, y = 0.5,
        width = unit(tw, "npc"), height = unit(th, "npc"),
        extend = "repeat"
      ),
      colour = NA
    ) +
    scale_x_discrete() + fy(0, 1) + theme_case()
)
