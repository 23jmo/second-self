import SwiftUI
import AppKit

// MARK: - VNC PiP View

/// Picture-in-picture VNC feed thumbnail.
/// Native MJPEG parser using URLSession (no WKWebView, no ATS issues).
/// Olive-green glow when Twin is working. Click to expand.
struct VNCPipView: View {
    let twinState: TwinState

    @StateObject private var streamer = MJPEGStreamer()
    @State private var isHovered: Bool = false
    @State private var expandedWindow: NSWindow?

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
            openExpandedVNCWindow()
        }
        .onAppear {
            streamer.start()
        }
        .onDisappear {
            streamer.stop()
        }
    }


    // MARK: - Expanded VNC Window

    private func openExpandedVNCWindow() {
        if expandedWindow != nil {
            expandedWindow?.makeKeyAndOrderFront(nil)
            return
        }

        let windowSize = CGSize(width: 800, height: 500)
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: windowSize),
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Second Self — Twin's Desktop"
        window.backgroundColor = NSColor(red: 0.05, green: 0.05, blue: 0.06, alpha: 1.0)
        window.isReleasedWhenClosed = false
        window.center()

        let hostingView = NSHostingView(
            rootView: ExpandedVNCView(streamer: streamer)
        )
        window.contentView = hostingView
        window.makeKeyAndOrderFront(nil)
        expandedWindow = window
    }
}

// MARK: - Expanded VNC View

struct ExpandedVNCView: View {
    @ObservedObject var streamer: MJPEGStreamer

    var body: some View {
        Group {
            if let image = streamer.currentFrame {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
            } else {
                VStack(spacing: 8) {
                    Text("Connecting to Twin's desktop...")
                        .font(.system(size: 14))
                        .foregroundColor(Color.ssTextSecondary)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.ssBackground)
    }
}

// MARK: - MJPEG Stream Parser

/// Connects to the agent-server MJPEG stream via URLSession.
/// Parses multipart/x-mixed-replace boundaries and extracts JPEG frames.
/// No WKWebView needed, no ATS restrictions.
final class MJPEGStreamer: NSObject, ObservableObject, URLSessionDataDelegate {
    @Published var currentFrame: NSImage?

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
    }

    private func connect() {
        guard isRunning else { return }

        let url = URL(string: ServerConfig.agentStreamURL)!
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
            // Retry after delay
            DispatchQueue.main.async { [weak self] in
                self?.retryTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: false) { [weak self] _ in
                    self?.connect()
                }
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
