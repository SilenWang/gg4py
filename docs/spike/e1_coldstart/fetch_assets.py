"""Stage the bytes the E1 cold-start page downloads, locally (no CDN at runtime).

Inputs
  node_modules/pyodide/            installed by `npm install --no-save --no-package-lock pyodide@V`
  pyodide-lock.json                shipped by that package; names + sha256 of every wheel

Outputs (git-ignored, recreated by `pixi run spike:e1:assets`)
  static/pyodide/pyodide.{mjs,js,asm.wasm,asm.mjs}   runtime + wasm
  static/pyodide/python_stdlib.zip                   stdlib
  static/pyodide/pyodide-lock.json                   package index (our own copy)
  static/pyodide/<wheel>                             numpy / pandas / their pure-Python deps
  static/manifest.json                               sizes + sha256 + where each byte came from

The page under test must never touch a CDN: the measured cold start has to be a
function of the payload we ship, not of a mirror's mood.  Wheels are downloaded
once here, at build time, from the first mirror that answers; the source URL is
recorded in the manifest so a rerun on another machine stays auditable.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
REPO = SPIKE.parent.parent
OUT = HERE / "static"
PYODIDE_OUT = OUT / "pyodide"
PKG_VERSION = "314.0.7"

# Wheels are needed for the baseline (numpy) and for the "+pandas" sensitivity
# variant.  pyodide-lock.json gives the exact file name and sha256.
WHEELS = ["numpy", "pandas", "python-dateutil", "pytz", "six"]

# Tried in order; the first 200/206 wins.  jsdelivr is the canonical Pyodide
# package host; the npmmirror copy is the fallback for networks where it is
# blocked.  Both are build-time only.
MIRRORS = [
    "https://cdn.jsdelivr.net/pyodide/v{version}/full/{file}",
    "https://registry.npmmirror.com/pyodide/{version}/files/full/{file}",
    "https://raw.githubusercontent.com/pyodide/pyodide/{version}/dist/{file}",
]

CORE_FILES = [
    "pyodide.mjs",
    "pyodide.js",
    "pyodide.asm.mjs",
    "pyodide.asm.wasm",
    "python_stdlib.zip",
    "pyodide-lock.json",
]


def package_dir() -> Path:
    candidates = [
        # `spike:e1:assets` installs into its own prefix so it cannot prune the
        # canvaskit-wasm package that E2 keeps in the repo-level node_modules.
        HERE / ".npm" / "node_modules" / "pyodide",
        REPO / "node_modules" / "pyodide",
    ]
    for pkg in candidates:
        if (pkg / "pyodide-lock.json").is_file():
            return pkg
    sys.exit(
        "pyodide npm package not found - run `pixi run spike:e1:assets` "
        f"(it installs pyodide@{PKG_VERSION} first)."
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def copy_core(pkg: Path) -> list[dict]:
    out = []
    for name in CORE_FILES:
        src = pkg / name
        if not src.is_file():
            sys.exit(f"pyodide package is missing {name}")
        data = src.read_bytes()
        (PYODIDE_OUT / name).write_bytes(data)
        out.append(
            {
                "file": f"pyodide/{name}",
                "bytes": len(data),
                "sha256": sha256_bytes(data),
                "source": f"npm pyodide@{PKG_VERSION}",
            }
        )
    return out


def fetch_wheel(lock: dict, name: str) -> dict:
    pkg = lock["packages"][name]
    file_name = pkg["file_name"]
    dest = PYODIDE_OUT / file_name
    if dest.is_file() and sha256_bytes(dest.read_bytes()) == pkg["sha256"]:
        return {
            "file": f"pyodide/{file_name}",
            "package": name,
            "version": pkg["version"],
            "bytes": dest.stat().st_size,
            "sha256": pkg["sha256"],
            "source": "cached",
        }

    errors = []
    for mirror in MIRRORS:
        url = mirror.format(version=PKG_VERSION, file=file_name)
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
        except Exception as exc:  # report every mirror we tried
            errors.append(f"{url}: {exc}")
            continue
        got = sha256_bytes(data)
        if got != pkg["sha256"]:
            errors.append(f"{url}: sha256 {got} != {pkg['sha256']}")
            continue
        dest.write_bytes(data)
        return {
            "file": f"pyodide/{file_name}",
            "package": name,
            "version": pkg["version"],
            "bytes": len(data),
            "sha256": got,
            "source": url,
        }

    sys.exit(f"could not fetch {file_name} from any mirror:\n  " + "\n  ".join(errors))


def main() -> int:
    pkg = package_dir()
    OUT.mkdir(parents=True, exist_ok=True)
    PYODIDE_OUT.mkdir(parents=True, exist_ok=True)

    lock = json.loads((pkg / "pyodide-lock.json").read_text(encoding="utf-8"))
    files = copy_core(pkg)
    files.extend(fetch_wheel(lock, name) for name in WHEELS)

    total = sum(f["bytes"] for f in files)
    manifest = {
        "pyodide_version": PKG_VERSION,
        "abi": lock["info"],
        "files": files,
        "total_disk_bytes": total,
        "note": (
            "static/ is generated and git-ignored; `pixi run spike:e1:assets` "
            "recreates it byte for byte (sha256 above)."
        ),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")

    for f in files:
        print(f"{f['bytes']:>10,d}  {f['file']}  <- {f['source']}")
    print(f"{total:>10,d}  total on disk ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
