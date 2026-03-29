import SwiftUI

// MARK: - Tool Call Pill

/// Compact cream-colored pill showing tool invocations.
/// Matches Figma node 90:117.
struct ToolCallPill: View {
    let tool: String
    let args: [String: String]
    let result: String?

    @State private var isExpanded: Bool = false

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(toolLabel)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Color.ssUserOlive)
                        .lineLimit(1)

                    if result != nil {
                        Spacer()
                        Button(action: { withAnimation(.ssMicro) { isExpanded.toggle() } }) {
                            Image(systemName: "chevron.down")
                                .font(.system(size: 8, weight: .bold))
                                .foregroundColor(Color.ssUserOlive.opacity(0.6))
                                .rotationEffect(.degrees(isExpanded ? 180 : 0))
                                .animation(.ssMicro, value: isExpanded)
                        }
                        .buttonStyle(.plain)
                    }
                }

                if isExpanded, let result = result {
                    Text(result)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(Color.ssUserOlive.opacity(0.8))
                        .lineLimit(8)
                        .padding(.top, 2)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 15)
                    .fill(Color.ssCream)
                    .overlay(
                        RoundedRectangle(cornerRadius: 15)
                            .stroke(Color.ssToolBorder, lineWidth: 1)
                    )
            )

            Spacer()
        }
    }

    private var toolLabel: String {
        if args.isEmpty { return tool }
        let firstArg = args.first.map { "\($0.value)" } ?? ""
        return "\(tool) \(firstArg)".prefix(50).description
    }
}
