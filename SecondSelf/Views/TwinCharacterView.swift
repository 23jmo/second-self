import SwiftUI

// MARK: - Twin Character View

/// The Twin mascot rendered as a simple SwiftUI shape composition.
/// Circle head + ellipse body in olive green.
/// Animates based on TwinState with spring timing.
/// Will be replaced with SVG/PDF assets from Figma later.
struct TwinCharacterView: View {
    let twinState: TwinState
    var compact: Bool = false

    // Animation state
    @State private var breatheScale: CGFloat = 1.0
    @State private var bobOffset: CGFloat = 0
    @State private var wiggleRotation: Double = 0
    @State private var bounceScale: CGFloat = 1.0
    @State private var errorTilt: Double = 0

    private var twinGreen: Color {
        Color(hex: 0xB5B055)
    }

    private var headSize: CGFloat {
        compact ? 18 : 28
    }

    private var bodyWidth: CGFloat {
        compact ? 22 : 34
    }

    private var bodyHeight: CGFloat {
        compact ? 14 : 20
    }

    var body: some View {
        VStack(spacing: compact ? 1 : 2) {
            // Head
            Circle()
                .fill(twinGreen)
                .frame(width: headSize, height: headSize)

            // Body
            Ellipse()
                .fill(twinGreen.opacity(0.85))
                .frame(width: bodyWidth, height: bodyHeight)
        }
        .scaleEffect(breatheScale * bounceScale)
        .offset(y: bobOffset)
        .rotationEffect(.degrees(wiggleRotation + errorTilt))
        .shadow(color: twinGreen.opacity(0.2), radius: 4)
        .onAppear {
            applyAnimation(for: twinState)
        }
        .onChange(of: twinState) { newState in
            resetAnimations()
            applyAnimation(for: newState)
        }
    }

    // MARK: - Animations

    private func applyAnimation(for state: TwinState) {
        switch state {
        case .idle:
            // Subtle breathing: scale 1.0 to 1.02, repeating 2s
            withAnimation(
                .spring(response: 1.0, dampingFraction: 0.7)
                .repeatForever(autoreverses: true)
            ) {
                breatheScale = 1.02
            }

        case .thinking:
            // Slow vertical bob: offset y oscillation
            withAnimation(
                .spring(response: 0.8, dampingFraction: 0.7)
                .repeatForever(autoreverses: true)
            ) {
                bobOffset = -4
            }

        case .working:
            // Slight rotation wiggle
            withAnimation(
                .spring(response: 0.3, dampingFraction: 0.7)
                .repeatForever(autoreverses: true)
            ) {
                wiggleRotation = 5
            }

        case .complete:
            // Quick scale bounce: 1.0 -> 1.1 -> 1.0
            withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) {
                bounceScale = 1.1
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) {
                    bounceScale = 1.0
                }
            }

        case .error:
            // Tilt 5 degrees
            withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) {
                errorTilt = 5
            }
        }
    }

    private func resetAnimations() {
        breatheScale = 1.0
        bobOffset = 0
        wiggleRotation = 0
        bounceScale = 1.0
        errorTilt = 0
    }
}
