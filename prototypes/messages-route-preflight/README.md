# PROTOTYPE — Messages route preflight

Question: can native Messages resolve one raw phone number to a stable, machine-readable
`iMessage` or `Text Message • SMS/RCS` route before any message body exists, and can the
probe abort cleanly when that state is missing or ambiguous?

This prototype exercises only the no-send preflight:

1. open a new empty composer;
2. enter one raw phone number in `To:`;
3. require the same recognized Accessibility placeholder for four consecutive samples;
4. discard the empty composer after a resolution, timeout, or ambiguous state.

It never accepts a body, invokes a Messages send command, presses Return/Enter, or clicks a
send button. The recipient is held only in memory. Messages still contacts Apple's routing
services as part of recipient resolution.

Run it on the Mac and macOS user whose Messages account would perform the eventual send:

```sh
swift prototypes/messages-route-preflight/main.swift
```

The terminal host needs macOS Accessibility permission. Start with Messages open and no
unfinished New Message composer.

## Result so far — 2026-08-05

On Carlson's Mac, the known SMS-only incident number completed six consecutive cycles. Every
cycle produced all of the following before the composer was discarded:

- one committed recipient token;
- an empty `messageBodyField`;
- the machine-readable placeholder `Text Message • SMS` for four consecutive samples; and
- no remaining New Message item after the PID-targeted Escape action.

No body was entered and no message was sent. An obviously invalid number also
resolved to `Text Message • SMS`; this proves the UI signal answers **which transport Messages
would try**, not whether the phone number exists or a carrier will deliver it.

This is not yet production proof. The same five-cycle check still needs to run in Kevin's
visible hosted-Mac GUI session for both a known SMS-only number and a known iMessage number.
An SSH-owned `System Events` probe hung rather than gaining the GUI/TCC context, so the
prototype correctly was not run through SSH and no hosted-Mac permissions were changed.
