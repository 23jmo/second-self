import Foundation

// MARK: - Proactive Suggestion

/// A suggestion pushed by the SuggestionEngine via the persistent /events SSE channel.
struct ProactiveSuggestion: Identifiable, Codable {
    let id: String                 // "sug_abc123"
    let title: String              // "Research competitor launches"
    let description: String        // Full description used as task prompt if accepted
    let source: SuggestionSource   // Where the suggestion came from
    let confidence: Double         // 0.0-1.0, server filters below 0.7
    let actionId: String           // Semantic label for RL reward grouping
    let context: [String: String]  // Extra context (company, industry, etc.)

    enum CodingKeys: String, CodingKey {
        case id, title, description, source, confidence
        case actionId = "action_id"
        case context
    }
}

// MARK: - Suggestion Source

enum SuggestionSource: String, Codable {
    case profile  // Based on Tavily profile data
    case pattern  // Based on conversation patterns
    case ambient  // Based on ambient desktop analysis

    var displayLabel: String {
        switch self {
        case .profile: return "Based on your profile"
        case .pattern: return "Based on our conversation"
        case .ambient:  return "I noticed something on my screen"
        }
    }
}
