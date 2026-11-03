"""skia 三路设备：PNG / SVG / PDF（M0-8）。

一台遍历器（`_SkiaDevice._paint_node`）+ 三个后端钩子（`_emit_glyphs` 与
`_begin` / `_finish`）。遍历器只做 IR 已经钉死的事：

- 自下而上合成 `viewport.transform`，**在页面空间**裁 `viewport.clip_rect`
  （`docs/notes/ir.md` §4 的消费约束）；
- `text.angle` 只叠局部旋转（视口旋转已经在 `transform` 里，`ir.md` §7）；
- gpar 是解析后的最终值，容器不带 gpar。

三个后端的差别只有两处：

| | 文字 | 画布 |
| --- | --- | --- |
| raster | `TextBlob`（skia 字形渲染，逐像素等于 `drawString()`） | 栅格画布 + `dpi` 缩放 |
| svg | 字形轮廓 `Font.getPath()` | `SVGCanvas.Make`（`kNoPrettyXML`） |
| pdf | 字形轮廓 `Font.getPath()` | `PDF.MakeDocument` + `beginPage` |

矢量后端把文字画成轮廓是 M0-8 的硬约束：PDF 产物里不能有 `/Font`（CJK 不依赖
阅读端字体），SVG 里不能有 `<text>`（`docs/notes/e3` 的结论：CanvasKit 只有
栅格后端，桌面 SVG 由 skia 序列化，文字必须是路径）。轮廓与栅格共用同一份
shaping 与笔位（`ggskia.text`），所以三路的位置一致，差的只是字形边缘的抗锯齿。
"""

from __future__ import annotations

import math
import re
import warnings
from collections.abc import Iterator, Sequence
from typing import Any

import numpy as np
import skia

from ggcore.arrow import head_geometry
from ggcore.device import Device, DeviceError, DeviceWarning
from ggcore.ir import LineEnd, LineJoin, NodeKind, Scene
from ggcore.png import encode_rgba
from ggskia.curves import curve_points, xspline_points
from ggskia.pch import character_pch, symbol
from ggskia.text import LINE_PITCH, TextShaper

__all__ = ["SkiaPdfDevice", "SkiaRasterDevice", "SkiaSvgDevice"]

_CAPS = {
    LineEnd.ROUND: skia.Paint.kRound_Cap,
    LineEnd.BUTT: skia.Paint.kButt_Cap,
    LineEnd.SQUARE: skia.Paint.kSquare_Cap,
}
_JOINS = {
    LineJoin.ROUND: skia.Paint.kRound_Join,
    LineJoin.MITER: skia.Paint.kMiter_Join,
    LineJoin.BEVEL: skia.Paint.kBevel_Join,
}


class _SkiaDevice(Device):
    """一台 skia 画布 + IR 遍历器。子类只需给画布与编码。"""

    #: emoji 字面策略：栅格用彩色 CBDT 位图，矢量后端用单色 Noto Emoji 轮廓。
    emoji_mode = "color"

    def __init__(
        self,
        width_pt: float,
        height_pt: float,
        dpi: float = 72.0,
        *,
        shaper: TextShaper | None = None,
    ) -> None:
        super().__init__(width_pt, height_pt, dpi=dpi)
        self.shaper = shaper if shaper is not None else TextShaper(emoji=self.emoji_mode)
        self.canvas: skia.Canvas | None = None
        self.scene: Scene | None = None

    # -- 子类钩子 -----------------------------------------------------------

    def _emit_glyphs(
        self,
        font: skia.Font,
        gids: Sequence[int],
        positions: Sequence[skia.Point],
        paint: skia.Paint,
    ) -> None:
        raise NotImplementedError

    # -- 遍历 ---------------------------------------------------------------

    def _draw_scene(self, scene: Scene) -> None:
        self.scene = scene
        self._paint_node(scene.root)

    def _paint_node(self, node: Any) -> None:
        kind = node.kind
        if kind is NodeKind.VIEWPORT:
            assert self.canvas is not None
            self.canvas.save()
            clip = node.bufs.get("clip_rect")
            if clip is not None:
                x0, y0, x1, y1 = (float(value) for value in clip[0])
                # 页面坐标：在 concat 之前裁，裁完再进子坐标系。
                self.canvas.clipRect(skia.Rect.MakeLTRB(x0, y0, x1, y1))
            a, b, c, d, e, f = node.params["transform"]
            # 行向量仿射（x' = ax + cy + e）→ skia 的行主序矩阵
            self.canvas.concat(skia.Matrix.MakeAll(a, c, e, b, d, f, 0, 0, 1))
            for child in node.children:
                self._paint_node(child)
            self.canvas.restore()
            return
        if kind is NodeKind.GTREE:
            for child in node.children:
                self._paint_node(child)
            return
        if kind is NodeKind.CLIP:
            self._paint_clip(node)
            return
        if kind in (NodeKind.NULL, NodeKind.ZERO):
            return
        handler = getattr(self, f"_draw_{kind.value}", None)
        if handler is None:  # pragma: no cover - 新增原语忘了画
            raise DeviceError(f"没有 {kind} 的画法")
        handler(node)

    def _paint_clip(self, node: Any) -> None:
        assert self.canvas is not None
        self.canvas.save()
        rect = node.bufs.get("rect")
        if rect is not None:
            x0, y0, x1, y1 = (float(value) for value in rect[0])
            self.canvas.clipRect(skia.Rect.MakeLTRB(x0, y0, x1, y1))
        else:
            path = self._polyline_path(node, closed=True)
            path.setFillType(
                skia.PathFillType.kEvenOdd
                if node.params["rule"] == "evenodd"
                else skia.PathFillType.kWinding
            )
            self.canvas.clipPath(path, doAntiAlias=True)
        for child in node.children:
            self._paint_node(child)
        self.canvas.restore()

    # -- 画笔 ---------------------------------------------------------------

    def _paint(self, gpar: Any, *, stroke: bool, use_col: bool = False) -> skia.Paint | None:
        colour = gpar.col if (stroke or use_col) else gpar.fill
        if colour is None:
            return None
        red, green, blue, alpha = colour
        paint = skia.Paint(AntiAlias=True)
        paint.setColor(skia.ColorSetARGB(round(alpha * gpar.alpha), red, green, blue))
        if stroke:
            paint.setStyle(skia.Paint.kStroke_Style)
            paint.setStrokeWidth(gpar.lwd)
            paint.setStrokeCap(_CAPS[gpar.lineend])
            paint.setStrokeJoin(_JOINS[gpar.linejoin])
            paint.setStrokeMiter(gpar.linemitre)
            if gpar.lty:
                paint.setPathEffect(skia.DashPathEffect.Make(list(gpar.lty), 0.0))
        else:
            paint.setStyle(skia.Paint.kFill_Style)
        return paint

    def _stroke_and_fill(self, node: Any, path: skia.Path, *, fill: bool = True) -> None:
        assert self.canvas is not None
        if fill:
            paint = self._paint(node.gpar, stroke=False)
            if paint is not None:
                self.canvas.drawPath(path, paint)
        stroke = self._paint(node.gpar, stroke=True)
        if stroke is not None:
            self.canvas.drawPath(path, stroke)

    # -- 几何 ---------------------------------------------------------------

    def _polyline_path(self, node: Any, *, closed: bool) -> skia.Path:
        """按 `id` 切子路径；NaN / Inf 是缺口（`docs/notes/ir.md` §5）。"""
        points = node.bufs["points"]
        ids = node.bufs.get("id")
        path = skia.Path()
        run: int | None = None
        for index in range(len(points)):
            x = float(points[index, 0])
            y = float(points[index, 1])
            if not (math.isfinite(x) and math.isfinite(y)):
                run = None
                continue
            code = int(ids[index]) if ids is not None else 0
            if run is None or code != run:
                path.moveTo(x, y)
                run = code
            else:
                path.lineTo(x, y)
        if closed:
            path.close()
        return path

    @staticmethod
    def _groups(points: np.ndarray[Any, Any], ids: Any) -> Iterator[np.ndarray[Any, Any]]:
        if ids is None:
            yield np.asarray(points)
            return
        codes = np.asarray(ids)
        start = 0
        for index in range(1, len(points) + 1):
            if index == len(points) or codes[index] != codes[start]:
                yield np.asarray(points[start:index])
                start = index

    @staticmethod
    def _polyline_path_from(points: np.ndarray[Any, Any], *, closed: bool) -> skia.Path:
        path = skia.Path()
        started = False
        for x, y in points:
            if not (math.isfinite(float(x)) and math.isfinite(float(y))):
                started = False
                continue
            if not started:
                path.moveTo(float(x), float(y))
                started = True
            else:
                path.lineTo(float(x), float(y))
        if closed:
            path.close()
        return path

    # -- 箭头（M2-S2） -------------------------------------------------------

    def _draw_arrow_heads(
        self, node: Any, first: tuple[float, float], last: tuple[float, float]
    ) -> None:
        """按节点参数画箭头（`grid::arrow` 的标记属性）。

        `first` / `last` 是路径两端的**相邻两点**（端点在前、切向上一点在后），
        切向由它们给出；箭翼几何与查看器共用 `ggcore.arrow.head_geometry()`。
        """
        ends = node.params.get("arrow", "none")
        if ends == "none":
            return
        length = float(node.params.get("arrow_length", 0.0))
        if length <= 0:
            return
        angle = float(node.params.get("arrow_angle", 30.0))
        closed = node.params.get("arrow_type", "open") == "closed"
        stroke = self._paint(node.gpar, stroke=True)
        fill = self._paint(node.gpar, stroke=False)
        if fill is None:
            fill = self._paint(node.gpar, stroke=False, use_col=True)
        assert self.canvas is not None
        tips: list[tuple[tuple[float, float], tuple[float, float]]] = []
        if ends in ("first", "both"):
            tips.append((first, last))
        if ends in ("last", "both"):
            tips.append((last, first))
        for tip, back in tips:
            b1, b2 = head_geometry(tip[0], tip[1], back[0], back[1], length_pt=length, angle=angle)
            if closed:
                path = skia.Path()
                path.moveTo(float(tip[0]), float(tip[1]))
                path.lineTo(b1[0], b1[1])
                path.lineTo(b2[0], b2[1])
                path.close()
                if fill is not None:
                    self.canvas.drawPath(path, fill)
                if stroke is not None:
                    self.canvas.drawPath(path, stroke)
            elif stroke is not None:
                self.canvas.drawLine(float(tip[0]), float(tip[1]), b1[0], b1[1], stroke)
                self.canvas.drawLine(float(tip[0]), float(tip[1]), b2[0], b2[1], stroke)

    # -- 原语 ---------------------------------------------------------------

    def _draw_rect(self, node: Any) -> None:
        assert self.canvas is not None
        for x0, y0, x1, y1 in node.bufs["rect"]:
            left, right = sorted((float(x0), float(x1)))
            top, bottom = sorted((float(y0), float(y1)))
            rect = skia.Rect.MakeLTRB(left, top, right, bottom)
            fill = self._paint(node.gpar, stroke=False)
            if fill is not None:
                self.canvas.drawRect(rect, fill)
            stroke = self._paint(node.gpar, stroke=True)
            if stroke is not None:
                self.canvas.drawRect(rect, stroke)

    def _draw_circle(self, node: Any) -> None:
        assert self.canvas is not None
        for cx, cy, radius in node.bufs["circle"]:
            fill = self._paint(node.gpar, stroke=False)
            if fill is not None:
                self.canvas.drawCircle(float(cx), float(cy), float(radius), fill)
            stroke = self._paint(node.gpar, stroke=True)
            if stroke is not None:
                self.canvas.drawCircle(float(cx), float(cy), float(radius), stroke)

    def _draw_lines(self, node: Any) -> None:
        self._stroke_and_fill(node, self._polyline_path(node, closed=False), fill=False)

    def _draw_segments(self, node: Any) -> None:
        assert self.canvas is not None
        stroke = self._paint(node.gpar, stroke=True)
        if stroke is None:
            return
        for x0, y0, x1, y1 in node.bufs["segments"]:
            if not all(math.isfinite(float(value)) for value in (x0, y0, x1, y1)):
                continue
            self.canvas.drawLine(float(x0), float(y0), float(x1), float(y1), stroke)
            self._draw_arrow_heads(node, (float(x0), float(y0)), (float(x1), float(y1)))

    def _draw_polyline(self, node: Any) -> None:
        self._stroke_and_fill(node, self._polyline_path(node, closed=False))
        points = node.bufs["points"]
        ids = node.bufs.get("id")
        for group in self._groups(np.asarray(points), ids):
            finite = [
                (float(x), float(y))
                for x, y in group
                if math.isfinite(float(x)) and math.isfinite(float(y))
            ]
            if len(finite) < 2:
                continue
            self._draw_arrow_heads(node, finite[0], finite[-1])

    def _draw_polygon(self, node: Any) -> None:
        self._stroke_and_fill(node, self._polyline_path(node, closed=True))

    def _draw_path(self, node: Any) -> None:
        path = self._polyline_path(node, closed=True)
        path.setFillType(
            skia.PathFillType.kEvenOdd
            if node.params["rule"] == "evenodd"
            else skia.PathFillType.kWinding
        )
        self._stroke_and_fill(node, path)

    def _draw_points(self, node: Any) -> None:
        assert self.canvas is not None
        pch = int(node.params["pch"])
        size = float(node.params["size"])
        stroke = self._paint(node.gpar, stroke=True)
        fill = self._paint(node.gpar, stroke=False)
        col_fill = self._paint(node.gpar, stroke=False, use_col=True)
        if stroke is None and fill is None:
            return
        text = character_pch(pch)
        if text is not None:
            # R 用当前 gp 的 fontsize，IR 的 points 没有这个字段：用 size 当字号。
            paint = self._paint(node.gpar, stroke=False, use_col=True)
            if paint is None:
                return
            for cx, cy in node.bufs["points"]:
                self._place_text(text, float(cx), float(cy), size, "center", "middle", 0.0, paint)
            return
        shape = symbol(pch, size)
        if shape is None:
            warnings.warn(
                f"pch {pch} 没有符号定义（R 也只是警告并跳过）", DeviceWarning, stacklevel=2
            )
            return
        for cx, cy in node.bufs["points"]:
            if not (math.isfinite(float(cx)) and math.isfinite(float(cy))):
                continue
            self.canvas.save()
            self.canvas.translate(float(cx), float(cy))
            if shape.fill_col and col_fill is not None:
                self.canvas.drawPath(shape.path, col_fill)
            if shape.fill_gpar and fill is not None:
                self.canvas.drawPath(shape.path, fill)
            if shape.stroke and stroke is not None:
                self.canvas.drawPath(shape.path, stroke)
            self.canvas.restore()

    def _draw_text(self, node: Any) -> None:
        # IR 的 text 用 `col` 着色（与 grid 一致），不是 `fill`。
        paint = self._paint(node.gpar, stroke=False, use_col=True)
        if paint is None:
            return
        size = float(node.params["size"])
        anchor = node.params["anchor"]
        baseline = node.params["baseline"]
        angle = float(node.params["angle"])
        positions = node.bufs["pos"]
        widths = node.bufs["width"]
        for index, label in enumerate(node.texts):
            x = float(positions[index, 0])
            y = float(positions[index, 1])
            self._place_text(
                label,
                x,
                y,
                size,
                anchor,
                baseline,
                angle,
                paint,
                width=float(widths[index]),
                font_key=node.params["font"],
            )

    def _place_text(
        self,
        label: str,
        x: float,
        y: float,
        size: float,
        anchor: str,
        baseline: str,
        angle: float,
        paint: skia.Paint,
        *,
        width: float | None = None,
        font_key: str = "sans",
    ) -> None:
        assert self.canvas is not None
        lines = label.split("\n")
        line_runs = [self.shaper.runs(font_key, line, size) for line in lines]
        if not any(line_runs):
            return
        first = next(runs[0] for runs in line_runs if runs)
        primary = self.shaper.font(first.face, size)
        metrics = primary.getMetrics()
        ascent = float(-metrics.fAscent)
        # R 4.5.3 的 `strheight`（grid 的 textGrob 用它做 vjust/heightDetails）
        # 实测 = 字体的 cap height × 72.27/72，不是 ascent + descent：
        # Noto CJK 20pt → 14.714（cap 14.66），Noto Sans 20pt → 14.338
        # （cap 14.28）；用 (ascent - descent)/2 会在 vjust=0.5 时多偏
        # 0.03em，落到 1px 字画的抗锯齿边缘上。见 metrics-ledger M1-文字测量。
        cap = float(metrics.fCapHeight)
        if cap > 0:
            cap *= 72.27 / 72.0
        else:  # 位图字体（CBDT）没有 cap height：退回字面框
            cap = ascent + float(metrics.fDescent)
        # 多行：R 4.5.3 实测行距 = 1.2 × lineheight × fontsize（默认 1.44×）；
        # 整块高度 = (n-1) × 行距 + strheight。
        block = (len(lines) - 1) * LINE_PITCH * size + cap
        top = {
            "alphabetic": -cap,
            "top": 0.0,
            "middle": -block / 2.0,
            "bottom": -block,
        }[baseline]
        self.canvas.save()
        self.canvas.translate(x, y)
        if angle:
            # 局部旋转：视口旋转已经在 `transform` 里。页面 y 向下、IR 角度逆时针。
            self.canvas.rotate(-angle, 0.0, 0.0)
        for index, runs in enumerate(line_runs):
            if not runs:
                continue
            line_width = sum(run.advance for run in runs)
            measured = line_width if width is None or len(lines) > 1 else width
            dx = {"left": 0.0, "center": -measured / 2.0, "right": -measured}[anchor]
            baseline_y = top + cap + index * LINE_PITCH * size
            pen = dx
            for run in runs:
                font = self.shaper.font(run.face, size)
                points = [skia.Point(pen + offset, baseline_y) for offset in run.offsets]
                self._emit_glyphs(font, run.gids, points, paint)
                pen += run.advance
        self.canvas.restore()

    def _draw_raster(self, node: Any) -> None:
        assert self.canvas is not None
        assert self.scene is not None
        blob = self.scene.blobs[node.params["blob"]]
        image = skia.Image.MakeFromEncoded(blob.data)
        if image is None:
            raise DeviceError(f"位图解码失败（mime={blob.mime}，{len(blob.data)} 字节）")
        x0, y0, x1, y1 = (float(value) for value in node.bufs["rect"][0])
        interpolate = bool(node.params["interpolate"])
        if self.format == "svg" and not interpolate:
            # SVG 只是把位图交出去，光栅化是后一步的事（resvg / 浏览器）：浏览器与
            # resvg 默认对缩放后的图做平滑插值，2×2 的像素格会糊成一团。参考产线
            # （svglite）把位图先按设备像素铺好再嵌进 SVG，这里照做——最近邻放大到
            # 目标尺寸，`<image>` 与目标矩形 1:1，后续光栅化不再重采样。
            image = self._prescale_nearest(image, max(1, round(x1 - x0)), max(1, round(y1 - y0)))
        sampling = (
            skia.SamplingOptions(skia.FilterMode.kLinear)
            if interpolate
            else skia.SamplingOptions(skia.FilterMode.kNearest)
        )
        self.canvas.drawImageRect(
            image, skia.Rect.MakeLTRB(x0, y0, x1, y1), sampling, skia.Paint(AntiAlias=True)
        )

    @staticmethod
    def _prescale_nearest(image: skia.Image, width: int, height: int) -> skia.Image:
        """最近邻放大到位图的最终像素尺寸（`interpolate = FALSE` 的 SVG 路径）。"""
        if image.width() == width and image.height() == height:
            return image
        # skia-python 的 `toarray()` 是 BGRA，`ggcore.png` 写的是 RGBA。
        pixels = np.asarray(image.toarray(), dtype=np.uint8)[:, :, [2, 1, 0, 3]]
        ys = np.repeat(np.arange(pixels.shape[0]), -(-height // pixels.shape[0]))[:height]
        xs = np.repeat(np.arange(pixels.shape[1]), -(-width // pixels.shape[1]))[:width]
        scaled = pixels[ys][:, xs]
        encoded = encode_rgba(width, height, np.ascontiguousarray(scaled))
        scaled_image = skia.Image.MakeFromEncoded(encoded)
        if scaled_image is None:  # pragma: no cover - 自己写的 PNG 一定能解码
            raise DeviceError("位图放大后编码失败")
        return scaled_image

    def _draw_xspline(self, node: Any) -> None:
        points = node.bufs["points"]
        ids = node.bufs.get("id")
        shape = float(node.params["shape"])
        is_open = bool(node.params["open"])
        for group in self._groups(points, ids):
            if len(group) < (2 if is_open else 3):
                continue
            sampled = xspline_points(
                [(float(x), float(y)) for x, y in group],
                shape,
                open=is_open,
                page=self.size_pt,
            )
            path = self._polyline_path_from(sampled, closed=not is_open)
            self._stroke_and_fill(node, path, fill=not is_open)

    def _draw_bezier(self, node: Any) -> None:
        control = node.bufs["control"]
        path = skia.Path()
        if len(control) == 0:
            return
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
        self._stroke_and_fill(node, path)

    def _draw_curve(self, node: Any) -> None:
        ends = node.bufs["ends"]
        is_open = bool(node.params["open"])
        height = self.height_pt
        path = skia.Path()
        for x1, y1, x2, y2 in ends:
            # `curve_points` 是 R 坐标（y 向上）的移植，`angle` 也按那个坐标系定义
            # （`grid::curveGrob` 的拐角选哪一侧靠它）。IR 的 y 向下，所以先翻成
            # R 坐标求值，再把折线翻回页面坐标；直接喂页面坐标会把整条曲线沿
            # 弦线镜像（`docs/notes/device.md` §6）。
            sampled = curve_points(
                float(x1),
                height - float(y1),
                float(x2),
                height - float(y2),
                curvature=float(node.params["curvature"]),
                angle=float(node.params["angle"]),
                ncp=int(node.params["ncp"]),
                shape=float(node.params["shape"]),
                square=bool(node.params["square"]),
                inflect=bool(node.params["inflect"]),
                open=is_open,
                page=self.size_pt,
            )
            sampled = np.column_stack((sampled[:, 0], height - sampled[:, 1]))
            path.addPath(self._polyline_path_from(sampled, closed=not is_open))
            if not is_open and len(sampled) >= 2:
                self._draw_arrow_heads(
                    node,
                    (float(sampled[0, 0]), float(sampled[0, 1])),
                    (float(sampled[-1, 0]), float(sampled[-1, 1])),
                )
        self._stroke_and_fill(node, path, fill=not is_open)


class SkiaRasterDevice(_SkiaDevice):
    """PNG 后端：点阵画布，`dpi` 决定像素密度。"""

    format = "png"

    def __init__(
        self,
        width_pt: float,
        height_pt: float,
        dpi: float = 72.0,
        *,
        shaper: TextShaper | None = None,
    ) -> None:
        super().__init__(width_pt, height_pt, dpi=dpi, shaper=shaper)
        self.surface: skia.Surface | None = None

    def _begin(self) -> None:
        width_px, height_px = self.size_px
        surface = skia.Surface.MakeRasterN32Premul(max(width_px, 1), max(height_px, 1))
        if surface is None:  # pragma: no cover - 内存不足才会发生
            raise DeviceError(f"无法创建 {width_px}×{height_px} 的栅格画布")
        self.surface = surface
        self.canvas = surface.getCanvas()
        self.canvas.clear(skia.ColorWHITE)
        self.canvas.scale(self.dpi / 72.0, self.dpi / 72.0)  # 页面 pt → 像素

    def _emit_glyphs(
        self,
        font: skia.Font,
        gids: Sequence[int],
        positions: Sequence[skia.Point],
        paint: skia.Paint,
    ) -> None:
        assert self.canvas is not None
        builder = skia.TextBlobBuilder()
        builder.allocRunPos(font, list(gids), list(positions))
        self.canvas.drawTextBlob(builder.make(), 0, 0, paint)

    def _finish(self) -> bytes:
        assert self.surface is not None
        image = self.surface.makeImageSnapshot()
        data = image.encodeToData(skia.kPNG, 100)
        if data is None:  # pragma: no cover - 编码失败才会发生
            raise DeviceError("PNG 编码失败")
        return bytes(data.bytes())


#: skia 的 SVG 序列化器给 `<clipPath>`（以及以后的渐变 / 图案）发的 id 是
#: **进程级递增**的：同一进程里第二次画布会从 `cl_3` 接着往下数，所以同一张图
#: 两次渲染的字节不同。id 只是文档内部的引用名，按出现顺序重编号即可让产物重新
#: 变成输入的纯函数（M1-12 的「两次 ggsave 逐字节相等」靠它）。
_SVG_ID = re.compile(r'id="([a-z]+)_([0-9a-f]+)"')
_SVG_URL = re.compile(r"url\(#([a-z]+_[0-9a-f]+)\)")
_SVG_HREF = re.compile(r'(xlink:href|href)="#([a-z]+_[0-9a-f]+)"')


def _stable_svg_ids(svg: bytes) -> bytes:
    """把 skia 的进程级 id 按出现顺序重编号（`cl_3` → `cl_0`，引用一并改）。"""
    text = svg.decode("utf-8")
    renamed: dict[str, str] = {}
    counters: dict[str, int] = {}

    def rename(match: re.Match[str]) -> str:
        prefix, old = match.group(1), match.group(2)
        key = f"{prefix}_{old}"
        new = renamed.get(key)
        if new is None:
            index = counters.get(prefix, 0)
            counters[prefix] = index + 1
            new = f"{prefix}_{index:x}"
            renamed[key] = new
        return f'id="{new}"'

    text = _SVG_ID.sub(rename, text)
    if not renamed:  # pragma: no cover - 空文档 / 没有 id 的画布
        return svg
    text = _SVG_URL.sub(lambda m: f"url(#{renamed.get(m.group(1), m.group(1))})", text)
    text = _SVG_HREF.sub(lambda m: f'{m.group(1)}="#{renamed.get(m.group(2), m.group(2))}"', text)
    return text.encode("utf-8")


class SkiaSvgDevice(_SkiaDevice):
    """SVG 后端：字形全部走轮廓，产物里没有 `<text>` / `@font-face`。"""

    format = "svg"
    emoji_mode = "outline"

    def _begin(self) -> None:
        self._stream = skia.DynamicMemoryWStream()
        bounds = skia.Rect.MakeWH(float(self.width_pt), float(self.height_pt))
        self.canvas = skia.SVGCanvas.Make(bounds, self._stream, skia.SVGCanvas.kNoPrettyXML_Flag)
        self.canvas.clear(skia.ColorWHITE)

    def _emit_glyphs(
        self,
        font: skia.Font,
        gids: Sequence[int],
        positions: Sequence[skia.Point],
        paint: skia.Paint,
    ) -> None:
        assert self.canvas is not None
        for gid, point in zip(gids, positions, strict=True):
            glyph = font.getPath(int(gid))
            if glyph is None:  # pragma: no cover - 空字形（位图 emoji）才会发生
                continue
            self.canvas.save()
            self.canvas.translate(point.x(), point.y())
            self.canvas.drawPath(glyph, paint)
            self.canvas.restore()

    def _finish(self) -> bytes:
        # SVGCanvas 在画布析构时才把缓冲写进 stream（见 skia.SVGCanvas.Make 的文档）。
        self.canvas = None
        data = self._stream.detachAsData()
        self._stream = None
        return _stable_svg_ids(bytes(data.bytes()))

    def _abort(self) -> None:
        # 画布析构时会把半成品写进 stream；这里先放开画布再放手 stream。
        self.canvas = None
        self._stream = None


class SkiaPdfDevice(_SkiaDevice):
    """PDF 后端：文字走轮廓，产物没有 `/Font`（CJK 不依赖阅读端字体）。"""

    format = "pdf"
    emoji_mode = "outline"

    def _begin(self) -> None:
        self._stream = skia.DynamicMemoryWStream()
        self._document = skia.PDF.MakeDocument(self._stream)
        if self._document is None:  # pragma: no cover - 极少见
            raise DeviceError("无法创建 PDF 文档")
        self.canvas = self._document.beginPage(float(self.width_pt), float(self.height_pt))
        self.canvas.clear(skia.ColorWHITE)

    _emit_glyphs = SkiaSvgDevice._emit_glyphs

    def _finish(self) -> bytes:
        document = self._document
        try:
            document.close()
            return bytes(self._stream.detachAsData().bytes())
        finally:
            # 顺序要紧：文档必须在 stream 之前释放（skia 的 PDF 文档析构会碰 stream，
            # 反了就段错误）。
            self.canvas = None
            self._document = None
            self._stream = None

    def _abort(self) -> None:
        """异常路径：先把文档关掉，再按「文档 → stream」的顺序释放。"""
        document = getattr(self, "_document", None)
        try:
            if document is not None:
                document.close()
        finally:
            self.canvas = None
            self._document = None
            self._stream = None
