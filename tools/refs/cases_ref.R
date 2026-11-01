#!/usr/bin/env Rscript
# M0-9 参考图产线：ggplot2 4.0.3 + svglite 出 docs/cases/<case>/expected.svg。
#
#   pixi run -e refs refs:cases
#
# 只在「换 pin」或「有意改口径」时重跑；产物入库，CI 不装 R。
#
# 五个约束，改这个脚本时不要破坏：
#
# 1. **ggplot2 版本钉死 4.0.3**（`docs/notes/upstream.md` 的 pin）。版本不符直接
#    退出，不做「差不多」的参考图。
# 2. **UTF-8 locale**：C locale 下 R 把中文标签当字节串，svglite 会画成一行点
#    （`.`）。pixi 任务已经带 `LC_ALL=C.UTF-8`，这里的断言防止手跑时悄悄退化。
# 3. 每张图都是 `theme_void()` + 显式 limits + `expand = c(0, 0)`：面板就是整页，
#    与 `src/ggcore/plotspec.py` 的适配层一一对应，没有轴/图例/边距。
# 4. 颜色/字号/线宽都与 `plot.py` 同值：`palette` ↔ `scale_*_manual()`，
#    `size_pt` ↔ `size = size_pt / .pt`，`lwd`（pt）↔ `linewidth = lwd / .pt`。
# 5. 产物只写 `expected.svg`；不要在这里生成 `expected.png`（一个 case 只留一张）。

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
if (nchar("\u4e2d\u6587") != 2) {
  stop("R 不在 UTF-8 locale 下：用 `LC_ALL=C.UTF-8 LANG=C.UTF-8` 重跑（见文件头第 2 条）")
}

repo <- normalizePath(".")
cases_dir <- file.path(repo, "docs", "cases")

theme_case <- function() {
  theme_void() + theme(legend.position = "none")
}

axis_fixed <- function(limits) {
  scale_x_continuous(limits = limits, expand = c(0, 0))
}

y_fixed <- function(limits) {
  scale_y_continuous(limits = limits, expand = c(0, 0))
}

save_case <- function(name, plot) {
  path <- file.path(cases_dir, name, "expected.svg")
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  svglite(path, width = 4, height = 3)
  print(plot)
  dev.off()
  cat(sprintf("wrote %s\n", sub(paste0(repo, "/"), "", path, fixed = TRUE)))
}

# --- 1. 散点：geom-point-basic -------------------------------------------------
df_point <- data.frame(
  x = rep(c(0.1, 0.3, 0.5, 0.7, 0.9), 5),
  y = rep(c(0.12, 0.31, 0.50, 0.69, 0.88), each = 5),
  g = rep(c("a", "b", "a", "b", "a"), 5)
)
save_case("geom-point-basic", ggplot(df_point, aes(x, y, colour = g)) +
  geom_point(size = 9 / .pt, stroke = 0) +
  scale_colour_manual(values = c(a = "#F8766D", b = "#00BA38")) +
  axis_fixed(c(0, 1)) +
  y_fixed(c(0, 1)) +
  theme_case())

# --- 2. 柱状：geom-col-basic ---------------------------------------------------
df_col <- data.frame(
  x = c(0.5, 1.5, 2.5, 3.5),
  y = c(0.35, 0.75, 0.55, 0.9),
  g = c("a", "b", "a", "b")
)
save_case("geom-col-basic", ggplot(df_col, aes(x, y, fill = g)) +
  geom_col(width = 0.7) +
  scale_fill_manual(values = c(a = "#4C78A8", b = "#F58518")) +
  axis_fixed(c(0, 4)) +
  y_fixed(c(0, 1)) +
  theme_case())

# --- 3. 中文标签：geom-text-cjk ------------------------------------------------
df_text <- data.frame(
  x = c(0.15, 0.5, 0.85, 0.3, 0.7),
  y = c(0.15, 0.35, 0.55, 0.75, 0.9),
  label = c("\u4e2d\u6587", "\u6807\u7b7e\u6d4b\u8bd5", "gg4py",
            "\u7b2c\u4e09\u884c", "\u6df7\u6392 A1"),
  g = c("a", "b", "a", "b", "a")
)
save_case("geom-text-cjk", ggplot(df_text, aes(x, y, label = label, colour = g)) +
  geom_text(size = 13 / .pt, family = "Noto Sans CJK SC") +
  scale_colour_manual(values = c(a = "#222222", b = "#C0392B")) +
  axis_fixed(c(0, 1)) +
  y_fixed(c(0, 1)) +
  theme_case())

# --- 4. 曲线：geom-curve-basic（SIL-599 的负向验证） ---------------------------
df_curve <- data.frame(
  x = c(0.15, 0.15),
  y = c(0.2, 0.8),
  xend = c(0.85, 0.85),
  yend = c(0.75, 0.25),
  g = c("a", "b")
)
save_case("geom-curve-basic", ggplot(df_curve, aes(x, y, xend = xend, yend = yend, colour = g)) +
  geom_curve(curvature = 0.5, angle = 90, ncp = 5, linewidth = 1 / .pt) +
  scale_colour_manual(values = c(a = "#4C78A8", b = "#E45756")) +
  axis_fixed(c(0, 1)) +
  y_fixed(c(0, 1)) +
  theme_case())
