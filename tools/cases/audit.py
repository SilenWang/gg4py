"""case 复刻完整性审计：`expected.svg` 的 `font-size` 多重集 vs 我们 IR 的 text `size` 多重集。

**为什么需要**（SIL-839）：`theme_test()` 写错、`plot.title` 漏掉——两次「case 复刻不全」
都是同一类错误，靠逐条盯 diff 发现，代价几十轮。这个审计不栅格化、不依赖字体，
只比两侧的字号多重集，能把这类系统性遗漏一次全暴露。

`--dpi 72` 下 1pt = 1px，所以 R 的 `font-size: 8.80px` 与 IR 的 `size = 8.8` 可直接比；
浮点按 1 位小数取整（`8.80` vs `8.8`）。

退出码：0 = 全部匹配；1 = 有不匹配（CI 用这个当门）。
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "src")

from ggcore.geom.scene import scene_from_plot
from ggcore.plotspec import load_plot

CASES = Path(__file__).resolve().parents[2] / "docs" / "cases"
_FONT_SIZE = re.compile(r"font-size:\s*([0-9.]+)px")


def expected_sizes(svg: Path) -> Counter[float]:
    return Counter(round(float(v), 1) for v in _FONT_SIZE.findall(svg.read_text(encoding="utf-8")))


def ours_sizes(case: Path) -> Counter[float] | None:
    """IR 里 text 节点的 `size` 多重集；构建失败时返回 None（该 case 跳过）。"""
    try:
        spec = load_plot(case)
        built = spec if isinstance(spec, dict) else {"plot": spec}
        width, height = built.get("size", (10, 8))
        scene = scene_from_plot(built["plot"], width_in=width, height_in=height)
    except Exception:
        return None

    out: Counter[float] = Counter()

    def walk(node) -> None:
        if node.kind.value == "text":
            params = getattr(node, "params", None) or {}
            size = params.get("size")
            if size is not None:
                out[round(float(size), 1)] += 1
        for child in node.children:
            walk(child)

    walk(scene.root)
    return out


def main() -> int:
    baseline = CASES / "audit-baseline.txt"
    known = (
        {line.strip() for line in baseline.read_text(encoding="utf-8").splitlines() if line.strip()}
        if baseline.is_file()
        else set()
    )
    rows: list[tuple[int, str, Counter[float], Counter[float]]] = []
    checked = skipped = 0
    for case in sorted(CASES.iterdir()):
        svg = case / "expected.svg"
        if not svg.is_file() or not (case / "plot.py").is_file():
            continue
        if (case / "meta.toml").is_file():
            meta = (case / "meta.toml").read_text(encoding="utf-8")
            if "skip" in meta and "audit" in meta:
                skipped += 1
                continue
        ours = ours_sizes(case)
        if ours is None:
            skipped += 1
            continue
        checked += 1
        exp = expected_sizes(svg)
        if exp != ours:
            missing = exp - ours
            extra = ours - exp
            rows.append((sum(missing.values()) + sum(extra.values()), case.name, missing, extra))

    rows.sort(key=lambda row: (-row[0], row[1]))
    new = [row for row in rows if row[1] not in known]
    print(
        f"cases:audit — 检查 {checked} 个 case，跳过 {skipped} 个，不匹配 {len(rows)} 个"
        f"（基线内 {len(rows) - len(new)}，新增 {len(new)}）"
    )
    for delta, name, missing, extra in rows:
        tag = "（基线）" if name in known else "（新增）"
        print(f"  {name}  差 {delta} 个文本 {tag}")
        if missing:
            print(f"    期望有、我们没有: {dict(sorted(missing.items()))}")
        if extra:
            print(f"    我们有、期望没有: {dict(sorted(extra.items()))}")
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
