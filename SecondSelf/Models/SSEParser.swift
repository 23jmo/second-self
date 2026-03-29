import Foundation

// MARK: - SSE Event

struct SSEEvent {
    let eventType: String
    let data: String
}

// MARK: - SSE Parser

/// Parses Server-Sent Events from chunked text data.
/// Handles the "event: type\ndata: json\n\n" format including
/// multi-line data fields.
final class SSEParser {
    private var buffer: String = ""

    /// Parse a chunk of incoming text and return any complete events.
    func parse(chunk: String) -> [SSEEvent] {
        buffer += chunk

        var events: [SSEEvent] = []

        // SSE events are separated by double newlines
        while let separatorRange = buffer.range(of: "\n\n") {
            let eventBlock = String(buffer[buffer.startIndex..<separatorRange.lowerBound])
            buffer = String(buffer[separatorRange.upperBound...])

            if let event = parseEventBlock(eventBlock) {
                events.append(event)
            }
        }

        return events
    }

    /// Reset the parser state (e.g., on reconnect).
    func reset() {
        buffer = ""
    }

    // MARK: - Private

    private func parseEventBlock(_ block: String) -> SSEEvent? {
        let lines = block.components(separatedBy: "\n")

        var eventType: String = "message" // Default SSE event type
        var dataLines: [String] = []

        for line in lines {
            if line.hasPrefix("event:") {
                eventType = line
                    .dropFirst("event:".count)
                    .trimmingCharacters(in: .whitespaces)
            } else if line.hasPrefix("data:") {
                let dataContent = line
                    .dropFirst("data:".count)
                    .trimmingCharacters(in: .init(charactersIn: " ")) // Only trim leading space, not all whitespace
                dataLines.append(String(dataContent))
            } else if line.hasPrefix(":") {
                // Comment line, ignore (often used for keepalive)
                continue
            }
            // Lines with no colon are ignored per SSE spec
        }

        guard !dataLines.isEmpty else { return nil }

        let data = dataLines.joined(separator: "\n")
        return SSEEvent(eventType: eventType, data: data)
    }
}
