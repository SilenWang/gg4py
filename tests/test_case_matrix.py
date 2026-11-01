"""案例库覆盖矩阵生成器（`tools/cases/matrix.py`，M0-11）的自测。

守四件事：

1. **新增 case 不改代码**：往根目录多放一个「三文件」目录，矩阵、清单、报告
   自动包含它（这正是 issue 的验收第 1 条）。
2. **做坏的 case 会红**：契约错（`plot.py` 抛异常 / 缺参考图 / meta 不合规）
   直接 `invalid`，`pixi run cases:matrix` 非 0 退出（验收第 2 条）。
3. **render / diff 未落地不是红**：退出码 3 记 `pending`，`--strict` 才判失败——
   否则 M0-8 / M0-9 落地之前 CI 永远是红的。
4. **矩阵是静态产物**：同一份仓库内容 → 同一份字节，`--check` 能守住新鲜度。
5. **报告不被行数截断**：60+ case（含大量 fail）时 `report.md` 仍是完整报告，
   逐 case 表与「需要修的 case」整节都在；只有 `--summary` 的短版本可截断。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
CASES_DIR = REPO / "docs" / "cases"

GOOD_PLOT = '''\
"""测试用 case：最小合法 plot 规格。"""

DATA = {"x": [1, 2, 3], "y": [4, 5, 6]}


def build():
    return {"data": DATA, "mapping": {"x": "x", "y": "y"}, "layers": [{"geom": "point"}]}
'''

SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">\n'
    '  <circle cx="10" cy="10" r="4" fill="#F8766D"/>\n'
    "</svg>\n"
)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 96


def _load_tool() -> Any:
    path = REPO / "tools" / "cases" / "matrix.py"
    spec = importlib.util.spec_from_file_location("cases_matrix_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass 在 exec 时用 cls.__module__ 回查 sys.modules，必须先登记。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()


# ---------------------------------------------------------------------------
# 造临时案例库
# ---------------------------------------------------------------------------


def make_root(tmp_path: Path, families: tuple[str, ...] = ("geom-point", "geom-bar")) -> Path:
    root = tmp_path / "cases"
    root.mkdir()
    quotes = ", ".join(json.dumps(family, ensure_ascii=False) for family in families)
    (root / "taxonomy.toml").write_text(
        f'families = [{quotes}]\nfeatures = ["aes-mapping", "aes-grouping"]\n',
        encoding="utf-8",
    )
    return root


def write_case(
    root: Path,
    name: str,
    *,
    family: str = "geom-point",
    features: tuple[str, ...] = ("aes-mapping",),
    ci: bool = True,
    plot: str = GOOD_PLOT,
    expected: str | None = "expected.svg",
    meta: str | None = None,
    source: str = "svglite:test",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plot.py").write_text(plot, encoding="utf-8")
    if expected is not None:
        payload = SVG if expected.endswith(".svg") else PNG
        if isinstance(payload, bytes):
            (directory / expected).write_bytes(payload)
        else:
            (directory / expected).write_text(payload, encoding="utf-8")
    if meta is None:
        feature_text = ", ".join(json.dumps(feature) for feature in features)
        meta = (
            f'family = "{family}"\nfeatures = [{feature_text}]\n'
            f'ci = {"true" if ci else "false"}\nsource = "{source}"\n'
        )
    (directory / "meta.toml").write_text(meta, encoding="utf-8")
    return directory


def run(root: Path, tmp_path: Path, *extra: str, backend: Any = None) -> tuple[int, str, Path]:
    report_dir = tmp_path / "report"
    args = ["--root", str(root), "--report-dir", str(report_dir), *extra]
    code = TOOL.main(args, backend=backend)
    matrix = (root / "matrix.md").read_text(encoding="utf-8")
    return code, matrix, report_dir


class FakeBackend:
    """替代 `pixi run render` / `pixi run diff`，让运行时分支可测。"""

    def __init__(self, render: str, diff: str = TOOL.PASS, detail: str = "", diff_text: str = ""):
        self.render_status = render
        self.diff_status = diff
        self.detail = detail
        self.diff_text = diff_text
        self.calls: list[tuple[str, str]] = []

    def render(self, case: Any) -> Any:
        self.calls.append(("render", case.name))
        return TOOL.StepResult(self.render_status, self.detail or "render")

    def diff(self, case: Any) -> Any:
        self.calls.append(("diff", case.name))
        return TOOL.StepResult(self.diff_status, self.detail or "diff", self.diff_text)


# ---------------------------------------------------------------------------
# 1. 新增 case 不改代码就进矩阵
# ---------------------------------------------------------------------------


def test_new_case_enters_matrix_without_code_changes(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic", features=("aes-mapping", "aes-grouping"))
    code, before, _ = run(root, tmp_path, "--no-run")
    assert code == 0
    assert "`geom-point-basic`" in before
    assert "三文件 case：**1** 个" in before

    # 只加一个目录（三个文件），不碰任何代码 → 下一次跑矩阵就包含它。
    write_case(root, "geom-bar-stacked", family="geom-bar", features=("aes-mapping",))
    code, after, _ = run(root, tmp_path, "--no-run")
    assert code == 0
    assert "三文件 case：**2** 个" in after
    assert "`geom-bar-stacked`" in after
    assert "| `geom-bar` |" in after


def test_matrix_cells_follow_family_and_feature(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic", features=("aes-mapping",))
    write_case(root, "geom-point-grouped", features=("aes-grouping",))
    _, matrix, _ = run(root, tmp_path, "--no-run")
    row = next(line for line in matrix.splitlines() if line.startswith("| `geom-point` |"))
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[1] == "`geom-point-basic`"
    assert cells[2] == "`geom-point-grouped`"


def test_empty_cells_are_explicit_dashes(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic", features=("aes-mapping",))
    _, matrix, _ = run(root, tmp_path, "--no-run")
    row = next(line for line in matrix.splitlines() if line.startswith("| `geom-bar` |"))
    assert "| — |" in row
    # 缺口清单：geom-bar 行把两个特性都列为未覆盖。
    gaps = matrix.split("## 覆盖缺口", 1)[1]
    assert "`geom-bar` | `aes-mapping`、`aes-grouping`" in gaps


def test_unregistered_family_and_feature_are_flagged(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-violin-basic", family="geom-violin", features=("cve-text",))
    code, matrix, _ = run(root, tmp_path, "--no-run")
    assert code == 0
    assert "## 未登记的族 / 特性" in matrix
    assert "- 族：`geom-violin`" in matrix
    assert "- 特性：`cve-text`" in matrix


# ---------------------------------------------------------------------------
# 2. 做坏的 case 让矩阵标红、退出码非 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"plot": "def build():\n    raise RuntimeError('boom')\n"}, "build()` 抛异常"),
        ({"plot": "DATA = {}\n"}, "必须定义 `build()`"),
        (
            {"plot": "def build():\n    return {'data': {}, 'layers': [{'geom': 'point'}]}\n"},
            "`data`",
        ),
        ({"plot": "def build():\n    return {'data': {'x': [1]}, 'layers': []}\n"}, "`layers`"),
        ({"plot": "def build():\n    return {'data': {'x': [1]}, 'layers': [{}]}\n"}, "`geom`"),
        ({"expected": None}, "缺参考图"),
        (
            {"meta": 'family = "geom-point"\nfeatures = ["aes-mapping"]\nci = "yes"\n'},
            "`ci` 必须是布尔值",
        ),
        ({"meta": 'features = ["aes-mapping"]\n'}, None),
        (
            {
                "meta": 'family = "geom-point"\nfeatures = ["aes-mapping"]\n'
                "tolerance = { png = 2.0 }\n"
            },
            "[0, 1)",
        ),
    ],
)
def test_broken_case_is_invalid_and_red(
    tmp_path: Path, kwargs: dict[str, Any], needle: str | None
) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic", **kwargs)
    code, matrix, report_dir = run(root, tmp_path, "--no-run")
    assert code == 1
    if needle is not None:
        assert "⛔" in matrix
    assert "**红**" in (report_dir / "report.md").read_text(encoding="utf-8")
    payload = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["red"] == ["geom-point-basic"]
    if needle is not None:
        assert needle in payload["cases"][0]["detail"]


def test_missing_family_is_listed_but_not_placed(tmp_path: Path) -> None:
    """缺 family 的 case 进不了矩阵格子（没有行），但清单与报告必须点名。"""
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic", meta='features = ["aes-mapping"]\n')
    code, matrix, report_dir = run(root, tmp_path, "--no-run")
    assert code == 1
    assert "未进矩阵：**1** 个 case 缺可用的 `family`" in matrix
    assert "meta.toml 缺 `family`" in matrix
    payload = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["red"] == ["geom-point-basic"]


def test_both_expected_files_is_invalid(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    directory = write_case(root, "geom-point-basic", expected="expected.svg")
    (directory / "expected.png").write_bytes(PNG)
    case = TOOL.load_case(directory)
    assert not case.valid
    assert any("只能有一个" in error for error in case.errors)


def test_bad_expected_bytes_is_invalid(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    directory = write_case(root, "geom-point-basic", expected=None)
    (directory / "expected.png").write_bytes(b"not a png" * 20)
    case = TOOL.load_case(directory)
    assert not case.valid
    assert any("不是 PNG" in error for error in case.errors)


# ---------------------------------------------------------------------------
# 3. render / diff 未落地是 pending，不是红；真失败才红
# ---------------------------------------------------------------------------


def test_pending_is_not_red_but_strict_is(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic")
    backend = FakeBackend(render=TOOL.PENDING, detail="render 未落地（M0-8）")
    code, _, report_dir = run(root, tmp_path, backend=backend)
    assert code == 0
    assert backend.calls == [("render", "geom-point-basic")]
    report = (report_dir / "report.md").read_text(encoding="utf-8")
    assert "⏳ pending" in report
    # pending 不是绿（SIL-644 S2）：既不能写「绿」，也不能写「全部绿」。
    assert "**绿**" not in report
    assert "待落地" in report
    assert "verdict = pending" in report
    payload = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["verdict"] == "pending"
    assert payload["ok"] is False

    code, _, report_dir = run(root, tmp_path, "--strict", backend=backend)
    assert code == 1
    strict_report = (report_dir / "report.md").read_text(encoding="utf-8")
    assert "**红" in strict_report and "**绿**" not in strict_report
    assert json.loads((report_dir / "report.json").read_text(encoding="utf-8"))["strict"] is True


def test_failing_diff_is_red_and_reports_how_far(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic")
    backend = FakeBackend(render=TOOL.PASS, diff=TOOL.FAIL, diff_text="像素差 1.7%（阈值 0.1%）")
    code, _, report_dir = run(root, tmp_path, backend=backend)
    assert code == 1
    assert backend.calls == [("render", "geom-point-basic"), ("diff", "geom-point-basic")]
    report = (report_dir / "report.md").read_text(encoding="utf-8")
    assert "❌ fail" in report
    assert "像素差 1.7%（阈值 0.1%）" in report
    assert "## 需要修的 case" in report


def test_render_failure_skips_diff(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic")
    backend = FakeBackend(render=TOOL.FAIL, detail="render 退出 2：boom")
    code, _, report_dir = run(root, tmp_path, backend=backend)
    assert code == 1
    assert backend.calls == [("render", "geom-point-basic")]
    assert "render 退出 2" in (report_dir / "report.md").read_text(encoding="utf-8")


def test_ci_false_is_skipped_and_marked(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-draft", ci=False)
    backend = FakeBackend(render=TOOL.PASS)
    code, matrix, report_dir = run(root, tmp_path, backend=backend)
    assert code == 0
    assert backend.calls == []
    assert "`geom-point-draft` ⏭" in matrix
    assert "⏭ skipped" in (report_dir / "report.md").read_text(encoding="utf-8")


def test_invalid_case_is_not_rendered(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic", plot="def build():\n    raise RuntimeError('boom')\n")
    backend = FakeBackend(render=TOOL.PASS)
    code, _, _ = run(root, tmp_path, backend=backend)
    assert code == 1
    assert backend.calls == []


# ---------------------------------------------------------------------------
# 4. 矩阵是静态产物：确定性 + --check 守新鲜度
# ---------------------------------------------------------------------------


def test_matrix_is_deterministic(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic")
    write_case(root, "geom-bar-basic", family="geom-bar")
    cases = TOOL.discover(root)
    taxonomy = TOOL.load_taxonomy(root / "taxonomy.toml")
    first = TOOL.render_matrix(cases, taxonomy, TOOL.legacy_snapshots(root), [])
    second = TOOL.render_matrix(cases, taxonomy, TOOL.legacy_snapshots(root), [])
    assert first == second


def test_check_detects_stale_matrix(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic")
    assert run(root, tmp_path, "--no-run")[0] == 0
    assert run(root, tmp_path, "--check", "--no-run")[0] == 0

    # 新增 case 但没重生成矩阵 → --check 必须红，并指出修法。
    write_case(root, "geom-bar-basic", family="geom-bar")
    code, _, _ = run(root, tmp_path, "--check", "--no-run")
    assert code == 1


def test_check_passes_on_the_committed_matrix() -> None:
    """仓库里的 `docs/cases/matrix.md` 与当前内容一致（CI 的守点）。"""
    assert TOOL.main(["--check", "--no-run"]) == 0


def test_missing_taxonomy_only_warns(tmp_path: Path) -> None:
    root = tmp_path / "cases"
    root.mkdir()
    write_case(root, "geom-point-basic")
    code, matrix, _ = run(root, tmp_path, "--no-run")
    assert code == 0
    assert "缺 `" in matrix and "taxonomy.toml`" in matrix
    assert "`geom-point`" in matrix


# ---------------------------------------------------------------------------
# 其他来源：历史快照 + e2 语料
# ---------------------------------------------------------------------------


def test_legacy_snapshots_are_registered_not_cases(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    snapshot = root / "grob-rect"
    snapshot.mkdir()
    (snapshot / "case.json").write_text('{"id": "grob-rect"}', encoding="utf-8")
    code, matrix, _ = run(root, tmp_path, "--no-run")
    assert code == 0
    assert "历史快照目录：**1** 个" in matrix
    assert "三文件 case：**0** 个" in matrix
    assert TOOL.discover(root) == []


def test_external_corpus_source_is_noted() -> None:
    """e2 语料不迁移，但矩阵里要注明来源（issue 验收第 3 条）。"""
    cases = TOOL.discover(CASES_DIR)
    taxonomy = TOOL.load_taxonomy()
    matrix = TOOL.render_matrix(
        cases, taxonomy, TOOL.legacy_snapshots(CASES_DIR), TOOL._external_rows(CASES_DIR)
    )
    assert "`docs/spike/e2_metrics`" in matrix
    assert "不迁移" in matrix
    assert "200 条" in matrix


def test_repo_cases_are_consistent() -> None:
    """仓库里每个三文件 case 的契约都成立（防止有人提交半成品）。"""
    broken = {case.name: case.errors for case in TOOL.discover(CASES_DIR) if not case.valid}
    assert broken == {}


# ---------------------------------------------------------------------------
# 5. 报告完整性：314 份快照量级也不能被行数截断
# ---------------------------------------------------------------------------


def test_report_keeps_full_list_and_red_section_beyond_line_limit(tmp_path: Path) -> None:
    """60+ case（含多 fail）：`report.md` 仍是完整报告，红名单一个不少。"""
    root = make_root(tmp_path)
    names = [f"geom-point-case-{index:02d}" for index in range(70)]
    for name in names:
        write_case(root, name)
    backend = FakeBackend(render=TOOL.PASS, diff=TOOL.FAIL, diff_text="像素差 1.7%（阈值 0.1%）")
    code, _, report_dir = run(root, tmp_path, backend=backend)
    assert code == 1

    report = (report_dir / "report.md").read_text(encoding="utf-8")
    assert len(report.splitlines()) > 60
    assert "已截断" not in report
    assert "## 需要修的 case" in report
    # 逐 case 表：第一个和最后一个 case 都还在（截断时最后一个会消失）。
    assert f"| `{names[0]}` |" in report
    assert f"| `{names[-1]}` |" in report
    # 红名单：70 个全部点名，而不是停在某个行号上。
    for name in names:
        assert f"- `{name}`：diff" in report


def test_step_summary_is_truncated_but_points_at_full_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--summary` 是唯一可截断的地方：保住结论 + 指向完整报告。"""
    # 结果不能取决于宿主是不是 GHA：注解走 stderr，stdout 只放正文。
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    root = make_root(tmp_path)
    names = [f"geom-point-case-{index:02d}" for index in range(70)]
    for name in names:
        write_case(root, name)
    backend = FakeBackend(render=TOOL.PASS, diff=TOOL.FAIL, diff_text="像素差 1.7%")
    report_dir = tmp_path / "report"
    code = TOOL.main(
        [
            "--root",
            str(root),
            "--report-dir",
            str(report_dir),
            "--summary",
        ],
        backend=backend,
    )
    assert code == 1

    out = capsys.readouterr().out
    start = out.index("# 案例矩阵：")
    summary = out[start : out.index("cases:matrix: ", start)]
    assert len(summary.splitlines()) <= TOOL.SUMMARY_MAX_LINES
    assert "案例矩阵：**红**" in summary
    assert "## 需要修的 case" in summary
    assert "…还有" in summary
    # 指向的是这次实际写出的报告（`--report-dir` 不是默认目录）。
    assert str(report_dir / "report.md") in summary
    assert ".cases-matrix/report.md" not in summary
    # stdout 里没有 workflow command。
    assert "::error" not in out
    # 报告文件本身没有被 summary 的截断影响。
    full = (report_dir / "report.md").read_text(encoding="utf-8")
    for name in names:
        assert f"- `{name}`：diff" in full


def test_gha_annotations_go_to_stderr_and_keep_summary_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI 的宿主环境（GITHUB_ACTIONS=true）下：stdout 仍是 ≤60 行的干净正文。

    这是 B2 的回归：注解曾写 stdout，70 个红 case 让短版本膨胀到 130 行。
    """
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    root = make_root(tmp_path)
    names = [f"geom-point-case-{index:02d}" for index in range(70)]
    for name in names:
        write_case(root, name)
    backend = FakeBackend(render=TOOL.PASS, diff=TOOL.FAIL, diff_text="像素差 1.7%")
    code = TOOL.main(
        [
            "--root",
            str(root),
            "--report-dir",
            str(tmp_path / "ci-report"),
            "--summary",
        ],
        backend=backend,
    )
    assert code == 1

    captured = capsys.readouterr()
    out = captured.out
    start = out.index("# 案例矩阵：")
    summary = out[start : out.index("cases:matrix: ", start)]
    assert len(summary.splitlines()) <= TOOL.SUMMARY_MAX_LINES
    assert "::error" not in out
    # 注解没丢：每个红 case 仍然以 workflow command 出现在 stderr（runner 两个流都认）。
    annotations = [line for line in captured.err.splitlines() if line.startswith("::error")]
    assert annotations == [f"::error title=案例矩阵::{name}: diff" for name in names]
    assert str(tmp_path / "ci-report" / "report.md") in summary


def test_zero_case_summary_says_no_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """0 个 case 不能报「全部绿」：那是空跑绿，日志与摘要都要点明没有真实验证。"""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    root = make_root(tmp_path)
    code = TOOL.main(
        ["--root", str(root), "--report-dir", str(tmp_path / "report"), "--summary"],
        backend=FakeBackend(render=TOOL.PASS, diff=TOOL.PASS),
    )
    assert code == 0

    captured = capsys.readouterr()
    assert "没有三文件 case" in captured.err
    assert "全部绿" not in captured.out
    assert "案例矩阵：**空**" in captured.out
    assert "没有 case 可跑" in captured.out
    assert "没有真实渲染覆盖" in captured.out


def test_report_has_family_rollup_and_points_to_matrix(tmp_path: Path) -> None:
    """运行时报告补上「按族汇总」，并直接指向 matrix.md（族 × 特性在那里）。"""
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic")
    write_case(root, "geom-bar-basic", family="geom-bar")
    backend = FakeBackend(render=TOOL.PASS, diff=TOOL.FAIL, diff_text="像素差 1.7%")
    code, _, report_dir = run(root, tmp_path, backend=backend)
    assert code == 1
    report = (report_dir / "report.md").read_text(encoding="utf-8")
    assert "## 按族汇总" in report
    assert "| `geom-point` | 1 | 1 |" in report
    assert "| `geom-bar` | 1 | 1 |" in report
    assert "matrix.md" in report


# ---------------------------------------------------------------------------
# 6. `--check` 是纯校验；缺 meta.toml 的半成品不再被静默丢弃
# ---------------------------------------------------------------------------


def test_check_writes_nothing_and_never_renders(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic")
    assert run(root, tmp_path, "--no-run")[0] == 0
    matrix_file = root / "matrix.md"
    before = matrix_file.read_text(encoding="utf-8")
    report_dir = tmp_path / "check-report"
    assert not report_dir.exists()

    backend = FakeBackend(render=TOOL.PASS, diff=TOOL.PASS)
    code = TOOL.main(
        ["--root", str(root), "--report-dir", str(report_dir), "--check"], backend=backend
    )
    assert code == 0
    assert backend.calls == []  # --check 隐含 --no-run
    assert not report_dir.exists()  # 不写 report.md / report.json
    assert matrix_file.read_text(encoding="utf-8") == before


def test_half_case_without_meta_toml_is_invalid_not_ignored(tmp_path: Path) -> None:
    """有 plot.py + expected.* 却忘写 meta.toml：按 invalid 报，不静默跳过。"""
    root = make_root(tmp_path)
    write_case(root, "geom-point-basic")
    half = root / "geom-bar-half"
    half.mkdir()
    (half / "plot.py").write_text(GOOD_PLOT, encoding="utf-8")
    (half / "expected.svg").write_text(SVG, encoding="utf-8")

    cases = {case.name: case for case in TOOL.discover(root)}
    assert "geom-bar-half" in cases
    assert not cases["geom-bar-half"].valid
    assert any("缺 meta.toml" in error for error in cases["geom-bar-half"].errors)

    code, matrix, report_dir = run(root, tmp_path, "--no-run")
    assert code == 1
    assert "三文件 case：**2** 个" in matrix
    assert "缺 meta.toml" in matrix
    assert "`geom-bar-half`：" in (report_dir / "report.md").read_text(encoding="utf-8")
    payload = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["red"] == ["geom-bar-half"]


def test_ci_is_optional_and_defaults_to_true(tmp_path: Path) -> None:
    """文档说 `ci` 可选、缺省 true；缺省时要真的进 render/diff，而不是被跳过。"""
    root = make_root(tmp_path)
    write_case(
        root,
        "geom-point-basic",
        meta='family = "geom-point"\nfeatures = ["aes-mapping"]\nsource = "svglite:test"\n',
    )
    directory = root / "geom-point-basic"
    case = TOOL.load_case(directory)
    assert case.valid and case.ci is True

    backend = FakeBackend(render=TOOL.PENDING, detail="render 未落地（M0-8）")
    code, _, _ = run(root, tmp_path, backend=backend)
    assert code == 0
    assert backend.calls == [("render", "geom-point-basic")]


def test_ci_true_with_local_source_is_invalid(tmp_path: Path) -> None:
    """硬要求 1：`ci = true` 的参考必须来自外部；自录基线永远自洽，等于没判据。"""
    root = make_root(tmp_path)
    write_case(
        root,
        "geom-point-local",
        meta='family = "geom-point"\nfeatures = ["aes-mapping"]\nsource = "local"\n',
    )
    case = TOOL.load_case(root / "geom-point-local")
    assert not case.valid
    assert any("必须来自外部参考" in error for error in case.errors)

    # `ci = false` 的草稿 case 允许 local（只登记，不进 CI）。
    write_case(
        root,
        "geom-point-draft",
        meta='family = "geom-point"\nfeatures = []\nci = false\nsource = "local"\n',
    )
    assert TOOL.load_case(root / "geom-point-draft").valid


def test_tolerance_svg_is_invalid_after_the_pixel_only_decision(tmp_path: Path) -> None:
    """硬要求 2：所有 case 都按像素比，`tolerance.svg` 已删除（不是静默忽略）。"""
    root = make_root(tmp_path)
    write_case(
        root,
        "geom-point-svg-tolerance",
        meta='family = "geom-point"\nfeatures = []\nsource = "svglite:test"\n'
        "tolerance = { svg = 0.001 }\n",
    )
    case = TOOL.load_case(root / "geom-point-svg-tolerance")
    assert not case.valid
    assert any("tolerance.svg" in error and "像素比" in error for error in case.errors)


def test_render_and_diff_use_the_expected_suffix(tmp_path: Path) -> None:
    """硬要求 2：格式由 `expected.*` 的后缀决定，并把 `tolerance.png` 传给 diff。"""
    import subprocess

    root = make_root(tmp_path)
    png_case = TOOL.load_case(write_case(root, "geom-point-png", expected="expected.png"))
    svg_case = TOOL.load_case(write_case(root, "geom-point-svg", expected="expected.svg"))
    assert (png_case.format, svg_case.format) == ("png", "svg")

    commands: list[list[str]] = []

    def runner(command, **kwargs):
        commands.append(list(command))
        if "render" in command:
            out = Path(command[command.index("--out") + 1])
            out.mkdir(parents=True, exist_ok=True)
            fmt = command[command.index("--format") + 1]
            case_dir = Path(command[command.index("render") + 1])
            (out / f"{case_dir.name}.{fmt}").write_bytes(
                b"\x89PNG\r\n\x1a\n" if fmt == "png" else b"<svg/>"
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"verdict": "pass", "image_diff_fraction": 0.0, "mean_diff": 0.0}),
            stderr="",
        )

    backend = TOOL.TaskBackend(prefix=("pixi", "run"), runner=runner)
    assert backend.render(png_case).status == TOOL.PASS
    assert backend.render(svg_case).status == TOOL.PASS

    # 带 tolerance 的 case：diff 必须收到 --json 与 --tolerance。
    tolerance_case = TOOL.load_case(
        write_case(
            root,
            "geom-point-tol",
            meta='family = "geom-point"\nfeatures = []\nsource = "svglite:test"\n'
            "tolerance = { png = 0.005 }\n",
        )
    )
    backend.diff(tolerance_case)

    render_commands = [cmd for cmd in commands if "render" in cmd]
    diff_commands = [cmd for cmd in commands if "diff" in cmd]
    assert render_commands[0][render_commands[0].index("--format") + 1] == "png"
    assert render_commands[1][render_commands[1].index("--format") + 1] == "svg"
    assert "--json" in diff_commands[0]
    assert diff_commands[0][diff_commands[0].index("--tolerance") + 1] == "0.005"


def test_diff_json_metrics_land_in_report(tmp_path: Path) -> None:
    """硬要求 3：矩阵从 `diff --json` 读百分比，写进报告与 report.json。"""
    import subprocess

    root = make_root(tmp_path)
    case = TOOL.load_case(write_case(root, "geom-point-basic"))

    payload = {
        "verdict": "pass",
        "ok": True,
        "image_diff_fraction": 0.0042,
        "mean_diff": 0.0007,
        "diff_pixels": 261,
        "total_pixels": 62208,
    }
    backend = TOOL.TaskBackend(
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )
    )
    step = backend.diff(case)
    assert step.status == TOOL.PASS
    assert step.metrics["image_diff_fraction"] == 0.0042
    assert step.metrics["mean_diff"] == 0.0007
    assert "图级 0.42%" in step.diff

    # 同样的结论进 report.json / report.md。
    verdicts = [TOOL.Verdict(case, TOOL.PASS, step.detail, step.diff, step.metrics)]
    written = TOOL.report_payload(
        verdicts, [case], TOOL.load_taxonomy(root / "taxonomy.toml"), "now"
    )
    assert written["cases"][0]["metrics"]["image_diff_fraction"] == 0.0042
    report = TOOL.render_report(
        verdicts, [case], TOOL.load_taxonomy(root / "taxonomy.toml"), now="now"
    )
    assert "图级 0.42%" in report

    # 超容差时：退出码 1 + reason 原样带出来。
    fail_payload = dict(payload, verdict="fail", ok=False, reason="图级差异 3.00% > 阈值 2.00%")
    failing = TOOL.TaskBackend(
        runner=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout=json.dumps(fail_payload), stderr=""
        )
    )
    failed = failing.diff(case)
    assert failed.status == TOOL.FAIL
    assert "图级差异 3.00%" in failed.detail
