# Security policy

Report vulnerabilities privately through this repository's **Security → Report a
vulnerability** flow. Do not include real recipient identifiers, message bodies,
credentials, or raw platform errors.

## Local boundary

The server runs with the permissions of its launching process and needs Automation
permission to control Messages.app. It does not need Full Disk Access or Contacts
permission and contains no local message, contact, chat, or attachment reader.

The send payload is supplied to `osascript` over standard input. Recipient and body
must not be added to arguments, environment variables, logs, tool results, fixtures,
or issue evidence.
