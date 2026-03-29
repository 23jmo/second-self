import Foundation

// MARK: - Multipart Form Data Builder

/// Builds multipart/form-data request bodies for URLSession uploads.
/// Swift has no built-in multipart support, so we construct the boundary-delimited
/// body manually. Used by ElevenLabsService for audio file uploads.
struct MultipartFormData {
    private let boundary: String
    private var body = Data()

    /// The Content-Type header value including the boundary.
    var contentType: String {
        "multipart/form-data; boundary=\(boundary)"
    }

    /// The assembled body data ready for URLRequest.httpBody.
    var data: Data { body }

    init(boundary: String = UUID().uuidString) {
        self.boundary = boundary
    }

    /// Add a text field.
    mutating func addField(name: String, value: String) {
        body.append("--\(boundary)\r\n")
        body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n")
        body.append("\r\n")
        body.append("\(value)\r\n")
    }

    /// Add a file field with binary data.
    mutating func addFile(name: String, fileName: String, mimeType: String, data fileData: Data) {
        body.append("--\(boundary)\r\n")
        body.append("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(fileName)\"\r\n")
        body.append("Content-Type: \(mimeType)\r\n")
        body.append("\r\n")
        body.append(fileData)
        body.append("\r\n")
    }

    /// Finalize the body with the closing boundary. Call this after adding all fields.
    mutating func finalize() {
        body.append("--\(boundary)--\r\n")
    }
}

// MARK: - Data Extension for String Appending

private extension Data {
    mutating func append(_ string: String) {
        if let data = string.data(using: .utf8) {
            append(data)
        }
    }
}
