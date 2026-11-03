"""图例（guide，M1-11）：`GuideLegend` / `GuideColourbar` / `GuideNone`。

对齐 ggplot2 4.0.3 的 guide 体系（`R/guide-legend.R`、`R/guide-colourbar.R`）：

- **一个美学只有一个 guide**：同一美学在 `plot.guides` 里最多一个条目，
  后加的替换先加的（`plot.guides` 是 dict，与 `plot.scales` 同一口径）；
- **合并规则**：`Guide$merge()` 的判据是 `hashables = (title, key$.label, name)`——
  title、按键标签、guide 类型都相同时合成一个 guide；`params$key <- cbind(key)`
  把两个美学的键值并到同一行，图标的绘制按图层顺序叠加；
- `show_legend=False`（图层参数）或 `guide="none"` → 不出现；
- 连续 colour / fill 默认 `GuideColourbar`，其余默认 `GuideLegend`；
- key 的图形**复用 `Geom.draw()`**：每个几何一个 key grob，不另写形状代码
  （`docs/notes/guide.md` 的「key 数据模板」）。

几何尺寸照 R 的 `guide_gengrob.legend` / `measure_grobs`：

```
竖向（legend.position = right / left）
  [legend.margin] [key 宽] [legend.key.spacing.x] [标签宽] [legend.margin]
  行：标题（文字行高 + legend.key.spacing） / 每个 key 一行（key 高；竖向没有行间距）

横向（top / bottom）
  每个 key 一格：[key 宽] [spacing.x] [标签宽]，格与格之间 spacing.x
  行：标题 / key 行
```

未实现（明确报错、点名）：`guide_bins`、`legend.position="inside"`、secondary axis
（轴在 `ggcore.axis` 报）、`legend.frame` 以外的高级图例盒子主题。
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.axis import (
    font_int,
    margin_sides_cm,
    paint,
    text_line_cm,
    text_width_cm,
)
from ggcore.build import LayerBuild, PlotBuild
from ggcore.data import Column, ColumnTable
from ggcore.eval import parse_aes
from ggcore.grobs import NullGrob, ZeroGrob, raster_grob, rect_grob, text_grob
from ggcore.theme import (
    ElementBlank,
    ElementLine,
    ElementRect,
    ElementText,
    ResolvedTheme,
)
from ggcore.units import UnitContext, convert_height, convert_width, unit
from ggcore.viewport import NA, gpar, viewport

__all__ = [
    "AUTO",
    "GUIDE_AESTHETICS",
    "Guide",
    "GuideBuild",
    "GuideColourbar",
    "GuideError",
    "GuideKey",
    "GuideLegend",
    "GuideNone",
    "LegendKeyCell",
    "LegendLayout",
    "build_guides",
    "guide_colourbar",
    "guide_from_component",
    "guide_legend",
    "guide_none",
    "legend_grob",
    "legend_layout",
]

#: 会产出图例的非位置美学，顺序固定（决定默认的图例顺序）。
GUIDE_AESTHETICS = ("colour", "fill", "size", "shape", "alpha")

#: `title=waiver()` 的对等物：没显式给标题时按标度 / 映射推。
AUTO: Any = object()

_POINTS_PER_INCH = 72.0
_CM_PER_INCH = 2.54


class GuideError(ValueError):
    """guide 参数无法表达，或请求了尚未实现的图例类型。"""


# ---------------------------------------------------------------------------
# guide 数据对象
# ---------------------------------------------------------------------------


class Guide:
    """所有 guide 的基类（`kind` 是 `"legend"` / `"colourbar"` / `"none"`）。"""

    kind: str = "legend"


@dataclass(frozen=True, slots=True)
class GuideLegend(Guide):
    """`guide_legend()`：离散键（colour / fill / size / shape / alpha）。"""

    title: Any = AUTO
    direction: str | None = None
    nrow: int | None = None
    ncol: int | None = None
    byrow: bool = False
    override_aes: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    keywidth: Any = None
    keyheight: Any = None
    reverse: bool = False
    order: float = 0.0
    kind: str = "legend"

    def __post_init__(self) -> None:
        if self.direction not in (None, "vertical", "horizontal"):
            raise GuideError(
                f"guide_legend(direction=) 只能是 'vertical' / 'horizontal'，"
                f"收到 {self.direction!r}"
            )
        for name in ("nrow", "ncol"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 1):
                raise GuideError(f"guide_legend({name}=) 必须是正整数，收到 {value!r}")
        object.__setattr__(self, "override_aes", MappingProxyType(dict(self.override_aes)))


@dataclass(frozen=True, slots=True)
class GuideColourbar(Guide):
    """`guide_colourbar()`：连续色标——渐变条 + 断点刻度 + 标签。"""

    title: Any = AUTO
    direction: str | None = None
    barwidth: Any = None
    barheight: Any = None
    nbin: int = 256
    ticks: bool = True
    reverse: bool = False
    order: float = 0.0
    kind: str = "colourbar"

    def __post_init__(self) -> None:
        if self.direction not in (None, "vertical", "horizontal"):
            raise GuideError(
                f"guide_colourbar(direction=) 只能是 'vertical' / 'horizontal'，"
                f"收到 {self.direction!r}"
            )
        if not isinstance(self.nbin, int) or self.nbin < 2:
            raise GuideError(f"guide_colourbar(nbin=) 必须 ≥ 2，收到 {self.nbin!r}")


@dataclass(frozen=True, slots=True)
class GuideNone(Guide):
    """`guide = "none"`：该美学不画图例。"""

    kind: str = "none"


def guide_legend(
    title: Any = AUTO,
    direction: str | None = None,
    nrow: int | None = None,
    ncol: int | None = None,
    byrow: bool = False,
    override_aes: Mapping[str, Any] | None = None,
    keywidth: Any = None,
    keyheight: Any = None,
    reverse: bool = False,
    order: float = 0.0,
) -> GuideLegend:
    return GuideLegend(
        title=title,
        direction=direction,
        nrow=nrow,
        ncol=ncol,
        byrow=bool(byrow),
        override_aes=dict(override_aes or {}),
        keywidth=keywidth,
        keyheight=keyheight,
        reverse=bool(reverse),
        order=float(order),
    )


def guide_colourbar(
    title: Any = AUTO,
    direction: str | None = None,
    barwidth: Any = None,
    barheight: Any = None,
    nbin: int = 256,
    ticks: bool = True,
    reverse: bool = False,
    order: float = 0.0,
) -> GuideColourbar:
    return GuideColourbar(
        title=title,
        direction=direction,
        barwidth=barwidth,
        barheight=barheight,
        nbin=int(nbin),
        ticks=bool(ticks),
        reverse=bool(reverse),
        order=float(order),
    )


def guide_none() -> GuideNone:
    return GuideNone()


_LEGEND_PARAMS = frozenset(
    {
        "title",
        "direction",
        "nrow",
        "ncol",
        "byrow",
        "override_aes",
        "override.aes",
        "keywidth",
        "keyheight",
        "reverse",
        "order",
    }
)
_COLOURBAR_PARAMS = frozenset(
    {"title", "direction", "barwidth", "barheight", "nbin", "ticks", "reverse", "order"}
)


def _clean(params: Mapping[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    out = {name: value for name, value in params.items() if name in allowed}
    if "override.aes" in out and "override_aes" not in out:
        out["override_aes"] = out.pop("override.aes")
    return out


def guide_from_component(component: Any) -> Guide:
    """`components.Guide`（注册名 + 参数）→ :mod:`ggcore.guide` 的实现。"""
    name = getattr(component, "name", None)
    params = dict(getattr(component, "params", {}) or {})
    if name == "none":
        return GuideNone()
    if name == "legend":
        return guide_legend(**{k: v for k, v in _clean(params, _LEGEND_PARAMS).items()})
    if name == "colourbar":
        return guide_colourbar(**{k: v for k, v in _clean(params, _COLOURBAR_PARAMS).items()})
    raise GuideError(
        f"未知的 guide {name!r}；已实现：legend / colourbar / none"
        "（guide_bins 未实现，见 docs/notes/guide.md）"
    )


# ---------------------------------------------------------------------------
# 训练好的 guide：keys + 标题
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuideKey:
    """一个图例键：标签 + 断点原值 + 各美学映射后的值。"""

    label: str
    values: Mapping[str, Any]
    #: 断点在标度空间的原值（连续色条用它算刻度位置）；离散是水平名。
    value: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class GuideBuild:
    """一张要画的图例：guide 定义 + 美学 + 标题 + 键 + 参与绘制的图层。"""

    guide: Guide
    aesthetics: tuple[str, ...]
    title: str | None
    keys: tuple[GuideKey, ...]
    layers: tuple[int, ...]
    #: 连续标度的范围（色条刻度按它定位）；离散为 None。
    limits: tuple[float, float] | None = None
    #: 连续标度的色带（`palette(0..1)`）；色条两端取它而不是断点色。
    palette: Callable[[Sequence[float]], list[str]] | None = None

    @property
    def kind(self) -> str:
        return self.guide.kind


def _layer_mapping(build: PlotBuild, index: int) -> Mapping[str, Any]:
    mappings = getattr(build, "raw_mappings", ())
    return mappings[index] if index < len(mappings) else {}


def _default_title(build: PlotBuild, aesthetic: str) -> str | None:
    labels = getattr(build, "labels", {}) or {}
    if aesthetic in labels:
        value = labels[aesthetic]
        return None if value is None else str(value)
    # 取第一条映射该美学的图层的表达式原文（`aes(colour="g")` → "g"）。
    for mapping in getattr(build, "raw_mappings", ()):
        if aesthetic in mapping:
            return str(mapping[aesthetic])
    return aesthetic


def _guide_component(build: PlotBuild, aesthetic: str) -> Guide | None:
    guides = getattr(build, "guides", None) or {}
    for key, component in guides.items():
        if getattr(component, "aesthetic", None) == aesthetic:
            return guide_from_component(component)
        if key == aesthetic and getattr(component, "aesthetic", None) in (None, aesthetic):
            return guide_from_component(component)
    return None


def _guide_from_value(value: Any) -> Guide | None:
    """`scale_*(guide=)` 的值 → 实现。

    R 的 `scale_*_*(guide = )` 接受三种写法，这里一一对等：

    - 字符串：`"none"` → :class:`GuideNone`；`"legend"` / `"colourbar"` 走注册表；
    - `components.Guide`（`registry.guide_legend(...)`）→ :func:`guide_from_component`；
    - `Guide` 实现本身（`ggcore.guide.guide_legend(...)`）原样返回。
    """
    if value is None:
        return None
    if isinstance(value, Guide):
        return value
    if isinstance(value, str):
        if value == "none":
            return guide_none()
        if value == "legend":
            return guide_legend()
        if value == "colourbar":
            return guide_colourbar()
        raise GuideError(
            f"未知的 guide {value!r}；已实现：legend / colourbar / none"
            "（guide_bins 未实现，见 docs/notes/guide.md）"
        )
    if getattr(value, "name", None) is not None:
        return guide_from_component(value)
    raise GuideError(
        f"无法把 {value!r} 当作 guide；用字符串（'none' / 'legend' / 'colourbar'）"
        "或 guide_legend() / guide_colourbar() / guide_none()"
    )


def _scale_guide(scale: Any) -> Guide | None:
    """标度上的 `guide=` 参数（`plot.guides` 没有对应条目时的回落）。"""
    params = getattr(scale, "params", None) or {}
    return _guide_from_value(params.get("guide"))


def _is_mapped(build: PlotBuild, index: int, aesthetic: str) -> bool:
    layer = build.layers[index]
    show = getattr(layer, "show_legend", None)
    if show is None:
        show = layer.params.get("show_legend", layer.params.get("show.legend"))
    if show is False:
        return False
    return aesthetic in _layer_mapping(build, index)


def _default_guide(build: PlotBuild, aesthetic: str, scale: Any) -> Guide:
    if aesthetic in ("colour", "fill") and not bool(getattr(scale, "discrete", False)):
        return guide_colourbar()
    return guide_legend()


def _key_values(scale: Any) -> tuple[tuple[str, Any, Any], ...]:
    """标度的 `(label, 断点原值, 映射值)` 序列（R `extract_key()` 的 `.label`/键）。"""
    breaks = tuple(scale.breaks())
    labels = tuple(scale.labels())
    values: list[Any] = []
    for value in breaks:
        if value is None:
            values.append(None)
            continue
        if scale.discrete:
            values.append(str(value))
        else:
            values.append(float(value))
    mapped = _list_of(scale.map(_column_of(values, scale)))
    out: list[tuple[str, Any, Any]] = []
    for label, value, item in zip(labels, values, mapped, strict=True):
        if label is None or value is None:
            continue
        if isinstance(item, float) and not np.isfinite(item):
            continue
        if item is None:
            continue
        out.append((str(label), value, item))
    return tuple(out)


def _column_of(values: Sequence[Any], scale: Any) -> Column:
    if getattr(scale, "discrete", False):
        texts = ["" if item is None else str(item) for item in values]
        return Column("str", np.array(texts, dtype=object))
    numbers = np.array(
        [np.nan if item is None else float(item) for item in values], dtype=np.float64
    )
    return Column("float", numbers)


def _list_of(mapped: Any) -> list[Any]:
    if not isinstance(mapped, Column):
        return list(mapped)
    values = np.asarray(mapped.values)
    mask = np.asarray(mapped.na_mask, dtype=bool)
    pairs = zip(values.tolist(), mask.tolist(), strict=True)
    if values.dtype.kind in ("O", "U"):
        return [None if missing else str(item) for item, missing in pairs]
    return [None if missing else float(item) for item, missing in pairs]


def build_guides(build: PlotBuild) -> tuple[GuideBuild, ...]:
    """`PlotBuild` → 要画的 guide 列表（已按合并规则折叠、按 order 排序）。"""
    scales = build.scales
    candidates: list[GuideBuild] = []
    for aesthetic in GUIDE_AESTHETICS:
        scale = scales.scale(aesthetic) if scales is not None else None
        if scale is None:
            continue
        layers = tuple(
            index for index in range(len(build.layers)) if _is_mapped(build, index, aesthetic)
        )
        if not layers:
            continue
        component = _guide_component(build, aesthetic)
        if isinstance(component, GuideNone):
            continue
        if component is None:
            # `plot.guides` 没有对应条目时回落到 `scale_*(guide=)`。
            component = _scale_guide(scale)
        if isinstance(component, GuideNone):
            continue
        guide = component if component is not None else _default_guide(build, aesthetic, scale)
        if isinstance(guide, GuideColourbar) and bool(getattr(scale, "discrete", False)):
            raise GuideError(
                f"guide_colourbar 只能用于连续标度；{aesthetic!r} 是离散标度"
                "（用 guide_legend() 或默认 guide）"
            )
        keys = _key_values(scale)
        if not keys:
            continue
        title_value = guide.title
        if title_value is AUTO:
            title = _default_title(build, aesthetic)
        else:
            title = None if title_value is None else str(title_value)
        if title_value is AUTO:
            explicit = _scale_name(scale)
            if explicit is not None:
                title = str(explicit)
        reverse = bool(getattr(guide, "reverse", False))
        if reverse:
            keys = tuple(reversed(keys))
        limits = None
        palette = None
        if not bool(getattr(scale, "discrete", False)):
            limits = tuple(float(item) for item in scale.limits())
            colour_ramp = getattr(scale, "palette", None)
            if callable(colour_ramp):
                palette = colour_ramp
        candidates.append(
            GuideBuild(
                guide=guide,
                aesthetics=(aesthetic,),
                title=title,
                keys=tuple(
                    GuideKey(label, {aesthetic: item}, value) for label, value, item in keys
                ),
                layers=layers,
                limits=limits,
                palette=palette,
            )
        )

    merged: list[GuideBuild] = []
    for candidate in candidates:
        for position, existing in enumerate(merged):
            if not _can_merge(existing, candidate):
                continue
            merged[position] = _merge(existing, candidate)
            break
        else:
            merged.append(candidate)
    return tuple(
        sorted(merged, key=lambda item: (float(getattr(item.guide, "order", 0.0)), _order_of(item)))
    )


def _scale_name(scale: Any) -> Any:
    """标度组件上的显式 `name`（`scale_colour_discrete(name="Cyl")`）。"""
    param = getattr(scale, "_param", None)
    if param is None:
        return None
    try:
        return param("name")
    except TypeError:  # pragma: no cover - 自定义标度子类可能没有 name 参数
        return None


def _order_of(guide: GuideBuild) -> int:
    if not guide.aesthetics:
        return len(GUIDE_AESTHETICS)
    return GUIDE_AESTHETICS.index(guide.aesthetics[0])


def _can_merge(left: GuideBuild, right: GuideBuild) -> bool:
    if left.kind != right.kind or left.kind == "none":
        return False
    if left.title != right.title:
        return False
    if tuple(key.label for key in left.keys) != tuple(key.label for key in right.keys):
        return False
    return not (set(left.aesthetics) & set(right.aesthetics))


def _merge(left: GuideBuild, right: GuideBuild) -> GuideBuild:
    keys = tuple(
        GuideKey(first.label, {**first.values, **second.values}, first.value)
        for first, second in zip(left.keys, right.keys, strict=True)
    )
    layers = tuple(dict.fromkeys((*left.layers, *right.layers)))
    overrides = {**dict(_override(left.guide)), **dict(_override(right.guide))}
    return GuideBuild(
        guide=replace(left.guide, override_aes=overrides),
        aesthetics=tuple(dict.fromkeys((*left.aesthetics, *right.aesthetics))),
        title=left.title,
        keys=keys,
        layers=layers,
        limits=left.limits,
        palette=left.palette,
    )


def _override(guide: Guide) -> Mapping[str, Any]:
    return getattr(guide, "override_aes", {}) or {}


# ---------------------------------------------------------------------------
# key 数据：复用 Geom.draw()
# ---------------------------------------------------------------------------

_AES_COLUMNS = (
    "colour",
    "fill",
    "alpha",
    "size",
    "shape",
    "stroke",
    "linewidth",
    "linetype",
    "group",
)

_GEOM_KEYS: Mapping[str, Mapping[str, tuple[float, ...]]] = MappingProxyType(
    {
        "point": MappingProxyType({"x": (0.5,), "y": (0.5,)}),
        "line": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "path": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "smooth": MappingProxyType({"x": (0.2, 0.8), "y": (0.2, 0.8)}),
        "bar": MappingProxyType({"xmin": (0.0,), "xmax": (1.0,), "ymin": (0.0,), "ymax": (1.0,)}),
        "col": MappingProxyType({"xmin": (0.0,), "xmax": (1.0,), "ymin": (0.0,), "ymax": (1.0,)}),
        "histogram": MappingProxyType(
            {"xmin": (0.0,), "xmax": (1.0,), "ymin": (0.0,), "ymax": (1.0,)}
        ),
        "area": MappingProxyType({"x": (0.0, 1.0), "ymin": (0.0, 0.0), "ymax": (0.0, 1.0)}),
        "boxplot": MappingProxyType(
            {
                "x": (0.5,),
                "xmin": (0.2,),
                "xmax": (0.8,),
                "ymin": (0.1,),
                "lower": (0.3,),
                "middle": (0.5,),
                "upper": (0.7,),
                "ymax": (0.9,),
            }
        ),
    }
)


def _is_mapped_aesthetic(mapping: Mapping[str, Any] | None, name: str) -> bool:
    """该美学是否被**标度映射**（而不是图层上的常量）。

    `aes(colour = "g")` 是映射；`aes(colour = 0.5)` 这类非字符串常量不算。
    """
    if not mapping or name not in mapping:
        return False
    return not parse_aes(mapping[name]).constant


def _missing_column(kind: str, nrows: int) -> Column:
    """全 NA 列：用「缺失」表示这个美学不属于当前 guide。"""
    if kind == "str":
        return Column(
            "str",
            np.array([""] * nrows, dtype=object),
            na_mask=np.ones(nrows, dtype=bool),
        )
    return Column("float", np.full(nrows, np.nan), na_mask=np.ones(nrows, dtype=bool))


def key_table(
    layer: LayerBuild,
    values: Mapping[str, Any],
    geom: str,
    *,
    mapping: Mapping[str, Any] | None = None,
) -> ColumnTable:
    """一个图例键的假数据表：几何模板 + 图层的常量美学 + 键的映射值。

    位置列由 :data:`_GEOM_KEYS` 的模板铺满 key 视口；其余美学取图层数据的第一行
    （常量 `geom_point(colour="red")` 因此能带进图例），再用键值覆盖被 guide 管理
    的那几列。`Geom.draw()` 拿到它与 0..1 的 key 面板就能画出和面板里一致的图形。

    `mapping` 是该图层的 `raw_mappings`：**只有常量美学能带进 key**。被标度映射、
    但不由这张 guide 管理的美学要省略——`colour` / `fill` 置成全 NA，其余用几何
    默认值。否则 `colour = cyl, fill = gear` 时 colour 图例的键会被灌进第一行的
    `fill`（R：colour 图例的圆只有 stroke，fill 图例的圆只有 fill）。
    """
    template = _GEOM_KEYS.get(geom)
    if template is None:
        raise GuideError(
            f"geom_{geom} 没有图例 key 模板（已实现：{', '.join(sorted(_GEOM_KEYS))}）；"
            "见 docs/notes/guide.md「未实现」"
        )
    nrows = len(next(iter(template.values())))
    columns: dict[str, Column] = {}
    managed = set(values)
    for name in _AES_COLUMNS:
        if name in managed:
            # 本 guide 的键值在下面统一写入。
            continue
        if _is_mapped_aesthetic(mapping, name):
            if name in ("colour", "fill") and name in layer.data:
                columns[name] = _missing_column(layer.data.column(name).kind, nrows)
            continue
        if name not in layer.data or layer.data.nrows == 0:
            continue
        first = _first_value(layer.data, name)
        if first is None:
            continue
        if isinstance(first, str):
            columns[name] = Column("str", np.array([first] * nrows, dtype=object))
        elif isinstance(first, bool):
            columns[name] = Column("bool", np.array([first] * nrows, dtype=bool))
        else:
            columns[name] = Column("float", np.full(nrows, float(first), dtype=np.float64))
    for name, value in values.items():
        if isinstance(value, str):
            columns[name] = Column("str", np.array([value] * nrows, dtype=object))
        elif isinstance(value, bool):
            columns[name] = Column("bool", np.array([value] * nrows, dtype=bool))
        else:
            number = float(value)
            columns[name] = Column("float", np.full(nrows, number, dtype=np.float64))
    for name, numbers in template.items():
        columns[name] = Column("float", np.array(numbers, dtype=np.float64))
    if geom == "boxplot":
        columns["flipped_aes"] = Column("bool", np.zeros(nrows, dtype=bool))
        columns["outliers"] = Column("float", np.full(nrows, np.nan))
    return ColumnTable(list(columns.items()), nrows=nrows)


def _first_value(table: ColumnTable, name: str) -> Any:
    column = table.column(name)
    if column.size == 0:
        return None
    mask = np.asarray(column.na_mask, dtype=bool)
    if bool(mask[0]):
        return None
    value = np.asarray(column.values)[0]
    if isinstance(value, np.generic):
        value = value.item()
    return value


def _key_grob(
    build: PlotBuild,
    layer_index: int,
    values: Mapping[str, Any],
    *,
    override: Mapping[str, Any] | None = None,
) -> Any | None:
    layer = build.layers[layer_index]
    geom = _geom_of(layer)
    resolved = {**dict(override or {}), **dict(values)}
    table = key_table(
        layer,
        resolved,
        geom.name,
        mapping=_layer_mapping(build, layer_index),
    )
    key_layer = replace(layer, data=table)
    grob = geom.draw(key_layer, _KeyPanel(), build.coord, build.theme, build.metrics)
    if isinstance(grob, (NullGrob, ZeroGrob)):
        return None
    return grob


class _KeyPanel:
    """0..1 的假面板：`PanelParams` 的 `transform()` 对等物（key 数据坐标即 npc）。"""

    x_range = (0.0, 1.0)
    y_range = (0.0, 1.0)
    x_limits = (0.0, 1.0)
    y_limits = (0.0, 1.0)

    def transform(self, column: Column, aesthetic: str = "x") -> Column:
        values = np.asarray(column.values, dtype=np.float64)
        mask = np.asarray(column.na_mask, dtype=bool)
        out = values.copy()
        out[mask] = 0.0
        return Column("float", out, na_mask=mask)


def _geom_of(layer: LayerBuild) -> Any:
    geom = getattr(layer, "geom_object", None)
    if geom is None:
        raise GuideError(f"layer[{layer.index}] 没有 geom 对象，无法画图例 key")
    return geom


# ---------------------------------------------------------------------------
# 尺寸
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Box:
    x_cm: float
    y_cm: float
    width_cm: float
    height_cm: float


def _cm_unit(value: Any, *, height: bool) -> float:
    if value is None:
        return 0.0
    try:
        convert = convert_height if height else convert_width
        return float(np.asarray(convert(value, "cm", ctx=UnitContext())).sum())
    except Exception as exc:  # pragma: no cover - 主题单位不合法时点名词条
        raise GuideError(f"guide 的尺寸单位无法换算成 cm：{value!r}（{exc}）") from None


def _key_size(theme: ResolvedTheme, guide: Guide) -> tuple[float, float]:
    width = _cm_unit(theme.get("legend.key.width"), height=False)
    height = _cm_unit(theme.get("legend.key.height"), height=True)
    override_w = getattr(guide, "keywidth", None)
    override_h = getattr(guide, "keyheight", None)
    if override_w is not None:
        width = _cm_unit(override_w, height=False)
    if override_h is not None:
        height = _cm_unit(override_h, height=True)
    if width <= 0 or height <= 0:
        raise GuideError("legend.key.width / legend.key.height 解析为 0，图例 key 没有尺寸")
    return width, height


def _text_element(theme: ResolvedTheme, name: str) -> ElementText:
    element = theme.get(name)
    if isinstance(element, ElementText):
        return element
    if isinstance(element, ElementBlank):
        return ElementText(size=0.0, colour=NA)
    return ElementText(size=11.0, colour="#000000")


def legend_direction(guide: Guide, position: str | None) -> str:
    explicit = getattr(guide, "direction", None)
    if explicit is not None:
        return explicit
    return "horizontal" if position in ("top", "bottom") else "vertical"


def _grid_shape(guide: Guide, n: int, direction: str) -> tuple[int, int, bool]:
    nrow = getattr(guide, "nrow", None)
    ncol = getattr(guide, "ncol", None)
    byrow = bool(getattr(guide, "byrow", False))
    if nrow is None and ncol is None:
        return (n, 1, False) if direction == "vertical" else (1, n, True)
    if nrow is None:
        assert ncol is not None
        nrow = max(1, int(np.ceil(n / ncol)))
    elif ncol is None:
        ncol = max(1, int(np.ceil(n / nrow)))
    if int(nrow) * int(ncol) < n:
        # R：`nrow * ncol needs to be larger than the number of legend keys`。
        raise GuideError(
            f"guide_legend(nrow={nrow}, ncol={ncol}) 放不下 {n} 个键；nrow * ncol 至少要 ≥ {n}"
        )
    return int(nrow), int(ncol), byrow


@dataclass(frozen=True, slots=True)
class LegendLayout:
    """一张图例的布局：外框尺寸 + 每个 key / 标签 / 标题的位置（局部 cm，y 向上）。"""

    width_cm: float
    height_cm: float
    direction: str
    title_box: _Box | None = None
    keys: tuple[LegendKeyCell, ...] = ()
    bar: _Box | None = None
    ticks: tuple[tuple[float, str], ...] = ()


@dataclass(frozen=True, slots=True)
class LegendKeyCell:
    key: GuideKey
    box: _Box
    label_box: _Box


def legend_layout(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    position: str | None = None,
    *,
    metrics: Any = None,
) -> LegendLayout:
    """一张图例的尺寸与内部格位（cm；不含外部的 `legend.box.spacing`）。"""
    guide = guide_build.guide
    direction = legend_direction(guide, position)
    padding = margin_sides_cm(theme.get("legend.margin"))
    pad_t, pad_r, pad_b, pad_l = padding
    title_el = _text_element(theme, "legend.title")
    text_el = _text_element(theme, "legend.text")
    title_size = float(title_el.size or 0.0)
    text_size = float(text_el.size or 0.0)
    gap = _cm_unit(theme.get("legend.key.spacing"), height=True) or _cm_unit(
        theme.get("legend.key.spacing.y"), height=True
    )
    spacing_x = _cm_unit(theme.get("legend.key.spacing.x"), height=False)
    spacing_y = (
        0.0
        if direction == "vertical"
        else (_cm_unit(theme.get("legend.key.spacing.y"), height=True))
    )
    title_line = text_line_cm(title_size) if guide_build.title else 0.0
    title_h = title_line + gap if guide_build.title else 0.0
    title_w = (
        text_width_cm(guide_build.title or "", title_size, metrics, title_el.family or "")
        if guide_build.title
        else 0.0
    )

    if isinstance(guide, GuideColourbar):
        return _colourbar_layout(
            guide_build,
            theme,
            direction=direction,
            padding=padding,
            title_h=title_h,
            title_w=title_w,
            title_line=title_line,
            spacing_x=spacing_x,
            text_el=text_el,
            metrics=metrics,
        )

    key_w, key_h = _key_size(theme, guide)
    n = len(guide_build.keys)
    nrow, ncol, byrow = _grid_shape(guide, n, direction)
    label_w: list[float] = [
        text_width_cm(key.label, text_size, metrics, text_el.family or "")
        for key in guide_build.keys
    ]
    # 每个 key 的格位：byrow 按行铺，否则按列铺（R arrange_layout 同）。
    cells: list[tuple[int, int, int]] = []
    for index in range(n):
        if byrow:
            row = index // ncol
            col = index % ncol
        else:
            row = index % nrow
            col = index // nrow
        cells.append((row, col, index))
    col_widths = [0.0] * ncol
    for _row, col, index in cells:
        col_widths[col] = max(col_widths[col], key_w + spacing_x + label_w[index])
    row_heights = [key_h] * nrow
    content_w = sum(col_widths) + spacing_x * (ncol - 1)
    content_h = sum(row_heights) + spacing_y * (nrow - 1)
    width = max(content_w, title_w) + pad_l + pad_r
    height = title_h + content_h + pad_t + pad_b

    title_box = None
    if guide_build.title:
        title_box = _Box(pad_l, height - pad_t - title_line, title_w, title_line)
    key_cells: list[LegendKeyCell] = []
    top = height - pad_t - title_h
    x_starts = [pad_l]
    for col in range(1, ncol):
        x_starts.append(x_starts[-1] + col_widths[col - 1] + spacing_x)
    y_starts = [top]
    for row in range(1, nrow):
        y_starts.append(y_starts[-1] - row_heights[row - 1] - spacing_y)
    for row, col, index in cells:
        key_box = _Box(x_starts[col], y_starts[row] - key_h, key_w, key_h)
        label_box = _Box(
            x_starts[col] + key_w + spacing_x,
            y_starts[row] - key_h,
            label_w[index],
            key_h,
        )
        key_cells.append(LegendKeyCell(guide_build.keys[index], key_box, label_box))
    return LegendLayout(
        width_cm=width,
        height_cm=height,
        direction=direction,
        title_box=title_box,
        keys=tuple(key_cells),
    )


def _bar_size(
    guide: GuideColourbar, key_w: float, key_h: float, direction: str = "vertical"
) -> tuple[float, float]:
    """色条尺寸：长轴默认 5 × key，短轴默认 key（与 R 4.0.3 的 30×150 key 比例一致）。"""
    explicit_w = _cm_unit(guide.barwidth, height=False) if guide.barwidth is not None else None
    explicit_h = _cm_unit(guide.barheight, height=True) if guide.barheight is not None else None
    if direction == "horizontal":
        bar_w = explicit_w if explicit_w is not None else 5.0 * key_w
        bar_h = explicit_h if explicit_h is not None else key_h
    else:
        bar_w = explicit_w if explicit_w is not None else key_w
        bar_h = explicit_h if explicit_h is not None else 5.0 * key_h
    return bar_w, bar_h


def _bar_ticks(
    guide_build: GuideBuild,
    guide: GuideColourbar,
    box: _Box,
    direction: str,
) -> tuple[tuple[float, str], ...]:
    """刻度位置（竖向是 y、横向是 x；局部 cm）+ 标签。

    `reverse=TRUE` 时 R 的 `.value` 是 `1 - (value - low) / span`：标签跟着色带一起
    翻，不能只翻色带（v1 的 bug）。
    """
    low, high = guide_build.limits if guide_build.limits is not None else (0.0, 1.0)
    span = float(high) - float(low)
    ticks: list[tuple[float, str]] = []
    for key in guide_build.keys:
        if span == 0 or not isinstance(key.value, (int, float)):
            fraction = 0.0
        else:
            fraction = (float(key.value) - float(low)) / span
        if guide.reverse:
            fraction = 1.0 - fraction
        if direction == "horizontal":
            ticks.append((box.x_cm + fraction * box.width_cm, key.label))
        else:
            ticks.append((box.y_cm + fraction * box.height_cm, key.label))
    return tuple(ticks)


def _colourbar_layout(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    *,
    direction: str,
    padding: tuple[float, float, float, float],
    title_h: float,
    title_w: float,
    title_line: float,
    spacing_x: float,
    text_el: ElementText,
    metrics: Any,
) -> LegendLayout:
    guide = guide_build.guide
    assert isinstance(guide, GuideColourbar)
    pad_t, pad_r, pad_b, pad_l = padding
    key_w, key_h = _key_size(theme, guide)
    bar_w, bar_h = _bar_size(guide, key_w, key_h, direction)
    text_size = float(text_el.size or 0.0)
    label_w = max(
        (
            text_width_cm(key.label, text_size, metrics, text_el.family or "")
            for key in guide_build.keys
        ),
        default=0.0,
    )
    if direction == "horizontal":
        # 横向：色条在上，标签排在下方一行（R 的 1.487cm 高就是这个结构）。
        width = max(bar_w, title_w) + pad_l + pad_r
        label_row = text_line_cm(text_size)
        height = title_h + bar_h + label_row + pad_t + pad_b
        title_box = None
        if guide_build.title:
            title_box = _Box(pad_l, height - pad_t - title_line, title_w, title_line)
        bar_box = _Box(pad_l, height - pad_t - title_h - bar_h, bar_w, bar_h)
        return LegendLayout(
            width_cm=width,
            height_cm=height,
            direction=direction,
            title_box=title_box,
            bar=bar_box,
            ticks=_bar_ticks(guide_build, guide, bar_box, direction),
        )
    width = bar_w + spacing_x + label_w + pad_l + pad_r
    width = max(width, title_w + pad_l + pad_r)
    height = title_h + bar_h + pad_t + pad_b
    title_box = None
    if guide_build.title:
        title_box = _Box(pad_l, height - pad_t - title_line, title_w, title_line)
    bar_box = _Box(pad_l, height - pad_t - title_h - bar_h, bar_w, bar_h)
    return LegendLayout(
        width_cm=width,
        height_cm=height,
        direction=direction,
        title_box=title_box,
        bar=bar_box,
        ticks=_bar_ticks(guide_build, guide, bar_box, direction),
    )


# ---------------------------------------------------------------------------
# 绘制
# ---------------------------------------------------------------------------


def _text_gp(element: ElementText) -> dict[str, Any]:
    return {
        "col": paint(element.colour) or "black",
        "fontsize": float(element.size or 11.0),
        "fontfamily": element.family or "",
        "font": font_int(element.face),
        "lineheight": float(element.lineheight or 1.2),
    }


def legend_grob(
    guide_build: GuideBuild,
    build: PlotBuild,
    theme: ResolvedTheme,
    layout: LegendLayout,
    *,
    metrics: Any = None,
    name: str = "guide",
) -> list[Any]:
    """一张图例的 grob 列表（局部 cm 坐标；调用方给外框视口）。"""
    width = layout.width_cm
    height = layout.height_cm
    grobs: list[Any] = []
    background = theme.get("legend.background")
    if isinstance(background, ElementRect):
        fill = paint(background.fill)
        if fill is not None:
            grobs.append(
                rect_grob(
                    0.0,
                    0.0,
                    width,
                    height,
                    just=("left", "bottom"),
                    default_units="cm",
                    gp=gpar(fill=fill, col=NA),
                    name=f"{name}.background",
                )
            )
    title_el = _text_element(theme, "legend.title")
    if guide_build.title and layout.title_box is not None:
        box = layout.title_box
        grobs.append(
            text_grob(
                guide_build.title,
                box.x_cm,
                box.y_cm + box.height_cm / 2.0,
                hjust=0.0,
                vjust=0.5,
                default_units="cm",
                gp=gpar(**_text_gp(title_el)),
                name=f"{name}.title",
            )
        )
    if isinstance(guide_build.guide, GuideColourbar) and layout.bar is not None:
        grobs.extend(_colourbar_grobs(guide_build, theme, layout, name=name))
        return grobs
    text_el = _text_element(theme, "legend.text")
    key_el = theme.get("legend.key")
    for index, cell in enumerate(layout.keys):
        key_box = cell.box
        if isinstance(key_el, ElementRect) and paint(key_el.fill) is not None:
            grobs.append(
                rect_grob(
                    key_box.x_cm,
                    key_box.y_cm,
                    key_box.width_cm,
                    key_box.height_cm,
                    just=("left", "bottom"),
                    default_units="cm",
                    gp=gpar(
                        fill=paint(key_el.fill),
                        col=paint(key_el.colour) or NA,
                        lwd=0.0,
                    ),
                    name=f"{name}.key-{index}-bg",
                )
            )
        vp = viewport(
            f"{name}-key-{index}",
            x=unit(key_box.x_cm + key_box.width_cm / 2.0, "cm"),
            y=unit(key_box.y_cm + key_box.height_cm / 2.0, "cm"),
            width=unit(key_box.width_cm, "cm"),
            height=unit(key_box.height_cm, "cm"),
            just="centre",
            xscale=(0.0, 1.0),
            yscale=(0.0, 1.0),
            clip="on",
        )
        for layer_index in guide_build.layers:
            if not _layer_maps_any(build, layer_index, guide_build.aesthetics):
                continue
            decor = _key_grob(
                build,
                layer_index,
                cell.key.values,
                override=_override(guide_build.guide),
            )
            if decor is None:
                continue
            grobs.append(replace(decor, vp=vp) if getattr(decor, "vp", None) is None else decor)
        label_box = cell.label_box
        grobs.append(
            text_grob(
                cell.key.label,
                label_box.x_cm,
                label_box.y_cm + label_box.height_cm / 2.0,
                hjust=0.0,
                vjust=0.5,
                default_units="cm",
                gp=gpar(**_text_gp(text_el)),
                name=f"{name}.label-{index}",
            )
        )
    return grobs


def _layer_maps_any(build: PlotBuild, index: int, aesthetics: Sequence[str]) -> bool:
    mapping = _layer_mapping(build, index)
    return any(aesthetic in mapping for aesthetic in aesthetics)


def _colourbar_grobs(
    guide_build: GuideBuild,
    theme: ResolvedTheme,
    layout: LegendLayout,
    *,
    name: str,
) -> list[Any]:
    """渐变条：一张 `nbin` 像素的位图贴到色条矩形（对齐 R 的 `rasterGrob`）。

    细矩形拼不出渐变：每块只有零点几个像素高，抗锯齿后与白底混合，整条偏白约
    30%。R/svglite 也是 `preserveAspectRatio='none'` 的 1×nbin 位图。
    """
    guide = guide_build.guide
    assert isinstance(guide, GuideColourbar)
    box = layout.bar
    assert box is not None
    nbin = int(guide.nbin)
    grobs: list[Any] = []
    steps = _bar_steps(guide_build, nbin)
    horizontal = layout.direction == "horizontal"
    data, width_px, height_px = _bar_png(steps, horizontal=horizontal)
    grobs.append(
        raster_grob(
            data,
            width_px,
            height_px,
            x=box.x_cm,
            y=box.y_cm,
            width=box.width_cm,
            height=box.height_cm,
            just=("left", "bottom"),
            interpolate=True,
            default_units="cm",
            name=f"{name}.bar",
        )
    )
    frame = theme.get("legend.frame")
    if isinstance(frame, ElementRect) and paint(frame.colour) is not None:
        grobs.append(
            rect_grob(
                box.x_cm,
                box.y_cm,
                box.width_cm,
                box.height_cm,
                just=("left", "bottom"),
                default_units="cm",
                gp=gpar(fill=NA, col=paint(frame.colour), lwd=0.0),
                name=f"{name}.frame",
            )
        )
    text_el = _text_element(theme, "legend.text")
    label_x = box.x_cm + box.width_cm + _cm_unit(theme.get("legend.key.spacing.x"), height=False)
    tick_el = theme.get("legend.ticks")
    tick_len = _cm_unit(theme.get("legend.ticks.length"), height=False) or 0.0
    from ggcore.grobs import segments_grob

    # ggplot2 4.0.3 的 colourbar 自带缺省刻度：`default_ticks = element_line(
    # colour = "white", linewidth = 0.5/.pt)`。theme_void 把 `line` 设成 blank，
    # colourbar 仍然画这层白刻度（参考 SVG 里每条断点左右各一段，画在色条内侧）。
    colour = paint(getattr(tick_el, "colour", None)) if isinstance(tick_el, ElementLine) else None
    lwd = float(getattr(tick_el, "linewidth", None) or 0.5) if colour is not None else 0.5
    colour = colour or "white"
    # `guide_colourbar(ticks = FALSE)` 只去掉刻度线，标签照画（与 R 4.0.3 一致）。
    draw_ticks = bool(guide.ticks) and tick_len > 0
    for index, (position, label) in enumerate(layout.ticks):
        if draw_ticks:
            # R 的 `build_ticks(position = "right"/"left")` 从色条边缘向**内**画，
            # 两侧各一段（参考 SVG 的 10 条白 polyline）。
            if horizontal:
                segments = (
                    (position, box.y_cm, position, box.y_cm + tick_len),
                    (
                        position,
                        box.y_cm + box.height_cm,
                        position,
                        box.y_cm + box.height_cm - tick_len,
                    ),
                )
            else:
                segments = (
                    (box.x_cm + tick_len, position, box.x_cm, position),
                    (
                        box.x_cm + box.width_cm - tick_len,
                        position,
                        box.x_cm + box.width_cm,
                        position,
                    ),
                )
            grobs.append(
                segments_grob(
                    [segment[0] for segment in segments],
                    [segment[1] for segment in segments],
                    [segment[2] for segment in segments],
                    [segment[3] for segment in segments],
                    default_units="cm",
                    gp=gpar(col=colour, lwd=lwd),
                    name=f"{name}.tick-{index}",
                )
            )
        if horizontal:
            # 横向：标签居中排在色条下方（R 的 text-anchor = middle）。
            grobs.append(
                text_grob(
                    label,
                    position,
                    box.y_cm - tick_len,
                    hjust=0.5,
                    vjust=1.0,
                    default_units="cm",
                    gp=gpar(**_text_gp(text_el)),
                    name=f"{name}.colourbar-label-{index}",
                )
            )
        else:
            grobs.append(
                text_grob(
                    label,
                    label_x,
                    position,
                    hjust=0.0,
                    vjust=0.5,
                    default_units="cm",
                    gp=gpar(**_text_gp(text_el)),
                    name=f"{name}.colourbar-label-{index}",
                )
            )
    return grobs


def _bar_steps(guide_build: GuideBuild, nbin: int) -> list[str]:
    """色条的 `nbin` 个颜色：两端是标度 limits（`palette(0)` / `palette(1)`），
    断点只决定刻度位置与标签（上游 `pal(seq(0, 1, length.out = nbin))`）。
    """
    palette = guide_build.palette
    if palette is not None:
        steps = list(palette(np.linspace(0.0, 1.0, nbin)))
        return steps[::-1] if guide_build.guide.reverse else steps
    # 没有 palette 的连续标度（理论上只有 colour/fill 连续会走到 colourbar）：
    # 退回按断点色插值。
    values = [key.values.get("colour", key.values.get("fill")) for key in guide_build.keys]
    colours = [value if isinstance(value, str) else "#808080" for value in values]
    return _gradient_stops(colours, nbin)


def _bar_png(colours: Sequence[str], *, horizontal: bool) -> tuple[bytes, int, int]:
    """`colours`（左/下 → 右/上）→ `(png, width_px, height_px)`。

    竖向取 1×n 位图、横向取 n×1 位图，贴图时 `preserveAspectRatio=none` 拉伸
    （R 的 svglite 产物是 1×300）。
    """
    from ggcore.grobs import parse_colour

    channels = [parse_colour(colour)[:3] for colour in colours]
    if horizontal:
        width, height = len(channels), 1
        rows = [b"".join(bytes(rgb) for rgb in channels)]
    else:
        # PNG 第一行是顶边：竖向色带底部是最小值。
        width, height = 1, len(channels)
        rows = [bytes(rgb) for rgb in reversed(channels)]
    raw = b"".join(b"\x00" + row for row in rows)  # 每行前 1 字节 filter=none

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    return png, width, height


def _gradient_stops(colours: Sequence[str], nbin: int) -> list[str]:
    """断点色 → `nbin` 个等距色（在 sRGB 里线性插值，与 R 的 colourbar 近似）。"""
    from ggcore.grobs import parse_colour

    if not colours:
        return ["#808080"] * nbin
    if len(colours) == 1:
        return [colours[0]] * nbin
    stops = [parse_colour(colour) for colour in colours]
    out: list[str] = []
    for index in range(nbin):
        position = index / (nbin - 1) * (len(stops) - 1)
        left = int(np.floor(position))
        right = min(left + 1, len(stops) - 1)
        fraction = position - left
        channels = [
            round(stops[left][channel] + (stops[right][channel] - stops[left][channel]) * fraction)
            for channel in range(3)
        ]
        out.append("#{:02X}{:02X}{:02X}".format(*channels))
    return out
