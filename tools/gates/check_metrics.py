"""M0-7 门禁 · 双端度量一致性（uharfbuzz × CanvasKit，附 skia-python 与兜底表）。

判据（`docs/notes/gates.md` · X5）：

1. **双端**：`MetricProvider`（HarfBuzz 后端）与浏览器端 CanvasKit SkParagraph
   对同 200 条冻结语料、同一批字体文件给出的 advance，逐条相对差 < 0.5%，
   且 run 切分布局逐条一致（0 不一致）。
2. **桌面端**：skia-python 对同一批字形（HarfBuzz 给出的 glyph id）的 advance 与
   provider 一致（< 0.5%）——这是实际绘制的引擎，不能只在 shaping 层对上。
3. **兜底表**：`TableBackend` 与 provider 在同一条语料上 run 切分一致，且对
   「兜底表声明支持的文字」相对差 < 5%（表不做 kerning/上下文 shaping，见账本
   M0-7）；不支持的书写系统只报告不判定。
4. **灵敏度**：把字体栈砍成单字族（等于关掉 fallback）后双端必须对不上——门禁
   若在这种输入上仍然绿，说明它量的是同一侧、已经失效。
5. **兜底表新鲜度**：`tools/metrics/build_table.py --check` 必须通过（表由同一
   脚本从当前字体与规则生成）。

用法：
    pixi run gate:metrics
    pixi run gate:metrics -- --sizes 10,16 --out /tmp/metrics-gate
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from ggcore.metrics import (  # noqa: E402
    DEFAULT_FONT_STACK,
    FontCatalog,
    MetricProvider,
    TableBackend,
)
from ggshape.harfbuzz import HarfBuzzBackend, harfbuzz_provider  # noqa: E402

CORPUS = REPO / "docs" / "spike" / "corpus" / "labels_200.json"
CANVASKIT = REPO / "tools" / "metrics" / "measure_canvaskit.cjs"
BUILD_TABLE = REPO / "tools" / "metrics" / "build_table.py"
DEFAULT_SIZES = (10.0, 12.0, 16.0, 24.0)
# 双端判据：E2 实测最差 0.241%，留一倍余量。
GATE = 0.005
# 兜底表判据：表不建模 kerning，这份语料上实测最大 2.374%，取 5%。
# 2.374% 只对这份 200 条冻结语料成立：绝对差 0.05–2.72 px @16px 随字对与长度累加，
# 短标签相对差更大（`'To'` 单对 5.84%），所以这不是误差上界——见 M0-7-d。
TABLE_GATE = 0.05


def rel_delta(a: float, b: float) -> float:
    """相对差，分母取 CanvasKit/参考侧（与 E2 一致）。"""
    return abs(a - b) / b if b else 0.0


def load_corpus(path: Path = CORPUS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def measure_canvaskit(corpus_path: Path, out_path: Path, size: float) -> dict:
    proc = subprocess.run(
        ["node", str(CANVASKIT), str(corpus_path), str(out_path), f"{size:g}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "gate:metrics: CanvasKit measurement failed "
            f"(node exit {proc.returncode}); run `pixi run assets:canvaskit` "
            "(or `pixi run gate:metrics`, which installs it) first.\n"
            f"{proc.stderr.strip()}"
        )
    return json.loads(out_path.read_text(encoding="utf-8"))


def compare_dual_end(
    provider: MetricProvider,
    corpus: dict,
    canvaskit: dict,
    size: float,
    gate: float = GATE,
) -> tuple[list[dict], dict]:
    """provider（HarfBuzz）vs CanvasKit，逐标签。"""
    ck_by_id = {row["id"]: row for row in canvaskit["labels"]}
    rows: list[dict] = []
    for label in corpus["labels"]:
        py_runs = provider.runs(label["text"], size)
        py_width = math.fsum(run.width for run in py_runs)
        ck = ck_by_id[label["id"]]
        ck_width = ck["width"]
        py_layout = [(run.font, run.text) for run in py_runs]
        ck_layout = [(run["face"], run["text"]) for run in ck["runs"]]
        rows.append(
            {
                "id": label["id"],
                "category": label["category"],
                "text": label["text"],
                "chars": len(label["text"]),
                "python_px": py_width,
                "canvaskit_px": ck_width,
                "canvaskit_implicit_px": ck["implicit_width"],
                "rel_delta": rel_delta(py_width, ck_width),
                "run_layout_matches": py_layout == ck_layout,
                "runs": [
                    {"face": run.font, "text": run.text, "width": run.width} for run in py_runs
                ],
            }
        )
    return rows, summarize(rows, size, gate)


def summarize(rows: list[dict], size: float, gate: float) -> dict:
    rels = [row["rel_delta"] for row in rows]
    failures = [row for row in rows if row["rel_delta"] >= gate]
    by_category: dict[str, dict] = {}
    for category in sorted({row["category"] for row in rows}):
        subset = [row for row in rows if row["category"] == category]
        category_rels = [row["rel_delta"] for row in subset]
        by_category[category] = {
            "n": len(subset),
            "max_rel": max(category_rels),
            "mean_rel": sum(category_rels) / len(category_rels),
            "failing": sum(1 for rel in category_rels if rel >= gate),
        }
    return {
        "font_size_px": size,
        "gate": gate,
        "passed": not failures,
        "overall": {
            "max_rel": max(rels),
            "mean_rel": sum(rels) / len(rels),
            "p99_rel": sorted(rels)[int(len(rels) * 0.99)],
            "failures": len(failures),
            "run_layout_mismatches": sum(1 for row in rows if not row["run_layout_matches"]),
            "labels_needing_explicit_runs": sum(
                1
                for row in rows
                if rel_delta(row["canvaskit_implicit_px"], row["canvaskit_px"]) >= gate
            ),
        },
        "by_category": by_category,
        "worst": sorted(rows, key=lambda row: row["rel_delta"], reverse=True)[:5],
    }


def compare_table(
    provider: MetricProvider,
    table_provider: MetricProvider,
    corpus: dict,
    size: float,
) -> list[dict]:
    """兜底表 vs provider：run 切分必须一致，支持的文字按 TABLE_GATE 判定。"""
    rows: list[dict] = []
    for label in corpus["labels"]:
        text = label["text"]
        hb_runs = provider.runs(text, size)
        table_runs = table_provider.runs(text, size)
        reference = math.fsum(run.width for run in hb_runs)
        candidate = math.fsum(run.width for run in table_runs)
        rows.append(
            {
                "id": label["id"],
                "category": label["category"],
                "supported": table_provider.supports(text),
                "python_px": reference,
                "table_px": candidate,
                "rel_delta": rel_delta(candidate, reference),
                "run_layout_matches": [(r.font, r.text) for r in hb_runs]
                == [(r.font, r.text) for r in table_runs],
            }
        )
    return rows


def compare_skia(
    backend: HarfBuzzBackend,
    provider: MetricProvider,
    corpus: dict,
    size: float,
) -> tuple[list[dict], str]:
    """skia-python 与 HarfBuzz 对同一批字形给出的 advance 是否一致（桌面端）。

    比的是**逐字形 advance**（hmtx / CBDT 位图 strike 推导出的宽度），不是整段
    文字宽度：`SkFont.getWidths` 不做 kerning/ligature shaping，而 provider 的宽度
    是 shaping 之后的，直接比会把 kern 差算成实现差异。这里两侧都是「同一字体
    文件里同一个 glyph id 的宽度」，才是桌面端绘制真正依赖的量；emoji 的 CBDT
    strike 推导差异也正是在这一层暴露（账本 L1）。
    """
    import skia

    typefaces: dict[str, object] = {}
    faces: dict[str, object] = {}

    def skia_font(filename: str) -> object:
        font = faces.get(filename)
        if font is None:
            face = typefaces.get(filename)
            if face is None:
                face = skia.Typeface.MakeFromFile(str(provider.catalog.path(filename)))
                if face is None:
                    raise SystemExit(f"gate:metrics: skia cannot load {filename}")
                typefaces[filename] = face
            font = skia.Font(face, size)
            # 线性（未 hint）度量 + 亚像素：与 HarfBuzz 的「字体单位 × size/upem」同口径。
            font.setSubpixel(True)
            font.setLinearMetrics(True)
            font.setHinting(skia.FontHinting.kNone)
            faces[filename] = font
        return font

    rows: list[dict] = []
    for label in corpus["labels"]:
        skia_total = 0.0
        harfbuzz_total = 0.0
        for run in provider.runs(label["text"], size):
            metrics = provider.font_metrics(run.font)
            shaped = backend.shape(run.font, run.text)
            units = backend.glyph_advances(run.font, shaped.gids)
            harfbuzz_total += math.fsum(units) / metrics.upem * size
            skia_total += math.fsum(skia_font(run.font).getWidths(list(shaped.gids)))
        rows.append(
            {
                "id": label["id"],
                "category": label["category"],
                "harfbuzz_glyph_px": harfbuzz_total,
                "skia_python_px": skia_total,
                "rel_delta": rel_delta(skia_total, harfbuzz_total),
            }
        )
    return rows, getattr(skia, "__version__", "?")


def check_sensitivity(
    provider: MetricProvider,
    corpus: dict,
    canvaskit: dict,
    size: float,
) -> dict:
    """字体栈只剩主字族 = 关掉 fallback；双端必须对不上。"""
    degraded = MetricProvider(
        HarfBuzzBackend(provider.catalog),
        catalog=provider.catalog,
        font_stack=(DEFAULT_FONT_STACK[0],),
    )
    _, summary = compare_dual_end(degraded, corpus, canvaskit, size)
    return {
        "font_stack": [DEFAULT_FONT_STACK[0]],
        "failures": summary["overall"]["failures"],
        "max_rel": summary["overall"]["max_rel"],
        "run_layout_mismatches": summary["overall"]["run_layout_mismatches"],
        "detected": summary["overall"]["failures"] > 0,
    }


def check_table_freshness() -> dict:
    proc = subprocess.run(
        [sys.executable, str(BUILD_TABLE), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "passed": proc.returncode == 0,
        "returncode": proc.returncode,
        "output": (proc.stdout + proc.stderr).strip(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M0-7: uharfbuzz vs CanvasKit metrics gate.")
    parser.add_argument(
        "--sizes",
        default=",".join(f"{size:g}" for size in DEFAULT_SIZES),
        help="comma separated font sizes in px (default: 10,12,16,24)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / ".gate-metrics",
        help="directory for intermediate measurements and the report (default: .gate-metrics)",
    )
    parser.add_argument(
        "--gate", type=float, default=GATE, help="dual-end tolerance (default 0.005)"
    )
    args = parser.parse_args(argv)

    sizes = [float(value) for value in args.sizes.split(",") if value.strip()]
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    corpus = load_corpus()
    catalog = FontCatalog()
    provider = harfbuzz_provider(catalog)
    backend = provider.backend
    table_provider = MetricProvider(TableBackend.from_file(), catalog=catalog)

    if tuple(corpus["font_stack"]) != tuple(provider.font_stack):
        print(
            "gate:metrics: FAIL — corpus font_stack differs from rules.json default_font_stack",
            file=sys.stderr,
        )
        print(f"  corpus: {corpus['font_stack']}", file=sys.stderr)
        print(f"  rules : {list(provider.font_stack)}", file=sys.stderr)
        return 2

    report: dict = {
        "gate": "M0-7 dual-end metrics (uharfbuzz × CanvasKit)",
        "corpus": str(CORPUS.relative_to(REPO)),
        "font_stack": list(provider.font_stack),
        "sizes": sizes,
        "thresholds": {"dual_end": args.gate, "table": TABLE_GATE},
        "per_size": {},
    }
    failures: list[str] = []

    for size in sizes:
        started = time.perf_counter()
        canvaskit = measure_canvaskit(CORPUS, out_dir / f"canvaskit_{size:g}px.json", size)
        _, summary = compare_dual_end(provider, corpus, canvaskit, size, args.gate)
        table_rows = compare_table(provider, table_provider, corpus, size)
        supported = [row for row in table_rows if row["supported"]]
        unsupported = [row for row in table_rows if not row["supported"]]
        table_summary = {
            "supported_n": len(supported),
            "unsupported_n": len(unsupported),
            "max_rel": max((row["rel_delta"] for row in supported), default=0.0),
            "mean_rel": (
                sum(row["rel_delta"] for row in supported) / len(supported) if supported else 0.0
            ),
            "failures": [row["id"] for row in supported if row["rel_delta"] >= TABLE_GATE],
            "run_layout_mismatches": sum(1 for row in table_rows if not row["run_layout_matches"]),
        }
        skia_rows, skia_version = compare_skia(backend, provider, corpus, size)
        skia_summary = {
            "version": skia_version,
            "max_rel": max(row["rel_delta"] for row in skia_rows),
            "mean_rel": sum(row["rel_delta"] for row in skia_rows) / len(skia_rows),
            "failures": [row["id"] for row in skia_rows if row["rel_delta"] >= args.gate],
        }
        sensitivity = check_sensitivity(provider, corpus, canvaskit, size)
        elapsed = time.perf_counter() - started

        report["per_size"][f"{size:g}"] = {
            "dual_end": summary,
            "table_fallback": table_summary,
            "skia_python": skia_summary,
            "sensitivity": sensitivity,
            "seconds": round(elapsed, 3),
        }

        overall = summary["overall"]
        print(
            f"M0-7 {size:>4g}px  dual-end max {overall['max_rel']:.4%} "
            f"mean {overall['mean_rel']:.4%} fail {overall['failures']} "
            f"run-mismatch {overall['run_layout_mismatches']} "
            f"explicit-run-labels {overall['labels_needing_explicit_runs']}"
        )
        print(
            f"          table max {table_summary['max_rel']:.4%} "
            f"mean {table_summary['mean_rel']:.4%} "
            f"(supported {table_summary['supported_n']}, "
            f"unsupported {table_summary['unsupported_n']}) "
            f"fail {len(table_summary['failures'])} "
            f"run-mismatch {table_summary['run_layout_mismatches']}"
        )
        print(
            f"          skia-python {skia_version} max {skia_summary['max_rel']:.4%} "
            f"mean {skia_summary['mean_rel']:.4%} fail {len(skia_summary['failures'])} "
            f"({elapsed:.1f}s)"
        )
        for category, stats in summary["by_category"].items():
            print(
                f"          {category:9s} n={stats['n']:3d} max {stats['max_rel']:.4%} "
                f"mean {stats['mean_rel']:.4%} fail {stats['failing']}"
            )
        worst = summary["worst"][0]
        print(
            f"          worst {worst['id']} {worst['category']} {worst['text'][:20]!r} "
            f"py={worst['python_px']:.4f} ck={worst['canvaskit_px']:.4f} "
            f"rel={worst['rel_delta']:.4%}"
        )
        if not sensitivity["detected"]:
            failures.append(
                f"{size:g}px: sensitivity check did not fail with a single-family stack"
            )
        if not summary["passed"]:
            failures.append(f"{size:g}px: dual-end failures {overall['failures']}")
        if overall["run_layout_mismatches"]:
            failures.append(f"{size:g}px: run layout mismatches {overall['run_layout_mismatches']}")
        if table_summary["failures"]:
            failures.append(f"{size:g}px: table fallback failures {table_summary['failures'][:5]}")
        if table_summary["run_layout_mismatches"]:
            failures.append(
                f"{size:g}px: table run layout mismatches {table_summary['run_layout_mismatches']}"
            )
        if skia_summary["failures"]:
            failures.append(f"{size:g}px: skia-python failures {skia_summary['failures'][:5]}")

    table_freshness = check_table_freshness()
    report["table_freshness"] = table_freshness
    report["cache"] = provider.cache_stats()
    if not table_freshness["passed"]:
        failures.append("metrics table is stale (pixi run metrics:table)")

    report["failures"] = failures
    report["passed"] = not failures
    report_path = out_dir / "metrics_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    stats = provider.cache_stats()
    print(
        f"          cache entries={stats['entries']} hits={stats['hits']} "
        f"misses={stats['misses']} hit-rate={stats['hit_rate']:.1%}"
    )
    print(f"          table freshness: {'ok' if table_freshness['passed'] else 'STALE'}")
    print(f"          report: {report_path.relative_to(REPO)}")

    if failures:
        print("gate:metrics: FAIL", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(f"gate:metrics: ok — dual-end < {args.gate:.2%} on {len(corpus['labels'])} labels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
