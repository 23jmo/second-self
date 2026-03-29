import SwiftUI

/// Mascot that hangs below the notch bar. Meant to be placed behind (lower Z)
/// the bar in a ZStack so the bar naturally hides it during the slide-in.
struct PeepingMascot: View {
    let barHeight: CGFloat
    let isVisible: Bool

    // Mascot sizing
    private let headRadius: CGFloat = 20
    private var eyeRadius: CGFloat { headRadius * 0.16 }
    private var eyeSpacing: CGFloat { headRadius * 0.55 }
    private var armWidth: CGFloat { headRadius * 0.65 }
    private var armHeight: CGFloat { headRadius * 0.35 }
    private let travel: CGFloat = 50

    // Colors from Figma
    private let creamColor = Color(red: 0xFB / 255.0, green: 0xFF / 255.0, blue: 0xD4 / 255.0)
    private let oliveColor = Color(red: 0x9C / 255.0, green: 0xA1 / 255.0, blue: 0x61 / 255.0)

    /// Total height below the bar that the mascot occupies when fully visible
    static let hangHeight: CGFloat = 58

    var body: some View {
        VStack(spacing: 0) {
            Spacer()
                .frame(height: barHeight)

            mascotBody
                .offset(y: isVisible ? 0 : -travel)
                .animation(.spring(response: 0.5, dampingFraction: 0.75), value: isVisible)
        }
        .allowsHitTesting(false)
    }

    private var mascotBody: some View {
        ZStack(alignment: .top) {
            // Arms at the very top (gripping the bar's bottom edge)
            HStack(spacing: headRadius * 2 - 6) {
                Ellipse()
                    .fill(gradient)
                    .frame(width: armWidth, height: armHeight)
                Ellipse()
                    .fill(gradient)
                    .frame(width: armWidth, height: armHeight)
            }
            .offset(y: -armHeight / 2 + 1)

            // Neck connector
            RoundedRectangle(cornerRadius: 3)
                .fill(gradient)
                .frame(width: headRadius * 1.4, height: 6)
                .offset(y: -1)

            // Head circle (rotated 180° — hanging upside-down)
            Circle()
                .fill(gradient)
                .frame(width: headRadius * 2, height: headRadius * 2)
                .shadow(color: .black.opacity(0.15), radius: 2, y: 1)
                .overlay(face)
                .rotationEffect(.degrees(180))
                .offset(y: armHeight / 2 + 4)
        }
        .frame(height: PeepingMascot.hangHeight)
    }

    private var face: some View {
        ZStack {
            // Eyes
            HStack(spacing: eyeSpacing) {
                Circle().fill(oliveColor)
                    .frame(width: eyeRadius * 2, height: eyeRadius * 2)
                Circle().fill(oliveColor)
                    .frame(width: eyeRadius * 2, height: eyeRadius * 2)
            }
            .offset(y: -headRadius * 0.1)

            // Triangle nose
            TriangleNose()
                .fill(oliveColor)
                .frame(width: 5, height: 4)
                .offset(y: headRadius * 0.18)

            // Mouth (small smile arc)
            MouthShape()
                .stroke(oliveColor, style: StrokeStyle(lineWidth: 1.2, lineCap: .round))
                .frame(width: 8, height: 5)
                .offset(y: headRadius * 0.38)
        }
    }

    private var gradient: LinearGradient {
        LinearGradient(
            colors: [creamColor, oliveColor],
            startPoint: .top,
            endPoint: .bottom
        )
    }
}

private struct TriangleNose: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        // Points upward (rotated 180° from downward triangle)
        path.move(to: CGPoint(x: rect.midX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        path.closeSubpath()
        return path
    }
}

private struct MouthShape: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addQuadCurve(
            to: CGPoint(x: rect.maxX, y: rect.minY),
            control: CGPoint(x: rect.midX, y: rect.maxY)
        )
        return path
    }
}
