import SwiftUI

struct InputPill: View {
    @Bindable var viewModel: NotchViewModel
    @FocusState private var isFocused: Bool

    var body: some View {
        HStack(spacing: 8) {
            TextField(viewModel.inputPlaceholder, text: $viewModel.inputText)
                .textFieldStyle(.plain)
                .font(Theme.bodyFont)
                .foregroundStyle(Theme.primaryText)
                .focused($isFocused)
                .onSubmit {
                    viewModel.sendMessage()
                }

            Button(action: { viewModel.sendMessage() }) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 24))
                    .foregroundStyle(
                        viewModel.inputText.isEmpty
                            ? Theme.secondaryText
                            : Theme.accentBlue
                    )
            }
            .buttonStyle(.plain)
            .disabled(viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .padding(.horizontal, 14)
        .frame(height: Theme.inputPillHeight)
        .background(
            Capsule()
                .fill(Theme.pillBackground)
                .overlay(
                    Capsule()
                        .strokeBorder(
                            isFocused ? Theme.accentBlue.opacity(0.5) : Theme.pillBorder,
                            lineWidth: 1
                        )
                )
        )
    }
}
