"""`ggcore.ir` — IR v0 的公开接口。

    >>> from ggcore.ir import Blob, BlobTable, Gpar, Node, NodeKind, Scene, f32
    >>> from ggcore.ir import decode, encode, IR_VERSION

- 节点类型表与校验：`ggcore.ir.nodes`（`NODE_SPECS`）
- CBOR 编解码：`ggcore.ir.codec`（`encode` / `decode`）
- 字段口径、blob 约定、版本策略：`docs/notes/ir.md`
"""

from __future__ import annotations

from ggcore.ir.codec import CBOR_BACKEND, IR_VERSION, IR_VERSION_STR, MAGIC, decode, encode
from ggcore.ir.demo import demo_scene
from ggcore.ir.errors import IRDecodeError, IRError, IRValidationError, IRVersionError
from ggcore.ir.nodes import (
    DEFAULT_MIME,
    GPAR_FIELDS,
    NODE_SPECS,
    Anchor,
    Baseline,
    Blob,
    BlobTable,
    FillRule,
    Gpar,
    LineEnd,
    LineJoin,
    Node,
    NodeKind,
    Scene,
    blob_id,
    buffer_equal,
    f32,
    i32,
    node_equal,
    scene_equal,
    walk,
)

__all__ = [
    "CBOR_BACKEND",
    "DEFAULT_MIME",
    "GPAR_FIELDS",
    "IR_VERSION",
    "IR_VERSION_STR",
    "MAGIC",
    "NODE_SPECS",
    "Anchor",
    "Baseline",
    "Blob",
    "BlobTable",
    "FillRule",
    "Gpar",
    "IRDecodeError",
    "IRError",
    "IRValidationError",
    "IRVersionError",
    "LineEnd",
    "LineJoin",
    "Node",
    "NodeKind",
    "Scene",
    "blob_id",
    "buffer_equal",
    "decode",
    "demo_scene",
    "encode",
    "f32",
    "i32",
    "node_equal",
    "scene_equal",
    "walk",
]
