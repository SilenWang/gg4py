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
//
// SIL-826（M3-4）之后这里也是**编辑器**的执行器：`run-source` 跑任意用户源码，走
// `ggcore.script.run_script`（与桌面端同一个函数，IR 才能逐字节一致），stdout /
// stderr 逐行回推，错误回一份只有用户栈帧的 traceback。两条路径共用同一个
// worker，是因为「浏览器里跑代码」只该有一个执行器——否则运行时页与编辑器页
// 会用两份不同的加载顺序，量出来的耗时也不能互相引用。


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

// --- SIL-826：编辑器（任意源码）------------------------------------------------
// `detect_needs` 与 `run_script` 都在 ggcore 里（`ggcore/script.py`），桌面端跑的是
// 同一个函数——「同一段脚本两端 IR 逐字节相同」才不是一句口号。
const PY_EDITOR_NEEDS = `
import json
from ggcore.script import detect_needs
GG_NEEDS = json.dumps(detect_needs(GG_SOURCE))
`;

const PY_EDITOR_RUN = `
import ast, json
from ggcore.script import ScriptError, run_script

_error = None
_result = None
try:
    variables = {}
    if GG_INLINE_DATA:
        try:
            variables["DATA"] = ast.literal_eval(GG_INLINE_DATA)
        except (ValueError, SyntaxError) as exc:
            raise ScriptError("数据面板里的内联数据不是合法的 Python 字面量：%s" % (exc,))
    _result = run_script(GG_SOURCE, filename=GG_PATH, variables=variables)
except ScriptError as exc:
    _error = exc.as_dict()
except BaseException as exc:
    import traceback
    _error = {
        "message": "%s: %s" % (type(exc).__name__, exc),
        "traceback": traceback.format_exc(),
    }
GG_ERROR = json.dumps(_error)
GG_META = json.dumps(_result.meta if _result is not None else {})
GG_IR = _result.ir_bytes if _result is not None else b""
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

  // 编辑器要看到用户 `print()` 的东西：stdout / stderr 逐行回推（batched 是
  // Pyodide 的「按行缓冲」口径，不会把一句 print 拆成几次消息）。
  pyodide.setStdout({ batched: (text) => post({ type: "stdout", text }) });
  pyodide.setStderr({ batched: (text) => post({ type: "stderr", text }) });

  const unpackStart = now();
  stage("archive", "gg4py.zip");
  const archive = await archivePromise;
  timings.archive_fetch_ms = now() - archiveStart;
  pyodide.unpackArchive(archive, "zip", { extractDir: "/app" });
  timings.archive_ms = now() - unpackStart;
  // 编辑器把数据面板的 CSV 写到 `/app/data.csv`，脚本用相对路径 `data.csv` 读它
  // ——桌面端（`tools/editor/check_editor.py`）在临时目录里放同名文件跑同一段
  // 代码，两端都不需要在源码里写死绝对路径。
  pyodide.runPython('import os; os.chdir("/app")');

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

// --- 编辑器：任意用户源码 -----------------------------------------------------

/**
 * 跑一段用户代码，回 `editor-result`（IR 字节 + 元数据）或 `editor-error`。
 *
 * 包按「静态扫描 + 显式 needs」加载：numpy 一定先装（ggcore 自己 import 它，
 * 不装就连 `detect_needs` 都 import 不了），其余按扫描结果补。
 */
async function runSource({ source, path, csv, inlineData }) {
  const started = now();
  const scriptPath = path || "/app/editor_script.py";
  pyodide.globals.set("GG_SOURCE", source);
  pyodide.globals.set("GG_PATH", scriptPath);
  pyodide.globals.set("GG_INLINE_DATA", inlineData || null);

  // 数据面板的 CSV：写进虚拟文件系统，脚本用相对路径 `data.csv` 读（cwd = /app）。
  if (typeof csv === "string" && csv.length > 0) {
    pyodide.FS.writeFile("/app/data.csv", new TextEncoder().encode(csv));
    stage("data", "data.csv");
  } else if (pyodide.FS.analyzePath("/app/data.csv").exists) {
    pyodide.FS.unlink("/app/data.csv");
  }

  const packagesMs = await loadPackages(["numpy"]);
  const coreMs = await ensureCore();
  pyodide.runPython(PY_EDITOR_NEEDS);
  const needs = JSON.parse(pyodide.globals.get("GG_NEEDS"));
  const extraMs = await loadPackages(["numpy", ...needs]);

  stage("run", "editor");
  const runStart = now();
  pyodide.runPython(PY_EDITOR_RUN);
  const error = JSON.parse(pyodide.globals.get("GG_ERROR"));
  const meta = JSON.parse(pyodide.globals.get("GG_META"));
  const runMs = now() - runStart;

  if (error !== null) {
    post({ type: "editor-error", ...error, run_ms: runMs, total_ms: now() - started });
    return;
  }

  const proxy = pyodide.globals.get("GG_IR");
  const bytes = proxy instanceof Uint8Array ? proxy : proxy.toJs();
  if (typeof proxy.destroy === "function") proxy.destroy();
  const payload = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  post(
    {
      type: "editor-result",
      meta: {
        ...meta,
        needs,
        run_ms: runMs,
        packages_ms: packagesMs + extraMs,
        core_import_ms: coreMs,
        worker_total_ms: now() - started,
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
    if (message.type === "run-source") {
      await runSource(message);
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
