#!/bin/zsh
set -eu
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -m sentinel
fi
if command -v uv >/dev/null 2>&1; then
  exec uv run python -m sentinel
fi
printf 'Install uv using https://docs.astral.sh/uv/getting-started/installation/ then run: uv sync\n'
exit 1
