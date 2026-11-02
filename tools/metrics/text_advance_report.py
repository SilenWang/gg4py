"""M1-kerning：现有 case 的 hinted vs linear/HarfBuzz 推进差。

    pixi run metrics:advance
    pixi run metrics:advance -- --json .metrics-advance/advance.json

逐条从 `docs/cases/*/plot.py`（三文件 case）与 `docs/cases/*/case.json`
（grob 快照）读文本、字号、字族/字面，比较三种推进：

- **hinted**：skia 缺省（`setLinearMetrics(False)`），每字形推进按整 pt 量化；
- **linear**：`setLinearMetrics(True)`，R 的 cairo/svglite 口径；
- **HarfBuzz**：`hb.shape` 的 advance 之和（度量端）。

输出最大/平均相对差与逐条明细。数字写进 `docs/notes/metrics-ledger.md`
（M1-kerning）；切换与否由数据决定，不是「哪个更好看」。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import skia

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from ggcore.metrics.runs import is_glue, is_supported  # noqa: E402
from ggcore.plotspec import load_plot  # noqa: E402
from ggskia.text import TextShaper  # noqa: E402

CASES = REPO / "docs" / "cases"
OUT = REPO / ".metrics-advance"
CORPUS = REPO / "docs" / "spike" / "corpus" / "labels_200.json"


def _case_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for case_dir in sorted(path for path in CASES.iterdir() if path.is_dir()):
        plot = case_dir / "plot.py"
        if plot.is_file():
            spec = load_plot(case_dir)
            mapping = spec.get("mapping", {}) or {}
            data = spec.get("data", {}) or {}
            for layer in spec.get("layers", []):
                if layer.get("geom") != "text":
                    continue
                merged = {**mapping, **(layer.get("mapping") or {})}
                params = layer.get("params") or {}
                labels = (
                    [str(value) for value in data[merged["label"]]]
                    if merged.get("label") in data
                    else [str(params.get("label", ""))]
                )
                family = str(params.get("family", "sans"))
                face = str(params.get("fontface", "plain"))
                suffix = {
                    "bold": ":bold",
                    "italic": ":italic",
                    "bold.italic": ":bold-italic",
                }.get(face, "")
                size = float(params.get("size_pt", 11.0))
                for label in labels:
                    entries.append(
                        {
                            "case": case_dir.name,
                            "font": f"{family}{suffix}",
                            "size": size,
                            "text": label,
                        }
                    )
        manifest = case_dir / "case.json"
        if manifest.is_file():
            document = json.loads(manifest.read_text(encoding="utf-8"))
            for grob in document.get("grobs", []):
                if grob.get("type") != "text":
                    continue
                gp = grob.get("gp") or {}
                entries.append(
                    {
                        "case": case_dir.name,
                        "font": str(gp.get("fontfamily") or "sans"),
                        "size": float(gp.get("fontsize", 12.0)),
                        "text": str(grob.get("label", "")),
                    }
                )
    if CORPUS.is_file():
        corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        for item in corpus.get("labels", []):
            entries.append(
                {
                    "case": "corpus-200",
                    "font": "sans",
                    "size": float(corpus.get("font_size_px", 16.0)),
                    "text": str(item["text"]),
                }
            )
    return entries


def _measure(shaper: TextShaper, entry: dict[str, Any]) -> dict[str, Any]:
    size = float(entry["size"])
    runs = shaper.runs(entry["font"], entry["text"], float(entry["size"]))
    hinted = 0.0
    linear = 0.0
    for run in runs:
        font_hinted = skia.Font(shaper.typeface(run.face), size)
        font_hinted.setLinearMetrics(False)
        hinted += float(font_hinted.measureText(run.text))
        font_linear = skia.Font(shaper.typeface(run.face), size)
        font_linear.setLinearMetrics(True)
        linear += float(font_linear.measureText(run.text))
    hb_total = sum(shaper.harfbuzz_advance(run.face, run.text, size) for run in runs)
    # HarfBuzz 只和「cmap 直映」的简单文字可比：复杂书写系统（连写/重排）与
    # emoji 序列（ZWJ/VS16，设备按码点直映不合成字形）本来就走另一条路
    # （docs/notes/device.md §4），硬比会得到 2–3 倍的假差。
    comparable = is_supported(entry["text"]) and not any(
        is_glue(ord(ch)) or _emoji_like(ord(ch)) for ch in entry["text"]
    )
    return {
        **entry,
        "hinted": hinted,
        "linear": linear,
        "harfbuzz": hb_total,
        "harfbuzz_comparable": comparable,
    }


def _emoji_like(codepoint: int) -> bool:
    """emoji 序列（肤色/国旗/keycap/ZWJ）在 skia 的码点直映里不合成字形。"""
    return (
        codepoint >= 0x1F000
        or 0x2600 <= codepoint <= 0x27BF
        or 0x2B00 <= codepoint <= 0x2BFF
        or codepoint == 0x20E3
    )


def build() -> dict[str, Any]:
    shaper = TextShaper()
    rows = [_measure(shaper, entry) for entry in _case_entries()]
    for row in rows:
        baseline = row["linear"] or 1.0
        row["hinted_vs_linear"] = (row["hinted"] - row["linear"]) / baseline
        row["hinted_vs_harfbuzz"] = (row["hinted"] - row["harfbuzz"]) / (row["harfbuzz"] or 1.0)
    comparable_rows = [row for row in rows if row["harfbuzz_comparable"]]
    worst = max(rows, key=lambda row: abs(row["hinted_vs_linear"]))
    return {
        "cases": len({row["case"] for row in rows}),
        "labels": len(rows),
        "max_abs_hinted_vs_linear": abs(worst["hinted_vs_linear"]),
        "worst": worst,
        "mean_abs_hinted_vs_linear": sum(abs(row["hinted_vs_linear"]) for row in rows) / len(rows),
        "harfbuzz_comparable": len(comparable_rows),
        "max_abs_hinted_vs_harfbuzz": max(
            abs(row["hinted_vs_harfbuzz"]) for row in comparable_rows
        ),
        "rows": rows,
    }


def render(report: dict[str, Any]) -> str:
    worst = report["worst"]
    lines = [
        f"cases: {report['cases']}  labels: {report['labels']}",
        f"hinted vs linear: max {report['max_abs_hinted_vs_linear']:.3%} "
        f"mean {report['mean_abs_hinted_vs_linear']:.3%}",
        f"hinted vs HarfBuzz: max {report['max_abs_hinted_vs_harfbuzz']:.3%}",
        f"  ({report['harfbuzz_comparable']}/{report['labels']} labels comparable; "
        "复杂书写系统与 emoji 序列走另一条路，不比)",
        f"worst: {worst['case']} {worst['font']} {worst['size']:g}pt "
        f"{worst['text']!r} hinted {worst['hinted']:.2f} linear {worst['linear']:.2f} "
        f"hb {worst['harfbuzz']:.2f}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="write the full report here")
    args = parser.parse_args(argv)
    report = build()
    print(render(report))
    target = args.json or OUT / "advance.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
