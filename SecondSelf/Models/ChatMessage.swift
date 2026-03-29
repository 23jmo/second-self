import Foundation

// MARK: - Message Sender

enum MessageSender {
    case user
    case twin
}

// MARK: - Message Content

enum MessageContent {
    case text(String)
    case toolCall(tool: String, args: [String: String], result: String?, progress: String?)
    case component(A2UIPayload)
}

// MARK: - Chat Message

struct ChatMessage: Identifiable {
    let id: UUID
    let sender: MessageSender
    var content: MessageContent
    let timestamp: Date
}
