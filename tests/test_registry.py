"""组件注册表：一条注册表、两个入口、遍历顺序稳定、替换即生效。"""

from __future__ import annotations

import pytest

from ggcore import plot, registry
from ggcore.layer import Geom, Layer

EXPECTED = {
    "geom": ("point", "line", "path", "bar", "col", "area", "histogram", "boxplot", "smooth"),
    "stat": ("identity", "bin", "count", "boxplot", "smooth"),
    "scale": (
        "x_continuous",
        "y_continuous",
        "x_discrete",
        "y_discrete",
        "x_log10",
        "y_log10",
        "colour_continuous",
        "colour_discrete",
        "fill_continuous",
        "fill_discrete",
        "size_continuous",
        "shape_discrete",
        "alpha_continuous",
    ),
    "coord": ("cartesian", "fixed"),
    "facet": ("null", "wrap", "grid"),
    "guide": ("legend", "colourbar", "none"),
    "theme": ("grey", "minimal", "void"),
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


def test_kind_order_is_fixed() -> None:
    assert registry.KINDS == ("geom", "stat", "scale", "coord", "facet", "guide", "theme", "label")


def test_iteration_is_stable_across_calls() -> None:
    first = {kind: registry.registered(kind) for kind in registry.KINDS}
    second = {kind: registry.registered(kind) for kind in registry.KINDS}
    assert first == second
    # 每个种类都是 tuple（有序），不是 set。
    assert all(isinstance(names, tuple) for names in first.values())


def test_geom_specs_carry_the_ggplot2_contract() -> None:
    assert registry.GEOM_SPECS["point"].required_aes == ("x", "y")
    assert registry.GEOM_SPECS["histogram"].required_aes == ("x",)
    assert registry.GEOM_SPECS["histogram"].stat == "bin"
    assert registry.GEOM_SPECS["bar"].stat == "count"
    assert registry.GEOM_SPECS["boxplot"].required_aes == ("x", "lower", "upper", "middle")


# ---------------------------------------------------------------------------
# 两个入口
# ---------------------------------------------------------------------------


def test_every_registered_name_has_both_entry_points() -> None:
    for kind in registry.KINDS:
        for name in registry.registered(kind):
            entry = registry.entry_name(kind, name)
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
