#!/usr/bin/env python
"""把 `docs/cases/grob-*` 的 grob 用例画成 PNG 快照（M0-6）。

    pixi run cases:grob            # 重新生成 baseline/<case id>.png
    pixi run cases:grob --check    # 只和仓库里的 baseline 比对，不写文件

链路与正式渲染一致：`case.json` → grob 树（`ggcore.grobs`）→
`ggcore.grobs.scene()`（场景遍历）→ 扁平 `Scene` → `Scene.to_ir_scene()`（float32
舍入）→ **`ggskia.SkiaRasterDevice`**。也就是说快照验证的是遍历结果**加写
IR 这一步**（坐标、gpar、裁剪、绘制顺序、节点分组）加设备本身，不是另一套几何
计算。设备只吃 IR（`docs/notes/grobs.md` §7.2），实现与口径见 `docs/notes/device.md`。

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

曲线（`xspline` / `curve`）、`pch` 符号表、文字 shaping 与 CJK 轮廓都在设备里
（M0-8），这里不再有近似：`ggskia.curves` 是 R `xspline.c` /
`grid::curveGrob` 的移植，`pch` 是 `engine.c::GESymbol()` 的几何，文字走
HarfBuzz shaping + 受管字体。

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
from ggcore.units import unit  # noqa: E402
from ggcore.viewport import (  # noqa: E402
    NA,
    Device,
    Gpar,
    Viewport,
    ViewportTree,
    viewport,
)
from ggskia import SkiaRasterDevice  # noqa: E402

CASES = REPO / "docs" / "cases"
# 「Noto Sans CJK SC」同时覆盖拉丁与中日韩字形；DejaVu 只作兜底。
FONT_NAMES = ("NotoSansCJKsc-VF.ttf", "DejaVuSans.ttf")
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
    """case.json → grob 树 → 场景遍历 → **IR** → M0-8 的 raster 设备 → PNG。"""
    resolved, ppi = build(case)
    ir_scene = resolved.to_ir_scene()
    device = SkiaRasterDevice(*ir_scene.size, dpi=ppi)
    device.open()
    device.draw_scene(ir_scene)
    # 页眉页脚不参与场景遍历：直接落在设备画布的页面坐标上（与旧基线的字面一致）。
    if case.get("title"):
        _label(device.canvas, case["title"], 12.0, 20.0, 10.0, "#222222")
    if case.get("caption"):
        _label(device.canvas, case["caption"], 12.0, ir_scene.size[1] - 10.0, 7.0, "#555555")
    return device.close()


def _label(canvas: Any, text: str, x: float, y: float, size_pt: float, colour: str) -> None:
    """页眉页脚：页面 pt 直接落字，不进 IR（快照的说明文字，不是图元）。"""
    paint = skia.Paint(AntiAlias=True)
    paint.setColor(_color(colour))
    typeface = skia.Typeface.MakeFromFile(str(font_file()))
    canvas.drawString(text, x, y, skia.Font(typeface, size_pt), paint)


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
