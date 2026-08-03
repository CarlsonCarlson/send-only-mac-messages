"""Forward tests for create, replace, and revoke bearer lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from send_only_mac_messages.auth import load_bearer_verifier

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "manage-mcp-bearer.sh"


def test_bearer_lifecycle_create_replace_and_revoke(tmp_path: Path) -> None:
    digest_path = tmp_path / "state" / "mcp-bearer-digest.v1.json"
    environment = {
        **os.environ,
        "SEND_ONLY_MCP_BEARER_DIGEST_PATH": os.fspath(digest_path),
    }

    created = _run("create", environment)
    first_bearer = created.stdout.strip()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first_bearer)
    assert created.stderr == ""
    assert digest_path.stat().st_mode & 0o777 == 0o600
    assert digest_path.parent.stat().st_mode & 0o777 == 0o700
    assert load_bearer_verifier(digest_path).validate(first_bearer)

    duplicate = _run("create", environment, check=False)
    assert duplicate.returncode == 1
    assert duplicate.stdout == ""
    assert "enabled verifier already exists" in duplicate.stderr

    replaced = _run("replace", environment)
    second_bearer = replaced.stdout.strip()
    assert second_bearer != first_bearer
    replacement_payload = json.loads(digest_path.read_text(encoding="utf-8"))
    assert replacement_payload == {
        "version": 1,
        "sha256": hashlib.sha256(second_bearer.encode("ascii")).hexdigest(),
        "enabled": True,
    }
    verifier = load_bearer_verifier(digest_path)
    assert verifier.validate(second_bearer)
    assert not verifier.validate(first_bearer)

    revoked = _run("revoke", environment)
    assert revoked.stdout == ""
    assert not load_bearer_verifier(digest_path).enabled
    assert not load_bearer_verifier(digest_path).validate(second_bearer)


def test_replace_and_revoke_require_existing_verifier(tmp_path: Path) -> None:
    environment = {
        **os.environ,
        "SEND_ONLY_MCP_BEARER_DIGEST_PATH": os.fspath(
            tmp_path / "missing" / "mcp-bearer-digest.v1.json"
        ),
    }

    for action in ("replace", "revoke"):
        result = _run(action, environment, check=False)
        assert result.returncode == 1
        assert result.stdout == ""
        assert "verifier file is required" in result.stderr


def _run(
    action: str,
    environment: dict[str, str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [os.fspath(SCRIPT), action],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=check,
    )
