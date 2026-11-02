"""生成 `src/ggcore/metrics/data/scripts.json`：码点 → HarfBuzz script 标签。

`runs.script_segments()` 要在 shaping 前按真实 script 切段，而 ggcore 只能依赖
标准库 + numpy（X1），不能 import uharfbuzz。这里把 HarfBuzz 自己的 unicode
script 判定冻结成 JSON：表中没有的码点（Common / Inherited / 未分配）由调用方
黏在前一段上。

uharfbuzz 0.57 没有导出 `hb_unicode_script()`，用单码点 buffer 的
`guess_segment_properties()` 取同一个判定（强 script → 标签，Common → None）。

这张表只服务 Python 侧的 shaping 分段：CanvasKit 的 SkParagraph 自己按 script
切段，两端没有「script 表」契约，所以它不进 `rules.json`，也不影响兜底表版本。

用法：

    pixi run python tools/metrics/build_scripts.py            # 重新生成
    pixi run python tools/metrics/build_scripts.py --check    # 只校验
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uharfbuzz as hb

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / "src" / "ggcore" / "metrics" / "data" / "scripts.json"


def script_table() -> list[list[str]]:
    """把 0..0x10FFFF 压成按码点升序、互不重叠的 [lo, hi, tag] 区间。"""
    ranges: list[list[str]] = []
    previous: str | None = None
    start = 0
    for codepoint in range(0x110000):
        if 0xD800 <= codepoint <= 0xDFFF:  # 代理区不是合法字符
            continue
        buffer = hb.Buffer()
        buffer.add_str(chr(codepoint))
        buffer.guess_segment_properties()
        tag = buffer.script
        if tag != previous:
            if previous is not None:
                ranges.append([f"{start:04x}", f"{codepoint - 1:04x}", previous])
            previous = tag
            start = codepoint
    if previous is not None:
        ranges.append([f"{start:04x}", "10ffff", previous])
    return ranges


def render() -> str:
    note = (
        "码点 → HarfBuzz script 标签（ISO 15924）。ggcore 不能 import uharfbuzz，"
        "所以把 HarfBuzz 的 unicode script 数据冻结在这里，供 "
        "ggcore.metrics.runs.script_segments() 在 shaping 前按真实 script 切段。"
        "未列出的码点 = Common / Inherited / 未分配，不新起段。"
        "由 tools/metrics/build_scripts.py 生成，不要手改。"
    )
    rows = ",\n".join(f'  ["{low}", "{high}", "{tag}"]' for low, high, tag in script_table())
    source = f"harfbuzz {hb.version_string()} (uharfbuzz {hb.__version__})"
    return (
        "{\n"
        f' "note": {json.dumps(note, ensure_ascii=False)},\n'
        f' "source": {json.dumps(source)},\n'
        ' "ranges": [\n'
        f"{rows}\n"
        " ]\n"
        "}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze HarfBuzz unicode script data.")
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    args = parser.parse_args(argv)

    rendered = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8")
        if current != rendered:
            print(f"{TARGET.relative_to(REPO)} is stale; rerun this script", file=sys.stderr)
            return 1
        print(f"{TARGET.relative_to(REPO)} is up to date")
        return 0
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
