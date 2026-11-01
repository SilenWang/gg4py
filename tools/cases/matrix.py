#!/usr/bin/env python
"""案例库覆盖矩阵生成器（M0-11）。

    pixi run cases:matrix            # 扫描 → 渲染/比对 → 写矩阵与报告
    pixi run cases:matrix --check    # 只校验 docs/cases/matrix.md 是否最新：不写任何文件、
                                     # 也不跑 render / diff（隐含 --no-run）
    pixi run cases:matrix --no-run   # 只做静态契约校验，不调用 render / diff
    pixi run cases:matrix --summary  # 额外把报告的短版本（≤60 行）打到 stdout，
                                     # 供 GHA step summary 使用（报告文件仍是完整版）

一个 case = `docs/cases/<case-name>/` 下三个文件：

| 文件 | 作用 |
| --- | --- |
| `plot.py` | 定义：`build()` 返回 plot 规格（data + mapping + layers） |
| `expected.svg` / `expected.png` | 参考图（二选一） |
| `meta.toml` | 族、特性标签、容差、是否进 CI |

新增 case 不需要改本文件，也不需要改 `pixi.toml`：下一次 `pixi run cases:matrix`
就会把它算进矩阵、清单和报告。约定全文见 `docs/cases/README.md`。

产物两个，生命周期不同：

| 产物 | 入库 | 内容 |
| --- | --- | --- |
| `docs/cases/matrix.md` | 是 | 静态覆盖视图：族 × 特性、缺口、清单、来源（纯由仓库内容决定） |
| `.cases-matrix/report.md` / `.json` | 否 | 运行时结论：哪个 case 红、差多少、为什么待落地 |

报告文件永远写完整版：上游验收资产是 314 份 SVG，案例库必然超过几十个，截断会把
「需要修的 case」整节切掉，让人看不到红名单。只有贴到 GHA step summary 的短版本
（`render_summary()`）才受行数上限约束，并且被截断的只会是长名单的尾部。

`meta.toml` 缺失不算「不是 case」：目录里出现了 `plot.py` 或 `expected.*` 就按
半成品 case 收进来标 `invalid`（只有 `case.json` 的历史快照目录除外）。

渲染与比对不另造命令：就走 M0-8 的 `pixi run render` 与 M0-9 的 `pixi run diff`
（`pixi.toml` 里的任务名）。两个入口还没落地时以退出码 3 报“未实现”，本工具把
它记成 `pending`（⏳），**不算红**——否则 M0-8 / M0-9 合并之前整条 CI 永远是红的；
`--strict` 可以把 pending 也当失败，等两个入口落地后由 CI 打开。

Case 状态：

| 状态 | 含义 | 红？ |
| --- | --- | --- |
| `pass` | render + diff 都通过 | 否 |
| `fail` | render 出错或 diff 超容差 | **是** |
| `invalid` | 三文件缺失 / `meta.toml` 不合规 / `plot.py` 契约不满足 | **是** |
| `pending` | render / diff 报未实现（退出码 3） | 否（`--strict` 下是） |
| `skipped` | `meta.ci = false`，只登记不跑 | 否 |
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CASES = REPO / "docs" / "cases"
TAXONOMY_FILE = CASES / "taxonomy.toml"
MATRIX_FILE = CASES / "matrix.md"
REPORT_DIR = REPO / ".cases-matrix"

PLOT_FILE = "plot.py"
META_FILE = "meta.toml"
EXPECTED_FILES = ("expected.svg", "expected.png")
# M0-4 / M0-6 的历史快照目录：case.json 规格 + baseline/，不进 geom 矩阵，只登记来源。
LEGACY_SPEC = "case.json"
# 外部语料：不迁移，但要在矩阵里注明来源（issue 验收第 3 条）。
EXTERNAL_CORPORA = (
    (
        "docs/spike/e2_metrics",
        "X5 双端度量语料（200 标签 × 4 字号），不迁移；gate:metrics 直接消费",
        "docs/spike/corpus/labels_200.json",
    ),
    (
        "docs/spike/e3_export",
        "E3 导出可行性实验（CanvasKit / PDF），不迁移",
        None,
    ),
)

# 占位入口的退出码，与 src/ggcore/cli/__init__.py 的 EXIT_NOT_IMPLEMENTED 对齐。
EXIT_NOT_IMPLEMENTED = 3

PASS = "pass"
FAIL = "fail"
PENDING = "pending"
SKIPPED = "skipped"
INVALID = "invalid"

GLYPHS = {PASS: "✅", FAIL: "❌", PENDING: "⏳", SKIPPED: "⏭", INVALID: "⛔"}
RED_STATES = {FAIL, INVALID}
META_KEYS = {"family", "features", "ci", "title", "source", "tolerance", "notes"}


# ---------------------------------------------------------------------------
# case 发现与静态契约校验
# ---------------------------------------------------------------------------


@dataclass
class Case:
    """一个 `docs/cases/<name>/` 三文件 case。"""

    name: str
    directory: Path
    family: str = ""
    features: tuple[str, ...] = ()
    ci: bool = True
    title: str = ""
    source: str = "local"
    tolerance: dict[str, float] = field(default_factory=dict)
    expected: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def _meta_errors(meta: Any) -> tuple[dict[str, Any], list[str]]:
    """校验 meta.toml 的必填项，返回（规整后的值, 错误列表）。"""
    errors: list[str] = []
    if not isinstance(meta, Mapping):
        return {}, ["meta.toml 的顶层必须是表（table）"]

    family = meta.get("family")
    if not isinstance(family, str) or not family.strip():
        errors.append("meta.toml 缺 `family`（非空字符串）")

    features = meta.get("features")
    if not isinstance(features, list) or not all(
        isinstance(feature, str) and feature.strip() for feature in features
    ):
        errors.append("meta.toml 缺 `features`（字符串数组，可为空数组）")
        features = []

    ci = meta.get("ci", True)
    if not isinstance(ci, bool):
        errors.append("meta.toml 的 `ci` 必须是布尔值")

    tolerance = meta.get("tolerance", {})
    if not isinstance(tolerance, Mapping):
        errors.append("meta.toml 的 `tolerance` 必须是表")
        tolerance = {}
    for fmt, value in tolerance.items():
        if fmt not in ("png", "svg"):
            errors.append(f"meta.toml 的 `tolerance.{fmt}` 不认识（只支持 png / svg）")
        elif not isinstance(value, (int, float)) or not 0.0 <= float(value) < 1.0:
            errors.append(f"meta.toml 的 `tolerance.{fmt}` 必须是 [0, 1) 的数（比例）")

    source = meta.get("source", "local")
    if not isinstance(source, str):
        errors.append("meta.toml 的 `source` 必须是字符串")
        source = "local"

    return (
        {
            "family": family.strip() if isinstance(family, str) else "",
            "features": tuple(f.strip() for f in features),
            "ci": ci if isinstance(ci, bool) else True,
            "title": meta.get("title", "") if isinstance(meta.get("title", ""), str) else "",
            "source": source,
            "tolerance": {k: float(v) for k, v in tolerance.items() if isinstance(v, (int, float))},
        },
        errors,
    )


def validate_plot_spec(spec: Any) -> list[str]:
    """`plot.py` 的 `build()` 返回值契约（M0-11 只钉最小字段）。"""
    if not isinstance(spec, Mapping):
        return [f"`build()` 必须返回 dict（plot 规格），实际是 {type(spec).__name__}"]

    errors: list[str] = []
    data = spec.get("data")
    if not isinstance(data, Mapping) or not data:
        errors.append("plot 规格缺 `data`（非空映射：列名 → 数组）")

    mapping = spec.get("mapping", {})
    if not isinstance(mapping, Mapping):
        errors.append("plot 规格的 `mapping` 必须是 dict")

    layers = spec.get("layers")
    if not isinstance(layers, (list, tuple)) or not layers:
        errors.append("plot 规格缺 `layers`（非空数组）")
        return errors
    for index, layer in enumerate(layers):
        if not isinstance(layer, Mapping):
            errors.append(f"layers[{index}] 必须是 dict")
        elif not isinstance(layer.get("geom"), str) or not layer["geom"].strip():
            errors.append(f'layers[{index}] 缺 `geom`（如 "point" / "bar"）')
    return errors


def load_plot(directory: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """在独立模块里执行 `plot.py`，调用 `build()`；异常都折成契约错误。"""
    path = directory / PLOT_FILE
    module_name = "gg4py_case_" + re.sub(r"\W", "_", directory.name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 只在文件不可读时发生
        return None, [f"{path.name} 无法作为模块加载"]
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # 契约错误要报出来，不能让整轮扫断
        return None, [f"{PLOT_FILE} 导入失败：{type(exc).__name__}: {exc}"]
    finally:
        sys.modules.pop(module_name, None)

    builder = getattr(module, "build", None)
    if not callable(builder):
        return None, [f"{PLOT_FILE} 必须定义 `build()` 并返回 plot 规格 dict"]
    try:
        return builder(), []
    except Exception as exc:  # 同上
        return None, [f"{PLOT_FILE} 的 `build()` 抛异常：{type(exc).__name__}: {exc}"]


def _expected_errors(directory: Path) -> tuple[str, list[str]]:
    """参考图存在性 + 基本格式校验。返回（文件名, 错误列表）。"""
    found = [name for name in EXPECTED_FILES if (directory / name).is_file()]
    if not found:
        return "", [f"缺参考图：{EXPECTED_FILES[0]} 或 {EXPECTED_FILES[1]} 二选一"]
    if len(found) > 1:
        return "", [f"参考图只能有一个，实际同时有 {', '.join(found)}"]

    name = found[0]
    payload = (directory / name).read_bytes()
    if len(payload) < 64:
        return name, [f"{name} 太小（{len(payload)} 字节），不像一张参考图"]
    if name.endswith(".png") and payload[:8] != b"\x89PNG\r\n\x1a\n":
        return name, [f"{name} 不是 PNG（文件头不对）"]
    if name.endswith(".svg"):
        head = payload.lstrip()[:5]
        if not head.startswith(b"<?xml") and not head.startswith(b"<svg"):
            return name, [f"{name} 不是 SVG（既没有 XML 声明也没有 <svg 根）"]
    return name, []


def load_case(directory: Path) -> Case:
    """读一个三文件 case；所有契约问题进 `errors`，不抛异常。"""
    case = Case(name=directory.name, directory=directory)
    meta_path = directory / META_FILE
    if not meta_path.is_file():
        # 半成品：放下了 plot.py / expected.* 却忘了 meta.toml。不能静默跳过——
        # 那会让一个「看起来已经在案例库里」的目录既不进矩阵也不标红。
        case.errors.append(f"缺 {META_FILE}（三文件 case 需要 meta.toml 才能进矩阵）")
        meta: Any = {}
        values: dict[str, Any] = {}
    else:
        try:
            with meta_path.open("rb") as handle:
                meta = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            case.errors.append(f"{META_FILE} 读取失败：{exc}")
            meta = {}
            values = {}
        else:
            values, meta_errors = _meta_errors(meta)
            case.errors.extend(meta_errors)

    case.family = values.get("family", "")
    case.features = values.get("features", ())
    case.ci = values.get("ci", True)
    case.title = values.get("title", "")
    case.source = values.get("source", "local")
    case.tolerance = values.get("tolerance", {})

    unknown = sorted(set(meta) - META_KEYS) if isinstance(meta, Mapping) else []
    if unknown:
        case.warnings.append(f"{META_FILE} 有未登记键：{', '.join(unknown)}")

    if not (directory / PLOT_FILE).is_file():
        case.errors.append(f"缺 {PLOT_FILE}")
    else:
        spec, plot_errors = load_plot(directory)
        if plot_errors:
            case.errors.extend(plot_errors)
        else:
            case.errors.extend(validate_plot_spec(spec))

    case.expected, expected_errors = _expected_errors(directory)
    case.errors.extend(expected_errors)
    return case


def _case_payload(directory: Path) -> bool:
    """目录里是否有三文件 case 的「文件本体」（`plot.py` 或 `expected.*`）。"""
    return (directory / PLOT_FILE).is_file() or any(
        (directory / name).is_file() for name in EXPECTED_FILES
    )


def discover(root: Path) -> list[Case]:
    """扫 `docs/cases/*/`：有 `meta.toml` 的是正式 case，有 `plot.py` / `expected.*`
    但缺 `meta.toml` 的是半成品（按 `invalid` 收进来，不静默丢弃）。

    只有 `case.json` 的历史快照目录（M0-4 / M0-6）不算三文件 case，也不按半成品
    报错——它们由 `legacy_snapshots()` 单独登记。
    """
    if not root.is_dir():
        return []
    cases: list[Case] = []
    for directory in sorted(root.iterdir(), key=lambda path: path.name):
        if not directory.is_dir():
            continue
        has_meta = (directory / META_FILE).is_file()
        if not has_meta and ((directory / LEGACY_SPEC).is_file() or not _case_payload(directory)):
            continue
        cases.append(load_case(directory))
    return cases


def legacy_snapshots(root: Path) -> list[Path]:
    """`case.json` 快照目录（M0-4 viewport / M0-6 grob），只登记来源。"""
    if not root.is_dir():
        return []
    return sorted(
        (
            directory
            for directory in root.iterdir()
            if directory.is_dir()
            and (directory / LEGACY_SPEC).is_file()
            and not (directory / META_FILE).is_file()
        ),
        key=lambda path: path.name,
    )


# ---------------------------------------------------------------------------
# 渲染 / 比对：只走既有任务名（M0-8 render、M0-9 diff）
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """一次 render / diff 调用的结果。`status` 取 pass / fail / pending。"""

    status: str
    detail: str = ""
    diff: str = ""


def _tail(text: str, lines: int = 3, limit: int = 240) -> str:
    rows = [row.strip() for row in text.strip().splitlines() if row.strip()]
    return " / ".join(rows[-lines:])[:limit]


class TaskBackend:
    """通过 `pixi run render` / `pixi run diff` 调用渲染与比对。

    M0-8 / M0-9 的入口契约（本工具依赖的就是这两条，不要另造命令）：

    - `pixi run render <case-dir> --format png --out <case-dir>/current`
      退出码 0 = 写出 PNG；3 = 未实现（记 pending）；其余 = 失败。
    - `pixi run diff <case-dir> --report <case-dir>/current/diff_report.md --tolerance <t>`
      退出码 0 = 通过；1 = 超容差；3 = 未实现（记 pending）；其余 = 失败。
    """

    def __init__(
        self,
        prefix: Sequence[str] = ("pixi", "run"),
        cwd: Path = REPO,
        env: Mapping[str, str] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.prefix = tuple(prefix)
        self.cwd = cwd
        self.env = dict(env) if env is not None else None
        self.runner = runner

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [*self.prefix, *args]
        env = dict(os.environ)
        env.update(self.env or {})
        return self.runner(
            command,
            cwd=str(self.cwd),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def render(self, case: Case) -> StepResult:
        out = case.directory / "current"
        result = self._run("render", str(case.directory), "--format", "png", "--out", str(out))
        if result.returncode == EXIT_NOT_IMPLEMENTED:
            return StepResult(PENDING, "render 未落地（M0-8）")
        if result.returncode != 0:
            return StepResult(FAIL, f"render 退出 {result.returncode}：{_tail(result.stderr)}")
        produced = sorted(out.glob("*.png")) if out.is_dir() else []
        if not produced:
            return StepResult(FAIL, f"render 退出 0 但 {out.name}/ 里没有 PNG")
        return StepResult(PASS, f"render → {produced[0].name}")

    def diff(self, case: Case) -> StepResult:
        report = case.directory / "current" / "diff_report.md"
        args = ["diff", str(case.directory), "--report", str(report)]
        tolerance = case.tolerance.get("png")
        if tolerance is not None:
            args.extend(["--tolerance", f"{tolerance:g}"])
        result = self._run(*args)
        detail = _tail(result.stdout) or _tail(result.stderr)
        if result.returncode == EXIT_NOT_IMPLEMENTED:
            return StepResult(PENDING, "diff 未落地（M0-9）")
        if result.returncode == 0:
            return StepResult(PASS, detail or "diff 通过", detail)
        return StepResult(FAIL, f"diff 退出 {result.returncode}：{detail}", detail)


@dataclass
class Verdict:
    """一个 case 的运行时结论。"""

    case: Case
    status: str
    detail: str = ""
    diff: str = ""


def evaluate(cases: Sequence[Case], backend: TaskBackend | None) -> list[Verdict]:
    """静态契约 → （可选）render + diff。契约不过的 case 不再浪费一次渲染。"""
    verdicts: list[Verdict] = []
    for case in cases:
        if not case.valid:
            verdicts.append(Verdict(case, INVALID, "；".join(case.errors)))
            continue
        if not case.ci:
            verdicts.append(Verdict(case, SKIPPED, "meta.ci = false（只登记不进 CI）"))
            continue
        if backend is None:
            verdicts.append(Verdict(case, SKIPPED, "--no-run：只做静态校验"))
            continue

        rendered = backend.render(case)
        if rendered.status != PASS:
            verdicts.append(Verdict(case, rendered.status, rendered.detail))
            continue
        compared = backend.diff(case)
        verdicts.append(
            Verdict(case, compared.status, compared.detail or rendered.detail, compared.diff)
        )
    return verdicts


# ---------------------------------------------------------------------------
# 聚合：族 × 特性
# ---------------------------------------------------------------------------


@dataclass
class Taxonomy:
    families: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    note: str = ""

    def axes(self, cases: Sequence[Case]) -> tuple[list[str], list[str]]:
        """已登记的轴 + case 里出现但没登记的（追加在后，矩阵里标「未登记」）。"""
        observed_families = sorted({case.family for case in cases if case.family})
        observed_features = sorted({feature for case in cases for feature in case.features})
        families = _union(self.families, observed_families)
        features = _union(self.features, observed_features)
        return families, features


def _union(declared: Sequence[str], observed: Sequence[str]) -> list[str]:
    return [*declared, *[item for item in observed if item not in declared]]


def _rel(path: Path) -> str:
    """尽量相对仓库根显示路径；临时目录（测试）就原样给绝对路径。"""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def load_taxonomy(path: Path = TAXONOMY_FILE) -> Taxonomy:
    if not path.is_file():
        return Taxonomy(note=f"缺 `{_rel(path)}`：矩阵只列 case 里出现过的族 / 特性")
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    families = _clean_axis(raw.get("families", []), "families")
    features = _clean_axis(raw.get("features", []), "features")
    return Taxonomy(families, features)


def _clean_axis(values: Any, name: str) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise SystemExit(f"taxonomy.toml: `{name}` 必须是字符串数组")
    seen: dict[str, None] = {}
    for item in values:
        if item in seen:
            raise SystemExit(f"taxonomy.toml: `{name}` 里有重复项 {item!r}")
        seen[item] = None
    return list(seen)


def aggregate(
    cases: Sequence[Case], taxonomy: Taxonomy
) -> tuple[list[str], list[str], dict[tuple[str, str], list[str]]]:
    """族（行）× 特性（列）→ 该组合下的 case 名。空组合不建键，渲染时标 `—`。"""
    families, features = taxonomy.axes(cases)
    cells: dict[tuple[str, str], list[str]] = {}
    for case in cases:
        if not case.family:
            continue
        for feature in case.features:
            cells.setdefault((case.family, feature), []).append(case.name)
    for names in cells.values():
        names.sort()
    return families, features, cells


# ---------------------------------------------------------------------------
# 产物：docs/cases/matrix.md（静态）+ .cases-matrix/report.md / .json（运行时）
# ---------------------------------------------------------------------------


def _code(text: str) -> str:
    return f"`{text}`"


def _tolerance_text(case: Case) -> str:
    if not case.tolerance:
        return "默认（X4）"
    return " / ".join(f"{fmt} {value:g}" for fmt, value in sorted(case.tolerance.items()))


def _external_rows(root: Path) -> list[tuple[str, str, str]]:
    """外部语料来源（不迁移，只登记）。"""
    rows: list[tuple[str, str, str]] = []
    for directory, description, counter in EXTERNAL_CORPORA:
        if not (REPO / directory).is_dir():
            continue
        count = "—"
        if counter and (REPO / counter).is_file():
            try:
                payload = json.loads((REPO / counter).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = None
            if isinstance(payload, list):
                count = f"{len(payload)} 条"
            elif isinstance(payload, dict) and isinstance(payload.get("count"), int):
                count = f"{payload['count']} 条"
        rows.append((f"{_code(directory)}", count, description))
    return rows


def render_matrix(
    cases: Sequence[Case],
    taxonomy: Taxonomy,
    legacy: Sequence[Path],
    external: Sequence[tuple[str, str, str]],
) -> str:
    """生成 `docs/cases/matrix.md`。纯函数：同一份仓库内容 → 同一份字节。"""
    families, features, cells = aggregate(cases, taxonomy)
    by_name = {case.name: case for case in cases}

    def cell_text(name: str) -> str:
        """契约不过的 case 在矩阵里直接带 ⛔，`ci = false` 的带 ⏭。"""
        case = by_name[name]
        if not case.valid:
            return f"{_code(name)} ⛔"
        if not case.ci:
            return f"{_code(name)} ⏭"
        return _code(name)

    lines: list[str] = [
        "# 案例覆盖矩阵",
        "",
        "<!-- 生成物，不要手改：pixi run cases:matrix；"
        "pixi run cases:matrix --check 校验是否最新 -->",
        "",
        "矩阵是**静态**覆盖视图（只由仓库内容决定）：行 = 族，列 = 特性标签，"
        f"`—` = 该组合没有 case。运行时红绿与「差多少」在 `{REPORT_DIR.name}/report.md`"
        "（`pixi run cases:matrix` 生成，不入库）。",
        "",
        f"- 三文件 case：**{len(cases)}** 个（`plot.py` + `expected.svg|png` + `meta.toml`）",
        f"- 历史快照目录：**{len(legacy)}** 个（`case.json`，M0-4 / M0-6，不进矩阵）",
    ]
    if taxonomy.note:
        lines.append(f"- {taxonomy.note}")
    unplaced = sorted(case.name for case in cases if not case.family)
    if unplaced:
        lines.append(
            f"- 未进矩阵：**{len(unplaced)}** 个 case 缺可用的 `family`"
            f"（{'、'.join(_code(name) for name in unplaced)}，见下方清单的契约列）"
        )
    declared_families = set(taxonomy.families)
    declared_features = set(taxonomy.features)
    lines.extend(["", "## 覆盖矩阵", ""])

    header = ["族 \\ 特性", *(f"`{feature}`" for feature in features), "合计"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---", *["---"] * len(features), "---"]) + " |")
    for family in families:
        names: list[str] = []
        row = [f"`{family}`"]
        for feature in features:
            members = cells.get((family, feature), [])
            names.extend(members)
            row.append("<br>".join(cell_text(name) for name in members) if members else "—")
        row.append(str(len(set(names))) if names else "—")
        lines.append("| " + " | ".join(row) + " |")
    feature_totals = [
        len(
            {
                name
                for (_, cell_feature), members in cells.items()
                if cell_feature == feature
                for name in members
            }
        )
        for feature in features
    ]
    placed = len({name for members in cells.values() for name in members})
    totals = [str(total) if total else "—" for total in feature_totals]
    totals.append(str(placed) if placed else "—")
    lines.append("| **合计** | " + " | ".join(totals) + " |")

    gaps = [
        (family, feature)
        for family in families
        for feature in features
        if not cells.get((family, feature))
    ]
    lines.extend(["", f"## 覆盖缺口（{len(gaps)} 个空位）", ""])
    if gaps:
        lines.append("按族列出没有 case 的特性（要补哪个格子就看这一节）：")
        lines.append("")
        lines.append("| 族 | 未覆盖的特性 |")
        lines.append("| --- | --- |")
        for family in families:
            missing = [feature for candidate, feature in gaps if candidate == family]
            if not missing:
                lines.append(f"| `{family}` | （全覆盖） |")
                continue
            lines.append(
                "| " + " | ".join([f"`{family}`", "、".join(_code(f) for f in missing)]) + " |"
            )
    else:
        lines.append("- 无：所有族 × 特性组合都有 case。")

    lines.extend(["", "## 案例清单", ""])
    if cases:
        lines.append("| case | 族 | 特性 | 容差 | ci | 参考 | 来源 | 契约 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for case in sorted(cases, key=lambda item: item.name):
            contract = "ok" if case.valid else "；".join(case.errors)
            lines.append(
                "| "
                + " | ".join(
                    [
                        _code(case.name),
                        _code(case.family) if case.family else "—",
                        "<br>".join(_code(feature) for feature in case.features) or "—",
                        _tolerance_text(case),
                        "是" if case.ci else "否",
                        _code(case.expected) if case.expected else "缺失",
                        case.source,
                        contract,
                    ]
                )
                + " |"
            )
    else:
        lines.append("（还没有三文件 case；新增一个目录就会自动出现在这里。）")

    unregistered_families = [family for family in families if family not in declared_families]
    unregistered_features = [feature for feature in features if feature not in declared_features]
    lines.extend(["", "## 未登记的族 / 特性", ""])
    if unregistered_families or unregistered_features:
        lines.append(
            "这些值出现在 case 的 `meta.toml` 里，但没写进 "
            f"`{_rel(TAXONOMY_FILE)}`；矩阵已自动加行/列，请补登记。"
        )
        lines.extend(f"- 族：`{family}`" for family in unregistered_families)
        lines.extend(f"- 特性：`{feature}`" for feature in unregistered_features)
    else:
        lines.append("无：矩阵里的每个族 / 特性都在 `taxonomy.toml` 里登记过。")

    lines.extend(["", "## 其他来源（不进 geom 矩阵）", ""])
    lines.append("| 来源 | 数量 | 说明 |")
    lines.append("| --- | --- | --- |")
    lines.append(
        "| `docs/cases/*/case.json`（M0-4 viewport / M0-6 grob） | "
        f"{len(legacy)} | 快照由 `pixi run cases:viewport` / `pixi run cases:grob` 维护，"
        "不套三文件约定 |"
    )
    for source, count, description in external:
        lines.append(f"| {source} | {count} | {description} |")
    lines.append("")
    return "\n".join(lines)


NO_FAMILY = "（未登记 family）"
# GHA step summary 的行数上限；只作用于 `render_summary()`，报告文件不受限。
SUMMARY_MAX_LINES = 60


def _counts(verdicts: Sequence[Verdict]) -> dict[str, int]:
    counts = {status: 0 for status in GLYPHS}
    for verdict in verdicts:
        counts[verdict.status] = counts.get(verdict.status, 0) + 1
    return counts


def _verdict_text(red: Sequence[Verdict], total: int) -> str:
    # 0 个 case 既不是红也不是绿：那是「空跑」，报绿等于说 job 守住了矩阵。
    if total == 0:
        return "**空**"
    return "**红**" if red else "**绿**"


def _counts_text(counts: Mapping[str, int]) -> str:
    return (
        f"通过 {counts[PASS]} / 失败 {counts[FAIL]} / "
        f"契约错 {counts[INVALID]} / 待落地 {counts[PENDING]} / 跳过 {counts[SKIPPED]}"
    )


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _family_rows(
    verdicts: Sequence[Verdict], families: Sequence[str]
) -> list[tuple[str, int, int]]:
    """按族汇总：族 →（case 数, 红数）；未登记 `family` 的 case 单列一行。"""
    buckets: dict[str, list[int]] = {}
    for verdict in verdicts:
        bucket = buckets.setdefault(verdict.case.family or NO_FAMILY, [0, 0])
        bucket[0] += 1
        if verdict.status in RED_STATES:
            bucket[1] += 1
    ordered = [*families, NO_FAMILY]
    rows = [(label, *buckets[label]) for label in ordered if label in buckets]
    rows.extend((label, *bucket) for label, bucket in buckets.items() if label not in ordered)
    return rows


def render_report(
    verdicts: Sequence[Verdict],
    cases: Sequence[Case],
    taxonomy: Taxonomy,
    *,
    now: str,
    matrix_file: Path = MATRIX_FILE,
) -> str:
    """运行时报告（**完整版**，写进 `.cases-matrix/report.md`）。

    这里**不截断**：上游验收资产是 314 份 SVG，案例库必然超过几十个；一旦按行数
    截断，逐 case 表和「需要修的 case」整节都会被切掉，红名单就没人看得到。
    贴到 GHA step summary 的短版本是另一个函数（`render_summary()`）。
    """
    families, features, cells = aggregate(cases, taxonomy)
    gaps = [
        (family, feature)
        for family in families
        for feature in features
        if not cells.get((family, feature))
    ]
    red = [verdict for verdict in verdicts if verdict.status in RED_STATES]
    pending = [verdict for verdict in verdicts if verdict.status == PENDING]
    counts = _counts(verdicts)
    lines = [
        "# 案例矩阵运行报告",
        "",
        f"- 时间：{now}",
        f"- 结论：{_verdict_text(red, len(cases))}（{_counts_text(counts)}）",
        f"- case：{len(cases)} 个（族 {len(families)} × 特性 {len(features)}，"
        f"空位 {len(gaps)} 个）",
        f"- 覆盖视图：`{_rel(matrix_file)}`（族 × 特性的覆盖矩阵、缺口与清单）；"
        "本报告只回答运行时红绿与「差多少」",
        "- 任务：`pixi run cases:matrix`",
        "",
    ]
    if red:
        lines.extend(["## 需要修的 case", ""])
        for verdict in red:
            lines.append(f"- `{verdict.case.name}`：{verdict.detail or '—'}")
        lines.append("")

    family_rows = _family_rows(verdicts, families)
    if family_rows:
        lines.extend(["## 按族汇总", "", "| 族 | case | 红 |", "| --- | --- | --- |"])
        for family, total, red_count in family_rows:
            label = _code(family) if family != NO_FAMILY else family
            lines.append(f"| {label} | {total} | {red_count if red_count else '—'} |")
        lines.append("")

    if not verdicts:
        lines.extend(["没有三文件 case，本轮没有可跑的东西。", ""])
    else:
        lines.append("| case | 结果 | 差多少 | 说明 |")
        lines.append("| --- | --- | --- | --- |")
        for verdict in verdicts:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _code(verdict.case.name),
                        f"{GLYPHS.get(verdict.status, verdict.status)} {verdict.status}",
                        verdict.diff or "—",
                        verdict.detail or "—",
                    ]
                )
                + " |"
            )
        lines.append("")

    if pending:
        lines.extend(
            [
                "## 待落地",
                "",
                f"{len(pending)} 个 case 的 render / diff 报“未实现”（退出码 3）："
                "M0-8（`pixi run render`）与 M0-9（`pixi run diff`）落地后自动转真跑；"
                "`--strict` 可以把它们当失败。",
                "",
            ]
        )
    lines.extend(["## 怎么新增 case", "", "见 `docs/cases/README.md`：放三个文件，不改代码。"])
    lines.append("")
    return "\n".join(lines)


def render_summary(
    verdicts: Sequence[Verdict],
    cases: Sequence[Case],
    taxonomy: Taxonomy,
    *,
    now: str,
    report_file: Path = REPORT_DIR / "report.md",
    max_lines: int = SUMMARY_MAX_LINES,
) -> str:
    """GHA step summary 用的短版本：结论 + 红名单。

    这是唯一会截断的地方，而且只截名单尾部（保留「还有 N 个」与完整报告的指向）：
    把「需要修的 case」整节切掉才是真正的问题。

    `report_file` 必须是**这次实际写出的**报告路径（`--report-dir` 会改它）：
    短版本里两处「全文见 …」都指向它，硬编码 `.cases-matrix/report.md` 会在
    自定义目录时把人带到不存在的文件。
    """
    families, features, cells = aggregate(cases, taxonomy)
    report_hint = f"`{_rel(report_file)}`"
    gaps = [
        (family, feature)
        for family in families
        for feature in features
        if not cells.get((family, feature))
    ]
    red = [verdict for verdict in verdicts if verdict.status in RED_STATES]
    counts = _counts(verdicts)
    lines = [
        f"# 案例矩阵：{_verdict_text(red, len(cases))}",
        "",
        f"- 时间：{now}",
        f"- 结论：{_counts_text(counts)}",
        f"- case：{len(cases)} 个（族 {len(families)} × 特性 {len(features)}，"
        f"空位 {len(gaps)} 个）",
        f"- 逐 case 表、「差多少」与完整红名单：{report_hint}",
        "",
    ]
    if not cases:
        # 0 个 case 时不能报「全部绿」：那正是「空跑绿」——job 什么都没验证。
        lines.append(
            "- ⚠️ 一个三文件 case 都没有：本 job 只验证静态矩阵，没有真实渲染覆盖"
            "（真实覆盖随 SIL-599 打开）"
        )
        lines.append("")
    tail = ["", "见 `docs/cases/README.md`：放三个文件就能新增 case。", ""]
    if not red:
        if cases:
            lines.extend(["全部绿。", *tail])
        else:
            lines.extend(["没有 case 可跑。", *tail])
        return "\n".join(lines)

    lines.extend(["## 需要修的 case", ""])
    entries = [f"- `{verdict.case.name}`：{_one_line(verdict.detail) or '—'}" for verdict in red]
    # 末行留给「…还有 N 个」，所以先扣掉它和结尾三行。
    budget = max_lines - len(lines) - len(tail) - 1
    for index, entry in enumerate(entries):
        if index >= max(budget, 0):
            hidden = len(entries) - index
            lines.append(f"- …还有 {hidden} 个红 case 没列出，全文见 {report_hint}")
            break
        lines.append(entry)
    lines.extend(tail)
    return "\n".join(lines)


def report_payload(
    verdicts: Sequence[Verdict], cases: Sequence[Case], taxonomy: Taxonomy, now: str
) -> dict[str, Any]:
    families, features, cells = aggregate(cases, taxonomy)
    red = [verdict.case.name for verdict in verdicts if verdict.status in RED_STATES]
    return {
        "generated_at": now,
        "ok": not red,
        "red": red,
        "axes": {"families": families, "features": features},
        "gaps": [
            [family, feature]
            for family in families
            for feature in features
            if not cells.get((family, feature))
        ],
        "cases": [
            {
                "name": verdict.case.name,
                "family": verdict.case.family,
                "features": list(verdict.case.features),
                "status": verdict.status,
                "diff": verdict.diff,
                "detail": verdict.detail,
                "ci": verdict.case.ci,
                "expected": verdict.case.expected,
                "source": verdict.case.source,
            }
            for verdict in verdicts
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _first_difference(committed: str, generated: str) -> str:
    committed_lines = committed.splitlines()
    generated_lines = generated.splitlines()
    for index, (left, right) in enumerate(zip(committed_lines, generated_lines, strict=False), 1):
        if left != right:
            return f"第 {index} 行：仓库里 {left!r}，重新生成 {right!r}"
    return f"行数不同：仓库里 {len(committed_lines)} 行，重新生成 {len(generated_lines)} 行"


def _gha_error(message: str) -> None:
    """GHA workflow command 走 **stderr**，stdout 只留正文。

    runner 对两个流都识别 workflow command，注解照样出现在 PR 的
    Annotations 里；但 `--summary` 的正文在 stdout，注解若也写 stdout 就会
    混进短版本（70 个红 case 直接多出 70 行），贴到 step summary 的内容就
    不再是「结论 + 红名单」。
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error title=案例矩阵::{message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cases:matrix",
        description="扫描 docs/cases 的三文件 case，渲染 + 比对，产出覆盖矩阵与报告。",
    )
    parser.add_argument("--root", type=Path, default=CASES, help="案例根目录（默认 docs/cases）")
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验 docs/cases/matrix.md 是否最新：不写矩阵 / 报告，"
        "也不跑 render / diff（隐含 --no-run）",
    )
    parser.add_argument("--no-run", action="store_true", help="只做静态校验，不调用 render / diff")
    parser.add_argument(
        "--strict", action="store_true", help="把 pending（render / diff 未落地）也当失败"
    )
    parser.add_argument("--case", action="append", dest="cases", help="只处理这个 case（可重复）")
    parser.add_argument(
        "--report-dir", type=Path, default=REPORT_DIR, help="运行时报告目录（默认 .cases-matrix）"
    )
    parser.add_argument(
        "--print", action="store_true", dest="print_matrix", help="把矩阵打到 stdout"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="把报告的短版本（结论 + 红名单，≤60 行）打到 stdout；"
        "GHA 贴 summary 时用它，报告文件本身始终完整",
    )
    return parser


def main(argv: list[str] | None = None, backend: TaskBackend | None = None) -> int:
    args = build_parser().parse_args(argv)
    # `--check` 是纯校验：不写矩阵 / 报告，也不跑 render / diff（隐含 --no-run）。
    check_only = args.check
    backend = None if (args.no_run or check_only) else (backend or TaskBackend())

    cases = discover(args.root)
    if args.cases:
        wanted = set(args.cases)
        cases = [case for case in cases if case.name in wanted]
        missing = wanted - {case.name for case in cases}
        for name in sorted(missing):
            print(f"cases:matrix: no case named {name!r}", file=sys.stderr)

    taxonomy = load_taxonomy(
        TAXONOMY_FILE if args.root == CASES else args.root / TAXONOMY_FILE.name
    )
    legacy = legacy_snapshots(args.root)
    external = _external_rows(args.root)

    matrix_file = MATRIX_FILE if args.root == CASES else args.root / MATRIX_FILE.name
    generated = render_matrix(cases, taxonomy, legacy, external)
    if args.print_matrix:
        print(generated)

    exit_code = 0
    if check_only:
        committed = matrix_file.read_text(encoding="utf-8") if matrix_file.is_file() else ""
        if committed != generated:
            print(
                f"cases:matrix: {_rel(matrix_file)} 不是最新"
                f"（{_first_difference(committed, generated)}）",
                file=sys.stderr,
            )
            print("  修法：pixi run cases:matrix 后把矩阵一起提交", file=sys.stderr)
            exit_code = 1
    else:
        matrix_file.parent.mkdir(parents=True, exist_ok=True)
        matrix_file.write_text(generated, encoding="utf-8")
        print(f"wrote {_rel(matrix_file)}")

    if not cases:
        # 0 个 case 时 job 仍是绿的，但什么都没验证——把这件事写进日志，
        # 别让「空跑绿」被当成「矩阵守住了」。真实覆盖随 SIL-599 打开。
        print(
            "cases:matrix: 没有三文件 case —— 本次只校验 docs/cases/matrix.md 是否最新，"
            "没有真实渲染 / 比对覆盖（真实覆盖随 SIL-599 打开）",
            file=sys.stderr,
        )

    verdicts = evaluate(cases, backend)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not check_only:
        report_dir: Path = args.report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / "report.md"
        # 报告文件永远完整（314 份上游快照量级也不能截断）；截断只发生在 step summary。
        report_file.write_text(
            render_report(verdicts, cases, taxonomy, now=now, matrix_file=matrix_file),
            encoding="utf-8",
        )
        payload = report_payload(verdicts, cases, taxonomy, now)
        (report_dir / "report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if args.summary:
            print(render_summary(verdicts, cases, taxonomy, now=now, report_file=report_file))

    for verdict in verdicts:
        if verdict.status in RED_STATES:
            _gha_error(f"{verdict.case.name}: {verdict.detail}")
    if args.strict:
        for verdict in verdicts:
            if verdict.status == PENDING:
                _gha_error(f"{verdict.case.name}: render / diff 未落地（--strict）")

    counts = _counts(verdicts)
    print(
        "cases:matrix: "
        f"{len(cases)} case(s) — pass {counts[PASS]}, fail {counts[FAIL]}, "
        f"invalid {counts[INVALID]}, pending {counts[PENDING]}, skipped {counts[SKIPPED]}"
    )
    failures = [verdict for verdict in verdicts if verdict.status in RED_STATES]
    strict_pending = [verdict for verdict in verdicts if args.strict and verdict.status == PENDING]
    if failures:
        for verdict in failures:
            print(f"  ❌ {verdict.case.name}: {verdict.detail}", file=sys.stderr)
        exit_code = 1
    if strict_pending:
        for verdict in strict_pending:
            print(f"  ⏳ {verdict.case.name}: render / diff 未落地（--strict）", file=sys.stderr)
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
