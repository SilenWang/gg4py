// SIL-824 · 页面侧：进度、示例调度、IR → DOM SVG。
//
// 页面自己不碰 wasm，也不认识 ggcore：它只做三件事——
//
//   1. 把「加载进度」画出来。字节数来自 Service Worker（它 tee 了每个 vendor
//      响应），分母来自 `vendor/manifest.json` + 每次跑示例时点名的包；因此
//      「已下载 9.8 / 13.2 MB（74%）」是真实传输量，不是估算。
//   2. 起 worker，把示例源码交给它。
//   3. 拿回 IR 字节，用 **web/viewer** 的 TS 渲染器（零 wasm）画成 DOM SVG。
//
// 出图口径与 E1 的「首图」一致：IR 到手 → 渲染 → 等两帧（第二帧证明已合成）→
// 记 `first_plot_ms`。字体是 `viewer/fonts.css` 的受管拉丁字面，35 MB 的 CJK 字面
// 不进首屏（示例文字是 ASCII，见 demos/*.py 的说明）。

// SIL-830：首屏的每一段**都不许串行**。`index.html` 的内联预载在 HTML 解析期就把
// worker 的 `boot` 发出去（warm），这里再把 manifest / 首图示例源码 / 渲染器三件事
// 与运行时的下载并起来。冷启动唯一必须等的只有「SW 接管」——不等它，pyodide 的请求
// 会绕开 Service Worker，字节进度与 warm 缓存一起丢。
const START = window.__ggPerf?.start ?? performance.now();

// 渲染器**按需**取：它是 4 个 ES 模块，放在关键路径上等于多两个 RTT 的等待；
// 而它真正要用是在 IR 回来之后（那时早就并行下载完了）。这里在 boot 里提前发起，
// 让它在运行时下载的同时到齐。
let renderer = null;

async function loadRenderer() {
  if (renderer === null) {
    const [ir, render] = await Promise.all([
      import("../viewer/dist/ir.js"),
      import("../viewer/dist/render.js"),
    ]);
    renderer = { decodeScene: ir.decodeScene, renderScene: render.renderScene };
  }
  return renderer;
}

const now = () => performance.now();

//: 首图（冷启动的验收终点就是它）：源码在 boot 里与运行时并行取。
const FIRST_DEMO = "basic";
//: 已取到的示例源码（`basic` 在 boot 里就填好，点击不会再等一个 RTT）。
const sources = new Map();

//: 示例清单：`source` 在点击时取（同一份文件桌面端也在跑，见 demos/*.py）。
const DEMOS = [
  { name: "basic", label: "散点 + 折线", note: "numpy" },
  { name: "contour", label: "等值线填充", note: "numpy + contourpy" },
  { name: "pandas", label: "pandas 输入", note: "numpy + pandas" },
];

//: 包 → 会下载哪些 wheel（用于把字节数计进进度分母；依赖是 lock 里的固定几条）。
const PACKAGE_WHEELS = {
  numpy: [/^numpy-/],
  contourpy: [/^contourpy-/],
  pandas: [/^pandas-/, /^python_dateutil-/, /^pytz-/, /^six-/],
};

const $ = (selector) => document.querySelector(selector);
const bar = $("#bar");
const stageEl = $("#stage");
const badgeState = $("#badge-state");
const badgeBytes = $("#badge-bytes");
const badgePackages = $("#badge-packages");
const badgeCache = $("#badge-cache");
const demosEl = $("#demos");
const stageArea = $("#stage-area");
const placeholder = $("#placeholder");
const resultEl = $("#result");
const runtimeEl = $("#runtime-info");
const timelineEl = $("#timeline");
const errorEl = $("#error");

const state = {
  started: START,
  //: 启动各步的时刻（页面时钟，navigation 起点）：warm 的 3 s 预算要能拆开看。
  marks: { module_eval: START },
  stage: "loading",
  ready: false,
  core: null,
  info: null,
  packages: [],
  error: null,
  firstPlotMs: null,
  timings: {},
  results: {},
  progress: { loaded: 0, total: 0, pct: 0 },
  cache: { hits: 0, misses: 0 },
};
/** 每一条进度快照（判定「加载进度可见」用它，导出给 Playwright）。 */
const progressLog = [];
/** 规划过的文件（相对 `vendor/`）→ 字节数：进度分母。 */
const planned = new Map();
/** 已下载字节（按文件计，取最大值，避免重复上报把总量算多）。 */
const received = new Map();

let manifest = null;
let worker = null;
let pending = null;
let current = null;

function bytesLabel(value) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(2)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(0)} KB`;
  return `${value} B`;
}

function recordProgress(extra = {}) {
  // 分母由「规划的文件」与「实际收到更多字节的文件」二者取大：manifest 与真实
  // 传输量偶有出入（比如 Range 请求、压缩容器），进度条不该因此越过 100%。
  for (const [name, value] of received) {
    const plan = planned.get(name) ?? 0;
    if (value > plan) planned.set(name, value);
  }
  const loaded = [...received.values()].reduce((sum, value) => sum + value, 0);
  const total = [...planned.values()].reduce((sum, value) => sum + value, 0);
  const pct = total > 0 ? Math.min(1, loaded / total) : 0;
  state.progress = { loaded, total, pct };
  bar.style.width = `${(pct * 100).toFixed(1)}%`;
  badgeBytes.textContent = total > 0 ? `${bytesLabel(loaded)} / ${bytesLabel(total)}` : "0 B";
  const entry = { at: now() - START, pct, loaded, total, stage: state.stage, ...extra };
  progressLog.push(entry);
  return entry;
}

function setStage(name, detail = "") {
  state.stage = name;
  stageEl.dataset.state = name === "error" ? "error" : name === "ready" ? "ok" : "loading";
  stageEl.textContent = detail ? `${name} · ${detail}` : name;
  recordProgress();
}

function setState(text, kind) {
  badgeState.textContent = text;
  badgeState.dataset.state = kind ?? "";
}

function planFile(name) {
  if (planned.has(name)) return;
  const entry = manifest?.files?.find((item) => item.file === name);
  const bytes = entry?.bytes ?? 0;
  if (bytes > 0) planned.set(name, bytes);
}

function planPackage(name) {
  const patterns = PACKAGE_WHEELS[name] ?? [new RegExp(`^${name}-`)];
  for (const entry of manifest?.files ?? []) {
    const file = entry.file.replace(/^vendor\//, "");
    const base = file.replace(/^pyodide\//, "");
    if (!file.startsWith("pyodide/")) continue;
    if (patterns.some((pattern) => pattern.test(base))) planned.set(file, entry.bytes);
  }
}

function noteVendorProgress(message) {
  // SW 报的是 URL 路径（`/runtime/vendor/pyodide/x`）；manifest 记的是相对 `vendor/` 的路径。
  const index = message.file.indexOf("/vendor/");
  if (index < 0) return;
  const name = message.file.slice(index + "/vendor/".length);
  if (name === "manifest.json") return;
  if (!planned.has(name)) {
    // 没规划到的文件（例如还没声明的包）也要计入，否则进度会卡在 99% 不动。
    planFile(name);
    if (!planned.has(name)) return;
  }
  const previous = received.get(name) ?? 0;
  const value = message.cached ? (planned.get(name) ?? 0) : message.loaded ?? 0;
  if (value <= previous) return;
  received.set(name, value);
  if (message.cached) state.cache.hits += 1;
  else state.cache.misses += 1;
  badgeCache.textContent = `缓存：命中 ${state.cache.hits}`;
  recordProgress({ file: name });
}

async function renderResult(name, meta, payload) {
  state.marks.result_in = now();
  const { decodeScene, renderScene } = await loadRenderer();
  const scene = decodeScene(new Uint8Array(payload));
  const result = renderScene(scene);
  stageArea.replaceChildren(result.svg);
  result.svg.classList.add("gg-svg");
  state.marks.render_done = now();
  current = { name, meta, scene };
  state.results[name] = { ...meta };
  setState(`${name} 出图完成`, "ok");

  const rows = [
    ["示例", name],
    ["IR 字节", `${meta.bytes} B`],
    ["IR 节点", String(meta.nodes)],
    ["sha256", meta.digest.slice(0, 24) + "…"],
    ["build", `${meta.build_ms} ms`],
    ["encode", `${meta.encode_ms} ms`],
    ["本次总耗时", `${Math.round(meta.total_ms)} ms`],
    ["回环一致", meta.roundtrip ? "是" : "否"],
    ["包", meta.packages.length ? meta.packages.join(" + ") : "无"],
  ];
  resultEl.replaceChildren(
    ...rows.flatMap(([key, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = key;
      const dd = document.createElement("dd");
      dd.textContent = value;
      return [dt, dd];
    }),
  );

  if (state.firstPlotMs === null) {
    // 首图：再等两帧（第二帧证明已合成）才记时，与 E1 的口径一致。
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        state.firstPlotMs = now();
        state.timings.first_plot_ms = state.firstPlotMs;
        timelineEl.append(timelineRow("first_plot", state.firstPlotMs));
        recordProgress({ first_plot: true });
      });
    });
  }
}

function timelineRow(label, ms) {
  const row = document.createElement("li");
  const key = document.createElement("b");
  key.textContent = label;
  const value = document.createElement("span");
  value.textContent = `${ms.toFixed(0)} ms`;
  row.append(key, value);
  return row;
}

function showError(message, traceback) {
  state.error = { message, traceback };
  stageEl.dataset.state = "error";
  stageEl.textContent = `失败：${message}`;
  setState("失败", "bad");
  errorEl.hidden = false;
  errorEl.textContent = traceback ? `${message}\n\n${traceback}` : message;
}

async function demoSource(name) {
  if (sources.has(name)) return sources.get(name);
  const response = await fetch(`./demos/${name}.py`);
  if (!response.ok) throw new Error(`demo ${name}: HTTP ${response.status}`);
  const source = await response.text();
  sources.set(name, source);
  return source;
}

async function runDemo(name) {
  if (!state.ready) throw new Error("运行时尚未就绪");
  if (pending) throw new Error("上一次出图还没结束");
  setState(`${name} 计算中`);
  setStage("run", name);
  const source = await demoSource(name);
  pending = new Promise((resolve, reject) => {
    worker.__resolve = resolve;
    worker.__reject = reject;
  });
  worker.postMessage({ type: "run", name, source });
  try {
    return await pending;
  } finally {
    pending = null;
  }
}

function selectDemo(name) {
  for (const button of demosEl.querySelectorAll("button")) {
    button.setAttribute("aria-selected", String(button.dataset.name === name));
  }
}

function buildDemoButtons() {
  for (const demo of DEMOS) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.name = demo.name;
    button.setAttribute("aria-selected", "false");
    button.textContent = demo.label;
    const note = document.createElement("small");
    note.textContent = `needs: ${demo.note}`;
    button.append(note);
    button.addEventListener("click", () => {
      selectDemo(demo.name);
      runDemo(demo.name).catch((error) => showError(String(error.message || error)));
    });
    demosEl.append(button);
  }
}

function handleServiceWorkerMessage(message) {
  if (message.type === "vendor-progress") noteVendorProgress(message);
  else if (message.type === "vendor-progress-error") {
    console.warn("vendor progress failed", message);
  }
}

function watchServiceWorkerMessages() {
  // 内联预载已经把监听器装好了（warm 时进度可能已经来过一批），这里接管队列；
  // 没有内联段时（别的页面 / 老 HTML）退回自己装。
  if (typeof window.__ggVendorSink === "function") {
    window.__ggVendorSink(handleServiceWorkerMessage);
    return;
  }
  navigator.serviceWorker.addEventListener("message", (event) =>
    handleServiceWorkerMessage(event.data || {}),
  );
}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || !location.protocol.startsWith("http")) return null;
  try {
    const registration = await navigator.serviceWorker.register("./sw.js", { scope: "./" });
    watchServiceWorkerMessages();
    return registration;
  } catch (error) {
    console.warn("Service Worker 不可用，进度改为按阶段显示", error);
    return null;
  }
}

/**
 * 冷启动必须先让 SW 接管，worker 才在它的覆盖下（否则 pyodide 的请求绕开 SW：
 * 没有逐字节进度，warm 也没有缓存）。warm 时页面一上来就有 controller，直接放行。
 */
async function serviceWorkerGate() {
  if (!("serviceWorker" in navigator) || !location.protocol.startsWith("http")) return;
  if (navigator.serviceWorker.controller) return;
  try {
    await navigator.serviceWorker.ready;
  } catch (error) {
    console.warn("Service Worker 未就绪，按无缓存路径继续", error);
  }
}

async function handleWorkerMessage(event) {
  const message = event.data || {};
  switch (message.type) {
    case "stage":
      setStage(message.stage, message.detail);
      return;
    case "fetch-progress": {
      // worker 自己读 gg4py.tar 时的字节数；SW 那条可能还没到，取两者的最大值。
      if (!planned.has(message.file)) planFile(message.file);
      const previous = received.get(message.file) ?? 0;
      if (message.loaded > previous) {
        received.set(message.file, message.loaded);
        recordProgress({ file: message.file });
      }
      return;
    }
    case "packages":
      for (const name of message.packages) planPackage(name);
      recordProgress({ packages: message.packages });
      return;
    case "packages-loaded":
      state.packages = message.packages;
      badgePackages.textContent = `包：${message.packages.length ? message.packages.join(" + ") : "无"}`;
      timelineEl.append(timelineRow("packages", message.ms));
      return;
    case "core":
      state.core = message.info;
      renderRuntimeInfo();
      return;
    case "ready":
      state.ready = true;
      state.readyAt = now();
      // progressLog 的 `at` 是「相对模块求值」的毫秒；懒加载判定要同一把尺子。
      state.readyRel = state.readyAt - START;
      state.marks.worker_ready = state.readyAt;
      // 「boot 阶段有没有装包」的判据：ready 那一刻的快照（之后首图会立刻加载 numpy）。
      state.packagesAtReady = [...state.packages];
      state.info = message.info;
      state.timings = { ...state.timings, ...message.timings };
      badgePackages.textContent = "包：无（懒加载）";
      setState("就绪");
      setStage("ready", `pyodide ${message.info.pyodide}`);
      renderRuntimeInfo();
      for (const key of ["runtime_ms", "archive_ms", "boot_ms"]) {
        if (message.timings[key] !== undefined) timelineEl.append(timelineRow(key, message.timings[key]));
      }
      placeholder?.remove();
      if (worker.__readyResolve) worker.__readyResolve(state);
      return;
    case "result": {
      await renderResult(message.name, message.meta, message.payload);
      const resolve = worker.__resolve;
      worker.__resolve = null;
      worker.__reject = null;
      if (typeof resolve === "function") resolve(state.results[message.name]);
      return;
    }
    case "error":
      showError(message.message, message.traceback);
      if (worker.__reject) {
        worker.__reject(new Error(message.message));
        worker.__resolve = null;
        worker.__reject = null;
      }
      return;
    default:
      return;
  }
}

function renderRuntimeInfo() {
  const rows = [
    ["pyodide", state.info?.pyodide ?? "—"],
    ["python", state.info?.python ?? "—"],
    ["ggcore", state.core?.ggcore ?? "（未导入）"],
    ["CBOR", state.core?.cbor ?? "—"],
    ["IR 版本", state.core?.ir_version ?? "—"],
    ["包", state.packages.length ? state.packages.join(" + ") : "无"],
  ];
  runtimeEl.replaceChildren(
    ...rows.flatMap(([key, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = key;
      const dd = document.createElement("dd");
      dd.textContent = value;
      return [dt, dd];
    }),
  );
}

//: 首屏要的字节：运行时核心 + gg4py.tar（包在示例跑起来时才进分母）。
const BOOT_FILES = [
  "pyodide/pyodide.mjs",
  "pyodide/pyodide.asm.mjs",
  "pyodide/pyodide.asm.wasm",
  "pyodide/python_stdlib.zip",
  "gg4py.tar",
];

async function boot() {
  // 四件事并起来：SW 接管（cold 必等，warm 直接过）、manifest、首图示例源码、
  // 渲染器。它们谁都不依赖谁，串行只是白等 RTT。
  const swGate = serviceWorkerGate();
  registerServiceWorker().catch(() => {});
  const manifestPromise = fetch("./vendor/manifest.json").then((response) => {
    if (!response.ok) throw new Error(`manifest.json: HTTP ${response.status}`);
    return response.json();
  });
  const demoPromise = demoSource(FIRST_DEMO);
  const rendererPromise = loadRenderer();
  // 两者都只是「提前拉」：失败时下面各自的 await 还会照常报错，这里先摘掉
  // 未处理拒绝（否则控制台会多一条无关紧要的 unhandled rejection）。
  demoPromise.catch(() => {});
  rendererPromise.catch(() => {});

  await swGate;
  state.marks.sw_done = now();
  manifest = await manifestPromise;
  for (const name of BOOT_FILES) planFile(name);
  recordProgress();

  // warm：worker 在 `index.html` 的内联预载里就起了（SW 已控制页面，缓存与进度
  // 都不受影响）；cold：这里在 SW 接管之后才起。
  const early = window.__ggWorkerEarly ?? null;
  worker = early ?? new Worker("./worker.js", { type: "module" });
  state.marks.worker_spawn = early ? (window.__ggPerf?.worker_early ?? now()) : now();
  // 内联预载期间 worker 就挂了的话，`ready` 永远不会来：提前报，不吊着页面。
  if (early && window.__ggWorkerEarlyError) throw new Error(window.__ggWorkerEarlyError);
  // ready 的 resolver 必须在「接管队列」之前就位：内联预载可能已经把 ready 消息
  // 攒在队列里，接管时会同步回放。
  const ready = new Promise((resolve) => {
    worker.__readyResolve = resolve;
  });
  if (early && typeof window.__ggWorkerSink === "function") {
    window.__ggWorkerSink((message) => void handleWorkerMessage({ data: message }));
  } else {
    worker.onmessage = handleWorkerMessage;
    worker.postMessage({ type: "boot" });
  }
  worker.onerror = (event) => showError(`worker: ${event.message || "unknown"}`);
  await ready;
  await demoPromise;

  // 首图：运行时一就绪就跑基础示例（首访的验收口径是「到第一张图」）。
  selectDemo(FIRST_DEMO);
  await runDemo(FIRST_DEMO);
  return state;
}

buildDemoButtons();
renderRuntimeInfo();
setStage("loading", "预热 worker");

// 判定与截图用的公开接口（`tools/pyodide/check_runtime.py` 读它）。
window.__ggRuntime = {
  state: () => ({
    stage: state.stage,
    marks: state.marks,
    ready: state.ready,
    ready_at: state.readyAt ?? null,
    ready_rel: state.readyRel ?? null,
    packages_at_ready: state.packagesAtReady ?? null,
    core: state.core,
    info: state.info,
    packages: state.packages,
    progress: state.progress,
    cache: state.cache,
    first_plot_ms: state.firstPlotMs,
    timings: state.timings,
    results: state.results,
    error: state.error,
    demos: DEMOS.map((demo) => demo.name),
  }),
  progressLog,
  // 资源时间线：判定「wheel 是不是在 ready 之后才开始下载」用它（懒加载的证据）。
  assets: () =>
    performance.getEntriesByType("resource").map((entry) => ({
      name: entry.name,
      start: entry.startTime,
      end: entry.responseEnd,
      bytes: entry.transferSize || entry.encodedBodySize || 0,
    })),
  run: (name) => runDemo(name),
};

// warm 路径上 SW 已经在管页面，worker 早在 HTML 解析期就起了——这里只负责把它
// 接过来（`boot()` 里判断 `__ggWorkerEarly`）。
boot().catch((error) => showError(String(error?.message || error)));
