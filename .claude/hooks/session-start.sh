#!/bin/bash
# Install the NVIDIA SkillSpector CLI (used by the skill-inspector skill) in cloud sessions.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

SKILLSPECTOR_REV="3c8e4b958fda9602e0044885f766be0e49f03585"

if ! command -v skillspector >/dev/null 2>&1; then
  uv tool install "skillspector[mcp] @ git+https://github.com/NVIDIA/skillspector.git@${SKILLSPECTOR_REV}"
fi

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
fi
