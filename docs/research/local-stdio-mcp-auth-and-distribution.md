# Local stdio MCP authentication and distribution

Date: 2026-08-03

## Question

How are other developers expected to use an open-source MCP server that does not
implement caller authentication, and what does that mean for this repository?

## Conclusion

The missing MCP OAuth layer is normal for this repository's intended deployment
model. It is a **local stdio adapter**, not a shared service. Each developer is
expected to run a separate copy on their own Mac, under their own macOS account,
Messages login, and Automation permission. Their MCP host launches the process and
communicates with it through the child process's private standard streams.

Open source is not the reason authentication is absent. Authentication code can be
open source; secrets remain private. The reason is that there is no independently
reachable server endpoint or population of remote callers to authenticate. If this
adapter were exposed over HTTP, caller authentication would become a required part
of the deployment design.

## The four separate trust decisions

| Decision | Typical owner for local stdio | This repository |
| --- | --- | --- |
| Trust the code and start it | MCP host and user | User clones/configures the repository; host launches `uv` |
| Decide who can reach the MCP process | Local transport and OS process boundary | stdio only; no listening socket |
| Authorize the underlying service | Local OS/application | Messages.app login plus macOS Automation permission |
| Approve a particular tool call | MCP host policy/UI and any parent workflow | Not implemented by this server |

The current MCP architecture says a local stdio server typically serves one MCP
client, while a remote Streamable HTTP server typically serves many. The stdio
binding specifically says the client launches the server as a subprocess and uses
`stdin`/`stdout` for the connection. [MCP architecture: Participants](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture#participants),
[MCP stdio transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)

That is the local access-control mechanism: possession of a network credential is
replaced by the host deliberately launching a program and owning its pipe. It is not
cryptographic user authentication, and another program running with sufficient local
privilege could launch its own copy. The MCP security guide therefore recommends
stdio for local servers to limit access to the MCP client and recommends a token or
restricted IPC if a local server uses HTTP instead. [MCP security guidance: Local
MCP Server Compromise](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices#local-mcp-server-compromise)

## What the current authorization specification requires

The current stable authorization specification is explicit:

- MCP authorization is optional.
- HTTP implementations should follow the MCP authorization specification.
- stdio implementations should not use that OAuth flow and should obtain any needed
  credentials from the environment.

[MCP 2026-07-28 Authorization: Protocol Requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization#protocol-requirements)

For local servers that call cloud APIs, credentials are commonly supplied through
environment variables or acquired through an embedded third-party authentication
library. OAuth in the MCP specification is designed for remotely hosted HTTP
servers. [Understanding Authorization in MCP](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/authorization#when-should-you-use-authorization)

This adapter does not need a GitHub-style API token because Messages.app owns the
upstream account session. macOS separately asks whether an application may automate
and control another application, and the user can revoke that permission in Privacy
& Security > Automation. [Apple: Allow apps to control other apps](https://support.apple.com/guide/mac-help/allow-apps-to-control-other-apps-on-mac-mchl07817563/mac)

Tool approval is also separate from authentication. MCP does not mandate one UI,
although hosts should show tools and invocations and offer human confirmation. The
tool specification still places input validation, access controls, rate limiting,
and output sanitization responsibilities on servers. [MCP Tools: User Interaction
Model](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#user-interaction-model),
[MCP Tools: Security Considerations](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#security-considerations)

## Typical open-source local-server workflow

The normal workflow is:

1. A developer installs a package, downloads a bundle, or clones the source.
2. They add `command`, `args`, and optional `env` settings to an MCP host.
3. The host launches a private local process when it needs the server.
4. That process operates with the developer's OS permissions and their own service
   credentials.
5. The host applies its own trust and tool-approval policy.

The official local-filesystem tutorial uses exactly this pattern and warns that the
server runs with the user's account permissions. The official reference-server
repository likewise shows `npx`/`uvx` packages configured through `command`, `args`,
and optional secret environment variables. [Connect to local MCP servers](https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers#installing-the-filesystem-server),
[official reference-server examples](https://github.com/modelcontextprotocol/servers#using-an-mcp-client)

First-party hosts use the same distinction. Codex starts stdio servers by command
and supports environment variables; its bearer-token and OAuth settings are for
Streamable HTTP servers. VS Code describes stdio as the most common local form and
can additionally sandbox the process. [OpenAI Codex MCP configuration](https://developers.openai.com/codex/mcp),
[VS Code MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)

For friendlier distribution, an author can publish a PyPI/npm/OCI package or an MCPB
artifact and advertise it using the MCP Registry's `server.json` metadata. The
registry stores installation metadata; the package registry or release host stores
the actual code. Each local user still launches their own copy. [MCP Registry](https://modelcontextprotocol.io/registry/about),
[supported package types](https://modelcontextprotocol.io/registry/package-types),
[MCPB overview](https://github.com/modelcontextprotocol/mcpb#for-bundle-developers)

## What fellow developers can do with this repository today

The implemented runtime matches the local pattern: `run_server()` selects stdio and
opens no HTTP listener. The README tells users to clone the repository, run `uv
sync`, and configure their MCP host to execute `uv --directory <clone> run
send-only-mac-messages`. It requires Messages.app to be signed into the intended
sending profile and the launching application or Terminal to have Automation
permission. [server implementation](https://github.com/CarlsonCarlson/send-only-mac-messages/blob/306070016c027ede4116a5dde493c159c683e58e/send_only_mac_messages/server.py#L51-L54),
[source installation and configuration](https://github.com/CarlsonCarlson/send-only-mac-messages/blob/306070016c027ede4116a5dde493c159c683e58e/README.md#L45-L85)

Therefore the currently published use path is:

> clone locally -> configure the host command -> approve macOS Automation -> let the
> host invoke the local tool

The repository also contains an MCPB manifest and a build script that vendors `uv`,
so a one-click local bundle is clearly intended. However, `0.1.0` is still marked
unreleased, there is no GitHub release containing an MCPB, no `server.json` for the
MCP Registry, and no published PyPI distribution. Fellow developers can build the
bundle themselves, but there is not yet a published package or one-click artifact.
[MCPB manifest](https://github.com/CarlsonCarlson/send-only-mac-messages/blob/306070016c027ede4116a5dde493c159c683e58e/manifest.json),
[MCPB build script](https://github.com/CarlsonCarlson/send-only-mac-messages/blob/306070016c027ede4116a5dde493c159c683e58e/scripts/build_mcpb.py),
[unreleased changelog](https://github.com/CarlsonCarlson/send-only-mac-messages/blob/306070016c027ede4116a5dde493c159c683e58e/CHANGELOG.md),
[releases](https://github.com/CarlsonCarlson/send-only-mac-messages/releases)

The current MCPB documentation uses manifest version `0.4`, while this repository's
manifest is `0.3`. That does not prove the bundle is unusable, but it means the
packaged-install path should be revalidated against current host behavior before it
is advertised as ready. [Current MCPB manifest example](https://github.com/modelcontextprotocol/mcpb#for-bundle-developers)

## Security implication for this send tool

No MCP OAuth layer is needed for the intended direct stdio use, but that does not
make every local use safe. This server accepts any syntactically valid phone number
and has no caller identity, recipient allowlist, per-user policy, rate limit, or
durable approval check. Host confirmation is recommended by MCP but is not guaranteed
by the protocol. A developer should run it only from a trusted host with an explicit
approval policy; autonomous or mass-send policy belongs in the trusted parent unless
the server is deliberately expanded to enforce it.

If the project later exposes Streamable HTTP—even only on localhost—the design must
change. The transport specification requires `Origin` validation, recommends binding
local instances only to `127.0.0.1`, and recommends authenticating every connection.
For a protected remote server, MCP defines the server as an OAuth resource server:
it publishes protected-resource metadata, accepts bearer tokens on every request,
validates that each token was issued for this server, and rejects invalid or
wrong-audience tokens. [Streamable HTTP: Security & Endpoint](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http#security-endpoint),
[MCP Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)

The clean boundary is therefore:

- **Local personal use:** stdio + trusted host + OS account/TCC + host approval.
- **Published local product:** the same runtime, packaged through PyPI/uvx or MCPB.
- **Shared/remote service:** Streamable HTTP + real caller authentication and
  authorization + tenant/policy/rate-limit/audit controls.
