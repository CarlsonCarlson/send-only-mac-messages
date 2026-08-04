# Security policy

Report vulnerabilities privately through this repository's **Security → Report a
vulnerability** flow. Do not include real recipient identifiers, message bodies,
credentials, or raw platform errors.

## Local boundary

The server runs with the permissions of its launching process and needs Automation
permission to control Messages.app. Transient delivery observation also requires Full
Disk Access to `chat.db`; macOS grants that file permission more broadly than the
adapter's fixed query. No Contacts permission is needed.

The package has no general history, contact, chat, or attachment reader. Its only
local-data path used by MCP is the read-only, ten-second-per-attempt observer. Exact
correlation requires recipient, start time, body, and transport; the resolved row id
is pinned only for the call. The generic query helper is internal and is not exposed
as an MCP tool. Candidate rows are not retained after the call. Exactly one SMS/RCS
fallback is permitted after a synchronous AppleScript failure or an exactly
correlated definitive iMessage failure. Unknown, timeout, interruption, and missing
response outcomes never authorize fallback or retry.

The send payload is supplied to `osascript` over standard input. Recipient and body
must not be added to arguments, environment variables, logs, tool results, fixtures,
or issue evidence.
