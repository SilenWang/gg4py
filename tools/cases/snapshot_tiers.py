#!/usr/bin/env python
"""快照阈值分档的测量与判定（SIL-745 #3）。

    pixi run tiers:measure      # 量 text_load / 墨量 / 实测差异 → docs/notes/snapshot-tiers.md
    pixi run tiers:check        # 校验：声明的容差不超过所属档位上限；实测差异不超过上限

## 为什么按「文本负载」分档

跨管线像素差的主因已定案为**文字**（SIL-715 #6：几何是主因，AA 次要；
M2-S1 把默认字面对齐到参考产线后，剩余差主要是字形边缘）。文字越多、字号越大，
每个字形边缘贡献的差异像素越多。所以档位的自变量取**静态可得**的
`text_load = Σ len(text) × (font_size / 11px)²`——它同时编码了「节点数」与
「字号」，不需要在 `--check` 里光栅化。

`ink`（非白像素占比）是同一个量的像素级观测，作为旁证写进表里，不参与判定：
它要光栅化，放进 `pixi run check` 太慢。

## 档位是上限，不是目标

档位只规定「最多允许多少」，**不**自动放宽任何 case：每个 case 仍然用
`meta.toml` 里写的 `tolerance`。`tiers:check` 只拦两种事——声明超过档位上限、
实测超过声明值。M1 的 61 条 case 全部落在 `text-light` / `text-medium`，上限仍是
2% / 1%，没有被「整体放宽」。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "docs" / "cases"
REPORT = ROOT / ".cases-matrix" / "report.json"
DOC = ROOT / "docs" / "notes" / "snapshot-tiers.md"

_TEXT = re.compile(r"<text\b[^>]*>(.*?)</text>", re.S)
_TAG = re.compile(r"<[^>]+>")
_ENTITY = re.compile(r"&[a-zA-Z]+;")
_FONT = re.compile(r"font-size:\s*([\d.]+)px")


def text_stats(svg: Path) -> tuple[int, float]:
    """`(文本节点数, text_load)`；字体缺省 11px（与 ggplot2 默认 base_size 同）。"""
    source = svg.read_text(encoding="utf-8", errors="replace")
    nodes = 0
    load = 0.0
    for match in _TEXT.finditer(source):
        nodes += 1
        body = _ENTITY.sub("x", _TAG.sub("", match.group(1)))
        size = _FONT.search(match.group(0))
        pointsize = float(size.group(1)) if size else 11.0
        load += len(body) * (pointsize / 11.0) ** 2
    return nodes, round(load, 1)


def ink_fraction(svg: Path) -> float:
    """非白像素占比（两侧同一光栅器；只作旁证）。"""
    sys.path.insert(0, str(ROOT / "src"))
    from PIL import Image

    from ggdiff.raster import rasterize_svg
    from ggdiff.svgtext import inline_text_paths

    with tempfile.TemporaryDirectory() as scratch:
        outlined = Path(scratch) / "outlined.svg"
        png = Path(scratch) / "render.png"
        inline_text_paths(svg, outlined)
        rasterize_svg(outlined, png)
        with Image.open(png) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            data = rgb.tobytes()
    white = 255 * 3
    ink = sum(1 for i in range(0, len(data), 3) if data[i] + data[i + 1] + data[i + 2] < white)
    return ink / (width * height)


#: 档位：`(名字, 上界 text_load, 图级上限, 均值上限)`。上界是开区间。
BANDS: tuple[tuple[str, float, float, float], ...] = (
    ("text-light", 20.0, 0.02, 0.01),
    ("text-medium", 200.0, 0.02, 0.01),
    ("text-heavy", float("inf"), 0.025, 0.012),
)


def band_of(load: float) -> tuple[str, float, float, float]:
    for band in BANDS:
        if load <= band[1]:
            return band
    return BANDS[-1]


def _declared_tolerance(directory: Path) -> float:
    import tomllib

    meta = tomllib.loads((directory / "meta.toml").read_text(encoding="utf-8"))
    return float((meta.get("tolerance") or {}).get("png", 0.02))


def _metrics() -> dict[str, Any]:
    if not REPORT.is_file():
        return {}
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    return {item["name"]: item for item in payload.get("cases", [])}


def rows(*, with_ink: bool = False) -> list[dict[str, Any]]:
    results = _metrics()
    measured: list[dict[str, Any]] = []
    for directory in sorted(CASES.iterdir()):
        expected = directory / "expected.svg"
        if not directory.is_dir() or not expected.is_file():
            continue
        nodes, load = text_stats(expected)
        name, _, image_cap, mean_cap = band_of(load)
        item = results.get(directory.name, {})
        metrics = item.get("metrics") or {}
        measured.append(
            {
                "case": directory.name,
                "nodes": nodes,
                "load": load,
                "band": name,
                "image_cap": image_cap,
                "mean_cap": mean_cap,
                "declared": _declared_tolerance(directory),
                "image": metrics.get("image_diff_fraction"),
                "mean": metrics.get("mean_diff"),
                "status": item.get("status"),
                "ink": ink_fraction(expected) if with_ink else None,
            }
        )
    return measured


def render_doc(measured: list[dict[str, Any]], *, with_ink: bool) -> str:
    lines = [
        "# 快照阈值分档（SIL-745 #3）",
        "",
        "<!-- 生成物：`pixi run tiers:measure`。规则全文见 docs/notes/snapshot-policy.md。 -->",
        "",
        "`text_load = Σ len(text) × (font_size / 11px)²`，静态从 `expected.svg` 量得；"
        "`ink` 是非白像素占比（同一 resvg 光栅器，仅作旁证）。",
        "",
        "| 档位 | text_load | 图级上限 | 均值上限 | case 数 | 实测最大图级 | 实测最大均值 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, upper, image_cap, mean_cap in BANDS:
        members = [row for row in measured if row["band"] == name]
        images = [row["image"] for row in members if row["image"] is not None]
        means = [row["mean"] for row in members if row["mean"] is not None]
        upper_text = "∞" if upper == float("inf") else f"{upper:g}"
        lines.append(
            f"| `{name}` | ≤ {upper_text} | {image_cap:.1%} | {mean_cap:.1%} | {len(members)} "
            f"| {max(images):.2%} | {max(means):.2%} |"
            if images
            else f"| `{name}` | ≤ {upper_text} | {image_cap:.1%} | {mean_cap:.1%} | 0 | — | — |"
        )
    lines.extend(
        [
            "",
            "档位是**上限**：每个 case 仍按 `meta.toml` 的 `tolerance` 判红，"
            "`tiers:check` 只拦「声明超过上限」与「实测超过声明」。",
            "",
        ]
    )
    header = (
        "| case | 节点 | text_load | "
        + ("ink | " if with_ink else "")
        + "图级 | 均值 | 档位 | 声明 |"
    )
    sep = "| --- | ---: | ---: | " + ("---: | " if with_ink else "") + "---: | ---: | --- | ---: |"
    lines.extend([header, sep])
    for row in sorted(measured, key=lambda item: -item["load"]):
        cells = [f"`{row['case']}`", str(row["nodes"]), f"{row['load']:g}"]
        if with_ink:
            cells.append(f"{row['ink']:.2%}" if row["ink"] is not None else "—")
        cells += [
            f"{row['image']:.2%}" if row["image"] is not None else "—",
            f"{row['mean']:.2%}" if row["mean"] is not None else "—",
            row["band"],
            f"{row['declared']:.1%}",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def check(measured: list[dict[str, Any]], *, include_measured: bool = False) -> list[str]:
    """声明 vs 档位上限；`include_measured` 时再对 `.cases-matrix/report.json` 的实测值。

    实测那半只给 `tiers:measure` / `--measured` 用：CI（`pixi run check`）里没有
    运行产物，拿旧报告判红只会制造假红。
    """
    problems = []
    for row in measured:
        if row["declared"] > row["image_cap"] + 1e-12:
            problems.append(
                f"{row['case']}: 声明 {row['declared']:.1%} 超过 {row['band']} 上限 "
                f"{row['image_cap']:.1%}（text_load={row['load']:g}）"
            )
        if not include_measured:
            continue
        if row["image"] is not None and row["image"] > row["declared"] + 1e-12:
            problems.append(
                f"{row['case']}: 实测图级 {row['image']:.2%} 超过声明 {row['declared']:.1%}"
            )
        if row["mean"] is not None and row["mean"] > 0.01 + 1e-12:
            problems.append(f"{row['case']}: 实测均值 {row['mean']:.2%} 超过全局均值门 1.00%")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--measure", action="store_true", help="写 docs/notes/snapshot-tiers.md（含墨量）"
    )
    parser.add_argument("--check", action="store_true", help="只校验上限（不写文件）")
    parser.add_argument(
        "--measured", action="store_true", help="同时比对上次 cases:matrix 的实测值"
    )
    args = parser.parse_args(argv)

    measured = rows(with_ink=args.measure and not args.check)
    problems = check(measured, include_measured=args.measured)
    if args.measure and not args.check:
        DOC.write_text(render_doc(measured, with_ink=True), encoding="utf-8")
        print(f"wrote {DOC.relative_to(ROOT)}")
    for row in measured:
        assert row["band"]
    counts: dict[str, int] = {}
    for row in measured:
        counts[row["band"]] = counts.get(row["band"], 0) + 1
    print("bands: " + ", ".join(f"{name}={count}" for name, count in sorted(counts.items())))
    if problems:
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        return 1
    print("snapshot tiers OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
