// E1 worker: this is the unit whose cold start we measure.
//
// Everything that costs bytes or CPU on the path to the first plot happens
// here and nowhere else: fetch the wasm, boot CPython, load the numeric stack,
// run the computation, hand back one transferable Float32 buffer.  The main
// thread only draws.
//
// The worker keeps its own performance timeline (its timeOrigin is the moment
// this realm was created, not the navigation), so every timestamp we emit is
// reported in the worker's own clock.  The page converts to navigation-relative
// milliseconds with `worker_time_origin - page_time_origin`.

import { loadPyodide } from "./static/pyodide/pyodide.mjs";

const now = () => performance.now();
const module_start = now();

// The workload is deliberately plot-shaped: 20k samples of a damped sine
// mixture, mean-pooled down to the 4k vertices a viewer would actually stroke.
// Same workload for both code paths, so "no numpy" measures the dependency,
// not a smaller job.
const PY_NUMPY = `
import json
import math
import sys
import numpy as np

N = int(WORKLOAD_SAMPLES)
K = int(WORKLOAD_POINTS)
x = np.linspace(0.0, 6.0 * math.pi, N, dtype=np.float64)
y = np.sin(x) * np.exp(-x / 20.0) + 0.12 * np.sin(7.3 * x) / (1.0 + x)
step = N // K
xs = x[: step * K].reshape(K, step).mean(axis=1).astype(np.float32)
ys = y[: step * K].reshape(K, step).mean(axis=1).astype(np.float32)
STATS = json.dumps({
    "backend": "numpy",
    "python": "%d.%d.%d" % sys.version_info[:3],
    "numpy_version": np.__version__,
    "samples": int(N),
    "points": int(K),
    "y_min": float(ys.min()),
    "y_max": float(ys.max()),
    "y_mean": float(ys.mean()),
})
xs.tobytes() + ys.tobytes()
`;

const PY_PURE = `
import json
import math
import sys

N = int(WORKLOAD_SAMPLES)
K = int(WORKLOAD_POINTS)
xs = [0.0] * N
ys = [0.0] * N
for i in range(N):
    t = 6.0 * math.pi * i / (N - 1)
    xs[i] = t
    ys[i] = math.sin(t) * math.exp(-t / 20.0) + 0.12 * math.sin(7.3 * t) / (1.0 + t)
step = N // K
ox = [0.0] * K
oy = [0.0] * K
for p in range(K):
    sx = 0.0
    sy = 0.0
    for j in range(p * step, (p + 1) * step):
        sx += xs[j]
        sy += ys[j]
    ox[p] = sx / step
    oy[p] = sy / step
STATS = json.dumps({
    "backend": "pure-python",
    "python": "%d.%d.%d" % sys.version_info[:3],
    "numpy_version": None,
    "samples": int(N),
    "points": int(K),
    "y_min": min(oy),
    "y_max": max(oy),
    "y_mean": sum(oy) / K,
})
import struct
struct.pack("<%df" % K, *ox) + struct.pack("<%df" % K, *oy)
`;

function resourceEntries() {
  // Requests issued by this worker (wasm, stdlib zip, wheels) land on the
  // worker's own Resource Timing buffer; the page cannot see them.
  return performance.getEntriesByType("resource").map((e) => ({
    name: e.name,
    initiator_type: e.initiatorType,
    start_time: e.startTime, // worker-relative ms
    response_end: e.responseEnd,
    duration: e.duration,
    transfer_size: e.transferSize,
    encoded_body_size: e.encodedBodySize,
    decoded_body_size: e.decodedBodySize,
    render_blocking: e.renderBlockingStatus,
  }));
}

function bytesFetched(entries) {
  // transferSize is 0 for responses served without CORS-safelisted timing
  // headers that the browser cannot attribute; fall back to encoded body size.
  return entries.reduce((n, e) => n + (e.transfer_size || e.encoded_body_size || 0), 0);
}

self.onmessage = async (event) => {
  const { variant = "baseline", workload = { samples: 20000, points: 4000 } } =
    event.data || {};

  const report = {
    variant,
    worker_time_origin: performance.timeOrigin,
    module_start,
    phases: {},
    packages: [],
  };

  try {
    const indexURL = new URL("./static/pyodide/", self.location.href).href;

    let t = now();
    const pyodide = await loadPyodide({ indexURL });
    report.phases.pyodide_init = { start: t, end: now() };

    if (variant !== "no_numpy") {
      report.packages = variant === "with_pandas" ? ["numpy", "pandas"] : ["numpy"];
      t = now();
      await pyodide.loadPackage(report.packages);
      report.phases.packages_load = { start: t, end: now() };
    }

    pyodide.globals.set("WORKLOAD_SAMPLES", workload.samples);
    pyodide.globals.set("WORKLOAD_POINTS", workload.points);

    t = now();
    const pyproxy = pyodide.runPython(variant === "no_numpy" ? PY_PURE : PY_NUMPY);
    // pyodide hands a Python `bytes` back as a PyProxy; `toJs()` copies it into
    // a real Uint8Array on the JS heap, which is what we can transfer.
    const view = pyproxy instanceof Uint8Array ? pyproxy : pyproxy.toJs();
    const stats = JSON.parse(pyodide.globals.get("STATS"));
    report.phases.compute = { start: t, end: now() };

    // One copy out of the Pyodide heap, then hand the buffer over without a
    // second copy: bulk float32 in, bulk float32 out, no per-element JSON.
    const payload =
      view.byteOffset === 0 && view.byteLength === view.buffer.byteLength
        ? view.buffer
        : view.buffer.slice(view.byteOffset, view.byteOffset + view.byteLength);
    if (typeof pyproxy.destroy === "function") pyproxy.destroy();

    report.resources = resourceEntries();
    report.bytes_fetched_in_worker = bytesFetched(report.resources);
    report.stats = stats;
    report.pyodide_version = pyodide.version;
    report.worker_done = now();

    self.postMessage({ type: "result", report, payload }, [payload]);
  } catch (err) {
    report.resources = resourceEntries();
    report.bytes_fetched_in_worker = bytesFetched(report.resources);
    self.postMessage({
      type: "error",
      report,
      message: String((err && err.stack) || err),
    });
  }
};
