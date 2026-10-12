# iMessage capability preflight and duplicate-safe routing

Date: 2026-08-05

## Question

Can the send-only Messages adapter determine whether a raw phone number is
iMessage-capable before it sends anything, so that one authorized call reaches
either iMessage or SMS/RCS without creating two recipient-visible submissions?

## Conclusion

Apple performs a recipient lookup internally, but the reviewed supported macOS
interfaces do not expose a reliable arbitrary-number iMessage-registration query.
The current Messages AppleScript dictionary can select an account whose type is
`iMessage`, `SMS`, or `RCS`; it cannot ask whether a raw recipient is currently
registered for iMessage.

There is real prior art outside those supported interfaces. BlueBubbles and
`openclaw/imsg` inject helpers into Messages.app and call Apple's private IDS query
controller to force-refresh a raw phone number's iMessage status. That is a genuine
live preflight, not a `chat.db` guess. The reviewed implementations require private,
unsupported frameworks, Messages process injection, and weakened macOS platform
protections, so they are evidence that the capability exists—not a production-safe
dependency for this hosted Mac.

This means an application-managed sequence of “submit iMessage, observe failure,
then submit SMS” cannot simultaneously guarantee both automatic reachability and no
cross-transport duplicate. After Messages accepts the first submission, a transient
failure is not proof that the iMessage can never arrive. That is the failure mode
recorded in [ADR-0006](../adr/0006-immediate-only-sms-fallback.md).

The most useful production-host investigation is a **no-send native-UI prototype**:
enter only
the raw number in a new Messages compose session, let Messages resolve the route,
read the blue/green pre-send state through macOS Accessibility, and—only after the
prototype proves the state is stable—send exactly once from that same compose
session. This would reuse Apple's internal routing decision rather than create a
second transport submission. It is not a supported AppleScript capability, however,
and must not be described as exactly-once or production-safe without further
evidence. A separate private-IDS prototype is technically stronger, but belongs only
on an isolated disposable Mac after explicit approval of its security tradeoff.

## Apple does the lookup internally

Apple Platform Security says that when a user enters a phone number or email address
for a new iMessage conversation, the device contacts Apple Identity Service (IDS) to
retrieve the public keys and APNs addresses associated with the addressee. Therefore
the native Messages stack has a pre-send routing signal. Apple does not document IDS
as a public arbitrary-recipient lookup API. [Apple Platform Security: How iMessage
sends and receives messages](https://support.apple.com/guide/security/how-imessage-sends-and-receives-messages-sec70e68c949/web)

Apple documents that the native compose UI reflects that decision: a blue Send
arrow means the message can use iMessage, while SMS, MMS, and RCS use green. This is
documented for iPhone; the proposed experiment must separately verify what macOS
Tahoe exposes through Accessibility before relying on it. [Apple iPhone User Guide:
Send and reply to messages](https://support.apple.com/guide/iphone/send-and-reply-to-messages-iph82fb73ba3/ios)

## What the supported macOS AppleScript surface exposes

Apple says an application's `.sdef` scripting dictionary describes the commands,
classes, and properties that the app supports. Apple also warns that terminology can
change between application and OS versions. [Apple Mac Automation Scripting Guide:
About Scripting Terminology](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/AboutScriptingTerminology.html)

The installed dictionary inspected for this research was:

- macOS `26.0.1` (`25A362`)
- Messages `26.0`
- `/System/Applications/Messages.app/Contents/Resources/Messages.sdef`
- SHA-256 `a9db9b015709c8c8e92a8bdccf08984635d5c3545f670bcd0e5a3a10bd5f9e4e`

It exposes:

- account service types `SMS`, `iMessage`, and `RCS`;
- `send`, `login`, and `logout` commands;
- participant properties `id`, `account`, `name`, `handle`, and Contacts-derived
  names; and
- account properties such as `enabled`, `connection status`, and `service type`.

It exposes no recipient-registration, capability, availability, route-resolution,
or cancellation property or command. The `service type` property describes the
selected **account**, not whether a participant handle is registered for that
service.

## Why the previous “buddy exists” preflight was a false positive

Upstream commit
[`f77be9e`](https://github.com/carterlasalle/mac_messages_mcp/blob/f77be9eb18d38ba1e3d0ea35721c45d4781344b9/mac_messages_mcp/messages.py#L950-L985)
implemented `_check_imessage_availability` by resolving:

```applescript
set targetService to 1st service whose service type = iMessage
set targetBuddy to buddy "<recipient>" of targetService
if targetBuddy exists then return "true"
```

That checks whether Messages can construct/resolve a participant object under the
iMessage account. It does not query a capability property because the scripting
dictionary has no such property. In the current incident, the send path constructed
the same kind of iMessage participant and Messages accepted the command, but the
outgoing iMessage later became Not Delivered. Participant existence is therefore
not an iMessage-registration test.

## Public Apple APIs do not fill the gap

### MessageUI

`MFMessageComposeViewController.canSendText()` reports whether the **device** is
capable of sending text messages. It takes no recipient and applies collectively to
iMessage, SMS, and MMS. Apple also says its compose interface does not guarantee
delivery. It is not a raw-number iMessage-registration API and is not a native macOS
background sender. [Apple `MFMessageComposeViewController`
documentation](https://developer.apple.com/documentation/messageui/mfmessagecomposeviewcontroller)

### Messages framework

`MSConversation` represents the conversation currently active inside an iMessage
app extension. Its participant identifiers are UUIDs for that conversation, not raw
phone handles with capability status. Apple lists this API for iOS, iPadOS, and Mac
Catalyst rather than native macOS. [Apple `MSConversation`
documentation](https://developer.apple.com/documentation/messages/msconversation)

### Critical Messaging

`MSCriticalSMSMessenger` is an entitled, authorization-gated, SMS-only API. Apple's
platform metadata lists iOS, iPadOS, and Mac Catalyst, not native macOS. It neither
looks up iMessage registration nor replaces this hosted-Mac adapter. [Apple Critical
Messaging overview](https://developer.apple.com/documentation/messages/critical-messaging-api),
[Apple `MSCriticalSMSMessenger`
documentation](https://developer.apple.com/documentation/messages/mscriticalsmsmessenger)

## Duplicate-safe routing options

### 1. Select SMS/RCS before submission

For raw phone numbers, choose the paired-iPhone SMS/RCS service and make one
submission. This removes application-created cross-transport duplicates and reaches
non-iMessage mobile numbers, but gives up iMessage-first delivery. It still does not
guarantee carrier delivery or exactly-once human receipt. Apple documents that a Mac
can send SMS/MMS/RCS through a configured iPhone. [Apple Messages User Guide: Set up
Messages on Mac](https://support.apple.com/en-euro/guide/messages/ichte16154fb/mac)

### 2. Require an explicit transport decision before the call

A caller or operator can authorize exactly one transport. This preserves the
one-submission invariant, but prior conversation history, a cache, or an old route
observation is not a reliable current registration check; a recipient can enable or
disable iMessage later.

### 3. Delegate one logical send to native Messages routing

The native Messages UI knows the pre-send blue/green route. A controlled prototype
could use Accessibility to:

1. open a new compose session without a body;
2. enter the exact raw number;
3. wait for a stable, inspectable route state;
4. abort without sending if the route is absent or ambiguous; and
5. after separate send authorization, populate the body and send once from that same
   compose session.

Keeping resolution and sending in the same compose session minimizes, but does not
eliminate, a time-of-check/time-of-use race. Accessibility/UI behavior is not part of
the Messages AppleScript dictionary, can change with macOS releases, and may expose
only visual state rather than a durable routing contract. This is a prototype
candidate, not a confirmed fix.

### 4. Let Apple automatically “Send as Text Message”

Apple documents an iPhone setting that automatically **tries** SMS when iMessage is
unavailable. Apple does not document an exactly-once, cancellation, or cross-channel
idempotency guarantee for that behavior, and the current adapter explicitly submits
to the iMessage account rather than invoking a documented generic auto-routing API.
The setting alone is not proof that this adapter can safely restore automatic
fallback. [Apple Support: If you can't send or receive messages on your iPhone or
iPad](https://support.apple.com/en-us/118433)

## Decision boundary

Do not restore observer-triggered SMS fallback merely because the failed row is an
exact body/recipient match. Exact correlation identifies which iMessage attempt was
observed; it does not prove that the attempt was canceled or can never arrive.

Do not treat `buddy exists`, an existing chat, a prior blue bubble, contact device
type, or cached history as current iMessage capability.

For the current supported AppleScript implementation, the only demonstrated way to
prevent application-created cross-transport duplicates is to submit exactly one
chosen transport. The native-UI/Accessibility route probe is the next bounded way to
test whether Apple's own pre-send decision can preserve iMessage-when-available and
SMS/RCS-otherwise without the adapter making two submissions.

## Comparative MCP/source-code survey

Repository default-branch heads were checked on 2026-08-05 and are pinned below.
The survey separates four different mechanisms that projects sometimes call an
“availability check”:

1. Apple's supported AppleScript surface, which selects a concrete account but has no
   per-recipient capability property;
2. historical `chat.db` inference, which can be stale or absent;
3. native Messages UI resolution, which exposes Apple's live decision before Send;
   and
4. private IDS/IMCore queries, which can perform a live lookup but require unsupported
   frameworks and, in the reviewed implementations, process injection.

| Implementation | Normal send routing | Pre-send capability source | Fallback and duplicate implications |
| --- | --- | --- | --- |
| [`carterlasalle/mac_messages_mcp@a6e4605`](https://github.com/carterlasalle/mac_messages_mcp/tree/a6e460526096996ea04ab880e519e3ae627b0dc3) | Hard-coded iMessage first; a synchronous AppleScript error can start a separate SMS send. | Separate MCP tool infers from prior `chat.db` rows; the send path does not call it. | No delayed-failure fallback in upstream main, but its synchronous two-call fallback has no cross-transport idempotency key. |
| [`openclaw/imsg@be5b490`](https://github.com/openclaw/imsg/tree/be5b490531000000abc079e26512b23709e16d84) | `auto` uses prior local service history; unknown recipients try iMessage, then a thrown AppleScript error can trigger a separate SMS call. | `--local` is history only. A separate injected `whois`/`handles.check` path calls private IDS. | Ordinary `send --service auto` does not use live `whois`; its fallback test expects two transport submissions. |
| [`BlueBubbles server@f2e2286`](https://github.com/BlueBubblesApp/bluebubbles-server/tree/f2e2286241a7c3b6617a82b37d4afaab4df3a6b9) + [`helper@1ee57f3`](https://github.com/BlueBubblesApp/bluebubbles-helper/tree/1ee57f3fde63f8cc5769d60cfabfe9a06fcc1069) | Sends to an already selected chat GUID whose prefix carries the service. | Separate private helper force-refreshes IDS status for the raw phone/email. | Strongest proof of live lookup, but its in-memory `tempGuid` gate is not durable provider idempotency and its AppleScript timeout recovery can resubmit. |
| [`griches/apple-mcp@4615246`](https://github.com/griches/apple-mcp/tree/461524625402548f7729db9f7a3758264b7644be) | Caller chooses iMessage or SMS; omission defaults to iMessage. | None. | One caller-selected service and no fallback avoids application-created cross-transport duplication, but may choose the wrong service. |
| [`antondkg/mcp-imessage@5d4f736`](https://github.com/antondkg/mcp-imessage/tree/5d4f7362a862760e4b5aec50be0fb4c684c8c41e) | iMessage first; stderr containing `buddy` or `service` starts a separate SMS send. | None. | No delayed-failure fallback or idempotency; an error-triggered second submission remains ambiguous. |
| [`joshiahiru/imessage-mcp@3692a35`](https://github.com/joshiahiru/imessage-mcp/tree/3692a35b16f7105603b291dd5ce349de1575cb48) | Caller selects iMessage or SMS; default is iMessage. Selecting SMS falls back to the iMessage account only when no SMS service object exists. | None. | It does not implement the advertised iMessage-to-SMS fallback, delivery observation, or idempotency. |
| [`marissamarym/imessage-mcp-server@4ed3876`](https://github.com/marissamarym/imessage-mcp-server/tree/4ed38767688fa3eafba7668e794fd651c7ffac57) | Always sends to an iMessage buddy. | None. | No SMS, preflight, delivery observation, retry, or idempotency. |
| [`photon-hq/imessage-kit@20a1536`](https://github.com/photon-hq/imessage-kit/tree/20a1536d7f56686b2973a27103949c5495955785) | Fresh direct messages hard-code the iMessage service. | None. | It retries each AppleScript step three times by default; without an idempotency key, retry after ambiguous acceptance can duplicate. |
| [`Rolstenhouse/py-iMessage@badc16c`](https://github.com/Rolstenhouse/py-iMessage/tree/badc16c5751e602f45b9422f7f8084412a7b1e90) | Separate JXA UI routine types the recipient/body and presses Return once. | Historical UI probe opens a new compose session and inspects an iMessage/not-registered menu. | Useful prior art for the UI experiment, but its current code intentionally returns false on macOS 10.16 or later and the probe/send sessions are separate. |

### Upstream lineage and the misleading “availability” tool

Upstream commit [`f77be9e`](https://github.com/carterlasalle/mac_messages_mcp/commit/f77be9eb18d38ba1e3d0ea35721c45d4781344b9)
introduced both the immediate iMessage-to-SMS AppleScript fallback and the original
`buddy exists` helper. Upstream main at `a6e4605` contains that fallback lineage plus
the delivery-observation work from `1a8f309`, but its availability helper is now a
different heuristic: it queries historical `handle.service`, message counts, and
message errors and returns true only for prior non-errored iMessage history.
[`messages.py` L1525-L1578](https://github.com/carterlasalle/mac_messages_mcp/blob/a6e460526096996ea04ab880e519e3ae627b0dc3/mac_messages_mcp/messages.py#L1525-L1578)

The MCP tool presents that historical result as whether the recipient “has iMessage
available,” but the actual send path does not call the tool or helper.
[`server.py` L306-L340](https://github.com/carterlasalle/mac_messages_mcp/blob/a6e460526096996ea04ab880e519e3ae627b0dc3/mac_messages_mcp/server.py#L306-L340)
The sender still selects the iMessage account first and switches to the SMS account
only inside the AppleScript error handler.
[`messages.py` L1693-L1759](https://github.com/carterlasalle/mac_messages_mcp/blob/a6e460526096996ea04ab880e519e3ae627b0dc3/mac_messages_mcp/messages.py#L1693-L1759)
Its database observer can report a delayed error, but reporting that outcome does not
perform live capability resolution.
[`messages.py` L810-L921](https://github.com/carterlasalle/mac_messages_mcp/blob/a6e460526096996ea04ab880e519e3ae627b0dc3/mac_messages_mcp/messages.py#L810-L921)

The send-only fork was cut from `a6e4605`: `6167a85` reduced the surface to one send
tool, and `7e71af5` later retained the relevant upstream send/observer subset. The
current fork therefore inherited the upstream concrete-account AppleScript design,
not a live recipient capability lookup.

### What mature projects do

`openclaw/imsg` is the closest maintained command/RPC engine. Its ordinary `auto`
mode queries local history: a prior SMS-only handle selects SMS, while a prior
iMessage handle or no history selects iMessage.
[`SendCommand.swift` L125-L154](https://github.com/openclaw/imsg/blob/be5b490531000000abc079e26512b23709e16d84/Sources/imsg/Commands/SendCommand.swift#L125-L154)
[`MessageStore+ServiceAvailability.swift` L32-L78](https://github.com/openclaw/imsg/blob/be5b490531000000abc079e26512b23709e16d84/Sources/IMsgCore/MessageStore%2BServiceAvailability.swift#L32-L78)
If an eligible iMessage AppleScript call throws, it invokes AppleScript again for SMS.
[`MessageSender.swift` L70-L104](https://github.com/openclaw/imsg/blob/be5b490531000000abc079e26512b23709e16d84/Sources/IMsgCore/MessageSender.swift#L70-L104)
[`MessageSender.swift` L159-L190](https://github.com/openclaw/imsg/blob/be5b490531000000abc079e26512b23709e16d84/Sources/IMsgCore/MessageSender.swift#L159-L190)
The regression test explicitly expects `imessage` followed by `sms`.
[`MessageSenderSMSFallbackTests.swift` L21-L35](https://github.com/openclaw/imsg/blob/be5b490531000000abc079e26512b23709e16d84/Tests/IMsgCoreTests/MessageSenderSMSFallbackTests.swift#L21-L35)

The same project has a separate **live private** lookup. Its injected helper formats
the destination as `tel:` or `mailto:`, calls private `IDSIDQueryController` methods
for Apple's Madrid/iMessage service, and maps status `1` to available.
[`IMsgInjected.m` L6411-L6461](https://github.com/openclaw/imsg/blob/be5b490531000000abc079e26512b23709e16d84/Sources/IMsgHelper/IMsgInjected.m#L6411-L6461)
The CLI distinguishes that bridge-backed `whois` from history-only `whois --local`.
[`BridgeIntroCommands.swift` L163-L267](https://github.com/openclaw/imsg/blob/be5b490531000000abc079e26512b23709e16d84/Sources/imsg/Commands/BridgeIntroCommands.swift#L163-L267)
This is not part of ordinary `send --service auto`. It relies on a helper injected
inside Messages.app; the project documents SIP-disabled and library-validation
requirements and calls the features unstable on current macOS.
[`advanced-imcore.md` L41-L51](https://github.com/openclaw/imsg/blob/be5b490531000000abc079e26512b23709e16d84/docs/advanced-imcore.md#L41-L51)

BlueBubbles independently proves the same private capability primitive. Its helper
converts the raw address into an IDS destination, force-refreshes
`IDSServiceNameiMessage`, and returns available only when status equals `1`.
[`BlueBubblesHelper.m` L636-L661](https://github.com/BlueBubblesApp/bluebubbles-helper/blob/1ee57f3fde63f8cc5769d60cfabfe9a06fcc1069/Messages/MacOS-11%2B/BlueBubblesHelper/BlueBubblesHelper.m#L636-L661)
The helper README explicitly describes private APIs, MacForge/mySIMBL injection, and
testing only through macOS 13.
[`README.md` L1-L48](https://github.com/BlueBubblesApp/bluebubbles-helper/blob/1ee57f3fde63f8cc5769d60cfabfe9a06fcc1069/README.md#L1-L48)
The server exposes the lookup behind private-API middleware and keeps lookup failure
as an error rather than silently interpreting it as SMS.
[`httpRoutes.ts` L537-L558](https://github.com/BlueBubblesApp/bluebubbles-server/blob/f2e2286241a7c3b6617a82b37d4afaab4df3a6b9/packages/server/src/server/api/http/api/v1/httpRoutes.ts#L537-L558)
[`handleInterface.ts` L76-L86](https://github.com/BlueBubblesApp/bluebubbles-server/blob/f2e2286241a7c3b6617a82b37d4afaab4df3a6b9/packages/server/src/server/api/interfaces/handleInterface.ts#L76-L86)

This answers “has anyone done it?”: **yes, BlueBubbles and `imsg` perform live IDS
lookups before a send can be selected—but only through Apple's private, unsupported
machinery.** Neither implementation turns the supported Messages AppleScript
dictionary into a live capability query.

### Why BlueBubbles uses private IDS instead of the compose UI

BlueBubbles did not disable SIP solely to answer this routing question. Its helper is
a general private-API bundle for reactions, typing indicators, replies, message
effects, edits, unsends, chat management, and many other features that AppleScript
does not expose; iMessage/FaceTime availability is one item in that larger feature
set. The project's installation guide says SIP is disabled so the server can inject
the helper into Messages and call internal functions. [BlueBubbles helper
README](https://github.com/BlueBubblesApp/bluebubbles-helper/blob/1ee57f3fde63f8cc5769d60cfabfe9a06fcc1069/README.md#L1-L48),
[BlueBubbles Private API installation](https://docs.bluebubbles.app/private-api/installation)

For availability specifically, the injected helper directly calls
`forceRefreshIDStatusForDestinations` on `IDSIDQueryController` and returns whether
the raw phone/email address has iMessage status `1`. The server exposes that through
a Private-API-gated HTTP route and treats a missing helper response as an error.
This is a headless address query, independent of the current Messages window,
Accessibility hierarchy, locale, focus, or an open composer. [BlueBubbles helper
implementation](https://github.com/BlueBubblesApp/bluebubbles-helper/blob/1ee57f3fde63f8cc5769d60cfabfe9a06fcc1069/Messages/MacOS-11%2B/BlueBubblesHelper/BlueBubblesHelper.m#L636-L661),
[server route](https://github.com/BlueBubblesApp/bluebubbles-server/blob/f2e2286241a7c3b6617a82b37d4afaab4df3a6b9/packages/server/src/server/api/http/api/v1/httpRoutes.ts#L537-L558),
[server interface](https://github.com/BlueBubblesApp/bluebubbles-server/blob/f2e2286241a7c3b6617a82b37d4afaab4df3a6b9/packages/server/src/server/api/interfaces/handleInterface.ts#L76-L86)

The native-UI prototype asks a narrower question by a different route: it lets the
Apple-signed Messages process perform its normal lookup, then infers the selected
transport from an Accessibility placeholder. BlueBubbles proves the private direct
query is possible; it does **not** show that this narrower no-send UI observation is
incorrect. No reviewed BlueBubbles source says the project tested and rejected an
Accessibility preflight; that comparison is an architectural inference. The private
path is also not automatically more operationally safe: the current helper README
says it was tested only through macOS 13, and the project's
contributor guide warns that an exception in the injected bundle can crash Messages
and leave the Private API broken until Messages restarts. [BlueBubbles helper
support boundary](https://github.com/BlueBubblesApp/bluebubbles-helper/blob/1ee57f3fde63f8cc5769d60cfabfe9a06fcc1069/README.md#L28-L48),
[BlueBubbles contributor warning](https://docs.bluebubbles.app/private-api/building-and-contributing)

### Reliability gaps the current UI prototype has not closed

The local result is promising but not yet enough to depend on in production:

- **Only the negative route was demonstrated.** Six fresh composers agreed for one
  known SMS-only number, while an invalid number also resolved to SMS. A known-current
  iMessage number has not yet proved that the same Accessibility node changes to
  `iMessage`, nor that it changes correctly after registration or deregistration.
- **The observed placeholder is not a documented routing API.** Apple documents the
  user workflow for entering a recipient and the blue/green service distinction, but
  does not document `AXPlaceholderValue`, `messageBodyField`, the English strings, or
  their stability as a programmatic contract. The prototype hard-codes all four.
  [Apple Messages User Guide: send a message on Mac](https://support.apple.com/en-mide/guide/messages/icht35827/mac),
  [Apple Messages setup and blue/green distinction](https://support.apple.com/en-euro/guide/messages/ichte16154fb/mac)
- **Four identical samples can establish short-term consistency, not finality.** The
  samples span less than one second after recipient commit. A slow IDS response,
  temporary network loss, a Messages restart, or a service outage could leave an
  intermediate value stable long enough to be accepted. The probe must record the
  complete transition timeline and prove that dependency failures become
  `unresolved`, never a confident SMS or iMessage result.
- **SMS routing has separate prerequisites.** Apple says SMS/MMS/RCS on a Mac depends
  on the paired iPhone, matching Apple Account, iMessage, and Text Message Forwarding;
  availability also varies by carrier and region. A green/SMS route is not proof that
  the relay is currently usable or that the destination is deliverable.
  [Apple Messages setup](https://support.apple.com/en-euro/guide/messages/ichte16154fb/mac)
- **Accessibility trust and GUI session are part of the system.** Apple requires the
  controlling process to receive explicit Accessibility permission. A successful
  Terminal-run probe does not establish that the eventual hosted executable,
  `launchd` context, locked-screen state, or remote session is trusted and able to
  manipulate the same GUI. [Apple: allow Accessibility apps](https://support.apple.com/en-gb/guide/mac-help/mh43185/mac),
  [Apple `AXIsProcessTrustedWithOptions`](https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions)
- **Steps 1–4 do not eliminate the later lookup-to-send race.** If production closes
  the resolved composer and performs a separate AppleScript send, the UI result is
  only a stale observation and Messages can re-resolve differently. A later send
  experiment must retain the same composer, recheck its route immediately before one
  Send action, and still submit at most once.

Testing on Kevin's hosted Mac is therefore a **necessary next gate**, not the whole
proof. Run the no-send probe in Kevin's visible, unlocked GUI session under the exact
executable identity intended for production. Use at least one known-current iMessage
control and one known-current SMS-only control; repeat fresh-composer cycles across a
Messages restart and a login/reboot; exercise slow/offline IDS and unavailable SMS
relay states; and confirm every failure is `unresolved`, every composer is discarded,
and no outgoing `chat.db` row appears. An SSH-owned probe is not equivalent because it
does not demonstrate the hosted GUI/TCC context.

### Other public-AppleScript MCPs and send libraries

- `griches/apple-mcp` requires the caller to choose `iMessage` or `SMS` and submits
  once to that exact account; it has no capability lookup or fallback.
  [`index.ts` L75-L94](https://github.com/griches/apple-mcp/blob/461524625402548f7729db9f7a3758264b7644be/messages/src/index.ts#L75-L94)
  [`applescript.ts` L32-L50](https://github.com/griches/apple-mcp/blob/461524625402548f7729db9f7a3758264b7644be/messages/src/applescript.ts#L32-L50)
- `antondkg/mcp-imessage` hard-codes iMessage first and starts a separate SMS
  AppleScript only when the first process fails with stderr mentioning `buddy` or
  `service`; it has no live preflight or idempotency key.
  [`send.rs` L16-L90](https://github.com/antondkg/mcp-imessage/blob/5d4f7362a862760e4b5aec50be0fb4c684c8c41e/src/send.rs#L16-L90)
  [`send.rs` L204-L234](https://github.com/antondkg/mcp-imessage/blob/5d4f7362a862760e4b5aec50be0fb4c684c8c41e/src/send.rs#L204-L234)
- `joshiahiru/imessage-mcp` defaults to iMessage and accepts an explicit SMS choice.
  If the requested SMS service does not exist, its script falls back in the opposite
  direction—to iMessage. It does not inspect recipient capability or delivery.
  [`src/index.ts` L108-L174](https://github.com/joshiahiru/imessage-mcp/blob/3692a35b16f7105603b291dd5ce349de1575cb48/src/index.ts#L108-L174)
- `marissamarym/imessage-mcp-server` always submits through an iMessage buddy and
  reports success when AppleScript exits successfully.
  [`src/index.ts` L159-L197](https://github.com/marissamarym/imessage-mcp-server/blob/4ed38767688fa3eafba7668e794fd651c7ffac57/src/index.ts#L159-L197)
- Photon `imessage-kit` likewise hard-codes iMessage for fresh direct messages and
  explicitly notes that AppleScript has no `any` service.
  [`applescript-builder.ts` L86-L138](https://github.com/photon-hq/imessage-kit/blob/20a1536d7f56686b2973a27103949c5495955785/src/infra/outgoing/applescript-builder.ts#L86-L138)
  It retries each AppleScript step three times by default, even though its own public
  contract says success is command acceptance rather than delivery. That retry policy
  is not proof against duplicates after an ambiguous first dispatch.
  [`sender.ts` L36-L44](https://github.com/photon-hq/imessage-kit/blob/20a1536d7f56686b2973a27103949c5495955785/src/infra/outgoing/sender.ts#L36-L44)
  [`sender.ts` L194-L209](https://github.com/photon-hq/imessage-kit/blob/20a1536d7f56686b2973a27103949c5495955785/src/infra/outgoing/sender.ts#L194-L209)
  [`sdk.ts` L149-L166](https://github.com/photon-hq/imessage-kit/blob/20a1536d7f56686b2973a27103949c5495955785/src/sdk.ts#L149-L166)

Historical `py-iMessage` is direct precedent for a no-send UI probe. It opens a new
compose session, enters the number, and inspects the recipient menu for `iMessage`
versus “not registered.”
[`check_imessage.js` L20-L58](https://github.com/Rolstenhouse/py-iMessage/blob/badc16c5751e602f45b9422f7f8084412a7b1e90/py_imessage/osascript/check_imessage.js#L20-L58)
However, the branch for macOS 10.16 or later is empty and therefore returns false;
the implementation is not reusable on current macOS. Its separate UI send script
also opens a new composer, so it does not preserve one resolved compose session.
[`send_message.js` L21-L45](https://github.com/Rolstenhouse/py-iMessage/blob/badc16c5751e602f45b9422f7f8084412a7b1e90/py_imessage/osascript/send_message.js#L21-L45)

### Source-backed recommendation (inference)

There are now two credible prototype tracks, but they have different security and
support boundaries.

**Prototype A—recommended first: native Messages UI routing without sending.** This
keeps SIP enabled and delegates live resolution to the already-running, Apple-signed
Messages process:

1. Open a fresh composer under the intended principal's existing Messages session.
2. Enter only one normalized recipient and commit the recipient chip; do not enter a
   body and do not activate Send.
3. Wait for a settled state, then inspect the Accessibility tree for a semantic
   service label, recipient status, composer placeholder, or Send-button label. If
   no semantic attribute exists, narrowly test the blue/green control state.
4. Return exactly one of `imessage`, `sms-rcs`, or `unresolved`; any timeout,
   conflicting signal, missing SMS relay, or permission failure is `unresolved`.
5. Close/discard the composer and confirm that no outgoing `chat.db` row was created.

Test the no-send resolver repeatedly against multiple controlled iMessage numbers,
multiple SMS-only numbers, a number with iMessage recently disabled, a malformed or
unreachable address, and SMS relay disabled. A pass requires zero bubbles/rows and a
stable result on every controlled case. The old `py-iMessage` source proves this
general UI technique was attempted before, but current macOS Accessibility nodes
must be discovered rather than copied from its obsolete indexes.

For an authorized send experiment, do **not** close the resolved composer or switch
back to a separately chosen AppleScript account. Enter the body in that same compose
session and activate Send once. Verify one outgoing row and one recipient-visible
submission. This minimizes the lookup-to-send race and preserves the core invariant:
one route decision owned by Messages, one Send action, one submission.

**Prototype B—headless research only: live private IDS.** The BlueBubbles implementation
is the strongest model: normalize to an IDS destination, force-refresh iMessage
status, require a tri-state result, choose one concrete service, and submit once.
Unknown, timeout, helper failure, or an unrecognized status must send nothing. Do not
copy the upstream `chat.db` heuristic and do not use a post-submit failure to select a
second transport.

This private path is unsupported, entitlement- and OS-version-sensitive, and the
reviewed projects require Messages injection plus weakened platform protections.
It should not be installed on the principal's production Mac merely for a prototype.
If UI resolution cannot be made deterministic and a headless lookup is still needed,
evaluate the IDS path only on an isolated disposable Mac after explicit approval of
the security tradeoff.
