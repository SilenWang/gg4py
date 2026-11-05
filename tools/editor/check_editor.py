#!/usr/bin/env python
"""SIL-826 · 浏览器代码编辑器的端到端验收（`pixi run editor:check`）。

页面是 `web/editor/index.html`：CodeMirror 编辑一段 Python，Pyodide worker 用
`ggcore.script.run_script` 执行，IR 用 `web/viewer` 的 TS 渲染器画成 DOM SVG。
这里在真 Chromium 里把它当产品验收，逐条对应 issue：

| 验收项 | 怎么判 |
| --- | --- |
| 写 `import ggcore` 的代码能出图 | 默认示例自动出图；示例库逐个跑通（9 个） |
| 改一行重跑 ≤ 2 s（warm） | 改标题后重跑，页面记的 `timings.last.total_ms` ≤ 2000 |
| 错误给 Python traceback，不白屏 | 运行时错误 + 语法错误各一次：`#traceback` 有用户行号，图保留 |
| 导出的 PNG 与屏幕所见一致 | 1× / 2×（DPR=2）导出的 PNG 与屏幕截图**逐像素**相同（RGBA 全等） |
| 同一脚本两端 IR 逐字节相同 | 9 个示例在 CPython 侧跑同一份 `run_script`，sha256 必须相同 |
| 静态页面 + 本地资产，无后端无账号 | 只放行本站请求；站外请求记红 |
| 代码留在 localStorage | 改一行 → 重载 → 编辑器里还是那一行 |
| 导出 SVG / PNG（1×/2×/4×，可给 DPI）/ JPG | 尺寸 = round(pt × 倍数)、DPI 等价、质量改变字节数 |

浏览器与资产不在时直接失败并说明先跑什么。产物（截图 + report.json）进
`.editor-check/`，不入库。
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
EDITOR = REPO / "web" / "editor"
EXAMPLES = EDITOR / "examples"
RUNTIME_VENDOR = REPO / "web" / "runtime" / "vendor"
VIEWER = REPO / "web" / "viewer"
OUT = REPO / ".editor-check"

#: 「改一行重跑」的预算（issue 的验收口径，warm = 运行时与 numpy 已经在内存里）。
WARM_BUDGET_MS = 2000.0
#: 像素对比允许的差异像素数：口径是**逐像素相同**，所以默认 0。
PIXEL_TOLERANCE = 0


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # 先注册再执行：`@dataclass` 会按 `cls.__module__` 去 `sys.modules` 里找自己。
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def require_build() -> None:
    missing = [
        str(path.relative_to(REPO))
        for path in (
            RUNTIME_VENDOR / "manifest.json",
            RUNTIME_VENDOR / "gg4py.tar",
            VIEWER / "dist" / "render.js",
            EDITOR / "dist" / "editor.js",
            EXAMPLES / "index.json",
        )
        if not path.exists()
    ]
    if missing:
        raise SystemExit(
            "editor:check 缺少产物：" + ", ".join(missing) + "\n  先跑 `pixi run editor:build`"
        )


def example_entries() -> list[dict[str, Any]]:
    return json.loads((EXAMPLES / "index.json").read_text(encoding="utf-8"))["examples"]


def desktop_digests() -> dict[str, dict[str, Any]]:
    """9 个示例在 CPython 上跑 SEQUENCE 的 IR 摘要（与浏览器侧比字节）。"""
    sys.path.insert(0, str(REPO / "src"))
    from ggcore.script import run_script

    warnings.simplefilter("ignore")
    out: dict[str, dict[str, Any]] = {}
    for entry in example_entries():
        name = entry["name"]
        source = (EXAMPLES / f"{name}.py").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            data = entry.get("data")
            if data and data.get("mode") == "csv":
                (Path(tmp) / "data.csv").write_text(data["text"], encoding="utf-8")
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                result = run_script(source, filename=f"{name}.py")
            finally:
                os.chdir(previous)
        out[name] = {
            "digest": result.meta["digest"],
            "bytes": result.meta["bytes"],
            "nodes": result.meta["nodes"],
            "needs": result.meta["needs"],
        }
    return out


# ---------------------------------------------------------------------------
# 页面交互
# ---------------------------------------------------------------------------


def page_state(page) -> dict[str, Any]:
    return page.evaluate("() => window.__ggEditor.state()")


def wait_ready(page, timeout: float = 300_000.0) -> None:
    page.wait_for_function(
        """() => {
             const editor = window.__ggEditor;
             if (!editor) return false;
             const state = editor.state();
             if (state.error && state.meta === null) {
               throw new Error(`页面报错：${state.error.message}`);
             }
             return state.ready === true;
           }""",
        timeout=timeout,
    )


def wait_plot(page, timeout: float = 300_000.0) -> None:
    page.wait_for_function(
        """() => {
             const editor = window.__ggEditor;
             return Boolean(editor) && editor.state().meta !== null;
           }""",
        timeout=timeout,
    )


def svg_stats(page) -> dict[str, Any] | None:
    return page.evaluate(
        """() => {
             const svg = document.querySelector("#stage-area svg.gg-svg");
             if (svg === null) return null;
             const box = svg.getBoundingClientRect();
             return {
               elements: svg.querySelectorAll("*").length,
               texts: svg.querySelectorAll("text").length,
               width: box.width,
               height: box.height,
               data_size: svg.getAttribute("data-size"),
               stale: svg.dataset.stale === "true",
             };
           }"""
    )


def run_example(page, name: str) -> dict[str, Any]:
    page.evaluate("(name) => window.__ggEditor.selectExample(name)", name)
    record = page.evaluate("() => window.__ggEditor.run()")
    return record if isinstance(record, dict) else {}


def export_record(page, fmt: str, **options: Any) -> dict[str, Any]:
    return page.evaluate(
        "([fmt, options]) => window.__ggEditor.export(fmt, options)", [fmt, options]
    )


def decode_png(b64: str):
    from PIL import Image

    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")


# ---------------------------------------------------------------------------
# 各项断言
# ---------------------------------------------------------------------------


def check_editor_ui(page, problems: list[str]) -> dict[str, Any]:
    stats = page.evaluate(
        """() => {
             const host = document.querySelector("#editor-host");
             const lines = host.querySelectorAll(".cm-line");
             const tokens = host.querySelectorAll(".cm-content span");
             return {
               mounted: host.querySelector(".cm-editor") !== null,
               lines: lines.length,
               tokens: tokens.length,
               first_line: lines.length > 0 ? lines[0].textContent : "",
             };
           }"""
    )
    if not stats["mounted"]:
        problems.append("编辑器没有挂载（#editor-host 里没有 .cm-editor）")
    if stats["lines"] < 5:
        problems.append(f"编辑器只有 {stats['lines']} 行（示例至少十几行）")
    # Python 高亮：CodeMirror 把 token 包进 span；纯 textarea 不会有这些节点。
    if stats["tokens"] < 10:
        problems.append(f"没有看到 Python 高亮的 token（{stats['tokens']} 个 span）")
    return stats


def check_first_plot(page, problems: list[str]) -> dict[str, Any]:
    stats = svg_stats(page)
    state = page_state(page)
    if stats is None:
        problems.append("首次出图后 #stage-area 里没有 svg.gg-svg")
        return {}
    if stats["elements"] < 10:
        problems.append(f"SVG 只有 {stats['elements']} 个元素，像是空图")
    meta = state.get("meta") or {}
    expected_w = round(float(meta.get("width_in", 0)) * 72)
    expected_h = round(float(meta.get("height_in", 0)) * 72)
    if abs(stats["width"] - expected_w) > 0.5 or abs(stats["height"] - expected_h) > 0.5:
        problems.append(
            f"屏幕上的 SVG 是 {stats['width']}×{stats['height']} px，"
            f"IR 尺寸是 {expected_w}×{expected_h} pt（应当 1 pt = 1 px）"
        )
    return {"svg": stats, "meta": meta}


def check_warm_rerun(page, source: str, problems: list[str]) -> dict[str, Any]:
    edited = source.replace('title="Hello, gg4py"', 'title="Hello, again"')
    if edited == source:
        edited = source + "\n# edit\n"
    page.evaluate("(text) => window.__ggEditor.setSource(text)", edited)
    started = time.perf_counter()
    record = run_example(page, page_state(page)["example"])
    wall_ms = (time.perf_counter() - started) * 1000.0
    state = page_state(page)
    last = state.get("timings", {}).get("last") or {}
    total_ms = last.get("total_ms")
    if record.get("error"):
        problems.append(f"warm 重跑失败：{record['error']}")
    if total_ms is None:
        problems.append("warm 重跑没有记下耗时")
    elif total_ms > WARM_BUDGET_MS:
        problems.append(f"warm 重跑 {total_ms:.0f} ms > {WARM_BUDGET_MS:.0f} ms")
    if svg_stats(page) is None:
        problems.append("warm 重跑后没有图")
    return {
        "total_ms": total_ms,
        "wall_ms": wall_ms,
        "record": {k: record.get(k) for k in ("run_ms", "worker_ms", "render_ms")},
    }


def check_error_paths(page, source: str, problems: list[str]) -> dict[str, Any]:
    broken = (
        "from ggcore.plot import aes, geom_point, ggplot\n"
        "from ggio.frame import to_column_table\n"
        "\n"
        "def build():\n"
        "    table = to_column_table({'x': [1.0], 'y': [2.0]})\n"
        "    return 1 / 0\n"
    )
    page.evaluate("(text) => window.__ggEditor.setSource(text)", broken)
    record = run_example(page, page_state(page)["example"])
    traceback = page.inner_text("#traceback")
    state = page_state(page)
    details = {"runtime": {"record": record.get("error"), "traceback": traceback}}
    if not record.get("error"):
        problems.append("故意除零的脚本没有报错")
    if "Traceback (most recent call last)" not in traceback:
        problems.append("错误时 #traceback 里没有 Python traceback")
    if "ZeroDivisionError" not in traceback:
        problems.append("traceback 里没有 ZeroDivisionError")
    if "line 6" not in traceback:
        problems.append("traceback 里没有用户代码的行号（line 6）")
    if state.get("meta") is None:
        problems.append("错误后上一张图被清掉了（应当保留并置灰）")
    if svg_stats(page) is None:
        problems.append("错误后页面白屏（没有上一张图）")

    syntax = "def build(:\n    return None\n"
    page.evaluate("(text) => window.__ggEditor.setSource(text)", syntax)
    record = run_example(page, page_state(page)["example"])
    traceback = page.inner_text("#traceback")
    details["syntax"] = {"record": record.get("error"), "traceback": traceback}
    if "SyntaxError" not in traceback:
        problems.append("语法错误没有回显 SyntaxError")

    page.evaluate("(text) => window.__ggEditor.setSource(text)", source)
    return details


def check_examples(
    page, expected: dict[str, dict[str, Any]], problems: list[str]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for entry in example_entries():
        name = entry["name"]
        record = run_example(page, name)
        state = page_state(page)
        meta = state.get("meta") or {}
        stats = svg_stats(page)
        item = {
            "error": record.get("error"),
            "digest": meta.get("digest"),
            "bytes": meta.get("bytes"),
            "nodes": meta.get("nodes"),
            "total_ms": (state.get("timings", {}).get("last") or {}).get("total_ms"),
            "svg": stats,
            "needs": meta.get("needs"),
        }
        out[name] = item
        if record.get("error"):
            problems.append(f"示例 {name} 跑失败：{record['error']}")
            continue
        if stats is None or stats["elements"] < 5:
            problems.append(f"示例 {name} 没有画出图（svg={stats}）")
        want = expected.get(name)
        if want is None:
            problems.append(f"示例 {name} 在桌面侧没有摘要")
        elif meta.get("digest") != want["digest"]:
            problems.append(
                f"示例 {name} 两端 IR 不一致：浏览器 {str(meta.get('digest'))[:12]} "
                f"vs 桌面 {want['digest'][:12]}"
            )
        elif meta.get("bytes") != want["bytes"]:
            problems.append(f"示例 {name} 的 IR 字节数不同：{meta.get('bytes')} vs {want['bytes']}")
    return out


def diff_pixels(left, right) -> tuple[int, Any]:
    """两张 RGBA 图的差异：返回（有差异的通道值个数, bbox）。"""
    from PIL import ImageChops

    diff = ImageChops.difference(left, right)
    bbox = diff.getbbox()
    if bbox is None:
        return 0, None
    histogram = diff.histogram()
    # 每个通道 256 个桶；非零桶的像素数就是「有任何差异」的像素数。
    differing = sum(
        histogram[channel * 256 + value] for channel in range(4) for value in range(1, 256)
    )
    return differing, bbox


def check_exports(page, problems: list[str]) -> dict[str, Any]:
    state = page_state(page)
    meta = state.get("meta") or {}
    width_pt = meta.get("width_in", 5.0) * 72
    height_pt = meta.get("height_in", 3.5) * 72
    out: dict[str, Any] = {"screen": svg_stats(page)}

    # 1× PNG 与屏幕所见逐像素相同。
    from PIL import Image

    shot = page.locator("#stage-area svg.gg-svg").screenshot(omit_background=True)
    record = export_record(page, "png", scale=1)
    exported = decode_png(record["base64"])
    screen = Image.open(io.BytesIO(shot)).convert("RGBA")
    out["png_1x"] = {
        "screen": list(screen.size),
        "export": list(exported.size),
        "bytes": record["bytes"],
        "dpi": record["dpi"],
    }
    if screen.size != exported.size:
        problems.append(f"1× PNG 尺寸 {exported.size} 与屏幕 {screen.size} 不一致")
    else:
        differing, bbox = diff_pixels(screen, exported)
        out["png_1x"]["diff_bbox"] = list(bbox) if bbox else None
        out["png_1x"]["differing"] = differing
        if differing > PIXEL_TOLERANCE:
            problems.append(f"1× 导出的 PNG 与屏幕有 {differing} 个通道值不同（bbox={bbox}）")

    # 2× / 4×：像素尺寸 = round(pt × 倍数)。
    for scale in (2, 4):
        item = export_record(page, "png", scale=scale)
        image = decode_png(item["base64"])
        want = (round(width_pt * scale), round(height_pt * scale))
        out[f"png_{scale}x"] = {
            "size": list(image.size),
            "want": list(want),
            "bytes": item["bytes"],
        }
        if image.size != want:
            problems.append(f"{scale}× PNG 是 {image.size}，应当是 {want}")

    # DPI：1× = 72 dpi，96 dpi 应当比 1× 大 4/3。
    item = export_record(page, "png", dpi=96)
    image = decode_png(item["base64"])
    want = (round(width_pt * 96 / 72), round(height_pt * 96 / 72))
    out["png_96dpi"] = {"size": list(image.size), "want": list(want)}
    if image.size != want:
        problems.append(f"96 dpi 的 PNG 是 {image.size}，应当是 {want}")

    # JPG：质量可调（0.4 与 1.0 的字节数必须不同），且不透明。
    low = export_record(page, "jpg", dpi=72, quality=0.4)
    high = export_record(page, "jpg", dpi=72, quality=1.0)
    out["jpg"] = {
        "mime": high["mime"],
        "bytes_low": low["bytes"],
        "bytes_high": high["bytes"],
        "size": list(decode_png(high["base64"]).size),
    }
    if high["mime"] != "image/jpeg":
        problems.append(f"JPG 导出的 mime 是 {high['mime']}")
    if low["bytes"] == high["bytes"]:
        problems.append("JPG 的质量参数没有生效（0.4 与 1.0 字节数相同）")

    # SVG：独立文档，尺寸按倍数、字体内嵌。
    item = export_record(page, "svg", scale=2)
    text = base64.b64decode(item["base64"]).decode("utf-8")
    out["svg"] = {
        "bytes": item["bytes"],
        "has_font_face": "@font-face" in text,
        "has_embedded_font": "data:font/ttf;base64" in text,
        "head": text[:160],
    }
    if not text.startswith("<?xml"):
        problems.append("导出的 SVG 没有 XML 声明")
    if "@font-face" not in text or "data:font/ttf;base64" not in text:
        problems.append("导出的 SVG 没有内嵌字体（在别的机器上会掉到系统字体）")
    if f'width="{round(width_pt * 2)}"' not in text:
        problems.append("导出的 2× SVG 宽度与 IR 尺寸对不上")
    return out


def check_2x_screen(browser, site, problems: list[str]) -> dict[str, Any]:
    """2× 的设备像素比下，屏幕上的图与 2× 导出的 PNG 逐像素相同。

    「同缩放倍数下像素相同」不只是 1× 一句话：换一个 `device_scale_factor=2` 的
    浏览器上下文（CSS 尺寸不变、物理像素翻倍），屏幕上的 720×504 必须还是同一张。
    CDP 的 `Emulation.setDeviceMetricsOverride` 改不动 Playwright 截图用的
    `device_scale_factor`，所以这里开一个新上下文重新加载——反正页面 boot 也在
    这个门禁的预算里。
    """
    out: dict[str, Any] = {}
    context = browser.new_context(viewport={"width": 1280, "height": 860}, device_scale_factor=2)
    try:
        page = context.new_page()
        page.set_default_timeout(300_000)
        page.goto(site.url + "/editor/index.html?example=hello", wait_until="domcontentloaded")
        wait_ready(page)
        wait_plot(page)
        from PIL import Image

        shot = page.locator("#stage-area svg.gg-svg").screenshot(omit_background=True)
        record = export_record(page, "png", scale=2)
        exported = decode_png(record["base64"])
        screen = Image.open(io.BytesIO(shot)).convert("RGBA")
        out = {"screen": list(screen.size), "export": list(exported.size)}
        if screen.size != exported.size:
            problems.append(f"2× PNG 尺寸 {exported.size} 与 2× 屏幕 {screen.size} 不一致")
        else:
            differing, bbox = diff_pixels(screen, exported)
            out["differing"] = differing
            out["diff_bbox"] = list(bbox) if bbox else None
            if differing > PIXEL_TOLERANCE:
                problems.append(f"2× 导出的 PNG 与 2× 屏幕有 {differing} 个通道值不同")
    finally:
        context.close()
    return out


def check_persistence(page, problems: list[str]) -> dict[str, Any]:
    marker = f"# 持久化检查 {int(time.time())}"
    current = page_state(page)["source"] or ""
    page.evaluate("(text) => window.__ggEditor.setSource(text)", current + "\n" + marker + "\n")
    page.wait_for_timeout(500)  # 让 350 ms 的防抖写入落下去
    page.reload(wait_until="domcontentloaded")
    wait_ready(page)
    wait_plot(page)
    state = page_state(page)
    if marker not in (state.get("source") or ""):
        problems.append("重载后编辑器里没有上次改的代码（localStorage 没生效）")
    if not state.get("stored"):
        problems.append("localStorage 里没有 gg4py.editor.v1")
    return {"stored": state.get("stored"), "restored_chars": state.get("source_chars")}


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="浏览器代码编辑器：端到端验收")
    parser.parse_args(argv)

    require_build()
    OUT.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(TOOLS / "pyodide"))
    sys.path.insert(0, str(TOOLS / "viewer"))
    runtime = _load_module("gg4py_check_runtime", TOOLS / "pyodide" / "check_runtime.py")
    import playwright_env

    playwright_env.configure()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - dev 环境才有 playwright
        print("editor:check: 需要 playwright（pixi 的 dev 环境）", file=sys.stderr)
        return 2

    expected = desktop_digests()
    problems: list[str] = []
    report: dict[str, Any] = {"examples_expected": expected, "problems": problems}

    site = runtime.serve_web()
    print(f"site {site.url} (root {runtime.WEB.relative_to(REPO)})")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            try:
                _context, page, _cdp = runtime.new_context(
                    browser, cache_disabled=True, block_external=True
                )
                run = runtime.Run(label="editor")
                runtime.observe(page, run, site)
                navigated = time.perf_counter()
                page.goto(site.url + "/editor/index.html", wait_until="domcontentloaded")
                wait_ready(page)
                wait_plot(page)
                report["first_plot_ms"] = (time.perf_counter() - navigated) * 1000.0

                report["ui"] = check_editor_ui(page, problems)
                report["first_plot"] = check_first_plot(page, problems)
                page.screenshot(path=str(OUT / "editor.png"))

                source = page_state(page)["source"] or ""
                report["warm_rerun"] = check_warm_rerun(page, source, problems)
                report["errors"] = check_error_paths(page, source, problems)
                report["examples"] = check_examples(page, expected, problems)
                report["exports"] = check_exports(page, problems)
                report["export_2x_screen"] = check_2x_screen(browser, site, problems)
                report["persistence"] = check_persistence(page, problems)

                report["requests"] = {
                    "count": len(run.requests),
                    "external": run.external_requests[:10],
                    "console_errors": run.console_errors[:10],
                }
                if run.external_requests:
                    problems.append(
                        f"出现站外请求（应当只用本地资产）：{run.external_requests[:5]}"
                    )
                if run.console_errors:
                    problems.append(f"控制台有错误：{run.console_errors[:3]}")
            finally:
                browser.close()
    finally:
        site.close()

    report["result"] = "ok" if not problems else "fail"
    (OUT / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"first plot : {report.get('first_plot_ms', 0):.0f} ms（含运行时启动与 numpy 下载）")
    warm = report.get("warm_rerun", {})
    wall = warm.get("wall_ms", 0)
    print(
        f"warm rerun : {warm.get('total_ms')} ms"
        f"（预算 {WARM_BUDGET_MS:.0f} ms，墙钟 {wall:.0f} ms）"
    )
    examples = report.get("examples", {})
    passed = sum(1 for item in examples.values() if not item.get("error"))
    print(f"examples   : {passed}/{len(examples)} 跑通，digest 与 CPython 一致")
    exports = report.get("exports", {})
    first = exports.get("png_1x", {})
    print(
        f"export 1×  : {first.get('screen')} 屏幕 vs {first.get('export')} 导出，"
        f"差异 {first.get('differing')} 个通道值"
    )
    print(f"result     : {report['result']}")
    if problems:
        print("problems   :")
        for problem in problems:
            print(f"  - {problem}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
