"""E1 gate: how long does the Pyodide cold start take behind a worker?

Measurement protocol
  page         : docs/spike/e1_coldstart/index.html + worker.js, static, no CDN
  runtime      : pyodide 314.0.7 (CPython 3.14.2, wasm32), numpy 2.4.6
  browser      : Chromium via Playwright, headless, viewport 1280x800
  throttling   : CDP `Network.emulateNetworkConditions`, one profile per run
  start        : navigation start (`performance.timeOrigin`)
  end          : the frame that contains the plot -- worker replies, the main
                 thread draws, two animation frames later the clock is read
                 (2nd rAF proves the frame was composited), then the canvas is
                 read back so a blank "paint" cannot win.
  cache        : `Network.setCacheDisabled(true)` + a fresh browser context per
                 cold run; the warm sample re-navigates in the *same* context
                 with the HTTP cache enabled.
  repetitions  : 5 cold starts per throttling profile (median + p90), plus the
                 numpy/pandas sensitivity variants.

Everything is served from a local static server, so the numbers depend only on
the payload in `static/` (staged by `spike:e1:assets`), never on a CDN.

Run: pixi run spike:e1
Env overrides: E1_RUNS (cold samples/profile), E1_SENS_RUNS (variant samples),
               E1_PROFILES (comma list, e.g. "fast4g"), E1_WARM=0 to skip warm.
"""

from __future__ import annotations

import datetime
import gzip
import hashlib
import http.server
import importlib.metadata
import json
import mimetypes
import os
import platform
import statistics
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path
from typing import ClassVar

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
REPO = SPIKE.parent.parent
STATIC = HERE / "static"
# The server root is the page's own directory: /index.html, /worker.js and
# /static/... must all live under one origin.
SITE = HERE
RESULTS = HERE / "results"

# Playwright's browser cache lives inside the checkout: $HOME is read-only in
# the runtime image, and `playwright install` cannot write there.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(REPO / ".playwright-browsers"))

# Chromium links against glib/nss/atk/... which come from the pixi env, but the
# activation here does not put $CONDA_PREFIX/lib on the loader path, so the
# browser binary would die on "libglib-2.0.so.0: cannot open shared object".
_conda_prefix = Path(os.environ.get("CONDA_PREFIX", ""))
_conda_lib = _conda_prefix / "lib"
if _conda_lib.is_dir():
    _ld = os.environ.get("LD_LIBRARY_PATH", "")
    _parts = [p for p in _ld.split(":") if p]
    if str(_conda_lib) not in _parts:
        os.environ["LD_LIBRARY_PATH"] = ":".join([str(_conda_lib), *_parts])

# Same story for text: this image has no /etc/fonts, so without pointing
# fontconfig at the pixi env's config Chromium finds zero faces and every
# fillText() comes out zero-width -- the CJK line in the plot would silently
# vanish while the timing still looked fine.
_fonts_conf = _conda_prefix / "etc" / "fonts" / "fonts.conf"
if _fonts_conf.is_file():
    os.environ.setdefault("FONTCONFIG_FILE", str(_fonts_conf))
    os.environ.setdefault("FONTCONFIG_PATH", str(_fonts_conf.parent))

# DevTools "Fast 4G" / "Fast 3G" presets as the issue defines them, plus the
# standard "Slow 3G" only as a stress reference (never part of the verdict).
# down/up are decimal bits per second; CDP wants bytes per second.
PROFILES = {
    "fast4g": {
        "label": "Fast 4G",
        "down_mbps": 9.0,
        "up_mbps": 1.5,
        "latency_ms": 170,
        "gate_ms": 3000,
        "gated": True,
    },
    "fast3g": {
        "label": "Fast 3G",
        "down_mbps": 1.6,
        "up_mbps": 0.75,
        "latency_ms": 562,
        "gate_ms": 8000,
        "gated": True,
    },
    "slow3g": {
        "label": "Slow 3G (stress reference, not judged)",
        "down_mbps": 0.4,
        "up_mbps": 0.4,
        "latency_ms": 2000,
        "gate_ms": None,
        "gated": False,
    },
}

SENSITIVITY_PROFILES = ["fast4g", "fast3g"]
VARIANTS = {
    "baseline": "numpy loaded, drawn with numpy",
    "no_numpy": "no wheel loaded, same workload in pure Python",
    "with_pandas": "numpy + pandas loaded (pandas never used for the plot)",
}

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
}

# Already-compressed containers are shipped as-is: gzipping a zip only adds
# bytes, and the whole point is to report what actually crosses the wire.
INCOMPRESSIBLE = {".zip", ".whl", ".png", ".woff2", ".gz", ".br"}


def wire_variant(path: Path) -> bytes | None:
    """Return the body the server would send for this file (gzip or raw)."""
    data = path.read_bytes()
    if path.suffix.lower() in INCOMPRESSIBLE:
        return None
    return gzip.compress(data, 6, mtime=0)


class StaticHandler(http.server.BaseHTTPRequestHandler):
    """Static file server with gzip, cache validators and a byte ledger."""

    protocol_version = "HTTP/1.1"
    server_version = "e1-static/1.0"

    root: ClassVar[Path] = SITE
    ledger: ClassVar[list[dict]] = []
    ledger_lock: ClassVar[threading.Lock] = threading.Lock()
    encoded: ClassVar[dict[str, bytes]] = {}
    etags: ClassVar[dict[str, str]] = {}

    def log_message(self, *args):  # silence: the ledger is the log
        pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", ""):
            path = "/index.html"
        rel = urllib.parse.unquote(path).lstrip("/")
        target = (self.root / rel).resolve()
        if not target.is_relative_to(self.root.resolve()) or not target.is_file():
            self.send_error(404)
            return

        raw = target.read_bytes()
        ctype = CONTENT_TYPES.get(
            target.suffix.lower(),
            mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        )
        etag = self.etags.setdefault(rel, f'"{hashlib.sha1(raw).hexdigest()}"')

        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        body = raw
        encoding = None
        if accepts_gzip and target.suffix.lower() not in INCOMPRESSIBLE:
            body = self.encoded.get(rel) or gzip.compress(raw, 6, mtime=0)
            self.encoded[rel] = body
            encoding = "gzip"

        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self._record(rel, 304, 0, len(raw), None, ctype)
            return

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "public, max-age=3600")
        if encoding:
            self.send_header("Content-Encoding", encoding)
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self._record(rel, 200, 0, len(raw), encoding, ctype, note="client-aborted")
            return
        self._record(rel, 200, len(body), len(raw), encoding, ctype)

    def _record(self, rel, status, wire, decoded, encoding, ctype, note=None):
        entry = {
            "path": rel,
            "status": status,
            "wire_bytes": wire,
            "decoded_bytes": decoded,
            "content_encoding": encoding,
            "content_type": ctype,
        }
        if note:
            entry["note"] = note
        with self.ledger_lock:
            self.ledger.append(entry)


def start_server() -> tuple[http.server.ThreadingHTTPServer, int]:
    # Precompute the gzip bodies so the first request does not pay for
    # compression inside the measured window.
    for path in SITE.rglob("*"):
        if not path.is_file() or ".npm" in path.parts or "results" in path.parts:
            continue
        rel = path.relative_to(SITE).as_posix()
        StaticHandler.etags[rel] = f'"{hashlib.sha1(path.read_bytes()).hexdigest()}"'
        if path.suffix.lower() not in INCOMPRESSIBLE:
            StaticHandler.encoded[rel] = gzip.compress(path.read_bytes(), 6, mtime=0)

    handler = StaticHandler
    handler.root = SITE
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def take_ledger() -> list[dict]:
    with StaticHandler.ledger_lock:
        entries = list(StaticHandler.ledger)
        StaticHandler.ledger.clear()
    return entries


def cdp_params(profile: dict) -> dict:
    return {
        "offline": False,
        "latency": profile["latency_ms"],
        "downloadThroughput": int(profile["down_mbps"] * 1_000_000 / 8),
        "uploadThroughput": int(profile["up_mbps"] * 1_000_000 / 8),
        "connectionType": "cellular4g" if profile["down_mbps"] > 5 else "cellular3g",
    }


def assets_table() -> dict:
    rows = []
    for path in sorted(STATIC.rglob("*")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        compressed = len(gzip.compress(raw, 6, mtime=0))
        rows.append(
            {
                "file": path.relative_to(STATIC).as_posix(),
                "disk_bytes": len(raw),
                "gzip_bytes": compressed,
                "served_encoding": None
                if path.suffix.lower() in INCOMPRESSIBLE
                else "gzip",
                # what the browser actually downloads (throttle applies to this)
                "wire_bytes": len(raw)
                if path.suffix.lower() in INCOMPRESSIBLE
                else compressed,
            }
        )
    total_disk = sum(r["disk_bytes"] for r in rows)
    total_wire = sum(r["wire_bytes"] for r in rows)
    by_group: dict[str, int] = {}
    for row in rows:
        name = row["file"]
        if name.endswith(".wasm"):
            group = "pyodide.asm.wasm"
        elif name.endswith("python_stdlib.zip"):
            group = "python_stdlib.zip"
        elif name.startswith("pyodide/numpy-"):
            group = "wheels/numpy"
        elif name.startswith("pyodide/pandas-"):
            group = "wheels/pandas"
        elif name.endswith(".whl"):
            group = "wheels/other"
        else:
            group = "js/json/html glue"
        by_group[group] = by_group.get(group, 0) + row["wire_bytes"]
    return {
        "files": rows,
        "total_disk_bytes": total_disk,
        "total_wire_bytes": total_wire,
        "note": (
            "total_*_bytes cover every file the server can serve, i.e. all "
            "variants together; what one cold start actually downloads is "
            "per-run `bytes.server_wire` (baseline 9.35 MB, no_numpy 6.39 MB, "
            "+pandas 14.28 MB)."
        ),
        "wire_bytes_by_group": dict(sorted(by_group.items(), key=lambda kv: -kv[1])),
    }


def summarize(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {"n": 0}
    p90 = ordered[min(len(ordered) - 1, round(0.9 * (len(ordered) - 1)))]
    return {
        "n": len(ordered),
        "median": statistics.median(ordered),
        "mean": statistics.fmean(ordered),
        "p90": p90,
        "min": ordered[0],
        "max": ordered[-1],
    }


def stage_table(samples: list[dict]) -> dict:
    """Median per-stage duration over the successful samples of one bucket."""
    keys = [
        "nav_to_worker_spawn",
        "worker_module_start",
        "wasm_download",
        "wasm_response_end",
        "pyodide_init",
        "pyodide_ready",
        "packages_load",
        "packages_ready",
        "compute",
        "compute_done",
        "worker_done",
        "points_received",
        "draw",
        "paint_after_draw",
        "first_paint",
    ]
    out = {}
    for key in keys:
        values = [
            s["stages"][key]
            for s in samples
            if s.get("stages", {}).get(key) is not None
        ]
        if values:
            out[key] = statistics.median(values)
    return out


def run_one(
    page,
    cdp,
    profile_key: str | None,
    variant: str,
    index: int,
    mode: str,
    base_url: str,
    timeout_ms: int,
) -> dict:
    profile = PROFILES[profile_key] if profile_key else None
    url = f"{base_url}/index.html?variant={variant}&run={mode}{index}"

    take_ledger()  # discard anything left over from boot
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_function("() => window.__e1Result !== undefined", timeout=timeout_ms)
    result = page.evaluate("window.__e1Result")
    page_resources = page.evaluate("window.__e1Resources()")
    nav = page.evaluate("window.__e1Nav()")
    ledger = take_ledger()

    record = {
        "profile": profile_key,
        "variant": variant,
        "mode": mode,
        "index": index,
        "ok": bool(result.get("ok")),
    }
    if not result.get("ok"):
        record["error"] = result.get("error")
        record["worker_report"] = result.get("worker_report")
        return record

    marks = result["marks"]
    worker = result["worker"]
    phases = worker["phases"]
    resources = worker["resources"]
    origin = result["page_time_origin"]

    def res_end(name_suffix):
        for entry in resources:
            if entry["name"].endswith(name_suffix):
                return entry
        return None

    wasm = res_end("pyodide.asm.wasm")
    # Worker stamps are on the worker's own clock (its realm creation); shift
    # them onto the navigation clock before anything is compared.
    origin_delta = worker["worker_time_origin"] - origin
    stages = {
        "nav_start": 0.0,
        "worker_spawn": marks["worker_spawn"],
        "worker_module_start": worker["module_start"] + origin_delta,
        "wasm_download": (wasm["end"] - wasm["start"]) if wasm else None,
        "wasm_response_end": wasm["end"] if wasm else None,
        "pyodide_init": phases["pyodide_init"]["ms"]
        if phases.get("pyodide_init")
        else None,
        "pyodide_ready": phases["pyodide_init"]["end"]
        if phases.get("pyodide_init")
        else None,
        "packages_load": phases["packages_load"]["ms"]
        if phases.get("packages_load")
        else None,
        "packages_ready": phases["packages_load"]["end"]
        if phases.get("packages_load")
        else None,
        "compute": phases["compute"]["ms"],
        "compute_done": phases["compute"]["end"],
        "worker_done": worker["worker_done"] + origin_delta,
        "points_received": marks["points_received"],
        "draw": marks["draw_end"] - marks["draw_start"],
        "paint_after_draw": marks["paint"] - marks["draw_end"],
        "first_paint": result["first_paint_ms"],
    }
    # derived: the three segments that add up to the whole thing
    stages["nav_to_worker_spawn"] = stages["worker_spawn"]
    stages["spawn_to_first_paint"] = stages["first_paint"] - stages["worker_spawn"]

    worker_transfer = sum(
        r["transfer_size"] or r["encoded_body_size"] or 0 for r in resources
    )
    page_transfer = sum(
        r["transfer_size"] or r["encoded_body_size"] or 0 for r in page_resources
    )
    nav_transfer = (nav or {}).get("transfer_size") or 0
    ledger_wire = sum(e["wire_bytes"] for e in ledger)

    record.update(
        {
            "first_paint_ms": result["first_paint_ms"],
            "stages": stages,
            "bytes": {
                "server_wire": ledger_wire,
                "server_decoded": sum(e["decoded_bytes"] for e in ledger),
                "requests": len(ledger),
                "nav_transfer_size": nav_transfer,
                "page_transfer_size": page_transfer,
                "worker_transfer_size": worker_transfer,
                "total_transfer_size": nav_transfer + page_transfer + worker_transfer,
                "by_path": {
                    e["path"]: e["wire_bytes"] for e in ledger if e["wire_bytes"]
                },
            },
            "worker_resources": [
                {
                    "name": r["name"].rsplit("/", 1)[-1],
                    "ms": round(r["end"] - r["start"], 1),
                    "transfer_size": r["transfer_size"],
                    "encoded_body_size": r["encoded_body_size"],
                    "decoded_body_size": r["decoded_body_size"],
                }
                for r in resources
            ],
            "canvas": result.get("canvas"),
            "text_metrics": result.get("text_metrics"),
            "stats": result.get("stats"),
            "pyodide_version": result.get("pyodide_version"),
            "page_time_origin": origin,
            "worker_time_origin": worker["worker_time_origin"],
            "packages": result.get("packages"),
        }
    )
    if profile and profile["gate_ms"]:
        record["gate_ms"] = profile["gate_ms"]
        record["passed_gate"] = record["first_paint_ms"] < profile["gate_ms"]
    return record


def main() -> int:
    runs_per_profile = int(os.environ.get("E1_RUNS", "5"))
    sens_runs = int(os.environ.get("E1_SENS_RUNS", "3"))
    warm_runs = int(os.environ.get("E1_WARM", "1")) == 1
    profile_keys = [
        p for p in os.environ.get("E1_PROFILES", "fast4g,fast3g,slow3g").split(",") if p
    ]

    missing = [f for f in ("pyodide/pyodide.asm.wasm",) if not (STATIC / f).is_file()]
    if missing:
        sys.exit("static/ is empty - run `pixi run spike:e1:assets` first")

    from playwright.sync_api import sync_playwright

    RESULTS.mkdir(exist_ok=True)
    server, port = start_server()
    base_url = f"http://127.0.0.1:{port}"
    print(f"E1 static server on {base_url} (root {SITE.relative_to(REPO)})")

    runs: list[dict] = []
    console_errors: list[dict] = []
    browser_version = ""

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        browser_version = browser.version
        print(f"chromium {browser_version}")

        def new_page(profile_key: str | None, cache_disabled: bool):
            context = browser.new_context(
                viewport={"width": 1280, "height": 800}, device_scale_factor=1
            )
            page = context.new_page()
            page.set_default_timeout(600_000)
            page.on(
                "console",
                lambda m: (
                    console_errors.append({"type": m.type, "text": m.text})
                    if m.type == "error"
                    else None
                ),
            )
            page.on(
                "pageerror",
                lambda e: console_errors.append({"type": "pageerror", "text": str(e)}),
            )
            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")
            cdp.send("Network.setCacheDisabled", {"cacheDisabled": cache_disabled})
            if profile_key:
                cdp.send(
                    "Network.emulateNetworkConditions",
                    cdp_params(PROFILES[profile_key]),
                )
            return context, page, cdp

        # --- gated profiles: cold starts + a warm-cache control ---------------
        for profile_key in profile_keys:
            profile = PROFILES[profile_key]
            for i in range(runs_per_profile):
                context, page, cdp = new_page(profile_key, cache_disabled=True)
                rec = run_one(
                    page, cdp, profile_key, "baseline", i, "cold", base_url, 600_000
                )
                rec["throttle"] = cdp_params(profile)
                runs.append(rec)
                print(
                    f"  {profile_key:7s} cold #{i + 1} "
                    + (
                        f"{rec['first_paint_ms']:9.0f} ms  wire {rec['bytes']['server_wire']:>9,d} B"
                        if rec["ok"]
                        else f"FAILED {rec.get('error')}"
                    )
                )
                if rec["ok"] and i == 0:
                    page.screenshot(
                        path=str(RESULTS / f"first_paint_{profile_key}.png")
                    )

                if warm_runs and rec["ok"]:
                    cdp.send("Network.setCacheDisabled", {"cacheDisabled": False})
                    warm = run_one(
                        page, cdp, profile_key, "baseline", i, "warm", base_url, 600_000
                    )
                    warm["throttle"] = cdp_params(profile)
                    runs.append(warm)
                    print(
                        f"  {profile_key:7s} warm #{i + 1} "
                        + (
                            f"{warm['first_paint_ms']:9.0f} ms  wire {warm['bytes']['server_wire']:>9,d} B"
                            if warm["ok"]
                            else f"FAILED {warm.get('error')}"
                        )
                    )
                context.close()

        # --- sensitivity: what the numeric stack costs ------------------------
        for profile_key in SENSITIVITY_PROFILES:
            if profile_key not in profile_keys:
                continue
            for variant in ("no_numpy", "with_pandas"):
                for i in range(sens_runs):
                    context, page, cdp = new_page(profile_key, cache_disabled=True)
                    rec = run_one(
                        page, cdp, profile_key, variant, i, "cold", base_url, 600_000
                    )
                    rec["throttle"] = cdp_params(PROFILES[profile_key])
                    runs.append(rec)
                    print(
                        f"  {profile_key:7s} {variant:11s} #{i + 1} "
                        + (
                            f"{rec['first_paint_ms']:9.0f} ms  wire {rec['bytes']['server_wire']:>9,d} B"
                            if rec["ok"]
                            else f"FAILED {rec.get('error')}"
                        )
                    )
                    context.close()

        browser.close()

    server.shutdown()

    # ------------------------------------------------------------------ summary
    summary: dict[str, dict] = {}
    for profile_key in profile_keys:
        summary[profile_key] = {}
        for variant in VARIANTS:
            for mode in ("cold", "warm"):
                bucket = [
                    r
                    for r in runs
                    if r["profile"] == profile_key
                    and r["variant"] == variant
                    and r["mode"] == mode
                    and r["ok"]
                ]
                if not bucket:
                    continue
                summary[profile_key].setdefault(variant, {})[mode] = {
                    "first_paint_ms": summarize([r["first_paint_ms"] for r in bucket]),
                    "stages_median_ms": stage_table(bucket),
                    "bytes": {
                        "server_wire_median": statistics.median(
                            r["bytes"]["server_wire"] for r in bucket
                        ),
                        "total_transfer_size_median": statistics.median(
                            r["bytes"]["total_transfer_size"] for r in bucket
                        ),
                        "requests_median": statistics.median(
                            r["bytes"]["requests"] for r in bucket
                        ),
                    },
                    "gate_ms": PROFILES[profile_key]["gate_ms"],
                    "gated": PROFILES[profile_key]["gated"],
                    "failed_runs": sum(
                        1
                        for r in runs
                        if r["profile"] == profile_key
                        and r["variant"] == variant
                        and r["mode"] == mode
                        and not r["ok"]
                    ),
                }

    verdict = {}
    for profile_key in profile_keys:
        base = summary.get(profile_key, {}).get("baseline", {}).get("cold")
        if not base:
            verdict[profile_key] = {
                "judged": False,
                "reason": "no successful baseline cold run",
            }
            continue
        gate = PROFILES[profile_key]["gate_ms"]
        median = base["first_paint_ms"]["median"]
        p90 = base["first_paint_ms"]["p90"]
        verdict[profile_key] = {
            "judged": PROFILES[profile_key]["gated"],
            "gate_ms": gate,
            "median_ms": median,
            "p90_ms": p90,
            "passed_median": (median < gate) if gate else None,
            "passed_p90": (p90 < gate) if gate else None,
        }

    gated = [v for v in verdict.values() if v.get("judged")]
    payload = {
        "experiment": "E1 Pyodide cold start in a worker, throttled 4G/3G",
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(
            timespec="seconds"
        ),
        "gate": {"fast4g_ms": 3000, "fast3g_ms": 8000},
        "profiles": {
            key: {**PROFILES[key], "cdp": cdp_params(PROFILES[key])}
            for key in profile_keys
        },
        "variants": VARIANTS,
        "environment": {
            "browser": f"chromium {browser_version} (playwright, headless)",
            "playwright_python": importlib.metadata.version("playwright"),
            "pyodide": "314.0.7",
            "python_in_pyodide": next(
                (
                    r["stats"]["python"]
                    for r in runs
                    if r.get("stats") and r["stats"].get("python")
                ),
                None,
            ),
            "numpy": next(
                (
                    r["stats"]["numpy_version"]
                    for r in runs
                    if r.get("stats") and r["stats"].get("numpy_version")
                ),
                None,
            ),
            "node": subprocess.run(
                ["node", "--version"], capture_output=True, text=True, check=False
            ).stdout.strip()
            or None,
            "cpu_count": os.cpu_count(),
            "platform": platform.platform(),
            "viewport": "1280x800 @1x",
            "server": "python http.server (HTTP/1.1, gzip, Cache-Control: max-age=3600)",
            "throttling": "CDP Network.emulateNetworkConditions; Network.setCacheDisabled",
            "timing": "performance.now() from navigation start to the 2nd rAF after drawing",
        },
        "assets": assets_table(),
        "plan": {
            "cold_runs_per_profile": runs_per_profile,
            "warm_runs_per_profile": runs_per_profile if warm_runs else 0,
            "sensitivity_runs": sens_runs,
            "sensitivity_profiles": [
                p for p in SENSITIVITY_PROFILES if p in profile_keys
            ],
        },
        "summary": summary,
        "verdict": verdict,
        "verdict_all_gates_passed": bool(gated)
        and all(v["passed_median"] for v in gated),
        "console_errors": console_errors[:40],
        "runs": runs,
    }

    out = RESULTS / "e1_results.json"
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    print()
    print(
        f"payload: {payload['assets']['total_wire_bytes']:,d} B on the wire "
        f"({payload['assets']['total_disk_bytes']:,d} B on disk)"
    )
    for profile_key, table in summary.items():
        base = table.get("baseline", {}).get("cold")
        if not base:
            continue
        fp = base["first_paint_ms"]
        gate = PROFILES[profile_key]["gate_ms"]
        tag = "" if not gate else (" PASS" if fp["median"] < gate else " FAIL")
        print(
            f"  {profile_key:7s} cold median {fp['median']:8.0f} ms  p90 {fp['p90']:8.0f} ms"
            f"  wire {base['bytes']['server_wire_median']:>9,.0f} B"
            + (f"  gate {gate} ms{tag}" if gate else "")
        )
        warm = table.get("baseline", {}).get("warm")
        if warm:
            wf = warm["first_paint_ms"]
            print(
                f"  {profile_key:7s} warm median {wf['median']:8.0f} ms  p90 {wf['p90']:8.0f} ms"
                f"  wire {warm['bytes']['server_wire_median']:>9,.0f} B"
            )
        for variant in ("no_numpy", "with_pandas"):
            var = table.get(variant, {}).get("cold")
            if var:
                vf = var["first_paint_ms"]
                delta = vf["median"] - fp["median"]
                print(
                    f"  {profile_key:7s} {variant:11s} median {vf['median']:8.0f} ms"
                    f"  ({delta:+.0f} ms vs baseline)"
                    f"  wire {var['bytes']['server_wire_median']:>9,.0f} B"
                )
    print()
    print(
        f"verdict: {'all gates passed' if payload['verdict_all_gates_passed'] else 'gate NOT met'}"
    )
    print(f"  -> {out.relative_to(REPO)}")
    if console_errors:
        print(f"  ({len(console_errors)} console errors captured)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
