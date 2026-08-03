# Principal-bound remote MCP setup

This deployment mirrors Heimdall's private remote-MCP authentication: one fixed
bearer, only its SHA-256 digest on the hosted Mac, and stateless Streamable HTTP
behind a dedicated Cloudflare hostname. It does not authorize a particular send or
prove delivery.

No command in this guide invokes Messages.app. A live canary remains a separate,
explicitly approved action.

## 1. Freeze one principal deployment

Choose non-PII values for these placeholders:

| Placeholder | Meaning |
| --- | --- |
| `__PUBLIC_HOST__` | Dedicated Cloudflare hostname for this sender |
| `__LOGICAL_SENDER__` | Stable label such as `principal_a` |
| `__MACOS_SHORT_USER__` | Exact hosted-Mac GUI short username |
| `__LOOPBACK_PORT__` | Principal-unique loopback port, such as `49160` |
| `__REPOSITORY_PATH__` | Absolute checkout path under that GUI user |
| `__UV_PATH__` | Absolute `uv` executable path for that user |
| `__BEARER_DIGEST_PATH__` | Absolute path to `mcp-bearer-digest.v1.json` |
| `__LOG_DIRECTORY__` | Owner-only directory for content-free process logs |

The process, hostname, port, bearer, LaunchAgent, and logical label must not be
shared with a second Messages principal.

## 2. Install and verify without sending

Run under the intended graphical user:

```bash
uv sync --extra dev
uv run pytest -q
uv run black --check .
uv run isort --check-only .
uv run mypy send_only_mac_messages
uv build
```

The remote entry point refuses to start unless its configured macOS user is the
effective user. It binds only to `127.0.0.1`.

## 3. Create the bearer

From the intended GUI user's terminal, optionally set the absolute verifier path and
run:

```bash
export SEND_ONLY_MCP_BEARER_DIGEST_PATH="__BEARER_DIGEST_PATH__"
./scripts/manage-mcp-bearer.sh create
```

The command prints the raw 43-character bearer exactly once. Copy it directly into
the client secret store. Do not put it in shell history, command arguments,
`config.toml`, launchd configuration, repository files, tickets, logs, or handoffs.
The hosted file contains only this schema and is atomically written with mode `0600`:

```json
{
  "version": 1,
  "sha256": "lowercase SHA-256 digest",
  "enabled": true
}
```

Lifecycle operations are:

```bash
./scripts/manage-mcp-bearer.sh replace
./scripts/manage-mcp-bearer.sh revoke
```

Restart the remote process after replace or revoke so it reloads the verifier.

## 4. Install the GUI LaunchAgent

Copy
`config/launchd/ai.mynimbus.send-only-mac-messages.remote.plist.example` to an
owner-only working file, replace every placeholder, validate it with `plutil -lint`,
then install it as a LaunchAgent for the intended graphical user. Never install it as
a root or system LaunchDaemon.

The template is restricted to the Aqua session. Before publishing the endpoint,
verify content-free evidence:

- effective UID equals `__MACOS_SHORT_USER__`
- `/dev/console` is owned by that same UID
- the configured logical sender is `__LOGICAL_SENDER__`
- the listener is only `127.0.0.1:__LOOPBACK_PORT__`
- authenticated `initialize` succeeds
- discovery returns exactly `tool_send_message`
- resources and prompts remain empty

A LaunchAgent has not yet been proven to retain the existing Terminal Automation
grant. If macOS presents a new Automation prompt, stop for the user. Do not work
around TCC with SSH, root, or a system daemon.

## 5. Publish the exact Cloudflare origin

Use `config/cloudflare/send-only-mcp-ingress.example.json` as the deployment
contract. The Cloudflare Tunnel must:

- preserve `__PUBLIC_HOST__`
- route only exact `/mcp` to `http://127.0.0.1:__LOOPBACK_PORT__`
- reject all other paths for that hostname
- apply coarse rate limiting

Origin bearer verification remains mandatory. Cloudflare is not the authentication
authority. No Cloudflare cache rule is required: MCP requests use `POST`, and the
origin returns `Cache-Control: no-store`. Do not enable Cache Reserve or create a
rule that makes this hostname cache-eligible.

Cloudflare Free permits one zone rate-limiting rule. If the zone already uses that
rule for another MCP hostname, add this hostname and exact `/mcp` path as another
`or` branch. Free-plan counters are shared by source IP and Cloudflare data center
across every hostname matched by that rule.

After publication, run the content-free public smoke. It never invokes the send
tool:

```bash
./scripts/smoke-public-mcp-url.sh --negative-only
./scripts/smoke-public-mcp-url.sh --positive-only
```

The negative smoke requires Cloudflare to block every non-`/mcp` path, while the
positive smoke verifies the bearer, Carlson sender binding, initialization, exact
one-tool discovery, zero resources, zero prompts, and no-store response headers.

## 6. Configure local Codex

Place the raw bearer in the owner-only client environment as
`MESSAGES_PRINCIPAL_A_MCP_BEARER`. Keep only the environment-variable name in Codex
configuration:

```toml
[mcp_servers.messages_principal_a]
url = "https://__PUBLIC_HOST__/mcp"
bearer_token_env_var = "MESSAGES_PRINCIPAL_A_MCP_BEARER"
http_headers = { "X-Expected-Sender" = "__LOGICAL_SENDER__" }
enabled_tools = ["tool_send_message"]

[mcp_servers.messages_principal_a.tools.tool_send_message]
approval_mode = "prompt"
```

Restart Codex after changing its environment or MCP configuration. Verify
authenticated initialization and tool discovery first. Do not invoke the tool as a
connectivity test.

## 7. Add a managed cloud agent later

This V1 deliberately has one bearer, matching Heimdall. Move or replace that bearer
when the managed cloud agent replaces local Codex. If both callers must coexist with
separate revocation, extend ADR-0002 before adding a second credential.

The cloud secret manager must inject the raw bearer into the MCP client's
`Authorization` header and the client must send the same non-secret
`X-Expected-Sender` label. Authentication still does not replace explicit send
approval. An unattended caller must not automatically retry a timeout, interruption,
error, or missing response until a separate idempotency/attempt-ledger contract is
implemented.

## Live-send gate

A canary requires a new instruction containing the intended logical sender, exact
recipient, and exact message text. Run only one invocation, never automatically
retry an ambiguous result, and require independent receipt confirmation before
calling the deployment proven.
