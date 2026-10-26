#!/bin/sh
# Builds the .vsix. The CLI is copied into vscode-extension/cli/ by the extension's vscode:prepublish script
# (scripts/bundle-cli.sh), so every vsce package includes it; this script then checks the package contents.
# Usage: sh scripts/package.sh
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
EXT="$ROOT/vscode-extension"
VERSION=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$EXT/package.json")

cd "$EXT"
npx --yes @vscode/vsce package --out "$ROOT/ai-baton-$VERSION.vsix"
for f in extension/cli/VERSION extension/cli/bin/baton extension/cli/baton/cli.py extension/cli-install.js extension/LICENSE.txt; do
  unzip -l "$ROOT/ai-baton-$VERSION.vsix" "$f" >/dev/null || { echo "Missing in the package: $f"; exit 1; }
done
echo "Built ai-baton-$VERSION.vsix (CLI $VERSION included)"
