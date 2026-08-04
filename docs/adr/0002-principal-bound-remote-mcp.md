# ADR-0002: Authenticate one principal-bound remote MCP with one bearer

**Status:** Accepted; delivery-result clauses superseded by ADR-0003

## Context

ADR-0001 reduced this repository to one send-only tool over local stdio. Local Codex
will now call the adapter on a hosted Mac, and a managed cloud agent may replace that
caller later. SSH-owned processes cannot inherit another process's Messages
Automation grant, so the scalable transport must terminate inside the intended
macOS graphical user's own process.

Heimdall already has a deployed private-MCP pattern: stateless Streamable HTTP on a
loopback backend, a dedicated Cloudflare hostname and exact `/mcp` path, and one
non-expiring bearer whose raw value exists only in the client. The host stores a
SHA-256 digest in an owner-only file and supports only local create, replace, and
revoke operations. Cloudflare provides TLS and ingress but is not the authentication
authority.

Caller authentication, sender identity, send authorization, and delivery state are
separate decisions. Authenticating an MCP request does not authorize its particular
message, select a Messages account, or prove delivery.

## Decision

Add an optional remote entry point while retaining the local stdio entry point.
Remote operation uses stateless JSON-response Streamable HTTP bound only to
`127.0.0.1`. An outbound Cloudflare Tunnel may publish one exact hostname and the
exact `/mcp` path to that loopback origin.

Use the same V1 authentication model as Heimdall:

- exactly one 32-random-byte, unpadded base64url bearer
- `Authorization: Bearer` on every HTTP request
- the raw bearer only in the client's secret environment
- only its lowercase SHA-256 digest on the hosted Mac
- a regular digest file owned by the server's effective user with mode `0600`
- constant-time digest comparison
- local `create`, `replace`, and `revoke` lifecycle operations
- no OAuth server, token database, Cloudflare Access identity, query-string secret,
  Keychain integration, or automatic rotation

The origin rejects the wrong host, path, query, method, content headers, oversized
body, bearer, browser origin, or logical sender before dispatching to MCP. All
transport rejections use a fixed body and `Cache-Control: no-store`.

Each endpoint has one immutable logical sender label and requires a matching
`X-Expected-Sender` header. The tool rechecks that request label, the effective UID,
and `/dev/console` owner immediately before invoking the send-only Messages adapter.
Any mismatch fails before Messages.app. A process addressed to one logical sender
can execute only inside that sender's configured GUI user or fail; it cannot fall
through to another account.

Run one remote process, hostname, bearer/digest, loopback port, LaunchAgent, and
logical label per sending principal. The process must be a per-user graphical
LaunchAgent or GUI application, never a system LaunchDaemon or SSH child.

Remote results add the configured logical sender label around the adapter's fixed
result token. `accepted-unverified` retains its ADR-0001 meaning and never claims
delivery. The server exposes one destructive, non-idempotent tool and serializes
send execution. A client must not automatically retry a timeout, interruption,
error, or missing response.

Explicit send approval remains outside bearer authentication. Local Codex must keep
the tool on per-call prompt. An unattended workflow requires its own approved-action
gate and an idempotency/attempt-ledger decision before retries are allowed.

## Consequences

- Local Codex can use `bearer_token_env_var` without storing the secret in
  `config.toml`.
- A future managed cloud agent can receive the bearer through its own secret store.
  If local and cloud callers must coexist with independently revocable credentials,
  that is a deliberate expansion beyond this one-bearer V1.
- Replacing or revoking the verifier requires restarting the remote process so it
  reloads the digest.
- The public hostname, logical sender, expected macOS user, port, and digest path are
  explicit launch configuration; the server never infers the intended principal
  from whichever user happened to launch it.
- Streamable HTTP does not solve TCC. Deployment is incomplete until a content-free
  check proves the process runs in the intended graphical session, followed by a
  separately approved one-shot send canary and receipt confirmation.
- Any second principal gets an independent deployment rather than a multi-account
  switch inside this server.
