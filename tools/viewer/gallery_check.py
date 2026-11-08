#!/usr/bin/env python
"""gallery.html 链接全量检查（SIL-828 / M3-7）。

    pixi run gallery:check            # 逐条请求 gallery.html 里的每个链接
    pixi run gallery:check --json     # 机读结果（给 CI / PR 贴表）

gallery 有两条产线（SIL-893），卡片契约相同、缩略图后缀不同：

- `pixi run viewer:cases`（验证产线，需 Chromium）：缩略图 `../gallery/<case>.png`
  来自 viewer 自己的 Chromium 截图；
- `pixi run viewer:gallery`（静态产线，无 Chromium）：缩略图 `../gallery/<case>.svg`，
  就是仓内的 `docs/cases/<case>/expected.svg`。

两份都写 `web/viewer/dist/gallery.html`，卡片链到
`../index.html?scene=gallery/<case>.ggir.cbor`。这份脚本按**浏览器实际会请求的 URL**
起一个 `web/viewer/` 静态服务器，逐条 GET，任何非 200、空响应或超时都算失败；带
`scene=` 的链接还会额外请求 viewer 随后 `fetch()` 的那份 IR。

除链接本身，还核对两件事：

- **卡片 ↔ case 一致**：每个合法 case 都要有卡片；卡片不能指向已经删掉的 case
  （失效链接的另一半——文件还在、case 不在）。
- **资产存在**：`<img src>` 与 `scene=` 指向的文件必须在磁盘上（HTTP 404 之外的
  另一层兜底，错误信息更直接）。

`gallery.html` 不存在时直接失败并提示生成命令——静默跳过会把「没生成」伪装成
「全部 200」。
"""

from __future__ import annotations

import argparse
import functools
import html.parser
import http.server
import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

REPO = Path(__file__).resolve().parents[2]
VIEWER = REPO / "web" / "viewer"
GALLERY = VIEWER / "dist" / "gallery.html"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


class _QuietServer(http.server.ThreadingHTTPServer):
    """静态服务器；客户端提前断开（我们只读响应体就关）不算错误。"""

    def handle_error(self, request, client_address) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class _Server:
    """把 viewer 根目录当静态站点（`file://` 下浏览器会拦 fetch，所以必须走 HTTP）。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def __enter__(self) -> str:
        handler = functools.partial(_QuietHandler, directory=str(self.root))
        self.httpd = _QuietServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _load_matrix_module():
    path = REPO / "tools" / "cases" / "matrix.py"
    spec = importlib.util.spec_from_file_location("gg4py_case_matrix_gallery", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise SystemExit(f"gallery:check: 找不到 {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _RefParser(html.parser.HTMLParser):
    """只收 `<a href>` / `<img src>` / `<script src>` / `<link href>`。"""

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str, str]] = []
        self.cards: list[str] = []
        self._in_h2 = False
        self._h2 = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.refs.append((tag, "href", values["href"] or ""))
        if tag in ("img", "script") and values.get("src"):
            self.refs.append((tag, "src", values["src"] or ""))
        if tag == "link" and values.get("href"):
            self.refs.append((tag, "href", values["href"] or ""))
        if tag == "h2":
            self._in_h2 = True
            self._h2 = ""

    def handle_data(self, data: str) -> None:
        if self._in_h2:
            self._h2 += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._in_h2:
            self._in_h2 = False
            self.cards.append(self._h2.strip())


@dataclass
class Check:
    url: str
    kind: str
    status: int | None = None
    detail: str = ""
    ok: bool = False

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "kind": self.kind,
            "status": self.status,
            "ok": self.ok,
            "detail": self.detail,
        }


@dataclass
class Report:
    gallery: str
    cards: int = 0
    links: list[Check] = field(default_factory=list)
    missing_cases: list[str] = field(default_factory=list)
    stale_cards: list[str] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [item for item in self.links if not item.ok]

    @property
    def passed(self) -> list[Check]:
        return [item for item in self.links if item.ok]


def _relative_target(base: Path, ref: str) -> Path | None:
    """把 gallery 里的相对 URL 解析成 viewer 根目录下的磁盘路径。"""
    parts = urlsplit(ref)
    if parts.scheme or ref.startswith(("#", "data:", "mailto:")):
        return None
    target = unquote(parts.path)
    if not target:
        return None
    return (base / target.lstrip("/")).resolve()


def _get(url: str, timeout: float) -> tuple[int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read()
            if response.status != 200:
                return response.status, f"HTTP {response.status}"
            if not body:
                return response.status, "空响应"
            return response.status, ""
    except urllib.error.HTTPError as error:
        return error.code, f"HTTP {error.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return None, f"{type(error).__name__}: {error}"


def check_gallery(
    gallery: Path, viewer: Path, timeout: float, *, case_names: set[str] | None = None
) -> Report:
    if not gallery.is_file():
        raise SystemExit(
            f"gallery:check: {gallery} 不存在；先跑 `pixi run viewer:gallery`（静态，"
            "不需要 Chromium）或 `pixi run viewer:cases`（需要 Chromium）生成 gallery"
        )
    parser = _RefParser()
    parser.feed(gallery.read_text(encoding="utf-8"))
    report = Report(gallery=str(gallery), cards=len(parser.cards))

    try:
        gallery_rel = gallery.resolve().relative_to(viewer.resolve()).as_posix()
    except ValueError:
        gallery_rel = gallery.name
    with _Server(viewer) as base:
        base_url = base + "/"
        gallery_url = urljoin(base_url, gallery_rel)
        for tag, attr, ref in parser.refs:
            kind = f"{tag}.{attr}"
            if urlsplit(ref).scheme or ref.startswith(("#", "data:", "mailto:")):
                report.links.append(Check(ref, kind, 200, "外部 / 锚点，跳过", True))
                continue
            url = urljoin(gallery_url, ref)
            status, detail = _get(url, timeout)
            item = Check(ref, kind, status, detail, status == 200)
            if item.ok:
                target = _relative_target(gallery.parent, urlsplit(ref).path)
                if target is not None and not target.is_file():
                    item.ok = False
                    item.detail = f"文件不存在：{target}"
            report.links.append(item)

            # card 链接：viewer 打开后再 fetch(scene)，这是第二个真实请求。
            scene = parse_qs(urlsplit(ref).query).get("scene")
            if scene:
                scene_ref = scene[0]
                scene_url = urljoin(base_url + "index.html", scene_ref)
                scene_status, scene_detail = _get(scene_url, timeout)
                scene_item = Check(
                    f"scene={scene_ref}", "scene", scene_status, scene_detail, scene_status == 200
                )
                target = _relative_target(viewer, scene_ref)
                if scene_item.ok and target is not None and not target.is_file():
                    scene_item.ok = False
                    scene_item.detail = f"文件不存在：{target}"
                report.links.append(scene_item)

    # 卡片 ↔ case 台账：每个合法 case 都要有卡片；卡片不能指向已删掉的 case。
    if case_names is None:
        matrix = _load_matrix_module()
        case_names = {case.name for case in matrix.discover(matrix.CASES) if case.valid}
    cards = set(parser.cards)
    report.missing_cases = sorted(case_names - cards)
    report.stale_cards = sorted(cards - case_names)
    return report


def _case_of(ref: str) -> str | None:
    """从卡片链接 / 缩略图 / scene 里认出 case 名。"""
    parts = urlsplit(ref)
    query = parse_qs(parts.query)
    if "scene" in query:
        return Path(query["scene"][0]).name.removesuffix(".ggir.cbor")
    name = Path(unquote(parts.path)).name
    for suffix in (".ggir.cbor", ".png", ".svg"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return None


def _print_compact(report: Report) -> None:
    """每张卡片一行：href / scene / png 三个请求的状态（给 PR 贴全量表）。"""
    grouped: dict[str, dict[str, Check]] = {}
    for item in report.links:
        case = _case_of(item.url)
        if case is None:
            grouped.setdefault("（非卡片链接）", {})[item.kind] = item
        else:
            grouped.setdefault(case, {})[item.kind] = item
    for case in sorted(grouped):
        cells = grouped[case]
        ok = all(item.ok for item in cells.values())
        parts = " · ".join(
            f"{kind}={item.status if item.status is not None else 'ERR'}"
            for kind, item in sorted(cells.items())
        )
        print(f"{'OK ' if ok else 'FAIL'} {case}  {parts}")


def _print_report(report: Report, *, total_cases: int) -> None:
    width = max((len(item.url) for item in report.links), default=8)
    for item in report.links:
        status = str(item.status) if item.status is not None else "ERR"
        mark = "OK " if item.ok else "FAIL"
        suffix = f"  {item.detail}" if item.detail else ""
        print(f"{mark} {status:>3}  {item.url:<{width}}  {item.kind}{suffix}")
    print()
    print(
        f"gallery:check: {report.gallery} — 链接 {len(report.passed)}/{len(report.links)} 返回 200"
    )
    print(f"gallery:check: 卡片 {report.cards} 个（合法 case {total_cases} 个）")
    if report.missing_cases:
        print(
            f"gallery:check: {len(report.missing_cases)} 个合法 case 没有卡片："
            + ", ".join(report.missing_cases),
            file=sys.stderr,
        )
    if report.stale_cards:
        print(
            f"gallery:check: {len(report.stale_cards)} 张卡片指向不存在的 case："
            + ", ".join(report.stale_cards),
            file=sys.stderr,
        )
    if report.failed:
        print(f"gallery:check: {len(report.failed)} 个链接不是 200 / 文件缺失", file=sys.stderr)
    else:
        print("gallery:check: 全部链接 200，卡片与 case 台账一致")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gallery:check", description="逐条请求 gallery.html 的链接并核对卡片 ↔ case。"
    )
    parser.add_argument("--gallery", type=Path, default=GALLERY, help="gallery.html 路径")
    parser.add_argument(
        "--viewer-root", type=Path, default=VIEWER, help="viewer 静态根（含 index.html）"
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="单个请求超时（秒）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--compact", action="store_true", help="每张卡片一行（href / scene / png 三个请求）"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    matrix = _load_matrix_module()
    case_names = {case.name for case in matrix.discover(matrix.CASES) if case.valid}
    total_cases = len(case_names)
    report = check_gallery(args.gallery, args.viewer_root, args.timeout, case_names=case_names)
    if args.json:
        print(
            json.dumps(
                {
                    "gallery": report.gallery,
                    "cards": report.cards,
                    "cases": total_cases,
                    "links_total": len(report.links),
                    "links_ok": len(report.passed),
                    "links_failed": len(report.failed),
                    "missing_cases": report.missing_cases,
                    "stale_cards": report.stale_cards,
                    "links": [item.as_dict() for item in report.links],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        if args.compact:
            _print_compact(report)
        else:
            _print_report(report, total_cases=total_cases)
    return 1 if (report.failed or report.missing_cases or report.stale_cards) else 0


if __name__ == "__main__":
    raise SystemExit(main())
