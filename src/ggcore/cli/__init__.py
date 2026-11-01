"""命令行入口。

`render` / `diff` 在 M0-1 只是占位实现：参数解析与退出码是真实的，执行到
“还没有渲染器/比对器”时以非 0 退出并说明由哪个阶段补齐。任务名
（`pixi run render` / `pixi run diff`）由后续阶段直接接线，不要改名。
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
