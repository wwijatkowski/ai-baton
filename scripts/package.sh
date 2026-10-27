#!/bin/sh
# Builds the .vsix. The CLI is copied into vscode-extension/cli/ by the extension's vscode:prepublish script
# (scripts/bundle-cli.sh), so every vsce package includes it; this script then checks the package contents.
# Usage: sh scripts/package.sh
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
EXT="$ROOT/vscode-extension"
VERSION=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$EXT/package.json")

cd "$EXT"
# The extension lives in a subfolder, so README links and images need explicit base URLs (served from GitHub).
BASE=https://github.com/wwijatkowski/ai-baton
npx --yes @vscode/vsce@4.0.0 package --out "$ROOT/ai-baton-$VERSION.vsix" \
  --baseContentUrl "$BASE/blob/HEAD/vscode-extension/" --baseImagesUrl "$BASE/raw/HEAD/vscode-extension/"
for f in extension/cli/VERSION extension/cli/BUILD extension/cli/bin/baton extension/cli/baton/cli.py extension/cli-install.js extension/LICENSE.txt; do
  unzip -l "$ROOT/ai-baton-$VERSION.vsix" "$f" >/dev/null || { echo "Missing in the package: $f"; exit 1; }
done
echo "Built ai-baton-$VERSION.vsix (CLI $VERSION included)"
