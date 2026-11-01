"""`pixi run render` —— 一份 IR 场景出图（M0-8）。

    pixi run render --scene docs/cases/<case>/current/<case>.ggir.cbor --out x.png
    pixi run render --scene s.ggir.cbor --out x.svg
    pixi run render --scene s.ggir.cbor --out x.pdf --dpi 300

输出格式由 `--out` 的后缀决定（`.png` / `.svg` / `.pdf`）；页面尺寸取自
`ir.Scene.size`（pt），`--dpi` 只影响栅格化的像素密度，缺省用 `Scene.dpi`。
设备契约见 `docs/notes/device.md`。

没有 `--scene` 时仍然留给 M0-1 的案例目录形态（`docs/cases/`），那部分由案例
脚本（`pixi run cases:grob` 等）接管，入口本身保持未实现。

模块放在 `ggskia` 而不是 `ggcore.cli`：skia 后端在包外（X1 门禁），CLI 跟着
后端走；任务名仍然是 M0-1 定的 `render`。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ggcore.cli import unimplemented
from ggcore.ir import IRDecodeError, decode
from ggskia import DeviceError, device_for

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CASES = REPO / "docs" / "cases"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ggcore render",
        description="Render an IR scene (.ggir.cbor) to PNG / SVG / PDF.",
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
        help="output file; its suffix picks the device (.png / .svg / .pdf)",
    )
    parser.add_argument(
        "--dpi",
        type=float,
        default=None,
        help="raster resolution (default: Scene.dpi); ignored by svg / pdf",
    )
    parser.add_argument(
        "--format",
        choices=("svg", "png", "pdf"),
        action="append",
        dest="formats",
        help="legacy case-directory mode: output format, repeatable",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.scene is None:
        formats = args.formats or ["svg"]
        return unimplemented(
            "render",
            "case directories go through the case scripts (pixi run cases:grob)",
            f"single scene: render --scene <file.ggir.cbor> --out x.png "
            f"(planned: {args.cases} -> {args.out or '<case>/current'} as {', '.join(formats)})",
        )
    if args.out is None:
        print("ggcore render: --scene 需要 --out（后缀决定格式）", file=sys.stderr)
        return 2
    try:
        scene = decode(args.scene.read_bytes())
        dpi = scene.dpi if args.dpi is None else float(args.dpi)
        device = device_for(args.out, *scene.size, dpi=dpi)
        data = device.render(scene)
    except (OSError, IRDecodeError, DeviceError) as error:
        print(f"ggcore render: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(
        f"{args.out}: {len(data)} bytes ({device.format}, "
        f"{scene.size[0]:g}×{scene.size[1]:g} pt, {dpi:g} dpi)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
