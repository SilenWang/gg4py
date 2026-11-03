"""Guards the frozen M-1 corpus so E2 and the M0-7 gate stay comparable."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "docs" / "spike" / "corpus" / "labels_200.json"
sys.path.insert(0, str(CORPUS.parent))

import generate_corpus

# Frozen on purpose: E2 and M0-7 must measure the same strings. Changing the
# corpus is a deliberate act that moves this digest.
EXPECTED_SHA256 = "5352de69d520d6cfe09c233265e51fbfc4e50903d089bce110cd71ce48425488"


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
