#!/usr/bin/env python
"""gallery.html 的唯一渲染实现，两个生成器共用（SIL-893）。

同一份卡片契约有两条产线：

| 产线 | 谁在写 | 缩略图来自 | 需要 Chromium |
| --- | --- | --- | --- |
| `pixi run viewer:cases` | `tools/viewer/cases.py` | viewer 自己渲染后的 Chromium 截图 | 是 |
| `pixi run viewer:gallery` | `tools/viewer/gallery_build.py` | 仓内的 `docs/cases/<case>/expected.svg` | 否 |

卡片契约（`tools/viewer/gallery_check.py` 逐条请求的就是它）：

- 卡片标题 `<h2>` 就是 case 名；
- 卡片链到 `../index.html?scene=gallery/<case>.ggir.cbor`（scene 按 viewer 根目录解析）；
- 缩略图 `../gallery/<case><suffix>`。

资产目录由 `gallery_assets_dir()` 决定，两条产线一致：`gallery.html` 在
`<viewer>/dist/` 下，但链接按 viewer 根目录解析，所以图片 / IR 落
`<viewer>/gallery/`。
"""

from __future__ import annotations

import html
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# gallery.html 的 CSS 是内联的（单文件、零依赖），长行是有意的。
# ruff: noqa: E501

# 每条产线的卡片状态。`static` 是 SIL-893 的静态 gallery 专用：缩略图是 R 产线的
# 参考图，**没做过像素验证**，所以不借 `pass` 的绿边（那会看起来像验证过了）。
GLYPHS = {"pass": "✅", "fail": "❌", "error": "⛔", "skip": "⏭", "static": "🖼"}


@dataclass
class Card:
    """gallery.html 的一张卡片（与产线无关的部分）。"""

    case: str
    family: str = ""
    status: str = "static"
    elements: int = 0
    diff: float | None = None
    mean: float | None = None
    detail: str = ""
    # 仓库内的参考图 / IR；都给了才会复制进资产目录并渲染成可点的卡片。
    thumbnail: Path | None = None
    ir_path: Path | None = None
    suffix: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def glyph(self) -> str:
        return GLYPHS.get(self.status, self.status)

    @property
    def thumbnail_suffix(self) -> str:
        if self.suffix:
            return self.suffix
        return self.thumbnail.suffix if self.thumbnail is not None else ""

    @property
    def clickable(self) -> bool:
        return self.thumbnail is not None and self.ir_path is not None


def gallery_assets_dir(gallery: Path) -> Path:
    """gallery 的图片 / IR 资产目录。

    `gallery.html` 在 `<viewer>/dist/` 下，但卡片链到的是 `<viewer>/index.html`
    （viewer 根目录），`scene` 参数按**相对 viewer 根目录**解析（`fetch()` 相对
    文档 URL）。所以资产放 `<viewer>/gallery/`，而不是 `dist/gallery/`：
    否则点开卡片会 `GET /gallery/<case>.ggir.cbor` → 404。
    """
    return gallery.parent.parent / "gallery"


def _fmt_percent(value: float | None) -> str:
    return f"{value:.2%}" if value is not None else "—"


def _card_html(card: Card, assets: Path) -> str:
    name = html.escape(card.case)
    family = html.escape(card.family)
    if not card.clickable:
        return (
            f'<article class="card {card.status}"><h2>{name}</h2>'
            f"<p>{family} · {card.glyph} {card.status}</p>"
            f'<p class="detail">{html.escape(card.detail or "无缩略图")}</p></article>'
        )
    thumb = assets / f"{card.case}{card.thumbnail_suffix}"
    ir_file = assets / f"{card.case}.ggir.cbor"
    # 静态产线直接把参考图 / IR 写进资产目录（源 = 目标），不必自我复制。
    if card.thumbnail.resolve() != thumb.resolve():
        shutil.copyfile(card.thumbnail, thumb)
    if card.ir_path.resolve() != ir_file.resolve():
        shutil.copyfile(card.ir_path, ir_file)
    if card.status == "static":
        meta = f"{family} · {card.elements} 个图元"
        note = card.detail or "静态参考图（R 产线 expected.svg），未做像素验证"
    else:
        meta = f"{family} · {card.elements} 个图元"
        note = (
            f"{_fmt_percent(card.diff)} / 均值 {_fmt_percent(card.mean)} "
            f"· {card.glyph} {card.status}"
        )
    return (
        f'<article class="card {card.status}">'
        f'<a href="../index.html?scene=gallery/{name}.ggir.cbor">'
        f'<img src="../gallery/{name}{card.thumbnail_suffix}" alt="{name}" loading="lazy">'
        f"</a><h2>{name}</h2>"
        f"<p>{meta}</p>"
        f'<p class="diff">{html.escape(note) if card.status == "static" else note}</p>'
        f"</article>"
    )


def write_gallery(
    cards: list[Card],
    gallery: Path,
    now: str,
    *,
    lede: str | None = None,
    subtitle: str = "gg4py viewer · case gallery",
) -> None:
    """写 `gallery.html`，并把卡片用到的缩略图 / IR 复制进 `<viewer>/gallery/`。"""
    assets = gallery_assets_dir(gallery)
    assets.mkdir(parents=True, exist_ok=True)
    body = [_card_html(card, assets) for card in cards]
    counts = {status: 0 for status in GLYPHS}
    for card in cards:
        counts[card.status] = counts.get(card.status, 0) + 1
    summary = (
        " · ".join(f"{status} {counts[status]}" for status in GLYPHS if counts.get(status))
        or f"{len(cards)} 张卡片"
    )
    if lede is None:
        lede = (
            f"{now} · {summary}。点缩略图进入 viewer，鼠标悬停看图元 tooltip，点图例 key 开关图例。"
        )
    document = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(subtitle)}</title>
    <style>
      body {{ margin: 0; padding: 24px; background: #f4f4f2; color: #1d1d1b;
             font: 13px/1.5 -apple-system, "Segoe UI", "Noto Sans CJK SC", sans-serif; }}
      h1 {{ margin: 0 0 6px; font-size: 18px; }}
      .lede {{ margin: 0 0 20px; color: #666; }}
      .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }}
      .card {{ margin: 0; padding: 10px; border: 1px solid #d6d6d2; border-radius: 8px; background: #fff; }}
      .card img {{ display: block; width: 100%; height: auto; border: 1px solid #eee; background: #fff; }}
      .card h2 {{ margin: 8px 0 2px; font-size: 13px; overflow-wrap: anywhere; }}
      .card p {{ margin: 2px 0; color: #666; font-variant-numeric: tabular-nums; }}
      .card.pass {{ border-color: #9ae6b4; }}
      .card.fail, .card.error {{ border-color: #feb2b2; }}
      .card.skip {{ opacity: .72; }}
      .detail {{ overflow-wrap: anywhere; }}
    </style>
  </head>
  <body>
    <h1>{html.escape(subtitle)}</h1>
    <p class="lede">{lede}</p>
    <main class="grid">
      {"".join(body)}
    </main>
  </body>
</html>
"""
    gallery.parent.mkdir(parents=True, exist_ok=True)
    gallery.write_text(document, encoding="utf-8")
