"""兜底度量表（M0-7）：无 HarfBuzz 时的逐码点 advance 表。

表由 `tools/metrics/build_table.py` 从**同一份受管字体文件**生成，二进制头里带
`TABLE_VERSION` 与 `RUN_RULES_VERSION`，任何一端规则改动都必须重新生成（版本
不匹配时 `decode_table` 直接拒绝）。生成脚本与读取代码共用本模块的编解码函数，
不存在第二套格式定义。

格式（小端）：

    b"GGMT" | u16 table_version | u16 rules_version | u32 raw_len | zlib(payload)

    payload:
      u16 font_count
      per font:
        u16 name_len | name (utf-8)
        u32 upem | i32 ascent | i32 descent | u16 notdef_advance
        u8  ligates_emoji   (1 = 该字族把 emoji 序列合成一个字形)
        u32 cp_count
        u32[cp_count] codepoints（升序）
        u16[cp_count] advances（字体设计单位）

能力边界（写进 `docs/notes/metrics-ledger.md` · M0-7）：表只做「逐码点 advance +
粘着码点 + grapheme cluster」，不做 kerning / ligature / 连写 / 重排。因此

* CJK 与 emoji 序列是准的（与渲染端差异 < 0.5%）；
* 拉丁文有 kerning 误差（纯拉丁类别实测最大 0.79%，含 `To`/`Sa` 等字对的标签
  整体最大 3.59%）；
* 阿拉伯/希伯来/印度诸语/泰文/朝鲜 jamo 等上下文 shaping 不支持——`supports()`
  返回 False，布局必须改用渲染端实测（这是 L1 的既有口径）。
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ggcore.metrics.provider import FontMetrics, ShapedRun
from ggcore.metrics.runs import RULES_VERSION, clusters, is_glue, is_supported

# 二进制格式版本：布局变化才 +1。
TABLE_VERSION = 1
# 度量规则版本：来自 data/rules.json 的 version。规则一变，旧表的数据口径就不再
# 成立，解码时按版本拒绝（重新生成走 `pixi run metrics:table`）。
RUN_RULES_VERSION = RULES_VERSION

_MAGIC = b"GGMT"
_HEADER = struct.Struct("<4sHHI")
_TABLE_PATH = Path(__file__).with_name("data") / f"metrics_table_v{TABLE_VERSION}.bin"
# 逐码点查找缓存的上限；超了就整体清空（命中率不是关键路径，内存才是）。
_LOOKUP_LIMIT = 100_000
METADATA_PATH = _TABLE_PATH.with_suffix(".json")


@dataclass(frozen=True)
class TableFont:
    """表里一个字体文件的度量与覆盖。"""

    filename: str
    upem: int
    ascent: int
    descent: int
    notdef_advance: int
    ligates_emoji: bool
    codepoints: np.ndarray  # uint32 升序
    advances: np.ndarray  # uint16，与 codepoints 等长

    def metrics(self) -> FontMetrics:
        return FontMetrics(upem=self.upem, ascent=self.ascent, descent=self.descent)


def encode_table(fonts: Sequence[TableFont]) -> bytes:
    """把字体表编码成确定性字节串（同一输入必然同一输出）。"""
    payload = bytearray()
    payload += struct.pack("<H", len(fonts))
    for font in fonts:
        name = font.filename.encode("utf-8")
        codepoints = np.ascontiguousarray(font.codepoints, dtype="<u4")
        advances = np.ascontiguousarray(font.advances, dtype="<u2")
        if codepoints.shape != advances.shape:
            raise ValueError(f"{font.filename}: codepoints and advances differ in length")
        if codepoints.size and not np.all(np.diff(codepoints.astype(np.int64)) > 0):
            raise ValueError(f"{font.filename}: codepoints must be strictly ascending")
        payload += struct.pack(
            "<H",
            len(name),
        )
        payload += name
        payload += struct.pack(
            "<IIiiH",
            font.upem,
            int(codepoints.size),
            font.ascent,
            font.descent,
            int(font.notdef_advance),
        )
        payload += struct.pack("<B", 1 if font.ligates_emoji else 0)
        payload += codepoints.tobytes()
        payload += advances.tobytes()

    compressed = zlib.compress(bytes(payload), level=9)
    return _HEADER.pack(_MAGIC, TABLE_VERSION, RUN_RULES_VERSION, len(payload)) + compressed


def decode_table(blob: bytes) -> tuple[TableFont, ...]:
    """解析度量表；magic/版本不符时抛 `ValueError`（不让旧表悄悄生效）。"""
    if len(blob) < _HEADER.size:
        raise ValueError("metrics table is truncated (no header)")
    magic, table_version, rules_version, raw_len = _HEADER.unpack_from(blob)
    if magic != _MAGIC:
        raise ValueError(f"not a metrics table: magic={magic!r}")
    if table_version != TABLE_VERSION:
        raise ValueError(
            f"metrics table version {table_version} != {TABLE_VERSION}; "
            f"regenerate it with `pixi run metrics:table`"
        )
    if rules_version != RUN_RULES_VERSION:
        raise ValueError(
            f"metrics table was built with run rules v{rules_version}, "
            f"code expects v{RUN_RULES_VERSION}; regenerate it with `pixi run metrics:table`"
        )
    payload = zlib.decompress(blob[_HEADER.size :])
    if len(payload) != raw_len:
        raise ValueError(f"metrics table payload is {len(payload)} bytes, header says {raw_len}")

    offset = 0

    def take(fmt: struct.Struct) -> tuple:
        nonlocal offset
        values = fmt.unpack_from(payload, offset)
        offset += fmt.size
        return values

    (font_count,) = take(struct.Struct("<H"))
    fonts: list[TableFont] = []
    for _ in range(font_count):
        (name_len,) = take(struct.Struct("<H"))
        name = payload[offset : offset + name_len].decode("utf-8")
        offset += name_len
        upem, cp_count, ascent, descent, notdef = take(struct.Struct("<IIiiH"))
        (ligates,) = take(struct.Struct("<B"))
        codepoints = np.frombuffer(payload, dtype="<u4", count=cp_count, offset=offset)
        offset += 4 * cp_count
        advances = np.frombuffer(payload, dtype="<u2", count=cp_count, offset=offset)
        offset += 2 * cp_count
        fonts.append(
            TableFont(
                filename=name,
                upem=upem,
                ascent=ascent,
                descent=descent,
                notdef_advance=notdef,
                ligates_emoji=bool(ligates),
                codepoints=codepoints,
                advances=advances,
            )
        )
    if offset != len(payload):
        raise ValueError(f"metrics table has {len(payload) - offset} trailing bytes")
    return tuple(fonts)


class TableBackend:
    """`MetricsBackend` 的兜底实现：读预生成表，不依赖任何 shaping 库。"""

    name = "table"

    def __init__(self, fonts: Sequence[TableFont]) -> None:
        self.fonts = {font.filename: font for font in fonts}
        if not self.fonts:
            raise ValueError("metrics table is empty")
        self._lookup: dict[tuple[str, int], int | None] = {}

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> TableBackend:
        table_path = Path(path) if path is not None else _TABLE_PATH
        if not table_path.is_file():
            raise FileNotFoundError(
                f"metrics table not found: {table_path}; run `pixi run metrics:table`"
            )
        return cls(decode_table(table_path.read_bytes()))

    # --- MetricsBackend ---------------------------------------------------

    def font_metrics(self, filename: str) -> FontMetrics:
        return self._font(filename).metrics()

    def covers(self, filename: str, codepoint: int) -> bool:
        return self._advance(filename, codepoint) is not None

    def shape(self, filename: str, text: str) -> ShapedRun:
        font = self._font(filename)
        advances: list[float] = []
        for cluster in clusters(text):
            codepoints = [ord(ch) for ch in cluster]
            if font.ligates_emoji and len(codepoints) > 1:
                # 该字族把 emoji 序列合成一个字形：整段只占基码点的宽度。
                advances.append(float(self._advance_or_notdef(font, codepoints[0])))
                continue
            for codepoint in codepoints:
                if is_glue(codepoint):
                    continue
                advances.append(float(self._advance_or_notdef(font, codepoint)))
        return ShapedRun(gids=(), advances=tuple(advances))

    def supports(self, text: str) -> bool:
        return is_supported(text)

    # --- 内部 -------------------------------------------------------------

    def _font(self, filename: str) -> TableFont:
        try:
            return self.fonts[filename]
        except KeyError as exc:
            raise LookupError(f"metrics table has no coverage for {filename!r}") from exc

    def _advance(self, filename: str, codepoint: int) -> int | None:
        key = (filename, codepoint)
        if key in self._lookup:
            return self._lookup[key]
        if len(self._lookup) > _LOOKUP_LIMIT:  # 防止长会话里无界增长
            self._lookup.clear()
        font = self._font(filename)
        index = int(np.searchsorted(font.codepoints, codepoint))
        if index < font.codepoints.size and int(font.codepoints[index]) == codepoint:
            value: int | None = int(font.advances[index])
        else:
            value = None
        self._lookup[key] = value
        return value

    def _advance_or_notdef(self, font: TableFont, codepoint: int) -> int:
        covered = self._advance(font.filename, codepoint)
        return font.notdef_advance if covered is None else covered

    def supported_fonts(self) -> tuple[str, ...]:
        return tuple(self.fonts)


def table_path() -> Path:
    """仓库里提交的度量表路径。"""
    return _TABLE_PATH
