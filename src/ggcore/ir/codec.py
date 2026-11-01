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
  忽略不认识的字段（前向兼容），但未知节点种类仍然报错——画不出来的东西不能猜。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import cbor2
import numpy as np

from ggcore.ir.errors import IRDecodeError, IRValidationError, IRVersionError
from ggcore.ir.nodes import (
    DEFAULT_MIME,
    DTYPE_WIRE,
    GPAR_FIELDS,
    NODE_SPECS,
    WIRE_DTYPES,
    Blob,
    BlobTable,
    Gpar,
    LineEnd,
    LineJoin,
    Node,
    NodeKind,
    Scene,
)

#: 当前写出的 IR 版本：(major, minor)。major 涨 = 不兼容，minor 涨 = 只加字段。
IR_VERSION: tuple[int, int] = (0, 1)
IR_VERSION_STR = ".".join(str(part) for part in IR_VERSION)
MAGIC = "ggir"


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
    if isinstance(value, str):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return value


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

    scene_obj = payload.get("scene")
    if not isinstance(scene_obj, Mapping):
        raise IRDecodeError("缺少 scene 映射")

    try:
        blobs = _blobs_from_obj(scene_obj.get("blobs", {}))
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


def _blobs_from_obj(raw: Any) -> BlobTable:
    if not isinstance(raw, Mapping):
        raise IRDecodeError(f"scene.blobs 必须是映射，收到 {type(raw).__name__}")
    entries: dict[str, Blob] = {}
    for bid, blob_obj in raw.items():
        if not isinstance(bid, str) or not bid:
            raise IRDecodeError(f"blob id 必须是非空字符串，收到 {bid!r}")
        if not isinstance(blob_obj, Mapping):
            raise IRDecodeError(f"blob[{bid!r}] 必须是映射")
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

    gpar = None
    if "gpar" in raw:
        if not spec.gpar:
            raise IRDecodeError(f"{path}（{kind.value}）不携带 gpar")
        gpar = _gpar_from_obj(raw["gpar"], path=f"{path}.gpar")

    params_raw = raw.get("params", {})
    if not isinstance(params_raw, Mapping):
        raise IRDecodeError(f"{path}.params 必须是映射")
    known_params = {param_spec.name for param_spec in spec.params}
    unknown_params = sorted(set(params_raw) - known_params)
    if unknown_params and not tolerant:
        raise IRDecodeError(
            f"{path}（{kind.value}）有未知参数 {unknown_params}；"
            f"可选 {sorted(known_params)}（前向兼容只在 minor 更新时生效）"
        )
    params = {name: value for name, value in params_raw.items() if name in known_params}

    bufs_raw = raw.get("bufs", {})
    if not isinstance(bufs_raw, Mapping):
        raise IRDecodeError(f"{path}.bufs 必须是映射")
    known_bufs = {buffer_spec.name for buffer_spec in spec.buffers}
    unknown_bufs = sorted(set(bufs_raw) - known_bufs)
    if unknown_bufs and not tolerant:
        raise IRDecodeError(
            f"{path}（{kind.value}）有未知缓冲 {unknown_bufs}；可选 {sorted(known_bufs)}"
        )
    bufs = {
        name: _buffer_from_obj(value, path=f"{path}.bufs.{name}")
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


def _gpar_from_obj(raw: Any, *, path: str) -> Gpar:
    if not isinstance(raw, Mapping):
        raise IRDecodeError(f"{path} 必须是映射")
    defaults = dict(GPAR_FIELDS)
    unknown = sorted(set(raw) - set(defaults))
    if unknown:
        raise IRDecodeError(f"{path} 有未知字段 {unknown}")
    fields = {name: raw.get(name, default) for name, default in defaults.items()}
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


def _buffer_from_obj(raw: Any, *, path: str) -> np.ndarray[Any, Any]:
    if not isinstance(raw, Mapping):
        raise IRDecodeError(f"{path} 必须是映射")
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
