import SwiftUI

// MARK: - Profile Card View

/// Contextual profiling card with fact confirmation.
/// As the AI learns about the user, it renders facts for confirmation.
struct ProfileCardView: View {
    let data: ProfileCardData
    let onConfirm: (String) -> Void
    let onDeny: (String) -> Void

    @State private var factStates: [FactState] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack(spacing: 6) {
                Image(systemName: "person.text.rectangle")
                    .font(.system(size: 11))
                    .foregroundColor(Color.ssTwinGreen)

                Text("I noticed...")
                    .font(.system(size: 12, weight: .medium))
                    .italic()
                    .foregroundColor(Color.ssTextPrimary)
            }
            .padding(.horizontal, 12)
            .padding(.top, 10)
            .padding(.bottom, 8)

            Divider()
                .background(Color.ssBorder)

            // Facts list
            VStack(alignment: .leading, spacing: 6) {
                ForEach(factStates.indices, id: \.self) { index in
                    factRow(at: index)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.ssBorder, lineWidth: 0.5)
                )
        )
        .onAppear { initializeFacts() }
    }

    // MARK: - Fact Row

    @ViewBuilder
    private func factRow(at index: Int) -> some View {
        let fact = factStates[index]

        HStack(spacing: 8) {
            Text("\"\(fact.text)\"")
                .font(.system(size: 12))
                .foregroundColor(fact.decision == .denied ? Color.ssTextSecondary : Color.ssTextPrimary)
                .strikethrough(fact.decision == .denied)
                .lineLimit(2)

            Spacer()

            if fact.decision == .pending {
                // Confirm/deny buttons
                HStack(spacing: 6) {
                    Button(action: { confirmFact(at: index) }) {
                        Image(systemName: "checkmark")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundColor(Color.ssSuccess)
                            .frame(width: 24, height: 24)
                            .background(
                                Circle()
                                    .fill(Color.ssSuccess.opacity(0.15))
                            )
                    }
                    .buttonStyle(.plain)

                    Button(action: { denyFact(at: index) }) {
                        Image(systemName: "xmark")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundColor(Color.ssError)
                            .frame(width: 24, height: 24)
                            .background(
                                Circle()
                                    .fill(Color.ssError.opacity(0.15))
                            )
                    }
                    .buttonStyle(.plain)
                }
            } else {
                // Status icon
                Image(systemName: fact.decision == .confirmed ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .font(.system(size: 14))
                    .foregroundColor(fact.decision == .confirmed ? Color.ssSuccess : Color.ssError)
            }
        }
    }

    // MARK: - State

    private func initializeFacts() {
        guard factStates.isEmpty else { return }
        factStates = data.facts.map { fact in
            let decision: FactDecision
            if let confirmed = fact.confirmed {
                decision = confirmed ? .confirmed : .denied
            } else {
                decision = .pending
            }
            return FactState(text: fact.text, decision: decision)
        }
    }

    private func confirmFact(at index: Int) {
        factStates[index].decision = .confirmed
        onConfirm(factStates[index].text)
    }

    private func denyFact(at index: Int) {
        factStates[index].decision = .denied
        onDeny(factStates[index].text)
    }
}

// MARK: - Fact State

enum FactDecision {
    case pending
    case confirmed
    case denied
}

struct FactState {
    let text: String
    var decision: FactDecision
}
