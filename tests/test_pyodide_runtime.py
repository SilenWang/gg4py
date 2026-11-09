"""SIL-824 · 浏览器运行时与「全量 case」Pyodide 门禁的单元测试。

这些用例不跑浏览器（浏览器那一层是 `pixi run pyodide:runtime`），守的是容易
悄悄退化的几件事：

* **表度量**（`ggcore.metrics.fallback`）在没有字体文件的进程里也能量文字——
  浏览器路径就靠它；纯 `textGrob` 快照以前会因为「没有 metrics」直接抛错。
* **逐条比较**（`run_cases.compare_cases`）真的在看摘要：缺 case、单侧失败、
  哈希不同、度量实现不同，四种差异都必须判红。
* **打包确定性**：`gg4py.tar` 两次构建字节相同；条目路径从仓库根算起（否则
  `/app` 下解出来的目录不是 `/app/src/ggcore`）；默认只带 `.pyc`（构建期在
  Pyodide 里编好，见 SIL-830），数据文件原样保留。
* **页面接线**：示例声明的 `needs` 都有对应的 wheel 规划、页面只从 `vendor/`
  取资产（无 CDN）、Service Worker 只接管 `vendor/`。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
sys.path.insert(0, str(REPO / "src"))

from ggcore import ir
from ggcore.metrics import TableMetrics
from ggcore.metrics.fallback import default_metrics
from ggcore.plotspec import build_scene, load_plot

CASES = REPO / "docs" / "cases"
RUNTIME = REPO / "web" / "runtime"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


run_cases = _module("gg4py_run_cases", TOOLS / "gates" / "pyodide" / "run_cases.py")
run_check = _module("gg4py_check_pyodide", TOOLS / "gates" / "check_pyodide_ir.py")
stage = _module("gg4py_stage_assets", TOOLS / "pyodide" / "stage_assets.py")


# ---------------------------------------------------------------------------
# 表度量：浏览器 / 无字体文件时的 `ggcore.units.Metrics`
# ---------------------------------------------------------------------------


def test_table_metrics_needs_no_font_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """浏览器里没有 fontconfig、没有字体文件：度量只读表，不许去翻字体目录。"""
    from ggcore.metrics import catalog

    def _boom() -> Path:  # pragma: no cover - 被调用就是失败
        raise AssertionError("表度量不该构造 FontCatalog")

    monkeypatch.setattr(catalog, "default_font_dir", _boom)
    metrics = TableMetrics()
    assert metrics.strwidth("Volume", fontsize=9, cex=1.0, font="Noto Sans CJK SC") > 0


def test_table_metrics_matches_the_provider() -> None:
    """`strwidth` 与 `MetricProvider` 同口径：整段 advance（px）/ 72。"""
    metrics = default_metrics()
    for text in ("Hello", "月份（万元）", "A/B", ""):
        width = metrics.strwidth(text, fontsize=12, cex=1.0, font="Noto Sans CJK SC")
        px = metrics.provider.strwidth(text, 12.0, metrics.stack("Noto Sans CJK SC"))
        assert width == pytest.approx(px / 72.0)


def test_table_metrics_width_grows_with_font_size() -> None:
    metrics = default_metrics()
    small = metrics.strwidth("ggplot", fontsize=8, cex=1.0)
    large = metrics.strwidth("ggplot", fontsize=16, cex=1.0)
    assert large == pytest.approx(small * 2, rel=1e-9)
    assert metrics.strheight("ggplot", fontsize=16, cex=1.0) > metrics.strheight(
        "ggplot", fontsize=8, cex=1.0
    )


def test_table_metrics_zero_size_is_zero_not_an_error() -> None:
    """R 里 0 号字就是零宽；`MetricProvider` 对 size <= 0 会报错，这里要挡住。"""
    metrics = default_metrics()
    assert metrics.strwidth("x", fontsize=0.0, cex=1.0) == 0.0
    assert metrics.strheight("x", fontsize=0.0, cex=1.0) == 0.0
    assert metrics.descent(fontsize=0.0) == 0.0


def test_table_metrics_stack_only_uses_fonts_in_the_table() -> None:
    metrics = default_metrics()
    available = set(metrics.backend.fonts)
    assert set(metrics.stack("Noto Sans CJK SC:bold-italic")) <= available
    assert set(metrics.stack("没登记的字族")) <= available


@pytest.mark.parametrize(
    "case",
    [
        "geom-text-cjk",
        "text-bold-italic",
        "text-emoji",
        "text-multiline",
        "upstream-guide-axis-check-overlap",
        "upstream-guide-axis-text-dodged",
        "upstream-legend-draw-all-keys",
    ],
)
def test_grob_snapshots_build_with_the_table_metrics(case: str) -> None:
    """这几条以前只要没有 HarfBuzz 就 `GrobError`（纯 textGrob 需要度量）。"""
    scene = build_scene(load_plot(CASES / case), metrics=default_metrics())
    assert len(ir.encode(scene)) > 0


# ---------------------------------------------------------------------------
# 全量 case：发现、摘要、逐条比较
# ---------------------------------------------------------------------------


def test_run_cases_covers_every_plot_py() -> None:
    expected = {path.parent.name for path in CASES.glob("*/plot.py")}
    found = {path.name for path in run_cases.case_dirs(CASES)}
    assert expected, "案例库不该是空的"
    assert found == expected


def test_run_cases_digest_is_stable_and_byte_sized() -> None:
    report = run_cases.run_cases(CASES, only="geom-point-basic")
    entry = report["cases"]["geom-point-basic"]
    assert len(entry["sha256"]) == 64
    assert entry["bytes"] > 0 and entry["nodes"] > 0
    assert report["metrics"] == "TableMetrics"
    again = run_cases.run_cases(CASES, only="geom-point-basic")
    assert again["cases"]["geom-point-basic"]["sha256"] == entry["sha256"]


def _report(cases: dict[str, str], failed: dict[str, str] | None = None) -> dict:
    return {
        "cases": {
            name: {"sha256": digest, "bytes": 10, "nodes": 1} for name, digest in cases.items()
        },
        "failed": failed or {},
        "metrics": "TableMetrics",
    }


def test_compare_cases_accepts_identical_reports() -> None:
    ok, problems = run_check.compare_cases(_report({"a": "0" * 64}), _report({"a": "0" * 64}))
    assert ok and problems == []


def test_compare_cases_flags_a_different_digest() -> None:
    ok, problems = run_check.compare_cases(_report({"a": "0" * 64}), _report({"a": "1" * 64}))
    assert not ok
    assert "IR 不同" in problems[0]


def test_compare_cases_flags_a_case_missing_on_one_side() -> None:
    ok, problems = run_check.compare_cases(
        _report({"a": "0" * 64, "b": "0" * 64}), _report({"a": "0" * 64})
    )
    assert not ok
    assert any("CPython 有、Pyodide 没有" in problem for problem in problems)


def test_compare_cases_flags_one_sided_failures() -> None:
    ok, problems = run_check.compare_cases(
        _report({"a": "0" * 64}), _report({"a": "0" * 64}, {"b": "TypeError: boom"})
    )
    assert not ok
    assert any("b: 只有 Pyodide 侧失败" in problem for problem in problems)


def test_compare_cases_flags_a_different_metrics_implementation() -> None:
    left = _report({"a": "0" * 64})
    right = _report({"a": "0" * 64})
    right["metrics"] = "_FallbackMetrics"
    ok, problems = run_check.compare_cases(left, right)
    assert not ok and any("度量实现不同" in problem for problem in problems)


def test_aggregate_digest_covers_every_case() -> None:
    left = run_check.aggregate_digest(_report({"a": "0" * 64, "b": "1" * 64}))
    right = run_check.aggregate_digest(_report({"b": "1" * 64, "a": "0" * 64}))
    changed = run_check.aggregate_digest(_report({"a": "0" * 64, "b": "2" * 64}))
    assert left == right
    assert left != changed


def test_gate_runs_the_full_case_sweep_by_default() -> None:
    """`pixi run gate:pyodide` 必须是全量：`--no-cases` 只留给手动调试。"""
    toml = (REPO / "pixi.toml").read_text(encoding="utf-8")
    gate = toml.split('"gate:pyodide" =', 1)[1].split("\n", 1)[0]
    assert "check_pyodide_ir.py" in gate
    assert "--no-cases" not in gate
    assert '"--no-cases"' in (TOOLS / "gates" / "check_pyodide_ir.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 资产打包
# ---------------------------------------------------------------------------


def test_archive_is_deterministic_and_repo_shaped(tmp_path: Path) -> None:
    first = stage.build_archive(tmp_path / "a" / "gg4py.tar", bytecode=False)
    second = stage.build_archive(tmp_path / "b" / "gg4py.tar", bytecode=False)
    assert first["sha256"] == second["sha256"]
    assert first["bytes"] == second["bytes"]
    import tarfile

    with tarfile.open(tmp_path / "a" / "gg4py.tar") as archive:
        members = archive.getmembers()
    names = [member.name for member in members]
    assert names == sorted(names)
    assert names[0].startswith("src/ggcore/")
    assert all(name.startswith("src/") for name in names)
    assert not any("__pycache__" in name or name.endswith(".orig") for name in names)
    assert "src/ggcore/metrics/data/metrics_table_v2.bin" in names
    # 固定元数据：同一份源码 → 同一个字节，缓存键与 sha256 才有意义。
    assert {member.mtime for member in members} == {0}
    assert {member.uid for member in members} == {0}


def test_archive_ships_bytecode_and_keeps_data_files(tmp_path: Path) -> None:
    """默认打包只带 `.pyc`（数据文件照旧）：浏览器里因此不做编译。"""
    if not (stage.SOURCE / "pyodide.asm.wasm").is_file():
        pytest.skip("先跑 `pixi run spike:e1:assets`")
    info = stage.build_archive(tmp_path / "gg4py.tar", bytecode=True)
    import tarfile

    with tarfile.open(tmp_path / "gg4py.tar") as archive:
        names = [member.name for member in archive.getmembers()]
    assert info["bytecode"] is True
    assert info["bytecode_files"] and info["bytecode_files"] > 80
    assert not [name for name in names if name.endswith(".py")]
    assert "src/ggcore/metrics/data/metrics_table_v2.bin" in names
    # 每个模块都能找到自己的字节码（`src/ggcore/x.py` → `src/ggcore/x.pyc`）。
    assert "src/ggcore/script.pyc" in names
    assert any(name.startswith("src/ggio/") and name.endswith(".pyc") for name in names)


def test_stage_fonts_keeps_only_small_faces(tmp_path: Path) -> None:
    if not (REPO / "web" / "viewer" / "fonts.css").is_file():
        pytest.skip("先跑 `pixi run viewer:build`")
    files = stage.stage_fonts(tmp_path / "fonts")
    kept = {entry["file"].removeprefix("fonts/") for entry in files}
    assert "Arimo-Italic-VF.ttf" in kept
    # 35 MB 的 CJK 字面与 9.5 MB 的彩色 emoji 都不该进首屏。
    assert "NotoSansCJKsc-VF.ttf" not in kept
    assert "NotoColorEmoji.ttf" not in kept
    css = (tmp_path / "fonts.css").read_text(encoding="utf-8")
    assert "NotoSansCJKsc" not in css
    assert 'url("fonts/Arimo-Italic-VF.ttf")' in css


def test_browser_guide_only_imports_packages_inside_the_tar() -> None:
    """`browser.md` 的代码块是「复制进编辑器就能跑」：只能 import tar 里有的包。

    SIL-914 把这一页的 import 改成了 `from gg4py import ...`，但 `gg4py.tar` 只打
    `PACKAGES`（`ggcore` / `ggio`），顶层 `gg4py` 不在包里——浏览器里那 5 段全部
    `ModuleNotFoundError`。这条断言把「文档写的 import」与「包里真有的包」钉在一起：
    谁动 `PACKAGES`，这一页就得同步改，反之亦然。
    """
    text = (REPO / "docs" / "guide" / "browser.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    assert len(blocks) >= 5
    shipped = set(stage.PACKAGES)
    outside: list[str] = []
    for source in blocks:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if top.startswith("gg") and top not in shipped:
                    outside.append(module)
    assert outside == []


# ---------------------------------------------------------------------------
# 页面接线（不跑浏览器）
# ---------------------------------------------------------------------------


def test_page_prereloads_the_worker_and_the_sw() -> None:
    """SIL-830：SW 注册与 worker 预载都在 HTML 解析期，不等 `runtime.js` 下载。

    这两条是首屏预算的一部分（warm 的 3 s 里 `runtime.js` 那一个 RTT 就是 170 ms），
    而且顺序有讲究：`controller` 为空时（cold）不许起 worker——那时起了它绕开
    Service Worker，字节进度与 warm 缓存一起丢。
    """
    html = (RUNTIME / "index.html").read_text(encoding="utf-8")
    js = (RUNTIME / "runtime.js").read_text(encoding="utf-8")
    assert 'navigator.serviceWorker.register("./sw.js"' in html
    assert "if (!navigator.serviceWorker.controller) return;" in html
    assert 'new Worker("./worker.js", { type: "module" })' in html
    assert "__ggWorkerSink" in html and "__ggWorkerSink" in js
    # SW 的字节进度同样要在解析期就有一个能收的监听器（warm 的 cache 命中是瞬时的，
    # 装晚了进度就永远停在 87%——这条由 `pyodide:timing` 的 warm 断言兜底）。
    assert "__ggVendorSink" in html and "__ggVendorSink" in js
    # 预载的 worker 出错时不能让 `await ready` 一直悬着。
    assert "__ggWorkerEarlyError" in html and "__ggWorkerEarlyError" in js
    # cold：worker 必须先过 SW 这道门；warm（已有 controller）不停。
    assert "navigator.serviceWorker.controller) return" in js
    assert "await navigator.serviceWorker.ready" in js


def test_service_worker_strips_content_encoding_when_caching() -> None:
    """缓存里是解码后的明文，回放时不能再带 `Content-Encoding: br`。"""
    sw = (RUNTIME / "sw.js").read_text(encoding="utf-8")
    assert '"content-encoding"' in sw or "'content-encoding'" in sw
    assert '"content-length"' in sw or "'content-length'" in sw
    # 缓存名带版本：换过缓存规则（SIL-830 的 zip → tar / gzip → br）之后旧缓存必须
    # 整体作废，否则 warm 会拿到按旧规则存的响应。
    assert 'CACHE = "gg4py-runtime-vendor-v2"' in sw
    assert "caches.delete(key)" in sw


def test_worker_unpacks_a_tar_and_never_waits_for_the_manifest() -> None:
    worker = (RUNTIME / "worker.js").read_text(encoding="utf-8")
    assert 'VENDOR + "gg4py.tar"' in worker
    assert 'unpackArchive(archive, "tar"' in worker
    # manifest 只在 ready 消息里报版本，不进关键路径。
    assert "manifestPromise" in worker
    assert "manifest = await manifestPromise" in worker


def test_boot_assets_are_precompressed(tmp_path: Path) -> None:
    """首屏文件必须带 `.br` 兄弟，且线上字节不超预算。

    判据与 `pixi run pyodide:bytes:check` 同源（同一个 `audit()`），这里只是把它
    也钉在单元测试里，改预算时两边一起红。
    """
    if not (stage.OUT / "manifest.json").is_file():
        pytest.skip("先跑 `pixi run pyodide:assets`")
    bytes_report = _module("gg4py_bytes_report", TOOLS / "pyodide" / "bytes_report.py")
    manifest = bytes_report.load_manifest()
    problems, totals = bytes_report.audit(manifest)
    assert problems == []
    assert totals["boot_wire_bytes"] < totals["boot_bytes"]
    table = bytes_report.entries(manifest)
    assert table["pyodide/pyodide.asm.wasm"]["encoding"] == "br"
    assert table["gg4py.tar"]["encoding"] == "br"
    # 源码包默认是字节码（体积换 import 时间，见 docs/notes/pyodide.md §10）。
    assert manifest["archive"]["bytecode"] is True


def test_page_loads_every_asset_from_vendor() -> None:
    html = (RUNTIME / "index.html").read_text(encoding="utf-8")
    js = (RUNTIME / "runtime.js").read_text(encoding="utf-8")
    worker = (RUNTIME / "worker.js").read_text(encoding="utf-8")
    sw = (RUNTIME / "sw.js").read_text(encoding="utf-8")
    assert 'href="./vendor/fonts.css"' in html
    assert 'src="./runtime.js"' in html
    # 页面与 worker 只从同源 vendor/ 取运行期资产；一个外部 URL 都不许出现。
    for source in (html, js, worker):
        for marker in ("https://", "http://"):
            assert marker not in source.replace("http://127.0.0.1", ""), source[:40]
    assert 'from "./vendor/pyodide/pyodide.mjs"' in worker
    assert 'const SCOPE = "/vendor/"' in sw


def test_demo_needs_match_the_planned_wheels() -> None:
    """示例声明的包 → 页面必须有对应的 wheel 规划，否则进度分母会漏。"""
    js = (RUNTIME / "runtime.js").read_text(encoding="utf-8")
    declared = set()
    for path in sorted((RUNTIME / "demos").glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"demo_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        declared.update(module.needs)
    assert {"numpy", "contourpy", "pandas"} <= declared
    for package in declared:
        assert f"{package}:" in js or f"^ {package}-" in js or package in js


def test_demos_declare_their_heavy_dependencies() -> None:
    def needs(name: str) -> list[str]:
        spec = importlib.util.spec_from_file_location(
            f"demo_{name}", RUNTIME / "demos" / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return list(module.needs)

    assert needs("basic") == ["numpy"]
    assert "contourpy" in needs("contour")
    assert "pandas" in needs("pandas")


# ---------------------------------------------------------------------------
# 验收判据本身（合成数据，不需要浏览器）
# ---------------------------------------------------------------------------


def test_assert_progress_rejects_a_flat_bar() -> None:
    check_runtime = _module("gg4py_check_runtime", TOOLS / "pyodide" / "check_runtime.py")
    run = check_runtime.Run.__new__(check_runtime.Run)
    run.label = "unit"
    run.state = {"progress": {"pct": 1.0}}
    run.progress = [
        {"stage": "runtime", "pct": 0.5},
        {"stage": "runtime", "pct": 0.5},
        {"stage": "run", "pct": 0.5},
    ]
    problems: list[str] = []
    check_runtime.assert_progress(run, problems)
    assert any("从未上升" in problem for problem in problems)


def test_assert_progress_accepts_a_real_ramp() -> None:
    check_runtime = _module("gg4py_check_runtime", TOOLS / "pyodide" / "check_runtime.py")
    run = check_runtime.Run.__new__(check_runtime.Run)
    run.label = "unit"
    run.state = {"progress": {"pct": 1.0}}
    run.progress = [
        {"stage": "runtime", "pct": 0.1},
        {"stage": "archive", "pct": 0.4},
        {"stage": "packages", "pct": 0.8},
        {"stage": "run", "pct": 1.0},
    ]
    problems: list[str] = []
    check_runtime.assert_progress(run, problems)
    assert problems == []


def test_check_runtime_computes_cpython_digests_for_every_demo() -> None:
    check_runtime = _module("gg4py_check_runtime", TOOLS / "pyodide" / "check_runtime.py")
    digests = check_runtime.demo_digests()
    assert set(digests) == {"basic", "contour", "pandas"}
    for name, entry in digests.items():
        assert len(entry["digest"]) == 64, name
        assert entry["bytes"] > 0 and entry["nodes"] > 0
        assert entry["needs"], name


def test_report_written_by_the_checker_is_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check_runtime = _module("gg4py_check_runtime", TOOLS / "pyodide" / "check_runtime.py")
    monkeypatch.setattr(check_runtime, "OUT", tmp_path)
    check_runtime.write_report({"mode": "unit", "ok": True, "problems": [], "wire_bytes": 1})
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "unit"
