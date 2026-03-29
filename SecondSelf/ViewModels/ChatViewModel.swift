import Foundation
import Combine

// MARK: - Chat View Model

/// Main view model managing chat messages, Twin state, and SSE connection
/// to the orchestrator at http://localhost:8420/chat.
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var twinState: TwinState = .idle
    @Published var isConnected: Bool = false
    @Published var inputText: String = ""
    /// VNC feed stays visible once the agent starts working, until user dismisses.
    @Published var showVNCFeed: Bool = false

    // The last tool action name from SSE events, shown in VNC bottom bar
    @Published var currentToolAction: String = ""

    /// Tracks notch expansion: 0=compact, 1=status mini, 2=full chat
    @Published var expansionStage: Int = 0

    /// Callback for notch tap-to-expand. Set by NotchOverlayController.
    var onNotchTap: (() -> Void)?
    /// Callback for closing expanded notch. Set by NotchOverlayController.
    var onNotchClose: (() -> Void)?

    private let orchestratorURL = URL(string: ServerConfig.chatEndpoint)!
    private var sseTask: URLSessionDataTask?
    private var reconnectTimer: Timer?
    private var currentTwinMessageID: UUID?
    private(set) var streamingComponentID: UUID?
    private let audioManager = AudioManager()

    private lazy var urlSession: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 300 // 5 min for long SSE streams
        config.timeoutIntervalForResource = 600
        return URLSession(configuration: config, delegate: sseDelegate, delegateQueue: .main)
    }()

    private lazy var sseDelegate: SSESessionDelegate = {
        SSESessionDelegate(viewModel: self)
    }()

    init() {
        // Start with a welcome message from the Twin
        let welcome = ChatMessage(
            id: UUID(),
            sender: .twin,
            content: .text("hey, poke here. what do you need?"),
            timestamp: Date()
        )
        messages.append(welcome)
    }

    // MARK: - VNC Feed

    func dismissVNCFeed() {
        showVNCFeed = false
    }

    // MARK: - Send Message

    func sendMessage(text: String) {
        guard !text.isEmpty else { return }

        // Add user message
        let userMessage = ChatMessage(
            id: UUID(),
            sender: .user,
            content: .text(text),
            timestamp: Date()
        )
        messages.append(userMessage)
        inputText = ""

        // Update state
        twinState = .thinking
        audioManager.playTaskStart()

        // Create the SSE request
        var request = URLRequest(url: orchestratorURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")

        let payload: [String: Any] = ["message": text]
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)

        // Cancel any existing SSE task
        sseTask?.cancel()

        // Start SSE stream via delegate-based data task
        sseTask = urlSession.dataTask(with: request)
        sseTask?.resume()
    }

    // MARK: - SSE Event Handling

    func handleSSEEvent(eventType: String, data: String) {
        guard let event = SSEEventType(rawValue: eventType) else { return }

        switch event {
        case .state:
            // Data is JSON: {"state": "thinking"} or {"state": "complete", "message": "Done!"}
            if let jsonData = data.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
               let stateStr = json["state"] as? String,
               let newState = TwinState(rawValue: stateStr) {
                twinState = newState
                if newState == .working {
                    showVNCFeed = true
                }
                if newState == .complete || newState == .idle {
                    currentToolAction = ""
                }
                if newState == .complete {
                    audioManager.playCompletion()
                    currentTwinMessageID = nil
                }
            }

        case .token:
            // Data is JSON: {"text": "Hello"}
            if let jsonData = data.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
               let text = json["text"] as? String {
                appendTokenToCurrentTwinMessage(text)
            }

        case .toolCall:
            handleToolCall(data: data)

        case .toolResult:
            handleToolResult(data: data)

        case .error:
            twinState = .error
            // Data is JSON: {"message": "description"}
            var errorText = data
            if let jsonData = data.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
               let msg = json["message"] as? String {
                errorText = msg
            }
            let errorMessage = ChatMessage(
                id: UUID(),
                sender: .twin,
                content: .text("Something went wrong: \(errorText)"),
                timestamp: Date()
            )
            messages.append(errorMessage)
            currentTwinMessageID = nil

        case .component:
            handleComponent(data: data)

        case .componentStart, .componentDelta, .componentEnd:
            break // Reserved for future streaming component support

        case .ping:
            break
        }
    }

    // MARK: - Token Streaming

    private func appendTokenToCurrentTwinMessage(_ token: String) {
        if let existingID = currentTwinMessageID,
           let index = messages.firstIndex(where: { $0.id == existingID }) {
            // Append to existing message
            if case .text(let existingText) = messages[index].content {
                messages[index].content = .text(existingText + token)
            }
        } else {
            // Create a new Twin message
            let newMessage = ChatMessage(
                id: UUID(),
                sender: .twin,
                content: .text(token),
                timestamp: Date()
            )
            currentTwinMessageID = newMessage.id
            messages.append(newMessage)
        }

        // Subtle typing click every ~5th character
        audioManager.incrementTypingCounter()
    }

    // MARK: - Tool Call / Result

    private func handleToolCall(data: String) {
        // Finalize any in-progress twin message
        currentTwinMessageID = nil

        guard let jsonData = data.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
              let tool = json["tool"] as? String else {
            return
        }

        let argsRaw = json["args"] as? [String: Any] ?? [:]
        let argsStrings = argsRaw.mapValues { "\($0)" }

        // Update current tool action for VNC bottom bar display
        currentToolAction = tool.replacingOccurrences(of: "_", with: " ")
            .replacingOccurrences(of: "browser ", with: "")
            .capitalized + "..."

        let toolMessage = ChatMessage(
            id: UUID(),
            sender: .twin,
            content: .toolCall(tool: tool, args: argsStrings, result: nil),
            timestamp: Date()
        )
        messages.append(toolMessage)
    }

    private func handleToolResult(data: String) {
        guard let jsonData = data.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any] else {
            return
        }

        // Parse result as either a String or a JSON dict
        let displayResult: String
        if let stringResult = json["result"] as? String {
            displayResult = stringResult
        } else if let dictResult = json["result"] as? [String: Any] {
            // Try to extract a "status" field for a concise display string
            if let status = dictResult["status"] as? String {
                displayResult = status
            } else if let serialized = try? JSONSerialization.data(withJSONObject: dictResult, options: [.sortedKeys]),
                      let jsonString = String(data: serialized, encoding: .utf8) {
                displayResult = jsonString
            } else {
                displayResult = "\(dictResult)"
            }
        } else {
            return
        }

        // Update the most recent tool call message with its result
        if let lastToolIndex = messages.lastIndex(where: {
            if case .toolCall(_, _, nil) = $0.content { return true }
            return false
        }) {
            if case .toolCall(let tool, let args, _) = messages[lastToolIndex].content {
                messages[lastToolIndex].content = .toolCall(tool: tool, args: args, result: displayResult)
            }
        }
    }

    // MARK: - Component Handling

    private func handleComponent(data: String) {
        // Finalize any in-progress twin text message
        currentTwinMessageID = nil

        guard let jsonData = data.data(using: .utf8) else {
            print("[A2UI] Failed to convert data string to UTF-8")
            return
        }

        // Parse the A2UI payload from {"a2ui": {...}}
        if let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
           let a2uiDict = json["a2ui"] {
            // Re-serialize the a2ui sub-object and decode
            if let a2uiData = try? JSONSerialization.data(withJSONObject: a2uiDict) {
                do {
                    let payload = try JSONDecoder().decode(A2UIPayload.self, from: a2uiData)
                    print("[A2UI] Decoded payload: \(payload.components.count) components")
                    for comp in payload.components {
                        print("[A2UI]   Component: type=\(comp.type), props=\(comp.properties.keys.sorted())")
                    }
                    appendComponentMessage(payload: payload)
                    return
                } catch {
                    print("[A2UI] Decode error from a2ui sub-object: \(error)")
                }
            }
        }

        // Fallback: try parsing the entire data as A2UI directly
        do {
            let payload = try JSONDecoder().decode(A2UIPayload.self, from: jsonData)
            print("[A2UI] Decoded payload (direct): \(payload.components.count) components")
            appendComponentMessage(payload: payload)
        } catch {
            print("[A2UI] All decode attempts failed: \(error)")
            // Last resort: show as text
            let msg = ChatMessage(
                id: UUID(),
                sender: .twin,
                content: .text("[Component failed to render]"),
                timestamp: Date()
            )
            messages.append(msg)
        }
    }

    private func appendComponentMessage(payload: A2UIPayload) {
        let msg = ChatMessage(
            id: UUID(),
            sender: .twin,
            content: .component(payload),
            timestamp: Date()
        )
        messages.append(msg)
    }

    /// Send a component action as a chat message back to the orchestrator.
    func sendComponentAction(actionId: String, context: String) {
        sendMessage(text: context)
    }

    // MARK: - Connection Management

    func handleStreamComplete() {
        currentTwinMessageID = nil
        if twinState == .thinking || twinState == .working {
            twinState = .idle
        }
    }

    func handleStreamError(_ error: Error) {
        isConnected = false
        currentTwinMessageID = nil

        // Always reset twinState so the input field re-enables
        if twinState == .thinking || twinState == .working {
            twinState = .idle
        }

        // Don't show error for cancelled tasks (intentional disconnects)
        if (error as NSError).code == NSURLErrorCancelled { return }

        // Schedule reconnection attempt
        scheduleReconnect()
    }

    private func scheduleReconnect() {
        reconnectTimer?.invalidate()
        reconnectTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: false) { [weak self] _ in
            self?.isConnected = false
            // Will reconnect on next sendMessage call
        }
    }

    deinit {
        sseTask?.cancel()
        reconnectTimer?.invalidate()
    }
}

// MARK: - SSE URLSession Delegate

/// Custom delegate that receives streaming data and parses SSE events.
final class SSESessionDelegate: NSObject, URLSessionDataDelegate {
    private weak var viewModel: ChatViewModel?
    private let parser = SSEParser()

    init(viewModel: ChatViewModel) {
        self.viewModel = viewModel
        super.init()
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        guard let text = String(data: data, encoding: .utf8) else { return }

        let events = parser.parse(chunk: text)
        for event in events {
            viewModel?.handleSSEEvent(eventType: event.eventType, data: event.data)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            viewModel?.handleStreamError(error)
        } else {
            viewModel?.handleStreamComplete()
        }
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        // Accept the response and continue receiving data
        completionHandler(.allow)

        if let httpResponse = response as? HTTPURLResponse {
            DispatchQueue.main.async { [weak self] in
                self?.viewModel?.isConnected = (httpResponse.statusCode == 200)
            }
        }
    }
}
