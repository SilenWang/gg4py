#!/usr/bin/env python
"""把 `docs/cases/grob-*` 的 grob 用例画成 PNG 快照（M0-6）。

    pixi run cases:grob            # 重新生成 baseline/<case id>.png
    pixi run cases:grob --check    # 只和仓库里的 baseline 比对，不写文件

链路与正式渲染一致**到场景为止**：`case.json` → grob 树（`ggcore.grobs`）→
`ggcore.grobs.scene()`（场景遍历）→ 扁平的 :class:`~ggcore.grobs.Scene` →
本文件的临时 skia 设备。也就是说快照验证的是遍历结果（坐标、gpar、裁剪、
绘制顺序），不是另一套几何计算。

**这是一台临时设备**：M0-8 的 raster 设备落地后由它接班，本文件只保留到那时。
它刻意只实现 IR 那一层已经钉死的东西（局部坐标 + 页面仿射 + 页面裁剪矩形 +
解析后的 gpar），曲线 / 符号 / 文字的细节按下面「近似」一节的规则画。

case.json 的四个部分：

| 键 | 说明 |
| --- | --- |
| `device` | `width_in` / `height_in` / `pixels_per_inch` |
| `viewports` | 数组，每项是 `ggcore.viewport.viewport()` 的参数（同 viewport 用例） |
| `grobs` | grob 规格数组，按下标顺序绘制（`vp` 是 `viewports` 的下标） |
| `steps`（可选） | 先 `push` / `pop` 视口，再画 grobs |

grob 规格的公共键：`type`（见下表）、`name`、`gp`（字段同 `ggcore.viewport.gpar()`，
颜色写 `#RRGGBB`，`"NA"` 表示 R 的 `NA`）、`vp`。坐标写数字（缺省 `npc`）或
`[amount, "unit"]`，向量写成 `[[…], "unit"]`。

| `type` | 其它键 |
| --- | --- |
| `rect` / `raster` | `x` `y` `width` `height` `just` / `hjust` `vjust` |
| `circle` | `x` `y` `r` |
| `lines` | `x` `y` |
| `segments` | `x0` `y0` `x1` `y1` |
| `polyline` / `polygon` / `path` | `x` `y` `id`（`path` 另有 `rule`） |
| `points` | `x` `y` `pch` `size`（`size_units` 缺省 `char`） |
| `text` | `label` `x` `y` `just` `rot` |
| `xspline` | `x` `y` `shape` `open` |
| `bezier` | `x` `y` |
| `curve` | `x1` `y1` `x2` `y2` `curvature` `angle` `ncp` `shape` `square` |
| `null` / `zero` | — |
| `clip` | `x` `y` `width` `height` `children` |
| `gTree` | `children`、`childrenvp`（`viewports` 的下标数组） |
| `gtable` | `widths` `heights` `cells`（每项 `t` `l` `b` `r` `z` `clip` `name` `grob`） |

近似（都由 M0-8 接班，这里只为出图）：

- `xspline` 用 shape=0 的 Catmull-Rom 折线近似，`shape≠0` 退化成折线；
- `bezier` 每 4 个控制点画一段三次曲线（IR 的语义），不画高阶单曲线；
- `curve` 用「两端点 + 直角拐点」的二次曲线近似（`square=True, angle=90` 的形状）；
- `points` 的 `pch` 只实现常用编号（0/1/2/3/4/5/15..20/21..25），其余报错；
- 文字一律用 pixi 受管的 Noto Sans CJK SC 单一字面；字重 / 字形由 M0-7 的
  字体目录解析，快照不区分 `bold` / `italic`。

文字度量由本文件提供（`skia.Font.measureText`，即“实际渲染端”的口径），
经 `ViewportTree(metrics=...)` 注入，所以 `text` 的 `width` 与画出来的宽度一致。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import skia

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from ggcore.grobs import (  # noqa: E402  （src 布局，先补 path 再导入）
    bezier_grob,
    circle_grob,
    clip_path,
    curve_grob,
    g_table_grob,
    g_tree,
    lines_grob,
    null_grob,
    path_grob,
    points_grob,
    polygon_grob,
    polyline_grob,
    raster_grob,
    rect_grob,
    scene,
    segments_grob,
    text_grob,
    xspline_grob,
    zero_grob,
)
from ggcore.gtable import gtable, gtable_add_grob  # noqa: E402
from ggcore.ir import LineEnd, LineJoin  # noqa: E402
from ggcore.units import unit  # noqa: E402
from ggcore.viewport import (  # noqa: E402
    NA,
    Device,
    Gpar,
    Viewport,
    ViewportTree,
    viewport,
)

CASES = REPO / "docs" / "cases"
# 「Noto Sans CJK SC」同时覆盖拉丁与中日韩字形；DejaVu 只作兜底。
FONT_NAMES = ("NotoSansCJKsc-VF.ttf", "DejaVuSans.ttf")
STROKE_CAPS = {
    LineEnd.ROUND: skia.Paint.kRound_Cap,
    LineEnd.BUTT: skia.Paint.kButt_Cap,
    LineEnd.SQUARE: skia.Paint.kSquare_Cap,
}
STROKE_JOINS = {
    LineJoin.ROUND: skia.Paint.kRound_Join,
    LineJoin.MITER: skia.Paint.kMiter_Join,
    LineJoin.BEVEL: skia.Paint.kBevel_Join,
}


# ---------------------------------------------------------------------------
# case.json → grob 树
# ---------------------------------------------------------------------------


def _unit(spec: Any, default_units: str = "npc") -> Any:
    """`0.3` / `[0.3, "npc"]` / `[[0.1, 0.2], "npc"]` → `Unit`。"""
    if isinstance(spec, (int, float)):
        return unit(float(spec), default_units)
    amount, kind = spec
    if isinstance(amount, (list, tuple)):
        return unit([float(item) for item in amount], kind)
    return unit(float(amount), kind)


def _color(value: str) -> int:
    text = value.lstrip("#")
    red, green, blue = (int(text[index : index + 2], 16) for index in (0, 2, 4))
    return skia.ColorSetARGB(255, red, green, blue)


def _gp_fields(spec: dict[str, Any] | None) -> dict[str, Any] | None:
    """JSON 里的 gp → `Gpar` 的字段字典（`"NA"` → 哨兵；列表保持列表 = 向量 gp）。

    映射里的列表原样交给 grob 构造器（`ggcore.grobs` 按元素摊开），视口那边
    要求标量，由 :func:`_build_viewport` 自己收窄。
    """
    if not spec:
        return None
    return {
        name: (NA if isinstance(value, str) and value == "NA" else value)
        for name, value in spec.items()
    }


def _build_viewport(spec: dict[str, Any]) -> Viewport:
    return viewport(
        spec["name"],
        x=_unit(spec["x"]),
        y=_unit(spec["y"]),
        width=_unit(spec["width"]),
        height=_unit(spec["height"]),
        just=spec.get("just", "centre"),
        xscale=spec.get("xscale", (0.0, 1.0)),
        yscale=spec.get("yscale", (0.0, 1.0)),
        angle=spec.get("angle", 0.0),
        clip=spec.get("clip", "inherit"),
        gp=Gpar(**(_gp_fields(spec.get("gp")) or {})),
    )


def build_grob(spec: dict[str, Any], viewports: list[Viewport]) -> Any:
    """一个 grob 规格 → 真 grob（子节点递归）。"""
    kind = spec["type"]
    common: dict[str, Any] = {}
    if "name" in spec:
        common["name"] = spec["name"]
    gp = _gp_fields(spec.get("gp"))
    if gp is not None:
        common["gp"] = gp
    if "vp" in spec:
        common["vp"] = viewports[spec["vp"]]
    default_units = spec.get("units", "npc")

    if kind == "rect":
        return rect_grob(
            x=_unit(spec.get("x", 0.5), default_units),
            y=_unit(spec.get("y", 0.5), default_units),
            width=_unit(spec.get("width", 1.0), default_units),
            height=_unit(spec.get("height", 1.0), default_units),
            just=spec.get("just", "centre"),
            default_units=default_units,
            **common,
        )
    if kind == "circle":
        return circle_grob(
            x=_unit(spec.get("x", 0.5), default_units),
            y=_unit(spec.get("y", 0.5), default_units),
            r=_unit(spec.get("r", 0.5), default_units),
            default_units=default_units,
            **common,
        )
    if kind == "lines":
        return lines_grob(
            _unit(spec.get("x", [[0.0, 1.0], "npc"]), default_units),
            _unit(spec.get("y", [[0.0, 1.0], "npc"]), default_units),
            **common,
        )
    if kind == "segments":
        return segments_grob(
            _unit(spec.get("x0", 0.0), default_units),
            _unit(spec.get("y0", 0.0), default_units),
            _unit(spec.get("x1", 1.0), default_units),
            _unit(spec.get("y1", 1.0), default_units),
            default_units=default_units,
            **common,
        )
    if kind in ("polyline", "polygon", "path"):
        factory = {"polyline": polyline_grob, "polygon": polygon_grob, "path": path_grob}[kind]
        extra = {"rule": spec["rule"]} if kind == "path" and "rule" in spec else {}
        return factory(
            _unit(spec.get("x", [[0.0, 1.0, 0.5], "npc"]), default_units),
            _unit(spec.get("y", [[0.0, 0.0, 1.0], "npc"]), default_units),
            id=spec.get("id"),
            default_units=default_units,
            **extra,
            **common,
        )
    if kind == "points":
        return points_grob(
            _unit(spec.get("x", 0.5), default_units),
            _unit(spec.get("y", 0.5), default_units),
            pch=spec.get("pch", 1),
            size=_unit(spec.get("size", 1.0), spec.get("size_units", "char")),
            size_units=spec.get("size_units", "char"),
            default_units=default_units,
            **common,
        )
    if kind == "text":
        return text_grob(
            spec["label"],
            x=_unit(spec["x"], default_units),
            y=_unit(spec["y"], default_units),
            just=spec.get("just", "centre"),
            rot=spec.get("rot", 0.0),
            default_units=default_units,
            **common,
        )
    if kind == "raster":
        data, width_px, height_px = _raster_image(spec.get("image", "gradient"), spec)
        return raster_grob(
            data,
            width_px,
            height_px,
            x=_unit(spec.get("x", 0.5), default_units),
            y=_unit(spec.get("y", 0.5), default_units),
            width=_unit(spec.get("width", 1.0), default_units),
            height=_unit(spec.get("height", 1.0), default_units),
            just=spec.get("just", "centre"),
            interpolate=spec.get("interpolate", True),
            **common,
        )
    if kind == "xspline":
        return xspline_grob(
            _unit(spec.get("x", [[0.0, 1.0], "npc"]), default_units),
            _unit(spec.get("y", [[0.0, 1.0], "npc"]), default_units),
            id=spec.get("id"),
            shape=spec.get("shape", 0.0),
            open=spec.get("open", True),
            default_units=default_units,
            **common,
        )
    if kind == "bezier":
        return bezier_grob(
            _unit(spec.get("x", [[0.0, 0.3, 0.7, 1.0], "npc"]), default_units),
            _unit(spec.get("y", [[0.0, 1.0, 1.0, 0.0], "npc"]), default_units),
            **common,
        )
    if kind == "curve":
        return curve_grob(
            _unit(spec.get("x1", 0.0), default_units),
            _unit(spec.get("y1", 0.0), default_units),
            _unit(spec.get("x2", 1.0), default_units),
            _unit(spec.get("y2", 1.0), default_units),
            curvature=spec.get("curvature", 1.0),
            angle=spec.get("angle", 90.0),
            ncp=spec.get("ncp", 1),
            shape=spec.get("shape", 0.5),
            square=spec.get("square", True),
            **common,
        )
    if kind == "null":
        return null_grob(**common)
    if kind == "zero":
        return zero_grob(**common)
    if kind == "clip":
        return clip_path(
            *[build_grob(child, viewports) for child in spec.get("children", [])],
            x=_unit(spec.get("x", 0.0), default_units),
            y=_unit(spec.get("y", 0.0), default_units),
            width=_unit(spec.get("width", 1.0), default_units),
            height=_unit(spec.get("height", 1.0), default_units),
            just=spec.get("just", ("left", "bottom")),
            default_units=default_units,
            **common,
        )
    if kind == "gTree":
        return g_tree(
            *[build_grob(child, viewports) for child in spec.get("children", [])],
            childrenvp=[viewports[index] for index in spec.get("childrenvp", [])] or None,
            **common,
        )
    if kind == "gtable":
        table = gtable(
            widths=[_unit(item) for item in spec["widths"]],
            heights=[_unit(item) for item in spec["heights"]],
            respect=spec.get("respect", False),
            name=spec.get("name", "layout"),
        )
        for cell in spec.get("cells", []):
            table = gtable_add_grob(
                table,
                build_grob(cell["grob"], viewports),
                t=cell["t"],
                l=cell["l"],
                b=cell.get("b", cell["t"]),
                r=cell.get("r", cell["l"]),
                z=cell.get("z", math.inf),
                clip=cell.get("clip", "on"),
                name=cell.get("name", "layout"),
            )
        return g_table_grob(table, name=spec.get("name"))
    raise ValueError(f"unknown grob type {kind!r}")


def _raster_image(kind: str, spec: dict[str, Any]) -> tuple[bytes, int, int]:
    """用例自带的小位图：确定性生成，不让二进制素材进仓库。"""
    if kind != "gradient":  # pragma: no cover - 规格写错才会走到
        raise ValueError(f"unknown raster image {kind!r}")
    size = int(spec.get("size", 24))
    ramp = np.linspace(0, 255, size, dtype=np.uint8)
    red = np.tile(ramp, (size, 1))
    green = np.tile(ramp.reshape(-1, 1), (1, size))
    blue = np.full((size, size), 96, dtype=np.uint8)
    alpha = np.full((size, size), 255, dtype=np.uint8)
    pixels = np.dstack([blue, green, red, alpha])  # skia 的 N32 是 BGRA
    image = skia.Image.fromarray(np.ascontiguousarray(pixels), colorType=skia.kBGRA_8888_ColorType)
    data = image.encodeToData(skia.kPNG, 100)
    if data is None:  # pragma: no cover - 编码失败才会发生
        raise SystemExit("raster PNG encoding failed")
    return bytes(data.bytes()), size, size


# ---------------------------------------------------------------------------
# 文字度量：交给实际渲染端（skia）
# ---------------------------------------------------------------------------


def font_file() -> Path:
    """pixi 环境里的 Noto Sans CJK SC（`font-ttf-noto-cjk`），兜底 DejaVu Sans。"""
    prefix = os.environ.get("CONDA_PREFIX")
    roots = [Path(prefix)] if prefix else []
    roots.extend([Path(sys.prefix), REPO / ".pixi" / "envs" / "dev"])
    for name in FONT_NAMES:
        for root in roots:
            for candidate in (root / "fonts" / name, root / "share" / "fonts" / name):
                if candidate.is_file():
                    return candidate
            hits = sorted(root.glob(f"**/{name}"))[:1] if root.is_dir() else []
            if hits:
                return hits[0]
    raise SystemExit(f"找不到受管字体 {FONT_NAMES}（pixi 的 font-ttf-* 应提供它们）")


class SkiaMetrics:
    """`ggcore.units.Metrics` 的 skia 实现：返回英寸（单位系统要的口径）。"""

    def __init__(self, typeface: skia.Typeface) -> None:
        self.typeface = typeface

    def _font(self, fontsize: float, cex: float) -> skia.Font:
        return skia.Font(self.typeface, max(float(fontsize) * float(cex), 1e-3))

    def strwidth(self, text: str, *, fontsize: float, cex: float) -> float:
        return float(self._font(fontsize, cex).measureText(text)) / 72.0

    def strheight(self, text: str, *, fontsize: float, cex: float) -> float:
        metrics = self._font(fontsize, cex).getMetrics()
        return float(-metrics.fAscent + metrics.fDescent) / 72.0


# ---------------------------------------------------------------------------
# 临时 skia 设备：只认 Scene
# ---------------------------------------------------------------------------


class SkiaDevice:
    """把扁平指令画到 skia 画布上（M0-8 raster 设备的临时替身）。"""

    def __init__(self, scene: Any, pixels_per_inch: float) -> None:
        self.scene = scene
        self.ppi = float(pixels_per_inch)
        self.typeface = skia.Typeface.MakeFromFile(str(font_file()))
        if self.typeface is None:  # pragma: no cover - 字体损坏才会发生
            raise SystemExit(f"无法加载字体 {font_file()}")
        width_px = round(scene.device.width_in * self.ppi)
        height_px = round(scene.device.height_in * self.ppi)
        self.surface = skia.Surface.MakeRasterN32Premul(width_px, height_px)
        self.canvas = self.surface.getCanvas()
        self.canvas.clear(skia.ColorWHITE)
        self.canvas.scale(self.ppi / 72.0, self.ppi / 72.0)  # 页面 pt → 像素

    # -- 画笔 ---------------------------------------------------------------

    def _paint(self, gpar: Any, *, stroke: bool, use_col: bool = False) -> skia.Paint | None:
        # 填充用 `fill`；描边与文字都用 `col`（IR：text 的字色就是 col）。
        colour = gpar.col if (stroke or use_col) else gpar.fill
        if colour is None:
            return None
        red, green, blue, alpha = colour
        paint = skia.Paint(AntiAlias=True)
        paint.setColor(skia.ColorSetARGB(round(alpha * gpar.alpha), red, green, blue))
        if stroke:
            paint.setStyle(skia.Paint.kStroke_Style)
            # 画布已经缩放到页面 pt，所以线宽直接就是 IR 里的 pt。
            paint.setStrokeWidth(gpar.lwd)
            paint.setStrokeCap(STROKE_CAPS[gpar.lineend])
            paint.setStrokeJoin(STROKE_JOINS[gpar.linejoin])
            paint.setStrokeMiter(gpar.linemitre)
            if gpar.lty:
                paint.setPathEffect(skia.DashPathEffect.Make(list(gpar.lty), 0.0))
        else:
            paint.setStyle(skia.Paint.kFill_Style)
        return paint

    def _font(self, size_pt: float) -> skia.Font:
        return skia.Font(self.typeface, max(float(size_pt), 0.1))

    def label(self, text: str, x: float, y: float, size_pt: float, colour: str) -> None:
        """页眉页脚：用页面 pt 直接落字（不参与场景遍历）。"""
        paint = skia.Paint(AntiAlias=True)
        paint.setColor(_color(colour))
        self.canvas.drawString(text, x, y, self._font(size_pt), paint)

    # -- 主循环 -------------------------------------------------------------

    def paint_instructions(self) -> None:
        for instruction in self.scene.instructions:
            self._draw(instruction)

    def snapshot(self) -> bytes:
        image = self.surface.makeImageSnapshot()
        data = image.encodeToData(skia.kPNG, 100)
        if data is None:  # pragma: no cover - 编码失败才会发生
            raise SystemExit("PNG encoding failed")
        return bytes(data.bytes())

    def _draw(self, instruction: Any) -> None:
        self.canvas.save()
        x0, y0, x1, y1 = instruction.clip
        self.canvas.clipRect(skia.Rect.MakeLTRB(x0, y0, x1, y1))
        a, b, c, d, e, f = instruction.transform
        # 行向量仿射（x' = ax + cy + e）→ skia 的行主序矩阵
        self.canvas.concat(skia.Matrix.MakeAll(a, c, e, b, d, f, 0, 0, 1))
        handler = getattr(self, f"_draw_{instruction.kind.value}", None)
        if handler is None:  # pragma: no cover - 新增原语忘了画
            raise SystemExit(f"no painter for {instruction.kind}")
        handler(instruction)
        self.canvas.restore()

    # -- 各原语 -------------------------------------------------------------

    def _draw_rect(self, instruction: Any) -> None:
        for x0, y0, x1, y1 in instruction.bufs["rect"]:
            rect = skia.Rect.MakeLTRB(float(x0), float(y0), float(x1), float(y1))
            fill = self._paint(instruction.gpar, stroke=False)
            if fill is not None:
                self.canvas.drawRect(rect, fill)
            stroke = self._paint(instruction.gpar, stroke=True)
            if stroke is not None:
                self.canvas.drawRect(rect, stroke)

    def _draw_circle(self, instruction: Any) -> None:
        for cx, cy, radius in instruction.bufs["circle"]:
            fill = self._paint(instruction.gpar, stroke=False)
            if fill is not None:
                self.canvas.drawCircle(float(cx), float(cy), float(radius), fill)
            stroke = self._paint(instruction.gpar, stroke=True)
            if stroke is not None:
                self.canvas.drawCircle(float(cx), float(cy), float(radius), stroke)

    def _draw_lines(self, instruction: Any) -> None:
        points = instruction.bufs["points"]
        path = skia.Path()
        path.moveTo(float(points[0, 0]), float(points[0, 1]))
        for x, y in points[1:]:
            path.lineTo(float(x), float(y))
        stroke = self._paint(instruction.gpar, stroke=True)
        if stroke is not None:
            self.canvas.drawPath(path, stroke)

    def _draw_segments(self, instruction: Any) -> None:
        stroke = self._paint(instruction.gpar, stroke=True)
        if stroke is None:
            return
        for x0, y0, x1, y1 in instruction.bufs["segments"]:
            self.canvas.drawLine(float(x0), float(y0), float(x1), float(y1), stroke)

    def _grouped_path(self, instruction: Any, *, closed: bool) -> skia.Path:
        points = instruction.bufs["points"]
        ids = instruction.bufs.get("id")
        path = skia.Path()
        if ids is None:
            codes = np.zeros(len(points), dtype=np.int64)
        else:
            codes = np.asarray(ids)
        start = True
        for index, (x, y) in enumerate(points):
            if start or codes[index] != codes[index - 1]:
                path.moveTo(float(x), float(y))
                start = False
            else:
                path.lineTo(float(x), float(y))
        if closed:
            path.close()
        return path

    def _stroke_and_fill(self, instruction: Any, path: skia.Path) -> None:
        fill = self._paint(instruction.gpar, stroke=False)
        if fill is not None:
            self.canvas.drawPath(path, fill)
        stroke = self._paint(instruction.gpar, stroke=True)
        if stroke is not None:
            self.canvas.drawPath(path, stroke)

    def _draw_polyline(self, instruction: Any) -> None:
        self._stroke_and_fill(instruction, self._grouped_path(instruction, closed=False))

    def _draw_polygon(self, instruction: Any) -> None:
        self._stroke_and_fill(instruction, self._grouped_path(instruction, closed=True))

    def _draw_path(self, instruction: Any) -> None:
        path = self._grouped_path(instruction, closed=True)
        path.setFillType(
            skia.PathFillType.kEvenOdd
            if instruction.params["rule"] == "evenodd"
            else skia.PathFillType.kWinding
        )
        self._stroke_and_fill(instruction, path)

    def _draw_points(self, instruction: Any) -> None:
        pch = int(instruction.params["pch"])
        size = float(instruction.params["size"])
        radius = max(size / 2.0, 0.1)
        stroke = self._paint(instruction.gpar, stroke=True)
        fill = self._paint(instruction.gpar, stroke=False)
        if stroke is None and fill is None:
            return
        for cx, cy in instruction.bufs["points"]:
            self._symbol(pch, float(cx), float(cy), radius, stroke, fill)

    def _symbol(
        self,
        pch: int,
        cx: float,
        cy: float,
        radius: float,
        stroke: skia.Paint | None,
        fill: skia.Paint | None,
    ) -> None:
        """常用 `pch` 的子集（M0-8 补全表；这里够画快照）。"""
        if pch not in (0, 1, 2, 3, 4, 5, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25):
            raise SystemExit(f"pch {pch} 不在临时设备的实现范围内（见 grob_cases.py 顶部）")
        # 21..25 与 15..20 同形状，区别只在填充色（fill vs col），见下方 filled_* 判断。
        base = pch - 6 if pch in (21, 22, 23, 24, 25) else pch
        closed = base in (0, 1, 2, 5, 15, 16, 17, 18, 19, 20)
        if pch in (3, 4):  # 加号 / 叉号
            paint = stroke or fill
            assert paint is not None
            if pch == 3:
                self.canvas.drawLine(cx - radius, cy, cx + radius, cy, paint)
                self.canvas.drawLine(cx, cy - radius, cx, cy + radius, paint)
            else:
                self.canvas.drawLine(cx - radius, cy - radius, cx + radius, cy + radius, paint)
                self.canvas.drawLine(cx - radius, cy + radius, cx + radius, cy - radius, paint)
            return
        path = skia.Path()
        if base in (1, 16, 19, 20):
            path.addCircle(cx, cy, radius)
        elif base in (0, 15):
            path.addRect(skia.Rect.MakeLTRB(cx - radius, cy - radius, cx + radius, cy + radius))
        elif base in (2, 17):
            path.moveTo(cx, cy - radius)
            path.lineTo(cx + radius * 0.866, cy + radius * 0.5)
            path.lineTo(cx - radius * 0.866, cy + radius * 0.5)
            path.close()
        elif base in (5, 18):
            path.moveTo(cx, cy - radius)
            path.lineTo(cx + radius, cy)
            path.lineTo(cx, cy + radius)
            path.lineTo(cx - radius, cy)
            path.close()
        else:
            raise SystemExit(f"pch {pch} 未实现")
        # R 的 pch：15..20 用 col 实心；21..25 用 fill 填充 + col 描边；其余只描边。
        filled_with_col = base in (15, 16, 17, 18, 19, 20)
        if closed:
            body = stroke if filled_with_col else fill
            if body is not None:
                self.canvas.drawPath(path, body)
            if stroke is not None and not filled_with_col:
                self.canvas.drawPath(path, stroke)

    def _draw_text(self, instruction: Any) -> None:
        # IR 的 text 用 `col` 着色（与 grid 一致），不是 `fill`。
        paint = self._paint(instruction.gpar, stroke=False, use_col=True)
        if paint is None:
            return
        font = self._font(float(instruction.params["size"]))
        anchor = instruction.params["anchor"]
        baseline = instruction.params["baseline"]
        angle = float(instruction.params["angle"])
        metrics = font.getMetrics()
        ascent = float(-metrics.fAscent)
        descent = float(metrics.fDescent)
        shift = {
            "alphabetic": 0.0,
            "top": ascent,
            "middle": (ascent - descent) / 2.0,
            "bottom": -descent,
        }[baseline]
        positions = instruction.bufs["pos"]
        widths = instruction.bufs["width"]
        for index, label in enumerate(instruction.texts):
            x, y = float(positions[index, 0]), float(positions[index, 1])
            width = float(widths[index])
            dx = {"left": 0.0, "center": -width / 2.0, "right": -width}[anchor]
            self.canvas.save()
            self.canvas.translate(x, y)
            if angle:
                # 页面坐标 y 向下，IR 的角度按逆时针记：skia 的正角是顺时针。
                self.canvas.rotate(-angle, 0.0, 0.0)
            self.canvas.drawString(label, dx, shift, font, paint)
            self.canvas.restore()

    def _draw_raster(self, instruction: Any) -> None:
        blob = self.scene.blobs[instruction.params["blob"]]
        image = skia.Image.MakeFromEncoded(blob.data)
        if image is None:  # pragma: no cover - 坏位图才会发生
            raise SystemExit("cannot decode raster blob")
        x0, y0, x1, y1 = (float(value) for value in instruction.bufs["rect"][0])
        sampling = (
            skia.SamplingOptions(skia.FilterMode.kLinear)
            if instruction.params["interpolate"]
            else skia.SamplingOptions(skia.FilterMode.kNearest)
        )
        self.canvas.drawImageRect(
            image,
            skia.Rect.MakeLTRB(x0, y0, x1, y1),
            sampling,
            skia.Paint(AntiAlias=True),
        )

    def _draw_xspline(self, instruction: Any) -> None:
        points = instruction.bufs["points"]
        ids = instruction.bufs.get("id")
        path = skia.Path()
        shape = float(instruction.params["shape"])
        open_curve = bool(instruction.params["open"])
        codes = np.zeros(len(points), dtype=np.int64) if ids is None else np.asarray(ids)
        groups: dict[int, list[tuple[float, float]]] = {}
        order: list[int] = []
        for index, point in enumerate(points):
            code = int(codes[index])
            if code not in groups:
                groups[code] = []
                order.append(code)
            groups[code].append((float(point[0]), float(point[1])))
        for code in order:
            group = groups[code]
            if abs(shape) < 1e-9 and len(group) > 2:
                self._catmull_rom(path, group, closed=not open_curve)
            else:
                path.moveTo(*group[0])
                for point in group[1:]:
                    path.lineTo(*point)
        self._stroke_and_fill(instruction, path)

    @staticmethod
    def _catmull_rom(path: skia.Path, points: list[tuple[float, float]], *, closed: bool) -> None:
        """Catmull-Rom 近似（shape = 0；每段采样 16 个点）。"""
        count = len(points)
        path.moveTo(*points[0])
        for index in range(count - 1):
            p0 = points[max(index - 1, 0)]
            p1 = points[index]
            p2 = points[index + 1]
            p3 = points[min(index + 2, count - 1)]
            for step in range(1, 17):
                t = step / 16.0
                t2 = t * t
                t3 = t2 * t
                x = 0.5 * (
                    2 * p1[0]
                    + (-p0[0] + p2[0]) * t
                    + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                    + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
                )
                y = 0.5 * (
                    2 * p1[1]
                    + (-p0[1] + p2[1]) * t
                    + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                    + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
                )
                path.lineTo(x, y)
        if closed:
            path.close()

    def _draw_bezier(self, instruction: Any) -> None:
        control = instruction.bufs["control"]
        path = skia.Path()
        path.moveTo(float(control[0, 0]), float(control[0, 1]))
        for index in range(0, len(control), 4):
            segment = control[index : index + 4]
            path.cubicTo(
                float(segment[1, 0]),
                float(segment[1, 1]),
                float(segment[2, 0]),
                float(segment[2, 1]),
                float(segment[3, 0]),
                float(segment[3, 1]),
            )
        self._stroke_and_fill(instruction, path)

    def _draw_curve(self, instruction: Any) -> None:
        ends = instruction.bufs["ends"]
        square = bool(instruction.params["square"])
        stroke = self._paint(instruction.gpar, stroke=True)
        if stroke is None:
            return
        for x1, y1, x2, y2 in ends:
            path = skia.Path()
            path.moveTo(float(x1), float(y1))
            # square=True, angle=90：控制点取“过两端点、与 x/y 轴平行”的交点（直角拐角）。
            corner = (
                (float(x2), float(y1))
                if square
                else (
                    (float(x1) + float(x2)) / 2.0,
                    (float(y1) + float(y2)) / 2.0,
                )
            )
            path.quadTo(corner[0], corner[1], float(x2), float(y2))
            self.canvas.drawPath(path, stroke)


# ---------------------------------------------------------------------------
# case → PNG
# ---------------------------------------------------------------------------


def build(case: dict[str, Any]) -> tuple[Any, float]:
    """case.json → （场景, 像素每英寸）。测试用它，渲染也用它。"""
    if case.get("kind") != "grob":
        raise ValueError(f"{case.get('id')}: not a grob case")
    device_spec = case["device"]
    ppi = float(device_spec["pixels_per_inch"])
    device = Device(float(device_spec["width_in"]), float(device_spec["height_in"]))
    typeface = skia.Typeface.MakeFromFile(str(font_file()))
    if typeface is None:  # pragma: no cover - 字体损坏才会发生
        raise SystemExit(f"无法加载字体 {font_file()}")
    tree = ViewportTree(device, metrics=SkiaMetrics(typeface))
    viewports = [_build_viewport(spec) for spec in case.get("viewports", [])]
    for step in case.get("steps", []):
        if step["op"] == "push":
            tree.push(viewports[step["vp"]])
        elif step["op"] == "pop":
            tree.pop(step.get("n", 1))
        else:  # pragma: no cover - 规格写错才会走到
            raise ValueError(f"{case['id']}: unknown step op {step['op']!r}")
    grobs = [build_grob(spec, viewports) for spec in case.get("grobs", [])]
    return scene(grobs, tree), ppi


def render(case: dict[str, Any]) -> bytes:
    resolved, ppi = build(case)
    painter = SkiaDevice(resolved, ppi)
    painter.paint_instructions()
    if case.get("title"):
        painter.label(case["title"], 12.0, 20.0, 10.0, "#222222")
    if case.get("caption"):
        painter.label(case["caption"], 12.0, resolved.size_pt[1] - 10.0, 7.0, "#555555")
    return painter.snapshot()


def load_cases(root: Path = CASES) -> list[tuple[Path, dict[str, Any]]]:
    cases: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.glob("*/case.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("kind") == "grob":
            cases.append((path.parent, data))
    return cases


def decode(png: bytes) -> np.ndarray[Any, Any]:
    """PNG 字节 → (h, w, 4) uint8。

    显式拷贝：skia 的懒解码图引用的是 `png` 那份字节，函数返回后两者都可能被回收，
    `toarray()` 的视图就会指向已经失效的缓冲（比对时会读成一片 0）。所以在
    `image` 还活着的时候拷一份出来。
    """
    image = skia.Image.MakeFromEncoded(png)
    if image is None:  # pragma: no cover - 坏 PNG 才会发生
        raise ValueError("cannot decode PNG")
    return np.array(image.toarray(), dtype=np.uint8, copy=True)


def compare(actual: bytes, expected: bytes) -> str | None:
    """像素比对（与 viewport 快照同一阈值，见 docs/notes/snapshot-policy.md）。"""
    left = decode(actual)
    right = decode(expected)
    if left.shape != right.shape:
        return f"size differs: {left.shape} vs {right.shape}"
    diff = np.abs(left.astype(np.int16) - right.astype(np.int16))
    worst = int(diff.max())
    mean = float(diff.mean())
    if worst <= 4 and mean <= 0.05:
        return None
    differing = int((diff.max(axis=2) > 24).sum())
    return f"max channel diff {worst}, mean {mean:.3f}, {differing} pixel(s) over 24"


def baseline_name(case: dict[str, Any]) -> str:
    return f"{case['id']}.png"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render grob snapshot cases to PNG.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare with the committed baseline instead of writing it",
    )
    parser.add_argument(
        "--case", action="append", dest="cases", help="only handle this case id (repeatable)"
    )
    args = parser.parse_args(argv)

    cases = load_cases()
    if not cases:
        print("cases:grob: no grob case found", file=sys.stderr)
        return 2
    wanted = set(args.cases or [])
    failures = 0
    for directory, case in cases:
        if wanted and case["id"] not in wanted:
            continue
        png = render(case)
        target = directory / "baseline" / baseline_name(case)
        if args.check:
            if not target.is_file():
                print(f"{case['id']}: missing baseline {target.relative_to(REPO)}", file=sys.stderr)
                failures += 1
                continue
            problem = compare(png, target.read_bytes())
            if problem is not None:
                print(f"{case['id']}: baseline differs — {problem}", file=sys.stderr)
                failures += 1
            else:
                print(f"{case['id']}: ok ({len(png)} bytes)")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png)
            print(f"wrote {target.relative_to(REPO)} ({len(png)} bytes)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
