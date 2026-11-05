"""M3-4（SIL-826）：浏览器编辑器的执行契约 `ggcore.script` 与 CSV 输入。

浏览器那一层由 `pixi run editor:check` 在真 Chromium 里验收；这里守的是**两端共用**
的那部分，它们退化时浏览器测试只会变红、不会告诉你为什么：

* `run_script()` 的三种出图写法（`build()` 返回 dict / 返回图对象 / 模块级 `plot`）
  归一成同一条 `build_scene()` 路径；
* 同一段源码跑两次、以及桌面端的一次，IR 必须逐字节相同（`digest` 相等）；
* 错误给的是**用户源文件**的 traceback（不含 `ggcore/script.py` 的内部帧）；
* `detect_needs()` 认 `needs = [...]` 与 `import`，语法错误时不炸；
* `ggio.csv.read_csv()` 的类型推断、缺失值与重名列报错。
"""

from __future__ import annotations

import pytest

from ggcore import ir
from ggcore.script import ScriptError, detect_needs, run_script
from ggio.csv import read_csv

PLOT_SOURCE = """
from ggcore.plot import aes, geom_point, ggplot, labs, theme_minimal
from ggio.frame import to_column_table

needs = ["numpy"]

DATA = {"x": [1, 2, 3, 4], "y": [2.0, 1.0, 4.0, 3.0]}


def build():
    p = (
        ggplot(to_column_table(DATA), aes(x="x", y="y"))
        + geom_point()
        + labs(title="hello")
        + theme_minimal()
    )
    return {"plot": p, "size": [4.0, 3.0]}
"""


def test_run_script_builds_ir_and_is_deterministic() -> None:
    first = run_script(PLOT_SOURCE, filename="hello.py")
    second = run_script(PLOT_SOURCE, filename="hello.py")
    assert first.meta["digest"] == second.meta["digest"]
    assert first.ir_bytes == second.ir_bytes
    assert first.meta["bytes"] == len(first.ir_bytes) > 0
    assert first.meta["nodes"] > 10
    # 场景能解回来（浏览器第一件事就是 decode 这份字节）。
    assert ir.decode(first.ir_bytes).size == (288.0, 216.0)
    assert first.meta["width_in"] == 4.0 and first.meta["height_in"] == 3.0


def test_build_may_return_a_plot_directly() -> None:
    source = """
from ggcore.plot import aes, geom_point, ggplot
from ggio.frame import to_column_table

DATA = {"x": [1, 2, 3], "y": [3, 2, 1]}

def build():
    return ggplot(to_column_table(DATA), aes(x="x", y="y")) + geom_point()
"""
    result = run_script(source, filename="direct.py", size=[4.0, 3.0])
    # 与显式给 size 的写法同一条路径：尺寸来自兜底参数。
    assert (result.meta["width_in"], result.meta["height_in"]) == (4.0, 3.0)
    assert result.meta["bytes"] > 0


def test_module_level_plot_variable_works() -> None:
    source = """
from ggcore.plot import aes, geom_point, ggplot
from ggio.frame import to_column_table

plot = ggplot(to_column_table({"x": [1, 2, 3], "y": [3, 2, 1]}), aes(x="x", y="y")) + geom_point()
"""
    result = run_script(source, filename="plot_var.py")
    assert result.meta["bytes"] > 0


def test_no_plot_is_a_readable_error() -> None:
    with pytest.raises(ScriptError) as info:
        run_script("x = 1\n", filename="empty.py")
    assert "build()" in info.value.message and "plot" in info.value.message


def test_runtime_error_traceback_only_mentions_user_frames() -> None:
    source = "def build():\n    return 1 / 0\n"
    with pytest.raises(ScriptError) as info:
        run_script(source, filename="boom.py")
    error = info.value
    assert error.message.startswith("ZeroDivisionError")
    assert 'File "boom.py", line 2' in error.traceback_text
    # 内部帧不该出现：用户只该看到自己写的那几行。
    assert "ggcore/script.py" not in error.traceback_text
    assert error.line == 2


def test_syntax_error_is_reported_with_line() -> None:
    with pytest.raises(ScriptError) as info:
        run_script("def build(:\n    pass\n", filename="syntax.py")
    error = info.value
    assert "SyntaxError" in error.traceback_text
    assert error.line == 1
    assert 'File "syntax.py", line 1' in error.traceback_text
    # 只出现一次：`format_exception_only()` 自己带 `File` 行，别再补一行。
    assert error.traceback_text.count('File "syntax.py"') == 1


def test_variables_are_injected_without_touching_source_lines() -> None:
    source = """
from ggcore.plot import aes, geom_point, ggplot
from ggio.frame import to_column_table

def build():
    p = ggplot(to_column_table(DATA), aes(x="x", y="y")) + geom_point()
    return {"plot": p, "size": [4.0, 3.0]}
"""
    result = run_script(
        source, filename="inline.py", variables={"DATA": {"x": [1, 2], "y": [2, 1]}}
    )
    assert result.meta["bytes"] > 0
    # 内置数据不让用双下划线名字当预置变量（会盖掉 __name__ / __builtins__ 之类）。
    with pytest.raises(ValueError):
        run_script("", filename="x.py", variables={"__name__": "nope"})


def test_execution_does_not_leak_into_caller_globals() -> None:
    source = "SECRET = 42\ndef build():\n    raise SystemExit('never')\n"
    with pytest.raises(ScriptError):
        run_script(source, filename="leak.py")
    assert "SECRET" not in globals()


def test_detect_needs_reads_declarations_and_imports() -> None:
    source = """
import numpy as np
import pandas as pd
from pyarrow import table
from ggcore.plot import aes

needs = ["numpy", "contourpy"]
"""
    assert detect_needs(source) == ["numpy", "contourpy", "pandas", "pyarrow"] or set(
        detect_needs(source)
    ) == {"numpy", "contourpy", "pandas", "pyarrow"}
    # 语法错误不炸：真正的报错留给 run_script（那里的 traceback 更准）。
    assert detect_needs("def build(:\n") == []
    # 只 import 标准库 / ggcore 自身时不需要额外轮子。
    assert detect_needs("import os\nfrom ggcore.plot import ggplot\n") == []


def test_read_csv_infers_types_and_missing() -> None:
    table = read_csv("x,y,g\n1,2.5,a\n2,,b\n3,4.0,a\n")
    assert table.names == ("x", "y", "g")
    assert table.nrows == 3
    assert table.column("x").kind == "int"
    assert table.column("y").kind == "float"
    assert table.column("g").kind == "str"
    assert table.column("g").levels == ("a", "b")
    assert table.column("y").na_mask.tolist() == [False, True, False]


def test_read_csv_rejects_duplicate_and_ragged_rows(tmp_path) -> None:
    with pytest.raises(ValueError, match="重名"):
        read_csv("a,a\n1,2\n")
    with pytest.raises(ValueError, match="字段"):
        read_csv("a,b\n1,2\n3\n")
    # 空文件与空表头也要说清是什么问题。
    with pytest.raises(ValueError, match="空"):
        read_csv("\n\n")


def test_read_csv_reads_a_path(tmp_path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("k,v\none,1\nthree,3\n", encoding="utf-8")
    table = read_csv(path)
    assert table.nrows == 2
    assert list(table.column("v").values) == [1.0, 3.0]
