"""Verify the distributed kit and run non-mutating checks on changed files."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

KIT = Path(__file__).resolve().parent
REQUIRED_FILES = frozenset({"INSTRUCTIONS.txt", "README.md", "llmlingua_cli.py",
                           "optional_api.py", "pre-commit.yaml", "preflight.py",
                           "requirements.txt", "setup.sh", "test_preflight.py"})


def installed_drift(kit: Path = KIT, bin_dir: Path | None = None) -> list[str]:
    failures = []
    bin_dir = bin_dir or Path(sys.executable).parent
    for line in (kit / "requirements.txt").read_text(encoding="utf-8").splitlines():
        name, expected = line.split("==")
        name = name.split("[")[0]
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "missing"
        if actual != expected:
            failures.append(f"{name}: {actual}; expected {expected}")
        if name in {"ruff", "prek", "litellm"}:
            executable = bin_dir / name
            if not executable.is_file() or not os.access(executable, os.X_OK):
                failures.append(f"{name}: missing executable")
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
    listed = set(manifest["sha256"])
    failures.extend(f"manifest missing: {name}" for name in sorted(REQUIRED_FILES - listed))
    failures.extend(f"manifest unexpected: {name}" for name in sorted(listed - REQUIRED_FILES))
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
