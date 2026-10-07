// PROTOTYPE — throwaway no-send probe.
//
// Question: can Messages expose a stable pre-send route for one raw phone number
// before any message body exists, with ambiguity causing an empty-composer abort?

import AppKit
import ApplicationServices
import Foundation

private let bold = "\u{001B}[1m"
private let dim = "\u{001B}[2m"
private let reset = "\u{001B}[0m"

enum Route: String {
    case iMessage = "iMessage"
    case textMessage = "SMS/RCS"
}

enum Phase: String {
    case idle
    case openingComposer = "opening-composer"
    case recipientEntered = "recipient-entered"
    case resolving
    case resolved
    case ambiguous
    case aborted
    case failed
}

struct ProbeState {
    var phase: Phase = .idle
    var run = 0
    var recipientLabel = "not entered"
    var bodyEmpty = true
    var committedRecipient = false
    var placeholder = "not observed"
    var stableSamples = 0
    var route: Route?
    var detail = "Ready."
    var completedRuns = 0
    var matchingRuns = 0
    var expectedRoute: Route?
}

enum ProbeAction {
    case start(run: Int, recipientLabel: String)
    case composerOpened
    case recipientEntered
    case sample(placeholder: String?, committed: Bool, stableSamples: Int)
    case resolved(Route)
    case ambiguous(String)
    case discarded
    case failed(String)
}

// Pure state transition logic. The Accessibility driver below owns all I/O.
func reduce(_ state: ProbeState, _ action: ProbeAction) -> ProbeState {
    var next = state
    switch action {
    case let .start(run, recipientLabel):
        next.phase = .openingComposer
        next.run = run
        next.recipientLabel = recipientLabel
        next.bodyEmpty = true
        next.committedRecipient = false
        next.placeholder = "not observed"
        next.stableSamples = 0
        next.route = nil
        next.detail = "Opening a body-free composer."
    case .composerOpened:
        next.phase = .recipientEntered
        next.detail = "Empty composer opened; only the To: field may be changed."
    case .recipientEntered:
        next.phase = .resolving
        next.detail = "Recipient entered; waiting for a stable native route."
    case let .sample(placeholder, committed, stableSamples):
        next.phase = .resolving
        next.placeholder = placeholder ?? "absent"
        next.committedRecipient = committed
        next.stableSamples = stableSamples
        next.detail = "Sampling the body placeholder; no body exists."
    case let .resolved(route):
        next.phase = .resolved
        next.route = route
        next.detail = "Stable route resolved; the empty composer will now be discarded."
    case let .ambiguous(reason):
        next.phase = .ambiguous
        next.detail = reason
    case .discarded:
        next.phase = .aborted
        next.completedRuns += 1
        if let route = next.route {
            if next.expectedRoute == nil {
                next.expectedRoute = route
            }
            if next.expectedRoute == route {
                next.matchingRuns += 1
            }
        }
        next.detail = "Empty composer discarded. No message body and no send occurred."
    case let .failed(message):
        next.phase = .failed
        next.detail = message
    }
    return next
}

func classify(placeholder: String?) -> Route? {
    guard let value = placeholder?.trimmingCharacters(in: .whitespacesAndNewlines) else {
        return nil
    }
    if value == "iMessage" {
        return .iMessage
    }
    if value.hasPrefix("Text Message") &&
        (value.contains("SMS") || value.contains("RCS") || value == "Text Message") {
        return .textMessage
    }
    return nil
}

func render(_ state: ProbeState) {
    print("\u{001B}[2J\u{001B}[H", terminator: "")
    print("\(bold)PROTOTYPE — Messages route preflight\(reset)")
    print("\(dim)No body. No Return/Enter. No send action. Empty composer is discarded.\(reset)\n")
    print("\(bold)phase\(reset): \(state.phase.rawValue)")
    print("\(bold)run\(reset): \(state.run)")
    print("\(bold)recipient\(reset): \(state.recipientLabel)")
    print("\(bold)body_empty\(reset): \(state.bodyEmpty)")
    print("\(bold)recipient_committed\(reset): \(state.committedRecipient)")
    print("\(bold)placeholder\(reset): \(state.placeholder)")
    print("\(bold)stable_samples\(reset): \(state.stableSamples)/4")
    print("\(bold)route\(reset): \(state.route?.rawValue ?? "unresolved")")
    print("\(bold)completed_runs\(reset): \(state.completedRuns)")
    print("\(bold)same_route_runs\(reset): \(state.matchingRuns)/\(state.completedRuns)")
    print("\(bold)detail\(reset): \(state.detail)\n")
    print("\(bold)[r]\(reset) \(dim)run once\(reset)  \(bold)[5]\(reset) \(dim)run five times\(reset)  \(bold)[q]\(reset) \(dim)quit\(reset)")
}

enum ProbeError: Error, CustomStringConvertible {
    case message(String)

    var description: String {
        switch self {
        case let .message(value): return value
        }
    }
}

func attribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else {
        return nil
    }
    return value
}

func stringAttribute(_ element: AXUIElement, _ name: String) -> String? {
    attribute(element, name) as? String
}

func children(_ element: AXUIElement) -> [AXUIElement] {
    attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
}

func descendants(_ root: AXUIElement) -> [AXUIElement] {
    var result: [AXUIElement] = []
    var stack = children(root)
    while let element = stack.popLast() {
        result.append(element)
        stack.append(contentsOf: children(element))
    }
    return result
}

func elementAttribute(_ element: AXUIElement, _ name: String) -> AXUIElement? {
    attribute(element, name) as! AXUIElement?
}

func setAttribute(_ element: AXUIElement, _ name: String, _ value: CFTypeRef) throws {
    let error = AXUIElementSetAttributeValue(element, name as CFString, value)
    guard error == .success else {
        throw ProbeError.message("Accessibility set \(name) failed with code \(error.rawValue).")
    }
}

func perform(_ element: AXUIElement, _ action: String) throws {
    let error = AXUIElementPerformAction(element, action as CFString)
    guard error == .success else {
        throw ProbeError.message("Accessibility action \(action) failed with code \(error.rawValue).")
    }
}

func postTextWithoutReturn(_ text: String, to processIdentifier: pid_t) throws {
    let allowed = CharacterSet(charactersIn: "+0123456789()- .")
    guard text.unicodeScalars.allSatisfy(allowed.contains),
          !text.contains("\n"),
          !text.contains("\r")
    else {
        throw ProbeError.message("Recipient contains characters the no-send typer refuses.")
    }
    let characters = Array(text.utf16)
    guard let down = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true),
          let up = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false)
    else {
        throw ProbeError.message("Could not create safe recipient keyboard events.")
    }
    characters.withUnsafeBufferPointer { buffer in
        down.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress!)
        up.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress!)
    }
    down.postToPid(processIdentifier)
    up.postToPid(processIdentifier)
}

func pressEscape(to processIdentifier: pid_t) throws {
    let escapeKey: CGKeyCode = 53
    guard let down = CGEvent(keyboardEventSource: nil, virtualKey: escapeKey, keyDown: true),
          let up = CGEvent(keyboardEventSource: nil, virtualKey: escapeKey, keyDown: false)
    else {
        throw ProbeError.message("Could not create the empty-composer Escape action.")
    }
    down.postToPid(processIdentifier)
    up.postToPid(processIdentifier)
}

func pressTab(to processIdentifier: pid_t) throws {
    let tabKey: CGKeyCode = 48
    guard let down = CGEvent(keyboardEventSource: nil, virtualKey: tabKey, keyDown: true),
          let up = CGEvent(keyboardEventSource: nil, virtualKey: tabKey, keyDown: false)
    else {
        throw ProbeError.message("Could not create the recipient-commit Tab action.")
    }
    down.postToPid(processIdentifier)
    up.postToPid(processIdentifier)
}

func clickCenter(_ element: AXUIElement) throws {
    guard let rawPosition = attribute(element, kAXPositionAttribute),
          let rawSize = attribute(element, kAXSizeAttribute),
          CFGetTypeID(rawPosition) == AXValueGetTypeID(),
          CFGetTypeID(rawSize) == AXValueGetTypeID()
    else {
        throw ProbeError.message("Accessibility geometry was unavailable for the compose button.")
    }
    let positionValue = unsafeBitCast(rawPosition, to: AXValue.self)
    let sizeValue = unsafeBitCast(rawSize, to: AXValue.self)
    var position = CGPoint.zero
    var size = CGSize.zero
    guard AXValueGetValue(positionValue, .cgPoint, &position),
          AXValueGetValue(sizeValue, .cgSize, &size)
    else {
        throw ProbeError.message("Accessibility geometry could not be decoded.")
    }
    let center = CGPoint(x: position.x + size.width / 2, y: position.y + size.height / 2)
    guard let down = CGEvent(
              mouseEventSource: nil,
              mouseType: .leftMouseDown,
              mouseCursorPosition: center,
              mouseButton: .left
          ),
          let up = CGEvent(
              mouseEventSource: nil,
              mouseType: .leftMouseUp,
              mouseCursorPosition: center,
              mouseButton: .left
          )
    else {
        throw ProbeError.message("Could not create the compose-button click.")
    }
    down.post(tap: .cghidEventTap)
    up.post(tap: .cghidEventTap)
}

func waitUntil(timeout: TimeInterval, poll: TimeInterval = 0.1, _ condition: () -> Bool) -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if condition() { return true }
        Thread.sleep(forTimeInterval: poll)
    }
    return condition()
}

func normalizedDigits(_ value: String) -> String {
    String(value.filter(\.isNumber))
}

func redactedRecipient(_ recipient: String) -> String {
    let digits = normalizedDigits(recipient)
    return digits.count >= 4 ? "••••\(digits.suffix(4))" : "redacted"
}

final class MessagesProbeDriver {
    private let application: NSRunningApplication
    private let applicationElement: AXUIElement
    private let stableSampleTarget = 4
    private let sampleInterval: TimeInterval = 0.25
    private let resolutionTimeout: TimeInterval = 8

    init() throws {
        guard AXIsProcessTrusted() else {
            throw ProbeError.message("Accessibility permission is required for this terminal host.")
        }
        guard let running = NSRunningApplication.runningApplications(
            withBundleIdentifier: "com.apple.MobileSMS"
        ).first else {
            throw ProbeError.message("Open Messages, then run the prototype again.")
        }
        application = running
        applicationElement = AXUIElementCreateApplication(running.processIdentifier)
    }

    private func mainWindow() -> AXUIElement? {
        elementAttribute(applicationElement, kAXMainWindowAttribute)
    }

    private func isFrontmost() -> Bool {
        (attribute(applicationElement, kAXFrontmostAttribute) as? Bool) == true
    }

    private func find(
        in root: AXUIElement,
        role: String? = nil,
        identifier: String? = nil,
        description: String? = nil
    ) -> AXUIElement? {
        ([root] + descendants(root)).first { element in
            if let role, stringAttribute(element, kAXRoleAttribute) != role { return false }
            if let identifier, stringAttribute(element, kAXIdentifierAttribute) != identifier { return false }
            if let description, stringAttribute(element, kAXDescriptionAttribute) != description { return false }
            return true
        }
    }

    private func currentComposer() -> (window: AXUIElement, to: AXUIElement, body: AXUIElement)? {
        guard let window = mainWindow(),
              let to = find(in: window, role: kAXTextFieldRole, description: "To:"),
              let body = find(in: window, role: kAXTextFieldRole, identifier: "messageBodyField")
        else {
            return nil
        }
        return (window, to, body)
    }

    private func bodyIsEmpty(_ body: AXUIElement) -> Bool {
        (stringAttribute(body, kAXValueAttribute) ?? "").isEmpty
    }

    private func isFocused(_ element: AXUIElement) -> Bool {
        guard let focused = elementAttribute(applicationElement, kAXFocusedUIElementAttribute) else {
            return false
        }
        return CFEqual(focused, element)
    }

    private func recipientIsCommitted(in window: AXUIElement, recipient: String) -> Bool {
        let expected = normalizedDigits(recipient)
        return descendants(window).contains { element in
            guard stringAttribute(element, kAXRoleAttribute) == kAXPopUpButtonRole else {
                return false
            }
            let description = stringAttribute(element, kAXDescriptionAttribute) ?? ""
            return normalizedDigits(description).contains(expected)
        }
    }

    private func discardEmptyComposer() throws {
        guard let composer = currentComposer() else { return }
        guard bodyIsEmpty(composer.body) else {
            throw ProbeError.message("Safety stop: composer body became non-empty; it was not discarded.")
        }
        try setAttribute(composer.to, kAXFocusedAttribute, kCFBooleanTrue)
        guard waitUntil(timeout: 1, { self.isFocused(composer.to) }) else {
            throw ProbeError.message("Safety stop: could not focus To: before aborting the empty composer.")
        }
        try pressEscape(to: application.processIdentifier)
        guard waitUntil(timeout: 2, { self.currentComposer() == nil }) else {
            throw ProbeError.message("Safety stop: empty composer did not disappear after discard.")
        }
    }

    func run(recipient: String, emit: (ProbeAction) -> Void) throws {
        _ = application.activate(options: [.activateAllWindows])
        try setAttribute(applicationElement, kAXFrontmostAttribute, kCFBooleanTrue)
        guard waitUntil(timeout: 2, { self.isFrontmost() }) else {
            throw ProbeError.message("Safety stop: Messages did not become the frontmost app.")
        }
        guard currentComposer() == nil else {
            throw ProbeError.message("Safety stop: an unfinished New Message composer already exists.")
        }
        guard let initialWindow = mainWindow(),
              let compose = find(in: initialWindow, role: kAXButtonRole, identifier: "composeButton")
        else {
            throw ProbeError.message("Messages compose button is unavailable.")
        }

        try clickCenter(compose)
        guard waitUntil(timeout: 5, { self.currentComposer() != nil }),
              let opened = currentComposer()
        else {
            throw ProbeError.message("New empty composer did not appear.")
        }
        guard bodyIsEmpty(opened.body) else {
            throw ProbeError.message("Safety stop: new composer body was not empty.")
        }
        emit(.composerOpened)

        try perform(opened.to, kAXPressAction)
        try setAttribute(opened.to, kAXFocusedAttribute, kCFBooleanTrue)
        guard waitUntil(timeout: 1, { self.isFocused(opened.to) }) else {
            try? discardEmptyComposer()
            throw ProbeError.message("Safety stop: To: field could not be focused.")
        }
        try postTextWithoutReturn(recipient, to: application.processIdentifier)
        guard waitUntil(timeout: 1, {
            guard let value = self.currentComposer().flatMap({ stringAttribute($0.to, kAXValueAttribute) }) else {
                return false
            }
            return normalizedDigits(value).contains(normalizedDigits(recipient))
        }) else {
            try? discardEmptyComposer()
            throw ProbeError.message("Recipient did not appear in the To: field.")
        }
        emit(.recipientEntered)

        guard let beforeCommit = currentComposer(), bodyIsEmpty(beforeCommit.body) else {
            try? discardEmptyComposer()
            throw ProbeError.message("Safety stop: body was not empty before recipient commit.")
        }
        try pressTab(to: application.processIdentifier)

        let deadline = Date().addingTimeInterval(resolutionTimeout)
        var lastRoute: Route?
        var stableSamples = 0
        var resolvedRoute: Route?

        while Date() < deadline {
            guard let sample = currentComposer() else {
                throw ProbeError.message("Safety stop: composer exited during route resolution.")
            }
            guard bodyIsEmpty(sample.body) else {
                try? discardEmptyComposer()
                throw ProbeError.message("Safety stop: body changed during route resolution.")
            }
            let placeholder = stringAttribute(sample.body, kAXPlaceholderValueAttribute)
            let committed = recipientIsCommitted(in: sample.window, recipient: recipient)
            let route = committed ? classify(placeholder: placeholder) : nil
            if route != nil && route == lastRoute {
                stableSamples += 1
            } else {
                stableSamples = route == nil ? 0 : 1
                lastRoute = route
            }
            emit(.sample(placeholder: placeholder, committed: committed, stableSamples: stableSamples))
            if let route, stableSamples >= stableSampleTarget {
                resolvedRoute = route
                break
            }
            Thread.sleep(forTimeInterval: sampleInterval)
        }

        if let resolvedRoute {
            emit(.resolved(resolvedRoute))
        } else {
            emit(.ambiguous("No recognized route stayed stable for four samples; aborting."))
        }
        try discardEmptyComposer()
        emit(.discarded)
    }
}

print("Recipient phone number (held in memory only): ", terminator: "")
guard let recipientInput = readLine()?.trimmingCharacters(in: .whitespacesAndNewlines),
      !recipientInput.isEmpty,
      (10...15).contains(normalizedDigits(recipientInput).count)
else {
    fatalError("A phone number with 10 to 15 digits is required.")
}

var state = ProbeState(recipientLabel: redactedRecipient(recipientInput))
render(state)

while let command = readLine()?.lowercased() {
    if command == "q" { break }
    let requestedRuns: Int
    if command == "r" {
        requestedRuns = 1
    } else if command == "5" {
        requestedRuns = 5
    } else {
        render(state)
        continue
    }

    do {
        let driver = try MessagesProbeDriver()
        for _ in 0..<requestedRuns {
            let runNumber = state.completedRuns + 1
            state = reduce(state, .start(run: runNumber, recipientLabel: redactedRecipient(recipientInput)))
            render(state)
            try driver.run(recipient: recipientInput) { action in
                state = reduce(state, action)
                render(state)
            }
        }
    } catch {
        state = reduce(state, .failed(String(describing: error)))
        render(state)
    }
}
