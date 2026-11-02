/**
 * IR v0（0.2）的解码与字段校验 —— 查看器唯一的数据入口。
 *
 * 口径与 `docs/notes/ir.md` 一一对应，改动先改那份文档：
 *
 * - 线格式是 canonical CBOR；bulk 数据是**原始 float32 / int32 小端字节**，
 *   不经过逐元素 JSON（`docs/notes/ir.md` §2 / §10）。
 * - 只认 major 0。minor ≤ 本实现时未知键报错（防止截断被静默吞掉），
 *   minor > 本实现时未知键跳过；未知节点种类 / 未知缓冲 dtype 两档都报错。
 * - 校验失败要能指出是哪个节点：错误信息带上节点 id（根视口是 `0`，
 *   子节点按 `0/3/2` 这样的索引路径），不猜、不降级。
 *
 * 这个文件只依赖 DOM 之外的标准库能力（DataView / TextDecoder），零 wasm。
 */

export type Color = [number, number, number, number];

export interface Gpar {
  fill: Color | null;
  col: Color | null;
  lwd: number;
  lty: number[];
  lineend: "round" | "butt" | "square";
  linejoin: "round" | "miter" | "bevel";
  linemitre: number;
  alpha: number;
}

export interface FloatBuffer {
  dtype: "f4" | "i4";
  rows: number;
  cols: number; // 一维缓冲是 1
  data: Float32Array | Int32Array;
}

export interface Blob {
  mime: string;
  data: Uint8Array;
}

export interface IrNode {
  kind: string;
  gpar: Gpar | null;
  params: Record<string, unknown>;
  bufs: Record<string, FloatBuffer>;
  texts: string[];
  children: IrNode[];
}

export interface IrScene {
  size: [number, number];
  dpi: number;
  blobs: Record<string, Blob>;
  root: IrNode;
}

/** 解码/校验错误。`nodeId` 非空时说明是哪个节点坏了。 */
export class IrError extends Error {
  readonly nodeId: string;

  constructor(message: string, nodeId = "") {
    super(nodeId ? `节点 ${nodeId}：${message}` : message);
    this.name = "IrError";
    this.nodeId = nodeId;
  }
}

/** major 不认识（`docs/notes/ir.md` §3）：查看器不猜相近版本。 */
export class IrVersionError extends IrError {
  constructor(message: string) {
    super(message);
    this.name = "IrVersionError";
  }
}

export const IR_MAJOR = 0;
export const IR_MINOR = 2;
export const DEFAULT_MIME = "application/octet-stream";

export const DEFAULT_GPAR: Gpar = {
  fill: null,
  col: null,
  lwd: 1.0,
  lty: [],
  lineend: "round",
  linejoin: "round",
  linemitre: 1.0,
  alpha: 1.0,
};

// ---------------------------------------------------------------------------
// 节点表：与 src/ggcore/ir/nodes.py 的 NODE_SPECS 同构（只留查看器要用的部分）
// ---------------------------------------------------------------------------

type ParamTag =
  | "str"
  | "float"
  | "int"
  | "bool"
  | "transform"
  | "anchor"
  | "baseline"
  | "fill_rule";

interface BufferSpec {
  dtype: "f4" | "i4";
  cols: number | null; // null = 一维
  required: boolean;
}

interface ParamSpec {
  tag: ParamTag;
  def?: unknown;
  required?: boolean;
}

interface NodeSpec {
  bufs: Record<string, BufferSpec>;
  params: Record<string, ParamSpec>;
  children: boolean;
  gpar: boolean;
  texts: boolean;
}

const F4 = (cols: number | null, required = true): BufferSpec => ({
  dtype: "f4",
  cols,
  required,
});
const ID = (): BufferSpec => ({ dtype: "i4", cols: null, required: false });
const P = (tag: ParamTag, def?: unknown): ParamSpec =>
  def === undefined ? { tag, required: true } : { tag, def };
const TRANSFORM: ParamSpec = { tag: "transform", def: [1, 0, 0, 1, 0, 0] };

const NODE_SPECS: Record<string, NodeSpec> = {
  viewport: {
    bufs: { clip_rect: F4(4, false) },
    params: { name: P("str", ""), clip: P("bool", true), transform: TRANSFORM },
    children: true,
    gpar: false,
    texts: false,
  },
  gtree: {
    bufs: {},
    params: { name: P("str", "") },
    children: true,
    gpar: false,
    texts: false,
  },
  clip: {
    bufs: { rect: F4(4, false), points: F4(2, false), id: ID() },
    params: { name: P("str", ""), rule: P("fill_rule", "winding") },
    children: true,
    gpar: false,
    texts: false,
  },
  rect: { bufs: { rect: F4(4) }, params: {}, children: false, gpar: true, texts: false },
  circle: { bufs: { circle: F4(3) }, params: {}, children: false, gpar: true, texts: false },
  lines: {
    bufs: { points: F4(2), id: ID() },
    params: {},
    children: false,
    gpar: true,
    texts: false,
  },
  segments: { bufs: { segments: F4(4) }, params: {}, children: false, gpar: true, texts: false },
  polyline: {
    bufs: { points: F4(2), id: ID() },
    params: {},
    children: false,
    gpar: true,
    texts: false,
  },
  polygon: {
    bufs: { points: F4(2), id: ID() },
    params: {},
    children: false,
    gpar: true,
    texts: false,
  },
  path: {
    bufs: { points: F4(2), id: ID() },
    params: { rule: P("fill_rule", "winding") },
    children: false,
    gpar: true,
    texts: false,
  },
  points: {
    bufs: { points: F4(2) },
    params: { pch: P("int", 1), size: P("float", 1.0) },
    children: false,
    gpar: true,
    texts: false,
  },
  text: {
    bufs: { pos: F4(2), width: F4(null) },
    params: {
      font: P("str"),
      size: P("float"),
      anchor: P("anchor", "center"),
      baseline: P("baseline", "middle"),
      angle: P("float", 0.0),
    },
    children: false,
    gpar: true,
    texts: true,
  },
  raster: {
    bufs: { rect: F4(4) },
    params: {
      blob: P("str"),
      width: P("int"),
      height: P("int"),
      interpolate: P("bool", true),
    },
    children: false,
    gpar: true,
    texts: false,
  },
  xspline: {
    bufs: { points: F4(2), id: ID() },
    params: { shape: P("float", 0.0), open: P("bool", true) },
    children: false,
    gpar: true,
    texts: false,
  },
  bezier: { bufs: { control: F4(2) }, params: {}, children: false, gpar: true, texts: false },
  curve: {
    bufs: { ends: F4(4) },
    params: {
      curvature: P("float", 1.0),
      angle: P("float", 90.0),
      ncp: P("int", 1),
      shape: P("float", 0.5),
      square: P("bool", true),
      inflect: P("bool", false),
      open: P("bool", true),
    },
    children: false,
    gpar: true,
    texts: false,
  },
  null: { bufs: {}, params: {}, children: false, gpar: false, texts: false },
  zero: { bufs: {}, params: {}, children: false, gpar: false, texts: false },
};

const GPAR_KEYS = new Set([
  "fill",
  "col",
  "lwd",
  "lty",
  "lineend",
  "linejoin",
  "linemitre",
  "alpha",
]);
const NODE_KEYS = new Set(["kind", "gpar", "params", "bufs", "texts", "children"]);
const SCENE_KEYS = new Set(["size", "dpi", "blobs", "root"]);
const ENVELOPE_KEYS = new Set(["magic", "ir_version", "scene"]);

// ---------------------------------------------------------------------------
// CBOR（只读）
// ---------------------------------------------------------------------------

class CborReader {
  private readonly view: DataView;
  private pos = 0;

  constructor(private readonly bytes: Uint8Array) {
    this.view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  }

  read(): unknown {
    if (this.pos >= this.bytes.length) {
      throw new IrError("CBOR 在读到值之前就结束了（文件被截断？）");
    }
    const initial = this.bytes[this.pos++];
    const major = initial >> 5;
    const info = initial & 0x1f;
    switch (major) {
      case 0:
        return this.integer(info);
      case 1:
        return -1 - this.integer(info);
      case 2:
        return this.byteString(info);
      case 3:
        return new TextDecoder("utf-8", { fatal: true }).decode(this.byteString(info));
      case 4: {
        const length = this.length(info);
        const items: unknown[] = [];
        for (let i = 0; i < length; i++) items.push(this.read());
        return items;
      }
      case 5: {
        const length = this.length(info);
        const map = new Map<string, unknown>();
        for (let i = 0; i < length; i++) {
          const key = this.read();
          if (typeof key !== "string") {
            throw new IrError(`CBOR 映射的键必须是字符串，收到 ${typeof key}`);
          }
          map.set(key, this.read());
        }
        return map;
      }
      case 6:
        // IR 线格式不写 tag（canonical CBOR 的 major 0/1 够用，docs/notes/ir.md §4）。
        throw new IrError("CBOR 里出现 tag，IR 线格式不写 tag（bignum 等都不支持）");
      case 7:
        return this.simple(info);
      default:
        throw new IrError(`CBOR major ${major} 不认识`);
    }
  }

  private integer(info: number): number {
    if (info < 24) return info;
    if (info === 24) return this.view.getUint8(this.take(1));
    if (info === 25) return this.view.getUint16(this.take(2), false);
    if (info === 26) return this.view.getUint32(this.take(4), false);
    if (info === 27) {
      const value = this.view.getBigUint64(this.take(8), false);
      if (value > BigInt(Number.MAX_SAFE_INTEGER)) {
        throw new IrError("CBOR 整数超出 JS 安全范围");
      }
      return Number(value);
    }
    throw new IrError(`CBOR 不定长 / 保留的附加信息 ${info} 不支持`);
  }

  private length(info: number): number {
    if (info === 31) throw new IrError("CBOR 不定长容器不支持（canonical 编码不会写）");
    return this.integer(info);
  }

  private byteString(info: number): Uint8Array {
    const length = this.length(info);
    const start = this.take(length);
    return this.bytes.subarray(start, start + length);
  }

  private simple(info: number): unknown {
    if (info === 20) return false;
    if (info === 21) return true;
    if (info === 22) return null;
    if (info === 23) return undefined;
    if (info === 25) return this.half(this.view.getUint16(this.take(2), false));
    if (info === 26) return this.view.getFloat32(this.take(4), false);
    if (info === 27) return this.view.getFloat64(this.take(8), false);
    throw new IrError(`CBOR simple/float 取值 ${info} 不支持`);
  }

  private half(bits: number): number {
    const sign = bits & 0x8000 ? -1 : 1;
    const exponent = (bits >> 10) & 0x1f;
    const fraction = bits & 0x3ff;
    if (exponent === 0) return sign * fraction * 2 ** -24;
    if (exponent === 31) return fraction === 0 ? sign * Infinity : NaN;
    return sign * (1 + fraction / 1024) * 2 ** (exponent - 15);
  }

  private take(count: number): number {
    if (this.pos + count > this.bytes.length) {
      throw new IrError("CBOR 数据在读到一半时结束（文件被截断？）");
    }
    const start = this.pos;
    this.pos += count;
    return start;
  }
}

/** 把 CBOR 字节解成 IR v0 的 `IrScene`；任何不合口径的输入都抛 `IrError`。 */
export function decodeScene(bytes: Uint8Array): IrScene {
  const raw = new CborReader(bytes).read();
  const envelope = asMap(raw, "文件根");
  rejectUnknown(envelope, ENVELOPE_KEYS, "文件根", "");

  if (envelope.get("magic") !== "ggir") {
    throw new IrError(`magic 必须是 "ggir"，收到 ${JSON.stringify(envelope.get("magic"))}`);
  }
  const version = envelope.get("ir_version");
  if (!Array.isArray(version) || version.length !== 2) {
    throw new IrError(`ir_version 必须是 [major, minor]，收到 ${JSON.stringify(version)}`);
  }
  const [major, minor] = version as number[];
  if (!Number.isInteger(major) || !Number.isInteger(minor)) {
    throw new IrVersionError(`ir_version 必须是整数对，收到 ${JSON.stringify(version)}`);
  }
  if (major !== IR_MAJOR) {
    throw new IrVersionError(
      `ir_version 的 major 是 ${major}，查看器只认 ${IR_MAJOR}.x（不猜相近版本）`,
    );
  }
  // minor ≤ 本实现：未知键 = 错误；minor 更新：未知键跳过（前向兼容）。
  const strict = minor <= IR_MINOR;

  const scene = asMap(envelope.get("scene"), "scene");
  rejectUnknown(scene, SCENE_KEYS, "scene", "");

  const size = asNumberPair(scene.get("size"), "scene.size");
  if (size[0] < 0 || size[1] < 0) {
    throw new IrError(`scene.size 不能为负，收到 ${JSON.stringify(size)}`);
  }
  const dpi = asNumber(scene.get("dpi") ?? 72.0, "scene.dpi");
  if (dpi <= 0) throw new IrError(`scene.dpi 必须为正，收到 ${dpi}`);

  const blobs: Record<string, Blob> = {};
  if (scene.has("blobs")) {
    for (const [id, entry] of asMap(scene.get("blobs"), "scene.blobs")) {
      const blob = asMap(entry, `blob ${id}`);
      const data = blob.get("data");
      if (!(data instanceof Uint8Array)) {
        throw new IrError(`blob ${id} 的 data 必须是字节串`);
      }
      const mime = blob.get("mime");
      blobs[id] = { mime: typeof mime === "string" && mime ? mime : DEFAULT_MIME, data };
    }
  }

  const root = decodeNode(scene.get("root"), "0", strict);
  if (root.kind !== "viewport") {
    throw new IrError(`Scene.root 必须是 viewport，收到 ${root.kind}`, "0");
  }
  return { size, dpi, blobs, root };
}

// ---------------------------------------------------------------------------
// 节点校验
// ---------------------------------------------------------------------------

function decodeNode(raw: unknown, id: string, strict: boolean): IrNode {
  const node = asMap(raw, `节点 ${id}`);
  const kind = node.get("kind");
  if (typeof kind !== "string") {
    throw new IrError("kind 必须是字符串", id);
  }
  const spec = NODE_SPECS[kind];
  if (spec === undefined) {
    // 未知节点种类两档都报错：画不出来的东西不能猜（docs/notes/ir.md §3）。
    throw new IrError(
      `未知节点种类 ${JSON.stringify(kind)}；可选：${Object.keys(NODE_SPECS).join(", ")}`,
      id,
    );
  }
  if (strict) rejectUnknown(node, NODE_KEYS, "节点", id);

  const gpar = spec.gpar ? decodeGpar(node.get("gpar"), id, strict) : null;
  if (!spec.gpar && node.has("gpar")) {
    throw new IrError(`${kind} 是容器/空节点，不携带 gpar`, id);
  }

  const params = decodeParams(node.get("params"), spec, kind, id, strict);
  const bufs = decodeBufs(node.get("bufs"), spec, kind, id, strict);

  const textsRaw = node.get("texts") ?? [];
  if (!Array.isArray(textsRaw)) {
    throw new IrError("texts 必须是字符串数组", id);
  }
  const texts = textsRaw.map((text) => {
    if (typeof text !== "string") throw new IrError("texts 必须是字符串数组", id);
    return text;
  });
  if (texts.length > 0 && !spec.texts) {
    throw new IrError(`${kind} 不携带文本`, id);
  }

  const childrenRaw = node.get("children") ?? [];
  if (!Array.isArray(childrenRaw)) {
    throw new IrError("children 必须是数组", id);
  }
  if (childrenRaw.length > 0 && !spec.children) {
    throw new IrError(`${kind} 是叶子节点，不能有 children`, id);
  }
  const children = childrenRaw.map((child, index) => decodeNode(child, `${id}/${index}`, strict));

  const result: IrNode = { kind, gpar, params, bufs, texts, children };
  checkCrossFields(result, id);
  return result;
}

function decodeGpar(raw: unknown, id: string, strict: boolean): Gpar {
  if (raw === undefined || raw === null) return { ...DEFAULT_GPAR };
  const map = asMap(raw, "gpar", id);
  if (strict) rejectUnknown(map, GPAR_KEYS, "gpar", id);
  const gpar: Gpar = { ...DEFAULT_GPAR };
  if (map.has("fill")) gpar.fill = colour(map.get("fill"), "gpar.fill", id);
  if (map.has("col")) gpar.col = colour(map.get("col"), "gpar.col", id);
  if (map.has("lwd")) {
    gpar.lwd = asNumber(map.get("lwd"), "gpar.lwd", id);
    if (gpar.lwd < 0) throw new IrError(`gpar.lwd 不能为负，收到 ${gpar.lwd}`, id);
  }
  if (map.has("lty")) {
    const lty = map.get("lty");
    if (!Array.isArray(lty)) throw new IrError("gpar.lty 必须是段长序列", id);
    gpar.lty = lty.map((segment) => {
      const value = asNumber(segment, "gpar.lty", id);
      if (value < 0) throw new IrError(`gpar.lty 的段长不能为负，收到 ${value}`, id);
      return value;
    });
  }
  if (map.has("lineend")) {
    const value = map.get("lineend");
    if (value !== "round" && value !== "butt" && value !== "square") {
      throw new IrError(`gpar.lineend 不认识：${JSON.stringify(value)}`, id);
    }
    gpar.lineend = value;
  }
  if (map.has("linejoin")) {
    const value = map.get("linejoin");
    if (value !== "round" && value !== "miter" && value !== "bevel") {
      throw new IrError(`gpar.linejoin 不认识：${JSON.stringify(value)}`, id);
    }
    gpar.linejoin = value;
  }
  if (map.has("linemitre")) {
    gpar.linemitre = asNumber(map.get("linemitre"), "gpar.linemitre", id);
    if (gpar.linemitre < 1) throw new IrError(`gpar.linemitre 不能小于 1`, id);
  }
  if (map.has("alpha")) {
    gpar.alpha = asNumber(map.get("alpha"), "gpar.alpha", id);
    if (gpar.alpha < 0 || gpar.alpha > 1) {
      throw new IrError(`gpar.alpha 必须在 [0, 1]，收到 ${gpar.alpha}`, id);
    }
  }
  return gpar;
}

function decodeParams(
  raw: unknown,
  spec: NodeSpec,
  kind: string,
  id: string,
  strict: boolean,
): Record<string, unknown> {
  const map = raw === undefined ? new Map<string, unknown>() : asMap(raw, "params", id);
  if (strict) {
    rejectUnknown(map, new Set(Object.keys(spec.params)), `${kind}.params`, id);
  }
  const out: Record<string, unknown> = {};
  for (const [name, fieldSpec] of Object.entries(spec.params)) {
    if (map.has(name)) {
      out[name] = checkParam(map.get(name), fieldSpec.tag, `${kind}.${name}`, id);
    } else if (fieldSpec.required) {
      throw new IrError(`缺少必填参数 ${JSON.stringify(name)}`, id);
    } else {
      out[name] = fieldSpec.def;
    }
  }
  return out;
}

function checkParam(value: unknown, tag: ParamTag, where: string, id: string): unknown {
  switch (tag) {
    case "str":
      if (typeof value !== "string") throw new IrError(`${where} 必须是字符串`, id);
      return value;
    case "float":
      return asNumber(value, where, id);
    case "int":
      if (!Number.isInteger(value)) throw new IrError(`${where} 必须是整数`, id);
      return value;
    case "bool":
      if (typeof value !== "boolean") throw new IrError(`${where} 必须是布尔值`, id);
      return value;
    case "transform": {
      if (!Array.isArray(value) || value.length !== 6) {
        throw new IrError(`${where} 必须是 6 个数的仿射元组`, id);
      }
      return value.map((component) => asNumber(component, where, id));
    }
    case "anchor":
      if (value !== "left" && value !== "center" && value !== "right") {
        throw new IrError(`${where} 不认识 ${JSON.stringify(value)}`, id);
      }
      return value;
    case "baseline":
      if (
        value !== "top" &&
        value !== "middle" &&
        value !== "bottom" &&
        value !== "alphabetic"
      ) {
        throw new IrError(`${where} 不认识 ${JSON.stringify(value)}`, id);
      }
      return value;
    case "fill_rule":
      if (value !== "winding" && value !== "evenodd") {
        throw new IrError(`${where} 不认识 ${JSON.stringify(value)}`, id);
      }
      return value;
  }
}

function decodeBufs(
  raw: unknown,
  spec: NodeSpec,
  kind: string,
  id: string,
  strict: boolean,
): Record<string, FloatBuffer> {
  const map = raw === undefined ? new Map<string, unknown>() : asMap(raw, "bufs", id);
  if (strict) rejectUnknown(map, new Set(Object.keys(spec.bufs)), `${kind}.bufs`, id);
  const out: Record<string, FloatBuffer> = {};
  for (const [name, bufferSpec] of Object.entries(spec.bufs)) {
    if (!map.has(name)) {
      if (bufferSpec.required) {
        throw new IrError(`缺少必填缓冲 ${JSON.stringify(name)}`, id);
      }
      continue;
    }
    const entry = asMap(map.get(name), `bufs.${name}`, id);
    rejectUnknown(entry, new Set(["dtype", "shape", "data"]), `bufs.${name}`, id);
    const dtype = entry.get("dtype");
    if (dtype !== "f4" && dtype !== "i4") {
      // 未知 dtype 两档都报错：新增 dtype 属于 major 变更。
      throw new IrError(`缓冲 ${name} 的 dtype 只能是 f4 / i4，收到 ${JSON.stringify(dtype)}`, id);
    }
    if (dtype !== bufferSpec.dtype) {
      throw new IrError(
        `缓冲 ${name} 的 dtype 必须是 ${bufferSpec.dtype}，收到 ${dtype}`,
        id,
      );
    }
    const shape = entry.get("shape");
    if (!Array.isArray(shape) || shape.some((n) => !Number.isInteger(n) || (n as number) < 0)) {
      throw new IrError(`缓冲 ${name} 的 shape 必须是非负整数数组`, id);
    }
    const dims = shape as number[];
    const expected = bufferSpec.cols === null ? 1 : 2;
    if (dims.length !== expected) {
      throw new IrError(`缓冲 ${name} 必须是 ${expected} 维，收到 shape=[${dims.join(", ")}]`, id);
    }
    if (bufferSpec.cols !== null && dims[1] !== bufferSpec.cols) {
      throw new IrError(`缓冲 ${name} 每行必须是 ${bufferSpec.cols} 个分量`, id);
    }
    const data = entry.get("data");
    if (!(data instanceof Uint8Array)) {
      throw new IrError(`缓冲 ${name} 的 data 必须是字节串`, id);
    }
    const rows = dims[0];
    const cols = bufferSpec.cols ?? 1;
    const count = rows * cols;
    if (data.byteLength !== count * 4) {
      throw new IrError(
        `缓冲 ${name} 的字节数 ${data.byteLength} 与 shape=[${dims.join(", ")}] 不符（期望 ${count * 4}）`,
        id,
      );
    }
    out[name] = { dtype, rows, cols, data: readBuffer(data, dtype, count) };
  }
  return out;
}

/** 线格式固定小端（`docs/notes/ir.md` §5）；用 DataView 显式按 LE 读。 */
function readBuffer(data: Uint8Array, dtype: "f4" | "i4", count: number): Float32Array | Int32Array {
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const out = dtype === "f4" ? new Float32Array(count) : new Int32Array(count);
  for (let i = 0; i < count; i++) {
    out[i] = dtype === "f4" ? view.getFloat32(i * 4, true) : view.getInt32(i * 4, true);
  }
  return out;
}

function checkCrossFields(node: IrNode, id: string): void {
  const kind = node.kind;
  if (node.texts.length > 0) {
    const pos = node.bufs["pos"];
    const width = node.bufs["width"];
    if (!pos || !width) {
      throw new IrError("text 缺少 pos / width 缓冲", id);
    }
    if (!(node.texts.length === pos.rows && pos.rows === width.rows)) {
      throw new IrError(
        `text 的 texts / pos / width 行数必须一致，收到 ${node.texts.length} / ${pos.rows} / ${width.rows}`,
        id,
      );
    }
  }
  if (kind === "viewport") {
    const clipRect = node.bufs["clip_rect"];
    if (node.params["clip"] === true && !clipRect) {
      throw new IrError("viewport.clip=True 时必须给 clip_rect", id);
    }
    if (clipRect && clipRect.rows !== 1) {
      throw new IrError("viewport.clip_rect 只能有一行", id);
    }
  }
  if (kind === "clip") {
    const hasRect = node.bufs["rect"] !== undefined;
    const hasPoints = node.bufs["points"] !== undefined;
    if (hasRect === hasPoints) {
      throw new IrError("clip 必须且只能给 rect 或 points 之一", id);
    }
    if (hasRect && node.bufs["rect"].rows !== 1) {
      throw new IrError("clip.rect 只能有一行", id);
    }
  }
  if (existsId(node) && node.bufs["points"] && node.bufs["id"].rows !== node.bufs["points"].rows) {
    throw new IrError(`${kind}.id 的行数必须和 points 一致`, id);
  }
  if (kind === "bezier" && node.bufs["control"].rows % 4 !== 0) {
    throw new IrError("bezier.control 的行数必须是 4 的倍数", id);
  }
}

function existsId(node: IrNode): boolean {
  return node.bufs["id"] !== undefined && node.bufs["id"] !== null;
}

// ---------------------------------------------------------------------------
// 小工具
// ---------------------------------------------------------------------------

function asMap(raw: unknown, where: string, id = ""): Map<string, unknown> {
  if (!(raw instanceof Map)) {
    throw new IrError(`${where} 必须是映射，收到 ${describe(raw)}`, id);
  }
  return raw;
}

function asNumber(raw: unknown, where: string, id = ""): number {
  if (typeof raw !== "number" || !Number.isFinite(raw)) {
    throw new IrError(`${where} 必须是有限数值，收到 ${describe(raw)}`, id);
  }
  return raw;
}

function asNumberPair(raw: unknown, where: string): [number, number] {
  if (!Array.isArray(raw) || raw.length !== 2) {
    throw new IrError(`${where} 必须是两个数`);
  }
  return [asNumber(raw[0], where), asNumber(raw[1], where)];
}

function colour(raw: unknown, where: string, id: string): Color {
  if (raw === null) throw new IrError(`${where} 不能是 null（缺省请直接省略该键）`, id);
  if (!Array.isArray(raw) || raw.length !== 4) {
    throw new IrError(`${where} 必须是 (r, g, b, a) 四元组`, id);
  }
  return raw.map((channel) => {
    if (!Number.isInteger(channel) || channel < 0 || channel > 255) {
      throw new IrError(`${where} 的分量必须是 0..255 的整数，收到 ${describe(channel)}`, id);
    }
    return channel as number;
  }) as Color;
}

function rejectUnknown(
  map: Map<string, unknown>,
  allowed: Set<string>,
  where: string,
  id: string,
): void {
  for (const key of map.keys()) {
    if (!allowed.has(key)) {
      throw new IrError(`${where} 有不认识的字段 ${JSON.stringify(key)}`, id);
    }
  }
}

function describe(raw: unknown): string {
  if (raw instanceof Uint8Array) return `字节串(${raw.byteLength})`;
  if (raw === undefined) return "undefined";
  try {
    return JSON.stringify(raw) ?? String(raw);
  } catch {
    return String(raw);
  }
}

// ---------------------------------------------------------------------------
// 读取节点数据
// ---------------------------------------------------------------------------

/** 节点的行数（一个节点可以带多条几何，`docs/notes/ir.md` §4 的 n）。 */
export function nodeRows(node: IrNode): number {
  if (node.kind === "text") return node.texts.length;
  const bufs = Object.values(node.bufs);
  if (bufs.length === 0) return 0;
  // `text` 的 pos 决定行数，其余按第一个带行数的缓冲。
  return bufs[0].rows;
}

export function bufValue(node: IrNode, name: string, row: number, col = 0): number {
  const buf = node.bufs[name];
  if (!buf) throw new IrError(`缺少缓冲 ${name}`, node.kind);
  return buf.data[row * buf.cols + col] as number;
}

export function paramNumber(node: IrNode, name: string): number {
  return node.params[name] as number;
}

export function paramString(node: IrNode, name: string): string {
  return node.params[name] as string;
}
