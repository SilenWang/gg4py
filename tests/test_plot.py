"""M1-1 语法骨架：`ggplot` 对象、`+` 组合、克隆语义、方法链别名。

等价性 / 克隆 / 报错三类断言都在这里；`+` 与方法的比较一律走结构快照
（:func:`structure`），不拿 `repr` 字符串当判据。
"""

from __future__ import annotations

import inspect

import pytest

from ggcore import plot, registry
from ggcore.aes import Aes, AfterStat, aes, after_stat
from ggcore.components import Theme
from ggcore.layer import Geom, Layer, Position
from ggcore.theme import element_line, element_text, rel, theme

DATA = {"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]}


def structure(p: plot.ggplot) -> tuple:
    """一张图的结构快照：字段逐个摊平，容器按顺序取元组（不碰 repr）。"""
    return (
        p.mapping,
        tuple(p.layers),
        tuple(p.scales.items()),
        tuple(p.guides.items()),
        p.theme,
        p.coordinates,
        p.facet,
        tuple(p.labels.items()),
        p.position,
    )


def base_plot(**kwargs) -> plot.ggplot:
    return plot.ggplot(DATA, aes(x="x", y="y"), **kwargs)


# ---------------------------------------------------------------------------
# ggplot 对象本身
# ---------------------------------------------------------------------------


def test_ggplot_defaults_match_the_ggplot2_object() -> None:
    p = base_plot()
    assert p.data is DATA
    assert p.mapping == aes(x="x", y="y")
    assert p.layers == []
    assert p.scales == {}
    assert p.guides == {}
    assert p.theme.name == "grey"
    assert p.theme.complete is True
    assert p.coordinates.name == "cartesian"
    assert p.facet.name == "null"
    assert p.labels == {}
    assert p.position is None


def test_ggplot_normalises_mapping_from_a_plain_mapping() -> None:
    p = plot.ggplot(DATA, {"x": "x", "y": "y * 2"})
    assert isinstance(p.mapping, Aes)
    assert p.mapping["y"] == "y * 2"
    assert dict(p.mapping) == {"x": "x", "y": "y * 2"}


def test_ggplot_rejects_a_mapping_that_is_not_a_mapping() -> None:
    with pytest.raises(TypeError, match="mapping"):
        plot.ggplot(DATA, 42)


def test_ggplot_rejects_unknown_kwargs() -> None:
    with pytest.raises(TypeError, match="sizee"):
        plot.ggplot(DATA, sizee=3)
    # 报错里要列出可用字段，方便下一步直接改对。
    with pytest.raises(TypeError, match="coordinates"):
        plot.ggplot(DATA, nope=1)


def test_ggplot_accepts_every_documented_field() -> None:
    p = plot.ggplot(
        DATA,
        aes(x="x"),
        layers=[plot.geom_point()],
        scales={"x": plot.scale_x_log10()},
        guides={"colour": plot.guide_legend(aesthetic="colour")},
        theme=plot.theme_minimal(),
        coordinates=plot.coord_fixed(),
        facet=plot.facet_wrap(("class",)),
        labels={"title": "t"},
        position=Position("dodge"),
    )
    assert len(p.layers) == 1
    assert p.scales["x"].name == "x_log10"
    assert p.guides["colour"].name == "legend"
    assert p.theme.name == "minimal"
    assert p.coordinates.name == "fixed"
    assert p.facet.name == "wrap"
    assert p.labels == {"title": "t"}
    assert p.position.name == "dodge"


# ---------------------------------------------------------------------------
# 克隆语义
# ---------------------------------------------------------------------------


def test_add_returns_a_new_plot_and_leaves_the_old_one_untouched() -> None:
    p = base_plot()
    q = p + plot.geom_point()

    assert q is not p
    assert len(p.layers) == 0
    assert len(q.layers) == 1
    # 不可变值共享：data 引用与 Aes 实例都不复制。
    assert q.data is p.data
    assert q.mapping is p.mapping


def test_add_copies_every_mutable_container() -> None:
    p = base_plot()
    q = p + plot.geom_point() + plot.scale_x_log10() + plot.labs(title="t")
    q.layers.append(plot.geom_line())
    q.scales["y"] = plot.scale_y_log10()
    q.labels["x"] = "displ"

    assert p.layers == []
    assert p.scales == {}
    assert p.labels == {}


def test_clone_isolates_containers_but_shares_immutable_values() -> None:
    p = base_plot() + plot.geom_point()
    q = p.clone()
    q.layers.clear()
    assert len(p.layers) == 1
    assert q.data is p.data
    assert q.mapping is p.mapping
    assert q.theme is p.theme
    assert q.coordinates is p.coordinates


def test_chained_adds_never_touch_the_original() -> None:
    p = base_plot()
    first = p + plot.geom_point()
    second = first + plot.geom_line()
    assert len(p.layers) == 0
    assert len(first.layers) == 1
    assert len(second.layers) == 2
    assert second.layers[0] is first.layers[0]


def test_adding_none_is_a_noop_but_still_returns_a_new_plot() -> None:
    p = base_plot()
    q = p + None
    assert q is not p
    assert structure(q) == structure(p)


# ---------------------------------------------------------------------------
# `+` 与方法的等价（三组，结构比较）
# ---------------------------------------------------------------------------


CHAIN_GROUPS = [
    (("geom_point", {"size": 3}), ("theme_grey", {})),
    (("scale_x_log10", {}), ("coord_fixed", {})),
    (("facet_wrap", {"facets": ("class",)}), ("labs", {"title": "t", "x": "displ"})),
]


@pytest.mark.parametrize(
    ("first", "second"),
    CHAIN_GROUPS,
    ids=["layer+theme", "scale+coord", "facet+labels"],
)
def test_plus_and_method_chain_are_equivalent(
    first: tuple[str, dict], second: tuple[str, dict]
) -> None:
    first_entry, first_kwargs = first
    second_entry, second_kwargs = second
    p = base_plot()

    via_plus = p + getattr(plot, first_entry)(**first_kwargs)
    via_plus = via_plus + getattr(plot, second_entry)(**second_kwargs)

    via_method = getattr(p, first_entry)(**first_kwargs)
    via_method = getattr(via_method, second_entry)(**second_kwargs)

    assert structure(via_plus) == structure(via_method)
    # 结构相等之外，确认每一步都还在 `ggplot` 上（别名返回新对象）。
    assert isinstance(via_method, plot.ggplot)
    assert via_method is not p


def test_method_alias_is_the_same_registry_entry() -> None:
    # 模块级函数来自同一份注册表（同一函数对象），方法调用时按名字回查。
    assert plot.geom_point is registry.geom_point
    assert plot.scale_x_log10 is registry.scale_x_log10
    assert plot.theme_grey is registry.theme_grey
    assert plot.labs is registry.labs


# ---------------------------------------------------------------------------
# 组件分派
# ---------------------------------------------------------------------------


def test_each_component_kind_lands_in_its_own_field() -> None:
    p = (
        base_plot()
        + plot.geom_point()
        + plot.scale_x_log10()
        + plot.theme_grey()
        + plot.coord_fixed()
        + plot.facet_wrap(("class",))
        + plot.guide_legend(aesthetic="colour")
        + plot.labs(title="t")
    )
    assert [layer.geom.name for layer in p.layers] == ["point"]
    assert list(p.scales) == ["x"]
    assert p.theme.name == "grey"
    assert p.coordinates.name == "fixed"
    assert p.facet.name == "wrap"
    assert list(p.guides) == ["colour"]
    assert p.labels == {"title": "t"}


def test_gg_add_is_the_implementation_behind_plus() -> None:
    p = base_plot()
    layer = plot.geom_point()
    assert structure(plot.gg_add(p, layer)) == structure(p + layer)


def test_scales_replace_by_aesthetic() -> None:
    p = base_plot() + plot.scale_x_continuous() + plot.scale_x_log10()
    assert list(p.scales) == ["x"]
    assert p.scales["x"].name == "x_log10"


def test_labels_merge_instead_of_replacing() -> None:
    p = base_plot() + plot.labs(title="t") + plot.labs(x="displ")
    assert p.labels == {"title": "t", "x": "displ"}


def test_complete_theme_replaces_and_partial_theme_merges() -> None:
    p = base_plot() + plot.theme_grey() + plot.theme_minimal()
    assert p.theme.name == "minimal"

    partial = theme(**{"axis.text": element_text(colour="red")})
    q = p + partial
    assert q.theme.name == "minimal"
    assert q.theme.elements["axis.text"].colour == "red"
    # 只覆盖 colour，size 仍从 minimal 的 axis.text 继承（rel(0.8) 留到解析时）。
    assert q.theme.elements["axis.text"].size == rel(0.8)
    assert "panel.grid" in q.theme.elements

    r = q + theme(**{"axis.line": element_line(colour="blue")})
    assert r.theme.elements["axis.line"].colour == "blue"
    assert r.theme.elements["axis.text"].colour == "red"
    # 原始对象不受影响（p / q 的 theme 元素没被就地改）。
    assert q.theme.elements["axis.text"].colour == "red"
    assert q.theme.elements["axis.line"].__class__.__name__ == "ElementBlank"


# ---------------------------------------------------------------------------
# 报错
# ---------------------------------------------------------------------------


def test_unknown_component_type_is_rejected() -> None:
    p = base_plot()
    with pytest.raises(TypeError, match="object"):
        p + object()
    with pytest.raises(TypeError, match="int"):
        p + 42


def test_gg_add_rejects_a_non_plot_first_argument() -> None:
    with pytest.raises(TypeError, match="int"):
        plot.gg_add(42, plot.geom_point())


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


def test_repr_summarises_layers_rows_columns_and_mapping_keys() -> None:
    p = plot.ggplot({"x": [1, 2, 3], "y": [4, 5, 6]}, aes(x="x", y="y")) + plot.geom_point()
    assert repr(p) == "<ggplot: data=3×2, layers=1, mapping=[x, y]>"


def test_repr_handles_no_data_and_empty_mapping() -> None:
    assert repr(plot.ggplot()) == "<ggplot: data=None, layers=0, mapping=[]>"


def test_repr_reads_dataframe_like_shapes() -> None:
    class Frame:
        shape = (4, 7)

    class Table:
        nrows = 5

        def columns(self) -> list[str]:
            return ["a", "b", "c"]

    assert "data=4×7" in repr(plot.ggplot(Frame()))
    assert "data=5×3" in repr(plot.ggplot(Table()))


# ---------------------------------------------------------------------------
# aes / layer 的构造壳
# ---------------------------------------------------------------------------


def test_aes_keeps_raw_expressions_and_is_immutable() -> None:
    mapping = aes(x="mpg / cyl", colour="class")
    assert mapping["x"] == "mpg / cyl"
    with pytest.raises(TypeError):
        mapping["x"] = "disp"  # type: ignore[index]


def test_after_stat_only_marks_the_expression() -> None:
    marker = after_stat("count")
    assert isinstance(marker, AfterStat)
    assert marker.expr == "count"
    assert aes(y=marker)["y"] == marker


def test_geom_constructors_return_layers_and_draw_through_the_registry() -> None:
    layer = plot.geom_point(size=3)
    assert isinstance(layer, Layer)
    assert isinstance(layer.geom, Geom)
    assert layer.geom.name == "point"
    assert layer.geom.required_aes == ("x", "y")
    assert layer.params["size"] == 3
    assert layer.stat.name == "identity"
    # M1-7 起 draw() 是真绘制：按名字查 ggcore.geom 的实现，不再是 NotImplementedError。
    from ggcore.geom import renderer_for

    assert renderer_for(layer.geom.name) is renderer_for("point")
    signature = inspect.signature(layer.geom.draw)
    assert list(signature.parameters) == ["build", "panel", "coord", "theme", "metrics"]
    with pytest.raises(TypeError):  # 缺参数是 TypeError，不是“未实现”
        layer.geom.draw()


def test_geom_accepts_an_explicit_stat_and_position() -> None:
    layer = plot.geom_bar(stat="identity", position="dodge")
    assert layer.stat.name == "identity"
    assert layer.position.name == "dodge"
    # 默认值来自 geom 的契约：geom_bar 用 stat_count。
    assert plot.geom_bar().stat.name == "count"


def test_stat_constructors_are_layer_shortcuts() -> None:
    layer = plot.stat_count(bins=10)
    assert isinstance(layer, Layer)
    assert layer.stat.name == "count"
    assert layer.stat.params["bins"] == 10
    assert layer.geom.name == "bar"


def test_unknown_component_type_in_layers_helpers_raises() -> None:
    with pytest.raises(TypeError, match="stat"):
        plot.geom_point(stat=42)
    with pytest.raises(TypeError, match="position"):
        plot.geom_point(position=42)


# ---------------------------------------------------------------------------
# 递归只读：任意层级都改不动原图
# ---------------------------------------------------------------------------


def test_nested_label_values_are_frozen_all_the_way_down() -> None:
    p = plot.ggplot({"x": [1]}, aes(x="x")) + plot.labs(meta={"a": 1})
    q = p + plot.geom_point()

    with pytest.raises(TypeError):
        q.labels["meta"]["a"] = 2
    assert p.labels == {"meta": {"a": 1}}
    assert dict(q.labels["meta"]) == {"a": 1}


def test_component_params_are_recursively_frozen() -> None:
    theme = Theme(
        elements={"axis.text": {"colour": "red"}, "axis.ticks": ["a"]},
        complete=False,
    )
    with pytest.raises(TypeError):
        theme.elements["axis.text"]["colour"] = "blue"
    assert isinstance(theme.elements["axis.ticks"], tuple)

    scale = plot.scale_x_log10(breaks=[1, 10])
    with pytest.raises(TypeError):
        scale.params["breaks"][0] = 2
    assert scale.params["breaks"] == (1, 10)

    layer = plot.geom_point(limits={"x": [0, 1]})
    with pytest.raises(TypeError):
        layer.params["limits"]["x"][0] = 5
    assert layer.params["limits"]["x"] == (0, 1)
    with pytest.raises(TypeError):
        layer.geom.default_aes["colour"] = "red"


def test_aes_nested_values_are_frozen() -> None:
    mapping = aes(x=["a", "b"], meta={"k": "v"})
    with pytest.raises(TypeError):
        mapping["x"][0] = "c"
    with pytest.raises(TypeError):
        mapping["meta"]["k"] = "w"
    assert mapping["x"] == ("a", "b")
