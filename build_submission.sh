#!/usr/bin/env bash
# Build submission zip script (Shell wrapper for build_submission.py)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: Python installation not found." >&2
    exit 1
fi

"$PYTHON_CMD" "$SCRIPT_DIR/build_submission.py" "$@"
