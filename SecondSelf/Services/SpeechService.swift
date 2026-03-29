import Foundation
import os

// MARK: - Whisper Speech-to-Text Service

/// Uses OpenAI Whisper API for transcription. Reads OPENAI_API_KEY from .env.
final class SpeechService {

    enum STTError: LocalizedError {
        case noAPIKey
        case networkError(Error)
        case authError
        case emptyTranscription
        case timeout
        case serverError(Int, String)

        var errorDescription: String? {
            switch self {
            case .noAPIKey: return "No OpenAI API key configured"
            case .networkError(let e): return "Network error: \(e.localizedDescription)"
            case .authError: return "Invalid API key"
            case .emptyTranscription: return "Nothing heard"
            case .timeout: return "Transcription timed out"
            case .serverError(let code, let msg): return "Server error \(code): \(msg)"
            }
        }
    }

    private static let endpoint = URL(string: "https://api.openai.com/v1/audio/transcriptions")!
    private let logger = Logger(subsystem: "com.secondself.app", category: "Whisper")

    var hasAPIKey: Bool {
        apiKey != nil
    }

    private var apiKey: String? {
        let key = AppDelegate.sharedEnvVars["OPENAI_API_KEY"]
        guard let key, !key.isEmpty else { return nil }
        return key
    }

    func transcribe(fileURL: URL) async throws -> String {
        guard let apiKey else {
            throw STTError.noAPIKey
        }

        let audioData: Data
        do {
            audioData = try Data(contentsOf: fileURL)
        } catch {
            throw STTError.networkError(error)
        }

        logger.info("Transcribing \(audioData.count) bytes with Whisper")

        let boundary = UUID().uuidString
        var body = Data()

        // model field
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"model\"\r\n\r\n".data(using: .utf8)!)
        body.append("whisper-1\r\n".data(using: .utf8)!)

        // language field
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"language\"\r\n\r\n".data(using: .utf8)!)
        body.append("en\r\n".data(using: .utf8)!)

        // file field
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"recording.wav\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n".data(using: .utf8)!)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        var request = URLRequest(url: Self.endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 30

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let error as URLError where error.code == .timedOut {
            throw STTError.timeout
        } catch {
            throw STTError.networkError(error)
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw STTError.networkError(URLError(.badServerResponse))
        }

        switch httpResponse.statusCode {
        case 200: break
        case 401:
            logger.error("Auth failed (401)")
            throw STTError.authError
        default:
            let body = String(data: data, encoding: .utf8) ?? "Unknown error"
            logger.error("Whisper failed \(httpResponse.statusCode): \(body)")
            throw STTError.serverError(httpResponse.statusCode, body)
        }

        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let text = json["text"] as? String,
              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw STTError.emptyTranscription
        }

        logger.info("Whisper transcription: \(text.prefix(50))...")
        return text
    }
}
