"""Fail-closed bearer verification for the remote MCP transport."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

BEARER_BYTES = 32
BEARER_TEXT_LENGTH = 43
BEARER_DIGEST_SCHEMA_VERSION = 1
BEARER_DIGEST_FILE_MODE = 0o600

_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BASE64URL = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class BearerVerifierLoadError(RuntimeError):
    """The bearer verifier file could not be admitted safely."""


@dataclass(frozen=True)
class BearerVerifier:
    """An enabled flag and SHA-256 digest loaded from an owner-only file."""

    enabled: bool
    digest: bytes

    def validate(self, presented_bearer: str) -> bool:
        """Validate exact bearer bytes using a constant-time digest comparison."""
        if not self.enabled:
            return False
        candidate = hashlib.sha256(presented_bearer.encode("utf-8")).digest()
        return hmac.compare_digest(candidate, self.digest)


def parse_authorization_header(values: list[str]) -> str | None:
    """Return one canonical 32-byte base64url bearer or reject the header."""
    if len(values) != 1:
        return None
    value = values[0]
    prefix_length = len("Bearer")
    if (
        len(value) != len("Bearer ") + BEARER_TEXT_LENGTH
        or value[:prefix_length].lower() != "bearer"
        or value[prefix_length] != " "
    ):
        return None
    bearer = value[len("Bearer ") :]
    if not _BASE64URL.fullmatch(bearer):
        return None
    return bearer


def load_bearer_verifier(
    path: str | os.PathLike[str],
    *,
    effective_uid: int | None = None,
    opener: Callable[[str], TextIO] | None = None,
) -> BearerVerifier:
    """Load one Heimdall-compatible bearer digest file, failing closed."""
    verifier_path = os.fspath(path)
    expected_uid = os.geteuid() if effective_uid is None else effective_uid
    open_verifier = opener or _open_verifier_file

    try:
        stream = open_verifier(verifier_path)
    except OSError as exc:
        raise BearerVerifierLoadError("bearer verifier is unavailable") from exc

    with stream:
        try:
            file_stat = os.fstat(stream.fileno())
        except OSError as exc:
            raise BearerVerifierLoadError(
                "bearer verifier metadata is unavailable"
            ) from exc

        if not stat.S_ISREG(file_stat.st_mode):
            raise BearerVerifierLoadError("bearer verifier is not a regular file")
        if file_stat.st_uid != expected_uid:
            raise BearerVerifierLoadError("bearer verifier owner mismatch")
        if stat.S_IMODE(file_stat.st_mode) != BEARER_DIGEST_FILE_MODE:
            raise BearerVerifierLoadError("bearer verifier mode must be 0600")

        try:
            raw = stream.read()
            payload = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BearerVerifierLoadError("bearer verifier JSON is invalid") from exc

    return _decode_verifier_payload(payload)


def default_bearer_digest_path() -> Path:
    """Return the per-user default used by the lifecycle script and server."""
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Send-only Mac Messages"
        / "mcp-bearer-digest.v1.json"
    )


def _open_verifier_file(path: str) -> TextIO:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    return os.fdopen(descriptor, "r", encoding="utf-8")


def _decode_verifier_payload(payload: Any) -> BearerVerifier:
    if not isinstance(payload, dict):
        raise BearerVerifierLoadError("bearer verifier must be a JSON object")
    if set(payload) != {"version", "sha256", "enabled"}:
        raise BearerVerifierLoadError("bearer verifier fields are invalid")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise BearerVerifierLoadError("bearer verifier version is invalid")
    digest_text = payload["sha256"]
    if not isinstance(digest_text, str) or not _LOWER_SHA256.fullmatch(digest_text):
        raise BearerVerifierLoadError("bearer verifier digest is invalid")
    if type(payload["enabled"]) is not bool:
        raise BearerVerifierLoadError("bearer verifier enabled flag is invalid")
    return BearerVerifier(
        enabled=payload["enabled"],
        digest=bytes.fromhex(digest_text),
    )
