# PROTOTYPE — numeric iMessage error terminality

## Question

Can any numeric `chat.db` iMessage error be treated as a terminal, pre-dispatch
rejection that safely authorizes a separate SMS submission? This prototype makes
the state model inspectable and can observe one already-authorized live attempt,
but it deliberately never sends a message and never authorizes SMS.

The important distinction is between collecting evidence and adopting a policy:
a persistent numeric error is a **candidate failure**, not proof that Apple canceled
every copy of the iMessage.

## One-command TUI

```sh
uv run python prototypes/numeric-error-terminality/main.py
```

Use the numbered actions to simulate no row, numeric errors, error recovery,
`is_sent`, `is_delivered`, and the end of the observation window. The full state is
redrawn after every action.

## Read-only live collector

The collector does not send. It reads one JSON object from standard input so the
recipient and body do not appear in process arguments or environment variables:

```sh
uv run python prototypes/numeric-error-terminality/collect.py <<'JSON'
{"recipient":"+15555550123","message":"approved body","sent_after_unix":0,"observe_seconds":60}
JSON
```

Run it only on the Mac and macOS user whose `chat.db` contains the authorized
attempt. It opens the database read-only, requires an exact body/recipient/iMessage
match, pins the matching row, and prints numeric state transitions as JSONL. Output
does not include the recipient, body, or GUID.

No collector result authorizes another transport. A future decision would require
repeated controlled evidence that a particular error occurs before APNs dispatch
and cannot later transition to delivery.
