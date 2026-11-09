"""SIL-911 · `gg4py` 顶层入口：单源投影、懒加载与子命名空间。

顶层名字是可执行的事实，不是一份手抄清单：

- `gg4py.__all__` 是 `ggcore.plot.__all__` 的现算投影，所以**新登记的组件
  自动出现在顶层**（下面用一条临时注册守住）；
- `ggsave` 不在包顶层 import `ggskia`（X1：`ggcore` 不能 import 渲染后端），
  没有 skia 的环境里 `import gg4py` 必须成功；
- `gg4py.io` / `gg4py.ir` / `gg4py.diff` 是开发者 API 的转发壳，不进 `__all__`。

口径与迁移示例：`docs/notes/public-api.md`。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import gg4py
import ggcore.io
import ggcore.ir
import ggcore.plot
from ggcore import registry
from ggio import frame

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"

#: 用户从 `gg4py` 直接取的核心名字。注册表项另由下面的循环逐个核对。
CORE_NAMES = (
    "ggplot",
    "aes",
    "labs",
    "guides",
    "from_arrow",
    "from_dict",
    "from_pandas",
    "to_column_table",
)


def run_python(code: str) -> subprocess.CompletedProcess[str]:
    """在干净的解释器里跑一段代码（`gg4py` 的导入副作用只在这里观察）。"""
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_top_level_names_are_a_projection_of_ggcore_plot() -> None:
    exported = set(gg4py.__all__)
    assert set(ggcore.plot.__all__) <= exported
    assert set(CORE_NAMES) <= exported
    assert {"ggsave", "__version__"} <= exported
    # 现算的清单：没有重复项（重复会让 `from gg4py import *` 与文档核对都失真）。
    assert len(gg4py.__all__) == len(exported)


def test_every_registry_entry_is_the_same_object_at_the_top_level() -> None:
    """「一条注册表，三个入口」：模块级、ggplot 方法与 `gg4py` 顶层同一对象。"""
    for kind in registry.KINDS:
        for name in registry.registered(kind):
            entry = registry.entry_name(kind, name)
            assert entry in gg4py.__all__, entry
            assert getattr(gg4py, entry) is getattr(ggcore.plot, entry), entry


def test_adapters_come_from_ggio_frame() -> None:
    callable_names = {name for name in frame.__all__ if callable(getattr(frame, name))}
    assert callable_names == set(CORE_NAMES[4:])
    assert callable_names <= set(gg4py.__all__)
    # 说明性常量不是入口，不提升到顶层。
    assert "SUPPORTED_INPUTS" not in gg4py.__all__


def test_newly_registered_component_appears_at_the_top_level_without_edits() -> None:
    """加一个组件只改注册表：`gg4py` 的 `__all__` 与属性自动跟上。"""

    def probe(**kwargs):
        return registry.construct("geom", "point", **kwargs)

    registry.register("geom", "sil911probe", probe)
    try:
        assert "geom_sil911probe" in gg4py.__all__
        entry = gg4py.geom_sil911probe
        assert callable(entry)
        plot = gg4py.ggplot({"x": [1.0], "y": [2.0]}, gg4py.aes(x="x", y="y"))
        assert len((plot + entry()).layers) == 1
        assert callable(plot.geom_sil911probe)
    finally:
        registry.unregister("geom", "sil911probe")

    assert "geom_sil911probe" not in gg4py.__all__
    with pytest.raises(AttributeError, match="geom_sil911probe"):
        _ = gg4py.geom_sil911probe


def test_ggsave_is_lazy_and_shared_with_ggcore_io() -> None:
    result = run_python(
        "import sys\n"
        "import gg4py\n"
        "assert 'ggskia' not in sys.modules, 'gg4py 顶层不该导入渲染后端'\n"
        "assert 'ggsave' in gg4py.__all__\n"
        "import ggcore.io\n"
        "assert gg4py.ggsave is ggcore.io.ggsave\n"
        "assert 'ggskia' in sys.modules\n"
        "print('ok')\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_import_gg4py_succeeds_without_skia() -> None:
    code = (
        "import sys\n"
        "class BlockSkia:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'skia' or name.startswith('skia.'):\n"
        '            raise ModuleNotFoundError(f"No module named {name!r}", name=name)\n'
        "        return None\n"
        "sys.meta_path.insert(0, BlockSkia())\n"
        "import gg4py\n"
        "assert gg4py.__version__\n"
        "assert 'ggsave' in gg4py.__all__\n"
        "import ggcore.io\n"
        "assert gg4py.ggsave is ggcore.io.ggsave, '没有 skia 时应回落到 ggcore.io'\n"
        "assert 'ggskia' not in sys.modules\n"
        "p = gg4py.ggplot({'x': [1.0, 2.0]}, gg4py.aes(x='x')) + gg4py.geom_point()\n"
        "assert len(p.layers) == 1\n"
        "print('ok')\n"
    )
    result = run_python(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_sub_namespaces_forward_to_the_canonical_modules() -> None:
    assert gg4py.io.save_ir is ggcore.io.save_ir
    assert gg4py.io.ggsave is ggcore.io.ggsave
    assert gg4py.ir.encode is ggcore.ir.encode
    # 开发者 API 不挤进顶层 `from gg4py import *`。
    assert {"io", "ir", "diff"}.isdisjoint(gg4py.__all__)

    import ggdiff

    assert gg4py.diff.compare_images is ggdiff.compare_images


def test_star_import_exposes_the_registry() -> None:
    namespace: dict[str, object] = {}
    exec("from gg4py import *", namespace)
    assert namespace["ggplot"] is gg4py.ggplot
    assert namespace["geom_point"] is gg4py.geom_point
    assert set(gg4py.__all__) <= set(namespace)
