"""IR v0 的异常族。

分三类，调用方可以按需要粗粒度或细粒度捕获：

- `IRValidationError`：构造节点/scene 时字段不合法（编码方问题）。
- `IRDecodeError`：线格式本身有问题（缺 magic、截断、字段类型不对、未知节点）。
- `IRVersionError`：版本不认识（`IRDecodeError` 的子类，便于“只捕版本问题”）。

全部继承 `IRError`，渲染/差分路径只需捕一个基类。
"""

from __future__ import annotations


class IRError(Exception):
    """IR 相关错误的基类。"""


class IRValidationError(IRError, ValueError):
    """构造 IR 时字段不合法（类型、形状、取值范围、交叉约束）。"""


class IRDecodeError(IRError):
    """线格式无法解码。"""


class IRVersionError(IRDecodeError):
    """`ir_version` 的 major 不认识；解码方必须拒绝而不是猜。"""
