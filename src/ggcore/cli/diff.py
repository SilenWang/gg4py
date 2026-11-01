"""`pixi run diff` —— 把 current/ 产物与纳管的基线/上游参考图比对。

M0-1 只接入口：容差口径见 `docs/notes/snapshot-policy.md`，比对器在 M0 后续
阶段落地。
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
        prog="ggcore diff",
        description="Diff generated case output against reference images.",
    )
    parser.add_argument(
        "cases",
        nargs="?",
        type=Path,
        default=DEFAULT_CASES,
        help=f"case directory (default: {DEFAULT_CASES})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="markdown report path (default: stdout)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=None,
        help="override the default tolerance from docs/notes/snapshot-policy.md",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return unimplemented(
        "diff",
        "comparator lands in a later M0 stage",
        f"planned: {args.cases} vs <case>/expected (tolerance={args.tolerance})",
    )


if __name__ == "__main__":
    sys.exit(main())
