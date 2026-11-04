#!/usr/bin/env python
"""G10a 的临时量尺：把 `g10_cases/*.py` 复制成临时三文件 case 后 render + diff。

    pixi run python tools/upstream/g10_measure.py [slug ...]

候选模块必须导出 `SNAPSHOT = "<guide-axis/foo.svg>"`（上游 `_snaps` 下的相对路径）。
临时 case 落在 `.g10/<slug>/`（不入库），所以不污染 `docs/cases` 与矩阵。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).resolve().parent / "g10_cases"
SCRATCH = ROOT / ".g10"
UPSTREAM = ROOT / ".upstream-gg"


def _snapshot_root() -> Path:
    trees = sorted(UPSTREAM.glob("ggplot2-*"))
    if not trees:
        raise SystemExit("缺 .upstream-gg：先跑 `pixi run snapshots:fetch`")
    return trees[-1] / "tests" / "testthat" / "_snaps"


def _snapshot_of(module: Path) -> str:
    for line in module.read_text(encoding="utf-8").splitlines():
        if line.startswith("SNAPSHOT = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f'{module.name}: 缺 SNAPSHOT = "<path>.svg"')


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ, PYTHONPATH="src")
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, env=environment)


def measure(slug: str) -> dict[str, object]:
    module = CASES / f"{slug}.py"
    snapshot = _snapshot_of(module)
    case = SCRATCH / slug
    case.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(module, case / "plot.py")
    shutil.copyfile(_snapshot_root() / snapshot, case / "expected.svg")
    (case / "meta.toml").write_text(
        f'family = "g10"\nfeatures = []\nci = false\nsource = "upstream:{snapshot}"\n',
        encoding="utf-8",
    )
    rendered = _run(
        [
            sys.executable,
            "-m",
            "ggskia.cli.render",
            str(case),
            "--format",
            "svg",
            "--out",
            str(case / "current"),
        ]
    )
    if rendered.returncode != 0:
        return {
            "slug": slug,
            "verdict": f"render {rendered.returncode}",
            "detail": rendered.stderr.strip()[-400:],
        }
    diffed = _run(
        [
            sys.executable,
            "-m",
            "ggdiff.cli",
            str(case),
            "--report",
            str(case / "diff_report.md"),
            "--json",
        ]
    )
    try:
        payload = json.loads(diffed.stdout[diffed.stdout.index("{") :])
    except (ValueError, json.JSONDecodeError):
        return {
            "slug": slug,
            "verdict": f"diff {diffed.returncode}",
            "detail": diffed.stderr.strip()[-400:],
        }
    return {
        "slug": slug,
        "verdict": payload.get("verdict", "?"),
        "image": payload.get("image_diff_fraction"),
        "mean": payload.get("mean_diff"),
    }


def main(argv: list[str]) -> int:
    slugs = argv or sorted(path.stem for path in CASES.glob("*.py"))
    for slug in slugs:
        result = measure(slug)
        image = result.get("image")
        mean = result.get("mean")
        numbers = "" if image is None else f"  image={image:.4%}  mean={mean:.4%}"
        print(f"{result['slug']:<56} {result['verdict']:<8}{numbers} {result.get('detail', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
