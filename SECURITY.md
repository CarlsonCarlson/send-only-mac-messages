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
local-data path used by MCP is a read-only, ten-second-per-attempt observer. It
filters outgoing candidates by recipient, attempt start time, exact body, and
expected transport, then pins the exact row identifier while that attempt remains
in flight. A newest-recipient-row heuristic cannot determine status or authorize a
second submission. The generic query helper is internal and is not exposed as an MCP
tool. Candidate rows are not retained after the call. One SMS/RCS fallback is
permitted only after a synchronous iMessage AppleScript failure. A database-observed
failure is final for the call and cannot authorize a second submission; later
ambiguous outcomes never authorize a retry.

The send payload is supplied to `osascript` over standard input. Recipient and body
must not be added to arguments, environment variables, logs, tool results, fixtures,
or issue evidence.
