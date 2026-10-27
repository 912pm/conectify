import AppKit
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate, NSWindowDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var origin: URL?
    var startup: Process?
    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "Quit Conectify", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(); menu.addItem(editItem)
        let edit = NSMenu(title: "Edit"); editItem.submenu = edit
        for (title, action, key) in [("Undo", "undo:", "z"), ("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        NSApp.mainMenu = menu
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "copyText")
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self; web.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 800), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Conectify"; window.minSize = NSSize(width: 820, height: 580)
        window.contentView = web; window.delegate = self
        window.setFrameAutosaveName("ConectifyMainWindow")
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        web.loadHTMLString("<body style='background:#f5f4ef;color:#647759;font:20px system-ui;padding:60px'>Opening Conectify…</body>", baseURL: nil)
        let task = Process(); startup = task
        task.executableURL = Bundle.main.executableURL!.deletingLastPathComponent().appendingPathComponent("ConectifyBackend")
        task.arguments = ["--url-only"]
        let output = Pipe(); let errors = Pipe()
        task.standardOutput = output; task.standardError = errors
        task.terminationHandler = { process in
            let data = output.fileHandleForReading.readDataToEndOfFile()
            let text = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            DispatchQueue.main.async {
                guard process.terminationStatus == 0, let url = URL(string: text), url.host == "127.0.0.1", url.scheme == "http" else {
                    self.showError("Conectify could not start. Check ~/Library/Application Support/Conectify/vault/server.log."); return
                }
                self.origin = url; self.web.load(URLRequest(url: url))
            }
        }
        do { try task.run() } catch { showError(error.localizedDescription) }
    }
    func showError(_ message: String) {
        let alert = NSAlert(); alert.messageText = "Conectify could not open"; alert.informativeText = message; alert.runModal()
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil); return true
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil); return false // Preserve unsaved edits when closing the window.
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        web.evaluateJavaScript("typeof dirty !== 'undefined' && dirty") { value, _ in
            if value as? Bool == true {
                let alert = NSAlert(); alert.messageText = "Quit without saving your edits?"
                alert.addButton(withTitle: "Keep editing"); alert.addButton(withTitle: "Quit")
                sender.reply(toApplicationShouldTerminate: alert.runModal() == .alertSecondButtonReturn)
            } else { sender.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
    }
    func local(_ url: URL) -> Bool { url.scheme == origin?.scheme && url.host == origin?.host && url.port == origin?.port }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let url = message.frameInfo.request.url, local(url), let text = message.body as? String else { return }
        NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string)
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.absoluteString == "about:blank" || local(url) { decisionHandler(.allow) }
        else { if navigationAction.navigationType == .linkActivated && ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }; decisionHandler(.cancel) }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let disposition = (navigationResponse.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition") ?? ""
        decisionHandler(disposition.hasPrefix("attachment") || !navigationResponse.canShowMIMEType ? .download : .allow)
    }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel(); panel.nameFieldStringValue = suggestedFilename
        panel.beginSheetModal(for: window) { result in
            guard result == .OK, let url = panel.url else { completionHandler(nil); return }
            // WebKit requires a non-existing destination; the save panel confirms replacement.
            do { if FileManager.default.fileExists(atPath: url.path) { try FileManager.default.removeItem(at: url) }; completionHandler(url) }
            catch { self.showError(error.localizedDescription); completionHandler(nil) }
        }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) { showError(error.localizedDescription) }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = parameters.allowsMultipleSelection; panel.canChooseDirectories = false
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = message; alert.addButton(withTitle: "OK"); alert.addButton(withTitle: "Cancel")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }
}
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
