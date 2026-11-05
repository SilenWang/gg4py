/**
 * M3-4 · 导出：SVG / PNG / JPG（1× / 2× / 4×，或直接给 DPI）。
 *
 * 只走浏览器自带的栅格化：`<svg>` → Blob → `<img>` → `<canvas>` → `toBlob()`。
 * 没有 wasm、没有 skia，也不需要（`docs/notes/device.md`：浏览器里只有 PDF 必须
 * 走桌面）。PNG/JPG 与桌面 skia 的产物**不逐字节相同**，但「导出与屏幕所见一致」
 * 这条要求在同一个浏览器里是可判定的：同缩放倍数下，导出的 PNG 与页面上的 SVG
 * 逐像素相同（`tools/editor/check_editor.py` 就在比这件事）。
 *
 * 两件事决定像素能不能对齐：
 *
 * 1. **尺寸口径**。IR 场景的单位是 pt，页面把它按 1 pt = 1 px 显示（`main.js`
 *    设的是整数 px）；导出第 n 倍就是 `round(pt * n)` 像素，与屏幕同一个取整。
 *    1× = 72 dpi（1 inch = 72 pt），所以 `dpi` 与倍数只是一件事的两种写法。
 * 2. **字体必须内嵌**。`<img>` 加载的 SVG 是独立文档，拿不到页面的 `@font-face`；
 *    不内嵌就会掉到系统字体，量出来的字宽与实际画出来的对不上。这里把
 *    `../viewer/fonts.css` 里**实际用到**的字面转成 data URI 塞进导出的 SVG
 *    （只带主字族的主字面，不把 CJK 35 MB 拖进每一张图）。
 */

const SVG_NS = "http://www.w3.org/2000/svg";
const XLINK_NS = "http://www.w3.org/1999/xlink";
const FONT_CSS_URL = new URL("../viewer/fonts.css", import.meta.url);

/** CSS 通用字族：出现在回退栈里，但不是字体文件名。 */
const GENERIC_FAMILIES = new Set([
  "sans",
  "sans-serif",
  "serif",
  "mono",
  "monospace",
  "cursive",
  "fantasy",
  "system-ui",
  "ui-sans-serif",
  "ui-serif",
  "ui-monospace",
]);

/** 场景的 pt 尺寸：优先 `data-size`（渲染器写的 `"360x252"`），否则读 viewBox。 */
export function sceneSize(svg) {
  const declared = svg.getAttribute("data-size");
  if (declared) {
    const [width, height] = declared.split("x").map(Number);
    if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
      return { width, height };
    }
  }
  const box = (svg.getAttribute("viewBox") ?? "").trim().split(/[\s,]+/).map(Number);
  if (box.length === 4 && Number.isFinite(box[2]) && Number.isFinite(box[3])) {
    return { width: box[2], height: box[3] };
  }
  throw new Error("这张 SVG 没有尺寸（缺 data-size / viewBox）");
}

// ---------------------------------------------------------------------------
// 字体：`viewer/fonts.css` → 实际用到的字面 → data URI
// ---------------------------------------------------------------------------

let facesPromise = null;

/** 解析 `@font-face` 块。viewer 的 fonts.css 由 emit_fonts.py 生成，格式固定。 */
function parseFaces(css) {
  const faces = [];
  for (const match of css.matchAll(/@font-face\s*\{([^}]*)\}/g)) {
    const body = match[1];
    const family = /font-family:\s*([^;]+);/.exec(body)?.[1]?.trim().replace(/^["']|["']$/g, "");
    const src = /src:\s*url\(\s*["']?([^"')]+)["']?\s*\)/.exec(body)?.[1]?.trim();
    if (!family || !src) continue;
    const weight = /font-weight:\s*([^;]+);/.exec(body)?.[1]?.trim() ?? "400";
    const style = /font-style:\s*([^;]+);/.exec(body)?.[1]?.trim() ?? "normal";
    faces.push({ family, src, weight, style });
  }
  return faces;
}

function loadFaces() {
  if (facesPromise === null) {
    facesPromise = fetch(FONT_CSS_URL)
      .then((response) => {
        if (!response.ok) throw new Error(`fonts.css: HTTP ${response.status}`);
        return response.text();
      })
      .then(parseFaces)
      .catch((error) => {
        console.warn("字体表读不到，导出的 SVG 不内嵌字体", error);
        return [];
      });
  }
  return facesPromise;
}

/** `font-weight` 可能是单值（400）也可能是区间（`100 900`，可变字体）。 */
function weightMatches(spec, weight) {
  const parts = String(spec).trim().split(/\s+/).map(Number);
  const value = Number(weight) || 400;
  if (parts.length === 1) return Number.isFinite(parts[0]) ? parts[0] === value : true;
  if (parts.length === 2) return value >= parts[0] && value <= parts[1];
  return true;
}

function firstFamily(value) {
  if (!value) return null;
  // 第一个**真实**字族：`sans` / `sans-serif` 这类是 CSS 通用族，不是字体文件名，
  // 把它们当字族去 `fonts.css` 里找字面永远找不到（ggcore 的 IR 里 font = "sans"）。
  for (const part of value.split(",")) {
    const name = part.trim().replace(/^["']|["']$/g, "");
    if (!name) continue;
    if (GENERIC_FAMILIES.has(name.toLowerCase())) continue;
    return name;
  }
  return null;
}

/** 导出的 SVG 里真正用到的 (字族, 粗细, 斜体) 组合。 */
function usedFonts(svg) {
  const used = new Map();
  for (const element of svg.querySelectorAll("text")) {
    const family = firstFamily(element.getAttribute("font-family"));
    if (!family) continue;
    const weight = element.getAttribute("font-weight") || "normal";
    const style = element.getAttribute("font-style") || "normal";
    used.set(`${family}|${weight}|${style}`, { family, weight, style });
  }
  return [...used.values()];
}

const dataUriCache = new Map();

async function dataUri(url) {
  if (dataUriCache.has(url)) return dataUriCache.get(url);
  const promise = (async () => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    let binary = "";
    const chunk = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunk) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
    }
    return `data:font/ttf;base64,${btoa(binary)}`;
  })();
  dataUriCache.set(url, promise);
  return promise;
}

/**
 * 给导出的 SVG 拼一份 `@font-face` 样式。
 *
 * 只按**主字族**取字面：回退栈里还有 CJK / emoji / DejaVu，把它们的字面都塞进
 * 每个导出文件既慢又大，而 ASCII 文本本来就用不到。
 */
async function embeddedFontCss(svg) {
  const faces = await loadFaces();
  if (faces.length === 0) return "";
  const wanted = [];
  const seen = new Set();
  for (const used of usedFonts(svg)) {
    const familyFaces = faces.filter(
      (face) => face.family.toLowerCase() === used.family.toLowerCase(),
    );
    if (familyFaces.length === 0) continue;
    const style = used.style.includes("italic") ? "italic" : "normal";
    const matched = familyFaces.filter(
      (face) =>
        (face.style.includes("italic") ? "italic" : "normal") === style &&
        weightMatches(face.weight, used.weight),
    );
    const chosen = matched.length > 0 ? matched : familyFaces;
    for (const face of chosen) {
      const key = `${face.family}|${face.weight}|${face.style}`;
      if (seen.has(key)) continue;
      seen.add(key);
      wanted.push({ face, where: used });
    }
  }
  if (wanted.length === 0) return "";
  const rules = await Promise.all(
    wanted.map(async ({ face, where }) => {
      const url = await dataUri(new URL(face.src, FONT_CSS_URL).href);
      const weight = /^\d+(\s+\d+)?$/.test(face.weight) ? face.weight : 400;
      return (
        `@font-face{font-family:"${face.family}";src:url(${url}) format("truetype");` +
        `font-weight:${weight};font-style:${face.style.includes("italic") ? "italic" : "normal"};` +
        `font-display:block}`
      );
    }),
  );
  // 供测试断言「内嵌的是用到的那些字面」。
  svg.dataset.embeddedFonts = wanted.map(({ face }) => `${face.family}:${face.weight}:${face.style}`).join(";");
  return rules.join("\n");
}

// ---------------------------------------------------------------------------
// 序列化 / 栅格化
// ---------------------------------------------------------------------------

/** 把页面上的 `<svg>` 序列化成独立文档（显式 px 尺寸 + 内嵌字体）。 */
export async function serializeSvg(svg, { scale = 1 } = {}) {
  const { width, height } = sceneSize(svg);
  const clone = svg.cloneNode(true);
  clone.setAttribute("width", String(Math.max(1, Math.round(width * scale))));
  clone.setAttribute("height", String(Math.max(1, Math.round(height * scale))));
  clone.setAttribute("xmlns", SVG_NS);
  clone.setAttribute("xmlns:xlink", XLINK_NS);
  // 页面上的 `style="width:360px"` 是显示口径，导出文档里由 width/height 决定。
  clone.removeAttribute("style");
  clone.removeAttribute("class");
  const css = await embeddedFontCss(clone);
  if (css) {
    const style = document.createElementNS(SVG_NS, "style");
    style.setAttribute("type", "text/css");
    style.textContent = `\n${css}\n`;
    clone.insertBefore(style, clone.firstChild);
  }
  return `<?xml version="1.0" encoding="UTF-8"?>\n${new XMLSerializer().serializeToString(clone)}`;
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("SVG 栅格化失败（浏览器拒绝了这张图）"));
    image.src = url;
  });
}

/**
 * 导出一张图。
 *
 * @param {SVGSVGElement} svg 页面上的渲染结果（`renderScene()` 的 `svg`）
 * @param {{format?: "svg"|"png"|"jpg", scale?: number, dpi?: number, quality?: number}} options
 *        `dpi` 优先于 `scale`（1× = 72 dpi）；`quality` 只对 JPG 生效。
 * @returns {Promise<{blob: Blob, mime: string, width: number, height: number, pixels: string}>}
 */
export async function exportPlot(svg, options = {}) {
  const format = options.format ?? "png";
  // `scale` 优先：显式给了倍数就不要再被默认 DPI（72）当成 1× 盖掉。
  const scale = options.scale ?? (options.dpi ? options.dpi / 72.0 : 1);
  const quality = options.quality ?? 0.92;
  if (!(scale > 0)) throw new Error(`缩放必须为正，收到 ${scale}`);
  const { width, height } = sceneSize(svg);
  const pxWidth = Math.max(1, Math.round(width * scale));
  const pxHeight = Math.max(1, Math.round(height * scale));
  const svgText = await serializeSvg(svg, { scale });

  if (format === "svg") {
    return {
      blob: new Blob([svgText], { type: "image/svg+xml;charset=utf-8" }),
      mime: "image/svg+xml",
      width: pxWidth,
      height: pxHeight,
      pixels: `${pxWidth}×${pxHeight}`,
    };
  }

  const jpeg = format === "jpg" || format === "jpeg";
  const url = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const image = await loadImage(url);
    const canvas = document.createElement("canvas");
    canvas.width = pxWidth;
    canvas.height = pxHeight;
    const context = canvas.getContext("2d");
    if (context === null) throw new Error("这个浏览器拿不到 2D canvas");
    if (jpeg) {
      // JPG 没有透明的说法：先把底铺成白色（与屏幕上的白纸一致）。
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, pxWidth, pxHeight);
    }
    // SVG 由浏览器按 canvas 的像素尺寸重新栅格化（向量放大，不是位图拉伸）。
    context.drawImage(image, 0, 0, pxWidth, pxHeight);
    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob(
        (out) => (out ? resolve(out) : reject(new Error("toBlob() 返回空"))),
        jpeg ? "image/jpeg" : "image/png",
        jpeg ? quality : undefined,
      );
    });
    return { blob, mime: jpeg ? "image/jpeg" : "image/png", width: pxWidth, height: pxHeight, pixels: `${pxWidth}×${pxHeight}` };
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Blob → base64（不含 data: 前缀）：页面下载与测试取字节都走它。 */
export async function blobToBase64(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
  }
  return btoa(binary);
}
