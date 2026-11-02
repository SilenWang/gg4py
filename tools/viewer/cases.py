#!/usr/bin/env python
"""M1-16：把案例库逐张丢进浏览器查看器，量化「61 条 case 都能打开」这件事。

    pixi run viewer:cases                    # 61 条三文件 case + 16 条 grob 快照
    pixi run viewer:cases --only facet-wrap-2x2,grob-raster,grob-text-rot
    pixi run viewer:cases --group cases      # 只跑三文件 case（CI 的快速档）
    pixi run viewer:cases --no-legacy

一张 case 的流程：

1. `tools/cases/matrix.py` 的 `discover()` / `legacy_snapshots()` 找 case；
   三文件 case 走 `ggcore.plotspec.build_scene()`，grob 快照走
   `tools/cases/grob_cases.build()` → `to_ir_scene()`；
2. 同一份场景编码成 `.viewer-cases/<case>.ggir.cbor`（deterministic bytes）；
3. 真 Chromium 加载 `.ggir.cbor`，量整页 DOM、`svg.gg-svg` 的图元数、加载耗时，
   并导出页内 `svg.gg-svg` 的 outerHTML 与 2× 截图；
4. 同一份 IR 用桌面 SVG 设备出图（等价 `pixi run render --scene … --out …svg`）；
5. 两侧都用 **resvg 2×** 光栅化后比像素：
   - viewer vs `expected.svg`（外部参考，判据 B 栏）；
   - viewer vs 桌面 SVG（同一份 IR，判据 B 栏 + 掩掉文字）；
   - 文字区域由 IR 的 `text` 元素边界（页内 getBBox/getCTM）算出并掩掉。

产物（`.viewer-cases/`，不入库）：`report.md`、`report.json`、每张 case 的
`.ggir.cbor` / `svg/<case>.svg` / `png/<case>.browser.png` / `desktop/<case>.svg`。

退出码：有红 case（加载失败 / 尺寸不一致 / 超阈值）→ 1；单张加载 > 5 s 记
`slow` 并进报告，但不判红。口径见 `docs/notes/viewer.md` §2 / §8 与
`docs/notes/snapshot-policy.md` B 栏。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import sys
import threading
import time
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for _path in (REPO / "src", REPO / "tools" / "cases", REPO / "tools" / "viewer"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import numpy as np  # noqa: E402
import playwright_env  # noqa: E402
from grob_cases import build as build_grob_scene  # noqa: E402
from matrix import discover, legacy_snapshots  # noqa: E402

from ggcore import ir  # noqa: E402
from ggcore.plotspec import PlotSpecError, build_scene, load_plot  # noqa: E402
from ggdiff.image import load_image  # noqa: E402
from ggdiff.raster import RasterError, rasterize_svg, resvg_version  # noqa: E402
from ggdiff.svgtext import SvgTextError, inline_text_paths  # noqa: E402
from ggskia import device_for  # noqa: E402
from ggskia.text import ShaperMetrics  # noqa: E402

__all__ = ["ViewerCase", "main", "run_cases"]

CASES_DIR = REPO / "docs" / "cases"
DEFAULT_OUT = REPO / ".viewer-cases"
REPORT_MD = "report.md"
REPORT_JSON = "report.json"

#: 两侧都按 2× 光栅化：1 pt = 2 px（`snapshot-policy.md` 的 B 栏同口径）。
SCALE = 2
DPI = 72 * SCALE
#: 单张加载超过这个时间记 `slow`（issue 的验收口径）。
SLOW_MS = 5000.0
#: B 栏：平均差异 ≤ 1%，单像素最大通道差 > 90/255 的占比 ≤ 2%。
MAX_MEAN = 0.01
MAX_OVER90 = 0.02
#: B 栏的另一条：> 4/255 的像素占比 ≤ 2%（case 的 `tolerance.png` 可收紧）。
MAX_OVER4 = 0.02
#: 文字掩码的膨胀半径（pt）：IR 与浏览器字宽差几个百分点时仍能盖住。
TEXT_PAD_PT = 6.0

PASS = "pass"
FAIL = "fail"


@dataclass
class ViewerCase:
    """一张待渲染的 case：来源、场景与参考图。"""

    name: str
    group: str  # "case"（三文件） / "grob"（快照）
    directory: Path
    scene: ir.Scene
    expected: Path | None = None
    tolerance: float = MAX_OVER4
    family: str = ""
    features: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)
    #: `meta.toml` 的 `ci = false`：case 自己登记了「还没接上的东西」，与 expected
    #: 的差异是已知缺口（矩阵同样只登记不判红）；桌面差与加载仍按红处理。
    known_gap: bool = False


# ---------------------------------------------------------------------------
# case 装配
# ---------------------------------------------------------------------------


def _kinds(scene: ir.Scene) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for node in ir.walk(scene.root):
        counts[node.kind.value] += 1
    return dict(sorted(counts.items()))


def _pch(scene: ir.Scene) -> list[int]:
    return [
        int(node.params["pch"])
        for node in ir.walk(scene.root)
        if node.kind.value == "points" and node.params.get("pch") is not None
    ]


def _three_file_cases(root: Path) -> tuple[list[ViewerCase], list[dict[str, Any]]]:
    """`docs/cases/*/plot.py`：61 条三文件 case。"""
    metrics = ShaperMetrics()
    cases: list[ViewerCase] = []
    invalid: list[dict[str, Any]] = []
    for case in discover(root):
        if not case.valid:
            invalid.append({"name": case.name, "reasons": list(case.errors)})
            continue
        try:
            spec = load_plot(case.directory)
            scene = build_scene(spec, metrics=metrics)
        except (PlotSpecError, ValueError) as error:
            invalid.append({"name": case.name, "reasons": [f"{type(error).__name__}: {error}"]})
            continue
        expected = case.directory / case.expected if case.expected else None
        known = not case.ci
        notes = []
        if known:
            meta = tomllib.loads((case.directory / "meta.toml").read_text(encoding="utf-8"))
            notes = [str(meta.get("notes", "")).strip()] if meta.get("notes") else []
        cases.append(
            ViewerCase(
                name=case.name,
                group="case",
                directory=case.directory,
                scene=scene,
                expected=expected,
                tolerance=case.tolerance.get("png", MAX_OVER4),
                family=case.family,
                features=case.features,
                known_gap=known,
                notes=notes,
            )
        )
    return cases, invalid


def _grob_cases(root: Path) -> list[ViewerCase]:
    """`docs/cases/grob-*/case.json`：走 grob 树 → IR，覆盖 raster / xspline /
    bezier / 旋转文字这类三文件 case 里没有的 kind。"""
    cases: list[ViewerCase] = []
    for directory in legacy_snapshots(root):
        spec = json.loads((directory / "case.json").read_text(encoding="utf-8"))
        if spec.get("kind") != "grob":
            continue
        resolved, _ppi = build_grob_scene(spec)
        cases.append(
            ViewerCase(
                name=directory.name,
                group="grob",
                directory=directory,
                scene=resolved.to_ir_scene(),
                notes=["grob 快照：baseline 含页眉标题，不与 expected 比像素，只与桌面同 IR 对拍"],
            )
        )
    return cases


def _filter(cases: list[ViewerCase], only: list[str]) -> list[ViewerCase]:
    if not only:
        return cases
    wanted = [name.strip() for name in only if name.strip()]
    known = {case.name for case in cases}
    missing = [name for name in wanted if name not in known]
    if missing:
        raise SystemExit(f"没有这些 case：{', '.join(missing)}")
    return [case for case in cases if case.name in wanted]


# ---------------------------------------------------------------------------
# 页内测量
# ---------------------------------------------------------------------------

#: 页内 JS：清状态 → 之后等 `status[data-state=ok]` 且文本带文件名（防串台）。
_RESET = """() => {
  const status = document.querySelector('#status');
  status.dataset.state = 'idle';
  status.textContent = '';
}"""

_TAGS = """() => {
  const counts = {};
  for (const element of document.querySelectorAll('svg.gg-svg [data-row]')) {
    counts[element.localName] = (counts[element.localName] || 0) + 1;
  }
  return counts;
}"""

_TEXT_BOXES = """() => {
  // `getCTM()` 是「元素用户单位 → CSS 像素」（页面把 288pt 排成 384px，还带
  // 页面排版偏移），掩码要的是页面 pt：先到屏幕坐标，再按根 SVG 的屏幕变换还原。
  const root = document.querySelector('svg.gg-svg');
  const rootScreen = root.getScreenCTM();
  const toUser = ([x, y]) => [
    (x - rootScreen.e) / rootScreen.a,
    (y - rootScreen.f) / rootScreen.d,
  ];
  return Array.from(root.querySelectorAll('text[data-kind="text"]')).map((element) => {
    const box = element.getBBox();
    const matrix = element.getScreenCTM();
    const corners = [
      [box.x, box.y],
      [box.x + box.width, box.y],
      [box.x, box.y + box.height],
      [box.x + box.width, box.y + box.height],
    ].map(([x, y]) =>
      toUser([matrix.a * x + matrix.c * y + matrix.e, matrix.b * x + matrix.d * y + matrix.f]),
    );
    return [
      Math.min(...corners.map((point) => point[0])),
      Math.min(...corners.map((point) => point[1])),
      Math.max(...corners.map((point) => point[0])),
      Math.max(...corners.map((point) => point[1])),
    ];
  });
}"""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


class ViewerServer:
    """`http.server` 一次（`file://` 下浏览器会拦 ES module）。"""

    def __init__(self) -> None:
        handler = functools.partial(_QuietHandler, directory=str(playwright_env.VIEWER))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _load_page(page: Any, cbor: Path) -> dict[str, Any]:
    """把一份 `.ggir.cbor` 拖进查看器，量 DOM / 图元 / 耗时，导出 SVG 与截图。"""
    name = cbor.name
    page.evaluate(_RESET)
    started = time.perf_counter()
    page.set_input_files("#file", str(cbor))
    page.wait_for_function(
        """(name) => {
          const status = document.querySelector('#status');
          return status.dataset.state === 'ok' && status.textContent.includes(name);
        }""",
        arg=name,
        timeout=30_000,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    state = page.evaluate("() => window.ggViewer.state()") or {}
    return {
        "load_ms": elapsed_ms,
        "dom_total": int(page.evaluate("() => document.querySelectorAll('*').length")),
        "svg_total": int(page.evaluate("() => document.querySelectorAll('svg.gg-svg *').length")),
        "elements": {key: int(value) for key, value in page.evaluate(_TAGS).items()},
        "leaves": int(state.get("leaves", 0)),
        "legends": int(state.get("legends", 0)),
        "text_boxes": page.evaluate(_TEXT_BOXES),
    }


# ---------------------------------------------------------------------------
# 光栅化与像素差
# ---------------------------------------------------------------------------


def _mask(boxes: list[list[float]], shape: tuple[int, int]) -> np.ndarray:
    """文字掩码：(H, W) bool，True = 文字区域。`boxes` 是页面 pt。"""
    height, width = shape
    mask = np.zeros((height, width), dtype=bool)
    pad = TEXT_PAD_PT * SCALE
    for x0, y0, x1, y1 in boxes:
        left = max(0, int(np.floor(x0 * SCALE - pad)))
        top = max(0, int(np.floor(y0 * SCALE - pad)))
        right = min(width, int(np.ceil(x1 * SCALE + pad)))
        bottom = min(height, int(np.ceil(y1 * SCALE + pad)))
        if right > left and bottom > top:
            mask[top:bottom, left:right] = True
    return mask


def pixel_diff(
    reference: np.ndarray, actual: np.ndarray, mask: np.ndarray | None = None
) -> dict[str, Any]:
    """三条数：平均差异、> 4/255 占比、> 90/255 占比（都按扫过的像素算）。"""
    if reference.shape != actual.shape:
        return {
            "size_mismatch": True,
            "mean": 1.0,
            "over4": 1.0,
            "over90": 1.0,
            "max": 255,
            "total": int(reference.shape[0] * reference.shape[1]),
        }
    difference = np.abs(reference.astype(np.int16) - actual.astype(np.int16))
    per_pixel = difference.max(axis=2)
    if mask is not None and mask.any():
        keep = ~mask
        difference = difference[keep]
        per_pixel = per_pixel[keep]
        total = int(keep.sum())
        masked = int(mask.sum())
    else:
        total = int(per_pixel.size)
        masked = 0
    return {
        "size_mismatch": False,
        "mean": float(difference.astype(np.float32).mean() / 255.0) if total else 0.0,
        "over4": float((per_pixel > 4).sum() / total) if total else 0.0,
        "over90": float((per_pixel > 90).sum() / total) if total else 0.0,
        "max": int(per_pixel.max()) if total else 0,
        "total": total,
        "masked": masked,
    }


def _rasterize_expected(path: Path, out: Path) -> Path:
    """`expected.svg` 先过 `ggdiff.svgtext`（resvg 画不出 Noto CJK VF）。"""
    if path.suffix.lower() == ".png":
        return path
    prepared = out.with_name(f"{out.stem}-outlined.svg")
    inline_text_paths(path, prepared)
    return rasterize_svg(prepared, out, dpi=DPI, background="#ffffff")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _desktop_svg(case: ViewerCase, path: Path) -> None:
    """同一份 IR → 桌面 SVG 设备（等价 `pixi run render --scene … --out …svg`）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(device_for("svg", *case.scene.size).render(case.scene))


def run_cases(
    cases: list[ViewerCase],
    *,
    out: Path,
    page: Any,
    requests: list[str] | None = None,
) -> list[dict[str, Any]]:
    """逐张渲染 + 对拍；返回每张 case 的记录（不含汇总）。"""
    records: list[dict[str, Any]] = []
    for case in cases:
        record: dict[str, Any] = {
            "name": case.name,
            "group": case.group,
            "family": case.family,
            "ir_nodes": sum(1 for _ in ir.walk(case.scene.root)),
            "ir_kinds": _kinds(case.scene),
            "pch": _pch(case.scene),
            "status": PASS,
            "reasons": [],
        }
        cbor = out / f"{case.name}.ggir.cbor"
        viewer_svg = out / "svg" / f"{case.name}.svg"
        viewer_png = out / "png" / f"{case.name}.browser.png"
        try:
            cbor.write_bytes(ir.encode(case.scene))
            _desktop_svg(case, out / "desktop" / f"{case.name}.svg")
            measured = _load_page(page, cbor)
            viewer_svg.parent.mkdir(parents=True, exist_ok=True)
            viewer_svg.write_text(
                page.evaluate("() => document.querySelector('svg.gg-svg').outerHTML"),
                encoding="utf-8",
            )
            viewer_png.parent.mkdir(parents=True, exist_ok=True)
            page.locator("svg.gg-svg").screenshot(path=str(viewer_png))
            record.update(measured)
        except Exception as error:
            record["status"] = FAIL
            record["reasons"].append(
                f"浏览器加载失败：{type(error).__name__}: {str(error).splitlines()[0][:200]}"
            )
            records.append(record)
            continue

        if requests is not None:
            record["wasm_requests"] = sum(1 for url in requests if ".wasm" in url)
        record["slow"] = record["load_ms"] > SLOW_MS
        if record["slow"]:
            record["reasons"].append(f"加载 {record['load_ms']:.0f}ms > {SLOW_MS:.0f}ms")

        # 2× 光栅化：viewer 写 pt（dpi 管用），桌面写无单位用户单位（用 zoom）。
        scratch = out / "raster" / case.name
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            viewer_raster = rasterize_svg(
                viewer_svg, scratch / "viewer.png", dpi=DPI, background="#ffffff"
            )
            desktop_raster = rasterize_svg(
                out / "desktop" / f"{case.name}.svg",
                scratch / "desktop.png",
                dpi=DPI,
                background="#ffffff",
                zoom=SCALE,
            )
        except RasterError as error:
            record["status"] = FAIL
            record["reasons"].append(f"光栅化失败：{error}")
            records.append(record)
            continue

        viewer_pixels = load_image(viewer_raster)
        desktop_pixels = load_image(desktop_raster)
        mask = _mask(record["text_boxes"], viewer_pixels.shape[:2])
        record["text_mask_fraction"] = float(mask.mean()) if mask.size else 0.0

        desktop = pixel_diff(viewer_pixels, desktop_pixels, mask)
        record["desktop"] = desktop
        if desktop["size_mismatch"]:
            record["status"] = FAIL
            record["reasons"].append(
                f"桌面尺寸不一致：viewer {viewer_pixels.shape[1]}×{viewer_pixels.shape[0]}"
            )
        else:
            if desktop["mean"] > MAX_MEAN:
                record["status"] = FAIL
                record["reasons"].append(f"桌面平均差异 {desktop['mean']:.3%} > {MAX_MEAN:.0%}")
            if desktop["over90"] > MAX_OVER90:
                record["status"] = FAIL
                record["reasons"].append(
                    f"桌面 >90/255 占比 {desktop['over90']:.3%} > {MAX_OVER90:.0%}"
                )

        if case.expected is not None:
            try:
                expected_raster = _rasterize_expected(case.expected, scratch / "expected.png")
            except (RasterError, SvgTextError) as error:
                record["status"] = FAIL
                record["reasons"].append(f"参考图光栅化失败：{error}")
                records.append(record)
                continue
            expected_pixels = load_image(expected_raster)
            expected = pixel_diff(viewer_pixels, expected_pixels, mask)
            record["expected"] = expected
            record["expected_kind"] = case.expected.suffix.lstrip(".")
            if expected["size_mismatch"]:
                record["status"] = FAIL
                record["reasons"].append(
                    f"参考尺寸不一致：viewer {viewer_pixels.shape[1]}×{viewer_pixels.shape[0]}"
                )
            else:
                expected_ok = expected["mean"] <= MAX_MEAN and expected["over4"] <= case.tolerance
                record["expected_ok"] = expected_ok
                if not expected_ok:
                    detail = (
                        f"参考平均差异 {expected['mean']:.3%} > {MAX_MEAN:.0%}"
                        if expected["mean"] > MAX_MEAN
                        else f"参考 >4/255 占比 {expected['over4']:.3%} > {case.tolerance:.2%}"
                    )
                    if case.known_gap:
                        # `ci = false`：case 自己登记的缺口（例如 panel 网格线未接），
                        # 桌面管线同样差这么多，不记在查看器头上。
                        record["known_gap"] = True
                        record["reasons"].append(f"已知缺口（ci=false）：{detail}")
                    else:
                        record["status"] = FAIL
                        record["reasons"].append(detail)
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def _pct(value: float) -> str:
    return f"{value:.3%}"


def _diff_cell(stats: dict[str, Any] | None) -> str:
    if stats is None:
        return "—"
    if stats.get("size_mismatch"):
        return "尺寸不一致"
    return f"{_pct(stats['mean'])} / {_pct(stats['over4'])} / {_pct(stats['over90'])}"


def _inventory(records: list[dict[str, Any]]) -> dict[str, Any]:
    """kind → 出现它的 case（报告 §2 的「覆盖表」）。"""
    kinds: dict[str, list[str]] = {}
    pch: Counter[int] = Counter()
    for record in records:
        for kind in record["ir_kinds"]:
            kinds.setdefault(kind, []).append(record["name"])
        pch.update(record.get("pch") or [])
    return {
        "kinds": {kind: sorted(names) for kind, names in sorted(kinds.items())},
        "pch": {str(key): value for key, value in sorted(pch.items())},
    }


def render_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# 查看器批量渲染报告（M1-16）",
        "",
        f"- 生成：{payload['generated_at']}",
        "- 查看器：`web/viewer`（`pixi run viewer:build`）",
        f"- 光栅器：`{payload['resvg']}`，两侧都 {payload['scale']}×"
        f"（1 pt = {payload['scale']} px）",
        f"- 阈值：平均差异 ≤ {MAX_MEAN:.0%}、单像素 > 90/255 占比 ≤ {MAX_OVER90:.0%}、",
        f"  单像素 > 4/255 占比 ≤ {MAX_OVER4:.0%}（case 的 `tolerance.png` 可收紧）；"
        "文字区域按 IR `text` 边界掩掉",
        "",
        "## 汇总",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 总数 | {summary['total']} |",
        f"| pass | {summary['pass']} |",
        f"| fail | {summary['fail']} |",
        f"| slow（> {SLOW_MS:.0f} ms） | {summary['slow']} |",
        f"| 已知缺口（`ci = false`） | {summary['known']} |",
        f"| `.wasm` 请求 | {payload['wasm_requests']} |",
        f"| 总耗时 | {summary['seconds']:.1f} s |",
        f"| 最慢三张 | {summary['slowest_text']} |",
        "",
    ]
    if payload.get("invalid"):
        lines += ["## invalid case（没进批量）", ""]
        for item in payload["invalid"]:
            lines.append(f"- `{item['name']}`：{'；'.join(item['reasons'])}")
        lines.append("")

    lines += [
        "## 逐张",
        "",
        "「与 expected」与「与桌面」都是 `mean / >4/255 / >90/255`（掩文字后）。",
        "",
        "| case | 组 | IR 节点 | 图元 | DOM | 加载 ms | 与 expected | 与桌面 | 结论 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for record in payload["cases"]:
        verdict = "✅ pass" if record["status"] == PASS else "❌ fail"
        slow = " ⏳" if record.get("slow") else ""
        lines.append(
            f"| `{record['name']}` | {record['group']} | {record['ir_nodes']} | "
            f"{record.get('leaves', '—')} | {record.get('dom_total', '—')} | "
            f"{record.get('load_ms', 0):.0f} | {_diff_cell(record.get('expected'))} | "
            f"{_diff_cell(record.get('desktop'))} | {verdict}{slow} |"
        )
    lines.append("")

    known = [record for record in payload["cases"] if record.get("known_gap")]
    if known:
        lines += [
            "## 已知缺口（与 expected 差，但 case 自己登记了 `ci = false`）",
            "",
            "这些差异在桌面管线同样存在（case 的 `meta.toml` 写明了阻塞项），"
            "查看器与桌面之间仍然判绿：",
            "",
        ]
        for record in known:
            lines.append(f"- `{record['name']}`：{'；'.join(record['reasons'])}")
        lines.append("")

    red = [record for record in payload["cases"] if record["status"] != PASS]
    if red:
        lines += ["## 红 case", ""]
        for record in red:
            lines.append(f"- `{record['name']}`：{'；'.join(record['reasons'])}")
        lines.append("")

    slow = [record for record in payload["cases"] if record.get("slow")]
    if slow:
        lines += ["## slow（> 5 s）", ""]
        for record in slow:
            lines.append(f"- `{record['name']}`：{record['load_ms']:.0f} ms")
        lines.append("")

    inventory = payload["inventory"]
    lines += ["## IR kind 覆盖（哪张真实 case 用到了它）", ""]
    for kind, names in inventory["kinds"].items():
        shown = "、".join(f"`{name}`" for name in names[:3])
        more = f" 等 {len(names)} 张" if len(names) > 3 else ""
        lines.append(f"- `{kind}`：{shown}{more}")
    lines += ["", "## pch 清单", ""]
    lines.append(
        "、".join(f"`{key}` × {value}" for key, value in inventory["pch"].items()) or "（无）"
    )
    lines.append("")
    return "\n".join(lines)


def _summary(records: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    slowest = sorted(records, key=lambda record: record.get("load_ms", 0), reverse=True)[:3]
    return {
        "total": len(records),
        "pass": sum(1 for record in records if record["status"] == PASS),
        "fail": sum(1 for record in records if record["status"] != PASS),
        "slow": sum(1 for record in records if record.get("slow")),
        "known": sum(1 for record in records if record.get("known_gap")),
        "seconds": seconds,
        "slowest": [
            {"case": record["name"], "load_ms": record.get("load_ms", 0)} for record in slowest
        ],
        "slowest_text": "、".join(
            f"`{record['name']}` {record.get('load_ms', 0):.0f} ms" for record in slowest
        ),
    }


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="viewer:cases")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="产物目录（不入库）")
    parser.add_argument(
        "--only",
        default="",
        help="只跑这些 case（逗号分隔；冒烟用）",
    )
    parser.add_argument(
        "--group",
        choices=("all", "cases", "grob"),
        default="all",
        help="三文件 case / grob 快照 / 两者（默认）",
    )
    parser.add_argument("--no-legacy", action="store_true", help="等价 --group cases")
    parser.add_argument("--json", action="store_true", help="把报告 JSON 打到 stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    started = time.perf_counter()
    # fontconfig / libGL 的搜索路径要在造 skia 场景之前设好（grob 快照的度量走 skia）。
    playwright_env.configure()
    three_file, invalid = _three_file_cases(CASES_DIR)
    legacy = _grob_cases(CASES_DIR) if args.group in ("all", "grob") and not args.no_legacy else []
    cases = (three_file if args.group in ("all", "cases") else []) + legacy
    cases = _filter(cases, args.only.split(",") if args.only else [])
    if not cases:
        raise SystemExit("没有可跑的 case")

    args.out.mkdir(parents=True, exist_ok=True)
    playwright_env.configure()
    from playwright.sync_api import sync_playwright

    with ViewerServer() as url:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(device_scale_factor=SCALE)
            requests: list[str] = []
            page.on("request", lambda request: requests.append(request.url))
            page.goto(f"{url}/index.html")
            page.wait_for_selector("#file")
            try:
                records = run_cases(cases, out=args.out, page=page, requests=requests)
            finally:
                browser.close()

    seconds = time.perf_counter() - started
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "resvg": resvg_version(),
        "scale": SCALE,
        "thresholds": {"mean": MAX_MEAN, "over90": MAX_OVER90, "over4": MAX_OVER4},
        "summary": _summary(records, seconds),
        "wasm_requests": sum(1 for url in requests if ".wasm" in url),
        "inventory": _inventory(records),
        "invalid": invalid,
        "cases": records,
    }
    (args.out / REPORT_MD).write_text(render_report(payload), encoding="utf-8")
    (args.out / REPORT_JSON).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = payload["summary"]
    print(
        f"{summary['pass']}/{summary['total']} pass，{summary['fail']} fail，"
        f"{summary['slow']} slow，{summary['seconds']:.1f}s → {args.out / REPORT_MD}"
    )
    if args.json:
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0 if summary["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
