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
import pprint
import shutil
import subprocess
import sys
import tempfile
import textwrap
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
                "features": [
                    "aes-mapping",
                    "facet-wrap",
                    "legend-right",
                    f"theme-{name}",
                    "base-size-33",
                ],
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


# ---------------------------------------------------------------------------
# geom-dotplot（SIL-787）
# ---------------------------------------------------------------------------

#: `test-geom-dotplot.R` 的三份夹具：随机数取 `set.seed(111)` / `set.seed(112)`
#: 之后逐位抄下来的值（R 4.5.3），不重新抽。
_DOTPLOT_D1_X = [
    -0.31423169595047251,
    2.4033750787787032,
    -0.71826396266405201,
    -1.7606109629935416,
    -1.1252811743977724,
    -0.71954056575150671,
    1.310223977253826,
    0.45189845282321606,
    0.15217740702295823,
    0.65337078277679583,
    -0.94733553853243446,
    -1.071086252558543,
    -0.17605937002612163,
    1.8720502082968995,
    -0.51033837959979045,
    1.4388904417981778,
    1.1531709539424315,
    -0.15483976358124263,
    -0.2599055202700481,
    0.47136677086213369,
]

_DOTPLOT_DAT1_Y = [
    0.2352207116136979,
    -0.33073587162669138,
    -0.31162382397876148,
    -2.3023456584293767,
    -0.17087604461386502,
    0.14027822510323076,
    -1.4974266555651168,
    -1.010188419051379,
    -0.94847560495244698,
    -0.49396221723510808,
    -0.17367412797058035,
    -0.40659878004065225,
    1.8456362638070769,
    0.39405410997450147,
    0.7975285012615172,
    -1.5666653601855778,
    -0.085851008822606156,
    -0.35913948123778322,
    -1.1936089665637317,
    0.3641867370222206,
    0.36166245158827537,
    0.3469643701135664,
    0.18973652668927543,
    -0.15957680553877868,
    0.32654923843186656,
    0.5982542023934897,
    -1.8415343000624469,
    2.7180555995417524,
    0.19124439045729366,
    -1.3012960652783192,
]

_DOTPLOT_DAT2_Y = [
    0.24887993672252107,
    2.3002587881560244,
    0.34407357929885268,
    -1.4977663208912044,
    -0.58758433165675328,
    -0.58469279265297269,
    -1.1205990348021924,
    0.49205171983606183,
    1.2326162706873334,
    0.51884209877988796,
    1.6653289953379988,
    0.15217428819980339,
    1.3330088320699756,
    -0.11312635979024291,
    0.29079286186156633,
    -0.56103860173402187,
    0.96620329329702181,
    1.0207828051246959,
    1.2033974143403428,
    0.15250668702484685,
    0.91859055286948732,
    -0.029472936987090824,
    -0.277222037705809,
    0.038432098256917215,
    2.2870604490585174,
    0.20185010496763192,
    0.96792349861687998,
    -1.4306470899384824,
    1.3768411527543938,
    1.2529906517770286,
    0.073561027835354897,
    0.34287107097199809,
    -0.3253027856738302,
    0.25177040639006176,
    -1.3042283750768202,
    -0.3665697778995598,
    -0.91310616144283874,
    0.0017302910206192952,
    -0.90483180613342473,
    -0.60076354316502056,
    -0.40462358365121154,
    -0.55942185906755659,
    -0.80847594259646705,
    1.2927839383260777,
    0.7841626812249084,
    0.47720927110228795,
    -0.63108789207386851,
    -0.6649123756098646,
    0.19511465527684818,
    0.48073563793413515,
    0.9059704504506777,
    1.5672244142183465,
    1.2909991406466983,
    -2.0718711119335711,
    0.7996848469058162,
    -0.7419642349815968,
    -1.363265798747116,
    0.053080729537229421,
    1.1405448007541588,
    0.30858454632943755,
    0.13576902412912278,
    -0.64194299702134505,
    -0.19982378816207119,
    0.33887515900166387,
    -0.97398280434253104,
    1.0951809442480671,
    -0.077863136718800449,
    2.5029410662844982,
    0.8879866230663479,
    1.2036485337845353,
    0.64555647411025319,
    -0.25234371565020092,
    -0.96069143361769982,
    0.16674026253659979,
    -0.07538117981102184,
    0.69172324326952639,
    -0.90270234513384051,
    -0.59476760948903695,
    -1.0515527530041857,
    -0.065724062725264293,
    1.111791472905175,
    0.077596463762945295,
    0.80506399888452185,
    -0.71034094097585454,
    0.46817656820136311,
    0.27655628660026388,
    -0.26463335737326671,
    -0.59256402592468982,
    0.85964675688526526,
    -0.34167750873657976,
]


def _literal(values: list[Any]) -> str:
    return "[" + ", ".join(repr(value) for value in values) + "]"


def _dotplot_data() -> dict[str, str]:
    dat1 = {
        "x": ["A", "B"] * 15,
        "y": _DOTPLOT_DAT1_Y,
        "g": ["C", "D", "E"] * 10,
    }
    dat2 = {
        "x": ["A", "B", "C"] * 30,
        "y": _DOTPLOT_DAT2_Y,
        "g": ["A", "B"] * 45,
        "xn": [1.0, 2.0, 3.0] * 30,
        "foo": ["foo"] * 90,
    }
    na_x = [None if index in (0, 9) else value for index, value in enumerate(_DOTPLOT_D1_X)]
    tables = {
        "D1": {"x": _DOTPLOT_D1_X},
        # 视觉测试块里的 `dat`：x 连续 + 两水平 g（A / B）。
        "DV": {"x": _DOTPLOT_D1_X, "g": ["A", "B"] * 10},
        # `linetype` / `stroke` 逐行映射；stroke 已经按 R 的
        # `continuous_scale("stroke", palette = rescale(x, to = c(1, 6)))` 预映射。
        "LT": {
            "x": _DOTPLOT_D1_X,
            "lt": ["a", "b"] * 10,
            "st": [1.0, 6.0] * 10,
        },
        "D1NA": {"x": na_x},
        "DAT1": dat1,
        "DAT2": dat2,
        "SR": {"x": [1.0, 1.0, 1.0, 2.0, 2.0]},
    }
    return {
        name: pprint.pformat(table, width=88, sort_dicts=False) for name, table in tables.items()
    }


def _dotplot_body(mapping: str, layers: list[str], title: str) -> str:
    lines = [
        "def build():",
        "    p = (",
        f"        ggplot(to_column_table(DATA), {mapping})",
        *[f"        + {layer}" for layer in layers],
        "        + theme_test()",
        f'        + labs(title="{title}")',
        "    )",
        '    return {"plot": p, "size": [10, 8]}',
    ]
    return "\n".join(lines)


def _dotplot_specs() -> list[dict[str, Any]]:
    data = _dotplot_data()
    specs: list[dict[str, Any]] = []

    def add(
        slug: str,
        snapshot: str,
        title: str,
        table: str,
        mapping: str,
        layers: list[str],
        features: list[str],
        notes: str | None = None,
    ) -> None:
        spec: dict[str, Any] = {
            "slug": slug,
            "snapshot": f"geom-dotplot/{snapshot}.svg",
            "title": title,
            "data": data[table],
            "body": _dotplot_body(mapping, layers, title),
            "family": "geom-dotplot",
            "features": features,
        }
        if notes is not None:
            spec["notes"] = notes
        specs.append(spec)

    add(
        "upstream-geom-dotplot-basic-dotdensity",
        "basic-dotplot-with-dot-density-binning-binwidth-4",
        "basic dotplot with dot-density binning, binwidth = .4",
        "D1",
        'aes(x="x")',
        ["geom_dotplot(binwidth=0.4)"],
        ["aes-mapping", "stat-bindot", "method-dotdensity"],
    )
    add(
        "upstream-geom-dotplot-histodot",
        "histodot-binning-equal-bin-spacing",
        "histodot binning (equal bin spacing)",
        "D1",
        'aes(x="x")',
        ['geom_dotplot(binwidth=0.4, method="histodot")'],
        ["aes-mapping", "stat-bindot", "method-histodot"],
    )
    add(
        "upstream-geom-dotplot-stackratio-half",
        "dots-stacked-closer-stackratio-5-fill-white",
        "dots stacked closer: stackratio=.5, fill=white",
        "D1",
        'aes(x="x")',
        ['geom_dotplot(binwidth=0.4, stackratio=0.5, fill="white")'],
        ["aes-mapping", "stat-bindot", "stackratio"],
    )
    add(
        "upstream-geom-dotplot-dotsize-large",
        "larger-dots-dotsize-1-5-fill-white",
        "larger dots: dotsize=1.5, fill=white",
        "D1",
        'aes(x="x")',
        ['geom_dotplot(binwidth=0.4, dotsize=1.4, fill="white")'],
        ["aes-mapping", "stat-bindot", "dotsize"],
    )
    for stackdir in ("up", "down", "center", "centerwhole"):
        add(
            f"upstream-geom-dotplot-stack-{stackdir}",
            f"stack-{stackdir}",
            f"stack {stackdir}",
            "D1",
            'aes(x="x")',
            [f'geom_dotplot(binwidth=0.4, stackdir="{stackdir}")'],
            ["aes-mapping", "stat-bindot", f"stackdir-{stackdir}"],
        )
        add(
            f"upstream-geom-dotplot-stack-{stackdir}-coord-flip",
            f"stack-{stackdir}-with-coord-flip",
            f"stack {stackdir} with coord_flip",
            "D1",
            'aes(x="x")',
            [f'geom_dotplot(binwidth=0.4, stackdir="{stackdir}")', "coord_flip()"],
            ["aes-mapping", "stat-bindot", f"stackdir-{stackdir}", "coord-flip"],
        )
    add(
        "upstream-geom-dotplot-multiple-groups-bins-not-aligned",
        "multiple-groups-bins-not-aligned",
        "multiple groups, bins not aligned",
        "DV",
        'aes(x="x", fill="g")',
        ["geom_dotplot(binwidth=0.4, alpha=0.4)"],
        ["aes-mapping", "stat-bindot", "binpositions-bygroup"],
    )
    add(
        "upstream-geom-dotplot-multiple-groups-bins-aligned",
        "multiple-groups-bins-aligned",
        "multiple groups, bins aligned",
        "DV",
        'aes(x="x", fill="g")',
        ['geom_dotplot(binwidth=0.4, alpha=0.4, binpositions="all")'],
        ["aes-mapping", "stat-bindot", "binpositions-all"],
    )
    add(
        "upstream-geom-dotplot-bin-along-y-stack-center",
        "bin-along-y-stack-center",
        "bin along y, stack center",
        "D1",
        'aes(x=0, y="x")',
        ['geom_dotplot(binwidth=0.4, binaxis="y", stackdir="center")'],
        ["aes-mapping", "stat-bindot", "binaxis-y", "stackdir-center"],
    )
    add(
        "upstream-geom-dotplot-bin-along-y-stack-centerwhole",
        "bin-along-y-stack-centerwhole",
        "bin along y, stack centerwhole",
        "D1",
        'aes(x=0, y="x")',
        ['geom_dotplot(binwidth=0.4, binaxis="y", stackdir="centerwhole")'],
        ["aes-mapping", "stat-bindot", "binaxis-y", "stackdir-centerwhole"],
    )
    add(
        "upstream-geom-dotplot-bin-along-y-stack-centerwhole-histodot",
        "bin-along-y-stack-centerwhole-histodot",
        "bin along y, stack centerwhole, histodot",
        "D1",
        'aes(x=0, y="x")',
        ['geom_dotplot(binwidth=0.4, binaxis="y", stackdir="centerwhole", method="histodot")'],
        ["aes-mapping", "stat-bindot", "binaxis-y", "method-histodot"],
    )
    add(
        "upstream-geom-dotplot-bin-x-three-y-groups-stack-centerwhole",
        "bin-x-three-y-groups-stack-centerwhole",
        "bin x, three y groups, stack centerwhole",
        "DAT2",
        'aes(x="y", y="x")',
        ['geom_dotplot(binwidth=0.25, binaxis="x", stackdir="centerwhole")'],
        ["aes-mapping", "stat-bindot", "binaxis-x", "stackdir-centerwhole"],
    )
    add(
        "upstream-geom-dotplot-bin-y-three-x-groups-stack-centerwhole",
        "bin-y-three-x-groups-stack-centerwhole",
        "bin y, three x groups, stack centerwhole",
        "DAT2",
        'aes(x="x", y="y")',
        ['geom_dotplot(binwidth=0.25, binaxis="y", stackdir="centerwhole")'],
        ["aes-mapping", "stat-bindot", "binaxis-y", "stackdir-centerwhole"],
    )
    add(
        "upstream-geom-dotplot-bin-y-three-x-groups-bins-aligned-across-groups",
        "bin-y-three-x-groups-bins-aligned-across-groups",
        "bin y, three x groups, bins aligned across groups",
        "DAT2",
        'aes(x="x", y="y")',
        ['geom_dotplot(binwidth=0.25, binaxis="y", stackdir="center", binpositions="all")'],
        ["aes-mapping", "stat-bindot", "binaxis-y", "binpositions-all"],
    )
    add(
        "upstream-geom-dotplot-bin-y-three-x-groups-bins-aligned-coord-flip",
        "bin-y-three-x-groups-bins-aligned-coord-flip",
        "bin y, three x groups, bins aligned, coord_flip",
        "DAT2",
        'aes(x="x", y="y")',
        [
            'geom_dotplot(binwidth=0.25, binaxis="y", stackdir="center", binpositions="all")',
            "coord_flip()",
        ],
        ["aes-mapping", "stat-bindot", "binaxis-y", "binpositions-all", "coord-flip"],
    )
    add(
        "upstream-geom-dotplot-bin-y-dodged",
        "bin-y-dodged",
        "bin y, dodged",
        "DAT2",
        'aes(x="foo", y="y", fill="x")',
        [
            "scale_y_continuous(breaks=[-4.0, -3.6, -3.2, -2.8, -2.4, -2.0, -1.6, "
            "-1.2, -0.8, -0.4, 0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8, 3.2, "
            "3.6, 4.0])",
            'geom_dotplot(binwidth=0.25, position="dodge", binaxis="y", stackdir="center")',
        ],
        ["aes-mapping", "stat-bindot", "binaxis-y", "position-dodge"],
    )
    add(
        "upstream-geom-dotplot-bin-y-dodged-coord-flip",
        "bin-y-dodged-coord-flip",
        "bin y, dodged, coord_flip",
        "DAT2",
        'aes(x="foo", y="y", fill="x")',
        [
            "scale_y_continuous(breaks=[-4.0, -3.6, -3.2, -2.8, -2.4, -2.0, -1.6, "
            "-1.2, -0.8, -0.4, 0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8, 3.2, "
            "3.6, 4.0])",
            'geom_dotplot(binwidth=0.25, position="dodge", binaxis="y", stackdir="center")',
            "coord_flip()",
        ],
        ["aes-mapping", "stat-bindot", "binaxis-y", "position-dodge", "coord-flip"],
    )
    add(
        "upstream-geom-dotplot-bin-y-three-x-groups-fill-and-dodge",
        "bin-y-three-x-groups-fill-and-dodge",
        "bin y, three x groups, fill and dodge",
        "DAT2",
        'aes(x="x", y="y", fill="g")',
        [
            "scale_y_continuous(breaks=[-4.0, -3.6, -3.2, -2.8, -2.4, -2.0, -1.6, "
            "-1.2, -0.8, -0.4, 0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.4, 2.8, 3.2, "
            "3.6, 4.0])",
            'geom_dotplot(binwidth=0.2, position="dodge", binaxis="y", stackdir="center")',
        ],
        ["aes-mapping", "stat-bindot", "binaxis-y", "position-dodge"],
    )
    add(
        "upstream-geom-dotplot-bin-y-continuous-x-grouping-by-x",
        "bin-y-continous-x-axis-grouping-by-x",
        "bin y, continous x-axis, grouping by x",
        "DAT2",
        'aes(x="xn", y="y", group="x")',
        ['geom_dotplot(binwidth=0.2, binaxis="y", stackdir="center")'],
        ["aes-mapping", "stat-bindot", "binaxis-y", "grouping"],
    )
    add(
        "upstream-geom-dotplot-bin-y-continuous-x-single-group",
        "bin-y-continous-x-axis-single-x-group",
        "bin y, continous x-axis, single x group",
        "DAT2",
        'aes(x="xn", y="y")',
        ['geom_dotplot(binwidth=0.2, binaxis="y", stackdir="center")'],
        ["aes-mapping", "stat-bindot", "binaxis-y"],
    )
    add(
        "upstream-geom-dotplot-variable-linetype-size",
        "variable-linetype-and-size-specified-as-aesthetics",
        "variable linetype and size specified as aesthetics",
        "LT",
        'aes(x="x", linetype="lt", stroke="st")',
        [
            'geom_dotplot(binwidth=0.4, fill="red", colour="blue")',
            "labs(\n"
            '            linetype=\'rep(c("a", "b"), length.out = nrow(dat))\',\n'
            "            stroke='rep(c(1, 2), length.out = nrow(dat))',\n"
            "        )",
        ],
        ["aes-mapping", "stat-bindot", "linetype-aes", "stroke-aes"],
        notes=(
            "SIL-787：vdiffr 快照原样纳入；标题是 doppelganger 名，主题是 vdiffr 的 "
            "theme_test()。残余偏差（SIL-715 #28）：linetype=b（lty 2）那 10 个点在 "
            "skia SVG 设备上丢了描边——actual 只有 fill 的 ellipse，expected 是 "
            "stroke-width 4.50 + stroke-dasharray 12,12 的蓝圈；图例侧 expected 7 key / "
            "actual 2。IR 的 dash pattern 是对的（gpar.lty=(9,9)），卡在 SVGCanvas 不序列化 "
            "PathEffect。实测 1.76% / 0.53%，仍在档内。"
        ),
    )
    add(
        "upstream-geom-dotplot-3-stackgroups-dotdensity-aligned",
        "3-stackgroups-dot-density-with-aligned-bins",
        "3 stackgroups, dot-density with aligned bins",
        "DAT2",
        'aes(x="y", fill="x")',
        ['geom_dotplot(binwidth=0.25, stackgroups=True, binpositions="all", alpha=0.5)'],
        ["aes-mapping", "stat-bindot", "stackgroups", "binpositions-all"],
    )
    add(
        "upstream-geom-dotplot-3-stackgroups-histodot",
        "3-stackgroups-histodot",
        "3 stackgroups, histodot",
        "DAT2",
        'aes(x="y", fill="x")',
        ['geom_dotplot(binwidth=0.25, stackgroups=True, method="histodot", alpha=0.5)'],
        ["aes-mapping", "stat-bindot", "stackgroups", "method-histodot"],
    )
    add(
        "upstream-geom-dotplot-3-stackgroups-bin-y-histodot",
        "3-stackgroups-bin-y-histodot",
        "3 stackgroups, bin y, histodot",
        "DAT2",
        'aes(x=1, y="y", fill="x")',
        [
            'geom_dotplot(binaxis="y", binwidth=0.25, stackgroups=True, '
            'method="histodot", alpha=0.5)'
        ],
        ["aes-mapping", "stat-bindot", "stackgroups", "binaxis-y"],
    )
    add(
        "upstream-geom-dotplot-bin-y-dodging-3-stackgroups-histodot",
        "bin-y-dodging-3-stackgroups-histodot",
        "bin y, dodging, 3 stackgroups, histodot",
        "DAT2",
        'aes(x="x", y="y", fill="g")',
        [
            'geom_dotplot(binaxis="y", binwidth=0.25, stackgroups=True, '
            'method="histodot", alpha=0.5, stackdir="centerwhole")'
        ],
        ["aes-mapping", "stat-bindot", "stackgroups", "binaxis-y"],
    )
    add(
        "upstream-geom-dotplot-facets-3-groups-histodot-stackgroups",
        "facets-3-groups-histodot-stackgroups",
        "facets, 3 groups, histodot, stackgroups",
        "DAT2",
        'aes(x="y", fill="g")',
        [
            'geom_dotplot(binwidth=0.25, stackgroups=True, method="histodot", alpha=0.5)',
            'facet_grid(rows="x")',
        ],
        ["aes-mapping", "stat-bindot", "stackgroups", "method-histodot", "facet-grid"],
    )
    add(
        "upstream-geom-dotplot-2-na-dotdensity",
        "2-na-values-dot-density-binning-binwidth-4",
        "2 NA values, dot-density binning, binwidth = .4",
        "D1NA",
        'aes(x="x")',
        ["geom_dotplot(binwidth=0.4)"],
        ["aes-mapping", "stat-bindot", "na-removal"],
    )
    add(
        "upstream-geom-dotplot-2-na-bin-along-y",
        "2-na-values-bin-along-y-stack-center",
        "2 NA values, bin along y, stack center",
        "D1NA",
        'aes(x=0, y="x")',
        ['geom_dotplot(binwidth=0.4, binaxis="y", stackdir="center")'],
        ["aes-mapping", "stat-bindot", "binaxis-y", "na-removal"],
    )
    add(
        "upstream-geom-dotplot-stackratio-1-5",
        "stackratio-1-5",
        "stackratio = 1.5",
        "SR",
        'aes(x="x")',
        [
            "geom_hline(yintercept=0.0)",
            'geom_dotplot(aes(x="x"), binwidth=0.5, stackdir="down", stackratio=1.5, fill=None)',
            'geom_dotplot(aes(x="x + 3"), binwidth=0.5, stackdir="up", stackratio=1.5, fill=None)',
            'geom_dotplot(aes(x="x + 6"), binwidth=0.5, stackdir="center", '
            "stackratio=1.5, fill=None)",
            'geom_dotplot(aes(x="x + 9"), binwidth=0.5, stackdir="centerwhole", '
            "stackratio=1.5, fill=None)",
        ],
        ["aes-mapping", "stat-bindot", "stackratio", "multi-layer"],
    )
    return specs


#: SIL-792（G3 theme）：SIL-745 的 `theme` 簇里除 8 套主题 / 3 个 `base_size = 33`
#: 变体以外的 15 条。每条都是「同一条 R 测试里的某个 `expect_doppelganger()`」，
#: 组合各不相同，所以同样直接给完整的 plot.py 正文（`source`）。
_THEME_MISC_SPECS: list[dict[str, Any]] = [
    {
        "slug": "upstream-theme-strip-styling",
        "snapshot": "theme/strip-styling.svg",
        "title": "strip_styling",
        "family": "theme",
        "features": ["facet-grid", "strip-styling"],
        "notes": "SIL-792：strip.background.x / .y 独立着色；无图层（geom_blank）。",
        "source": '''
"""upstream/theme：strip.background.x/.y 独立着色。"""

from ggcore.plot import aes, facet_grid, geom_blank, ggplot, labs
from ggcore.theme import element_rect, theme
from ggio.frame import to_column_table

DATA = {"x": [1, 2], "y": [1, 2]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + facet_grid(rows="x", cols="y")
        + theme(
            **{
                "strip.background.x": element_rect(fill="red"),
                "strip.background.y": element_rect(fill="green"),
            }
        )
        + labs(title="strip_styling")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-rotated-x-axis-tick-labels",
        "snapshot": "theme/rotated-x-axis-tick-labels.svg",
        "title": "rotated x axis tick labels",
        "family": "theme",
        "features": ["axis-text-rotation"],
        "notes": "SIL-792：`axis.text.x` 旋转 50°、hjust = 1。",
        "source": '''
"""upstream/theme：`axis.text.x` 旋转 50°、hjust=1。"""

from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import element_text, theme
from ggio.frame import to_column_table

DATA = {"label": ["short", "medium size", "very long label"], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="label", y="y"))
        + geom_point()
        + theme(**{"axis.text.x": element_text(angle=50, hjust=1)})
        + labs(title="rotated x axis tick labels")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-titles-aligned-to-entire-plot",
        "snapshot": "theme/titles-aligned-to-entire-plot.svg",
        "title": "titles aligned to entire plot",
        "family": "theme",
        "features": ["plot-title-position"],
        "notes": "SIL-792：plot.title.position = 'plot'。",
        "source": '''
"""upstream/theme：`plot.title.position = "plot"`。"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["a", "b", "c"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", color="z"))
        + geom_point()
        + facet_wrap("z")
        + labs(
            title="Plot title aligned to entire plot",
            subtitle="Subtitle aligned to entire plot",
            caption="Caption aligned to panels",
        )
        + theme(**{"plot.title.position": "plot"})
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-caption-aligned-to-entire-plot",
        "snapshot": "theme/caption-aligned-to-entire-plot.svg",
        "title": "caption aligned to entire plot",
        "family": "theme",
        "features": ["plot-caption-position"],
        "notes": "SIL-792：plot.caption.position = 'plot'。",
        "source": '''
"""upstream/theme：`plot.caption.position = "plot"`。"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggcore.theme import theme
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["a", "b", "c"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", color="z"))
        + geom_point()
        + facet_wrap("z")
        + labs(
            title="Plot title aligned to panels",
            subtitle="Subtitle aligned to panels",
            caption="Caption aligned to entire plot",
        )
        + theme(**{"plot.caption.position": "plot"})
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-large-spacing",
        "snapshot": "theme/large-spacing.svg",
        "title": "large spacing",
        "family": "theme",
        "features": ["theme-spacing"],
        "notes": "SIL-792：theme(spacing = unit(1, 'cm'))。",
        "source": '''
"""upstream/theme：`theme(spacing = unit(1, "cm"))`。"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggcore.theme import theme, theme_gray
from ggcore.viewport import unit
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["a", "b", "a"], "a": [1, 1, 1]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + facet_wrap("a")
        + theme_gray()
        + theme(**{"spacing": unit(1.0, "cm")})
        + labs(title="large spacing")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-large-margins",
        "snapshot": "theme/large-margins.svg",
        "title": "large margins",
        "family": "theme",
        "features": ["theme-margins"],
        "notes": "SIL-792：theme(margins = margin(1, 1, 1, 1, 'cm'))。",
        "source": '''
"""upstream/theme：`theme(margins = margin(1, 1, 1, 1, "cm"))`。"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggcore.theme import margin, theme, theme_gray
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["a", "b", "a"], "a": [1, 1, 1]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + facet_wrap("a")
        + theme_gray()
        + theme(**{"margins": margin(1, 1, 1, 1, "cm")})
        + labs(title="large margins")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-ticks-length",
        "snapshot": "theme/ticks-length.svg",
        "title": "ticks_length",
        "family": "theme",
        "features": ["sec-axis", "axis-ticks-length"],
        "notes": "SIL-792：四边刻度长度独立（含负值）。",
        "source": '''
"""upstream/theme：四个方向的刻度长度独立。"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_text, margin, theme, theme_test
from ggcore.viewport import unit
from ggio.frame import to_column_table

DATA = {"x": list(range(1, 11)), "y": list(range(1, 11))}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + theme_test()
        + geom_point()
        + scale_x_continuous(sec_axis=dup_axis())
        + scale_y_continuous(sec_axis=dup_axis())
        + theme(
            **{
                "axis.ticks.length.x.top": unit(-0.5, "cm"),
                "axis.ticks.length.x.bottom": unit(-0.25, "cm"),
                "axis.ticks.length.y.left": unit(0.25, "cm"),
                "axis.ticks.length.y.right": unit(0.5, "cm"),
                "axis.text.x.bottom": element_text(margin=margin(t=0.25, unit="cm")),
                "axis.text.x.top": element_text(margin=margin(b=0.25, unit="cm")),
            }
        )
        + labs(title="ticks_length")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-axes-styling",
        "snapshot": "theme/axes-styling.svg",
        "title": "axes_styling",
        "family": "theme",
        "features": ["sec-axis", "axis-elements"],
        "notes": "SIL-792：四边轴标题 / 文本 / 刻度 / 轴线独立着色。",
        "source": '''
"""upstream/theme：四边轴标题 / 文本 / 刻度 / 轴线独立着色。"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, element_text, theme
from ggio.frame import to_column_table

DATA = {"x": list(range(1, 11)), "y": list(range(1, 11))}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(sec_axis=dup_axis())
        + scale_y_continuous(sec_axis=dup_axis())
        + theme(
            **{
                "axis.title.x.top": element_text(colour="red"),
                "axis.title.x.bottom": element_text(colour="green"),
                "axis.title.y.left": element_text(colour="blue"),
                "axis.title.y.right": element_text(colour="yellow"),
                "axis.text.x.top": element_text(colour="red"),
                "axis.text.x.bottom": element_text(colour="green"),
                "axis.text.y.left": element_text(colour="blue"),
                "axis.text.y.right": element_text(colour="yellow"),
                "axis.ticks.x.top": element_line(colour="red"),
                "axis.ticks.x.bottom": element_line(colour="green"),
                "axis.ticks.y.left": element_line(colour="blue"),
                "axis.ticks.y.right": element_line(colour="yellow"),
                "axis.line.x.top": element_line(colour="red"),
                "axis.line.x.bottom": element_line(colour="green"),
                "axis.line.y.left": element_line(colour="blue"),
                "axis.line.y.right": element_line(colour="yellow"),
            }
        )
        + labs(title="axes_styling")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-height-is-3-times-width",
        "snapshot": "theme/height-is-3-times-width.svg",
        "title": "height is 3 times width",
        "family": "theme",
        "features": ["aspect-ratio"],
        "notes": "SIL-792：theme(aspect.ratio = 3)。",
        "source": '''
"""upstream/theme：`theme(aspect.ratio = ...)`。"""

from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8],
    "y": [1, 2, 3, 4, 5, 6, 7, 8],
    "f": ["a", "a", "a", "a", "b", "b", "b", "b"],
    "f1": [1, 1, 1, 1, 2, 2, 2, 2],
    "f2": [1, 2, 1, 2, 1, 2, 1, 2],
    "rep": [1, 1, 2, 2, 1, 1, 2, 2],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + theme_test()
        + labs(x=None, y=None)
    )
    p = p + theme(**{"aspect.ratio": 3}) + labs(title="height is 3 times width")
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-width-is-3-times-height",
        "snapshot": "theme/width-is-3-times-height.svg",
        "title": "width is 3 times height",
        "family": "theme",
        "features": ["aspect-ratio"],
        "notes": "SIL-792：theme(aspect.ratio = 1 / 3)。",
        "source": '''
"""upstream/theme：`theme(aspect.ratio = ...)`。"""

from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8],
    "y": [1, 2, 3, 4, 5, 6, 7, 8],
    "f": ["a", "a", "a", "a", "b", "b", "b", "b"],
    "f1": [1, 1, 1, 1, 2, 2, 2, 2],
    "f2": [1, 2, 1, 2, 1, 2, 1, 2],
    "rep": [1, 1, 2, 2, 1, 1, 2, 2],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + theme_test()
        + labs(x=None, y=None)
    )
    p = p + theme(**{"aspect.ratio": 1 / 3}) + labs(title="width is 3 times height")
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-height-is-3-times-width-2-wrap-facets",
        "snapshot": "theme/height-is-3-times-width-2-wrap-facets.svg",
        "title": "height is 3 times width, 2 wrap facets",
        "family": "theme",
        "features": ["aspect-ratio", "facet-wrap"],
        "notes": "SIL-792：aspect.ratio + facet_wrap()。",
        "source": '''
"""upstream/theme：`theme(aspect.ratio = ...)`。"""

from ggcore.plot import aes, facet_wrap, geom_point, ggplot, labs
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8],
    "y": [1, 2, 3, 4, 5, 6, 7, 8],
    "f": ["a", "a", "a", "a", "b", "b", "b", "b"],
    "f1": [1, 1, 1, 1, 2, 2, 2, 2],
    "f2": [1, 2, 1, 2, 1, 2, 1, 2],
    "rep": [1, 1, 2, 2, 1, 1, 2, 2],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + theme_test()
        + labs(x=None, y=None)
    )
    p = (
        p
        + theme(**{"aspect.ratio": 3})
        + facet_wrap("f")
        + labs(title="height is 3 times width, 2 wrap facets")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-height-is-3-times-width-2-column-facets",
        "snapshot": "theme/height-is-3-times-width-2-column-facets.svg",
        "title": "height is 3 times width, 2 column facets",
        "family": "theme",
        "features": ["aspect-ratio", "facet-grid"],
        "notes": "SIL-792：aspect.ratio + facet_grid(. ~ f)。",
        "source": '''
"""upstream/theme：`theme(aspect.ratio = ...)`。"""

from ggcore.plot import aes, facet_grid, geom_point, ggplot, labs
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8],
    "y": [1, 2, 3, 4, 5, 6, 7, 8],
    "f": ["a", "a", "a", "a", "b", "b", "b", "b"],
    "f1": [1, 1, 1, 1, 2, 2, 2, 2],
    "f2": [1, 2, 1, 2, 1, 2, 1, 2],
    "rep": [1, 1, 2, 2, 1, 1, 2, 2],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + theme_test()
        + labs(x=None, y=None)
    )
    p = (
        p
        + theme(**{"aspect.ratio": 3})
        + facet_grid(cols="f")
        + labs(title="height is 3 times width, 2 column facets")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-height-is-3-times-width-2-row-facets",
        "snapshot": "theme/height-is-3-times-width-2-row-facets.svg",
        "title": "height is 3 times width, 2 row facets",
        "family": "theme",
        "features": ["aspect-ratio", "facet-grid"],
        "notes": "SIL-792：aspect.ratio + facet_grid(f ~ .)。",
        "source": '''
"""upstream/theme：`theme(aspect.ratio = ...)`。"""

from ggcore.plot import aes, facet_grid, geom_point, ggplot, labs
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8],
    "y": [1, 2, 3, 4, 5, 6, 7, 8],
    "f": ["a", "a", "a", "a", "b", "b", "b", "b"],
    "f1": [1, 1, 1, 1, 2, 2, 2, 2],
    "f2": [1, 2, 1, 2, 1, 2, 1, 2],
    "rep": [1, 1, 2, 2, 1, 1, 2, 2],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + theme_test()
        + labs(x=None, y=None)
    )
    p = (
        p
        + theme(**{"aspect.ratio": 3})
        + facet_grid(rows="f")
        + labs(title="height is 3 times width, 2 row facets")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-height-is-3-times-width-2x2-facets",
        "snapshot": "theme/height-is-3-times-width-2x2-facets.svg",
        "title": "height is 3 times width, 2x2 facets",
        "family": "theme",
        "features": ["aspect-ratio", "facet-grid"],
        "notes": "SIL-792：aspect.ratio + facet_grid(f1 ~ f2)。",
        "source": '''
"""upstream/theme：`theme(aspect.ratio = ...)`。"""

from ggcore.plot import aes, facet_grid, geom_point, ggplot, labs
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x": [1, 2, 3, 4, 5, 6, 7, 8],
    "y": [1, 2, 3, 4, 5, 6, 7, 8],
    "f": ["a", "a", "a", "a", "b", "b", "b", "b"],
    "f1": [1, 1, 1, 1, 2, 2, 2, 2],
    "f2": [1, 2, 1, 2, 1, 2, 1, 2],
    "rep": [1, 1, 2, 2, 1, 1, 2, 2],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + theme_test()
        + labs(x=None, y=None)
    )
    p = (
        p
        + theme(**{"aspect.ratio": 3})
        + facet_grid(rows="f1", cols="f2")
        + labs(title="height is 3 times width, 2x2 facets")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-theme-horizontal-legends-placed-apart",
        "snapshot": "theme/horizontal-legends-placed-apart.svg",
        "title": "horizontal legends placed apart",
        "family": "theme",
        "features": ["legend-spacing", "legend-top"],
        "notes": "SIL-792：legend.spacing.x = unit(1, 'null')。",
        "source": '''
"""upstream/theme：`legend.spacing.x = unit(1, "null")`。"""

from ggcore.plot import aes, geom_point, ggplot, labs
from ggcore.theme import element_rect, theme
from ggcore.viewport import unit
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "a": ["a", "b", "c"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="a", shape="x"))
        + geom_point()
        + theme(
            **{
                "legend.box.background": element_rect(colour="blue", fill=None),
                "legend.background": element_rect(colour="red", fill=None),
            }
        )
        + theme(
            **{
                "legend.position": "top",
                "legend.spacing.x": unit(1.0, "null"),
            }
        )
        + labs(title="horizontal legends placed apart")
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
]


#: G1b（SIL-791）：`guide-axis` 簇里已经复刻成三文件 case 的 10 条。
#:
#: 与 `_G1A_SPECS` 同一套写法：整份 `plot.py` 正文 + 特性标签。剩下的 13 条留在
#: `tools/upstream/snapshots.toml` 的同名快照条目里（卡点写在 `reason` 上）。
_G1B_SPECS: list[dict[str, Any]] = [
    {
        "slug": "upstream-guide-axis-axis-guides-basic",
        "snapshot": "guide-axis/axis-guides-basic.svg",
        "title": "axis guides basic",
        "features": ["guide-axis"],
        "notes": "SIL-791：vdiffr 快照原样纳入；标题是 doppelganger 名。",
        "source": r'''"""上游快照复刻：grid 直画的一条轴。

vdiffr 名：`axis guides basic`。
源：`guide-axis/axis-guides-basic.svg`
（vdiffr 名 `axis guides basic`）。

上游 `test_draw_axis()` 不是 ggplot：它用 `draw_axis()` 在 0.05 / 0.9 / 0.05 npc
的三格 gtable 里直画四条轴。这里用一张空面板 + 四条轴（主轴 + `dup_axis()`）复现
同一版式：面板落在页面的 5%..95%，刻度与标签都画在面板内侧
（`axis.ticks.length` 取负值，R 的 guide 就是这么把轴线、刻度、文字排进同一个
单元格的）。
"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_blank,
    ggplot,
    guide_axis,
    guides,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, margin, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0.0, 1.0], "y": [0.0, 1.0]}
BREAKS = (
    0.25,
    0.5,
    0.75,
)
LABELS = (
    "1",
    "2",
    "3",
)

#: 面板落在 5%..95%（上游 gtable 的 0.05 / 0.9 / 0.05 npc）；轴带（刻度 + 文字）
#: 占掉的部分从 36pt 里扣，值由渲染后量面板得到。
MARGIN = margin(21.476, 31.654, 21.476, 31.654)


def build():
    axis = dict()
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + scale_x_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + scale_y_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + labs(x=None, y=None)
        + guides(
            x=guide_axis(**axis),
            y=guide_axis(**axis),
            **{"x.sec": guide_axis(**axis), "y.sec": guide_axis(**axis)},
        )
        + theme_test()
        + theme(
            **{
                "axis.line": element_line(linewidth=0.5),
                "axis.ticks.length": unit(-2.75, "pt"),
                "plot.margin": MARGIN,
            }
        )
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-guide-axis-axis-guides-negative-rotation",
        "snapshot": "guide-axis/axis-guides-negative-rotation.svg",
        "title": "axis guides, negative rotation",
        "features": ["guide-axis", "rotation"],
        "notes": "SIL-791：vdiffr 快照原样纳入；标题是 doppelganger 名。",
        "source": r'''"""上游快照复刻：grid 直画的一条轴。

vdiffr 名：`axis guides, negative rotation`。
源：`guide-axis/axis-guides-negative-rotation.svg`
（vdiffr 名 `axis guides, negative rotation`）。

上游 `test_draw_axis()` 不是 ggplot：它用 `draw_axis()` 在 0.05 / 0.9 / 0.05 npc
的三格 gtable 里直画四条轴。这里用一张空面板 + 四条轴（主轴 + `dup_axis()`）复现
同一版式：面板落在页面的 5%..95%，刻度与标签都画在面板内侧
（`axis.ticks.length` 取负值，R 的 guide 就是这么把轴线、刻度、文字排进同一个
单元格的）。
"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_blank,
    ggplot,
    guide_axis,
    guides,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, margin, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0.0, 1.0], "y": [0.0, 1.0]}
BREAKS = (
    0.0909090909,
    0.1818181818,
    0.2727272727,
    0.3636363636,
    0.4545454545,
    0.5454545455,
    0.6363636364,
    0.7272727273,
    0.8181818182,
    0.9090909091,
)
LABELS = (
    "1,000",
    "2,000",
    "3,000",
    "4,000",
    "5,000",
    "6,000",
    "7,000",
    "8,000",
    "9,000",
    "10,000",
)

#: 面板落在 5%..95%（上游 gtable 的 0.05 / 0.9 / 0.05 npc）；轴带（刻度 + 文字）
#: 占掉的部分从 36pt 里扣，值由渲染后量面板得到。
MARGIN = margin(4.75, 11.95, 4.75, 11.95)


def build():
    axis = dict(angle=-45)
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + scale_x_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + scale_y_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + labs(x=None, y=None)
        + guides(
            x=guide_axis(**axis),
            y=guide_axis(**axis),
            **{"x.sec": guide_axis(**axis), "y.sec": guide_axis(**axis)},
        )
        + theme_test()
        + theme(
            **{
                "axis.line": element_line(linewidth=0.5),
                "axis.ticks.length": unit(-2.75, "pt"),
                "plot.margin": MARGIN,
            }
        )
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-guide-axis-axis-guides-positive-rotation",
        "snapshot": "guide-axis/axis-guides-positive-rotation.svg",
        "title": "axis guides, positive rotation",
        "features": ["guide-axis", "rotation"],
        "notes": "SIL-791：vdiffr 快照原样纳入；标题是 doppelganger 名。",
        "source": r'''"""上游快照复刻：grid 直画的一条轴。

vdiffr 名：`axis guides, positive rotation`。
源：`guide-axis/axis-guides-positive-rotation.svg`
（vdiffr 名 `axis guides, positive rotation`）。

上游 `test_draw_axis()` 不是 ggplot：它用 `draw_axis()` 在 0.05 / 0.9 / 0.05 npc
的三格 gtable 里直画四条轴。这里用一张空面板 + 四条轴（主轴 + `dup_axis()`）复现
同一版式：面板落在页面的 5%..95%，刻度与标签都画在面板内侧
（`axis.ticks.length` 取负值，R 的 guide 就是这么把轴线、刻度、文字排进同一个
单元格的）。
"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_blank,
    ggplot,
    guide_axis,
    guides,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, margin, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0.0, 1.0], "y": [0.0, 1.0]}
BREAKS = (
    0.0909090909,
    0.1818181818,
    0.2727272727,
    0.3636363636,
    0.4545454545,
    0.5454545455,
    0.6363636364,
    0.7272727273,
    0.8181818182,
    0.9090909091,
)
LABELS = (
    "1,000",
    "2,000",
    "3,000",
    "4,000",
    "5,000",
    "6,000",
    "7,000",
    "8,000",
    "9,000",
    "10,000",
)

#: 面板落在 5%..95%（上游 gtable 的 0.05 / 0.9 / 0.05 npc）；轴带（刻度 + 文字）
#: 占掉的部分从 36pt 里扣，值由渲染后量面板得到。
MARGIN = margin(4.75, 11.95, 4.75, 11.95)


def build():
    axis = dict(angle=45)
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + scale_x_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + scale_y_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + labs(x=None, y=None)
        + guides(
            x=guide_axis(**axis),
            y=guide_axis(**axis),
            **{"x.sec": guide_axis(**axis), "y.sec": guide_axis(**axis)},
        )
        + theme_test()
        + theme(
            **{
                "axis.line": element_line(linewidth=0.5),
                "axis.ticks.length": unit(-2.75, "pt"),
                "plot.margin": MARGIN,
            }
        )
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-guide-axis-axis-guides-vertical-negative-rotation",
        "snapshot": "guide-axis/axis-guides-vertical-negative-rotation.svg",
        "title": "axis guides, vertical negative rotation",
        "features": ["guide-axis", "rotation"],
        "notes": "SIL-791：vdiffr 快照原样纳入；标题是 doppelganger 名。",
        "source": r'''"""上游快照复刻：grid 直画的一条轴。

vdiffr 名：`axis guides, vertical negative rotation`。
源：`guide-axis/axis-guides-vertical-negative-rotation.svg`
（vdiffr 名 `axis guides, vertical negative rotation`）。

上游 `test_draw_axis()` 不是 ggplot：它用 `draw_axis()` 在 0.05 / 0.9 / 0.05 npc
的三格 gtable 里直画四条轴。这里用一张空面板 + 四条轴（主轴 + `dup_axis()`）复现
同一版式：面板落在页面的 5%..95%，刻度与标签都画在面板内侧
（`axis.ticks.length` 取负值，R 的 guide 就是这么把轴线、刻度、文字排进同一个
单元格的）。
"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_blank,
    ggplot,
    guide_axis,
    guides,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, margin, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0.0, 1.0], "y": [0.0, 1.0]}
BREAKS = (
    0.0909090909,
    0.1818181818,
    0.2727272727,
    0.3636363636,
    0.4545454545,
    0.5454545455,
    0.6363636364,
    0.7272727273,
    0.8181818182,
    0.9090909091,
)
LABELS = (
    "1,000",
    "2,000",
    "3,000",
    "4,000",
    "5,000",
    "6,000",
    "7,000",
    "8,000",
    "9,000",
    "10,000",
)

#: 面板落在 5%..95%（上游 gtable 的 0.05 / 0.9 / 0.05 npc）；轴带（刻度 + 文字）
#: 占掉的部分从 36pt 里扣，值由渲染后量面板得到。
MARGIN = margin(2.432, 28.676, 2.432, 28.676)


def build():
    axis = dict(angle=-90)
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + scale_x_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + scale_y_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + labs(x=None, y=None)
        + guides(
            x=guide_axis(**axis),
            y=guide_axis(**axis),
            **{"x.sec": guide_axis(**axis), "y.sec": guide_axis(**axis)},
        )
        + theme_test()
        + theme(
            **{
                "axis.line": element_line(linewidth=0.5),
                "axis.ticks.length": unit(-2.75, "pt"),
                "plot.margin": MARGIN,
            }
        )
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-guide-axis-axis-guides-vertical-rotation",
        "snapshot": "guide-axis/axis-guides-vertical-rotation.svg",
        "title": "axis guides, vertical rotation",
        "features": ["guide-axis", "rotation"],
        "notes": "SIL-791：vdiffr 快照原样纳入；标题是 doppelganger 名。",
        "source": r'''"""上游快照复刻：grid 直画的一条轴。

vdiffr 名：`axis guides, vertical rotation`。
源：`guide-axis/axis-guides-vertical-rotation.svg`
（vdiffr 名 `axis guides, vertical rotation`）。

上游 `test_draw_axis()` 不是 ggplot：它用 `draw_axis()` 在 0.05 / 0.9 / 0.05 npc
的三格 gtable 里直画四条轴。这里用一张空面板 + 四条轴（主轴 + `dup_axis()`）复现
同一版式：面板落在页面的 5%..95%，刻度与标签都画在面板内侧
（`axis.ticks.length` 取负值，R 的 guide 就是这么把轴线、刻度、文字排进同一个
单元格的）。
"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_blank,
    ggplot,
    guide_axis,
    guides,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, margin, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0.0, 1.0], "y": [0.0, 1.0]}
BREAKS = (
    0.0909090909,
    0.1818181818,
    0.2727272727,
    0.3636363636,
    0.4545454545,
    0.5454545455,
    0.6363636364,
    0.7272727273,
    0.8181818182,
    0.9090909091,
)
LABELS = (
    "1,000",
    "2,000",
    "3,000",
    "4,000",
    "5,000",
    "6,000",
    "7,000",
    "8,000",
    "9,000",
    "10,000",
)

#: 面板落在 5%..95%（上游 gtable 的 0.05 / 0.9 / 0.05 npc）；轴带（刻度 + 文字）
#: 占掉的部分从 36pt 里扣，值由渲染后量面板得到。
MARGIN = margin(2.432, 28.676, 2.432, 28.676)


def build():
    axis = dict(angle=90)
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + scale_x_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + scale_y_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + labs(x=None, y=None)
        + guides(
            x=guide_axis(**axis),
            y=guide_axis(**axis),
            **{"x.sec": guide_axis(**axis), "y.sec": guide_axis(**axis)},
        )
        + theme_test()
        + theme(
            **{
                "axis.line": element_line(linewidth=0.5),
                "axis.ticks.length": unit(-2.75, "pt"),
                "plot.margin": MARGIN,
            }
        )
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-guide-axis-axis-guides-zero-breaks",
        "snapshot": "guide-axis/axis-guides-zero-breaks.svg",
        "title": "axis guides, zero breaks",
        "features": ["guide-axis"],
        "notes": "SIL-791：vdiffr 快照原样纳入；标题是 doppelganger 名。",
        "source": r'''"""上游快照复刻：grid 直画的一条轴。

vdiffr 名：`axis guides, zero breaks`。
源：`guide-axis/axis-guides-zero-breaks.svg`
（vdiffr 名 `axis guides, zero breaks`）。

上游 `test_draw_axis()` 不是 ggplot：它用 `draw_axis()` 在 0.05 / 0.9 / 0.05 npc
的三格 gtable 里直画四条轴。这里用一张空面板 + 四条轴（主轴 + `dup_axis()`）复现
同一版式：面板落在页面的 5%..95%，刻度与标签都画在面板内侧
（`axis.ticks.length` 取负值，R 的 guide 就是这么把轴线、刻度、文字排进同一个
单元格的）。
"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_blank,
    ggplot,
    guide_axis,
    guides,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, margin, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0.0, 1.0], "y": [0.0, 1.0]}
BREAKS = ()
LABELS = ()

#: 面板落在 5%..95%（上游 gtable 的 0.05 / 0.9 / 0.05 npc）；轴带（刻度 + 文字）
#: 占掉的部分从 36pt 里扣，值由渲染后量面板得到。
MARGIN = margin(28.8, 36.0, 28.8, 36.0)


def build():
    axis = dict()
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + scale_x_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + scale_y_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + labs(x=None, y=None)
        + guides(
            x=guide_axis(**axis),
            y=guide_axis(**axis),
            **{"x.sec": guide_axis(**axis), "y.sec": guide_axis(**axis)},
        )
        + theme_test()
        + theme(
            **{
                "axis.line": element_line(linewidth=0.5),
                "axis.ticks.length": unit(-2.75, "pt"),
                "plot.margin": MARGIN,
            }
        )
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-guide-axis-axis-guides-zero-rotation",
        "snapshot": "guide-axis/axis-guides-zero-rotation.svg",
        "title": "axis guides, zero rotation",
        "features": ["guide-axis"],
        "notes": "SIL-791：vdiffr 快照原样纳入；标题是 doppelganger 名。",
        "source": r'''"""上游快照复刻：grid 直画的一条轴。

vdiffr 名：`axis guides, zero rotation`。
源：`guide-axis/axis-guides-zero-rotation.svg`
（vdiffr 名 `axis guides, zero rotation`）。

上游 `test_draw_axis()` 不是 ggplot：它用 `draw_axis()` 在 0.05 / 0.9 / 0.05 npc
的三格 gtable 里直画四条轴。这里用一张空面板 + 四条轴（主轴 + `dup_axis()`）复现
同一版式：面板落在页面的 5%..95%，刻度与标签都画在面板内侧
（`axis.ticks.length` 取负值，R 的 guide 就是这么把轴线、刻度、文字排进同一个
单元格的）。
"""

from ggcore.plot import (
    aes,
    dup_axis,
    geom_blank,
    ggplot,
    guide_axis,
    guides,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, margin, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0.0, 1.0], "y": [0.0, 1.0]}
BREAKS = (
    0.0909090909,
    0.1818181818,
    0.2727272727,
    0.3636363636,
    0.4545454545,
    0.5454545455,
    0.6363636364,
    0.7272727273,
    0.8181818182,
    0.9090909091,
)
LABELS = (
    "1,000",
    "2,000",
    "3,000",
    "4,000",
    "5,000",
    "6,000",
    "7,000",
    "8,000",
    "9,000",
    "10,000",
)

#: 面板落在 5%..95%（上游 gtable 的 0.05 / 0.9 / 0.05 npc）；轴带（刻度 + 文字）
#: 占掉的部分从 36pt 里扣，值由渲染后量面板得到。
MARGIN = margin(21.476, 9.632, 21.476, 9.632)


def build():
    axis = dict(angle=0)
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_blank()
        + scale_x_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + scale_y_continuous(
            limits=(0.0, 1.0),
            expand=(0.0, 0.0),
            breaks=BREAKS,
            labels=LABELS,
            **{"sec.axis": dup_axis()},
        )
        + labs(x=None, y=None)
        + guides(
            x=guide_axis(**axis),
            y=guide_axis(**axis),
            **{"x.sec": guide_axis(**axis), "y.sec": guide_axis(**axis)},
        )
        + theme_test()
        + theme(
            **{
                "axis.line": element_line(linewidth=0.5),
                "axis.ticks.length": unit(-2.75, "pt"),
                "plot.margin": MARGIN,
            }
        )
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-guide-axis-guide-titles-with-coord-transform",
        "snapshot": "guide-axis/guide-titles-with-coord-transform.svg",
        "title": "guide titles with coord_transform()",
        "features": ["guide-axis", "coord-trans", "lab-axis-title"],
        "notes": "SIL-791：vdiffr 快照原样纳入；标题是 doppelganger 名。",
        "source": r'''"""上游快照复刻：轴标题不被 `coord_transform()` 冲掉。

源：guide-axis/guide-titles-with-coord-transform.svg（vdiffr 名
'guide titles with coord_transform()'）。
"""

from ggcore.plot import (
    aes,
    coord_transform,
    geom_point,
    ggplot,
    guide_axis,
    guides,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0], "y": [1.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + theme_test()
        + guides(
            x=guide_axis(title="x (primary)"),
            y=guide_axis(title="y (primary)"),
            **{
                "x.sec": guide_axis(title="x (secondary)"),
                "y.sec": guide_axis(title="y (secondary)"),
            },
        )
        + coord_transform()
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-guide-axis-position-guide-titles",
        "snapshot": "guide-axis/position-guide-titles.svg",
        "title": "position guide titles",
        "features": ["guide-axis", "guide-none", "lab-axis-title"],
        "notes": "SIL-791：vdiffr 快照原样纳入；标题是 doppelganger 名。",
        "source": r'''"""上游快照复刻：`guide_none(title = )` 只留轴标题，不画刻度。

源：guide-axis/position-guide-titles.svg（vdiffr 名 'position guide titles'）。
"""

from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_none,
    guides,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0], "y": [1.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + theme_test()
        + guides(
            x=guide_none(title="x (primary)"),
            y=guide_none(title="y (primary)"),
            **{
                "x.sec": guide_none(title="x (secondary)"),
                "y.sec": guide_none(title="y (secondary)"),
            },
        )
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
    {
        "slug": "upstream-guide-axis-thick-axis-lines",
        "snapshot": "guide-axis/thick-axis-lines.svg",
        "title": "thick axis lines",
        "features": ["guide-axis", "theme-complete"],
        "notes": "SIL-791：vdiffr 快照原样纳入；标题是 doppelganger 名。",
        "source": r'''"""上游快照复刻：`theme_test()` + 粗轴线（linewidth 5、square 端点）。

源：guide-axis/thick-axis-lines.svg（vdiffr 名 'thick axis lines'）。
"""

from ggcore.plot import aes, geom_point, ggplot
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "mpg": [
        21,
        21,
        22.8,
        21.4,
        18.7,
        18.1,
        14.3,
        24.4,
        22.8,
        19.2,
        17.8,
        16.4,
        17.3,
        15.2,
        10.4,
        10.4,
        14.7,
        32.4,
        30.4,
        33.9,
        21.5,
        15.5,
        15.2,
        13.3,
        19.2,
        27.3,
        26,
        30.4,
        15.8,
        19.7,
        15,
        21.4,
    ],
    "cyl": [
        6,
        6,
        4,
        6,
        8,
        6,
        8,
        4,
        4,
        6,
        6,
        8,
        8,
        8,
        8,
        8,
        8,
        4,
        4,
        4,
        4,
        8,
        8,
        8,
        8,
        4,
        4,
        4,
        8,
        6,
        8,
        4,
    ],
    "disp": [
        160,
        160,
        108,
        258,
        360,
        225,
        360,
        146.7,
        140.8,
        167.6,
        167.6,
        275.8,
        275.8,
        275.8,
        472,
        460,
        440,
        78.7,
        75.7,
        71.1,
        120.1,
        318,
        304,
        350,
        400,
        79,
        120.3,
        95.1,
        351,
        145,
        301,
        121,
    ],
    "hp": [
        110,
        110,
        93,
        110,
        175,
        105,
        245,
        62,
        95,
        123,
        123,
        180,
        180,
        180,
        205,
        215,
        230,
        66,
        52,
        65,
        97,
        150,
        150,
        245,
        175,
        66,
        91,
        113,
        264,
        175,
        335,
        109,
    ],
    "drat": [
        3.9,
        3.9,
        3.85,
        3.08,
        3.15,
        2.76,
        3.21,
        3.69,
        3.92,
        3.92,
        3.92,
        3.07,
        3.07,
        3.07,
        2.93,
        3,
        3.23,
        4.08,
        4.93,
        4.22,
        3.7,
        2.76,
        3.15,
        3.73,
        3.08,
        4.08,
        4.43,
        3.77,
        4.22,
        3.62,
        3.54,
        4.11,
    ],
    "wt": [
        2.62,
        2.875,
        2.32,
        3.215,
        3.44,
        3.46,
        3.57,
        3.19,
        3.15,
        3.44,
        3.44,
        4.07,
        3.73,
        3.78,
        5.25,
        5.424,
        5.345,
        2.2,
        1.615,
        1.835,
        2.465,
        3.52,
        3.435,
        3.84,
        3.845,
        1.935,
        2.14,
        1.513,
        3.17,
        2.77,
        3.57,
        2.78,
    ],
    "qsec": [
        16.46,
        17.02,
        18.61,
        19.44,
        17.02,
        20.22,
        15.84,
        20,
        22.9,
        18.3,
        18.9,
        17.4,
        17.6,
        18,
        17.98,
        17.82,
        17.42,
        19.47,
        18.52,
        19.9,
        20.01,
        16.87,
        17.3,
        15.41,
        17.05,
        18.9,
        16.7,
        16.9,
        14.5,
        15.5,
        14.6,
        18.6,
    ],
    "vs": [
        0,
        0,
        1,
        1,
        0,
        1,
        0,
        1,
        1,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        1,
        0,
        0,
        0,
        0,
        1,
        0,
        1,
        0,
        0,
        0,
        1,
    ],
    "am": [
        1,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        1,
        1,
        1,
        1,
    ],
    "gear": [
        4,
        4,
        4,
        3,
        3,
        3,
        3,
        4,
        4,
        4,
        4,
        3,
        3,
        3,
        3,
        3,
        3,
        4,
        4,
        4,
        3,
        3,
        3,
        3,
        3,
        4,
        5,
        5,
        5,
        5,
        5,
        4,
    ],
    "carb": [
        4,
        4,
        1,
        1,
        2,
        1,
        4,
        2,
        2,
        4,
        4,
        3,
        3,
        3,
        4,
        4,
        4,
        1,
        2,
        1,
        1,
        2,
        2,
        4,
        2,
        1,
        2,
        2,
        4,
        6,
        8,
        2,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="wt", y="mpg"))
        + geom_point()
        + theme_test()
        + theme(**{"axis.line": element_line(linewidth=5, lineend="square")})
    )
    return {"plot": p, "size": [10, 8]}
''',
    },
]


def specs() -> list[dict[str, Any]]:
    # `upstream-theme-bw` 是先手写验证过的原型，保留它的 plot.py 不动。
    # 三个 `base_size = 33` 变体实测超阈（geom 缺省尺寸没跟 `theme$pointsize` 走，
    # 见 tools/upstream/snapshots.toml 的 reason），按缺口归口，不生成 case。
    # `upstream-theme-bw` 是手写原型，保留不动；三个 `base_size = 33` 变体
    # 已由 `from_theme()` 修好（SIL-792），重新纳入生成表。
    skip = {
        "upstream-theme-bw",
    }
    base = [
        spec
        for spec in _theme_specs() + _guide_specs() + _dotplot_specs()
        if spec["slug"] not in skip
    ]
    return (
        base
        + _G1A_SPECS
        + _G6_SPECS
        + _THEME_MISC_SPECS
        + _G1B_SPECS
        + _violin_specs()
        + _raster_specs()
    )


#: G1a（SIL-788）：guides / guide-legend / guide-colorbar / draw-key 四个簇的复刻表。
#:
#: 与上面前三族不同，这些图是「同一条 R 测试里的某个 `expect_doppelganger()`」，
#: 语法层组合各不相同（分箱标度、inside 图例、逐 guide 主题、旋转标签…），
#: 用模板反而更难读，所以每条直接给**完整的 plot.py 正文**（`source`）+ 特性标签。
#: `title` 仍是 vdiffr 的 doppelganger 名——它同时是 `labs(title=)` 的值，
#: 上游快照里画的就是这一行。
_G1A_SPECS: list[dict[str, Any]] = [
    {
        "slug": "upstream-guides-legend-on-left",
        "snapshot": "guides/legend-on-left.svg",
        "title": "legend on left",
        "features": ["guide-legend", "legend-pos-left"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_rect, element_text, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0], "y": [1.0], "z": ["a"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + labs(title="legend on left")
        + theme_test()
        + theme(
            **{
                "axis.text.x": element_text(angle=90, vjust=0.5),
                "legend.background": element_rect(fill="grey90"),
                "legend.key": element_rect(fill="grey90"),
                "legend.position": "left",
            }
        )
        + scale_x_continuous(breaks=(1,), labels=("very long axis label",))
        + scale_y_continuous(breaks=(1,), labels=("very long axis label",))
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-legend-on-right",
        "snapshot": "guides/legend-on-right.svg",
        "title": "legend on right",
        "features": ["guide-legend", "legend-pos-right"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_rect, element_text, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0], "y": [1.0], "z": ["a"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + labs(title="legend on right")
        + theme_test()
        + theme(
            **{
                "axis.text.x": element_text(angle=90, vjust=0.5),
                "legend.background": element_rect(fill="grey90"),
                "legend.key": element_rect(fill="grey90"),
                "legend.position": "right",
            }
        )
        + scale_x_continuous(breaks=(1,), labels=("very long axis label",))
        + scale_y_continuous(breaks=(1,), labels=("very long axis label",))
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-legend-on-top",
        "snapshot": "guides/legend-on-top.svg",
        "title": "legend on top",
        "features": ["guide-legend", "legend-pos-top"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_rect, element_text, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0], "y": [1.0], "z": ["a"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + labs(title="legend on top")
        + theme_test()
        + theme(
            **{
                "axis.text.x": element_text(angle=90, vjust=0.5),
                "legend.background": element_rect(fill="grey90"),
                "legend.key": element_rect(fill="grey90"),
                "legend.position": "top",
            }
        )
        + scale_x_continuous(breaks=(1,), labels=("very long axis label",))
        + scale_y_continuous(breaks=(1,), labels=("very long axis label",))
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-legend-on-bottom",
        "snapshot": "guides/legend-on-bottom.svg",
        "title": "legend on bottom",
        "features": ["guide-legend", "legend-pos-bottom"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_rect, element_text, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1.0], "y": [1.0], "z": ["a"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z"))
        + geom_point()
        + labs(title="legend on bottom")
        + theme_test()
        + theme(
            **{
                "axis.text.x": element_text(angle=90, vjust=0.5),
                "legend.background": element_rect(fill="grey90"),
                "legend.key": element_rect(fill="grey90"),
                "legend.position": "bottom",
            }
        )
        + scale_x_continuous(breaks=(1,), labels=("very long axis label",))
        + scale_y_continuous(breaks=(1,), labels=("very long axis label",))
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-padding-in-legend-box",
        "snapshot": "guides/padding-in-legend-box.svg",
        "title": "padding in legend box",
        "features": ["guide-legend", "legend-pos-right"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_bar,
    ggplot,
    guide_colourbar,
    guides,
    labs,
)
from ggcore.theme import element_rect, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C"], "y": [1, 1, 1], "c": [1, 2, 3]}


def build():
    base = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="x", colour="c"))
        + geom_bar(stat="identity")
        + guides(colour=guide_colourbar(order=1))
        + theme_test()
        + labs(title="padding in legend box")
        + theme(**{"legend.background": element_rect(colour="black")})
    )
    return {"plot": base, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-legend-inside-plot-centered",
        "snapshot": "guides/legend-inside-plot-centered.svg",
        "title": "legend inside plot, centered",
        "features": ["guide-legend", "guide-inside"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_bar,
    ggplot,
    guide_colourbar,
    guides,
    labs,
)
from ggcore.theme import element_rect, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C"], "y": [1, 1, 1], "c": [1, 2, 3]}


def build():
    base = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="x", colour="c"))
        + geom_bar(stat="identity")
        + guides(colour=guide_colourbar(order=1))
        + theme_test()
        + labs(title="legend inside plot, centered")
        + theme(**{"legend.background": element_rect(colour="black")})
    )
    p = base + theme(**{"legend.position": "inside", "legend.position.inside": (0.5, 0.5)})
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-legend-inside-plot-bottom-left",
        "snapshot": "guides/legend-inside-plot-bottom-left.svg",
        "title": "legend inside plot, bottom left",
        "features": ["guide-legend", "guide-inside"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_bar,
    ggplot,
    guide_colourbar,
    guides,
    labs,
)
from ggcore.theme import element_rect, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C"], "y": [1, 1, 1], "c": [1, 2, 3]}


def build():
    base = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="x", colour="c"))
        + geom_bar(stat="identity")
        + guides(colour=guide_colourbar(order=1))
        + theme_test()
        + labs(title="legend inside plot, bottom left")
        + theme(**{"legend.background": element_rect(colour="black")})
    )
    p = base + theme(
        **{
            "legend.position": "inside",
            "legend.justification": (0, 0),
            "legend.position.inside": (0, 0),
        }
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-legend-inside-plot-top-right",
        "snapshot": "guides/legend-inside-plot-top-right.svg",
        "title": "legend inside plot, top right",
        "features": ["guide-legend", "guide-inside"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_bar,
    ggplot,
    guide_colourbar,
    guides,
    labs,
)
from ggcore.theme import element_rect, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C"], "y": [1, 1, 1], "c": [1, 2, 3]}


def build():
    base = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="x", colour="c"))
        + geom_bar(stat="identity")
        + guides(colour=guide_colourbar(order=1))
        + theme_test()
        + labs(title="legend inside plot, top right")
        + theme(**{"legend.background": element_rect(colour="black")})
    )
    p = base + theme(
        **{
            "legend.position": "inside",
            "legend.justification": (1, 1),
            "legend.position.inside": (1, 1),
        }
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-legend-inside-plot-bottom-left-of-legend-at-center",
        "snapshot": "guides/legend-inside-plot-bottom-left-of-legend-at-center.svg",
        "title": "legend inside plot, bottom left of legend at center",
        "features": ["guide-legend", "guide-inside"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_bar,
    ggplot,
    guide_colourbar,
    guides,
    labs,
)
from ggcore.theme import element_rect, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C"], "y": [1, 1, 1], "c": [1, 2, 3]}


def build():
    base = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="x", colour="c"))
        + geom_bar(stat="identity")
        + guides(colour=guide_colourbar(order=1))
        + theme_test()
        + labs(title="legend inside plot, bottom left of legend at center")
        + theme(**{"legend.background": element_rect(colour="black")})
    )
    p = base + theme(
        **{
            "legend.position": "inside",
            "legend.justification": (0, 0),
            "legend.position.inside": (0.5, 0.5),
        }
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-legend-inside-plot-multiple-positions",
        "snapshot": "guides/legend-inside-plot-multiple-positions.svg",
        "title": "legend inside plot, multiple positions",
        "features": ["guide-legend", "guide-inside", "guide-multi"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_bar,
    ggplot,
    guide_colourbar,
    guide_legend,
    guides,
    labs,
)
from ggcore.theme import element_rect, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": ["A", "B", "C"], "y": [1, 1, 1], "c": [1, 2, 3]}


def build():
    base = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="x", colour="c"))
        + geom_bar(stat="identity")
        + guides(colour=guide_colourbar(order=1))
        + theme_test()
        + labs(title="legend inside plot, multiple positions")
        + theme(**{"legend.background": element_rect(colour="black")})
    )
    p = (
        base
        + theme(**{"legend.position": "inside"})
        + guides(
            colour=guide_colourbar(
                position="inside",
                theme=theme(
                    **{
                        "legend.position.inside": (0, 1),
                        "legend.justification.inside": (0, 1),
                    }
                ),
            ),
            fill=guide_legend(
                position="inside",
                theme=theme(
                    **{
                        "legend.position.inside": (1, 0),
                        "legend.justification.inside": (1, 0),
                    }
                ),
            ),
        )
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-multi-line-guide-title",
        "snapshot": "guides/multi-line-guide-title-works.svg",
        "title": "multi-line guide title works",
        "features": ["guide-legend", "multiline"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    guide_legend,
    guides,
    labs,
    scale_colour_discrete,
    scale_fill_continuous,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["1", "2", "3"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z", fill="y"))
        + geom_point(shape=21)
        + guides(colour=guide_legend(order=2), fill=guide_colourbar(order=1))
        + theme_test()
        + labs(title="multi-line guide title works")
    )
    p = (
        p
        + scale_colour_discrete(name="the\ndiscrete\ncolorscale")
        + scale_fill_continuous(name="the\ncontinuous\ncolorscale")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-vertical-gap-1cm-title-guide",
        "snapshot": "guides/vertical-gap-of-1cm-between-guide-title-and-guide.svg",
        "title": "vertical gap of 1cm between guide title and guide",
        "features": ["guide-legend"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    guide_legend,
    guides,
    labs,
)
from ggcore.theme import element_text, margin, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["1", "2", "3"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z", fill="y"))
        + geom_point(shape=21)
        + guides(colour=guide_legend(order=2), fill=guide_colourbar(order=1))
        + theme_test()
        + labs(title="vertical gap of 1cm between guide title and guide")
    )
    p = p + theme(**{"legend.title": element_text(margin=margin(b=1, unit="cm"))})
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-horizontal-gap-1cm-guide-text",
        "snapshot": "guides/horizontal-gap-of-1cm-between-guide-and-guide-text.svg",
        "title": "horizontal gap of 1cm between guide and guide text",
        "features": ["guide-legend"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    guide_legend,
    guides,
    labs,
)
from ggcore.theme import element_text, margin, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3], "z": ["1", "2", "3"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="z", fill="y"))
        + geom_point(shape=21)
        + guides(colour=guide_legend(order=2), fill=guide_colourbar(order=1))
        + theme_test()
        + labs(title="horizontal gap of 1cm between guide and guide text")
    )
    p = p + theme(**{"legend.text": element_text(margin=margin(l=1, unit="cm"))})
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-title-text-positioning-alignment",
        "snapshot": "guides/guide-title-and-text-positioning-and-alignment-via-themes.svg",
        "title": "guide title and text positioning and alignment via themes",
        "features": ["guide-legend", "theme-text"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    guide_legend,
    guides,
    labs,
)
from ggcore.theme import element_text, margin, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 10, 100]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", colour="x", size="x"))
        + geom_point()
        + guides(shape=guide_legend(order=1), colour=guide_colourbar(order=2))
        + theme_test()
        + labs(title="guide title and text positioning and alignment via themes")
        + theme(
            **{
                "legend.title": element_text(hjust=0.5, margin=margin(t=30, b=5.5)),
                "legend.text": element_text(hjust=1, margin=margin(l=10.5, t=10, b=10)),
            }
        )
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-rotated-guide-titles-labels",
        "snapshot": "guides/rotated-guide-titles-and-labels.svg",
        "title": "rotated guide titles and labels",
        "features": ["guide-legend", "rotation"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    guide_legend,
    labs,
    scale_colour_continuous,
    scale_fill_continuous,
)
from ggcore.theme import element_text, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [5, 10, 15], "f": [10, 5, 0]}


def build():
    p = ggplot(to_column_table(DATA), aes(x="x", y="x", colour="x", fill="f")) + geom_point(
        shape=21, size=5, stroke=3
    )
    p = p + scale_colour_continuous(
        name="value",
        guide=guide_colourbar(
            theme=theme(
                **{
                    "legend.title": element_text(size=11, angle=0, hjust=0.5, vjust=1),
                    "legend.text": element_text(size=0.8 * 11, angle=270, hjust=0.5, vjust=1),
                }
            ),
            order=2,
        ),
    )
    p = p + scale_fill_continuous(
        breaks=(5, 10, 15),
        limits=(5, 15),
        labels=("long 5", "long 10", "long 15"),
        name="fill value",
        guide=guide_legend(
            direction="horizontal",
            theme=theme(
                **{
                    "legend.title.position": "top",
                    "legend.text.position": "bottom",
                    "legend.title": element_text(size=11, angle=180, hjust=0, vjust=1),
                    "legend.text": element_text(size=0.8 * 11, angle=90, hjust=1, vjust=0.5),
                }
            ),
            order=1,
        ),
    )
    p = p + theme_test() + labs(title="rotated guide titles and labels")
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-legends-all-title-justifications",
        "snapshot": "guides/legends-with-all-title-justifications.svg",
        "title": "legends with all title justifications",
        "features": ["guide-legend", "hjust"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_legend,
    guides,
    labs,
    scale_alpha,
)
from ggcore.theme import element_text, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2], "z": ["1", "2"]}


def build():
    p = (
        ggplot(
            to_column_table(DATA),
            aes(x="x", y="x", colour="z", fill="z", shape="z", alpha="x"),
        )
        + geom_point()
        + scale_alpha(breaks=(1, 2))
        + guides(
            colour=guide_legend(
                "colour title with hjust = 0",
                order=1,
                theme=theme(**{"legend.title": element_text(hjust=0)}),
            ),
            fill=guide_legend(
                "fill title with hjust = 1",
                order=2,
                theme=theme(
                    **{
                        "legend.title": element_text(hjust=1),
                        "legend.title.position": "bottom",
                    }
                ),
                override_aes={"shape": 21},
            ),
            alpha=guide_legend(
                "Title\nfor\nalpha\nwith\nvjust=0",
                order=3,
                theme=theme(
                    **{
                        "legend.title": element_text(vjust=0),
                        "legend.title.position": "left",
                    }
                ),
            ),
            shape=guide_legend(
                "Title\nfor\nshape\nwith\nvjust=1",
                order=4,
                theme=theme(
                    **{
                        "legend.title": element_text(vjust=1),
                        "legend.title.position": "right",
                    }
                ),
            ),
        )
        + theme_test()
        + labs(title="legends with all title justifications")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-bins-coinciding-1",
        "snapshot": "guides/guide-bins-understands-coinciding-limits-and-bins.svg",
        "title": "guide_bins understands coinciding limits and bins",
        "features": ["guide-bins", "scale-limits"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "cty": [
        int(value)
        for value in (
            "18 21 20 21 16 18 18 18 16 20 19 15 "
            "17 17 15 15 17 16 14 11 14 13 12 16 "
            "15 16 15 15 14 11 11 14 19 22 18 18 "
            "17 18 17 16 16 17 17 11 15 15 16 16 "
            "15 14 13 14 14 14 9 11 11 13 13 9 "
            "13 11 13 11 12 9 13 13 12 9 11 11 "
            "13 11 11 11 12 14 15 14 13 13 13 14 "
            "14 13 13 13 11 13 18 18 17 16 15 15 "
            "15 15 14 28 24 25 23 24 26 25 24 21 "
            "18 18 21 21 18 18 19 19 19 20 20 17 "
            "16 17 17 15 15 14 9 14 13 11 11 12 "
            "12 11 11 11 12 14 13 13 13 21 19 23 "
            "23 19 19 18 19 19 14 15 14 12 18 16 "
            "17 18 16 18 18 20 19 20 18 21 19 19 "
            "19 20 20 19 20 15 16 15 15 16 14 21 "
            "21 21 21 18 18 19 21 21 21 22 18 18 "
            "18 24 24 26 28 26 11 13 15 16 17 15 "
            "15 15 16 21 19 21 22 17 33 21 19 22 "
            "21 21 21 16 17 35 29 21 19 20 20 21 "
            "18 19 21 16 18 17 "
        ).split()
    ],
    "hwy": [
        int(value)
        for value in (
            "29 29 31 30 26 26 27 26 25 28 27 25 "
            "25 25 25 24 25 23 20 15 20 17 17 26 "
            "23 26 25 24 19 14 15 17 27 30 26 29 "
            "26 24 24 22 22 24 24 17 22 21 23 23 "
            "19 18 17 17 19 19 12 17 15 17 17 12 "
            "17 16 18 15 16 12 17 17 16 12 15 16 "
            "17 15 17 17 18 17 19 17 19 19 17 17 "
            "17 16 16 17 15 17 26 25 26 24 21 22 "
            "23 22 20 33 32 32 29 32 34 36 36 29 "
            "26 27 30 31 26 26 28 26 29 28 27 24 "
            "24 24 22 19 20 17 12 19 18 14 15 18 "
            "18 15 17 16 18 17 19 19 17 29 27 31 "
            "32 27 26 26 25 25 17 17 20 18 26 26 "
            "27 28 25 25 24 27 25 26 23 26 26 26 "
            "26 25 27 25 27 20 20 19 17 20 17 29 "
            "27 31 31 26 26 28 27 29 31 31 26 26 "
            "27 30 33 35 37 35 15 18 20 20 22 17 "
            "19 18 20 29 26 29 29 24 44 29 26 29 "
            "29 29 29 23 24 44 41 29 26 28 29 29 "
            "29 28 29 26 26 26 "
        ).split()
    ],
    "year": [
        int(value)
        for value in (
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 2008 2008 2008 2008 2008 1999 2008 1999 "
            "1999 2008 2008 2008 2008 2008 1999 1999 1999 2008 1999 2008 "
            "2008 1999 1999 1999 1999 2008 2008 2008 1999 1999 2008 2008 "
            "2008 2008 1999 1999 2008 2008 2008 1999 1999 1999 2008 2008 "
            "2008 1999 2008 1999 2008 2008 2008 2008 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 1999 1999 1999 2008 2008 1999 1999 "
            "1999 1999 1999 2008 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 2008 2008 1999 1999 1999 1999 1999 2008 2008 2008 2008 "
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 2008 "
            "2008 2008 2008 2008 1999 1999 2008 2008 2008 2008 1999 2008 "
            "2008 1999 1999 1999 2008 1999 2008 2008 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "1999 2008 2008 1999 1999 2008 2008 2008 2008 1999 1999 1999 "
            "1999 2008 2008 2008 2008 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 2008 1999 2008 1999 1999 2008 1999 "
            "1999 2008 2008 1999 1999 2008 2008 1999 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 "
        ).split()
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cty", y="hwy", colour="year"))
        + geom_point()
        + scale_colour_binned(
            limits=(1999, 2008), breaks=(1999, 2000, 2002, 2004, 2006), guide="bins"
        )
        + theme_test()
        + labs(title="guide_bins understands coinciding limits and bins")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-bins-coinciding-2",
        "snapshot": "guides/guide-bins-understands-coinciding-limits-and-bins-2.svg",
        "title": "guide_bins understands coinciding limits and bins 2",
        "features": ["guide-bins", "scale-limits"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "cty": [
        int(value)
        for value in (
            "18 21 20 21 16 18 18 18 16 20 19 15 "
            "17 17 15 15 17 16 14 11 14 13 12 16 "
            "15 16 15 15 14 11 11 14 19 22 18 18 "
            "17 18 17 16 16 17 17 11 15 15 16 16 "
            "15 14 13 14 14 14 9 11 11 13 13 9 "
            "13 11 13 11 12 9 13 13 12 9 11 11 "
            "13 11 11 11 12 14 15 14 13 13 13 14 "
            "14 13 13 13 11 13 18 18 17 16 15 15 "
            "15 15 14 28 24 25 23 24 26 25 24 21 "
            "18 18 21 21 18 18 19 19 19 20 20 17 "
            "16 17 17 15 15 14 9 14 13 11 11 12 "
            "12 11 11 11 12 14 13 13 13 21 19 23 "
            "23 19 19 18 19 19 14 15 14 12 18 16 "
            "17 18 16 18 18 20 19 20 18 21 19 19 "
            "19 20 20 19 20 15 16 15 15 16 14 21 "
            "21 21 21 18 18 19 21 21 21 22 18 18 "
            "18 24 24 26 28 26 11 13 15 16 17 15 "
            "15 15 16 21 19 21 22 17 33 21 19 22 "
            "21 21 21 16 17 35 29 21 19 20 20 21 "
            "18 19 21 16 18 17 "
        ).split()
    ],
    "hwy": [
        int(value)
        for value in (
            "29 29 31 30 26 26 27 26 25 28 27 25 "
            "25 25 25 24 25 23 20 15 20 17 17 26 "
            "23 26 25 24 19 14 15 17 27 30 26 29 "
            "26 24 24 22 22 24 24 17 22 21 23 23 "
            "19 18 17 17 19 19 12 17 15 17 17 12 "
            "17 16 18 15 16 12 17 17 16 12 15 16 "
            "17 15 17 17 18 17 19 17 19 19 17 17 "
            "17 16 16 17 15 17 26 25 26 24 21 22 "
            "23 22 20 33 32 32 29 32 34 36 36 29 "
            "26 27 30 31 26 26 28 26 29 28 27 24 "
            "24 24 22 19 20 17 12 19 18 14 15 18 "
            "18 15 17 16 18 17 19 19 17 29 27 31 "
            "32 27 26 26 25 25 17 17 20 18 26 26 "
            "27 28 25 25 24 27 25 26 23 26 26 26 "
            "26 25 27 25 27 20 20 19 17 20 17 29 "
            "27 31 31 26 26 28 27 29 31 31 26 26 "
            "27 30 33 35 37 35 15 18 20 20 22 17 "
            "19 18 20 29 26 29 29 24 44 29 26 29 "
            "29 29 29 23 24 44 41 29 26 28 29 29 "
            "29 28 29 26 26 26 "
        ).split()
    ],
    "year": [
        int(value)
        for value in (
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 2008 2008 2008 2008 2008 1999 2008 1999 "
            "1999 2008 2008 2008 2008 2008 1999 1999 1999 2008 1999 2008 "
            "2008 1999 1999 1999 1999 2008 2008 2008 1999 1999 2008 2008 "
            "2008 2008 1999 1999 2008 2008 2008 1999 1999 1999 2008 2008 "
            "2008 1999 2008 1999 2008 2008 2008 2008 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 1999 1999 1999 2008 2008 1999 1999 "
            "1999 1999 1999 2008 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 2008 2008 1999 1999 1999 1999 1999 2008 2008 2008 2008 "
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 2008 "
            "2008 2008 2008 2008 1999 1999 2008 2008 2008 2008 1999 2008 "
            "2008 1999 1999 1999 2008 1999 2008 2008 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "1999 2008 2008 1999 1999 2008 2008 2008 2008 1999 1999 1999 "
            "1999 2008 2008 2008 2008 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 2008 1999 2008 1999 1999 2008 1999 "
            "1999 2008 2008 1999 1999 2008 2008 1999 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 "
        ).split()
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cty", y="hwy", colour="year"))
        + geom_point()
        + scale_colour_binned(
            limits=(1999, 2008), breaks=(2000, 2002, 2004, 2006, 2008), guide="bins"
        )
        + theme_test()
        + labs(title="guide_bins understands coinciding limits and bins 2")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-bins-coinciding-3",
        "snapshot": "guides/guide-bins-understands-coinciding-limits-and-bins-3.svg",
        "title": "guide_bins understands coinciding limits and bins 3",
        "features": ["guide-bins", "scale-limits"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "cty": [
        int(value)
        for value in (
            "18 21 20 21 16 18 18 18 16 20 19 15 "
            "17 17 15 15 17 16 14 11 14 13 12 16 "
            "15 16 15 15 14 11 11 14 19 22 18 18 "
            "17 18 17 16 16 17 17 11 15 15 16 16 "
            "15 14 13 14 14 14 9 11 11 13 13 9 "
            "13 11 13 11 12 9 13 13 12 9 11 11 "
            "13 11 11 11 12 14 15 14 13 13 13 14 "
            "14 13 13 13 11 13 18 18 17 16 15 15 "
            "15 15 14 28 24 25 23 24 26 25 24 21 "
            "18 18 21 21 18 18 19 19 19 20 20 17 "
            "16 17 17 15 15 14 9 14 13 11 11 12 "
            "12 11 11 11 12 14 13 13 13 21 19 23 "
            "23 19 19 18 19 19 14 15 14 12 18 16 "
            "17 18 16 18 18 20 19 20 18 21 19 19 "
            "19 20 20 19 20 15 16 15 15 16 14 21 "
            "21 21 21 18 18 19 21 21 21 22 18 18 "
            "18 24 24 26 28 26 11 13 15 16 17 15 "
            "15 15 16 21 19 21 22 17 33 21 19 22 "
            "21 21 21 16 17 35 29 21 19 20 20 21 "
            "18 19 21 16 18 17 "
        ).split()
    ],
    "hwy": [
        int(value)
        for value in (
            "29 29 31 30 26 26 27 26 25 28 27 25 "
            "25 25 25 24 25 23 20 15 20 17 17 26 "
            "23 26 25 24 19 14 15 17 27 30 26 29 "
            "26 24 24 22 22 24 24 17 22 21 23 23 "
            "19 18 17 17 19 19 12 17 15 17 17 12 "
            "17 16 18 15 16 12 17 17 16 12 15 16 "
            "17 15 17 17 18 17 19 17 19 19 17 17 "
            "17 16 16 17 15 17 26 25 26 24 21 22 "
            "23 22 20 33 32 32 29 32 34 36 36 29 "
            "26 27 30 31 26 26 28 26 29 28 27 24 "
            "24 24 22 19 20 17 12 19 18 14 15 18 "
            "18 15 17 16 18 17 19 19 17 29 27 31 "
            "32 27 26 26 25 25 17 17 20 18 26 26 "
            "27 28 25 25 24 27 25 26 23 26 26 26 "
            "26 25 27 25 27 20 20 19 17 20 17 29 "
            "27 31 31 26 26 28 27 29 31 31 26 26 "
            "27 30 33 35 37 35 15 18 20 20 22 17 "
            "19 18 20 29 26 29 29 24 44 29 26 29 "
            "29 29 29 23 24 44 41 29 26 28 29 29 "
            "29 28 29 26 26 26 "
        ).split()
    ],
    "year": [
        int(value)
        for value in (
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 2008 2008 2008 2008 2008 1999 2008 1999 "
            "1999 2008 2008 2008 2008 2008 1999 1999 1999 2008 1999 2008 "
            "2008 1999 1999 1999 1999 2008 2008 2008 1999 1999 2008 2008 "
            "2008 2008 1999 1999 2008 2008 2008 1999 1999 1999 2008 2008 "
            "2008 1999 2008 1999 2008 2008 2008 2008 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 1999 1999 1999 2008 2008 1999 1999 "
            "1999 1999 1999 2008 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 2008 2008 1999 1999 1999 1999 1999 2008 2008 2008 2008 "
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 2008 "
            "2008 2008 2008 2008 1999 1999 2008 2008 2008 2008 1999 2008 "
            "2008 1999 1999 1999 2008 1999 2008 2008 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "1999 2008 2008 1999 1999 2008 2008 2008 2008 1999 1999 1999 "
            "1999 2008 2008 2008 2008 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 2008 1999 2008 1999 1999 2008 1999 "
            "1999 2008 2008 1999 1999 2008 2008 1999 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 "
        ).split()
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cty", y="hwy", colour="year"))
        + geom_point()
        + scale_colour_binned(
            limits=(1999, 2008),
            breaks=(1999, 2000, 2002, 2004, 2006),
            guide="bins",
            show_limits=True,
        )
        + theme_test()
        + labs(title="guide_bins understands coinciding limits and bins 3")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-bins-labels-limits-in-breaks",
        "snapshot": "guides/guide-bins-sets-labels-when-limits-is-in-breaks.svg",
        "title": "guide_bins sets labels when limits is in breaks",
        "features": ["guide-bins", "scale-limits"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "cty": [
        int(value)
        for value in (
            "18 21 20 21 16 18 18 18 16 20 19 15 "
            "17 17 15 15 17 16 14 11 14 13 12 16 "
            "15 16 15 15 14 11 11 14 19 22 18 18 "
            "17 18 17 16 16 17 17 11 15 15 16 16 "
            "15 14 13 14 14 14 9 11 11 13 13 9 "
            "13 11 13 11 12 9 13 13 12 9 11 11 "
            "13 11 11 11 12 14 15 14 13 13 13 14 "
            "14 13 13 13 11 13 18 18 17 16 15 15 "
            "15 15 14 28 24 25 23 24 26 25 24 21 "
            "18 18 21 21 18 18 19 19 19 20 20 17 "
            "16 17 17 15 15 14 9 14 13 11 11 12 "
            "12 11 11 11 12 14 13 13 13 21 19 23 "
            "23 19 19 18 19 19 14 15 14 12 18 16 "
            "17 18 16 18 18 20 19 20 18 21 19 19 "
            "19 20 20 19 20 15 16 15 15 16 14 21 "
            "21 21 21 18 18 19 21 21 21 22 18 18 "
            "18 24 24 26 28 26 11 13 15 16 17 15 "
            "15 15 16 21 19 21 22 17 33 21 19 22 "
            "21 21 21 16 17 35 29 21 19 20 20 21 "
            "18 19 21 16 18 17 "
        ).split()
    ],
    "hwy": [
        int(value)
        for value in (
            "29 29 31 30 26 26 27 26 25 28 27 25 "
            "25 25 25 24 25 23 20 15 20 17 17 26 "
            "23 26 25 24 19 14 15 17 27 30 26 29 "
            "26 24 24 22 22 24 24 17 22 21 23 23 "
            "19 18 17 17 19 19 12 17 15 17 17 12 "
            "17 16 18 15 16 12 17 17 16 12 15 16 "
            "17 15 17 17 18 17 19 17 19 19 17 17 "
            "17 16 16 17 15 17 26 25 26 24 21 22 "
            "23 22 20 33 32 32 29 32 34 36 36 29 "
            "26 27 30 31 26 26 28 26 29 28 27 24 "
            "24 24 22 19 20 17 12 19 18 14 15 18 "
            "18 15 17 16 18 17 19 19 17 29 27 31 "
            "32 27 26 26 25 25 17 17 20 18 26 26 "
            "27 28 25 25 24 27 25 26 23 26 26 26 "
            "26 25 27 25 27 20 20 19 17 20 17 29 "
            "27 31 31 26 26 28 27 29 31 31 26 26 "
            "27 30 33 35 37 35 15 18 20 20 22 17 "
            "19 18 20 29 26 29 29 24 44 29 26 29 "
            "29 29 29 23 24 44 41 29 26 28 29 29 "
            "29 28 29 26 26 26 "
        ).split()
    ],
    "year": [
        int(value)
        for value in (
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 2008 2008 2008 2008 2008 1999 2008 1999 "
            "1999 2008 2008 2008 2008 2008 1999 1999 1999 2008 1999 2008 "
            "2008 1999 1999 1999 1999 2008 2008 2008 1999 1999 2008 2008 "
            "2008 2008 1999 1999 2008 2008 2008 1999 1999 1999 2008 2008 "
            "2008 1999 2008 1999 2008 2008 2008 2008 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 1999 1999 1999 2008 2008 1999 1999 "
            "1999 1999 1999 2008 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 2008 2008 1999 1999 1999 1999 1999 2008 2008 2008 2008 "
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 2008 "
            "2008 2008 2008 2008 1999 1999 2008 2008 2008 2008 1999 2008 "
            "2008 1999 1999 1999 2008 1999 2008 2008 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "1999 2008 2008 1999 1999 2008 2008 2008 2008 1999 1999 1999 "
            "1999 2008 2008 2008 2008 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 2008 1999 2008 1999 1999 2008 1999 "
            "1999 2008 2008 1999 1999 2008 2008 1999 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 "
        ).split()
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cty", y="hwy", colour="year"))
        + geom_point()
        + scale_colour_binned(
            limits=(1999, 2008),
            breaks=(1999, 2000, 2002, 2004, 2006),
            labels=(1, 2, 3, 4, 5),
            guide="bins",
        )
        + theme_test()
        + labs(title="guide_bins sets labels when limits is in breaks")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-colorsteps-coinciding-1",
        "snapshot": "guides/guide-colorsteps-understands-coinciding-limits-and-bins.svg",
        "title": "guide_colorsteps understands coinciding limits and bins",
        "features": ["guide-coloursteps", "scale-limits"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "cty": [
        int(value)
        for value in (
            "18 21 20 21 16 18 18 18 16 20 19 15 "
            "17 17 15 15 17 16 14 11 14 13 12 16 "
            "15 16 15 15 14 11 11 14 19 22 18 18 "
            "17 18 17 16 16 17 17 11 15 15 16 16 "
            "15 14 13 14 14 14 9 11 11 13 13 9 "
            "13 11 13 11 12 9 13 13 12 9 11 11 "
            "13 11 11 11 12 14 15 14 13 13 13 14 "
            "14 13 13 13 11 13 18 18 17 16 15 15 "
            "15 15 14 28 24 25 23 24 26 25 24 21 "
            "18 18 21 21 18 18 19 19 19 20 20 17 "
            "16 17 17 15 15 14 9 14 13 11 11 12 "
            "12 11 11 11 12 14 13 13 13 21 19 23 "
            "23 19 19 18 19 19 14 15 14 12 18 16 "
            "17 18 16 18 18 20 19 20 18 21 19 19 "
            "19 20 20 19 20 15 16 15 15 16 14 21 "
            "21 21 21 18 18 19 21 21 21 22 18 18 "
            "18 24 24 26 28 26 11 13 15 16 17 15 "
            "15 15 16 21 19 21 22 17 33 21 19 22 "
            "21 21 21 16 17 35 29 21 19 20 20 21 "
            "18 19 21 16 18 17 "
        ).split()
    ],
    "hwy": [
        int(value)
        for value in (
            "29 29 31 30 26 26 27 26 25 28 27 25 "
            "25 25 25 24 25 23 20 15 20 17 17 26 "
            "23 26 25 24 19 14 15 17 27 30 26 29 "
            "26 24 24 22 22 24 24 17 22 21 23 23 "
            "19 18 17 17 19 19 12 17 15 17 17 12 "
            "17 16 18 15 16 12 17 17 16 12 15 16 "
            "17 15 17 17 18 17 19 17 19 19 17 17 "
            "17 16 16 17 15 17 26 25 26 24 21 22 "
            "23 22 20 33 32 32 29 32 34 36 36 29 "
            "26 27 30 31 26 26 28 26 29 28 27 24 "
            "24 24 22 19 20 17 12 19 18 14 15 18 "
            "18 15 17 16 18 17 19 19 17 29 27 31 "
            "32 27 26 26 25 25 17 17 20 18 26 26 "
            "27 28 25 25 24 27 25 26 23 26 26 26 "
            "26 25 27 25 27 20 20 19 17 20 17 29 "
            "27 31 31 26 26 28 27 29 31 31 26 26 "
            "27 30 33 35 37 35 15 18 20 20 22 17 "
            "19 18 20 29 26 29 29 24 44 29 26 29 "
            "29 29 29 23 24 44 41 29 26 28 29 29 "
            "29 28 29 26 26 26 "
        ).split()
    ],
    "year": [
        int(value)
        for value in (
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 2008 2008 2008 2008 2008 1999 2008 1999 "
            "1999 2008 2008 2008 2008 2008 1999 1999 1999 2008 1999 2008 "
            "2008 1999 1999 1999 1999 2008 2008 2008 1999 1999 2008 2008 "
            "2008 2008 1999 1999 2008 2008 2008 1999 1999 1999 2008 2008 "
            "2008 1999 2008 1999 2008 2008 2008 2008 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 1999 1999 1999 2008 2008 1999 1999 "
            "1999 1999 1999 2008 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 2008 2008 1999 1999 1999 1999 1999 2008 2008 2008 2008 "
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 2008 "
            "2008 2008 2008 2008 1999 1999 2008 2008 2008 2008 1999 2008 "
            "2008 1999 1999 1999 2008 1999 2008 2008 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "1999 2008 2008 1999 1999 2008 2008 2008 2008 1999 1999 1999 "
            "1999 2008 2008 2008 2008 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 2008 1999 2008 1999 1999 2008 1999 "
            "1999 2008 2008 1999 1999 2008 2008 1999 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 "
        ).split()
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cty", y="hwy", colour="year"))
        + geom_point()
        + scale_colour_binned(limits=(1999, 2008), breaks=(1999, 2000, 2002, 2004, 2006))
        + theme_test()
        + labs(title="guide_colorsteps understands coinciding limits and bins")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-colorsteps-coinciding-2",
        "snapshot": "guides/guide-colorsteps-understands-coinciding-limits-and-bins-2.svg",
        "title": "guide_colorsteps understands coinciding limits and bins 2",
        "features": ["guide-coloursteps", "scale-limits"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "cty": [
        int(value)
        for value in (
            "18 21 20 21 16 18 18 18 16 20 19 15 "
            "17 17 15 15 17 16 14 11 14 13 12 16 "
            "15 16 15 15 14 11 11 14 19 22 18 18 "
            "17 18 17 16 16 17 17 11 15 15 16 16 "
            "15 14 13 14 14 14 9 11 11 13 13 9 "
            "13 11 13 11 12 9 13 13 12 9 11 11 "
            "13 11 11 11 12 14 15 14 13 13 13 14 "
            "14 13 13 13 11 13 18 18 17 16 15 15 "
            "15 15 14 28 24 25 23 24 26 25 24 21 "
            "18 18 21 21 18 18 19 19 19 20 20 17 "
            "16 17 17 15 15 14 9 14 13 11 11 12 "
            "12 11 11 11 12 14 13 13 13 21 19 23 "
            "23 19 19 18 19 19 14 15 14 12 18 16 "
            "17 18 16 18 18 20 19 20 18 21 19 19 "
            "19 20 20 19 20 15 16 15 15 16 14 21 "
            "21 21 21 18 18 19 21 21 21 22 18 18 "
            "18 24 24 26 28 26 11 13 15 16 17 15 "
            "15 15 16 21 19 21 22 17 33 21 19 22 "
            "21 21 21 16 17 35 29 21 19 20 20 21 "
            "18 19 21 16 18 17 "
        ).split()
    ],
    "hwy": [
        int(value)
        for value in (
            "29 29 31 30 26 26 27 26 25 28 27 25 "
            "25 25 25 24 25 23 20 15 20 17 17 26 "
            "23 26 25 24 19 14 15 17 27 30 26 29 "
            "26 24 24 22 22 24 24 17 22 21 23 23 "
            "19 18 17 17 19 19 12 17 15 17 17 12 "
            "17 16 18 15 16 12 17 17 16 12 15 16 "
            "17 15 17 17 18 17 19 17 19 19 17 17 "
            "17 16 16 17 15 17 26 25 26 24 21 22 "
            "23 22 20 33 32 32 29 32 34 36 36 29 "
            "26 27 30 31 26 26 28 26 29 28 27 24 "
            "24 24 22 19 20 17 12 19 18 14 15 18 "
            "18 15 17 16 18 17 19 19 17 29 27 31 "
            "32 27 26 26 25 25 17 17 20 18 26 26 "
            "27 28 25 25 24 27 25 26 23 26 26 26 "
            "26 25 27 25 27 20 20 19 17 20 17 29 "
            "27 31 31 26 26 28 27 29 31 31 26 26 "
            "27 30 33 35 37 35 15 18 20 20 22 17 "
            "19 18 20 29 26 29 29 24 44 29 26 29 "
            "29 29 29 23 24 44 41 29 26 28 29 29 "
            "29 28 29 26 26 26 "
        ).split()
    ],
    "year": [
        int(value)
        for value in (
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 2008 2008 2008 2008 2008 1999 2008 1999 "
            "1999 2008 2008 2008 2008 2008 1999 1999 1999 2008 1999 2008 "
            "2008 1999 1999 1999 1999 2008 2008 2008 1999 1999 2008 2008 "
            "2008 2008 1999 1999 2008 2008 2008 1999 1999 1999 2008 2008 "
            "2008 1999 2008 1999 2008 2008 2008 2008 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 1999 1999 1999 2008 2008 1999 1999 "
            "1999 1999 1999 2008 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 2008 2008 1999 1999 1999 1999 1999 2008 2008 2008 2008 "
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 2008 "
            "2008 2008 2008 2008 1999 1999 2008 2008 2008 2008 1999 2008 "
            "2008 1999 1999 1999 2008 1999 2008 2008 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "1999 2008 2008 1999 1999 2008 2008 2008 2008 1999 1999 1999 "
            "1999 2008 2008 2008 2008 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 2008 1999 2008 1999 1999 2008 1999 "
            "1999 2008 2008 1999 1999 2008 2008 1999 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 "
        ).split()
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cty", y="hwy", colour="year"))
        + geom_point()
        + scale_colour_binned(limits=(1999, 2008), breaks=(2000, 2002, 2004, 2006, 2008))
        + theme_test()
        + labs(title="guide_colorsteps understands coinciding limits and bins 2")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-colorsteps-coinciding-3",
        "snapshot": "guides/guide-colorsteps-understands-coinciding-limits-and-bins-3.svg",
        "title": "guide_colorsteps understands coinciding limits and bins 3",
        "features": ["guide-coloursteps", "scale-limits"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "cty": [
        int(value)
        for value in (
            "18 21 20 21 16 18 18 18 16 20 19 15 "
            "17 17 15 15 17 16 14 11 14 13 12 16 "
            "15 16 15 15 14 11 11 14 19 22 18 18 "
            "17 18 17 16 16 17 17 11 15 15 16 16 "
            "15 14 13 14 14 14 9 11 11 13 13 9 "
            "13 11 13 11 12 9 13 13 12 9 11 11 "
            "13 11 11 11 12 14 15 14 13 13 13 14 "
            "14 13 13 13 11 13 18 18 17 16 15 15 "
            "15 15 14 28 24 25 23 24 26 25 24 21 "
            "18 18 21 21 18 18 19 19 19 20 20 17 "
            "16 17 17 15 15 14 9 14 13 11 11 12 "
            "12 11 11 11 12 14 13 13 13 21 19 23 "
            "23 19 19 18 19 19 14 15 14 12 18 16 "
            "17 18 16 18 18 20 19 20 18 21 19 19 "
            "19 20 20 19 20 15 16 15 15 16 14 21 "
            "21 21 21 18 18 19 21 21 21 22 18 18 "
            "18 24 24 26 28 26 11 13 15 16 17 15 "
            "15 15 16 21 19 21 22 17 33 21 19 22 "
            "21 21 21 16 17 35 29 21 19 20 20 21 "
            "18 19 21 16 18 17 "
        ).split()
    ],
    "hwy": [
        int(value)
        for value in (
            "29 29 31 30 26 26 27 26 25 28 27 25 "
            "25 25 25 24 25 23 20 15 20 17 17 26 "
            "23 26 25 24 19 14 15 17 27 30 26 29 "
            "26 24 24 22 22 24 24 17 22 21 23 23 "
            "19 18 17 17 19 19 12 17 15 17 17 12 "
            "17 16 18 15 16 12 17 17 16 12 15 16 "
            "17 15 17 17 18 17 19 17 19 19 17 17 "
            "17 16 16 17 15 17 26 25 26 24 21 22 "
            "23 22 20 33 32 32 29 32 34 36 36 29 "
            "26 27 30 31 26 26 28 26 29 28 27 24 "
            "24 24 22 19 20 17 12 19 18 14 15 18 "
            "18 15 17 16 18 17 19 19 17 29 27 31 "
            "32 27 26 26 25 25 17 17 20 18 26 26 "
            "27 28 25 25 24 27 25 26 23 26 26 26 "
            "26 25 27 25 27 20 20 19 17 20 17 29 "
            "27 31 31 26 26 28 27 29 31 31 26 26 "
            "27 30 33 35 37 35 15 18 20 20 22 17 "
            "19 18 20 29 26 29 29 24 44 29 26 29 "
            "29 29 29 23 24 44 41 29 26 28 29 29 "
            "29 28 29 26 26 26 "
        ).split()
    ],
    "year": [
        int(value)
        for value in (
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 2008 2008 2008 2008 2008 1999 2008 1999 "
            "1999 2008 2008 2008 2008 2008 1999 1999 1999 2008 1999 2008 "
            "2008 1999 1999 1999 1999 2008 2008 2008 1999 1999 2008 2008 "
            "2008 2008 1999 1999 2008 2008 2008 1999 1999 1999 2008 2008 "
            "2008 1999 2008 1999 2008 2008 2008 2008 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 1999 1999 1999 2008 2008 1999 1999 "
            "1999 1999 1999 2008 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 2008 2008 1999 1999 1999 1999 1999 2008 2008 2008 2008 "
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 2008 "
            "2008 2008 2008 2008 1999 1999 2008 2008 2008 2008 1999 2008 "
            "2008 1999 1999 1999 2008 1999 2008 2008 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "1999 2008 2008 1999 1999 2008 2008 2008 2008 1999 1999 1999 "
            "1999 2008 2008 2008 2008 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 2008 1999 2008 1999 1999 2008 1999 "
            "1999 2008 2008 1999 1999 2008 2008 1999 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 "
        ).split()
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cty", y="hwy", colour="year"))
        + geom_point()
        + scale_colour_binned(
            limits=(1999, 2008), breaks=(1999, 2000, 2002, 2004, 2006), show_limits=True
        )
        + theme_test()
        + labs(title="guide_colorsteps understands coinciding limits and bins 3")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-colorsteps-labels-limits-in-breaks",
        "snapshot": "guides/guide-colorsteps-sets-labels-when-limits-is-in-breaks.svg",
        "title": "guide_colorsteps sets labels when limits is in breaks",
        "features": ["guide-coloursteps", "scale-limits"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "cty": [
        int(value)
        for value in (
            "18 21 20 21 16 18 18 18 16 20 19 15 "
            "17 17 15 15 17 16 14 11 14 13 12 16 "
            "15 16 15 15 14 11 11 14 19 22 18 18 "
            "17 18 17 16 16 17 17 11 15 15 16 16 "
            "15 14 13 14 14 14 9 11 11 13 13 9 "
            "13 11 13 11 12 9 13 13 12 9 11 11 "
            "13 11 11 11 12 14 15 14 13 13 13 14 "
            "14 13 13 13 11 13 18 18 17 16 15 15 "
            "15 15 14 28 24 25 23 24 26 25 24 21 "
            "18 18 21 21 18 18 19 19 19 20 20 17 "
            "16 17 17 15 15 14 9 14 13 11 11 12 "
            "12 11 11 11 12 14 13 13 13 21 19 23 "
            "23 19 19 18 19 19 14 15 14 12 18 16 "
            "17 18 16 18 18 20 19 20 18 21 19 19 "
            "19 20 20 19 20 15 16 15 15 16 14 21 "
            "21 21 21 18 18 19 21 21 21 22 18 18 "
            "18 24 24 26 28 26 11 13 15 16 17 15 "
            "15 15 16 21 19 21 22 17 33 21 19 22 "
            "21 21 21 16 17 35 29 21 19 20 20 21 "
            "18 19 21 16 18 17 "
        ).split()
    ],
    "hwy": [
        int(value)
        for value in (
            "29 29 31 30 26 26 27 26 25 28 27 25 "
            "25 25 25 24 25 23 20 15 20 17 17 26 "
            "23 26 25 24 19 14 15 17 27 30 26 29 "
            "26 24 24 22 22 24 24 17 22 21 23 23 "
            "19 18 17 17 19 19 12 17 15 17 17 12 "
            "17 16 18 15 16 12 17 17 16 12 15 16 "
            "17 15 17 17 18 17 19 17 19 19 17 17 "
            "17 16 16 17 15 17 26 25 26 24 21 22 "
            "23 22 20 33 32 32 29 32 34 36 36 29 "
            "26 27 30 31 26 26 28 26 29 28 27 24 "
            "24 24 22 19 20 17 12 19 18 14 15 18 "
            "18 15 17 16 18 17 19 19 17 29 27 31 "
            "32 27 26 26 25 25 17 17 20 18 26 26 "
            "27 28 25 25 24 27 25 26 23 26 26 26 "
            "26 25 27 25 27 20 20 19 17 20 17 29 "
            "27 31 31 26 26 28 27 29 31 31 26 26 "
            "27 30 33 35 37 35 15 18 20 20 22 17 "
            "19 18 20 29 26 29 29 24 44 29 26 29 "
            "29 29 29 23 24 44 41 29 26 28 29 29 "
            "29 28 29 26 26 26 "
        ).split()
    ],
    "year": [
        int(value)
        for value in (
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 2008 2008 2008 2008 2008 1999 2008 1999 "
            "1999 2008 2008 2008 2008 2008 1999 1999 1999 2008 1999 2008 "
            "2008 1999 1999 1999 1999 2008 2008 2008 1999 1999 2008 2008 "
            "2008 2008 1999 1999 2008 2008 2008 1999 1999 1999 2008 2008 "
            "2008 1999 2008 1999 2008 2008 2008 2008 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 1999 1999 1999 2008 2008 1999 1999 "
            "1999 1999 1999 2008 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 2008 2008 1999 1999 1999 1999 1999 2008 2008 2008 2008 "
            "1999 1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 2008 "
            "2008 2008 2008 2008 1999 1999 2008 2008 2008 2008 1999 2008 "
            "2008 1999 1999 1999 2008 1999 2008 2008 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "1999 2008 2008 1999 1999 2008 2008 2008 2008 1999 1999 1999 "
            "1999 2008 2008 2008 2008 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 1999 1999 2008 2008 1999 1999 "
            "2008 1999 1999 1999 2008 2008 1999 2008 1999 1999 2008 1999 "
            "1999 2008 2008 1999 1999 2008 2008 1999 1999 1999 1999 2008 "
            "2008 2008 2008 1999 1999 1999 1999 1999 1999 2008 2008 1999 "
            "1999 2008 2008 1999 1999 2008 "
        ).split()
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="cty", y="hwy", colour="year"))
        + geom_point()
        + scale_colour_binned(
            limits=(1999, 2008),
            breaks=(1999, 2000, 2002, 2004, 2006),
            labels=(1, 2, 3, 4, 5),
        )
        + theme_test()
        + labs(title="guide_colorsteps sets labels when limits is in breaks")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-bins-looks-as-it-should",
        "snapshot": "guides/guide-bins-looks-as-it-should.svg",
        "title": "guide_bins looks as it should",
        "features": ["guide-bins", "scale-size"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guides,
    labs,
    scale_size_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", size="x"))
        + geom_point()
        + scale_size_binned()
        + guides()
        + theme_test()
        + labs(title="guide_bins looks as it should")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-bins-show-limits",
        "snapshot": "guides/guide-bins-can-show-limits.svg",
        "title": "guide_bins can show limits",
        "features": ["guide-bins", "scale-size"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_bins,
    guides,
    labs,
    scale_size_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", size="x"))
        + geom_point()
        + scale_size_binned()
        + guides(size=guide_bins(show_limits=True))
        + theme_test()
        + labs(title="guide_bins can show limits")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-bins-show-arrows",
        "snapshot": "guides/guide-bins-can-show-arrows.svg",
        "title": "guide_bins can show arrows",
        "features": ["guide-bins", "scale-size"],
        "source": r"""from ggcore.plot import (
    aes,
    arrow,
    geom_point,
    ggplot,
    guide_bins,
    guides,
    labs,
    scale_size_binned,
)
from ggcore.theme import element_line, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", size="x"))
        + geom_point()
        + scale_size_binned()
        + guides(size=guide_bins())
        + theme_test()
        + theme(
            **{
                "legend.axis.line": element_line(
                    linewidth=0.5 / 2.845276,
                    arrow=arrow(length=unit(1.5, "mm"), ends="both"),
                )
            }
        )
        + theme_test()
        + labs(title="guide_bins can show arrows")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-bins-remove-axis",
        "snapshot": "guides/guide-bins-can-remove-axis.svg",
        "title": "guide_bins can remove axis",
        "features": ["guide-bins", "scale-size"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_bins,
    guides,
    labs,
    scale_size_binned,
)
from ggcore.theme import element_blank, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", size="x"))
        + geom_point()
        + scale_size_binned()
        + guides(size=guide_bins())
        + theme_test()
        + theme(**{"legend.axis.line": element_blank()})
        + theme_test()
        + labs(title="guide_bins can remove axis")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-bins-work-horizontally",
        "snapshot": "guides/guide-bins-work-horizontally.svg",
        "title": "guide_bins work horizontally",
        "features": ["guide-bins", "guide-horizontal"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_bins,
    guides,
    labs,
    scale_size_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", size="x"))
        + geom_point()
        + scale_size_binned()
        + guides(size=guide_bins(direction="horizontal"))
        + theme_test()
        + labs(title="guide_bins work horizontally")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-coloursteps-looks-as-it-should",
        "snapshot": "guides/guide-coloursteps-looks-as-it-should.svg",
        "title": "guide_coloursteps looks as it should",
        "features": ["guide-coloursteps"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guides,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 4], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="x"))
        + geom_point()
        + scale_colour_binned(breaks=(1.5, 2, 3))
        + guides()
        + theme_test()
        + labs(title="guide_coloursteps looks as it should")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-coloursteps-show-limits",
        "snapshot": "guides/guide-coloursteps-can-show-limits.svg",
        "title": "guide_coloursteps can show limits",
        "features": ["guide-coloursteps"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_coloursteps,
    guides,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 4], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="x"))
        + geom_point()
        + scale_colour_binned(breaks=(1.5, 2, 3))
        + guides(colour=guide_coloursteps(show_limits=True))
        + theme_test()
        + labs(title="guide_coloursteps can show limits")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-coloursteps-binsize",
        "snapshot": "guides/guide-coloursteps-can-have-bins-relative-to-binsize.svg",
        "title": "guide_coloursteps can have bins relative to binsize",
        "features": ["guide-coloursteps"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_coloursteps,
    guides,
    labs,
    scale_colour_binned,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 4], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="x"))
        + geom_point()
        + scale_colour_binned(breaks=(1.5, 2, 3))
        + guides(colour=guide_coloursteps(even_steps=False))
        + theme_test()
        + labs(title="guide_coloursteps can have bins relative to binsize")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-bins-ticks-transparency",
        "snapshot": "guides/guide-bins-can-show-ticks-and-transparancy.svg",
        "title": "guide_bins can show ticks and transparancy",
        "features": ["guide-coloursteps", "alpha-aes"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_coloursteps,
    guides,
    labs,
    scale_colour_binned,
)
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 4], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="x"))
        + geom_point()
        + scale_colour_binned(breaks=(1.5, 2, 3))
        + guides(
            colour=guide_coloursteps(
                alpha=0.75,
                theme=theme(
                    **{"legend.ticks": element_line(linewidth=0.5 / 2.845276, colour="white")}
                ),
            )
        )
        + theme_test()
        + labs(title="guide_bins can show ticks and transparancy")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-reversed-guide-bins",
        "snapshot": "guides/reversed-guide-bins.svg",
        "title": "reversed guide_bins",
        "features": ["guide-bins", "guide-bins-reverse"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_bins,
    guides,
    labs,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [0, 100]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", colour="x", fill="x"))
        + geom_point()
        + guides(
            colour=guide_bins(reverse=True, show_limits=True, order=1),
            fill=guide_bins(reverse=True, show_limits=False, order=2, override_aes={"shape": 21}),
        )
        + theme_test()
        + labs(title="reversed guide_bins")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-guide-custom-with-void-theme",
        "snapshot": "guides/guide-custom-with-void-theme.svg",
        "title": "guide_custom with void theme",
        "features": ["guide-legend", "theme-complete"],
        "source": r"""from ggcore.grobs import circle_grob
from ggcore.plot import (
    aes,
    geom_blank,
    ggplot,
    guide_custom,
    guides,
    labs,
)
from ggcore.theme import theme_void
from ggcore.viewport import unit
from ggio.frame import to_column_table

EMPTY = {"x": [], "y": []}


def build():
    # 上游是 `ggplot()`（没有图层）；三文件 case 要求至少一层，用 `geom_blank()`
    # 铺一个空数据图层，像素上没有区别（不画任何东西）。
    p = (
        ggplot(to_column_table(EMPTY), aes(x="x", y="y"))
        + geom_blank()
        + guides(custom=guide_custom(circle_grob(r=unit(1, "cm")), title="custom guide"))
    )
    p = p + theme_void() + labs(title="guide_custom with void theme")
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guides-old-s3-guide-circle",
        "snapshot": "guides/old-s3-guide-drawing-a-circle.svg",
        "title": "old S3 guide drawing a circle",
        "features": ["guide-legend", "api-extension"],
        "source": r"""from ggcore.grobs import circle_grob
from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_custom,
    guides,
    labs,
)
from ggcore.theme import theme_test
from ggcore.viewport import unit
from ggio.frame import to_column_table

DATA = {
    "mpg": [
        21.0,
        21.0,
        22.8,
        21.4,
        18.7,
        18.1,
        14.3,
        24.4,
        22.8,
        19.2,
        17.8,
        16.4,
        17.3,
        15.2,
        10.4,
        10.4,
        14.7,
        32.4,
        30.4,
        33.9,
        21.5,
        15.5,
        15.2,
        13.3,
        19.2,
        27.3,
        26.0,
        30.4,
        15.8,
        19.7,
        15.0,
        21.4,
    ],
    "disp": [
        160,
        160,
        108,
        258,
        360,
        225,
        360,
        146.7,
        140.8,
        167.6,
        167.6,
        275.8,
        275.8,
        275.8,
        472,
        460,
        440,
        78.7,
        75.7,
        71.1,
        120.1,
        318,
        304,
        350,
        400,
        79,
        120.3,
        95.1,
        351,
        145,
        301,
        121,
    ],
    "cyl": [
        "6",
        "6",
        "4",
        "6",
        "8",
        "6",
        "8",
        "4",
        "4",
        "6",
        "6",
        "8",
        "8",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "4",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "8",
        "6",
        "8",
        "4",
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="disp", y="mpg"))
        + geom_point()
        + guides(custom=guide_custom(circle_grob(r=unit(0.5, "npc")), position="bottom"))
        + theme_test()
        + labs(title="old S3 guide drawing a circle")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guide-legend-vertical-direction",
        "snapshot": "guide-legend/vertical-legend-direction.svg",
        "title": "vertical legend direction",
        "features": ["guide-legend", "guide-direction-vertical"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
)
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "mpg": [
        21.0,
        21.0,
        22.8,
        21.4,
        18.7,
        18.1,
        14.3,
        24.4,
        22.8,
        19.2,
        17.8,
        16.4,
        17.3,
        15.2,
        10.4,
        10.4,
        14.7,
        32.4,
        30.4,
        33.9,
        21.5,
        15.5,
        15.2,
        13.3,
        19.2,
        27.3,
        26.0,
        30.4,
        15.8,
        19.7,
        15.0,
        21.4,
    ],
    "disp": [
        160,
        160,
        108,
        258,
        360,
        225,
        360,
        146.7,
        140.8,
        167.6,
        167.6,
        275.8,
        275.8,
        275.8,
        472,
        460,
        440,
        78.7,
        75.7,
        71.1,
        120.1,
        318,
        304,
        350,
        400,
        79,
        120.3,
        95.1,
        351,
        145,
        301,
        121,
    ],
    "cyl": [
        "6",
        "6",
        "4",
        "6",
        "8",
        "6",
        "8",
        "4",
        "4",
        "6",
        "6",
        "8",
        "8",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "4",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "8",
        "6",
        "8",
        "4",
    ],
    "drat": [
        3.9,
        3.9,
        3.85,
        3.08,
        3.15,
        2.76,
        3.21,
        3.69,
        3.92,
        3.92,
        3.92,
        3.07,
        3.07,
        3.07,
        2.93,
        3.0,
        3.23,
        4.08,
        4.93,
        4.22,
        3.7,
        2.76,
        3.15,
        3.73,
        3.08,
        4.08,
        4.43,
        3.77,
        4.22,
        3.62,
        3.54,
        4.11,
    ],
    "carb": [
        "4",
        "4",
        "1",
        "1",
        "2",
        "1",
        "4",
        "2",
        "2",
        "4",
        "4",
        "3",
        "3",
        "3",
        "4",
        "4",
        "4",
        "1",
        "2",
        "1",
        "1",
        "2",
        "2",
        "4",
        "2",
        "1",
        "2",
        "2",
        "4",
        "6",
        "8",
        "2",
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="disp", y="mpg", shape="cyl", colour="drat"))
        + geom_point()
        + theme_test()
        + theme(**{"legend.direction": "vertical"})
        + labs(title="vertical legend direction")
    )

    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guide-legend-horizontal-direction",
        "snapshot": "guide-legend/horizontal-legend-direction.svg",
        "title": "horizontal legend direction",
        "features": ["guide-legend", "guide-direction-horizontal"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
)
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "mpg": [
        21.0,
        21.0,
        22.8,
        21.4,
        18.7,
        18.1,
        14.3,
        24.4,
        22.8,
        19.2,
        17.8,
        16.4,
        17.3,
        15.2,
        10.4,
        10.4,
        14.7,
        32.4,
        30.4,
        33.9,
        21.5,
        15.5,
        15.2,
        13.3,
        19.2,
        27.3,
        26.0,
        30.4,
        15.8,
        19.7,
        15.0,
        21.4,
    ],
    "disp": [
        160,
        160,
        108,
        258,
        360,
        225,
        360,
        146.7,
        140.8,
        167.6,
        167.6,
        275.8,
        275.8,
        275.8,
        472,
        460,
        440,
        78.7,
        75.7,
        71.1,
        120.1,
        318,
        304,
        350,
        400,
        79,
        120.3,
        95.1,
        351,
        145,
        301,
        121,
    ],
    "cyl": [
        "6",
        "6",
        "4",
        "6",
        "8",
        "6",
        "8",
        "4",
        "4",
        "6",
        "6",
        "8",
        "8",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "4",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "8",
        "6",
        "8",
        "4",
    ],
    "drat": [
        3.9,
        3.9,
        3.85,
        3.08,
        3.15,
        2.76,
        3.21,
        3.69,
        3.92,
        3.92,
        3.92,
        3.07,
        3.07,
        3.07,
        2.93,
        3.0,
        3.23,
        4.08,
        4.93,
        4.22,
        3.7,
        2.76,
        3.15,
        3.73,
        3.08,
        4.08,
        4.43,
        3.77,
        4.22,
        3.62,
        3.54,
        4.11,
    ],
    "carb": [
        "4",
        "4",
        "1",
        "1",
        "2",
        "1",
        "4",
        "2",
        "2",
        "4",
        "4",
        "3",
        "3",
        "3",
        "4",
        "4",
        "4",
        "1",
        "2",
        "1",
        "1",
        "2",
        "2",
        "4",
        "2",
        "1",
        "2",
        "2",
        "4",
        "6",
        "8",
        "2",
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="disp", y="mpg", shape="cyl", colour="drat"))
        + geom_point()
        + theme_test()
        + theme(**{"legend.direction": "horizontal"})
        + labs(title="horizontal legend direction")
    )

    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guide-legend-widely-spaced-keys",
        "snapshot": "guide-legend/legend-with-widely-spaced-keys.svg",
        "title": "legend with widely spaced keys",
        "features": ["guide-legend"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_legend,
    guides,
    labs,
)
from ggcore.theme import theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {
    "mpg": [
        21.0,
        21.0,
        22.8,
        21.4,
        18.7,
        18.1,
        14.3,
        24.4,
        22.8,
        19.2,
        17.8,
        16.4,
        17.3,
        15.2,
        10.4,
        10.4,
        14.7,
        32.4,
        30.4,
        33.9,
        21.5,
        15.5,
        15.2,
        13.3,
        19.2,
        27.3,
        26.0,
        30.4,
        15.8,
        19.7,
        15.0,
        21.4,
    ],
    "disp": [
        160,
        160,
        108,
        258,
        360,
        225,
        360,
        146.7,
        140.8,
        167.6,
        167.6,
        275.8,
        275.8,
        275.8,
        472,
        460,
        440,
        78.7,
        75.7,
        71.1,
        120.1,
        318,
        304,
        350,
        400,
        79,
        120.3,
        95.1,
        351,
        145,
        301,
        121,
    ],
    "cyl": [
        "6",
        "6",
        "4",
        "6",
        "8",
        "6",
        "8",
        "4",
        "4",
        "6",
        "6",
        "8",
        "8",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "4",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "8",
        "6",
        "8",
        "4",
    ],
    "drat": [
        3.9,
        3.9,
        3.85,
        3.08,
        3.15,
        2.76,
        3.21,
        3.69,
        3.92,
        3.92,
        3.92,
        3.07,
        3.07,
        3.07,
        2.93,
        3.0,
        3.23,
        4.08,
        4.93,
        4.22,
        3.7,
        2.76,
        3.15,
        3.73,
        3.08,
        4.08,
        4.43,
        3.77,
        4.22,
        3.62,
        3.54,
        4.11,
    ],
    "carb": [
        "4",
        "4",
        "1",
        "1",
        "2",
        "1",
        "4",
        "2",
        "2",
        "4",
        "4",
        "3",
        "3",
        "3",
        "4",
        "4",
        "4",
        "1",
        "2",
        "1",
        "1",
        "2",
        "2",
        "4",
        "2",
        "1",
        "2",
        "2",
        "4",
        "6",
        "8",
        "2",
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="disp", y="mpg", colour="carb"))
        + geom_point()
        + guides(colour=guide_legend(ncol=2))
        + theme_test()
        + theme(
            **{
                "legend.key.spacing.x": unit(2, "lines"),
                "legend.key.spacing.y": unit(1, "lines"),
            }
        )
        + labs(title="legend with widely spaced keys")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guide-legend-left-aligned-key",
        "snapshot": "guide-legend/left-aligned-legend-key.svg",
        "title": "left aligned legend key",
        "features": ["guide-legend", "legend-pos-top"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
)
from ggcore.theme import element_blank, element_line, element_rect, margin, theme
from ggio.frame import to_column_table

DATA = {
    "mpg": [
        21.0,
        21.0,
        22.8,
        21.4,
        18.7,
        18.1,
        14.3,
        24.4,
        22.8,
        19.2,
        17.8,
        16.4,
        17.3,
        15.2,
        10.4,
        10.4,
        14.7,
        32.4,
        30.4,
        33.9,
        21.5,
        15.5,
        15.2,
        13.3,
        19.2,
        27.3,
        26.0,
        30.4,
        15.8,
        19.7,
        15.0,
        21.4,
    ],
    "disp": [
        160,
        160,
        108,
        258,
        360,
        225,
        360,
        146.7,
        140.8,
        167.6,
        167.6,
        275.8,
        275.8,
        275.8,
        472,
        460,
        440,
        78.7,
        75.7,
        71.1,
        120.1,
        318,
        304,
        350,
        400,
        79,
        120.3,
        95.1,
        351,
        145,
        301,
        121,
    ],
    "cyl": [
        "6",
        "6",
        "4",
        "6",
        "8",
        "6",
        "8",
        "4",
        "4",
        "6",
        "6",
        "8",
        "8",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "4",
        "8",
        "8",
        "8",
        "8",
        "4",
        "4",
        "4",
        "8",
        "6",
        "8",
        "4",
    ],
    "drat": [
        3.9,
        3.9,
        3.85,
        3.08,
        3.15,
        2.76,
        3.21,
        3.69,
        3.92,
        3.92,
        3.92,
        3.07,
        3.07,
        3.07,
        2.93,
        3.0,
        3.23,
        4.08,
        4.93,
        4.22,
        3.7,
        2.76,
        3.15,
        3.73,
        3.08,
        4.08,
        4.43,
        3.77,
        4.22,
        3.62,
        3.54,
        4.11,
    ],
    "carb": [
        "4",
        "4",
        "1",
        "1",
        "2",
        "1",
        "4",
        "2",
        "2",
        "4",
        "4",
        "3",
        "3",
        "3",
        "4",
        "4",
        "4",
        "1",
        "2",
        "1",
        "1",
        "2",
        "2",
        "4",
        "2",
        "1",
        "2",
        "2",
        "4",
        "6",
        "8",
        "2",
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="disp", y="mpg", colour="cyl"))
        + geom_point()
        + theme(
            **{
                "legend.title": element_blank(),
                "legend.margin": margin(),
                "legend.position": "top",
                "legend.justification": "left",
                "legend.key": element_rect(colour="black"),
                "axis.line": element_line(colour="black"),
            }
        )
        + labs(title="left aligned legend key")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guide-legend-byrow-true",
        "snapshot": "guide-legend/legend-byrow-true.svg",
        "title": "legend.byrow = TRUE",
        "features": ["guide-legend"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_legend,
    labs,
    scale_colour_discrete,
)
from ggcore.theme import theme, theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3, 4, 5, 6], "f": ["A", "B", "C", "D", "E", "F"]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", colour="f"))
        + geom_point()
        + scale_colour_discrete(
            guide=guide_legend(ncol=3, theme=theme(**{"legend.byrow": True})),
        )
        + theme_test()
        + labs(title="legend.byrow = TRUE")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guide-colorbar-white-to-red",
        "snapshot": "guide-colorbar/white-to-red-colorbar-white-ticks-no-frame.svg",
        "title": "white-to-red colorbar, white ticks, no frame",
        "features": ["guide-colourbar", "scale-gradient"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_gradient,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [0, 1, 2]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", colour="x"))
        + geom_point()
        + scale_colour_gradient(low="white", high="red")
        + theme_test()
        + labs(title="white-to-red colorbar, white ticks, no frame")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guide-colorbar-customized",
        "snapshot": "guide-colorbar/customized-colorbar.svg",
        "title": "customized colorbar",
        "features": ["guide-colourbar", "scale-gradient"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    guide_colourbar,
    labs,
    scale_colour_gradient,
)
from ggcore.theme import element_line, element_rect, theme, theme_test
from ggcore.units import unit
from ggio.frame import to_column_table

DATA = {"x": [0, 1, 2]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="x", colour="x"))
        + geom_point()
        + scale_colour_gradient(
            low="white",
            high="red",
            guide=guide_colourbar(
                theme=theme(
                    **{
                        "legend.frame": element_rect(colour="green", linewidth=1.5 / 2.845276),
                        "legend.ticks": element_line("black", linewidth=2.5 / 2.845276),
                        "legend.ticks.length": unit((0.2, 0.4), "npc"),
                    }
                ),
                alpha=0.75,
            ),
        )
        + theme_test()
        + labs(
            title="customized colorbar",
            subtitle="white-to-red semitransparent colorbar, long thick black ticks, green frame",
        )
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-guide-colorbar-combined-aesthetics",
        "snapshot": "guide-colorbar/combined-colour-and-fill-aesthetics.svg",
        "title": "combined colour and fill aesthetics",
        "features": ["guide-colourbar", "scale-viridis", "guide-merged"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_point,
    ggplot,
    labs,
    scale_colour_viridis_c,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [6, 5, 7]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y", colour="x", fill="y"))
        + geom_point(shape=21, size=3, stroke=2)
        + scale_colour_viridis_c(name="value", option="B", aesthetics=("colour", "fill"))
        + theme_test()
        + labs(title="combined colour and fill aesthetics")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-draw-key-horizontal-boxplot-crossbar",
        "snapshot": "draw-key/horizontal-boxplot-and-crossbar.svg",
        "title": "horizontal boxplot and crossbar",
        "features": ["guide-legend", "orientation-horizontal"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_boxplot,
    geom_crossbar,
    ggplot,
    guide_legend,
    guides,
    labs,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "middle": [1, 2],
    "lower": [0, 1],
    "upper": [2, 3],
    "min": [-1, 0],
    "max": [3, 4],
    "group1": ["a", "b"],
    "group2": ["c", "d"],
}


def build():
    p = (
        ggplot(
            to_column_table(DATA),
            aes(
                x="middle",
                xmiddle="middle",
                xlower="lower",
                xupper="upper",
                xmin="min",
                xmax="max",
            ),
        )
        + geom_boxplot(aes(y="group1", colour="group1"), stat="identity")
        + geom_crossbar(aes(y="group2", fill="group2"))
        + guides(colour=guide_legend(order=1))
        + theme_test()
        + labs(title="horizontal boxplot and crossbar")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
    {
        "slug": "upstream-draw-key-horizontal-linerange-pointrange",
        "snapshot": "draw-key/horizontal-linerange-and-pointrange.svg",
        "title": "horizontal linerange and pointrange",
        "features": ["guide-legend", "orientation-horizontal"],
        "source": r"""from ggcore.plot import (
    aes,
    geom_linerange,
    geom_pointrange,
    ggplot,
    guide_legend,
    guides,
    labs,
)
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "middle": [1, 2],
    "lower": [0, 1],
    "upper": [2, 3],
    "min": [-1, 0],
    "max": [3, 4],
    "group1": ["a", "b"],
    "group2": ["c", "d"],
}


def build():
    p = (
        ggplot(
            to_column_table(DATA),
            aes(
                x="middle",
                xmiddle="middle",
                xlower="lower",
                xupper="upper",
                xmin="min",
                xmax="max",
            ),
        )
        + geom_linerange(aes(y="group1", colour="group1"))
        + geom_pointrange(aes(y="group2", shape="group2"))
        + guides(colour=guide_legend(order=1))
        + theme_test()
        + labs(title="horizontal linerange and pointrange")
    )
    return {"plot": p, "size": [10, 8]}
""",
    },
]

#: G6（SIL-790）：`scales-breaks-labels` 13 + `scale_date` 8 两簇的复刻表。
#:
#: 与 G1a 同样用完整 `source` + `meta` 正文（每条图的语法组合不同，模板反而难读）。
#: `scale_date` 的数据是 R 4.5 直接导出的：`set.seed(321)` 之后 `sample(100, 50)`
#: 取 `dx`、`runif(50)` 取 `price`——不是本仓生成的随机数（R 与 numpy 的 RNG 不可
#: 互相复现，见 tools/refs/position_ref.R 的同一句口径）。
_G6_SPECS: list[dict[str, Any]] = [
    {
        "slug": "upstream-scale-date-dates-along-x-default-breaks",
        "snapshot": "scale_date/dates-along-x-default-breaks.svg",
        "title": "上游快照：dates along x, default breaks",
        "source": r'''"""上游快照复刻：dates along x, default breaks。

源：scale_date/dates-along-x-default-breaks.svg。
vdiffr 名：dates along x, default breaks。

`set.seed(321)` 的 `dx` / `price` 由 R 4.5 直接导出
（`sample(100, 50)` + `runif(50)`），不是本仓生成的随机数。

R 测试里隐含的默认标度（`scale_x_date()`）显式写出：本仓还没有
「Date 列 → `scale_*_date()`」的隐式标度解析，图本身与 R 一致。

expected.svg 是上游那份，未改写。
"""

import datetime

from ggcore.plot import aes, geom_line, ggplot, labs, scale_x_date
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "dx": [
        datetime.date(2012, 2, 29),
        datetime.date(2012, 3, 3),
        datetime.date(2012, 3, 6),
        datetime.date(2012, 3, 7),
        datetime.date(2012, 3, 8),
        datetime.date(2012, 3, 10),
        datetime.date(2012, 3, 12),
        datetime.date(2012, 3, 14),
        datetime.date(2012, 3, 16),
        datetime.date(2012, 3, 17),
        datetime.date(2012, 3, 19),
        datetime.date(2012, 3, 22),
        datetime.date(2012, 3, 24),
        datetime.date(2012, 3, 28),
        datetime.date(2012, 3, 29),
        datetime.date(2012, 3, 30),
        datetime.date(2012, 4, 2),
        datetime.date(2012, 4, 3),
        datetime.date(2012, 4, 4),
        datetime.date(2012, 4, 9),
        datetime.date(2012, 4, 13),
        datetime.date(2012, 4, 14),
        datetime.date(2012, 4, 15),
        datetime.date(2012, 4, 16),
        datetime.date(2012, 4, 17),
        datetime.date(2012, 4, 19),
        datetime.date(2012, 4, 22),
        datetime.date(2012, 4, 26),
        datetime.date(2012, 4, 27),
        datetime.date(2012, 4, 28),
        datetime.date(2012, 4, 30),
        datetime.date(2012, 5, 1),
        datetime.date(2012, 5, 2),
        datetime.date(2012, 5, 5),
        datetime.date(2012, 5, 11),
        datetime.date(2012, 5, 13),
        datetime.date(2012, 5, 15),
        datetime.date(2012, 5, 16),
        datetime.date(2012, 5, 17),
        datetime.date(2012, 5, 18),
        datetime.date(2012, 5, 19),
        datetime.date(2012, 5, 20),
        datetime.date(2012, 5, 22),
        datetime.date(2012, 5, 26),
        datetime.date(2012, 5, 27),
        datetime.date(2012, 5, 28),
        datetime.date(2012, 5, 29),
        datetime.date(2012, 6, 3),
        datetime.date(2012, 6, 6),
        datetime.date(2012, 6, 7),
    ],
    "price": [
        0.9616501040,
        0.1624869567,
        0.0412904064,
        0.1565073295,
        0.5024147367,
        0.7918214588,
        0.0852337643,
        0.5842047508,
        0.3109124061,
        0.8940171362,
        0.6412378051,
        0.9455218136,
        0.7880687607,
        0.2636332642,
        0.1869768053,
        0.6517536691,
        0.9137707094,
        0.9281317706,
        0.5269326805,
        0.6258383121,
        0.1299404269,
        0.7331085226,
        0.5964183512,
        0.4944653544,
        0.4151498503,
        0.1815023392,
        0.0621891215,
        0.5988593667,
        0.6920898366,
        0.5219928171,
        0.2529071253,
        0.1591295504,
        0.5071416628,
        0.6335240912,
        0.5045890666,
        0.6020734545,
        0.1328208803,
        0.8721084816,
        0.1653388974,
        0.9785593627,
        0.4015488112,
        0.6336023652,
        0.6511391723,
        0.5311487252,
        0.9967931078,
        0.8299274566,
        0.9569348753,
        0.8791833892,
        0.2694185616,
        0.5792052438,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="dx", y="price"))
        + geom_line()
        + scale_x_date()
        + theme_test()
        + labs(title="dates along x, default breaks")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-date"]
ci = true
title = "上游快照：dates along x, default breaks"
source = "upstream:tests/testthat/_snaps/scale_date/dates-along-x-default-breaks.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名；数据按 R 的 set.seed(321) 导出。"
""",
    },
    {
        "slug": "upstream-scale-date-dates-along-y-default-breaks",
        "snapshot": "scale_date/dates-along-y-default-breaks.svg",
        "title": "上游快照：dates along y, default breaks",
        "source": r'''"""上游快照复刻：dates along y, default breaks。

源：scale_date/dates-along-y-default-breaks.svg。
vdiffr 名：dates along y, default breaks。

`set.seed(321)` 的 `dx` / `price` 由 R 4.5 直接导出
（`sample(100, 50)` + `runif(50)`），不是本仓生成的随机数。

R 测试里隐含的默认标度（`scale_y_date()`）显式写出：本仓还没有
「Date 列 → `scale_*_date()`」的隐式标度解析，图本身与 R 一致。

expected.svg 是上游那份，未改写。
"""

import datetime

from ggcore.plot import aes, geom_line, ggplot, labs, scale_y_date
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "dx": [
        datetime.date(2012, 2, 29),
        datetime.date(2012, 3, 3),
        datetime.date(2012, 3, 6),
        datetime.date(2012, 3, 7),
        datetime.date(2012, 3, 8),
        datetime.date(2012, 3, 10),
        datetime.date(2012, 3, 12),
        datetime.date(2012, 3, 14),
        datetime.date(2012, 3, 16),
        datetime.date(2012, 3, 17),
        datetime.date(2012, 3, 19),
        datetime.date(2012, 3, 22),
        datetime.date(2012, 3, 24),
        datetime.date(2012, 3, 28),
        datetime.date(2012, 3, 29),
        datetime.date(2012, 3, 30),
        datetime.date(2012, 4, 2),
        datetime.date(2012, 4, 3),
        datetime.date(2012, 4, 4),
        datetime.date(2012, 4, 9),
        datetime.date(2012, 4, 13),
        datetime.date(2012, 4, 14),
        datetime.date(2012, 4, 15),
        datetime.date(2012, 4, 16),
        datetime.date(2012, 4, 17),
        datetime.date(2012, 4, 19),
        datetime.date(2012, 4, 22),
        datetime.date(2012, 4, 26),
        datetime.date(2012, 4, 27),
        datetime.date(2012, 4, 28),
        datetime.date(2012, 4, 30),
        datetime.date(2012, 5, 1),
        datetime.date(2012, 5, 2),
        datetime.date(2012, 5, 5),
        datetime.date(2012, 5, 11),
        datetime.date(2012, 5, 13),
        datetime.date(2012, 5, 15),
        datetime.date(2012, 5, 16),
        datetime.date(2012, 5, 17),
        datetime.date(2012, 5, 18),
        datetime.date(2012, 5, 19),
        datetime.date(2012, 5, 20),
        datetime.date(2012, 5, 22),
        datetime.date(2012, 5, 26),
        datetime.date(2012, 5, 27),
        datetime.date(2012, 5, 28),
        datetime.date(2012, 5, 29),
        datetime.date(2012, 6, 3),
        datetime.date(2012, 6, 6),
        datetime.date(2012, 6, 7),
    ],
    "price": [
        0.9616501040,
        0.1624869567,
        0.0412904064,
        0.1565073295,
        0.5024147367,
        0.7918214588,
        0.0852337643,
        0.5842047508,
        0.3109124061,
        0.8940171362,
        0.6412378051,
        0.9455218136,
        0.7880687607,
        0.2636332642,
        0.1869768053,
        0.6517536691,
        0.9137707094,
        0.9281317706,
        0.5269326805,
        0.6258383121,
        0.1299404269,
        0.7331085226,
        0.5964183512,
        0.4944653544,
        0.4151498503,
        0.1815023392,
        0.0621891215,
        0.5988593667,
        0.6920898366,
        0.5219928171,
        0.2529071253,
        0.1591295504,
        0.5071416628,
        0.6335240912,
        0.5045890666,
        0.6020734545,
        0.1328208803,
        0.8721084816,
        0.1653388974,
        0.9785593627,
        0.4015488112,
        0.6336023652,
        0.6511391723,
        0.5311487252,
        0.9967931078,
        0.8299274566,
        0.9569348753,
        0.8791833892,
        0.2694185616,
        0.5792052438,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="price", y="dx"))
        + geom_line()
        + scale_y_date()
        + theme_test()
        + labs(title="dates along y, default breaks")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-date"]
ci = true
title = "上游快照：dates along y, default breaks"
source = "upstream:tests/testthat/_snaps/scale_date/dates-along-y-default-breaks.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名；数据按 R 的 set.seed(321) 导出。"
""",
    },
    {
        "slug": "upstream-scale-date-scale-x-date-breaks-3-weeks",
        "snapshot": "scale_date/scale-x-date-breaks-3-weeks.svg",
        "title": '上游快照：scale_x_date(breaks = "3 weeks")',
        "source": r'''"""上游快照复刻：scale_x_date(breaks = "3 weeks")。

源：scale_date/scale-x-date-breaks-3-weeks.svg。
vdiffr 名：scale_x_date(breaks = "3 weeks")。

`set.seed(321)` 的 `dx` / `price` 由 R 4.5 直接导出
（`sample(100, 50)` + `runif(50)`），不是本仓生成的随机数。

expected.svg 是上游那份，未改写。
"""

import datetime

from ggcore.plot import aes, geom_line, ggplot, labs, scale_x_date
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "dx": [
        datetime.date(2012, 2, 29),
        datetime.date(2012, 3, 3),
        datetime.date(2012, 3, 6),
        datetime.date(2012, 3, 7),
        datetime.date(2012, 3, 8),
        datetime.date(2012, 3, 10),
        datetime.date(2012, 3, 12),
        datetime.date(2012, 3, 14),
        datetime.date(2012, 3, 16),
        datetime.date(2012, 3, 17),
        datetime.date(2012, 3, 19),
        datetime.date(2012, 3, 22),
        datetime.date(2012, 3, 24),
        datetime.date(2012, 3, 28),
        datetime.date(2012, 3, 29),
        datetime.date(2012, 3, 30),
        datetime.date(2012, 4, 2),
        datetime.date(2012, 4, 3),
        datetime.date(2012, 4, 4),
        datetime.date(2012, 4, 9),
        datetime.date(2012, 4, 13),
        datetime.date(2012, 4, 14),
        datetime.date(2012, 4, 15),
        datetime.date(2012, 4, 16),
        datetime.date(2012, 4, 17),
        datetime.date(2012, 4, 19),
        datetime.date(2012, 4, 22),
        datetime.date(2012, 4, 26),
        datetime.date(2012, 4, 27),
        datetime.date(2012, 4, 28),
        datetime.date(2012, 4, 30),
        datetime.date(2012, 5, 1),
        datetime.date(2012, 5, 2),
        datetime.date(2012, 5, 5),
        datetime.date(2012, 5, 11),
        datetime.date(2012, 5, 13),
        datetime.date(2012, 5, 15),
        datetime.date(2012, 5, 16),
        datetime.date(2012, 5, 17),
        datetime.date(2012, 5, 18),
        datetime.date(2012, 5, 19),
        datetime.date(2012, 5, 20),
        datetime.date(2012, 5, 22),
        datetime.date(2012, 5, 26),
        datetime.date(2012, 5, 27),
        datetime.date(2012, 5, 28),
        datetime.date(2012, 5, 29),
        datetime.date(2012, 6, 3),
        datetime.date(2012, 6, 6),
        datetime.date(2012, 6, 7),
    ],
    "price": [
        0.9616501040,
        0.1624869567,
        0.0412904064,
        0.1565073295,
        0.5024147367,
        0.7918214588,
        0.0852337643,
        0.5842047508,
        0.3109124061,
        0.8940171362,
        0.6412378051,
        0.9455218136,
        0.7880687607,
        0.2636332642,
        0.1869768053,
        0.6517536691,
        0.9137707094,
        0.9281317706,
        0.5269326805,
        0.6258383121,
        0.1299404269,
        0.7331085226,
        0.5964183512,
        0.4944653544,
        0.4151498503,
        0.1815023392,
        0.0621891215,
        0.5988593667,
        0.6920898366,
        0.5219928171,
        0.2529071253,
        0.1591295504,
        0.5071416628,
        0.6335240912,
        0.5045890666,
        0.6020734545,
        0.1328208803,
        0.8721084816,
        0.1653388974,
        0.9785593627,
        0.4015488112,
        0.6336023652,
        0.6511391723,
        0.5311487252,
        0.9967931078,
        0.8299274566,
        0.9569348753,
        0.8791833892,
        0.2694185616,
        0.5792052438,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="dx", y="price"))
        + geom_line()
        + scale_x_date(date_breaks="3 weeks")
        + theme_test()
        + labs(title='scale_x_date(breaks = "3 weeks")')
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-date"]
ci = true
title = "上游快照：scale_x_date(breaks = \"3 weeks\")"
source = "upstream:tests/testthat/_snaps/scale_date/scale-x-date-breaks-3-weeks.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名；数据按 R 的 set.seed(321) 导出。"
""",
    },
    {
        "slug": "upstream-scale-date-scale-x-date-breaks-breaks-width-2-weeks",
        "snapshot": "scale_date/scale-x-date-breaks-breaks-width-2-weeks.svg",
        "title": '上游快照：scale_x_date(breaks = breaks_width("2 weeks"))',
        "source": r'''"""上游快照复刻：scale_x_date(breaks = breaks_width("2 weeks"))。

源：scale_date/scale-x-date-breaks-breaks-width-2-weeks.svg。
vdiffr 名：scale_x_date(breaks = breaks_width("2 weeks"))。

`set.seed(321)` 的 `dx` / `price` 由 R 4.5 直接导出
（`sample(100, 50)` + `runif(50)`），不是本仓生成的随机数。

expected.svg 是上游那份，未改写。
"""

import datetime

from ggcore.plot import aes, geom_line, ggplot, labs, scale_x_date
from ggcore.scales_date import breaks_width_date
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "dx": [
        datetime.date(2012, 2, 29),
        datetime.date(2012, 3, 3),
        datetime.date(2012, 3, 6),
        datetime.date(2012, 3, 7),
        datetime.date(2012, 3, 8),
        datetime.date(2012, 3, 10),
        datetime.date(2012, 3, 12),
        datetime.date(2012, 3, 14),
        datetime.date(2012, 3, 16),
        datetime.date(2012, 3, 17),
        datetime.date(2012, 3, 19),
        datetime.date(2012, 3, 22),
        datetime.date(2012, 3, 24),
        datetime.date(2012, 3, 28),
        datetime.date(2012, 3, 29),
        datetime.date(2012, 3, 30),
        datetime.date(2012, 4, 2),
        datetime.date(2012, 4, 3),
        datetime.date(2012, 4, 4),
        datetime.date(2012, 4, 9),
        datetime.date(2012, 4, 13),
        datetime.date(2012, 4, 14),
        datetime.date(2012, 4, 15),
        datetime.date(2012, 4, 16),
        datetime.date(2012, 4, 17),
        datetime.date(2012, 4, 19),
        datetime.date(2012, 4, 22),
        datetime.date(2012, 4, 26),
        datetime.date(2012, 4, 27),
        datetime.date(2012, 4, 28),
        datetime.date(2012, 4, 30),
        datetime.date(2012, 5, 1),
        datetime.date(2012, 5, 2),
        datetime.date(2012, 5, 5),
        datetime.date(2012, 5, 11),
        datetime.date(2012, 5, 13),
        datetime.date(2012, 5, 15),
        datetime.date(2012, 5, 16),
        datetime.date(2012, 5, 17),
        datetime.date(2012, 5, 18),
        datetime.date(2012, 5, 19),
        datetime.date(2012, 5, 20),
        datetime.date(2012, 5, 22),
        datetime.date(2012, 5, 26),
        datetime.date(2012, 5, 27),
        datetime.date(2012, 5, 28),
        datetime.date(2012, 5, 29),
        datetime.date(2012, 6, 3),
        datetime.date(2012, 6, 6),
        datetime.date(2012, 6, 7),
    ],
    "price": [
        0.9616501040,
        0.1624869567,
        0.0412904064,
        0.1565073295,
        0.5024147367,
        0.7918214588,
        0.0852337643,
        0.5842047508,
        0.3109124061,
        0.8940171362,
        0.6412378051,
        0.9455218136,
        0.7880687607,
        0.2636332642,
        0.1869768053,
        0.6517536691,
        0.9137707094,
        0.9281317706,
        0.5269326805,
        0.6258383121,
        0.1299404269,
        0.7331085226,
        0.5964183512,
        0.4944653544,
        0.4151498503,
        0.1815023392,
        0.0621891215,
        0.5988593667,
        0.6920898366,
        0.5219928171,
        0.2529071253,
        0.1591295504,
        0.5071416628,
        0.6335240912,
        0.5045890666,
        0.6020734545,
        0.1328208803,
        0.8721084816,
        0.1653388974,
        0.9785593627,
        0.4015488112,
        0.6336023652,
        0.6511391723,
        0.5311487252,
        0.9967931078,
        0.8299274566,
        0.9569348753,
        0.8791833892,
        0.2694185616,
        0.5792052438,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="dx", y="price"))
        + geom_line()
        + scale_x_date(breaks=breaks_width_date("2 weeks"))
        + theme_test()
        + labs(title='scale_x_date(breaks = breaks_width("2 weeks"))')
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-date"]
ci = true
title = "上游快照：scale_x_date(breaks = breaks_width(\"2 weeks\"))"
source = "upstream:tests/testthat/_snaps/scale_date/scale-x-date-breaks-breaks-width-2-weeks.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名；数据按 R 的 set.seed(321) 导出。"
""",
    },
    {
        "slug": "upstream-scale-date-scale-x-date-labels-label-date-m-d",
        "snapshot": "scale_date/scale-x-date-labels-label-date-m-d.svg",
        "title": '上游快照：scale_x_date(labels = label_date("%m/%d"))',
        "source": r'''"""上游快照复刻：scale_x_date(labels = label_date("%m/%d"))。

源：scale_date/scale-x-date-labels-label-date-m-d.svg。
vdiffr 名：scale_x_date(labels = label_date("%m/%d"))。

`set.seed(321)` 的 `dx` / `price` 由 R 4.5 直接导出
（`sample(100, 50)` + `runif(50)`），不是本仓生成的随机数。

expected.svg 是上游那份，未改写。
"""

import datetime

from ggcore.plot import aes, geom_line, ggplot, labs, scale_x_date
from ggcore.scales_date import date_formatter
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "dx": [
        datetime.date(2012, 2, 29),
        datetime.date(2012, 3, 3),
        datetime.date(2012, 3, 6),
        datetime.date(2012, 3, 7),
        datetime.date(2012, 3, 8),
        datetime.date(2012, 3, 10),
        datetime.date(2012, 3, 12),
        datetime.date(2012, 3, 14),
        datetime.date(2012, 3, 16),
        datetime.date(2012, 3, 17),
        datetime.date(2012, 3, 19),
        datetime.date(2012, 3, 22),
        datetime.date(2012, 3, 24),
        datetime.date(2012, 3, 28),
        datetime.date(2012, 3, 29),
        datetime.date(2012, 3, 30),
        datetime.date(2012, 4, 2),
        datetime.date(2012, 4, 3),
        datetime.date(2012, 4, 4),
        datetime.date(2012, 4, 9),
        datetime.date(2012, 4, 13),
        datetime.date(2012, 4, 14),
        datetime.date(2012, 4, 15),
        datetime.date(2012, 4, 16),
        datetime.date(2012, 4, 17),
        datetime.date(2012, 4, 19),
        datetime.date(2012, 4, 22),
        datetime.date(2012, 4, 26),
        datetime.date(2012, 4, 27),
        datetime.date(2012, 4, 28),
        datetime.date(2012, 4, 30),
        datetime.date(2012, 5, 1),
        datetime.date(2012, 5, 2),
        datetime.date(2012, 5, 5),
        datetime.date(2012, 5, 11),
        datetime.date(2012, 5, 13),
        datetime.date(2012, 5, 15),
        datetime.date(2012, 5, 16),
        datetime.date(2012, 5, 17),
        datetime.date(2012, 5, 18),
        datetime.date(2012, 5, 19),
        datetime.date(2012, 5, 20),
        datetime.date(2012, 5, 22),
        datetime.date(2012, 5, 26),
        datetime.date(2012, 5, 27),
        datetime.date(2012, 5, 28),
        datetime.date(2012, 5, 29),
        datetime.date(2012, 6, 3),
        datetime.date(2012, 6, 6),
        datetime.date(2012, 6, 7),
    ],
    "price": [
        0.9616501040,
        0.1624869567,
        0.0412904064,
        0.1565073295,
        0.5024147367,
        0.7918214588,
        0.0852337643,
        0.5842047508,
        0.3109124061,
        0.8940171362,
        0.6412378051,
        0.9455218136,
        0.7880687607,
        0.2636332642,
        0.1869768053,
        0.6517536691,
        0.9137707094,
        0.9281317706,
        0.5269326805,
        0.6258383121,
        0.1299404269,
        0.7331085226,
        0.5964183512,
        0.4944653544,
        0.4151498503,
        0.1815023392,
        0.0621891215,
        0.5988593667,
        0.6920898366,
        0.5219928171,
        0.2529071253,
        0.1591295504,
        0.5071416628,
        0.6335240912,
        0.5045890666,
        0.6020734545,
        0.1328208803,
        0.8721084816,
        0.1653388974,
        0.9785593627,
        0.4015488112,
        0.6336023652,
        0.6511391723,
        0.5311487252,
        0.9967931078,
        0.8299274566,
        0.9569348753,
        0.8791833892,
        0.2694185616,
        0.5792052438,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="dx", y="price"))
        + geom_line()
        + scale_x_date(labels=date_formatter("date", "%m/%d"))
        + theme_test()
        + labs(title='scale_x_date(labels = label_date("%m/%d"))')
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-date"]
ci = true
title = "上游快照：scale_x_date(labels = label_date(\"%m/%d\"))"
source = "upstream:tests/testthat/_snaps/scale_date/scale-x-date-labels-label-date-m-d.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名；数据按 R 的 set.seed(321) 导出。"
""",
    },
    {
        "slug": "upstream-scale-date-scale-x-date-labels-label-date-w-week",
        "snapshot": "scale_date/scale-x-date-labels-label-date-w-week.svg",
        "title": '上游快照：scale_x_date(labels = label_date("%W"), "week")',
        "source": r'''"""上游快照复刻：scale_x_date(labels = label_date("%W"), "week")。

源：scale_date/scale-x-date-labels-label-date-w-week.svg。
vdiffr 名：scale_x_date(labels = label_date("%W"), "week")。

`set.seed(321)` 的 `dx` / `price` 由 R 4.5 直接导出
（`sample(100, 50)` + `runif(50)`），不是本仓生成的随机数。

expected.svg 是上游那份，未改写。
"""

import datetime

from ggcore.plot import aes, geom_line, ggplot, labs, scale_x_date
from ggcore.scales_date import date_formatter
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "dx": [
        datetime.date(2012, 2, 29),
        datetime.date(2012, 3, 3),
        datetime.date(2012, 3, 6),
        datetime.date(2012, 3, 7),
        datetime.date(2012, 3, 8),
        datetime.date(2012, 3, 10),
        datetime.date(2012, 3, 12),
        datetime.date(2012, 3, 14),
        datetime.date(2012, 3, 16),
        datetime.date(2012, 3, 17),
        datetime.date(2012, 3, 19),
        datetime.date(2012, 3, 22),
        datetime.date(2012, 3, 24),
        datetime.date(2012, 3, 28),
        datetime.date(2012, 3, 29),
        datetime.date(2012, 3, 30),
        datetime.date(2012, 4, 2),
        datetime.date(2012, 4, 3),
        datetime.date(2012, 4, 4),
        datetime.date(2012, 4, 9),
        datetime.date(2012, 4, 13),
        datetime.date(2012, 4, 14),
        datetime.date(2012, 4, 15),
        datetime.date(2012, 4, 16),
        datetime.date(2012, 4, 17),
        datetime.date(2012, 4, 19),
        datetime.date(2012, 4, 22),
        datetime.date(2012, 4, 26),
        datetime.date(2012, 4, 27),
        datetime.date(2012, 4, 28),
        datetime.date(2012, 4, 30),
        datetime.date(2012, 5, 1),
        datetime.date(2012, 5, 2),
        datetime.date(2012, 5, 5),
        datetime.date(2012, 5, 11),
        datetime.date(2012, 5, 13),
        datetime.date(2012, 5, 15),
        datetime.date(2012, 5, 16),
        datetime.date(2012, 5, 17),
        datetime.date(2012, 5, 18),
        datetime.date(2012, 5, 19),
        datetime.date(2012, 5, 20),
        datetime.date(2012, 5, 22),
        datetime.date(2012, 5, 26),
        datetime.date(2012, 5, 27),
        datetime.date(2012, 5, 28),
        datetime.date(2012, 5, 29),
        datetime.date(2012, 6, 3),
        datetime.date(2012, 6, 6),
        datetime.date(2012, 6, 7),
    ],
    "price": [
        0.9616501040,
        0.1624869567,
        0.0412904064,
        0.1565073295,
        0.5024147367,
        0.7918214588,
        0.0852337643,
        0.5842047508,
        0.3109124061,
        0.8940171362,
        0.6412378051,
        0.9455218136,
        0.7880687607,
        0.2636332642,
        0.1869768053,
        0.6517536691,
        0.9137707094,
        0.9281317706,
        0.5269326805,
        0.6258383121,
        0.1299404269,
        0.7331085226,
        0.5964183512,
        0.4944653544,
        0.4151498503,
        0.1815023392,
        0.0621891215,
        0.5988593667,
        0.6920898366,
        0.5219928171,
        0.2529071253,
        0.1591295504,
        0.5071416628,
        0.6335240912,
        0.5045890666,
        0.6020734545,
        0.1328208803,
        0.8721084816,
        0.1653388974,
        0.9785593627,
        0.4015488112,
        0.6336023652,
        0.6511391723,
        0.5311487252,
        0.9967931078,
        0.8299274566,
        0.9569348753,
        0.8791833892,
        0.2694185616,
        0.5792052438,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="dx", y="price"))
        + geom_line()
        + scale_x_date(breaks="week", labels=date_formatter("date", "%W"))
        + theme_test()
        + labs(title='scale_x_date(labels = label_date("%W"), "week")')
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-date"]
ci = true
title = "上游快照：scale_x_date(labels = label_date(\"%W\"), \"week\")"
source = "upstream:tests/testthat/_snaps/scale_date/scale-x-date-labels-label-date-w-week.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名；数据按 R 的 set.seed(321) 导出。"
""",
    },
    {
        "slug": "upstream-scale-date-scale-y-date-breaks-3-weeks",
        "snapshot": "scale_date/scale-y-date-breaks-3-weeks.svg",
        "title": '上游快照：scale_y_date(breaks = "3 weeks")',
        "source": r'''"""上游快照复刻：scale_y_date(breaks = "3 weeks")。

源：scale_date/scale-y-date-breaks-3-weeks.svg。
vdiffr 名：scale_y_date(breaks = "3 weeks")。

`set.seed(321)` 的 `dx` / `price` 由 R 4.5 直接导出
（`sample(100, 50)` + `runif(50)`），不是本仓生成的随机数。

expected.svg 是上游那份，未改写。
"""

import datetime

from ggcore.plot import aes, geom_line, ggplot, labs, scale_y_date
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "dx": [
        datetime.date(2012, 2, 29),
        datetime.date(2012, 3, 3),
        datetime.date(2012, 3, 6),
        datetime.date(2012, 3, 7),
        datetime.date(2012, 3, 8),
        datetime.date(2012, 3, 10),
        datetime.date(2012, 3, 12),
        datetime.date(2012, 3, 14),
        datetime.date(2012, 3, 16),
        datetime.date(2012, 3, 17),
        datetime.date(2012, 3, 19),
        datetime.date(2012, 3, 22),
        datetime.date(2012, 3, 24),
        datetime.date(2012, 3, 28),
        datetime.date(2012, 3, 29),
        datetime.date(2012, 3, 30),
        datetime.date(2012, 4, 2),
        datetime.date(2012, 4, 3),
        datetime.date(2012, 4, 4),
        datetime.date(2012, 4, 9),
        datetime.date(2012, 4, 13),
        datetime.date(2012, 4, 14),
        datetime.date(2012, 4, 15),
        datetime.date(2012, 4, 16),
        datetime.date(2012, 4, 17),
        datetime.date(2012, 4, 19),
        datetime.date(2012, 4, 22),
        datetime.date(2012, 4, 26),
        datetime.date(2012, 4, 27),
        datetime.date(2012, 4, 28),
        datetime.date(2012, 4, 30),
        datetime.date(2012, 5, 1),
        datetime.date(2012, 5, 2),
        datetime.date(2012, 5, 5),
        datetime.date(2012, 5, 11),
        datetime.date(2012, 5, 13),
        datetime.date(2012, 5, 15),
        datetime.date(2012, 5, 16),
        datetime.date(2012, 5, 17),
        datetime.date(2012, 5, 18),
        datetime.date(2012, 5, 19),
        datetime.date(2012, 5, 20),
        datetime.date(2012, 5, 22),
        datetime.date(2012, 5, 26),
        datetime.date(2012, 5, 27),
        datetime.date(2012, 5, 28),
        datetime.date(2012, 5, 29),
        datetime.date(2012, 6, 3),
        datetime.date(2012, 6, 6),
        datetime.date(2012, 6, 7),
    ],
    "price": [
        0.9616501040,
        0.1624869567,
        0.0412904064,
        0.1565073295,
        0.5024147367,
        0.7918214588,
        0.0852337643,
        0.5842047508,
        0.3109124061,
        0.8940171362,
        0.6412378051,
        0.9455218136,
        0.7880687607,
        0.2636332642,
        0.1869768053,
        0.6517536691,
        0.9137707094,
        0.9281317706,
        0.5269326805,
        0.6258383121,
        0.1299404269,
        0.7331085226,
        0.5964183512,
        0.4944653544,
        0.4151498503,
        0.1815023392,
        0.0621891215,
        0.5988593667,
        0.6920898366,
        0.5219928171,
        0.2529071253,
        0.1591295504,
        0.5071416628,
        0.6335240912,
        0.5045890666,
        0.6020734545,
        0.1328208803,
        0.8721084816,
        0.1653388974,
        0.9785593627,
        0.4015488112,
        0.6336023652,
        0.6511391723,
        0.5311487252,
        0.9967931078,
        0.8299274566,
        0.9569348753,
        0.8791833892,
        0.2694185616,
        0.5792052438,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="price", y="dx"))
        + geom_line()
        + scale_y_date(date_breaks="3 weeks")
        + theme_test()
        + labs(title='scale_y_date(breaks = "3 weeks")')
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-date"]
ci = true
title = "上游快照：scale_y_date(breaks = \"3 weeks\")"
source = "upstream:tests/testthat/_snaps/scale_date/scale-y-date-breaks-3-weeks.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名；数据按 R 的 set.seed(321) 导出。"
""",
    },
    {
        "slug": "upstream-scale-date-scale-y-date-breaks-breaks-width-2-weeks",
        "snapshot": "scale_date/scale-y-date-breaks-breaks-width-2-weeks.svg",
        "title": '上游快照：scale_y_date(breaks = breaks_width("2 weeks"))',
        "source": r'''"""上游快照复刻：scale_y_date(breaks = breaks_width("2 weeks"))。

源：scale_date/scale-y-date-breaks-breaks-width-2-weeks.svg。
vdiffr 名：scale_y_date(breaks = breaks_width("2 weeks"))。

`set.seed(321)` 的 `dx` / `price` 由 R 4.5 直接导出
（`sample(100, 50)` + `runif(50)`），不是本仓生成的随机数。

expected.svg 是上游那份，未改写。
"""

import datetime

from ggcore.plot import aes, geom_line, ggplot, labs, scale_y_date
from ggcore.scales_date import breaks_width_date
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {
    "dx": [
        datetime.date(2012, 2, 29),
        datetime.date(2012, 3, 3),
        datetime.date(2012, 3, 6),
        datetime.date(2012, 3, 7),
        datetime.date(2012, 3, 8),
        datetime.date(2012, 3, 10),
        datetime.date(2012, 3, 12),
        datetime.date(2012, 3, 14),
        datetime.date(2012, 3, 16),
        datetime.date(2012, 3, 17),
        datetime.date(2012, 3, 19),
        datetime.date(2012, 3, 22),
        datetime.date(2012, 3, 24),
        datetime.date(2012, 3, 28),
        datetime.date(2012, 3, 29),
        datetime.date(2012, 3, 30),
        datetime.date(2012, 4, 2),
        datetime.date(2012, 4, 3),
        datetime.date(2012, 4, 4),
        datetime.date(2012, 4, 9),
        datetime.date(2012, 4, 13),
        datetime.date(2012, 4, 14),
        datetime.date(2012, 4, 15),
        datetime.date(2012, 4, 16),
        datetime.date(2012, 4, 17),
        datetime.date(2012, 4, 19),
        datetime.date(2012, 4, 22),
        datetime.date(2012, 4, 26),
        datetime.date(2012, 4, 27),
        datetime.date(2012, 4, 28),
        datetime.date(2012, 4, 30),
        datetime.date(2012, 5, 1),
        datetime.date(2012, 5, 2),
        datetime.date(2012, 5, 5),
        datetime.date(2012, 5, 11),
        datetime.date(2012, 5, 13),
        datetime.date(2012, 5, 15),
        datetime.date(2012, 5, 16),
        datetime.date(2012, 5, 17),
        datetime.date(2012, 5, 18),
        datetime.date(2012, 5, 19),
        datetime.date(2012, 5, 20),
        datetime.date(2012, 5, 22),
        datetime.date(2012, 5, 26),
        datetime.date(2012, 5, 27),
        datetime.date(2012, 5, 28),
        datetime.date(2012, 5, 29),
        datetime.date(2012, 6, 3),
        datetime.date(2012, 6, 6),
        datetime.date(2012, 6, 7),
    ],
    "price": [
        0.9616501040,
        0.1624869567,
        0.0412904064,
        0.1565073295,
        0.5024147367,
        0.7918214588,
        0.0852337643,
        0.5842047508,
        0.3109124061,
        0.8940171362,
        0.6412378051,
        0.9455218136,
        0.7880687607,
        0.2636332642,
        0.1869768053,
        0.6517536691,
        0.9137707094,
        0.9281317706,
        0.5269326805,
        0.6258383121,
        0.1299404269,
        0.7331085226,
        0.5964183512,
        0.4944653544,
        0.4151498503,
        0.1815023392,
        0.0621891215,
        0.5988593667,
        0.6920898366,
        0.5219928171,
        0.2529071253,
        0.1591295504,
        0.5071416628,
        0.6335240912,
        0.5045890666,
        0.6020734545,
        0.1328208803,
        0.8721084816,
        0.1653388974,
        0.9785593627,
        0.4015488112,
        0.6336023652,
        0.6511391723,
        0.5311487252,
        0.9967931078,
        0.8299274566,
        0.9569348753,
        0.8791833892,
        0.2694185616,
        0.5792052438,
    ],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="price", y="dx"))
        + geom_line()
        + scale_y_date(breaks=breaks_width_date("2 weeks"))
        + theme_test()
        + labs(title='scale_y_date(breaks = breaks_width("2 weeks"))')
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-date"]
ci = true
title = "上游快照：scale_y_date(breaks = breaks_width(\"2 weeks\"))"
source = "upstream:tests/testthat/_snaps/scale_date/scale-y-date-breaks-breaks-width-2-weeks.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名；数据按 R 的 set.seed(321) 导出。"
""",
    },
    {
        "slug": "upstream-scales-character",
        "snapshot": "scales-breaks-labels/character.svg",
        "title": "上游快照：character",
        "source": r'''"""上游快照复刻：character。

离散 x + `geom_blank()`。
源：scales-breaks-labels/character.svg。
vdiffr 名：character。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_blank, ggplot, labs
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x_num": [1, 3],
    "x_chr": ["a", "b"],
    "x_date": ["2012-02-29", "2012-06-08"],
    "x_log": [1, 1e4],
    "y": [1, 3],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x_chr", y="y"))
        + geom_blank()
        + theme_test()
        + theme(
            **{
                "panel.grid.major": element_line(colour="grey30", linewidth=0.5),
                "panel.grid.minor": element_line(colour="grey70"),
            }
        )
        + labs(x=None, y=None, title="character")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：character"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/character.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-date",
        "snapshot": "scales-breaks-labels/date.svg",
        "title": "上游快照：date",
        "source": r'''"""上游快照复刻：date。

月主断点 / 周次断点 + `label_date("%m/%d")`。
源：scales-breaks-labels/date.svg。
vdiffr 名：date。

expected.svg 是上游那份，未改写。
"""

import datetime as _dt

from ggcore.plot import aes, geom_blank, ggplot, labs, scale_x_date
from ggcore.scales_date import breaks_width_date, date_formatter
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x_num": [1, 3],
    "x_chr": ["a", "b"],
    "x_date": [_dt.date(2012, 2, 29), _dt.date(2012, 6, 8)],
    "x_log": [1, 1e4],
    "y": [1, 3],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x_date", y="y"))
        + geom_blank()
        + scale_x_date(
            labels=date_formatter("date", "%m/%d"),
            breaks=breaks_width_date("1 month"),
            minor_breaks=breaks_width_date("1 week"),
        )
        + theme_test()
        + theme(
            **{
                "panel.grid.major": element_line(colour="grey30", linewidth=0.5),
                "panel.grid.minor": element_line(colour="grey70"),
            }
        )
        + labs(x=None, y=None, title="date")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：date"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/date.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-functional-limits",
        "snapshot": "scales-breaks-labels/functional-limits.svg",
        "title": "上游快照：functional limits",
        "source": r'''"""上游快照复刻：functional limits。

`scale_y_continuous(limits = <function>)`。
源：scales-breaks-labels/functional-limits.svg。
vdiffr 名：functional limits。

expected.svg 是上游那份，未改写。
"""

import math

from ggcore.plot import aes, geom_bar, ggplot, labs, scale_y_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

#: `mpg` 的 `class × drv` 计数（只保留本图用到的两列；数据 = 234 行）。
COUNTS = {
    "2seater": {"r": 5},
    "compact": {"4": 12, "f": 35},
    "midsize": {"4": 3, "f": 38},
    "minivan": {"f": 11},
    "pickup": {"4": 33},
    "subcompact": {"4": 4, "f": 22, "r": 9},
    "suv": {"4": 51, "r": 11},
}
DRIVES = ("4", "f", "r")
DATA = {
    "class": [cls for cls, row in COUNTS.items() for drv in DRIVES for _ in range(row.get(drv, 0))],
    "drv": [drv for cls, row in COUNTS.items() for drv in DRIVES for _ in range(row.get(drv, 0))],
}


def _limiter(by):
    def limits(values):
        low, high = values
        return (math.floor(low / by) * by, math.ceil(high / by) * by)

    return limits


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="class"))
        + geom_bar(aes(fill="drv"))
        + scale_y_continuous(limits=_limiter(50))
        + theme_test()
        + labs(title="functional limits")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：functional limits"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/functional-limits.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-no-alpha-breaks",
        "snapshot": "scales-breaks-labels/no-alpha-breaks-no-legend.svg",
        "title": "上游快照：no alpha breaks (no legend)",
        "source": r'''"""上游快照复刻：no alpha breaks (no legend)。

`scale_alpha_continuous(breaks = NULL)` → 无图例。
源：scales-breaks-labels/no-alpha-breaks-no-legend.svg。
vdiffr 名：no alpha breaks (no legend)。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_alpha_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x=1, y="y", alpha="x"))
        + geom_point()
        + scale_alpha_continuous(breaks=None)
        + theme_test()
        + labs(title="no alpha breaks (no legend)")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：no alpha breaks (no legend)"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/no-alpha-breaks-no-legend.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-no-colour-breaks",
        "snapshot": "scales-breaks-labels/no-colour-breaks-no-legend.svg",
        "title": "上游快照：no colour breaks (no legend)",
        "source": r'''"""上游快照复刻：no colour breaks (no legend)。

`scale_colour_continuous(breaks = NULL)` → 无图例。
源：scales-breaks-labels/no-colour-breaks-no-legend.svg。
vdiffr 名：no colour breaks (no legend)。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_colour_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x=1, y="y", colour="x"))
        + geom_point()
        + scale_colour_continuous(breaks=None)
        + theme_test()
        + labs(title="no colour breaks (no legend)")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：no colour breaks (no legend)"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/no-colour-breaks-no-legend.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-no-fill-breaks",
        "snapshot": "scales-breaks-labels/no-fill-breaks-no-legend.svg",
        "title": "上游快照：no fill breaks (no legend)",
        "source": r'''"""上游快照复刻：no fill breaks (no legend)。

`scale_fill_continuous(breaks = NULL)` → 无图例。
源：scales-breaks-labels/no-fill-breaks-no-legend.svg。
vdiffr 名：no fill breaks (no legend)。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_fill_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x=1, y="y", fill="x"))
        + geom_point(shape=21)
        + scale_fill_continuous(breaks=None)
        + theme_test()
        + labs(title="no fill breaks (no legend)")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：no fill breaks (no legend)"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/no-fill-breaks-no-legend.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-no-size-breaks",
        "snapshot": "scales-breaks-labels/no-size-breaks-no-legend.svg",
        "title": "上游快照：no size breaks (no legend)",
        "source": r'''"""上游快照复刻：no size breaks (no legend)。

`scale_size_continuous(breaks = NULL)` → 无图例。
源：scales-breaks-labels/no-size-breaks-no-legend.svg。
vdiffr 名：no size breaks (no legend)。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_size_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x=1, y="y", size="x"))
        + geom_point()
        + scale_size_continuous(breaks=None)
        + theme_test()
        + labs(title="no size breaks (no legend)")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：no size breaks (no legend)"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/no-size-breaks-no-legend.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-no-x-breaks",
        "snapshot": "scales-breaks-labels/no-x-breaks.svg",
        "title": "上游快照：no x breaks",
        "source": r'''"""上游快照复刻：no x breaks。

`scale_x_continuous(breaks = NULL)`。
源：scales-breaks-labels/no-x-breaks.svg。
vdiffr 名：no x breaks。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_x_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + scale_x_continuous(breaks=None)
        + theme_test()
        + labs(title="no x breaks")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：no x breaks"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/no-x-breaks.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-no-y-breaks",
        "snapshot": "scales-breaks-labels/no-y-breaks.svg",
        "title": "上游快照：no y breaks",
        "source": r'''"""上游快照复刻：no y breaks。

`scale_y_continuous(breaks = NULL)`。
源：scales-breaks-labels/no-y-breaks.svg。
vdiffr 名：no y breaks。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_point, ggplot, labs, scale_y_continuous
from ggcore.theme import theme_test
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [1, 2, 3]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + scale_y_continuous(breaks=None)
        + theme_test()
        + labs(title="no y breaks")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：no y breaks"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/no-y-breaks.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-numeric",
        "snapshot": "scales-breaks-labels/numeric.svg",
        "title": "上游快照：numeric",
        "source": r'''"""上游快照复刻：numeric。

主 / 次网格线 + 显式断点。
源：scales-breaks-labels/numeric.svg。
vdiffr 名：numeric。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import (
    aes,
    geom_blank,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x_num": [1, 3],
    "x_chr": ["a", "b"],
    "x_date": ["2012-02-29", "2012-06-08"],
    "x_log": [1, 1e4],
    "y": [1, 3],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x_num", y="y"))
        + geom_blank()
        + scale_x_continuous(breaks=(1, 2, 3), minor_breaks=(1.25, 2.75))
        + scale_y_continuous(breaks=(1, 2, 3), minor_breaks=(1.25, 2.75))
        + theme_test()
        + theme(
            **{
                "panel.grid.major": element_line(colour="grey30", linewidth=0.5),
                "panel.grid.minor": element_line(colour="grey70"),
            }
        )
        + labs(x=None, y=None, title="numeric")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：numeric"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/numeric.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-numeric-exp",
        "snapshot": "scales-breaks-labels/numeric-exp.svg",
        "title": "上游快照：numeric-exp",
        "source": r'''"""上游快照复刻：numeric-exp。

x / y 都走 `transform_exp(2)`。
源：scales-breaks-labels/numeric-exp.svg。
vdiffr 名：numeric-exp。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import aes, geom_blank, ggplot, labs, scale_x_continuous, scale_y_continuous
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x_num": [1, 3],
    "x_chr": ["a", "b"],
    "x_date": ["2012-02-29", "2012-06-08"],
    "x_log": [1, 1e4],
    "y": [1, 3],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x_num", y="x_num"))
        + geom_blank()
        + scale_x_continuous(trans=("exp", 2))
        + scale_y_continuous(trans=("exp", 2))
        + theme_test()
        + theme(
            **{
                "panel.grid.major": element_line(colour="grey30", linewidth=0.5),
                "panel.grid.minor": element_line(colour="grey70"),
            }
        )
        + labs(x=None, y=None, title="numeric-exp")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：numeric-exp"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/numeric-exp.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-numeric-log",
        "snapshot": "scales-breaks-labels/numeric-log.svg",
        "title": "上游快照：numeric log",
        "source": r'''"""上游快照复刻：numeric log。

x 走 log2、y 走 log10。
源：scales-breaks-labels/numeric-log.svg。
vdiffr 名：numeric log。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import (
    aes,
    geom_blank,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_log10,
)
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x_num": [1, 3],
    "x_chr": ["a", "b"],
    "x_date": ["2012-02-29", "2012-06-08"],
    "x_log": [1, 1e4],
    "y": [1, 3],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x_log", y="x_log"))
        + geom_blank()
        + scale_x_continuous(trans="log2")
        + scale_y_log10()
        + theme_test()
        + theme(
            **{
                "panel.grid.major": element_line(colour="grey30", linewidth=0.5),
                "panel.grid.minor": element_line(colour="grey70"),
            }
        )
        + labs(x=None, y=None, title="numeric-log")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：numeric log"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/numeric-log.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
    {
        "slug": "upstream-scales-numeric-polar",
        "snapshot": "scales-breaks-labels/numeric-polar.svg",
        "title": "上游快照：numeric-polar",
        "source": r'''"""上游快照复刻：numeric-polar。

同一张图 + `coord_polar()`。
源：scales-breaks-labels/numeric-polar.svg。
vdiffr 名：numeric-polar。

expected.svg 是上游那份，未改写。
"""

from ggcore.plot import (
    aes,
    coord_polar,
    geom_blank,
    ggplot,
    labs,
    scale_x_continuous,
    scale_y_continuous,
)
from ggcore.theme import element_line, theme, theme_test
from ggio.frame import to_column_table

DATA = {
    "x_num": [1, 3],
    "x_chr": ["a", "b"],
    "x_date": ["2012-02-29", "2012-06-08"],
    "x_log": [1, 1e4],
    "y": [1, 3],
}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x_num", y="y"))
        + geom_blank()
        + scale_x_continuous(breaks=(1, 2, 3), minor_breaks=(1.25, 2.75))
        + scale_y_continuous(breaks=(1, 2, 3), minor_breaks=(1.25, 2.75))
        + theme_test()
        + theme(
            **{
                "panel.grid.major": element_line(colour="grey30", linewidth=0.5),
                "panel.grid.minor": element_line(colour="grey70"),
            }
        )
        + labs(x=None, y=None)
        + coord_polar()
        + labs(title="numeric-polar")
    )
    return {"plot": p, "size": [10, 8]}
''',
        "meta": r"""family = "scale"
features = ["scale-breaks"]
ci = true
title = "上游快照：numeric-polar"
source = "upstream:tests/testthat/_snaps/scales-breaks-labels/numeric-polar.svg"
tolerance = { png = 0.02 }
notes = "SIL-790：vdiffr 快照原样纳入；标题是 doppelganger 名。"
""",
    },
]

#: G4（SIL-794）：`geom-violin` 14 条 + `geom-raster` 12 条。
#:
#: 两个簇的图都来自 `test-geom-violin.R` / `test-geom-raster.R` 的
#: `expect_doppelganger()`，口径是 vdiffr 的默认（`theme_test()`、10 × 8 in）。
#: violin 的数据是 `set.seed(111)` 之后**连续**抽的两段 `rnorm(90)`——第二段接着
#: 第一段的 RNG 流，不能重新播种；raster 的数据是确定的。
_VIOLIN_Y1 = [
    0.2352207116136979,
    -0.33073587162669138,
    -0.31162382397876148,
    -2.3023456584293767,
    -0.17087604461386502,
    0.14027822510323076,
    -1.4974266555651168,
    -1.010188419051379,
    -0.94847560495244698,
    -0.49396221723510808,
    -0.17367412797058035,
    -0.40659878004065225,
    1.8456362638070769,
    0.39405410997450147,
    0.7975285012615172,
    -1.5666653601855778,
    -0.085851008822606156,
    -0.35913948123778322,
    -1.1936089665637317,
    0.3641867370222206,
    0.36166245158827537,
    0.3469643701135664,
    0.18973652668927543,
    -0.15957680553877868,
    0.32654923843186656,
    0.5982542023934897,
    -1.8415343000624469,
    2.7180555995417524,
    0.19124439045729366,
    -1.3012960652783192,
    -3.1132173012951165,
    -0.94135739527933993,
    1.4002587816673546,
    -1.6204700283490798,
    -2.265995957106016,
    1.1629935891806336,
    -0.11615504069648808,
    0.33425600937476491,
    -0.62085810636913807,
    -1.3098449084808674,
    -1.1757260417049971,
    -1.1212155328138087,
    -1.3619044836547853,
    0.48112457846871437,
    0.74197162553291085,
    0.027824625215327498,
    0.33137971081842127,
    0.64411413199137724,
    2.4856615614379654,
    1.9599817076962347,
    0.19166338489197002,
    1.5525442721051541,
    0.914242286889689,
    0.35862537480139478,
    0.175095636090836,
    -0.84726776895397149,
    0.97823165740086415,
    1.8058682591488724,
    0.12291480235291645,
    -0.1297720262758997,
    -0.21642865914933687,
    1.4464781673502374,
    0.40970980155600101,
    0.91091657198872822,
    1.4303581665751275,
    -0.38129195562227353,
    0.20230717688131547,
    -0.80619919408145113,
    0.29463418370697519,
    1.4048830831206927,
    1.0237668464541809,
    0.47612606448547196,
    -0.67033032989887575,
    0.15923432120867573,
    -0.38271538313402881,
    0.9357625932445246,
    -0.63153226774163385,
    -0.098306077478636358,
    1.0319849831198364,
    0.3878084294579055,
    -1.2561293133373184,
    -0.7869527300902347,
    0.42981154866788385,
    -0.37641621920596979,
    -1.2162290663652151,
    1.0292785141184106,
    0.43039699902490719,
    -1.2455740200933809,
    -0.60272848648728317,
    0.66006938738224785,
]

_VIOLIN_Y2 = [
    2.0507495261136075,
    0.49080817881842581,
    -1.7314794187800149,
    0.71088365940818043,
    0.013822911462220842,
    -1.4010415973662063,
    1.2591236654416733,
    -0.12747751837564192,
    -0.72938651365146534,
    -1.2113613602100406,
    0.59961974484182734,
    -1.1603295272202521,
    0.43909343443560167,
    0.20485373663196663,
    -0.69918134010149835,
    -0.92662567667307771,
    -1.0134823752407285,
    0.6049870597715532,
    1.734400132788088,
    -0.3498505306375837,
    1.1991855088291656,
    1.0239009980506748,
    -0.046275149345726269,
    1.3865084257746001,
    -2.1952727189392696,
    -0.12755691295972088,
    -1.3169968418775473,
    -1.426935140776123,
    0.87944163077744786,
    0.3939915750615513,
    0.68892548380832375,
    2.3537165014781198,
    -1.0150976714256845,
    0.29097752030343998,
    1.5653260791163035,
    -0.8471183683926844,
    1.3276601582188632,
    0.47704633129749491,
    0.1852509367019981,
    0.25329488826917751,
    2.5922273505980837,
    1.0743469927976015,
    -1.5969018923284333,
    -0.087588596342839956,
    0.36076759047357126,
    -0.87995998139024934,
    -3.323334964637354,
    -0.46751545310407377,
    0.43154026568606418,
    -0.60398945383959857,
    0.67444669272786928,
    0.63592053581511487,
    -0.61297038759660016,
    0.41489134542087347,
    0.87734337263099016,
    0.021157582615034556,
    1.8103832947141232,
    -0.45209570417603312,
    -0.12512398552467086,
    0.76680041643095487,
    -0.091520260917946933,
    -1.8743058094967706,
    -0.66416201764243754,
    0.20341281786445098,
    -2.5944433933631905,
    -0.093733931432688405,
    -0.42731991750985981,
    0.44297927707369894,
    -1.1878079253766662,
    0.62642547340094923,
    0.36164660142629207,
    -0.47296057907429301,
    0.94489370229113456,
    0.90640224753217669,
    0.47177370465355117,
    0.38949993045205211,
    0.52194026734166332,
    0.90445283980168634,
    1.6967909263582432,
    -0.88433743533715903,
    0.85648970146977699,
    0.1749424505741527,
    -0.39850496200257007,
    0.27520256239410407,
    -1.2687187990691433,
    -0.010081328985713329,
    0.65340172450247769,
    0.098579979494000658,
    0.90261694132495107,
    -0.51989749588921874,
]


def _violin_data_source() -> str:
    return "\n".join(
        [
            f"Y1 = {_literal(_VIOLIN_Y1)}",
            f"Y2 = {_literal(_VIOLIN_Y2)}",
            "",
            '_X = ["A", "B", "C"] * 30',
            '# R: dat[dat$x != "C" | c(TRUE, FALSE), ] —— C 组只留一半（30 → 15 行）。',
            '_KEEP = [index for index in range(90) if _X[index] != "C" or index % 2 == 0]',
            "DAT = {",
            '    "x": [_X[index] for index in _KEEP],',
            '    "y": [Y1[index] for index in _KEEP],',
            "    # R: as.numeric(x)：离散水平 1/2/3，三组等量 → 连续轴上的中心落在 2.0。",
            '    "xn": [float("ABC".index(_X[index]) + 1) for index in _KEEP],',
            '    "foo": ["foo"] * len(_KEEP),',
            "}",
            "DAT2 = {",
            '    "x": _X,',
            '    "y": Y2,',
            '    "g": ["e", "f"] * 45,',
            '    "foo": ["foo"] * 90,',
            "}",
        ]
    )


def _violin_source(*, table: str, mapping: str, layers: list[str], title: str) -> str:
    body = "\n".join(f"        + {layer}" for layer in layers)
    optional = [
        name
        for name in ("coord_flip", "coord_polar", "geom_point", "position_dodge")
        if f"{name}(" in body
    ]
    names = sorted(["aes", "geom_violin", "ggplot", "labs", *optional])
    return (
        "\n".join(
            [
                "from ggcore.plot import (",
                *[f"    {name}," for name in names],
                ")",
                "from ggcore.theme import theme_test",
                "from ggio.frame import to_column_table",
                "",
                _violin_data_source(),
                "",
                "",
                "def build():",
                "    p = (",
                f"        ggplot(to_column_table({table}), {mapping})",
                body,
                "        + theme_test()",
                f'        + labs(title="{title}")',
                "    )",
                '    return {"plot": p, "size": [10, 8]}',
            ]
        )
        + "\n"
    )


def _violin_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []

    def add(
        slug: str,
        snapshot: str,
        title: str,
        mapping: str,
        layers: list[str],
        features: list[str],
        *,
        table: str = "DAT",
    ) -> None:
        specs.append(
            {
                "slug": slug,
                "snapshot": f"geom-violin/{snapshot}.svg",
                "title": title,
                "family": "geom-violin",
                "features": features,
                "notes": (
                    "SIL-794：vdiffr 快照原样纳入；标题是 doppelganger 名，"
                    "主题是 vdiffr 的 theme_test()。"
                ),
                "source": _violin_source(table=table, mapping=mapping, layers=layers, title=title),
            }
        )

    add(
        "upstream-geom-violin-basic",
        "basic",
        "basic",
        'aes(x="x", y="y")',
        ["geom_violin()"],
        ["aes-mapping", "stat-ydensity"],
    )
    add(
        "upstream-geom-violin-scale-area-to-sample-size",
        "scale-area-to-sample-size-c-is-smaller",
        "scale area to sample size (C is smaller)",
        'aes(x="x", y="y")',
        ['geom_violin(scale="count")'],
        ["aes-mapping", "stat-ydensity"],
    )
    add(
        "upstream-geom-violin-narrower-width",
        "narrower-width-5",
        "narrower (width=.5)",
        'aes(x="x", y="y")',
        ["geom_violin(width=0.5)"],
        ["aes-mapping", "stat-ydensity"],
    )
    add(
        "upstream-geom-violin-with-tails-and-points",
        "with-tails-and-points",
        "with tails and points",
        'aes(x="x", y="y")',
        ["geom_violin(trim=False)", "geom_point(shape=21)"],
        ["aes-mapping", "stat-ydensity", "shape-aes"],
    )
    add(
        "upstream-geom-violin-with-smaller-bandwidth-and-points",
        "with-smaller-bandwidth-and-points",
        "with smaller bandwidth and points",
        'aes(x="x", y="y")',
        ["geom_violin(adjust=0.3)", "geom_point(shape=21)"],
        ["aes-mapping", "stat-ydensity", "shape-aes"],
    )
    add(
        "upstream-geom-violin-dodging",
        "dodging",
        "dodging",
        'aes(x="foo", y="y", fill="x")',
        ["geom_violin()"],
        ["aes-mapping", "aes-grouping", "position-dodge"],
    )
    add(
        "upstream-geom-violin-coord-polar",
        "coord-polar",
        "coord_polar",
        'aes(x="x", y="y")',
        ["geom_violin()", "coord_polar()"],
        ["aes-mapping", "coord-polar"],
    )
    add(
        "upstream-geom-violin-coord-flip",
        "coord-flip",
        "coord_flip",
        'aes(x="x", y="y")',
        ["geom_violin()", "coord_flip()"],
        ["aes-mapping", "coord-flip"],
    )
    add(
        "upstream-geom-violin-dodging-and-coord-flip",
        "dodging-and-coord-flip",
        "dodging and coord_flip",
        'aes(x="foo", y="y", fill="x")',
        ["geom_violin()", "coord_flip()"],
        ["aes-mapping", "aes-grouping", "position-dodge", "coord-flip"],
    )
    add(
        "upstream-geom-violin-continuous-x-axis-many-groups",
        "continuous-x-axis-many-groups-center-should-be-at-2-0",
        "continuous x axis, many groups (center should be at 2.0)",
        'aes(x="xn", y="y")',
        ["geom_violin()"],
        ["aes-mapping", "stat-ydensity"],
    )
    add(
        "upstream-geom-violin-continuous-x-axis-single-group",
        "continuous-x-axis-single-group-center-should-be-at-1-0",
        "continuous x axis, single group (center should be at 1.0)",
        'aes(x=1, y="y")',
        ["geom_violin()"],
        ["aes-mapping", "stat-ydensity"],
    )
    add(
        "upstream-geom-violin-styled-quantiles",
        "styled-quantiles",
        "styled quantiles",
        'aes(x="x", y="y")',
        [
            "geom_violin(**{"
            '"quantile.colour": "red", '
            '"quantile.linetype": "dotted", '
            '"quantile.linewidth": 2})'
        ],
        ["aes-mapping", "stat-ydensity"],
    )
    add(
        "upstream-geom-violin-grouping-on-x-and-fill",
        "grouping-on-x-and-fill",
        "grouping on x and fill",
        'aes(x="x", y="y", fill="g")',
        ["geom_violin()"],
        ["aes-mapping", "aes-grouping", "position-dodge"],
        table="DAT2",
    )
    add(
        "upstream-geom-violin-grouping-on-x-and-fill-dodge-width",
        "grouping-on-x-and-fill-dodge-width-0-5",
        "grouping on x and fill, dodge width = 0.5",
        'aes(x="x", y="y", fill="g")',
        ["geom_violin(position=position_dodge(width=0.5))"],
        ["aes-mapping", "aes-grouping", "position-dodge"],
        table="DAT2",
    )
    return specs


def _raster_source(
    *,
    data: str,
    layers: list[str],
    title: str,
    ordered_fill: bool = False,
    fill_label: str | None = None,
) -> str:
    body = "\n".join(f"        + {layer}" for layer in layers)
    optional = [
        name
        for name in ("coord_polar", "geom_point", "scale_x_continuous", "scale_y_continuous")
        if f"{name}(" in body
    ]
    names = sorted(["aes", "geom_raster", "ggplot", "labs", *optional])
    # `interaction(x, y)` 的水平顺序是 x 变化最快（A.C / B.C / A.D / B.D），不是
    # 字典序；这条 case 用显式的 categorical 列把等级顺序钉成 R 的那一份。
    header: list[str] = []
    if ordered_fill:
        header.extend(["import numpy as np", "", "from ggcore.data import Column, ColumnTable"])
    header.extend(
        [
            "from ggcore.plot import (",
            *[f"    {name}," for name in names],
            ")",
            "from ggcore.theme import theme_test",
            "from ggio.frame import to_column_table",
        ]
    )
    return (
        "\n".join(
            [
                *header,
                "",
                data,
                "",
                "",
                "def build():",
                "    p = (",
                '        ggplot(to_column_table(DATA), aes(x="x", y="y", fill="z"))',
                body,
                "        + theme_test()",
                (
                    f'        + labs(title="{title}")'
                    if fill_label is None
                    else f'        + labs(title="{title}", fill="{fill_label}")'
                ),
                "    )",
                '    return {"plot": p, "size": [10, 8]}',
            ]
        )
        + "\n"
    )


#: `test-geom-raster.R` 的三份小矩阵（3×2 / 1×3 / 3×1，行序 = R 的 `data_frame`）。
_RASTER_MATRIX_32 = (
    "DATA = {\n"
    '    "x": [-1.0, -1.0, -1.0, 1.0, 1.0, 1.0],\n'
    '    "y": [-1.0, 0.0, 1.0, -1.0, 0.0, 1.0],\n'
    '    "z": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],\n'
    "}"
)
_RASTER_MATRIX_13 = (
    'DATA = {\n    "x": [-1.0, 0.0, 1.0],\n    "y": [0.0, 0.0, 0.0],\n    "z": [1.0, 2.0, 3.0],\n}'
)
_RASTER_MATRIX_31 = (
    'DATA = {\n    "x": [0.0, 0.0, 0.0],\n    "y": [-1.0, 0.0, 1.0],\n    "z": [1.0, 2.0, 3.0],\n}'
)
_RASTER_IRREGULAR = (
    "# R: expand.grid(x = 1:10, y = 1:10) —— 第一个变量 x 变化最快。\n"
    "_X = [value for _ in range(10) for value in range(1, 11)]\n"
    "_Y = [value for value in range(1, 11) for _ in range(10)]\n"
    "_COL = []\n"
    "for _x, _y in zip(_X, _Y, strict=True):\n"
    "    _value = (_x + _y) % 2\n"
    "    if (_x == 5 and _value == 1) or (_y == 5 and _value == 0):\n"
    "        _COL.append(None)\n"
    "    else:\n"
    "        _COL.append(str(_value))\n"
    'DATA = {"x": _X, "y": _Y, "z": _COL}'
)
_RASTER_DISCRETE = (
    "# R: expand.grid(x = c('A', 'B'), y = c('C', 'D'))，fill = interaction(x, y)。\n"
    "# interaction() 的水平顺序是 x 变化最快，所以等级是 A.C / B.C / A.D / B.D。\n"
    '_LEVELS = ("A.C", "B.C", "A.D", "B.D")\n'
    "DATA = ColumnTable(\n"
    "    [\n"
    '        ("x", Column("str", np.array(["A", "B", "A", "B"]))),\n'
    '        ("y", Column("str", np.array(["C", "C", "D", "D"]))),\n'
    '        ("z", Column("categorical", np.array([0, 1, 2, 3], dtype=np.int32),'
    " levels=_LEVELS)),\n"
    "    ]\n"
    ")"
)


def _raster_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []

    def add(
        slug: str,
        snapshot: str,
        title: str,
        data: str,
        layers: list[str],
        features: list[str],
        *,
        fill: str = 'fill="z"',
        ordered_fill: bool = False,
        fill_label: str | None = None,
    ) -> None:
        source = _raster_source(
            data=data,
            layers=layers,
            title=title,
            ordered_fill=ordered_fill,
            fill_label=fill_label,
        )
        source = source.replace('aes(x="x", y="y", fill="z")', f'aes(x="x", y="y", {fill})')
        specs.append(
            {
                "slug": slug,
                "snapshot": f"geom-raster/{snapshot}.svg",
                "title": title,
                "family": "geom-raster",
                "features": features,
                "notes": (
                    "SIL-794：vdiffr 快照原样纳入；标题是 doppelganger 名，"
                    "主题是 vdiffr 的 theme_test()。"
                ),
                "source": source,
            }
        )

    points = ["geom_raster()", 'geom_point(colour="red")']
    for slug, snapshot, title, matrix in (
        ("3-x-2", "3-x-2", "3 x 2", _RASTER_MATRIX_32),
        ("1-x-3", "1-x-3", "1 x 3", _RASTER_MATRIX_13),
        ("3-x-1", "3-x-1", "3 x 1", _RASTER_MATRIX_31),
    ):
        add(
            f"upstream-geom-raster-{slug}",
            snapshot,
            title,
            matrix,
            points,
            ["aes-mapping"],
        )
        add(
            f"upstream-geom-raster-{slug}-set-limits",
            f"{snapshot}-set-limits",
            f"{title}, set limits",
            matrix,
            [
                *points,
                "scale_x_continuous(limits=(-2, 2))",
                "scale_y_continuous(limits=(-2, 2))",
            ],
            ["aes-mapping", "scale-limits"],
        )
        add(
            f"upstream-geom-raster-{slug}-just-0-0",
            f"{snapshot}-just-0-0",
            f"{title}, just = (0, 0)",
            matrix,
            ["geom_raster(hjust=0, vjust=0)", 'geom_point(colour="red")'],
            ["aes-mapping"],
        )

    add(
        "upstream-geom-raster-rectangle-fallback",
        "rectangle-fallback",
        "rectangle fallback",
        (
            "# 非线性的 coord_polar() 下 geom_raster 降级成矩形（R 侧 suppressMessages）。\n"
            'DATA = {"x": [1.0, 2.0, 1.0, 2.0], "y": [1.0, 1.0, 2.0, 2.0],'
            ' "z": ["A", "B", "C", "D"]}'
        ),
        ["geom_raster()", "coord_polar()"],
        ["aes-mapping", "coord-polar", "scale-discrete"],
    )
    add(
        "upstream-geom-raster-irregular-categorical",
        "irregular-categorical",
        "irregular categorical",
        _RASTER_IRREGULAR,
        ["geom_raster()"],
        ["aes-mapping", "scale-discrete"],
        fill='fill="z"',
        fill_label="factor(col)",
    )
    add(
        "upstream-geom-raster-discrete-positions",
        "discrete-positions",
        "discrete positions",
        _RASTER_DISCRETE,
        ["geom_raster()"],
        ["aes-mapping", "scale-discrete"],
        ordered_fill=True,
        fill_label="interaction(x, y)",
    )
    return specs


_PLOT_NAMES = (
    "aes",
    "coord_flip",
    "facet_grid",
    "facet_wrap",
    "geom_dotplot",
    "geom_hline",
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
    if "source" in spec:
        return _ruff_format(spec["source"])
    body = spec["body"]
    plot_imports = [name for name in _PLOT_NAMES if f"{name}(" in body or f'"{name}"' in body]
    theme_imports = [f"theme_{name}" for name in _THEME_NAMES if f"theme_{name}(" in body]
    element_imports = [name for name in _ELEMENT_NAMES if f"{name}(" in body]
    lines = [
        '"""上游快照复刻。',
        "",
        *textwrap.wrap(
            f"源：{spec['snapshot']}（vdiffr 名 {spec['title']!r}）。",
            width=96,
        ),
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
    return "\n".join(lines) + "\n"


def _meta_source(spec: dict[str, Any]) -> str:
    # G6 的条目直接给 `meta` 正文，原样落盘（族 / 特性 / tolerance 各簇自己定）。
    if "meta" in spec:
        return spec["meta"]
    # G1a（SIL-788）/ G3（SIL-792）的条目直接给 `source`（完整 plot.py 正文）；
    # dotplot 族也带 `features`，所以判别键必须是 `source`，不能用 `features`。
    if "source" in spec:
        family = spec.get("family", "guide")
        notes = spec.get("notes", "SIL-788：vdiffr 快照原样纳入；标题是 doppelganger 名。")
        return (
            f'family = "{family}"\n'
            f"features = {json.dumps(spec['features'])}\n"
            "ci = true\n"
            f'title = "上游快照：{spec["title"]}"\n'
            f'source = "upstream:tests/testthat/_snaps/{spec["snapshot"]}"\n'
            "tolerance = { png = 0.02 }\n"
            f"notes = {json.dumps(notes, ensure_ascii=False)}\n"
        )
    family = spec["snapshot"].split("/")[0]
    family = spec.get("family", family)
    if family == "geom-dotplot":
        features = spec.get("features", ["aes-mapping", "stat-bindot"])
        notes = spec.get(
            "notes",
            "SIL-787：vdiffr 快照原样纳入；标题是 doppelganger 名，主题是 vdiffr 的 theme_test()。",
        )
        return (
            f'family = "{family}"\n'
            f"features = {json.dumps(features)}\n"
            "ci = true\n"
            f'title = "上游快照：{spec["title"]}"\n'
            f'source = "upstream:tests/testthat/_snaps/{spec["snapshot"]}"\n'
            "tolerance = { png = 0.02 }\n"
            f'notes = "{notes}"\n'
        )
    family = "guides" if family == "guides" else "theme"
    if family == "guides":
        facet = "facet-grid" if "facet-grid" in spec["slug"] else "facet-wrap"
        features = ["aes-mapping", facet, f"legend-{spec['title'].rsplit(' ', 1)[-1]}"]
    else:
        features = spec.get(
            "features", ["aes-mapping", "facet-wrap", "legend-right", f"theme-{spec['title']}"]
        )
    return (
        f'family = "{family}"\n'
        f"features = {json.dumps(features)}\n"
        "ci = true\n"
        f'title = "上游快照：{spec["title"]}"\n'
        f'source = "upstream:tests/testthat/_snaps/{spec["snapshot"]}"\n'
        "tolerance = { png = 0.02 }\n"
        'notes = "SIL-745：vdiffr 快照原样纳入；标题是 doppelganger 名。"\n'
    )


def _ruff_format(source: str) -> str:
    """生成物先过 ruff 格式化，写盘内容与 `pixi run lint` 期望的一致。"""
    try:
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "case.py"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                ["ruff", "format", str(path)], capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                return path.read_text(encoding="utf-8")
    except OSError:  # pragma: no cover - 没有 ruff 时退回原样
        pass
    return source


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
            target / "plot.py": _ruff_format(_plot_source(spec)),
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
