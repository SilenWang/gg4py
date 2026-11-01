"""生成兜底度量表 `src/ggcore/metrics/data/metrics_table_v1.bin`（M0-7）。

表是 `ggcore.metrics.table.TableBackend` 的输入：无 HarfBuzz 的时（Pyodide 早期
路径）用逐码点 advance 量文字。数据只来自受管字体文件本身，因此

* 同一批字体 + 同一套规则 → **字节完全相同**（`--check` 就靠这一点）；
* 字体升级（sha256 变化）或规则版本变化 → 表必须重新生成，否则门禁红。

用法：

    pixi run metrics:table            # 重新生成（写仓库文件）
    pixi run metrics:check-table      # 只校验：重新生成并比对，不改文件

`--check` 同时比对 `metrics_table_v1.json`（人读的元数据：版本、字体 sha256、
覆盖数、规则版本），两者任一漂移都算失败。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import uharfbuzz as hb

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ggcore.metrics.catalog import DEFAULT_FONT_STACK, FontCatalog
from ggcore.metrics.runs import COMPLEX_SCRIPT_RANGES, GLUE_RANGES
from ggcore.metrics.table import (
    RUN_RULES_VERSION,
    TABLE_VERSION,
    TableFont,
    encode_table,
    table_path,
)
from ggshape.harfbuzz import HarfBuzzBackend

REPO = Path(__file__).resolve().parents[2]
METADATA_PATH = table_path().with_suffix(".json")


def build(catalog: FontCatalog | None = None) -> tuple[bytes, bytes]:
    """返回 (表字节, 元数据字节)。纯函数：同一字体集合 → 同一输出。"""
    resolved = catalog if catalog is not None else FontCatalog()
    backend = HarfBuzzBackend(resolved)
    fonts: list[TableFont] = []
    font_meta: list[dict] = []
    for filename in DEFAULT_FONT_STACK:
        codepoints, advances = backend.coverage(filename)
        metrics = backend.font_metrics(filename)
        notdef = backend.notdef_advance(filename)
        ligates = backend.ligates_emoji_clusters(filename)
        fonts.append(
            TableFont(
                filename=filename,
                upem=metrics.upem,
                ascent=metrics.ascent,
                descent=metrics.descent,
                notdef_advance=notdef,
                ligates_emoji=ligates,
                codepoints=np.asarray(codepoints, dtype=np.uint32),
                advances=np.asarray(advances, dtype=np.uint16),
            )
        )
        font_meta.append(
            {
                "file": filename,
                "family": resolved.family(filename),
                "sha256": resolved.sha256(filename),
                "upem": metrics.upem,
                "ascent": metrics.ascent,
                "descent": metrics.descent,
                "notdef_advance": notdef,
                "ligates_emoji_clusters": ligates,
                "covered_codepoints": len(codepoints),
            }
        )

    blob = encode_table(fonts)
    metadata = {
        "schema": 1,
        "table_version": TABLE_VERSION,
        "run_rules_version": RUN_RULES_VERSION,
        "format": "GGMT (magic) + zlib，布局见 src/ggcore/metrics/table.py",
        "generator": "tools/metrics/build_table.py",
        "generated_with": {
            "uharfbuzz": getattr(hb, "__version__", "?"),
            "harfbuzz": hb.version_string(),
            "numpy": np.__version__,
        },
        "font_stack": list(DEFAULT_FONT_STACK),
        "fonts": font_meta,
        "table_bytes": len(blob),
        "table_sha256": hashlib.sha256(blob).hexdigest(),
        "rules": {
            "glue_ranges": [list(pair) for pair in GLUE_RANGES],
            "complex_script_ranges": [list(pair) for pair in COMPLEX_SCRIPT_RANGES],
            "note": (
                "表只做逐码点 advance + 粘着码点 + grapheme cluster；"
                "不做 kerning/ligature/连写/重排（见 docs/notes/metrics-ledger.md · M0-7）"
            ),
        },
    }
    meta_bytes = (json.dumps(metadata, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    return blob, meta_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the offline metrics fallback table.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and compare with the committed table (no writes)",
    )
    args = parser.parse_args(argv)

    blob, meta_bytes = build()
    blob_path = table_path()
    meta_path = METADATA_PATH
    table_meta = json.loads(meta_bytes)

    print(
        f"metrics table v{TABLE_VERSION} (rules v{RUN_RULES_VERSION}): "
        f"{table_meta['table_bytes']} bytes, sha256={table_meta['table_sha256'][:12]}"
    )
    for font in table_meta["fonts"]:
        print(
            f"  {font['file']:24s} family={font['family']:20s} "
            f"upem={font['upem']:5d} covered={font['covered_codepoints']:6d} "
            f"ligates_emoji={font['ligates_emoji_clusters']}"
        )

    if args.check:
        problems: list[str] = []
        for path, expected in ((blob_path, blob), (meta_path, meta_bytes)):
            if not path.is_file():
                problems.append(f"missing: {path.relative_to(REPO)}")
                continue
            actual = path.read_bytes()
            if actual != expected:
                problems.append(
                    f"stale: {path.relative_to(REPO)} "
                    f"(committed {len(actual)} B, regenerated {len(expected)} B)"
                )
        if problems:
            print("metrics table is out of date:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            print("  fix: pixi run metrics:table", file=sys.stderr)
            return 1
        print("metrics table matches the fonts and rules in the tree")
        return 0

    blob_path.parent.mkdir(parents=True, exist_ok=True)
    blob_path.write_bytes(blob)
    meta_path.write_bytes(meta_bytes)
    print(f"wrote {blob_path.relative_to(REPO)}")
    print(f"wrote {meta_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
