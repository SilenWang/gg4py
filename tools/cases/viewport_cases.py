#!/usr/bin/env python
"""把 `docs/cases` 下的 viewport 用例画成 PNG 快照（M0-4）。

    pixi run cases:viewport            # 重新生成 baseline/*.png
    pixi run cases:viewport --check    # 只和仓库里的 baseline 比对，不写文件

`docs/cases/<case>/case.json` 在 `kind = "viewport"` 时是一段**视口脚本**：
一个设备尺寸、一组视口规格（`ggcore.viewport.viewport()` 的参数）和一串绘制
原语。原语都在**当前视口**里取坐标，落笔前按当前视口的裁剪框裁剪——所以这些
快照同时在验证变换（旋转叠加）和裁剪三态。

绘制原语：

| op | 字段 | 说明 |
| --- | --- | --- |
| `push` | `vp`: 视口下标 | 压入 `viewports[i]` |
| `pop` | `n` | 出栈 |
| `outline` | `color` / `width_pt` | 当前视口 `0..1 npc` 的边框 |
| `axes` | `color` | 本地坐标轴：左边、下边 + 刻度 |
| `polyline` | `x` / `y` / `unit` / `color` | 视口坐标里的折线（矢量） |
| `bands` | `color` / `ys` / `x` | 本地 npc 的横带（`x` 可超出 0..1）：暴露裁剪边界 |
| `label` | `text` / `at` / `color` | 在当前视口里定位的说明文字 |
| `clipbox` | `color` | 当前生效的裁剪框（虚线） |

文字用的是 pixi 受管的 DejaVu Sans（`font-ttf-dejavu`），行宽、字形都随
环境钉死；不依赖系统字体。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import skia

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from ggcore.units import unit  # noqa: E402  （src 布局，先补 path 再导入）
from ggcore.viewport import Device, Gpar, ViewportTree, VpNode, viewport  # noqa: E402

CASES = REPO / "docs" / "cases"
BASELINE = "viewport.png"
# 「Noto Sans CJK SC」同时覆盖拉丁与中日韩字形；DejaVu 只作兜底。
FONT_NAMES = ("NotoSansCJKsc-VF.ttf", "DejaVuSans.ttf")


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _color(value: str) -> int:
    text = value.lstrip("#")
    if len(text) == 6:
        red, green, blue = (int(text[index : index + 2], 16) for index in (0, 2, 4))
        return skia.ColorSetARGB(255, red, green, blue)
    if len(text) == 8:
        red, green, blue, alpha = (int(text[index : index + 2], 16) for index in (0, 2, 4, 6))
        return skia.ColorSetARGB(alpha, red, green, blue)
    raise ValueError(f"bad colour: {value!r}")


def _unit(spec: list[Any]) -> Any:
    return unit(float(spec[0]), spec[1])


def _build(spec: dict[str, Any]) -> Any:
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
        gp=Gpar(**spec.get("gp", {})),
    )


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


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


class Scene:
    """一台设备 + 一棵视口树 + 画布。坐标一律先说英寸（y 向上），落笔时翻成像素。"""

    def __init__(self, spec: dict[str, Any]) -> None:
        device = spec["device"]
        self.ppi = float(device["pixels_per_inch"])
        self.device = Device(float(device["width_in"]), float(device["height_in"]))
        self.width_px = round(self.device.width_in * self.ppi)
        self.height_px = round(self.device.height_in * self.ppi)
        self.surface = skia.Surface.MakeRasterN32Premul(self.width_px, self.height_px)
        self.canvas = self.surface.getCanvas()
        self.canvas.clear(skia.ColorWHITE)
        self.tree = ViewportTree(self.device)
        self.typeface = skia.Typeface.MakeFromFile(str(font_file()))
        if self.typeface is None:  # pragma: no cover - 字体损坏才会发生
            raise SystemExit(f"无法加载字体 {font_file()}")

    # -- 坐标 ---------------------------------------------------------------

    def px(self, x_in: float, y_in: float) -> tuple[float, float]:
        return (x_in * self.ppi, (self.device.height_in - y_in) * self.ppi)

    def px_rect(self, box: tuple[float, float, float, float]) -> skia.Rect:
        left, bottom = self.px(box[0], box[1])
        right, top = self.px(box[2], box[3])
        return skia.Rect.MakeLTRB(left, top, right, bottom)

    def stroke_width(self, width_pt: float) -> float:
        return max(width_pt * self.ppi / 72.0, 1.0)

    def paint(
        self,
        color: str,
        *,
        width_pt: float | None = None,
        dashed: bool = False,
    ) -> skia.Paint:
        paint = skia.Paint(AntiAlias=True)
        paint.setColor(_color(color))
        if width_pt is None:
            paint.setStyle(skia.Paint.kFill_Style)
        else:
            paint.setStyle(skia.Paint.kStroke_Style)
            paint.setStrokeWidth(self.stroke_width(width_pt))
            paint.setStrokeCap(skia.Paint.kRound_Cap)
            paint.setStrokeJoin(skia.Paint.kRound_Join)
            if dashed:
                paint.setPathEffect(skia.DashPathEffect.Make([6.0, 4.0], 0.0))
        return paint

    def text(self, text: str, x_px: float, y_px: float, color: str, size_pt: float) -> None:
        paint = self.paint(color)
        font = skia.Font(self.typeface, max(size_pt * self.ppi / 72.0, 6.0))
        self.canvas.drawString(text, x_px, y_px, font, paint)

    @property
    def current(self) -> VpNode:
        return self.tree.current

    def inside(self, draw: Any) -> None:
        """按当前视口的裁剪框裁一次再画（`clip` 三态在这里生效）。"""
        self.canvas.save()
        self.canvas.clipRect(self.px_rect(self.current.clip_box))
        draw()
        self.canvas.restore()

    # -- 原语 ---------------------------------------------------------------

    def outline(self, color: str, width_pt: float) -> None:
        node = self.current
        corners = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        xs = unit([c[0] for c in corners], "npc")
        ys = unit([c[1] for c in corners], "npc")
        points = node.device_points(xs, ys)

        def draw() -> None:
            path = skia.Path()
            path.moveTo(*self.px(*points[0]))
            for point in points[1:]:
                path.lineTo(*self.px(*point))
            path.close()
            self.canvas.drawPath(path, self.paint(color, width_pt=width_pt))

        self.inside(draw)

    def axes(self, color: str) -> None:
        node = self.current

        def draw() -> None:
            paint = self.paint(color, width_pt=0.6)
            for (x0, y0), (x1, y1) in (((0.0, 0.0), (1.0, 0.0)), ((0.0, 0.0), (0.0, 1.0))):
                start = node.device_points(unit(x0, "npc"), unit(y0, "npc"))[0]
                end = node.device_points(unit(x1, "npc"), unit(y1, "npc"))[0]
                self.canvas.drawLine(*self.px(*start), *self.px(*end), paint)
            # 0.25 步长的刻度
            for step in (0.25, 0.5, 0.75):
                start = node.device_points(unit(step, "npc"), unit(0.0, "npc"))[0]
                end = node.device_points(unit(step, "npc"), unit(-0.03, "npc"))[0]
                self.canvas.drawLine(*self.px(*start), *self.px(*end), paint)
                start = node.device_points(unit(0.0, "npc"), unit(step, "npc"))[0]
                end = node.device_points(unit(-0.03, "npc"), unit(step, "npc"))[0]
                self.canvas.drawLine(*self.px(*start), *self.px(*end), paint)

        self.inside(draw)

    def polyline(self, xs: list[float], ys: list[float], unit_name: str, color: str) -> None:
        node = self.current
        if len(xs) != len(ys):
            raise ValueError("polyline x/y must have the same length")
        points = node.device_points(unit(xs, unit_name), unit(ys, unit_name))

        def draw() -> None:
            path = skia.Path()
            path.moveTo(*self.px(*points[0]))
            for point in points[1:]:
                path.lineTo(*self.px(*point))
            self.canvas.drawPath(path, self.paint(color, width_pt=1.6))

        self.inside(draw)

    def bands(
        self,
        color: str,
        ys: list[float],
        x_range: list[float],
        width_pt: float = 2.0,
    ) -> None:
        """在视口 npc 坐标里画几条横带（`x` 可以超出 0..1）：裁不裁剪一眼可见。"""
        node = self.current
        paint = self.paint(color, width_pt=width_pt)

        def draw() -> None:
            for y in ys:
                start = node.device_points(unit(x_range[0], "npc"), unit(y, "npc"))[0]
                end = node.device_points(unit(x_range[1], "npc"), unit(y, "npc"))[0]
                self.canvas.drawLine(*self.px(*start), *self.px(*end), paint)

        self.inside(draw)

    def label(self, text: str, at: list[list[Any]], color: str, size_pt: float = 8.0) -> None:
        point = self.current.device_points(_unit(at[0]), _unit(at[1]))[0]
        x_px, y_px = self.px(*point)
        self.text(text, x_px, y_px, color, size_pt)

    def clipbox(self, color: str) -> None:
        box = self.current.clip_box
        self.canvas.drawRect(self.px_rect(box), self.paint(color, width_pt=0.8, dashed=True))

    # -- 页眉页脚 -----------------------------------------------------------

    def header(self, title: str) -> None:
        self.text(title, 18.0, 24.0, "#222222", 11.0)

    def footer(self, caption: str) -> None:
        self.text(caption, 18.0, self.height_px - 12.0, "#555555", 7.5)

    def png(self) -> bytes:
        image = self.surface.makeImageSnapshot()
        data = image.encodeToData(skia.kPNG, 100)
        if data is None:  # pragma: no cover - 编码失败才会发生
            raise SystemExit("PNG encoding failed")
        return bytes(data.bytes())


# ---------------------------------------------------------------------------
# case.json → PNG
# ---------------------------------------------------------------------------


def render(case: dict[str, Any]) -> bytes:
    if case.get("kind") != "viewport":
        raise ValueError(f"{case.get('id')}: not a viewport case")
    scene = Scene(case)
    if case.get("title"):
        scene.header(case["title"])
    specs = case["viewports"]
    for step in case["steps"]:
        op = step["op"]
        if op == "push":
            scene.tree.push(_build(specs[step["vp"]]))
        elif op == "pop":
            scene.tree.pop(step.get("n", 1))
        elif op == "outline":
            scene.outline(step["color"], step.get("width_pt", 1.2))
        elif op == "axes":
            scene.axes(step["color"])
        elif op == "polyline":
            scene.polyline(step["x"], step["y"], step["unit"], step["color"])
        elif op == "bands":
            scene.bands(step["color"], step["ys"], step["x"], step.get("width_pt", 2.0))
        elif op == "label":
            scene.label(step["text"], step["at"], step["color"], step.get("size_pt", 8.0))
        elif op == "clipbox":
            scene.clipbox(step["color"])
        else:  # pragma: no cover - 规格写错才会走到
            raise ValueError(f"{case['id']}: unknown op {op!r}")
    if case.get("caption"):
        scene.footer(case["caption"])
    return scene.png()


def load_cases(root: Path = CASES) -> list[tuple[Path, dict[str, Any]]]:
    cases: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(root.glob("*/case.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("kind") == "viewport":
            cases.append((path.parent, data))
    return cases


def decode(png: bytes) -> np.ndarray[Any, Any]:
    """PNG 字节 → (h, w, 4) uint8（通道顺序随 skia 的 N32 布局，比对时无需关心）。"""
    image = skia.Image.MakeFromEncoded(png)
    if image is None:  # pragma: no cover - 坏 PNG 才会发生
        raise ValueError("cannot decode PNG")
    return image.toarray()


def compare(actual: bytes, expected: bytes) -> str | None:
    """像素比对：返回不一致的说明，一致时返回 None。

    阈值留了余量：光栅化的抗锯齿在不同 CPU 的 SIMD 路径上可能差一两个灰阶，
    但结构变化（视口挪位、裁剪框错、文字缺失）会让整片像素差到几百，均值
    一定过线。
    """
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render viewport snapshot cases to PNG.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare with the committed baseline instead of writing it",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="only handle this case id (repeatable)",
    )
    args = parser.parse_args(argv)

    cases = load_cases()
    if not cases:
        print("cases:viewport: no viewport case found", file=sys.stderr)
        return 2
    wanted = set(args.cases or [])
    failures = 0
    for directory, case in cases:
        if wanted and case["id"] not in wanted:
            continue
        png = render(case)
        target = directory / "baseline" / BASELINE
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
