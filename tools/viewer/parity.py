#!/usr/bin/env python
"""M2-12：同一份 IR 的两条渲染腿对拍（skia SVG 设备 × 浏览器 DOM SVG）。

    pixi run viewer:parity:report          # 全部 ci = true 的 case，写报告入库（唯一生成入口）
    pixi run viewer:parity --sample 12     # CI 子集（不写报告，只判红绿）
    pixi run viewer:parity --case geom-line-width
    pixi run viewer:parity:report:check    # 报告与 docs/cases 清单同源（静态，几毫秒）
    pixi run viewer:parity:report:check:measure  # 再真跑全量逐条比 status（≈1.5 min）

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
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
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
from ggdiff.svgimage import snap_pixelated_images  # noqa: E402
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
#: 入库报告的默认路径（生成物，由 `viewer:parity` 全量重写）。
DEFAULT_REPORT = REPO / "docs" / "notes" / "viewer-parity.md"
#: 机读摘要的签名：结构一变就换版本，免得 check 用旧解析器读新格式。
SUMMARY_SIGNATURE = "viewer-parity/2"
#: 机读摘要块的小标题：check 从这里往下找第一个 ```json 围栏。
SUMMARY_HEADING = "## 机读摘要"

SVG_NS = "http://www.w3.org/2000/svg"
_PAINTED = {
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
}
#: 参与「涂色集合」的元素里**没有** `<image>`：SVG 的 `fill` / `stroke` 对位图
#: 没有意义，而两条腿对它的继承还不一样（skia 把位图放进 `<defs>` 再由 `<use>`
#: 画，查看器直接内联），把缺省黑色算进来会让「整页只有一张位图」的 case 凭空多
#: 一种颜色（SIL-867：`geom-raster` 涂色集合 1:2，位图本身像素差 0.000%）。
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


_URL_REF = re.compile(r"^url\(#(.+)\)$")


def _local(tag: str) -> str:
    return tag.replace(f"{{{SVG_NS}}}", "")


def _painted_colours(element: ET.Element, inherited: dict[str, str]) -> set[tuple[str, str]]:
    """一个元素（及其子树）按 SVG 缺省值解析后的涂色集合。"""
    found: set[tuple[str, str]] = set()
    style = _element_style(element, inherited)
    if _local(element.tag) in _PAINTED:
        group = float(style.get("opacity", "1") or 1)
        for role, opacity_key in (("fill", "fill-opacity"), ("stroke", "stroke-opacity")):
            colour = style.get(role, _DEFAULTS[role])
            if colour == "none":
                continue
            alpha = group * float(style.get(opacity_key, "1") or 1)
            found.add((colour, f"{round(alpha, 3):g}"))
    for child in element:
        found |= _painted_colours(child, style)
    return found


def _paint_definitions(
    root: ET.Element,
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, set[tuple[str, str]]]]:
    """`<defs>` 里的渐变 / 图案索引：`url(#id)` 引用要能翻译成具体颜色。

    两条腿对同一份 IR 生成的 `<linearGradient id>` 名字不同（skia 是
    `gradient_0`，查看器是 `ggv-fill-0`），所以**不能**拿 `url(#…)` 字符串当涂色
    比；要按引用解到 stop 颜色 / 图案内容颜色上（SIL-751）。
    """
    gradients: dict[str, list[tuple[str, str]]] = {}
    patterns: dict[str, set[tuple[str, str]]] = {}
    for element in root.iter():
        tag = _local(element.tag)
        if tag in ("linearGradient", "radialGradient"):
            stops: list[tuple[str, str]] = []
            for stop in element:
                if _local(stop.tag) != "stop":
                    continue
                colour = _norm_colour(stop.get("stop-color", "#000000"))
                opacity = _norm_number(stop.get("stop-opacity", "1"))
                stops.append((colour, opacity))
            gradients[element.get("id", "")] = stops
        elif tag == "pattern":
            patterns[element.get("id", "")] = _painted_colours(element, dict(_DEFAULTS))
    return gradients, patterns


def normalised_palette(svg_path: Path) -> set[tuple[str, str]]:
    """SVG 里所有已绘制元素的最终涂色 `(颜色, 不透明度)`（集合）。

    不计重数是关键：同一份 IR，skia 把一行文字拆成 43 条字形路径，查看器是一
    条轮廓路径；同一涂色出现几次没有语义。

    `fill: url(#…)` 按**定义**展开：渐变取每档 stop 的（颜色 × stop-opacity ×
    元素 fill-opacity），图案取内容元素的涂色 × 元素 fill-opacity。这样两条腿
    的 id 不一样也不影响比较，真正比的是「画到画布上的颜色与透明度」。
    """
    root = ET.parse(svg_path).getroot()
    gradients, patterns = _paint_definitions(root)
    palette: set[tuple[str, str]] = set()

    def add_paint(colour: str, alpha: float) -> None:
        reference = _URL_REF.match(colour)
        if reference is None:
            palette.add((colour, f"{round(alpha, 3):g}"))
            return
        key = reference.group(1)
        if key in gradients:
            for stop_colour, stop_opacity in gradients[key]:
                palette.add((stop_colour, f"{round(alpha * float(stop_opacity), 3):g}"))
            return
        if key in patterns:
            for inner_colour, inner_alpha in patterns[key]:
                palette.add((inner_colour, f"{round(alpha * float(inner_alpha), 3):g}"))
            return
        # 引用不到定义（例如 mask）：保留原样，让集合差自己报出来。
        palette.add((colour, f"{round(alpha, 3):g}"))

    def walk(element: ET.Element, inherited: dict[str, str]) -> None:
        tag = _local(element.tag)
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
                add_paint(colour, alpha)
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
        snap_pixelated_images(viewer_path)
        snap_pixelated_images(skia_outlined)

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
                f"墨迹包围盒差 {_pt(result.bbox_delta)} pt / 重心差 {_pt(result.centroid_delta)} pt"
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


def _pt(value: float | None) -> str:
    """pt 数字（保留两位）；`None` / `inf`（整页没有墨迹）显示为破折号。"""
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:.2f}"


def _finite(value: float | None) -> float | None:
    """JSON 里不能写 `Infinity`；无墨迹的那一侧记成 `null`。"""
    if value is None or not math.isfinite(value):
        return None
    return round(value, 3)


def inventory() -> list[Any]:
    """报告该覆盖的 case：三文件齐备且 `ci = true`（与 `viewer:parity` 同源）。

    `discover` 只读 `docs/cases/*/` 的静态契约，不渲染、不启浏览器——check 端
    可以几毫秒重算一次清单，这才是「报告与实测同源」的第一条判据。
    """
    matrix = case_runner._load_matrix_module()
    discovered = matrix.discover(case_runner.CASES)
    return sorted(
        (case for case in discovered if case.valid and case.ci), key=lambda case: case.name
    )


def inventory_digest(cases: list[Any]) -> str:
    """清单指纹：`name<TAB>family` 逐行排序后的 sha256。

    只覆盖「报告该覆盖谁」，不含任何实测值：新增 / 删除 case 或改 `family`
    都会让指纹变，所以「case 从 82 涨到 532 却没人重跑报告」在 check 的第一条
    就红（SIL-1017 的原始故障）。
    """
    payload = "".join(
        f"{case.name}\t{case.family}\n" for case in sorted(cases, key=lambda case: case.name)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def summarize(
    results: list[ParityCase], *, now: str, command: str, cases: list[Any]
) -> dict[str, Any]:
    """报告的机读摘要：check 只比这一块，并与人读表格交叉校验。

    `inventory.cases` 记的是清单条数（应等于 `len(results)`，报告必须是全量），
    `counts` / `failures` 记的是实测结果。两者分开，check 才能同时抓「清单漂移」
    与「数字被手改」。
    """
    counts = {
        status: sum(1 for item in results if item.status == status)
        for status in ("pass", "fail", "error")
    }
    return {
        "signature": SUMMARY_SIGNATURE,
        "generated_at": now,
        "command": command,
        "inventory": {"cases": len(cases), "sha256": inventory_digest(cases)},
        "counts": counts,
        "failures": [
            {
                "case": item.case,
                "family": item.family,
                "status": item.status,
                "reason": item.detail or "—",
            }
            for item in results
            if not item.ok
        ],
    }


def render_report(results: list[ParityCase], *, now: str, command: str, cases: list[Any]) -> str:
    summary = summarize(results, now=now, command=command, cases=cases)
    counts = summary["counts"]
    worst = max((item.pixel or 0.0) for item in results) if results else 0.0
    digest = summary["inventory"]["sha256"]
    lines = [
        "# 两条渲染腿的语义对拍（skia SVG × 浏览器 DOM SVG）",
        "",
        f"- 时间：{now}",
        f"- 复现：`{command}`",
        f"- 案例清单：{len(cases)} 条（`ci = true` 且三文件齐备）· 指纹 `sha256:{digest[:16]}`",
        f"- 结论：pass {counts['pass']} / fail {counts['fail']} / error {counts['error']}"
        f" / 共 {len(results)}；最大像素差 {_pct(worst)}"
        f"（阈值 {MAX_PIXEL_DIFF:.1%}，均值 ≤ {DEFAULT_MAX_MEAN:.0%}）",
        "- 校验：`pixi run viewer:parity:report:check` —— 清单漂移、计数、失败名单"
        "任一处与实测对不上即红；手改本文件任何数字都会失败。",
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
            SUMMARY_HEADING,
            "",
            "`pixi run viewer:parity:report:check` 只比这一块（并与上面的表格交叉校验）："
            "手改任何计数、失败名单或清单指纹，门禁都会变红。",
            "",
            "```json",
            json.dumps(summary, ensure_ascii=False, indent=2),
            "```",
            "",
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


# ---------------------------------------------------------------------------
# 报告门禁（SIL-1017：报告由 CI 校验，不再手改）
# ---------------------------------------------------------------------------

#: 报告表格的一行：`| \`case\` | \`族\` | … | ✅ pass |`。
_TABLE_ROW = re.compile(
    r"^\| `(?P<case>[^`]+)` \| `(?P<family>[^`]*)` \| [^|]+ \| [^|]+ \| [^|]+ "
    r"\| [^|]+ \| [^|]+ \| (?P<glyph>[^|]*?) \|$",
    re.MULTILINE,
)
_STATUS_BY_GLYPH = {"✅": "pass", "❌": "fail", "⛔": "error"}
_FAILURE_HEADING = re.compile(r"^### `(?P<case>[^`]+)`$", re.MULTILINE)
_COUNT_LINE = re.compile(
    r"^- 结论：pass (?P<pass>\d+) / fail (?P<fail>\d+) / error (?P<error>\d+)"
    r" / 共 (?P<total>\d+)；",
    re.MULTILINE,
)
_INVENTORY_LINE = re.compile(
    r"^- 案例清单：(?P<total>\d+) 条.*?指纹 `sha256:(?P<digest>[0-9a-f]+)`",
    re.MULTILINE,
)
_COMMAND_LINE = re.compile(r"^- 复现：`(?P<command>[^`]+)`", re.MULTILINE)


def _between(text: str, start: str, end: str) -> str:
    """取 `start` 之后、`end` 之前的片段（两个标记都不含）。"""
    begin = text.find(start)
    if begin < 0:
        return ""
    begin += len(start)
    stop = text.find(end, begin)
    return text[begin:] if stop < 0 else text[begin:stop]


def _show(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def read_summary(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """取报告里的机读摘要：`## 机读摘要` 下第一个 ```json 围栏。"""
    index = text.find(SUMMARY_HEADING)
    if index < 0:
        return None, [
            f"报告缺少 `{SUMMARY_HEADING}` 段落（跑 `pixi run viewer:parity:report` 重新生成）"
        ]
    fence = text.find("```json", index)
    if fence < 0:
        return None, [f"`{SUMMARY_HEADING}` 下没有 ```json 围栏"]
    start = fence + len("```json")
    end = text.find("```", start)
    if end < 0:
        return None, ["机读摘要的 ```json 围栏没有闭合"]
    try:
        payload = json.loads(text[start:end])
    except json.JSONDecodeError as error:
        return None, [f"机读摘要不是合法 JSON：{error}"]
    if not isinstance(payload, dict):
        return None, ["机读摘要的顶层必须是对象"]
    return payload, []


def _table_rows(text: str, problems: list[str]) -> list[tuple[str, str, str]]:
    """解析人读表格的 `(case, 族, status)`；结论列认不出来就记一条问题。"""
    rows: list[tuple[str, str, str]] = []
    for match in _TABLE_ROW.finditer(text):
        glyph = (match["glyph"] or "").strip().split()
        status = _STATUS_BY_GLYPH.get(glyph[0]) if glyph else None
        if status is None:
            problems.append(f"表格行 `{match['case']}` 的结论列无法识别：{match['glyph']!r}")
            continue
        rows.append((match["case"], match["family"], status))
    return rows


def check_report(
    path: Path = DEFAULT_REPORT, *, results: list[ParityCase] | None = None
) -> list[str]:
    """入库报告与实测是否一致（`pixi run viewer:parity:report:check`）。

    静态层（几毫秒，`viewer:parity:report:check`）：

    - **清单同源**：表格的 case 名单 / 顺序 / 族，以及头部的条数与指纹，都由
      `docs/cases` 现场重算——新增或删除 case 却没重跑报告，第一条就红；
    - **三处交叉一致**：头部结论行、表格逐行状态、`## 未通过` 名单、机读摘要的
      counts / failures，任一处被手改都会与其他三处对不上；
    - **失败有原因**：`## 未通过` 里每条都必须写清哪一层超阈值（或异常），
      审计不用再重跑基线 worktree 才能知道为什么红。

    `results` 非空时再叠一层「真跑」（`--measure`）：逐条 status 与失败名单必须
    与报告相同。`pixi run check` 跑的是 measure 变体（全量一次 ≈1.5 min）——
    静态层只能抓「自洽性」，把一条失败一致地改写成通过要真跑才看得见。
    """
    problems: list[str] = []
    if not path.is_file():
        return [f"{_show(path)} 不存在（跑 `pixi run viewer:parity:report` 生成）"]
    text = path.read_text(encoding="utf-8")
    summary, parse_problems = read_summary(text)
    problems.extend(parse_problems)

    cases = inventory()
    expected_names = [case.name for case in cases]
    expected_family = {case.name: case.family for case in cases}
    expected_digest = inventory_digest(cases)

    # 报告必须是全量：抽样报告（`--sample`）不进库。
    command_match = _COMMAND_LINE.search(text)
    if command_match is None:
        problems.append("报告缺少「- 复现：`…`」行")
    elif "--sample" in command_match["command"]:
        problems.append(f"报告是抽样生成的（`{command_match['command']}`）；入库报告必须是全量")

    # 头部：条数与清单指纹。
    inventory_match = _INVENTORY_LINE.search(text)
    if inventory_match is None:
        problems.append("报告缺少「- 案例清单：N 条 … 指纹 `sha256:…`」行")
    else:
        declared = int(inventory_match["total"])
        digest = inventory_match["digest"]
        if declared != len(expected_names):
            problems.append(
                f"头部声明的案例数 {declared} ≠ docs/cases 实测 {len(expected_names)} 条"
                "（新增 / 删除 case 后要重跑 `pixi run viewer:parity:report`）"
            )
        if len(digest) < 12:
            problems.append(f"清单指纹太短（{digest!r}），无法核对")
        elif not expected_digest.startswith(digest):
            problems.append(
                f"清单指纹 {digest} ≠ 实测 {expected_digest[: len(digest)]}"
                "（case 名单或 family 变了）"
            )

    # 表格：与实测清单逐条对齐。
    table = _table_rows(text, problems)
    if not table:
        problems.append("报告里没有 case 表格（表头 `| case | 族 | … | 结论 |`）")
    table_names = [name for name, _family, _status in table]
    if table_names and table_names != expected_names:
        present = set(table_names)
        known = set(expected_names)
        detail: list[str] = []
        missing = [name for name in expected_names if name not in present]
        extra = [name for name in table_names if name not in known]
        if missing:
            detail.append(f"缺 {len(missing)} 条（如 {', '.join(missing[:5])}）")
        if extra:
            detail.append(f"多 {len(extra)} 条（如 {', '.join(extra[:5])}）")
        if not detail:
            detail.append("case 名集合相同但行数或顺序不一致")
        problems.append("报告的 case 表格与 docs/cases 实测清单不一致：" + "；".join(detail))
    for name, family, _status in table:
        expected = expected_family.get(name)
        if expected is not None and family != expected:
            problems.append(f"`{name}` 的族写成 `{family}`，meta.toml 是 `{expected}`")

    # 头部结论行：总数必须等于实测清单，分项必须等于表格。
    count_match = _COUNT_LINE.search(text)
    head: dict[str, int] | None = None
    if count_match is None:
        problems.append("报告缺少「- 结论：pass N / fail M / error K / 共 T；」行")
    else:
        head = {key: int(count_match[key]) for key in ("pass", "fail", "error", "total")}
        if head["total"] != len(expected_names):
            problems.append(
                f"结论行的总数 {head['total']} ≠ docs/cases 实测 {len(expected_names)} 条"
            )
        if head["pass"] + head["fail"] + head["error"] != head["total"]:
            problems.append(
                "结论行自相矛盾："
                f"pass {head['pass']} + fail {head['fail']} + error {head['error']}"
                f" ≠ 共 {head['total']}"
            )
        for status in ("pass", "fail", "error"):
            rows_with = sum(1 for _name, _family, value in table if value == status)
            if table and head[status] != rows_with:
                problems.append(
                    f"结论行写 {status} {head[status]}，表格里有 {rows_with} 行"
                    f" {_glyph_for(status)}"
                )

    # 机读摘要：与表格、头部三处交叉。
    declared_failures: list[tuple[str, str]] = []
    if summary is not None:
        if summary.get("signature") != SUMMARY_SIGNATURE:
            problems.append(
                f"机读摘要签名 {summary.get('signature')!r} ≠ {SUMMARY_SIGNATURE!r}"
                "（报告是旧生成器写的，跑 `pixi run viewer:parity:report` 重新生成）"
            )
        block = summary.get("inventory") or {}
        if block.get("cases") != len(expected_names):
            problems.append(
                f"机读摘要 inventory.cases={block.get('cases')} ≠ 实测 {len(expected_names)} 条"
            )
        if block.get("sha256") != expected_digest:
            problems.append(f"机读摘要的清单指纹 {block.get('sha256')} ≠ 实测 {expected_digest}")
        counts = summary.get("counts") or {}
        for status in ("pass", "fail", "error"):
            if head is not None and counts.get(status) != head[status]:
                problems.append(
                    f"机读摘要 counts.{status}={counts.get(status)} 与结论行 {head[status]} 不一致"
                )
            rows_with = sum(1 for _name, _family, value in table if value == status)
            if table and counts.get(status) != rows_with:
                problems.append(
                    f"机读摘要 counts.{status}={counts.get(status)} 与表格 {rows_with} 行不一致"
                )
        failures = summary.get("failures")
        if not isinstance(failures, list):
            problems.append("机读摘要的 failures 必须是数组")
        else:
            declared_failures = [
                (str(item.get("case")), str(item.get("status")))
                for item in failures
                if isinstance(item, dict)
            ]
            table_failures = sorted(
                (name, status) for name, _family, status in table if status != "pass"
            )
            if sorted(declared_failures) != table_failures:
                problems.append(
                    "机读摘要的 failures 与表格非 pass 行不一致："
                    f"摘要 {len(declared_failures)} 条，表格 {len(table_failures)} 条"
                )
            for item in failures:
                if not isinstance(item, dict):
                    continue
                if not str(item.get("reason") or "").strip(" —-"):
                    problems.append(f"机读摘要里 `{item.get('case')}` 的失败原因为空")

    # `## 未通过` 名单：与表格非 pass 行一致，且每条写明原因。
    unpassed = _between(text, "## 未通过", SUMMARY_HEADING)
    headings = [match["case"] for match in _FAILURE_HEADING.finditer(unpassed)]
    table_failure_names = sorted(name for name, _family, status in table if status != "pass")
    if sorted(headings) != table_failure_names:
        problems.append(
            "`## 未通过` 的条目与表格非 pass 行不一致："
            f"段落 {len(headings)} 条，表格 {len(table_failure_names)} 条"
        )
    for block in re.split(r"^### `", unpassed, flags=re.MULTILINE)[1:]:
        name = block.split("`", 1)[0]
        reason_line = next((line for line in block.splitlines() if line.startswith("- 结论：")), "")
        reason = reason_line.split("；", 1)[1].strip() if "；" in reason_line else ""
        if not reason or reason == "—":
            problems.append(
                f"`{name}` 没有失败原因（要写清像素差 / 包围盒 / 涂色集合哪一层超阈值，或异常类型）"
            )

    # 真跑层：逐条 status 与失败名单。
    if results is not None:
        measured = {item.case: item.status for item in results}
        reported = {name: status for name, _family, status in table}
        for name in expected_names:
            if name not in measured:
                problems.append(f"实测没有跑 `{name}`")
            elif measured[name] != reported.get(name):
                problems.append(f"`{name}` 实测 {measured[name]}，报告写 {reported.get(name)}")
        for name in measured:
            if name not in reported:
                problems.append(f"实测多出 `{name}`，报告里没有")
        actual_failures = sorted((item.case, item.status) for item in results if not item.ok)
        if actual_failures != sorted(declared_failures):
            sample = ", ".join(name for name, _ in actual_failures[:5])
            problems.append(
                "失败名单与实测不一致："
                f"实测 {len(actual_failures)} 条（{sample}…），"
                f"报告 {len(declared_failures)} 条"
            )
    return problems


def _glyph_for(status: str) -> str:
    return {"pass": "✅", "fail": "❌", "error": "⛔"}.get(status, status)


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


# ---------------------------------------------------------------------------
# 非缺省 lineheight 的双腿对拍（SIL-869）
# ---------------------------------------------------------------------------

#: 取三个值：1.2 是 grid 缺省（对照组），1.0 / 2.0 是「更紧 / 更松」两侧。
#: 行距 = `1.2 × lineheight × size`，所以 12 pt 下分别是 14.4 / 17.28 / 28.8 pt。
LINEHEIGHTS = (1.0, 1.2, 2.0)
#: 文本墨迹包围盒四边之差，单位 pt。比常规 case 的 1 pt 更紧：这里整页只有
#: 文本，没有其它图元的抗锯齿边缘混进来。
MAX_LINEHEIGHT_DELTA = 0.5


@dataclass
class LineHeightParity:
    """一条非缺省 lineheight 在两条腿上的文本墨迹包围盒。"""

    lineheight: float
    skia_box: tuple[int, int, int, int] | None
    viewer_box: tuple[int, int, int, int] | None

    @property
    def skia_span(self) -> float | None:
        return None if self.skia_box is None else float(self.skia_box[3] - self.skia_box[1])

    @property
    def viewer_span(self) -> float | None:
        return None if self.viewer_box is None else float(self.viewer_box[3] - self.viewer_box[1])

    @property
    def span_delta(self) -> float:
        if self.skia_span is None or self.viewer_span is None:
            return float("inf")
        return abs(self.skia_span - self.viewer_span)

    @property
    def bbox_delta(self) -> float:
        """四边的最大差；两侧任一侧没有墨迹时判无穷大。"""
        return _bbox_delta(self.skia_box, self.viewer_box)

    @property
    def ok(self) -> bool:
        return self.bbox_delta <= MAX_LINEHEIGHT_DELTA


def lineheight_scene(lineheight: float) -> ir.Scene:
    """一条三行文本的合成场景：除了 `lineheight` 之外什么都不变。

    用与 `text-multiline` 同一条字体（Noto Sans CJK SC）与同一套
    anchor / baseline，这样浏览器腿的 `dominant-baseline` 换算与设备腿的
    cap height 口径都在既有的、已被对拍过的路径上。
    """
    text = ir.Node(
        ir.NodeKind.TEXT,
        ir.Gpar(col=(0, 0, 0, 255)),
        params={
            "font": "Noto Sans CJK SC",
            "size": 12.0,
            "anchor": "center",
            "baseline": "middle",
            "lineheight": lineheight,
        },
        bufs={"pos": ir.f32([[150.0, 100.0]]), "width": ir.f32([40.0])},
        texts=("alpha\nbravo\ncharlie",),
    )
    root = ir.Node(
        ir.NodeKind.VIEWPORT,
        params={"name": "page", "clip": False},
        children=(text,),
    )
    return ir.Scene(root=root, size=(300.0, 200.0))


def lineheight_parity(page, *, shaper, scratch: Path) -> list[LineHeightParity]:
    """同一份合成 IR 走两条腿：`LINEHEIGHTS` 各量一次文本墨迹包围盒的 y 跨度。

    这不是「断言解析出来的参数」：`SkiaSvgDevice` 真画一份 SVG，浏览器里的
    查看器真画另一份，两侧都把 `<text>` 轮廓化后交给 resvg（与常规对拍同一条
    链路），最后量 PNG 上非白墨迹的 y 跨度。缺省 1.2 一组是回归对照——它的
    数字必须与 SIL-869 之前一致。
    """
    results: list[LineHeightParity] = []
    for lineheight in LINEHEIGHTS:
        directory = scratch / f"lineheight-{lineheight:g}"
        directory.mkdir(parents=True, exist_ok=True)
        scene = lineheight_scene(lineheight)
        cbor = directory / "scene.ggir.cbor"
        cbor.write_bytes(ir.encode(scene))

        skia_svg = directory / "skia.svg"
        skia_svg.write_bytes(SkiaSvgDevice(*scene.size, dpi=72, shaper=shaper).render(scene))
        viewer_raw = _viewer_svg(page, cbor, directory / "viewer.svg")
        skia_outlined = directory / "skia.outlined.svg"
        viewer_outlined = directory / "viewer.outlined.svg"
        inline_text_paths(skia_svg, skia_outlined, shaper=shaper)
        inline_text_paths(viewer_raw, viewer_outlined, shaper=shaper)

        skia_png = rasterize_svg(
            skia_outlined, directory / "skia.png", dpi=72, background="#ffffff"
        )
        viewer_png = rasterize_svg(
            viewer_outlined, directory / "viewer.png", dpi=72, background="#ffffff"
        )
        results.append(
            LineHeightParity(
                lineheight=lineheight,
                skia_box=ink_bbox(skia_png),
                viewer_box=ink_bbox(viewer_png),
            )
        )
    return results


def lineheight_negative_control(scratch: Path) -> tuple[bool, str]:
    """负向对照：松行距的 viewer 输出对缺省行距的设备输出，必须判红。

    没有这一条，三组 0.00 pt 也可能只是「两侧都没在看 `lineheight`」。这里故意
    把 `lineheight = 2.0` 的浏览器腿与 `lineheight = 1.2` 的设备腿放在一起：两
    块文本的 y 跨度差 ≈ 23 pt，判据必须抓到。
    """
    reference = scratch / "lineheight-1.2" / "skia.png"
    other = scratch / "lineheight-2" / "viewer.png"
    delta = _bbox_delta(ink_bbox(reference), ink_bbox(other))
    return (
        delta > MAX_LINEHEIGHT_DELTA,
        f"1.2 设备腿 vs 2.0 浏览器腿：包围盒四边差 {_pt(delta)} pt"
        f"（阈值 {MAX_LINEHEIGHT_DELTA} pt）",
    )


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
        default=None,
        help=f"Markdown 报告路径（缺省 {DEFAULT_REPORT.relative_to(REPO)}；`--no-report` 时不写）",
    )
    parser.add_argument("--no-report", action="store_true", help="只判红绿，不写报告")
    parser.add_argument(
        "--check-report",
        action="store_true",
        help="校验入库报告与实测一致（CI 门禁）；不渲染、不写文件",
    )
    parser.add_argument(
        "--measure",
        action="store_true",
        help="配合 `--check-report`：真跑全量对拍再逐条比对"
        "（本机 ≈1.5 min，`pixi run check` 用它）",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="跑完之后做负向对照：平移 2 pt / 换一种颜色，判据必须变红",
    )
    parser.add_argument("--out", type=Path, default=REPO / ".viewer-cases", help="JSON 与中间产物")
    return parser


def _require_viewer_build() -> bool:
    if (REPO / "web" / "viewer" / "dist" / "main.js").is_file():
        return True
    print("viewer:parity: 先跑 `pixi run viewer:build`", file=sys.stderr)
    return False


def measure(
    runnable: list[Any], *, out: Path, selftest_run: bool
) -> tuple[list[ParityCase], list[LineHeightParity]] | None:
    """跑一遍对拍，返回（逐条结果, lineheight 自测）；环境缺失时返回 None。"""
    metrics = ShaperMetrics()
    shaper = TextShaper(emoji="outline")
    playwright_env.configure()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - dev 环境才有
        print("viewer:parity: 需要 playwright（pixi 的 dev 环境）", file=sys.stderr)
        return None

    results: list[ParityCase] = []
    lineheight_results: list[LineHeightParity] = []
    out.mkdir(parents=True, exist_ok=True)
    scratch_root = out / "parity"
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
            return None
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
            if selftest_run:
                lineheight_results = lineheight_parity(
                    page, shaper=shaper, scratch=out / "lineheight"
                )
        finally:
            browser.close()
    return results, lineheight_results


def _check_report_main(args: argparse.Namespace) -> int:
    """`--check-report`：入库报告必须与实测一致（SIL-1017 的 CI 守点）。"""
    if args.cases or args.sample is not None:
        print("viewer:parity: --check-report 不能和 --case / --sample 一起用", file=sys.stderr)
        return 2
    results: list[ParityCase] | None = None
    if args.measure:
        if not _require_viewer_build():
            return 2
        measured = measure(inventory(), out=args.out, selftest_run=False)
        if measured is None:
            return 2
        results, _lineheight = measured
        failed = [item for item in results if not item.ok]
        print(
            f"viewer:parity: 实测 {len(results)} case(s) — pass {len(results) - len(failed)}"
            f" / fail/error {len(failed)}"
        )
    path = args.report or DEFAULT_REPORT
    problems = check_report(path, results=results)
    if problems:
        print(f"{_show(path)} 与实测不一致（{len(problems)} 处）：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "修法：跑 `pixi run viewer:parity:report` 重新生成（不要手改报告）。",
            file=sys.stderr,
        )
        return 1
    print(f"{_show(path)} 与实测一致（{len(inventory())} case）")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check_report:
        return _check_report_main(args)
    if not _require_viewer_build():
        return 2

    all_cases = inventory()
    discovered = list(all_cases)
    wanted = set(args.cases or ())
    if wanted:
        discovered = [case for case in discovered if case.name in wanted]
        for name in sorted(wanted - {case.name for case in discovered}):
            print(f"viewer:parity: no case named {name!r}", file=sys.stderr)
    runnable = list(discovered)
    if args.sample is not None:
        runnable = case_runner._select_sample(runnable, max(args.sample, 0))
    runnable.sort(key=lambda case: case.name)

    measured = measure(runnable, out=args.out, selftest_run=args.selftest)
    if measured is None:
        return 2
    results, lineheight_results = measured

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
        "lineheight_selftest": [
            {
                "lineheight": item.lineheight,
                "skia_span_pt": _finite(item.skia_span),
                "viewer_span_pt": _finite(item.viewer_span),
                "span_delta_pt": _finite(item.span_delta),
                "bbox_delta_pt": _finite(item.bbox_delta),
                "status": "pass" if item.ok else "fail",
            }
            for item in lineheight_results
        ],
    }
    (args.out / "parity.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.no_report:
        pass
    elif args.sample is not None or args.cases:
        # 入库报告必须是全量：抽样只判红绿，不许覆盖报告（`viewer:parity:ci` 走 --no-report）。
        print("viewer:parity: 抽样 / 单条运行不写入库报告（报告必须是全量清单）")
    else:
        command = "pixi run viewer:parity:report"
        report_path = args.report or DEFAULT_REPORT
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_report(results, now=now, command=command, cases=all_cases),
            encoding="utf-8",
        )
        print(f"viewer:parity: report {_show(report_path)}")

    failed = [item for item in results if not item.ok]
    if args.selftest:
        for item in lineheight_results:
            glyph = "✅" if item.ok else "❌"
            print(
                f"{glyph} selftest: lineheight {item.lineheight:g} 双腿对拍"
                f"（y 跨度 skia {_pt(item.skia_span)} / viewer {_pt(item.viewer_span)} pt，"
                f"跨度差 {_pt(item.span_delta)} pt / 四边差 {_pt(item.bbox_delta)} pt）"
            )
            if not item.ok:
                failed.append(
                    ParityCase(
                        case=f"selftest:lineheight-{item.lineheight:g}",
                        family="selftest",
                        status="fail",
                        detail=f"文本墨迹包围盒四边差 {_pt(item.bbox_delta)} pt",
                    )
                )
        for name, detected, detail in selftest(args.out / "parity"):
            glyph = "✅" if detected else "❌"
            print(f"{glyph} selftest: {name}（{detail}）")
            if not detected:
                failed.append(ParityCase(case=f"selftest:{name}", family="selftest", status="fail"))
        if lineheight_results:
            detected, detail = lineheight_negative_control(args.out / "lineheight")
            glyph = "✅" if detected else "❌"
            print(f"{glyph} selftest: 忽略 lineheight 必须被判红（{detail}）")
            if not detected:
                failed.append(
                    ParityCase(case="selftest:lineheight-ignored", family="selftest", status="fail")
                )
    print(
        f"viewer:parity: {len(results)} case(s) — pass {len(results) - len(failed)}, "
        f"fail/error {len(failed)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
