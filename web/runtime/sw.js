// SIL-824 · Service Worker：只接管 `vendor/`，两件事——报下载进度、给 warm 启动铺路。
//
// 为什么进度要放在 SW 里：wasm（9.6 MB）与 stdlib（2.5 MB）是 **pyodide 自己**
// fetch 的，页面拿不到逐字节回调；而 SW 在中间，可以把响应体 tee 一份出来数字节，
// 同时把原始流照常交给 pyodide（不改变时序，也不整包缓冲）。
//
// 缓存策略：vendor 下的文件是**版本化**的（`pyodide:assets` 重建，manifest 带
// sha256），所以 cache-first 安全；命中就不发请求，warm 首访的字节数因此只剩
// 页面自身的几十 KB。
//
// 边界：只处理同源 GET + `/vendor/` 下的路径。页面、脚本、dist 走浏览器自己的
// HTTP 缓存，SW 不掺和（否则「warm 命中」到底命中的是谁就说不清了）。

// SIL-830：缓存名带版本。资产换了（zip → tar、gzip → brotli）之后，旧缓存里的响应
// 少了「摘掉 Content-Encoding」的修正，必须让它们整体作废，不能靠运行时兜。
const CACHE = "gg4py-runtime-vendor-v2";
//: 只接管这些前缀：`/vendor/` 是本工程约定的资产目录。
const SCOPE = "/vendor/";

self.addEventListener("install", (event) => {
  // 不预缓存：首访的 9.6 MB 要走「真实下载 + 逐字节进度」，预缓存会把这两个
  // 观测点都藏进 install 阶段。缓存是首访时顺带填的。
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // 旧版本的缓存（`gg4py-runtime-vendor` / …-v1）直接删：里面的响应是按旧规则
      // 缓存的，留着只会让 warm 拿到不该拿的字节。
      for (const key of await caches.keys()) {
        if (key !== CACHE) await caches.delete(key);
      }
      await self.clients.claim();
    })(),
  );
});

async function broadcast(message) {
  const clients = await self.clients.matchAll({ includeUncontrolled: true, type: "window" });
  for (const client of clients) client.postMessage(message);
}

async function streamAndCache(event, response) {
  const url = new URL(event.request.url);
  // `content-length` 是**压缩后**的长度，而下面数的 `loaded` 是解码后的（brotli 的
  // wasm 会报成 9.6 / 2.74 MB）。页面用的是自己按 manifest 算的分母，这个 total 只是
  // 附带的参考值，不参与百分比。
  const total = Number(response.headers.get("content-length")) || 0;
  if (response.body === null) return response;

  const [body, copy] = response.body.tee();
  // 缓存里存的是**解码后**的字节（`response.body` 由浏览器解码，gzip / brotli 都
  // 一样），所以落缓存时必须把 `Content-Encoding` / `Content-Length` 摘掉：
  // 带着 `Content-Encoding: br` 存解码后的明文，warm 时回放会被再解一次（SIL-830
  // 把 wasm / 源码包都换成了 brotli 预压缩，这条从「侥幸」变成「必须」）。
  const headers = Array.from(response.headers.entries()).filter(
    ([name]) => !["content-encoding", "content-length"].includes(name.toLowerCase()),
  );

  // 旁路：数字节 → 内存里攒一份 → 攒齐后写 cache。
  (async () => {
    const reader = copy.getReader();
    const chunks = [];
    let loaded = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        loaded += value.byteLength;
        await broadcast({ type: "vendor-progress", file: url.pathname, loaded, total, done: false });
      }
      await broadcast({ type: "vendor-progress", file: url.pathname, loaded, total, done: true });
      const cache = await caches.open(CACHE);
      await cache.put(
        event.request,
        new Response(new Blob(chunks), {
          status: 200,
          statusText: "OK",
          headers: [...headers, ["Content-Length", String(loaded)]],
        }),
      );
    } catch (error) {
      await broadcast({ type: "vendor-progress-error", file: url.pathname, message: String(error) });
    }
  })();

  return new Response(body, { status: response.status, statusText: response.statusText, headers });
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.includes(SCOPE)) return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      const hit = await cache.match(request);
      if (hit) {
        await broadcast({
          type: "vendor-progress",
          file: url.pathname,
          loaded: 0,
          total: Number(hit.headers.get("content-length")) || 0,
          done: true,
          cached: true,
        });
        return hit;
      }
      const response = await fetch(request);
      if (!response.ok) return response;
      return streamAndCache(event, response);
    })(),
  );
});
