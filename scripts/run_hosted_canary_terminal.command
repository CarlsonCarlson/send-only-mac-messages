#!/bin/zsh

# One-shot launcher that must run under Carlson's visible Terminal GUI process.

set -eu

HOSTED_SCRIPT_DIR=${0:A:h}
HOSTED_REPO_DIR=${HOSTED_SCRIPT_DIR:h}
HOSTED_MODE=${1:---smoke}

if [[ "$(/usr/bin/id -un)" != "carlson" ]]; then
  /usr/bin/printf '{"phase":"failed","failure_class":"wrong_user"}\n' >&2
  exit 1
fi

if [[ "$(/usr/bin/stat -f %Su /dev/console)" != "$(/usr/bin/id -un)" ]]; then
  /usr/bin/printf '{"phase":"failed","failure_class":"wrong_console_user"}\n' >&2
  exit 1
fi

HOSTED_PARENT_PID=$PPID
HOSTED_TERMINAL_FOUND=false
while (( HOSTED_PARENT_PID > 1 )); do
  HOSTED_PARENT_COMMAND=$(/bin/ps -p "$HOSTED_PARENT_PID" -o command=)
  if [[ "$HOSTED_PARENT_COMMAND" == *"/Terminal.app/Contents/MacOS/Terminal"* ]]; then
    HOSTED_TERMINAL_FOUND=true
    break
  fi
  HOSTED_PARENT_PID=$(/bin/ps -p "$HOSTED_PARENT_PID" -o ppid= | /usr/bin/tr -d ' ')
done

if [[ "$HOSTED_TERMINAL_FOUND" != true ]]; then
  /usr/bin/printf '{"phase":"failed","failure_class":"not_terminal_owned"}\n' >&2
  exit 1
fi

if /usr/bin/command -v uv >/dev/null 2>&1; then
  HOSTED_UV_BIN=$(/usr/bin/command -v uv)
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  HOSTED_UV_BIN="$HOME/.local/bin/uv"
else
  /usr/bin/printf '{"phase":"failed","failure_class":"uv_missing"}\n' >&2
  exit 1
fi

case "$HOSTED_MODE" in
  --smoke|--send)
    ;;
  *)
    /usr/bin/printf '{"phase":"failed","failure_class":"invalid_mode"}\n' >&2
    exit 2
    ;;
esac

cd "$HOSTED_REPO_DIR"

if [[ "$HOSTED_MODE" == "--smoke" ]]; then
  "$HOSTED_UV_BIN" run --frozen python scripts/hosted_canary.py --smoke-only
  exit $?
fi

"$HOSTED_UV_BIN" run --frozen python scripts/hosted_canary.py
