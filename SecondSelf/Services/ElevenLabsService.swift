import Foundation
import os

// MARK: - ElevenLabs Service

/// Client for ElevenLabs APIs. Currently STT only, structured for future TTS expansion.
/// Reads ELEVENLABS_API_KEY from the app's .env vars (exposed via AppDelegate.sharedEnvVars).
final class ElevenLabsService {

    enum STTError: LocalizedError {
        case noAPIKey
        case networkError(Error)
        case authError
        case emptyTranscription
        case timeout
        case serverError(Int, String)

        var errorDescription: String? {
            switch self {
            case .noAPIKey: return "No ElevenLabs API key configured"
            case .networkError(let e): return "Network error: \(e.localizedDescription)"
            case .authError: return "Invalid API key"
            case .emptyTranscription: return "Nothing heard"
            case .timeout: return "Transcription timed out"
            case .serverError(let code, let msg): return "Server error \(code): \(msg)"
            }
        }
    }

    private static let sttEndpoint = URL(string: "https://api.elevenlabs.io/v1/speech-to-text")!
    private static let model = "scribe_v1"
    private static let timeoutSeconds: TimeInterval = 30

    private let logger = Logger(subsystem: "com.secondself.app", category: "ElevenLabs")

    /// Whether an API key is available in .env.
    var hasAPIKey: Bool {
        apiKey != nil
    }

    private var apiKey: String? {
        let key = AppDelegate.sharedEnvVars["ELEVENLABS_API_KEY"]
        guard let key, !key.isEmpty else { return nil }
        return key
    }

    // MARK: - Speech to Text

    /// Transcribe an audio file using ElevenLabs Scribe.
    /// - Parameter fileURL: Path to a WAV audio file (16kHz mono PCM).
    /// - Returns: The transcribed text.
    /// - Throws: `STTError` on failure.
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

        logger.info("Transcribing \(audioData.count) bytes from \(fileURL.lastPathComponent)")

        // Build multipart form body
        var form = MultipartFormData()
        form.addField(name: "model_id", value: Self.model)
        form.addField(name: "language_code", value: "en")
        form.addFile(name: "file", fileName: "recording.wav", mimeType: "audio/wav", data: audioData)
        form.finalize()

        // Build request
        var request = URLRequest(url: Self.sttEndpoint)
        request.httpMethod = "POST"
        request.setValue(form.contentType, forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "xi-api-key")
        request.httpBody = form.data
        request.timeoutInterval = Self.timeoutSeconds

        // Send
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let error as URLError where error.code == .timedOut {
            logger.error("Request timed out")
            throw STTError.timeout
        } catch {
            logger.error("Network error: \(error.localizedDescription)")
            throw STTError.networkError(error)
        }

        // Parse response
        guard let httpResponse = response as? HTTPURLResponse else {
            throw STTError.networkError(URLError(.badServerResponse))
        }

        switch httpResponse.statusCode {
        case 200:
            break
        case 401:
            logger.error("Auth failed (401)")
            throw STTError.authError
        default:
            let body = String(data: data, encoding: .utf8) ?? "Unknown error"
            logger.error("STT failed \(httpResponse.statusCode): \(body)")
            throw STTError.serverError(httpResponse.statusCode, body)
        }

        // Extract text from response JSON
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let text = json["text"] as? String else {
            logger.error("Could not parse 'text' from response")
            throw STTError.emptyTranscription
        }

        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            throw STTError.emptyTranscription
        }

        logger.info("Transcription: \(trimmed.prefix(80))...")
        return trimmed
    }
}
