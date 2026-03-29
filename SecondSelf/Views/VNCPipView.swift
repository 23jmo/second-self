import SwiftUI
import AppKit

// MARK: - VNC PiP View

/// Picture-in-picture VNC feed thumbnail.
/// Tapping expands the VNC view within the notch panel (content swap).
struct VNCPipView: View {
    @ObservedObject var streamer: MJPEGStreamer
    let twinState: TwinState
    let onExpand: () -> Void

    @State private var isHovered: Bool = false

    private let thumbnailSize = CGSize(width: 140, height: 90)

    var body: some View {
        ZStack(alignment: .topLeading) {
            // Live desktop feed
            Group {
                if let image = streamer.currentFrame {
                    Image(nsImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                } else {
                    Rectangle()
                        .fill(Color.ssBackground)
                }
            }
            .frame(width: thumbnailSize.width, height: thumbnailSize.height)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(
                        twinState == .working ? Color.ssTwinGreen : Color.ssBorder,
                        lineWidth: twinState == .working ? 1.5 : 0.5
                    )
            )
            .shadow(
                color: twinState == .working
                    ? Color.ssTwinGreen.opacity(0.3)
                    : Color.black.opacity(0.3),
                radius: twinState == .working ? 8 : 4
            )

            // LIVE indicator (only when actually streaming)
            if streamer.currentFrame != nil {
                HStack(spacing: 4) {
                    Circle()
                        .fill(Color.ssError)
                        .frame(width: 5, height: 5)
                    Text("LIVE")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundColor(Color.ssTextPrimary)
                }
                .padding(.horizontal, 6)
                .padding(.vertical, 3)
                .background(
                    Capsule()
                        .fill(Color.black.opacity(0.6))
                )
                .padding(6)
            }
        }
        .scaleEffect(isHovered ? 1.05 : 1.0)
        .animation(.spring(response: 0.3, dampingFraction: 0.7), value: isHovered)
        .onHover { hovering in
            isHovered = hovering
        }
        .onTapGesture {
            onExpand()
        }
    }
}

// MARK: - VNC Expanded Content View

/// Full VNC desktop view shown inside the notch panel when PiP is tapped.
/// Shows the MJPEG stream (passive view) plus a "Take Control" button that
/// launches TigerVNC for full remote control. TigerVNC handles mouse, keyboard,
/// and clipboard natively via the VNC/RFB protocol.
struct VNCExpandedContentView: View {
    @ObservedObject var streamer: MJPEGStreamer
    let twinState: TwinState
    let currentToolAction: String
    let onBack: () -> Void

    @State private var lastLaunchTime: Date = .distantPast

    var body: some View {
        VStack(spacing: 0) {
            // Stream area
            GeometryReader { geo in
                ZStack(alignment: .bottom) {
                    // MJPEG feed (passive view)
                    streamContent
                        .frame(width: geo.size.width, height: geo.size.height)
                        .clipped()
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .overlay(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(
                                    twinState == .working ? Color.ssTwinGreen : Color.ssBorder,
                                    lineWidth: twinState == .working ? 1.5 : 0.5
                                )
                        )
                        .shadow(
                            color: twinState == .working
                                ? Color.ssTwinGreen.opacity(0.3)
                                : Color.black.opacity(0.1),
                            radius: twinState == .working ? 12 : 2
                        )
                        .contentShape(Rectangle())
                        .onTapGesture {
                            launchTigerVNC()
                        }

                    VStack(spacing: 0) {
                        Spacer()

                        // "Take Control" button overlay
                        Button(action: launchTigerVNC) {
                            HStack(spacing: 6) {
                                Image(systemName: "cursorarrow.click.2")
                                    .font(.system(size: 11, weight: .medium))
                                Text("Take Control")
                                    .font(.system(size: 12, weight: .medium))
                            }
                            .foregroundColor(Color.ssTextPrimary)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 7)
                            .background(
                                Capsule()
                                    .fill(Color.ssTwinGreen.opacity(0.9))
                            )
                        }
                        .buttonStyle(.plain)
                        .padding(.bottom, 8)

                        // Bottom bar with current action
                        HStack {
                            if !currentToolAction.isEmpty {
                                Text(currentToolAction)
                                    .font(.system(size: 11))
                                    .italic()
                                    .foregroundColor(Color.ssTextSecondary)
                            } else if twinState == .idle {
                                Text("Ready — tap to take control")
                                    .font(.system(size: 11))
                                    .foregroundColor(Color.ssTextSecondary)
                            }
                            Spacer()
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(Color.ssBackground.opacity(0.8))
                    }

                    // Task complete toast
                    if twinState == .complete {
                        Button(action: onBack) {
                            HStack(spacing: 6) {
                                Text("Task complete")
                                    .font(.system(size: 12, weight: .medium))
                                Image(systemName: "arrow.uturn.backward")
                                    .font(.system(size: 10, weight: .semibold))
                            }
                            .foregroundColor(Color.ssBackground)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                            .background(Capsule().fill(Color.ssTwinGreen))
                        }
                        .buttonStyle(.plain)
                        .padding(.bottom, 60)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                }
            }
            .padding(12)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.ssSurface)
    }

    // MARK: - Stream Content

    @ViewBuilder
    private var streamContent: some View {
        if let image = streamer.currentFrame {
            Image(nsImage: image)
                .resizable()
                .aspectRatio(contentMode: .fill)
        } else {
            VStack(spacing: 12) {
                ProgressView()
                    .scaleEffect(0.8)
                Text("Connecting to Twin's desktop...")
                    .font(.system(size: 13))
                    .foregroundColor(Color.ssTextSecondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.ssBackground)
        }
    }

    // MARK: - Launch TigerVNC

    private func launchTigerVNC() {
        // Debounce: ignore taps within 2 seconds of last launch
        guard Date().timeIntervalSince(lastLaunchTime) > 2.0 else { return }
        lastLaunchTime = Date()

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-a", "TigerVNC", "--args", "localhost:5901"]

        do {
            try process.run()
            print("[VNC] Launched TigerVNC for remote control")
        } catch {
            print("[VNC] Failed to launch TigerVNC: \(error)")
            if let url = URL(string: "vnc://localhost:5901") {
                NSWorkspace.shared.open(url)
            }
        }
    }
}

// MARK: - Stream State

enum StreamState: Equatable {
    case disconnected
    case connecting
    case live
    case reconnecting
    case error
}

// MARK: - MJPEG Stream Parser

/// Connects to the agent-server MJPEG stream via URLSession.
/// Parses multipart/x-mixed-replace boundaries and extracts JPEG frames.
/// No WKWebView needed, no ATS restrictions.
final class MJPEGStreamer: NSObject, ObservableObject, URLSessionDataDelegate {
    @Published var currentFrame: NSImage?
    @Published var streamState: StreamState = .disconnected

    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var buffer = Data()
    private var isRunning = false
    private var retryTimer: Timer?
    private var frameCount = 0
    private var lastFrameID: ObjectIdentifier?

    // Pre-allocated JPEG markers (avoid heap alloc per frame)
    private static let jpegSOI = Data([0xFF, 0xD8])
    private static let jpegEOI = Data([0xFF, 0xD9])

    // Background queue for JPEG decoding (keep main thread free for UI)
    private let decodeQueue = DispatchQueue(label: "mjpeg.decode", qos: .userInitiated)

    func start() {
        guard !isRunning else { return }
        isRunning = true
        print("[VNC-PiP] Starting MJPEG streamer...")
        DispatchQueue.main.async { self.streamState = .connecting }
        connect()
    }

    func stop() {
        isRunning = false
        task?.cancel()
        task = nil
        session?.invalidateAndCancel()
        session = nil
        retryTimer?.invalidate()
        retryTimer = nil
        DispatchQueue.main.async {
            self.streamState = .disconnected
            self.currentFrame = nil
        }
    }

    private func connect() {
        guard isRunning else { return }

        guard let url = URL(string: ServerConfig.agentStreamURL) else { return }
        print("[VNC-PiP] Connecting to \(url)...")

        // Invalidate previous session to prevent leaks
        session?.invalidateAndCancel()

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 3600
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)

        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        task = session?.dataTask(with: request)
        task?.resume()
    }

    // MARK: - URLSessionDataDelegate

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        buffer.append(data)
        extractFrames()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            print("[VNC-PiP] Stream error: \(error.localizedDescription)")
        }
        if isRunning {
            buffer.removeAll()
            DispatchQueue.main.async { [weak self] in
                self?.streamState = .reconnecting
                self?.retryTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: false) { [weak self] _ in
                    self?.streamState = .connecting
                    self?.connect()
                }
            }
        } else {
            DispatchQueue.main.async { [weak self] in
                self?.streamState = .disconnected
            }
        }
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        if let http = response as? HTTPURLResponse {
            print("[VNC-PiP] Connected! HTTP \(http.statusCode)")
            if http.statusCode == 200 {
                DispatchQueue.main.async { [weak self] in
                    self?.streamState = .live
                }
            }
        }
        completionHandler(.allow)
    }

    // MARK: - JPEG Frame Extraction

    private func extractFrames() {
        while let jpegStart = buffer.firstRange(of: Self.jpegSOI),
              let jpegEnd = buffer[jpegStart.lowerBound...].firstRange(of: Self.jpegEOI) {

            let frameData = Data(buffer[jpegStart.lowerBound...jpegEnd.upperBound - 1])
            buffer.removeSubrange(..<jpegEnd.upperBound)

            // Decode JPEG off the main thread
            decodeQueue.async { [weak self] in
                guard let image = NSImage(data: frameData) else { return }
                DispatchQueue.main.async {
                    self?.currentFrame = image
                    self?.frameCount += 1
                    if let count = self?.frameCount, count <= 3 || count % 50 == 0 {
                        print("[VNC-PiP] Frame \(count) (\(frameData.count / 1024)KB)")
                    }
                }
            }
        }

        if buffer.count > 5_000_000 {
            buffer.removeAll()
        }
    }
}
