import SwiftUI

struct ExpandedView: View {
    @Bindable var viewModel: NotchViewModel

    var body: some View {
        VStack(spacing: 0) {
            // Header bar
            HStack {
                Circle()
                    .fill(Theme.accentGreen)
                    .frame(width: 8, height: 8)

                Text("SecondSelf")
                    .font(Theme.titleFont)
                    .foregroundStyle(Theme.primaryText)

                Spacer()

                Button(action: { viewModel.collapse() }) {
                    Image(systemName: "chevron.up")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Theme.secondaryText)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 16)
            .padding(.top, 14)
            .padding(.bottom, 10)

            // Response area
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    if viewModel.isLoading {
                        HStack(spacing: 8) {
                            ProgressView()
                                .scaleEffect(0.7)
                                .controlSize(.small)
                            Text("Working...")
                                .font(Theme.bodyFont)
                                .foregroundStyle(Theme.secondaryText)
                        }
                        .padding(.horizontal, 4)
                    }

                    if !viewModel.responseText.isEmpty {
                        Text(viewModel.responseText)
                            .font(Theme.bodyFont)
                            .foregroundStyle(Theme.primaryText)
                            .textSelection(.enabled)
                    }

                    if !viewModel.actionsText.isEmpty {
                        Text(viewModel.actionsText)
                            .font(Theme.captionFont)
                            .foregroundStyle(Theme.accentGreen)
                            .padding(.top, 4)
                    }

                    if viewModel.responseText.isEmpty && !viewModel.isLoading {
                        Text("Ask me to do something — send an email, schedule a meeting, look something up.")
                            .font(Theme.bodyFont)
                            .foregroundStyle(Theme.secondaryText.opacity(0.6))
                    }
                }
                .padding(.horizontal, 4)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 380)
            .padding(.horizontal, 12)

            Spacer()

            // Text input pill
            InputPill(viewModel: viewModel)
                .padding(.horizontal, 12)
                .padding(.bottom, 12)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
