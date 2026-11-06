"""gallery 链接检查（SIL-828 / M3-7）：脚本本身的自测 + 仓库现状的离线门禁。

外链判 200 需要网络，不进 CI（`pixi run docs:links` 才是那一步）。这里只钉两件事：

1. 解析器认得 Markdown 链接 / 自动链接 / `pixi run …`，并跳过锚点与
   `examples:<name>` 这类占位写法；
2. 仓库现状（本地目标 + 文档里写的任务）在 `--offline` 下是绿的——新增示例忘了
   登记任务、或文档里的相对路径失效，都会在这里红。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools" / "gallery"))

import links


def test_markdown_links_split_external_local_and_skip_anchors(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "\n".join(
            [
                "| [Heatmap](https://r-graph-gallery.com/215-the-heatmap-function.html) | x |",
                "![shot](../examples/heatmap/heatmap.png)",
                "[锚点](#section) [邮件](mailto:a@b.c)",
                "<https://pixi.sh>",
            ]
        ),
        encoding="utf-8",
    )
    items = links._md_links(doc)
    targets = [(item.target, item.kind) for item in items]
    assert ("https://r-graph-gallery.com/215-the-heatmap-function.html", "external") in targets
    assert ("../examples/heatmap/heatmap.png", "local") in targets
    assert ("https://pixi.sh", "external") in targets
    assert all(not target.startswith(("#", "mailto:")) for target, _ in targets)


def test_documented_commands_must_exist_and_placeholders_are_skipped(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "\n".join(
            [
                "`pixi run examples:heatmap` 重画",
                "(`pixi run examples:<name>` regenerates)",
                "`pixi run no:such:task` 是坏引用",
            ]
        ),
        encoding="utf-8",
    )
    tasks = {"examples:heatmap": "…"}
    results = links._command_links([doc], tasks)
    summary = [(result.item.target, result.status) for result in results]
    assert ("pixi run examples:heatmap", "ok") in summary
    assert ("pixi run no:such:task", "fail") in summary
    assert all(target != "pixi run examples" for target, _ in summary)


def test_repository_gallery_links_are_green_offline() -> None:
    """仓库现状：本地目标都在、文档里写的任务都存在（不联网）。"""
    completed = subprocess.run(
        [sys.executable, str(REPO / "tools" / "gallery" / "links.py"), "--offline"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
