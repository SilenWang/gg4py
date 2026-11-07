"""`pixi run diff` 的命令行入口。

两种调用形态：

```bash
# 1) 三文件 case：expected.* vs current/*（矩阵走这条）
pixi run diff docs/cases/geom-point-basic \
    --report docs/cases/geom-point-basic/current/diff_report.md --tolerance 0.02

# 不传 --report 时，报告与热图写在 case 目录下（issue 约定的位置，不入库）
pixi run diff docs/cases/geom-point-basic

# 2) 两个文件：参考 + 实测（人工排查时用）
pixi run diff expected.svg current/geom-point-basic.svg --json
```

退出码：0 = 通过；1 = 超容差；2 = 用法 / IO / 光栅化错误。`--json` 时 stdout
只有一份 JSON，人读摘要改走 stderr，方便 `| jq`。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from ggdiff.compare import (
    DEFAULT_MAX_FRACTION,
    DEFAULT_MAX_MEAN,
    DEFAULT_PIXEL_THRESHOLD,
    DiffResult,
    compare_images,
)
from ggdiff.image import load_image, save_heatmap
from ggdiff.raster import DEFAULT_DPI, RasterError, rasterize_svg, resvg_version
from ggdiff.report import render_report
from ggdiff.svgimage import SvgImageError, snap_pixelated_images
from ggdiff.svgtext import SvgTextError, inline_text_paths

EXPECTED_NAMES = ("expected.png", "expected.svg")


class DiffError(RuntimeError):
    """用法 / IO 错误（退出码 2），不是「图不一样」。"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diff",
        description="Compare a reference image (or case expected.*) against the actual output.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="<case-dir> 或 <reference> <actual>",
    )
    parser.add_argument(
        "--reference", type=Path, default=None, help="参考图（覆盖 case 目录里的 expected.*）"
    )
    parser.add_argument(
        "--actual", type=Path, default=None, help="实测产物（覆盖 case 目录里的 current/*）"
    )
    parser.add_argument(
        "--report", type=Path, default=None, help="markdown 报告路径（默认 <case>/diff_report.md）"
    )
    parser.add_argument(
        "--heatmap", type=Path, default=None, help="差异热图 PNG 路径（默认与报告同目录）"
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_MAX_FRACTION,
        help=f"图级差异上限（比例，默认 {DEFAULT_MAX_FRACTION:g} = 2%%）",
    )
    parser.add_argument(
        "--mean-tolerance",
        type=float,
        default=DEFAULT_MAX_MEAN,
        help=f"平均差异上限（比例，默认 {DEFAULT_MAX_MEAN:g} = 1%%）",
    )
    parser.add_argument(
        "--pixel-threshold",
        type=int,
        default=DEFAULT_PIXEL_THRESHOLD,
        help=f"单像素算作差异的最大通道差（默认 {DEFAULT_PIXEL_THRESHOLD}/255）",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"SVG 光栅化分辨率（默认 {DEFAULT_DPI}：1 pt = 1 px）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="把结构化结论打到 stdout（矩阵与下游脚本只认它）",
    )
    return parser


# ---------------------------------------------------------------------------
# 解析输入
# ---------------------------------------------------------------------------


def _one(*candidates: Path) -> Path | None:
    existing = [path for path in candidates if path is not None and path.is_file()]
    return existing[0] if existing else None


def _resolve_case(directory: Path, args: argparse.Namespace) -> tuple[Path, Path]:
    """case 目录 → （参考, 实测）。格式由 `expected.*` 的后缀决定。"""
    reference = args.reference or _one(*(directory / name for name in EXPECTED_NAMES))
    if reference is None:
        raise DiffError(f"{directory} 里没有 expected.png / expected.svg——参考图必须是其中之一")
    if reference.suffix.lower() not in (".png", ".svg"):
        raise DiffError(f"参考图 {reference} 只能是 .png / .svg")

    if args.actual is not None:
        actual = args.actual
    else:
        current = directory / "current"
        candidates = (
            sorted(current.glob(f"*.{reference.suffix.lstrip('.').lower()}"))
            if current.is_dir()
            else []
        )
        preferred = current / f"{directory.name}{reference.suffix.lower()}"
        actual = (
            preferred if preferred.is_file() else (candidates[0] if len(candidates) == 1 else None)
        )
        if actual is None:
            if candidates:
                raise DiffError(
                    f"{current} 里有 {len(candidates)} 个 {reference.suffix} 产物，"
                    f"用 --actual 指定（{', '.join(path.name for path in candidates)}）"
                )
            raise DiffError(f"{current} 里没有 {reference.suffix} 产物——先跑 `pixi run render`")
    if not actual.is_file():
        raise DiffError(f"实测产物不存在：{actual}")
    return reference, actual


def _resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path | None]:
    """返回（参考, 实测, case 目录或 None）。"""
    if args.reference is not None or args.actual is not None:
        if args.reference is None or args.actual is None:
            raise DiffError("--reference / --actual 必须一起给，或都不给（用 case 目录）")
        reference, actual = args.reference, args.actual
        case_dir = args.paths[0] if len(args.paths) == 1 and args.paths[0].is_dir() else None
        return reference, actual, case_dir

    if len(args.paths) == 2:
        return args.paths[0], args.paths[1], None
    if len(args.paths) == 1 and args.paths[0].is_dir():
        reference, actual = _resolve_case(args.paths[0], args)
        return reference, actual, args.paths[0]
    raise DiffError(
        "用法：`diff <case-dir>` 或 `diff <reference> <actual>`（见 `pixi run diff --help`）"
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _rasterize_if_needed(path: Path, scratch: Path, dpi: int) -> tuple[Path, bool]:
    """SVG → PNG；PNG 原样返回。返回（位图路径, 是否做了光栅化）。

    `scratch` 必须是**这一侧独占**的目录（调用方传 `<tmp>/reference` /
    `<tmp>/actual`）：两侧产物只按 `path.stem` 命名，同名 SVG（`a/foo.svg` 与
    `b/foo.svg`）落到同一个名字上会互相覆盖，随后比的是同一张图 → 静默判绿
    （SIL-649）。

    SVG 先过 `ggdiff.svgtext`：`<text>` 就地换成字形轮廓。resvg 0.47 画不出
    pixi 的 Noto CJK VF（参考图会整段空白），这一步把文本变成路径后两边就只比
    几何与字形，不再依赖光栅器的字体栈。转换仍是「R 的位置 + R 的宽度」。
    """
    if path.suffix.lower() == ".png":
        return path, False
    if path.suffix.lower() != ".svg":
        raise DiffError(f"只支持 .png / .svg，收到 {path}")
    scratch.mkdir(parents=True, exist_ok=True)
    prepared = scratch / f"{path.stem}-outlined.svg"
    try:
        inline_text_paths(path, prepared)
        snap_pixelated_images(prepared)
    except (SvgTextError, SvgImageError) as error:
        raise DiffError(str(error)) from error
    target = scratch / f"{path.stem}.png"
    rasterize_svg(prepared, target, dpi=dpi)
    return target, True


def _default_report(
    reference: Path, actual: Path, case_dir: Path | None, args: argparse.Namespace
) -> Path | None:
    if args.report is not None:
        return args.report
    if case_dir is not None:
        # issue 约定的位置：`docs/cases/<name>/diff_report.md`（不入库，见 .gitignore）；
        # 矩阵走 `--report <case>/current/diff_report.md`，与渲染产物放一起。
        return case_dir / "diff_report.md"
    return None


def _default_heatmap(
    report: Path | None, case_dir: Path | None, args: argparse.Namespace
) -> Path | None:
    if args.heatmap is not None:
        return args.heatmap
    if report is not None:
        return report.parent / f"{report.stem}_heatmap.png"
    return None


def _emit(payload: dict[str, object], args: argparse.Namespace, human: str) -> None:
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(human, file=sys.stderr)
    else:
        print(human)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        reference, actual, case_dir = _resolve_paths(args)
    except DiffError as error:
        return _error(str(error), args)

    report = _default_report(reference, actual, case_dir, args)
    heatmap_path = _default_heatmap(report, case_dir, args)

    try:
        with tempfile.TemporaryDirectory(prefix="ggdiff-") as scratch_name:
            scratch = Path(scratch_name)
            # 两侧各用一个子目录：只按文件名命名，同名参考/实测不能落在一起。
            reference_png, reference_raster = _rasterize_if_needed(
                reference, scratch / "reference", args.dpi
            )
            actual_png, actual_raster = _rasterize_if_needed(actual, scratch / "actual", args.dpi)
            if reference_png.resolve() == actual_png.resolve():  # pragma: no cover - 防御
                raise DiffError("参考与实测落到了同一张位图上，拒绝比「自己和自己」")
            reference_pixels = load_image(reference_png)
            actual_pixels = load_image(actual_png)
    except (DiffError, RasterError, OSError) as error:
        return _error(str(error), args)

    result, mask, amount = compare_images(
        reference_pixels,
        actual_pixels,
        max_fraction=args.tolerance,
        max_mean=args.mean_tolerance,
        pixel_threshold=args.pixel_threshold,
    )

    if heatmap_path is not None:
        try:
            save_heatmap(heatmap_path, reference_pixels, mask, amount=amount)
        except OSError as error:
            return _error(f"写热图失败：{error}", args)

    raster_note = _describe_raster(reference, actual, reference_raster, actual_raster, args.dpi)
    title = case_dir.name if case_dir is not None else reference.stem
    if report is not None:
        try:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                render_report(
                    result,
                    title=title,
                    reference=reference,
                    actual=actual,
                    rasterized=raster_note,
                    heatmap=heatmap_path,
                    resvg=_safe_resvg_version(reference_raster or actual_raster),
                ),
                encoding="utf-8",
            )
        except OSError as error:
            return _error(f"写报告失败：{error}", args)

    payload = {
        **result.as_dict(),
        "reference": str(reference),
        "actual": str(actual),
        "heatmap": str(heatmap_path) if heatmap_path is not None else None,
        "report": str(report) if report is not None else None,
    }
    human = _human_summary(result, title)
    _emit(payload, args, human)
    return 0 if result.ok else 1


def _describe_raster(
    reference: Path, actual: Path, reference_raster: bool, actual_raster: bool, dpi: int
) -> str:
    parts: list[str] = []
    for label, path, rasterized in (
        ("参考", reference, reference_raster),
        ("实测", actual, actual_raster),
    ):
        if rasterized:
            parts.append(f"{label} `{path.suffix}` → resvg --dpi {dpi}")
        else:
            parts.append(f"{label} `{path.suffix}`（直接比像素）")
    return "；".join(parts)


def _safe_resvg_version(used: bool) -> str:
    if not used:
        return ""
    try:
        return resvg_version()
    except RasterError:  # pragma: no cover - resvg 刚刚才成功用过
        return ""


def _human_summary(result: DiffResult, title: str) -> str:
    verdict = "绿（通过）" if result.ok else "红（超容差）"
    lines = [
        f"diff {title}: {verdict}",
        f"  图级差异 {result.image_diff_fraction:.4%}"
        f"（阈值 {result.thresholds['image_diff_fraction']:.2%}）",
        f"  平均差异 {result.mean_diff:.4%}（阈值 {result.thresholds['mean_diff']:.2%}）",
        f"  差异像素 {result.diff_pixels} / {result.total_pixels}"
        f"（{result.width}×{result.height}）",
    ]
    if result.reason:
        lines.append(f"  原因：{result.reason}")
    return "\n".join(lines)


def _error(message: str, args: argparse.Namespace) -> int:
    if args.json:
        print(
            json.dumps(
                {"verdict": "error", "ok": False, "reason": message}, ensure_ascii=False, indent=2
            )
        )
        print(f"diff: {message}", file=sys.stderr)
    else:
        print(f"diff: {message}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
