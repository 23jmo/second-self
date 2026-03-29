import SwiftUI

// MARK: - Confirm Action View

/// Simple approve/deny card for single destructive actions.
/// The twin asks permission before executing something impactful.
struct ConfirmActionView: View {
    let data: ConfirmActionData
    let onAllow: () -> Void
    let onDeny: () -> Void

    @State private var hasActed: Bool = false
    @State private var wasAllowed: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 10))
                    .foregroundColor(Color.ssTwinGreen)

                Text("The twin wants to:")
                    .font(.system(size: 11))
                    .foregroundColor(Color.ssTextSecondary)
            }

            // Action description
            Text(data.action)
                .font(.system(size: 13))
                .foregroundColor(Color.ssTextPrimary)
                .fixedSize(horizontal: false, vertical: true)

            if !hasActed {
                // Action buttons
                HStack(spacing: 10) {
                    Button(action: handleAllow) {
                        HStack(spacing: 4) {
                            Image(systemName: "checkmark")
                                .font(.system(size: 10, weight: .bold))
                            Text("Allow")
                                .font(.system(size: 11, weight: .semibold))
                        }
                        .foregroundColor(Color.ssBackground)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 6)
                        .background(
                            Capsule().fill(Color.ssTwinGreen)
                        )
                    }
                    .buttonStyle(.plain)

                    Button(action: handleDeny) {
                        HStack(spacing: 4) {
                            Image(systemName: "xmark")
                                .font(.system(size: 10, weight: .bold))
                            Text("Deny")
                                .font(.system(size: 11, weight: .medium))
                        }
                        .foregroundColor(Color.ssTextSecondary)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 6)
                        .background(
                            Capsule()
                                .stroke(Color.ssBorder, lineWidth: 0.5)
                        )
                    }
                    .buttonStyle(.plain)

                    Spacer()
                }
            } else {
                // Post-action status
                HStack(spacing: 6) {
                    Image(systemName: wasAllowed ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .font(.system(size: 11))
                        .foregroundColor(wasAllowed ? Color.ssSuccess : Color.ssError)
                    Text(wasAllowed ? "Allowed" : "Denied")
                        .font(.system(size: 11))
                        .foregroundColor(Color.ssTextSecondary)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.ssBorder, lineWidth: 0.5)
                )
        )
    }

    private func handleAllow() {
        hasActed = true
        wasAllowed = true
        onAllow()
    }

    private func handleDeny() {
        hasActed = true
        wasAllowed = false
        onDeny()
    }
}
