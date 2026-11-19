"""Vendor the pinned, public Pyodide runtime; never reads API credentials."""
from pathlib import Path
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.29.0"
BASE = f"https://cdn.jsdelivr.net/pyodide/v{VERSION}/full/"
OUT = ROOT / "vendor/pyodide"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    def fetch(name, sha=None):
        p = OUT / name
        if p.is_file() and (sha is None or hashlib.sha256(p.read_bytes()).hexdigest() == sha):
            return p.read_bytes()
        raw = urllib.request.urlopen(BASE + name, timeout=120).read()
        if sha and hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError(f"Runtime hash mismatch: {name}")
        p.write_bytes(raw)
        return raw
    lock = json.loads(fetch("pyodide-lock.json"))
    for name in ("pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip"):
        fetch(name)
    pending, done = ["tiktoken", "ssl"], set()
    while pending:
        name = pending.pop()
        if name in done:
            continue
        done.add(name)
        pkg = lock["packages"][name]
        fetch(pkg["file_name"], pkg["sha256"])
        pending.extend(pkg["depends"])
    manifest = dict(version=VERSION, source=BASE, packages=sorted(done),
                    files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(OUT.iterdir()) if p.is_file()})
    (ROOT / "docs/runtime-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Pinned Pyodide {VERSION}, {len(manifest['files'])} runtime files")


if __name__ == "__main__":
    main()
