// SIL-826（M3-4）· 页面侧：CodeMirror 编辑器 + Pyodide worker + IR → DOM SVG + 导出。
//
// 这一页只做四件事，其余都是既有部件：
//
//   1. **代码**：CodeMirror 6（`src/editor.ts` → `dist/editor.js`）编辑一段 Python，
//      内容按示例分键存在 localStorage。`Ctrl/Cmd+Enter` 重跑。
//   2. **执行**：`../runtime/worker.js`（运行时页用的同一个 Pyodide worker）跑
//      `ggcore.script.run_script`，stdout / stderr 逐行回推，错误回用户栈帧的
//      traceback。包按静态 import 扫描懒加载，numpy 首次出图时才下。
//   3. **出图**：拿回 IR 字节，用 `../viewer/dist` 的 TS 渲染器（零 wasm）画成
//      DOM SVG。屏幕按 1 pt = 1 px 显示，所以 1× 导出的 PNG 就是屏幕上这张图。
//   4. **导出**：`export.js`（SVG / PNG / JPG，1×/2×/4× 或给 DPI）。
//
// 「改一行重跑 ≤ 2 s（warm）」的口径：从点运行（或按键）到**第二帧合成完成**，
// 含 worker 里 exec + build + encode 与页面的 decode + 渲染。数字写在状态行里，
// `tools/editor/check_editor.py` 读 `window.__ggEditor.state().timings.last`。

import { exportPlot, blobToBase64, sceneSize } from "./export.js";

const WORKER_URL = new URL("../runtime/worker.js", import.meta.url);
const STORE_KEY = "gg4py.editor.v1";
const EXAMPLE_INDEX = new URL("./examples/index.json", import.meta.url);
const EXAMPLE_SOURCE = (name) => new URL(`./examples/${name}.py`, import.meta.url);
const RUN_PATH = (name) => `/app/${name || "editor"}.py`;

const $ = (selector) => document.querySelector(selector);
const bar = $("#bar");
const badgeState = $("#badge-state");
const badgeRuntime = $("#badge-runtime");
const badgePackages = $("#badge-packages");
const examplesSelect = $("#examples");
const resetButton = $("#reset-example");
const editorHost = $("#editor-host");
const dataPanel = $("#data-panel");
const dataText = $("#data-text");
const dataHint = $("#data-hint");
const dataModeLabel = $("#data-mode-label");
const runButton = $("#run");
const stageArea = $("#stage-area");
const statusLine = $("#status-line");
const stdoutEl = $("#stdout");
const stderrEl = $("#stderr");
const tracebackEl = $("#traceback");
const consoleCount = $("#console-count");
const metaEl = $("#meta");
const scaleSelect = $("#scale");
const dpiInput = $("#dpi");
const qualityInput = $("#quality");

const STAGE_PCT = {
  boot: 0.05,
  runtime: 0.25,
  "runtime-ready": 0.4,
  archive: 0.5,
  ready: 0.6,
  packages: 0.78,
  "packages-ready": 0.85,
  data: 0.88,
  run: 0.9,
  done: 1,
};

const DEFAULT_DATA = {
  mode: "csv",
  text: "class,value\na,3.2\nb,4.8\nc,2.1\nd,5.6\ne,4.1\nf,3.0\n",
};

const DATA_HINTS = {
  csv: '数据面板的 CSV 会写到 <code>data.csv</code>：<code>from ggio.csv import read_csv</code>，然后 <code>read_csv("data.csv")</code>。',
  inline:
    '内联数据必须是 Python 字面量（dict of arrays），作为 <code>DATA</code> 变量注入：<code>to_column_table(DATA)</code>。',
};

const state = {
  ready: false,
  running: false,
  stage: "boot",
  example: null,
  examples: [],
  /** 每个示例的原文（来自 examples/*.py，只读，用来「重置」）。 */
  exampleSources: {},
  /** 用户在 localStorage 里改过的源码：示例名 → 源码。 */
  sources: {},
  /** 每个示例的数据面板：示例名 → {mode, text}。 */
  dataByExample: {},
  info: null,
  core: null,
  packages: [],
  meta: null,
  error: null,
  scene: null,
  timings: { last: null, runs: [] },
  exports: [],
  progress: { pct: 0, label: "启动中" },
};

let editor = null;
let worker = null;
let renderer = null;
let pendingRun = null;
let saveTimer = null;

// ---------------------------------------------------------------------------
// 小工具
// ---------------------------------------------------------------------------

const bytesLabel = (value) => {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(2)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
};

const ms = (value) => (Number.isFinite(value) ? `${Math.round(value)} ms` : "—");

const nextFrame = () => new Promise((resolve) => requestAnimationFrame(() => resolve(null)));

function setBadge(text, kind = "") {
  badgeState.textContent = text;
  badgeState.dataset.state = kind;
}

function setProgress(pct, label) {
  state.progress = { pct, label };
  bar.style.width = `${Math.min(100, Math.max(0, pct * 100)).toFixed(1)}%`;
}

function setStage(name, detail = "") {
  state.stage = name;
  const pct = STAGE_PCT[name] ?? state.progress.pct;
  setProgress(pct, detail || name);
  if (name !== "ready" && name !== "done" && name !== "error") {
    statusLine.textContent = detail ? `${name} · ${detail}` : name;
  }
}

function showFatal(message) {
  setBadge("失败", "bad");
  statusLine.dataset.state = "error";
  statusLine.textContent = message;
  tracebackEl.hidden = false;
  tracebackEl.textContent = message;
}

// ---------------------------------------------------------------------------
// 持久化：源码、数据面板、导出设置
// ---------------------------------------------------------------------------

function readStore() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (error) {
    console.warn("localStorage 读不出来，按首次访问处理", error);
    return null;
  }
}

function writeStore() {
  try {
    localStorage.setItem(
      STORE_KEY,
      JSON.stringify({
        example: state.example,
        sources: state.sources,
        dataByExample: state.dataByExample,
        scale: scaleSelect.value,
        dpi: dpiInput.value,
        quality: qualityInput.value,
      }),
    );
  } catch (error) {
    console.warn("localStorage 写不进去（可能是隐私模式）", error);
  }
}

function scheduleSave() {
  if (saveTimer !== null) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    writeStore();
  }, 350);
}

function saveNow() {
  if (saveTimer !== null) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  writeStore();
}

// ---------------------------------------------------------------------------
// 数据面板
// ---------------------------------------------------------------------------

function dataFor(name) {
  const stored = state.dataByExample[name];
  if (stored) return stored;
  const entry = state.examples.find((item) => item.name === name);
  if (entry?.data) return { mode: entry.data.mode ?? "csv", text: entry.data.text ?? "" };
  return { mode: "csv", text: "" };
}

function currentData() {
  return state.dataByExample[state.example] ?? dataFor(state.example);
}

function renderDataPanel() {
  const data = dataFor(state.example);
  state.dataByExample[state.example] = data;
  dataText.value = data.text;
  for (const button of dataPanel.querySelectorAll("[role=tab]")) {
    button.setAttribute("aria-selected", String(button.dataset.mode === data.mode));
  }
  dataModeLabel.textContent = data.mode === "csv" ? "CSV" : "内联数据";
  dataHint.innerHTML = DATA_HINTS[data.mode] ?? "";
  dataPanel.open = data.text.trim().length > 0;
}

function setDataMode(mode) {
  const data = currentData();
  state.dataByExample[state.example] = { mode, text: data.text };
  renderDataPanel();
  scheduleSave();
}

// ---------------------------------------------------------------------------
// 示例
// ---------------------------------------------------------------------------

async function loadExamples() {
  const response = await fetch(EXAMPLE_INDEX);
  if (!response.ok) throw new Error(`示例清单：HTTP ${response.status}`);
  const index = await response.json();
  state.examples = index.examples ?? [];
  await Promise.all(
    state.examples.map(async (entry) => {
      const source = await fetch(EXAMPLE_SOURCE(entry.name));
      if (!source.ok) throw new Error(`示例 ${entry.name}：HTTP ${source.status}`);
      state.exampleSources[entry.name] = await source.text();
    }),
  );
}

function buildExampleSelect() {
  examplesSelect.replaceChildren(
    ...state.examples.map((entry) => {
      const option = document.createElement("option");
      option.value = entry.name;
      option.textContent = entry.label ?? entry.name;
      option.title = entry.note ?? "";
      return option;
    }),
  );
}

function selectExample(name, { force = false } = {}) {
  if (!state.exampleSources[name]) return;
  if (state.example && editor !== null && !force) {
    state.sources[state.example] = editor.getValue();
  }
  state.example = name;
  examplesSelect.value = name;
  const source = state.sources[name] ?? state.exampleSources[name];
  if (editor !== null) editor.setValue(source);
  renderDataPanel();
  setStage(state.ready ? "ready" : "boot", `示例 ${name}`);
  scheduleSave();
}

// ---------------------------------------------------------------------------
// worker
// ---------------------------------------------------------------------------

function spawnWorker() {
  worker = new Worker(WORKER_URL, { type: "module" });
  worker.onmessage = (event) => handleWorkerMessage(event.data ?? {});
  worker.onerror = (event) => {
    showFatal(`worker: ${event.message || "unknown"}`);
    settleRun(new Error(event.message || "worker error"));
  };
  worker.postMessage({ type: "boot" });
}

function handleWorkerMessage(message) {
  switch (message.type) {
    case "stage":
      setStage(message.stage, message.detail);
      return;
    case "fetch-progress":
      if (message.total > 0) {
        setProgress(0.35 + 0.15 * (message.loaded / message.total), "下载运行时资产");
      }
      return;
    case "packages":
      setBadge(`加载 ${message.packages.join(" + ")}`, "busy");
      setProgress(0.7, `加载 ${message.packages.join(" + ")}`);
      return;
    case "packages-loaded":
      state.packages = message.packages;
      badgePackages.textContent = `包：${message.packages.length ? message.packages.join(" + ") : "无（懒加载）"}`;
      return;
    case "core":
      state.core = message.info;
      badgeRuntime.textContent = `ggcore ${message.info.ggcore}`;
      return;
    case "ready":
      state.ready = true;
      state.info = message.info;
      badgeRuntime.textContent = `pyodide ${message.info.pyodide ?? "?"}`;
      setBadge("就绪", "ok");
      setStage("ready", "运行时就绪（数值栈尚未加载）");
      setProgress(0.6, "运行时就绪");
      runButton.disabled = false;
      stageArea.querySelector(".placeholder")?.remove();
      if (shouldAutorun()) run().catch((error) => showFatal(String(error.message || error)));
      return;
    case "stdout":
      appendOutput(stdoutEl, message.text);
      return;
    case "stderr":
      appendOutput(stderrEl, message.text);
      return;
    case "editor-result":
      handleResult(message).catch((error) => showFatal(String(error.message || error)));
      return;
    case "editor-error":
      handleEditorError(message);
      return;
    case "error":
      showFatal(`${message.message}${message.traceback ? `\n\n${message.traceback}` : ""}`);
      settleRun(new Error(message.message));
      return;
    default:
      return;
  }
}

function appendOutput(element, text) {
  element.textContent += text.endsWith("\n") ? text : `${text}\n`;
  consoleCount.textContent = `${(stdoutEl.textContent + stderrEl.textContent).split("\n").length - 1} 行`;
}

// ---------------------------------------------------------------------------
// 运行
// ---------------------------------------------------------------------------

function clearConsole() {
  stdoutEl.textContent = "";
  stderrEl.textContent = "";
  tracebackEl.textContent = "";
  tracebackEl.hidden = true;
  consoleCount.textContent = "";
  statusLine.dataset.state = "";
  const previous = stageArea.querySelector("svg.gg-svg");
  if (previous) previous.dataset.stale = "false";
}

function shouldAutorun() {
  const params = new URLSearchParams(location.search);
  return params.get("autorun") !== "0";
}

function run() {
  if (!state.ready || state.running) return Promise.resolve(null);
  const source = editor !== null ? editor.getValue() : "";
  state.sources[state.example] = source;
  saveNow();
  clearConsole();
  state.running = true;
  state.error = null;
  runButton.disabled = true;
  setBadge("运行中", "busy");
  setStage("run", `运行 ${state.example}`);
  const data = currentData();
  const started = performance.now();
  const promise = new Promise((resolve) => {
    pendingRun = { started, resolve, example: state.example };
  });
  worker.postMessage({
    type: "run-source",
    source,
    path: RUN_PATH(state.example),
    csv: data.mode === "csv" ? data.text : null,
    inlineData: data.mode === "inline" ? data.text : null,
  });
  return promise;
}

function settleRun(error = null) {
  const pending = pendingRun;
  pendingRun = null;
  state.running = false;
  runButton.disabled = !state.ready;
  if (pending) pending.resolve(error ? { error: String(error.message ?? error) } : state.timings.last);
}

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

/**
 * 把屏幕上的 SVG 对到整数像素上。
 *
 * `#stage-area` 居中的结果是 `left: 754.39px` 这种半像素坐标，浏览器会把整张图
 * 重采样一次——屏幕看到的就不是「1 pt = 1 px」的干净栅格，导出的 1× PNG 也就
 * 对不上（差在抗锯齿，不在内容）。这里补一次亚像素平移，让左上角落在整数上。
 */
function snapSvg() {
  const svg = stageArea.querySelector("svg.gg-svg");
  if (svg === null) return;
  svg.style.transform = "";
  const rect = svg.getBoundingClientRect();
  const dx = Math.round(rect.left) - rect.left;
  const dy = Math.round(rect.top) - rect.top;
  if (dx !== 0 || dy !== 0) svg.style.transform = `translate(${dx}px, ${dy}px)`;
}

async function handleResult(message) {
  const { decodeScene, renderScene } = await loadRenderer();
  const scene = decodeScene(new Uint8Array(message.payload));
  const result = renderScene(scene);
  const svg = result.svg;
  const { width, height } = sceneSize(svg);
  // 屏幕口径：1 pt = 1 px（整数）。导出第 n 倍 = round(pt * n)，与屏幕同一个取整，
  // 所以 1× 的 PNG 与这块 SVG 逐像素相同（见 export.js 的模块说明）。
  svg.style.width = `${Math.round(width)}px`;
  svg.style.height = `${Math.round(height)}px`;
  svg.classList.add("gg-svg");
  stageArea.replaceChildren(svg);
  // 先布局再对像素：`getBoundingClientRect()` 会强制一次 reflow，拿到的是真位置。
  snapSvg();

  state.scene = scene;
  state.meta = message.meta;
  state.error = null;
  await nextFrame();
  await nextFrame();
  const total = performance.now() - (pendingRun?.started ?? performance.now());
  const record = {
    example: state.example,
    total_ms: total,
    worker_ms: message.meta.worker_total_ms,
    run_ms: message.meta.run_ms,
    build_ms: message.meta.build_ms,
    encode_ms: message.meta.encode_ms,
    render_ms: Math.max(0, total - (message.meta.worker_total_ms ?? 0)),
    packages_ms: message.meta.packages_ms,
    digest: message.meta.digest,
    bytes: message.meta.bytes,
    nodes: message.meta.nodes,
    width_pt: width,
    height_pt: height,
    at: Date.now(),
  };
  state.timings.last = record;
  state.timings.runs.push(record);
  setProgress(1, "完成");
  setBadge("出图完成", "ok");
  statusLine.dataset.state = "ok";
  statusLine.textContent =
    `重跑 ${ms(total)}（worker ${ms(message.meta.worker_total_ms)} · 渲染 ${ms(record.render_ms)}）` +
    ` · build ${ms(message.meta.build_ms)} · encode ${ms(message.meta.encode_ms)}`;
  renderMeta();
  settleRun();
}

function handleEditorError(message) {
  state.error = {
    message: message.message,
    traceback: message.traceback ?? message.message,
    line: message.line ?? null,
  };
  tracebackEl.hidden = false;
  tracebackEl.textContent = message.traceback || message.message;
  const previous = stageArea.querySelector("svg.gg-svg");
  if (previous) previous.dataset.stale = "true";
  setBadge("出错", "bad");
  statusLine.dataset.state = "error";
  statusLine.textContent = message.message;
  settleRun(new Error(message.message));
}

// ---------------------------------------------------------------------------
// 元数据 / 状态
// ---------------------------------------------------------------------------

function renderMeta() {
  const meta = state.meta;
  if (meta === null) {
    metaEl.replaceChildren();
    return;
  }
  const rows = [
    ["示例", state.example ?? "—"],
    ["IR 字节", `${meta.bytes} B`],
    ["IR 节点", String(meta.nodes)],
    ["sha256", `${meta.digest.slice(0, 24)}…`],
    ["尺寸", `${meta.width_in} × ${meta.height_in} in（${Math.round(meta.width_in * 72)} × ${Math.round(meta.height_in * 72)} pt）`],
    ["build / encode", `${ms(meta.build_ms)} / ${ms(meta.encode_ms)}`],
    ["重跑（warm）", ms(state.timings.last?.total_ms)],
    ["包", meta.packages.length ? meta.packages.join(" + ") : "无"],
    ["运行时", `pyodide ${meta.pyodide ?? "?"} · python ${meta.python ?? "?"}`],
    ["IR 版本 / CBOR", `${meta.ir_version} · ${meta.cbor}`],
  ];
  metaEl.replaceChildren(
    ...rows.flatMap(([key, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = key;
      const dd = document.createElement("dd");
      dd.textContent = value;
      return [dt, dd];
    }),
  );
}

// ---------------------------------------------------------------------------
// 导出
// ---------------------------------------------------------------------------

function currentSvg() {
  const svg = stageArea.querySelector("svg.gg-svg");
  if (svg === null) throw new Error("还没有图可以导出：先跑一次代码");
  return svg;
}

async function exportCurrent(format, options = {}) {
  const svg = currentSvg();
  const dpi = options.dpi ?? (Number(dpiInput.value) || 72);
  const { blob, mime, width, height, pixels } = await exportPlot(svg, {
    format,
    dpi,
    scale: options.scale,
    quality: options.quality ?? Number(qualityInput.value),
  });
  const record = {
    format,
    mime,
    width,
    height,
    pixels,
    bytes: blob.size,
    dpi,
    base64: await blobToBase64(blob),
    at: Date.now(),
  };
  state.exports.push(record);
  return record;
}

async function downloadCurrent(format) {
  try {
    const record = await exportCurrent(format);
    const link = document.createElement("a");
    link.href = `data:${record.mime};base64,${record.base64}`;
    link.download = `${state.example ?? "gg4py"}-${record.pixels}.${format === "jpg" ? "jpg" : format}`;
    document.body.append(link);
    link.click();
    link.remove();
    statusLine.dataset.state = "ok";
    statusLine.textContent = `已导出 ${format.toUpperCase()} · ${record.pixels} px · ${bytesLabel(record.bytes)}`;
  } catch (error) {
    showFatal(`导出失败：${error.message || error}`);
  }
}

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------

function wireEvents() {
  examplesSelect.addEventListener("change", () => selectExample(examplesSelect.value));
  resetButton.addEventListener("click", () => {
    if (state.example === null) return;
    delete state.sources[state.example];
    editor?.setValue(state.exampleSources[state.example]);
    scheduleSave();
  });
  runButton.addEventListener("click", () => {
    run().catch(() => {});
  });
  for (const button of stageArea.closest("section").querySelectorAll("[data-export]")) {
    button.addEventListener("click", () => downloadCurrent(button.dataset.export));
  }
  for (const button of dataPanel.querySelectorAll("[role=tab]")) {
    button.addEventListener("click", () => setDataMode(button.dataset.mode));
  }
  dataText.addEventListener("input", () => {
    state.dataByExample[state.example] = { mode: currentData().mode, text: dataText.value };
    scheduleSave();
  });
  scaleSelect.addEventListener("change", () => {
    dpiInput.value = String(Number(scaleSelect.value) * 72);
    scheduleSave();
  });
  dpiInput.addEventListener("change", () => {
    const scale = Number(dpiInput.value) / 72;
    const match = [...scaleSelect.options].find((option) => Number(option.value) === scale);
    scaleSelect.value = match ? match.value : scaleSelect.value;
    scheduleSave();
  });
  qualityInput.addEventListener("change", scheduleSave);
  window.addEventListener("beforeunload", saveNow);
  // 窗口尺寸变化会重新居中（又变成半像素），重新对一次。
  window.addEventListener("resize", snapSvg);
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(snapSvg).observe(stageArea);
  }
  window.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      run().catch(() => {});
    }
  });
}

async function boot() {
  setStage("boot", "读取示例库");
  const saved = readStore();
  if (saved) {
    state.sources = saved.sources ?? {};
    state.dataByExample = saved.dataByExample ?? {};
    if (saved.scale) scaleSelect.value = String(saved.scale);
    if (saved.dpi) dpiInput.value = String(saved.dpi);
    if (saved.quality) qualityInput.value = String(saved.quality);
  }
  await loadExamples();
  buildExampleSelect();
  const params = new URLSearchParams(location.search);
  const initial = params.get("example") ?? saved?.example ?? state.examples[0]?.name;
  state.example = initial;
  examplesSelect.value = initial;
  const source = state.sources[initial] ?? state.exampleSources[initial];

  try {
    const module = await import("./dist/editor.js");
    editor = module.createEditor(editorHost, {
      doc: source,
      onChange: (text) => {
        state.sources[state.example] = text;
        scheduleSave();
      },
      onRun: () => {
        run().catch(() => {});
      },
    });
  } catch (error) {
    showFatal(
      `编辑器没能加载（web/editor/dist/editor.js）：${error.message || error}\n` +
        "先跑 `pixi run editor:build`。",
    );
    return;
  }
  renderDataPanel();
  wireEvents();
  // 渲染器与 worker 并行预热：IR 回来时它早就到了，不进「重跑」的计时。
  loadRenderer().catch(() => {});
  spawnWorker();
}

window.__ggEditor = {
  /** 测试与手测用的快照（`tools/editor/check_editor.py` 读它）。 */
  state: () => ({
    ready: state.ready,
    running: state.running,
    stage: state.stage,
    example: state.example,
    examples: state.examples.map((entry) => entry.name),
    source: editor?.getValue() ?? null,
    source_chars: editor?.getValue().length ?? 0,
    meta: state.meta,
    error: state.error,
    timings: state.timings,
    packages: state.packages,
    info: state.info,
    core: state.core,
    progress: state.progress,
    stage_pct: state.progress.pct,
    stored: localStorage.getItem(STORE_KEY) !== null,
    data: currentData(),
    exports: state.exports.map(({ base64, ...rest }) => rest),
  }),
  run: () => run(),
  selectExample: (name) => selectExample(name, { force: true }),
  setSource: (text) => {
    if (state.example !== null) state.sources[state.example] = text;
    editor?.setValue(text);
    saveNow();
  },
  setData: (mode, text) => {
    state.dataByExample[state.example] = { mode, text };
    renderDataPanel();
    saveNow();
  },
  export: (format, options) => exportCurrent(format, options ?? {}),
  stored: () => readStore(),
};

boot().catch((error) => showFatal(`启动失败：${error.message || error}`));
