#!/usr/bin/env python
"""`pixi run viewer:serve`：一条命令打开静态 gallery（SIL-893）。

    pixi run viewer:serve                  # http://127.0.0.1:8000/dist/gallery.html
    pixi run viewer:serve --port 8010

为什么需要它：`gallery.html` 与 `index.html` 都要 `fetch()` 卡片对应的
`.ggir.cbor`，`file://` 下浏览器会拦（同源策略），所以必须有一个静态服务。
**这个任务只起服务，不要浏览器自动化**——它跟 `viewer:gallery` 是同一层。

服务根是 `web/viewer/`（不是仓库根）：`gallery.html` 里的链接
（`../index.html?scene=gallery/<case>.ggir.cbor`）都按这个根目录解析，
与 `viewer:cases` / `gallery:check` 的口径一致。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import sys
from pathlib import Path
from typing import ClassVar

REPO = Path(__file__).resolve().parents[2]
VIEWER = REPO / "web" / "viewer"


class _Handler(http.server.SimpleHTTPRequestHandler):
    # 容器里的 `mimetypes` 不认识 `.cbor`；给个明确类型，viewer 那边照常吃字节。
    extensions_map: ClassVar[dict[str, str]] = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".cbor": "application/cbor",
    }


def make_server(host: str, port: int, root: Path) -> http.server.ThreadingHTTPServer:
    """按 viewer 根目录起一个静态服务（`port=0` 让内核挑一个空闲端口，测试用）。"""
    handler = functools.partial(_Handler, directory=str(root))
    return http.server.ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地静态服务：viewer + 静态 gallery")
    parser.add_argument("--port", type=int, default=8000, help="端口（默认 8000）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--root", type=Path, default=VIEWER, help="服务根（默认 web/viewer）")
    args = parser.parse_args(argv)

    if not (args.root / "index.html").is_file():
        print(f"viewer:serve: {args.root} 下没有 index.html", file=sys.stderr)
        return 2

    gallery = args.root / "dist" / "gallery.html"
    try:
        server = make_server(args.host, args.port, args.root)
    except OSError as error:
        print(
            f"viewer:serve: 起不了服务（{error}）；端口被占用时换一个："
            "`pixi run viewer:serve --port 8010`",
            file=sys.stderr,
        )
        return 2
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    if gallery.is_file():
        print(f"静态 gallery : {base}/dist/gallery.html", flush=True)
        print("  （缩略图是 R 产线的 expected.svg；点卡片在浏览器里渲染同一份 IR）", flush=True)
    else:
        print(f"还没有 gallery.html（{gallery}）：先跑 `pixi run viewer:gallery`", flush=True)
    print(f"空 viewer    : {base}/index.html?scene=gallery/…（也可直接拖入 IR）", flush=True)
    print("Ctrl+C 停止", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
