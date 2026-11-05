// SIL-830 · 在 Pyodide 里把 `src/{ggcore,ggio}` 预编译成 `.pyc`（构建期，不在用户侧）。
//
// 为什么必须在 Pyodide 里编：`.pyc` 的魔法数跟 CPython 版本绑定，浏览器里跑的是
// pyodide@314.0.7 的 **CPython 3.14**，而桌面环境是 3.12——用桌面 python 编出来的
// 字节码在浏览器里会被直接判定为「版本不对」而退回源码重编，收益为零。这里用同一份
// 运行时（`docs/spike/e1_coldstart/static/pyodide`，`pixi run spike:e1:assets` 落的）
// 在构建期编一次，产物进 `gg4py.tar`。
//
// 三条确定性要求（同一份源码 → 同一个字节）：
//   * `UNCHECKED_HASH` 失效模式：不把源文件的 mtime / size 写进 pyc；
//   * `stripdir=/app`：`co_filename` 是 `src/ggcore/x.py`，不含临时挂载点；
//   * 条目由 `stage_assets.py` 排序打包，时间戳固定。
//
// 用法：
//   node tools/pyodide/compile_pyc.mjs --out <dir> [--optimize 0|2] [--measure]
//
// 输出：一行 JSON（文件数、字节数、以及 `--measure` 时两端 `import ggcore` 的毫秒数）。

import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");
const ASSETS = join(REPO, "docs", "spike", "e1_coldstart", "static", "pyodide");
const SRC = join(REPO, "src");
const PACKAGES = ["ggcore", "ggio"];

function parseArgs(argv) {
  const args = { out: null, optimize: 0, measure: false };
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    if (flag === "--out") args.out = argv[++i];
    else if (flag === "--optimize") args.optimize = Number(argv[++i]);
    else if (flag === "--measure") args.measure = true;
    else throw new Error(`unknown argument: ${flag}`);
  }
  if (!args.out) throw new Error("--out is required");
  return args;
}

/** `src/{ggcore,ggio}` → [相对 `src/` 的路径, 字节]（跳过缓存与备份）。 */
function sourceTree() {
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir).sort()) {
      if (entry === "__pycache__") continue;
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if (!entry.endsWith(".pyc") && !entry.endsWith(".orig")) {
        files.push([full.slice(SRC.length + 1), readFileSync(full)]);
      }
    }
  };
  for (const pkg of PACKAGES) walk(join(SRC, pkg));
  return files;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const { loadPyodide } = await import(pathToFileURL(join(ASSETS, "pyodide.mjs")).href);
  // node 下 indexURL 是文件系统路径（不是 file:// URL）：pyodide 用它拼
  // `<indexURL>pyodide.asm.mjs`，给 URL 会拼成 `path/file:/...`（同 run_ir.mjs）。
  const pyodide = await loadPyodide({ indexURL: ASSETS + sep });

  // 挂载点 `/app` 与运行时页一致（`unpackArchive(..., {extractDir: "/app"})`），
  // 所以 pyc 里的 `co_filename` 就是页面里 traceback 会显示的那条路径。
  for (const pkg of PACKAGES) pyodide.FS.mkdirTree(`/app/src/${pkg}`);
  for (const [rel, data] of sourceTree()) {
    const full = `/app/src/${rel}`;
    pyodide.FS.mkdirTree(dirname(full));
    pyodide.FS.writeFile(full, data);
  }

  const started = Date.now();
  const compiled = pyodide.runPython(`
import compileall, json, py_compile
ok = compileall.compile_dir(
    "/app/src",
    quiet=1,
    force=True,
    legacy=True,
    optimize=${args.optimize},
    invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    stripdir="/app",
)
json.dumps({"ok": bool(ok)})
`);
  const compileMs = Date.now() - started;
  if (!JSON.parse(compiled).ok) throw new Error("compileall 失败");

  // 读回 pyc：`/app/src/<pkg>/...pyc` → `<out>/src/<pkg>/...pyc`。
  // 目录遍历走 pyodide 的 FS（`/app` 是 wasm 里的虚拟文件系统，node 的 fs 看不见）。
  const listed = JSON.parse(
    pyodide.runPython(`
import json, os
out = []
for root, _dirs, files in os.walk("/app/src"):
    for name in sorted(files):
        if name.endswith(".pyc"):
            full = os.path.join(root, name)
            out.append(os.path.relpath(full, "/app"))
json.dumps(sorted(out))
`),
  );
  const out = [];
  for (const rel of listed) {
    const data = pyodide.FS.readFile(`/app/${rel}`);
    const target = join(args.out, rel);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, Buffer.from(data));
    out.push({ file: rel, bytes: data.length });
  }

  let measure = null;
  if (args.measure) {
    // 同一份运行时里量两次 `import ggcore`：源码树 vs 只有 pyc 的树。
    // 先把 numpy 装上（ggcore 自己 import 它，装机时间两边一样，不在比较范围）。
    await pyodide.loadPackage("numpy");
    pyodide.runPython(`
import os, shutil
os.makedirs("/pyc/src", exist_ok=True)
shutil.copytree("/app/src", "/pyc/src", dirs_exist_ok=True)
for root, _dirs, files in os.walk("/pyc/src"):
    for name in files:
        if name.endswith(".py"):
            os.unlink(os.path.join(root, name))
`);
    measure = JSON.parse(
      pyodide.runPython(`
import json, sys, time

def measure_import(path, rounds=3):
    best = None
    for _ in range(rounds):
        for name in [n for n in sys.modules if n == "ggcore" or n.startswith("ggcore.")
                     or n == "ggio" or n.startswith("ggio.")]:
            del sys.modules[name]
        sys.path.insert(0, path)
        try:
            start = time.perf_counter()
            import ggcore
            elapsed = (time.perf_counter() - start) * 1000.0
        finally:
            sys.path.remove(path)
        best = elapsed if best is None else min(best, elapsed)
    return round(best, 1)

sys.dont_write_bytecode = True
json.dumps({"source_ms": measure_import("/app/src"), "pyc_ms": measure_import("/pyc/src")})
`),
    );
  }

  process.stdout.write(
    JSON.stringify({
      files: out.length,
      bytes: out.reduce((sum, entry) => sum + entry.bytes, 0),
      optimize: args.optimize,
      compile_ms: compileMs,
      pyodide: pyodide.version,
      measure,
    }) + "\n",
  );
}

await main();
