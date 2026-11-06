"""plotmath 子集：`geom_text(parse = TRUE)` 的表达式解析与排版（SIL-839）。

R 的 plotmath 是 grid 的排版语言：`parse()` 把字符串变成 expression，再由
`textGrob()` 的 `widthDetails` / `heightDetails` 排版。这里只实现复刻上游快照
（`geom-text/geom-text-with-expressions.svg`）需要的那一小撮：

| 语法 | 行为 |
| --- | --- |
| `alpha` / `beta` / `gamma` … | 希腊字母（Unicode 直出；svglite 也写 `α` 这类字符） |
| `a + b` / `a - b` | 二元运算符，两侧各留 `0.185em`（快照实测） |
| `a * b` | 并置，无间距 |
| `a^b` | 上标：`0.7` 倍字号、基线上抬 `0.502em`（快照实测） |
| `a[b]` | 下标：`0.7` 倍字号、基线下沉 `0.502em` |
| `sqrt(x)` | 根号：5 点折线（宽 `1.019em`，被开方内容从 `0.519em` 起） |

解析不了的输入**不报错**：退回普通文本（R 的 `parse_safe()` 也是这个口径）。

排版结果是一组 :class:`TextRun`（不同字号 / 抬升的文本段）加一组
:class:`Polyline`（根号），坐标都是「相对标签左边界、相对主行基线、向上为正」
的 em 值；pt / npc 的换算留给调用方（`ggcore.geom.text`）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BINARY_SPACE_EM",
    "DESCENT_EM",
    "SUBSCRIPT_CEX",
    "SUPERSCRIPT_CEX",
    "MathLabel",
    "MathText",
    "Polyline",
    "TextRun",
    "extent",
    "is_math",
    "layout",
    "measure_from",
    "parse",
    "wrap",
]

#: 上标 / 下标的字号倍率（R 的 plotmath 固定 0.7）。
SUPERSCRIPT_CEX = 0.7
SUBSCRIPT_CEX = 0.7
#: 上标抬升 / 下标下沉（em，相对**当前**字号）。11pt 的快照里实测 5.52pt。
SCRIPT_SHIFT_EM = 0.502
#: 二元运算符两侧的空白（em）。快照里 `α + β` 的间隙各 2.03pt / 11pt。
BINARY_SPACE_EM = 0.185
#: 根号整体宽度与被开方内容的起点（em）。快照里 11.21pt / 5.71pt，除以 11pt。
RADICAL_WIDTH_EM = 1.0191
RADICAL_BODY_EM = 0.5191
#: 根号的折线（em；y 向上为正、主行基线为 0），按同一份快照的 5 个点归一化。
RADICAL_POINTS = (
    (0.0, 0.2845),
    (0.1236, 0.3555),
    (0.2482, -0.0118),
    (0.4127, 0.9355),
    (RADICAL_WIDTH_EM, 0.9355),
)
#: 根号的描边宽度（pt，与字号无关；R 里是 `lwd = 0.75`）。
RADICAL_LWD = 0.75
#: 主行的 ascent（em）。排版只需要它来算上标有没有把标签顶高。
ASCENT_EM = 0.71
#: 主行基线以下的 descent（em）。R 的 plotmath 行盒按「上标顶 + 主行底」量：
#: 8.8pt 的 `10^2` 在上游 `guide-axis/guides-with-minor-ticks` 里高 10.64pt
#: （axis-b 行 = 12.84pt 含 2.2pt margin），其中基线以上 0.999em、以下 0.21em。
DESCENT_EM = 0.21
#: 没有度量实现时的每字符宽（em，与 `ggcore.axis.FALLBACK_CHAR_EM` 同一口径）。
FALLBACK_CHAR_EM = 0.6


class MathText(str):
    """标记为 plotmath 的文本：值仍是源串，解析不了时它就是回退的普通文本。

    `str` 子类让整条流水线（标度标签 → 轴 guide / strip → grob）继续当字符串用，
    只有量尺寸与落字的两处按 :func:`layout` 展开——IR 里因此是「一段 plotmath
    拆成多个 text 节点」，不需要给 text 节点加「段」信息。
    """

    __slots__ = ()


def is_math(value: Any) -> bool:
    """`value` 是不是 plotmath 标签（`MathText`）。"""
    return isinstance(value, MathText)


def wrap(text: Any) -> str:
    """把 `text` 包成 plotmath 标签；解析不了时原样返回普通 `str`（同 `parse_safe()`）。"""
    source = str(text)
    return MathText(source) if is_plausible(source) else str(source)


#: plotmath 的希腊字母表（含大写）。
GREEK: dict[str, str] = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "omicron": "ο",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Alpha": "Α",
    "Beta": "Β",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
}

#: 直接透传的字形（这些名字在 plotmath 里不是变量）。
SYMBOLS: dict[str, str] = {
    "infinity": "∞",
    "degree": "°",
    "cdot": "·",
    "times": "×",
    "pm": "±",
    "leq": "≤",
    "geq": "≥",
    "neq": "≠",
    "approx": "≈",
    "prime": "′",
}
#: 二元运算符（两侧留空白）。
BINARY_OPS = {"+": "+", "-": "−", "==": "=", "!=": "≠", "<": "<", ">": ">"}


@dataclass(frozen=True, slots=True)
class TextRun:
    """一段同字号、同基线的文本。`x_em` 相对标签左边界。"""

    text: str
    x_em: float
    rise_em: float = 0.0
    cex: float = 1.0

    @property
    def top_em(self) -> float:
        """这段文本的顶边（em，相对主行基线）。"""
        return self.rise_em + self.cex * ASCENT_EM


@dataclass(frozen=True, slots=True)
class Polyline:
    """根号一类的折线（em，相对标签左边界、主行基线，向上为正）。"""

    points: tuple[tuple[float, float], ...]
    lwd: float = RADICAL_LWD


@dataclass(frozen=True, slots=True)
class MathLabel:
    """一个标签的排版结果。"""

    width_em: float
    #: 上标把标签顶高出来的部分（em）；调用方拿它算整块高度。
    extra_ascent_em: float
    runs: tuple[TextRun, ...]
    rules: tuple[Polyline, ...]
    #: 基线以上的高度（em）：`max(rise + cex · ASCENT)`，至少一个主行。
    ascent_em: float = ASCENT_EM
    #: 基线以下的高度（em）。
    descent_em: float = DESCENT_EM

    @property
    def height_em(self) -> float:
        """整块高度（em）：ascent + descent（R 的 `stringHeight()` 口径）。"""
        return self.ascent_em + self.descent_em


Measure = Callable[[str, float], float]


class _ParseError(ValueError):
    pass


class _Parser:
    """极简递归下降：`expr := term (('+'|'-') term)*`、`term := factor ('*' factor)*`。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0

    def parse(self) -> list:
        nodes = self.expression()
        self.skip_space()
        if self.index < len(self.text):
            raise _ParseError(f"多余的字符 {self.text[self.index :]!r}")
        return nodes

    def peek(self) -> str:
        return self.text[self.index] if self.index < len(self.text) else ""

    def skip_space(self) -> None:
        while self.index < len(self.text) and self.text[self.index].isspace():
            self.index += 1

    def accept(self, *chars: str) -> str | None:
        self.skip_space()
        for char in chars:
            if self.text.startswith(char, self.index):
                self.index += len(char)
                return char
        return None

    def expression(self) -> list:
        nodes = self.term()
        while True:
            op = self.accept("+", "-")
            if op is None:
                return nodes
            nodes.extend([("bin", op), *self.term()])

    def term(self) -> list:
        nodes = self.factor()
        while True:
            if self.accept("*") is not None:
                nodes.extend([("juxt",), *self.factor()])
                continue
            # 隐式并置：`2 alpha` 这种（plotmath 里 `*` 也可省）。
            self.skip_space()
            char = self.peek()
            if char and (char.isdigit() or char in "(" or char.isalpha()):
                nodes.extend([("juxt",), *self.factor()])
                continue
            return nodes

    def factor(self) -> list:
        nodes = [self.atom()]
        while True:
            if self.accept("^") is not None:
                nodes = [("script", 1, nodes, [self.atom()])]
                continue
            if self.accept("[") is not None:
                inner = self.expression()
                self.skip_space()
                if self.accept("]") is None:
                    raise _ParseError("`[` 没有配对的 `]`")
                nodes = [("script", -1, nodes, inner)]
                continue
            return nodes

    def atom(self):
        self.skip_space()
        char = self.peek()
        if not char:
            raise _ParseError("表达式意外结束")
        if char == "(":
            self.index += 1
            inner = self.expression()
            self.skip_space()
            if self.accept(")") is None:
                raise _ParseError("`(` 没有配对的 `)`")
            return ("group", inner)
        if char in "\"'":
            quote = char
            end = self.text.find(quote, self.index + 1)
            if end < 0:
                raise _ParseError("引号没有配对")
            value = self.text[self.index + 1 : end]
            self.index = end + 1
            return ("text", value)
        if char.isdigit() or char == ".":
            start = self.index
            while self.peek() and (self.peek().isdigit() or self.peek() == "."):
                self.index += 1
            return ("text", self.text[start : self.index])
        if char.isalpha() and char.isascii():
            start = self.index
            while self.peek() and (self.peek().isalnum() or self.peek() in "._"):
                self.index += 1
            name = self.text[start : self.index]
            self.skip_space()
            if self.peek() == "(":
                self.index += 1
                return ("call", name, self.call_args())
            return ("ident", name)
        raise _ParseError(f"不认识的字符 {char!r}")

    def call_args(self) -> list[list]:
        args: list[list] = []
        self.skip_space()
        if self.accept(")") is not None:
            return args
        while True:
            args.append(self.expression())
            self.skip_space()
            if self.accept(")") is not None:
                return args
            if self.accept(",") is None:
                raise _ParseError("函数调用只认 `,` 分隔")


def parse(text: str) -> list:
    """把 plotmath 字符串解析成节点列表；语法不合法时抛 `_ParseError`。"""
    return _Parser(text).parse()


def layout(text: str, *, fontsize: float, measure: Measure) -> MathLabel:
    """把 `text` 排成一个 :class:`MathLabel`（全部是 em 坐标）。

    `measure(text, size_pt)` 返回该字符串在 `size_pt` 下的宽度（pt）。
    """
    runs: list[TextRun] = []
    rules: list[Polyline] = []
    pen = 0.0
    for node in parse(text):
        pen += _place(node, measure, fontsize, 1.0, 0.0, pen, runs, rules)
    ascent = max((run.top_em for run in runs), default=ASCENT_EM)
    return MathLabel(
        width_em=pen,
        extra_ascent_em=max(0.0, ascent - ASCENT_EM),
        runs=tuple(runs),
        rules=tuple(rules),
        ascent_em=ascent,
        descent_em=DESCENT_EM,
    )


def measure_from(metrics: Any, family: str = "") -> Measure:
    """`ggcore.units.Metrics`（英寸）→ :data:`Measure`（pt）。

    `metrics` 为 `None` 时按 :data:`FALLBACK_CHAR_EM` 估（与 `text_width_cm()`
    没有度量时的口径一致），版面不会因为缺度量塌成 0。
    """
    if metrics is None:

        def estimate(text: str, size_pt: float) -> float:
            return FALLBACK_CHAR_EM * float(size_pt) * len(text)

        return estimate

    def measure(text: str, size_pt: float) -> float:
        return (
            float(metrics.strwidth(text, fontsize=float(size_pt), cex=1.0, font=str(family))) * 72.0
        )

    return measure


def extent(text: str, *, fontsize: float, measure: Measure) -> tuple[float, float, float]:
    """`(宽, 基线以上, 基线以下)`，单位 pt。"""
    label = layout(text, fontsize=fontsize, measure=measure)
    return (
        label.width_em * fontsize,
        label.ascent_em * fontsize,
        label.descent_em * fontsize,
    )


def _glyph(node, measure: Measure, size: float, cex: float) -> str:
    name = node[1]
    if node[0] == "ident":
        return GREEK.get(name) or SYMBOLS.get(name) or name
    return name


def _place(
    node,
    measure: Measure,
    size: float,
    cex: float,
    rise: float,
    x: float,
    runs: list[TextRun],
    rules: list[Polyline],
) -> float:
    """把 `node` 排到 `runs` / `rules`，返回它占的宽度（em）。`x` 是当前笔位。"""
    kind = node[0]
    if kind in ("text", "ident"):
        text = _glyph(node, measure, size, cex)
        if not text:
            return 0.0
        runs.append(TextRun(text, x, rise, cex))
        return measure(text, size * cex) / size
    if kind == "group":
        pen = x
        for child in node[1]:
            pen += _place(child, measure, size, cex, rise, pen, runs, rules)
        return pen - x
    if kind == "bin":
        symbol = BINARY_OPS.get(node[1], node[1])
        pen = x + BINARY_SPACE_EM
        runs.append(TextRun(symbol, pen, rise, cex))
        pen += measure(symbol, size * cex) / size + BINARY_SPACE_EM
        return pen - x
    if kind == "juxt":
        return 0.0
    if kind == "script":
        direction, base_nodes, script_nodes = node[1], node[2], node[3]
        pen = x
        for child in base_nodes:
            pen += _place(child, measure, size, cex, rise, pen, runs, rules)
        script_cex = cex * (SUPERSCRIPT_CEX if direction > 0 else SUBSCRIPT_CEX)
        script_rise = rise + direction * SCRIPT_SHIFT_EM * cex
        for child in script_nodes:
            pen += _place(child, measure, size, script_cex, script_rise, pen, runs, rules)
        return pen - x
    if kind == "call":
        name, args = node[1], node[2]
        if name == "sqrt" and args:
            pen = x + RADICAL_BODY_EM
            for child in args[0]:
                pen += _place(child, measure, size, cex, rise, pen, runs, rules)
            width = max(RADICAL_WIDTH_EM, pen - x)
            rules.append(Polyline(tuple((x + px, py + rise) for px, py in RADICAL_POINTS)))
            return width
        # 不认识的函数：按普通文本画名字（`parse_safe()` 的口径是整串回退，
        # 这里只退化这一段，够用）。
        runs.append(TextRun(name, x, rise, cex))
        return measure(name, size * cex) / size
    raise _ParseError(f"未知节点 {kind!r}")


def is_plausible(text: str) -> bool:
    """字符串能不能当 plotmath 解析（`parse=TRUE` 的回退判定）。"""
    try:
        parse(text)
    except (_ParseError, RecursionError, ValueError):
        return False
    return True
