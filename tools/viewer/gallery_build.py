#!/usr/bin/env python
"""SIL-893：静态 gallery —— 不装 Chromium 也能浏览整本案例库。

    pixi run viewer:gallery                    # 全部合法 case → dist/gallery.html
    pixi run viewer:gallery --case geom-col-basic
    pixi run viewer:gallery --gallery /tmp/x/dist/gallery.html

和 `pixi run viewer:cases` 的分工：

| | `viewer:cases` | `viewer:gallery` |
| --- | --- | --- |
| 干什么 | 验证：IR → Chromium → DOM SVG，与 `expected.svg` 对拍 | 摆摊：卡片图 + IR |
| 需要 Chromium | **是** | 否（`viewer:build` 只跑 npm + tsc） |
| 缩略图 | viewer 自己的 Chromium 截图 | 仓内 `docs/cases/<case>/expected.svg` |
| 卡片状态 | pass / fail / error / skip（真跑过才有结论） | `static`（没做过像素验证，不借绿灯） |

每条 case 的产物（都不入库，`.gitignore` 已覆盖 `web/viewer/gallery/` 与
`web/viewer/dist/`）：

    web/viewer/gallery/<case>.ggir.cbor   # IR，viewer 打开卡片时 fetch 的就是它
    web/viewer/gallery/<case>.svg         # 缩略图（直接复制 expected.svg）
    web/viewer/dist/gallery.html          # 卡片链 ../index.html?scene=gallery/<case>.ggir.cbor

缩略图为什么直接搬 `expected.svg` 而不光栅化：R 产线那一份就是「这张图应该长什么样」
的权威答案，浏览器渲染 SVG 是它的本职；拿 resvg 逐条光栅化 500+ 张会把生成时间从
几秒推到分钟级，而这层缩略图并不承担验证职责。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CASES = REPO / "docs" / "cases"
VIEWER = REPO / "web" / "viewer"
DIST = VIEWER / "dist"
GALLERY = DIST / "gallery.html"

sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools" / "viewer"))

import gallery_html  # noqa: E402

from ggcore import ir  # noqa: E402
from ggcore.plotspec import build_scene, load_plot  # noqa: E402
from ggskia.text import ShaperMetrics  # noqa: E402


def _load_matrix_module():
    """复用 `tools/cases/matrix.py` 的 case 发现与契约校验，不复制第二份。"""
    path = REPO / "tools" / "cases" / "matrix.py"
    spec = importlib.util.spec_from_file_location("gg4py_case_matrix_static", path)
    if spec is None or spec.loader is None:  # pragma: no cover - 文件不可读时才发生
        raise RuntimeError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_cards(cases: list, assets: Path, metrics: ShaperMetrics) -> tuple[list, list[str]]:
    """逐条 case 写 IR，返回（卡片, 错误说明）。缩略图指向仓内的参考图。"""
    assets.mkdir(parents=True, exist_ok=True)
    cards: list[gallery_html.Card] = []
    problems: list[str] = []
    for case in cases:
        expected = case.directory / case.expected if case.expected else None
        try:
            scene = build_scene(load_plot(case.directory), metrics=metrics)
            data = ir.encode(scene)
            cbor = assets / f"{case.name}.ggir.cbor"
            cbor.write_bytes(data)
        except Exception as error:  # 单条 case 坏掉不该让整本画廊消失
            detail = f"{type(error).__name__}: {error}".splitlines()[0][:400]
            problems.append(f"{case.name}: {detail}")
            cards.append(
                gallery_html.Card(
                    case=case.name,
                    family=case.family,
                    status="error",
                    detail=detail,
                )
            )
            continue
        elements = sum(1 for _ in ir.walk(scene.root))
        if expected is None or not expected.is_file():
            problems.append(f"{case.name}: 缺参考图 {case.expected or '（未声明）'}")
            cards.append(
                gallery_html.Card(
                    case=case.name,
                    family=case.family,
                    status="error",
                    elements=elements,
                    detail=f"缺参考图 {case.expected or '（未声明）'}，卡片没有缩略图",
                )
            )
            continue
        cards.append(
            gallery_html.Card(
                case=case.name,
                family=case.family,
                status="static",
                elements=elements,
                thumbnail=expected,
                ir_path=cbor,
            )
        )
    return cards, problems


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="viewer:gallery",
        description="生成静态 gallery.html：缩略图用 expected.svg，不需要 Chromium。",
    )
    parser.add_argument("--root", type=Path, default=CASES, help="案例根目录（默认 docs/cases）")
    parser.add_argument("--case", action="append", dest="cases", help="只跑这个 case（可重复）")
    parser.add_argument("--gallery", type=Path, default=GALLERY, help="gallery.html 路径")
    parser.add_argument(
        "--check-assets",
        action="store_true",
        help="额外核对资产目录里每个缩略图 / IR 都是非空文件（默认在汇总里打印数字）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    started = time.perf_counter()
    args = build_parser().parse_args(argv)

    if not (args.gallery.parent / "main.js").is_file():
        print(
            "viewer:gallery: 同目录下没有 main.js，先跑 `pixi run viewer:build`"
            "（卡片点开后的 viewer 要用它），或把 --gallery 指到已构建的 dist/ 里",
            file=sys.stderr,
        )
        return 2

    matrix = _load_matrix_module()
    discovered = matrix.discover(args.root)
    if args.cases:
        wanted = set(args.cases)
        discovered = [case for case in discovered if case.name in wanted]
        for name in sorted(wanted - {case.name for case in discovered}):
            print(f"viewer:gallery: no case named {name!r}", file=sys.stderr)

    cases = sorted((case for case in discovered if case.valid), key=lambda case: case.name)
    assets = gallery_html.gallery_assets_dir(args.gallery)
    cards, problems = build_cards(cases, assets, ShaperMetrics())

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    clickable = sum(1 for card in cards if card.clickable)
    lede = (
        f"{now} · {len(cards)} 张卡片 / {len(cases)} 个 case，"
        f"{clickable} 张有缩略图。缩略图是 R 产线（ggplot2 4.0.3 + svglite）的 "
        "<code>expected.svg</code>，<b>没有做像素验证</b>；点卡片在浏览器里渲染同一份 IR"
        f"（hover / 图例开关可用）。跑像素对拍请用 <code>pixi run viewer:cases</code>。"
    )
    gallery_html.write_gallery(
        cards,
        args.gallery,
        now,
        lede=lede,
        subtitle="gg4py viewer · static gallery",
    )

    elapsed = time.perf_counter() - started
    if args.check_assets:
        empty = [
            path.name
            for path in sorted(assets.iterdir())
            if path.is_file() and path.stat().st_size == 0
        ]
        if empty:
            problems.append(f"{len(empty)} 个资产是空文件：{', '.join(empty[:5])}")
    print(
        f"viewer:gallery: {len(cards)} 张卡片 / {len(cases)} 个 case（合法 case 总数 "
        f"{sum(1 for case in discovered if case.valid)}）；缩略图 {clickable} 张，"
        f"IR {sum(1 for card in cards if card.ir_path is not None and card.clickable)} 份；"
        f"资产目录 {assets}"
    )
    print(f"viewer:gallery: gallery.html → {args.gallery}（{elapsed:.1f} s）")
    if problems:
        print(f"viewer:gallery: {len(problems)} 条没进画廊：", file=sys.stderr)
        for line in problems[:10]:
            print(f"  - {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
