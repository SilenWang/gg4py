#!/usr/bin/env Rscript
#
# 生成 src/ggcore/palette_data.py 与 tests/fixtures/palettes_r_reference.json。
#
#   pixi run -e refs refs:scales        # scales_ref.R 之后再跑一次
#   Rscript tools/refs/palettes_ref.R   # 只重生成色板表
#
# 两份产物：
#
# 1. `src/ggcore/palette_data.py`（入库的取值表，**不靠近似公式**）：
#    - `BREWER_PALETTES`：RColorBrewer 每个 palette 在 n = 3..maxcolors 上的
#      **逐 n 取值表**。RColorBrewer 不是「取最大表的前 n 个」——`Blues` 的 3 色
#      与 9 色是完全不同的插值表（见 `?brewer.pal`），所以整张表逐色入库。
#    - `VIRIDIS_MAP`：`viridisLite::viridis.map` 的 8 位量化（A–H 各 256 个），
#      即 `viridis()` 内部 `grDevices::rgb(map$R, map$G, map$B)` 的结果；
#      之后 `colorRamp(space = "Lab", interpolate = "spline")` 的插值在
#      `ggcore.palettes` 里复刻。
# 2. `tests/fixtures/palettes_r_reference.json`（对拍夹具）：
#    brewer 每个 palette 的首 / 中 / 尾色 + 若干 n 的整表，viridis 每档 a–h 的
#    抽样（n = 2/3/5/8），grey / hue 的抽样，以及各项的来源版本。
#
# 数值与十六进制都按 R 的原值落盘（`%.17g` / 大写 `#RRGGBBAA`），Python 侧
# `tests/test_palettes_r_parity.py` 逐字节比较。

suppressPackageStartupMessages(library(ggplot2))  # 带出 scales / RColorBrewer / viridisLite

if (!isTRUE(l10n_info()[["UTF-8"]])) {
  stop("R 不在 UTF-8 locale 下：用 `LC_ALL=C.UTF-8 LANG=C.UTF-8` 重跑")
}
if (!identical(as.character(packageVersion("ggplot2")), "4.0.3")) {
  stop("ggplot2 必须是 4.0.3（上游 pin）")
}

data_path <- "src/ggcore/palette_data.py"
fixture_path <- "tests/fixtures/palettes_r_reference.json"

r_version <- R.version.string
brewer_version <- as.character(packageVersion("RColorBrewer"))
viridis_version <- as.character(packageVersion("viridisLite"))
ggplot2_version <- as.character(packageVersion("ggplot2"))

str_quote <- function(text) {
  text <- gsub("\\", "\\\\", text, fixed = TRUE)
  text <- gsub("\"", "\\\"", text, fixed = TRUE)
  paste0("\"", text, "\"")
}

# ---------------------------------------------------------------------------
# 1. RColorBrewer：逐 palette、逐 n 的整表
# ---------------------------------------------------------------------------

info <- RColorBrewer::brewer.pal.info
palette_names <- rownames(info)
brewer_tables <- list()
for (name in palette_names) {
  max_n <- unname(info[name, "maxcolors"])
  table <- list()
  for (n in 3:max_n) {
    # n < 3 时 RColorBrewer 会警告并回落到 3；ggcore 的 brewer_pal() 同样如此，
    # 表里只存 n >= 3 的真实取值。
    table[[as.character(n)]] <- RColorBrewer::brewer.pal(n, name)
  }
  brewer_tables[[name]] <- table
}

# ---------------------------------------------------------------------------
# 2. viridisLite：8 档 × 256 色的量化表
# ---------------------------------------------------------------------------

options <- c("A", "B", "C", "D", "E", "F", "G", "H")
viridis_map <- list()
for (option in options) {
  map <- viridisLite::viridis.map[viridisLite::viridis.map$opt == option, ]
  viridis_map[[option]] <- grDevices::rgb(map$R, map$G, map$B)
}

# ---------------------------------------------------------------------------
# 3. 生成 src/ggcore/palette_data.py
# ---------------------------------------------------------------------------

lines <- c(
  '"""色板取值表（生成物，勿手改）。',
  "",
  "由 `pixi run -e refs refs:scales` 调用 `tools/refs/palettes_ref.R` 生成。",
  "取值的来源（全部逐色入库，不靠近似公式）：",
  "",
  sprintf("- R：%s", r_version),
  sprintf("- ggplot2：%s（上游 pin）", ggplot2_version),
  sprintf("- RColorBrewer：%s（`brewer.pal()` 的逐 n 表）", brewer_version),
  sprintf("- viridisLite：%s（`viridis.map` 的 8 位量化）", viridis_version),
  "",
  "口径见 `docs/notes/scales.md` §6。",
  '"""',
  "",
  "from __future__ import annotations",
  "",
  "from types import MappingProxyType",
  "",
  sprintf("R_VERSION = %s", str_quote(r_version)),
  sprintf("GGPLOT2_VERSION = %s", str_quote(ggplot2_version)),
  sprintf("RCOLORBREWER_VERSION = %s", str_quote(brewer_version)),
  sprintf("VIRIDISLITE_VERSION = %s", str_quote(viridis_version)),
  "",
  "#: palette 名 → (maxcolors, 类别：div / qual / seq)",
  "BREWER_INFO = MappingProxyType({"
)
for (name in palette_names) {
  lines <- c(lines, sprintf(
    "    %s: (%d, %s),",
    str_quote(name), as.integer(info[name, "maxcolors"]), str_quote(info[name, "category"])
  ))
}
lines <- c(lines, "})", "", "#: palette 名 → {n: (hex, …)}；n 从 3 到 maxcolors。", "BREWER_PALETTES = MappingProxyType({")
for (name in palette_names) {
  lines <- c(lines, sprintf("    %s: {", str_quote(name)))
  max_n <- unname(info[name, "maxcolors"])
  for (n in 3:max_n) {
    colours <- paste(vapply(brewer_tables[[name]][[as.character(n)]], str_quote, ""), collapse = ", ")
    lines <- c(lines, sprintf("        %d: (%s),", n, colours))
  }
  lines <- c(lines, "    },")
}
lines <- c(lines, "})", "", "#: option（A–H）→ 256 个 #RRGGBB（viridisLite::viridis.map 的量化值）", "VIRIDIS_MAP = MappingProxyType({")
for (option in options) {
  colours <- paste(vapply(viridis_map[[option]], str_quote, ""), collapse = ", ")
  lines <- c(lines, sprintf("    %s: (", str_quote(option)))
  # 每行 8 个，免得单行过长
  chunks <- split(viridis_map[[option]], ceiling(seq_along(viridis_map[[option]]) / 8))
  body <- vapply(chunks, function(part) {
    paste0("        ", paste(vapply(part, str_quote, ""), collapse = ", "), ",")
  }, "")
  lines <- c(lines, body)
  lines <- c(lines, "    ),")
}
lines <- c(lines, "})", "")
dir.create(dirname(data_path), recursive = TRUE, showWarnings = FALSE)
writeLines(lines, data_path)

# ---------------------------------------------------------------------------
# 4. 对拍夹具
# ---------------------------------------------------------------------------

json_escape <- function(text) {
  text <- gsub("\\", "\\\\", text, fixed = TRUE)
  text <- gsub("\"", "\\\"", text, fixed = TRUE)
  text <- gsub("\n", "\\n", text, fixed = TRUE)
  text <- gsub("\t", "\\t", text, fixed = TRUE)
  paste0("\"", text, "\"")
}

to_json <- function(x, indent = 0L) {
  pad <- strrep("  ", indent)
  pad2 <- strrep("  ", indent + 1L)
  if (is.null(x)) {
    return("null")
  }
  if (is.logical(x) && length(x) == 1L) {
    return(if (isTRUE(x)) "true" else "false")
  }
  if (is.numeric(x) && length(x) == 1L) {
    return(sprintf("%.17g", x))
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

vector_json <- function(values) lapply(seq_along(values), function(i) unname(values[[i]]))

# brewer：每个 palette 在 maxcolors 下的首 / 中 / 尾色 + 若干 n 的整表。
brewer_reference <- list()
for (name in palette_names) {
  max_n <- unname(info[name, "maxcolors"])
  pal <- RColorBrewer::brewer.pal(max_n, name)
  brewer_reference[[name]] <- list(
    max = max_n,
    type = unname(info[name, "category"]),
    first = pal[[1]],
    mid = pal[[ceiling(max_n / 2)]],
    last = pal[[max_n]],
    all = vector_json(pal)
  )
}

# brewer 的 n 依赖：抽 8 个 palette，把 3..max 的整表落下来（证明不是截断）。
brewer_n_reference <- list()
for (name in c("Blues", "Reds", "Set1", "Spectral", "Paired", "Greens", "Accent", "BrBG")) {
  max_n <- unname(info[name, "maxcolors"])
  table <- list()
  for (n in 3:max_n) {
    table[[as.character(n)]] <- vector_json(RColorBrewer::brewer.pal(n, name))
  }
  brewer_n_reference[[name]] <- table
}

# viridis：每档 a–h 的抽样（n = 2/3/5/8）+ begin/end/direction/alpha 变体。
viridis_reference <- list()
for (option in options) {
  samples <- list()
  for (n in c(2, 3, 5, 8)) {
    samples[[as.character(n)]] <- vector_json(viridisLite::viridis(n, option = option))
  }
  samples[["begin_end"]] <- vector_json(
    viridisLite::viridis(5, begin = 0.2, end = 0.8, option = option)
  )
  samples[["direction"]] <- vector_json(
    viridisLite::viridis(5, direction = -1, option = option)
  )
  samples[["alpha"]] <- vector_json(viridisLite::viridis(3, alpha = 0.5, option = option))
  viridis_reference[[option]] <- samples
}

grey_reference <- list()
for (n in c(1, 2, 3, 4, 5, 6, 9, 10)) {
  grey_reference[[as.character(n)]] <- vector_json(scales::pal_grey(0.2, 0.8)(n))
}
grey_custom <- list(
  start01 = vector_json(scales::pal_grey(0.1, 0.9)(5)),
  start05 = vector_json(scales::pal_grey(0.5, 1)(4))
)

hue_reference <- list()
for (n in c(2, 3, 4, 5, 6, 7, 10)) {
  hue_reference[[as.character(n)]] <- vector_json(scales::pal_hue()(n))
}

# 数值型离散调色板（ordinal / area / radius 族）：直接取 ggplot2 的 fallback。
ordinal_reference <- list(
  size = vector_json(sqrt(seq(4, 36, length.out = 6))),
  alpha = vector_json(seq(0.1, 1, length.out = 6)),
  linewidth = vector_json(seq(2, 6, length.out = 6)),
  linetype = vector_json(c("solid", "22", "42", "44", "13", "1343")),
  shape = vector_json(c(16, 17, 15, 3, 7, 8)),
  shape_open = vector_json(c(1, 2, 0, 3, 7, 8))
)

# scale_type()：一个向量该用哪类标度（R 返回字符向量，可能两段）。
scale_type_reference <- list(
  character = vector_json(scale_type(c("a", "b"))),
  factor = vector_json(scale_type(factor(c("a", "b")))),
  ordered = vector_json(scale_type(ordered(c("a", "b")))),
  numeric = vector_json(scale_type(c(1, 2, 3))),
  logical = vector_json(scale_type(c(TRUE, FALSE))),
  date = vector_json(scale_type(as.Date("2020-01-01"))),
  datetime = vector_json(scale_type(as.POSIXct("2020-01-01", tz = "UTC")))
)

document <- list(
  generated_by = "tools/refs/palettes_ref.R",
  r_version = r_version,
  ggplot2_version = ggplot2_version,
  RColorBrewer_version = brewer_version,
  viridisLite_version = viridis_version,
  locale = "C.UTF-8",
  brewer = brewer_reference,
  brewer_n = brewer_n_reference,
  viridis = viridis_reference,
  grey = grey_reference,
  grey_custom = grey_custom,
  hue = hue_reference,
  ordinal = ordinal_reference,
  scale_type = scale_type_reference
)

dir.create(dirname(fixture_path), recursive = TRUE, showWarnings = FALSE)
writeLines(to_json(document), fixture_path)
cat(sprintf(
  "wrote %s (%d palettes) and %s\n",
  data_path, length(palette_names), fixture_path
))
