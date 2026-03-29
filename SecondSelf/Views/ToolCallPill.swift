import SwiftUI

// MARK: - Tool Call Pill

/// Compact pill showing when the Twin invokes a tool.
/// Olive-green tinted background, monospace text with tool name + args.
struct ToolCallPill: View {
    let tool: String
    let args: [String: String]
    let result: String?

    @State private var isExpanded: Bool = false

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                // Tool header
                HStack(spacing: 6) {
                    Image(systemName: "wrench.and.screwdriver.fill")
                        .font(.system(size: 9))
                        .foregroundColor(twinGreen)

                    Text(tool)
                        .font(.system(size: 11, design: .monospaced))
                        .fontWeight(.medium)
                        .foregroundColor(twinGreen)

                    if !args.isEmpty {
                        Text(argsPreview)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(twinGreen.opacity(0.7))
                            .lineLimit(1)
                    }

                    if result != nil {
                        Spacer()

                        Button(action: { isExpanded.toggle() }) {
                            Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                                .font(.system(size: 8, weight: .bold))
                                .foregroundColor(twinGreen.opacity(0.6))
                        }
                        .buttonStyle(.plain)
                    }
                }

                // Expanded result
                if isExpanded, let result = result {
                    Text(result)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(Color(hex: 0xF5F5F7).opacity(0.8))
                        .lineLimit(8)
                        .padding(.top, 2)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(twinGreen.opacity(0.1))
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(twinGreen.opacity(0.4), lineWidth: 0.5)
                    )
            )

            Spacer()
        }
    }

    private var twinGreen: Color {
        Color(hex: 0xB5B055)
    }

    private var argsPreview: String {
        let pairs = args.map { "\($0.key): \($0.value)" }
        let joined = pairs.joined(separator: ", ")
        if joined.count > 40 {
            return String(joined.prefix(40)) + "..."
        }
        return joined
    }
}
