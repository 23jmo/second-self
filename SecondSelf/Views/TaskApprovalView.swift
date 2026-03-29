import SwiftUI

// MARK: - Task Approval View

/// Interactive task plan with drag-to-reorder and approve/reject actions.
/// The user can reorder steps before approving. Reordering is disabled
/// while streaming is active to prevent race conditions.
struct TaskApprovalView: View {
    let data: TaskApprovalData
    let isStreaming: Bool
    let onApprove: ([(id: Int, text: String)]) -> Void
    let onReject: () -> Void

    @State private var steps: [StepItem] = []
    @State private var hasActed: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack {
                Image(systemName: "list.bullet.clipboard")
                    .font(.system(size: 11))
                    .foregroundColor(Color.ssTwinGreen)

                Text(data.title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(Color.ssTextPrimary)

                Spacer()

                if isStreaming {
                    StreamingDots()
                }
            }
            .padding(.horizontal, 12)
            .padding(.top, 10)
            .padding(.bottom, 8)

            Divider()
                .background(Color.ssBorder)

            // Steps list
            List {
                ForEach(steps) { step in
                    HStack(spacing: 8) {
                        if !isStreaming && !hasActed {
                            Image(systemName: "line.3.horizontal")
                                .font(.system(size: 10))
                                .foregroundColor(Color.ssTextSecondary.opacity(0.5))
                        }

                        Text("\(step.displayIndex).")
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundColor(Color.ssTextSecondary)
                            .frame(width: 20, alignment: .trailing)

                        Text(step.text)
                            .font(.system(size: 12))
                            .foregroundColor(Color.ssTextPrimary)
                    }
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: 3, leading: 12, bottom: 3, trailing: 12))
                }
                .onMove(perform: isStreaming || hasActed ? nil : moveSteps)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .frame(height: CGFloat(min(steps.count, 8)) * 28 + 4)

            // Action buttons
            if !hasActed {
                Divider()
                    .background(Color.ssBorder)

                HStack(spacing: 10) {
                    Button(action: handleApprove) {
                        HStack(spacing: 4) {
                            Image(systemName: "checkmark")
                                .font(.system(size: 10, weight: .bold))
                            Text("Approve")
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
                    .disabled(isStreaming)
                    .opacity(isStreaming ? 0.5 : 1.0)

                    Button(action: handleReject) {
                        HStack(spacing: 4) {
                            Image(systemName: "xmark")
                                .font(.system(size: 10, weight: .bold))
                            Text("Reject")
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
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
            } else {
                // Post-action confirmation
                HStack(spacing: 6) {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 11))
                        .foregroundColor(Color.ssSuccess)
                    Text("Plan approved")
                        .font(.system(size: 11))
                        .foregroundColor(Color.ssTextSecondary)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.ssBorder, lineWidth: 0.5)
                )
        )
        .onAppear { initializeSteps() }
    }

    // MARK: - Actions

    private func initializeSteps() {
        guard steps.isEmpty else { return }
        steps = data.steps.enumerated().map { index, step in
            StepItem(originalId: step.id, text: step.text, displayIndex: index + 1)
        }
    }

    private func moveSteps(from source: IndexSet, to destination: Int) {
        steps.move(fromOffsets: source, toOffset: destination)
        // Re-number after reorder
        for i in steps.indices {
            steps[i].displayIndex = i + 1
        }
    }

    private func handleApprove() {
        hasActed = true
        let reordered = steps.map { (id: $0.originalId, text: $0.text) }
        onApprove(reordered)
    }

    private func handleReject() {
        hasActed = true
        onReject()
    }
}

// MARK: - Step Item

struct StepItem: Identifiable {
    let id = UUID()
    let originalId: Int
    let text: String
    var displayIndex: Int
}

// MARK: - Streaming Dots

/// Small animated dots indicating the component is still receiving data.
struct StreamingDots: View {
    @State private var dotCount: Int = 1
    private let timer = Timer.publish(every: 0.4, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .fill(Color.ssTwinGreen)
                    .frame(width: 4, height: 4)
                    .opacity(index < dotCount ? 0.8 : 0.2)
            }
        }
        .onReceive(timer) { _ in
            dotCount = (dotCount % 3) + 1
        }
    }
}
