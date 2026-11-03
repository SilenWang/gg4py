#!/usr/bin/env python
"""M2-12：同一份 IR 的两条渲染腿对拍（skia SVG 设备 × 浏览器 DOM SVG）。

    pixi run viewer:parity                 # 全部 ci = true 的 case，写报告入库
    pixi run viewer:parity --sample 12     # CI 子集（不写报告，只判红绿）
    pixi run viewer:parity --case geom-line-width

为什么不是「逐元素比字符串」：两条腿的元素切分口径不同。skia 把文字画成
**每个字形一条 `<path>`**（`docs/notes/device.md`：矢量后端不许有 `<text>`），
查看器写的是 `<text>`（对拍前用 `ggdiff.svgtext.inline_text_paths` 换成轮廓，
一条文本一行）；`rect` 在 skia 里是 `<path>`，在查看器里是真 `<rect>`。所以
元素数天然不同，逐元素比会全是噪声。

这里按**归一化属性**比三层（判据见 `docs/notes/viewer.md` §10.2）：

1. `palette`：两侧所有已绘制元素的**最终涂色**集合（属性 + 继承 + SVG 缺省值
   解析后归一化成 `#rrggbb` × opacity）。集合必须**完全相等**——多一种颜色、
   少一档透明度都是语义差。
   为什么不比线宽 / 虚线：skia 的 SVGCanvas 会把虚线描边**展开成填充多边形**、
   把 `lwd=0` 的描边省掉，两条腿对同一语义本来就用不同的 SVG 表达
   （`docs/notes/device.md`）。线宽与虚线的差异由第 3 层墨迹差兜住。
2. `位置`：两侧 PNG 的墨迹包围盒（四边各 ≤ 1 pt）与亮度加权重心（≤ 1 pt）。
   抓「涂色对、位置或大小错」。
3. `墨迹差`：两侧 PNG 二值墨迹的对称差（1 px 形态学容差）≤ 0.5%，
   另加 `ggdiff` 的全通道均值 ≤ 1%。抓「画丢 / 画多 / 线宽 / 虚线 / 形状错」。

`墨迹差` 这一列就是报告里的「差异」，三条全过才算 pass。
产物：`docs/notes/viewer-parity.md`（入库）+ `.viewer-cases/parity.json`（不入库）。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools" / "viewer"))

import cases as case_runner  # noqa: E402
import playwright_env  # noqa: E402

from ggcore import ir  # noqa: E402
from ggcore.plotspec import build_scene, load_plot  # noqa: E402
from ggdiff.compare import DEFAULT_MAX_MEAN, compare_images  # noqa: E402
from ggdiff.image import load_image  # noqa: E402
from ggdiff.raster import rasterize_svg  # noqa: E402
from ggdiff.svgtext import inline_text_paths  # noqa: E402
from ggskia.skia import SkiaSvgDevice  # noqa: E402
from ggskia.text import ShaperMetrics, TextShaper  # noqa: E402

#: 验收阈值：同一 IR 两条腿的差异必须 < 0.5%。
MAX_PIXEL_DIFF = 0.005
#: 墨迹包围盒的四条边，单位 pt（72 dpi 下 1 px）：抗锯齿边缘允许差一档。
MAX_BBOX_DELTA = 1.0
#: 墨迹重心，单位 pt：位置整体错开时这一项先红（bbox 对边缘像素太钝）。
MAX_CENTROID_DELTA = 1.0
#: 墨迹像素的亮度阈值：任一通道 < 250 即算「有墨」。
INK_THRESHOLD = 250

SVG_NS = "http://www.w3.org/2000/svg"
_PAINTED = {
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "image",
    "text",
}
#: 参与「涂色集合」的属性（只留颜色与透明度，见模块头的理由）。
_STYLE_KEYS = ("fill", "fill-opacity", "stroke", "stroke-opacity", "opacity")
#: SVG 的层叠缺省值（skia 只写与缺省不同的属性，查看器会写全）。
_DEFAULTS = {
    "fill": "#000000",
    "fill-opacity": "1",
    "stroke": "none",
    "stroke-opacity": "1",
    "opacity": "1",
}

_NAMED_COLOURS = {
    "white": "#ffffff",
    "black": "#000000",
    "red": "#ff0000",
    "green": "#008000",
    "blue": "#0000ff",
    "transparent": "none",
}


@dataclass
class ParityCase:
    case: str
    family: str
    status: str = "error"
    pixel: float | None = None
    pixel_exact: float | None = None
    mean: float | None = None
    bbox_delta: float | None = None
    centroid_delta: float | None = None
    styles_skia: int = 0
    styles_viewer: int = 0
    colour_missing: list[str] = field(default_factory=list)
    colour_extra: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def style_ok(self) -> bool:
        return not self.colour_missing and not self.colour_extra

    @property
    def bbox_ok(self) -> bool:
        return (
            self.bbox_delta is not None
            and self.bbox_delta <= MAX_BBOX_DELTA
            and (self.centroid_delta or 0.0) <= MAX_CENTROID_DELTA
        )

    @property
    def pixel_ok(self) -> bool:
        return (
            self.pixel is not None
            and self.pixel <= MAX_PIXEL_DIFF
            and (self.mean or 0.0) <= DEFAULT_MAX_MEAN
        )

    @property
    def ok(self) -> bool:
        return self.status == "pass"

    def as_dict(self) -> dict[str, object]:
        return {
            "case": self.case,
            "family": self.family,
            "status": self.status,
            "pixel_diff_fraction": self.pixel,
            "pixel_diff_fraction_exact": self.pixel_exact,
            "mean_diff": self.mean,
            "bbox_delta_pt": self.bbox_delta,
            "centroid_delta_pt": self.centroid_delta,
            "styles_skia": self.styles_skia,
            "styles_viewer": self.styles_viewer,
            "colour_missing": self.colour_missing,
            "colour_extra": self.colour_extra,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# 归一化属性
# ---------------------------------------------------------------------------


def _norm_colour(value: str) -> str:
    raw = value.strip().lower()
    if raw in _NAMED_COLOURS:
        return _NAMED_COLOURS[raw]
    if raw.startswith("#"):
        digits = raw[1:]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) >= 6:
            return f"#{digits[:6]}"
    return raw


def _norm_number(value: str) -> str:
    try:
        number = float(value)
    except ValueError:
        return value.strip()
    if not math.isfinite(number):
        return value.strip()
    rounded = round(number, 3)
    return "0" if rounded == 0 else f"{rounded:g}"


def _norm_style(name: str, value: str) -> str:
    if name in ("fill", "stroke"):
        return _norm_colour(value)
    if name in ("fill-opacity", "stroke-opacity", "opacity"):
        return _norm_number(value)
    if name == "stroke-dasharray":
        parts = [part for part in value.replace(",", " ").split() if part]
        if not parts or parts[0].lower() == "none":
            return "none"
        return " ".join(_norm_number(part) for part in parts)
    if name in ("stroke-width", "stroke-miterlimit"):
        return _norm_number(value)
    return value.strip().lower()


def _element_style(element: ET.Element, inherited: dict[str, str]) -> dict[str, str]:
    style = dict(inherited)
    for name in _STYLE_KEYS:
        value = element.get(name)
        if value is not None:
            style[name] = _norm_style(name, value)
    raw = element.get("style") or ""
    for item in raw.split(";"):
        if ":" not in item:
            continue
        key, _, value = item.partition(":")
        key = key.strip().lower()
        if key in _STYLE_KEYS:
            style[key] = _norm_style(key, value.strip())
    return style


def normalised_palette(svg_path: Path) -> set[tuple[str, str]]:
    """SVG 里所有已绘制元素的最终涂色 `(颜色, 不透明度)`（集合）。

    不计重数是关键：同一份 IR，skia 把一行文字拆成 43 条字形路径，查看器是一
    条轮廓路径；同一涂色出现几次没有语义。
    """
    root = ET.parse(svg_path).getroot()
    palette: set[tuple[str, str]] = set()

    def walk(element: ET.Element, inherited: dict[str, str]) -> None:
        tag = element.tag.replace(f"{{{SVG_NS}}}", "")
        if tag in ("defs", "clipPath", "linearGradient", "radialGradient", "pattern", "mask"):
            return
        style = _element_style(element, inherited)
        if tag in _PAINTED:
            group = float(style.get("opacity", "1") or 1)
            for role, opacity_key in (("fill", "fill-opacity"), ("stroke", "stroke-opacity")):
                colour = style.get(role, _DEFAULTS[role])
                if colour == "none":
                    continue
                alpha = group * float(style.get(opacity_key, "1") or 1)
                palette.add((colour, f"{round(alpha, 3):g}"))
        for child in element:
            walk(child, style)

    walk(root, dict(_DEFAULTS))
    return palette


# ---------------------------------------------------------------------------
# 墨迹包围盒
# ---------------------------------------------------------------------------


def ink_bbox(png_path: Path) -> tuple[int, int, int, int] | None:
    """墨迹的 `(x0, y0, x1, y1)`（含端点）；整页空白返回 None。

    阈值取近白（任一通道 < 250）：两条腿的抗锯齿档位不完全相同，边界的**弱**
    像素会差一档，所以包围盒允许 1 pt；整体位移由重心（`MAX_CENTROID_DELTA`）
    抓，不靠包围盒。
    """
    import numpy as np

    image = load_image(png_path)
    mask = (image < 250).any(axis=2)
    if not mask.any():
        return None
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]), int(rows[-1])


def _bbox_delta(a: tuple[int, int, int, int] | None, b: tuple[int, int, int, int] | None) -> float:
    if a is None or b is None:
        return 0.0 if a is b else float("inf")
    return float(max(abs(left - right) for left, right in zip(a, b, strict=True)))


def ink_centroid(png_path: Path) -> tuple[float, float] | None:
    """墨迹的「墨量重心」：`sum(1 - luma) * x / sum(1 - luma)`（单位 px）。"""
    import numpy as np

    image = load_image(png_path).astype(np.float64)
    weight = 1.0 - image.mean(axis=2) / 255.0
    total = weight.sum()
    if total <= 0:
        return None
    rows, cols = np.indices(weight.shape)
    return float((weight * cols).sum() / total), float((weight * rows).sum() / total)


def _centroid_delta(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float:
    if a is None or b is None:
        return 0.0 if a is b else float("inf")
    return float(max(abs(left - right) for left, right in zip(a, b, strict=True)))


def ink_difference(reference_png: Path, actual_png: Path, *, radius: int = 1) -> float:
    """墨迹的对称差占比（1 px 形态学容差），即「差异」这一列。

    为什么比墨迹而不是比灰度：两条腿对同一个圆 / 同一段文字用了不同的 SVG
    表达（skia 是 `addCircle` 的二次折线，查看器是 kappa 三次曲线；文字一侧逐
    字形、另一侧整行轮廓），栅格化后**边缘那 1 px** 的抗锯齿强度必然差一档
    （实测差 ~10/255，但形状完全重合）。把「另一侧 1 px 邻域内也有墨」的像素
    判为同形之后，剩下的是真正画丢 / 画多 / 错位 / 线宽或虚线不对的墨迹。
    涂色强度的一致性由 `mean`（全通道平均差 ≤ 1%）兜住，颜色本身由 palette
    集合兜住。
    """
    import numpy as np

    left = (load_image(reference_png) < INK_THRESHOLD).any(axis=2)
    right = (load_image(actual_png) < INK_THRESHOLD).any(axis=2)
    height, width = left.shape

    def covered(mask) -> np.ndarray:
        grown = np.zeros_like(mask)
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                shifted = np.zeros_like(mask)
                shifted[
                    max(0, -dy) : height + min(0, -dy),
                    max(0, -dx) : width + min(0, -dx),
                ] = mask[
                    max(0, dy) : height + min(0, dy),
                    max(0, dx) : width + min(0, dx),
                ]
                grown |= shifted
        return grown

    only_left = left & ~covered(right)
    only_right = right & ~covered(left)
    return float(only_left.sum() + only_right.sum()) / float(left.size)


# ---------------------------------------------------------------------------
# 浏览器
# ---------------------------------------------------------------------------


def _viewer_svg(page, cbor: Path, out: Path) -> Path:
    page.evaluate(
        "() => { const s = document.querySelector('#status');"
        " s.dataset.state = 'pending'; s.textContent = '加载中…'; }"
    )
    page.set_input_files("#file", str(cbor))
    page.wait_for_selector("#status[data-state='ok']", timeout=20_000)
    payload = case_runner._serialize_viewer_svg(page)
    if payload is None:
        raise RuntimeError("viewer 没有产出 svg.gg-svg")
    out.write_text(payload["markup"], encoding="utf-8")
    return out


def _run_case(case, page, *, metrics, shaper, scratch: Path) -> ParityCase:
    result = ParityCase(case=case.name, family=case.family)
    try:
        scene = build_scene(load_plot(case.directory), metrics=metrics)
        cbor = scratch / "scene.ggir.cbor"
        cbor.write_bytes(ir.encode(scene))

        skia_path = scratch / "skia.svg"
        skia_path.write_bytes(SkiaSvgDevice(*scene.size, dpi=72).render(scene))
        viewer_raw = _viewer_svg(page, cbor, scratch / "viewer.svg")

        # 文字轮廓化：两侧都只剩 `<path>`，样式与像素才有可比性。
        viewer_path = scratch / "viewer.outlined.svg"
        skia_outlined = scratch / "skia.outlined.svg"
        inline_text_paths(viewer_raw, viewer_path, shaper=shaper)
        inline_text_paths(skia_path, skia_outlined, shaper=shaper)

        screen = scratch / "png"
        screen.mkdir(exist_ok=True)
        skia_png = rasterize_svg(skia_outlined, screen / "skia.png", dpi=72, background="#ffffff")
        viewer_png = rasterize_svg(viewer_path, screen / "viewer.png", dpi=72, background="#ffffff")

        skia_palette = normalised_palette(skia_outlined)
        viewer_palette = normalised_palette(viewer_path)
        result.styles_skia = len(skia_palette)
        result.styles_viewer = len(viewer_palette)
        result.colour_missing = sorted(
            f"{colour} @ {alpha}" for colour, alpha in skia_palette - viewer_palette
        )[:8]
        result.colour_extra = sorted(
            f"{colour} @ {alpha}" for colour, alpha in viewer_palette - skia_palette
        )[:8]
        result.bbox_delta = _bbox_delta(ink_bbox(skia_png), ink_bbox(viewer_png))
        result.centroid_delta = _centroid_delta(ink_centroid(skia_png), ink_centroid(viewer_png))

        diff, _mask, _amount = compare_images(
            load_image(skia_png),
            load_image(viewer_png),
            max_fraction=MAX_PIXEL_DIFF,
            max_mean=DEFAULT_MAX_MEAN,
        )
        result.pixel_exact = diff.image_diff_fraction
        result.pixel = ink_difference(skia_png, viewer_png)
        result.mean = diff.mean_diff
        result.status = (
            "pass" if (result.pixel_ok and result.bbox_ok and result.style_ok) else "fail"
        )
        reasons = []
        if not result.pixel_ok:
            reasons.append("像素差超 0.5%")
        if not result.bbox_ok:
            reasons.append(
                f"墨迹包围盒差 {result.bbox_delta} pt / 重心差 {result.centroid_delta} pt"
            )
        if not result.style_ok:
            reasons.append("涂色集合不一致")
        result.detail = "；".join(reasons)
    except Exception as error:  # 浏览器 / 解码 / 光栅化失败都算 error
        result.status = "error"
        result.detail = f"{type(error).__name__}: {error}".splitlines()[0][:400]
    return result


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return f"{value:.3%}" if value is not None else "—"


def render_report(results: list[ParityCase], *, now: str, command: str) -> str:
    passed = sum(1 for item in results if item.ok)
    worst = max((item.pixel or 0.0) for item in results) if results else 0.0
    lines = [
        "# 两条渲染腿的语义对拍（skia SVG × 浏览器 DOM SVG）",
        "",
        f"- 时间：{now}",
        f"- 复现：`{command}`",
        f"- 结论：pass {passed} / {len(results)}；最大像素差 {_pct(worst)}"
        f"（阈值 {MAX_PIXEL_DIFF:.1%}，均值 ≤ {DEFAULT_MAX_MEAN:.0%}）",
        "- 同一份 IR 分别走 `SkiaSvgDevice`（字形轮廓、`<path>`，见 `docs/notes/device.md`）"
        "与查看器的 DOM SVG；两侧文字都轮廓化后比三层："
        "颜色集合（完全相等）、墨迹包围盒（≤ 1 pt）与重心（≤ 1 pt）、墨迹差（≤ 0.5%）。",
        "",
        "| case | 族 | 颜色 skia/viewer | 墨迹差 | 包围盒差 | 重心差 | 均值 | 结论 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in results:
        box = "—" if item.bbox_delta is None else f"{item.bbox_delta:.0f} pt"
        centre = "—" if item.centroid_delta is None else f"{item.centroid_delta:.2f} pt"
        glyph = {"pass": "✅", "fail": "❌", "error": "⛔"}.get(item.status, item.status)
        lines.append(
            f"| `{item.case}` | `{item.family}` | {item.styles_skia}/{item.styles_viewer} "
            f"| {_pct(item.pixel)} | {box} | {centre} | {_pct(item.mean)} | {glyph} {item.status} |"
        )
    problem = [item for item in results if not item.ok]
    lines.append("")
    if problem:
        lines.extend(["## 未通过", ""])
        for item in problem:
            lines.append(f"### `{item.case}`")
            lines.append("")
            lines.append(f"- 结论：{item.status}；{item.detail or '—'}")
            if item.colour_missing:
                lines.append(f"- skia 有、viewer 缺：{'; '.join(item.colour_missing)}")
            if item.colour_extra:
                lines.append(f"- viewer 多出：{'; '.join(item.colour_extra)}")
            lines.append("")
    else:
        lines.extend(["全部通过。", ""])
    lines.extend(
        [
            "## 口径",
            "",
            "- **颜色集合**：两侧所有已绘制元素的最终涂色（属性 + 继承 + SVG 缺省值），"
            "归一成 `#rrggbb` × opacity；按集合比、不计元素个数——skia 每个字形一条路径，"
            "查看器一条文本一行。线宽 / 虚线不进这一层（skia 会把虚线展开成填充多边形，"
            "见 `docs/notes/device.md`），由像素差兜住。",
            "- **墨迹包围盒 / 重心**：PNG 上非白像素的四条边逐边 ≤ 1 pt（抗锯齿边缘的一档），"
            "按亮度加权的墨量重心 ≤ 0.5 pt（整体位移）。",
            "- **墨迹差**：两侧 PNG 的二值墨迹（任一通道 < 250）的对称差占比，"
            "带 1 px 形态学容差——同一形状的两种 SVG 表达只差边缘抗锯齿那一档。"
            "**均值**沿用 `ggdiff` 的全通道平均差（≤ 1%），保证墨迹内部的颜色强度一致。",
            "",
        ]
    )
    return "\n".join(lines)


def _mutated_shift(source: Path, target: Path, *, pt: float) -> None:
    """把整张图平移 `pt`，用来验证「墨迹差」真的看得见位移。"""
    root = ET.parse(source).getroot()
    wrapper = ET.Element(f"{{{SVG_NS}}}g", {"transform": f"translate({pt} 0)"})
    for child in list(root):
        root.remove(child)
        wrapper.append(child)
    root.append(wrapper)
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)


def _mutated_colour(source: Path, target: Path, *, colour: str) -> None:
    """把第一个具名颜色换掉，用来验证「颜色集合」真的看得见错色。"""
    payload = source.read_text(encoding="utf-8")
    for name in ("fill=", "stroke="):
        index = payload.find(f'{name}"#')
        if index >= 0:
            start = index + len(name) + 1
            end = payload.index('"', start)
            payload = payload[:start] + colour + payload[end:]
            break
    target.write_text(payload, encoding="utf-8")


def selftest(scratch_root: Path, *, radius: int = 1) -> list[tuple[str, bool, str]]:
    """负向对照：故意改坏一份 viewer SVG，三个判据必须各自变红。

    只看「全绿」不知道判据有没有在看东西（`gate:pyodide:selftest` 同一个思路）。
    """
    cases = sorted(path for path in scratch_root.glob("*/viewer.outlined.svg"))
    if not cases:
        return [("selftest", False, "没有可用的 viewer SVG（先跑一轮对拍）")]
    source = cases[0]
    work = scratch_root / "_selftest"
    work.mkdir(parents=True, exist_ok=True)
    reference = source.with_name("skia.outlined.svg")
    checks: list[tuple[str, bool, str]] = []

    shifted = work / "shifted.svg"
    _mutated_shift(source, shifted, pt=2.0)
    shifted_png = rasterize_svg(shifted, work / "shifted.png", dpi=72, background="#ffffff")
    reference_png = rasterize_svg(reference, work / "reference.png", dpi=72, background="#ffffff")
    moved_ink = ink_difference(reference_png, shifted_png, radius=radius)
    moved_centre = _centroid_delta(ink_centroid(reference_png), ink_centroid(shifted_png))
    # 判据是三条一起看：平移不一定改变「有墨 / 没墨」的占比（细线挪 2 px 仍有
    # 大半落在 1 px 容差里），但重心一定会跳。
    detected_shift = moved_ink > MAX_PIXEL_DIFF or moved_centre > MAX_CENTROID_DELTA
    checks.append(
        (
            "平移 2 pt 必须被判失败",
            detected_shift,
            f"墨迹差 {moved_ink:.3%} / 重心差 {moved_centre:.2f} pt",
        )
    )

    recoloured = work / "recoloured.svg"
    _mutated_colour(source, recoloured, colour="#ff00ff")
    palette_a = normalised_palette(reference)
    palette_b = normalised_palette(recoloured)
    checks.append(
        (
            "换一种颜色必须被颜色集合抓到",
            bool(palette_a ^ palette_b),
            f"差集 {sorted(palette_a ^ palette_b)[:2]}",
        )
    )
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="viewer:parity",
        description="同一份 IR：skia SVG 设备 vs 浏览器查看器 DOM SVG 的语义对拍。",
    )
    parser.add_argument("--case", action="append", dest="cases", help="只跑这个 case（可重复）")
    parser.add_argument("--sample", type=int, default=None, help="按族轮转取前 N 条（CI 用）")
    parser.add_argument(
        "--report",
        type=Path,
        default=REPO / "docs" / "notes" / "viewer-parity.md",
        help="Markdown 报告路径（`--no-report` 时不写）",
    )
    parser.add_argument("--no-report", action="store_true", help="只判红绿，不写报告")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="跑完之后做负向对照：平移 2 pt / 换一种颜色，判据必须变红",
    )
    parser.add_argument("--out", type=Path, default=REPO / ".viewer-cases", help="JSON 与中间产物")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (REPO / "web" / "viewer" / "dist" / "main.js").is_file():
        print("viewer:parity: 先跑 `pixi run viewer:build`", file=sys.stderr)
        return 2

    matrix = case_runner._load_matrix_module()
    discovered = matrix.discover(case_runner.CASES)
    wanted = set(args.cases or ())
    if wanted:
        discovered = [case for case in discovered if case.name in wanted]
        for name in sorted(wanted - {case.name for case in discovered}):
            print(f"viewer:parity: no case named {name!r}", file=sys.stderr)
    runnable = [case for case in discovered if case.valid and case.ci]
    if args.sample is not None:
        runnable = case_runner._select_sample(runnable, max(args.sample, 0))
    runnable.sort(key=lambda case: case.name)

    metrics = ShaperMetrics()
    shaper = TextShaper(emoji="outline")
    playwright_env.configure()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - dev 环境才有
        print("viewer:parity: 需要 playwright（pixi 的 dev 环境）", file=sys.stderr)
        return 2

    results: list[ParityCase] = []
    args.out.mkdir(parents=True, exist_ok=True)
    scratch_root = args.out / "parity"
    with (
        case_runner.ViewerServer() as url,
        sync_playwright() as playwright,
    ):
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - 只在没装浏览器时命中
            print(
                f"viewer:parity: 没有可用 Chromium（先跑 `pixi run viewer:browsers`）：{error}",
                file=sys.stderr,
            )
            return 2
        page = browser.new_page(viewport={"width": 1000, "height": 800}, device_scale_factor=1)
        page.goto(f"{url}/index.html")
        page.wait_for_selector("#file")
        try:
            for case in runnable:
                scratch = scratch_root / case.name
                scratch.mkdir(parents=True, exist_ok=True)
                result = _run_case(case, page, metrics=metrics, shaper=shaper, scratch=scratch)
                results.append(result)
                glyph = {"pass": "✅", "fail": "❌", "error": "⛔"}.get(
                    result.status, result.status
                )
                print(
                    f"{glyph} {result.case}: pixel {_pct(result.pixel)} / mean {_pct(result.mean)}"
                    f" / bbox {result.bbox_delta} pt"
                    f" / colours {result.styles_skia}:{result.styles_viewer}"
                    + (f" — {result.detail}" if result.detail else ""),
                    flush=True,
                )
        finally:
            browser.close()

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "generated_at": now,
        "thresholds": {
            "pixel": MAX_PIXEL_DIFF,
            "mean": DEFAULT_MAX_MEAN,
            "bbox_pt": MAX_BBOX_DELTA,
        },
        "counts": {
            status: sum(1 for item in results if item.status == status)
            for status in ("pass", "fail", "error")
        },
        "cases": [item.as_dict() for item in results],
    }
    (args.out / "parity.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not args.no_report:
        command = "pixi run viewer:parity" + (f" --sample {args.sample}" if args.sample else "")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(results, now=now, command=command), encoding="utf-8")
        print(f"viewer:parity: report {args.report}")

    failed = [item for item in results if not item.ok]
    if args.selftest:
        for name, detected, detail in selftest(scratch_root):
            glyph = "✅" if detected else "❌"
            print(f"{glyph} selftest: {name}（{detail}）")
            if not detected:
                failed.append(ParityCase(case=f"selftest:{name}", family="selftest", status="fail"))
    print(
        f"viewer:parity: {len(results)} case(s) — pass {len(results) - len(failed)}, "
        f"fail/error {len(failed)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
