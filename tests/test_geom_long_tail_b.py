"""M2-7 长尾 B：文本 / 点 / 分布 / 2D 族 geom 的契约与绘制。

三组断言：

1. **契约**：注册表里的名字、默认 stat / position、`required_aes` /
   `default_aes` 与 4.0.3 的 `Geom*` 一致；`geom_jitter(width=)` 的 position 语义。
2. **绘制**：`Geom.draw()` 产出的节点形状（text / label / polygon / path / circle /
   rect）与坐标口径；`check_overlap` 的重叠删行。
3. **图例 key**：每个新 geom 都有 `_GEOM_KEYS` 模板，`key_table()` 能画出键数据
   （`draw_key_*` 的等价物）。

统计量（density / ydensity / bindot / bin2d / binhex / contour / density_2d /
qq / quantile / function / sum）归 stat 侧任务；这里用 `stat = "identity"` 把
**stat 输出**喂给绘制层，和 M1-7 对 boxplot / smooth 的口径相同。
"""

from __future__ import annotations

import numpy as np
import pytest

from ggcore import registry
from ggcore.build import build_plot
from ggcore.geom import registered_renderers, renderer_for
from ggcore.geom.scene import scene_from_plot
from ggcore.guide import _GEOM_KEYS
from ggcore.plot import aes, ggplot
from ggcore.theme import theme as local_theme
from ggio.frame import to_column_table

SIZE = dict(width_in=4.0, height_in=3.0)


class FakeMetrics:
    """稳定度量：0.5em/字符、cap height 0.75em、descent 0.22em（英寸）。"""

    def strwidth(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        del font
        lines = str(text).split("\n")
        return 0.5 * float(fontsize) * float(cex) * max(len(line) for line in lines) / 72.0

    def strheight(self, text: str, *, fontsize: float, cex: float, font: str = "sans") -> float:
        del font
        return 0.75 * float(fontsize) * float(cex) * str(text).count("\n") / 72.0 or (
            0.75 * float(fontsize) * float(cex) / 72.0
        )

    def descent(self, *, fontsize: float, cex: float = 1.0, font: str = "sans") -> float:
        del font
        return 0.22 * float(fontsize) * float(cex) / 72.0


METRICS = FakeMetrics()

#: 18 个导出 / 20 个注册名（`geom_bin2d` / `geom_bin_2d` 这类别名各占一个名字）。
NEW_GEOMS = (
    "text",
    "label",
    "jitter",
    "count",
    "bin2d",
    "bin_2d",
    "hex",
    "density",
    "density_2d",
    "density2d",
    "density_2d_filled",
    "density2d_filled",
    "contour",
    "contour_filled",
    "dotplot",
    "violin",
    "qq",
    "qq_line",
    "quantile",
    "function",
)


def _nodes(scene) -> list:
    out = []

    def walk(node):
        out.append(node)
        for child in node.children:
            walk(child)

    walk(scene.root)
    return out


def _kinds(scene, kind: str) -> list:
    return [node for node in _nodes(scene) if node.kind.value == kind]


def _scene(plot) -> object:
    # 本文件只断言**绘制**节点；图例 key 另有专门的测试（`_GEOM_KEYS`），
    # 这里把图例关掉，免得 colourbar / key 的矩形混进计数。
    return scene_from_plot(
        plot + registry.theme_void() + local_theme(**{"legend.position": "none"}),
        metrics=METRICS,
        **SIZE,
    )


# ---------------------------------------------------------------------------
# 契约
# ---------------------------------------------------------------------------


def test_all_long_tail_geoms_are_registered_with_renderers() -> None:
    names = set(registered_renderers())
    assert set(NEW_GEOMS) <= names
    # 别名（`geom_bin_2d` / `geom_density2d`）复用同一个绘制实现，`name` 是规范名。
    canonical = {
        "bin_2d": "bin2d",
        "density2d": "density_2d",
        "density2d_filled": "density_2d_filled",
    }
    for name in NEW_GEOMS:
        assert renderer_for(name).name == canonical.get(name, name)


@pytest.mark.parametrize(
    ("factory", "stat", "position"),
    [
        ("geom_text", "identity", "nudge"),
        ("geom_label", "identity", "nudge"),
        ("geom_jitter", "identity", "jitter"),
        ("geom_count", "sum", "identity"),
        ("geom_bin2d", "bin2d", "identity"),
        ("geom_bin_2d", "bin2d", "identity"),
        ("geom_hex", "binhex", "identity"),
        ("geom_density", "density", "identity"),
        ("geom_density_2d", "density_2d", "identity"),
        ("geom_density2d", "density_2d", "identity"),
        ("geom_density_2d_filled", "density_2d_filled", "identity"),
        ("geom_density2d_filled", "density_2d_filled", "identity"),
        ("geom_contour", "contour", "identity"),
        ("geom_contour_filled", "contour_filled", "identity"),
        ("geom_violin", "ydensity", "dodge"),
        ("geom_qq", "qq", "identity"),
        ("geom_qq_line", "qq_line", "identity"),
        ("geom_quantile", "quantile", "identity"),
        ("geom_function", "function", "identity"),
    ],
)
def test_default_stat_and_position_match_ggplot2(factory: str, stat: str, position: str) -> None:
    layer = getattr(registry, factory)()
    assert layer.stat.name == stat
    assert layer.position.name == position


def test_geom_jitter_width_converts_to_position_jitter() -> None:
    layer = registry.geom_jitter(width=0.2, height=0.1)
    assert layer.position.name == "jitter"
    assert layer.position.params["width"] == pytest.approx(0.2)
    assert layer.position.params["height"] == pytest.approx(0.1)
    assert "width" not in layer.params and "height" not in layer.params
    with pytest.raises(ValueError, match="不能同时给"):
        registry.geom_jitter(width=0.2, position="jitter")


def test_required_and_default_aes_match_ggplot2() -> None:
    text = registry.geom_text().geom
    assert text.required_aes == ("x", "y", "label")
    assert text.non_missing_aes == ("angle",)
    assert text.default_aes["angle"] == 0.0
    assert text.default_aes["hjust"] == 0.5
    assert text.default_aes["size"] == pytest.approx(3.87)
    assert text.default_aes["lineheight"] == pytest.approx(1.2)

    label = registry.geom_label().geom
    assert label.default_aes["fill"] == "white"
    assert label.default_aes["linewidth"] == pytest.approx(0.25)

    bin2d = registry.geom_bin2d().geom
    assert bin2d.non_missing_aes == ("xmin", "xmax", "ymin", "ymax")
    assert bin2d.default_aes["fill"] == "#333333"
    assert bin2d.default_aes["linewidth"] == pytest.approx(0.2)

    assert registry.geom_hex().geom.default_aes["fill"] == "#808080"
    assert registry.geom_density().geom.default_aes["fill"] is None
    assert registry.geom_contour().geom.default_aes["colour"] == "#3366FF"
    assert registry.geom_violin().geom.default_aes["fill"] == "white"
    assert registry.geom_dotplot().geom.default_aes["fill"] == "black"


# ---------------------------------------------------------------------------
# geom_text
# ---------------------------------------------------------------------------


def _text_plot(**params) -> object:
    data = to_column_table(
        {
            "x": [0.15, 0.5, 0.85],
            "y": [0.5, 0.5, 0.5],
            "label": ["left", "mid", "right"],
            "ang": [0.0, 45.0, 0.0],
        }
    )
    return ggplot(data, aes(x="x", y="y", label="label", angle="ang")) + registry.geom_text(
        size=5, **params
    )


def test_text_draws_one_grob_per_angle_and_keeps_rotation() -> None:
    scene = _scene(_text_plot())
    texts = _kinds(scene, "text")
    assert len({float(node.params["angle"]) for node in texts}) == 2
    assert sum(len(node.texts) for node in texts) == 3
    node = next(node for node in texts if float(node.params["angle"]) == 45.0)
    assert node.texts == ("mid",)
    # size = 5mm → 5 * 72.27/25.4 pt
    assert float(node.params["size"]) == pytest.approx(5 * 72.27 / 25.4)


def test_text_hjust_and_vjust_shift_the_anchor() -> None:
    data = to_column_table({"x": [0.5], "y": [0.5], "label": ["a"]})
    base = ggplot(data, aes(x="x", y="y", label="label")) + registry.geom_text(size=5)
    left = ggplot(data, aes(x="x", y="y", label="label")) + registry.geom_text(size=5, hjust=0.0)
    right = ggplot(data, aes(x="x", y="y", label="label")) + registry.geom_text(size=5, hjust=1.0)
    quarter = ggplot(data, aes(x="x", y="y", label="label")) + registry.geom_text(
        size=5, hjust=0.25
    )
    n0 = _kinds(_scene(base), "text")[0]
    n1 = _kinds(_scene(left), "text")[0]
    n2 = _kinds(_scene(right), "text")[0]
    n3 = _kinds(_scene(quarter), "text")[0]
    assert [n.params["anchor"] for n in (n1, n0, n2)] == ["left", "center", "right"]
    # 非枚举值折进 pos（pos 是锚点，不是视觉位置）：hjust = 0.25 的锚点向
    # left 锚点方向偏移 1/4 文字宽。
    assert float(n3.bufs["pos"][0][0]) < float(n1.bufs["pos"][0][0])
    assert float(n1.bufs["pos"][0][0]) == pytest.approx(float(n0.bufs["pos"][0][0]))


def test_text_check_overlap_drops_the_second_label() -> None:
    data = to_column_table({"x": [0.5, 0.52], "y": [0.5, 0.5], "label": ["overlap", "overlap"]})
    plot = (
        ggplot(data, aes(x="x", y="y", label="label"))
        + registry.geom_text(size=8, check_overlap=True)
        + registry.scale_x_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
        + registry.scale_y_continuous(limits=(0.0, 1.0), expand=(0.0, 0.0))
    )
    texts = _kinds(_scene(plot), "text")
    assert sum(len(node.texts) for node in texts) == 1


def test_text_nudge_offsets_in_data_space() -> None:
    data = to_column_table({"x": [0.5], "y": [0.5], "label": ["a"]})
    plain = ggplot(data, aes(x="x", y="y", label="label")) + registry.geom_text(size=5)
    nudged = ggplot(data, aes(x="x", y="y", label="label")) + registry.geom_text(
        size=5, nudge_x=0.2
    )
    assert (
        _kinds(_scene(nudged), "text")[0].bufs["pos"][0][0]
        > _kinds(_scene(plain), "text")[0].bufs["pos"][0][0]
    )


# ---------------------------------------------------------------------------
# geom_label
# ---------------------------------------------------------------------------


def test_label_draws_background_rect_and_text() -> None:
    data = to_column_table({"x": [0.5, 0.5], "y": [0.3, 0.7], "label": ["ab", "cde"]})
    plot = ggplot(data, aes(x="x", y="y", label="label")) + registry.geom_label(size=5)
    scene = _scene(plot)
    rects = _kinds(scene, "rect")
    texts = _kinds(scene, "text")
    assert len(rects) == 2
    assert sum(len(node.texts) for node in texts) == 2
    widths = np.asarray([node.bufs["rect"][0][2] - node.bufs["rect"][0][0] for node in rects])
    # 更长的标签得到更宽的背景框。
    assert widths[1] > widths[0] > 0


# ---------------------------------------------------------------------------
# 分布族
# ---------------------------------------------------------------------------


def test_density_draws_area_polygon_and_upper_outline_only() -> None:
    data = to_column_table({"x": [0.1, 0.3, 0.5, 0.7, 0.9], "y": [0.1, 0.5, 0.9, 0.4, 0.1]})
    plot = ggplot(data, aes(x="x", y="y")) + registry.geom_density(
        stat="identity", colour="black", fill=None
    )
    scene = _scene(plot)
    assert len(_kinds(scene, "polygon")) == 1
    # outline.type = "upper"：只描上沿一条折线（area 的默认 both 是两条）。
    assert len(_kinds(scene, "polyline")) == 1


def test_violin_uses_violinwidth_and_closes_the_polygon() -> None:
    data = to_column_table(
        {
            "x": [1.0, 1.0, 1.0],
            "y": [0.1, 0.3, 0.5],
            "violinwidth": [0.0, 0.5, 1.0],
            "xmin": [0.6, 0.6, 0.6],
            "xmax": [1.4, 1.4, 1.4],
            "group": [1.0, 1.0, 1.0],
        }
    )
    plot = ggplot(
        data, aes(x="x", y="y", violinwidth="violinwidth", xmin="xmin", xmax="xmax")
    ) + registry.geom_violin(stat="identity", fill="white", colour="black")
    polygons = _kinds(_scene(plot), "polygon")
    assert len(polygons) == 1
    points = np.asarray(polygons[0].bufs["points"])
    assert points.shape[0] == 7  # 3 + 3 + 闭合点
    # 两端 violinwidth = 0 → 收在中心线上；`y = 0.5` 处展开到 xmin / xmax。
    assert points[0][0] == pytest.approx(points[-1][0])
    # 左沿向下展开（x 递减），右沿向上收窄（x 递减），两端回到中心线。
    assert points[0][0] > points[1][0] > points[2][0]
    assert points[3][0] > points[4][0] > points[5][0]
    assert points[3][0] - points[2][0] > 1.0


def test_dotplot_expands_count_and_stacks_upwards() -> None:
    data = to_column_table(
        {
            "x": [0.2, 0.2, 0.5],
            "y": [0.0, 0.0, 0.0],
            "binwidth": [0.1, 0.1, 0.1],
            "count": [3.0, 0.0, 1.0],
            "group": [1.0, 1.0, 1.0],
        }
    )
    plot = ggplot(
        data, aes(x="x", y="y", binwidth="binwidth", count="count")
    ) + registry.geom_dotplot(stat="identity", fill="black")
    build = build_plot(plot)
    assert build.layers[0].data.nrows == 4  # 3 + 0 + 1
    circles = _kinds(_scene(plot), "circle")
    assert sum(node.bufs["circle"].shape[0] for node in circles) == 4
    ys = np.concatenate([np.asarray(node.bufs["circle"])[:, 1] for node in circles])
    # 同一 x 的三个点沿 y 向上堆叠（IR 的 y 向下，所以堆叠是递减）。
    assert len(np.unique(np.round(ys[:3], 6))) == 3


# ---------------------------------------------------------------------------
# 2D 族
# ---------------------------------------------------------------------------


def test_hex_draws_six_vertex_polygons() -> None:
    data = to_column_table(
        {
            "x": [0.3, 0.7],
            "y": [0.4, 0.6],
            "width": [0.2, 0.2],
            "height": [0.2, 0.2],
            "count": [1.0, 2.0],
        }
    )
    plot = ggplot(data, aes(x="x", y="y")) + registry.geom_hex(stat="identity", fill="#4C78A8")
    polygons = _kinds(_scene(plot), "polygon")
    # 固定 fill：两个 bin 合成一个多边形节点，每个 bin 6 个顶点。
    assert len(polygons) == 1
    assert np.asarray(polygons[0].bufs["points"]).shape[0] == 12


def test_bin2d_draws_one_rect_per_bin() -> None:
    data = to_column_table(
        {
            "x": [0.25, 0.75],
            "y": [0.3, 0.7],
            "width": [0.5, 0.5],
            "height": [0.4, 0.4],
            "count": [1.0, 2.0],
        }
    )
    plot = ggplot(data, aes(x="x", y="y")) + registry.geom_bin2d(stat="identity", fill="#4C78A8")
    scene = _scene(plot)
    rects = _kinds(scene, "rect")
    assert sum(node.bufs["rect"].shape[0] for node in rects) == 2


def test_contour_draws_one_line_per_group() -> None:
    data = to_column_table(
        {
            "x": [0.1, 0.4, 0.7, 0.1, 0.4, 0.7],
            "y": [0.2, 0.5, 0.2, 0.6, 0.9, 0.6],
            "level": [1.0, 1.0, 1.0, 2.0, 2.0, 2.0],
            "group": ["g1", "g1", "g1", "g2", "g2", "g2"],
        }
    )
    plot = ggplot(data, aes(x="x", y="y", group="group", colour="level")) + registry.geom_contour(
        stat="identity"
    )
    assert len(_kinds(_scene(plot), "polyline")) == 2


def test_contour_filled_draws_band_paths_with_evenodd_rule() -> None:
    data = to_column_table(
        {
            "x": [0.0, 1.0, 1.0, 0.0, 0.2, 0.3, 0.3, 0.2],
            "y": [0.0, 0.0, 1.0, 1.0, 0.2, 0.2, 0.3, 0.3],
            "level": [
                "(0, 1]",
                "(0, 1]",
                "(0, 1]",
                "(0, 1]",
                "(0, 1]",
                "(0, 1]",
                "(0, 1]",
                "(0, 1]",
            ],
            "group": ["b1"] * 8,
            "subgroup": ["s1"] * 4 + ["s2"] * 4,
        }
    )
    plot = ggplot(
        data, aes(x="x", y="y", fill="level", group="group", subgroup="subgroup")
    ) + registry.geom_contour_filled(stat="identity")
    paths = _kinds(_scene(plot), "path")
    assert len(paths) == 1
    assert paths[0].params["rule"].value == "evenodd"
    ids = np.asarray(paths[0].bufs["id"])
    assert len(set(ids.tolist())) == 2


# ---------------------------------------------------------------------------
# 点 / 线族的薄封装
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factory", "columns", "kind", "minimum"),
    [
        ("geom_jitter", {"x": [0.3, 0.6], "y": [0.4, 0.7]}, "points", 2),
        ("geom_count", {"x": [0.3, 0.6], "y": [0.4, 0.7], "n": [1.0, 3.0]}, "points", 2),
        ("geom_qq", {"x": [0.2, 0.8], "y": [0.3, 0.6]}, "points", 2),
        ("geom_qq_line", {"x": [0.2, 0.8], "y": [0.3, 0.6]}, "polyline", 1),
        ("geom_quantile", {"x": [0.2, 0.5, 0.8], "y": [0.3, 0.5, 0.6]}, "polyline", 1),
        ("geom_function", {"x": [0.2, 0.5, 0.8], "y": [0.3, 0.5, 0.6]}, "polyline", 1),
    ],
)
def test_thin_wrappers_draw_the_underlying_primitive(
    factory: str, columns: dict, kind: str, minimum: int
) -> None:
    data = to_column_table(columns)
    mapping = {"x": "x", "y": "y"}
    if "n" in columns:
        mapping["size"] = "n"
    plot = ggplot(data, aes(**mapping)) + getattr(registry, factory)(stat="identity")
    nodes = _kinds(_scene(plot), kind)
    total = sum(int(node.bufs["points"].shape[0]) for node in nodes if "points" in node.bufs)
    assert total >= minimum


# ---------------------------------------------------------------------------
# 默认 stat 的别名（SIL-765）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory", ["geom_bin_2d", "geom_hex"])
def test_default_stat_alias_resolves_to_the_registered_stat(factory: str) -> None:
    """`Geom$default_stat` 是 R 的别名（`bin2d` / `binhex`），要落到正名实现。

    M2-6 的 stat 只登记正名（`bin_2d` / `bin_hex`）；`compute_stat()` 走
    `STAT_ALIASES` 解析，否则 `geom_bin_2d()` / `geom_hex()` 的默认 stat 会报
    「尚未实现」。
    """
    data = to_column_table(
        {
            "x": [0.1, 0.4, 0.7, 0.2, 0.5, 0.8],
            "y": [0.2, 0.6, 0.3, 0.7, 0.4, 0.9],
        }
    )
    plot = ggplot(data, aes(x="x", y="y")) + getattr(registry, factory)()
    build = build_plot(plot)
    assert build.layers[0].data.nrows > 0
    assert {"count", "fill"}.issubset(set(build.layers[0].data.names))


# ---------------------------------------------------------------------------
# 图例 key
# ---------------------------------------------------------------------------


def test_every_new_geom_has_a_legend_key_template() -> None:
    missing = [name for name in NEW_GEOMS if name not in _GEOM_KEYS]
    assert not missing
