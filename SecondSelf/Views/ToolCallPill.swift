import SwiftUI
import AppKit

// MARK: - Tool Call Pill

/// Inline tool call indicator — real app icons + human-readable text, no chip background.
struct ToolCallPill: View {
    let tool: String
    let args: [String: String]
    let result: String?
    var progress: String? = nil

    @State private var isExpanded: Bool = false

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    // Real app icon
                    ToolAppIcon(tool: tool)
                        .frame(width: 18, height: 18)

                    Text(displayText)
                        .font(.system(size: 13, weight: .regular))
                        .foregroundColor(.white.opacity(0.55))
                        .lineLimit(1)
                        .truncationMode(.middle)

                    if result != nil {
                        Spacer()
                        Button(action: { withAnimation(.ssMicro) { isExpanded.toggle() } }) {
                            Image(systemName: "chevron.right")
                                .font(.system(size: 9, weight: .semibold))
                                .foregroundColor(.white.opacity(0.25))
                                .rotationEffect(.degrees(isExpanded ? 90 : 0))
                                .animation(.ssMicro, value: isExpanded)
                        }
                        .buttonStyle(.plain)
                    }
                }

                // Progress text shown while tool is running
                if result == nil, let progress = progress {
                    Text(progress)
                        .font(.system(size: 11, weight: .regular))
                        .foregroundColor(.white.opacity(0.35))
                        .lineLimit(1)
                        .padding(.leading, 26)
                        .transition(.opacity)
                        .animation(.easeInOut(duration: 0.3), value: progress)
                }

                if isExpanded, let result = result {
                    Text(result)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(.white.opacity(0.4))
                        .lineLimit(8)
                        .padding(.leading, 26)
                        .padding(.top, 1)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
            .padding(.vertical, 4)

            Spacer()
        }
    }

    private var displayText: String {
        let action = friendlyAction
        let target = args.first.map { "\($0.value)" } ?? ""
        if target.isEmpty { return action }
        return "\(action) \(target)"
    }

    private var friendlyAction: String {
        switch tool {
        case "browser_goto":     return "Opening"
        case "browser_click":    return "Clicking"
        case "browser_fill":     return "Typing in"
        case "browser_snapshot": return "Reading page"
        case "browser_text":     return "Reading text"
        case "browser_press":    return "Pressing"
        case "browser_close":    return "Closing browser"
        case "screenshot":       return "Taking screenshot"
        case "open_app":         return "Opening"
        case "type_text":        return "Typing"
        case "hotkey":           return "Pressing"
        case "click_at":         return "Clicking"
        case "sync_cookies":     return "Syncing cookies"
        case "tavily_search":    return "Searching"
        case "gmail_search":     return "Searching Gmail"
        case "gmail_read":       return "Reading email"
        case "calendar_list":    return "Checking calendar"
        default:
            return tool.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
}

// MARK: - Tool App Icon

/// Grabs real macOS app icons at runtime. Falls back to SF Symbols.
struct ToolAppIcon: View {
    let tool: String

    var body: some View {
        if let nsImage = appIcon {
            Image(nsImage: nsImage)
                .resizable()
                .aspectRatio(contentMode: .fit)
        } else {
            // Fallback SF Symbol
            Image(systemName: fallbackSymbol)
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(.white.opacity(0.4))
        }
    }

    private var appIcon: NSImage? {
        if let path = appPath {
            return NSWorkspace.shared.icon(forFile: path)
        }
        return nil
    }

    private var appPath: String? {
        switch tool {
        // Browser tools → Chrome icon
        case _ where tool.starts(with: "browser"), "sync_cookies":
            return findApp("Google Chrome") ?? findApp("Chromium")

        // Gmail → Mail.app icon (closest native equivalent)
        case _ where tool.contains("gmail") || tool.contains("email"):
            return "/System/Applications/Mail.app"

        // Calendar
        case _ where tool.contains("calendar"):
            return "/System/Applications/Calendar.app"

        // Screenshot → Screenshot.app
        case "screenshot":
            return "/System/Applications/Utilities/Screenshot.app"

        // open_app → try to find the specific app
        case "open_app":
            if let appName = specificAppName {
                return findApp(appName)
            }
            return nil

        // Desktop tools → Automator (closest "automation" icon)
        case "type_text", "hotkey", "click_at":
            return "/System/Applications/Automator.app"

        // Search
        case "tavily_search":
            return findApp("Safari")

        default:
            return nil
        }
    }

    private var specificAppName: String? {
        // For open_app, the app name is in the args — but we only have the tool name here.
        // The args are on ToolCallPill, not passed down. Return nil to use fallback.
        nil
    }

    private var fallbackSymbol: String {
        switch tool {
        case _ where tool.starts(with: "browser"):  return "globe"
        case "screenshot":                           return "camera.viewfinder"
        case _ where tool.contains("gmail"):         return "envelope"
        case _ where tool.contains("calendar"):      return "calendar"
        case "tavily_search":                        return "magnifyingglass"
        case _ where tool.starts(with: "render_"):   return "rectangle.on.rectangle"
        default:                                     return "gearshape"
        }
    }

    private func findApp(_ name: String) -> String? {
        let candidates = [
            "/Applications/\(name).app",
            "/System/Applications/\(name).app",
            "/System/Applications/Utilities/\(name).app",
        ]
        return candidates.first { FileManager.default.fileExists(atPath: $0) }
    }
}
