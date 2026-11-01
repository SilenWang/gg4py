"""Turn shaped text into a skia.Path using HarfBuzz outlines (no skia text APIs).

Two reasons this is the path we want in the real device layer:

  * CJK/emoji must become geometry for PDF so the output never depends on the
    viewer having the font installed (M0-8 "CJK 转 path").
  * skia-python's SkFont text helpers depend on a host fontconfig; deriving
    outlines from the same HarfBuzz faces the metrics layer uses keeps desktop
    and browser rendering derived from one shaping engine.
"""

from __future__ import annotations

from dataclasses import dataclass

import skia
import uharfbuzz as hb


class SkiaPen:
    """fontTools-style pen that writes into a skia.Path."""

    def __init__(self, path: skia.Path | None = None) -> None:
        self.path = path if path is not None else skia.Path()

    def moveTo(self, pt) -> None:  # noqa: N802 - HarfBuzz pen protocol
        self.path.moveTo(pt[0], pt[1])

    def lineTo(self, pt) -> None:  # noqa: N802
        self.path.lineTo(pt[0], pt[1])

    def curveTo(self, *pts) -> None:  # noqa: N802
        if len(pts) == 3:
            self.path.cubicTo(*pts[0], *pts[1], *pts[2])
        else:
            raise NotImplementedError(f"cubic with {len(pts)} points")

    def qCurveTo(self, *pts) -> None:  # noqa: N802
        if pts and pts[-1] is None:
            raise NotImplementedError("TrueType contour starting off-curve")
        if len(pts) == 2:
            self.path.quadTo(*pts[0], *pts[1])
        elif len(pts) == 1:
            self.path.lineTo(*pts[0])
        else:
            raise NotImplementedError(f"quadratic with {len(pts)} points")

    def closePath(self) -> None:  # noqa: N802
        self.path.close()


@dataclass
class ShapedRun:
    font: hb.Font
    glyphs: list[int]
    advances: list[float]
    upem: int


def shape(text: str, face_data: bytes) -> ShapedRun:
    face = hb.Face(face_data)
    font = hb.Font(face)
    upem = face.upem
    font.scale = (upem, upem)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf)
    return ShapedRun(
        font=font,
        glyphs=[info.codepoint for info in buf.glyph_infos],
        advances=[pos.x_advance for pos in buf.glyph_positions],
        upem=upem,
    )


def text_path(run: ShapedRun) -> skia.Path:
    """Glyph outlines in font units, laid out along the baseline."""
    out = skia.Path()
    x = 0.0
    for gid, advance in zip(run.glyphs, run.advances):
        glyph_pen = SkiaPen()
        run.font.draw_glyph_with_pen(gid, glyph_pen)
        matrix = skia.Matrix()
        matrix.setTranslate(x, 0.0)
        out.addPath(glyph_pen.path, matrix)
        x += advance
    return out


def draw_text_units(canvas: skia.Canvas, run: ShapedRun, x: float, y: float, size: float, paint) -> None:
    """Draw font-unit outlines at (x, y) baseline with the given font size."""
    canvas.save()
    canvas.translate(x, y)
    canvas.scale(size / run.upem, -size / run.upem)
    canvas.drawPath(text_path(run), paint)
    canvas.restore()
