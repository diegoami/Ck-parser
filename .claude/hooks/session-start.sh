#!/bin/bash
# Installs the project's dependencies so tests run in Claude Code on the web.
# Idempotent; only runs in remote (web) sessions.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "${CLAUDE_ENV_FILE:-/dev/null}"
fi

uv sync --group dev
