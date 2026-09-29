//@ pragma IconTheme Yaru
//@ pragma Env QT_QUICK_BACKEND=software
// Omarchy Phone shell. Vox Libertatis.
// Run: qs -p shell/qs     (Hyprland starts it from shell/hypr/hyprland.lua)
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import qs.Commons
import qs.Services
import qs.Surfaces

ShellRoot {
  // Creation order = stacking order within a layer.
  HomeScreen {}
  StatusBar {}
  NavBar {}
  Keyboard {}
  Banner {}
  Osd {}
  Shade {}
  Switcher {}
  PowerMenu {}
  CallSurface {}
  LockScreen {}

  // Hardware keys: Hyprland binds dispatch hl.dsp.global("ophone:<name>").
  GlobalShortcut { appid: "ophone"; name: "home"; description: "Home button"; onPressed: Phone.homePressed() }
  GlobalShortcut { appid: "ophone"; name: "power"; description: "Power button"; onPressed: Phone.powerPressed(); onReleased: Phone.powerReleased() }
  GlobalShortcut { appid: "ophone"; name: "volume-up"; description: "Volume up"; onPressed: Phone.volumeUp() }
  GlobalShortcut { appid: "ophone"; name: "volume-down"; description: "Volume down"; onPressed: Phone.volumeDown() }
  GlobalShortcut { appid: "ophone"; name: "mute"; description: "Ring/silent switch"; onPressed: Phone.toggleSilent() }
  GlobalShortcut { appid: "ophone"; name: "switcher"; description: "App switcher"; onPressed: Phone.toggleSwitcher() }
  GlobalShortcut { appid: "ophone"; name: "lock"; description: "Lock"; onPressed: Phone.lock() }
  GlobalShortcut { appid: "ophone"; name: "keyboard"; description: "On-screen keyboard"; onPressed: Phone.keyboardOpen = !Phone.keyboardOpen }

  // Scripting / test surface: qs -p shell/qs ipc call shell <fn> [args]
  // (shell/bin/ophone-ctl wraps this.)
  IpcHandler {
    target: "shell"
    function ping(): string { return "pong " + Notifs.count }
    function home(): void { Phone.home() }
    function switcher(): void { Phone.showSwitcher() }
    function shade(): void { Phone.openShade() }
    function closeShade(): void { Phone.closeShade() }
    function keyboard(): void { Phone.keyboardOpen = !Phone.keyboardOpen }
    function lock(): void { Phone.lock() }
    function pin(): void { if (Phone.locked) Phone.pinVisible = true }
    function powerMenu(): void { Phone.powerMenu() }
    function powerPress(): void { Phone.powerPressed() }
    function powerRelease(): void { Phone.powerReleased() }
    function homeKey(): void { Phone.homePressed() }
    function volumeUp(): void { Phone.volumeUp() }
    function volumeDown(): void { Phone.volumeDown() }
    function silent(): void { Phone.toggleSilent() }
    function isSilent(): bool { return Phone.silent }
    function isLocked(): bool { return Phone.locked }
    function answerCall(): void { Notifs.answer() }
    function declineCall(): void { Notifs.decline() }
    function clearNotifications(): void { Notifs.clearAll() }
    // JSON list of current notifications (for app developers and tests).
    function notifications(): string {
      return JSON.stringify(Notifs.list.map(n => ({ id: n.id, app: n.appName, summary: n.summary, body: n.body,
        category: Notifs.category(n), urgency: n.urgency, hints: Object.keys(n.hints || {}),
        actions: n.actions.map(a => a.identifier) })))
    }
    // Preview helper: back to a clean home screen. Unlocks only in dry-run mode.
    function reset(): void {
      Phone.closeOverlays(); Phone.keyboardOpen = false; Notifs.hideBanner()
      if (Phone.dryRun) { Notifs.clearEverything(); Phone.unlock() }
      Phone.home()
    }
  }
}
