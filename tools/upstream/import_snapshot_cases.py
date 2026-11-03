#!/usr/bin/env python
"""把上游 `_snaps` 里已复刻的快照写成三文件 case（SIL-745）。

    pixi run snapshots:fetch                 # 先按 pin 拉一份源码
    pixi run snapshots:import                # 只生成/更新源码文件与 meta.toml
    pixi run snake...（渲染与比对走 cases:matrix）

每个条目声明四件事：case 名、上游快照路径、vdiffr 的 doppelganger 名（它就是
上游快照里的标题文字）、以及 `build()` 的函数体。`expected.svg` 直接从
`.upstream-gg/` 复制——**不做任何改写**，因为 vdiffr 快照的 `expected.svg` 对
我们就是一个合法参考图（同一条 svglite 产线）。

`tools/upstream/snapshots.toml` 里的 `[snapshots."<path>"] case = "<slug>"` 由
本脚本同步维护，所以处置清单与 case 目录不会各说各话。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import snapshots  # noqa: E402

CASES = ROOT / "docs" / "cases"

#: 主题族的公共数据与形状（`test-theme.R` 的 "themes don't change without
#: acknowledgement" 与 "themes look decent at larger base sizes"）。
THEME_DATA = '{"x": [1, 2, 3], "y": [1, 2, 3], "z": ["a", "b", "a"], "a": [1, 1, 1]}'

THEME_BODY = """\
def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + facet_wrap("a")
        + {theme}({args})
        + labs(title="{title}")
    )
    return {{"plot": p, "size": [10, 8]}}
"""

#: 指南族的公共形状（`test-guides.R` 的 "guides are positioned correctly"）。
GUIDE_DATA = '{"x": [1.0], "y": [1.0], "z": ["a"]}'

GUIDE_BODY = """\
def build():
    base = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + labs(title="title of plot")
        + theme_test()
        + theme(
            **{{
                "axis.text.x": element_text(angle=90, vjust=0.5),
                "legend.background": element_rect(fill="grey90"),
                "legend.key": element_rect(fill="grey90"),
            }}
        )
        + scale_x_continuous(breaks=(1,), labels=("very long axis label",))
        + scale_y_continuous(breaks=(1,), labels=("very long axis label",))
    )
    p = (
        base
        + {facet}
        + theme(**{{"legend.position": "{position}"}})
        + labs(title="{title}")
    )
    return {{"plot": p, "size": [10, 8]}}
"""


def _theme_specs() -> list[dict[str, Any]]:
    specs = []
    for name in (
        "bw",
        "classic",
        "dark",
        "minimal",
        "gray",
        "light",
        "void",
        "linedraw",
    ):
        specs.append(
            {
                "slug": f"upstream-theme-{name}",
                "snapshot": f"theme/theme-{name}.svg",
                "title": f"theme_{name}",
                "data": THEME_DATA,
                "body": THEME_BODY.format(theme=f"theme_{name}", args="", title=f"theme_{name}"),
            }
        )
        specs.append(
            {
                "slug": f"upstream-theme-{name}-large",
                "snapshot": f"theme/theme-{name}-large.svg",
                "title": f"theme_{name}_large",
                "data": THEME_DATA,
                "body": THEME_BODY.format(
                    theme=f"theme_{name}", args="base_size=33", title=f"theme_{name}_large"
                ),
            }
        )
    return specs


def _guide_specs() -> list[dict[str, Any]]:
    specs = []
    positions = ("left", "bottom", "right", "top")
    for _kind, facet, prefix in (
        ("grid", 'facet_grid(rows="x", cols="y")', "facet-grid"),
        ("wrap", 'facet_wrap("x")', "facet-wrap"),
    ):
        for position in positions:
            specs.append(
                {
                    "slug": f"upstream-guides-{prefix}-legend-{position}",
                    "snapshot": f"guides/{prefix}-legend-on-{position}.svg",
                    "title": f"{prefix.replace('-', '_')}, legend on {position}",
                    "data": GUIDE_DATA,
                    "body": GUIDE_BODY.format(
                        facet=facet,
                        position=position,
                        title=f"{prefix.replace('-', '_')}, legend on {position}",
                    ),
                }
            )
    return specs


def specs() -> list[dict[str, Any]]:
    # `upstream-theme-bw` 是先手写验证过的原型，保留它的 plot.py 不动。
    # 三个 `base_size = 33` 变体实测超阈（geom 缺省尺寸没跟 `theme$pointsize` 走，
    # 见 tools/upstream/snapshots.toml 的 reason），按缺口归口，不生成 case。
    skip = {
        "upstream-theme-bw",
        "upstream-theme-bw-large",
        "upstream-theme-classic-large",
        "upstream-theme-linedraw-large",
    }
    return [spec for spec in _theme_specs() + _guide_specs() if spec["slug"] not in skip]


_PLOT_NAMES = (
    "aes",
    "facet_grid",
    "facet_wrap",
    "geom_point",
    "ggplot",
    "labs",
    "scale_x_continuous",
    "scale_y_continuous",
)
_THEME_NAMES = (
    "bw",
    "classic",
    "dark",
    "gray",
    "light",
    "linedraw",
    "minimal",
    "test",
    "void",
)
_ELEMENT_NAMES = ("element_rect", "element_text", "theme")


def _plot_source(spec: dict[str, Any]) -> str:
    body = spec["body"]
    plot_imports = [name for name in _PLOT_NAMES if f"{name}(" in body or f'"{name}"' in body]
    theme_imports = [f"theme_{name}" for name in _THEME_NAMES if f"theme_{name}(" in body]
    element_imports = [name for name in _ELEMENT_NAMES if f"{name}(" in body]
    lines = [
        '"""上游快照复刻。',
        "",
        f"源：{spec['snapshot']}（vdiffr 名 {spec['title']!r}）。",
        "自动生成：`pixi run snapshots:import`。expected.svg 是上游那份，未改写。",
        '"""',
        "",
        "from ggcore.plot import (",
        *[f"    {name}," for name in plot_imports],
        ")",
    ]
    theme_all = element_imports + theme_imports
    if theme_all:
        lines.extend(["from ggcore.theme import (", *[f"    {name}," for name in theme_all], ")"])
    lines.extend(
        [
            "from ggio.frame import to_column_table",
            "",
            f"DATA = {spec['data']}",
            "",
            "",
            body,
        ]
    )
    return "\n".join(lines)


def _meta_source(spec: dict[str, Any]) -> str:
    family = spec["snapshot"].split("/")[0]
    family = "guides" if family == "guides" else "theme"
    if family == "guides":
        facet = "facet-grid" if "facet-grid" in spec["slug"] else "facet-wrap"
        features = ["aes-mapping", facet, f"legend-{spec['title'].rsplit(' ', 1)[-1]}"]
    else:
        features = ["aes-mapping", "facet-wrap", "legend-right", f"theme-{spec['title']}"]
    return (
        f'family = "{family}"\n'
        f"features = {json.dumps(features)}\n"
        "ci = true\n"
        f'title = "上游快照：{spec["title"]}"\n'
        f'source = "upstream:tests/testthat/_snaps/{spec["snapshot"]}"\n'
        "tolerance = { png = 0.02 }\n"
        'notes = "SIL-745：vdiffr 快照原样纳入；标题是 doppelganger 名。"\n'
    )


def write_cases(*, only: list[str] | None = None, dry_run: bool = False) -> int:
    tree = snapshots.fetch(force=False)
    snaps = tree / "tests" / "testthat" / "_snaps"
    written = 0
    for spec in specs():
        if only and spec["slug"] not in only:
            continue
        source = snaps / spec["snapshot"]
        if not source.is_file():
            print(f"missing upstream snapshot: {spec['snapshot']}", file=sys.stderr)
            return 1
        target = CASES / spec["slug"]
        files = {
            target / "plot.py": _plot_source(spec),
            target / "meta.toml": _meta_source(spec),
        }
        for path, content in files.items():
            if dry_run:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                path.write_text(content, encoding="utf-8")
                written += 1
        expected = target / "expected.svg"
        if not dry_run:
            expected.parent.mkdir(parents=True, exist_ok=True)
            if not expected.is_file() or snapshots._sha256(expected) != snapshots._sha256(source):
                shutil.copyfile(source, expected)
                written += 1
    print(f"{'would write' if dry_run else 'wrote'} {written} files for {len(specs())} cases")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", action="append", help="只处理这些 case 名（可重复）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return write_cases(only=args.only, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
