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
# 2. **UTF-8 locale**：SVG 里的中文必须原样落字。注意 `nchar("中文") == 2` 是个
#    假判据——R 4.5.3 即使在 `LC_ALL=C` 下也按原生 UTF-8 处理字符串（实测两种
#    locale 的产物逐字节相同，SIL-649），所以「C locale 画成一行点」在本环境复现
#    不出来。但这是 R 的实现细节，不能当保护：断言改成按 locale 判
#    （`l10n_info()$codeset`），非 UTF-8 直接退出。pixi 任务已带 `LC_ALL=C.UTF-8`。
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
if (!isTRUE(l10n_info()[["UTF-8"]])) {
  codeset <- l10n_info()[["codeset"]]
  stop(sprintf(
    "R 不在 UTF-8 locale 下（l10n_info()$codeset = %s）：用 `LC_ALL=C.UTF-8 LANG=C.UTF-8` 重跑（见文件头第 2 条）",
    if (is.null(codeset) || !nzchar(codeset)) "?" else codeset
  ))
}

repo <- normalizePath(".")
cases_dir <- file.path(repo, "docs", "cases")
# 可选的 case 过滤：`Rscript tools/refs/cases_ref.R text-multiline` 只重画点名
# 的 case（新增/改单个 case 时不必整批重写 expected.svg）。不带参数照旧全量。
only <- commandArgs(trailingOnly = TRUE)

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
  if (length(only) > 0 && !(name %in% only)) {
    return(invisible(NULL))
  }
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
# 一条 18 字的左对齐长标签 + 一条短标签（SIL-649）。宽度误差沿字符串累积：
# 左对齐时第 i 个字偏移 ≈ 2% × i × 字号，短标签在 2% 的图级阈值下只剩
# 抗锯齿噪声。字号 10 pt（不是越大越好）：两边基线差的绝对值随字号线性增长，
# 而宽度误差只跟标签总宽有关，实测 10 pt + 长标签的信噪比最好。
df_text <- data.frame(
  x = c(0.03, 0.03),
  y = c(0.62, 0.28),
  label = c("\u4e2d\u6587\u6807\u7b7e\u5bbd\u5ea6\u57fa\u51c6\u6821\u9a8c\u7b2c\u4e8c\u884c\u6587\u672c\u5bf9\u6bd4",
            "\u7b2c\u4e09\u884c"),
  g = c("a", "b")
)
save_case("geom-text-cjk", ggplot(df_text, aes(x, y, label = label, colour = g)) +
  geom_text(size = 10 / .pt, hjust = 0, family = "Noto Sans CJK SC") +
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

# --- 5. 真实字面：text-bold-italic（M1 文字测量） ----------------------------
df_faces <- data.frame(
  x = rep(0.04, 4),
  y = c(0.84, 0.62, 0.40, 0.18),
  label = c(
    "Regular text sample",
    "Bold text sample",
    "Italic text sample",
    "Bold italic sample"
  ),
  face = c("plain", "bold", "italic", "bold.italic")
)
plot_faces <- ggplot(df_faces, aes(x, y, label = label)) +
  axis_fixed(c(0, 1)) +
  y_fixed(c(0, 1)) +
  theme_case()
for (i in seq_len(nrow(df_faces))) {
  plot_faces <- plot_faces +
    geom_text(
      data = df_faces[i, , drop = FALSE],
      size = 12 / .pt,
      hjust = 0,
      family = "Noto Sans",
      fontface = df_faces$face[i]
    )
}
save_case("text-bold-italic", plot_faces)

# --- 6. 多行：text-multiline（M1 文字测量） -----------------------------------
df_multi <- data.frame(
  x = c(0.03, 0.55),
  y = c(0.72, 0.30),
  label = c(
    "\u591a\u884c\u6587\u672c\u7b2c\u4e00\u884c\n\u7b2c\u4e8c\u884c mixed Latin \u6587\u5b57\n\u7b2c\u4e09\u884c",
    "two lines\nsecond line"
  ),
  hjust = c(0, 0.5)
)
plot_multi <- ggplot(df_multi, aes(x, y, label = label)) +
  axis_fixed(c(0, 1)) +
  y_fixed(c(0, 1)) +
  theme_case() +
  geom_text(
    data = df_multi[1, , drop = FALSE],
    size = 10 / .pt,
    hjust = 0,
    family = "Noto Sans CJK SC"
  ) +
  geom_text(
    data = df_multi[2, , drop = FALSE],
    size = 10 / .pt,
    hjust = 0.5,
    family = "Noto Sans CJK SC"
  )
save_case("text-multiline", plot_multi)

# --- 7. emoji：text-emoji（M1 文字测量） --------------------------------------
df_emoji <- data.frame(
  x = rep(0.04, 3),
  y = c(0.80, 0.55, 0.30),
  label = c(
    "smile \U0001F600",
    "rocket \U0001F680 check \u2705",
    "\u4e2d\u6587 \U0001F600 \u6df7\u6392"
  )
)
save_case("text-emoji", ggplot(df_emoji, aes(x, y, label = label)) +
  geom_text(size = 14 / .pt, hjust = 0, family = "Noto Sans CJK SC") +
  axis_fixed(c(0, 1)) +
  y_fixed(c(0, 1)) +
  theme_case())
