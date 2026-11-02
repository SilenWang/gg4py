"""把夹具场景导出成 `.ggir.cbor`（浏览器查看器的手测 / 截图素材）。

    pixi run viewer:sample                 # → web/viewer/samples/facet-legend.ggir.cbor
    pixi run viewer:sample --out x.cbor --width 6 --height 4

产物是确定性字节（`docs/notes/ir.md` §9），没进版本库：随用随生成。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from facet_legend import HEIGHT_IN, WIDTH_IN, facet_legend_scene  # noqa: E402

from ggcore import ir  # noqa: E402

DEFAULT_OUT = REPO / "web" / "viewer" / "samples" / "facet-legend.ggir.cbor"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="viewer:sample")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--width", type=float, default=WIDTH_IN, help="页面宽，英寸")
    parser.add_argument("--height", type=float, default=HEIGHT_IN, help="页面高，英寸")
    args = parser.parse_args(argv)

    scene = facet_legend_scene(width_in=args.width, height_in=args.height)
    data = ir.encode(scene)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(
        f"{args.out}: {len(data)} bytes "
        f"({scene.size[0]:g}×{scene.size[1]:g} pt, {_count(scene)} 个 IR 节点)"
    )
    return 0


def _count(scene: ir.Scene) -> int:
    return sum(1 for _ in ir.walk(scene.root))


if __name__ == "__main__":
    raise SystemExit(main())
