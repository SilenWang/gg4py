"""`pixi run ggsave` —— 一张 `ggplot` 落到 PNG / SVG / PDF，或 IR（M1-12）。

```bash
pixi run ggsave tools/examples/ggsave_demo.py:plot out.png
pixi run ggsave tools/examples/ggsave_demo.py:plot out.svg --width 10 --units cm
pixi run ggsave tools/examples/ggsave_demo.py:plot out.ggir.cbor
pixi run ggsave tools/examples/ggsave_demo.py:plot out.ir.json --dpi 150
```

第一个参数是 `<module:plot_fn>`：

- `<module:fn>` 走 import（`python -m` 已把 cwd 放进 `sys.path`）；
- `<path/to/file.py:fn>` 直接按文件加载，不用先建包。

`plot_fn` 不收参数，返回一个 `ggcore.plot.ggplot`。输出格式由 `--out` 的后缀
决定：`.png` / `.svg` / `.pdf` 交给 `ggcore.io.ggsave`，`.ggir.cbor` /
`.ir.json` 交给 `save_ir` / `export_ir_json`。缺省尺寸 7×5 in、`dpi=72`，
单位可选 `in` / `cm` / `mm` / `pt`（口径见 `docs/notes/io.md`）。

**为什么入口在 `ggskia` 而不是 `ggcore.cli`**：PNG / SVG / PDF 需要
`skia-python`，而 X1 门禁（`pixi run gate:imports`）不允许 `src/ggcore/` import
它；`docs/notes/gates.md` 的同一条规则下，`render` 的入口也在 `ggskia.cli`。
`ggcore.io` 只放设备无关的编排（选尺寸、写 IR、JSON 视图），后端由 `ggskia`
在 import 时注册进来——所以 `pixi run ggsave` 与
`python -m ggskia.cli.ggsave` 是同一条命令。
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from ggcore.device import DeviceError
from ggcore.io import UNITS, SaveError, SaveResult, export_ir_json, ggsave, save_ir
from ggcore.ir import IRError
from ggcore.plot import ggplot

#: 四种输出后缀 → 动作（`pixi run ggsave` 的任务名与 `render` 同一套 CLI 口径）。
GRAPHICS = ("png", "svg", "pdf")
IR_FORMATS = ("cbor", "json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ggcore ggsave",
        description=(
            "Save a ggplot object to PNG / SVG / PDF, or export its IR (.ggir.cbor / .ir.json)."
        ),
    )
    parser.add_argument("target", help="<module:plot_fn> or <path/to/file.py:plot_fn>")
    parser.add_argument(
        "out",
        type=Path,
        help="output file; suffix picks the action: .png / .svg / .pdf / .cbor / .json",
    )
    parser.add_argument(
        "--width", type=float, default=None, help="plot width in --units (default: 7)"
    )
    parser.add_argument(
        "--height", type=float, default=None, help="plot height in --units (default: 5)"
    )
    parser.add_argument(
        "--units", choices=UNITS, default="in", help="units of --width / --height (default: in)"
    )
    parser.add_argument(
        "--dpi",
        type=float,
        default=None,
        help="raster resolution (default: 72; ignored by svg / pdf / IR)",
    )
    return parser


# ---------------------------------------------------------------------------
# <module:plot_fn>
# ---------------------------------------------------------------------------


def _split_target(target: str) -> tuple[str, str]:
    reference, sep, name = target.rpartition(":")
    if not sep or not reference or not name:
        raise SaveError(
            f"target 必须是 <module:plot_fn> 或 <path/to/file.py:plot_fn>，收到 {target!r}"
        )
    return reference, name


def _import_plot_module(reference: str) -> Any:
    """模块名或 `.py` 路径 → 模块对象（路径形态不要求先建包）。"""
    path = Path(reference)
    if reference.endswith(".py") or path.is_file():
        if not path.is_file():
            raise SaveError(f"{path} 不存在")
        module_name = "gg4py_ggsave_" + "".join(
            char if char.isalnum() else "_" for char in path.stem
        )
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:  # pragma: no cover - 只有读不了时才发生
            raise SaveError(f"{path} 无法作为模块加载")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(module_name, None)
        return module
    try:
        return importlib.import_module(reference)
    except ImportError as exc:
        raise SaveError(
            f"{reference} 导入失败：{exc}（模块名要在 PYTHONPATH 里；"
            "也可以直接给 `<path/to/file.py:plot_fn>`）"
        ) from exc


def load_plot(target: str) -> ggplot:
    """`<module:plot_fn>` → 一个 `ggplot` 对象（`plot_fn` 不收参数）。"""
    reference, name = _split_target(target)
    module = _import_plot_module(reference)
    builder = getattr(module, name, None)
    if not callable(builder):
        raise SaveError(f"{reference} 里没有可调用的 {name}()")
    try:
        plot = builder()
    except Exception as exc:
        raise SaveError(f"{name}() 抛异常：{type(exc).__name__}: {exc}") from exc
    if not isinstance(plot, ggplot):
        raise SaveError(f"{name}() 必须返回 ggcore.plot.ggplot，实际是 {type(plot).__name__}")
    return plot


# ---------------------------------------------------------------------------
# 后缀 → 动作
# ---------------------------------------------------------------------------


def _suffix(out: Path) -> str:
    return out.suffix.lower().lstrip(".")


def run(args: argparse.Namespace) -> SaveResult:
    suffix = _suffix(args.out)
    if suffix not in GRAPHICS + IR_FORMATS:
        raise SaveError(
            f"{args.out} 的后缀不认识；可选："
            + " / ".join(f".{item}" for item in GRAPHICS + IR_FORMATS)
        )
    plot = load_plot(args.target)
    common: dict[str, Any] = {"units": args.units}
    if args.width is not None:
        common["width"] = args.width
    if args.height is not None:
        common["height"] = args.height
    if suffix in IR_FORMATS:
        action = save_ir if suffix == "cbor" else export_ir_json
        return action(plot, args.out, **common)
    if args.dpi is not None:
        common["dpi"] = args.dpi
    return ggsave(plot, args.out, **common)


def describe(result: SaveResult) -> str:
    """一行产物摘要（命令行的 stdout 就是它）。"""
    size = f"{result.width_pt:g}×{result.height_pt:g} pt"
    if result.size_px is not None:
        size += f" → {result.size_px[0]}×{result.size_px[1]} px"
    detail = f"{result.format}, {size}, {result.dpi:g} dpi"
    if result.device is not None:
        detail += f", {result.device}"
    return f"{result.path}: {result.bytes} bytes ({detail})"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (OSError, DeviceError, SaveError, IRError, ValueError) as error:
        print(f"ggcore ggsave: {error}", file=sys.stderr)
        return 2
    print(describe(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
