/**
 * 交互：hover 提示 + 图例开关。
 *
 * 作用域（细节与已知缺口见 `docs/notes/viewer.md`）：
 *
 * - **hover**：命中一个叶子（`data-row` 的那个 SVG 元素），提示框显示它所在的
 *   具名视口（`panel-1-1` 这类名字来自 IR 的 `viewport.name`）、geom 层（按 IR
 *   图元种类推断，IR v0 没有层名字段）、节点 id 与数据行号（缓冲行）。`points`
 *   这类整节点合成为单个元素的图元只到节点粒度，显示 `1–rows` 的行范围。
 * - **图例**：名字形如 `<guide>-key-<i>` 的视口就是图例 key 的节点组。点它把
 *   这一组（key 图元 + 同一个 guide 里与它纵向对齐的 key 底框 / 标签文字）
 *   隐藏 / 显示。IR 没有 key→entry 的归属字段，配对靠页面包围盒的纵向对齐，
 *   这条推断记在 viewer.md 的缺口表里。
 */

import type { Box, RenderResult, RenderedLeaf, RenderedViewport } from "./render.js";

const KEY_PATTERN = /^(.*)-key-(\d+)$/;

/** IR 图元种类 → geom 名（IR 里没有层名，按图元推断，见 viewer.md 缺口表）。 */
const GEOM_LABEL: Record<string, string> = {
  points: "point",
  circle: "point",
  polyline: "line",
  path: "path",
  polygon: "polygon",
  rect: "bar / col",
  segments: "segment",
  text: "text",
  raster: "raster",
  xspline: "xspline",
  bezier: "bezier",
  curve: "curve",
};

export interface LegendEntry {
  key: string;
  guide: string;
  index: number;
  viewport: RenderedViewport;
  /** 一起隐藏的叶子：key 图元 + 同一 guide 里纵向对齐的底框 / 标签。 */
  members: RenderedLeaf[];
  hidden: boolean;
}

export interface Interaction {
  legends: LegendEntry[];
  reset(): void;
  hide(entry: LegendEntry, hidden: boolean): void;
}

export function attachInteractions(result: RenderResult, tooltip: HTMLElement): Interaction {
  const legends = legendEntries(result);
  const tooltipOwner = tooltip.parentElement ?? document.body;

  for (const entry of legends) {
    entry.viewport.group.setAttribute("data-legend-key", entry.key);
    entry.viewport.group.classList.add("gg-legend-key");
    entry.viewport.group.setAttribute("role", "button");
    entry.viewport.group.setAttribute("tabindex", "0");
    entry.viewport.group.setAttribute("aria-pressed", "false");
    entry.viewport.group.setAttribute("aria-label", `图例 ${entry.guide} 第 ${entry.index + 1} 项`);
    // 关掉以后 key 图元是 `display: none`，点击热区会跟着消失；盖一块透明矩形
    // 让同一个位置还能点回来（它没有 `data-row`，不参与图元计数）。
    const box = entry.viewport.bbox;
    if (box !== null) {
      const hit = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      hit.setAttribute("class", "gg-legend-hit");
      hit.setAttribute("x", String(box.x0));
      hit.setAttribute("y", String(box.y0));
      hit.setAttribute("width", String(Math.max(0, box.x1 - box.x0)));
      hit.setAttribute("height", String(Math.max(0, box.y1 - box.y0)));
      hit.setAttribute("fill", "transparent");
      entry.viewport.group.append(hit);
    }
  }

  const hide = (entry: LegendEntry, hidden: boolean): void => {
    entry.hidden = hidden;
    // 组本身保持可见（里面盖着一块透明热区），只把图元藏起来——这样再点一下
    // 就能恢复，不会出现“关掉以后点不回来”。
    entry.viewport.group.setAttribute("data-hidden", hidden ? "true" : "false");
    entry.viewport.group.setAttribute("aria-pressed", hidden ? "true" : "false");
    for (const member of entry.members) {
      member.element.setAttribute("data-hidden", hidden ? "true" : "false");
      member.element.style.display = hidden ? "none" : "";
    }
  };

  const showTooltip = (leaf: RenderedLeaf, event: MouseEvent): void => {
    const geom = GEOM_LABEL[leaf.kind] ?? leaf.kind;
    const where = leaf.viewport || "（未命名视口）";
    tooltip.replaceChildren();
    const title = document.createElement("div");
    title.className = "tooltip-title";
    title.textContent = `${where} · ${geom} 层`;
    tooltip.append(title);
    const meta = document.createElement("div");
    meta.className = "tooltip-meta";
    // 一个节点一个元素时（points / segments…）显示整段行范围，不假装能命中单行。
    const rows =
      leaf.rows > 1 ? `数据行 1–${leaf.rows}` : `数据行 ${leaf.row + 1}/${leaf.rows}`;
    meta.textContent = `节点 ${leaf.id} · ${rows}`;
    tooltip.append(meta);
    if (leaf.text) {
      const body = document.createElement("div");
      body.className = "tooltip-text";
      body.textContent = leaf.text;
      tooltip.append(body);
    }
    tooltip.hidden = false;
    const bounds = tooltipOwner.getBoundingClientRect();
    const left = event.clientX - bounds.left + 14;
    const top = event.clientY - bounds.top + 14;
    tooltip.style.left = `${Math.min(left, Math.max(0, bounds.width - tooltip.offsetWidth - 8))}px`;
    tooltip.style.top = `${Math.min(top, Math.max(0, bounds.height - tooltip.offsetHeight - 8))}px`;
  };

  result.svg.addEventListener("mouseover", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const element = target.closest<SVGElement>("[data-row]");
    if (element === null) return;
    const leaf = leavesByElement(result).get(element);
    if (leaf === undefined) return;
    element.classList.add("is-hover");
    showTooltip(leaf, event);
  });

  result.svg.addEventListener("mouseout", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const element = target.closest<SVGElement>("[data-row]");
    if (element !== null) element.classList.remove("is-hover");
    tooltip.hidden = true;
  });

  result.svg.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const key = target.closest<SVGGElement>("[data-legend-key]");
    if (key === null) return;
    const entry = legends.find((candidate) => candidate.viewport.group === key);
    if (entry === undefined) return;
    hide(entry, !entry.hidden);
  });

  return {
    legends,
    hide,
    reset(): void {
      for (const entry of legends) hide(entry, false);
    },
  };
}

/** 叶子元素 → 记录（`data-row` 的元素就是 leaf.element）。 */
function leavesByElement(result: RenderResult): Map<Element, RenderedLeaf> {
  const map = new Map<Element, RenderedLeaf>();
  for (const leaf of result.leaves) map.set(leaf.element, leaf);
  return map;
}

function legendEntries(result: RenderResult): LegendEntry[] {
  const entries: LegendEntry[] = [];
  for (const viewport of result.viewports) {
    const match = KEY_PATTERN.exec(viewport.name);
    if (match === null) continue;
    const [, guide, indexText] = match;
    const index = Number(indexText);
    const box = viewport.bbox;
    const members: RenderedLeaf[] = [];
    // IR 的视口是扁平的（连续同变换的指令合成一组），guide-0 与 guide-0-key-0
    // 是**兄弟**节点，不是父子；按名字前缀找同一个 guide 的组。
    const guideGroups = result.viewports.filter((candidate) => candidate.name === guide);
    for (const leaf of result.leaves) {
      if (viewport.group.contains(leaf.element)) {
        // key 自己的图元：跟着 key 组一起隐藏（状态也写在元素上，方便断言）。
        members.push(leaf);
        continue;
      }
      if (box === null) continue;
      if (!guideGroups.some((candidate) => candidate.group.contains(leaf.element))) continue;
      if (!verticallyAligned(leaf.bbox, box)) continue;
      members.push(leaf);
    }
    entries.push({ key: viewport.name, guide, index, viewport, members, hidden: false });
  }
  entries.sort((left, right) => left.guide.localeCompare(right.guide) || left.index - right.index);
  return entries;
}

/** 两个盒子在同一行：中心线落在对方的纵向范围内（图例 key / 底框 / 标签同一行）。 */
function verticallyAligned(candidate: Box, key: Box): boolean {
  const centre = (candidate.y0 + candidate.y1) / 2;
  return centre >= key.y0 - 0.5 && centre <= key.y1 + 0.5;
}
