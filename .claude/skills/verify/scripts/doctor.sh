#!/usr/bin/env bash
# Read-only: is this Mac worth driving? Never sends. Usage: doctor.sh [chat-id]
set -u
cd "$(dirname "$0")/../../../.."
ok=0
check() { if "$@" >/dev/null 2>&1; then echo "ok   $*"; else echo "FAIL $*"; ok=1; fi; }
check test -d .venv
check uv run --frozen python -c "import mcp, send_only_mac_messages.server"
check uv run --frozen python scripts/bump_version.py --check
check pgrep -x Messages
check sqlite3 -readonly "$HOME/Library/Messages/chat.db" "select 1 from chat limit 1"
echo "services: $(osascript -e 'tell application "Messages" to get count of every service' 2>&1)"
if [ "${1:-}" != "" ]; then
  n=$(sqlite3 -readonly "$HOME/Library/Messages/chat.db" \
    "select count(*) from chat_handle_join j join chat c on c.ROWID=j.chat_id where c.guid='$1'")
  echo "target chat '$1' participants: ${n:-?}"
  [ "${n:-0}" -gt 0 ] || ok=1
fi
exit $ok
