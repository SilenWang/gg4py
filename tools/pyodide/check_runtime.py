#!/usr/bin/env python
"""SIL-824 · 浏览器运行时的端到端验收：自托管、懒加载、进度、断网、加载耗时。

    pixi run pyodide:check        # CI 用：断网 + 懒加载 + 进度 + 三示例两端 IR 一致
    pixi run pyodide:timing       # 实测：Fast 4G 冷启动 / warm 缓存，对照 12 s / 3 s

页面是 `web/runtime/index.html`（本地静态服务器提供 `web/`，与查看器同一个 origin）。
验收口径逐条对应 issue：

| 验收项 | 怎么判 |
| --- | --- |
| 资产本地托管，不依赖 CDN | 只允许 `127.0.0.1` 一个 origin；另有「阻断站外」重载须照常出图 |
| numpy / pandas / contourpy 懒加载 | `ready` 之前**不得**出现 `.whl` 请求；跑哪个示例才装哪个包 |
| 必须有可见加载进度 | 进度序列覆盖 ≥3 个阶段、百分比单调上升且到过 90%+；同时截图存档 |
| 同一段脚本两端 IR 逐字节相同 | 三个示例在 CPython 侧另跑一遍，sha256 必须相同 |
| warm ≤ 3 s / 首访 4G ≤ 12 s | `--measure`：服务端按 Fast 4G 限速，冷启动 vs 同浏览器重载 |

产物（不入库）：`.pyodide-runtime/report.json` 与截图。
"""

from __future__ import annotations

import argparse
import functools
import gzip
import http.server
import importlib.util
import itertools
import json
import mimetypes
import statistics
import sys
import threading
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "web"
RUNTIME = WEB / "runtime"
VENDOR = RUNTIME / "vendor"
DEMOS = RUNTIME / "demos"
VIEWER = WEB / "viewer"
OUT = REPO / ".pyodide-runtime"

COLD_BUDGET_MS = 12_000.0
WARM_BUDGET_MS = 3_000.0

#: DevTools 的 Fast 4G 预置（与 `docs/spike/e1_coldstart/run_e1.py` 同一组数字）。
PROFILES = {
    "fast4g": {"label": "Fast 4G", "down_mbps": 9.0, "up_mbps": 1.5, "latency_ms": 170},
}

#: `web/` 根下的静态文件类型（mimetypes 在容器里不认识 .wasm / .whl）。
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".css": "text/css; charset=utf-8",
    ".wasm": "application/wasm",
    ".zip": "application/zip",
    ".whl": "application/octet-stream",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ttf": "font/ttf",
    ".py": "text/plain; charset=utf-8",
}
#: 已压缩过的容器不再 gzip（zip 容器再压只是浪费 CPU 与字节）。
INCOMPRESSIBLE = {".zip", ".whl", ".png", ".ttf"}
#: 限速时的写块大小（512 KiB：`time.sleep` 每次都有 ~1 ms 的过冲，块太小会把
#: 10 MB 的载荷罚掉一秒多；这个粒度仍足够让进度条动起来）。
CHUNK_BYTES = 512 * 1024


# ---------------------------------------------------------------------------
# 本地静态服务器（gzip + 字节账本）
# ---------------------------------------------------------------------------


class _Limiter:
    """一条共享的「带宽」：所有响应按字节数排队，等价于一条限速链路。

    为什么不用 CDP 的 `Network.emulateNetworkConditions`：它作用在 **page target**
    上，而这次加载里 13 MB 是 **worker** 自己 fetch 的（pyodide 运行时、stdio、
    轮子、gg4py.tar）——worker 是独立 target，收不到 page session 的节流。E1 那组
    数字之所以被节流到，是因为它的载荷全在 worker 侧的 CDP 会话里也能观测到，
    但「不生效」在结果是看不出来的（只会显得特别快）。所以这里在服务端限速：
    口径更直白，也不依赖 CDP 的 target 语义。
    """

    def __init__(self, bytes_per_second: float, latency_ms: float) -> None:
        self.bytes_per_second = max(1.0, bytes_per_second)
        self.latency = latency_ms / 1000.0
        self._lock = threading.Lock()
        self._next_free = time.monotonic()

    def take(self, nbytes: int) -> float:
        """为一个数据块排队，返回「现在要等多久才能写」。整条链路共享一个时间轴。

        只按带宽排队，**不**按块加时延：时延是一次请求一次（`latency`），按块加会
        把 9.6 MB 的 wasm 罚成几百次 RTT（实测冷启动会从 10 s 涨到 41 s）。
        """
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_free)
            self._next_free = start + nbytes / self.bytes_per_second
            return start - now


class _Handler(http.server.SimpleHTTPRequestHandler):
    """`web/` 的静态服务：文本类响应 gzip，限速可配，并把「线上字节」记进 ledger。"""

    ledger: ClassVar[list[dict[str, Any]]] = []
    limiter: ClassVar[_Limiter | None] = None
    #: HTTP/1.1 + keep-alive：默认的 HTTP/1.0 会给每个请求重建 TCP 连接，
    #: 在 170 ms 的 4G 时延下等于每个文件白付一次握手（10 个请求 ≈ 1.7 s）。
    #: 真实静态托管（HTTP/2）不会这么差，所以这里对齐「一个有 keep-alive 的静态站」。
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_GET(self) -> None:
        path = self.translate_path(self.path)
        target = Path(path)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self.send_error(404)
            return
        suffix = target.suffix.lower()
        # 预压缩优先（等价于 nginx 的 `brotli_static on`）：`pyodide:assets` 会把
        # wasm / 源码包 / asm.mjs 的 `.br` 兄弟一起落盘，静态托管按
        # `Content-Encoding: br` 回放。**不在请求期压**是被测过的：wasm 9.6 MB 用
        # gzip 现压要几百毫秒，首字节因此晚到，冷启动数字里混进了服务端 CPU。
        brotli_path = Path(str(target) + ".br")
        # `Accept-Encoding: gzip, deflate, br` → 按 token 比，不做子串匹配
        # （`br` 是 `zstd` 都兜不住的那种短 token，子串匹配容易误判）。
        accepted = {
            token.split(";", 1)[0].strip().lower()
            for token in self.headers.get("Accept-Encoding", "").split(",")
        }
        accepts_brotli = "br" in accepted or "*" in accepted
        if accepts_brotli and brotli_path.is_file():
            body = brotli_path.read_bytes()
            decoded = target.stat().st_size
            encoding = "br"
        else:
            data = target.read_bytes()
            decoded = len(data)
            body = data if suffix in INCOMPRESSIBLE else gzip.compress(data, 6, mtime=0)
            encoding = None if body is data else "gzip"
        content_type = CONTENT_TYPES.get(suffix) or mimetypes.guess_type(target.name)[0]
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        if encoding:
            self.send_header("Content-Encoding", encoding)
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", "no-transform")
        self.end_headers()
        limiter = _Handler.limiter
        _Handler.ledger.append(
            {
                "path": "/" + target.relative_to(WEB).as_posix(),
                "decoded_bytes": decoded,
                "wire_bytes": len(body),
                "encoding": encoding or "identity",
            }
        )
        if limiter is None:
            self.wfile.write(body)
            return
        # 分块写：带宽按块排队（限速体现在传输过程上，进度条也有粒度）；
        # 时延按请求算一次。
        time.sleep(limiter.latency)
        for offset in range(0, len(body), CHUNK_BYTES):
            chunk = body[offset : offset + CHUNK_BYTES]
            delay = limiter.take(len(chunk))
            if delay > 0:
                time.sleep(delay)
            self.wfile.write(chunk)


@dataclass
class Site:
    server: http.server.ThreadingHTTPServer
    thread: threading.Thread

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def serve_web(profile: dict[str, float] | None = None) -> Site:
    """起 `web/` 的静态服务；给了 profile 就按它的下行带宽 / 时延限速。"""
    _Handler.ledger = []
    _Handler.limiter = (
        _Limiter(profile["down_mbps"] * 1_000_000 / 8, profile["latency_ms"])
        if profile is not None
        else None
    )
    handler = functools.partial(_Handler, directory=str(WEB))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return Site(server, thread)


# ---------------------------------------------------------------------------
# CPython 侧：同一份示例脚本跑一遍，拿到「应该是什么」的摘要
# ---------------------------------------------------------------------------


def demo_digests() -> dict[str, dict[str, Any]]:
    """`web/runtime/demos/*.py` 在 CPython 上的 IR 摘要（与浏览器侧逐字节比）。"""
    sys.path.insert(0, str(REPO / "src"))
    from ggcore import ir
    from ggcore.metrics.fallback import default_metrics
    from ggcore.plotspec import build_scene

    warnings.simplefilter("ignore")
    metrics = default_metrics()
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(DEMOS.glob("*.py")):
        spec_obj = importlib.util.spec_from_file_location(f"gg4py_demo_{path.stem}", path)
        if spec_obj is None or spec_obj.loader is None:  # pragma: no cover
            raise SystemExit(f"无法加载示例 {path}")
        module = importlib.util.module_from_spec(spec_obj)
        spec_obj.loader.exec_module(module)
        scene = build_scene(module.build(), metrics=metrics)
        data = ir.encode(scene)
        out[path.stem] = {
            "digest": __import__("hashlib").sha256(data).hexdigest(),
            "bytes": len(data),
            "needs": list(getattr(module, "needs", [])),
            "nodes": sum(1 for _ in ir.walk(scene.root)),
        }
    return out


# ---------------------------------------------------------------------------
# 浏览器侧
# ---------------------------------------------------------------------------


@dataclass
class Run:
    """一次导航的观测结果。"""

    label: str
    first_plot_ms: float | None = None
    state: dict[str, Any] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    progress: list[dict[str, Any]] = field(default_factory=list)
    external_requests: list[str] = field(default_factory=list)
    wheels: list[str] = field(default_factory=list)
    wire_bytes: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "first_plot_ms": self.first_plot_ms,
            "state": self.state,
            "requests": len(self.requests),
            "external_requests": self.external_requests,
            "console_errors": self.console_errors,
            "progress_events": len(self.progress),
            "wheels": self.wheels,
            "wire_bytes": self.wire_bytes,
        }


def wait_ready(page, timeout: float = 300_000) -> None:
    page.wait_for_function(
        """() => {
             const rt = window.__ggRuntime;
             if (rt === undefined) return false;
             const state = rt.state();
             if (state.error) throw new Error(`页面报错：${state.error.message}`);
             return state.ready === true;
           }""",
        timeout=timeout,
    )


def wait_first_plot(page, timeout: float = 300_000) -> None:
    page.wait_for_function(
        """() => {
             const rt = window.__ggRuntime;
             if (rt === undefined) return false;
             const state = rt.state();
             if (state.error) throw new Error(`页面报错：${state.error.message}`);
             return state.first_plot_ms !== null;
           }""",
        timeout=timeout,
    )


def new_context(browser, *, cache_disabled: bool = False, block_external: bool = False):
    context = browser.new_context(viewport={"width": 1280, "height": 860})
    page = context.new_page()
    page.set_default_timeout(300_000)
    if block_external:
        # 「断网」的等价物：只放行本站，其余（CDN / 字体站 / 任何外部）一律 abort。
        # DevTools 的 offline 模式连 localhost 也断，静态页面本来就打不开，那不是
        # 这条验收想问的问题——它要问的是「有没有依赖 CDN」。
        def _route(route, request):
            host = request.url.split("/")[2] if "//" in request.url else ""
            if host.startswith("127.0.0.1"):
                route.continue_()
            else:
                route.abort()

        context.route("**/*", _route)
    cdp = context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.setCacheDisabled", {"cacheDisabled": cache_disabled})
    return context, page, cdp


def observe(page, run: Run, site: Site) -> None:
    """挂上请求 / 控制台监听，把观测结果收进 `run`。"""

    def _request(request):
        run.requests.append(request.url)
        if not request.url.startswith(site.url):
            run.external_requests.append(request.url)

    page.on("request", _request)
    page.on(
        "console",
        lambda message: (
            run.console_errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on("pageerror", lambda error: run.console_errors.append(str(error)))


def snapshot(page, run: Run) -> None:
    state = page.evaluate("() => window.__ggRuntime.state()")
    run.state = state
    run.progress = page.evaluate("() => window.__ggRuntime.progressLog.slice()")
    run.first_plot_ms = state.get("first_plot_ms")


def assert_progress(run: Run, problems: list[str]) -> None:
    """「必须有可见加载进度」：阶段够多、百分比真的涨过、且展示在 DOM 上。"""
    stages = {entry.get("stage") for entry in run.progress}
    if len(stages) < 3:
        problems.append(f"{run.label}: 进度只覆盖 {len(stages)} 个阶段 {sorted(stages)}")
    pcts = [entry.get("pct", 0.0) for entry in run.progress]
    if not pcts or max(pcts) < 0.9:
        problems.append(f"{run.label}: 进度没走到 90%（max {max(pcts, default=0):.2f}）")
    if not any(b > a for a, b in itertools.pairwise(pcts)):
        problems.append(f"{run.label}: 进度百分比从未上升")
    visible = run.state.get("progress", {}).get("pct", 0.0)
    if visible < 0.99:
        problems.append(f"{run.label}: 页面上的进度条停在 {visible:.2f}")


def assert_no_cdn(run: Run, site: Site, problems: list[str]) -> None:
    if run.external_requests:
        problems.append(f"{run.label}: 出现站外请求 {run.external_requests[:5]}")
    del site  # 判定只看「有没有站外请求」，具体文件在下面按阶段断言
    if run.console_errors:
        problems.append(f"{run.label}: 控制台错误 {run.console_errors[:3]}")


def wheel_assets(page) -> list[dict[str, Any]]:
    """页面资源时间线里的 wheel 请求（含起始时间）。"""
    return [
        entry
        for entry in page.evaluate("() => window.__ggRuntime.assets()")
        if entry["name"].endswith(".whl")
    ]


def assert_lazy(run: Run, problems: list[str]) -> None:
    """`ready` 之前不许下任何 wheel：数值栈是真的按需加载，不是 boot 的一部分。

    证据取自页面的进度日志——每一条都带着出发它的文件名与时刻，而 Service Worker
    能看到 **worker** 发的请求（页面自己的 `performance` 时间线看不到 worker 的
    网络）。这也正是「懒加载」与「boot 里悄悄预装」的分界。
    """
    # 用与进度日志同一把尺子（相对模块求值的毫秒），不能拿绝对时钟比。
    ready_at = run.state.get("ready_rel")
    if ready_at is None:
        problems.append(f"{run.label}: 没有记下 ready 时刻")
        return
    wheels = [
        (entry["file"], entry["at"])
        for entry in run.progress
        if str(entry.get("file", "")).endswith(".whl")
    ]
    early = sorted({name.rsplit("/", 1)[-1] for name, at in wheels if at < ready_at})
    if early:
        problems.append(f"{run.label}: ready 之前就下载了 wheel（不是懒加载）：{early}")
    run.wheels = sorted({name.rsplit("/", 1)[-1] for name, _ in wheels})


# ---------------------------------------------------------------------------
# 三个模式
# ---------------------------------------------------------------------------


def check_mode(browser, site: Site, expected: dict[str, dict[str, Any]], shot_dir: Path) -> int:
    problems: list[str] = []
    run = Run(label="check")
    context, page, _cdp = new_context(browser, cache_disabled=True)
    observe(page, run, site)
    page.goto(site.url + "/runtime/index.html", wait_until="domcontentloaded")

    # 加载中截图：进度条必须真的在动。
    mid_shot = screenshot_when_loading(page, shot_dir / "loading.png")
    wait_ready(page)
    wait_first_plot(page)
    snapshot(page, run)

    if run.state.get("packages_at_ready"):
        problems.append(f"boot 阶段就装了包（应当是空的）：{run.state['packages_at_ready']}")

    assert_progress(run, problems)
    assert_no_cdn(run, site, problems)
    assert_lazy(run, problems)

    # 三个示例：IR 摘要必须与 CPython 侧相同；包按 needs 逐个加载。
    for name in ("basic", "contour", "pandas"):
        before = set(run.state.get("packages", []))
        page.evaluate("(name) => window.__ggRuntime.run(name)", name)
        page.wait_for_function(
            "(name) => window.__ggRuntime.state().results[name] !== undefined",
            arg=name,
        )
        snapshot(page, run)
        result = run.state["results"][name]
        want = expected[name]
        if result["digest"] != want["digest"]:
            problems.append(
                f"{name}: IR 与 CPython 不一致（{result['bytes']} B {result['digest'][:16]}… / "
                f"{want['bytes']} B {want['digest'][:16]}…）"
            )
        if not result.get("roundtrip", False):
            problems.append(f"{name}: IR 解码回环失败")
        added = set(run.state.get("packages", [])) - before
        if name == "contour" and "contourpy" not in run.state.get("packages", []):
            problems.append("contour: 没有加载 contourpy")
        if name == "pandas" and "pandas" not in run.state.get("packages", []):
            problems.append("pandas: 没有加载 pandas")
        if name == "basic" and added - {"numpy"}:
            problems.append(f"basic: 多装了 {sorted(added - {'numpy'})}")
        print(
            f"  示例 {name:8s} {result['bytes']:>6d} B sha256 {result['digest'][:16]}… "
            f"packages={run.state.get('packages')}"
        )

    page.wait_for_function(
        "() => document.querySelector('#stage-area svg.gg-svg') !== null", timeout=30_000
    )
    page.screenshot(path=str(shot_dir / "final.png"))
    context.close()

    # 断网等价物：阻断所有站外请求再重载一遍，页面必须照常出图。
    offline = Run(label="offline")
    context, page, _cdp = new_context(browser, cache_disabled=True, block_external=True)
    observe(page, offline, site)
    page.goto(site.url + "/runtime/index.html", wait_until="domcontentloaded")
    try:
        wait_ready(page)
        wait_first_plot(page)
    except Exception as error:
        problems.append(f"offline: 阻断站外请求后页面没有出图（{error}）")
    snapshot(page, offline)
    if offline.first_plot_ms is None:
        problems.append("offline: 没有 first_plot_ms")
    page.evaluate("() => window.__ggRuntime.run('contour')")
    page.wait_for_function("() => window.__ggRuntime.state().results.contour !== undefined")
    snapshot(page, offline)
    if offline.state["results"]["contour"]["digest"] != expected["contour"]["digest"]:
        problems.append("offline: contour 的 IR 与 CPython 不一致")
    page.screenshot(path=str(shot_dir / "offline.png"))
    context.close()

    report = {
        "mode": "check",
        "ok": not problems,
        "problems": problems,
        "boot": run.as_dict(),
        "offline": offline.as_dict(),
        "wire_bytes": sum(entry["wire_bytes"] for entry in _Handler.ledger),
        "ledger": _Handler.ledger,
        "loading_screenshot": str(mid_shot) if mid_shot else None,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_report(report)
    print_report(report)
    return 0 if not problems else 1


def screenshot_when_loading(page, path: Path, timeout: float = 60.0) -> Path | None:
    """在进度处于 5%–99% 之间时截一张（证明「可见加载进度」）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            snapshot_state = page.evaluate(
                "() => (window.__ggRuntime ? window.__ggRuntime.state() : null)"
            )
        except Exception:
            snapshot_state = None
        if snapshot_state is not None:
            if snapshot_state.get("error"):
                return None
            pct = snapshot_state.get("progress", {}).get("pct", 0.0)
            if 0.05 <= pct <= 0.99:
                page.screenshot(path=str(path))
                return path
        time.sleep(0.02)
    return None


def timing_mode(
    playwright,
    site: Site,
    expected: dict[str, dict[str, Any]],
    shot_dir: Path,
    *,
    runs: int,
    profile_key: str,
) -> int:
    profile = PROFILES[profile_key]
    problems: list[str] = []
    cold: list[float] = []
    warm: list[float] = []
    runs_report: list[dict[str, Any]] = []

    for index in range(runs):
        # 每次冷启动用**新浏览器**：Cache Storage / HTTP 缓存 / Service Worker 全部
        # 从零开始，才配叫「首访」。CDP 的 `setCacheDisabled` 只作用于 page target，
        # 管不到 worker 的请求，靠它会测出「假冷启动」。
        fresh = playwright.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        try:
            run = Run(label=f"cold#{index + 1}")
            ledger_start = len(_Handler.ledger)
            context, page, _cdp = new_context(fresh)
            observe(page, run, site)
            page.goto(site.url + "/runtime/index.html", wait_until="domcontentloaded")
            if index == 0:
                screenshot_when_loading(page, shot_dir / f"cold_{profile_key}_loading.png")
            wait_first_plot(page)
            snapshot(page, run)
            run.wire_bytes = sum(entry["wire_bytes"] for entry in _Handler.ledger[ledger_start:])
            if run.first_plot_ms is not None:
                cold.append(run.first_plot_ms)
            page.screenshot(path=str(shot_dir / f"cold_{profile_key}_{index + 1}.png"))
            assert_progress(run, problems)
            assert_no_cdn(run, site, problems)
            assert_lazy(run, problems)
            if not any("numpy-" in name for name in run.wheels):
                problems.append(f"{run.label}: 没有下载 numpy wheel（首图本来要用它）")
            print(
                f"  {profile['label']:8s} 冷启动 #{index + 1}  {run.first_plot_ms:8.0f} ms  "
                f"wire {run.wire_bytes / 1e6:6.2f} MB"
            )

            # warm：同一浏览器重新导航一次（HTTP 缓存 + Service Worker 已就位）。
            ledger_start = len(_Handler.ledger)
            warm_run = Run(label=f"warm#{index + 1}")
            observe(page, warm_run, site)
            page.reload(wait_until="domcontentloaded")
            wait_first_plot(page)
            snapshot(page, warm_run)
            warm_run.wire_bytes = sum(
                entry["wire_bytes"] for entry in _Handler.ledger[ledger_start:]
            )
            if warm_run.first_plot_ms is not None:
                warm.append(warm_run.first_plot_ms)
            # warm 也要有完整进度：缓存命中是瞬时的，进度如果因为「监听器装晚了」
            # 丢掉最早几个文件，页面会永远停在 87%（SIL-830 的回归点）。
            assert_progress(warm_run, problems)
            print(
                f"  {profile['label']:8s} warm   #{index + 1}  {warm_run.first_plot_ms:8.0f} ms  "
                f"wire {warm_run.wire_bytes / 1e6:6.2f} MB"
            )
            if index == 0:
                page.screenshot(path=str(shot_dir / f"warm_{profile_key}.png"))
            runs_report.append({"cold": run.as_dict(), "warm": warm_run.as_dict()})
            context.close()
        finally:
            fresh.close()

    cold_median = statistics.median(cold) if cold else float("nan")
    warm_median = statistics.median(warm) if warm else float("nan")
    if not cold or cold_median > COLD_BUDGET_MS:
        problems.append(
            f"首访 {profile['label']} 中位 {cold_median:.0f} ms > {COLD_BUDGET_MS:.0f} ms"
        )
    if not warm or warm_median > WARM_BUDGET_MS:
        problems.append(f"warm 中位 {warm_median:.0f} ms > {WARM_BUDGET_MS:.0f} ms")

    report = {
        "mode": "timing",
        "ok": not problems,
        "profile": {"key": profile_key, **profile},
        "cold_ms": cold,
        "warm_ms": warm,
        "cold_median_ms": cold_median,
        "warm_median_ms": warm_median,
        "budget": {"cold_ms": COLD_BUDGET_MS, "warm_ms": WARM_BUDGET_MS},
        "runs": runs_report,
        "problems": problems,
        "wire_bytes": sum(entry["wire_bytes"] for entry in _Handler.ledger),
        "ledger": _Handler.ledger,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_report(report)
    print_report(report)
    return 0 if not problems else 1


# ---------------------------------------------------------------------------
# 报告与入口
# ---------------------------------------------------------------------------


def write_report(report: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")


def print_report(report: dict[str, Any]) -> None:
    print()
    print(f"mode      : {report['mode']}")
    if report["mode"] == "timing":
        print(f"cold      : {report['cold_ms']}")
        print(f"warm      : {report['warm_ms']}")
        print(
            f"median    : cold {report['cold_median_ms']:.0f} ms / "
            f"warm {report['warm_median_ms']:.0f} ms"
        )
    print(f"wire      : {report['wire_bytes']:,d} B（gzip 后实际传输）")
    if report["problems"]:
        print("problems  :")
        for problem in report["problems"]:
            print(f"  - {problem}")
        print("result    : FAIL")
    else:
        print("result    : ok")


def require_build() -> None:
    missing = []
    if not (VENDOR / "manifest.json").is_file():
        missing.append("web/runtime/vendor/manifest.json")
    if not (VENDOR / "gg4py.tar").is_file():
        missing.append("web/runtime/vendor/gg4py.tar")
    if not (VIEWER / "dist" / "render.js").is_file():
        missing.append("web/viewer/dist/render.js")
    if not (VIEWER / "fonts.css").is_file():
        missing.append("web/viewer/fonts.css")
    if missing:
        raise SystemExit(
            "pyodide:runtime 缺少产物："
            + ", ".join(missing)
            + "\n  先跑 `pixi run pyodide:assets`（依赖 viewer:build 与 spike:e1:assets）"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="浏览器运行时：验收 / 加载耗时。")
    parser.add_argument("--measure", action="store_true", help="跑 Fast 4G 冷启动 + warm 实测")
    parser.add_argument("--runs", type=int, default=3, help="--measure 每种状态的次数")
    parser.add_argument("--profile", default="fast4g", choices=sorted(PROFILES))
    args = parser.parse_args(argv)

    require_build()
    sys.path.insert(0, str(REPO / "tools" / "viewer"))
    import playwright_env

    playwright_env.configure()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - dev 环境才有 playwright
        print("pyodide:runtime: 需要 playwright（pixi 的 dev 环境）", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    shot_dir = OUT
    expected = demo_digests()
    # 实测模式在**服务端**限速（理由见 `_Limiter`），验收模式不限速。
    site = serve_web(PROFILES[args.profile] if args.measure else None)
    print(f"site {site.url} (root {WEB.relative_to(REPO)})")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            try:
                if args.measure:
                    return timing_mode(
                        playwright,
                        site,
                        expected,
                        shot_dir,
                        runs=args.runs,
                        profile_key=args.profile,
                    )
                return check_mode(browser, site, expected, shot_dir)
            finally:
                browser.close()
    finally:
        site.close()


if __name__ == "__main__":
    sys.exit(main())
