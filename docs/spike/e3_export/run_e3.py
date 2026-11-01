"""E3 gate: can all three export paths be delivered with the chosen stack?

Question: CanvasKit has no PDF writer and no SVG writer. Is that a blocker?

Method:
  1. Enumerate the real canvaskit-wasm API and try PNG / SVG / PDF from one
     drawing (node probe).
  2. Do the same drawing on the desktop/service side with skia-python: PDF via
     skia.PDF.MakeDocument, SVG via skia.SVGCanvas.Make. Text is drawn as
     HarfBuzz outlines (docs/spike/common/hb_path.py) so the output carries
     geometry, not a font dependency.

Run: pixi run spike:e3
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import skia

SPIKE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SPIKE))

from common.hb_path import draw_text_units, shape, text_path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
RESULTS = HERE / "results"
ARTIFACTS = RESULTS / "artifacts"
FONTS = Path(os.environ.get("CONDA_PREFIX", "")) / "fonts"

W, H = 320, 180
LABEL = "月份 增长 42%"  # what a real chart axis/title holds


def draw(canvas: skia.Canvas, run) -> None:
    canvas.clear(skia.ColorWHITE)
    fill = skia.Paint(Color=skia.Color(0x2C, 0x7B, 0xB6), AntiAlias=True)
    stroke = skia.Paint(
        Color=skia.Color(0x22, 0x22, 0x22), AntiAlias=True, Style=skia.Paint.kStroke_Style
    )
    canvas.drawRect(skia.Rect.MakeXYWH(24, 40, 120, 80), fill)
    canvas.drawLine(24, 150, 296, 150, stroke)
    draw_text_units(canvas, run, 24, 130, 16.0, skia.Paint(Color=skia.ColorBLACK, AntiAlias=True))


def canvas_probe() -> dict:
    out_json = RESULTS / "e3_canvaskit_probe.json"
    subprocess.run(
        ["node", str(HERE / "probe_canvaskit.cjs"), str(out_json)],
        check=True,
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    return json.loads(out_json.read_text(encoding="utf-8"))


def pdf_probe(run) -> dict:
    stream = skia.DynamicMemoryWStream()
    doc = skia.PDF.MakeDocument(stream)
    page = doc.beginPage(W, H)
    draw(page, run)
    doc.endPage()
    doc.close()
    blob = stream.detachAsData().bytes()
    path = ARTIFACTS / "sample.pdf"
    path.write_bytes(blob)
    # Content streams are Flate-compressed; decompress to prove the label ended
    # up as painted geometry rather than an embedded font reference.
    ops = b""
    for chunk in re.findall(rb"stream\r?\n(.*?)endstream", blob, re.S):
        try:
            ops += zlib.decompress(chunk)
        except zlib.error:
            ops += chunk
    return {
        "file": str(path.relative_to(HERE)),
        "bytes": len(blob),
        "header_ok": blob.startswith(b"%PDF-"),
        "pages": len(re.findall(rb"/Type\s*/Page[^s]", blob)),
        "needs_font_resource": b"/Font" in blob,
        "path_ops": sum(
            ops.count(op) for op in (b" m\n", b" l\n", b" c\n", b" m ", b" l ", b" c ")
        ),
        "content_stream_bytes": len(ops),
    }


def svg_probe(run) -> dict:
    stream = skia.DynamicMemoryWStream()
    canvas = skia.SVGCanvas.Make(
        skia.Rect.MakeWH(W, H), stream, skia.SVGCanvas.kConvertTextToPaths_Flag
    )
    draw(canvas, run)
    del canvas  # flushes buffered draw calls
    blob = stream.detachAsData().bytes()
    path = ARTIFACTS / "sample.svg"
    path.write_bytes(blob)
    text = blob.decode("utf-8", "replace")
    try:
        root = ET.fromstring(text)
        parsed, root_tag = True, root.tag.rsplit("}", 1)[-1]
    except ET.ParseError:
        parsed, root_tag = False, ""
    return {
        "file": str(path.relative_to(HERE)),
        "bytes": len(blob),
        "parses_as_xml": parsed,
        "root_tag": root_tag,
        "has_viewbox": "viewBox" in text,
        "path_elements": text.count("<path"),
    }


def cjk_outline_probe(run) -> dict:
    path = text_path(run)
    bbox = path.computeTightBounds()
    return {
        "labels": LABEL,
        "glyphs": len(run.glyphs),
        "path_empty": path.isEmpty(),
        "bbox_w": round(bbox.width(), 2),
        "bbox_h": round(bbox.height(), 2),
        "advance_px_at_16": round(sum(run.advances) / run.upem * 16.0, 4),
    }


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)

    ck = canvas_probe()
    run = shape(LABEL, (FONTS / "NotoSansCJKsc-VF.ttf").read_bytes())
    pdf = pdf_probe(run)
    svg = svg_probe(run)
    cjk = cjk_outline_probe(run)

    browser_ok = ck["makes_png"] and not ck["makes_pdf"] and not ck["has_svg_canvas"]
    desktop_ok = (
        pdf["header_ok"]
        and pdf["pages"] == 1
        and svg["parses_as_xml"]
        and svg["root_tag"] == "svg"
        and not cjk["path_empty"]
    )
    passed = browser_ok and desktop_ok

    summary = {
        "experiment": "E3 export gap: CanvasKit cannot write PDF/SVG",
        "passed": passed,
        "browser_side": {
            "canvaskit": ck,
            "verdict": (
                "raster only (PNG); no PDF document, no SVG canvas"
                if browser_ok
                else "unexpected: see probe fields"
            ),
        },
        "desktop_service_side": {
            "skia_python": skia.__version__,
            "pdf": pdf,
            "svg": svg,
            "cjk_outlines": cjk,
            "verdict": (
                "skia-python writes PDF and SVG; text travels as HarfBuzz outlines"
                if desktop_ok
                else "unexpected: see probe fields"
            ),
        },
        "conclusion": {
            "svg": "TS serializer from IR (zero wasm), same IR -> DOM <svg>",
            "pdf": "desktop / service only, skia.PDF.MakeDocument + HarfBuzz outlines",
            "png": "browser via CanvasKit raster surface; desktop via skia-python",
            "font_dependency": "none in output: text is geometry, not a font reference",
        },
    }
    out = RESULTS / "e3_results.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"E3 {'PASS' if passed else 'FAIL'}")
    print(
        f"  canvaskit {ck['version']}: png={ck['makes_png']} pdf={ck['makes_pdf']} "
        f"svg={ck['has_svg_canvas']} vector_exports={ck['vector_or_document_exports']}"
    )
    print(
        f"  skia-python PDF: header={pdf['header_ok']} pages={pdf['pages']} "
        f"bytes={pdf['bytes']} needs_font={pdf['needs_font_resource']}"
    )
    print(
        f"  skia-python SVG: parses={svg['parses_as_xml']} root={svg['root_tag']} "
        f"viewBox={svg['has_viewbox']} paths={svg['path_elements']} bytes={svg['bytes']}"
    )
    print(
        f"  CJK outlines: glyphs={cjk['glyphs']} empty={cjk['path_empty']} "
        f"{cjk['bbox_w']}x{cjk['bbox_h']} units, advance@{16}px={cjk['advance_px_at_16']}"
    )
    print(f"  -> {out.relative_to(REPO)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
