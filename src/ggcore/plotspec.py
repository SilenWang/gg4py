"""plot 规格 → IR 场景（M0-9 的案例适配层）。

三文件 case 的 `plot.py` 返回一份 plot 规格 dict（`docs/cases/README.md`），
本模块把它画成一张 `ggcore.ir.Scene`：

    spec = load_plot(docs/cases/geom-point-basic)
    ir_scene = scene_from_spec(spec, metrics=...)

它**不是** ggplot2 语法层（`ggcore.plot` / `ggcore.aes` 仍是 M1 的事）。这里只
实现案例库需要的那个最小子集：固定数据、显式 limits、`theme_void()` 口径的
整页面板，加上四种 layer（`point` / `bar` / `text` / `curve`）。口径与
`tools/refs/cases_ref.R` 的 R 参考一一对应：

- 页面尺寸 `size = [宽 in, 高 in]`，面板就是整页（没有轴、图例、边距）；
- `limits` 给定时按 `expand = c(0, 0)` 线性映射，不给则按 ggplot2 的 5% 扩张；
- 颜色由 `palette` 显式给出，R 侧用同值的 `scale_*_manual()`，不做调色板推导；
- 坐标一律写 pt（y 向下），图层按给出顺序绘制。

案例库之外的绘制走设备自己的入口（`pixi run render --scene …`），不经过这里。

模块必须在 X1 白名单内：只用标准库 + numpy + `ggcore` 自身。
"""

from __future__ import annotations

import importlib.util
import inspect
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ggcore import ir
from ggcore.grobs import (
    curve_grob,
    points_grob,
    rect_grob,
    scene,
    text_grob,
)
from ggcore.units import Metrics, unit
from ggcore.viewport import NA, Device, ViewportTree, gpar, viewport

__all__ = [
    "DEFAULT_EXPAND",
    "DEFAULT_SIZE_IN",
    "GEOMS",
    "PLOT_FILE",
    "PlotSpecError",
    "build_scene",
    "load_plot",
    "resolve_limits",
]

PLOT_FILE = "plot.py"
#: 4×3 in / 288×216 pt：与 R 侧 `svglite(width = 4, height = 3)` 同一张纸。
DEFAULT_SIZE_IN = (4.0, 3.0)
#: ggplot2 continuous scale 的缺省扩张（mult = 0.05）。
DEFAULT_EXPAND = 0.05
#: 案例库支持的 layer 类型（R 侧 `tools/refs/cases_ref.R` 一一对应）。
GEOMS = frozenset({"point", "bar", "col", "text", "curve"})
#: ggplot2 的缺省字体（R 侧 theme_void + `family = "Noto Sans CJK SC"`）。
DEFAULT_FAMILY = "Noto Sans CJK SC"
#: 缺省前景色（ggplot2 的 `colour = "black"`）。
DEFAULT_COLOUR = "#000000"
#: 缺省填充色（`geom_col` 的 `fill = "grey35"`）。
DEFAULT_FILL = "#595959"


class PlotSpecError(ValueError):
    """plot 规格不满足契约（`cases:matrix` 会把消息记成 `invalid`）。"""


@dataclass(frozen=True, slots=True)
class BuildResult:
    """`plot.py` 的 `build()` 结果 + 来源目录（报错时好定位）。"""

    spec: Mapping[str, Any]
    directory: Path


# ---------------------------------------------------------------------------
# 读 plot.py
# ---------------------------------------------------------------------------


def load_plot(directory: str | Path, *, metrics: Any = None) -> Mapping[str, Any]:
    """在独立模块里执行 `<directory>/plot.py`，调用 `build()` 并返回规格。

    与 `tools/cases/matrix.py` 的静态校验同一份契约，但这里只在渲染时调用：
    导入失败 / 没有 `build()` / 返回值不是映射都折成 :class:`PlotSpecError`。

    `metrics` 只在 `build()` 显式接受同名参数时传进去：裸 grob / gtable 这类
    快照的版面（比如 `check.overlap` 要按真实字宽决定保留哪些标签）必须用设备
    的字体度量算，不能退回估算。老 case 的 `build()` 不接受它，行为不变。
    """
    path = Path(directory)
    if path.is_file():  # 直接给了 plot.py
        path = path.parent
    plot_file = path / PLOT_FILE
    if not plot_file.is_file():
        raise PlotSpecError(f"{plot_file} 不存在")

    module_name = "gg4py_plotspec_" + re.sub(r"\W", "_", path.resolve().name)
    spec = importlib.util.spec_from_file_location(module_name, plot_file)
    if spec is None or spec.loader is None:  # pragma: no cover - 只在文件不可读时发生
        raise PlotSpecError(f"{plot_file} 无法作为模块加载")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # 契约错误要带类型与消息，别只留 traceback
        raise PlotSpecError(f"{PLOT_FILE} 导入失败：{type(exc).__name__}: {exc}") from exc
    finally:
        sys.modules.pop(module_name, None)

    builder = getattr(module, "build", None)
    if not callable(builder):
        raise PlotSpecError(f"{PLOT_FILE} 必须定义 `build()` 并返回 plot 规格 dict")
    try:
        result = builder(metrics=metrics) if _takes_metrics(builder) else builder()
    except Exception as exc:
        raise PlotSpecError(
            f"{PLOT_FILE} 的 `build()` 抛异常：{type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(result, Mapping):
        raise PlotSpecError(f"`build()` 必须返回 dict，实际是 {type(result).__name__}")
    return result


def _takes_metrics(builder: Any) -> bool:
    """`build()` 是否声明了 `metrics` 参数（`build(metrics=None)`）。"""
    try:
        parameters = inspect.signature(builder).parameters
    except (TypeError, ValueError):  # pragma: no cover - 内置/包装函数
        return False
    return "metrics" in parameters


# ---------------------------------------------------------------------------
# 规格规整
# ---------------------------------------------------------------------------


def _size_in(spec: Mapping[str, Any]) -> tuple[float, float]:
    raw = spec.get("size", DEFAULT_SIZE_IN)
    if (
        not isinstance(raw, Sequence)
        or isinstance(raw, (str, bytes))
        or len(raw) != 2
        or not all(isinstance(item, (int, float)) and math.isfinite(float(item)) for item in raw)
    ):
        raise PlotSpecError(f"`size` 必须是 [宽 in, 高 in] 两个正数，收到 {raw!r}")
    width, height = float(raw[0]), float(raw[1])
    if width <= 0 or height <= 0:
        raise PlotSpecError(f"`size` 必须为正，收到 {raw!r}")
    return width, height


def _layers(spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    layers = spec.get("layers")
    if not isinstance(layers, Sequence) or isinstance(layers, (str, bytes)) or not layers:
        raise PlotSpecError("`layers` 必须是非空数组")
    result: list[Mapping[str, Any]] = []
    for index, layer in enumerate(layers):
        if not isinstance(layer, Mapping):
            raise PlotSpecError(f"layers[{index}] 必须是 dict")
        geom = layer.get("geom")
        if not isinstance(geom, str) or geom not in GEOMS:
            raise PlotSpecError(
                f"layers[{index}].geom 必须是 {', '.join(sorted(GEOMS))} 之一，收到 {geom!r}"
            )
        result.append(layer)
    return result


def _data(spec: Mapping[str, Any]) -> Mapping[str, Any]:
    data = spec.get("data")
    if not isinstance(data, Mapping) or not data:
        raise PlotSpecError("`data` 必须是非空映射（列名 → 数组）")
    for name, values in data.items():
        _array(name, values)
    return data


def _array(name: str, values: Any) -> np.ndarray[Any, Any]:
    """列 → 一维 float/object 数组；DataFrame-like（有 `__getitem__`）也收。"""
    if hasattr(values, "to_numpy") and not isinstance(values, (list, tuple)):
        values = values.to_numpy()
    arr = np.asarray(values)
    if arr.ndim != 1:
        raise PlotSpecError(f"列 {name!r} 必须是一维数组，实际是 {arr.shape}")
    return arr


def _column(data: Mapping[str, Any], name: str) -> np.ndarray[Any, Any]:
    if name not in data:
        raise PlotSpecError(f"`data` 里没有列 {name!r}（有：{', '.join(map(str, data))}）")
    return _array(name, data[name])


def _mapping(spec: Mapping[str, Any], layer: Mapping[str, Any]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for source in (spec.get("mapping", {}), layer.get("mapping", {})):
        if not isinstance(source, Mapping):
            raise PlotSpecError("`mapping` 必须是 dict")
        for key, value in source.items():
            if not isinstance(value, str):
                raise PlotSpecError(f"mapping[{key!r}] 必须是列名（字符串），收到 {value!r}")
            merged[str(key)] = value
    return merged


def _column_or_constant(
    data: Mapping[str, Any],
    mapping: Mapping[str, str],
    aes: str,
    params: Mapping[str, Any],
    *,
    count: int,
    default: Any = None,
) -> Any:
    """`aes` 里的列名优先，其次 layer.params 的同名常量，最后 `default`。"""
    if aes in mapping:
        return _column(data, mapping[aes])
    if aes in params:
        return params[aes]
    return default


def _values(values: Any, count: int, name: str) -> list[Any]:
    """把列 / 常量摊成 `count` 个元素（R 的模回收）。"""
    arr = np.asarray(values)
    if arr.ndim == 0:
        return [arr.item()] * count
    if arr.shape[0] == 1:
        return [arr[0].item()] * count
    if arr.shape[0] != count:
        raise PlotSpecError(f"{name} 长度 {arr.shape[0]} 与数据行数 {count} 不一致")
    return [item for item in arr.tolist()]


def _numeric(values: Any, count: int, name: str) -> np.ndarray[Any, Any]:
    try:
        arr = np.asarray(_values(values, count, name), dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise PlotSpecError(f"{name} 必须是数值：{exc}") from exc
    if not np.all(np.isfinite(arr)):
        raise PlotSpecError(f"{name} 里有非有限值（NaN / Inf）")
    return arr


# ---------------------------------------------------------------------------
# limits
# ---------------------------------------------------------------------------


def _extent(values: Sequence[np.ndarray[Any, Any]]) -> tuple[float, float] | None:
    finite = [item[np.isfinite(item)] for item in values if np.size(item)]
    if not finite:
        return None
    low = min(float(item.min()) for item in finite)
    high = max(float(item.max()) for item in finite)
    return low, high


def _expand(low: float, high: float, expand: float = DEFAULT_EXPAND) -> tuple[float, float]:
    """ggplot2 continuous scale 的缺省扩张；零跨度时给 ±1，避免除零。"""
    span = high - low
    if span == 0:
        return low - 1.0, high + 1.0
    return low - span * expand, high + span * expand


def resolve_limits(spec: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    """x / y 的显示范围：显式 `limits` 优先，否则按数据范围加 5%。

    显式 limits 等价于 R 侧的 `scale_*_continuous(limits = ..., expand = c(0, 0))`。
    """
    raw = spec.get("limits", {})
    if not isinstance(raw, Mapping):
        raise PlotSpecError("`limits` 必须是 `{x = [lo, hi], y = [lo, hi]}`")
    axes: dict[str, list[np.ndarray[Any, Any]]] = {"x": [], "y": []}
    data = _data(spec)
    for layer in _layers(spec):
        mapping = _mapping(spec, layer)
        params = layer.get("params", {})
        count = _layer_count(data, mapping, layer)
        geom = str(layer["geom"])
        for axis in ("x", "y"):
            values = _numeric(
                _column_or_constant(data, mapping, axis, params, count=count), count, axis
            )
            axes[axis].append(values)
        if geom == "curve":
            for axis in ("xend", "yend"):
                values = _numeric(
                    _column_or_constant(data, mapping, axis, params, count=count), count, axis
                )
                axes[axis[0]].append(values)
        if geom in ("bar", "col") and "ymin" in mapping:
            axes["y"].append(_numeric(_column(data, mapping["ymin"]), count, "ymin"))

    limits: dict[str, tuple[float, float]] = {}
    for axis in ("x", "y"):
        if axis in raw:
            pair = raw[axis]
            if (
                not isinstance(pair, Sequence)
                or isinstance(pair, (str, bytes))
                or len(pair) != 2
                or not all(isinstance(item, (int, float)) for item in pair)
            ):
                raise PlotSpecError(f"`limits.{axis}` 必须是 [lo, hi] 两个数，收到 {pair!r}")
            low, high = float(pair[0]), float(pair[1])
            if not low < high:
                raise PlotSpecError(f"`limits.{axis}` 必须 lo < hi，收到 {pair!r}")
            limits[axis] = (low, high)
            continue
        extent = _extent(axes[axis])
        if extent is None:
            raise PlotSpecError(f"没有可推断的 {axis} 范围（数据为空？）")
        limits[axis] = _expand(*extent)
    return limits


def _layer_count(
    data: Mapping[str, Any], mapping: Mapping[str, str], layer: Mapping[str, Any]
) -> int:
    """一层的行数：优先 x 列，其次任一映射列的长度。"""
    if "x" in mapping:
        return int(_column(data, mapping["x"]).shape[0])
    for column in mapping.values():
        return int(_column(data, column).shape[0])
    params = layer.get("params", {})
    for key in ("x", "y"):
        if key in params:
            return int(np.asarray(params[key]).shape[0] if np.ndim(params[key]) else 1)
    raise PlotSpecError(f"layer {layer.get('geom')!r} 既没有映射也没有坐标参数")


# ---------------------------------------------------------------------------
# 画：plot 规格 → grob → 扁平场景 → IR
# ---------------------------------------------------------------------------


def _palette(spec: Mapping[str, Any], layer: Mapping[str, Any]) -> dict[str, str]:
    palette: dict[str, str] = {}
    for source in (spec.get("palette", {}), layer.get("params", {}).get("palette", {})):
        if not isinstance(source, Mapping):
            raise PlotSpecError("`palette` 必须是 {类别: 颜色} 的映射")
        palette.update({str(key): str(value) for key, value in source.items()})
    return palette


def _colour(
    values: Any, count: int, name: str, palette: Mapping[str, str], default: str
) -> list[str]:
    resolved: list[str] = []
    for value in _values(values, count, name):
        key = str(value)
        if palette:
            if key not in palette:
                raise PlotSpecError(f"{name} 的取值 {key!r} 不在 `palette` 里（{sorted(palette)}）")
            resolved.append(palette[key])
        elif isinstance(value, str):
            resolved.append(value)
        else:
            raise PlotSpecError(f"{name} 不是字符串，且没有 `palette`")
    return resolved or [default] * count


def _aes_colours(
    data: Mapping[str, Any],
    mapping: Mapping[str, str],
    params: Mapping[str, Any],
    palette: Mapping[str, str],
    aes: str,
    count: int,
    default: str,
) -> list[str]:
    """`colour` / `fill`：映射到列时查 `palette`，`params` 里给的是字面颜色。"""
    if aes in mapping:
        return _colour(_column(data, mapping[aes]), count, aes, palette, default)
    if aes in params:
        raw = params[aes]
        values = _values(raw, count, aes)
        return [str(item) for item in values]
    return [default] * count


def _finite_float(params: Mapping[str, Any], name: str, default: float) -> float:
    value = params.get(name, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise PlotSpecError(f"`{name}` 必须是有限数值，收到 {value!r}")
    return float(value)


def _int_param(params: Mapping[str, Any], name: str, default: int) -> int:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PlotSpecError(f"`{name}` 必须是 >= 1 的整数，收到 {value!r}")
    return int(value)


class _Painter:
    """页内坐标换算 + 逐层落 grob（面板 = 整页，y 向下）。"""

    def __init__(
        self, width_in: float, height_in: float, limits: Mapping[str, tuple[float, float]]
    ):
        self.width_in = width_in
        self.height_in = height_in
        self.width_pt = width_in * 72.0
        self.height_pt = height_in * 72.0
        self.limits = dict(limits)

    def x_pt(self, values: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        low, high = self.limits["x"]
        return (values - low) / (high - low) * self.width_pt

    def y_pt(self, values: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        # grob 的本地坐标是 R 口径（y 向上），视口遍历时会翻成页面 y 向下。
        low, high = self.limits["y"]
        return (values - low) / (high - low) * self.height_pt


def _gp_colour(colour: str, **extra: Any) -> Any:
    return gpar(col=colour, **extra)


def build_scene(spec: Mapping[str, Any], *, metrics: Metrics | None = None) -> ir.Scene:
    """plot 规格 → `ggcore.ir.Scene`（float32、y 向下、单位 pt）。

    四种规格形态：

    - `{"plot": ggplot(...), "size": [...]}`：走 M1-7 的真管线
      （`build_plot()` + `ggcore.geom.scene.scene_from_build()`），语法层与绘制
      契约都是生产路径；
    - `{"grob": <grid grob>, "size": [...]}`：裸 grob 快照（`grid.newpage()` +
      `grid.draw()` 那种），整页一个视口；
    - `{"gtable": <GTable>, "size": [...]}`：裸 gtable 快照（`plot(gt)` 那种）。
      与 `{"grob": …}` 同一条渲染腿——gtable 本身就是 grob，`scene()` 认它；
      单独一支是为了让契约校验报出「这是 gtable，不是普通 grob」；
    - `{"data": ..., "layers": [...]}`：M0-9 的最小适配层（仍服务老 case）。
    """
    if "plot" in spec:
        from ggcore.geom.scene import scene_from_plot

        width_in, height_in = _size_in(spec)
        return scene_from_plot(
            spec["plot"], width_in=width_in, height_in=height_in, metrics=metrics
        )
    width_in, height_in = _size_in(spec)
    if "grob" in spec or "gtable" in spec:
        # 裸 grob 快照（`grid.newpage(); grid.draw(g)`）：不经 ggplot 管线，直接把
        # 一个 grid grob / gtable 画在整页上（`theme/point-elements`、
        # `guide-axis/axis-guides-check-overlap` 这类快照就是它）。
        item = spec["gtable"] if "gtable" in spec else spec["grob"]
        tree = ViewportTree(Device(width_in, height_in), metrics=metrics)
        tree.push(
            viewport(
                "page",
                x=0.5,
                y=0.5,
                width=1.0,
                height=1.0,
                clip="off",
                gp=gpar(fontsize=12.0, fontfamily=""),
            )
        )
        return scene([item], tree).to_ir_scene()
    data = _data(spec)
    layers = _layers(spec)
    limits = resolve_limits(spec)
    painter = _Painter(width_in, height_in, limits)

    tree = ViewportTree(Device(width_in, height_in), metrics=metrics)
    page = viewport(
        "page",
        x=0.5,
        y=0.5,
        width=1.0,
        height=1.0,
        clip="off",
        gp=gpar(fontsize=11.0, fontfamily=DEFAULT_FAMILY),
    )
    tree.push(page)
    grobs: list[Any] = []
    for layer in layers:
        grobs.extend(_layer_grobs(spec, layer, data, painter))
    return scene(grobs, tree).to_ir_scene()


def _layer_grobs(
    spec: Mapping[str, Any],
    layer: Mapping[str, Any],
    data: Mapping[str, Any],
    painter: _Painter,
) -> list[Any]:
    geom = str(layer["geom"])
    mapping = _mapping(spec, layer)
    params = layer.get("params", {})
    if not isinstance(params, Mapping):
        raise PlotSpecError("layer 的 `params` 必须是 dict")
    count = _layer_count(data, mapping, layer)
    palette = _palette(spec, layer)

    x = _numeric(_column_or_constant(data, mapping, "x", params, count=count), count, "x")
    y = _numeric(_column_or_constant(data, mapping, "y", params, count=count), count, "y")
    x_pt = painter.x_pt(x)
    y_pt = painter.y_pt(y)

    if geom == "point":
        colours = _aes_colours(data, mapping, params, palette, "colour", count, DEFAULT_COLOUR)
        size_pt = _finite_float(params, "size_pt", 7.0)
        alpha = _finite_float(params, "alpha", 1.0)
        out: list[Any] = []
        for index in range(count):
            out.append(
                points_grob(
                    unit(float(x_pt[index]), "bigpts"),
                    unit(float(y_pt[index]), "bigpts"),
                    pch=19,
                    size=unit(size_pt, "bigpts"),
                    size_units="bigpts",
                    gp=_gp_colour(colours[index], fill=colours[index], lwd=0.0, alpha=alpha),
                )
            )
        return out

    if geom in ("bar", "col"):
        fills = _aes_colours(data, mapping, params, palette, "fill", count, DEFAULT_FILL)
        width = _finite_float(params, "width", 0.9)
        base = (
            _numeric(_column(data, mapping["ymin"]), count, "ymin")
            if "ymin" in mapping
            else np.zeros(count, dtype=np.float64)
        )
        low_limit, high_limit = painter.limits["x"]
        dx_pt = width / (high_limit - low_limit) * painter.width_pt
        base_pt = painter.y_pt(base)
        rects: list[Any] = []
        for index in range(count):
            x0 = float(x_pt[index]) - dx_pt / 2.0
            x1 = float(x_pt[index]) + dx_pt / 2.0
            low, high = sorted((float(y_pt[index]), float(base_pt[index])))
            rects.append(
                rect_grob(
                    x=(x0 + x1) / 2.0,
                    y=(low + high) / 2.0,
                    width=x1 - x0,
                    height=high - low,
                    just="centre",
                    default_units="bigpts",
                    gp=gpar(fill=fills[index], col=NA),
                )
            )
        return rects

    if geom == "text":
        labels = _labels(data, mapping, params, count)
        colours = _aes_colours(data, mapping, params, palette, "colour", count, DEFAULT_COLOUR)
        size_pt = _finite_float(params, "size_pt", 11.0)
        hjust = _finite_float(params, "hjust", 0.5)
        vjust = _finite_float(params, "vjust", 0.5)
        family = _text_param(params, "family", DEFAULT_FAMILY)
        font = _font_int(_text_param(params, "fontface", "plain"))
        lineheight = _finite_float(params, "lineheight", 1.2)
        out = []
        for index in range(count):
            out.append(
                text_grob(
                    labels[index],
                    unit(float(x_pt[index]), "bigpts"),
                    unit(float(y_pt[index]), "bigpts"),
                    hjust=hjust,
                    vjust=vjust,
                    default_units="bigpts",
                    gp=gpar(
                        col=colours[index],
                        fontsize=size_pt,
                        fontfamily=family,
                        font=font,
                        lineheight=lineheight,
                    ),
                )
            )
        return out

    # curve
    xend = _numeric(_column_or_constant(data, mapping, "xend", params, count=count), count, "xend")
    yend = _numeric(_column_or_constant(data, mapping, "yend", params, count=count), count, "yend")
    colours = _aes_colours(data, mapping, params, palette, "colour", count, DEFAULT_COLOUR)
    curvature = _finite_float(params, "curvature", 0.5)
    angle = _finite_float(params, "angle", 90.0)
    ncp = _int_param(params, "ncp", 5)
    lwd = _finite_float(params, "lwd", 0.5)
    xend_pt = painter.x_pt(xend)
    yend_pt = painter.y_pt(yend)
    curves: list[Any] = []
    for index in range(count):
        curves.append(
            curve_grob(
                unit(float(x_pt[index]), "bigpts"),
                unit(float(y_pt[index]), "bigpts"),
                unit(float(xend_pt[index]), "bigpts"),
                unit(float(yend_pt[index]), "bigpts"),
                curvature=curvature,
                angle=angle,
                ncp=ncp,
                square=False,
                default_units="bigpts",
                gp=gpar(col=colours[index], fill=NA, lwd=lwd),
            )
        )
    return curves


def _labels(
    data: Mapping[str, Any], mapping: Mapping[str, str], params: Mapping[str, Any], count: int
) -> list[str]:
    if "label" in mapping:
        raw = _column(data, mapping["label"])
    elif "labels" in params:
        raw = params["labels"]
    elif "label" in params:
        raw = params["label"]
    else:
        raise PlotSpecError("text layer 需要 `mapping.label` 或 `params.labels`")
    return [str(item) for item in _values(raw, count, "label")]


#: ggplot2 的 `fontface` 字符串 → gpar 的 `font` 整数（R `validGP()` 的口径）。
_FONT_FACES: dict[str, int] = {
    "plain": 1,
    "normal": 1,
    "bold": 2,
    "italic": 3,
    "oblique": 3,
    "bold.italic": 4,
    "bolditalic": 4,
}


def _text_param(params: Mapping[str, Any], name: str, default: str) -> str:
    value = params.get(name, default)
    if not isinstance(value, str) or not value:
        raise PlotSpecError(f"`{name}` 必须是非空字符串，收到 {value!r}")
    return value


def _font_int(fontface: str) -> int:
    face = fontface.strip().lower()
    if face not in _FONT_FACES:
        raise PlotSpecError(
            f"`fontface` 必须是 {', '.join(sorted(_FONT_FACES))} 之一，收到 {fontface!r}"
        )
    return _FONT_FACES[face]
