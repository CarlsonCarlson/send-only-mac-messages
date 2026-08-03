#!/bin/zsh

# Opened by LaunchServices in Carlson's GUI Terminal. The approved phone handle
# arrives through a mode-600 FIFO and is never stored in a regular file or put in
# a process argument or environment variable.

set -eu
umask 077

HOSTED_SCRIPT_DIR=${0:A:h}
HOSTED_RUNTIME_DIR=/tmp/send-only-mac-messages-hosted-canary
HOSTED_TARGET_FIFO=$HOSTED_RUNTIME_DIR/approved-target.fifo
HOSTED_STATUS_FILE=$HOSTED_RUNTIME_DIR/status.jsonl

if [[ "$(/usr/bin/id -un)" != "carlson" ]]; then
  /usr/bin/printf '{"phase":"failed","failure_class":"wrong_user"}\n' >&2
  exit 1
fi

if [[ ! -d "$HOSTED_RUNTIME_DIR" ]] || \
   [[ "$(/usr/bin/stat -f %Su "$HOSTED_RUNTIME_DIR")" != "carlson" ]] || \
   [[ ! -p "$HOSTED_TARGET_FIFO" ]] || \
   [[ "$(/usr/bin/stat -f %Su "$HOSTED_TARGET_FIFO")" != "carlson" ]] || \
   [[ "$(/usr/bin/stat -f %Lp "$HOSTED_TARGET_FIFO")" != "600" ]]; then
  /usr/bin/printf '{"phase":"failed","failure_class":"invalid_fifo"}\n' >&2
  exit 1
fi

/usr/bin/printf '{"phase":"terminal_started","target_transport":"fifo"}\n' \
  | /usr/bin/tee "$HOSTED_STATUS_FILE"

"$HOSTED_SCRIPT_DIR/run_hosted_canary_terminal.command" --send \
  < "$HOSTED_TARGET_FIFO" 2>&1 \
  | /usr/bin/tee -a "$HOSTED_STATUS_FILE"
HOSTED_SEND_EXIT=${pipestatus[1]}

/bin/rm -f "$HOSTED_TARGET_FIFO"
/usr/bin/printf \
  '{"phase":"terminal_finished","exit_code":%d,"fifo_removed":true}\n' \
  "$HOSTED_SEND_EXIT" \
  | /usr/bin/tee -a "$HOSTED_STATUS_FILE"

exit "$HOSTED_SEND_EXIT"
