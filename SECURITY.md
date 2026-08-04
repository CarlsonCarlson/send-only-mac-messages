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
local-data path used by MCP is the verbatim upstream read-only, six-second observer.
It filters outgoing candidates by recipient and send time, prefers an exact body
match, and retains upstream's newest-recipient-row fallback. The generic upstream
query helper is internal and is not exposed as an MCP tool. Candidate rows are not
retained after the call. SMS fallback occurs only inside the initial upstream
AppleScript when the iMessage block errors; later or ambiguous outcomes never
authorize a retry.

The send payload is supplied to `osascript` over standard input. Recipient and body
must not be added to arguments, environment variables, logs, tool results, fixtures,
or issue evidence.
