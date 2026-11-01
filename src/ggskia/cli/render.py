"""`pixi run render` —— 出图入口（M0-8 / M0-9）。

两种输入形态，输出格式都由 `--out` 的后缀或 `--format` 决定
（`.png` / `.svg` / `.pdf`）：

```bash
# 1) 一份 IR 场景（M0-8）
pixi run render --scene docs/cases/<case>/current/<case>.ggir.cbor --out x.png
pixi run render --scene s.ggir.cbor --out x.svg
pixi run render --scene s.ggir.cbor --out x.pdf --dpi 300

# 2) 一个三文件 case 目录（M0-9 的适配层）
pixi run render docs/cases/geom-point-basic --format png --out docs/cases/geom-point-basic/current
```

第二种形态就是 `cases:matrix` 的 `TaskBackend` 契约：读 `<case>/plot.py` 的
`build()`，经 `ggcore.plotspec` 变成 IR 场景，再交给设备。写进目录时的文件名是
`<case>.<format>`；`--out` 带后缀时按文件写。

页面尺寸取自 `ir.Scene.size`（pt），`--dpi` 只影响栅格化的像素密度，缺省用
`Scene.dpi`。设备契约见 `docs/notes/device.md`，案例适配层见
`docs/notes/diff.md`。

模块放在 `ggskia` 而不是 `ggcore.cli`：skia 后端在包外（X1 门禁），CLI 跟着
后端走；任务名仍然是 M0-1 定的 `render`。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ggcore.ir import IRDecodeError, decode
from ggcore.plotspec import PlotSpecError, build_scene, load_plot
from ggskia import DeviceError, device_for
from ggskia.text import ShaperMetrics

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CASES = REPO / "docs" / "cases"
FORMATS = ("svg", "png", "pdf")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ggcore render",
        description="Render an IR scene (.ggir.cbor) or a case directory to PNG / SVG / PDF.",
    )
    parser.add_argument(
        "cases",
        nargs="?",
        type=Path,
        default=DEFAULT_CASES,
        help=f"case directory (default: {DEFAULT_CASES})",
    )
    parser.add_argument(
        "--scene",
        type=Path,
        default=None,
        help="IR scene file (.ggir.cbor) to render",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output file (suffix picks the device) or directory (writes <case>.<format>)",
    )
    parser.add_argument(
        "--dpi",
        type=float,
        default=None,
        help="raster resolution (default: Scene.dpi); ignored by svg / pdf",
    )
    parser.add_argument(
        "--format",
        choices=FORMATS,
        action="append",
        dest="formats",
        help="output format for case-directory mode, repeatable (default: svg)",
    )
    return parser


def _scene(args: argparse.Namespace):
    """`--scene` 或 case 目录 → （IR 场景, 来源标签）。"""
    if args.scene is not None:
        return decode(args.scene.read_bytes()), str(args.scene)
    directory = args.cases
    if not directory.is_dir():
        raise PlotSpecError(f"{directory} 不是 case 目录（缺 plot.py）")
    spec = load_plot(directory)
    metrics = ShaperMetrics()
    return build_scene(spec, metrics=metrics), str(directory)


def _outputs(args: argparse.Namespace) -> list[tuple[str, Path]]:
    """（格式, 输出路径）列表；目录形态按 `<case>.<format>` 落盘。"""
    formats = args.formats or ([] if args.out is not None and args.out.suffix else ["svg"])
    if args.out is None:
        raise DeviceError("需要 --out（文件或目录）")
    suffix = args.out.suffix.lstrip(".").lower()
    if suffix:
        if suffix not in FORMATS:
            raise DeviceError(
                f"--out {args.out} 的后缀不认识（可选：{' / '.join(FORMATS)}；"
                "目录形态的 --out 不要带后缀）"
            )
        if len(formats) > 1:
            raise DeviceError(f"--out {args.out} 是文件，只能配一个 --format")
        if formats and formats[0] != suffix:
            raise DeviceError(
                f"--out {args.out} 的后缀是 {suffix}，与 --format {formats[0]} 不一致"
            )
        return [(suffix, args.out)]
    # 没有后缀（或未知后缀）→ 当目录：文件名取 case 目录名，格式取 --format。
    name = args.cases.resolve().name if args.scene is None else args.scene.stem.split(".")[0]
    return [(fmt, args.out / f"{name}.{fmt}") for fmt in formats]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ir_scene, _source = _scene(args)
        outputs = _outputs(args)
    except (OSError, IRDecodeError, DeviceError, PlotSpecError) as error:
        print(f"ggcore render: {error}", file=sys.stderr)
        return 2

    dpi = ir_scene.dpi if args.dpi is None else float(args.dpi)
    messages: list[str] = []
    try:
        for fmt, target in outputs:
            device = device_for(fmt, *ir_scene.size, dpi=dpi)
            data = device.render(ir_scene)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            messages.append(
                f"{target}: {len(data)} bytes ({device.format}, "
                f"{ir_scene.size[0]:g}×{ir_scene.size[1]:g} pt, {dpi:g} dpi)"
            )
    except (OSError, DeviceError) as error:
        print(f"ggcore render: {error}", file=sys.stderr)
        return 2
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
