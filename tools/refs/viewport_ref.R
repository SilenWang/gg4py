#!/usr/bin/env Rscript
#
# 生成 tests/fixtures/viewport_r_reference.json —— viewport 对拍的 R 侧参考值。
#
#   pixi run -e refs refs:viewport
#
# 每条用例是一段**步骤脚本**（push / pop / up / down / seek / check），R 侧照
# 脚本走一遍，在每个 check 上记下：路径与深度、累计旋转、视口宽高（英寸）、
# 裁剪框（英寸）、解析后的 gpar、以及若干探针的「本视口英寸」与「设备英寸」。
# Python 侧用同一份脚本重放（spec 原样写进夹具），逐项对拍。
#
# 设备固定成 6×4 in 的 pdf(NULL)（设备单位是点，1 in = 72）；用到的单位都
# 不依赖字体度量，所以结果只取决于本文件的输入。
#
# 口径与差异见 docs/notes/viewport.md。

library(grid)

out_path <- "tests/fixtures/viewport_r_reference.json"

# ---------------------------------------------------------------------------
# 极简 JSON 输出（不引入 jsonlite）
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
  if (is.null(x)) return("null")
  if (is.logical(x) && length(x) == 1L) {
    if (is.na(x)) return("null")
    return(if (isTRUE(x)) "true" else "false")
  }
  if (is.numeric(x) && length(x) == 1L) return(fmt_num(x))
  if (is.character(x) && length(x) == 1L) return(json_escape(x))
  if (is.list(x)) {
    nm <- names(x)
    if (!is.null(nm) && all(nzchar(nm))) {
      if (length(x) == 0L) return("{}")
      items <- vapply(seq_along(x), function(i) {
        paste0(pad2, json_escape(nm[[i]]), ": ", to_json(x[[i]], indent + 1L))
      }, character(1))
      return(paste0("{\n", paste(items, collapse = ",\n"), "\n", pad, "}"))
    }
    if (length(x) == 0L) return("[]")
    items <- vapply(x, function(el) paste0(pad2, to_json(el, indent + 1L)), character(1))
    return(paste0("[\n", paste(items, collapse = ",\n"), "\n", pad, "]"))
  }
  if (length(x) == 0L) return("[]")
  items <- vapply(seq_along(x), function(i) {
    paste0(pad2, to_json(x[[i]], indent + 1L))
  }, character(1))
  paste0("[\n", paste(items, collapse = ",\n"), "\n", pad, "]")
}

# ---------------------------------------------------------------------------
# 用例 DSL
# ---------------------------------------------------------------------------

# 单位：list(value, unit)，Python 侧 unit(value, unit)
u <- function(value, unit) list(value = value, unit = unit)

# 视口：与 ggcore.viewport.viewport() 的参数一一对应
vp <- function(name, x = u(0.5, "npc"), y = u(0.5, "npc"),
               width = u(1, "npc"), height = u(1, "npc"),
               just = "centre", xscale = c(0, 1), yscale = c(0, 1),
               angle = 0, clip = "inherit", gp = list()) {
  list(name = name, x = x, y = y, width = width, height = height, just = just,
       xscale = xscale, yscale = yscale, angle = angle, clip = clip, gp = gp)
}

step <- function(op, ...) {
  fields <- list(...)
  out <- list(op = op)
  for (name in names(fields)) out[[name]] <- fields[[name]]
  out
}

push <- function(v) step("push", vp = v)
pop <- function(n = 1) step("pop", n = n)
up <- function(n = 1) step("up", n = n)
down <- function(path, strict = FALSE) step("down", path = path, strict = strict)
seek <- function(path) step("seek", path = path)
check <- function(id, probes) step("check", id = id, probes = probes)

# 探针：npc 三个角 + 一个 cm 位置 + 一个 lines/char 位置（后两个走 gpar 的字号）
probes_basic <- list(
  list(x = u(0, "npc"), y = u(0, "npc")),
  list(x = u(0.5, "npc"), y = u(0.5, "npc")),
  list(x = u(1, "npc"), y = u(1, "npc")),
  list(x = u(2.5, "cm"), y = u(1, "cm")),
  list(x = u(1, "lines"), y = u(1, "char"))
)

# 带 native 的探针：只在视口给了非退化 xscale/yscale 的用例里用
probes_native <- c(
  probes_basic,
  list(
    list(x = u(0.25, "native"), y = u(0.75, "native")),
    list(x = u(0.5, "native"), y = u(0.5, "native"))
  )
)

# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------

cases <- list(
  list(
    id = "flat-cm-reversed-scale",
    notes = "单层视口：cm 几何 + 反向 xscale + 各类探针",
    steps = list(
      push(vp("flat", x = u(1, "cm"), y = u(2, "cm"), width = u(3, "cm"), height = u(1, "cm"),
              just = c("left", "bottom"), xscale = c(10, 0), yscale = c(5, 1),
              clip = "on", gp = list(col = "red", fontsize = 24))),
      check("flat", probes_native),
      pop(1),
      check("root", probes_basic)
    )
  ),
  list(
    id = "nested-three-rotated",
    notes = "三层嵌套，角度 15/25/50 累加成 90；各级 just 不同",
    steps = list(
      push(vp("a", x = u(0.2, "npc"), y = u(0.2, "npc"), width = u(0.6, "npc"),
              height = u(0.6, "npc"), just = c("left", "bottom"), angle = 15,
              gp = list(fontsize = 18))),
      check("a", probes_basic),
      push(vp("b", x = u(0.5, "npc"), y = u(0.5, "npc"), width = u(0.8, "npc"),
              height = u(0.5, "npc"), angle = 25, xscale = c(0, 10), yscale = c(-1, 1))),
      check("a-b", probes_native),
      push(vp("c", x = u(0.5, "native"), y = u(0.5, "native"), width = u(3, "cm"),
              height = u(2, "cm"), angle = 50, just = c(0.2, 0.8), clip = "on")),
      check("a-b-c", probes_basic),
      pop(3),
      check("root", probes_basic)
    )
  ),
  list(
    id = "clip-on-off-inherit",
    notes = "裁剪三态 + 旋转不可裁剪时的退化（45 与累计 180）",
    steps = list(
      push(vp("p1", x = u(0.1, "npc"), y = u(0.1, "npc"), width = u(0.8, "npc"),
              height = u(0.8, "npc"), clip = "on")),
      check("p1-on", probes_basic),
      push(vp("p2", x = u(0.5, "npc"), y = u(0.5, "npc"), width = u(0.5, "npc"),
              height = u(0.5, "npc"), clip = "inherit")),
      check("p1-p2-inherit", probes_basic),
      push(vp("p3", width = u(2, "npc"), height = u(2, "npc"), clip = "off")),
      check("p1-p2-p3-off", probes_basic),
      up(1),
      push(vp("rot45", width = u(1, "npc"), height = u(1, "npc"), angle = 45, clip = "on")),
      check("p1-p2-rot45", probes_basic),
      up(2),
      push(vp("q90", x = u(0.5, "npc"), y = u(0.5, "npc"), width = u(0.5, "npc"),
              height = u(0.5, "npc"), angle = 90, clip = "on")),
      check("q90", probes_basic),
      push(vp("r180", width = u(1, "npc"), height = u(1, "npc"), angle = 90, clip = "on")),
      check("q90-r180", probes_basic),
      pop(3)
    )
  ),
  list(
    id = "gpar-inherit",
    notes = "14 个 gpar 字段逐字段继承；cex/alpha/lex 累积；pop 后回到 parentgpar",
    steps = list(
      push(vp("g1", x = u(0, "npc"), y = u(0, "npc"), width = u(1, "npc"),
              height = u(1, "npc"), just = c("left", "bottom"),
              gp = list(col = "red", fill = "blue", lwd = 2, lty = "dashed",
                        lineend = "butt", linejoin = "mitre", linemitre = 4,
                        alpha = 0.9, cex = 1.5, fontsize = 20, lineheight = 1.5,
                        font = 2, fontfamily = "serif", lex = 2))),
      check("g1", probes_basic),
      push(vp("g2", width = u(0.5, "npc"), height = u(0.5, "npc"),
              gp = list(lwd = 5, cex = 0.5))),
      check("g1-g2", probes_basic),
      push(vp("g3", width = u(0.5, "npc"), height = u(0.5, "npc"),
              gp = list(alpha = 0.5, fontsize = 10))),
      check("g1-g2-g3", probes_basic),
      pop(1),
      check("g1-g2-restored", probes_basic),
      pop(2),
      check("root", probes_basic)
    )
  ),
  list(
    id = "navigate",
    notes = "up/down/pop 的路径、深度、gpar 与裁剪恢复",
    steps = list(
      push(vp("nav-a", x = u(0.2, "npc"), y = u(0.2, "npc"), width = u(0.6, "npc"),
              height = u(0.6, "npc"), clip = "on", gp = list(col = "red"))),
      push(vp("nav-b", x = u(0.5, "npc"), y = u(0.5, "npc"), width = u(0.5, "npc"),
              height = u(0.5, "npc"), xscale = c(0, 4), yscale = c(0, 3),
              gp = list(lwd = 3))),
      check("nav-a::nav-b", probes_native),
      up(1),
      check("nav-a-up", probes_basic),
      down("nav-b"),
      check("nav-a-down-nav-b", probes_native),
      pop(2),
      check("root", probes_basic),
      push(vp("nav-x", width = u(0.5, "npc"), height = u(0.5, "npc"))),
      push(vp("nav-y", width = u(0.5, "npc"), height = u(0.5, "npc"), angle = 30)),
      up(0),
      seek("nav-x::nav-y"),
      check("nav-x::nav-y-seek", probes_basic),
      pop(2)
    )
  )
)

# ---------------------------------------------------------------------------
# 执行 + 记录
# ---------------------------------------------------------------------------

width_in <- 6
height_in <- 4

run_case <- function(case) {
  pdf(NULL, width = width_in, height = height_in, pointsize = 12)
  grid.newpage()
  # pdf 的设备单位就是 bigpts（1/72 in），用它把 cliprect 折回英寸
  unit_per_inch <- as.numeric(convertWidth(unit(1, "inches"), "bigpts"))
  state <- new.env(parent = emptyenv())
  state$warned <- FALSE
  state$steps <- list()

  record <- function(id, probes) {
    pvp <- grid:::grid.Call(grid:::C_currentViewport)
    # as.character(vpPath) 会给一条 "a::b" 字符串，这里按 R 的 sep 拆回段
    path_text <- as.character(current.vpPath())
    path <- if (length(path_text) == 0L) character(0) else strsplit(path_text, "::", fixed = TRUE)[[1]]
    gp <- unclass(get.gpar())
    gp$gamma <- NULL
    probe_records <- lapply(probes, function(p) {
      x <- unit(p$x$value, p$x$unit)
      y <- unit(p$y$value, p$y$unit)
      loc <- c(convertX(x, "inches"), convertY(y, "inches"))
      device <- as.numeric(unlist(deviceLoc(x, y)))
      list(spec = p, loc_in = as.numeric(loc), device_in = device)
    })
    list(
      id = id,
      path = if (length(path) == 0L) NULL else as.list(path),
      depth = length(path),
      rotation = pvp$rotation,
      width_in = pvp$width.cm / 2.54,
      height_in = pvp$height.cm / 2.54,
      clip_in = as.numeric(pvp$cliprect) / unit_per_inch,
      clip_warning = state$warned,
      gpar = gp,
      probes = probe_records
    )
  }

  push_vp <- function(spec) {
    args <- list(
      x = unit(spec$x$value, spec$x$unit),
      y = unit(spec$y$value, spec$y$unit),
      width = unit(spec$width$value, spec$width$unit),
      height = unit(spec$height$value, spec$height$unit),
      just = spec$just,
      xscale = spec$xscale,
      yscale = spec$yscale,
      angle = spec$angle,
      clip = spec$clip,
      gp = do.call(gpar, spec$gp),
      name = spec$name
    )
    pushViewport(do.call(viewport, args))
  }

  withCallingHandlers(
    for (s in case$steps) {
      op <- s$op
      if (op == "push") {
        push_vp(s$vp)
        state$steps[[length(state$steps) + 1L]] <- s
      } else if (op == "pop") {
        popViewport(s$n)
        state$steps[[length(state$steps) + 1L]] <- s
      } else if (op == "up") {
        upViewport(s$n)
        state$steps[[length(state$steps) + 1L]] <- s
      } else if (op == "down") {
        downViewport(s$path, strict = isTRUE(s$strict))
        state$steps[[length(state$steps) + 1L]] <- s
      } else if (op == "seek") {
        seekViewport(s$path)
        state$steps[[length(state$steps) + 1L]] <- s
      } else if (op == "check") {
        recorded <- record(s$id, s$probes)
        state$warned <- FALSE
        s$expected <- recorded
        state$steps[[length(state$steps) + 1L]] <- s
      } else {
        stop("unknown op: ", op)
      }
    },
    warning = function(w) {
      if (grepl("cannot clip to rotated viewport", conditionMessage(w), fixed = TRUE)) {
        state$warned <- TRUE
      }
      invokeRestart("muffleWarning")
    }
  )
  dev.off()
  list(
    id = case$id,
    notes = case$notes,
    steps = state$steps
  )
}

records <- lapply(cases, run_case)

document <- list(
  r_version = R.version.string,
  generated_by = "tools/refs/viewport_ref.R",
  device = list(type = "pdf(NULL)", width_in = width_in, height_in = height_in,
                pointsize = 12, units_per_inch = 72),
  cases = records
)

dir.create(dirname(out_path), showWarnings = FALSE, recursive = TRUE)
writeLines(to_json(document), out_path)
cat("wrote ", out_path, " (", length(records), " cases, ", R.version.string, ")\n", sep = "")
