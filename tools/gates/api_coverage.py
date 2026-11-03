#!/usr/bin/env python
"""`api:coverage`：v4.0.3 导出 → 注册表 / 公开命名空间的覆盖门禁（SIL-745）。

    pixi run api:coverage            # 计算 → 重写 docs/notes/api-coverage.md
    pixi run api:coverage:check      # 只校验：阈值 + 缺口归口 + 文档新鲜度
    pixi run api:coverage --refresh /path/to/ggplot2/NAMESPACE
                                     # 换 pin 时重生成 tools/gates/upstream_api.json
    pixi run api:coverage --json     # 机读结果（不写文件）

## 分子是什么

分母钉死在上游 v4.0.3 的 `NAMESPACE`（`tools/gates/upstream_api.json` 是它的快照，
CI 不联网）。分母按前缀分类，并去掉两个**不是分类构造器**的裸名字：
`guides()`（批量设置入口）与 `theme()`（局部主题构造器）——它们本身不是
geom/stat/… 组件，上游自己的分类也不把它们算进那一类。

分子有两个口径，报告里都写：

1. **public**（门禁判据）：`ggcore.registry` 里的组件名 **或** `ggcore.plot`
   命名空间里的同名可调用对象。用这个口径是因为上游有相当一批导出**不是组件
   构造器**：`theme_set()` / `theme_get()` / `theme_update()` / `theme_replace()`、
   4.0 的 `theme_sub_*()`、guide 的协议钩子 `guide_train()` / `guide_geom()` /
   `guide_merge()` / `guide_transform()` / `guide_gengrob()`、以及 `scale_type()`。
   把它们塞进注册表会让 `registered("theme")` 里混进「不是一套主题」的东西
   （`docs/notes/theme.md` 的派生表会因此多出十几行），所以它们只出现在公开
   命名空间。
2. **registry**（透明口径）：只数 `registered(kind)`。它比 public 低，差额就是
   上面这批函数；报告里逐条列出。

## 缺口必须有归口

没覆盖的导出不是「算进百分比就算了」：每一条都要在 `GAPS` 里有 issue 与原因，
否则门禁红。这是「缺口清单为空或全部有 issue 归口」的机器实现。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

DATA = ROOT / "tools" / "gates" / "upstream_api.json"
DOC = ROOT / "docs" / "notes" / "api-coverage.md"

THRESHOLD = 0.90

#: 上游钉版（与 docs/notes/upstream.md 的 `- commit:` 同一行来源）。
PIN = {
    "repo": "tidyverse/ggplot2",
    "tag": "v4.0.3",
    "commit": "cc1444c10edb87650fbe0cb31d56f0da1a255634",
}

#: 缺口 → (issue, 原因)。没登记就没归口，门禁直接红。
GAPS: dict[str, tuple[str, str]] = {
    "geom_freqpoly": (
        "SIL-715",
        '`geom_freqpoly()` 是 `geom_line(stat = "bin")` 的形状；`Geom` 目前还不带'
        '「换默认 stat」的入口，登记它会让 `registered_renderers() == registered("geom")`'
        " 的不变量要求多写一个渲染器（SIL-779 钉的口径）。",
    ),
    "geom_sf": (
        "SIL-715",
        "空间几何（M3-2）：需要 sf 数据的 *list-column* 解析与 geom_sf 的 grob 路径；"
        "M2 只做注册会破坏「注册即绘制」的不变量。",
    ),
    "geom_sf_label": ("SIL-715", "同 `geom_sf`：M3-2 空间能力。"),
    "geom_sf_text": ("SIL-715", "同 `geom_sf`：M3-2 空间能力。"),
    "stat_density2d_filled": (
        "SIL-715",
        "上游只是 `stat_density_2d_filled` 的别名；`STAT_GEOMS` 是「一个 stat 一个"
        "默认 geom」，加别名要先决定它挂哪个 geom，排进 SIL-715 的别名清理。",
    ),
    "stat_sf": ("SIL-715", "同 `geom_sf`：M3-2 空间能力。"),
    "stat_sf_coordinates": ("SIL-715", "同 `geom_sf`：M3-2 空间能力。"),
}

#: 种类的上游前缀。写在这里而不是 JSON 里，是因为它同时决定注册表的 kind。
KINDS: dict[str, str] = {
    "geom": "geom_",
    "stat": "stat_",
    "scale": "scale_",
    "coord": "coord_",
    "facet": "facet_",
    "guide": "guide_",
    "position": "position_",
    "theme": "theme_",
}

#: 前缀命中但**不属于该分类组件**的裸名字（见模块文档「分子是什么」）。
EXCLUDE: dict[str, tuple[str, ...]] = {"guide": ("guides",), "theme": ("theme",)}


def _exports(namespace: Path) -> list[str]:
    pattern = re.compile(r"^export\((.+)\)$")
    names: list[str] = []
    for line in namespace.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            names.append(match.group(1))
    return names


def build_surface(namespace: Path, *, pin: dict[str, str]) -> dict[str, Any]:
    exports = _exports(namespace)
    categories: dict[str, Any] = {}
    for kind, prefix in KINDS.items():
        excluded = set(EXCLUDE.get(kind, ()))
        names = sorted(
            {name for name in exports if name.startswith(prefix) and name not in excluded}
        )
        categories[kind] = {
            "prefix": prefix,
            "exclude": sorted(excluded),
            "exports": names,
        }
    return {
        "pin": pin,
        "source": "NAMESPACE",
        "threshold": THRESHOLD,
        "categories": categories,
    }


def load_surface() -> dict[str, Any]:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _public_namespace() -> Any:
    from ggcore import plot

    return plot


def measure(surface: dict[str, Any]) -> dict[str, Any]:
    """每个分类的 upstream / registry / public 三个数 + 缺口。"""
    from ggcore import registry

    namespace = _public_namespace()
    rows: list[dict[str, Any]] = []
    for kind, category in surface["categories"].items():
        upstream = category["exports"]
        registered = {category["prefix"] + name for name in registry.registered(kind)}
        public = {name for name in upstream if hasattr(namespace, name)}
        covered = {name for name in upstream if name in registered or name in public}
        registry_only = registered & set(upstream)
        rows.append(
            {
                "kind": kind,
                "upstream": len(upstream),
                "registry": len(registry_only),
                "public": len(covered),
                "coverage": len(covered) / len(upstream) if upstream else 1.0,
                "registry_coverage": len(registry_only) / len(upstream) if upstream else 1.0,
                "gaps": [name for name in upstream if name not in covered],
                "surface_only": sorted(public - registered),
            }
        )
    upstream_total = sum(row["upstream"] for row in rows)
    public_total = sum(row["public"] for row in rows)
    registry_total = sum(row["registry"] for row in rows)
    return {
        "pin": surface["pin"],
        "threshold": surface.get("threshold", THRESHOLD),
        "rows": rows,
        "upstream_total": upstream_total,
        "public_total": public_total,
        "registry_total": registry_total,
        "overall": public_total / upstream_total if upstream_total else 1.0,
        "registry_overall": registry_total / upstream_total if upstream_total else 1.0,
        "gaps": [gap for row in rows for gap in row["gaps"]],
    }


def _pct(value: float) -> str:
    return f"{value:.1%}"


def render_report(result: dict[str, Any]) -> str:
    pin = result["pin"]
    threshold = result["threshold"]
    lines = [
        "# API 覆盖率（v4.0.3 NAMESPACE → 注册表 / 公开命名空间）",
        "",
        "<!-- 生成物：`pixi run api:coverage`；`pixi run api:coverage:check` 校验阈值、",
        "     缺口归口与本文是否最新。不要手改本文件。 -->",
        "",
        f"- 参考实现：`{pin['repo']}` `{pin['tag']}` @ `{pin['commit']}`",
        "- 分母：上游 `NAMESPACE` 里按前缀分类的导出（快照 "
        "`tools/gates/upstream_api.json`，CI 不联网）",
        f"- 门禁阈值：每个分类 ≥ {threshold:.0%}，整体 ≥ {threshold:.0%}",
        "- 分子（判据，`public`）：注册表条目 **或** `ggcore.plot` 里的同名可调用对象；"
        "`registry` 列只数注册表，差额是那些不是组件的导出（全局主题状态、"
        "`theme_sub_*`、guide 协议钩子、`scale_type`）",
        "",
        "| 分类 | 上游 | registry | public | 覆盖率（public） | registry 口径 | 结论 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in result["rows"]:
        ok = "✅" if row["coverage"] >= threshold else "❌"
        lines.append(
            f"| `{row['kind']}` | {row['upstream']} | {row['registry']} | {row['public']} "
            f"| {_pct(row['coverage'])} | {_pct(row['registry_coverage'])} | {ok} |"
        )
    lines.append(
        f"| **合计** | **{result['upstream_total']}** | **{result['registry_total']}** "
        f"| **{result['public_total']}** | **{_pct(result['overall'])}** "
        f"| {_pct(result['registry_overall'])} | "
        f"{'✅' if result['overall'] >= threshold else '❌'} |"
    )
    lines.extend(["", "## 缺口清单", ""])
    if not result["gaps"]:
        lines.append("无缺口：上游每个导出都能在注册表或公开命名空间里找到。")
    else:
        lines.append("每一条都必须有 issue 归口，否则 `api:coverage:check` 直接红。")
        lines.extend(["", "| 导出 | 归口 | 原因 |", "| --- | --- | --- |"])
        for name in result["gaps"]:
            issue, reason = GAPS.get(name, ("", "**未登记归口**"))
            lines.append(f"| `{name}` | {issue} | {reason} |")
    lines.extend(["", "## 只在公开命名空间、不在注册表的导出", ""])
    surface_only = sorted({name for row in result["rows"] for name in row["surface_only"]})
    if not surface_only:
        lines.append("无。")
    else:
        lines.append(
            "这些是上游导出，但不是「能加到图上的组件」，所以放在 `ggcore.plot` 的"
            "命名空间里（与上游同名同义），而不是注册表："
        )
        lines.extend(["", "```text", *surface_only, "```"])
    lines.extend(
        [
            "",
            "## 口径边界",
            "",
            "- 覆盖率证明的是**入口存在**，不是行为对等：行为由 `tests/` 的 R 对拍夹具与 "
            "`docs/cases/` 的快照守着。新增注册名必须同时带测试（X5 的案例层要求）。",
            "- 换 pin 时：`pixi run api:coverage --refresh <ggplot2 源码目录>/NAMESPACE`，"
            "把 JSON 与本文一起提交。",
            "",
        ]
    )
    return "\n".join(lines)


def failures(result: dict[str, Any], *, doc_stale: bool) -> list[str]:
    threshold = result["threshold"]
    problems = [
        f"{row['kind']} 覆盖率 {_pct(row['coverage'])} < {threshold:.0%}"
        for row in result["rows"]
        if row["coverage"] < threshold
    ]
    if result["overall"] < threshold:
        problems.append(f"整体覆盖率 {_pct(result['overall'])} < {threshold:.0%}")
    for name in result["gaps"]:
        if name not in GAPS:
            problems.append(f"缺口 {name} 没有 issue 归口")
    if doc_stale:
        problems.append(f"{DOC.relative_to(ROOT)} 不是最新的（`pixi run api:coverage`）")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    parser.add_argument("--json", action="store_true", help="把结果打到 stdout（不写文件）")
    parser.add_argument(
        "--refresh",
        metavar="NAMESPACE",
        type=Path,
        help="从一份 ggplot2 NAMESPACE 重生成 tools/gates/upstream_api.json",
    )
    args = parser.parse_args(argv)

    if args.refresh is not None:
        surface = build_surface(args.refresh, pin=PIN)
        DATA.write_text(json.dumps(surface, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {DATA.relative_to(ROOT)}")
        return 0

    surface = load_surface()
    result = measure(surface)
    report = render_report(result)

    if args.json:
        print(json.dumps({**result, "problems": failures(result, doc_stale=False)}, indent=2))
        return 0

    doc_stale = not DOC.is_file() or DOC.read_text(encoding="utf-8") != report
    if not args.check:
        DOC.write_text(report, encoding="utf-8")
        doc_stale = False

    problems = failures(result, doc_stale=doc_stale)
    for row in result["rows"]:
        print(
            f"{row['kind']:9s} {row['public']:3d}/{row['upstream']:<3d} "
            f"public {_pct(row['coverage']):>6s}  registry {_pct(row['registry_coverage']):>6s}"
            + ("" if row["coverage"] >= result["threshold"] else "  <-- below threshold")
        )
    print(
        f"{'TOTAL':9s} {result['public_total']:3d}/{result['upstream_total']:<3d} "
        f"public {_pct(result['overall']):>6s}  registry {_pct(result['registry_overall']):>6s}"
    )
    if result["gaps"]:
        print(f"gaps ({len(result['gaps'])}): " + ", ".join(result["gaps"]))
    if problems:
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        return 1
    print("api coverage OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
