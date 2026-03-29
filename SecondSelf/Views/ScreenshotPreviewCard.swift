import SwiftUI
import AppKit

// MARK: - Screenshot Preview Card

/// Inline screenshot from the agent's browser, rendered as a card
/// with olive-green glow border matching VNCPipView styling.
struct ScreenshotPreviewCard: View {
    let data: ScreenshotData

    @State private var decodedImage: NSImage?
    @State private var decodeFailed: Bool = false

    private static let maxBase64Length = 15_000_000  // ~10 MB decoded
    private static let maxDecodedBytes = 10_485_760  // 10 MB

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let nsImage = decodedImage {
                Image(nsImage: nsImage)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(maxHeight: 200)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.ssTwinGreen.opacity(0.6), lineWidth: 1)
                    )
                    .shadow(color: Color.ssTwinGreen.opacity(0.2), radius: 6, x: 0, y: 0)
            } else if decodeFailed {
                // Broken image fallback
                HStack {
                    Image(systemName: "photo.badge.exclamationmark")
                        .font(.system(size: 20))
                        .foregroundColor(Color.ssTextSecondary)
                    Text("Image unavailable")
                        .font(.system(size: 11))
                        .foregroundColor(Color.ssTextSecondary)
                }
                .frame(maxWidth: .infinity, minHeight: 60)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.ssBackground)
                )
            } else {
                // Loading placeholder
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.ssBackground)
                    .frame(maxWidth: .infinity, minHeight: 60, maxHeight: 100)
                    .overlay(
                        ProgressView()
                            .controlSize(.small)
                    )
            }

            // Caption
            if let caption = data.caption {
                Text(caption)
                    .font(.system(size: 11))
                    .italic()
                    .foregroundColor(Color.ssTextSecondary)
                    .lineLimit(2)
            }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.ssBorder, lineWidth: 0.5)
                )
        )
        .task {
            await decodeImageAsync()
        }
    }

    // MARK: - Image Decoding (off main thread)

    private func decodeImageAsync() async {
        let base64 = data.imageBase64
        let result: NSImage? = await Task.detached(priority: .userInitiated) {
            guard base64.count < ScreenshotPreviewCard.maxBase64Length,
                  let bytes = Data(base64Encoded: base64),
                  bytes.count < ScreenshotPreviewCard.maxDecodedBytes else {
                return nil
            }
            return NSImage(data: bytes)
        }.value

        if let image = result {
            decodedImage = image
        } else {
            decodeFailed = true
        }
    }
}
