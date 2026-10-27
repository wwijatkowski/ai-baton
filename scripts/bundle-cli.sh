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
# A hash of the bundled files: the extension reinstalls the CLI when it changes, even with the same version (test builds).
python3 - "$EXT/cli" <<'PY' > "$EXT/cli/BUILD"
import hashlib, pathlib, sys
root, digest = pathlib.Path(sys.argv[1]), hashlib.sha256()
for path in sorted(p for p in root.rglob('*') if p.is_file() and p.name != 'BUILD'):
    digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
print(digest.hexdigest()[:12])
PY
echo "Bundled CLI $VERSION into $EXT/cli"
