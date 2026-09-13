# Cost tools: local and cloud

Generated from `IdealX-dev/idealx-claude-standards/cost-aware`; change the
canonical kit and redistribute it. Existing application dependencies, provider
credentials, hooks and required tests remain authoritative.

In Codex Cloud **setup and maintenance scripts**, append:

```bash
bash .codex/cost-tools/setup.sh
```

The script installs pinned tools into user-owned isolated environments, caches
them, verifies RTK's release hash, persists command paths, and repairs missing
executables. It does not enable a proxy, alter billing, select a Codex model,
send application requests or overwrite existing Git hooks. Setup needs network;
ordinary checks do not. Existing cloud setup commands must remain in place.
Commands live in `$HOME/.local/share/idealx-cost-tools/bin`; setup adds that
directory to `.bashrc` without replacing existing commands. In an existing
noninteractive shell, prepend that directory to PATH before using the tools.

Before committing, run:

```bash
python .codex/cost-tools/preflight.py
```

It checks bundle integrity and runs Ruff via prek against changed Python files,
without stashing, formatting or modifying the index. Existing project checks
still apply. CI runs the same check against the PR diff. With no changes it
checks only the bundle, not the whole repository.

Use RTK for supported noisy output, or `caveman shrink -- <read-only command>`.
Keep full evidence for reviews and failures. Do not compress twice.

LiteLLM is available for API-backed development through `api_completion()` in
`optional_api.py`: explicit model, exact-request memory caching, bounded retries,
no model substitution or background service. Use an already authorized provider
and run the helper in a process without an existing LiteLLM cache; it rejects
other caches to prevent unintended persistence or sharing. Use the provider's
normal environment credentials; a ChatGPT subscription is not an API
key. No application endpoint is changed by installation.

LLMLingua is available through `compress_notes()` in the same module. It runs
locally on CPU and downloads the public Microsoft compression model on first
use. Only low-risk prose is eligible. Code, instructions, real freight facts,
secrets and evidence are excluded. Preserve the original and compare quality
before adopting a compressed result. Merely installing it proves no savings.
The `llmlingua` command exposes help and version only; it accepts no text.
`compress_notes()` is a candidate-generation library for reviewed callers, not
an automatic safety classifier or production pipeline. Its boolean is caller
attestation, not validation. A caller must establish input eligibility and
evaluate candidate quality against the retained original before using it.

`preflight.py` checks kit hashes; `--installed` additionally checks pinned Python
versions in the isolated environment. Setup repairs missing or drifted tools.
Do not rewrite source or reduce validation
automatically. RTK bytes, provider tokens and actual invoice charges are different
measurements. Report only the one that was measured.
