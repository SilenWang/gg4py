"""标度导出表：名字 → 美学 / 实现族 / 构造默认值。

M2-4 A 段把 v4.0.3 NAMESPACE 里连续侧的全部 `scale_*` 导出一次性登记，做法不是
逐个写函数，而是一张声明表：

    ScaleEntry("x_log10", "x", "position", {"trans": "log10"})

:func:`ggcore.registry._scale_factory` 用这张表生成公开入口（`scale_x_log10()` /
`p.scale_x_log10()`），:func:`ggcore.scales.scale_from_component` 用 `family`
选实现类、用 `defaults` 补构造参数（直接 `Scale(name, aesthetic, {})` 的路径也
走这里，所以表是唯一的默认值来源）。

`scale_colour_*` / `scale_color_*` / `scale_fill_*` 是同一实现的三个名字（上游
`scale_color_*` 只是 `scale_colour_*` 的别名）；这里显式列全，`api:coverage`
按 NAMESPACE 逐个对名字。

本模块不 import 任何 ggcore 模块（注册表与 scales 都 import 它），避免循环。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

__all__ = ["SCALE_DEFAULTS", "SCALE_ENTRIES", "SCALE_FAMILIES", "SCALE_SPECS", "ScaleEntry"]


@dataclass(frozen=True, slots=True)
class ScaleEntry:
    """一个公开的 `scale_*` 导出。"""

    #: 注册名（去掉 `scale_` 前缀），例如 `x_log10` / `colour_steps2`。
    name: str
    #: 作用的美学；`colour` / `fill` / `alpha` / `size` / `linewidth` / `x` / `y`。
    aesthetic: str
    #: 实现族（见 `scales._FAMILY_BUILDERS`）。
    family: str
    #: 构造默认值（与用户参数合并，用户优先）。
    defaults: Mapping[str, Any]


def _entry(name: str, aesthetic: str, family: str, **defaults: Any) -> ScaleEntry:
    return ScaleEntry(name, aesthetic, family, MappingProxyType(defaults))


def _entries() -> tuple[ScaleEntry, ...]:
    # --- M1-4 的 15 个名字（顺序保持不变：注册表的遍历顺序是既有契约） -----
    base = (
        _entry("x_continuous", "x", "position"),
        _entry("y_continuous", "y", "position"),
        _entry("x_discrete", "x", "discrete"),
        _entry("y_discrete", "y", "discrete"),
        _entry("x_log10", "x", "position", trans="log10"),
        _entry("y_log10", "y", "position", trans="log10"),
        _entry("colour_continuous", "colour", "gradient"),
        _entry("colour_gradient", "colour", "gradient"),
        _entry("colour_discrete", "colour", "discrete"),
        _entry("fill_continuous", "fill", "gradient"),
        _entry("fill_gradient", "fill", "gradient"),
        _entry("fill_discrete", "fill", "discrete"),
        _entry("size_continuous", "size", "size_area"),
        _entry("shape_discrete", "shape", "shape"),
        _entry("alpha_continuous", "alpha", "alpha"),
    )

    # --- 位置：sqrt / reverse / binned / 日期时间 ---------------------------
    position = (
        _entry("x_sqrt", "x", "position", trans="sqrt"),
        _entry("y_sqrt", "y", "position", trans="sqrt"),
        _entry("x_reverse", "x", "position", trans="reverse"),
        _entry("y_reverse", "y", "position", trans="reverse"),
        _entry("x_binned", "x", "position_binned", **{"n.breaks": 10, "oob": "squish"}),
        _entry("y_binned", "y", "position_binned", **{"n.breaks": 10, "oob": "squish"}),
        _entry("x_date", "x", "position", trans="date"),
        _entry("y_date", "y", "position", trans="date"),
        _entry("x_datetime", "x", "position", trans="time"),
        _entry("y_datetime", "y", "position", trans="time"),
        _entry("x_time", "x", "position", trans="hms"),
        _entry("y_time", "y", "position", trans="hms"),
    )

    # --- colour / color / fill：连续 / 分箱 / 渐变 / 日期时间 --------------
    # `color` 与 `colour` 是同一实现的别名（NAMESPACE 两个都导出）。
    colour_families = (
        ("continuous", "gradient"),
        ("binned", "binned"),
        ("gradient", "gradient"),
        ("gradient2", "gradient2"),
        ("gradientn", "gradientn"),
        ("steps", "binned"),
        ("steps2", "binned2"),
        ("stepsn", "binnedn"),
        ("date", "gradient"),
        ("datetime", "gradient"),
        ("distiller", "distiller"),
        ("fermenter", "fermenter"),
    )
    date_trans = {"date": "date", "datetime": "time"}
    colours: list[ScaleEntry] = []
    for prefix in ("colour", "color", "fill"):
        for suffix, family in colour_families:
            defaults: dict[str, Any] = {}
            if suffix in date_trans:
                defaults["trans"] = date_trans[suffix]
            # `scale_color_*` 是 `scale_colour_*` 的别名：两者都作用在 `colour`
            # 美学上（上游 NAMESPACE 也是同一个函数）。
            aesthetic = "colour" if prefix in ("colour", "color") else prefix
            colours.append(_entry(f"{prefix}_{suffix}", aesthetic, family, **defaults))

    # --- 其它美学的连续侧 ------------------------------------------------
    extras = (
        _entry("alpha", "alpha", "alpha"),
        _entry("alpha_binned", "alpha", "alpha_binned", oob="squish"),
        _entry("alpha_date", "alpha", "alpha", trans="date"),
        _entry("alpha_datetime", "alpha", "alpha", trans="time"),
        _entry("size", "size", "size_area"),
        _entry("size_area", "size", "size_area_absolute"),
        _entry("size_binned", "size", "size_binned", oob="squish"),
        _entry("size_binned_area", "size", "size_binned_absolute", oob="squish"),
        _entry("size_date", "size", "size_area", trans="date"),
        _entry("size_datetime", "size", "size_area", trans="time"),
        _entry("radius", "size", "radius"),
        _entry("linewidth", "linewidth", "linewidth"),
        _entry("linewidth_continuous", "linewidth", "linewidth"),
        _entry("linewidth_binned", "linewidth", "linewidth_binned", oob="squish"),
        _entry("linewidth_date", "linewidth", "linewidth", trans="date"),
        _entry("linewidth_datetime", "linewidth", "linewidth", trans="time"),
    )

    # --- M2-4 B 段：离散 / 色板（与 A 段共用同一张声明表） ------------------
    # 名字、注册顺序照 #53（SIL-730）的注册表；与 A 段重名的（`size_area` /
    # `radius` / `linewidth_*` / `*_distiller`）只在 A 段登记一次，这里不重复。
    b_segment: list[ScaleEntry] = []

    # colour / color / fill：brewer / grey / hue / ordinal / manual / identity /
    # viridis（A 段已有 binned / steps / gradient* / distiller / fermenter）。
    b_colour_families = (
        ("brewer", "brewer"),
        ("grey", "grey"),
        ("hue", "hue"),
        ("ordinal", "ordinal_colour"),
        ("manual", "manual_colour"),
        ("identity", "identity_discrete"),
        ("viridis_c", "viridis_c"),
        ("viridis_d", "viridis_d"),
        ("viridis_b", "viridis_b"),
    )
    for prefix in ("colour", "color", "fill"):
        for suffix, family in b_colour_families:
            defaults: dict[str, Any] = {}
            if suffix == "grey":
                defaults["na.value"] = "red"
            if suffix == "identity":
                defaults["guide"] = "none"
            aesthetic = "colour" if prefix in ("colour", "color") else prefix
            b_segment.append(_entry(f"{prefix}_{suffix}", aesthetic, family, **defaults))

    b_segment.extend(
        (
            # --- size ----------------------------------------------------
            _entry("size_discrete", "size", "size_discrete"),
            _entry("size_ordinal", "size", "size_ordinal"),
            _entry("size_manual", "size", "size_ordinal"),
            _entry("size_identity", "size", "identity_continuous", guide="none"),
            # --- alpha ---------------------------------------------------
            _entry("alpha_discrete", "alpha", "alpha_discrete"),
            _entry("alpha_ordinal", "alpha", "alpha_ordinal"),
            _entry("alpha_manual", "alpha", "alpha_ordinal"),
            _entry("alpha_identity", "alpha", "identity_continuous", guide="none"),
            # --- shape ---------------------------------------------------
            _entry("shape", "shape", "shape"),
            _entry("shape_ordinal", "shape", "shape_ordinal"),
            _entry("shape_manual", "shape", "shape"),
            _entry("shape_identity", "shape", "identity_continuous", guide="none"),
            _entry("shape_continuous", "shape", "shape"),
            _entry("shape_binned", "shape", "shape_binned"),
            # --- linetype ------------------------------------------------
            _entry("linetype", "linetype", "linetype"),
            _entry("linetype_discrete", "linetype", "linetype"),
            _entry("linetype_manual", "linetype", "linetype"),
            _entry("linetype_identity", "linetype", "identity_discrete", guide="none"),
            _entry("linetype_continuous", "linetype", "linetype"),
            _entry("linetype_binned", "linetype", "linetype_binned"),
            # --- linewidth -----------------------------------------------
            _entry("linewidth_discrete", "linewidth", "linewidth_discrete"),
            _entry("linewidth_ordinal", "linewidth", "linewidth_ordinal"),
            _entry("linewidth_manual", "linewidth", "linewidth_ordinal"),
            _entry("linewidth_identity", "linewidth", "identity_continuous", guide="none"),
            # --- 跨美学 ---------------------------------------------------
            _entry("discrete_manual", "colour", "manual_generic"),
            _entry("discrete_identity", "colour", "identity_discrete", guide="none"),
            _entry("continuous_identity", "size", "identity_continuous", guide="none"),
        )
    )

    return base + position + tuple(colours) + extras + tuple(b_segment)


SCALE_ENTRIES: tuple[ScaleEntry, ...] = _entries()

# 同一注册名只登记一次（M1 的 15 个名字排在最前，后加的别名不重复占位）。
_deduped: list[ScaleEntry] = []
_seen: set[str] = set()
for _entry_item in SCALE_ENTRIES:
    if _entry_item.name in _seen:
        continue
    _seen.add(_entry_item.name)
    _deduped.append(_entry_item)
SCALE_ENTRIES = tuple(_deduped)

#: `registry.SCALE_SPECS` 的历史形状：`(name, aesthetic, defaults)`。
SCALE_SPECS: tuple[tuple[str, str, dict[str, Any]], ...] = tuple(
    (entry.name, entry.aesthetic, dict(entry.defaults)) for entry in SCALE_ENTRIES
)

SCALE_FAMILIES: Mapping[str, str] = MappingProxyType(
    {entry.name: entry.family for entry in SCALE_ENTRIES}
)

SCALE_DEFAULTS: Mapping[str, dict[str, Any]] = MappingProxyType(
    {entry.name: dict(entry.defaults) for entry in SCALE_ENTRIES}
)
