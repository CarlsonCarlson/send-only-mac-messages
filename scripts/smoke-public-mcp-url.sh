#!/usr/bin/env bash

# Content-free public smoke for the Carlson send-only MCP. This script never
# invokes tool_send_message and never prints the bearer.
set +x
set -euo pipefail

readonly DEFAULT_URL="https://carlson-send-message-mcp.mynimbus.ai/mcp"
readonly DEFAULT_ENV_FILE="$HOME/.codex/.env"
readonly BEARER_ENV_NAME="CARLSON_SEND_MESSAGE_MCP_BEARER"

mode="all"
public_url="$DEFAULT_URL"
env_file="$DEFAULT_ENV_FILE"

usage() {
  cat >&2 <<'USAGE'
Usage: scripts/smoke-public-mcp-url.sh [--negative-only|--positive-only]
       [--url https://host/mcp] [--env-file PATH]

Runs content-free HTTP/MCP checks. Positive mode reads exactly one
CARLSON_SEND_MESSAGE_MCP_BEARER assignment from an owner-only mode-0600 file.
No mode invokes tool_send_message.
USAGE
  exit 2
}

while (($#)); do
  case "$1" in
    --negative-only)
      mode="negative"
      shift
      ;;
    --positive-only)
      mode="positive"
      shift
      ;;
    --url)
      (($# >= 2)) || usage
      public_url=$2
      shift 2
      ;;
    --env-file)
      (($# >= 2)) || usage
      env_file=$2
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      usage
      ;;
  esac
done

for required_command in curl python3; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf 'missing required command: %s\n' "$required_command" >&2
    exit 1
  }
done

read -r public_scheme public_host public_path < <(
  python3 - "$public_url" <<'PY'
import sys
from urllib.parse import urlsplit

value = urlsplit(sys.argv[1])
if value.scheme != "https" or not value.hostname or value.port is not None:
    raise SystemExit("URL must be an HTTPS hostname without an explicit port")
if value.path != "/mcp" or value.query or value.fragment or value.username:
    raise SystemExit("URL must contain exact /mcp with no query, fragment, or user info")
print(value.scheme, value.hostname, value.path)
PY
)

smoke_dir=$(mktemp -d /tmp/carlson-send-message-public-smoke.XXXXXX)
cleanup_smoke() {
  find "$smoke_dir" -maxdepth 1 -type f -exec unlink {} \;
  rmdir "$smoke_dir"
}
trap cleanup_smoke EXIT

initialize_payload='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"public-smoke","version":"1"}}}'

request_status() {
  local output_path=$1
  shift
  curl --silent --show-error \
    --connect-timeout 5 \
    --max-time 15 \
    --output "$output_path" \
    --write-out '%{http_code}' \
    "$@"
}

common_headers() {
  printf '%s\n' \
    'X-Expected-Sender: carlson' \
    'Content-Type: application/json' \
    'Accept: application/json, text/event-stream'
}

authenticated_headers() {
  awk -F= -v wanted="$BEARER_ENV_NAME" '
    $1 == wanted { print "Authorization: Bearer " $2 }
  ' "$env_file"
  common_headers
}

validate_env_file() {
  python3 - "$env_file" "$BEARER_ENV_NAME" <<'PY'
import os
import pathlib
import re
import stat
import sys

path = pathlib.Path(sys.argv[1])
name = sys.argv[2]
info = path.lstat()
if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
    raise SystemExit("bearer environment file owner/type invalid")
if stat.S_IMODE(info.st_mode) != 0o600:
    raise SystemExit("bearer environment file mode must be 0600")
matches = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(name + "=")]
if len(matches) != 1 or not re.fullmatch(re.escape(name) + r"=[A-Za-z0-9_-]{43}", matches[0]):
    raise SystemExit("bearer environment assignment invalid")
print("bearer_file_valid=true")
PY
}

if [[ "$mode" == "all" || "$mode" == "negative" ]]; then
  root_status=$(request_status "$smoke_dir/root.body" "https://$public_host/")
  slash_status=$(request_status "$smoke_dir/slash.body" "https://$public_host/mcp/")
  get_status=$(request_status "$smoke_dir/get.body" "$public_url")
  no_bearer_status=$(request_status "$smoke_dir/no-bearer.body" \
    --request POST "$public_url" \
    --header 'X-Expected-Sender: carlson' \
    --header 'Content-Type: application/json' \
    --header 'Accept: application/json, text/event-stream' \
    --data-binary "$initialize_payload")
  wrong_bearer_status=$(request_status "$smoke_dir/wrong-bearer.body" \
    --request POST "$public_url" \
    --header 'Authorization: Bearer AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' \
    --header 'X-Expected-Sender: carlson' \
    --header 'Content-Type: application/json' \
    --header 'Accept: application/json, text/event-stream' \
    --data-binary "$initialize_payload")

  [[ "$root_status" == "403" ]] || {
    printf 'negative_smoke=failed case=root_path expected=403 observed=%s\n' "$root_status" >&2
    exit 1
  }
  [[ "$slash_status" == "403" ]] || {
    printf 'negative_smoke=failed case=slash_path expected=403 observed=%s\n' "$slash_status" >&2
    exit 1
  }
  [[ "$get_status" == "405" ]] || {
    printf 'negative_smoke=failed case=get_mcp expected=405 observed=%s\n' "$get_status" >&2
    exit 1
  }
  [[ "$no_bearer_status" == "401" ]] || {
    printf 'negative_smoke=failed case=no_bearer expected=401 observed=%s\n' "$no_bearer_status" >&2
    exit 1
  }
  [[ "$wrong_bearer_status" == "401" ]] || {
    printf 'negative_smoke=failed case=wrong_bearer expected=401 observed=%s\n' "$wrong_bearer_status" >&2
    exit 1
  }
  printf 'negative_smoke=passed\n'
fi

if [[ "$mode" == "all" || "$mode" == "positive" ]]; then
  validate_env_file
  wrong_sender_status=$(request_status "$smoke_dir/wrong-sender.body" \
    --request POST "$public_url" \
    --header @<(authenticated_headers | sed 's/X-Expected-Sender: carlson/X-Expected-Sender: kevin/') \
    --data-binary "$initialize_payload")
  initialize_status=$(curl --silent --show-error \
    --connect-timeout 5 \
    --max-time 15 \
    --dump-header "$smoke_dir/initialize.headers" \
    --output "$smoke_dir/initialize.body" \
    --write-out '%{http_code}' \
    --request POST "$public_url" \
    --header @<(authenticated_headers) \
    --data-binary "$initialize_payload")
  tools_status=$(request_status "$smoke_dir/tools.body" \
    --request POST "$public_url" \
    --header @<(authenticated_headers) \
    --data-binary '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')
  resources_status=$(request_status "$smoke_dir/resources.body" \
    --request POST "$public_url" \
    --header @<(authenticated_headers) \
    --data-binary '{"jsonrpc":"2.0","id":3,"method":"resources/list","params":{}}')
  prompts_status=$(request_status "$smoke_dir/prompts.body" \
    --request POST "$public_url" \
    --header @<(authenticated_headers) \
    --data-binary '{"jsonrpc":"2.0","id":4,"method":"prompts/list","params":{}}')

  [[ "$wrong_sender_status" == "403" ]] || {
    printf 'positive_smoke=failed case=wrong_sender expected=403 observed=%s\n' "$wrong_sender_status" >&2
    exit 1
  }
  [[ "$initialize_status" == "200" && "$tools_status" == "200" && "$resources_status" == "200" && "$prompts_status" == "200" ]] || {
    printf 'positive_smoke=failed case=mcp_status\n' >&2
    exit 1
  }

  python3 - "$smoke_dir" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])

def parse(name):
    raw = (root / name).read_text(encoding="utf-8").strip()
    if raw.startswith("event:"):
        rows = [line.removeprefix("data: ") for line in raw.splitlines() if line.startswith("data: ")]
        if len(rows) != 1:
            raise SystemExit("unexpected SSE response")
        raw = rows[0]
    return json.loads(raw)

initialize = parse("initialize.body")
tools = parse("tools.body")
resources = parse("resources.body")
prompts = parse("prompts.body")
headers = (root / "initialize.headers").read_text(encoding="latin-1").lower()
if initialize.get("id") != 1 or "result" not in initialize:
    raise SystemExit("initialize response invalid")
if [tool.get("name") for tool in tools.get("result", {}).get("tools", [])] != ["tool_send_message"]:
    raise SystemExit("tool inventory invalid")
if resources.get("result", {}).get("resources") != []:
    raise SystemExit("resources inventory invalid")
if prompts.get("result", {}).get("prompts") != []:
    raise SystemExit("prompts inventory invalid")
if "cache-control: no-store" not in headers or "x-content-type-options: nosniff" not in headers:
    raise SystemExit("security headers invalid")
print("initialize_valid=true")
print("tool_inventory=tool_send_message")
print("resources_count=0")
print("prompts_count=0")
print("security_headers_valid=true")
PY
  printf 'positive_smoke=passed\n'
  printf 'tool_invoked=false\n'
fi
