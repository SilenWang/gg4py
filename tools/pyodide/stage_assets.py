"""SIL-824 · 把浏览器运行时要的资产**本地化**到 `web/runtime/vendor/`。

页面在运行时只访问自己的 origin，一个 CDN 都不碰；`vendor/` 是生成物（不入库），
由本脚本重建：

    pixi run pyodide:assets     # = spike:e1:assets（npm 装 pyodide + 下轮子）+ 本脚本

产物：

    web/runtime/vendor/pyodide/       pyodide 运行时 + stdlib + 锁文件 + 轮子
    web/runtime/vendor/gg4py.zip      ggcore / ggio 源码（含兜底度量表），页面解包用
    web/runtime/vendor/fonts/         受管字体里的**拉丁**字面（每个 ≤ 2 MiB）
    web/runtime/vendor/fonts.css      只声明上面这些字面的 @font-face
    web/runtime/vendor/manifest.json  每个文件的字节数 + sha256 + 来源（进度条与校验用）

三件事刻意这么做：

1. **和 E1 共用一份 pyodide 包**。`spike:e1:assets` 已经把 npm 包与轮子按
   pyodide-lock.json 的 sha256 落到 `docs/spike/e1_coldstart/static/pyodide/`；
   这里只复制，不再下一次网，CI 的下载次数不变。
2. **gg4py.zip 是确定性的**：条目排序、固定时间戳、固定压缩级别。`manifest.json`
   里的 sha256 因此只在源码改动时变化，Service Worker 的缓存键可以直接用它。
   `__pycache__` / `*.orig` 不入包。
3. **字体只带拉丁字面**。`viewer/fonts.css` 把 8 个受管字族全声明上了，其中
   `NotoSansCJKsc-VF.ttf` 是 35 MB、`NotoColorEmoji.ttf` 是 9.5 MB——页面一旦渲染
   任何一段 CJK 文本，浏览器就会去下 35 MB，`首访 4G ≤ 12 s` 直接没戏（实测：
   一次页面加载光字体就 36 MB）。这里按文件大小挑 ≤ 2 MiB 的字面（Arimo 325 KB、
   DejaVu 740 KB、Noto Sans 1.5 MB、Noto Emoji 409 KB），写成
   `vendor/fonts.css`；CJK 文本回落到系统字体。这是 CJK 字体子集化（M3-4 之后
   的事）之前的明确取舍，不是漏了。

   量文字仍然走 `ggcore.metrics.fallback.TableMetrics`：宽度来自 ggcore 自带
   的兜底度量表（覆盖 CJK），与这里「画字用哪份文面」是两件事。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE = REPO / "docs" / "spike" / "e1_coldstart" / "static" / "pyodide"
OUT = REPO / "web" / "runtime" / "vendor"
SRC = REPO / "src"
#: 打进 `gg4py.zip` 的包：ggcore 是内核，ggio 是 DataFrame-like 适配层（示例会用到）。
PACKAGES = ("ggcore", "ggio")
#: 固定时间戳（1980-01-01，zip 的最早合法值）：同一个源码树 → 同一个 zip 字节。
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
#: 进首屏的字体上限。CJK（35 MB）与彩色 emoji（9.5 MB）超过它，见模块说明第 3 条。
MAX_FONT_BYTES = 2 * 1024 * 1024
VIEWER = REPO / "web" / "viewer"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _package_version() -> str | None:
    """pyodide 的版本号：E1 的 `static/manifest.json` 是唯一一份写下来的。"""
    try:
        data = json.loads((SOURCE.parent / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):  # pragma: no cover - 只在手改产物时发生
        return None
    return data.get("pyodide_version")


def copy_runtime(dest: Path) -> list[dict]:
    """pyodide 运行时 + 轮子：从 E1 的 static 目录复制（sha256 已在那边校验过）。"""
    if not (SOURCE / "pyodide.mjs").is_file():
        raise SystemExit(
            f"{SOURCE} 是空的 —— 先跑 `pixi run spike:e1:assets`（`pyodide:assets` 已依赖它）"
        )
    dest.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []
    for path in sorted(SOURCE.iterdir()):
        if not path.is_file() or path.name.endswith((".orig", ".map")):
            continue
        target = dest / path.name
        shutil.copyfile(path, target)
        data = target.read_bytes()
        files.append(
            {
                "file": f"pyodide/{path.name}",
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )
    return files


def stage_fonts(dest: Path) -> list[dict]:
    """`viewer/fonts.css` → 只保留 ≤ 2 MiB 的字面，写到 `vendor/fonts/` + `vendor/fonts.css`。

    CSS 与字体都由 `pixi run viewer:build` 生成（`web/viewer/fonts/`），这里只做
    「挑子集 + 改相对路径」，不自己写第二份字族表。
    """
    css_path = VIEWER / "fonts.css"
    source_dir = VIEWER / "fonts"
    if not css_path.is_file() or not source_dir.is_dir():
        raise SystemExit(
            f"{css_path} 不存在 —— 先跑 `pixi run viewer:build`（`pyodide:assets` 已依赖它）"
        )
    dest.mkdir(parents=True, exist_ok=True)
    kept: list[str] = []
    files: list[dict] = []
    out_lines = [
        "/* 由 tools/pyodide/stage_assets.py 从 web/viewer/fonts.css 裁剪生成：",
        "   只保留 ≤ 2 MiB 的受管字面（CJK / 彩色 emoji 不进首屏，见工具说明）。 */",
    ]
    for block in re.split(r"@font-face\s*\{", css_path.read_text(encoding="utf-8")):
        if 'url("fonts/' not in block:
            continue
        name = block.split('url("fonts/', 1)[1].split('"', 1)[0]
        source = source_dir / name
        if not source.is_file() or source.stat().st_size > MAX_FONT_BYTES:
            continue
        target = dest / name
        shutil.copyfile(source, target)
        data = target.read_bytes()
        kept.append(name)
        files.append(
            {
                "file": f"fonts/{name}",
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )
        out_lines.append(
            "@font-face {"
            + block.replace('url("fonts/', 'url("fonts/').strip().rstrip("}").rstrip()
            + " }"
        )
    (dest.parent / "fonts.css").write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"fonts: kept {len(kept)} face(s) <= {MAX_FONT_BYTES // 1024} KiB: {', '.join(kept)}")
    return files


def source_files() -> list[tuple[str, bytes]]:
    """`src/{ggcore,ggio}` 的打包清单：排序 + 跳过缓存与备份文件。

    条目路径从**仓库根**算起（`src/ggcore/...`），这样 `extractDir="/app"` 之后
    得到的是 `/app/src/ggcore`——与仓库布局一致，`sys.path` 也只需指到 `/app/src`。
    从 `src/` 算起会把包解到 `/app/ggcore`，两边路径口径就不一样了。
    """
    entries: list[tuple[str, bytes]] = []
    for package in PACKAGES:
        root = SRC / package
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in (".pyc", ".orig"):
                continue
            entries.append((path.relative_to(REPO).as_posix(), path.read_bytes()))
    if not entries:
        raise SystemExit(f"{SRC} 下没有可打包的源码")
    return entries


def build_zip(dest: Path) -> dict:
    """确定性 zip：条目排序、固定时间戳、deflate 9。"""
    entries = source_files()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    data = dest.read_bytes()
    return {
        "file": dest.name,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "entries": len(entries),
        "source_bytes": sum(len(payload) for _, payload in entries),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 Pyodide 运行时与 ggcore 源码本地化。")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    out = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    files = copy_runtime(out / "pyodide")
    files.extend(stage_fonts(out / "fonts"))
    archive = build_zip(out / "gg4py.zip")

    core_files = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip")
    core = [entry for entry in files if entry["file"].rsplit("/", 1)[-1] in core_files]
    lock = json.loads((out / "pyodide" / "pyodide-lock.json").read_text(encoding="utf-8"))
    info = lock.get("info", {})
    manifest = {
        # 锁文件里没有 pyodide 的版本号字段；用 E1 manifest 的同一口径（npm 包的
        # 版本写在 package.json 里，这里退到 lock 的 python 版本 + abi 供核对）。
        "pyodide_version": info.get("version") or _package_version(),
        "abi": info,
        "files": files,
        "archive": archive,
        #: 首屏（boot 到 `import ggcore` 可用）要的字节：运行时核心 + gg4py.zip。
        "boot_bytes": sum(entry["bytes"] for entry in core) + archive["bytes"],
        "total_bytes": sum(entry["bytes"] for entry in files) + archive["bytes"],
        "note": (
            "generated by `pixi run pyodide:assets`; not committed. "
            "runtime never touches a CDN — every request is same-origin."
        ),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")

    for entry in files:
        print(f"{entry['bytes']:>10,d}  {entry['file']}")
    print(f"{archive['bytes']:>10,d}  {archive['file']} ({archive['entries']} files)")
    print(f"{manifest['boot_bytes']:>10,d}  boot bytes (core + archive)")
    print(f"{manifest['total_bytes']:>10,d}  total staged bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
