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
  TapToCallBanner {}
  Osd {}
  Shade {}
  Switcher {}
  PowerMenu {}
  SettingsSurface {}
  CallSurface {}
  LockScreen {}

  // Hardware keys: Hyprland binds dispatch hl.dsp.global("ophone:<name>").
  GlobalShortcut { appid: "ophone"; name: "home"; description: "Home button"; onPressed: Phone.homePressed() }
  GlobalShortcut { appid: "ophone"; name: "power"; description: "Power button"; onPressed: Phone.powerPressed(); onReleased: Phone.powerReleased() }
  GlobalShortcut { appid: "ophone"; name: "volume-up"; description: "Volume up"; onPressed: Phone.volumeUp() }
  GlobalShortcut { appid: "ophone"; name: "volume-down"; description: "Volume down"; onPressed: Phone.volumeDown() }
  GlobalShortcut { appid: "ophone"; name: "mute"; description: "Ring/silent switch"; onPressed: Phone.toggleSilent() }
  GlobalShortcut { appid: "ophone"; name: "switcher"; description: "App switcher"; onPressed: { Phone.byKey = !Phone.switcherOpen; Phone.toggleSwitcher() } }
  GlobalShortcut { appid: "ophone"; name: "shade"; description: "Notifications and quick settings"; onPressed: { Phone.byKey = Phone.shade === 0; Phone.toggleShade() } }
  GlobalShortcut { appid: "ophone"; name: "power-menu"; description: "Power menu"; onPressed: { Phone.byKey = !Phone.powerMenuOpen; Phone.togglePowerMenu() } }
  GlobalShortcut { appid: "ophone"; name: "lock"; description: "Lock"; onPressed: Phone.lock() }
  GlobalShortcut { appid: "ophone"; name: "keyboard"; description: "On-screen keyboard"; onPressed: Phone.toggleKeyboard() }

  // Scripting / test surface: qs -p shell/qs ipc call shell <fn> [args]
  // (shell/bin/ophone-ctl wraps this.)
  IpcHandler {
    target: "shell"
    function ping(): string { return "pong " + Notifs.count }
    function home(): void { Phone.home() }
    function switcher(): void { Phone.showSwitcher() }
    function shade(): void { Phone.openShade() }
    function closeShade(): void { Phone.closeShade() }
    function keyboard(): void { Phone.toggleKeyboard() }
    function isKeyboardOpen(): bool { return Phone.keyboardOpen }
    // Preview/test helper: which layout the focused field's content purpose
    // selected (qwerty, numeric, phone, email, url, password) and the raw
    // purpose ophone-im reported it from (normal, numeric, phone, email,
    // url, password -- see shell/im/ophone-im.c).
    function keyboardLayout(): string { return Phone.keyboardLayout }
    function contentPurpose(): string { return Phone.imPurpose }
    // Preview/test helper: type text through the input method when a field
    // is focused (falls back to nothing if none is -- Keyboard.qml is the
    // real typing path for wtype-driven keys).
    function typeText(text: string): void { Phone.imCommit(text) }
    function lock(): void { Phone.lock() }
    function pin(): void { if (Phone.locked) Phone.pinVisible = true }
    function powerMenu(): void { Phone.powerMenu() }
    function settings(): void { Phone.openSettings() }
    function closeSettings(): void { Phone.closeSettings() }
    function isSettingsOpen(): bool { return Phone.settingsOpen }
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
    // Preview/test helpers for tap-to-call (docs/phone/DESIGN.md §4.1):
    // JSON list of numbers currently detected in the clipboard, and
    // whether the chip is actually showing (false while locked, even with
    // numbers detected -- see TapToCallBanner.qml).
    function tapToCallNumbers(): string { return JSON.stringify(NumberDetect.current) }
    function tapToCallVisible(): bool { return NumberDetect.current.length > 0 && !Phone.locked }
    // Simulates tapping the first chip, without needing a synthetic touch
    // event in the preview: the same call TapToCallCard's onDial makes.
    function tapToCallDial(): void {
      if (NumberDetect.current.length > 0) Phone.dialNumber(NumberDetect.current[0].uri)
      NumberDetect.clear()
    }
    // JSON list of current notifications (for app developers and tests).
    function notifications(): string {
      return JSON.stringify(Notifs.list.map(n => ({ id: n.id, app: n.appName, summary: n.summary, body: n.body,
        category: Notifs.category(n), urgency: n.urgency, hints: Object.keys(n.hints || {}),
        actions: n.actions.map(a => a.identifier) })))
    }
    // Preview helper: back to a clean home screen. Unlocks only in dry-run mode.
    function reset(): void {
      Phone.closeOverlays(); Phone.resetKeyboard(); Notifs.hideBanner(); NumberDetect.clear()
      if (Phone.dryRun) { Notifs.clearEverything(); Phone.unlock() }
      Phone.home()
    }
  }
}
