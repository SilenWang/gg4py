"""E2 gate: do uharfbuzz and CanvasKit.Paragraph agree on text advance?

Measures the same 200 frozen labels (docs/spike/corpus/labels_200.json) with
the same font files on both sides:

  * CPython: uharfbuzz shaping, per-codepoint fallback over the corpus font
    stack (first face that has a nominal glyph wins, like SkFontMgr).
  * Node: CanvasKit SkParagraph via TypefaceFontProvider + FontCollection,
    which is the renderer the browser viewer will actually use.

Gate: per-label |delta| / canvaskit_width < 0.5%.

Run: pixi run spike:e2
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

import uharfbuzz as hb

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
REPO = SPIKE.parent.parent
CORPUS = SPIKE / "corpus" / "labels_200.json"
RESULTS = HERE / "results"
GATE = 0.005

# Characters that must never start a new font run: joiners, selectors and
# combining marks belong to whatever face shaped the character before them.
GLUE = {0x200D, 0xFE0E, 0xFE0F, 0xFE00, 0xE0100}


def font_dir() -> Path:
    prefix = os.environ.get("CONDA_PREFIX")
    if not prefix:
        sys.exit("CONDA_PREFIX is unset - run this through `pixi run spike:e2`")
    return Path(prefix) / "fonts"


def load_fonts(stack: list[str]) -> list[tuple[str, hb.Font, int]]:
    out = []
    for name in stack:
        data = (font_dir() / name).read_bytes()
        face = hb.Face(data)
        font = hb.Font(face)
        upem = face.upem
        font.scale = (upem, upem)  # advances returned in font units
        out.append((name, font, upem))
    return out


def covers(font: hb.Font, codepoint: int) -> bool:
    gid = font.get_nominal_glyph(codepoint)
    return gid is not None and gid != 0


def split_runs(text: str, fonts) -> list[tuple[int, str]]:
    """Split text into (font_index, run) using first-covering-face fallback."""
    runs: list[tuple[int, str]] = []
    current_idx = 0
    current: list[str] = []
    for ch in text:
        cp = ord(ch)
        idx = None
        if cp not in GLUE:
            for i, (_, font, _) in enumerate(fonts):
                if covers(font, cp):
                    idx = i
                    break
        if idx is None:
            current.append(ch)  # glue, or nobody covers it: stay in the run
            continue
        if current and idx != current_idx:
            runs.append((current_idx, "".join(current)))
            current = []
        current_idx = idx
        current.append(ch)
    if current:
        runs.append((current_idx, "".join(current)))
    return runs


def measure(text: str, fonts, size: float) -> tuple[float, list[dict]]:
    total = 0.0
    runs_out: list[dict] = []
    for idx, run in split_runs(text, fonts):
        name, font, upem = fonts[idx]
        buf = hb.Buffer()
        buf.add_str(run)
        buf.guess_segment_properties()
        hb.shape(font, buf)
        width = sum(pos.x_advance for pos in buf.glyph_positions) / upem * size
        total += width
        runs_out.append({"face": name, "text": run, "width": round(width, 6)})
    return total, runs_out


def run_canvaskit(corpus: dict, out_json: Path, size: float) -> dict:
    script = HERE / "measure_canvaskit.cjs"
    subprocess.run(
        ["node", str(script), str(CORPUS), str(out_json), str(size)],
        check=True,
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    return json.loads(out_json.read_text(encoding="utf-8"))


def compare_one_size(corpus: dict, fonts, size: float) -> tuple[list[dict], str]:
    tag = f"{size:g}px"
    ck = run_canvaskit(corpus, RESULTS / f"canvaskit_raw_{tag}.json", size)
    ck_by_id = {row["id"]: row for row in ck["labels"]}
    rows = []
    for label in corpus["labels"]:
        py_width, py_runs = measure(label["text"], fonts, size)
        ck_row = ck_by_id[label["id"]]
        ck_width = ck_row["width"]
        delta = abs(py_width - ck_width)
        rel = delta / ck_width if ck_width else 0.0
        run_layout_matches = [(r["face"], r["text"]) for r in py_runs] == [
            (r["face"], r["text"]) for r in ck_row["runs"]
        ]
        rows.append(
            {
                "id": label["id"],
                "category": label["category"],
                "text": label["text"],
                "font_size_px": size,
                "chars": len(label["text"]),
                "uharfbuzz_px": round(py_width, 6),
                "canvaskit_px": round(ck_width, 6),
                "canvaskit_implicit_px": round(ck_row["implicit_width"], 6),
                "abs_delta_px": round(delta, 6),
                "rel_delta": rel,
                "run_layout_matches": run_layout_matches,
                "runs": py_runs,
            }
        )
    return rows, ck["node"]


def summarize_size(rows: list[dict], size: float) -> dict:
    rels = [r["rel_delta"] for r in rows]
    failures = [r for r in rows if r["rel_delta"] >= GATE]
    by_cat: dict[str, dict] = {}
    for cat in sorted({r["category"] for r in rows}):
        subset = [r for r in rows if r["category"] == cat]
        rel_sub = [r["rel_delta"] for r in subset]
        by_cat[cat] = {
            "n": len(subset),
            "max_rel": max(rel_sub),
            "mean_rel": statistics.fmean(rel_sub),
            "max_abs_px": max(r["abs_delta_px"] for r in subset),
            "failing": sum(1 for r in rel_sub if r >= GATE),
        }

    return {
        "font_size_px": size,
        "passed": not failures,
        "overall": {
            "max_rel": max(rels),
            "mean_rel": statistics.fmean(rels),
            "p99_rel": sorted(rels)[int(len(rels) * 0.99)],
            "max_abs_px": max(r["abs_delta_px"] for r in rows),
            "failures": len(failures),
            "run_layout_mismatches": sum(1 for r in rows if not r["run_layout_matches"]),
        },
        "implicit_fallback_gap": {
            "note": (
                "CanvasKit TypefaceFontProvider does not fall back across "
                "families; these labels measure differently if the run split "
                "is skipped and only the primary family is asked for."
            ),
            "labels_needing_explicit_runs": sum(
                1
                for r in rows
                if abs(r["canvaskit_implicit_px"] - r["canvaskit_px"])
                / max(r["canvaskit_px"], 1e-9)
                >= GATE
            ),
        },
        "by_category": by_cat,
        "worst": sorted(rows, key=lambda r: r["rel_delta"], reverse=True)[:10],
    }


def main() -> int:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    fonts = load_fonts(corpus["font_stack"])
    sizes = [float(s) for s in os.environ.get("E2_SIZES", "10,12,16,24").split(",")]

    RESULTS.mkdir(exist_ok=True)
    per_size = {}
    all_rows = []
    node_version = ""
    for size in sizes:
        rows, node_version = compare_one_size(corpus, fonts, size)
        all_rows.extend(rows)
        per_size[f"{size:g}"] = summarize_size(rows, size)

    worst = max(all_rows, key=lambda r: r["rel_delta"])
    failures = sum(s["overall"]["failures"] for s in per_size.values())
    summary = {
        "experiment": "E2 uharfbuzz vs CanvasKit.Paragraph advance parity",
        "gate": f"per-label rel delta < {GATE:.2%} at every font size",
        "passed": failures == 0,
        "corpus": {
            "path": "docs/spike/corpus/labels_200.json",
            "sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
            "count": len(corpus["labels"]),
            "font_stack": corpus["font_stack"],
        },
        "method": {
            "run_split": (
                "both sides split each label into per-font runs with the rule "
                "'first face in font_stack whose cmap covers the codepoint wins; "
                "joiners/selectors/combining marks stay in the current run'"
            ),
            "uharfbuzz": "hb.shape() per run, advance summed in font units, scaled by size/upem",
            "canvaskit": "one SkParagraph per run (explicit fontFamilies), widths summed",
        },
        "versions": {
            "uharfbuzz_harfbuzz": hb.version_string(),
            "uharfbuzz_py": getattr(__import__("uharfbuzz"), "__version__", "?"),
            "canvaskit_wasm": "0.42.0",
            "node": node_version,
        },
        "sizes": [f"{s:g}" for s in sizes],
        "per_size": per_size,
        "worst_label": worst,
        "labels": all_rows,
    }
    out = RESULTS / "e2_results.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"E2 {'PASS' if failures == 0 else 'FAIL'}  gate {GATE:.2%}  sizes {sizes}")
    for size, stats in per_size.items():
        o = stats["overall"]
        print(
            f"  {size:>4s}px max {o['max_rel']:.4%} mean {o['mean_rel']:.4%} "
            f"p99 {o['p99_rel']:.4%} max|d| {o['max_abs_px']:.4f}px "
            f"fail {o['failures']} run-mismatch {o['run_layout_mismatches']}"
        )
        for cat, c in stats["by_category"].items():
            print(
                f"      {cat:9s} n={c['n']:3d} max {c['max_rel']:.4%} "
                f"mean {c['mean_rel']:.4%} max|d| {c['max_abs_px']:.4f}px fail {c['failing']}"
            )
    print(
        f"  worst {worst['id']} {worst['category']} {worst['text'][:24]!r} "
        f"at {worst.get('font_size_px', '?')}px: py={worst['uharfbuzz_px']:.4f} "
        f"ck={worst['canvaskit_px']:.4f} rel={worst['rel_delta']:.4%}"
    )
    print(f"  -> {out.relative_to(REPO)}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
