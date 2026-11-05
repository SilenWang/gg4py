"""`annotate()` / `annotation_borders()` 的契约（SIL-825，M3-1）。

三组断言：

1. **图层形状**：`stat` / `position` 是 identity、`inherit_aes = False`、
   `show_legend = False`，位置美学进**数据 + 映射**、其余参数进 `params`；
2. **长度规则**：标量广播到 n；去掉长度 1 之后仍有多个长度 → 报错（上游的
   `Unequal parameter lengths`）；
3. **标度与标题**：位置美学参与标度训练（撑开面板范围）；轴标题只认 plot 级
   mapping，`annotate()` 自己的映射不会变成轴标题。

快照对拍不在这里：`upstream-annotate-utah` / `upstream-annotate-segment-transform`
走 `pixi run cases:matrix`（参考图是上游 vdiffr 快照）。
"""

from __future__ import annotations

import pytest

from ggcore.annotations import annotate, annotation_borders, borders
from ggcore.build import build_plot
from ggcore.geom.scene import _axis_title_text
from ggcore.layer import Layer
from ggcore.map_data import STATE_UTAH, map_frame
from ggcore.plot import aes, geom_point, ggplot
from ggio.frame import to_column_table


def test_annotate_layer_contract() -> None:
    layer = annotate("segment", x=1, y=10, xend=10, yend=1, colour="red")
    assert isinstance(layer, Layer)
    assert layer.stat.name == "identity"
    assert layer.position.name == "identity"
    assert layer.inherit_aes is False
    assert layer.show_legend is False
    # 位置美学进数据 + 映射；colour 是设值（params），不进映射、不进图例。
    assert layer.data is not None
    assert set(layer.data.names) == {"x", "y", "xend", "yend"}
    assert dict(layer.mapping) == {"x": "x", "y": "y", "xend": "xend", "yend": "yend"}
    assert layer.params["colour"] == "red"
    assert "colour" not in layer.mapping


def test_annotate_broadcasts_scalars() -> None:
    layer = annotate("text", x=[1, 2, 3], y=5, label="a")
    assert layer.data is not None
    assert layer.data.nrows == 3
    assert list(layer.data.column("y").values) == [5.0, 5.0, 5.0]
    # `label` 不在位置美学里：它是设值（params），由 finish() 阶段落到数据列。
    assert layer.params["label"] == "a"


def test_annotate_rejects_unequal_lengths() -> None:
    with pytest.raises(ValueError, match="长度不一致"):
        annotate("segment", x=[1, 2], y=[1, 2, 3])


def test_annotate_requires_a_position_aesthetic() -> None:
    with pytest.raises(ValueError, match="位置美学"):
        annotate("text", label="x")


def test_annotate_warns_for_reference_line_geoms() -> None:
    with pytest.warns(UserWarning, match="不支持"):
        annotate("hline", y=1)


def test_annotate_trains_the_position_scales() -> None:
    """位置美学参与标度训练：annotate 的点把面板范围撑到 0..10。"""
    plot = ggplot() + annotate("point", x=[0.0, 10.0], y=[0.0, 10.0])
    build = build_plot(plot)
    ranges = build.panels[0].panel_params.continuous_ranges
    low, high = ranges["x"]
    # 默认 5% expand：0..10 → -0.5..10.5
    assert low == pytest.approx(-0.5)
    assert high == pytest.approx(10.5)


def test_layer_mapping_does_not_become_axis_title() -> None:
    """`annotate()` 的映射是 `aes_all()` 的 "unlabelled"，不能变成轴标题（SIL-825）。"""
    plot = ggplot() + annotate("segment", x=1, y=2, xend=3, yend=4)
    assert plot.layers[0].unlabelled is True
    build = build_plot(plot)
    assert _axis_title_text(build, "x") is None
    assert _axis_title_text(build, "y") is None


def test_plot_mapping_still_supplies_axis_titles() -> None:
    """普通图层继承 plot 级 mapping：轴标题仍从映射来（unlabelled 只排 annotate）。"""
    table = to_column_table({"wt": [1.0], "mpg": [2.0]})
    build = build_plot(ggplot(table, mapping=aes(x="wt", y="mpg")) + geom_point())
    assert _axis_title_text(build, "x") == "wt"
    assert _axis_title_text(build, "y") == "mpg"


def test_annotation_borders_utah() -> None:
    layer = annotation_borders("state", "utah", fill=None, colour="grey50")
    assert layer.geom.name == "polygon"
    assert layer.data is not None and layer.data.nrows == 59
    assert set(layer.params["group"]) == {1.0}
    xs = layer.data.column("x").values
    ys = layer.data.column("y").values
    assert (float(min(xs)), float(max(xs))) == pytest.approx((-114.047284, -109.039589))
    assert (float(min(ys)), float(max(ys))) == pytest.approx((36.995881, 42.003501))


def test_annotation_borders_unknown_region_is_loud() -> None:
    with pytest.raises(NotImplementedError, match="只内置"):
        annotation_borders("world", ".")


def test_annotation_borders_bbox_filter() -> None:
    frame = map_frame("state", "utah", ylim=(41.9, 43.0))
    assert frame["y"] and all(value >= 41.9 for value in frame["y"])
    assert len(frame["x"]) == len(frame["y"]) == len(frame["group"])


def test_borders_is_deprecated_alias() -> None:
    with pytest.warns(DeprecationWarning):
        layer = borders("state", "utah")
    assert layer.data is not None and layer.data.nrows == len(STATE_UTAH["x"])
