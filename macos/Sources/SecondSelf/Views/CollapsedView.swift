import SwiftUI

struct CollapsedView: View {
    let viewModel: NotchViewModel

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(viewModel.isStatusActive ? Theme.accentGreen : Theme.secondaryText)
                .frame(width: 8, height: 8)
                .shadow(
                    color: viewModel.isStatusActive ? Theme.accentGreen.opacity(0.6) : .clear,
                    radius: 4
                )

            Text("SecondSelf")
                .font(Theme.captionFont)
                .foregroundStyle(Theme.secondaryText)

            Spacer()

            Image(systemName: "chevron.down")
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(Theme.secondaryText.opacity(0.5))
        }
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
    }
}
