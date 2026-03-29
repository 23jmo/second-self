import SwiftUI

struct PreviewView: View {
    let viewModel: NotchViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Circle()
                    .fill(Theme.accentGreen)
                    .frame(width: 8, height: 8)

                Text("SecondSelf")
                    .font(Theme.titleFont)
                    .foregroundStyle(Theme.primaryText)

                Spacer()

                Button(action: { viewModel.collapse() }) {
                    Image(systemName: "xmark")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(Theme.secondaryText)
                }
                .buttonStyle(.plain)
            }

            Text(viewModel.previewText)
                .font(Theme.bodyFont)
                .foregroundStyle(Theme.secondaryText)
                .lineLimit(2)

            Spacer()

            Button(action: { viewModel.handleClick() }) {
                Text("Open")
                    .font(Theme.captionFont)
                    .foregroundStyle(Theme.accentBlue)
            }
            .buttonStyle(.plain)
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}
