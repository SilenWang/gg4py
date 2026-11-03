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
    base = [
        spec
        for spec in _theme_specs() + _guide_specs() + _dotplot_specs()
        if spec["slug"] not in skip
    ]
    return base + _G1A_SPECS


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
        return spec["source"]
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
    # G1a（SIL-788）的条目直接给 `source`（完整 plot.py 正文）；dotplot 族也带
    # `features`，所以判别键必须是 `source`，不能用 `features`。
    if "source" in spec:
        return (
            'family = "guide"\n'
            f"features = {json.dumps(spec['features'])}\n"
            "ci = true\n"
            f'title = "上游快照：{spec["title"]}"\n'
            f'source = "upstream:tests/testthat/_snaps/{spec["snapshot"]}"\n'
            "tolerance = { png = 0.02 }\n"
            'notes = "SIL-788：vdiffr 快照原样纳入；标题是 doppelganger 名。"\n'
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
