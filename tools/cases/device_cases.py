#!/usr/bin/env python
"""M0-8 的三路冒烟图：一张手搓图 → PNG / SVG / PDF。

    pixi run cases:device          # 写 docs/cases/device-smoke/current/{png,svg,pdf}
    pixi run cases:device --check  # 只验验收条目，不写文件

图是 issue 验收第 4 条点名的组合：矩形 + 折线 + 中文标签 + 旋转视口里的文字。
三条验收（第 1–3 条）在这里逐条判：

1. PDF 非空、> 1 KB、产物里没有 `/Font`；
2. SVG 能被 XML 解析器解析、含 `<path`；
3. 中文在两路矢量产物里都是轮廓（没有 `<text>`、`font-family`，也没有原串）。

场景构造与 `tests/test_device.py` 共用这一份（测试直接 import 本文件），所以
“PR 里那张 PNG”和 CI 判的东西是同一张图。
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from ggcore.grobs import lines_grob, rect_grob, scene, text_grob  # noqa: E402
from ggcore.ir import Scene  # noqa: E402
from ggcore.viewport import Device, ViewportTree, gpar, viewport  # noqa: E402
from ggskia import SkiaPdfDevice, SkiaRasterDevice, SkiaSvgDevice  # noqa: E402
from ggskia.text import TextShaper  # noqa: E402

OUT = REPO / "docs" / "cases" / "device-smoke" / "current"
DPI = 150.0


class ShaperMetrics:
    """`ggcore.units.Metrics` 的适配器：宽度就问设备自己的排版（英寸）。"""

    def __init__(self) -> None:
        self.shaper = TextShaper()

    def strwidth(self, text: str, *, fontsize: float, cex: float) -> float:
        runs = self.shaper.runs("sans", text, fontsize * cex)
        return sum(run.advance for run in runs) / 72.0

    def strheight(self, text: str, *, fontsize: float, cex: float) -> float:
        metrics = self.shaper.font("NotoSansCJKsc-VF.ttf", fontsize * cex).getMetrics()
        return float(-metrics.fAscent + metrics.fDescent) / 72.0


def build_scene(cjk_label: str = "中文标签 · M0-8") -> Scene:
    """6×4 in 的手搓图：矩形 + 折线 + 中文标签 + 旋转视口里的文字。"""
    tree = ViewportTree(Device(6, 4), metrics=ShaperMetrics())
    root = viewport("page", x=0.5, y=0.5, width=1.0, height=1.0, clip="off", gp=gpar(fontsize=12))
    rotated = viewport("rot", x=0.62, y=0.28, width=0.34, height=0.16, angle=30, clip="off")
    tree.push(root)
    box = rect_grob(
        x=0.3, y=0.68, width=0.36, height=0.24, gp=gpar(fill="#4C78A8", col="#1b1b1b", lwd=1.5)
    )
    line = lines_grob(
        x=[0.12, 0.35, 0.55, 0.88], y=[0.2, 0.42, 0.18, 0.4], gp=gpar(col="#E45756", lwd=2)
    )
    label = text_grob(cjk_label, x=0.3, y=0.5, gp=gpar(col="#222222", fontsize=14))
    tilted = text_grob("rot 30°", x=0.5, y=0.5, gp=gpar(col="#54A24B", fontsize=12), vp=rotated)
    return scene([box, line, label, tilted], tree).to_ir_scene()


def render_all(ir_scene: Scene) -> dict[str, bytes]:
    return {
        "png": SkiaRasterDevice(*ir_scene.size, dpi=DPI).render(ir_scene),
        "svg": SkiaSvgDevice(*ir_scene.size).render(ir_scene),
        "pdf": SkiaPdfDevice(*ir_scene.size).render(ir_scene),
    }


def check(ir_scene: Scene, outputs: dict[str, bytes]) -> list[str]:
    """验收 1–3：返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    pdf, svg, png = outputs["pdf"], outputs["svg"], outputs["png"]
    if len(pdf) <= 1024:
        problems.append(f"PDF 只有 {len(pdf)} 字节（要求 > 1 KB）")
    if b"/Font" in pdf:
        problems.append("PDF 里出现了 /Font（文字必须是轮廓）")
    try:
        ET.fromstring(svg)
    except ET.ParseError as error:
        problems.append(f"SVG 不是合法 XML：{error}")
    if b"<path" not in svg:
        problems.append("SVG 里没有 <path")
    for name, payload in (("SVG", svg), ("PDF", pdf)):
        if b"<text" in payload or b"font-family" in payload:
            problems.append(f"{name} 里有文字对象（<text> / font-family）")
        if "中文标签".encode() in payload:
            problems.append(f"{name} 里出现了原文（说明没转成轮廓）")
    if not png.startswith(b"\x89PNG") or len(png) < 1024:
        problems.append("PNG 不是有效的非空位图")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the M0-8 three-format smoke figure.")
    parser.add_argument("--check", action="store_true", help="only verify, do not write files")
    parser.add_argument("--out", type=Path, default=OUT, help=f"output directory (default: {OUT})")
    args = parser.parse_args(argv)

    ir_scene = build_scene()
    outputs = render_all(ir_scene)
    problems = check(ir_scene, outputs)
    if problems:
        for problem in problems:
            print(f"cases:device: {problem}", file=sys.stderr)
        return 1
    if args.check:
        print(f"cases:device: ok ({', '.join(f'{k} {len(v)} B' for k, v in outputs.items())})")
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    for suffix, payload in outputs.items():
        target = args.out / f"device-smoke.{suffix}"
        target.write_bytes(payload)
        print(f"wrote {target.relative_to(REPO)} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
