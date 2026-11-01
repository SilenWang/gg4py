"""viewport 与 R `grid` 的逐条对拍（SIL-596 / M0-4）。

夹具 `tests/fixtures/viewport_r_reference.json` 由 `tools/refs/viewport_ref.R`
在 pixi 的 `refs` 环境（r-base 4.5.3）里生成：每条用例是一段**步骤脚本**
（push / pop / up / down / seek / check），R 侧走一遍并把每个 check 的结果记下来。
这里用同一份脚本重放 `ggcore.viewport`，逐项对拍路径、深度、累计旋转、视口尺寸、
裁剪框、解析后的 gpar，以及每个探针的「本视口英寸」与「设备英寸」。重新生成：

    pixi run -e refs refs:viewport
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ggcore.units import unit
from ggcore.viewport import (
    Device,
    Gpar,
    RotatedClipWarning,
    ViewportTree,
    VpNode,
    viewport,
)

FIXTURE = Path(__file__).parent / "fixtures" / "viewport_r_reference.json"
DOCUMENT = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = DOCUMENT["cases"]
DEVICE = Device(DOCUMENT["device"]["width_in"], DOCUMENT["device"]["height_in"])

#: 对拍容差：两侧都走同一套 double 运算，差异只应来自运算顺序。
TOL = {"rel": 1e-11, "abs": 1e-12}

GPAR_NAMES = (
    "fill",
    "col",
    "lwd",
    "lty",
    "lineend",
    "linejoin",
    "linemitre",
    "alpha",
    "cex",
    "fontsize",
    "lineheight",
    "font",
    "fontfamily",
    "lex",
)


def _unit(spec: dict[str, Any]) -> Any:
    return unit(float(spec["value"]), spec["unit"])


def _build(spec: dict[str, Any]) -> Any:
    """把夹具里的视口 spec 还原成 ggcore.viewport.viewport(...)。"""
    # 空的 gpar 在 R 侧是 list()，JSON 里是 []（无名字的对象没法自证），这里补回 {}。
    delta = spec.get("gp") or {}
    if isinstance(delta, list):
        delta = {}
    return viewport(
        spec["name"],
        x=_unit(spec["x"]),
        y=_unit(spec["y"]),
        width=_unit(spec["width"]),
        height=_unit(spec["height"]),
        just=spec["just"],
        xscale=spec["xscale"],
        yscale=spec["yscale"],
        angle=spec["angle"],
        clip=spec["clip"],
        gp=Gpar(**delta),
    )


def _replay(case: dict[str, Any]) -> Iterator[tuple[dict[str, Any], VpNode]]:
    """按夹具脚本走一遍，每个 check 产出 (步骤, 当前节点)。

    `check` 上的 `expected.clip_warning` 由 R 那边的 warning 处理器记下；这里用
    `record=True` 收自己的警告，保证“该警告/不该警告”两边一致。
    """
    tree = ViewportTree(DEVICE)
    for step in case["steps"]:
        op = step["op"]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if op == "push":
                tree.push(_build(step["vp"]))
            elif op == "pop":
                tree.pop(step["n"])
            elif op == "up":
                tree.up(step["n"])
            elif op == "down":
                tree.down(step["path"], strict=bool(step.get("strict", False)))
            elif op == "seek":
                tree.seek(step["path"])
            elif op == "check":
                yield step, tree.current
                continue
            else:  # pragma: no cover - 夹具格式错误
                raise AssertionError(f"unknown op: {op}")
        rotated = [item for item in caught if issubclass(item.category, RotatedClipWarning)]
        if op == "check":  # pragma: no cover - 上面的分支已经 continue
            pass
        if op in {"pop", "up"} and rotated:  # pragma: no cover - 夹具不该有这种步骤
            raise AssertionError("unexpected clip warning while navigating")


def _check_name(case: dict[str, Any], step: dict[str, Any]) -> str:
    return f"{case['id']}::{step['expected']['id']}"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_viewport_matches_r(case: dict[str, Any]) -> None:
    checked = 0
    for step, node in _replay(case):
        expected = step["expected"]
        name = _check_name(case, step)

        path = None if expected["path"] is None else "::".join(expected["path"])
        actual_path = None if node.parent is None else str(node.path)
        assert actual_path == path, name
        assert node.depth == expected["depth"], name
        assert node.rotation == pytest.approx(expected["rotation"], **TOL), name
        assert node.width_in == pytest.approx(expected["width_in"], **TOL), name
        assert node.height_in == pytest.approx(expected["height_in"], **TOL), name
        assert node.clip_rect == pytest.approx(expected["clip_in"], **TOL), name

        for field in GPAR_NAMES:
            want = expected["gpar"][field]
            got = getattr(node.gpar, field)
            if isinstance(want, str):
                assert got == want, f"{name} gpar.{field}"
            else:
                assert float(got) == pytest.approx(float(want), **TOL), f"{name} gpar.{field}"

        for probe in expected["probes"]:
            spec = probe["spec"]
            xs = _unit(spec["x"])
            ys = _unit(spec["y"])
            loc = node.local_loc(xs, ys)[0]
            assert loc == pytest.approx(probe["loc_in"], **TOL), f"{name} local_loc"
            device = node.device_points(xs, ys)[0]
            assert device == pytest.approx(probe["device_in"], **TOL), f"{name} device"
        checked += 1
    assert checked == sum(1 for step in case["steps"] if step["op"] == "check")


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_clip_warnings_match_r(case: dict[str, Any]) -> None:
    """R 在哪个 check 上报 `cannot clip to rotated viewport`，这里就要报同一个。"""
    tree = ViewportTree(DEVICE)
    warned_since_check = False
    for step in case["steps"]:
        op = step["op"]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if op == "push":
                tree.push(_build(step["vp"]))
            elif op == "pop":
                tree.pop(step["n"])
            elif op == "up":
                tree.up(step["n"])
            elif op == "down":
                tree.down(step["path"], strict=bool(step.get("strict", False)))
            elif op == "seek":
                tree.seek(step["path"])
        if any(issubclass(item.category, RotatedClipWarning) for item in caught):
            warned_since_check = True
        if op == "check":
            assert warned_since_check == step["expected"]["clip_warning"], (
                f"{case['id']}::{step['expected']['id']}"
            )
            warned_since_check = False
