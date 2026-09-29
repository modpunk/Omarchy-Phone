pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Services.Notifications

// The phone's notification daemon (org.freedesktop.Notifications).
//
// Apps talk to it with plain freedesktop notifications. Two categories get
// special surfaces (see docs/shell/INTEGRATION.md):
//   call.incoming  -> full-screen incoming call (also over the lock screen)
//   call           -> "call in progress" pill in the status bar
Singleton {
  id: root

  readonly property var list: server.trackedNotifications.values
  readonly property var feed: list.filter(n => !isCall(n))
  readonly property int count: feed.length
  property var banner: null
  property var incomingCall: null
  property var ongoingCall: null

  function category(n) { return n && n.hints ? String(n.hints["category"] || "") : "" }
  function isCall(n) { const c = category(n); return c === "call.incoming" || c === "call" }
  function action(n, id) {
    if (!n) return null
    for (const a of n.actions) if (a.identifier === id) return a
    return null
  }
  function invoke(n, id) {
    const a = action(n, id)
    if (a) a.invoke()
    else if (n && id === "default") n.dismiss()
  }
  function activate(n) {
    // Tap: run the default action if there is one, else just dismiss.
    const a = action(n, "default")
    if (a) a.invoke(); else n.dismiss()
  }
  function clearAll() { for (const n of feed.slice()) n.dismiss() }
  function clearEverything() { for (const n of list.slice()) n.dismiss(); refreshCalls() }

  function answer() {
    const n = incomingCall
    if (!n) return
    incomingCall = null
    Phone.ringingCall = null
    invoke(n, "accept")
    if (n.tracked) n.dismiss()   // resident notifications stay after invoke; the call surface must not
  }
  function decline() {
    const n = incomingCall
    if (!n) return
    incomingCall = null
    Phone.ringingCall = null
    if (action(n, "decline")) invoke(n, "decline")
    if (n.tracked) n.dismiss()
  }

  function refreshCalls() {
    let inc = null, cur = null
    for (const n of server.trackedNotifications.values) {
      if (category(n) === "call.incoming") inc = n
      else if (category(n) === "call") cur = n
    }
    incomingCall = inc
    ongoingCall = cur
    Phone.ringingCall = inc
  }

  NotificationServer {
    id: server
    keepOnReload: true
    actionsSupported: true
    imageSupported: true
    bodyMarkupSupported: false
    persistenceSupported: true
    inlineReplySupported: true
    extraHints: ["category", "x-ophone-caller", "x-ophone-number", "x-ophone-video"]

    onNotification: n => {
      n.tracked = true
      n.closed.connect(() => Qt.callLater(root.refreshCalls))
      if (root.isCall(n)) {
        if (root.category(n) === "call.incoming") Phone.screenOnNow()
        Qt.callLater(root.refreshCalls)   // trackedNotifications updates after this handler
        return
      }
      if (Phone.shade < 0.5 && !Phone.locked) {
        root.banner = n
        bannerTimer.restart()
      }
    }
  }

  // Volume down while ringing: ask the app to stop the ringtone (optional
  // "silence" action); the call keeps ringing on screen.
  Connections {
    target: Phone
    function onSilenceRinger() { if (root.action(root.incomingCall, "silence")) root.invoke(root.incomingCall, "silence") }
  }

  Timer { id: bannerTimer; interval: 4000; onTriggered: root.banner = null }
  function hideBanner() { banner = null; bannerTimer.stop() }
}
