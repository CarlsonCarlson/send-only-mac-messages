"""Regression tests for the Heimdall-compatible bearer verifier."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from send_only_mac_messages.auth import (
    BearerVerifierLoadError,
    load_bearer_verifier,
    parse_authorization_header,
)


def test_authorization_header_uses_exact_heimdall_grammar() -> None:
    bearer = "A" * 43

    assert parse_authorization_header([f"Bearer {bearer}"]) == bearer
    assert parse_authorization_header([f"bearer {bearer}"]) == bearer

    for values in (
        [],
        [f"Bearer {bearer}", f"Bearer {bearer}"],
        [f"Bearer {bearer},Bearer {bearer}"],
        [f" Bearer {bearer}"],
        [f"Bearer  {bearer}"],
        [f"Bearer {bearer} "],
        [f"Basic {bearer}"],
        [f"Bearer {'A' * 42}="],
        [f"Bearer {'A' * 42}+"],
        [f"Bearer {'A' * 42}/"],
        [f"Bearer {'A' * 42}"],
        [f"Bearer {'A' * 44}"],
    ):
        assert parse_authorization_header(values) is None


def test_verifier_loads_owner_only_digest_and_matches_exact_token(
    tmp_path: Path,
) -> None:
    bearer = "B" * 43
    path = _write_verifier(tmp_path, bearer)

    verifier = load_bearer_verifier(path)

    assert verifier.enabled
    assert verifier.validate(bearer)
    assert not verifier.validate("C" * 43)
    assert not verifier.validate(f" {bearer}")


def test_disabled_verifier_rejects_the_matching_token(tmp_path: Path) -> None:
    bearer = "D" * 43
    path = _write_verifier(tmp_path, bearer, enabled=False)

    verifier = load_bearer_verifier(path)

    assert not verifier.enabled
    assert not verifier.validate(bearer)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"version": 1, "sha256": "0" * 64},
        {"version": 2, "sha256": "0" * 64, "enabled": True},
        {"version": True, "sha256": "0" * 64, "enabled": True},
        {"version": 1, "sha256": "A" * 64, "enabled": True},
        {"version": 1, "sha256": "0" * 63, "enabled": True},
        {"version": 1, "sha256": "0" * 64, "enabled": "true"},
        {"version": 1, "sha256": "0" * 64, "enabled": True, "extra": 1},
    ],
)
def test_verifier_rejects_malformed_payloads(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "verifier.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(BearerVerifierLoadError):
        load_bearer_verifier(path)


def test_verifier_rejects_wrong_mode_and_symlink(tmp_path: Path) -> None:
    bearer = "E" * 43
    path = _write_verifier(tmp_path, bearer)
    path.chmod(0o644)

    with pytest.raises(BearerVerifierLoadError):
        load_bearer_verifier(path)

    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(BearerVerifierLoadError):
        load_bearer_verifier(link)


def test_verifier_rejects_owner_mismatch(tmp_path: Path) -> None:
    path = _write_verifier(tmp_path, "F" * 43)

    with pytest.raises(BearerVerifierLoadError):
        load_bearer_verifier(path, effective_uid=os.geteuid() + 1)


def _write_verifier(
    directory: Path,
    bearer: str,
    *,
    enabled: bool = True,
) -> Path:
    path = directory / "verifier.json"
    payload = {
        "version": 1,
        "sha256": hashlib.sha256(bearer.encode("ascii")).hexdigest(),
        "enabled": enabled,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    return path
