"""The hosted-Mac update script refuses a checkout with no branch before it does anything.

On 2026-10-27 a deploy from a detached HEAD sent an empty branch argument over SSH, which
dropped it, so the remote metadata step failed with "$5: unbound variable" after staging
had begun.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".agents/skills/update-hosted-mac/scripts/update-hosted-mac.sh"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _run_in_repo(
    tmp_path: Path, *, detach: bool
) -> tuple[subprocess.CompletedProcess[str], Path]:
    repo = tmp_path / "repo"
    script = repo / ".agents/skills/update-hosted-mac/scripts/update-hosted-mac.sh"
    script.parent.mkdir(parents=True)
    shutil.copy(SCRIPT, script)
    (repo / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.0.1"\n')
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "add", ".")
    _git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "-qm",
        "x",
    )
    if detach:
        _git(repo, "checkout", "-q", "--detach")
    called = tmp_path / "remote-called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("sshpass", "ssh"):
        fake = fake_bin / name
        fake.write_text(f"#!/bin/sh\ntouch {called}\nexit 1\n")
        fake.chmod(0o755)
    password = tmp_path / "password"
    password.write_text("x")
    password.chmod(0o600)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HOSTED_MAC_PASSWORD_FILE": str(password),
    }
    result = subprocess.run(
        ["bash", str(script), "--skip-local-gates", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result, called


def test_refuses_a_detached_head_before_any_remote_call(tmp_path: Path) -> None:
    result, called = _run_in_repo(tmp_path, detach=True)

    assert result.returncode == 2
    assert "HEAD is detached" in result.stderr
    assert not called.exists()


def test_a_checked_out_branch_gets_past_the_branch_check(tmp_path: Path) -> None:
    result, called = _run_in_repo(tmp_path, detach=False)

    assert "HEAD is detached" not in result.stderr
    assert called.exists()
