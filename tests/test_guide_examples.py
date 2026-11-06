"""`tools/docs/guide_examples.py` 的自测（M3-6 文档门禁的解析与执行口径）。

门禁本身挂在 `pixi run check` 的 `docs:guide:check` 里；这里只钉两件事：

1. 代码块解析：只收 ```python、跳过 `r` / `text`、`no-run` 注释必须带原因；
2. 执行口径：定义了 `build()` 或留下 `p` 的块会真构图并编码 IR，构图期报错必须
   判红（不是只看 import 能不能过）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_tool():
    path = ROOT / "tools" / "docs" / "guide_examples.py"
    spec = importlib.util.spec_from_file_location("guide_examples", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclass 在 `sys.modules` 里找模块（未登记时 `__module__` 解析失败）。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guide = _load_tool()


def test_parse_blocks_only_python_and_reports_empty_no_run() -> None:
    text = "\n".join(
        [
            "# 标题",
            "",
            "```r",
            "ggplot(df, aes(x, y))",
            "```",
            "",
            "<!-- no-run: 签名片段 -->",
            "```python",
            "p + geom_point()",
            "```",
            "",
            "```python",
            "x = 1",
            "```",
            "```text",
            "不是代码",
            "```",
            "<!-- no-run: -->",
            "```python",
            "y = 2",
            "```",
        ]
    )
    blocks, bad = guide.parse_blocks(text, Path("guide.md"))

    assert [block.source.strip() for block in blocks] == ["p + geom_point()", "x = 1", "y = 2"]
    assert blocks[0].skip == "签名片段"
    assert blocks[1].skip is None
    assert [number for number, _ in bad] == [18]


def test_run_block_reports_construction_errors() -> None:
    block = guide.Block(
        path=Path("guide.md"),
        line=1,
        source=(
            "from ggcore.plot import aes, geom_point, ggplot\n"
            "from ggio.frame import to_column_table\n"
            "\n"
            "p = ggplot(to_column_table({'x': [1, 2]}), aes(x='x', y='missing')) + geom_point()\n"
        ),
    )
    result = guide.run_block(block)

    assert not result.ok
    assert "missing" in result.detail


def test_run_block_builds_and_encodes_ir() -> None:
    block = guide.Block(
        path=Path("guide.md"),
        line=1,
        source=(
            "from ggcore.plot import aes, geom_point, ggplot\n"
            "from ggio.frame import to_column_table\n"
            "\n"
            "PAIR = {'x': [1, 2], 'y': [2, 1]}\n"
            "p = ggplot(to_column_table(PAIR), aes(x='x', y='y')) + geom_point()\n"
        ),
    )
    result = guide.run_block(block)

    assert result.ok, result.detail
    assert "字节 IR" in result.detail


@pytest.mark.parametrize(
    "page",
    [
        "index.md",
        "r-to-python.md",
        "browser.md",
        "aes.md",
        "data.md",
        "layers.md",
        "geom.md",
        "stat.md",
        "position.md",
        "scale.md",
        "coord.md",
        "facet.md",
        "guide.md",
        "theme.md",
        "annotation.md",
        "sf.md",
        "export.md",
    ],
)
def test_every_guide_page_is_indexed(page: str) -> None:
    index = (ROOT / "docs" / "guide" / "index.md").read_text(encoding="utf-8")
    assert (ROOT / "docs" / "guide" / page).is_file()
    if page not in {"index.md", "r-to-python.md", "browser.md"}:
        assert f"[`{page}`]({page})" in index
