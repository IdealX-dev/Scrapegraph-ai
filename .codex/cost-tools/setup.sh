#!/usr/bin/env bash
set -euo pipefail
kit=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [ "$(uname -s)" != Linux ]; then
  echo 'This installer requires Linux or WSL; native Windows uses the Windows command installer.' >&2
  exit 1
fi
for prerequisite in python3 node npm curl tar sha256sum; do
  command -v "$prerequisite" >/dev/null || { echo "Missing prerequisite: $prerequisite" >&2; exit 1; }
done
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) process.exit(1)' || {
  echo 'Node.js 22 or newer is required; this kit does not replace the host runtime.' >&2; exit 1;
}
tools_dir="${IDEALX_COST_TOOLS_DIR:-$HOME/.local/share/idealx-cost-tools}"
bin_dir="$tools_dir/bin"
mkdir -p "$tools_dir" "$bin_dir"
export PATH="$bin_dir:$tools_dir/node/bin:$PATH"
export PIP_DISABLE_PIP_VERSION_CHECK=1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
python3 "$kit/preflight.py" --verify-only
stamp=$(sha256sum "$kit/requirements.txt" | cut -d ' ' -f 1)
if [ ! -x "$tools_dir/python/bin/python" ]; then
  python3 -m venv "$tools_dir/python"
fi
if [ ! -f "$tools_dir/requirements.sha256" ] ||
   [ "$(cat "$tools_dir/requirements.sha256")" != "$stamp" ] ||
   ! "$tools_dir/python/bin/python" "$kit/preflight.py" --installed >/dev/null 2>&1; then
  "$tools_dir/python/bin/python" -m pip install --quiet 'torch==2.14.0+cpu' --index-url https://download.pytorch.org/whl/cpu
  "$tools_dir/python/bin/python" -m pip install --quiet -r "$kit/requirements.txt"
  # pip can consider a distribution installed even when its console script is gone.
  if ! "$tools_dir/python/bin/python" "$kit/preflight.py" --installed >/dev/null 2>&1; then
    "$tools_dir/python/bin/python" -m pip install --quiet --force-reinstall --no-deps \
      'ruff==0.16.7' 'prek==0.5.3' 'litellm[proxy]==1.100.1'
  fi
  "$tools_dir/python/bin/python" -m pip check
  "$tools_dir/python/bin/python" -m pip freeze --all > "$tools_dir/installed-closure.txt"
  printf '%s\n' "$stamp" > "$tools_dir/requirements.sha256"
fi
for tool in ruff prek litellm; do
  ln -sfn "$tools_dir/python/bin/$tool" "$bin_dir/$tool"
done
if [ ! -x "$tools_dir/node/bin/caveman" ] ||
   ! "$tools_dir/node/bin/caveman" --version >/dev/null 2>&1 ||
   [ "$(node -p "require('$tools_dir/node/lib/node_modules/@caveman-ai/cli/package.json').version" 2>/dev/null || true)" != '1.3.3' ]; then
  npm install --global --prefix "$tools_dir/node" --no-audit --no-fund '@caveman-ai/cli@1.3.3'
fi
ln -sfn "$tools_dir/node/bin/caveman" "$bin_dir/caveman"
mkdir -p "$tools_dir/lib"
cp -- "$kit/optional_api.py" "$kit/llmlingua_cli.py" "$tools_dir/lib/"
printf '#!/usr/bin/env bash\nexec "%s" "%s" "$@"\n' \
  "$tools_dir/python/bin/python" "$tools_dir/lib/llmlingua_cli.py" > "$bin_dir/llmlingua"
chmod 755 "$bin_dir/llmlingua"
case "$(uname -m)" in
  x86_64) asset=rtk-x86_64-unknown-linux-musl.tar.gz; checksum=7278231dfd7e6a730a4ab7f847b195bcf02289c2d57622b0dab75a6411100c8f ;;
  aarch64|arm64) asset=rtk-aarch64-unknown-linux-gnu.tar.gz; checksum=c8ea4b6560841e73157c134fd4a3293914c6ede42e786ee985cf491fde691ba7 ;;
  *) echo 'Unsupported RTK architecture; no fallback binary installed' >&2; exit 1 ;;
esac
archive="$tools_dir/$asset"
if ! printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check --status 2>/dev/null; then
  curl --fail --location --silent --show-error --max-time 120 \
    "https://github.com/rtk-ai/rtk/releases/download/v0.49.0/$asset" -o "$archive.download"
  printf '%s  %s\n' "$checksum" "$archive.download" | sha256sum --check --status
  mv -- "$archive.download" "$archive"
fi
binary_checksum=$(tar -xOzf "$archive" rtk | sha256sum | cut -d ' ' -f 1)
if [ ! -x "$bin_dir/rtk" ] || ! printf '%s  %s\n' "$binary_checksum" "$bin_dir/rtk" | sha256sum --check --status 2>/dev/null; then
  tar -xOzf "$archive" rtk > "$bin_dir/rtk.new"
  chmod 755 "$bin_dir/rtk.new"
  mv -- "$bin_dir/rtk.new" "$bin_dir/rtk"
fi
# Setup and agent phases are separate shells. Persist PATH as documented by Codex.
path_line='export PATH="${IDEALX_COST_TOOLS_DIR:-$HOME/.local/share/idealx-cost-tools}/bin:$PATH"'
shell_rc="${IDEALX_COST_TOOLS_SHELL_RC:-$HOME/.bashrc}"
touch "$shell_rc"
grep -Fqx "$path_line" "$shell_rc" || printf '\n%s\n' "$path_line" >> "$shell_rc"
"$tools_dir/python/bin/python" "$kit/preflight.py" --installed
ruff --version
prek --version
rtk --version
caveman --version
llmlingua --help >/dev/null
printf 'Cost tools ready. Application providers and active Git hooks unchanged.\n'
