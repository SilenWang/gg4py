#!/usr/bin/env python
"""本地起一个静态服务，打开浏览器就能用编辑器（`pixi run editor:serve`）。

编辑器是**一个静态页面 + 本地资产**：没有后端、没有账号、没有构建服务。但它不能
用 `file://` 打开（浏览器会拦 ES module 与 fetch），所以给一个最小静态服务：

    pixi run editor:serve            # http://127.0.0.1:8000/editor/
    pixi run editor:serve --port 9000

服务根是 `web/`（与 `pyodide:runtime` / viewer 的验收同一个 origin），MIME 表复用
`tools/pyodide/check_runtime.py` 的那一份——容器里的 `mimetypes` 不认识
`.wasm` / `.whl` / `.mjs`，漏一个就是「浏览器里加载不了 pyodide」。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import sys
import threading
from pathlib import Path
from typing import ClassVar

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WEB = REPO / "web"
sys.path.insert(0, str(REPO / "tools" / "pyodide"))

from check_runtime import CONTENT_TYPES  # noqa: E402 - 先放 sys.path 再 import 本地脚本


class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map: ClassVar[dict[str, str]] = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        **CONTENT_TYPES,
    }

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s\n" % (format % args))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地静态服务：编辑器 / 查看器 / 运行时页")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)

    if not (WEB / "editor" / "index.html").is_file():
        print("缺 web/editor/index.html", file=sys.stderr)
        return 2
    if not (WEB / "runtime" / "vendor" / "pyodide" / "pyodide.mjs").is_file():
        print("缺 web/runtime/vendor（先跑 `pixi run pyodide:assets`）", file=sys.stderr)
        return 2

    handler = functools.partial(_Handler, directory=str(WEB))
    server = http.server.ThreadingHTTPServer((args.host, args.port), handler)
    host, port = server.server_address[:2]
    print(f"gg4py editor : http://{host}:{port}/editor/")
    print(f"viewer       : http://{host}:{port}/viewer/")
    print("Ctrl+C 停止")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
