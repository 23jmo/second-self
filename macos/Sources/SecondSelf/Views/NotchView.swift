import SwiftUI

struct NotchView: View {
    @Bindable var viewModel: NotchViewModel

    var body: some View {
        ZStack(alignment: .top) {
            // Background
            RoundedRectangle(cornerRadius: currentCornerRadius)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: currentCornerRadius)
                        .fill(Theme.panelBackground)
                )
                .shadow(color: .black.opacity(0.3), radius: 10, y: 5)

            // Content
            switch viewModel.panelState {
            case .collapsed:
                CollapsedView(viewModel: viewModel)
            case .preview:
                PreviewView(viewModel: viewModel)
            case .expanded:
                ExpandedView(viewModel: viewModel)
            }
        }
        .frame(width: currentWidth, height: currentHeight)
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: viewModel.panelState)
        .onTapGesture {
            if viewModel.panelState == .collapsed {
                viewModel.handleClick()
            }
        }
    }

    private var currentWidth: CGFloat {
        switch viewModel.panelState {
        case .collapsed: return Theme.collapsedWidth
        case .preview:   return Theme.previewWidth
        case .expanded:  return Theme.expandedWidth
        }
    }

    private var currentHeight: CGFloat {
        switch viewModel.panelState {
        case .collapsed: return Theme.collapsedHeight
        case .preview:   return Theme.previewHeight
        case .expanded:  return Theme.expandedHeight
        }
    }

    private var currentCornerRadius: CGFloat {
        switch viewModel.panelState {
        case .collapsed, .preview: return Theme.cornerRadius
        case .expanded:            return Theme.expandedCornerRadius
        }
    }
}
