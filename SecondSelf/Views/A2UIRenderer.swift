import SwiftUI

// MARK: - A2UI Renderer

/// Dispatches an A2UIPayload to the appropriate native SwiftUI view.
/// Falls back to a generic card for unknown component types.
struct A2UIRenderer: View {
    let payload: A2UIPayload
    let isStreaming: Bool
    let onAction: (String, String) -> Void  // (actionId, contextDescription)

    init(payload: A2UIPayload, isStreaming: Bool = false, onAction: @escaping (String, String) -> Void) {
        self.payload = payload
        self.isStreaming = isStreaming
        self.onAction = onAction
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(rootComponents) { component in
                    componentView(for: component)
                }
            }
            Spacer(minLength: 40)
        }
    }

    // MARK: - Component Dispatch

    @ViewBuilder
    private func componentView(for component: A2UIComponent) -> some View {
        switch component.type {
        case A2UIComponentType.taskApproval:
            if let data = TaskApprovalData(from: component) {
                TaskApprovalView(
                    data: data,
                    isStreaming: isStreaming,
                    onApprove: { reorderedSteps in
                        let stepList = reorderedSteps.map { $0.text }.joined(separator: ", ")
                        onAction("approve", "Approved plan: [\(stepList)]")
                    },
                    onReject: {
                        onAction("reject", "Rejected the proposed plan")
                    }
                )
            } else {
                fallbackView(for: component)
            }

        case A2UIComponentType.profileCard:
            if let data = ProfileCardData(from: component) {
                ProfileCardView(
                    data: data,
                    onConfirm: { fact in
                        onAction("confirm", "Confirmed: \(fact)")
                    },
                    onDeny: { fact in
                        onAction("deny", "That's incorrect: \(fact)")
                    }
                )
            } else {
                fallbackView(for: component)
            }

        case A2UIComponentType.screenshot:
            if let data = ScreenshotData(from: component) {
                ScreenshotPreviewCard(data: data)
            } else {
                fallbackView(for: component)
            }

        case A2UIComponentType.confirmAction:
            if let data = ConfirmActionData(from: component) {
                ConfirmActionView(
                    data: data,
                    onAllow: {
                        onAction("allow", "Allowed: \(data.action)")
                    },
                    onDeny: {
                        onAction("deny", "Denied: \(data.action)")
                    }
                )
            } else {
                fallbackView(for: component)
            }

        default:
            fallbackView(for: component)
        }
    }

    // MARK: - Fallback

    /// Generic card for unknown or malformed component types.
    private func fallbackView(for component: A2UIComponent) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: "square.grid.2x2")
                    .font(.system(size: 9))
                    .foregroundColor(Color.ssTwinGreen)
                Text(component.type)
                    .font(.system(size: 11, design: .monospaced))
                    .fontWeight(.medium)
                    .foregroundColor(Color.ssTwinGreen)
            }

            ForEach(Array(component.properties.keys.sorted()), id: \.self) { key in
                if let value = component.properties[key] {
                    HStack(alignment: .top, spacing: 4) {
                        Text("\(key):")
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(Color.ssTextSecondary)
                        Text(valueDescription(value))
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(Color.ssTextPrimary.opacity(0.8))
                            .lineLimit(3)
                    }
                }
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(Color.ssBorder, lineWidth: 0.5)
                )
        )
    }

    // MARK: - Helpers

    /// Root-level components (no parentId).
    private var rootComponents: [A2UIComponent] {
        payload.components.filter { $0.parentId == nil }
    }

    private func valueDescription(_ value: A2UIValue) -> String {
        switch value {
        case .string(let s): return s
        case .int(let i): return "\(i)"
        case .double(let d): return "\(d)"
        case .bool(let b): return b ? "true" : "false"
        case .array(let a): return "[\(a.count) items]"
        case .object(let o): return "{\(o.count) keys}"
        case .null: return "null"
        }
    }
}
