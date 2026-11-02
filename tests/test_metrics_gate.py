"""门禁自测：双端比较逻辑必须真的会判红。

`gate:metrics` 的实测数据来自 node 侧的 CanvasKit，跑不起 node 的机器上也要能验证
「比较逻辑本身是敏感的」，所以这里把 CanvasKit 的返回替换成合成数据：把 Python
侧的宽度放大 1%，判定必须红；run 切分错位也必须被发现。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from ggcore.metrics import FontCatalog
from ggshape import harfbuzz_provider

REPO = Path(__file__).resolve().parent.parent
GATE_PATH = REPO / "tools" / "gates" / "check_metrics.py"

spec = importlib.util.spec_from_file_location("check_metrics_gate", GATE_PATH)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

TEXTS = [
    {"id": "L000", "category": "latin", "text": "Sepal Length"},
    {"id": "L001", "category": "cjk", "text": "月份（万元）"},
    {"id": "L002", "category": "emoji", "text": "🌱 Sales"},
]


@pytest.fixture(scope="module")
def provider():
    return harfbuzz_provider(FontCatalog())


def canvaskit_payload(provider, texts, scale: float = 1.0, corrupt_layout: bool = False) -> dict:
    labels = []
    for label in texts:
        runs = provider.runs(label["text"], 16)
        labels.append(
            {
                "id": label["id"],
                "category": label["category"],
                "width": sum(run.width for run in runs) * scale,
                "implicit_width": sum(run.width for run in runs),
                "runs": [
                    {
                        "face": run.font,
                        "text": run.text + ("x" if corrupt_layout and index == 0 else ""),
                        "width": run.width,
                    }
                    for index, run in enumerate(runs)
                ],
            }
        )
    return {"labels": labels}


def test_agreeing_measurements_pass(provider) -> None:
    corpus = {"labels": TEXTS}
    rows, summary = gate.compare_dual_end(provider, corpus, canvaskit_payload(provider, TEXTS), 16)
    assert summary["passed"] is True
    assert summary["overall"]["failures"] == 0
    assert summary["overall"]["run_layout_mismatches"] == 0
    assert len(rows) == len(TEXTS)


def test_one_percent_drift_is_rejected(provider) -> None:
    corpus = {"labels": TEXTS}
    rows, summary = gate.compare_dual_end(
        provider, corpus, canvaskit_payload(provider, TEXTS, scale=1.01), 16
    )
    assert summary["passed"] is False
    assert summary["overall"]["failures"] == len(TEXTS)
    assert all(row["rel_delta"] == pytest.approx(0.01 / 1.01, rel=1e-6) for row in rows)


def test_run_layout_mismatch_is_rejected(provider) -> None:
    corpus = {"labels": TEXTS}
    _, summary = gate.compare_dual_end(
        provider, corpus, canvaskit_payload(provider, TEXTS, corrupt_layout=True), 16
    )
    assert summary["overall"]["run_layout_mismatches"] == len(TEXTS)


def test_degraded_font_stack_is_detected_as_a_failure(provider) -> None:
    """关掉 fallback（字体栈只剩主字族）必须让门禁红——这是门禁的灵敏度自检。"""
    corpus = {"labels": TEXTS}
    response = canvaskit_payload(provider, TEXTS)
    result = gate.check_sensitivity(provider, corpus, response, 16)
    assert result["detected"] is True
    # 主字族是 Noto Sans CJK SC，已经覆盖拉丁与 CJK，砍栈只改变 emoji 那条；
    # 门禁仍必须把它抓出来（这正是 fallback 存在的意义）。
    assert result["failures"] == 1
    assert result["run_layout_mismatches"] == 1
