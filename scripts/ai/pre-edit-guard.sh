#!/usr/bin/env bash
# Claude Code PreToolUse hook (matcher Edit|Write|MultiEdit), see .claude/settings.json.
# Exit 2 blocks the edit and shows the reason to the agent. Logic: pre_edit_guard.py.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$here/pre_edit_guard.py"
