#!/usr/bin/env bash

# Secrets never enter shell variables, including when the caller enables xtrace.
set +x
set -euo pipefail

readonly DEFAULT_DIGEST_FILE_PATH="$HOME/Library/Application Support/Send-only Mac Messages/mcp-bearer-digest.v1.json"
readonly DIGEST_FILE_PATH="${SEND_ONLY_MCP_BEARER_DIGEST_PATH:-$DEFAULT_DIGEST_FILE_PATH}"

umask 077

usage() {
  printf 'Usage: %s create|replace|revoke\n' "$(basename "$0")" >&2
  exit 2
}

case "${1-}" in
  create|replace|revoke)
    ACTION=$1
    ;;
  *)
    usage
    ;;
esac

set +e
python3 - "$ACTION" "$DIGEST_FILE_PATH" 2>/dev/null <<'PY'
import base64
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile

EXIT_ENABLED_EXISTS = 10
EXIT_REQUIRED = 11
EXIT_ADMISSION = 12
EXIT_LIFECYCLE = 13


class AdmissionError(Exception):
    pass


def open_flags(base):
    return base | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def load_digest(path):
    try:
        fd = os.open(path, open_flags(os.O_RDONLY | os.O_NONBLOCK))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AdmissionError() from exc

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise AdmissionError()
        if file_stat.st_uid != os.geteuid():
            raise AdmissionError()
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            raise AdmissionError()
        with os.fdopen(fd, "r", encoding="utf-8", closefd=True) as stream:
            fd = -1
            payload = json.load(stream)
    except AdmissionError:
        raise
    except Exception as exc:
        raise AdmissionError() from exc
    finally:
        if fd >= 0:
            os.close(fd)

    if not isinstance(payload, dict):
        raise AdmissionError()
    if set(payload) != {"version", "sha256", "enabled"}:
        raise AdmissionError()
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise AdmissionError()
    digest = payload["sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise AdmissionError()
    if not isinstance(payload["enabled"], bool):
        raise AdmissionError()
    return payload


def write_digest(path, digest, enabled):
    directory = os.path.dirname(path)
    temp_path = None
    temp_fd = -1
    try:
        temp_fd, temp_path = tempfile.mkstemp(
            prefix=".mcp-bearer-digest.v1.json.tmp.",
            dir=directory,
        )
        os.fchmod(temp_fd, 0o600)
        payload = json.dumps(
            {"version": 1, "sha256": digest, "enabled": enabled},
            indent=2,
        ).encode("utf-8") + b"\n"
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError(errno.EIO, "short verifier write")
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = -1
        os.replace(temp_path, path)
        temp_path = None

        directory_fd = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


def run(action, path):
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    lock_path = os.path.join(directory, ".mcp-bearer-digest.v1.lock")
    lock_fd = os.open(lock_path, open_flags(os.O_RDWR | os.O_CREAT), 0o600)
    try:
        lock_stat = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != os.geteuid():
            raise OSError(errno.EPERM, "invalid lifecycle lock")
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        existing = load_digest(path)
        if action == "create":
            if existing is not None and existing["enabled"]:
                return EXIT_ENABLED_EXISTS, None
        elif existing is None:
            return EXIT_REQUIRED, None

        if action == "revoke":
            write_digest(path, existing["sha256"], False)
            return 0, None

        bearer = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
        digest = hashlib.sha256(bearer.encode("ascii")).hexdigest()
        write_digest(path, digest, True)
        return 0, bearer
    finally:
        os.close(lock_fd)


try:
    status, bearer = run(sys.argv[1], sys.argv[2])
except AdmissionError:
    status, bearer = EXIT_ADMISSION, None
except Exception:
    status, bearer = EXIT_LIFECYCLE, None

if status == 0 and bearer is not None:
    print(bearer)
raise SystemExit(status)
PY
SCRIPT_STATUS=$?
set -e

case "$SCRIPT_STATUS" in
  0)
    exit 0
    ;;
  10)
    printf '%s\n' "enabled verifier already exists" >&2
    ;;
  11)
    printf '%s\n' "verifier file is required" >&2
    ;;
  12)
    printf '%s\n' "existing verifier file failed admission" >&2
    ;;
  *)
    printf '%s\n' "mcp bearer lifecycle failed" >&2
    ;;
esac
exit 1
