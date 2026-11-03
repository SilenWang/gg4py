"""IR v0 · 节点类型表。

IR 承载的是**已解析几何**：单位换算、gpar 继承、视口变换、字体度量都在写 IR
之前完成。节点里只留最终坐标、最终颜色、最终文本宽度，因此：

- bulk 数据（顶点、控制点、矩形）一律是 C 连续的 float32 缓冲（`numpy.float32`
  的 `bytes` 上线），分组标记用 int32，禁止逐元素 JSON；
- 容器（`viewport` / `gtree` / `clip`）按子节点顺序绘制，先出现先画（自后向前）；
- gpar 不再继承：每个可绘制节点带的就是解析后的最终值，容器不携带 gpar。

`NODE_SPECS` 是这张表本身：编码、解码、构造校验都从它取字段清单，`docs/notes/ir.md`
里的节点表也由它派生。改字段先改这里，再改文档。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

import numpy as np

from ggcore.ir.errors import IRValidationError

# 线格式固定小端（x86 / ARM 都是 LE；大端机器不在支持范围，写死比隐式转换好排查）。
F32 = np.dtype("<f4")
I32 = np.dtype("<i4")

WIRE_DTYPES: Mapping[str, np.dtype[Any]] = {"f4": F32, "i4": I32}
DTYPE_WIRE: Mapping[np.dtype[Any], str] = {F32: "f4", I32: "i4"}

DEFAULT_MIME = "application/octet-stream"
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

#: `int` 参数的线格式范围，端点包含。canonical CBOR 的 major 0/1 最多写 64 位；
#: 再大就要 bignum tag（2/3），而 IR 线格式不写 tag，浏览器侧的纯 Python 编码器
#: 也不实现它。所以这不是业务上界，而是**编解码口径**：超出范围在构造节点时就拒绝，
#: 免得 CPython 能写、Pyodide 写不出来（docs/notes/pyodide.md §7）。
INT_MIN = -(1 << 64)
INT_MAX = (1 << 64) - 1


# ---------------------------------------------------------------------------
# 缓冲：bulk 数据的唯一形态
# ---------------------------------------------------------------------------


def _frozen_view(arr: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    # view() 是新的 ndarray 对象，改它的 writeable 标志不影响调用方手里的数组。
    view = arr.view()
    view.setflags(write=False)
    return view


def f32(values: Any) -> np.ndarray[Any, Any]:
    """转成 C 连续的只读 float32 缓冲（几何顶点、宽度、矩形都用它）。

    输入是 float64 / Python list 时在这里一次性舍入到 float32——这是 IR 的精度
    口径：写进去的是 float32，读出来的逐位相同，不做第二次舍入。
    """
    arr = np.asarray(values)
    if arr.dtype != F32:
        arr = arr.astype(F32)
    return _frozen_view(np.ascontiguousarray(arr))


def i32(values: Any) -> np.ndarray[Any, Any]:
    """转成 C 连续的只读 int32 缓冲（分组 id 用）。"""
    arr = np.asarray(values)
    if arr.dtype != I32:
        arr = arr.astype(I32)
    return _frozen_view(np.ascontiguousarray(arr))


def buffer_equal(a: np.ndarray[Any, Any], b: np.ndarray[Any, Any]) -> bool:
    """缓冲逐位相等：dtype、形状、原始字节都要一样（不是 allclose）。"""
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class NodeKind(StrEnum):
    """节点种类，共 18 种：3 个容器（`viewport` / `gtree` / `clip`）+ 15 个叶子
    （13 种可绘制原语 + `null` + `zero`）。

    `ggcore.grobs.Scene.to_ir_scene()` 只产出其中 14 种（13 种可绘制原语 +
    `viewport`）：`null` / `zero` 只有布局语义，`gtree` / `clip` 是遍历容器，
    都不从 grob 路径来（`docs/notes/grobs.md` §1）。
    """

    # 容器
    VIEWPORT = "viewport"
    GTREE = "gtree"
    CLIP = "clip"
    # 原语（M0-6 名单）
    RECT = "rect"
    CIRCLE = "circle"
    LINES = "lines"
    SEGMENTS = "segments"
    POLYLINE = "polyline"
    POLYGON = "polygon"
    PATH = "path"
    POINTS = "points"
    TEXT = "text"
    RASTER = "raster"
    XSPLINE = "xspline"
    BEZIER = "bezier"
    CURVE = "curve"
    NULL = "null"
    # 零尺寸 grob：参与布局，不产出绘制指令
    ZERO = "zero"


class Anchor(StrEnum):
    """文本的水平锚定方式：`pos` 指的是文本的哪一边。"""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class Baseline(StrEnum):
    """文本的竖直锚定方式（不是数值基线偏移）。"""

    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"
    ALPHABETIC = "alphabetic"


class FillRule(StrEnum):
    WINDING = "winding"
    EVENODD = "evenodd"


class ArrowEnds(StrEnum):
    """箭头画在哪个端点（`grid::arrow(ends =)`）；`none` = 不画。"""

    NONE = "none"
    FIRST = "first"
    LAST = "last"
    BOTH = "both"


class ArrowType(StrEnum):
    """箭头形状：`open` 是两条边，`closed` 是填色三角（`grid::arrow(type =)`）。"""

    OPEN = "open"
    CLOSED = "closed"


class LineEnd(StrEnum):
    BUTT = "butt"
    ROUND = "round"
    SQUARE = "square"


class LineJoin(StrEnum):
    MITER = "miter"
    ROUND = "round"
    BEVEL = "bevel"


# ---------------------------------------------------------------------------
# gpar：解析后的图形参数
# ---------------------------------------------------------------------------

Color = tuple[int, int, int, int]


def _colour(value: Any, field_name: str) -> Color:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 4:
        raise IRValidationError(f"gpar.{field_name} 必须是 (r, g, b, a) 四元组，收到 {value!r}")
    channels: list[int] = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 255:
            raise IRValidationError(
                f"gpar.{field_name} 的分量必须是 0..255 的整数，收到 {channel!r}"
            )
        channels.append(channel)
    return (channels[0], channels[1], channels[2], channels[3])


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IRValidationError(f"{field_name} 必须是数值，收到 {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise IRValidationError(f"{field_name} 必须是有限值，收到 {value!r}")
    return number


@dataclass(frozen=True)
class Gpar:
    """一个节点的最终图形参数（继承已经在写 IR 之前算完）。

    缺省值就是“什么都不画”：`col` / `fill` 为 None 表示不描边 / 不填充。颜色是
    8 位 RGBA（`col2rgb` 的舍入在写 IR 前完成）；`lwd` 单位 pt，虚线 `lty` 是
    已经按 `lwd` 折算好的 pt 段长（空元组 = 实线）。
    """

    fill: Color | None = None
    col: Color | None = None
    lwd: float = 1.0
    lty: tuple[float, ...] = ()
    lineend: LineEnd = LineEnd.ROUND
    linejoin: LineJoin = LineJoin.ROUND
    linemitre: float = 1.0
    alpha: float = 1.0

    def __post_init__(self) -> None:
        if self.fill is not None:
            object.__setattr__(self, "fill", _colour(self.fill, "fill"))
        if self.col is not None:
            object.__setattr__(self, "col", _colour(self.col, "col"))
        lwd = _finite(self.lwd, "gpar.lwd")
        if lwd < 0:
            raise IRValidationError(f"gpar.lwd 不能为负，收到 {lwd!r}")
        object.__setattr__(self, "lwd", lwd)
        if isinstance(self.lty, str) or not isinstance(self.lty, Sequence):
            raise IRValidationError(f"gpar.lty 必须是段长序列，收到 {self.lty!r}")
        dashes = tuple(_finite(segment, "gpar.lty") for segment in self.lty)
        if any(segment < 0 for segment in dashes):
            raise IRValidationError(f"gpar.lty 的段长不能为负，收到 {dashes!r}")
        object.__setattr__(self, "lty", dashes)
        if not isinstance(self.lineend, LineEnd):
            raise IRValidationError(f"gpar.lineend 不认识：{self.lineend!r}")
        if not isinstance(self.linejoin, LineJoin):
            raise IRValidationError(f"gpar.linejoin 不认识：{self.linejoin!r}")
        linemitre = _finite(self.linemitre, "gpar.linemitre")
        if linemitre < 1:
            raise IRValidationError(f"gpar.linemitre 不能小于 1，收到 {linemitre!r}")
        object.__setattr__(self, "linemitre", linemitre)
        alpha = _finite(self.alpha, "gpar.alpha")
        if not 0.0 <= alpha <= 1.0:
            raise IRValidationError(f"gpar.alpha 必须在 [0, 1]，收到 {alpha!r}")
        object.__setattr__(self, "alpha", alpha)


# 字段顺序即线格式顺序（canonical CBOR 会再排序，这里只用作“哪些字段是缺省”的来源）。
GPAR_FIELDS: tuple[tuple[str, Any], ...] = (
    ("fill", None),
    ("col", None),
    ("lwd", 1.0),
    ("lty", ()),
    ("lineend", LineEnd.ROUND),
    ("linejoin", LineJoin.ROUND),
    ("linemitre", 1.0),
    ("alpha", 1.0),
)


# ---------------------------------------------------------------------------
# 字段描述表
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BufferSpec:
    """一个缓冲字段：dtype、每行分量数（None = 一维）、是否必填。"""

    name: str
    dtype: str = "f4"
    cols: int | None = None
    required: bool = True
    note: str = ""

    @property
    def np_dtype(self) -> np.dtype[Any]:
        return WIRE_DTYPES[self.dtype]

    def check(self, kind: NodeKind, arr: Any) -> np.ndarray[Any, Any]:
        if not isinstance(arr, np.ndarray):
            raise IRValidationError(
                f"{kind}.{self.name} 必须是 numpy 数组（用 ggcore.ir.f32 / i32 构造），"
                f"收到 {type(arr).__name__}"
            )
        if arr.dtype != self.np_dtype:
            raise IRValidationError(
                f"{kind}.{self.name} 的 dtype 必须是 {self.dtype}（{self.np_dtype}），"
                f"收到 {arr.dtype}；用 ggcore.ir.f32 / i32 转换"
            )
        if not arr.flags.c_contiguous:
            raise IRValidationError(f"{kind}.{self.name} 必须是 C 连续缓冲")
        expected_ndim = 1 if self.cols is None else 2
        if arr.ndim != expected_ndim:
            raise IRValidationError(
                f"{kind}.{self.name} 必须是 {expected_ndim} 维"
                f"（{'一维' if self.cols is None else f'(n, {self.cols})'}），"
                f"收到 shape={arr.shape}"
            )
        if self.cols is not None and arr.shape[1] != self.cols:
            raise IRValidationError(
                f"{kind}.{self.name} 每行必须是 {self.cols} 个分量，收到 shape={arr.shape}"
            )
        return _frozen_view(arr)


#: 参数字段的类型标签 → 校验函数在 `_check_param` 里。
ParamTag = str


@dataclass(frozen=True)
class ParamSpec:
    """一个参数字段：类型标签、缺省值、是否必填，以及数值型的取值域。

    `minimum` / `maximum` 只对 `float` / `int` 标签生效，端点都包含在内；取值域
    和类型一样是**线格式口径**，编码与解码两边共用这份校验。`int` 另有一条
    全局上界 `[INT_MIN, INT_MAX]`（64 位），由 `_check_param` 统一施加。
    """

    name: str
    tag: ParamTag
    default: Any = None
    required: bool = False
    note: str = ""
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class NodeSpec:
    kind: NodeKind
    buffers: tuple[BufferSpec, ...] = ()
    params: tuple[ParamSpec, ...] = ()
    children: bool = False
    gpar: bool = True
    texts: bool = False
    doc: str = ""


_ID_POINTS = BufferSpec("id", "i4", None, required=False, note="每个顶点的分组号，值变化即换子路径")
_POINTS = BufferSpec("points", "f4", 2, note="(n, 2) 顶点：x, y")
_TRANSFORM = ParamSpec("transform", "transform", IDENTITY, note="子坐标 → 父坐标的 2×3 仿射")

#: 箭头标记（M2-S2）：`grid::arrow()` 的四个字段落在**节点参数**上，几何（箭翼往
#: 哪边张开）由设备按端点切向求值——曲线节点的切向只有设备能算（它按 `curvature`
#: / `ncp` 采样），把切向写进 IR 就得让 ggcore 也实现一遍曲线公式。
#: `arrow_length` 是解析后的 pt；`arrow = "none"` 时其余三个字段无意义，编码时按
#: 缺省值省略，所以不带箭头的 scene 字节不变（IR 0.2 → 0.3 只加了字段）。
_ARROW_PARAMS = (
    ParamSpec("arrow", "arrow_ends", ArrowEnds.NONE, note="箭头端点：none/first/last/both"),
    ParamSpec("arrow_length", "float", 0.0, minimum=0.0, note="箭翼长度，pt"),
    ParamSpec("arrow_angle", "float", 30.0, minimum=0.0, maximum=90.0, note="箭翼与轴线夹角，度"),
    ParamSpec("arrow_type", "arrow_type", ArrowType.OPEN, note="open / closed"),
)

NODE_SPECS: Mapping[NodeKind, NodeSpec] = MappingProxyType(
    {
        NodeKind.VIEWPORT: NodeSpec(
            NodeKind.VIEWPORT,
            buffers=(
                BufferSpec(
                    "clip_rect",
                    "f4",
                    4,
                    required=False,
                    note="(x0, y0, x1, y1)，页面绝对坐标 pt；clip=True 时必填",
                ),
            ),
            params=(
                ParamSpec("name", "str", ""),
                ParamSpec("clip", "bool", True, note="裁剪到 clip_rect（页面坐标）"),
                _TRANSFORM,
            ),
            children=True,
            gpar=False,
            doc="视口：变换 + 裁剪 + 子节点。父视口的 gpar 不往下传（IR 里已解析）。",
        ),
        NodeKind.GTREE: NodeSpec(
            NodeKind.GTREE,
            params=(ParamSpec("name", "str", ""),),
            children=True,
            gpar=False,
            doc="纯分组容器：v0 只表达绘制顺序，不带裁剪 / gpar / 布局语义。",
        ),
        NodeKind.CLIP: NodeSpec(
            NodeKind.CLIP,
            buffers=(
                BufferSpec("rect", "f4", 4, required=False, note="(x0, y0, x1, y1) 矩形裁剪"),
                BufferSpec("points", "f4", 2, required=False, note="多边形/多子路径裁剪"),
                _ID_POINTS,
            ),
            params=(
                ParamSpec("name", "str", ""),
                ParamSpec("rule", "fill_rule", FillRule.WINDING),
            ),
            children=True,
            gpar=False,
            doc="任意形状裁剪：rect 与 points 二选一，points 可带 id 分多条子路径。",
        ),
        NodeKind.RECT: NodeSpec(
            NodeKind.RECT,
            buffers=(BufferSpec("rect", "f4", 4, note="(x0, y0, x1, y1)，按对角点归一化"),),
            doc="矩形：每行 (x0, y0, x1, y1)，不要求 x0 < x1。",
        ),
        NodeKind.CIRCLE: NodeSpec(
            NodeKind.CIRCLE,
            buffers=(BufferSpec("circle", "f4", 3, note="(cx, cy, r)，r 在视口单位下"),),
            doc="圆：每行 (cx, cy, r)。椭圆由视口变换表达。",
        ),
        NodeKind.LINES: NodeSpec(
            NodeKind.LINES,
            buffers=(_POINTS, _ID_POINTS),
            doc="折线组：points + 可选 id，id 相同且连续的顶点连成一条线。",
        ),
        NodeKind.SEGMENTS: NodeSpec(
            NodeKind.SEGMENTS,
            buffers=(BufferSpec("segments", "f4", 4, note="(x0, y0, x1, y1) 每行一条线段"),),
            params=_ARROW_PARAMS,
            doc=(
                "线段：每行 (x0, y0, x1, y1)，互不相连；"
                "`arrow*` 是 grid::arrow() 的标记属性（M2-S2）。"
            ),
        ),
        NodeKind.POLYLINE: NodeSpec(
            NodeKind.POLYLINE,
            buffers=(_POINTS, _ID_POINTS),
            params=_ARROW_PARAMS,
            doc=(
                "折线（grid.polyline 对等物）：单条或多条，id 分组规则同 lines；"
                "`arrow*` 按每条子路径的首/末顶点画箭头。"
            ),
        ),
        NodeKind.POLYGON: NodeSpec(
            NodeKind.POLYGON,
            buffers=(_POINTS, _ID_POINTS),
            doc="多边形：points + 可选 id；填充走 gpar.fill。",
        ),
        NodeKind.PATH: NodeSpec(
            NodeKind.PATH,
            buffers=(_POINTS, _ID_POINTS),
            params=(ParamSpec("rule", "fill_rule", FillRule.WINDING),),
            doc="路径（grid.path 对等物）：多条子路径 + 填充规则，对应 SVG 的 path。",
        ),
        NodeKind.POINTS: NodeSpec(
            NodeKind.POINTS,
            buffers=(_POINTS,),
            params=(
                ParamSpec("pch", "int", 1, note="grid pch 编号；形状解析留给设备"),
                ParamSpec("size", "float", 1.0, note="最终尺寸，pt"),
            ),
            doc="散点：每行一个点，pch/size 已解析。",
        ),
        NodeKind.TEXT: NodeSpec(
            NodeKind.TEXT,
            buffers=(
                BufferSpec("pos", "f4", 2, note="(n, 2) 锚点坐标（已按 anchor/baseline 对齐）"),
                BufferSpec("width", "f4", None, note="(n,) 最终文本宽度，pt"),
            ),
            params=(
                ParamSpec("font", "str", required=True, note="已解析的字族 key，不是回退栈"),
                ParamSpec("size", "float", required=True, note="字号，pt"),
                ParamSpec("anchor", "anchor", Anchor.CENTER, note="pos 指文本的哪一边"),
                ParamSpec("baseline", "baseline", Baseline.MIDDLE, note="竖直锚定方式"),
                ParamSpec("angle", "float", 0.0, note="旋转角，度，逆时针"),
            ),
            texts=True,
            doc=(
                "文本：只携带最终宽度与锚点。字体度量、回退切 run 在写 IR 之前完成"
                "（度量账本 L1 / L3），这里不带 font stack、不带测量上下文。"
            ),
        ),
        NodeKind.RASTER: NodeSpec(
            NodeKind.RASTER,
            buffers=(BufferSpec("rect", "f4", 4, note="(x0, y0, x1, y1) 目标矩形"),),
            params=(
                ParamSpec("blob", "str", required=True, note="blob 表里的 id"),
                ParamSpec("width", "int", required=True, minimum=1, note="像素宽（≥1）"),
                ParamSpec("height", "int", required=True, minimum=1, note="像素高（≥1）"),
                ParamSpec("interpolate", "bool", True),
            ),
            doc="位图：像素在 blob 表，节点只说贴到哪、多大、是否插值。",
        ),
        NodeKind.XSPLINE: NodeSpec(
            NodeKind.XSPLINE,
            buffers=(_POINTS, _ID_POINTS),
            params=(
                ParamSpec(
                    "shape",
                    "float",
                    0.0,
                    minimum=-1.0,
                    maximum=1.0,
                    note="-1..1，0 为 Catmull-Rom 样条",
                ),
                ParamSpec("open", "bool", True),
            ),
            doc="xspline：控制点 + 形状参数，曲线由设备按同一公式求出。",
        ),
        NodeKind.BEZIER: NodeSpec(
            NodeKind.BEZIER,
            buffers=(
                BufferSpec(
                    "control",
                    "f4",
                    2,
                    note="(4n, 2) 控制点，每 4 行一段三次贝塞尔",
                ),
            ),
            doc="贝塞尔：每 4 个控制点一段三次曲线（grid.bezier 语义）。",
        ),
        NodeKind.CURVE: NodeSpec(
            NodeKind.CURVE,
            buffers=(BufferSpec("ends", "f4", 4, note="(n, 4) 每行 (x1, y1, x2, y2)"),),
            params=(
                ParamSpec("curvature", "float", 1.0),
                ParamSpec("angle", "float", 90.0),
                ParamSpec("ncp", "int", 1),
                ParamSpec("shape", "float", 0.5),
                ParamSpec("square", "bool", True),
                ParamSpec("inflect", "bool", False),
                ParamSpec("open", "bool", True),
                *_ARROW_PARAMS,
            ),
            doc=(
                "curve：两端点 + 弯曲参数（grid.curve 语义），曲线形状由设备复现；"
                "`arrow*` 的切向由设备按采样后的曲线端点求。"
            ),
        ),
        NodeKind.NULL: NodeSpec(
            NodeKind.NULL,
            gpar=False,
            doc="nullGrob：不画、不占位。",
        ),
        NodeKind.ZERO: NodeSpec(
            NodeKind.ZERO,
            gpar=False,
            doc="zeroGrob：不画，但参与布局（布局信息在写 IR 前已消费）。",
        ),
    }
)

#: 只用容器语义的种类（children 必填字段之外还要和 gpar 二选一）。
CONTAINER_KINDS = frozenset(kind for kind, spec in NODE_SPECS.items() if spec.children)
DRAWABLE_KINDS = frozenset(kind for kind, spec in NODE_SPECS.items() if spec.gpar)

_ENUM_TAGS: Mapping[ParamTag, type[StrEnum]] = {
    "anchor": Anchor,
    "baseline": Baseline,
    "fill_rule": FillRule,
    "arrow_ends": ArrowEnds,
    "arrow_type": ArrowType,
}


def _check_param(kind: NodeKind, spec: ParamSpec, value: Any) -> Any:
    where = f"{kind}.{spec.name}"
    tag = spec.tag
    if tag == "float":
        return _finite(value, where)
    if tag == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise IRValidationError(f"{where} 必须是整数，收到 {value!r}")
        if not INT_MIN <= value <= INT_MAX:
            raise IRValidationError(
                f"{where} 超出 64 位整数范围 [{INT_MIN}, {INT_MAX}]，收到 {value}；"
                "IR 线格式不写 bignum tag，超出范围的值在浏览器里编不出来"
            )
        return value
    if tag == "bool":
        if not isinstance(value, bool):
            raise IRValidationError(f"{where} 必须是布尔值，收到 {value!r}")
        return value
    if tag == "str":
        if not isinstance(value, str):
            raise IRValidationError(f"{where} 必须是字符串，收到 {value!r}")
        return value
    if tag == "transform":
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 6:
            raise IRValidationError(f"{where} 必须是 6 个数的仿射元组，收到 {value!r}")
        return tuple(_finite(component, where) for component in value)
    enum = _ENUM_TAGS.get(tag)
    if enum is None:  # pragma: no cover - 表写错才会走到
        raise IRValidationError(f"{where} 的类型标签不认识：{tag!r}")
    if isinstance(value, enum):
        return value
    if isinstance(value, str):
        try:
            return enum(value)
        except ValueError as exc:
            allowed = ", ".join(member.value for member in enum)
            raise IRValidationError(f"{where} 不认识 {value!r}，可选：{allowed}") from exc
    raise IRValidationError(f"{where} 必须是 {enum.__name__}，收到 {value!r}")


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class Node:
    """一个 IR 节点。字段按 `NODE_SPECS[kind]` 校验，缺省参数在构造时补齐。"""

    kind: NodeKind
    gpar: Gpar | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    bufs: Mapping[str, np.ndarray[Any, Any]] = field(default_factory=dict)
    texts: tuple[str, ...] = ()
    children: tuple[Node, ...] = ()

    def __post_init__(self) -> None:
        kind = self.kind if isinstance(self.kind, NodeKind) else _coerce_kind(self.kind)
        spec = NODE_SPECS[kind]
        object.__setattr__(self, "kind", kind)

        if self.gpar is not None and not isinstance(self.gpar, Gpar):
            raise IRValidationError(f"{kind}.gpar 必须是 Gpar，收到 {type(self.gpar).__name__}")
        if self.gpar is not None and not spec.gpar:
            raise IRValidationError(f"{kind} 是容器/空节点，不携带 gpar")

        object.__setattr__(self, "params", _check_params(kind, spec, self.params))
        object.__setattr__(self, "bufs", _check_buffers(kind, spec, self.bufs))

        texts = tuple(self.texts)
        if texts and not spec.texts:
            raise IRValidationError(f"{kind} 不携带文本")
        for label in texts:
            if not isinstance(label, str):
                raise IRValidationError(f"{kind}.texts 必须是字符串，收到 {label!r}")
        object.__setattr__(self, "texts", texts)

        children = tuple(self.children)
        for child in children:
            if not isinstance(child, Node):
                raise IRValidationError(f"{kind}.children 必须是 Node，收到 {type(child).__name__}")
        if children and not spec.children:
            raise IRValidationError(f"{kind} 是叶子节点，不能有 children")
        object.__setattr__(self, "children", children)

        _check_cross_fields(self, spec)

    # 逐位比较（含浮点 NaN 的位模式）；dataclass 的 __eq__ 会在 numpy 数组上炸。
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Node):
            return NotImplemented
        return node_equal(self, other)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        fields = [f"kind={self.kind.value!r}"]
        changed = _non_default_params(self)
        if changed:
            fields.append(f"params={changed!r}")
        if self.gpar is not None and self.gpar != Gpar():
            fields.append(f"gpar={self.gpar!r}")
        if self.bufs:
            fields.append(f"bufs={{{', '.join(f'{k}: {v.shape}' for k, v in self.bufs.items())}}}")
        if self.texts:
            fields.append(f"texts={self.texts!r}")
        if self.children:
            fields.append(f"children={len(self.children)}")
        return f"Node({', '.join(fields)})"


def _coerce_kind(value: Any) -> NodeKind:
    try:
        return NodeKind(value)
    except ValueError as exc:
        allowed = ", ".join(kind.value for kind in NodeKind)
        raise IRValidationError(f"未知节点种类 {value!r}，可选：{allowed}") from exc


def _check_params(kind: NodeKind, spec: NodeSpec, params: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(params, Mapping):
        raise IRValidationError(f"{kind}.params 必须是映射，收到 {type(params).__name__}")
    known = {field_spec.name for field_spec in spec.params}
    unknown = sorted(set(params) - known)
    if unknown:
        raise IRValidationError(f"{kind} 没有参数 {unknown}；可选：{sorted(known) or '（无）'}")
    resolved: dict[str, Any] = {}
    for field_spec in spec.params:
        if field_spec.name in params:
            value = _check_param(kind, field_spec, params[field_spec.name])
            _check_range(kind, field_spec, value)
            resolved[field_spec.name] = value
        elif field_spec.required:
            raise IRValidationError(f"{kind} 缺少必填参数 {field_spec.name!r}")
        else:
            resolved[field_spec.name] = field_spec.default
    return MappingProxyType(resolved)


def _check_range(kind: NodeKind, spec: ParamSpec, value: Any) -> None:
    """数值参数的取值域（端点包含）；`minimum` / `maximum` 为空表示不限。"""
    if spec.minimum is None and spec.maximum is None:
        return
    where = f"{kind}.{spec.name}"
    if spec.minimum is not None and value < spec.minimum:
        raise IRValidationError(f"{where} 不能小于 {spec.minimum:g}，收到 {value!r}")
    if spec.maximum is not None and value > spec.maximum:
        raise IRValidationError(f"{where} 不能大于 {spec.maximum:g}，收到 {value!r}")


def _check_buffers(
    kind: NodeKind, spec: NodeSpec, bufs: Mapping[str, Any]
) -> Mapping[str, np.ndarray[Any, Any]]:
    if not isinstance(bufs, Mapping):
        raise IRValidationError(f"{kind}.bufs 必须是映射，收到 {type(bufs).__name__}")
    known = {buffer_spec.name: buffer_spec for buffer_spec in spec.buffers}
    unknown = sorted(set(bufs) - set(known))
    if unknown:
        raise IRValidationError(f"{kind} 没有缓冲 {unknown}；可选：{sorted(known) or '（无）'}")
    resolved: dict[str, np.ndarray[Any, Any]] = {}
    for name, buffer_spec in known.items():
        if name in bufs:
            resolved[name] = buffer_spec.check(kind, bufs[name])
        elif buffer_spec.required:
            raise IRValidationError(f"{kind} 缺少必填缓冲 {name!r}")
    return MappingProxyType(resolved)


def _check_cross_fields(node: Node, spec: NodeSpec) -> None:
    kind = node.kind
    if spec.texts:
        rows = int(node.bufs["pos"].shape[0]) if "pos" in node.bufs else 0
        widths = int(node.bufs["width"].shape[0]) if "width" in node.bufs else 0
        if not (len(node.texts) == rows == widths):
            raise IRValidationError(
                f"text 的 texts / pos / width 行数必须一致，"
                f"收到 {len(node.texts)} / {rows} / {widths}"
            )
    if kind is NodeKind.VIEWPORT and node.params["clip"] and "clip_rect" not in node.bufs:
        raise IRValidationError("viewport.clip=True 时必须给 clip_rect（页面坐标裁剪框）")
    if "clip_rect" in node.bufs and node.bufs["clip_rect"].shape[0] != 1:
        raise IRValidationError(
            f"viewport.clip_rect 只能有一行（一个视口一个裁剪框），"
            f"收到 shape={node.bufs['clip_rect'].shape}"
        )
    if kind is NodeKind.CLIP:
        has_rect = "rect" in node.bufs
        has_points = "points" in node.bufs
        if has_rect == has_points:
            raise IRValidationError("clip 必须且只能给 rect 或 points 之一")
        if has_rect and node.bufs["rect"].shape[0] != 1:
            raise IRValidationError(
                f"clip.rect 只能有一行（形状裁剪只表达一个矩形），"
                f"收到 shape={node.bufs['rect'].shape}"
            )
        if "id" in node.bufs:
            if not has_points:
                raise IRValidationError("clip.id 只能和 points 一起给")
            if node.bufs["id"].shape[0] != node.bufs["points"].shape[0]:
                raise IRValidationError("clip.id 的行数必须和 points 一致")
    for buffer_spec in spec.buffers:
        if buffer_spec.name == "id" and "id" in node.bufs:
            points = node.bufs.get("points")
            if points is not None and node.bufs["id"].shape[0] != points.shape[0]:
                raise IRValidationError(
                    f"{kind}.id 的行数必须和 points 一致，"
                    f"收到 {node.bufs['id'].shape[0]} / {points.shape[0]}"
                )
            if points is None and kind is not NodeKind.CLIP:
                raise IRValidationError(f"{kind}.id 只能和 points 一起给")
    if kind is NodeKind.BEZIER:
        rows = int(node.bufs["control"].shape[0])
        if rows % 4:
            raise IRValidationError(
                f"bezier.control 的行数必须是 4 的倍数（每 4 行一段三次贝塞尔），收到 {rows} 行"
            )


def _non_default_params(node: Node) -> dict[str, Any]:
    spec = NODE_SPECS[node.kind]
    changed: dict[str, Any] = {}
    for field_spec in spec.params:
        value = node.params[field_spec.name]
        if value != field_spec.default:
            changed[field_spec.name] = value
    return changed


def walk(node: Node) -> Iterator[Node]:
    """深度优先遍历（先父后子，子节点按绘制顺序）。"""
    yield node
    for child in node.children:
        yield from walk(child)


def node_equal(a: Node, b: Node) -> bool:
    """逐位相等：dtype / shape / 原始字节，参数与 gpar 精确相等。"""
    if a is b:
        return True
    if a.kind != b.kind or a.gpar != b.gpar:
        return False
    if dict(a.params) != dict(b.params):
        return False
    if a.texts != b.texts:
        return False
    if set(a.bufs) != set(b.bufs):
        return False
    for name, left in a.bufs.items():
        if not buffer_equal(left, b.bufs[name]):
            return False
    if len(a.children) != len(b.children):
        return False
    return all(node_equal(left, right) for left, right in zip(a.children, b.children, strict=True))


# ---------------------------------------------------------------------------
# blob 表
# ---------------------------------------------------------------------------


def blob_id(data: bytes, mime: str = DEFAULT_MIME) -> str:
    """内容寻址的 blob id：`sha256(mime + b"\\0" + data)`。

    同一份字节 + 同一个 mime 在任何机器上都得到同一个 id，所以编码是确定性的，
    相同的位图也不会在表里出现两次。
    """
    if not isinstance(mime, str) or not mime:
        raise IRValidationError(f"blob.mime 必须是非空字符串，收到 {mime!r}")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise IRValidationError(f"blob.data 必须是 bytes，收到 {type(data).__name__}")
    digest = hashlib.sha256(mime.encode("utf-8") + b"\0" + bytes(data)).hexdigest()
    return f"sha256:{digest}"


@dataclass(frozen=True)
class Blob:
    """一段不透明的二进制（位图、字体、外部位图缓存）。"""

    data: bytes
    mime: str = DEFAULT_MIME

    def __post_init__(self) -> None:
        if not isinstance(self.data, (bytes, bytearray, memoryview)):
            raise IRValidationError(f"Blob.data 必须是 bytes，收到 {type(self.data).__name__}")
        object.__setattr__(self, "data", bytes(self.data))
        if not isinstance(self.mime, str) or not self.mime:
            raise IRValidationError(f"Blob.mime 必须是非空字符串，收到 {self.mime!r}")


@dataclass(frozen=True)
class BlobTable:
    """id → Blob。编码时按 id 排序写出，所以表内顺序不影响字节。"""

    entries: Mapping[str, Blob] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.entries, Mapping):
            raise IRValidationError(
                f"BlobTable.entries 必须是映射，收到 {type(self.entries).__name__}"
            )
        checked: dict[str, Blob] = {}
        for bid, blob in self.entries.items():
            if not isinstance(bid, str) or not bid:
                raise IRValidationError(f"blob id 必须是非空字符串，收到 {bid!r}")
            if not isinstance(blob, Blob):
                raise IRValidationError(f"blob[{bid!r}] 必须是 Blob，收到 {type(blob).__name__}")
            checked[bid] = blob
        object.__setattr__(self, "entries", MappingProxyType(checked))

    @classmethod
    def empty(cls) -> BlobTable:
        return cls({})

    @classmethod
    def of(cls, *blobs: Blob) -> BlobTable:
        """按内容寻址收表（同一份数据只留一条）。"""
        entries: dict[str, Blob] = {}
        for blob in blobs:
            if not isinstance(blob, Blob):
                raise IRValidationError(f"BlobTable.of 只收 Blob，收到 {type(blob).__name__}")
            entries[blob_id(blob.data, blob.mime)] = blob
        return cls(entries)

    def add(self, data: bytes, mime: str = DEFAULT_MIME) -> tuple[BlobTable, str]:
        """放入一段字节，返回（新表, id）。同一内容重复放是幂等的。"""
        blob = Blob(data, mime)
        bid = blob_id(blob.data, blob.mime)
        if bid in self.entries:
            return self, bid
        entries = dict(self.entries)
        entries[bid] = blob
        return BlobTable(entries), bid

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.entries))

    def __getitem__(self, bid: str) -> Blob:
        return self.entries[bid]

    def __contains__(self, bid: object) -> bool:
        return bid in self.entries

    def __len__(self) -> int:
        return len(self.entries)


# ---------------------------------------------------------------------------
# scene
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class Scene:
    """一张图的根：页面尺寸（pt）+ 根视口 + blob 表。

    `size` 是页面尺寸（pt，`dpi` 只影响栅格化的像素换算）；几何坐标都在根视口的
    坐标空间里，根视口通常 `transform=identity`、`clip=False`。
    """

    root: Node
    size: tuple[float, float] = (640.0, 480.0)
    dpi: float = 72.0
    blobs: BlobTable = field(default_factory=BlobTable.empty)

    def __post_init__(self) -> None:
        if not isinstance(self.root, Node):
            raise IRValidationError(f"Scene.root 必须是 Node，收到 {type(self.root).__name__}")
        if self.root.kind is not NodeKind.VIEWPORT:
            raise IRValidationError("Scene.root 必须是 viewport 节点")
        if isinstance(self.size, (str, bytes)) or not isinstance(self.size, Sequence):
            raise IRValidationError(f"Scene.size 必须是 (width, height)，收到 {self.size!r}")
        if len(self.size) != 2:
            raise IRValidationError(f"Scene.size 必须是 (width, height)，收到 {self.size!r}")
        size = tuple(_finite(value, "Scene.size") for value in self.size)
        if size[0] < 0 or size[1] < 0:
            raise IRValidationError(f"Scene.size 不能为负，收到 {size!r}")
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "dpi", _finite(self.dpi, "Scene.dpi"))
        if self.dpi <= 0:
            raise IRValidationError(f"Scene.dpi 必须为正，收到 {self.dpi!r}")
        if not isinstance(self.blobs, BlobTable):
            raise IRValidationError(
                f"Scene.blobs 必须是 BlobTable，收到 {type(self.blobs).__name__}"
            )
        for node in walk(self.root):
            if node.kind is NodeKind.RASTER:
                bid = node.params["blob"]
                if bid not in self.blobs:
                    raise IRValidationError(f"raster 引用了不存在的 blob {bid!r}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Scene):
            return NotImplemented
        return scene_equal(self, other)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return (
            f"Scene(size={self.size!r}, dpi={self.dpi!r}, "
            f"blobs={len(self.blobs)}, root={self.root!r})"
        )


def scene_equal(a: Scene, b: Scene) -> bool:
    if a is b:
        return True
    if a.size != b.size or a.dpi != b.dpi:
        return False
    if a.blobs.ids() != b.blobs.ids():
        return False
    for bid in a.blobs.ids():
        left, right = a.blobs[bid], b.blobs[bid]
        if left.mime != right.mime or left.data != right.data:
            return False
    return node_equal(a.root, b.root)
