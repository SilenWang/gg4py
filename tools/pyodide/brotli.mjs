// SIL-830 · 用 node 自带的 zlib 做 brotli 预压缩（不引入新的压缩库依赖）。
//
// 为什么在**构建期**压：`wasm` 是 9.6 MB，按请求现压（`gzip.compress`）会让首字节
// 晚到几百毫秒；brotli q11 更是要 20 s，只能在构建期算一次。产物是 `<file>.br`
// 兄弟文件，静态服务按 `Content-Encoding: br` 回放（nginx 的 `brotli_static on`
// 是同一个语义），浏览器侧完全不感知。
//
// 用法：
//   node tools/pyodide/brotli.mjs <quality> <in> <out>
// 输出：一行 JSON `{"in":..,"out":..,"quality":..}`，方便 stage_assets.py 记账。

import { readFileSync, writeFileSync } from "node:fs";
import { brotliCompressSync, constants } from "node:zlib";

const [qualityArg, input, output] = process.argv.slice(2);
if (!input || !output) {
  console.error("usage: node tools/pyodide/brotli.mjs <quality> <in> <out>");
  process.exit(2);
}
const quality = Number(qualityArg ?? 11);
const data = readFileSync(input);
const started = Date.now();
const compressed = brotliCompressSync(data, {
  params: {
    [constants.BROTLI_PARAM_QUALITY]: quality,
    [constants.BROTLI_PARAM_SIZE_HINT]: data.length,
    [constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_GENERIC,
  },
});
writeFileSync(output, compressed);
process.stdout.write(
  JSON.stringify({
    in: input,
    out: output,
    bytes: data.length,
    wire_bytes: compressed.length,
    quality,
    ms: Date.now() - started,
  }) + "\n",
);
