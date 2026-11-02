"""M1-12：`ggsave` / `save_ir` / `export_ir_json` 的入口测试。

验收口径（issue SIL-707）：

- 同一张图三路输出都成功，PNG 的像素尺寸 = `width × dpi` / `height × dpi`；
- 矢量后端的文字仍是轮廓（SVG 无 `<text>`、PDF 无 `/Font`），新入口没有绕过 M0-8 的约定；
- `save_ir` 写出后再 `decode`，与原场景 `scene_equal`；
- 同一输入两次 `ggsave` 逐字节相等；
- `units` 四种各一次，`dpi=150` 的像素尺寸正确。

另外守住 `.ir.json` 的口径（bulk 数据只留摘要，X1 `gate:ir-json` 的边界）与
CLI（`python -m ggskia.cli.ggsave`）。口径全文见 `docs/notes/io.md`。
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import skia

from ggcore import ir
from ggcore.geom.scene import scene_from_plot
from ggcore.io import (
    DEFAULT_DPI,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    Backend,
    SaveError,
    export_ir_json,
    ggsave,
    ir_json_view,
    register_backend,
    registered_backend,
    save_ir,
)
from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggio.frame import from_dict
from ggskia import SkiaSvgDevice, device_for
from ggskia.cli import ggsave as ggsave_cli
from ggskia.cli import render as render_cli
from ggskia.text import ShaperMetrics

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "tools" / "examples" / "ggsave_demo.py"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def plot() -> ggplot:
    """带图例 + 分面的散点图（与 `tools/examples/ggsave_demo.py` 同一张图）。"""
    rng = np.random.default_rng(707)
    size = 30
    return (
        ggplot(
            from_dict(
                {
                    "x": rng.normal(size=size),
                    "y": rng.normal(size=size),
                    "group": np.array(["a", "b", "c"])[rng.integers(0, 3, size)],
                    "panel": np.array(["早期", "晚期"])[rng.integers(0, 2, size)],
                }
            ),
            aes(x="x", y="y", colour="group"),
        )
        + geom_point()
        + facet_wrap("panel")
        + labs(title="ggsave 测试")
    )


@pytest.fixture(scope="module")
def metrics() -> ShaperMetrics:
    return ShaperMetrics()


def png_size(data: bytes) -> tuple[int, int]:
    """PNG 的 IHDR 宽高（不依赖解码器，和 `docs/notes/device.md` 的口径一致）。"""
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[12:16] == b"IHDR"
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def dark_pixels(data: bytes) -> int:
    """深色像素数：页面是白底 + grey92 面板，字与坐标轴是深色（彩点不算）。"""
    image = skia.Image.MakeFromEncoded(data)
    assert image is not None
    pixels = np.array(image.toarray(), dtype=np.uint8, copy=True)
    return int((pixels[:, :, :3] < 200).all(axis=2).sum())


# ---------------------------------------------------------------------------
# 三路输出
# ---------------------------------------------------------------------------


def test_three_formats_come_from_one_plot(tmp_path: Path) -> None:
    outputs = {}
    for suffix in ("png", "svg", "pdf"):
        result = ggsave(plot(), tmp_path / f"out.{suffix}", width=4, height=3, dpi=144)
        assert result.path == tmp_path / f"out.{suffix}"
        assert result.format == suffix
        assert result.bytes == result.path.stat().st_size
        assert (result.width_pt, result.height_pt) == (288.0, 216.0)
        assert (
            result.device
            == {
                "png": "SkiaRasterDevice",
                "svg": "SkiaSvgDevice",
                "pdf": "SkiaPdfDevice",
            }[suffix]
        )
        outputs[suffix] = result.path.read_bytes()

    assert png_size(outputs["png"]) == (4 * 144, 3 * 144)
    assert outputs["svg"].lstrip().startswith(b"<?xml")
    assert b"<path" in outputs["svg"]
    assert outputs["pdf"].startswith(b"%PDF")
    # 三路都真的画了东西：标题 / 分面 strip / 图例 / 坐标轴的字是深色。
    assert dark_pixels(outputs["png"]) > 1000


def test_png_pixels_follow_width_height_and_dpi(tmp_path: Path) -> None:
    default = ggsave(plot(), tmp_path / "default.png")
    assert default.dpi == DEFAULT_DPI
    assert default.size_px == (
        round(DEFAULT_WIDTH * DEFAULT_DPI),
        round(DEFAULT_HEIGHT * DEFAULT_DPI),
    )
    assert default.size_px == (504, 360)

    big = ggsave(plot(), tmp_path / "big.png", width=6.5, height=3.25, dpi=150)
    assert png_size(big.path.read_bytes()) == (975, 488)
    assert big.size_px == png_size(big.path.read_bytes())


@pytest.mark.parametrize(
    ("width", "height", "units", "expected_in"),
    [
        (7.0, 5.0, "in", (7.0, 5.0)),
        (17.78, 12.7, "cm", (7.0, 5.0)),
        (177.8, 127.0, "mm", (7.0, 5.0)),
        (504.0, 360.0, "pt", (7.0, 5.0)),
    ],
)
def test_units_scale_the_same_page(
    tmp_path: Path, width: float, height: float, units: str, expected_in: tuple[float, float]
) -> None:
    result = ggsave(
        plot(), tmp_path / f"{units}.png", width=width, height=height, units=units, dpi=150
    )
    assert result.units == units
    assert (result.width_in, result.height_in) == pytest.approx(expected_in, abs=1e-9)
    assert (result.width_pt, result.height_pt) == pytest.approx((504.0, 360.0), abs=1e-9)
    assert result.size_px == (1050, 750)
    assert png_size(result.path.read_bytes()) == (1050, 750)


def test_vector_backends_keep_text_as_outlines(tmp_path: Path) -> None:
    svg = ggsave(plot(), tmp_path / "out.svg").path.read_bytes()
    pdf = ggsave(plot(), tmp_path / "out.pdf").path.read_bytes()
    assert b"<text" not in svg
    assert b"font-family" not in svg
    assert b"/Font" not in pdf


def test_ggsave_is_byte_identical_on_a_second_run(tmp_path: Path) -> None:
    for suffix in ("png", "svg", "pdf"):
        first = ggsave(plot(), tmp_path / f"a.{suffix}", dpi=144).path.read_bytes()
        second = ggsave(plot(), tmp_path / f"b.{suffix}", dpi=144).path.read_bytes()
        assert first == second, suffix


# ---------------------------------------------------------------------------
# 设备覆盖与参数校验
# ---------------------------------------------------------------------------


def test_device_override_wins_over_the_suffix(tmp_path: Path) -> None:
    target = tmp_path / "plot.bin"
    result = ggsave(plot(), target, device="svg")
    assert result.format == "svg"
    assert target.read_bytes().lstrip().startswith(b"<?xml")


def test_device_instance_and_factory_are_accepted(tmp_path: Path) -> None:
    scene_size = (288.0, 216.0)
    instance = SkiaSvgDevice(*scene_size)
    result = ggsave(plot(), tmp_path / "x.svg", width=4, height=3, device=instance)
    assert result.device == "SkiaSvgDevice"
    assert b"<path" in result.path.read_bytes()

    calls: list[tuple[float, float, float]] = []

    def factory(width_pt: float, height_pt: float, *, dpi: float):
        calls.append((width_pt, height_pt, dpi))
        return device_for("png", width_pt, height_pt, dpi=dpi)

    by_factory = ggsave(plot(), tmp_path / "y.png", width=4, height=3, dpi=96, device=factory)
    assert calls == [(288.0, 216.0, 96.0)]
    assert by_factory.device == "SkiaRasterDevice"
    assert png_size(by_factory.path.read_bytes()) == (384, 288)


def test_device_instance_must_match_the_page(tmp_path: Path) -> None:
    with pytest.raises(SaveError, match="页面尺寸"):
        ggsave(plot(), tmp_path / "x.svg", device=SkiaSvgDevice(100.0, 100.0))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"units": "px"}, "units"),
        ({"width": 0.0}, "width"),
        ({"height": float("nan")}, "height"),
        ({"width": "7"}, "width"),
        ({"dpi": 0}, "dpi"),
    ],
)
def test_bad_dimensions_are_rejected(tmp_path: Path, kwargs: dict, message: str) -> None:
    with pytest.raises(SaveError, match=message):
        ggsave(plot(), tmp_path / "bad.png", **kwargs)


def test_unknown_suffix_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SaveError, match="后缀"):
        ggsave(plot(), tmp_path / "out.eps")


def test_missing_backend_only_blocks_graphics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没注册后端时：`.cbor` / `.json` 照写，PNG 给出可照做的报错。"""
    monkeypatch.setattr("ggcore.io._BACKEND", None)
    assert registered_backend() is None
    with pytest.raises(SaveError, match="ggskia"):
        ggsave(plot(), tmp_path / "out.png")
    assert save_ir(plot(), tmp_path / "scene.ggir.cbor").bytes > 0
    assert export_ir_json(plot(), tmp_path / "scene.ir.json").bytes > 0


# ---------------------------------------------------------------------------
# IR 落盘
# ---------------------------------------------------------------------------


def test_save_ir_roundtrips_to_the_same_scene(tmp_path: Path, metrics: ShaperMetrics) -> None:
    target = tmp_path / "scene.ggir.cbor"
    result = save_ir(plot(), target)
    assert result.format == "cbor"
    assert result.device is None
    assert result.size_px is None
    assert result.dpi == 72.0

    restored = ir.decode(target.read_bytes())
    expected = scene_from_plot(
        plot(), width_in=DEFAULT_WIDTH, height_in=DEFAULT_HEIGHT, metrics=metrics
    )
    assert ir.scene_equal(restored, expected)
    assert restored.size == (504.0, 360.0)


def test_saved_ir_renders_through_the_render_task(tmp_path: Path) -> None:
    """`.ggir.cbor` 是 `pixi run render --scene …` 的输入：换个入口还能出图。"""
    source = save_ir(plot(), tmp_path / "scene.ggir.cbor").path
    target = tmp_path / "from-ir.png"
    assert render_cli.main(["--scene", str(source), "--out", str(target)]) == 0
    assert png_size(target.read_bytes()) == (504, 360)


def test_save_ir_honours_units_and_size(tmp_path: Path) -> None:
    result = save_ir(plot(), tmp_path / "scene.ggir.cbor", width=10, height=6, units="cm")
    assert (result.width_in, result.height_in) == pytest.approx(
        (3.937007874015748, 2.3622047244094486)
    )
    assert ir.decode(result.path.read_bytes()).size == pytest.approx(
        (10 / 2.54 * 72, 6 / 2.54 * 72), abs=1e-9
    )


def test_export_ir_json_describes_nodes_without_bulk_data(tmp_path: Path) -> None:
    target = tmp_path / "scene.ir.json"
    result = export_ir_json(plot(), target)
    assert result.format == "json"
    assert result.size_px is None

    view = json.loads(target.read_text(encoding="utf-8"))
    assert view["magic"] == "ggir"
    assert view["ir_version"] == ir.IR_VERSION_STR
    assert view["size"] == [504.0, 360.0]
    assert view["dpi"] == 72.0

    cbor = save_ir(plot(), tmp_path / "scene.ggir.cbor")
    decoded = ir.decode(cbor.path.read_bytes())
    assert view["stats"]["node_count"] == len(list(ir.walk(decoded.root)))

    # 每个缓冲只留摘要：dtype / shape / nbytes / sha256，没有逐元素数据。
    seen: list[str] = []

    def walk(node: dict) -> None:
        seen.append(node["id"])
        for buffer in node.get("bufs", []):
            assert set(buffer) == {"name", "dtype", "shape", "nbytes", "sha256"}
            assert isinstance(buffer["shape"], list)
            assert len(buffer["sha256"]) == 64
        for child in node.get("children", []):
            walk(child)

    walk(view["root"])
    assert len(seen) == len(set(seen)) == view["stats"]["node_count"]
    assert view["stats"]["buffer_bytes"] > 0


def test_ir_json_view_matches_the_scene(tmp_path: Path, metrics: ShaperMetrics) -> None:
    scene = scene_from_plot(plot(), width_in=4, height_in=3, metrics=metrics)
    view = ir_json_view(scene)
    assert view["size"] == [288.0, 216.0]
    kinds = {node.kind.value for node in ir.walk(scene.root)}
    assert {"viewport", "points", "text"} <= kinds
    assert view["root"]["id"] == "0"
    assert view["root"]["children"][0]["id"] == "0/0"


def test_ir_json_view_rejects_non_scenes() -> None:
    with pytest.raises(TypeError, match=r"ir\.Scene"):
        ir_json_view({"size": [1, 1]})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_every_target_kind(tmp_path: Path) -> None:
    target = f"{DEMO}:plot"
    for suffix in ("png", "svg", "pdf", "ggir.cbor", "ir.json"):
        out = tmp_path / f"demo.{suffix}"
        assert ggsave_cli.main([target, str(out), "--dpi", "150"]) == 0
        assert out.stat().st_size > 0
    assert png_size((tmp_path / "demo.png").read_bytes()) == (1050, 750)
    assert (tmp_path / "demo.ggir.cbor").read_bytes()[:1] != b"{"
    assert json.loads((tmp_path / "demo.ir.json").read_text(encoding="utf-8"))["magic"] == "ggir"


def test_cli_reports_the_artifact(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "line.png"
    assert ggsave_cli.main([f"{DEMO}:plot", str(out), "--width", "4", "--height", "3"]) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith(f"{out}: ")
    assert "png" in line and "288×216 pt → 288×216 px" in line and "SkiaRasterDevice" in line


def test_cli_reports_the_ir_artifact_without_pixels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "line.ir.json"
    assert ggsave_cli.main([f"{DEMO}:plot", str(out)]) == 0
    line = capsys.readouterr().out.strip()
    assert "json" in line and "px" not in line


def test_cli_rejects_bad_targets_and_suffixes(tmp_path: Path) -> None:
    assert ggsave_cli.main([f"{DEMO}:missing", str(tmp_path / "x.png")]) == 2
    assert ggsave_cli.main([f"{DEMO}:plot", str(tmp_path / "x.eps")]) == 2
    assert ggsave_cli.main(["no-colon", str(tmp_path / "x.png")]) == 2
    assert not (tmp_path / "x.png").exists()


def test_cli_runs_as_a_module_subprocess(tmp_path: Path) -> None:
    environment = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    out = tmp_path / "sub.png"
    result = subprocess.run(
        [sys.executable, "-m", "ggskia.cli.ggsave", f"{DEMO}:plot", str(out)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert str(out) in result.stdout
    assert png_size(out.read_bytes()) == (504, 360)


def test_backend_registration_shape() -> None:
    backend = registered_backend()
    assert backend is not None and backend.name == "ggskia"
    assert backend.metrics is ShaperMetrics
    with pytest.raises(TypeError, match="Backend"):
        register_backend("nope")  # type: ignore[arg-type]
    register_backend(Backend(device=device_for, metrics=ShaperMetrics, name="ggskia"))
    assert registered_backend() is not None
