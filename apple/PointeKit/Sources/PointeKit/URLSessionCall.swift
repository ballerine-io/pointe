import Foundation

/// The call's socket over `URLSessionWebSocketTask`.
public struct URLSessionCallDialer: CallDialer {
    private let request: @Sendable () -> URLRequest

    /// `request` is asked at each dial, so a key that changed on disk is read again.
    public init(request: @escaping @Sendable () -> URLRequest) {
        self.request = request
    }

    public func dial() async throws -> any CallSocket {
        let opened = Opened()
        let session = URLSession(configuration: DaemonEndpoint.session().configuration, delegate: opened, delegateQueue: nil)
        let task = session.webSocketTask(with: request())
        task.maximumMessageSize = 4 << 20
        let socket = URLSessionCallSocket(task: task, session: session)
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                opened.wait(continuation)
                task.resume()
            }
        } onCancel: {
            socket.close()
        }
        return socket
    }
}

/// Tells the dial when the upgrade finished, or why it did not.
private final class Opened: NSObject, URLSessionWebSocketDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Error>?
    private var result: Result<Void, Error>?

    func wait(_ continuation: CheckedContinuation<Void, Error>) {
        lock.lock()
        defer { lock.unlock() }
        if let result { continuation.resume(with: result) } else { self.continuation = continuation }
    }

    private func finish(_ result: Result<Void, Error>) {
        lock.lock()
        defer { lock.unlock() }
        guard self.result == nil else { return }
        self.result = result
        continuation?.resume(with: result)
        continuation = nil
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
        finish(.success(()))
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        finish(.failure(CallClose(code: closeCode.rawValue, http: (webSocketTask.response as? HTTPURLResponse)?.statusCode,
                                  reason: reason.flatMap { String(data: $0, encoding: .utf8) } ?? "")))
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        let http = (task.response as? HTTPURLResponse)?.statusCode
        finish(.failure(CallClose(code: (task as? URLSessionWebSocketTask)?.closeCode.rawValue ?? 0, http: http == 101 ? nil : http)))
    }
}

final class URLSessionCallSocket: CallSocket, @unchecked Sendable {
    private let task: URLSessionWebSocketTask
    private let session: URLSession

    init(task: URLSessionWebSocketTask, session: URLSession) {
        self.task = task
        self.session = session
    }

    func send(text: String) { task.send(.string(text)) { _ in } }
    func send(audio: Data) { task.send(.data(audio)) { _ in } }

    func receive() async throws -> CallFrame {
        do {
            switch try await task.receive() {
            case .data(let data): return .audio(data)
            case .string(let text): return .text(text)
            @unknown default: return .text("")
            }
        } catch {
            let http = (task.response as? HTTPURLResponse)?.statusCode
            throw CallClose(code: task.closeCode.rawValue, http: http == 101 ? nil : http,
                            reason: task.closeReason.flatMap { String(data: $0, encoding: .utf8) } ?? "")
        }
    }

    func close() {
        task.cancel(with: .normalClosure, reason: nil)
        session.finishTasksAndInvalidate()
    }
}
