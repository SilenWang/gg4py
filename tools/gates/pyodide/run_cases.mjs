// SIL-824 · 在 Pyodide 里跑 `run_cases.py`（与 CPython 侧是同一个文件），
// 写出全量 case 的 IR 摘要。
//
// 挂载的是一棵**仓库布局的子集**，因为 `docs/cases/_fixtures.py` 与部分 plot.py
// 用 `Path(__file__).resolve().parents[...]` 推仓库根：
//
//     /app/src/ggcore                 ggcore 源码（含 metrics/data 里的度量表）
//     /app/src/ggio                   DataFrame-like 适配层（plot.py 的 import）
//     /app/docs/cases/_fixtures.py    共享夹具（mtcars / mpg）
//     /app/docs/cases/<name>/plot.py  515 条 case 的 plot.py（**不挂 expected.svg**）
//     /app/tools/upstream/fixtures    `_fixtures.py` 读的 mpg_models.json
//
// `expected.svg` 一律不挂：500 多条参考图有几十 MB，门禁只看 IR 摘要。
//
// 用法：
//   pixi run node tools/gates/pyodide/run_cases.mjs --out .gate-pyodide/pyodide-cases.json
//   ... [--inject-case <name>]   负向自测：把某条 case 的摘要改掉一个字符

import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..", "..");
const ASSETS = join(REPO, "docs", "spike", "e1_coldstart", "static", "pyodide");
const SRC = join(REPO, "src");
const CASES = join(REPO, "docs", "cases");
const FIXTURES = join(REPO, "tools", "upstream", "fixtures");
const APP = "/app";

function parseArgs(argv) {
  const args = { out: null, injectCase: null, case_: null, ir: null };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    if (flag === "--out") args.out = argv[++i];
    else if (flag === "--inject-case") args.injectCase = argv[++i];
    else if (flag === "--case") args.case_ = argv[++i];
    else if (flag === "--ir") args.ir = argv[++i];
    else throw new Error(`unknown argument: ${flag}`);
  }
  if (!args.out) throw new Error("--out is required");
  if (args.ir && !args.case_) throw new Error("--ir needs --case");
  return args;
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
  for (const pattern of [/^numpy-.*\.whl$/, /^contourpy-.*\.whl$/]) {
    if (!readdirSync(ASSETS).some((name) => pattern.test(name))) {
      throw new Error(`no ${pattern} wheel in ${ASSETS} — run \`pixi run spike:e1:assets\``);
    }
  }
}

/** `src/` 整棵树 → [相对路径, 内容]（`__pycache__` 跳过；数据文件也要挂）。 */
function packageTree(root, { skip = () => false } = {}) {
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      if (entry === "__pycache__") continue;
      const full = join(dir, entry);
      if (skip(full)) continue;
      if (statSync(full).isDirectory()) walk(full);
      else files.push([full.slice(root.length + 1), readFileSync(full)]);
    }
  };
  walk(root);
  return files;
}

function writeFiles(pyodide, base, files) {
  for (const [relative, bytes] of files) {
    const target = join(base, relative);
    pyodide.FS.mkdirTree(dirname(target));
    pyodide.FS.writeFile(target, bytes);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  requireAssets();

  const { loadPyodide } = await import(pathToFileURL(join(ASSETS, "pyodide.mjs")).href);
  const started = performance.now();
  // node 下 indexURL 是文件系统路径：运行时 / stdlib / 轮子全部来自本地目录，不碰 CDN。
  const pyodide = await loadPyodide({ indexURL: ASSETS + sep });
  const bootMs = performance.now() - started;

  const loadStart = performance.now();
  // contourpy 与 numpy 一起装：案例库里有等值线（stat_contour 族）的 case，
  // 两端必须用同一个 contourpy 版本，否则「一致」是两个实现的巧合（SIL-758）。
  await pyodide.loadPackage(["numpy", "contourpy"]);
  const packagesMs = performance.now() - loadStart;

  const mountStart = performance.now();
  // 只挂 ggcore / ggio：案例库的 plot.py 不 import 其它子包（`tests` 里才有）。
  for (const name of ["ggcore", "ggio"]) {
    writeFiles(pyodide, join(APP, "src"), packageTree(join(SRC, name), {
      skip: (full) => full.endsWith(".orig"),
    }).map(([relative, bytes]) => [join(name, relative), bytes]));
  }
  // 案例库：只要 plot.py 与 _fixtures.py，不挂 expected.svg。
  pyodide.FS.mkdirTree(join(APP, "docs", "cases"));
  pyodide.FS.writeFile(
    join(APP, "docs", "cases", "_fixtures.py"),
    readFileSync(join(CASES, "_fixtures.py")),
  );
  for (const name of readdirSync(CASES)) {
    const plot = join(CASES, name, "plot.py");
    try {
      statSync(plot);
    } catch {
      continue;
    }
    pyodide.FS.mkdirTree(join(APP, "docs", "cases", name));
    pyodide.FS.writeFile(join(APP, "docs", "cases", name, "plot.py"), readFileSync(plot));
  }
  writeFiles(pyodide, APP, packageTree(FIXTURES).map(([relative, bytes]) => [
    join("tools", "upstream", "fixtures", relative),
    bytes,
  ]));
  pyodide.FS.mkdirTree(join(APP, "tools", "gates", "pyodide"));
  pyodide.FS.writeFile(
    join(APP, "tools", "gates", "pyodide", "run_cases.py"),
    readFileSync(join(HERE, "run_cases.py")),
  );
  pyodide.FS.mkdirTree("/out");
  const mountMs = performance.now() - mountStart;

  const runStart = performance.now();
  const caseArgs = args.case_
    ? [", \"--case\", " + JSON.stringify(args.case_), args.ir ? ", \"--ir\", \"/out/one.ir\"" : ""].join("")
    : "";
  pyodide.runPython(`
import sys
sys.path.insert(0, "/app/src")
sys.path.insert(0, "/app/tools/gates/pyodide")
import run_cases
run_cases.main(["--out", "/out/cases.json"${caseArgs}])
`);
  const runMs = performance.now() - runStart;

  const report = JSON.parse(pyodide.FS.readFile("/out/cases.json", { encoding: "utf8" }));
  if (args.ir) {
    mkdirSync(dirname(resolve(args.ir)), { recursive: true });
    writeFileSync(resolve(args.ir), Buffer.from(pyodide.FS.readFile("/out/one.ir")));
  }
  Object.assign(report, {
    pyodide: pyodide.version,
    node: process.version,
    boot_ms: round(bootMs),
    packages_ms: round(packagesMs),
    mount_ms: round(mountMs),
    run_ms: round(runMs),
  });
  if (args.injectCase) {
    const entry = report.cases[args.injectCase];
    if (!entry) throw new Error(`inject-case: ${args.injectCase} not in report`);
    const flipped = entry.sha256.slice(0, -1) + (entry.sha256.endsWith("0") ? "1" : "0");
    entry.sha256 = flipped;
    console.error(`inject-case: flipped last nibble of ${args.injectCase} digest (negative control)`);
  }

  mkdirSync(dirname(resolve(args.out)), { recursive: true });
  writeFileSync(resolve(args.out), JSON.stringify(report, null, 1) + "\n");
  console.log(
    `${Object.keys(report.cases).length} cases, ${Object.keys(report.failed).length} failed, ` +
      `${report.total_bytes} B via pyodide ${pyodide.version} (numpy ${report.numpy}, ` +
      `metrics ${report.metrics})`,
  );
}

const round = (value) => Math.round(value * 1000) / 1000;

main().catch((error) => {
  console.error(`run_cases.mjs: ${error.message}`);
  process.exit(1);
});
