---
name: update-hosted-mac
description: Update or verify the tracked send-only-mac-messages version on the hosted Mac. Use for an explicit hosted-Mac deployment or a read-only version check.
---

# Update Hosted Mac

Run from the `send-only-mac-messages` repository root. The deployment source is the
exact tracked `HEAD`; dirty and untracked worktree content stays local.

## Branches

- **Update**: An explicit request to deploy, install, update, refresh, or replace the
  hosted Mac authorizes a recoverable handoff of the matching sender LaunchAgent.
  Proceed without another permission request. The script stages and verifies `HEAD`,
  unloads the existing LaunchAgent only for activation, replaces the source, reloads
  it, and proves the runtime is running on the deployed checkout.
- **Verify**: A request to check the installed version is read-only. Run the script
  with `--dry-run`; the LaunchAgent remains loaded.

## Steps

1. Inspect `git status`, `HEAD`, its tree hash, and the synchronized package version.
   Completion: the exact tracked deployment identity is known.
2. Confirm the requested SSH user is the intended Messages principal. The default is
   Kevin's configured target; use a different principal only when the user names it.
   Completion: remote and console users match the intended principal.
3. Run the bundled script for the selected branch:

   ```sh
   .agents/skills/update-hosted-mac/scripts/update-hosted-mac.sh
   ```

4. Report the commit, tree, package version, console user, recoverable backup, runtime
   activation result, and evidence-log path. Completion for an update requires the
   deployed metadata to match `HEAD` and any previously loaded sender to be loaded and
   running again. Completion for verification requires zero remote mutations.

## Required setup

- Put the hosted SSH password in `secrets/hosted-mac-ssh-password` with mode `600`,
  or set `HOSTED_MAC_PASSWORD_FILE` to an existing owner-only password file.
- The default target is `kevinhom@192.30.129.13`. Override it only when the user
  explicitly identifies a different principal and host.
- Evidence stays content-free: omit passwords, bearer values, message content, phone
  numbers, and verifier files from logs and reports.

## Script contract

- Capture a content-free evidence log under `/tmp/send-only-mac-messages/`.
- Run local version, test, formatting, and type gates.
- Verify the remote SSH user exactly matches the target username.
- Validate the existing LaunchAgent definition before unloading it. A process without
  a matching LaunchAgent remains a hard stop because it cannot be restored safely.
- Bootstrap the repository-pinned `uv` version when the target account has no usable
  `uv` binary.
- Transfer `git archive HEAD` to a fresh remote staging directory, so unrelated
  worktree content cannot leak into the hosted checkout.
- Run remote dependency sync, version validation, tests, formatting, type checks, and
  the smoke-only MCP surface check. The smoke must not call `tool_send_message`.
- Keep the active runtime up while staging. Then unload the matching LaunchAgent,
  atomically activate the verified stage, and reload it in the same GUI domain.
- Roll back to the timestamped backup and restore the prior runtime after any
  activation, post-activation, or reload failure.

Useful overrides:

```sh
HOSTED_MAC_SSH_TARGET='kevinhom@192.30.129.13'
HOSTED_MAC_PASSWORD_FILE='/absolute/owner-only/password-file'
UV_VERSION='0.11.19'
REMOTE_PYTHON_VERSION='3.13'
```

Use `--skip-local-gates` only when equivalent gates already passed for the exact
commit and the user accepts that evidence. Use `--dry-run` for an inspection-only
preflight.

## Boundaries

This workflow may unload and reload an existing matching LaunchAgent during an
explicit update. It does not create a sender service, create or rotate a bearer,
modify Cloudflare, change the GUI user, invoke Messages.app, or perform a send.
Runtime activation proves the process is running, not TCC authorization or delivery.
