"""SIL-824 / SIL-830 · 把浏览器运行时要的资产**本地化**到 `web/runtime/vendor/`。

页面在运行时只访问自己的 origin，一个 CDN 都不碰；`vendor/` 是生成物（不入库），
由本脚本重建：

    pixi run pyodide:assets     # = spike:e1:assets（npm 装 pyodide + 下轮子）+ 本脚本

产物：

    web/runtime/vendor/pyodide/       pyodide 运行时 + stdlib + 锁文件 + 轮子
    web/runtime/vendor/gg4py.tar      ggcore / ggio（含兜底度量表），页面解包用
    web/runtime/vendor/*.br           上面这些文件的 brotli 预压缩兄弟（静态服务按
                                      `Content-Encoding: br` 回放，浏览器不感知）
    web/runtime/vendor/fonts/         受管字体里的**拉丁**字面（每个 ≤ 2 MiB）
    web/runtime/vendor/fonts.css      只声明上面这些字面的 @font-face
    web/runtime/vendor/manifest.json  每个文件的字节数 + sha256 + 线上字节（进度条与校验用）

四件事刻意这么做：

1. **和 E1 共用一份 pyodide 包**。`spike:e1:assets` 已经把 npm 包与轮子按
   pyodide-lock.json 的 sha256 落到 `docs/spike/e1_coldstart/static/pyodide/`；
   这里只复制，不再下一次网，CI 的下载次数不变。
2. **源码包是确定性 tar（不是 zip）**。同一份源码树 → 同一个字节（条目排序、
   mtime=0、uid/gid=0、UTF-8 名字），`manifest.json` 的 sha256 因此只在源码改动时
   变化。换掉 zip 的理由是字节数：86 个文件的 zip（每个条目一份 deflate 流 + 头）
   740 KB，同内容的 tar 再 brotli q11 是 458 KB——**少 38%**，直接换成了首访时间
   （SIL-830）。`__pycache__` / `*.orig` 不入包。
3. **字节码预编译（`.pyc`）默认开着**，编在构建期、用**浏览器那把** CPython
   （`tools/pyodide/compile_pyc.mjs` 在 pyodide 里跑 `compileall`）：`.pyc` 的魔法
   数跟 CPython 版本绑定，桌面 3.12 编出来的字节码在浏览器 3.14 里会被判定为版本
   不对而白丢。实测（Pyodide 314.0.7，numpy 已装）`import ggcore`：源码 761.8 ms
   / 字节码 195.4 ms（`--measure` 的口径），线上字节 +0.51 MB（tar+brotli 1,018 KB
   vs 504 KB）。整机 A/B：冷 11.95 → 11.84 s、**warm 3.49 → 2.87 s**（字节从缓存来，
   编译不再发生，warm 是纯赚）。优化级固定 **0**：`optimize=1` 会删掉 `assert`、
   `=2` 再删 docstring，省的那点字节不值得让浏览器端和桌面端跑两套语义。
4. **字体只带拉丁字面**。`viewer/fonts.css` 把 8 个受管字族全声明上了，其中
   `NotoSansCJKsc-VF.ttf` 是 35 MB、`NotoColorEmoji.ttf` 是 9.5 MB——页面一旦渲染
   任何一段 CJK 文本，浏览器就会去下 35 MB，`首访 4G ≤ 12 s` 直接没戏（实测：
   一次页面加载光字体就 36 MB）。这里按文件大小挑 ≤ 2 MiB 的字面（Arimo 325 KB、
   DejaVu 740 KB、Noto Sans 1.5 MB、Noto Emoji 409 KB），写成
   `vendor/fonts.css`；CJK 文本回落到系统字体。这是 CJK 字体子集化（M3-4 之后
   的事）之前的明确取舍，不是漏了。

   量文字仍然走 `ggcore.metrics.fallback.TableMetrics`：宽度来自 ggcore 自带
   的兜底度量表（覆盖 CJK），与这里「画字用哪份文面」是两件事。

预压缩只做**赚得到**的文件（收益 ≥ 2%）：wasm 3.53 → 2.74 MB、`pyodide.asm.mjs`
0.26 → 0.21 MB、源码包 3.56 → 1.02 MB（不带字节码时 2.61 → 0.50 MB）。numpy 等
`.whl` 本身就是 zip，brotli 只省
0.3%，不压（省下的线上字节抵不上构建时间与一份重复存储）。压缩结果按内容 sha256
缓存在 `.pyodide-cache/brotli/`（不入库），wasm 的 q11 要 20 s，只有首次构建付一次。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE = REPO / "docs" / "spike" / "e1_coldstart" / "static" / "pyodide"
OUT = REPO / "web" / "runtime" / "vendor"
SRC = REPO / "src"
#: 打进源码包的包：ggcore 是内核，ggio 是 DataFrame-like 适配层（示例会用到）。
PACKAGES = ("ggcore", "ggio")
#: 进首屏的字体上限。CJK（35 MB）与彩色 emoji（9.5 MB）超过它，见模块说明第 4 条。
MAX_FONT_BYTES = 2 * 1024 * 1024
VIEWER = REPO / "web" / "viewer"
#: 预压缩的 brotli 质量：11 是「最大压缩」，构建期一次，用户侧只解码。
BROTLI_QUALITY = 11
#: 收益低于这个比例的文件不压（省下的字节抵不上构建时间与一份重复存储）。
MIN_BROTLI_GAIN = 0.02
#: 压缩产物缓存（不入库）：wasm 的 q11 要 20 s，只有首次构建付一次。
BROTLI_CACHE = REPO / ".pyodide-cache" / "brotli"
#: `tools/pyodide/*.mjs`：brotli 与「在 pyodide 里编 pyc」两个构建期小工具。
BROTLI_TOOL = HERE / "brotli.mjs"
PYC_TOOL = HERE / "compile_pyc.mjs"


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
    seen: set[str] = set()
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
        kept.append(name)
        # 同一个字面可能被多条 `@font-face` 引用（Arimo Italic 有 4 条）：CSS 全留，
        # manifest 只记一次——否则字节账会把同一个文件算四遍（SIL-830 的审计工具
        # 就是拿 manifest 当账本的）。
        if name not in seen:
            seen.add(name)
            data = target.read_bytes()
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


def compile_bytecode(optimize: int = 0) -> tuple[dict[str, bytes], dict]:
    """在 **Pyodide 里**把源码编成 `.pyc`（见 `compile_pyc.mjs` 的说明）。

    返回 `{tar 条目名: 字节}`（与源码包同一套路径，只是后缀换成 `.pyc`）与一次
    编译的元数据（文件数、耗时、以及 `--measure` 的 import 对比）。
    """
    with tempfile.TemporaryDirectory(prefix="gg4py-pyc-") as tmp:
        proc = subprocess.run(
            ["node", str(PYC_TOOL), "--out", tmp, "--optimize", str(optimize)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(f"compile_pyc.mjs 失败：\n{proc.stderr.strip()}")
        meta = json.loads(proc.stdout.strip().splitlines()[-1])
        root = Path(tmp)
        entries: dict[str, bytes] = {}
        for path in sorted((root / "src").rglob("*.pyc")):
            entries[path.relative_to(root).as_posix()] = path.read_bytes()
    if not entries:
        raise SystemExit("compile_pyc.mjs 没有产出任何 .pyc")
    return entries, meta


def build_archive(dest: Path, *, bytecode: bool = True, optimize: int = 0) -> dict:
    """确定性 tar（条目排序、mtime=0、uid/gid=0）。

    `bytecode=True` 时用 Pyodide 编出来的 `.pyc` 顶替 `.py`；数据文件（度量表
    `metrics/data/*.bin` 之类）原样保留——源码包里少了它们，`import ggcore` 在
    浏览器里就会在读表时炸。
    """
    entries = source_files()
    compiled: dict[str, bytes] = {}
    meta: dict = {}
    if bytecode:
        compiled, meta = compile_bytecode(optimize)

    packed: list[tuple[str, bytes]] = []
    missing: list[str] = []
    for name, data in entries:
        if bytecode and name.endswith(".py"):
            pyc = compiled.get(name[:-3] + ".pyc")
            if pyc is None:  # pragma: no cover - 只有工具漏编某个文件时才会发生
                missing.append(name)
                packed.append((name, data))
            else:
                packed.append((name[:-3] + ".pyc", pyc))
        else:
            packed.append((name, data))
    if missing:  # pragma: no cover
        raise SystemExit(f"这些文件没有编出 .pyc：{missing[:5]}")
    packed.sort(key=lambda entry: entry[0])

    dest.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in packed:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.type = tarfile.REGTYPE
            archive.addfile(info, io.BytesIO(data))
    payload = buffer.getvalue()
    dest.write_bytes(payload)
    return {
        "file": dest.name,
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "entries": len(packed),
        "source_bytes": sum(len(data) for _, data in entries),
        "bytecode": bytecode,
        "bytecode_optimize": optimize if bytecode else None,
        "bytecode_files": meta.get("files"),
        "bytecode_compile_ms": meta.get("compile_ms"),
    }


def _brotli_cache_key(data: bytes, quality: int) -> str:
    return hashlib.sha256(data + f"\0brotli{quality}".encode()).hexdigest()


def brotli_bytes(data: bytes, quality: int = BROTLI_QUALITY) -> bytes:
    """brotli q11（node 自带的 zlib），按内容 sha256 缓存——wasm 一次 20 s。"""
    key = _brotli_cache_key(data, quality)
    cached = BROTLI_CACHE / f"{key}.br"
    if cached.is_file():
        return cached.read_bytes()
    BROTLI_CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gg4py-br-") as tmp:
        raw = Path(tmp) / "in"
        out = Path(tmp) / "out.br"
        raw.write_bytes(data)
        proc = subprocess.run(
            ["node", str(BROTLI_TOOL), str(quality), str(raw), str(out)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise SystemExit(f"brotli.mjs 失败：\n{proc.stderr.strip()}")
        payload = out.read_bytes()
    cached.write_bytes(payload)
    return payload


def stage_brotli(path: Path, *, quality: int = BROTLI_QUALITY) -> dict:
    """给一个已落盘的文件生成 `<name>.br` 兄弟；收益不足则删掉、退化成不压。"""
    data = path.read_bytes()
    if len(data) < 32 * 1024:  # 小文件压不动，还多一次请求
        return {"encoding": None, "bytes": len(data), "wire_bytes": len(data)}
    payload = brotli_bytes(data, quality)
    gain = 1.0 - len(payload) / len(data)
    if gain < MIN_BROTLI_GAIN:
        return {
            "encoding": None,
            "bytes": len(data),
            "wire_bytes": len(data),
            "gain": round(gain, 4),
        }
    target = path.with_name(path.name + ".br")
    target.write_bytes(payload)
    return {
        "encoding": "br",
        "bytes": len(data),
        "wire_bytes": len(payload),
        "gain": round(gain, 4),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 Pyodide 运行时与 ggcore 源码本地化。")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--no-bytecode",
        action="store_true",
        help="源码原样打包（对照用：字节码预编译是 SIL-830 的默认值）",
    )
    parser.add_argument(
        "--optimize",
        type=int,
        default=0,
        help=".pyc 的优化级；默认 0（保留 assert 与 docstring，两端语义一致）",
    )
    parser.add_argument("--quality", type=int, default=BROTLI_QUALITY, help="brotli 质量")
    parser.add_argument(
        "--no-brotli", action="store_true", help="不生成 .br（对照用：量压缩收益时）"
    )
    args = parser.parse_args(argv)

    out = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    files = copy_runtime(out / "pyodide")
    files.extend(stage_fonts(out / "fonts"))
    archive = build_archive(
        out / "gg4py.tar", bytecode=not args.no_bytecode, optimize=args.optimize
    )

    # 预压缩：运行时里值得压的那几个 + 源码包。`pyodide-lock.json` 只有 119 KB 且
    # 只在 boot 时读一次，压不压差别可以忽略，统一按 32 KiB 门槛过一遍。
    compressed = 0
    wire_total = 0
    for entry in files:
        path = out / entry["file"]
        info = (
            {"encoding": None, "bytes": entry["bytes"], "wire_bytes": entry["bytes"]}
            if args.no_brotli
            else stage_brotli(path, quality=args.quality)
        )
        entry.update({"wire_bytes": info["wire_bytes"], "encoding": info["encoding"]})
        wire_total += info["wire_bytes"]
        compressed += 1 if info["encoding"] else 0
    archive_info = (
        {"encoding": None, "wire_bytes": archive["bytes"]}
        if args.no_brotli
        else stage_brotli(out / archive["file"], quality=args.quality)
    )
    archive.update({"wire_bytes": archive_info["wire_bytes"], "encoding": archive_info["encoding"]})
    wire_total += archive_info["wire_bytes"]
    compressed += 1 if archive_info["encoding"] else 0

    # 首屏要的字节：`loadPyodide` 自己会读 lock，所以它也算在内。
    core_files = (
        "pyodide.mjs",
        "pyodide.asm.mjs",
        "pyodide.asm.wasm",
        "python_stdlib.zip",
        "pyodide-lock.json",
    )
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
        #: 首屏（boot 到 `import ggcore` 可用）要的字节：运行时核心 + lock + 源码包。
        "boot_bytes": sum(entry["bytes"] for entry in core) + archive["bytes"],
        "boot_wire_bytes": sum(entry["wire_bytes"] for entry in core) + archive["wire_bytes"],
        "total_bytes": sum(entry["bytes"] for entry in files) + archive["bytes"],
        "wire_bytes": wire_total,
        "encoding": {
            "brotli_quality": args.quality,
            "files": compressed,
            "enabled": not args.no_brotli,
        },
        "note": (
            "generated by `pixi run pyodide:assets`; not committed. "
            "runtime never touches a CDN — every request is same-origin. "
            "`*.br` siblings are served with Content-Encoding: br (brotli_static)."
        ),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")

    for entry in files:
        wire = entry.get("wire_bytes", entry["bytes"])
        flag = "br" if entry.get("encoding") else "  "
        print(f"{entry['bytes']:>10,d} {wire:>10,d} {flag}  {entry['file']}")
    print(
        f"{archive['bytes']:>10,d} {archive['wire_bytes']:>10,d} "
        f"{'br' if archive.get('encoding') else '  '}  {archive['file']} "
        f"({archive['entries']} files, bytecode={archive['bytecode']})"
    )
    print(
        f"{manifest['boot_bytes']:>10,d} {manifest['boot_wire_bytes']:>10,d} "
        f"     boot bytes (core + archive)"
    )
    print(f"{manifest['total_bytes']:>10,d} {manifest['wire_bytes']:>10,d}      total staged bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
