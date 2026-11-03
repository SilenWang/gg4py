"""IR v0 · CBOR 编解码。

线格式一览（键名与 `ggcore/ir/nodes.py` 的 `NODE_SPECS` 一一对应，逐字段说明见
`docs/notes/ir.md`）：

    {
      "magic": "ggir",
      "ir_version": [0, 1],
      "scene": {
        "size": [w, h],                # pt
        "dpi": 72.0,
        "blobs": {"sha256:…": {"mime": "image/png", "data": b"…"}},
        "root": {"kind": "viewport", …}
      }
    }

约定：

- 只用 canonical CBOR（`cbor2.dumps(..., canonical=True)`）：键排序、参数只写
  非缺省值、blob 表按 id 排序，所以同一 scene 两次编码字节完全相同。
- bulk 数据是**原始 float32 小端字节**（`{"dtype": "f4", "shape": [...], "data": b"…"}`），
  不做逐元素 JSON，也不 base64。
- 解码方只认 `ir_version` 的 major；major 不认识直接拒绝。minor 比本实现新时，
  忽略每一层不认识的键（envelope / `scene` / `blobs` 条目 / 节点 / `params` /
  `bufs` / 缓冲对象 / `gpar`），但未知节点种类和未知缓冲 dtype 仍然报错——
  画不出来、读不懂的东西不能猜。minor ≤ 本实现时这些未知键都报错。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ggcore.ir.errors import IRDecodeError, IRValidationError, IRVersionError
from ggcore.ir.nodes import (
    DEFAULT_MIME,
    DTYPE_WIRE,
    F32,
    GPAR_FIELDS,
    NODE_SPECS,
    WIRE_DTYPES,
    Blob,
    BlobTable,
    Extend,
    FillKind,
    Gpar,
    LinearGradient,
    LineEnd,
    LineJoin,
    Node,
    NodeKind,
    RadialGradient,
    Scene,
    Stop,
    TilePattern,
)

#: 实际在跑的 CBOR 实现。CPython 用 `cbor2`（Rust 扩展）；Pyodide 的包索引里没有
#: `cbor2`、PyPI 也只有编译不了 wasm 的扩展轮子，所以那边退回 `ggcore.ir._cbor`
#: （纯 Python、同一份 canonical 线格式）。两边字节一致由 `pixi run gate:pyodide`
#: 逐字节守住，见 `docs/notes/pyodide.md`。
try:
    import cbor2

    CBOR_BACKEND = "cbor2"
except ImportError:  # pragma: no cover - 只有 Pyodide 走这里
    from ggcore.ir import _cbor as cbor2

    CBOR_BACKEND = "ggcore.ir._cbor"

#: 当前写出的 IR 版本：(major, minor)。major 涨 = 不兼容，minor 涨 = 只加字段。
IR_VERSION: tuple[int, int] = (0, 3)
IR_VERSION_STR = ".".join(str(part) for part in IR_VERSION)
MAGIC = "ggir"

# 每一层映射的已知键。未知键在 minor ≤ 本实现时报错，minor > 本实现时跳过。
_ENVELOPE_KEYS = frozenset({"magic", "ir_version", "scene"})
_SCENE_KEYS = frozenset({"size", "dpi", "blobs", "root"})
_BLOB_KEYS = frozenset({"mime", "data"})
_BUFFER_KEYS = frozenset({"dtype", "shape", "data"})
_NODE_KEYS = frozenset({"kind", "gpar", "params", "bufs", "texts", "children"})

_FORWARD_HINT = "未知字段只在 minor 比本实现新时容忍（docs/notes/ir.md §3）"


def _reject_unknown_keys(
    raw: Mapping[Any, Any],
    known: frozenset[str],
    *,
    where: str,
    what: str,
    tolerant: bool,
) -> None:
    """同一 major 内的未知键口径：minor ≤ 本实现严格，minor > 本实现跳过。

    每一层映射都走这里，不留“这一层校验了、那一层没校验”的口子。
    """
    unknown = sorted(repr(key) for key in raw if key not in known)
    if not unknown or tolerant:
        return
    raise IRDecodeError(f"{where} 有未知{what} {unknown}；可选 {sorted(known)}（{_FORWARD_HINT}）")


# ---------------------------------------------------------------------------
# 编码
# ---------------------------------------------------------------------------


def encode(scene: Scene) -> bytes:
    """把 scene 编成 CBOR 字节。同一 scene 永远得到同一串字节。"""
    if not isinstance(scene, Scene):
        raise TypeError(f"encode() 只接受 Scene，收到 {type(scene).__name__}")
    payload: dict[str, Any] = {
        "magic": MAGIC,
        "ir_version": list(IR_VERSION),
        "scene": {
            "size": [scene.size[0], scene.size[1]],
            "dpi": scene.dpi,
            "blobs": {
                bid: {"mime": scene.blobs[bid].mime, "data": scene.blobs[bid].data}
                for bid in scene.blobs.ids()
            },
            "root": _node_to_obj(scene.root),
        },
    }
    return cbor2.dumps(payload, canonical=True)


def _node_to_obj(node: Node) -> dict[str, Any]:
    spec = NODE_SPECS[node.kind]
    obj: dict[str, Any] = {"kind": node.kind.value}

    if node.gpar is not None:
        gpar: dict[str, Any] = {}
        for name, default in GPAR_FIELDS:
            value = getattr(node.gpar, name)
            if value != default:
                gpar[name] = _to_wire(value)
        obj["gpar"] = gpar

    params: dict[str, Any] = {}
    for param_spec in spec.params:
        value = node.params[param_spec.name]
        if value != param_spec.default:
            params[param_spec.name] = _to_wire(value)
    if params:
        obj["params"] = params

    if node.bufs:
        obj["bufs"] = {
            name: {
                "dtype": DTYPE_WIRE[arr.dtype],
                "shape": list(arr.shape),
                "data": arr.tobytes(),
            }
            for name, arr in node.bufs.items()
        }
    if node.texts:
        obj["texts"] = list(node.texts)
    if node.children:
        obj["children"] = [_node_to_obj(child) for child in node.children]
    return obj


def _to_wire(value: Any) -> Any:
    if isinstance(value, (LinearGradient, RadialGradient, TilePattern)):
        return _fill_to_wire(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return value


#: 每种非纯色 fill 的已知键（解码时用于“未知字段”口径）。
_FILL_KEYS: Mapping[str, frozenset[str]] = {
    FillKind.LINEAR.value: frozenset({"kind", "stops", "start", "end", "extend"}),
    FillKind.RADIAL.value: frozenset({"kind", "stops", "center", "radius", "focal", "extend"}),
    FillKind.PATTERN.value: frozenset({"kind", "content", "size", "origin", "extend"}),
}


def _stops_to_wire(stops: Sequence[Stop]) -> dict[str, Any]:
    """色标写成一条 f4 (n, 5) 缓冲：offset + r, g, b, a（20 B/档）。"""
    rows = np.array([stop.to_row() for stop in stops], dtype=np.float64)
    data = np.ascontiguousarray(rows.astype(F32))
    return {"dtype": "f4", "shape": list(data.shape), "data": data.tobytes()}


def _fill_to_wire(fill: Any) -> dict[str, Any]:
    if isinstance(fill, LinearGradient):
        return {
            "kind": fill.kind.value,
            "stops": _stops_to_wire(fill.stops),
            "start": list(fill.start),
            "end": list(fill.end),
            "extend": fill.extend.value,
        }
    if isinstance(fill, RadialGradient):
        obj: dict[str, Any] = {
            "kind": fill.kind.value,
            "stops": _stops_to_wire(fill.stops),
            "center": list(fill.center),
            "radius": fill.radius,
            "extend": fill.extend.value,
        }
        if fill.focal is not None:
            obj["focal"] = list(fill.focal)
        return obj
    assert isinstance(fill, TilePattern)
    return {
        "kind": fill.kind.value,
        "size": list(fill.size),
        "origin": list(fill.origin),
        "extend": fill.extend.value,
        "content": [_node_to_obj(item) for item in fill.content],
    }


# ---------------------------------------------------------------------------
# 解码
# ---------------------------------------------------------------------------


def decode(data: bytes | bytearray | memoryview) -> Scene:
    """把 CBOR 字节解回 scene；版本或结构不认识时抛 `IRDecodeError`。"""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"decode() 只接受 bytes，收到 {type(data).__name__}")
    try:
        payload = cbor2.loads(bytes(data))
    except Exception as exc:  # cbor2 的异常族很杂，统一包成 IRDecodeError
        raise IRDecodeError(f"CBOR 解析失败：{exc}") from exc

    if not isinstance(payload, Mapping):
        raise IRDecodeError(f"顶层必须是映射，收到 {type(payload).__name__}")
    if payload.get("magic") != MAGIC:
        raise IRDecodeError(f"magic 不是 {MAGIC!r}：{payload.get('magic')!r}")
    tolerant = _check_version(payload.get("ir_version"))
    _reject_unknown_keys(
        payload, _ENVELOPE_KEYS, where="envelope", what="顶层键", tolerant=tolerant
    )

    scene_obj = payload.get("scene")
    if not isinstance(scene_obj, Mapping):
        raise IRDecodeError("缺少 scene 映射")
    _reject_unknown_keys(scene_obj, _SCENE_KEYS, where="scene", what="字段", tolerant=tolerant)

    try:
        blobs = _blobs_from_obj(scene_obj.get("blobs", {}), tolerant=tolerant)
        size = _pair(scene_obj.get("size"), "scene.size")
        dpi = _number(scene_obj.get("dpi", 72.0), "scene.dpi")
        root = _node_from_obj(scene_obj.get("root"), tolerant=tolerant, path="scene.root")
        return Scene(root=root, size=size, dpi=dpi, blobs=blobs)
    except IRValidationError as exc:
        raise IRDecodeError(str(exc)) from exc


def _check_version(raw: Any) -> bool:
    """返回是否进入“容忍未知字段”模式（线格式 minor 比本实现新）。"""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 2:
        raise IRDecodeError(f"ir_version 必须是 [major, minor]，收到 {raw!r}")
    for part in raw:
        if isinstance(part, bool) or not isinstance(part, int) or part < 0:
            raise IRDecodeError(f"ir_version 的分量必须是非负整数，收到 {raw!r}")
    major, minor = int(raw[0]), int(raw[1])
    if major != IR_VERSION[0]:
        raise IRVersionError(
            f"IR major={major} 不被支持；本实现只认 {IR_VERSION[0]}.x"
            f"（写出的版本是 {IR_VERSION_STR}）"
        )
    return minor > IR_VERSION[1]


def _blobs_from_obj(raw: Any, *, tolerant: bool) -> BlobTable:
    if not isinstance(raw, Mapping):
        raise IRDecodeError(f"scene.blobs 必须是映射，收到 {type(raw).__name__}")
    entries: dict[str, Blob] = {}
    for bid, blob_obj in raw.items():
        if not isinstance(bid, str) or not bid:
            raise IRDecodeError(f"blob id 必须是非空字符串，收到 {bid!r}")
        if not isinstance(blob_obj, Mapping):
            raise IRDecodeError(f"blob[{bid!r}] 必须是映射")
        _reject_unknown_keys(
            blob_obj,
            _BLOB_KEYS,
            where=f"blob[{bid!r}]",
            what="字段",
            tolerant=tolerant,
        )
        data = blob_obj.get("data")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise IRDecodeError(f"blob[{bid!r}].data 必须是 bytes")
        mime = blob_obj.get("mime") or DEFAULT_MIME
        if not isinstance(mime, str):
            raise IRDecodeError(f"blob[{bid!r}].mime 必须是字符串")
        entries[bid] = Blob(bytes(data), mime)
    return BlobTable(entries)


def _node_from_obj(raw: Any, *, tolerant: bool, path: str) -> Node:
    if not isinstance(raw, Mapping):
        raise IRDecodeError(f"{path} 必须是映射，收到 {type(raw).__name__}")
    kind_raw = raw.get("kind")
    try:
        kind = NodeKind(kind_raw)
    except ValueError as exc:
        raise IRDecodeError(f"{path}.kind 不认识：{kind_raw!r}") from exc
    spec = NODE_SPECS[kind]
    _reject_unknown_keys(
        raw, _NODE_KEYS, where=f"{path}（{kind.value}）", what="字段", tolerant=tolerant
    )

    gpar = None
    if "gpar" in raw:
        if not spec.gpar:
            raise IRDecodeError(f"{path}（{kind.value}）不携带 gpar")
        gpar = _gpar_from_obj(raw["gpar"], path=f"{path}.gpar", tolerant=tolerant)

    params_raw = raw.get("params", {})
    if not isinstance(params_raw, Mapping):
        raise IRDecodeError(f"{path}.params 必须是映射")
    known_params = frozenset(param_spec.name for param_spec in spec.params)
    _reject_unknown_keys(
        params_raw,
        known_params,
        where=f"{path}（{kind.value}）",
        what="参数",
        tolerant=tolerant,
    )
    params = {name: value for name, value in params_raw.items() if name in known_params}

    bufs_raw = raw.get("bufs", {})
    if not isinstance(bufs_raw, Mapping):
        raise IRDecodeError(f"{path}.bufs 必须是映射")
    known_bufs = frozenset(buffer_spec.name for buffer_spec in spec.buffers)
    _reject_unknown_keys(
        bufs_raw,
        known_bufs,
        where=f"{path}（{kind.value}）",
        what="缓冲",
        tolerant=tolerant,
    )
    bufs = {
        name: _buffer_from_obj(value, path=f"{path}.bufs.{name}", tolerant=tolerant)
        for name, value in bufs_raw.items()
        if name in known_bufs
    }

    texts_raw = raw.get("texts", [])
    if not isinstance(texts_raw, Sequence) or isinstance(texts_raw, (str, bytes)):
        raise IRDecodeError(f"{path}.texts 必须是字符串数组")
    for label in texts_raw:
        if not isinstance(label, str):
            raise IRDecodeError(f"{path}.texts 必须是字符串数组，收到 {label!r}")

    children_raw = raw.get("children", [])
    if not isinstance(children_raw, Sequence) or isinstance(children_raw, (str, bytes)):
        raise IRDecodeError(f"{path}.children 必须是数组")
    children = [
        _node_from_obj(child, tolerant=tolerant, path=f"{path}.children[{index}]")
        for index, child in enumerate(children_raw)
    ]

    try:
        return Node(
            kind=kind,
            gpar=gpar,
            params=params,
            bufs=bufs,
            texts=tuple(texts_raw),
            children=tuple(children),
        )
    except IRValidationError as exc:
        raise IRDecodeError(f"{path}: {exc}") from exc


def _gpar_from_obj(raw: Any, *, path: str, tolerant: bool) -> Gpar:
    if not isinstance(raw, Mapping):
        raise IRDecodeError(f"{path} 必须是映射")
    defaults = dict(GPAR_FIELDS)
    _reject_unknown_keys(raw, frozenset(defaults), where=path, what="字段", tolerant=tolerant)
    fields = {name: raw.get(name, default) for name, default in defaults.items()}
    # `fill` 是联合类型：纯色仍是 4 元组，渐变 / 图案是带 `kind` 的映射（§6.1）。
    if isinstance(fields["fill"], Mapping):
        fields["fill"] = _fill_from_obj(fields["fill"], path=f"{path}.fill", tolerant=tolerant)
    for name, enum in (("lineend", LineEnd), ("linejoin", LineJoin)):
        value = fields[name]
        if isinstance(value, enum):
            continue
        try:
            fields[name] = enum(value)
        except ValueError as exc:
            raise IRDecodeError(f"{path}.{name} 不认识：{value!r}") from exc
    try:
        return Gpar(**fields)
    except IRValidationError as exc:
        raise IRDecodeError(f"{path}: {exc}") from exc


def _extend_from_obj(raw: Any, *, path: str) -> Extend:
    try:
        return Extend("pad" if raw is None else raw)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in Extend)
        raise IRDecodeError(f"{path} 不认识：{raw!r}（可选 {allowed}）") from exc


def _stops_from_obj(raw: Any, *, path: str, tolerant: bool) -> tuple[Stop, ...]:
    """色标缓冲 → `Stop` 序列。列必须是 offset + r, g, b, a，颜色是整数。"""
    arr = _buffer_from_obj(raw, path=path, tolerant=tolerant)
    if arr.ndim != 2 or arr.shape[1] != 5:
        raise IRDecodeError(f"{path} 必须是 (n, 5) 的 f4 缓冲，收到 shape={arr.shape}")
    if arr.shape[0] < 2:
        raise IRDecodeError(f"{path} 至少要两个色标，收到 {arr.shape[0]} 个")
    stops: list[Stop] = []
    for index, row in enumerate(arr):
        offset = float(row[0])
        if not 0.0 <= offset <= 1.0:
            raise IRDecodeError(f"{path}[{index}].offset 必须在 [0, 1]，收到 {offset!r}")
        channels: list[int] = []
        for channel in row[1:]:
            value = float(channel)
            if not value.is_integer() or not 0.0 <= value <= 255.0:
                raise IRDecodeError(
                    f"{path}[{index}] 的颜色分量必须是 0..255 的整数，收到 {value!r}"
                )
            channels.append(int(value))
        stops.append(Stop(offset, (channels[0], channels[1], channels[2], channels[3])))
    return tuple(stops)


def _fill_from_obj(raw: Any, *, path: str, tolerant: bool) -> LinearGradient | RadialGradient:
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in _FILL_KEYS:
        raise IRDecodeError(
            f"{path}.kind 不认识：{kind!r}（可选 {sorted(_FILL_KEYS)}）；"
            "纯色 fill 是不带 kind 的 4 元组"
        )
    _reject_unknown_keys(
        raw, _FILL_KEYS[kind], where=f"{path}（{kind}）", what="字段", tolerant=tolerant
    )
    try:
        if kind == FillKind.PATTERN.value:
            content_raw = raw.get("content")
            if isinstance(content_raw, (str, bytes)) or not isinstance(content_raw, Sequence):
                raise IRDecodeError(f"{path}.content 必须是节点数组")
            content = tuple(
                _node_from_obj(item, tolerant=tolerant, path=f"{path}.content[{index}]")
                for index, item in enumerate(content_raw)
            )
            return TilePattern(
                content=content,
                size=_pair(raw.get("size"), f"{path}.size"),
                origin=_pair(raw.get("origin"), f"{path}.origin"),
                extend=_extend_from_obj(raw.get("extend"), path=f"{path}.extend"),
            )
        stops = _stops_from_obj(raw.get("stops"), path=f"{path}.stops", tolerant=tolerant)
        extend = _extend_from_obj(raw.get("extend"), path=f"{path}.extend")
        if kind == FillKind.LINEAR.value:
            return LinearGradient(
                stops=stops,
                start=_pair(raw.get("start"), f"{path}.start"),
                end=_pair(raw.get("end"), f"{path}.end"),
                extend=extend,
            )
        focal_raw = raw.get("focal")
        focal = None
        if focal_raw is not None:
            if (
                isinstance(focal_raw, (str, bytes))
                or not isinstance(focal_raw, Sequence)
                or len(focal_raw) != 3
            ):
                raise IRDecodeError(f"{path}.focal 必须是三个数（fx, fy, fr），收到 {focal_raw!r}")
            focal = tuple(_number(value, f"{path}.focal") for value in focal_raw)
        return RadialGradient(
            stops=stops,
            center=_pair(raw.get("center"), f"{path}.center"),
            radius=_number(raw.get("radius"), f"{path}.radius"),
            focal=focal,
            extend=extend,
        )
    except IRValidationError as exc:
        raise IRDecodeError(f"{path}: {exc}") from exc


def _buffer_from_obj(raw: Any, *, path: str, tolerant: bool) -> np.ndarray[Any, Any]:
    if not isinstance(raw, Mapping):
        raise IRDecodeError(f"{path} 必须是映射")
    # 未知子键与其它层同一口径（minor 比本实现新时跳过）；但 dtype 必须认识——
    # 读不懂的缓冲不能当成已知的处理，所以这一条不随 tolerant 放宽。
    _reject_unknown_keys(
        raw,
        _BUFFER_KEYS,
        where=path,
        what="字段",
        tolerant=tolerant,
    )
    dtype_code = raw.get("dtype")
    dtype = WIRE_DTYPES.get(dtype_code) if isinstance(dtype_code, str) else None
    if dtype is None:
        raise IRDecodeError(f"{path}.dtype 不认识：{dtype_code!r}（可选 f4 / i4）")
    shape_raw = raw.get("shape")
    if not isinstance(shape_raw, Sequence) or isinstance(shape_raw, (str, bytes)):
        raise IRDecodeError(f"{path}.shape 必须是整数数组")
    shape: list[int] = []
    for dim in shape_raw:
        if isinstance(dim, bool) or not isinstance(dim, int) or dim < 0:
            raise IRDecodeError(f"{path}.shape 的分量必须是非负整数，收到 {shape_raw!r}")
        shape.append(int(dim))
    data = raw.get("data")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise IRDecodeError(f"{path}.data 必须是 bytes（float32 原始字节，不是 JSON 数组）")
    payload = bytes(data)
    expected = math.prod(shape) * dtype.itemsize
    if len(payload) != expected:
        raise IRDecodeError(
            f"{path}.data 长度 {len(payload)} 与 shape={shape} × "
            f"{dtype.itemsize}B 不符（期望 {expected}B）"
        )
    # frombuffer 拿到的是只读视图，reshape 也是视图：解码结果天然不可写，且不复制。
    arr = np.frombuffer(payload, dtype=dtype)
    try:
        arr = arr.reshape(shape)
    except ValueError as exc:
        raise IRDecodeError(f"{path}.shape 与 data 长度不符：{exc}") from exc
    return arr


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IRDecodeError(f"{where} 必须是数值，收到 {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise IRDecodeError(f"{where} 必须是有限值，收到 {value!r}")
    return number


def _pair(value: Any, where: str) -> tuple[float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise IRDecodeError(f"{where} 必须是两个数，收到 {value!r}")
    return (_number(value[0], where), _number(value[1], where))
