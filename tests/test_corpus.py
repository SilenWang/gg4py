"""Guards the frozen M-1 corpus so E2 and the M0-7 gate stay comparable."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "docs" / "spike" / "corpus" / "labels_200.json"
sys.path.insert(0, str(CORPUS.parent))

import generate_corpus  # noqa: E402

# Frozen on purpose: E2 and M0-7 must measure the same strings. Changing the
# corpus is a deliberate act that moves this digest.
EXPECTED_SHA256 = "6c93e4143ba1876447c88f31bdb06a9d1500e44dca05f3ef1694f9a4dabedfb1"


def test_committed_corpus_is_regenerable() -> None:
    _, body = generate_corpus.build()
    assert body == CORPUS.read_text(encoding="utf-8")


def test_corpus_shape() -> None:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    assert data["count"] == 200
    labels = data["labels"]
    assert len(labels) == 200
    assert len({label["id"] for label in labels}) == 200
    assert sorted({label["category"] for label in labels}) == [
        "cjk",
        "combining",
        "emoji",
        "latin",
        "long",
    ]
    assert all(label["text"].strip() for label in labels)
    assert hashlib.sha256(CORPUS.read_bytes()).hexdigest() == EXPECTED_SHA256
