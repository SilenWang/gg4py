"""覆盖矩阵的台账纪律（SIL-828 / M3-7）。

矩阵的两条轴写在 `docs/cases/taxonomy.toml`：族（行）与特性（列）。case 的
`meta.toml` 用了没登记的值时，`pixi run cases:matrix` 仍会自动加行 / 加列，但
`docs/cases/matrix.md` 会多出一节「未登记的族 / 特性」——那就是矩阵里的「空格」：
行列不在台账里，覆盖缺口清单也就不可信。

这里把「补登记」变成硬判据：任何 case 的 `family` / `features` 都必须在
`taxonomy.toml` 里登记过。新增 case 先用 taxonomy 里的词；确实需要新词就一并登记
（顺序按主题追加，不重排，见文件头）。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CASES = REPO / "docs" / "cases"


def _meta() -> dict[str, dict]:
    return {
        path.parent.name: tomllib.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CASES.glob("*/meta.toml"))
    }


def test_every_case_family_and_feature_is_registered() -> None:
    taxonomy = tomllib.loads((CASES / "taxonomy.toml").read_text(encoding="utf-8"))
    families = set(taxonomy["families"])
    features = set(taxonomy["features"])

    meta = _meta()
    assert meta, "案例库不该是空的"

    missing_families = sorted(
        {entry["family"] for entry in meta.values() if entry.get("family")} - families
    )
    missing_features = sorted(
        {feature for entry in meta.values() for feature in entry.get("features", [])} - features
    )

    assert missing_families == [], f"族没登记进 taxonomy.toml：{missing_families}"
    assert missing_features == [], f"特性没登记进 taxonomy.toml：{missing_features}"


def test_taxonomy_entries_are_unique() -> None:
    """同一轴里不该重复登记（重复会让矩阵列数虚增、合计对不上）。"""
    taxonomy = tomllib.loads((CASES / "taxonomy.toml").read_text(encoding="utf-8"))
    for axis in ("families", "features"):
        values = taxonomy[axis]
        duplicates = sorted({value for value in values if values.count(value) > 1})
        assert duplicates == [], f"{axis} 有重复项：{duplicates}"
