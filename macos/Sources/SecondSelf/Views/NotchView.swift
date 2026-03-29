import SwiftUI

struct NotchView: View {
    @Bindable var viewModel: NotchViewModel
    @State private var isHovering = false

    var body: some View {
        ZStack(alignment: .top) {
            // Mascot behind the bar (lowest Z — bar covers it during slide-in)
            if viewModel.panelState == .collapsed {
                PeepingMascot(barHeight: Theme.collapsedHeight, isVisible: isHovering)
            }

            // Background bar
            RoundedRectangle(cornerRadius: currentCornerRadius)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: currentCornerRadius)
                        .fill(Theme.panelBackground)
                )
                .shadow(color: .black.opacity(0.3), radius: 10, y: 5)
                .frame(height: barOnlyHeight)

            // Content (constrained to bar area, not full frame)
            switch viewModel.panelState {
            case .collapsed:
                CollapsedView(viewModel: viewModel)
                    .frame(height: Theme.collapsedHeight)
            case .preview:
                PreviewView(viewModel: viewModel)
            case .expanded:
                ExpandedView(viewModel: viewModel)
            }
        }
        .frame(width: currentWidth, height: currentHeight)
        .onHover { hovering in
            if viewModel.panelState == .collapsed {
                isHovering = hovering
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: viewModel.panelState)
        .onTapGesture {
            if viewModel.panelState == .collapsed {
                viewModel.handleClick()
            }
        }
        .onChange(of: viewModel.panelState) { oldValue, newValue in
            if newValue != .collapsed {
                isHovering = false
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
        case .collapsed: return Theme.collapsedHeight + PeepingMascot.hangHeight
        case .preview:   return Theme.previewHeight
        case .expanded:  return Theme.expandedHeight
        }
    }

    private var barOnlyHeight: CGFloat {
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
