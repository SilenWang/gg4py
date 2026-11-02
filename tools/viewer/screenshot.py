"""M1-13：把查看器页面截成 PNG（评审 / 文档用，可重复跑）。

    pixi run viewer:shot                      # → .viewer-shot/viewer.png
    pixi run viewer:shot --out shot.png --hover

`--hover` 把鼠标停在第一个面板的点上，截图里能看到 tooltip。页面走 `http.server`
（`file://` 会拦 ES module），Chromium 来自 `.playwright-browsers`。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "viewer"))

import playwright_env  # noqa: E402
from facet_legend import facet_legend_scene  # noqa: E402

from ggcore import ir  # noqa: E402

DEFAULT_OUT = REPO / ".viewer-shot" / "viewer.png"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="viewer:shot")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--scene", type=Path, default=None, help="缺省用夹具生成的场景")
    parser.add_argument("--hover", action="store_true", help="把鼠标停在第一个面板的点上")
    parser.add_argument(
        "--click-legend", type=int, default=None, metavar="N", help="先关掉第 N 个图例项"
    )
    parser.add_argument("--width", type=int, default=1100)
    parser.add_argument("--height", type=int, default=820)
    args = parser.parse_args(argv)

    playwright_env.configure()
    from playwright.sync_api import sync_playwright

    scene_path = args.scene
    if scene_path is None:
        scene_path = args.out.with_suffix(".ggir.cbor")
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_bytes(ir.encode(facet_legend_scene()))

    handler = functools.partial(_QuietHandler, directory=str(playwright_env.VIEWER))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": args.width, "height": args.height})
            page.goto(f"http://127.0.0.1:{httpd.server_address[1]}/index.html")
            page.set_input_files("#file", str(scene_path))
            page.wait_for_selector("#status[data-state='ok']", timeout=15_000)
            if args.click_legend is not None:
                page.locator(f'[data-legend-key="guide-0-key-{args.click_legend}"]').click()
            if args.hover:
                page.locator('[data-kind="points"][data-vp="panel-1"]').first.hover()
                page.locator("#tooltip").wait_for(state="visible")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(args.out))
            print(f"{args.out}: {page.inner_text('#status')}")
            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
