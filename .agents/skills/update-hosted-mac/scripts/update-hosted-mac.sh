#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: .agents/skills/update-hosted-mac/scripts/update-hosted-mac.sh [options]

Deploy the exact tracked HEAD of send-only-mac-messages to the hosted Mac.
An update restores an existing matching LaunchAgent after the source swap.
It never creates a sender service or sends a message.

Options:
  --skip-local-gates  Skip local version, test, format, and type gates.
  --dry-run           Run local and remote preflight without changing remote files.
  -h, --help          Show this help.

Environment:
  HOSTED_MAC_SSH_TARGET     Default: kevinhom@192.30.129.13
  HOSTED_MAC_PASSWORD_FILE Default: secrets/hosted-mac-ssh-password
  UV_VERSION               Default: 0.11.19
  REMOTE_PYTHON_VERSION    Default: 3.13
  UV_BIN                   Optional local uv executable override
USAGE
}

RUN_LOCAL_GATES=1
DRY_RUN=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --skip-local-gates)
      RUN_LOCAL_GATES=0
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$REPO_ROOT"

HOSTED_MAC_SSH_TARGET="${HOSTED_MAC_SSH_TARGET:-kevinhom@192.30.129.13}"
HOSTED_MAC_PASSWORD_FILE="${HOSTED_MAC_PASSWORD_FILE:-secrets/hosted-mac-ssh-password}"
UV_VERSION="${UV_VERSION:-0.11.19}"
REMOTE_PYTHON_VERSION="${REMOTE_PYTHON_VERSION:-3.13}"
UV_BIN="${UV_BIN:-}"

case "$HOSTED_MAC_SSH_TARGET" in
  *@*) TARGET_USER=${HOSTED_MAC_SSH_TARGET%@*} ;;
  *) echo "HOSTED_MAC_SSH_TARGET must use user@host form" >&2; exit 2 ;;
esac
case "$TARGET_USER" in
  ''|*[!a-zA-Z0-9._-]*) echo "Invalid SSH target username" >&2; exit 2 ;;
esac
case "$UV_VERSION" in
  ''|*[!0-9.]*) echo "UV_VERSION must contain only digits and dots" >&2; exit 2 ;;
esac
case "$REMOTE_PYTHON_VERSION" in
  ''|*[!0-9.]*) echo "REMOTE_PYTHON_VERSION must contain only digits and dots" >&2; exit 2 ;;
esac

if [ ! -f "$HOSTED_MAC_PASSWORD_FILE" ]; then
  echo "Hosted Mac password file not found: $HOSTED_MAC_PASSWORD_FILE" >&2
  exit 1
fi
if [ "$(stat -f %Lp "$HOSTED_MAC_PASSWORD_FILE")" != "600" ]; then
  echo "Hosted Mac password file must have mode 600" >&2
  exit 1
fi

for required in git ssh sshpass tar; do
  if ! command -v "$required" >/dev/null 2>&1; then
    echo "Missing required command: $required" >&2
    exit 1
  fi
done

if [ -z "$UV_BIN" ]; then
  UV_BIN="$(command -v uv || true)"
fi
if [ "$RUN_LOCAL_GATES" = "1" ] && [ -z "$UV_BIN" ]; then
  echo "Local uv is required unless --skip-local-gates is used" >&2
  exit 1
fi

LOCAL_HEAD="$(git rev-parse HEAD)"
LOCAL_TREE="$(git rev-parse 'HEAD^{tree}')"
LOCAL_BRANCH="$(git branch --show-current)"
LOCAL_VERSION="$(sed -n '/^\[project\]/,/^\[/p' pyproject.toml | sed -n 's/^version = "\([^"]*\)"/\1/p' | head -1)"
if [ -z "$LOCAL_VERSION" ]; then
  echo "Could not read project version from pyproject.toml" >&2
  exit 1
fi

EVIDENCE_DIR=/tmp/send-only-mac-messages
TIMESTAMP="$(date +%Y%m%dT%H%M%S%z)"
EVIDENCE_LOG="$EVIDENCE_DIR/update-hosted-mac-$TIMESTAMP.log"
REMOTE_STAGE_NAME=".send-only-mac-messages-stage-$TIMESTAMP"
REMOTE_BACKUP_NAME=".send-only-mac-messages-backup-$TIMESTAMP"
REMOTE_FAILED_NAME=".send-only-mac-messages-failed-$TIMESTAMP"
mkdir -p "$EVIDENCE_DIR"
: > "$EVIDENCE_LOG"

redact_stream() {
  perl -pe 's/(Authorization:[[:space:]]*Bearer)[[:space:]]+\S+/$1 [REDACTED]/gi; s/(password:).+/$1 [REDACTED]/gi'
}

log() {
  printf '%s\n' "$*" | tee -a "$EVIDENCE_LOG"
}

run_logged() {
  local label=$1
  shift
  log ""
  log "## $label"
  date -u '+%Y-%m-%dT%H:%M:%SZ' | tee -a "$EVIDENCE_LOG" >/dev/null
  set +e
  (set -e; "$@") 2>&1 | redact_stream | tee -a "$EVIDENCE_LOG"
  local rc=${PIPESTATUS[0]}
  set -e
  printf '[%s exit=%s]\n' "$label" "$rc" >> "$EVIDENCE_LOG"
  return "$rc"
}

SSH_OPTIONS=(
  -o StrictHostKeyChecking=accept-new
  -o IdentitiesOnly=yes
  -o PreferredAuthentications=password,keyboard-interactive
  -o PubkeyAuthentication=no
)

ssh_remote() {
  sshpass -f "$HOSTED_MAC_PASSWORD_FILE" ssh \
    "${SSH_OPTIONS[@]}" \
    "$HOSTED_MAC_SSH_TARGET" \
    "$@"
}

local_identity() {
  printf 'branch=%s\n' "${LOCAL_BRANCH:-detached}"
  printf 'commit=%s\n' "$LOCAL_HEAD"
  printf 'tree=%s\n' "$LOCAL_TREE"
  printf 'version=%s\n' "$LOCAL_VERSION"
  printf 'deployment_source=tracked_HEAD\n'
  printf 'worktree_status_begin\n'
  git status --short
  printf 'worktree_status_end\n'
}

local_gates() {
  "$UV_BIN" run --frozen python scripts/bump_version.py --check --expected "$LOCAL_VERSION"
  "$UV_BIN" run --frozen pytest -q
  "$UV_BIN" run --frozen black --check .
  "$UV_BIN" run --frozen isort --check-only .
  "$UV_BIN" run --frozen mypy send_only_mac_messages
}

remote_preflight() {
  ssh_remote bash -s -- "$TARGET_USER" <<'REMOTE'
set -euo pipefail
EXPECTED_USER=$1
ACTUAL_USER=$(id -un)
[ "$ACTUAL_USER" = "$EXPECTED_USER" ] || {
  echo "Remote user mismatch: expected $EXPECTED_USER, found $ACTUAL_USER" >&2
  exit 1
}
TARGET="$HOME/dev/send-only-mac-messages"
TARGET_UID=$(id -u)
CONSOLE_USER=$(stat -f %Su /dev/console)
printf 'remote_user=%s\n' "$ACTUAL_USER"
printf 'remote_home=%s\n' "$HOME"
printf 'console_user=%s\n' "$CONSOLE_USER"
printf 'arch=%s\n' "$(uname -m)"
printf 'os=%s\n' "$(sw_vers -productVersion)"
if [ -e "$TARGET" ]; then
  [ "$(stat -f %Su "$TARGET")" = "$ACTUAL_USER" ] || {
    echo "Existing target is not owned by the remote user" >&2
    exit 1
  }
  printf 'existing_checkout=true\n'
  if [ -f "$TARGET/.deployed-version.json" ]; then
    python3 - "$TARGET/.deployed-version.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
print("existing_commit=" + str(payload.get("commit", "unknown")))
print("existing_version=" + str(payload.get("version", "unknown")))
PY
  fi
else
  printf 'existing_checkout=false\n'
fi
LABEL=ai.mynimbus.send-only-mac-messages.remote
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
if launchctl print "gui/$TARGET_UID/$LABEL" >/dev/null 2>&1; then
  [ -f "$PLIST" ] || {
    echo "Loaded sender LaunchAgent has no restorable plist" >&2
    exit 1
  }
  [ "$(stat -f %Su "$PLIST")" = "$ACTUAL_USER" ] || {
    echo "Sender LaunchAgent plist is not owned by the remote user" >&2
    exit 1
  }
  python3 - "$PLIST" "$LABEL" "$TARGET" <<'PY'
import plistlib
import sys

path, expected_label, expected_target = sys.argv[1:]
with open(path, "rb") as stream:
    payload = plistlib.load(stream)
if payload.get("Label") != expected_label:
    raise SystemExit("Sender LaunchAgent label mismatch")
if payload.get("WorkingDirectory") != expected_target:
    raise SystemExit("Sender LaunchAgent working directory mismatch")
if expected_target not in payload.get("ProgramArguments", []):
    raise SystemExit("Sender LaunchAgent repository path mismatch")
PY
  printf 'sender_runtime=loaded\n'
elif pgrep -u "$TARGET_UID" -f 'send-only-mac-messages-remote' >/dev/null 2>&1; then
  echo "Running sender has no matching LaunchAgent and cannot be restored safely" >&2
  exit 1
else
  printf 'sender_runtime=absent\n'
fi
REMOTE
}

remote_prepare_stage_and_uv() {
  ssh_remote bash -s -- "$REMOTE_STAGE_NAME" "$UV_VERSION" <<'REMOTE'
set -euo pipefail
STAGE_NAME=$1
PINNED_UV_VERSION=$2
STAGE="$HOME/dev/$STAGE_NAME"
mkdir -p "$HOME/dev" "$HOME/.local/bin"
[ ! -e "$STAGE" ] || { echo "Remote stage already exists" >&2; exit 1; }
mkdir "$STAGE"

if command -v uv >/dev/null 2>&1; then
  REMOTE_UV=$(command -v uv)
elif [ -x "$HOME/.local/bin/uv" ]; then
  REMOTE_UV="$HOME/.local/bin/uv"
else
  case "$(uname -m)" in
    arm64) UV_ASSET=uv-aarch64-apple-darwin ;;
    x86_64) UV_ASSET=uv-x86_64-apple-darwin ;;
    *) echo "Unsupported hosted Mac architecture" >&2; exit 1 ;;
  esac
  UV_TEMP_DIR=$(mktemp -d /tmp/send-only-uv.XXXXXX)
  trap 'rm -rf "$UV_TEMP_DIR"' EXIT
  UV_URL="https://github.com/astral-sh/uv/releases/download/$PINNED_UV_VERSION/$UV_ASSET.tar.gz"
  curl -fsSL --proto '=https' --tlsv1.2 "$UV_URL" -o "$UV_TEMP_DIR/uv.tar.gz"
  curl -fsSL --proto '=https' --tlsv1.2 "$UV_URL.sha256" -o "$UV_TEMP_DIR/uv.tar.gz.sha256"
  EXPECTED_SHA=$(awk 'NR == 1 {print $1}' "$UV_TEMP_DIR/uv.tar.gz.sha256")
  ACTUAL_SHA=$(shasum -a 256 "$UV_TEMP_DIR/uv.tar.gz" | awk '{print $1}')
  [ "$EXPECTED_SHA" = "$ACTUAL_SHA" ] || { echo "uv archive checksum mismatch" >&2; exit 1; }
  tar -xzf "$UV_TEMP_DIR/uv.tar.gz" -C "$UV_TEMP_DIR"
  install -m 755 "$UV_TEMP_DIR/$UV_ASSET/uv" "$HOME/.local/bin/uv"
  REMOTE_UV="$HOME/.local/bin/uv"
fi
printf 'remote_uv=%s\n' "$REMOTE_UV"
"$REMOTE_UV" --version
REMOTE
}

transfer_tracked_head() {
  git archive --format=tar HEAD | ssh_remote \
    "tar -xf - -C \"\$HOME/dev/$REMOTE_STAGE_NAME\""
  ssh_remote bash -s -- \
    "$REMOTE_STAGE_NAME" \
    "$LOCAL_HEAD" \
    "$LOCAL_TREE" \
    "$LOCAL_BRANCH" \
    "$LOCAL_VERSION" <<'REMOTE'
set -euo pipefail
STAGE="$HOME/dev/$1"
python3 - "$STAGE/.deployed-version.json" "$2" "$3" "$4" "$5" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

path, commit, tree, branch, version = sys.argv[1:]
payload = {
    "schemaVersion": 1,
    "commit": commit,
    "tree": tree,
    "branch": branch,
    "version": version,
    "deployedAt": datetime.now(timezone.utc).isoformat(),
    "source": "git archive HEAD",
}
with open(path, "x", encoding="utf-8") as stream:
    json.dump(payload, stream, indent=2, sort_keys=True)
    stream.write("\n")
os.chmod(path, 0o644)
PY
REMOTE
}

remote_stage_gates() {
  ssh_remote bash -s -- \
    "$REMOTE_STAGE_NAME" \
    "$LOCAL_VERSION" \
    "$REMOTE_PYTHON_VERSION" <<'REMOTE'
set -euo pipefail
STAGE="$HOME/dev/$1"
EXPECTED_VERSION=$2
PYTHON_VERSION=$3
if command -v uv >/dev/null 2>&1; then
  REMOTE_UV=$(command -v uv)
else
  REMOTE_UV="$HOME/.local/bin/uv"
fi
cd "$STAGE"
export UV_NO_PROGRESS=1
export PATH="$(dirname "$REMOTE_UV"):$PATH"
"$REMOTE_UV" sync --python "$PYTHON_VERSION" --extra dev --frozen
"$REMOTE_UV" run --python "$PYTHON_VERSION" --frozen python scripts/bump_version.py --check --expected "$EXPECTED_VERSION"
"$REMOTE_UV" run --python "$PYTHON_VERSION" --frozen pytest -q
"$REMOTE_UV" run --python "$PYTHON_VERSION" --frozen black --check .
"$REMOTE_UV" run --python "$PYTHON_VERSION" --frozen isort --check-only .
"$REMOTE_UV" run --python "$PYTHON_VERSION" --frozen mypy send_only_mac_messages
"$REMOTE_UV" run --python "$PYTHON_VERSION" --frozen python scripts/hosted_canary.py --smoke-only
REMOTE
}

remote_activate_and_restore_runtime() {
  ssh_remote bash -s -- \
    "$REMOTE_STAGE_NAME" \
    "$REMOTE_BACKUP_NAME" \
    "$REMOTE_FAILED_NAME" \
    "$LOCAL_HEAD" \
    "$LOCAL_TREE" \
    "$LOCAL_VERSION" \
    "$REMOTE_PYTHON_VERSION" <<'REMOTE'
set -Eeuo pipefail
STAGE="$HOME/dev/$1"
BACKUP="$HOME/dev/$2"
FAILED="$HOME/dev/$3"
TARGET="$HOME/dev/send-only-mac-messages"
EXPECTED_HEAD=$4
EXPECTED_TREE=$5
EXPECTED_VERSION=$6
PYTHON_VERSION=$7
LABEL=ai.mynimbus.send-only-mac-messages.remote
TARGET_UID=$(id -u)
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SOURCE_SWAP_STARTED=0
RUNTIME_WAS_LOADED=0
ROLLBACK_ACTIVE=0

runtime_loaded() {
  launchctl print "gui/$TARGET_UID/$LABEL" >/dev/null 2>&1
}

runtime_process_running() {
  pgrep -u "$TARGET_UID" -f 'send-only-mac-messages-remote' >/dev/null 2>&1
}

stop_runtime() {
  if runtime_loaded; then
    launchctl bootout "gui/$TARGET_UID/$LABEL"
  fi
  attempt=0
  while runtime_process_running && [ "$attempt" -lt 50 ]; do
    sleep 0.2
    attempt=$((attempt + 1))
  done
  if runtime_process_running; then
    echo "Sender runtime did not stop after LaunchAgent bootout" >&2
    return 1
  fi
}

start_runtime() {
  [ "$RUNTIME_WAS_LOADED" = "1" ] || return 0
  if ! runtime_loaded; then
    launchctl bootstrap "gui/$TARGET_UID" "$PLIST"
  fi
  launchctl kickstart -k "gui/$TARGET_UID/$LABEL"
  attempt=0
  until runtime_loaded && runtime_process_running; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 50 ]; then
      echo "Sender runtime did not start after LaunchAgent bootstrap" >&2
      return 1
    fi
    sleep 0.2
  done
  sleep 1
  runtime_loaded && runtime_process_running
}

rollback() {
  original_rc=$1
  trap - ERR HUP INT TERM
  if [ "$ROLLBACK_ACTIVE" = "1" ]; then
    exit "$original_rc"
  fi
  ROLLBACK_ACTIVE=1
  set +e
  if [ "$SOURCE_SWAP_STARTED" = "1" ]; then
    stop_runtime >/dev/null 2>&1 || true
    if [ -e "$TARGET" ]; then
      mv "$TARGET" "$FAILED"
      printf 'failed_checkout=%s\n' "$FAILED"
    fi
    if [ -e "$BACKUP" ]; then
      mv "$BACKUP" "$TARGET"
      printf 'restored_backup=%s\n' "$TARGET"
    fi
  fi
  if [ "$RUNTIME_WAS_LOADED" = "1" ]; then
    if start_runtime; then
      printf 'rollback_runtime=restored\n'
    else
      printf 'rollback_runtime=restore_failed\n' >&2
    fi
  fi
  exit "$original_rc"
}

trap 'rollback "$?"' ERR
trap 'rollback 1' HUP INT TERM

[ -d "$STAGE" ] || { echo "Verified stage is missing" >&2; exit 1; }
[ ! -e "$BACKUP" ] || { echo "Backup path already exists" >&2; exit 1; }
[ ! -e "$FAILED" ] || { echo "Failed-checkout path already exists" >&2; exit 1; }

if runtime_loaded; then
  RUNTIME_WAS_LOADED=1
  [ -f "$PLIST" ] || { echo "Restorable LaunchAgent plist is missing" >&2; exit 1; }
elif runtime_process_running; then
  echo "Running sender has no matching LaunchAgent and cannot be restored safely" >&2
  exit 1
fi

if [ "$RUNTIME_WAS_LOADED" = "1" ]; then
  stop_runtime
  printf 'runtime_quiesced=true\n'
else
  printf 'runtime_quiesced=not_applicable\n'
fi

SOURCE_SWAP_STARTED=1
if [ -e "$TARGET" ]; then
  mv "$TARGET" "$BACKUP"
  printf 'backup=%s\n' "$BACKUP"
else
  printf 'backup=none_initial_install\n'
fi
mv "$STAGE" "$TARGET"
printf 'activated=%s\n' "$TARGET"

if command -v uv >/dev/null 2>&1; then
  REMOTE_UV=$(command -v uv)
else
  REMOTE_UV="$HOME/.local/bin/uv"
fi
export PATH="$(dirname "$REMOTE_UV"):$PATH"
python3 - "$TARGET/.deployed-version.json" "$EXPECTED_HEAD" "$EXPECTED_TREE" "$EXPECTED_VERSION" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    payload = json.load(stream)
expected = {"commit": sys.argv[2], "tree": sys.argv[3], "version": sys.argv[4]}
actual = {key: payload.get(key) for key in expected}
if actual != expected:
    raise SystemExit(f"deployment metadata mismatch: {actual!r}")
print("deployed_commit=" + actual["commit"])
print("deployed_tree=" + actual["tree"])
print("deployed_version=" + actual["version"])
PY
cd "$TARGET"
"$REMOTE_UV" run --python "$PYTHON_VERSION" --frozen python scripts/bump_version.py --check --expected "$EXPECTED_VERSION"
"$REMOTE_UV" run --python "$PYTHON_VERSION" --frozen python scripts/hosted_canary.py --smoke-only
printf 'console_user=%s\n' "$(stat -f %Su /dev/console)"
start_runtime
if [ "$RUNTIME_WAS_LOADED" = "1" ]; then
  printf 'runtime_activation=performed\n'
  printf 'sender_runtime=running\n'
else
  printf 'runtime_activation=not_applicable\n'
  printf 'sender_runtime=absent\n'
fi

trap - ERR HUP INT TERM
printf 'transaction=complete\n'
REMOTE
}

remote_preserve_failed_stage() {
  ssh_remote bash -s -- "$REMOTE_STAGE_NAME" "$REMOTE_FAILED_NAME" <<'REMOTE'
set -euo pipefail
STAGE="$HOME/dev/$1"
FAILED="$HOME/dev/$2"
if [ -e "$STAGE" ]; then
  [ ! -e "$FAILED" ] || { echo "Failed-stage evidence path already exists" >&2; exit 1; }
  mv "$STAGE" "$FAILED"
  printf 'failed_stage=%s\n' "$FAILED"
else
  printf 'failed_stage=not_present\n'
fi
REMOTE
}

log "Send-only Mac Messages hosted source update"
run_logged "Local identity" local_identity
if [ "$RUN_LOCAL_GATES" = "1" ]; then
  run_logged "Local gates" local_gates
else
  log "Local gates skipped by explicit option."
fi
run_logged "Remote account and runtime preflight" remote_preflight

if [ "$DRY_RUN" = "1" ]; then
  log "Dry run complete; no remote files changed."
  log "Evidence log: $EVIDENCE_LOG"
  exit 0
fi

if ! run_logged "Prepare remote stage and uv" remote_prepare_stage_and_uv; then
  run_logged "Preserve failed stage" remote_preserve_failed_stage || true
  exit 1
fi
if ! run_logged "Transfer tracked HEAD" transfer_tracked_head; then
  run_logged "Preserve failed stage" remote_preserve_failed_stage || true
  exit 1
fi
if ! run_logged "Remote staged gates" remote_stage_gates; then
  run_logged "Preserve failed stage" remote_preserve_failed_stage || true
  exit 1
fi
if ! run_logged "Activate source and restore runtime" remote_activate_and_restore_runtime; then
  log "Deployment failed; the remote transaction attempted source and runtime rollback."
  log "Evidence log: $EVIDENCE_LOG"
  exit 1
fi

log ""
log "Deployment result: passed"
log "Remote source: /Users/$TARGET_USER/dev/send-only-mac-messages"
log "Commit: $LOCAL_HEAD"
log "Tree: $LOCAL_TREE"
log "Version: $LOCAL_VERSION"
log "Runtime activation: restored when previously loaded"
log "Evidence log: $EVIDENCE_LOG"
