import SwiftUI

// MARK: - Suggestion Banner

/// Displays a proactive suggestion from the twin with Accept/Dismiss/Tell me more buttons.
/// Slides in from the top of the chat area. Shows source label.
struct SuggestionBanner: View {
    let suggestion: ProactiveSuggestion
    let onAccept: () -> Void
    let onDismiss: () -> Void
    let onTellMeMore: () -> Void

    @State private var isVisible = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Source label
            HStack(spacing: 4) {
                Image(systemName: sourceIcon)
                    .font(.system(size: 10))
                Text(suggestion.source.displayLabel)
                    .font(.system(size: 10, weight: .medium))
            }
            .foregroundColor(Color.ssTwinGreen)

            // Suggestion text
            Text(suggestion.title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(Color.ssTextPrimary)

            Text(suggestion.description)
                .font(.system(size: 11))
                .foregroundColor(Color.ssTextSecondary)
                .lineLimit(3)

            // Action buttons
            HStack(spacing: 8) {
                // Accept (primary)
                Button(action: onAccept) {
                    Text("Accept")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(.black)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 5)
                        .background(Color.ssTwinGreen)
                        .clipShape(Capsule())
                }
                .buttonStyle(.plain)

                // Dismiss (secondary)
                Button(action: onDismiss) {
                    Text("Dismiss")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Color.ssTextSecondary)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 5)
                        .background(
                            Capsule()
                                .stroke(Color.ssBorder, lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)

                // Tell me more (tertiary)
                Button(action: onTellMeMore) {
                    Text("Tell me more")
                        .font(.system(size: 11))
                        .foregroundColor(Color.ssTwinGreen)
                }
                .buttonStyle(.plain)

                Spacer()
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(Color.ssTwinGreen.opacity(0.3), lineWidth: 1)
                )
        )
        .shadow(color: Color.ssTwinGreen.opacity(0.1), radius: 8, y: 2)
        .padding(.horizontal, 12)
        .offset(y: isVisible ? 0 : -100)
        .opacity(isVisible ? 1 : 0)
        .onAppear {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) {
                isVisible = true
            }
        }
    }

    private var sourceIcon: String {
        switch suggestion.source {
        case .profile: return "person.crop.circle"
        case .pattern: return "arrow.triangle.2.circlepath"
        case .ambient: return "eye"
        }
    }
}
