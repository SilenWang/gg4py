/**
 * 查看器入口：读 `.ggir.cbor` → 解码 → IR → DOM SVG → 交互。
 *
 * 零 wasm：页面只加载 `dist/*.js` 与 CSS，没有任何 `.wasm` 请求（`tests/test_viewer.py`
 * 用 Playwright 的网络日志钉住这一条）。
 */

import { IrError, decodeScene } from "./ir.js";
import type { IrScene } from "./ir.js";
import { attachInteractions } from "./interact.js";
import type { Interaction } from "./interact.js";
import { renderScene } from "./render.js";
import type { RenderResult } from "./render.js";

const stage = requireElement<HTMLElement>("#stage");
const status = requireElement<HTMLElement>("#status");
const tooltip = requireElement<HTMLElement>("#tooltip");
const picker = requireElement<HTMLInputElement>("#file");
const reset = requireElement<HTMLButtonElement>("#reset");

let interaction: Interaction | null = null;
let current: { scene: IrScene; result: RenderResult } | null = null;

function requireElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (element === null) throw new Error(`页面缺少 ${selector}`);
  return element;
}

function showError(error: unknown): void {
  stage.replaceChildren();
  interaction = null;
  current = null;
  const message = error instanceof Error ? error.message : String(error);
  status.textContent = `加载失败：${message}`;
  status.dataset.state = "error";
  // 详细原因（含节点 id）放进提示框，别只留在控制台。
  tooltip.replaceChildren();
  const body = document.createElement("div");
  body.className = "tooltip-text";
  body.textContent = message;
  tooltip.append(body);
  tooltip.hidden = false;
  tooltip.style.left = "16px";
  tooltip.style.top = "16px";
  console.error(error);
}

export function loadBytes(bytes: Uint8Array, name: string): void {
  try {
    const scene = decodeScene(bytes);
    const result = renderScene(scene);
    stage.replaceChildren(result.svg);
    tooltip.hidden = true;
    interaction = attachInteractions(result, tooltip);
    current = { scene, result };
    status.dataset.state = "ok";
    status.textContent =
      `${name} · ${trim(scene.size[0])}×${trim(scene.size[1])} pt · ` +
      `${result.nodeCount} 个 IR 节点 / ${result.leaves.length} 个图元 · ` +
      `${interaction.legends.length} 个图例项（可点击开关）`;
  } catch (error) {
    if (error instanceof IrError) {
      console.warn(`IR 解码失败（node=${error.nodeId || "-"}）: ${error.message}`);
    }
    showError(error);
  }
}

async function loadFile(file: File): Promise<void> {
  status.dataset.state = "loading";
  status.textContent = `读取 ${file.name}…`;
  try {
    loadBytes(new Uint8Array(await file.arrayBuffer()), file.name);
  } catch (error) {
    showError(error);
  }
}

function trim(value: number): string {
  return String(Math.round(value * 100) / 100);
}

picker.addEventListener("change", () => {
  const file = picker.files?.[0];
  if (file !== undefined) void loadFile(file);
});

reset.addEventListener("click", () => {
  interaction?.reset();
});

for (const type of ["dragenter", "dragover"] as const) {
  document.addEventListener(type, (event) => {
    event.preventDefault();
    document.body.classList.add("is-dragging");
  });
}

for (const type of ["dragleave", "drop"] as const) {
  document.addEventListener(type, (event) => {
    event.preventDefault();
    if (type === "dragleave" && event.target !== document.documentElement) return;
    document.body.classList.remove("is-dragging");
  });
}

document.addEventListener("drop", (event) => {
  const file = event.dataTransfer?.files?.[0];
  if (file !== undefined) void loadFile(file);
});

// 给测试与调试留一个只读入口：`ggViewer.state()` 返回当前场景的计数。
declare global {
  interface Window {
    ggViewer?: {
      loadBytes(bytes: Uint8Array, name: string): void;
      state(): { nodes: number; leaves: number; legends: number; size: [number, number] } | null;
    };
  }
}

window.ggViewer = {
  loadBytes,
  state: () =>
    current === null
      ? null
      : {
          nodes: current.result.nodeCount,
          leaves: current.result.leaves.length,
          legends: interaction?.legends.length ?? 0,
          size: current.scene.size,
        },
};

// gallery.html 的卡片链到 `index.html?scene=gallery/<case>.ggir.cbor`：
// 同一个 viewer 页面自动加载，hover / 图例开关都能直接用。路径按相对 URL 取，
// 不走 file://（ES module 本来也只支持 http）。
const sceneParam = new URLSearchParams(window.location.search).get("scene");
if (sceneParam !== null && sceneParam !== "") {
  const name = sceneParam.split("/").pop() ?? sceneParam;
  status.dataset.state = "loading";
  status.textContent = `读取 ${name}…`;
  void fetch(sceneParam)
    .then((response) => {
      if (!response.ok) throw new Error(`${sceneParam}: HTTP ${response.status}`);
      return response.arrayBuffer();
    })
    .then((buffer) => loadBytes(new Uint8Array(buffer), name))
    .catch(showError);
} else {
  status.textContent = "把 .ggir.cbor 拖进来，或点「打开文件」。";
}
