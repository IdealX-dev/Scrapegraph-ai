"""Portable behavior checks: no application imports, credentials or paid calls."""
from __future__ import annotations

import hashlib
import json
import io
import os
import re
import shutil
import tarfile
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import optional_api
import preflight
import llmlingua_cli


class PortableChecks(unittest.TestCase):
    def test_compression_command_cannot_accept_unreviewed_text(self):
        with patch.object(sys, "argv", ["llmlingua", "--low-risk-prose", "--input", "evidence.txt"]), \
             patch.object(sys, "stderr"), patch.object(optional_api, "compress_notes") as compress:
            with self.assertRaises(SystemExit) as raised:
                llmlingua_cli.main()
        self.assertEqual(raised.exception.code, 2)
        compress.assert_not_called()

    def test_compression_command_version_does_not_load_model(self):
        with patch.object(sys, "argv", ["llmlingua", "--version"]), \
             patch.object(llmlingua_cli.importlib.metadata, "version", return_value="0.2.2"), \
             patch("builtins.print") as output:
            self.assertEqual(llmlingua_cli.main(), 0)
        output.assert_called_once_with("llmlingua 0.2.2")

    def test_hash_detects_changed_and_missing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            expected = hashlib.sha256(b"original").hexdigest()
            for name in preflight.REQUIRED_FILES:
                (kit / name).write_text("original")
            (kit / "manifest.json").write_text(json.dumps({"sha256": dict.fromkeys(preflight.REQUIRED_FILES, expected)}))
            self.assertEqual(preflight.verify_bundle(kit), [])
            (kit / "setup.sh").write_text("changed")
            self.assertEqual(preflight.verify_bundle(kit), ["setup.sh"])
            (kit / "setup.sh").unlink()
            self.assertEqual(preflight.verify_bundle(kit), ["setup.sh"])

    def test_manifest_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            (kit / "manifest.json").write_text(json.dumps({"sha256": {"../other": "invalid"}}))
            with self.assertRaises(ValueError):
                preflight.verify_bundle(kit)

    def test_version_drift_and_missing_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            (kit / "requirements.txt").write_text("ruff==1.0\nlitellm[proxy]==2.0\n")
            for name in ("ruff", "litellm"):
                (kit / name).write_text("executable")
                (kit / name).chmod(0o755)
            with patch.object(preflight.importlib.metadata, "version", side_effect=["1.0", "2.0"]):
                self.assertEqual(preflight.installed_drift(kit, bin_dir=kit), [])
            with patch.object(preflight.importlib.metadata, "version", side_effect=["0.9", preflight.importlib.metadata.PackageNotFoundError]):
                self.assertEqual(len(preflight.installed_drift(kit, bin_dir=kit)), 2)

    def test_real_git_tracks_staged_unstaged_untracked_and_base(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def git(*args):
                return subprocess.run(
                    ["git", "-c", "user.name=Tool Test", "-c", "user.email=test@example.invalid",
                     "-c", "core.hooksPath=" + str(root / "no-hooks"), *args], cwd=root,
                    check=True, capture_output=True, text=True,
                ).stdout.strip()

            git("init", "-q")
            (root / "tracked.py").write_text("before = True\n")
            (root / ".gitignore").write_text("ignored.py\n")
            git("add", "tracked.py", ".gitignore")
            git("commit", "-qm", "fixture")
            base = git("rev-parse", "HEAD")
            (root / "tracked.py").write_text("after = True\n")
            (root / "staged.py").write_text("staged = True\n")
            git("add", "staged.py")
            (root / "new file.pyi").write_text("answer: int\n")
            (root / "ignored.py").write_text("ignored = True\n")
            status = git("status", "--porcelain")
            self.assertEqual(preflight.changed_files(root=root), ["new file.pyi", "staged.py", "tracked.py"])
            self.assertEqual(git("status", "--porcelain"), status)
            git("commit", "-qm", "fixture addition")
            self.assertEqual(preflight.changed_files(base=base, root=root), ["staged.py"])

    def test_external_cache_is_rejected_without_mutation_or_api_call(self):
        external = object()
        client = ModuleType("litellm")
        client.cache = external
        client.completion = Mock()
        factory = Mock(return_value=SimpleNamespace(type="local"))
        cache_module = ModuleType("litellm.caching.caching")
        cache_module.Cache = factory
        with patch.dict(sys.modules, {"litellm": client, "litellm.caching.caching": cache_module}), patch.object(optional_api, "_owned_cache", None):
            with self.assertRaisesRegex(ValueError, "Existing LiteLLM cache preserved"):
                optional_api.api_completion(model="provider/model", messages=[])
        self.assertIs(client.cache, external)
        client.completion.assert_not_called()
        factory.assert_not_called()

    def test_local_cache_is_reused_with_bounded_retry_default(self):
        client = ModuleType("litellm")
        client.cache = None
        client.completion = Mock(return_value="response")
        factory = Mock(return_value=SimpleNamespace(type="local"))
        cache_module = ModuleType("litellm.caching.caching")
        cache_module.Cache = factory
        with patch.dict(sys.modules, {"litellm": client, "litellm.caching.caching": cache_module}), patch.object(optional_api, "_owned_cache", None):
            for _ in range(2):
                self.assertEqual(optional_api.api_completion(model="provider/model", messages=[]), "response")
        factory.assert_called_once_with(type="local", ttl=300)
        self.assertEqual(client.completion.call_args.kwargs["num_retries"], 0)
        self.assertTrue(client.completion.call_args.kwargs["caching"])

    def test_explicit_model_and_prose_guards(self):
        with self.assertRaises(ValueError):
            optional_api.api_completion(model="", messages=[])
        with self.assertRaises(ValueError):
            optional_api.compress_notes("source evidence", low_risk_prose=False)
        with self.assertRaises(ValueError):
            optional_api.compress_notes("prose", low_risk_prose=True, rate=0)


    def test_manifest_cannot_omit_required_instructions(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            (kit / "manifest.json").write_text(json.dumps({"sha256": {}}))
            self.assertIn("manifest missing: INSTRUCTIONS.txt", preflight.verify_bundle(kit))

    def test_metadata_does_not_hide_a_missing_console_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            kit = Path(temporary)
            (kit / "requirements.txt").write_text("ruff==1.0\n")
            with patch.object(preflight.importlib.metadata, "version", return_value="1.0"):
                self.assertEqual(preflight.installed_drift(kit, bin_dir=kit), ["ruff: missing executable"])

    def test_request_options_cannot_disable_safety(self):
        for options in ({"caching": False}, {"num_retries": 2}, {"fallbacks": ["other/model"]},
                        {"context_window_fallback_dict": {}}, {"ttl": 900}, {"stream": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                optional_api.api_completion(model="provider/model", messages=[], **options)

    def test_existing_global_routing_is_not_silently_used(self):
        client = ModuleType("litellm")
        client.cache = None
        client.model_alias_map = {"provider/model": "other/model"}
        client.completion = Mock()
        cache_module = ModuleType("litellm.caching.caching")
        cache_module.Cache = Mock()
        with patch.dict(sys.modules, {"litellm": client, "litellm.caching.caching": cache_module}):
            with self.assertRaisesRegex(ValueError, "routing preserved"):
                optional_api.api_completion(model="provider/model", messages=[])
        client.completion.assert_not_called()

    def test_cli_help_never_compresses_stdin(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("llmlingua_cli.py"))],
                                input="private original evidence", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Compression is not enabled", result.stdout)
        self.assertNotIn("private original evidence", result.stdout)


class InstallerChecks(unittest.TestCase):
    """Run the real installer with isolated paths and offline command doubles."""

    def run_installer(self, scenario):
        bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
        if not bash or not Path(bash).is_file():
            self.skipTest("Linux/WSL or Git Bash is required for installer tests")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kit, tools, fakebin = root / "kit", root / "tools with spaces", root / "fakebin"
            kit.mkdir()
            fakebin.mkdir()
            source = Path(__file__).resolve().parent
            for name in preflight.REQUIRED_FILES:
                original = source / name
                if name == "INSTRUCTIONS.txt" and not original.exists():
                    original = source.parent / name
                shutil.copyfile(original, kit / name)
            binary = b"#!/usr/bin/env bash\necho 'rtk 0.49.0'\n"
            archive = root / "fixture.tar.gz"
            with tarfile.open(archive, "w:gz") as package:
                info = tarfile.TarInfo("rtk")
                info.size, info.mode = len(binary), 0o755
                package.addfile(info, io.BytesIO(binary))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            setup = (kit / "setup.sh").read_text(encoding="utf-8")
            setup = re.sub(r"checksum=[a-f0-9]{64}", "checksum=" + digest, setup)
            (kit / "setup.sh").write_text(setup, encoding="utf-8", newline="\n")
            hashes = {name: hashlib.sha256((kit / name).read_text(encoding="utf-8").encode()).hexdigest()
                      for name in preflight.REQUIRED_FILES}
            (kit / "manifest.json").write_text(json.dumps({"sha256": hashes}))

            def executable(path, body):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
                path.chmod(0o755)

            executable(fakebin / "python3", f'exec "{Path(sys.executable).as_posix()}" "$@"\n')
            executable(fakebin / "node", 'if [ "$1" = "-p" ]; then printf "1.3.3"; fi\n')
            executable(fakebin / "npm", 'echo UNEXPECTED_NPM >&2; exit 1\n')
            executable(fakebin / "uname", 'if [ "$1" = "-s" ]; then echo Linux; else echo x86_64; fi\n')
            executable(fakebin / "curl", r'''
echo download >> "$TEST_CALLS"
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then shift; cp "$TEST_ARCHIVE" "$1"; exit 0; fi
  shift
done
exit 1
''')
            venv = tools / "python/bin"
            for name in ("ruff", "prek", "litellm"):
                executable(venv / name, "exit 0\n")
            executable(venv / "python", r'''
tool_bin=$(dirname -- "$0")
case "$*" in
  *--installed*)
    for tool in ruff prek litellm; do [ -x "$tool_bin/$tool" ] || exit 1; done ;;
  *--force-reinstall*)
    echo repair >> "$TEST_CALLS"
    for tool in ruff prek litellm; do
      printf '#!/usr/bin/env bash\nexit 0\n' > "$tool_bin/$tool"
      chmod 755 "$tool_bin/$tool"
    done ;;
esac
exit 0
''')
            executable(tools / "node/bin/caveman", "exit 0\n")
            (tools / "bin").mkdir()
            (tools / "requirements.sha256").write_text(
                hashlib.sha256((kit / "requirements.txt").read_bytes()).hexdigest() + "\n")
            cached = tools / "rtk-x86_64-unknown-linux-musl.tar.gz"
            shutil.copyfile(archive, cached)
            (tools / "bin/rtk").write_bytes(binary)
            (tools / "bin/rtk").chmod(0o755)
            if scenario == "missing-console":
                (venv / "ruff").unlink()
            elif scenario == "spoofed-binary":
                (tools / "bin/rtk").write_bytes(binary + b"# changed but same version\n")
            elif scenario == "tampered-archive":
                cached.write_bytes(b"untrusted")
            calls = root / "calls"
            env = dict(os.environ, PATH=str(fakebin) + os.pathsep + os.environ["PATH"],
                       IDEALX_COST_TOOLS_DIR=tools.as_posix(),
                       IDEALX_COST_TOOLS_SHELL_RC=(root / "isolated.bashrc").as_posix(),
                       TEST_ARCHIVE=archive.as_posix(), TEST_CALLS=calls.as_posix(),
                       TEST_FAKE_BIN=fakebin.as_posix(), TEST_SETUP=(kit / "setup.sh").as_posix(),
                       PYTHONUTF8="1")
            # Git Bash prepends its own system paths. Apply fixture paths inside
            # that shell, using its path mapper rather than guessing /c mounts.
            bootstrap = r'''
if command -v cygpath >/dev/null; then
  TEST_FAKE_BIN=$(cygpath -u "$TEST_FAKE_BIN")
  export IDEALX_COST_TOOLS_DIR=$(cygpath -u "$IDEALX_COST_TOOLS_DIR")
fi
export PATH="$TEST_FAKE_BIN:$PATH"
exec bash "$TEST_SETUP"
'''
            result = subprocess.run([bash, "--noprofile", "--norc", "-c", bootstrap],
                                    cwd=kit, env=env, capture_output=True, text=True,
                                    encoding="utf-8", timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((tools / "bin/rtk").read_bytes(), binary)
            self.assertTrue((venv / "ruff").is_file())
            return calls.read_text() if calls.exists() else ""

    def test_missing_console_script_is_repaired_with_metadata_retained(self):
        self.assertIn("repair", self.run_installer("missing-console"))

    def test_matching_version_cannot_hide_a_modified_binary(self):
        self.assertNotIn("download", self.run_installer("spoofed-binary"))

    def test_tampered_cached_archive_is_replaced_before_use(self):
        self.assertIn("download", self.run_installer("tampered-archive"))


if __name__ == "__main__":
    unittest.main()
