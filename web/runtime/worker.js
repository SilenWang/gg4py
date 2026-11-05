// SIL-824 · Pyodide worker：把 ggcore **整棵**装进 wasm，数值栈按需加载。
//
// 三条线在这里分开，因为它们决定「首访 4G ≤ 12 s / warm ≤ 3 s」能不能站住：
//
//   1. 运行时（pyodide.mjs / asm.wasm / stdlib）来自 `./vendor/pyodide/`，同源、
//      无 CDN；Service Worker（`sw.js`）把下载进度报给页面，并把响应缓存住供
//      warm 启动直接命中。
//   2. ggcore / ggio 打成 `./vendor/gg4py.zip`（`pixi run pyodide:assets` 生成），
//      这里自己 fetch（能报字节进度）后 `unpackArchive` 到 `/app`。目录结构与仓库
//      一致（`/app/src/ggcore`、`/app/src/ggio`），不造第二套布局。
//   3. **numpy / contourpy / pandas 一个都不在 boot 里**：boot 只到「解包完源码 +
//      pyodide 可用」。每次跑示例先读该示例的 `needs`（`ast` 静态解析，不执行
//      代码）再 `loadPackage`，然后才 `import ggcore` —— ggcore 自己 import numpy，
//      所以 numpy 的下载时机等于「第一次真的要出图」。
//
// 页面只拿两样东西：IR 字节（transferable）与一份元数据（摘要 / 版本 / 耗时）。

import { loadPyodide } from "./vendor/pyodide/pyodide.mjs";

const now = () => performance.now();
const VENDOR = new URL("./vendor/", self.location.href).href;
const PYODIDE_DIR = VENDOR + "pyodide/";

let pyodide = null;
let manifest = null;
let ggcoreInfo = null;
/** 已经 `loadPackage` 过的包（页面要展示「哪些装了、哪些没装」）。 */
const loaded = new Set();
const timings = {};

function post(message, transfer) {
  if (transfer) self.postMessage(message, transfer);
  else self.postMessage(message);
}

function stage(name, detail = "") {
  post({ type: "stage", stage: name, detail, at: now() });
}

/** 读一份响应体，边读边把字节数报给页面（`gg4py.zip` 用）。 */
async function fetchWithProgress(url, label) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${label}: HTTP ${response.status}`);
  const total = Number(response.headers.get("content-length")) || 0;
  if (response.body === null) return new Uint8Array(await response.arrayBuffer());
  const reader = response.body.getReader();
  const chunks = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.byteLength;
    post({ type: "fetch-progress", file: label, loaded: received, total });
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

//: 静态读 `needs`（不执行示例代码）：`ast.literal_eval` 只认字面量，安全且无副作用。
const PY_NEEDS = `
import ast, json
tree = ast.parse(GG_DEMO_SOURCE)
needs = []
for node in tree.body:
    targets = node.targets if isinstance(node, ast.Assign) else []
    if any(isinstance(t, ast.Name) and t.id == "needs" for t in targets):
        needs = ast.literal_eval(node.value)
GG_NEEDS = json.dumps(list(needs))
`;

const PY_IMPORT = `
import json, sys
sys.path.insert(0, "/app/src")
import ggcore
from ggcore import ir
GG_CORE = json.dumps({
    "ggcore": getattr(ggcore, "__version__", "unknown"),
    "ir_version": ir.IR_VERSION_STR,
    "cbor": ir.CBOR_BACKEND,
    "python": "%d.%d.%d" % sys.version_info[:3],
})
`;

const PY_RUN = `
import hashlib, json, time
import numpy as np
from ggcore import ir
from ggcore.metrics.fallback import default_metrics
from ggcore.plotspec import build_scene

namespace = {"__name__": "gg4py_demo", "__file__": GG_DEMO_PATH}
exec(compile(GG_DEMO_SOURCE, GG_DEMO_PATH, "exec"), namespace)
spec = namespace["build"]()

build_start = time.perf_counter()
scene = build_scene(spec, metrics=default_metrics())
build_ms = (time.perf_counter() - build_start) * 1000.0

encode_start = time.perf_counter()
data = ir.encode(scene)
encode_ms = (time.perf_counter() - encode_start) * 1000.0

roundtrip = ir.scene_equal(ir.decode(data), scene)
GG_RESULT = json.dumps({
    "digest": hashlib.sha256(data).hexdigest(),
    "bytes": len(data),
    "nodes": sum(1 for _ in ir.walk(scene.root)),
    "build_ms": round(build_ms, 3),
    "encode_ms": round(encode_ms, 3),
    "roundtrip": roundtrip,
    "numpy": np.__version__,
    "metrics": type(default_metrics()).__name__,
})
data
`;

async function boot() {
  const started = now();
  manifest = await (await fetch(VENDOR + "manifest.json")).json();
  stage("runtime", `pyodide ${manifest.pyodide_version ?? ""}`);

  // gg4py.zip（0.72 MB）与运行时**并行**下载：它和 wasm/stdlib 抢的是同一条链路，
  // 但两者都不依赖对方，串起来会白白多等一个 RTT + 一次解压前的空窗。
  const archiveStart = now();
  const archivePromise = fetchWithProgress(VENDOR + "gg4py.zip", "gg4py.zip");

  pyodide = await loadPyodide({ indexURL: PYODIDE_DIR });
  timings.runtime_ms = now() - started;
  stage("runtime-ready", `pyodide ${pyodide.version}`);

  const unpackStart = now();
  stage("archive", "gg4py.zip");
  const archive = await archivePromise;
  timings.archive_fetch_ms = now() - archiveStart;
  pyodide.unpackArchive(archive, "zip", { extractDir: "/app" });
  timings.archive_ms = now() - unpackStart;

  stage("ready", "运行时就绪（数值栈尚未加载）");
  post({
    type: "ready",
    info: {
      pyodide: pyodide.version,
      python: manifest.abi?.python ?? null,
      abi: manifest.abi ?? null,
      archive: manifest.archive ?? null,
    },
    timings: { ...timings, boot_ms: now() - started },
    packages: [...loaded],
  });
}

async function ensureCore() {
  if (ggcoreInfo !== null) return 0;
  const started = now();
  pyodide.runPython(PY_IMPORT);
  ggcoreInfo = JSON.parse(pyodide.globals.get("GG_CORE"));
  timings.core_import_ms = now() - started;
  stage("ggcore", `ggcore ${ggcoreInfo.ggcore} · ${ggcoreInfo.cbor}`);
  post({ type: "core", info: ggcoreInfo });
  return timings.core_import_ms;
}

async function loadPackages(needs) {
  const missing = [...new Set(needs.map(String))].filter((name) => !loaded.has(name));
  if (missing.length === 0) return 0;
  const started = now();
  // 页面按这条消息把对应 wheel 的字节数加进进度分母（pandas 的依赖也在其中）。
  post({ type: "packages", packages: missing, at: now() });
  stage("packages", missing.join(" + "));
  await pyodide.loadPackage(missing);
  for (const name of missing) loaded.add(name);
  const elapsed = now() - started;
  timings.packages_ms = (timings.packages_ms ?? 0) + elapsed;
  post({ type: "packages-loaded", packages: [...loaded], ms: elapsed });
  stage("packages-ready", [...loaded].join(" + "));
  return elapsed;
}

async function runDemo({ name, source }) {
  const started = now();
  pyodide.globals.set("GG_DEMO_SOURCE", source);
  pyodide.globals.set("GG_DEMO_PATH", `/app/web/runtime/demos/${name}.py`);

  pyodide.runPython(PY_NEEDS);
  const needs = JSON.parse(pyodide.globals.get("GG_NEEDS"));
  const packagesMs = await loadPackages(needs);
  const coreMs = await ensureCore();

  stage("run", name);
  const runStart = now();
  const proxy = pyodide.runPython(PY_RUN);
  const bytes = proxy instanceof Uint8Array ? proxy : proxy.toJs();
  if (typeof proxy.destroy === "function") proxy.destroy();
  const runMs = now() - runStart;
  const result = JSON.parse(pyodide.globals.get("GG_RESULT"));

  const payload = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  post(
    {
      type: "result",
      name,
      meta: {
        ...result,
        needs,
        run_ms: runMs,
        packages_ms: packagesMs,
        core_import_ms: coreMs,
        total_ms: now() - started,
        pyodide: pyodide.version,
        python: ggcoreInfo?.python ?? null,
        packages: [...loaded],
      },
      payload,
    },
    [payload],
  );
}

self.onmessage = async (event) => {
  const message = event.data || {};
  try {
    if (message.type === "boot") {
      await boot();
      return;
    }
    if (message.type === "run") {
      await runDemo(message);
      return;
    }
    throw new Error(`unknown message: ${message.type}`);
  } catch (error) {
    post({
      type: "error",
      stage: message.type,
      message: String((error && error.message) || error),
      traceback: typeof error === "object" && error !== null ? String(error.stack || "") : "",
    });
  }
};
