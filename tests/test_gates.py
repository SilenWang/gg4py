"""门禁自测：X1 的门在“错误代码”上必须失败，在正确代码上必须通过。

这些用例把违规样例种到 tmp 目录里跑真实脚本（子进程），所以门禁失效比
“某人记得手测一次”更早被发现。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ggcore import __version__
from ggcore.ir import decode, demo_scene, encode

REPO = Path(__file__).resolve().parent.parent
GATES = REPO / "tools" / "gates"


def run_gate(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATES / script), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def plant(tmp_path: Path, source: str, name: str = "planted.py") -> Path:
    root = tmp_path / "pkg"
    root.mkdir(exist_ok=True)
    (root / name).write_text(source, encoding="utf-8")
    return root


# --- X1 · import 白名单 ----------------------------------------------------


def test_import_gate_passes_on_the_real_package() -> None:
    result = run_gate("check_import_whitelist.py")
    assert result.returncode == 0, result.stderr
    assert "gate:imports: ok" in result.stdout


def test_import_gate_allows_stdlib_and_numpy(tmp_path: Path) -> None:
    root = plant(tmp_path, "import json\nimport numpy as np\nfrom numpy.typing import NDArray\n")
    result = run_gate("check_import_whitelist.py", "--root", str(root))
    assert result.returncode == 0, result.stderr


def test_import_gate_allows_contourpy_for_the_2d_stats(tmp_path: Path) -> None:
    # M2-6：contourpy 进白名单（等值线是 stat 的内核，不是设备）；理由与 Pyodide
    # 可用性记录在 docs/notes/gates.md。
    root = plant(tmp_path, "import contourpy\nimport numpy as np\n")
    result = run_gate("check_import_whitelist.py", "--root", str(root))
    assert result.returncode == 0, result.stderr


def test_import_gate_rejects_a_single_bad_import(tmp_path: Path) -> None:
    root = plant(tmp_path, "import os\nimport pandas as pd\n")
    result = run_gate("check_import_whitelist.py", "--root", str(root))
    assert result.returncode == 1
    assert "forbidden import 'pandas'" in result.stderr
    assert "planted.py:2" in result.stderr


def test_import_gate_rejects_relative_import_escape(tmp_path: Path) -> None:
    # 相对导入留在包内，不算越界；越界的是绝对导入到包外模块。
    root = plant(tmp_path, "from .helpers import x\nfrom skia import Canvas\n")
    result = run_gate("check_import_whitelist.py", "--root", str(root))
    assert result.returncode == 1
    assert "forbidden import 'skia'" in result.stderr
    assert "helpers" not in result.stderr


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\n\n\ndef load():\n    return importlib.import_module('pandas')\n",
        "import importlib as il\n\n\ndef load():\n    return il.import_module('pandas')\n",
        "from importlib import import_module as load_mod\n\n\n"
        "def load():\n    return load_mod('pandas')\n",
        "import importlib.util\n\n\ndef load():\n    return importlib.import_module('pandas')\n",
        "from builtins import __import__ as imp\n\n\ndef load():\n    return imp('pandas')\n",
        "def load():\n    return __import__('pandas')\n",
        "import importlib\n\n\ndef load(name):\n    return importlib.import_module(name)\n",
        # 赋值别名：把函数对象存进另一个名字，再调用。
        "import importlib\n\n\nf = importlib.import_module\n\n\ndef load():\n"
        "    return f('pandas')\n",
        # 别名成链：f → g，门禁要迭代到不动点。
        "import importlib\n\n\nf = importlib.import_module\ng = f\n\n\ndef load():\n"
        "    return g('pandas')\n",
        # 字面量取属性，直接当调用目标。
        "import importlib\n\n\ndef load():\n"
        "    return getattr(importlib, 'import_module')('pandas')\n",
        # 字面量取属性先存成别名。
        "import importlib as il\n\n\nf = getattr(il, 'import_module')\n\n\ndef load():\n"
        "    return f('pandas')\n",
        # from-import 之后再赋值一次。
        "from importlib import import_module\n\n\ng = import_module\n\n\ndef load():\n"
        "    return g('pandas')\n",
        # 内置 __import__ 的赋值别名。
        "importer = __import__\n\n\ndef load():\n    return importer('pandas')\n",
        # `.__call__` 只是把同一个目标再交出来一次，不能当成“又间接了一层”。
        "import importlib\n\n\nf = importlib.import_module\n\n\ndef load():\n"
        "    return f.__call__('pandas')\n",
        "import importlib\n\n\nf = importlib.import_module\n\n\ndef load():\n"
        "    return getattr(f, '__call__')('pandas')\n",
        "import importlib\n\n\ndef load():\n"
        "    return getattr(getattr(importlib, 'import_module'), '__call__')('pandas')\n",
        # 属性链直呼：`importlib.import_module.__call__`。
        "import importlib\n\n\ndef load():\n"
        "    return importlib.import_module.__call__('pandas')\n",
        # `.__call__` 也能存成别名，再成链。
        "import importlib\n\n\nf = importlib.import_module\ng = f.__call__\n\n\ndef load():\n"
        "    return g('pandas')\n",
        # 非字面量同样拦（归约之后仍取不到模块名）。
        "import importlib\n\n\nf = importlib.import_module\n\n\ndef load(name):\n"
        "    return f.__call__(name)\n",
    ],
)
def test_import_gate_rejects_dynamic_imports(tmp_path: Path, source: str) -> None:
    # 模块名藏在字符串里（或根本取不到）时，import 语句扫描看不见，门禁必须另拦。
    root = plant(tmp_path, source)
    result = run_gate("check_import_whitelist.py", "--root", str(root))
    assert result.returncode == 1, result.stdout
    assert "pandas" in result.stderr or "non-literal" in result.stderr


def test_import_gate_allows_literal_dynamic_import_of_a_whitelisted_module(
    tmp_path: Path,
) -> None:
    root = plant(
        tmp_path,
        "import importlib\n\n\ndef load():\n    return importlib.import_module('numpy')\n",
    )
    result = run_gate("check_import_whitelist.py", "--root", str(root))
    assert result.returncode == 0, result.stderr


def test_import_gate_allows_alias_of_a_whitelisted_module(tmp_path: Path) -> None:
    root = plant(
        tmp_path,
        "import importlib\n\n\nf = importlib.import_module\n\n\ndef load():\n"
        "    return f('numpy')\n",
    )
    result = run_gate("check_import_whitelist.py", "--root", str(root))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source",
    [
        # 自定义类实例的 `obj.__call__(...)`：和 `obj(...)` 是同一个目标，不是导入。
        "class Renderer:\n"
        "    def __call__(self, name):\n"
        "        return name\n"
        "\n"
        "\n"
        "obj = Renderer()\n"
        "\n"
        "\n"
        "def load():\n"
        "    return obj.__call__('pandas')\n",
        # 白名单模块：剥掉 `.__call__` 之后仍是同一次导入，必须放行。
        "import importlib\n\n\ndef load():\n    return importlib.import_module.__call__('numpy')\n",
    ],
)
def test_import_gate_allows_call_wrappers_outside_the_blocked_set(
    tmp_path: Path, source: str
) -> None:
    """放行侧：归约 `.__call__` 只能把目标还原成“同一个东西”，不能把非导入目标
    也算成导入，也不能把白名单导入算成越界。拦截侧保证不了这一侧——
    `test_import_gate_rejects_dynamic_imports` 本组共 19 条，其中 6 条来自 SIL-607。
    """
    root = plant(tmp_path, source)
    result = run_gate("check_import_whitelist.py", "--root", str(root))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source",
    [
        # operator.attrgetter 把属性名交给一个库里函数，AST 上看不到调用与名字的连线。
        "import importlib\nimport operator\n\n\ndef load():\n"
        "    return operator.attrgetter('import_module')(importlib)('pandas')\n",
        # 属性名在运行时才拼出来，字面量规则取不到。
        "import importlib\n\n\ndef load(name='import_module'):\n"
        "    return getattr(importlib, name)('pandas')\n",
        # functools.partial 把函数对象藏进参数里，门禁只认“调用目标”。
        "import functools\nimport importlib\n\n\ndef load():\n"
        "    return functools.partial(importlib.import_module, 'pandas')()\n",
        # eval / exec 的代码在字符串里，静态扫描按设计不看字符串里的源码。
        "def load():\n    return eval(\"__import__('pandas')\")\n",
    ],
)
def test_import_gate_documented_boundary_still_passes(tmp_path: Path, source: str) -> None:
    """保证范围的边界（docs/notes/gates.md）：这几类再间接一层的写法静态扫描覆盖不到。

    这条用例不是在证明门禁“拦得住”，而是把已知漏口钉在原地：哪天门禁扩张到能
    拦它们，这里会先红，提醒同步改文档与保证范围。
    """
    root = plant(tmp_path, source)
    result = run_gate("check_import_whitelist.py", "--root", str(root))
    assert result.returncode == 0, result.stderr


# --- X1 · IR 禁止逐元素 JSON ----------------------------------------------


def test_ir_json_gate_passes_on_the_real_package() -> None:
    result = run_gate("check_ir_json.py")
    assert result.returncode == 0, result.stderr


def test_ir_json_gate_allows_binary_packing(tmp_path: Path) -> None:
    source = (
        "import struct\n"
        "\n"
        "\n"
        "def pack(values):\n"
        "    return struct.pack(f'<{len(values)}f', *values)\n"
    )
    root = plant(tmp_path, source)
    result = run_gate("check_ir_json.py", "--root", str(root))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source",
    [
        "import json\n\n\ndef dump(scene):\n    return json.dumps(scene)\n",
        "from json import dumps as encode\n\n\ndef dump(scene):\n    return encode(scene)\n",
        "import orjson\n\n\ndef dump(scene):\n    return orjson.dumps(scene)\n",
        "import json as j\n\n\ndef dump(scene):\n    return j.dumps(scene)\n",
        "import orjson as oj\n\n\ndef dump(scene):\n    return oj.dump(scene)\n",
        "import json as j\n\n\ndef encoder():\n    return j.JSONEncoder()\n",
        "def dump(scene):\n    return scene.to_json()\n",
    ],
)
def test_ir_json_gate_rejects_json_serialisation(tmp_path: Path, source: str) -> None:
    root = plant(tmp_path, source)
    result = run_gate("check_ir_json.py", "--root", str(root))
    assert result.returncode == 1, result.stdout
    assert "per-element JSON" in result.stderr


# --- X1 · 同输入同字节 ----------------------------------------------------


def test_determinism_gate_is_stable_on_the_repo() -> None:
    result = run_gate("check_determinism.py")
    assert result.returncode == 0, result.stderr
    assert "gate:determinism: ok" in result.stdout
    assert "sha256=" in result.stdout


def test_demo_scene_serialises_stably() -> None:
    data = encode(demo_scene())
    assert encode(demo_scene()) == data
    assert decode(data) == demo_scene()
    assert encode(decode(data)) == data


def test_version_is_exported() -> None:
    assert __version__.count(".") == 2
