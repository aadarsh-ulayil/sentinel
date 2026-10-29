import Cocoa
import WebKit
import UserNotifications

// A local menu-bar companion. The Python gateway remains the enforcement boundary.
final class Sentinel: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    var window: NSWindow?
    var statusItem: NSStatusItem!
    var timer: Timer?
    var token = ""
    var seen = Set<String>()
    var pending: [[String: Any]] = []
    var running: [String] = []
    var requesting = false
    var disconnected = false
    var connectedOnce = false
    var failures = 0
    let center = UNUserNotificationCenter.current()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        guard let configURL = Bundle.main.url(forResource: "config", withExtension: "json"),
              let data = try? Data(contentsOf: configURL),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              let path = config["credentials_file"],
              let credentials = try? Data(contentsOf: URL(fileURLWithPath: path)),
              let values = try? JSONSerialization.jsonObject(with: credentials) as? [String: String],
              let value = values["token"] else { NSApp.terminate(nil); return }
        token = value
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = NSImage(systemSymbolName: "shield", accessibilityDescription: "SENTINEL")
        statusItem.button?.toolTip = "SENTINEL — connecting to the local gateway"
        center.delegate = self
        let review = UNNotificationAction(identifier: "REVIEW", title: "Review action", options: [.foreground])
        let deny = UNNotificationAction(identifier: "DENY", title: "Deny", options: [.destructive])
        center.setNotificationCategories([UNNotificationCategory(identifier: "APPROVAL", actions: [review, deny], intentIdentifiers: [])])
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
        refreshMenu()
        openLog()
        poll()
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.poll() }
    }

    func request(_ path: String, body: [String: Any]? = nil, completion: @escaping (Int, Data?) -> Void) {
        guard let url = URL(string: "http://127.0.0.1:8000" + path) else { return }
        var req = URLRequest(url: url, timeoutInterval: 5)
        req.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        if let body = body {
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        URLSession.shared.dataTask(with: req) { data, response, _ in
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            DispatchQueue.main.async { completion(status, data) }
        }.resume()
    }

    func notify(_ id: String, title: String, message: String, action: Int? = nil) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = message
        content.sound = .default
        if let aid = action { content.categoryIdentifier = "APPROVAL"; content.userInfo = ["action_id": aid] }
        center.add(UNNotificationRequest(identifier: id, content: content, trigger: nil))
    }

    func poll() {
        guard !requesting else { return }
        requesting = true
        request("/api/state") { [weak self] status, data in
            guard let self = self else { return }
            self.requesting = false
            guard status == 200, let data = data,
                  let state = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let actions = state["actions"] as? [[String: Any]] else {
                self.failures += 1
                if self.failures == 3 {
                    self.notify("gateway-offline", title: "SENTINEL gateway unavailable", message: "Connected agents cannot execute tools through the gateway. Check the menu-bar status.")
                }
                self.disconnected = true; self.refreshMenu(); return
            }
            let initial = !self.connectedOnce
            self.failures = 0
            self.disconnected = false; self.connectedOnce = true
            let oldPending = Set(self.pending.compactMap { $0["id"] as? Int })
            self.pending = actions.filter { ($0["status"] as? String) == "waiting_for_human" }
            let currentPending = Set(self.pending.compactMap { $0["id"] as? Int })
            self.center.removeDeliveredNotifications(withIdentifiers: oldPending.subtracting(currentPending).map { "approval-\($0)" })
            self.running = (state["runs"] as? [[String: Any]] ?? []).filter { ($0["status"] as? String) == "running" }.compactMap { $0["id"] as? String }
            for action in actions {
                guard let aid = action["id"] as? Int, let status = action["status"] as? String else { continue }
                let key = "\(aid)-\(status)"
                guard !self.seen.contains(key) else { continue }
                self.seen.insert(key)
                let tool = action["tool"] as? String ?? "tool"
                if status == "waiting_for_human" {
                    self.notify("approval-\(aid)", title: "SENTINEL: approval needed", message: "\(tool) is paused. Review or deny it. No answer within 60 seconds means deny.", action: aid)
                } else if status == "blocked" || status == "failed" {
                    if !initial {
                        self.notify("blocked-\(aid)", title: "SENTINEL blocked an action", message: "\(tool) was stopped by a restriction. Details are in the optional activity log.")
                    }
                }
            }
            self.refreshMenu()
        }
    }

    func refreshMenu() {
        let menu = NSMenu()
        let status = disconnected ? "Gateway unavailable" : (connectedOnce ? "Protection active · connected tools only" : "Connecting…")
        menu.addItem(withTitle: status, action: nil, keyEquivalent: "")
        statusItem.button?.toolTip = "SENTINEL — " + status
        statusItem.button?.title = pending.isEmpty ? "" : " \(pending.count)"
        menu.addItem(.separator())
        for action in pending {
            guard let aid = action["id"] as? Int else { continue }
            let item = NSMenuItem(title: "Review #\(aid): \(action["tool"] as? String ?? "action")", action: #selector(reviewMenu(_:)), keyEquivalent: "")
            item.target = self; item.representedObject = aid; menu.addItem(item)
        }
        if pending.isEmpty { menu.addItem(withTitle: "No approvals waiting", action: nil, keyEquivalent: "") }
        let log = NSMenuItem(title: "Open SENTINEL", action: #selector(openLog), keyEquivalent: "")
        log.target = self; menu.addItem(log)
        let kill = NSMenuItem(title: "Kill all active runs", action: #selector(killRuns), keyEquivalent: "")
        kill.target = self; kill.isEnabled = !running.isEmpty; menu.addItem(kill)
        menu.addItem(.separator())
        let test = NSMenuItem(title: "Test notification", action: #selector(testNotification), keyEquivalent: "")
        test.target = self; menu.addItem(test)
        let quit = NSMenuItem(title: "Quit notification companion", action: #selector(quitCompanion), keyEquivalent: "")
        quit.target = self; menu.addItem(quit)
        statusItem.menu = menu
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openLog()
        return true
    }

    @objc func openLog() {
        if let window = window {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let web = WKWebView(frame: .zero, configuration: configuration)
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1100, height: 760),
                             styleMask: [.titled, .closable, .miniaturizable, .resizable],
                             backing: .buffered, defer: false)
        panel.title = "SENTINEL"
        panel.isReleasedWhenClosed = false
        panel.contentView = web
        panel.center()
        window = panel
        // Keep the local operator session in memory, out of URLs and page scripts.
        let cookie = HTTPCookie(properties: [.name: "sentinel_session", .value: token,
                                            .domain: "127.0.0.1", .path: "/",
                                            HTTPCookiePropertyKey("HttpOnly"): "TRUE",
                                            HTTPCookiePropertyKey("SameSite"): "Strict"])!
        configuration.websiteDataStore.httpCookieStore.setCookie(cookie) {
            web.load(URLRequest(url: URL(string: "http://127.0.0.1:8000/")!))
        }
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    @objc func testNotification() { notify(UUID().uuidString, title: "SENTINEL is running", message: "This is a test. Allowed actions stay quiet; blocks and approval requests trigger alerts.") }
    @objc func quitCompanion() { NSApp.terminate(nil) }
    @objc func killRuns() { for run in running { request("/api/runs/\(run)/kill", body: [:]) { _, _ in }; }; poll() }
    @objc func reviewMenu(_ sender: NSMenuItem) { if let aid = sender.representedObject as? Int { review(aid) } }

    func review(_ aid: Int) {
        request("/api/actions/\(aid)") { [weak self] status, data in
            guard let self = self else { return }
            guard status == 200, let data = data,
                  let action = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  action["status"] as? String == "waiting_for_human" else {
                self.notify(UUID().uuidString, title: "Action is no longer waiting", message: "It may have timed out, been denied, or the run was stopped."); return
            }
            let alert = NSAlert()
            alert.messageText = "Review SENTINEL action #\(aid)"
            alert.informativeText = "Tool: \(action["tool"] as? String ?? "")\nArguments (untrusted data):\n\(action["args_json"] as? String ?? "")\n\nReason: \(action["reason"] as? String ?? "")\n\nOnly approve if you intend this action. The gateway rechecks whether it is still waiting."
            alert.addButton(withTitle: "Deny")
            alert.addButton(withTitle: "Approve")
            alert.addButton(withTitle: "Cancel")
            NSApp.activate(ignoringOtherApps: true)
            let answer = alert.runModal()
            if answer == .alertFirstButtonReturn { self.answer(aid, approve: false) }
            if answer == .alertSecondButtonReturn { self.answer(aid, approve: true) }
        }
    }

    func answer(_ aid: Int, approve: Bool) {
        request("/api/actions/\(aid)/answer", body: ["approve": approve]) { [weak self] status, _ in
            if status != 200 { self?.notify(UUID().uuidString, title: "Approval was not applied", message: "The action may have expired or the gateway is unavailable.") }
            self?.poll()
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        DispatchQueue.main.async {
            if let aid = response.notification.request.content.userInfo["action_id"] as? Int {
                if response.actionIdentifier == "DENY" { self.answer(aid, approve: false) }
                else if response.actionIdentifier != UNNotificationDismissActionIdentifier { self.review(aid) }
            }
            completionHandler()
        }
    }
}

let app = NSApplication.shared
let delegate = Sentinel()
app.delegate = delegate
app.run()
