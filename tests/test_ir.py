"""IR v0 的 round-trip、确定性、版本与体积判定。

口径（`docs/notes/ir.md`）：

- 数值相等是**逐位**的（dtype + shape + 原始字节），不是 `allclose`；
- 同一 scene 两次编码字节完全一致，与 dict 插入顺序、blob 入表顺序无关；
- 解码只认 `ir_version` 的 major；
- text 节点只带最终宽度与锚点，不带任何测量意图。
"""

from __future__ import annotations

import json

import cbor2
import numpy as np
import pytest

from ggcore.ir import (
    DEFAULT_MIME,
    IR_VERSION,
    IR_VERSION_STR,
    NODE_SPECS,
    Anchor,
    Baseline,
    Blob,
    BlobTable,
    FillRule,
    Gpar,
    IRDecodeError,
    IRValidationError,
    IRVersionError,
    LineEnd,
    LineJoin,
    Node,
    NodeKind,
    Scene,
    blob_id,
    decode,
    demo_scene,
    encode,
    f32,
    i32,
    scene_equal,
    walk,
)

COLOUR = (31, 119, 180, 255)


def viewport(children: tuple[Node, ...] = (), **params) -> Node:
    return Node(NodeKind.VIEWPORT, params={"clip": False, **params}, children=children)


def wire(scene: Scene) -> dict:
    """编码后再解成普通对象，方便在用例里做“线格式”级的篡改。"""
    payload = cbor2.loads(encode(scene))
    assert isinstance(payload, dict)
    return payload


def rebuild(payload: dict) -> bytes:
    return cbor2.dumps(payload, canonical=True)


def raster_node(blob_table: BlobTable, data: bytes, mime: str = "image/png") -> tuple[Node, str]:
    _table, bid = blob_table.add(data, mime)
    node = Node(
        NodeKind.RASTER,
        params={"blob": bid, "width": 2, "height": 2},
        bufs={"rect": f32([[0.0, 0.0, 10.0, 10.0]])},
    )
    return node, bid


def all_kinds_scene() -> Scene:
    """把 18 种节点都铺一遍的 scene。"""
    points = f32([[0.0, 0.0], [1.0, 1.0], [2.0, 0.5], [3.0, 2.0]])
    ids = i32([0, 0, 1, 1])
    blobs, raster_id = BlobTable.empty().add(b"\x89PNG\r\n\x1a\n", "image/png")
    children = (
        Node(
            NodeKind.GTREE,
            params={"name": "group"},
            children=(
                Node(
                    NodeKind.RECT,
                    Gpar(fill=(255, 255, 255, 255), col=COLOUR, lwd=0.5),
                    bufs={"rect": f32([[0.0, 0.0, 10.0, 10.0], [2.0, 2.0, 8.0, 8.0]])},
                ),
                Node(
                    NodeKind.CIRCLE,
                    Gpar(col=COLOUR),
                    bufs={"circle": f32([[5.0, 5.0, 2.0]])},
                ),
                Node(
                    NodeKind.LINES,
                    Gpar(col=COLOUR),
                    bufs={"points": points, "id": ids},
                ),
                Node(
                    NodeKind.SEGMENTS,
                    Gpar(col=COLOUR),
                    bufs={"segments": f32([[0.0, 0.0, 1.0, 1.0]])},
                ),
                Node(
                    NodeKind.POLYLINE,
                    Gpar(col=COLOUR),
                    bufs={"points": points, "id": ids},
                ),
                Node(
                    NodeKind.POLYGON,
                    Gpar(fill=COLOUR),
                    bufs={"points": points, "id": ids},
                ),
                Node(
                    NodeKind.PATH,
                    Gpar(fill=COLOUR, lty=(4.0, 2.0)),
                    params={"rule": FillRule.EVENODD},
                    bufs={"points": points, "id": ids},
                ),
                Node(
                    NodeKind.POINTS,
                    Gpar(col=COLOUR),
                    params={"pch": 19, "size": 3.5},
                    bufs={"points": points},
                ),
                Node(
                    NodeKind.TEXT,
                    Gpar(col=(10, 10, 10, 255)),
                    params={
                        "font": "DejaVu Sans",
                        "size": 9.0,
                        "anchor": Anchor.RIGHT,
                        "baseline": Baseline.BOTTOM,
                        "angle": 45.0,
                    },
                    bufs={"pos": f32([[1.0, 2.0], [3.0, 4.0]]), "width": f32([12.5, 7.25])},
                    texts=("中文", "abc"),
                ),
                Node(
                    NodeKind.RASTER,
                    params={"blob": raster_id, "width": 2, "height": 2, "interpolate": False},
                    bufs={"rect": f32([[0.0, 0.0, 4.0, 4.0]])},
                ),
                Node(
                    NodeKind.XSPLINE,
                    Gpar(col=COLOUR),
                    params={"shape": 0.5, "open": False},
                    bufs={"points": points},
                ),
                Node(
                    NodeKind.BEZIER,
                    Gpar(col=COLOUR),
                    bufs={"control": f32(np.arange(16, dtype=np.float32).reshape(8, 2))},
                ),
                Node(
                    NodeKind.CURVE,
                    Gpar(col=COLOUR, lineend=LineEnd.SQUARE, linejoin=LineJoin.BEVEL),
                    params={"curvature": -0.5, "angle": 45.0, "ncp": 2, "inflect": True},
                    bufs={"ends": f32([[0.0, 0.0, 5.0, 5.0]])},
                ),
                Node(
                    NodeKind.CLIP,
                    params={"name": "clip-rect", "rule": FillRule.WINDING},
                    bufs={"rect": f32([[1.0, 1.0, 9.0, 9.0]])},
                    children=(Node(NodeKind.POLYGON, Gpar(fill=COLOUR), bufs={"points": points}),),
                ),
                Node(
                    NodeKind.CLIP,
                    params={"name": "clip-path"},
                    bufs={"points": points, "id": ids},
                    children=(Node(NodeKind.LINES, Gpar(col=COLOUR), bufs={"points": points}),),
                ),
                Node(NodeKind.NULL),
                Node(NodeKind.ZERO),
            ),
        ),
        Node(
            NodeKind.VIEWPORT,
            params={
                "name": "panel",
                "clip": True,
                "transform": (0.5, 0.0, 0.0, 0.5, 2.0, 3.0),
            },
            bufs={"clip_rect": f32([[0.0, 0.0, 10.0, 10.0]])},
            children=(Node(NodeKind.RECT, Gpar(fill=COLOUR), bufs={"rect": f32([[0, 0, 1, 1]])}),),
        ),
    )
    return Scene(root=viewport(children, name="root"), size=(600.0, 400.0), blobs=blobs)


# --- round-trip ------------------------------------------------------------


def assert_bitwise_equal(left: Scene, right: Scene) -> None:
    assert right == left
    assert scene_equal(left, right)
    for a, b in zip(walk(left.root), walk(right.root), strict=True):
        assert a.kind is b.kind
        assert set(a.bufs) == set(b.bufs)
        for name, buf in a.bufs.items():
            other = b.bufs[name]
            assert other.dtype == buf.dtype
            assert other.shape == buf.shape
            assert other.tobytes() == buf.tobytes()


def test_demo_scene_round_trips_bitwise() -> None:
    scene = demo_scene()
    decoded = decode(encode(scene))
    assert_bitwise_equal(scene, decoded)
    assert encode(decoded) == encode(scene)


def test_every_node_kind_round_trips() -> None:
    scene = all_kinds_scene()
    kinds = {node.kind for node in walk(scene.root)}
    assert kinds == set(NodeKind)  # 18 种一个不漏，M0-6 加原语时这里会红
    decoded = decode(encode(scene))
    assert_bitwise_equal(scene, decoded)
    assert encode(decoded) == encode(scene)


def test_empty_scene_round_trips() -> None:
    scene = Scene(root=viewport(), size=(0.0, 0.0))
    data = encode(scene)
    assert decode(data) == scene
    assert encode(decode(data)) == data
    # 没有子节点 / 缓冲时不写这些键：空 scene 的线格式只剩 viewport 的缺省参数。
    root = wire(scene)["scene"]["root"]
    assert set(root) == {"kind", "params"}
    assert root["params"] == {"clip": False}


def test_nested_viewports_round_trip() -> None:
    inner = Node(
        NodeKind.VIEWPORT,
        params={"name": "inner", "clip": True, "transform": (0.0, 1.0, -1.0, 0.0, 5.0, 0.0)},
        bufs={"clip_rect": f32([[0.0, 0.0, 2.0, 2.0]])},
        children=(Node(NodeKind.POINTS, Gpar(col=COLOUR), bufs={"points": f32([[0.5, 0.5]])}),),
    )
    middle = Node(
        NodeKind.VIEWPORT,
        params={"name": "middle", "clip": True, "transform": (2.0, 0.0, 0.0, 2.0, 1.0, 1.0)},
        bufs={"clip_rect": f32([[0.0, 0.0, 4.0, 4.0]])},
        children=(Node(NodeKind.GTREE, params={"name": "g"}, children=(inner,)),),
    )
    scene = Scene(
        root=viewport((middle,), name="outer", transform=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)),
        size=(320.0, 240.0),
    )
    decoded = decode(encode(scene))
    assert_bitwise_equal(scene, decoded)
    depths = []

    def visit(node: Node, depth: int) -> None:
        if node.kind is NodeKind.VIEWPORT:
            depths.append((node.params["name"], depth, node.params["transform"]))
        for child in node.children:
            visit(child, depth + 1)

    visit(decoded.root, 0)
    assert [name for name, _, _ in depths] == ["outer", "middle", "inner"]
    assert [depth for _, depth, _ in depths] == [0, 1, 3]
    # 旋转变换逐位保留（float64 参数，不经过 float32）。
    assert depths[2][2] == (0.0, 1.0, -1.0, 0.0, 5.0, 0.0)


def test_float32_values_are_bit_exact() -> None:
    raw = [0.1, 1.0 / 3.0, -0.0, 1e-40, 3.4028235e38, np.inf, -np.inf, np.nan]
    points = f32(np.array(raw, dtype=np.float32).reshape(-1, 2))
    scene = Scene(
        root=viewport((Node(NodeKind.POINTS, Gpar(col=COLOUR), bufs={"points": points}),))
    )
    decoded = decode(encode(scene))
    restored = decoded.root.children[0].bufs["points"]
    assert restored.dtype == np.float32
    assert restored.view(np.uint32).tolist() == points.view(np.uint32).tolist()
    # 输入是 float64 时在 f32() 一次性舍入：0.1 落成 float32 的 0.1，而不是 0.1 的 f64。
    assert float(f32([0.1])[0]) != 0.1
    assert float(f32([0.1])[0]) == float(np.float32(0.1))


def test_gpar_round_trips_and_defaults_are_omitted() -> None:
    gpar = Gpar(
        fill=(1, 2, 3, 4),
        col=(5, 6, 7, 255),
        lwd=2.5,
        lty=(1.0, 2.0),
        lineend=LineEnd.BUTT,
        linejoin=LineJoin.MITER,
        linemitre=3.5,
        alpha=0.25,
    )
    node = Node(NodeKind.RECT, gpar, bufs={"rect": f32([[0, 0, 1, 1]])})
    decoded = decode(encode(Scene(root=viewport((node,)))))
    assert decoded.root.children[0].gpar == gpar

    default_node = Node(NodeKind.RECT, Gpar(), bufs={"rect": f32([[0, 0, 1, 1]])})
    bare_node = Node(NodeKind.RECT, bufs={"rect": f32([[0, 0, 1, 1]])})
    default_payload = wire(Scene(root=viewport((default_node,))))
    bare_payload = wire(Scene(root=viewport((bare_node,))))
    assert default_payload["scene"]["root"]["children"][0]["gpar"] == {}
    assert "gpar" not in bare_payload["scene"]["root"]["children"][0]


# --- 确定性 ----------------------------------------------------------------


def test_encoding_is_byte_stable() -> None:
    scene = demo_scene()
    assert encode(scene) == encode(scene)
    assert encode(demo_scene()) == encode(demo_scene())


def test_encoding_ignores_dict_and_blob_insertion_order() -> None:
    first_blob = b"first"
    second_blob = b"second"
    left_table, left_id = BlobTable.empty().add(first_blob)
    left_table, second_id = left_table.add(second_blob)
    right_table, _ = BlobTable.empty().add(second_blob)
    right_table, _ = right_table.add(first_blob)

    left = Scene(
        root=viewport(
            (
                Node(
                    NodeKind.RASTER,
                    params={"blob": left_id, "width": 1, "height": 1},
                    bufs={"rect": f32([[0, 0, 1, 1]])},
                ),
                Node(
                    NodeKind.RASTER,
                    params={"blob": second_id, "width": 1, "height": 1},
                    bufs={"rect": f32([[0, 0, 1, 1]])},
                ),
            )
        ),
        blobs=left_table,
    )
    right = Scene(
        root=viewport(
            (
                Node(
                    NodeKind.RASTER,
                    params={"blob": left_id, "width": 1, "height": 1},
                    bufs={"rect": f32([[0, 0, 1, 1]])},
                ),
                Node(
                    NodeKind.RASTER,
                    params={"blob": second_id, "width": 1, "height": 1},
                    bufs={"rect": f32([[0, 0, 1, 1]])},
                ),
            )
        ),
        blobs=right_table,
    )
    # 参数只写非缺省值、blob 按 id 排序 + canonical CBOR：入表顺序不进字节。
    assert encode(left) == encode(right)


def test_encoding_writes_the_ir_version() -> None:
    payload = wire(demo_scene())
    assert payload["magic"] == "ggir"
    assert payload["ir_version"] == list(IR_VERSION)
    assert IR_VERSION_STR == ".".join(str(part) for part in IR_VERSION)


# --- 版本与结构校验 --------------------------------------------------------


def test_decode_rejects_unknown_major() -> None:
    for major in (1, 2, 99):
        payload = wire(demo_scene())
        payload["ir_version"] = [major, 0]
        with pytest.raises(IRVersionError) as excinfo:
            decode(rebuild(payload))
        assert isinstance(excinfo.value, IRDecodeError)
        assert f"major={major}" in str(excinfo.value)


def test_decode_accepts_newer_minor_but_rejects_unknown_major_zero() -> None:
    payload = wire(demo_scene())
    payload["ir_version"] = [IR_VERSION[0], IR_VERSION[1] + 1]
    node = payload["scene"]["root"]["children"][0]
    node["params"] = {**node.get("params", {}), "future_field": 1}
    node["bufs"] = {
        **node.get("bufs", {}),
        "future_buffer": {"dtype": "f4", "shape": [1], "data": b"\x00\x00\x80\x3f"},
    }
    decoded = decode(rebuild(payload))
    assert decoded.root.children[0].kind is NodeKind.VIEWPORT
    assert "future_field" not in decoded.root.children[0].params
    assert "future_buffer" not in decoded.root.children[0].bufs


def test_decode_rejects_unknown_fields_within_the_same_minor() -> None:
    payload = wire(demo_scene())
    node = payload["scene"]["root"]["children"][0]
    node["params"] = {**node.get("params", {}), "future_field": 1}
    with pytest.raises(IRDecodeError, match="future_field"):
        decode(rebuild(payload))


def test_decode_rejects_unknown_node_kind() -> None:
    payload = wire(demo_scene())
    payload["scene"]["root"]["children"][0]["kind"] = "ellipse"
    with pytest.raises(IRDecodeError, match="ellipse"):
        decode(rebuild(payload))


def test_decode_rejects_broken_payloads() -> None:
    data = encode(demo_scene())
    with pytest.raises(IRDecodeError):
        decode(b"")
    with pytest.raises(IRDecodeError):
        decode(data[: len(data) // 2])
    payload = wire(demo_scene())
    payload["magic"] = "nope"
    with pytest.raises(IRDecodeError, match="magic"):
        decode(rebuild(payload))
    payload = wire(demo_scene())
    del payload["scene"]
    with pytest.raises(IRDecodeError, match="scene"):
        decode(rebuild(payload))


def test_decode_rejects_buffer_length_mismatch() -> None:
    payload = wire(all_kinds_scene())
    rect = payload["scene"]["root"]["children"][0]["children"][0]
    rect["bufs"]["rect"]["data"] = rect["bufs"]["rect"]["data"][:-4]
    with pytest.raises(IRDecodeError, match="长度"):
        decode(rebuild(payload))


def test_decode_rejects_per_element_json_buffers() -> None:
    payload = wire(all_kinds_scene())
    rect = payload["scene"]["root"]["children"][0]["children"][0]
    rect["bufs"]["rect"]["data"] = [[0.0, 0.0, 10.0, 10.0]]
    with pytest.raises(IRDecodeError, match="bytes"):
        decode(rebuild(payload))


# --- text 节点口径 ---------------------------------------------------------


def test_text_node_carries_no_measurement_intent() -> None:
    spec = NODE_SPECS[NodeKind.TEXT]
    assert {param.name for param in spec.params} == {
        "font",
        "size",
        "anchor",
        "baseline",
        "angle",
    }
    assert {buffer.name for buffer in spec.buffers} == {"pos", "width"}

    text = Node(
        NodeKind.TEXT,
        Gpar(col=(0, 0, 0, 255)),
        params={"font": "DejaVu Sans", "size": 10.0},
        bufs={"pos": f32([[1.0, 2.0]]), "width": f32([12.5])},
        texts=("x",),
    )
    decoded = decode(encode(Scene(root=viewport((text,)))))
    restored = decoded.root.children[0]
    assert restored.texts == ("x",)
    assert restored.bufs["width"].dtype == np.float32
    assert restored.bufs["width"].tobytes() == text.bufs["width"].tobytes()
    # 带测量意图的字段一个都进不来：IR 里只有“最终宽度”。
    for forbidden in (
        "font_stack",
        "fontstack",
        "family",
        "fallback",
        "glyphs",
        "advance",
        "measure",
        "strwidth",
        "shaping",
        "hjust",
        "vjust",
    ):
        assert forbidden not in {param.name for param in spec.params}
        assert forbidden not in restored.params
        with pytest.raises(IRValidationError):
            Node(
                NodeKind.TEXT,
                params={"font": "f", "size": 1.0, forbidden: 1},
                bufs={"pos": f32([[0.0, 0.0]]), "width": f32([0.0])},
                texts=("x",),
            )


def test_text_rows_must_line_up() -> None:
    with pytest.raises(IRValidationError, match="行数"):
        Node(
            NodeKind.TEXT,
            params={"font": "f", "size": 1.0},
            bufs={"pos": f32([[0.0, 0.0], [1.0, 1.0]]), "width": f32([1.0])},
            texts=("a", "b"),
        )


# --- blob 表 ---------------------------------------------------------------


def test_blob_ids_are_content_addressed() -> None:
    data = b"same bytes"
    assert blob_id(data) == blob_id(data)
    assert blob_id(data) != blob_id(data, "image/png")
    assert blob_id(data).startswith("sha256:")
    table, first = BlobTable.empty().add(data)
    assert first == blob_id(data)
    same_table, second = table.add(data)
    assert second == first
    assert len(same_table) == len(table) == 1


def test_blob_default_mime_is_applied_on_decode() -> None:
    node, bid = raster_node(BlobTable.empty(), b"pixels", DEFAULT_MIME)
    scene = Scene(root=viewport((node,)), blobs=BlobTable.of(Blob(b"pixels")))
    payload = wire(scene)
    del payload["scene"]["blobs"][bid]["mime"]
    decoded = decode(rebuild(payload))
    assert decoded.blobs[bid].mime == DEFAULT_MIME
    assert decoded == scene


def test_missing_blob_reference_is_rejected() -> None:
    node = Node(
        NodeKind.RASTER,
        params={"blob": "sha256:deadbeef", "width": 1, "height": 1},
        bufs={"rect": f32([[0, 0, 1, 1]])},
    )
    with pytest.raises(IRValidationError, match="blob"):
        Scene(root=viewport((node,)))


def test_large_blob_round_trips() -> None:
    payload_bytes = bytes(range(256)) * (4 * 1024 * 1024 // 256)
    assert len(payload_bytes) == 4 * 1024 * 1024
    node, bid = raster_node(BlobTable.empty(), payload_bytes, "image/jpeg")
    scene = Scene(root=viewport((node,)), blobs=BlobTable.of(Blob(payload_bytes, "image/jpeg")))
    data = encode(scene)
    assert len(data) >= len(payload_bytes)
    decoded = decode(data)
    assert decoded == scene
    assert decoded.blobs[bid].data == payload_bytes
    assert decoded.blobs[bid].mime == "image/jpeg"
    assert encode(decoded) == data


# --- 缓冲与校验 ------------------------------------------------------------


def test_buffers_are_read_only_float32() -> None:
    buf = f32([[0.0, 1.0]])
    assert buf.dtype == np.float32
    assert not buf.flags.writeable
    decoded = decode(encode(Scene(root=viewport((Node(NodeKind.POINTS, bufs={"points": buf}),)))))
    assert not decoded.root.children[0].bufs["points"].flags.writeable

    with pytest.raises(IRValidationError, match="dtype"):
        Node(NodeKind.POINTS, bufs={"points": np.zeros((1, 2), dtype=np.float64)})
    with pytest.raises(IRValidationError, match="shape"):
        Node(NodeKind.POINTS, bufs={"points": f32([[0.0, 0.0, 0.0]])})


def test_invalid_scenes_are_rejected() -> None:
    with pytest.raises(IRValidationError, match="root"):
        Scene(root=Node(NodeKind.RECT, Gpar(), bufs={"rect": f32([[0, 0, 1, 1]])}))
    with pytest.raises(IRValidationError, match="size"):
        Scene(root=viewport(), size=(-1.0, 10.0))
    with pytest.raises(IRValidationError, match="dpi"):
        Scene(root=viewport(), dpi=0.0)
    with pytest.raises(IRValidationError, match="gpar"):
        Node(NodeKind.VIEWPORT, Gpar(), children=())
    with pytest.raises(IRValidationError, match="clip_rect"):
        Node(NodeKind.VIEWPORT, params={"clip": True})
    with pytest.raises(IRValidationError, match="rect 或 points"):
        Node(NodeKind.CLIP, children=())
    with pytest.raises(IRValidationError, match="id"):
        Node(
            NodeKind.LINES,
            bufs={"points": f32([[0.0, 0.0], [1.0, 1.0]]), "id": i32([0])},
        )
    with pytest.raises(IRValidationError, match="没有参数"):
        Node(NodeKind.NULL, params={"shape": 1})


# --- 体积：10k 点 path vs 逐元素 JSON --------------------------------------


def ten_thousand_point_path() -> tuple[Scene, np.ndarray]:
    count = 10_000
    rng = np.random.default_rng(7)
    points = np.column_stack([rng.normal(size=count), rng.normal(size=count)]).astype(np.float32)
    scene = Scene(
        root=viewport(
            (
                Node(
                    NodeKind.PATH,
                    Gpar(col=COLOUR),
                    bufs={"points": f32(points)},
                ),
            )
        )
    )
    return scene, points


def test_10k_point_path_is_much_smaller_than_json() -> None:
    scene, points = ten_thousand_point_path()
    data = encode(scene)
    json_bytes = len(
        json.dumps(
            [[float(x), float(y)] for x, y in points],
            separators=(",", ":"),
        ).encode()
    )
    # 口径：JSON 侧保留完整数值（float32 → float64 文本），不靠丢精度来缩体积。
    assert len(data) < json_bytes / 5
    # 顶点是 8 字节/点（2 × float32），JSON 侧 ≥ 30 字节/点。
    assert len(data) < 10_000 * 10
    assert json_bytes > 10_000 * 30


def test_point_buffer_size_is_eight_bytes_per_point() -> None:
    scene, _ = ten_thousand_point_path()
    payload = wire(scene)
    buffer = payload["scene"]["root"]["children"][0]["bufs"]["points"]
    assert buffer["dtype"] == "f4"
    assert buffer["shape"] == [10_000, 2]
    assert len(buffer["data"]) == 10_000 * 2 * 4
