"""Portable behavior checks: no application imports, credentials or paid calls."""
from __future__ import annotations

import hashlib
import json
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
            (kit / "manifest.json").write_text(json.dumps({"sha256": {"source.py": expected}}))
            (kit / "source.py").write_text("original")
            self.assertEqual(preflight.verify_bundle(kit), [])
            (kit / "source.py").write_text("changed")
            self.assertEqual(preflight.verify_bundle(kit), ["source.py"])
            (kit / "source.py").unlink()
            self.assertEqual(preflight.verify_bundle(kit), ["source.py"])

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
            with patch.object(preflight.importlib.metadata, "version", side_effect=["1.0", "2.0"]):
                self.assertEqual(preflight.installed_drift(kit), [])
            with patch.object(preflight.importlib.metadata, "version", side_effect=["0.9", preflight.importlib.metadata.PackageNotFoundError]):
                self.assertEqual(len(preflight.installed_drift(kit)), 2)

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


if __name__ == "__main__":
    unittest.main()
