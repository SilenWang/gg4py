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
