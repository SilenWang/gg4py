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
import unicodedata
from pathlib import Path

import numpy as np
import uharfbuzz as hb

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ggcore.metrics.catalog import DEFAULT_FONT_STACK, FontCatalog
from ggcore.metrics.runs import COMPLEX_SCRIPT_RANGES, GLUE_RANGES, is_glue, is_supported
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
# 字对 kerning 的覆盖范围：cmap 里 `U+0000–U+2FFF` 的单码点字对。再往上是
# CJK / emoji 区，那里字对推进由固定宽度或合字决定，逐对枚举既慢又没用。
KERN_MAX_CODEPOINT = 0x3000


def _shape_advance(font: hb.Font, text: str) -> tuple[int, float]:
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(font, buffer)
    total = sum(float(position.x_advance) for position in buffer.glyph_positions)
    return len(buffer.glyph_infos), total


def _kern_candidates(backend: HarfBuzzBackend, filename: str) -> list[int]:
    """参与字对枚举的码点。

    只要「单独 shaping 出来恰好一个字形、且推进等于它的 hmtx advance」的码点：
    格式控制符（U+2062 之类不可见运算符）会被 HarfBuzz 整个吞掉、组合记号没有
    推进，把它们当字对左端会算出几 em 的假 kerning。
    """
    font = backend.hb_font(filename)
    codepoints, _ = backend.coverage(filename)
    out: list[int] = []
    for cp in codepoints:
        if cp >= KERN_MAX_CODEPOINT or is_glue(cp) or not is_supported(chr(cp)):
            continue
        char = chr(cp)
        if unicodedata.category(char)[0] in ("M", "C"):
            continue
        count, advance = _shape_advance(font, char)
        if count != 1:
            continue
        nominal = float(font.get_glyph_h_advance(font.get_nominal_glyph(cp) or 0))
        if abs(advance - nominal) > 1e-6:
            continue
        out.append(cp)
    return out


def kern_pairs(backend: HarfBuzzBackend, filename: str) -> tuple[np.ndarray, np.ndarray]:
    """逐字对 shape 一遍，取「整对推进 − 两个单字推进」作为增量。

    HarfBuzz 不给「查一对」的接口，而一对一次的 shaping 只要 ~1 µs：受管字体在
    这个码点范围里最多三千个码点，全量枚举是秒级，换来的是「与渲染端同一套
    GPOS/kern 结果」，也自动带上字对合字（`fi` 之类）的推进差。
    """
    font = backend.hb_font(filename)
    candidates = _kern_candidates(backend, filename)
    singles = {cp: _shape_advance(font, chr(cp))[1] for cp in candidates}
    first: list[int] = []
    second: list[int] = []
    deltas: list[int] = []
    for left in candidates:
        for right in candidates:
            _, total = _shape_advance(font, chr(left) + chr(right))
            delta = round(total - singles[left] - singles[right])
            if delta:
                first.append(left)
                second.append(right)
                deltas.append(delta)
    return (
        np.column_stack(
            [
                np.asarray(first, dtype=np.uint32),
                np.asarray(second, dtype=np.uint32),
            ]
        ),
        np.asarray(deltas, dtype=np.int16),
    )


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
        kern_codepoints, kern_deltas = kern_pairs(backend, filename)
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
                kern_codepoints=kern_codepoints,
                kern_deltas=kern_deltas,
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
                "kern_pairs": int(kern_deltas.size),
                "kern_total_units": int(kern_deltas.astype(np.int64).sum()),
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
            "kern_max_codepoint": KERN_MAX_CODEPOINT,
            "note": (
                "表做逐码点 advance + 字对 kerning（U+0000–U+2FFF，逐对 shape 抽取）"
                "+ 粘着码点 + grapheme cluster；不做连写/重排/上下文替换"
                "（见 docs/notes/metrics-ledger.md · M2-b）"
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
