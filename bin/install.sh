#!/bin/bash
# Refresh Cynthia's installed package metadata without changing dependencies.
# Run after a version bump, then use /restart so /about and the watermark update.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python="$root/env/bin/python"

if [[ ! -x "$python" ]]; then
    echo "Missing $python; create the env virtualenv first." >&2
    exit 1
fi

expected=$(
    "$python" - "$root/pyproject.toml" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as file:
    print(tomllib.load(file)["project"]["version"])
PY
)

"$python" -m pip install --no-deps -e "$root"
installed=$("$python" -c "from importlib.metadata import version; print(version('cynthia'))")

if [[ "$installed" != "$expected" ]]; then
    echo "Installed Cynthia $installed, but pyproject.toml declares $expected." >&2
    exit 1
fi

echo "Installed Cynthia $installed. Run /restart to apply it to /about and the watermark."
