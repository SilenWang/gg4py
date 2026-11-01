"""命令行辅助（`ggcore` 内的那一半）。

`render` 已经在 M0-8 接线，入口在 `ggskia.cli.render`——skia 后端在包外
（X1 门禁），CLI 跟着后端走；任务名仍然是 M0-1 定的 `pixi run render`。

`diff` 在 M0-9 落地，入口在 `ggdiff.cli`：差分要读 PNG（Pillow）、调 resvg
（子进程）、打 JSON，这些都不在 `ggcore` 的白名单里。`ggcore` 只提供无损的
IR 与案例适配层（`ggcore.plotspec`），比对器与光栅化留在包外。
"""

from __future__ import annotations

import sys

# 占位实现的退出码：与 lint/测试失败（1）区分开，便于 CI 与脚本判断。
EXIT_NOT_IMPLEMENTED = 3


def unimplemented(tool: str, milestone: str, hint: str) -> int:
    """打印“尚未实现”并返回占位退出码。"""
    print(f"gg4py {tool}: not implemented yet ({milestone}).", file=sys.stderr)
    print(f"  {hint}", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED
