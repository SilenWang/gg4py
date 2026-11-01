"""`pixi run render` —— 把 docs/cases 下的案例渲染成 SVG/PNG/PDF。

M0-1 只接入口：真正调用 skia-python 的渲染器在 M0 后续阶段落地。届时
`--cases` 的目录约定见 `docs/cases/README.md`。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ggcore.cli import unimplemented

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CASES = REPO / "docs" / "cases"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ggcore render",
        description="Render every case under docs/cases to the requested format.",
    )
    parser.add_argument(
        "cases",
        nargs="?",
        type=Path,
        default=DEFAULT_CASES,
        help=f"case directory (default: {DEFAULT_CASES})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output directory (default: <cases>/<case>/current/)",
    )
    parser.add_argument(
        "--format",
        choices=("svg", "png", "pdf"),
        action="append",
        dest="formats",
        help="output format, repeatable (default: svg)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    formats = args.formats or ["svg"]
    return unimplemented(
        "render",
        "renderer lands in a later M0 stage",
        f"planned: {args.cases} -> {args.out or '<case>/current'} as {', '.join(formats)}",
    )


if __name__ == "__main__":
    sys.exit(main())
