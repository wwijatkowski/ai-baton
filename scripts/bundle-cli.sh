#!/bin/sh
# Copies the CLI (baton/ and bin/) into vscode-extension/cli/ with a VERSION file. Runs as the extension's
# vscode:prepublish script, so any `vsce package` or `vsce publish` includes the CLI.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
EXT="$ROOT/vscode-extension"
VERSION=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$EXT/package.json")
rm -rf "$EXT/cli"
mkdir -p "$EXT/cli/bin"
cp -R "$ROOT/baton" "$EXT/cli/baton"
cp "$ROOT/bin/baton" "$EXT/cli/bin/baton"
find "$EXT/cli" -name '__pycache__' -type d -prune -exec rm -rf {} +
echo "$VERSION" > "$EXT/cli/VERSION"
echo "Bundled CLI $VERSION into $EXT/cli"
