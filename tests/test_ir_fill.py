"""IR v0.3 · `gpar.fill` 的联合类型（SIL-751）。

三层口径：

1. **纯色不变**：`fill` 仍是 `[r, g, b, a]`，v0.2 的文件原样读得进来；
2. **渐变 / 图案**：色标写成一条 f4 `(n, 5)` 缓冲（offset + rgba），往返逐位相同；
3. **校验**：色标单调、半径为正、图案内容只能是纯色小图元——坏值在构造期就报，
   不留给渲染端猜。
"""

from __future__ import annotations

import cbor2
import pytest

from ggcore.ir import (
    IR_VERSION,
    Extend,
    Gpar,
    IRDecodeError,
    IRValidationError,
    IRVersionError,
    LinearGradient,
    Node,
    RadialGradient,
    Stop,
    TilePattern,
    decode,
    encode,
    f32,
)
from ggcore.ir import (
    decode as ir_decode,
)

COLOUR = (31, 119, 180, 255)


def _viewport(*children: Node, size: float = 100.0) -> Node:
    return Node(
        "viewport",
        params={"name": "page", "clip": True, "transform": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)},
        bufs={"clip_rect": f32([[0.0, 0.0, size, size]])},
        children=children,
    )


def _scene(node: Node) -> object:
    from ggcore.ir import Scene

    return Scene(root=_viewport(node), size=(100.0, 100.0))


def _rect(fill: object) -> Node:
    return Node("rect", gpar=Gpar(fill=fill), bufs={"rect": f32([[0.0, 0.0, 10.0, 10.0]])})


LINEAR = LinearGradient(
    stops=(Stop(0.0, (255, 0, 0, 255)), Stop(0.5, (0, 255, 0, 255)), Stop(1.0, (0, 0, 255, 128))),
    start=(1.5, 2.5),
    end=(9.5, 2.5),
    extend=Extend.REFLECT,
)
RADIAL = RadialGradient(
    stops=(Stop(0.0, (255, 255, 255, 255)), Stop(1.0, (0, 0, 0, 255))),
    center=(5.0, 5.0),
    radius=4.0,
    focal=(4.0, 5.0, 1.0),
)
PATTERN = TilePattern(
    content=(
        Node("rect", gpar=Gpar(fill=(255, 0, 0, 255)), bufs={"rect": f32([[0.0, 0.0, 2.0, 2.0]])}),
        Node("circle", gpar=Gpar(fill=(0, 0, 255, 255)), bufs={"circle": f32([[2.0, 2.0, 1.0]])}),
    ),
    size=(4.0, 4.0),
    origin=(1.0, 1.0),
)


def test_ir_version_is_0_4() -> None:
    assert IR_VERSION == (0, 4)


@pytest.mark.parametrize("fill", [LINEAR, RADIAL, PATTERN])
def test_fill_round_trips_byte_exactly(fill: object) -> None:
    data = encode(_scene(_rect(fill)))
    back = decode(data)
    assert back.root.children[0].gpar.fill == fill
    assert encode(back) == data


def test_solid_fill_wire_format_is_unchanged() -> None:
    """纯色不写 `kind`：线格式仍是四元组（既有 case 的字节不能变）。"""
    data = encode(_scene(_rect(COLOUR)))
    payload = cbor2.loads(data)
    gpar = payload["scene"]["root"]["children"][0]["gpar"]
    assert gpar["fill"] == list(COLOUR)


def test_stops_are_one_compact_buffer() -> None:
    """色标是一组 (n, 5) 的 f4 缓冲，不是逐档的小映射。"""
    payload = cbor2.loads(encode(_scene(_rect(LINEAR))))
    stops = payload["scene"]["root"]["children"][0]["gpar"]["fill"]["stops"]
    assert stops["dtype"] == "f4"
    assert stops["shape"] == [3, 5]
    assert len(stops["data"]) == 3 * 5 * 4


def test_v0_2_file_still_reads() -> None:
    """旧 v0.2 文件：纯色 fill + `ir_version=[0, 2]`，必须原样读进来。"""
    payload = cbor2.loads(encode(_scene(_rect(COLOUR))))
    payload["ir_version"] = [0, 2]
    back = ir_decode(cbor2.dumps(payload, canonical=True))
    assert back.root.children[0].gpar.fill == COLOUR


def test_v0_2_file_without_fill_still_reads() -> None:
    payload = cbor2.loads(
        encode(_scene(Node("rect", gpar=Gpar(), bufs={"rect": f32([[0.0, 0.0, 1.0, 1.0]])})))
    )
    payload["ir_version"] = [0, 1]
    back = ir_decode(cbor2.dumps(payload, canonical=True))
    assert back.root.children[0].gpar.fill is None


def test_v0_3_arrow_file_still_reads() -> None:
    """v0.3 的箭头参数（#61）在 v0.4 里照读。

    0.3 = `arrow*`（#61），0.4 = 渐变 fill（本 PR）。同 major、文件 minor 更旧 →
    走严格模式，所以 0.4 的读方**必须**认识 0.3 的字段，否则升级一次就把老文件读死了。
    """
    node = Node(
        "segments",
        gpar=Gpar(col=(0, 0, 0, 255)),
        params={
            "arrow": "last",
            "arrow_length": 6.0,
            "arrow_angle": 30.0,
            "arrow_type": "closed",
        },
        bufs={"segments": f32([[0.0, 0.0, 10.0, 10.0]])},
    )
    payload = cbor2.loads(encode(_scene(node)))
    payload["ir_version"] = [0, 3]
    back = ir_decode(cbor2.dumps(payload, canonical=True))
    params = back.root.children[0].params
    assert str(params["arrow"]) == "last"
    assert float(params["arrow_length"]) == 6.0
    assert str(params["arrow_type"]) == "closed"


def test_v0_4_gradient_file_is_rejected_by_a_v0_3_reader() -> None:
    """反方向：0.4 的渐变文件给 0.3 读方，必须明确报版本错误，不能静默降级。

    `reader_version=(0, 3)` 把读方的版本视野降到 0.3：渐变 / 图案 fill 是 0.4 才有的
    语义，`_FILL_MINOR` 直接报 `IRVersionError`（如果按「跳过未知键」处理，渐变会变成
    不填充——静默画错图）。纯色不受影响，0.3 读方照常读。
    """
    data = encode(_scene(_rect(LINEAR)))
    assert cbor2.loads(data)["ir_version"] == [0, 4]
    with pytest.raises(IRVersionError, match=r"0\.4"):
        ir_decode(data, reader_version=(0, 3))
    solid = encode(_scene(_rect(COLOUR)))
    assert ir_decode(solid, reader_version=(0, 3)).root.children[0].gpar.fill == COLOUR


def test_stop_offsets_must_be_monotonic() -> None:
    with pytest.raises(IRValidationError):
        LinearGradient(
            stops=(Stop(0.5, COLOUR), Stop(0.25, COLOUR)), start=(0.0, 0.0), end=(1.0, 0.0)
        )


def test_gradient_needs_two_stops() -> None:
    with pytest.raises(IRValidationError):
        LinearGradient(stops=(Stop(0.0, COLOUR),), start=(0.0, 0.0), end=(1.0, 0.0))


def test_linear_gradient_rejects_coincident_points() -> None:
    with pytest.raises(IRValidationError):
        LinearGradient(
            stops=(Stop(0.0, COLOUR), Stop(1.0, COLOUR)), start=(1.0, 1.0), end=(1.0, 1.0)
        )


def test_radial_gradient_rejects_bad_radius_and_focal() -> None:
    stops = (Stop(0.0, COLOUR), Stop(1.0, COLOUR))
    with pytest.raises(IRValidationError):
        RadialGradient(stops=stops, center=(0.0, 0.0), radius=0.0)
    with pytest.raises(IRValidationError):
        RadialGradient(stops=stops, center=(0.0, 0.0), radius=2.0, focal=(0.0, 0.0, 2.0))


def test_pattern_rejects_empty_content_and_nesting() -> None:
    with pytest.raises(IRValidationError):
        TilePattern(content=(), size=(1.0, 1.0), origin=(0.0, 0.0))
    nested = _rect(LINEAR)
    with pytest.raises(IRValidationError):
        TilePattern(content=(nested,), size=(1.0, 1.0), origin=(0.0, 0.0))
    with pytest.raises(IRValidationError):
        TilePattern(content=(_rect(COLOUR),), size=(0.0, 1.0), origin=(0.0, 0.0))


def test_decode_rejects_unknown_fill_kind() -> None:
    payload = cbor2.loads(encode(_scene(_rect(LINEAR))))
    payload["scene"]["root"]["children"][0]["gpar"]["fill"]["kind"] = "conic"
    with pytest.raises(IRDecodeError):
        decode(cbor2.dumps(payload, canonical=True))


def test_decode_rejects_non_integer_stop_colours() -> None:
    payload = cbor2.loads(encode(_scene(_rect(LINEAR))))
    raw = bytearray(payload["scene"]["root"]["children"][0]["gpar"]["fill"]["stops"]["data"])
    # 第一档的红色分量改成 12.5（f4 位型：0x41480000 = 12.5）
    raw[4:8] = (12.5).hex().encode() if False else bytes.fromhex("00004841")
    payload["scene"]["root"]["children"][0]["gpar"]["fill"]["stops"]["data"] = bytes(raw)
    with pytest.raises(IRDecodeError):
        decode(cbor2.dumps(payload, canonical=True))
