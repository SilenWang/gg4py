"""`ggsave` + IR 导出（M1-12）：一张 `ggplot` → PNG / SVG / PDF，或 `.ggir.cbor` / `.ir.json`。

    from ggio.frame import from_dict
    from ggcore.plot import aes, geom_point, ggplot
    from ggskia import ggsave

    data = from_dict({"x": [1.0, 2.0, 3.0], "y": [3.0, 1.0, 2.0]})
    p = ggplot(data, aes(x="x", y="y")) + geom_point()
    ggsave(p, "out.png", width=7, height=5, dpi=150)   # 1050×750 px

三件事在这里落地：

1. :func:`ggsave` —— 按后缀选设备（`.png` / `.svg` / `.pdf`），`units` 把
   `width` / `height` 换成英寸，页面尺寸以 pt 交给设备。
2. :func:`save_ir` —— 同一张图 → `ggcore.ir.encode()` 写 `.ggir.cbor`
   （`pixi run render --scene …` 与浏览器端读的就是这份字节）。
3. :func:`export_ir_json` —— 同一张图的**调试视图**：节点 id / kind / 非缺省
   参数 / 缓冲摘要（dtype、shape、sha256）。bulk 数据不逐元素展开（X1 门禁
   `gate:ir-json` 守的就是这条），所以 `.ir.json` 画不出图，只给浏览器调试与
   人眼核对用。

分层：本模块只 import 标准库 / numpy / `ggcore`（X1 白名单），设备与字体度量在
包外（`ggskia`，依赖 `skia-python`）。两边靠注册口连接：`ggskia` 在 import 时
调用 :func:`register_backend`，把 `device_for` 与 `ShaperMetrics` 交进来。没注册
后端时 `.cbor` / `.json` 照常写（IR 不需要字体），要 PNG / SVG / PDF 会报一条
能照做的错（装 `ggskia` / 用 `pixi run ggsave`）。

口径 —— 单位换算、缺省值、三路设备的能力差异、`.ir.json` 的用途与体积 —— 见
`docs/notes/io.md`。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ggcore import ir
from ggcore.device import FORMATS, Device
from ggcore.geom.scene import scene_from_plot
from ggcore.units import BIGPOINTS_PER_INCH, CM_PER_INCH

__all__ = [
    "DEFAULT_DPI",
    "DEFAULT_HEIGHT",
    "DEFAULT_WIDTH",
    "GRAPHIC_FORMATS",
    "UNITS",
    "Backend",
    "SaveError",
    "SaveResult",
    "export_ir_json",
    "ggsave",
    "ir_json_view",
    "register_backend",
    "registered_backend",
    "save_ir",
]

#: `ggsave()` 的缺省页面尺寸（英寸）。本任务钉 7×5；与上游 4.0.3 的差异见
#: `docs/notes/io.md` §2（上游在没开设备时是 7×7，`dpi` 缺省 300）。
DEFAULT_WIDTH = 7.0
DEFAULT_HEIGHT = 5.0
#: 缺省 DPI。只决定栅格化的像素换算，不改变几何（`docs/notes/ir.md` §1）。
DEFAULT_DPI = 72.0

#: `width` / `height` 接受的长度单位 → 英寸。别名只做归一化，报告里写规范名。
_UNIT_TO_INCH = {
    "in": 1.0,
    "inch": 1.0,
    "inches": 1.0,
    "cm": 1.0 / CM_PER_INCH,
    "mm": 1.0 / (CM_PER_INCH * 10.0),
    # ggsave 的 `pt` 是**设备 pt**（1/72 in，与 IR / `ggcore.device` 同一把尺），
    # 不是 grid 的 `points`（1/72.27 in TeX pt，见 docs/notes/units.md）。
    "pt": 1.0 / BIGPOINTS_PER_INCH,
}
UNITS: tuple[str, ...] = ("in", "cm", "mm", "pt")

#: `ggsave()` 能直接落盘的格式（后缀 → 设备）。
GRAPHIC_FORMATS: tuple[str, ...] = tuple(sorted(FORMATS))


class SaveError(ValueError):
    """`ggsave` / IR 导出的参数问题（格式、单位、尺寸、设备尺寸不符）。"""


@dataclass(frozen=True, slots=True)
class SaveResult:
    """一次落盘的结果（测试直接断言这些字段，不用读文件反推）。"""

    path: Path
    format: str
    width_in: float
    height_in: float
    #: 页面尺寸（pt），与 `ir.Scene.size` 逐位相等。
    width_pt: float
    height_pt: float
    dpi: float
    units: str
    #: 栅格化的像素尺寸；矢量后端与 IR 导出为 None（`Device.size_px` 的参考值不进结果）。
    size_px: tuple[int, int] | None
    #: 写出的字节数。
    bytes: int
    #: 实际用的设备类名（`ir.Scene` 的两路导出没有设备，为 None）。
    device: str | None = None

    def __repr__(self) -> str:
        parts = [
            f"path={str(self.path)!r}",
            f"format={self.format!r}",
            f"size={self.width_pt:g}×{self.height_pt:g}pt",
            f"dpi={self.dpi:g}",
            f"bytes={self.bytes}",
        ]
        if self.size_px is not None:
            parts.append(f"px={self.size_px[0]}×{self.size_px[1]}")
        if self.device is not None:
            parts.append(f"device={self.device}")
        return f"SaveResult({', '.join(parts)})"


# ---------------------------------------------------------------------------
# 包外后端的注册口
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Backend:
    """包外渲染后端：设备工厂 + 可选的字体度量工厂。

    - `device(format, width_pt, height_pt, *, dpi)` → `ggcore.device.Device`；
    - `metrics()` → `ggcore.units.Metrics`（写进 IR 的 `text.width` 来自它）。

    协议在 `ggcore`，实现在 `ggskia`（X1：`ggcore` 不能 import skia /
    harfbuzz），与 `ggcore.metrics` 的「协议在内核、HarfBuzz 在包外」同一条规则。
    """

    device: Callable[..., Device]
    metrics: Callable[[], Any] | None = None
    name: str = ""


_BACKEND: Backend | None = None


def register_backend(backend: Backend | None) -> None:
    """注册（或清空）包外后端。`ggskia` 在 import 时调用它。"""
    if backend is not None and not isinstance(backend, Backend):
        raise TypeError(f"register_backend() 需要 Backend，收到 {type(backend).__name__}")
    if backend is not None and not callable(backend.device):
        raise TypeError("Backend.device 必须是可调用的设备工厂")
    global _BACKEND
    _BACKEND = backend


def registered_backend() -> Backend | None:
    """当前注册的后端（没注册时为 None；`.cbor` / `.json` 不需要它）。"""
    return _BACKEND


def _backend_or_error() -> Backend:
    if _BACKEND is None:
        raise SaveError(
            "没有可用的渲染后端：PNG / SVG / PDF 需要 ggskia（skia-python 在包外，"
            "X1 门禁不允许 ggcore import 它）。装好 dev 环境后 `import ggskia` 即可"
            "（它会注册后端），或者直接用 `pixi run ggsave <module:plot_fn> out.png`。"
            "`.ggir.cbor` / `.ir.json` 不需要后端。"
        )
    return _BACKEND


# ---------------------------------------------------------------------------
# 尺寸与单位
# ---------------------------------------------------------------------------


def _unit_factor(units: str) -> tuple[str, float]:
    """归一化单位名，返回（规范名, 每单位多少英寸）。"""
    if not isinstance(units, str):
        raise SaveError(f"units 必须是字符串，收到 {type(units).__name__}")
    name = units.strip().lower()
    factor = _UNIT_TO_INCH.get(name)
    if factor is None:
        raise SaveError(f"不认识的 units {units!r}；可选：{' / '.join(UNITS)}")
    canonical = "in" if name.startswith("inch") else name
    return canonical, factor


def _length(value: Any, units: str, name: str) -> float:
    """一个长度参数 → 英寸（有限正数）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SaveError(f"{name} 必须是数值，收到 {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise SaveError(f"{name} 必须是有限值，收到 {value!r}")
    if number <= 0:
        raise SaveError(f"{name} 必须为正，收到 {value!r}")
    _, factor = _unit_factor(units)
    return number * factor


def _inches(width: Any, height: Any, units: str) -> tuple[str, float, float]:
    canonical, _ = _unit_factor(units)
    return canonical, _length(width, units, "width"), _length(height, units, "height")


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------


def _scene(plot: Any, width_in: float, height_in: float, metrics: Any) -> ir.Scene:
    """`ggplot` → `ir.Scene`；`metrics` 缺省取注册后端的那一份。"""
    resolved = metrics
    if resolved is None and _BACKEND is not None and _BACKEND.metrics is not None:
        resolved = _BACKEND.metrics()
    return scene_from_plot(plot, width_in=width_in, height_in=height_in, metrics=resolved)


def _write(path: Path, data: bytes) -> None:
    """落盘（父目录不存在就建；与 `pixi run render` 的目录口径一致）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


# ---------------------------------------------------------------------------
# ggsave：按后缀选设备
# ---------------------------------------------------------------------------


def _suffix_format(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix not in FORMATS:
        raise SaveError(
            f"{path} 的后缀不认识（可选：{', '.join('.' + fmt for fmt in GRAPHIC_FORMATS)}；"
            "IR 导出用 save_ir() / export_ir_json()）"
        )
    return suffix


def _make_device(spec: Any, fmt: str, size_pt: tuple[float, float], dpi: float) -> Device:
    """`device=` 的三形态：格式名 / `Device` 实例 / 设备工厂。"""
    if spec is None or isinstance(spec, str):
        name = fmt if spec is None else str(spec).strip().lower().lstrip(".")
        if name not in FORMATS:
            raise SaveError(f"device={spec!r} 不认识；可选：{', '.join(GRAPHIC_FORMATS)}")
        device = _backend_or_error().device(name, size_pt[0], size_pt[1], dpi=dpi)
    elif isinstance(spec, Device):
        # 显式给的设备不需要后端注册，只要求纸和场景一样大。
        device = spec
        if tuple(device.size_pt) != tuple(size_pt):
            raise SaveError(
                f"device 的页面尺寸是 {device.size_pt} pt，与场景 {tuple(size_pt)} pt 不符"
                "（设备不替场景改纸，docs/notes/device.md §2）"
            )
    elif callable(spec):
        device = spec(size_pt[0], size_pt[1], dpi=dpi)
    else:  # pragma: no cover - 只有传错类型才到这里
        raise SaveError(f"device 必须是格式名 / Device 实例 / 设备工厂，收到 {type(spec).__name__}")
    if not isinstance(device, Device):
        raise SaveError(f"device 工厂返回了 {type(device).__name__}，不是 ggcore.device.Device")
    return device


def ggsave(
    plot: Any,
    filename: str | Path,
    *,
    width: float = DEFAULT_WIDTH,
    height: float = DEFAULT_HEIGHT,
    dpi: float = DEFAULT_DPI,
    device: Any = None,
    units: str = "in",
    metrics: Any = None,
) -> SaveResult:
    """把一张 `ggplot` 写成 PNG / SVG / PDF，返回 :class:`SaveResult`。

    - 格式由 `filename` 的后缀决定（`.png` / `.svg` / `.pdf`）；`device=` 可以是
      格式名（显式覆盖后缀）、`ggcore.device.Device` 实例或设备工厂；
    - `width` / `height` 按 `units`（`in` / `cm` / `mm` / `pt`）给出，缺省 7×5 in；
    - `dpi` 只影响栅格化的像素换算；页面尺寸（pt）与几何与 dpi 无关。
    """
    path = Path(filename)
    if isinstance(device, Device) and device.format:
        fmt = device.format
    elif isinstance(device, str):
        fmt = device.strip().lower().lstrip(".")
        if fmt not in FORMATS:
            raise SaveError(f"device={device!r} 不认识；可选：{', '.join(GRAPHIC_FORMATS)}")
    else:
        fmt = _suffix_format(path)
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)) or not math.isfinite(dpi):
        raise SaveError(f"dpi 必须是有限数值，收到 {dpi!r}")
    if float(dpi) <= 0:
        raise SaveError(f"dpi 必须为正，收到 {dpi!r}")
    canonical, width_in, height_in = _inches(width, height, units)

    scene = _scene(plot, width_in, height_in, metrics)
    resolved = _make_device(device, fmt, scene.size, float(dpi))
    data = resolved.render(scene)
    _write(path, data)
    return SaveResult(
        path=path,
        format=resolved.format or fmt,
        width_in=width_in,
        height_in=height_in,
        width_pt=scene.size[0],
        height_pt=scene.size[1],
        dpi=resolved.dpi,
        units=canonical,
        size_px=resolved.size_px if resolved.format == "png" else None,
        bytes=len(data),
        device=type(resolved).__name__,
    )


# ---------------------------------------------------------------------------
# IR 落盘：.ggir.cbor / .ir.json
# ---------------------------------------------------------------------------


def save_ir(
    plot: Any,
    path: str | Path,
    *,
    width: float = DEFAULT_WIDTH,
    height: float = DEFAULT_HEIGHT,
    units: str = "in",
    metrics: Any = None,
) -> SaveResult:
    """同一张图 → `.ggir.cbor`（canonical CBOR），返回 :class:`SaveResult`。

    `dpi` 不在签名里：IR 只承载几何，`Scene.dpi` 恒为 72（`docs/notes/ir.md` §1），
    出图时的分辨率由设备参数决定。
    """
    target = Path(path)
    canonical, width_in, height_in = _inches(width, height, units)
    scene = _scene(plot, width_in, height_in, metrics)
    data = ir.encode(scene)
    _write(target, data)
    return SaveResult(
        path=target,
        format="cbor",
        width_in=width_in,
        height_in=height_in,
        width_pt=scene.size[0],
        height_pt=scene.size[1],
        dpi=scene.dpi,
        units=canonical,
        size_px=None,
        bytes=len(data),
    )


def export_ir_json(
    plot: Any,
    path: str | Path,
    *,
    width: float = DEFAULT_WIDTH,
    height: float = DEFAULT_HEIGHT,
    units: str = "in",
    metrics: Any = None,
) -> SaveResult:
    """同一张图 → `.ir.json`（调试视图），返回 :class:`SaveResult`。

    视图内容是 :func:`ir_json_view` 的 JSON 文本；bulk 缓冲只留摘要，所以它**不是**
    传输格式——要能画出来的字节请用 :func:`save_ir`。
    """
    target = Path(path)
    canonical, width_in, height_in = _inches(width, height, units)
    scene = _scene(plot, width_in, height_in, metrics)
    data = (_write_json(ir_json_view(scene)) + "\n").encode("utf-8")
    _write(target, data)
    return SaveResult(
        path=target,
        format="json",
        width_in=width_in,
        height_in=height_in,
        width_pt=scene.size[0],
        height_pt=scene.size[1],
        dpi=scene.dpi,
        units=canonical,
        size_px=None,
        bytes=len(data),
    )


def ir_json_view(scene: ir.Scene) -> dict[str, Any]:
    """`ir.Scene` → 可 JSON 序列化的调试视图（不展开 bulk 数据）。

    每个节点带 `id`（从根出发的索引路径，如 `0/3/1`）、`kind`、**非缺省**的
    `gpar` / `params`（与 CBOR 的“只写非缺省字段”同一条规则）、`bufs` 摘要
    （`dtype` / `shape` / `nbytes` / `sha256`）、`texts` 与 `children`。空容器
    不写，所以一份视图就是「节点树 + 数据指纹」，体积与点数无关。
    """
    if not isinstance(scene, ir.Scene):
        raise TypeError(f"ir_json_view() 只接受 ir.Scene，收到 {type(scene).__name__}")
    buffers = 0
    for node in ir.walk(scene.root):
        buffers += sum(int(array.nbytes) for array in node.bufs.values())
    return {
        "magic": ir.MAGIC,
        "ir_version": ir.IR_VERSION_STR,
        "size": [scene.size[0], scene.size[1]],
        "dpi": scene.dpi,
        "stats": {
            "node_count": sum(1 for _ in ir.walk(scene.root)),
            "buffer_bytes": buffers,
            "blob_count": len(scene.blobs),
            "blob_bytes": sum(len(scene.blobs[bid].data) for bid in scene.blobs.ids()),
        },
        "blobs": [
            {
                "id": bid,
                "mime": scene.blobs[bid].mime,
                "nbytes": len(scene.blobs[bid].data),
                "sha256": hashlib.sha256(scene.blobs[bid].data).hexdigest(),
            }
            for bid in scene.blobs.ids()
        ],
        "root": _node_view(scene.root, "0"),
    }


def _node_view(node: ir.Node, path: str) -> dict[str, Any]:
    spec = ir.NODE_SPECS[node.kind]
    view: dict[str, Any] = {"id": path, "kind": node.kind.value}

    gpar: dict[str, Any] = {}
    if node.gpar is not None:
        for name, default in ir.GPAR_FIELDS:
            value = getattr(node.gpar, name)
            if value != default:
                gpar[name] = _plain(value)
    if gpar:
        view["gpar"] = gpar

    params: dict[str, Any] = {}
    for param in spec.params:
        value = node.params[param.name]
        if value != param.default:
            params[param.name] = _plain(value)
    if params:
        view["params"] = params

    bufs: list[dict[str, Any]] = []
    for buffer in spec.buffers:
        array = node.bufs.get(buffer.name)
        if array is None:  # pragma: no cover - 必填缓冲由 Node 校验保证
            continue
        bufs.append(
            {
                "name": buffer.name,
                "dtype": buffer.dtype,
                "shape": [int(size) for size in array.shape],
                "nbytes": int(array.nbytes),
                "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
            }
        )
    if bufs:
        view["bufs"] = bufs
    if node.texts:
        view["texts"] = list(node.texts)
    if node.children:
        view["children"] = [
            _node_view(child, f"{path}/{index}") for index, child in enumerate(node.children)
        ]
    return view


def _plain(value: Any) -> Any:
    """IR 参数 → JSON 值（StrEnum 转 str，元组转 list，其余原样）。"""
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# JSON 文本（手写；X1 门禁要求 ggcore 里不出现 json 模块）
# ---------------------------------------------------------------------------

_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def _quote(text: str) -> str:
    chunks = ['"']
    for char in text:
        escaped = _ESCAPES.get(char)
        if escaped is not None:
            chunks.append(escaped)
        elif char < " ":
            chunks.append(f"\\u{ord(char):04x}")
        else:
            chunks.append(char)
    chunks.append('"')
    return "".join(chunks)


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _quote(str(value))
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, float):
        # JSON 没有 NaN / ±Inf；视图只给调试看，非有限值写 null（`docs/notes/io.md`）。
        return repr(float(value)) if math.isfinite(value) else "null"
    item = getattr(value, "item", None)
    if callable(item):  # numpy 标量
        return _scalar(item())
    raise TypeError(f"ir_json_view() 里有无法写成 JSON 的值：{value!r}（{type(value).__name__}）")


def _write_json(value: Any, indent: int = 0) -> str:
    """确定性 JSON 文本（2 空格缩进；键序按构造顺序，不排序）。"""
    pad = "  " * indent
    inner = "  " * (indent + 1)
    if isinstance(value, Mapping):
        if not value:
            return "{}"
        items = [
            f"{inner}{_quote(str(key))}: {_write_json(item, indent + 1)}"
            for key, item in value.items()
        ]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            return "[]"
        items = [f"{inner}{_write_json(item, indent + 1)}" for item in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return _scalar(value)
