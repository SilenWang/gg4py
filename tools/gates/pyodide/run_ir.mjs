// M0-10 · 在 Pyodide 里跑 `run_ir.py`（与 CPython 侧是同一个文件），写出 IR 字节。
//
// 复用 E1 的加载方式与产物（`pixi run spike:e1:assets` → docs/spike/e1_coldstart/static）：
// pyodide 运行时、stdlib、numpy 轮子全部来自本地目录，不碰 CDN。这里是 node，
// 不是浏览器，所以没有 DOM / worker，也不需要 first paint —— M0-10 只验字节一致。
//
// 用法：
//   pixi run node tools/gates/pyodide/run_ir.mjs --out .gate-pyodide/pyodide.ir \
//       --meta .gate-pyodide/pyodide.json [--inject-diff <offset>]
//
// `--inject-diff` 是负向自测用的：把 Pyodide 侧产出的第 N 个字节翻一位，模拟
// “两边算出了不同字节”。门禁必须红。

import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..", "..");
const ASSETS = join(REPO, "docs", "spike", "e1_coldstart", "static", "pyodide");
const GG_SRC = join(REPO, "src", "ggcore");

function parseArgs(argv) {
  const args = { out: null, meta: null, injectDiff: null };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    if (flag === "--out") args.out = argv[++i];
    else if (flag === "--meta") args.meta = argv[++i];
    else if (flag === "--inject-diff") args.injectDiff = Number(argv[++i]);
    else throw new Error(`unknown argument: ${flag}`);
  }
  if (!args.out) throw new Error("--out is required");
  return args;
}

/**
 * `src/ggcore` 整棵树 → [相对路径, 内容]。
 * 带数据文件（`metrics/data/*.json` / `*.bin`）：浏览器里的 `ggcore` 也要读它们，
 * 挂载少一份就等于给未来的 Pyodide 路径埋一个只在那边炸的坑。`__pycache__` 跳过。
 */
function packageTree(root) {
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      if (entry === "__pycache__") continue;
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else files.push([full.slice(root.length + 1), readFileSync(full)]);
    }
  };
  walk(root);
  return files;
}

function requireAssets() {
  const needed = ["pyodide.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];
  for (const name of needed) {
    try {
      statSync(join(ASSETS, name));
    } catch {
      throw new Error(`missing ${name} in ${ASSETS} — run \`pixi run spike:e1:assets\``);
    }
  }
  const wheel = readdirSync(ASSETS).find((name) => /^numpy-.*\.whl$/.test(name));
  if (!wheel) throw new Error(`no numpy wheel in ${ASSETS} — run \`pixi run spike:e1:assets\``);
  // M2-6 / SIL-758：等值线冒烟要真的在浏览器运行时里跑 contourpy。
  const contourWheel = readdirSync(ASSETS).find((name) => /^contourpy-.*\.whl$/.test(name));
  if (!contourWheel) {
    throw new Error(`no contourpy wheel in ${ASSETS} — run \`pixi run spike:e1:assets\``);
  }
  return wheel;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  requireAssets();

  const started = performance.now();
  const { loadPyodide } = await import(pathToFileURL(join(ASSETS, "pyodide.mjs")).href);
  // node 下 indexURL 是文件系统路径（不是 file:// URL）：pyodide 用它拼
  // pyodide.asm.mjs / python_stdlib.zip / 轮子，全部从本地目录读，不碰 CDN。
  const pyodide = await loadPyodide({ indexURL: ASSETS + sep });
  const bootMs = performance.now() - started;

  const numpyStart = performance.now();
  // contourpy 与 numpy 一起装：`run_ir.py` 的等值线冒烟要用它算几何。
  await pyodide.loadPackage(["numpy", "contourpy"]);
  const numpyMs = performance.now() - numpyStart;

  const mountStart = performance.now();
  pyodide.FS.mkdirTree("/app/ggcore");
  for (const [relative, bytes] of packageTree(GG_SRC)) {
    const target = join("/app", "ggcore", relative);
    pyodide.FS.mkdirTree(dirname(target));
    pyodide.FS.writeFile(target, bytes);
  }
  for (const name of ["run_ir.py", "mini_plot.py", "plot.json"]) {
    pyodide.FS.writeFile(join("/app", name), readFileSync(join(HERE, name)));
  }
  pyodide.FS.mkdirTree("/out");
  const mountMs = performance.now() - mountStart;

  const runStart = performance.now();
  const exitCode = pyodide.runPython(`
import sys
sys.path.insert(0, "/app")
import run_ir
rc = run_ir.main(["--out", "/out/pyodide.ir", "--meta", "/out/meta.json"])
rc
`);
  const runMs = performance.now() - runStart;

  if (exitCode !== 0) throw new Error(`run_ir.main returned ${exitCode}`);

  const bytes = Buffer.from(pyodide.FS.readFile("/out/pyodide.ir"));
  if (args.injectDiff !== null) {
    const offset = args.injectDiff % bytes.length;
    bytes[offset] ^= 0x01; // 一个字节的一位：最小可能的差异
    console.error(`inject-diff: flipped bit 0 of byte ${offset} (negative control)`);
  }

  mkdirSync(dirname(resolve(args.out)), { recursive: true });
  writeFileSync(resolve(args.out), bytes);
  // 边角取值矩阵（NaN 位型 / ±Inf / 64 位 int 上界）：同样一份，两侧逐字节比。
  const edge = Buffer.from(pyodide.FS.readFile("/out/pyodide.ir.edge"));
  writeFileSync(resolve(`${args.out}.edge`), edge);

  const meta = JSON.parse(pyodide.FS.readFile("/out/meta.json", { encoding: "utf8" }));
  Object.assign(meta, {
    pyodide: pyodide.version,
    node: process.version,
    boot_ms: round(bootMs),
    numpy_load_ms: round(numpyMs),
    mount_ms: round(mountMs),
    run_ms: round(runMs),
    total_ms: round(performance.now() - started),
  });
  if (args.meta) {
    mkdirSync(dirname(resolve(args.meta)), { recursive: true });
    writeFileSync(resolve(args.meta), JSON.stringify(meta, null, 1) + "\n");
  }
  console.log(
    `${bytes.length} B (+${edge.length} B edge) via pyodide ${pyodide.version}, ` +
      `numpy ${meta.numpy}, contourpy ${meta.contourpy}`,
  );
}

const round = (value) => Math.round(value * 1000) / 1000;

main().catch((error) => {
  console.error(`run_ir.mjs: ${error.message}`);
  process.exit(1);
});
