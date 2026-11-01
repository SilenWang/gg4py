"""Generate the frozen 200-label text corpus used by the M-1 metric gate (E2).

Shared by E2 (uharfbuzz vs CanvasKit advance parity) and the M0-7 CI gate so
both measure the same strings. Deterministic: same seed -> byte-identical file.

Run: pixi run spike:corpus
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

SEED = 20261101
PER_CATEGORY = 40
OUT = Path(__file__).with_name("labels_200.json")

# --- latin / digits / punctuation -------------------------------------------
LATIN_WORDS = [
    "Sepal", "Petal", "Length", "Width", "Species", "setosa", "virginica",
    "versicolor", "count", "median", "mpg", "cyl", "displ", "hwy", "drv",
    "Intercept", "slope", "p-value", "R²", "95% CI", "n = 1,234", "−1.5e-3",
    "−40 °C", "1 000 000", "3.14159", "µg/L", "Ångström", "naïve", "café",
]
LATIN_UNITS = ["", " (mm)", " [%]", " — total", "/day", " ±0.02", " #12"]

# --- CJK --------------------------------------------------------------------
CJK_WORDS = [
    "月份", "销售额", "增长率", "平均值", "中位数", "标准差", "样本量", "地区",
    "华东", "华北", "华南", "西南", "第一组", "对照组", "实验组", "处理前",
    "处理后", "总计", "占比", "密度", "温度", "压力", "刚度", "直径",
    "売上高", "前年比", "기온", "평균값", "관측소", "제주도", "東京都", "大阪府",
]
CJK_UNITS = ["（万元）", "（%）", "／天", "·总计", "（含税）", "", "・平均"]

# --- emoji ------------------------------------------------------------------
EMOJI_BASE = ["🌱", "📈", "📉", "🎯", "🔥", "✅", "⚠️", "🧪", "🧬", "🛰️"]
EMOJI_SEQ = [
    "👨‍👩‍👧‍👦", "🏳️‍🌈", "👩‍💻", "🧑‍🔬", "🇨🇳", "🇯🇵", "🇩🇪", "👍🏽", "👋🏻",
    "#️⃣", "1️⃣", "❤️‍🔥", "🤝", "🫶", "🪐", "⛰️", "🧭", "🕰️", "🦠", "🔬",
]
EMOJI_TEMPLATE = ["{e}", "{e} {t}", "{t} {e}", "{e}{e} {t}", "{t}: {e} ({p}%)"]

# --- combining marks / complex scripts --------------------------------------
COMBINING = [
    "e\u0301", "a\u0308\u0304", "o\u0302\u0323", "n\u0303", "u\u0308",
    "q\u0307\u0323", "A\u030a", "x\u0338", "z\u0327\u0301",
    "नमस्ते", "हिन्दी", "क्षेत्र", "தமிழ்", "ภาษาไทย", "वर्ष 2026",
    "العربية", "مُرحَّبًا", "٢٠٢٦", "עברית", "שלום",
    "Tiếng Việt", "Nguyễn", "Đặng", "Ĳsselmeer", "ǅungla",
    "\u1100\u1161\u11a8", "\uac00\ubc31", "\u0e01\u0e33", "ﬁ ligature", "e\u0301\u0301\u0301",
    "\u0915\u094d\u0937", "\u0f42\u0f7a", "\u05d0\u05b8", "Z\u0327\u0301a",
]
COMBINING_TEMPLATE = ["{s}", "{s} (2026)", "{s} — 12.5%", "{s}组", "n={s}"]

# --- long strings -----------------------------------------------------------
LONG_PARTS = [
    "Confidence interval", "标准误", "观察值", "estimated", "分位数",
    "p < 0.001", "拟合曲线", "residual", "残差平方和", "— ", " ", "and ",
]


def _category_rows(rng: random.Random) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}

    latin = []
    while len(latin) < PER_CATEGORY:
        n_words = rng.choice([1, 1, 2, 2, 3])
        words = rng.sample(LATIN_WORDS, n_words)
        sep = rng.choice([" ", " ", " · ", " / "])
        latin.append(sep.join(words) + rng.choice(LATIN_UNITS))
    rows["latin"] = latin

    cjk = []
    while len(cjk) < PER_CATEGORY:
        n_words = rng.choice([1, 1, 2, 3])
        words = rng.sample(CJK_WORDS, n_words)
        sep = rng.choice(["", " ", "、", "と"])
        tail = rng.choice(CJK_UNITS)
        if rng.random() < 0.25:
            tail = f" {rng.randint(1, 999)}"
        cjk.append(sep.join(words) + tail)
    rows["cjk"] = cjk

    emoji = []
    while len(emoji) < PER_CATEGORY:
        e = rng.choice(EMOJI_SEQ)
        emoji.append(
            rng.choice(EMOJI_TEMPLATE).format(
                e=e,
                t=rng.choice(["Sales", "增长", "Yield", "样本", "Total"]),
                p=rng.randint(1, 99),
            )
        )
    rows["emoji"] = emoji

    combining = []
    while len(combining) < PER_CATEGORY:
        s = rng.choice(COMBINING)
        combining.append(rng.choice(COMBINING_TEMPLATE).format(s=s))
    rows["combining"] = combining

    long_rows = []
    while len(long_rows) < PER_CATEGORY:
        target = rng.randint(40, 200)
        out = ""
        while len(out) < target:
            out += rng.choice(LONG_PARTS) + rng.choice(["", " ", ", "])
        long_rows.append(out[:target])
    rows["long"] = long_rows

    return rows


def build() -> dict:
    rng = random.Random(SEED)
    label = 0
    items = []
    for category, texts in _category_rows(rng).items():
        for text in texts:
            items.append({"id": f"L{label:03d}", "category": category, "text": text})
            label += 1
    assert len(items) == 200, len(items)
    payload = {
        "schema": 1,
        "seed": SEED,
        "count": len(items),
        "font_stack": ["DejaVuSans.ttf", "NotoSansCJKsc-VF.ttf", "NotoColorEmoji.ttf"],
        "font_size_px": 16.0,
        "labels": items,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    return payload, body


if __name__ == "__main__":
    data, body = build()
    OUT.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode()).hexdigest()
    print(f"wrote {OUT} ({data['count']} labels, sha256={digest})")
