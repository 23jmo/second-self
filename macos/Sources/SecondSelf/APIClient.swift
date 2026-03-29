import Foundation

// MARK: - Request/Response Models

struct OnboardRequestBody: Codable {
    let name: String
    let email: String
    let context: String
    let session_id: String
}

struct OnboardResponseBody: Codable {
    let session_id: String
}

struct ChatRequestBody: Codable {
    let message: String
    let session_id: String
}

struct ChatResponseBody: Codable {
    let response: String
    let actions_taken: [ActionTaken]
}

struct ActionTaken: Codable {
    let tool: String
    let summary: String
}

struct LatestSessionResponse: Codable {
    let found: Bool
    let session_id: String?
    let name: String?
    let has_profile: Bool?
    let has_google_tokens: Bool?
}

// MARK: - API Client

@MainActor
final class APIClient {
    static let shared = APIClient()

    private let baseURL = "http://localhost:8000"
    private let session = URLSession.shared

    func onboard(name: String, email: String = "", context: String = "", sessionId: String = "") async throws -> String {
        let url = URL(string: "\(baseURL)/onboard")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60

        let body = OnboardRequestBody(name: name, email: email, context: context, session_id: sessionId)
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            let detail = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.serverError(statusCode: (response as? HTTPURLResponse)?.statusCode ?? 0, detail: detail)
        }

        let decoded = try JSONDecoder().decode(OnboardResponseBody.self, from: data)
        return decoded.session_id
    }

    func fetchLatestSession() async throws -> LatestSessionResponse {
        let url = URL(string: "\(baseURL)/session/latest")!
        var request = URLRequest(url: url)
        request.timeoutInterval = 10

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw APIError.invalidResponse
        }

        return try JSONDecoder().decode(LatestSessionResponse.self, from: data)
    }

    func sendChatMessage(_ message: String, sessionId: String) async throws -> ChatResponseBody {
        let url = URL(string: "\(baseURL)/chat")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60

        let body = ChatRequestBody(message: message, session_id: sessionId)
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            let detail = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.serverError(statusCode: (response as? HTTPURLResponse)?.statusCode ?? 0, detail: detail)
        }

        return try JSONDecoder().decode(ChatResponseBody.self, from: data)
    }
}

enum APIError: LocalizedError {
    case invalidResponse
    case serverError(statusCode: Int, detail: String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Invalid response from server"
        case .serverError(let code, let detail):
            return "Server error (\(code)): \(detail)"
        }
    }
}
