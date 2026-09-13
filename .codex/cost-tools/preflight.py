"""Verify the distributed kit and run non-mutating checks on changed files."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

KIT = Path(__file__).resolve().parent


def installed_drift(kit: Path = KIT) -> list[str]:
    failures = []
    for line in (kit / "requirements.txt").read_text(encoding="utf-8").splitlines():
        name, expected = line.split("==")
        name = name.split("[")[0]
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "missing"
        if actual != expected:
            failures.append(f"{name}: {actual}; expected {expected}")
    return failures


def verify_bundle(kit: Path = KIT) -> list[str]:
    manifest = json.loads((kit / "manifest.json").read_text(encoding="utf-8"))
    failures = []
    for name, expected in manifest["sha256"].items():
        target = (kit / name).resolve()
        if not target.is_relative_to(kit.resolve()):
            raise ValueError("Manifest path escapes the kit")
        if not target.is_file() or hashlib.sha256(target.read_text(encoding="utf-8").encode("utf-8")).hexdigest() != expected:
            failures.append(name)
    return failures


def changed_files(base: str | None = None, root: Path | None = None) -> list[str]:
    args = ["git", "diff", "--name-only", "--diff-filter=ACMR", "-z"]
    groups = [[f"{base}...HEAD"]] if base else [["--cached"], []]
    found = set()
    for extra in groups:
        result = subprocess.run(args + extra + ["--"], cwd=root, check=True,
                                capture_output=True)
        found.update(p for p in result.stdout.decode("utf-8").split("\0") if p)
    if base is None:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "*.py", "*.pyi"],
            cwd=root, check=True, capture_output=True,
        )
        found.update(p for p in result.stdout.decode("utf-8").split("\0") if p)
    return sorted(p for p in found if p.endswith((".py", ".pyi")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    failures = verify_bundle()
    if failures:
        print("Cost kit drift: " + ", ".join(failures), file=sys.stderr)
        return 1
    if args.installed:
        failures = installed_drift()
        if failures:
            print("Cost tool version drift: " + ", ".join(failures), file=sys.stderr)
            return 1
        print("Pinned Python tool versions passed")
        return 0
    if args.verify_only:
        print("Cost kit integrity passed")
        return 0
    files = changed_files(args.base)
    if not files:
        print("Cost kit integrity passed; no changed Python files")
        return 0
    # Explicit files prevent prek from stashing unrelated working-tree changes.
    return subprocess.run(["prek", "run", "--config", str(KIT / "pre-commit.yaml"),
                           "--files", *files], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
