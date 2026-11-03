"""M1 文字测量：真实字面、`\\n` 多行、emoji 轮廓（SIL-655）。

不靠看图：字面解析、推进差、逐行宽度、行距、emoji 的 run/轮廓/颜色都逐条断言。
像素级对拍在 `tests/test_text_parity.py`（R 的 stringWidth）与
`tests/test_diff.py`（三个新 case）。
"""

from __future__ import annotations

import zlib

import numpy as np
import pytest
import skia

from ggcore.grobs import height_details, scene, text_grob, width_details
from ggcore.metrics import MetricProvider, TableBackend
from ggcore.metrics.catalog import FontCatalog
from ggcore.metrics.faces import FontFaceError
from ggcore.units import convert_height, convert_width, unit
from ggcore.viewport import Device, ViewportTree, gpar, viewport
from ggshape.harfbuzz import HarfBuzzBackend
from ggskia import SkiaPdfDevice, SkiaRasterDevice, SkiaSvgDevice
from ggskia.text import LINE_PITCH, ShaperMetrics, TextShaper, resolve_stack

WIDTH_PT = 200.0
HEIGHT_PT = 200.0


def _tree(fontsize: float = 20.0) -> ViewportTree:
    tree = ViewportTree(Device(WIDTH_PT / 72, HEIGHT_PT / 72), metrics=ShaperMetrics())
    tree.push(viewport("page", x=0.5, y=0.5, width=1.0, height=1.0, gp=gpar(fontsize=fontsize)))
    return tree


def _raster(label: str, *, fontsize: float = 20.0, hjust: float = 0.0, vjust: float = 0.5):
    tree = _tree(fontsize)
    grob = text_grob(
        label,
        x=unit(10.0, "bigpts"),
        y=unit(HEIGHT_PT / 2, "bigpts"),
        hjust=hjust,
        vjust=vjust,
        default_units="bigpts",
    )
    ir_scene = scene([grob], tree).to_ir_scene()
    png = SkiaRasterDevice(*ir_scene.size, dpi=72).render(ir_scene)
    image = skia.Image.MakeFromEncoded(png)
    assert image is not None
    return np.array(image.toarray(), dtype=np.int16)[:, :, :3]


def _ink_rows(pixels: np.ndarray) -> list[tuple[int, int]]:
    rows = np.where((pixels < 250).any(axis=2).any(axis=1))[0]
    assert rows.size, "没有墨迹"
    groups: list[tuple[int, int]] = []
    start = previous = int(rows[0])
    for row in rows[1:]:
        row = int(row)
        if row > previous + 3:
            groups.append((start, previous))
            start = row
        previous = row
    groups.append((start, previous))
    return groups


# ---------------------------------------------------------------------------
# 1. 字面：FontCatalog.resolve
# ---------------------------------------------------------------------------


def test_font_catalog_resolves_static_and_variable_faces() -> None:
    catalog = FontCatalog()
    regular = catalog.resolve("Noto Sans", 400, False)
    bold = catalog.resolve("Noto Sans", 700, False)
    italic = catalog.resolve("Noto Sans", 400, True)
    bold_italic = catalog.resolve("Noto Sans", 700, True)
    assert regular.filename == "NotoSans-VF.ttf" and regular.variation is None
    assert bold.filename == "NotoSans-VF.ttf" and bold.variation == 700
    assert italic.filename == "NotoSans-Italic-VF.ttf" and italic.variation is None
    assert bold_italic.filename == "NotoSans-Italic-VF.ttf"
    assert bold_italic.variation == 700

    dejavu_bold = catalog.resolve("DejaVu Sans", 700, False)
    assert dejavu_bold.filename == "DejaVuSans-Bold.ttf"
    assert dejavu_bold.variation is None  # 静态字面不走 wght 轴


def test_missing_face_raises_and_lists_available_styles() -> None:
    """CJK 只有 regular/bold：italic 必须报错，不静默回落常规。"""
    catalog = FontCatalog()
    with pytest.raises(FontFaceError, match="没有 italic 字面") as error:
        catalog.resolve("Noto Sans CJK SC", 400, True)
    assert "可用字面" in str(error.value)
    assert "regular" in str(error.value)
    # CJK 的 bold 是同一个可变文件上的 wght=700，报错必须把它列出来。
    assert "bold（wght=700）" in str(error.value)
    assert catalog.resolve("Noto Sans CJK SC", 700, False).variation == 700


def test_unknown_family_falls_back_to_the_managed_default() -> None:
    """未登记字族回落缺省字面（Arimo），不报错。

    `Arimo` 本身现在是登记字族——R 的 svglite 把缺省字面写成它（M2-a），
    conda-forge 只有 `Arimo-Italic-VF.ttf` 这一份文件（wght 轴只有 400），
    所以粗体请求落同一份字面，不编造一个不存在的 `wght` 轴。
    """
    faces = resolve_stack("Helvetica")
    assert faces[0].family == "Arimo"
    assert resolve_stack("Arimo")[0].filename == "Arimo-Italic-VF.ttf"
    assert resolve_stack("Arimo:bold")[0].weight == 700
    assert resolve_stack("Arimo:bold")[0].variation is None


def test_real_face_changes_advance() -> None:
    """Bold 必须真的更宽；斜体必须真的不同（同一串、同一字号）。"""
    metrics = ShaperMetrics()
    width = {
        face: metrics.strwidth("Bold text sample", fontsize=12, cex=1.0, font=key)
        for face, key in {
            "regular": "Noto Sans",
            "bold": "Noto Sans:bold",
            "italic": "Noto Sans:italic",
            "bold-italic": "Noto Sans:bold-italic",
        }.items()
    }
    assert width["regular"] == pytest.approx(94.50 / 72.0, rel=0.01)
    assert width["bold"] == pytest.approx(100.78 / 72.0, rel=0.01)
    assert width["italic"] == pytest.approx(88.52 / 72.0, rel=0.01)
    assert width["bold-italic"] == pytest.approx(95.34 / 72.0, rel=0.01)
    assert width["italic"] < width["regular"]  # 斜体字面更窄
    assert width["bold"] != pytest.approx(width["regular"])
    assert width["bold-italic"] != pytest.approx(width["bold"])


def test_bold_glyph_outline_differs_from_regular() -> None:
    """轮廓本身不同（不是只改 advance）：同一个 'B' 的路径点数/边界不同。"""
    shaper = TextShaper()
    regular = shaper.font(shaper.stack("Noto Sans")[0], 40)
    bold = shaper.font(shaper.stack("Noto Sans:bold")[0], 40)
    gid_r = int(regular.textToGlyphs("B")[0])
    gid_b = int(bold.textToGlyphs("B")[0])
    bounds_r = regular.getPath(gid_r).computeTightBounds()
    bounds_b = bold.getPath(gid_b).computeTightBounds()
    assert bounds_r.width() != pytest.approx(bounds_b.width())
    assert bounds_b.width() > bounds_r.width()


# ---------------------------------------------------------------------------
# 2. 多行：宽度、行距、整块锚点
# ---------------------------------------------------------------------------


def test_multiline_ir_width_is_the_widest_line_and_height_is_lines() -> None:
    tree = _tree(10.0)
    grob = text_grob("a\nbbbb\ncc", x=unit(1.0, "npc"), y=unit(1.0, "npc"))
    instruction = scene([grob], tree).instructions[0]
    metrics = ShaperMetrics()
    expected = max(
        metrics.strwidth(line, fontsize=10.0, cex=1.0) * 72.0 for line in ("a", "bbbb", "cc")
    )
    assert float(instruction.bufs["width"][0]) == pytest.approx(expected, rel=1e-6)

    node = tree.current
    height = convert_height(height_details(grob, node), "bigpts", ctx=node.unit_context())[0]
    assert height == pytest.approx(3 * 10.0 * 1.2)  # 行数 × 行高
    width = convert_width(width_details(grob, node), "bigpts", ctx=node.unit_context())[0]
    assert width == pytest.approx(expected)


def test_multiline_draws_one_line_per_row_with_r_line_pitch() -> None:
    size = 20.0
    # 三行用同一个字形：墨迹的上下沿相同，组顶点的间距就是基线行距。
    pixels = _raster("ooo\nooo\nooo", fontsize=size)
    groups = _ink_rows(pixels)
    assert len(groups) == 3, groups
    tops = [top for top, _ in groups]
    gaps = np.diff(tops)
    assert gaps == pytest.approx([LINE_PITCH * size, LINE_PITCH * size], abs=1.0)


def test_multiline_left_just_shares_the_left_edge() -> None:
    pixels = _raster("one\nsecond line\nthird", fontsize=20.0, hjust=0.0)
    groups = _ink_rows(pixels)
    lefts = []
    for top, bottom in groups:
        cols = np.where((pixels[top : bottom + 1] < 250).any(axis=2).any(axis=0))[0]
        lefts.append(int(cols[0]))
    assert max(lefts) - min(lefts) <= 1


def test_multiline_vertical_anchor_is_the_block() -> None:
    """vjust=0 的锚点是整块底边：最后一行贴着锚点，不是每行各自贴。"""
    pixels = _raster("one\ntwo\nthree", fontsize=20.0, vjust=0.0)
    groups = _ink_rows(pixels)
    assert len(groups) == 3
    # 锚点在页面 y = 100；整块底边贴在那里（最后一行基线 ≈ 100）。
    assert 90.0 < groups[-1][1] < 112.0
    assert groups[0][0] < groups[-1][0]


def test_svg_multiline_has_paths_not_text() -> None:
    tree = _tree(12.0)
    ir_scene = scene([text_grob("a\nb\nc")], tree).to_ir_scene()
    svg = SkiaSvgDevice(*ir_scene.size).render(ir_scene)
    assert b"<text" not in svg
    assert svg.count(b"<path") >= 3


# ---------------------------------------------------------------------------
# 3. emoji：run 切分、矢量轮廓、栅格彩色
# ---------------------------------------------------------------------------


def test_emoji_runs_switch_face_mid_string() -> None:
    shaper = TextShaper()
    runs = shaper.runs("sans", "smile \U0001f600", 20.0)
    assert [run.filename for run in runs] == ["Arimo-Italic-VF.ttf", "NotoColorEmoji.ttf"]
    assert runs[0].text == "smile "
    assert runs[1].text == "\U0001f600"
    # 彩色位图 24.95 vs 单色轮廓 25.39（+1.8%），R/cairo 是 25.0。
    assert runs[1].advance == pytest.approx(24.95, rel=0.01)
    outline = TextShaper(emoji="outline").runs("sans", "\U0001f600", 20.0)
    assert outline[0].filename == "NotoEmoji-Regular.ttf"
    assert outline[0].advance == pytest.approx(25.39, abs=0.02)


def test_emoji_width_is_the_same_on_all_three_metric_paths() -> None:
    """emoji 回退链只有 rules.json 一份：provider / 兜底表 / 设备三者同宽。"""
    provider = MetricProvider(HarfBuzzBackend()).strwidth("\U0001f600", 20.0)
    table = MetricProvider(TableBackend.from_file()).strwidth("\U0001f600", 20.0)
    device = ShaperMetrics().strwidth("\U0001f600", fontsize=20.0, cex=1.0) * 72.0
    assert provider == pytest.approx(table, rel=1e-6)
    assert provider == pytest.approx(device, rel=0.01)
    for width in (provider, table, device):
        assert width == pytest.approx(25.00, rel=0.02)


def test_emoji_outline_is_used_by_vector_backends_only() -> None:
    stack_color = [face.filename for face in resolve_stack("sans", emoji="color")]
    stack_outline = [face.filename for face in resolve_stack("sans", emoji="outline")]
    assert "NotoColorEmoji.ttf" in stack_color
    assert "NotoColorEmoji.ttf" not in stack_outline
    assert "NotoEmoji-Regular.ttf" in stack_outline


def test_emoji_vector_backend_draws_outlines() -> None:
    tree = _tree(40.0)
    ir_scene = scene(
        [text_grob("\U0001f600", x=unit(20, "bigpts"), y=unit(60, "bigpts"), hjust=0)], tree
    ).to_ir_scene()
    svg = SkiaSvgDevice(*ir_scene.size).render(ir_scene)
    assert b"<text" not in svg
    assert b"<path" in svg


def test_emoji_pdf_backend_draws_outlines() -> None:
    """PDF 里 emoji 也必须是轮廓：没有位图、没有字体、有路径算子。"""
    tree = _tree(40.0)
    ir_scene = scene(
        [text_grob("\U0001f600", x=unit(20, "bigpts"), y=unit(60, "bigpts"), hjust=0)], tree
    ).to_ir_scene()
    pdf = SkiaPdfDevice(*ir_scene.size).render(ir_scene)
    assert b"/Subtype /Image" not in pdf
    assert b"/Font" not in pdf
    # 内容流是 Flate 压缩的，路径算子要在解压后看。
    start = pdf.index(b"stream\n") + len(b"stream\n")
    content = zlib.decompress(pdf[start : pdf.index(b"endstream", start)])
    assert b" m\n" in content
    assert b" c\n" in content or b" l\n" in content


def test_emoji_raster_backend_keeps_colour() -> None:
    pixels = _raster("\U0001f600", fontsize=40.0)
    assert (pixels < 250).any()
    coloured = (
        (np.abs(pixels[:, :, 0] - pixels[:, :, 1]) > 10)
        | (np.abs(pixels[:, :, 1] - pixels[:, :, 2]) > 10)
    ).sum()
    assert coloured > 100, f"彩色像素只有 {coloured}，栅格后端退成了单色"
