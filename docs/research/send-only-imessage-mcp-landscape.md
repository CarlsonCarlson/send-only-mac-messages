# Send-only Apple Messages MCP landscape

Date: 2026-08-02

## Question

Is there an existing open-source MCP server that is already narrow enough to use as the production base for raw-number Apple Messages sends, without message reads, Contacts access, `chat.db`, Full Disk Access, or Heimdall integration?

## Conclusion

One source repository is genuinely send-only, but none of the reviewed projects is a production-ready base that should be adopted unchanged. The smallest and closest project, [`joshiahiru/imessage-mcp`](https://github.com/joshiahiru/imessage-mcp), remains useful prior art but needs significant security, correctness, licensing, test, lifecycle, and delivery-state work.

The current `carterlasalle/mac_messages_mcp` fork has much stronger tests and a successful hosted-Mac capability proof. The initial research recommendation was to start a new repository because transforming it required a large deletion. Carlson subsequently prioritized the most reliably tested base and chose that deletion explicitly. The adopted path is therefore to rename the fork to `send-only-mac-messages`, retain its proven send behavior, and remove every reader, read dependency, read test, and read-facing document.

## Closest candidate: `joshiahiru/imessage-mcp`

Primary sources: [repository](https://github.com/joshiahiru/imessage-mcp), [README](https://github.com/joshiahiru/imessage-mcp/blob/3692a35b16f7105603b291dd5ce349de1575cb48/README.md), [complete server source](https://github.com/joshiahiru/imessage-mcp/blob/3692a35b16f7105603b291dd5ce349de1575cb48/src/index.ts), [package metadata](https://github.com/joshiahiru/imessage-mcp/blob/3692a35b16f7105603b291dd5ce349de1575cb48/package.json), and [history](https://github.com/joshiahiru/imessage-mcp/commits/main/).

### What fits

- Its MCP surface contains `send_imessage` plus a content-free configuration check; it exposes no message-history, contact, chat-list, attachment, or database tool.
- It accepts formatted or E.164-like raw phone numbers without Contacts lookup and also accepts iMessage email addresses.
- It drives Messages.app with AppleScript and requires Automation permission, not Full Disk Access.
- It is small: one TypeScript server source file, a package manifest, and a manual send harness.
- Its README describes iMessage and SMS via Text Message Forwarding.

### Why it is not safe to adopt unchanged

- The repository has one commit from 2026-05-28, no release, no automated test suite, no CI, no issues, no stars, and no forks.
- The repository tree has no `LICENSE` file. `package.json` says MIT, but the distributable file list refers to a license file that does not exist; reuse terms therefore need clarification from the owner before copying code.
- It passes the normalized recipient and entire message body as `osascript` command-line arguments. Those values can appear in process metadata, violating the hosted prototype's privacy requirement.
- It returns the raw recipient and a message preview in the MCP result. That is acceptable for an interactive local client but conflicts with the production sender's redacted operational evidence contract.
- Its tool description and README say it falls back to SMS, but the source does not automatically retry iMessage as SMS. The caller selects `iMessage` or `SMS`; the AppleScript falls back from a missing requested SMS service to iMessage, not the reverse.
- AppleScript acceptance is returned as success with no idempotency, retry safety, durable command state, delivery observation, or outcome-unknown state.
- It does not address the hosted Carlson GUI/TCC lifecycle, restart behavior, packaging, rollback, or remote authenticated ingress.
- Its npm name is not available: the published [`imessage-mcp`](https://www.npmjs.com/package/imessage-mcp) package belongs to a different, mature read-only project.

## Other reviewed projects

### `marissamarym/imessage-mcp-server`

Primary sources: [repository](https://github.com/marissamarym/imessage-mcp-server), [README](https://github.com/marissamarym/imessage-mcp-server/blob/4ed38767688fa3eafba7668e794fd651c7ffac57/README.md), and [history](https://github.com/marissamarym/imessage-mcp-server/commits/master/).

This is not send-only. It exposes a Contacts resource and `search_contacts`, requires Contacts permission, and supports recipient lookup alongside sending. It has no tests, no release, no recognized repository license, and its last source commit was 2024-12-11.

### `anipotts/imessage-mcp`

Primary sources: [repository](https://github.com/anipotts/imessage-mcp), [README](https://github.com/anipotts/imessage-mcp/blob/main/README.md), [npm package](https://www.npmjs.com/package/imessage-mcp), and [v1.3.0 release](https://github.com/anipotts/imessage-mcp/releases/tag/v1.3.0).

This is a mature but intentionally read-only analytics MCP with 26 tools, direct `chat.db` and AddressBook access, and Full Disk Access. It is not a send base and also occupies the natural `imessage-mcp` package name.

### Forks of `carterlasalle/mac_messages_mcp`

Primary source: [GitHub fork list](https://github.com/carterlasalle/mac_messages_mcp/forks).

GitHub reports 48 forks. Their live repository metadata did not identify an intentionally send-only fork; the descriptions retained the upstream read/search/contact/attachment/send scope. The Carlson fork is therefore not missing an obvious reader-free sibling that can simply replace it.

## Adopted decision

Use the tested Carlson fork as the base, rename it `send-only-mac-messages`, and make the deletion itself an executable security boundary. The resulting package exposes exactly one raw-number send tool, preserves iMessage with immediate SMS/RCS fallback, keeps recipient and message out of process arguments and logs, and reports honest accepted-unverified results. It exposes no content-free health tool because the agreed first version is literally send-only.

Retain the upstream fork relationship and the prototype commit as historical evidence, but do not merge the prototype branch. Production work starts from clean mainline on a new branch and must reproduce the hosted canary after the read surface is gone.
