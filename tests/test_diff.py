"""M0-9 差分管线：像素判据、报告、热图、结构化 JSON、SVG 文本转路径。

守 issue 的三条验收：

1. 正确实现 → 绿；**人为偏移 2 像素 → 红**（图级 < 2%、均值 < 1%）。
2. `diff` 给出可机读的百分比（`--json`），矩阵不解析人读文本。
3. 统一栅格：SVG 走 resvg，`<text>` 先转轮廓（resvg 0.47 画不出 Noto CJK VF）。
"""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from ggdiff.cli import main as diff_main
from ggdiff.compare import compare_images
from ggdiff.image import load_image, save_png
from ggdiff.raster import RasterError, rasterize_svg, resvg_path
from ggdiff.svgtext import inline_text_paths

REPO = Path(__file__).resolve().parents[1]


def _figure() -> np.ndarray:
    """一张有实心块、有文字粗细边缘的合成图（白底黑块）。"""
    image = np.full((120, 160, 3), 255, dtype=np.uint8)
    image[20:60, 20:70] = 0
    image[70:100, 90:140] = 40
    return image


def _shift(image: np.ndarray, dx: int, dy: int) -> np.ndarray:
    shifted = np.full_like(image, 255)
    height, width = image.shape[:2]
    shifted[max(dy, 0) : height + min(dy, 0), max(dx, 0) : width + min(dx, 0)] = image[
        max(-dy, 0) : height + min(-dy, 0), max(-dx, 0) : width + min(-dx, 0)
    ]
    return shifted


# ---------------------------------------------------------------------------
# 像素判据
# ---------------------------------------------------------------------------


def test_identical_images_pass_with_zero_metrics() -> None:
    image = _figure()
    result, mask, _ = compare_images(image, image.copy())
    assert result.verdict == "pass" and result.ok
    assert result.image_diff_fraction == 0.0
    assert result.mean_diff == 0.0
    assert not mask.any()


def test_two_pixel_shift_fails() -> None:
    image = _figure()
    result, mask, amount = compare_images(image, _shift(image, 2, 2))
    assert result.verdict == "fail"
    assert result.image_diff_fraction > 0.02
    assert result.reason.startswith("图级差异")
    assert mask.any() and amount.max() == 255


def test_broad_tint_fails_on_mean_even_when_no_pixel_exceeds_the_threshold() -> None:
    """整图偏 3/255：没有像素超过单像素阈值，但均值越过 1% —— 平均差异抓这个。"""
    reference = np.full((100, 100, 3), 128, dtype=np.uint8)
    actual = np.full((100, 100, 3), 131, dtype=np.uint8)
    result, mask, _ = compare_images(reference, actual)
    assert not mask.any()
    assert result.image_diff_fraction == 0.0
    assert result.mean_diff == pytest.approx(3 / 255)
    assert result.verdict == "fail"
    assert "平均差异" in result.reason


def test_size_mismatch_is_red_with_a_clear_reason() -> None:
    result, _, _ = compare_images(np.zeros((10, 10, 3), np.uint8), np.zeros((11, 10, 3), np.uint8))
    assert result.verdict == "fail"
    assert "尺寸不一致" in result.reason


# ---------------------------------------------------------------------------
# CLI：报告 / 热图 / JSON / 退出码
# ---------------------------------------------------------------------------


def _solid_svg(fill: str) -> str:
    """一张只有整块色块的 SVG（没有 `<text>`，不会被文本转路径改写）。"""
    return (
        "<?xml version='1.0' encoding='UTF-8' ?>\n"
        "<svg xmlns='http://www.w3.org/2000/svg' width='72' height='54' viewBox='0 0 72 54'>\n"
        f"<rect width='72' height='54' fill='#FFFFFF'/>\n"
        f"<rect x='10' y='8' width='40' height='30' fill='{fill}'/>\n"
        "</svg>\n"
    )


def _case_dir(tmp_path: Path, *, shift: tuple[int, int] = (0, 0)) -> Path:
    directory = tmp_path / "cases" / "geom-demo"
    current = directory / "current"
    current.mkdir(parents=True)
    image = _figure()
    Image.fromarray(image).save(directory / "expected.png")
    Image.fromarray(_shift(image, *shift)).save(current / "geom-demo.png")
    return directory


def test_cli_passes_writes_report_and_heatmap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = _case_dir(tmp_path)
    code = diff_main([str(case), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "pass" and payload["ok"] is True
    assert payload["image_diff_fraction"] == 0.0
    assert payload["thresholds"]["image_diff_fraction"] == 0.02
    assert payload["thresholds"]["mean_diff"] == 0.01
    assert Path(payload["report"]).is_file()
    assert Path(payload["heatmap"]).is_file()
    report = Path(payload["report"]).read_text(encoding="utf-8")
    assert "判定：**通过**" in report
    assert "图级差异" in report and "平均差异" in report


def test_cli_fails_on_two_pixel_offset_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = _case_dir(tmp_path, shift=(2, 2))
    code = diff_main([str(case), "--json", "--report", str(tmp_path / "r" / "report.md")])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "fail"
    assert payload["reason"]
    assert Path(payload["heatmap"]).is_file()
    assert "判定：**失败**" in Path(payload["report"]).read_text(encoding="utf-8")


def test_cli_two_file_form_and_tolerance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image = _figure()
    reference = tmp_path / "ref.png"
    actual = tmp_path / "actual.png"
    Image.fromarray(image).save(reference)
    Image.fromarray(_shift(image, 2, 2)).save(actual)

    code = diff_main(
        [str(reference), str(actual), "--tolerance", "0.5", "--mean-tolerance", "0.5", "--json"]
    )
    assert code == 0  # 两个阈值都放宽 → 绿
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "pass"

    code = diff_main([str(reference), str(actual), "--mean-tolerance", "0.0", "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "fail"


def test_cli_errors_are_structured_and_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = diff_main([str(tmp_path / "nope"), "--json"])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "error" and payload["ok"] is False


# ---------------------------------------------------------------------------
# 统一栅格：resvg + 文本转路径
# ---------------------------------------------------------------------------

SVGLITE_LIKE = (
    "<?xml version='1.0' encoding='UTF-8' ?>\n"
    "<svg xmlns='http://www.w3.org/2000/svg' width='288.00pt' height='216.00pt' "
    "viewBox='0 0 288.00 216.00'>\n"
    "<rect width='100%' height='100%' style='stroke: none; fill: #FFFFFF;'/>\n"
    "<text x='144.0' y='120.0' text-anchor='middle' "
    "style='font-size: 13.00px; fill: #222222; font-family: \"Noto Sans CJK SC\";' "
    "textLength='26.00px' lengthAdjust='spacingAndGlyphs'>中文</text>\n"
    "</svg>\n"
)


def _resvg_available() -> bool:
    try:
        resvg_path()
    except RasterError:
        return False
    return True


requires_resvg = pytest.mark.skipif(not _resvg_available(), reason="resvg 不在环境里")


def test_inline_text_paths_removes_text_and_keeps_geometry(tmp_path: Path) -> None:
    source = tmp_path / "in.svg"
    target = tmp_path / "out.svg"
    source.write_text(SVGLITE_LIKE, encoding="utf-8")
    converted = inline_text_paths(source, target)
    assert converted == 1
    payload = target.read_text(encoding="utf-8")
    assert "<text" not in payload
    assert "<path" in payload or ":path" in payload
    # 锚点 middle + textLength 26 → 起点 144 - 13 = 131。
    assert "translate(131.000 120.000)" in payload
    # 内联 style 覆盖 svglite 的 `.svglite path { fill: none }`。
    assert "fill: #222222; stroke: none;" in payload


def test_inline_text_paths_is_a_passthrough_for_our_own_svgs(tmp_path: Path) -> None:
    source = tmp_path / "ours.svg"
    source.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'><path d='M0 0'/></svg>", encoding="utf-8"
    )
    target = tmp_path / "copy.svg"
    assert inline_text_paths(source, target) == 0
    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


@requires_resvg
def test_resvg_renders_converted_cjk_text(tmp_path: Path) -> None:
    """参考图的 CJK 标签必须有墨：未转换时 resvg 画 Noto CJK VF 是空白的。"""
    source = tmp_path / "in.svg"
    source.write_text(SVGLITE_LIKE, encoding="utf-8")
    converted = tmp_path / "out.svg"
    inline_text_paths(source, converted)
    rasterize_svg(converted, tmp_path / "out.png", dpi=72)
    image = load_image(tmp_path / "out.png")
    assert int((image.min(axis=2) < 200).sum()) > 50
    assert image.shape == (216, 288, 3)


@requires_resvg
def test_same_named_svgs_are_not_compared_against_themselves(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SIL-649：`baseline/foo.svg` vs `current/foo.svg` 内容不同 → 必须红。

    修之前两侧的光栅化产物都叫 `scratch/foo.png`，后写的一侧覆盖先写的一侧，
    随后比的是同一张位图：`verdict=pass`、`image_diff=0`、退出码 0。同名文件在
    baseline 对比里是常态，静默判绿是差分体系里最不能有的失效模式。
    """
    reference = tmp_path / "baseline" / "foo.svg"
    actual = tmp_path / "current" / "foo.svg"
    reference.parent.mkdir()
    actual.parent.mkdir()
    reference.write_text(_solid_svg("#4C78A8"), encoding="utf-8")
    actual.write_text(_solid_svg("#F58518"), encoding="utf-8")
    assert reference.stem == actual.stem

    code = diff_main([str(reference), str(actual), "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "fail"
    assert payload["diff_pixels"] > 0
    assert payload["image_diff_fraction"] > payload["thresholds"]["image_diff_fraction"]


@requires_resvg
def test_same_named_identical_svgs_still_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """反面：同名且内容相同 → 仍然绿（不是靠「长得像」放过，是真比出 0）。"""
    reference = tmp_path / "a" / "foo.svg"
    actual = tmp_path / "b" / "foo.svg"
    reference.parent.mkdir()
    actual.parent.mkdir()
    for path in (reference, actual):
        path.write_text(_solid_svg("#4C78A8"), encoding="utf-8")

    assert diff_main([str(reference), str(actual), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "pass"
    assert payload["image_diff_fraction"] == 0.0


@requires_resvg
def test_diff_of_the_same_svg_is_zero(tmp_path: Path) -> None:
    source = tmp_path / "in.svg"
    source.write_text(SVGLITE_LIKE, encoding="utf-8")
    case = tmp_path / "cases" / "geom-text"
    case.mkdir(parents=True)
    shutil.copy(source, case / "expected.svg")
    current = case / "current"
    current.mkdir()
    shutil.copy(source, current / "geom-text.svg")
    code = diff_main([str(case)])
    assert code == 0


@requires_resvg
def test_resvg_actually_handles_pt_units_at_72_dpi(tmp_path: Path) -> None:
    """1 pt = 1 px：svglite 写 288pt，我们的设备写 288 用户单位，两边像素尺寸必须一致。"""
    source = tmp_path / "in.svg"
    source.write_text(SVGLITE_LIKE, encoding="utf-8")
    rasterize_svg(source, tmp_path / "out.png", dpi=72)
    assert load_image(tmp_path / "out.png").shape == (216, 288, 3)


def test_resvg_missing_gives_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GGDIFF_RESVG", "")
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(RasterError, match="找不到 resvg"):
        resvg_path()


def test_repository_baselines_pass_the_gate() -> None:
    """仓库里四张基准图的 expected.* 与提交的契约一致（不渲染，只读 meta）。"""
    cases = [path for path in (REPO / "docs" / "cases").iterdir() if (path / "meta.toml").is_file()]
    assert len(cases) >= 3
    for case in cases:
        meta = (case / "meta.toml").read_text(encoding="utf-8")
        assert 'source = "svglite:' in meta
        assert (case / "expected.svg").is_file()


def _render_text_case(scale: float) -> bytes:
    """渲染 `geom-text-cjk`，并把每个字形的推进与位置按 `scale` 缩放。

    这就是「实测侧文字宽度 +X%」的扰动：字形轮廓不变，只有步进变宽/变窄——
    等价于度量端算错宽度，而不是换字体或改字号。
    """
    from ggcore.plotspec import build_scene, load_plot
    from ggskia.skia import SkiaSvgDevice
    from ggskia.text import GlyphRun, ShaperMetrics, TextShaper

    case = REPO / "docs" / "cases" / "geom-text-cjk"
    shaper = TextShaper()
    runs = shaper.runs

    def scaled(key: str, text: str, size: float) -> tuple[GlyphRun, ...]:
        return tuple(
            GlyphRun(
                run.face,
                run.text,
                run.gids,
                tuple(offset * scale for offset in run.offsets),
                run.advance * scale,
            )
            for run in runs(key, text, size)
        )

    shaper.runs = scaled  # type: ignore[method-assign]
    scene = build_scene(load_plot(case), metrics=ShaperMetrics(shaper))
    return SkiaSvgDevice(*scene.size, dpi=scene.dpi, shaper=shaper).render(scene)


@requires_resvg
def test_two_percent_text_width_error_is_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """SIL-649 的验收：实测侧文字宽度 **+2%** 时 `cases:matrix` 必须红。

    阈值取 case 自己的 `tolerance.png`（1.4%），基线必须绿、+2% 必须红。
    这个 case 的标签是 18 字左对齐长标签：宽度误差沿字符串累积，短标签在
    2% 阈值下只剩垂直度量差的噪声（改之前 +2% 只有 1.47% → 1.50%）。
    """
    case = REPO / "docs" / "cases" / "geom-text-cjk"
    meta = tomllib.loads((case / "meta.toml").read_text(encoding="utf-8"))
    tolerance = float(meta["tolerance"]["png"])
    assert tolerance < 0.02, "文字类 case 必须比默认 2% 更紧"

    for scale, expected in ((1.0, 0), (1.02, 1)):
        target = tmp_path / f"text-{scale}.svg"
        target.write_bytes(_render_text_case(scale))
        code = diff_main(
            [str(case / "expected.svg"), str(target), "--tolerance", f"{tolerance:g}", "--json"]
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == expected, (scale, payload)
        if scale == 1.02:
            assert payload["verdict"] == "fail"
            assert payload["image_diff_fraction"] > tolerance


def test_png_roundtrip(tmp_path: Path) -> None:
    image = _figure()
    target = save_png(tmp_path / "x.png", image)
    assert target.is_file()
    assert np.array_equal(load_image(target), image)
