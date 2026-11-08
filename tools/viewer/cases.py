#!/usr/bin/env python
"""M1-16：把案例库逐条过一遍浏览器查看器，并与 `expected.svg` 像素对拍。

    pixi run viewer:cases                 # 全部 ci = true 的 case，全量
    pixi run viewer:cases --sample 12     # CI：风险组全量 + 按族轮转 12 条
    pixi run viewer:cases --case geom-col-basic
    pixi run viewer:cases --include-skipped

一条 case 的链路：

    plot.py → ggcore.plotspec → IR(.ggir.cbor) → Playwright/Chromium 里的
    web/viewer/index.html → 取回渲染后的 DOM SVG → ggdiff（<text>→轮廓、resvg
    --dpi 72、图级 ≤2% / 均值 ≤1%）→ 报告 + gallery.html

为什么 diff 不直接比 Chromium 截图：参考图是 R svglite 的 SVG，两侧必须经过
**同一个光栅器**（`docs/notes/diff.md` §2）。所以 viewer 渲染出的 SVG 被取回后，
和 `expected.svg` 一样走 resvg；Chromium 截图只用于 gallery 缩略图。

**这个任务负责验证，不是「看图」**：它必须有 Chromium。只想静态浏览整本案例库
（不装浏览器自动化）用 `pixi run viewer:gallery && pixi run viewer:serve`
（见 `docs/notes/gallery.md`），那条产线只把 IR 和 `expected.svg` 摆成画廊，
不做像素对拍。

产物（都不入库）：

    .viewer-cases/<case>/<case>.ggir.cbor   # 送进浏览器的 IR
    .viewer-cases/<case>/viewer.svg         # 浏览器渲染后的 DOM SVG
    .viewer-cases/<case>/viewer.png         # Chromium 截图（缩略图）
    .viewer-cases/report.md / report.json   # 汇总
    web/viewer/dist/gallery.html + dist/gallery/  # 可点进去 hover 的 gallery
"""

# gallery.html 的 CSS 是内联的（单文件、零依赖），长行是有意的。
# ruff: noqa: E501

from __future__ import annotations

import argparse
import functools
import http.server
import importlib.util
import json
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CASES = REPO / "docs" / "cases"
VIEWER = REPO / "web" / "viewer"
DIST = VIEWER / "dist"
OUT_DIR = REPO / ".viewer-cases"
GALLERY = DIST / "gallery.html"

# 缺浏览器时的报错（SIL-893）。`viewer:cases` 是**验证**任务：没有 Chromium 就
# 不能静默降级成「只生成 gallery」——那看起来像验证过了。所以这里说清职责、
# 指路静态浏览，并把 playwright / Chromium 的原始报错接在后面（定位装浏览器那一步）。
_NO_BROWSER_HINT = (
    "没有可用 Chromium。这是**验证**任务——每条 case 都要在 Chromium 里渲染、取回 "
    "DOM SVG，再与 expected.svg 做像素对拍；缺浏览器时它不会降级成「只生成 gallery」。\n"
    "  要跑验证：`pixi run viewer:browsers`（把 Chromium 装进 .playwright-browsers/）后重跑\n"
    "  只想静态看图：`pixi run viewer:gallery` 然后 `pixi run viewer:serve`\n"
    "原始报错："
)

sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools" / "viewer"))

import gallery_html  # noqa: E402
import playwright_env  # noqa: E402

from ggcore import ir  # noqa: E402
from ggcore.plotspec import build_scene, load_plot  # noqa: E402
from ggdiff.compare import DEFAULT_MAX_FRACTION, DEFAULT_MAX_MEAN, compare_images  # noqa: E402
from ggdiff.image import load_image  # noqa: E402
from ggdiff.raster import rasterize_svg  # noqa: E402
from ggdiff.svgimage import snap_pixelated_images  # noqa: E402
from ggdiff.svgtext import inline_text_paths  # noqa: E402
from ggskia.text import ShaperMetrics, TextShaper  # noqa: E402

PASS = "pass"
FAIL = "fail"
ERROR = "error"
SKIP = "skip"
RED = {FAIL, ERROR}

# ci = false 的 case：参考图能生成，但实现侧有缺口时在这里点名解释，不把它们
# 算成 viewer 的缺口。SIL-723 修掉 theme 网格线与 colourbar 取色后这里已空；
# 之后再有缺口按同样的格式登记。
IMPLEMENTATION_GAPS: dict[str, str] = {}


def _load_matrix_module():
    """复用 `tools/cases/matrix.py` 的 case 发现与契约校验，不复制第二份。"""
    path = REPO / "tools" / "cases" / "matrix.py"
    spec = importlib.util.spec_from_file_location("gg4py_case_matrix", path)
    if spec is None or spec.loader is None:  # pragma: no cover - 文件不可读时才发生
        raise RuntimeError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class Result:
    """一条 case 的浏览器渲染 + 像素对拍结果。"""

    case: str
    family: str
    status: str
    elements: int = 0
    nodes: int = 0
    diff: float | None = None
    mean: float | None = None
    tolerance: float = DEFAULT_MAX_FRACTION
    detail: str = ""
    kinds: dict[str, int] = field(default_factory=dict)
    thumbnail: str | None = None
    ir_path: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == PASS

    @property
    def gap(self) -> str:
        if self.status == SKIP:
            return IMPLEMENTATION_GAPS.get(self.case, "ci = false，按案例库约定跳过")
        if self.case in IMPLEMENTATION_GAPS:
            return f"实现缺口：{IMPLEMENTATION_GAPS[self.case]}"
        if self.status in RED:
            return "viewer 缺口"
        return ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "family": self.family,
            "status": self.status,
            "elements": self.elements,
            "nodes": self.nodes,
            "image_diff_fraction": self.diff,
            "mean_diff": self.mean,
            "tolerance": self.tolerance,
            "detail": self.detail,
            "gap": self.gap,
            "kinds": self.kinds,
            "thumbnail": self.thumbnail,
            "ir": self.ir_path,
        }


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


class ViewerServer:
    """`web/viewer/` 的静态服务器（`file://` 会拦 ES module）。"""

    def __enter__(self) -> str:
        handler = functools.partial(_QuietHandler, directory=str(VIEWER))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _relative(path: Path) -> str:
    """仓库内给相对路径，临时目录（测试用）给绝对路径。"""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _count_kinds(scene: ir.Scene) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in ir.walk(scene.root):
        kind = node.kind.value
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _scene_for(case_dir: Path, metrics: ShaperMetrics) -> ir.Scene:
    return build_scene(load_plot(case_dir), metrics=metrics)


def _serialize_viewer_svg(page) -> dict[str, Any]:
    """取回 viewer 的 DOM SVG，并补一块白底。

    `index.html` 用 CSS 给 `svg` 白底；SVG 被单独拿出来交给 resvg 时 CSS 不在，
    透明底会和参考图的白底整片判红。这里加白底只影响对拍，不改 viewer 的代码。
    """
    return page.evaluate(
        """() => {
          const svg = document.querySelector('#stage svg.gg-svg');
          if (svg === null) return null;
          const clone = svg.cloneNode(true);
          clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
          clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
          const viewBox = (clone.getAttribute('viewBox') || '0 0 0 0')
            .trim().split(/\\s+/).map(Number);
          const background = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          background.setAttribute('x', String(viewBox[0] || 0));
          background.setAttribute('y', String(viewBox[1] || 0));
          background.setAttribute('width', String(viewBox[2] || 0));
          background.setAttribute('height', String(viewBox[3] || 0));
          background.setAttribute('fill', '#ffffff');
          const defs = clone.querySelector('defs');
          if (defs !== null) defs.after(background);
          else clone.prepend(background);
          return {
            markup: new XMLSerializer().serializeToString(clone),
            width: viewBox[2] || 0,
            height: viewBox[3] || 0,
          };
        }"""
    )


def _diff(
    expected: Path,
    actual_svg: Path,
    *,
    tolerance: float,
    shaper: TextShaper,
    scratch: Path,
) -> tuple[float, float, str]:
    """两侧都走 inline_text_paths + snap_pixelated_images → resvg → 像素 diff。"""
    reference_svg = scratch / "reference.svg"
    actual_outlined = scratch / "actual.svg"
    if expected.suffix.lower() == ".png":
        reference_png = expected
    else:
        inline_text_paths(expected, reference_svg, shaper=shaper)
        snap_pixelated_images(reference_svg)
        reference_png = rasterize_svg(
            reference_svg, scratch / "reference.png", dpi=72, background="#ffffff"
        )
    inline_text_paths(actual_svg, actual_outlined, shaper=shaper)
    snap_pixelated_images(actual_outlined)
    actual_png = rasterize_svg(
        actual_outlined, scratch / "actual.png", dpi=72, background="#ffffff"
    )
    result, _mask, _amount = compare_images(
        load_image(reference_png),
        load_image(actual_png),
        max_fraction=tolerance,
        max_mean=DEFAULT_MAX_MEAN,
    )
    return result.image_diff_fraction, result.mean_diff, result.reason


def _run_in_browser(
    page,
    case,
    *,
    out_dir: Path,
    metrics: ShaperMetrics,
    shaper: TextShaper,
    screenshot: bool,
    diff_enabled: bool,
) -> Result:
    result = Result(case=case.name, family=case.family, status=ERROR)
    case_out = out_dir / case.name
    case_out.mkdir(parents=True, exist_ok=True)
    tolerance = case.png_tolerance
    if tolerance is None:
        tolerance = DEFAULT_MAX_FRACTION
    result.tolerance = float(tolerance)

    try:
        scene = _scene_for(case.directory, metrics)
        result.kinds = _count_kinds(scene)
        cbor = case_out / f"{case.name}.ggir.cbor"
        cbor.write_bytes(ir.encode(scene))
        result.ir_path = _relative(cbor)

        # 上一条 case 的 `ok` 会让 wait_for_selector 立刻返回；先清掉状态。
        page.evaluate(
            "() => { const s = document.querySelector('#status');"
            " s.dataset.state = 'pending'; s.textContent = '加载中…'; }"
        )
        page.set_input_files("#file", str(cbor))
        page.wait_for_selector("#status[data-state='ok']", timeout=20_000)

        state = page.evaluate("() => window.ggViewer.state()")
        result.elements = int(state["leaves"])
        result.nodes = int(state["nodes"])

        payload = _serialize_viewer_svg(page)
        if payload is None:
            result.detail = "viewer 没有产出 svg.gg-svg"
            return result
        svg_path = case_out / "viewer.svg"
        svg_path.write_text(payload["markup"], encoding="utf-8")

        if screenshot:
            png_path = case_out / "viewer.png"
            page.locator("#stage svg.gg-svg").screenshot(path=str(png_path))
            result.thumbnail = _relative(png_path)

        if not diff_enabled:
            # ci = false 的 case 仍进浏览器与 gallery（覆盖与 M1-13 的“所有 IR 都能
            # 打开”是同一条验收），但不参与红绿；实现侧的缺口由 M2 修。
            result.status = SKIP
            result.detail = IMPLEMENTATION_GAPS.get(case.name, "ci = false，按案例库约定不判红")
            return result

        with tempfile.TemporaryDirectory(prefix=f"viewer-{case.name}-") as name:
            diff, mean, reason = _diff(
                case.directory / case.expected,
                svg_path,
                tolerance=result.tolerance,
                shaper=shaper,
                scratch=Path(name),
            )
        result.diff = diff
        result.mean = mean
        if diff > result.tolerance or mean > DEFAULT_MAX_MEAN:
            result.status = FAIL
            result.detail = reason or "超容差"
        else:
            result.status = PASS
    except Exception as error:
        # 浏览器/解码侧的异常都折成 ERROR，报告里带 traceback 的首行。
        result.status = ERROR
        result.detail = f"{type(error).__name__}: {error}".splitlines()[0][:400]
    return result


def _always_sampled(case) -> bool:
    """CI 抽样必须**全量**跑的风险组（SIL-867）。

    族轮转按族名字母序走，12 条名额在 `guide`（92 条）/ `matrix`（51 条）两个大族
    就吃满了：`geom-raster`（第 9 个族）与 `matrix-report-*`（`matrix` 族里排最后）
    永远轮不到，于是 13 条 raster 的 `<image>` 回归与 report 档的容差接线整个被抽样
    掩盖——`viewer:cases:ci` 一路绿，全量一跑 13 条红。两组都便宜（13 + 3 条，
    实测约 8 秒），所以不挑代表，直接全量。
    """
    return getattr(case, "family", "") == "geom-raster" or getattr(case, "band", None) is not None


def _select_sample(cases: list, limit: int) -> list:
    """风险组（`_always_sampled`）全量 + 族轮转 `limit` 条：每族先出一条，再第二轮。"""
    always = sorted((case for case in cases if _always_sampled(case)), key=lambda c: c.name)
    groups: dict[str, list] = {}
    for case in cases:
        if _always_sampled(case):
            continue
        groups.setdefault(case.family or "（未登记）", []).append(case)
    for bucket in groups.values():
        bucket.sort(key=lambda item: item.name)
    ordered: list = list(always)
    picked = 0
    while picked < limit and any(groups.values()):
        for family in sorted(groups):
            if not groups[family]:
                continue
            ordered.append(groups[family].pop(0))
            picked += 1
            if picked >= limit:
                break
    return ordered


def _fmt_percent(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "—"


def _status_glyph(status: str) -> str:
    return {PASS: "✅", FAIL: "❌", ERROR: "⛔", SKIP: "⏭"}.get(status, status)


def render_report(
    results: list[Result],
    *,
    now: str,
    wasm_requests: list[str],
    expected_count: int,
) -> str:
    counts = {
        status: sum(1 for item in results if item.status == status)
        for status in (PASS, FAIL, ERROR, SKIP)
    }
    lines = [
        "# 浏览器查看器 × 案例库",
        "",
        f"- 时间：{now}",
        f"- 结论：pass {counts[PASS]} / fail {counts[FAIL]} / error {counts[ERROR]} / skip {counts[SKIP]}"
        f"（本轮 {len(results)} 条，案例库 ci = true 共 {expected_count} 条）",
        f"- 零 wasm：{'是' if not wasm_requests else '否，请求了 ' + ', '.join(wasm_requests[:3])}",
        "- 判据：`expected.svg` 与 viewer 的 DOM SVG 都走 resvg --dpi 72；"
        "图级差异 ≤ 各 case 的 `tolerance.png`（没写就取 `meta.toml` 的 `band` 档位上限，"
        f"`report` → 5%；两者都没有按缺省 {DEFAULT_MAX_FRACTION:.0%}）、"
        f"平均差异 ≤ {DEFAULT_MAX_MEAN:.0%}。",
        "",
        "| case | 族 | 元素 | 图级差异 | 平均差异 | 结论 |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for item in results:
        lines.append(
            f"| `{item.case}` | `{item.family}` | {item.elements} | {_fmt_percent(item.diff)} "
            f"| {_fmt_percent(item.mean)} | {_status_glyph(item.status)} {item.status} |"
        )
    lines.append("")
    problem = [item for item in results if item.status in RED or item.status == SKIP]
    if problem:
        lines.extend(
            ["## 未过 / 跳过", "", "| case | 结论 | 缺口 | 说明 |", "| --- | --- | --- | --- |"]
        )
        for item in problem:
            lines.append(
                f"| `{item.case}` | {_status_glyph(item.status)} {item.status} | {item.gap} | {item.detail or '—'} |"
            )
        lines.append("")
    else:
        lines.extend(["全部通过。", ""])
    lines.extend(
        [
            "## 产物",
            "",
            "- 每条 case：`.viewer-cases/<case>/<case>.ggir.cbor`、`viewer.svg`、`viewer.png`",
            "- Gallery：`web/viewer/dist/gallery.html`（点卡片进 viewer，可 hover / 开关图例）",
            "- 复现：`pixi run viewer:build && pixi run viewer:browsers && pixi run viewer:cases`",
            "",
        ]
    )
    return "\n".join(lines)


def write_gallery(results: list[Result], gallery: Path, out_dir: Path, now: str) -> None:
    """把本轮结果写成 `gallery.html`（HTML 本体在 `gallery_html` 里，静态 gallery 共用）。

    `out_dir` 保留在签名里：历史调用方按「产物目录」传参，卡片资产的实际去处由
    `gallery_html.gallery_assets_dir()` 按 gallery.html 的位置决定。
    """
    del out_dir
    cards = [
        gallery_html.Card(
            case=item.case,
            family=item.family,
            status=item.status,
            elements=item.elements,
            diff=item.diff,
            mean=item.mean,
            detail=item.detail,
            thumbnail=REPO / item.thumbnail if item.thumbnail is not None else None,
            ir_path=REPO / item.ir_path if item.ir_path is not None else None,
            suffix=".png",
        )
        for item in results
    ]
    counts = {
        status: sum(1 for item in results if item.status == status)
        for status in (PASS, FAIL, ERROR, SKIP)
    }
    lede = (
        f"{now} · pass {counts[PASS]} / fail {counts[FAIL]} / error {counts[ERROR]} "
        f"/ skip {counts[SKIP]}。点缩略图进入 viewer，鼠标悬停看图元 tooltip，"
        "点图例 key 开关图例。"
    )
    gallery_html.write_gallery(cards, gallery, now, lede=lede)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="viewer:cases",
        description="逐条渲染 docs/cases，用浏览器查看器出 SVG，再与 expected.svg 像素对拍。",
    )
    parser.add_argument("--root", type=Path, default=CASES, help="案例根目录（默认 docs/cases）")
    parser.add_argument("--case", action="append", dest="cases", help="只跑这个 case（可重复）")
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="CI 用：风险组（geom-raster 全族 + 声明了 band 的 case）全量 + 按族轮转 N 条",
    )
    parser.add_argument(
        "--include-skipped",
        action="store_true",
        help="连 ci = false 的 case 一起跑（默认按案例库约定跳过）",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="产物目录（默认 .viewer-cases）")
    parser.add_argument("--gallery", type=Path, default=GALLERY, help="gallery.html 路径")
    parser.add_argument("--no-screenshot", action="store_true", help="只出 SVG，不截缩略图")
    parser.add_argument(
        "--min-pass",
        type=int,
        default=0,
        help="通过数低于这个值时退出 1（CI 用；默认只要求没有红 case）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (DIST / "main.js").is_file():
        print(
            "viewer:cases: web/viewer/dist/main.js 不存在，先跑 `pixi run viewer:build`",
            file=sys.stderr,
        )
        return 2

    matrix = _load_matrix_module()
    discovered = matrix.discover(args.root)
    if args.cases:
        wanted = set(args.cases)
        discovered = [case for case in discovered if case.name in wanted]
        missing = wanted - {case.name for case in discovered}
        for name in sorted(missing):
            print(f"viewer:cases: no case named {name!r}", file=sys.stderr)

    valid_cases = [case for case in discovered if case.valid]
    if args.sample is not None:
        runnable = _select_sample([case for case in valid_cases if case.ci], max(args.sample, 0))
    else:
        runnable = list(valid_cases)
    runnable.sort(key=lambda case: case.name)
    ci_total = sum(1 for case in discovered if case.valid and case.ci)

    results: list[Result] = []

    metrics = ShaperMetrics()
    shaper = TextShaper(emoji="outline")
    wasm_requests: list[str] = []
    playwright_env.configure()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - dev 环境才有 playwright
        print(f"viewer:cases: {_NO_BROWSER_HINT}", file=sys.stderr)
        return 2

    with ViewerServer() as url, sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - 只在没装浏览器时命中
            print(f"viewer:cases: {_NO_BROWSER_HINT}\n\n{error}", file=sys.stderr)
            return 2
        page = browser.new_page(viewport={"width": 1000, "height": 800}, device_scale_factor=1)
        page.on(
            "request",
            lambda request: wasm_requests.append(request.url) if ".wasm" in request.url else None,
        )
        page.goto(f"{url}/index.html")
        page.wait_for_selector("#file")
        try:
            for case in runnable:
                result = _run_in_browser(
                    page,
                    case,
                    out_dir=args.out,
                    metrics=metrics,
                    shaper=shaper,
                    screenshot=not args.no_screenshot,
                    diff_enabled=args.include_skipped or case.ci,
                )
                results.append(result)
                print(
                    f"{_status_glyph(result.status)} {result.case}: "
                    f"{result.elements} elements, diff {_fmt_percent(result.diff)} "
                    f"/ mean {_fmt_percent(result.mean)}"
                    + (f" — {result.detail}" if result.detail else ""),
                    flush=True,
                )
        finally:
            browser.close()

    results.sort(key=lambda item: item.case)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.out.mkdir(parents=True, exist_ok=True)
    report = render_report(results, now=now, wasm_requests=wasm_requests, expected_count=ci_total)
    (args.out / "report.md").write_text(report, encoding="utf-8")
    (args.out / "report.json").write_text(
        json.dumps(
            {
                "generated_at": now,
                "wasm_requests": wasm_requests,
                "counts": {
                    status: sum(1 for item in results if item.status == status)
                    for status in (PASS, FAIL, ERROR, SKIP)
                },
                "cases": [item.as_dict() for item in results],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_gallery(results, args.gallery, args.out, now)

    counts = {
        status: sum(1 for item in results if item.status == status)
        for status in (PASS, FAIL, ERROR, SKIP)
    }
    print(
        f"viewer:cases: {len(results)} case(s) — pass {counts[PASS]}, fail {counts[FAIL]}, "
        f"error {counts[ERROR]}, skip {counts[SKIP]} — report {args.out / 'report.md'}"
    )
    if wasm_requests:
        print(f"viewer:cases: 发现 wasm 请求：{wasm_requests[:3]}", file=sys.stderr)
    red = counts[FAIL] + counts[ERROR]
    if counts[PASS] < args.min_pass:
        print(
            f"viewer:cases: 通过 {counts[PASS]} < --min-pass {args.min_pass}",
            file=sys.stderr,
        )
        return 1
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
