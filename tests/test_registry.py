"""组件注册表：一条注册表、两个入口、遍历顺序稳定、替换即生效。"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from ggcore import plot, registry
from ggcore.layer import Geom, Layer

EXPECTED = {
    "geom": ("point", "line", "path", "bar", "col", "area", "histogram", "boxplot", "smooth"),
    "stat": (
        "identity",
        "bin",
        "count",
        "boxplot",
        "smooth",
        "align",
        "qq",
        "qq_line",
        "ecdf",
        "ellipse",
        "quantile",
        "summary",
        "summary_bin",
        "sum",
        "unique",
        "density",
        "function",
        "connect",
        "manual",
        "spoke",
        "ydensity",
    ),
    "position": (
        "identity",
        "stack",
        "fill",
        "dodge",
        "dodge2",
        "jitter",
        "jitterdodge",
        "nudge",
    ),
    "scale": (
        "x_continuous",
        "y_continuous",
        "x_discrete",
        "y_discrete",
        "x_log10",
        "y_log10",
        "colour_continuous",
        "colour_gradient",
        "colour_discrete",
        "fill_continuous",
        "fill_gradient",
        "fill_discrete",
        "size_continuous",
        "shape_discrete",
        "alpha_continuous",
        "x_sqrt",
        "y_sqrt",
        "x_reverse",
        "y_reverse",
        "x_binned",
        "y_binned",
        "x_date",
        "y_date",
        "x_datetime",
        "y_datetime",
        "x_time",
        "y_time",
        "colour_binned",
        "colour_gradient2",
        "colour_gradientn",
        "colour_steps",
        "colour_steps2",
        "colour_stepsn",
        "colour_date",
        "colour_datetime",
        "colour_distiller",
        "colour_fermenter",
        "color_continuous",
        "color_binned",
        "color_gradient",
        "color_gradient2",
        "color_gradientn",
        "color_steps",
        "color_steps2",
        "color_stepsn",
        "color_date",
        "color_datetime",
        "color_distiller",
        "color_fermenter",
        "fill_binned",
        "fill_gradient2",
        "fill_gradientn",
        "fill_steps",
        "fill_steps2",
        "fill_stepsn",
        "fill_date",
        "fill_datetime",
        "fill_distiller",
        "fill_fermenter",
        "alpha",
        "alpha_binned",
        "alpha_date",
        "alpha_datetime",
        "size",
        "size_area",
        "size_binned",
        "size_binned_area",
        "size_date",
        "size_datetime",
        "radius",
        "linewidth",
        "linewidth_continuous",
        "linewidth_binned",
        "linewidth_date",
        "linewidth_datetime",
        "colour_brewer",
        "colour_grey",
        "colour_hue",
        "colour_ordinal",
        "colour_manual",
        "colour_identity",
        "colour_viridis_c",
        "colour_viridis_d",
        "colour_viridis_b",
        "color_brewer",
        "color_grey",
        "color_hue",
        "color_ordinal",
        "color_manual",
        "color_identity",
        "color_viridis_c",
        "color_viridis_d",
        "color_viridis_b",
        "fill_brewer",
        "fill_grey",
        "fill_hue",
        "fill_ordinal",
        "fill_manual",
        "fill_identity",
        "fill_viridis_c",
        "fill_viridis_d",
        "fill_viridis_b",
        "size_discrete",
        "size_ordinal",
        "size_manual",
        "size_identity",
        "alpha_discrete",
        "alpha_ordinal",
        "alpha_manual",
        "alpha_identity",
        "shape",
        "shape_ordinal",
        "shape_manual",
        "shape_identity",
        "shape_continuous",
        "shape_binned",
        "linetype",
        "linetype_discrete",
        "linetype_manual",
        "linetype_identity",
        "linetype_continuous",
        "linetype_binned",
        "linewidth_discrete",
        "linewidth_ordinal",
        "linewidth_manual",
        "linewidth_identity",
        "discrete_manual",
        "discrete_identity",
        "continuous_identity",
    ),
    "coord": (
        "cartesian",
        "fixed",
        "equal",
        "flip",
        "trans",
        "transform",
        "polar",
        "radial",
        "sf",
        "map",
        "quickmap",
    ),
    "facet": ("null", "wrap", "grid"),
    "guide": ("legend", "colourbar", "none"),
    "theme": ("grey", "bw", "minimal", "void"),
    "label": ("labs",),
}


def sparkle(**params) -> Layer:
    return Layer(geom=Geom(name="sparkle"), params=params)


def twinkle(**params) -> Layer:
    return Layer(geom=Geom(name="sparkle", required_aes=("x",)), params=params)


@pytest.fixture
def sparkle_registered():
    registry.register_geom("sparkle", sparkle)
    yield
    if "sparkle" in registry.registered("geom"):
        registry.unregister("geom", "sparkle")


# ---------------------------------------------------------------------------
# 默认登记
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(EXPECTED))
def test_default_names_are_registered_in_order(kind: str) -> None:
    assert registry.registered(kind) == EXPECTED[kind]


def test_theme_names_is_derived_from_the_registry() -> None:
    # 常量是注册表的快照，不是手写清单（SIL-671：手写的三元组漏了 `bw`）。
    assert registry.THEME_NAMES == registry.registered("theme")
    assert registry.THEME_NAMES == ("grey", "bw", "minimal", "void")


def test_theme_names_tracks_register_and_unregister() -> None:
    before = registry.THEME_NAMES
    registry.register_theme("wb", registry.theme_grey)
    try:
        assert registry.THEME_NAMES == (*before, "wb")
    finally:
        registry.unregister("theme", "wb")
    assert registry.THEME_NAMES == before


def test_kind_order_is_fixed() -> None:
    assert registry.KINDS == (
        "geom",
        "stat",
        "position",
        "scale",
        "coord",
        "facet",
        "guide",
        "theme",
        "label",
    )


def test_iteration_is_stable_across_calls() -> None:
    first = {kind: registry.registered(kind) for kind in registry.KINDS}
    second = {kind: registry.registered(kind) for kind in registry.KINDS}
    assert first == second
    # 每个种类都是 tuple（有序），不是 set。
    assert all(isinstance(names, tuple) for names in first.values())


def test_geom_specs_carry_the_ggplot2_contract() -> None:
    assert registry.GEOM_SPECS["point"].required_aes == ("x", "y")
    # bar / histogram 的 y 由 stat_count / stat_bin 产出，是 stat 之后的必需列。
    assert registry.GEOM_SPECS["bar"].required_aes == ("x", "y")
    assert registry.GEOM_SPECS["histogram"].required_aes == ("x", "y")
    assert registry.GEOM_SPECS["histogram"].stat == "bin"
    assert registry.GEOM_SPECS["bar"].stat == "count"
    assert registry.GEOM_SPECS["bar"].default_aes["width"] == 0.9
    boxplot = registry.GEOM_SPECS["boxplot"]
    assert boxplot.required_aes == (
        "x|y",
        "lower|xlower",
        "upper|xupper",
        "middle|xmiddle",
        "ymin|xmin",
        "ymax|xmax",
    )
    assert boxplot.default_aes["weight"] == 1
    assert boxplot.default_aes["width"] == 0.9
    assert boxplot.default_aes["colour"] == "grey20"


def test_required_aes_groups_expands_the_upstream_alternatives() -> None:
    assert registry.required_aes_groups(("x", "y")) == (("x",), ("y",))
    groups = registry.required_aes_groups(registry.GEOM_SPECS["boxplot"].required_aes)
    assert groups == (
        ("x", "y"),
        ("lower", "xlower"),
        ("upper", "xupper"),
        ("middle", "xmiddle"),
        ("ymin", "xmin"),
        ("ymax", "xmax"),
    )


def test_area_uses_stat_align_without_a_default_outline() -> None:
    area = registry.GEOM_SPECS["area"]
    assert area.stat == "align"
    assert area.default_aes["colour"] is None
    assert registry.STAT_GEOMS["align"] == "area"

    layer = plot.stat_align()
    assert layer.stat.name == "align"
    assert layer.geom.name == "area"
    assert plot.geom_area().stat.name == "align"
    assert plot.geom_area().geom.default_aes["colour"] is None


# ---------------------------------------------------------------------------
# 两个入口
# ---------------------------------------------------------------------------


def test_every_registered_name_has_both_entry_points() -> None:
    for kind in registry.KINDS:
        for name in registry.registered(kind):
            entry = registry.entry_name(kind, name)
            assert entry in registry.__all__, entry
            assert callable(getattr(registry, entry)), entry
            assert callable(getattr(plot, entry)), entry
            # 模块级入口是同一个函数对象：没有第二套实现。
            assert getattr(plot, entry) is getattr(registry, entry), entry
            # ggplot 上也有同名方法。
            assert callable(getattr(plot.ggplot, entry)), entry


def test_module_entry_point_and_method_construct_the_same_component() -> None:
    p = plot.ggplot()
    # 直接比结构：`+` 与方法的产物逐字段相同。
    via_plus = p + registry.geom_point(size=2)
    via_method = p.geom_point(size=2)
    assert via_plus.layers == via_method.layers
    assert p.layers == []
    assert registry.scale_x_log10() == p.scale_x_log10().scales["x"]
    assert registry.theme_grey() == p.theme_grey().theme


def test_labels_entry_point_is_labs_without_a_prefix() -> None:
    assert registry.entry_name("label", "labs") == "labs"
    assert plot.labs(title="t").values == {"title": "t"}
    assert (plot.ggplot() + plot.labs(title="t")).labels == plot.ggplot().labs(title="t").labels


# ---------------------------------------------------------------------------
# 报错
# ---------------------------------------------------------------------------


def test_constructing_an_unknown_name_lists_what_exists() -> None:
    with pytest.raises(LookupError, match="sparkle") as excinfo:
        registry.construct("geom", "sparkle")
    assert "point" in str(excinfo.value)


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="annotation"):
        registry.registered("annotation")
    with pytest.raises(ValueError, match="annotation"):
        registry.register("annotation", "text", sparkle)


def test_register_rejects_a_name_that_is_not_an_identifier() -> None:
    with pytest.raises(ValueError, match="标识符"):
        registry.register_geom("not-a-name", sparkle)


def test_register_rejects_a_non_callable() -> None:
    with pytest.raises(TypeError):
        registry.register_geom("nope", 42)


def test_unregistering_an_unknown_name_raises() -> None:
    with pytest.raises(LookupError, match="sparkle"):
        registry.unregister("geom", "sparkle")


# ---------------------------------------------------------------------------
# 同源：改注册表项，别名跟着变
# ---------------------------------------------------------------------------


def test_alias_follows_the_registry_without_rebinding(sparkle_registered) -> None:
    entry = registry.entry_name("geom", "sparkle")
    p = plot.ggplot()

    # 新登记的名字立刻同时出现在两个入口上。
    assert callable(getattr(registry, entry))
    assert callable(getattr(plot, entry))
    assert callable(getattr(plot.ggplot, entry))

    assert getattr(p, entry)(shiny=True).layers[0].geom.name == "sparkle"
    assert getattr(registry, entry)(shiny=True).params["shiny"] is True

    # 已经绑定下来的方法也走注册表（不是把构造器闭包进去）。
    bound_method = getattr(p, entry)

    # 换掉注册项：两个入口（包括已绑定的方法）都跟着变。
    registry.register_geom("sparkle", twinkle)
    assert getattr(registry, entry)().geom.required_aes == ("x",)
    assert getattr(p, entry)().layers[0].geom.required_aes == ("x",)
    assert bound_method().layers[0].geom.required_aes == ("x",)
    assert getattr(plot, entry) is getattr(registry, entry)


def test_unregister_cleans_up_both_entry_points(sparkle_registered) -> None:
    assert hasattr(plot.ggplot, "geom_sparkle")
    registry.unregister("geom", "sparkle")
    assert "sparkle" not in registry.registered("geom")
    assert not hasattr(registry, "geom_sparkle")
    assert not hasattr(plot, "geom_sparkle")
    assert not hasattr(plot.ggplot, "geom_sparkle")


def test_registry_all_tracks_register_and_unregister(sparkle_registered) -> None:
    # 新登记的名字进 __all__，且 __all__ 里每个名字都真的存在。
    assert "geom_sparkle" in registry.__all__
    assert all(hasattr(registry, name) for name in registry.__all__)

    registry.unregister("geom", "sparkle")
    assert "geom_sparkle" not in registry.__all__
    assert all(hasattr(registry, name) for name in registry.__all__)

    # 关键回归：unregister 之后 `from ggcore.registry import *` 不能再 AttributeError。
    namespace: dict[str, object] = {}
    exec("from ggcore.registry import *", namespace)
    assert "geom_point" in namespace
    assert "geom_sparkle" not in namespace


def test_reregistering_keeps_the_original_position(sparkle_registered) -> None:
    before = registry.registered("geom")
    assert before[-1] == "sparkle"
    registry.register_geom("sparkle", twinkle)
    after = registry.registered("geom")
    assert after == before
    assert after[-1] == "sparkle"


# ---------------------------------------------------------------------------
# 占位对象的形状
# ---------------------------------------------------------------------------


def test_scale_placeholder_carries_its_aesthetic_and_params() -> None:
    scale = plot.scale_x_log10()
    assert scale.name == "x_log10"
    assert scale.aesthetic == "x"
    assert scale.key == "x"
    assert scale.params["trans"] == "log10"


def test_theme_coord_facet_guide_placeholders_carry_params() -> None:
    assert plot.theme_grey().complete is True
    assert plot.theme_void().name == "void"
    assert plot.coord_cartesian(ylim=(0, 1)).params["ylim"] == (0, 1)
    assert plot.facet_wrap(("class",)).params["facets"] == ("class",)
    guide = plot.guide_colourbar(aesthetic="fill")
    assert guide.name == "colourbar"
    assert guide.key == "fill"


def test_geom_specs_carry_the_default_position() -> None:
    assert registry.GEOM_SPECS["bar"].position == "stack"
    assert registry.GEOM_SPECS["col"].position == "stack"
    assert registry.GEOM_SPECS["histogram"].position == "stack"
    assert registry.GEOM_SPECS["area"].position == "stack"
    assert registry.GEOM_SPECS["boxplot"].position == "dodge2"
    assert registry.GEOM_SPECS["point"].position == "identity"
    assert registry.GEOM_SPECS["smooth"].position == "identity"


def test_layer_factories_take_position_from_the_spec_unless_overridden() -> None:
    assert plot.geom_bar().position.name == "stack"
    assert plot.geom_boxplot().position.name == "dodge2"
    assert plot.geom_point().position.name == "identity"
    assert plot.stat_count().position.name == "stack"
    assert plot.stat_align().position.name == "stack"
    # 显式传参仍然覆盖 spec 的默认值。
    assert plot.geom_bar(position="dodge").position.name == "dodge"


def test_smooth_carries_a_weight_default() -> None:
    assert registry.GEOM_SPECS["smooth"].default_aes["weight"] == 1


def test_params_route_to_layer_or_stat_only() -> None:
    # geom 的参数只进 Layer.params，不会偷偷落到 stat 上。
    geom_layer = plot.geom_histogram(bins=30)
    assert geom_layer.params["bins"] == 30
    assert dict(geom_layer.stat.params) == {}

    # stat 的参数只进 Stat.params。
    stat_layer = plot.stat_count(bins=10)
    assert dict(stat_layer.params) == {}
    assert stat_layer.stat.params["bins"] == 10


# ---------------------------------------------------------------------------
# M2-9 扩展：组件类、内置名字保护、default_aes 继承
# ---------------------------------------------------------------------------


class ParentGeom(Geom):
    """用来验证 `default_aes` 合并语义的父类。"""

    name = "parent"
    required_aes = ("x", "y")
    default_aes: ClassVar[dict[str, Any]] = {"colour": "black", "linewidth": 0.5}


class ChildGeom(ParentGeom):
    name = "child"
    default_aes: ClassVar[dict[str, Any]] = {"linewidth": 1.5, "alpha": 0.5}

    def draw(self, build, panel, coord, theme, metrics):
        del build, panel, coord, theme, metrics
        raise AssertionError("contract-only test")


class PointOverride(Geom):
    """与内置 `point` 同名，用来验证 `allow_override=True` 的恢复路径。"""

    name = "point"
    required_aes = ("x", "y")
    default_aes: ClassVar[dict[str, Any]] = {"colour": "red"}


def test_default_aes_is_merged_without_mutating_the_parent() -> None:
    child = ChildGeom()
    assert child.required_aes == ("x", "y")
    assert dict(child.default_aes) == {
        "colour": "black",
        "linewidth": 1.5,
        "alpha": 0.5,
    }
    assert dict(ParentGeom.default_aes) == {"colour": "black", "linewidth": 0.5}


def test_registering_a_component_class_gives_both_entry_points() -> None:
    registry.register_geom("child", ChildGeom)
    try:
        entry = registry.entry_name("geom", "child")
        assert callable(getattr(registry, entry)) and callable(getattr(plot, entry))
        layer = registry.geom_child(colour="red")
        assert isinstance(layer, Layer)
        assert isinstance(layer.geom, ChildGeom)
        assert layer.geom.name == "child"
        assert dict(layer.geom.default_aes)["alpha"] == 0.5
        assert layer.params["colour"] == "red"
        assert plot.ggplot().geom_child().layers[0].geom.name == "child"
    finally:
        registry.unregister("geom", "child")
    assert "child" not in registry.registered("geom")


def test_third_party_registration_cannot_shadow_a_builtin_name() -> None:
    with pytest.raises(ValueError, match="内置名字"):
        registry.register_geom("point", PointOverride)

    original = registry.GEOM_SPECS["point"]
    registry.register_geom("point", PointOverride, allow_override=True)
    try:
        assert dict(registry.geom_point().geom.default_aes) == {"colour": "red"}
    finally:
        registry.unregister("geom", "point")

    # unregister 恢复内置原件，而不是把 point 删掉。
    restored = registry.geom_point().geom
    assert restored.name == "point"
    assert restored.required_aes == original.required_aes
    assert "point" in registry.registered("geom")


def test_unregistering_an_unshadowed_builtin_is_rejected() -> None:
    with pytest.raises(ValueError, match="内置组件"):
        registry.unregister("geom", "point")
    assert "point" in registry.registered("geom")


def test_a_component_class_name_must_match_its_registration() -> None:
    with pytest.raises(ValueError, match="不一致"):
        registry.register_geom("other", ChildGeom)
    assert "other" not in registry.registered("geom")
