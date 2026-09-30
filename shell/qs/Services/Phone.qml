pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Bluetooth

// Shell-wide state and actions. Surfaces bind to these properties; the
// hardware keys, gestures and IPC all end up calling these functions.
Singleton {
  id: root

  readonly property bool dryRun: Quickshell.env("OPHONE_DRY_RUN") === "1"
  readonly property string shellDir: Quickshell.env("OPHONE_SHELL") || Quickshell.shellDir + "/.."
  readonly property int homeWorkspace: 1
  readonly property int appWorkspace: 2

  // --- surface state
  // F4 (security review): this used to default to false unconditionally, so
  // a freshly booted phone came up fully unlocked until someone pressed
  // power once. It now starts locked whenever a lock-screen PIN is
  // configured (see pinConfigured below) -- and stays unlocked at boot only
  // when there's genuinely no PIN to unlock with, so this can never brick a
  // device that hasn't been provisioned yet. dryRun (the preview) is always
  // unlocked at boot so the existing scenarios are unaffected.
  property bool locked: false
  property bool pinVisible: false
  property real shade: 0            // 0 = closed .. 1 = fully open
  property bool shadeDragging: false
  property bool switcherOpen: false
  property bool keyboardOpen: false
  // Focus-driven state (see "On-screen keyboard" below): keyboardOpen is
  // derived from these, never set directly by anything but this block.
  property bool imAvailable: false     // ophone-im bound input-method-v2 (no other IME running)
  property bool imFieldFocused: false  // a text-input is currently focused
  property bool keyboardPinned: false     // manually forced open
  property bool keyboardSuppressed: false // manually forced closed while still focused
  // The focused field's content purpose, as decoded by ophone-im from the
  // input-method-v2 content_type event (see shell/im/ophone-im.c): one of
  // normal, numeric, phone, email, url, password. "normal" whenever nothing
  // is focused or the field never set a purpose (most fields never do).
  property string imPurpose: "normal"
  // Keyboard.qml's layout choice, derived from imPurpose. A manual toggle or
  // hardware keyboard never changes this: it only affects keyboardOpen.
  readonly property string keyboardLayout: {
    switch (imPurpose) {
      case "numeric": return "numeric"
      case "phone": return "phone"
      case "password": return "password"
      case "email": return "email"
      case "url": return "url"
      default: return "qwerty"
    }
  }
  readonly property bool hardwareKeyboardConnected: {
    const devs = Bluetooth.devices ? Bluetooth.devices.values : []
    for (const d of devs) if (d.connected && d.icon === "input-keyboard") return true
    return false
  }
  onHardwareKeyboardConnectedChanged: updateKeyboardVisibility()
  function updateKeyboardVisibility() {
    keyboardOpen = keyboardPinned || (imFieldFocused && !keyboardSuppressed && !hardwareKeyboardConnected)
  }
  // Called by ophone-im (see the Process below) when a text-input-v3 field
  // gains/loses focus. A hardware keyboard suppresses the auto-show only;
  // the manual toggle (toggleKeyboard) always works regardless.
  function imFocusIn() { imFieldFocused = true; keyboardSuppressed = false; updateKeyboardVisibility() }
  function imFocusOut() { imFieldFocused = false; keyboardPinned = false; keyboardSuppressed = false; imPurpose = "normal"; updateKeyboardVisibility() }
  // SUPER+K, the nav-bar glyph and the shade tile all call this.
  function toggleKeyboard() {
    if (keyboardOpen) { keyboardPinned = false; keyboardSuppressed = true }
    else { keyboardPinned = true; keyboardSuppressed = false }
    updateKeyboardVisibility()
  }
  // Plain characters go through the input method when one is focused (the
  // correct path for apps that speak text-input-v3); everything else
  // (backspace, Enter, and anything whenever no field is focused, e.g. a
  // terminal) still goes through wtype in Keyboard.qml -- see there for why
  // backspace doesn't use delete_surrounding_text.
  function imCommit(text) { if (imAvailable && imFieldFocused) imWatch.write("T" + text + "\n") }
  // Force it closed, e.g. leaving the app entirely (home/lock): don't let a
  // stale "still focused" reopen it next tick.
  function resetKeyboard() { keyboardPinned = false; keyboardSuppressed = false; keyboardOpen = false }

  Process {
    id: imWatch
    command: [shellDir + "/bin/ophone-im"]
    running: true
    stdinEnabled: true
    stdout: SplitParser {
      onRead: line => {
        if (line === "active") { root.imAvailable = true; root.imFocusIn() }
        else if (line === "inactive") { root.imFocusOut() }
        else if (line.startsWith("content ")) { root.imPurpose = line.slice(8) }
        else if (line === "unavailable") {
          root.imAvailable = false
          root.imFocusOut()
          console.warn("omarchy-phone: another input method is already running; on-screen keyboard needs the manual toggle")
        }
      }
    }
    onExited: (code, status) => {
      // Whatever imFieldFocused was, it's meaningless now: nothing is
      // listening for the next real activate/deactivate until the process
      // restarts, and Keyboard.qml must not keep routing keys at an
      // ophone-im that isn't there (imCommit/imBackspace no-op once
      // imAvailable is false, but imFieldFocused staying true would still
      // leave the *visible* keyboard silently swallowing keystrokes instead
      // of falling back to wtype).
      imAvailable = false
      imFocusOut()
      if (code !== 0) imRestart.restart() // missing binary, protocol not supported, etc: back off and retry
    }
  }
  Timer { id: imRestart; interval: 4000; onTriggered: { imWatch.running = false; imWatch.running = true } }

  property bool powerMenuOpen: false
  property bool settingsOpen: false
  property bool screenOn: true
  readonly property bool anyOverlay: shade > 0 || switcherOpen || powerMenuOpen || settingsOpen
  // Set by the keyboard shortcuts just before they open a surface, so it
  // opens with the focus ring on its first item (touch opens it without one).
  property bool byKey: false
  function takeByKey() { const k = byKey; byKey = false; return k }
  // Shift+Tab arrives as Backtab from a real keyboard but as Tab+Shift from
  // some (virtual) ones; surfaces read keys through this.
  function keyOf(ev) { return ev.key === Qt.Key_Tab && (ev.modifiers & Qt.ShiftModifier) ? Qt.Key_Backtab : ev.key }
  signal homeRequested()           // home pressed: the home screen clears its search
  readonly property bool atHome: Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id === homeWorkspace : true

  // --- lock-screen PIN (docs/shell/DESIGN.md "Lock screen PIN")
  // Fail-safe (docs/phone/API.md "Shell hooks"): $XDG_RUNTIME_DIR is per-session tmpfs, so a
  // stale "off" from a previous run could never survive a crash -- except that it would, since
  // nothing else clears it. Publish "on" unconditionally before boot lock state is even decided,
  // so a crash/restart always comes back private until _decideBootLock (below) says otherwise.
  Component.onCompleted: sys(["locked", "on"])
  readonly property string pinFile: Quickshell.env("OPHONE_PIN_FILE") || "/etc/omarchy-phone/pin-hash"
  property bool pinConfigured: false
  property bool _bootLockDecided: false
  FileView {
    path: root.pinFile
    printErrors: false
    watchChanges: true
    onFileChanged: reload()
    onLoaded: { root.pinConfigured = true; root._decideBootLock() }
    onLoadFailed: { root.pinConfigured = false; root._decideBootLock() }
  }
  function _decideBootLock() {
    if (_bootLockDecided) return
    _bootLockDecided = true
    if (!dryRun && pinConfigured) locked = true
    sys(["locked", locked ? "on" : "off"])
  }

  // --- idle auto-lock (docs/shell/DESIGN.md "Idle auto-lock"): Hyprland's
  // ext-idle-notify-v1, the same protocol swaylock/hypridle use, consumed
  // directly through Quickshell's own wrapper (no hypridle process, no extra
  // dependency -- idiomatic for this codebase, which already leans on
  // Quickshell.Wayland for WlSessionLock rather than a separate lock binary).
  // Locking requires a configured PIN for the same reason the boot lock
  // does; the screen still blanks either way, to save power.
  IdleMonitor {
    id: idleMonitor
    enabled: true
    respectInhibitors: true
    timeout: {
      // Seconds, not milliseconds: verified empirically (see docs/shell/DESIGN.md
      // "Idle auto-lock") -- IdleMonitor.timeout: 3 marks idle at ~3s.
      const override = Quickshell.env("OPHONE_IDLE_SECONDS")
      const n = override ? parseInt(override) : Config.idleLockSeconds
      return Number.isFinite(n) ? n : Config.idleLockSeconds
    }
    onIsIdleChanged: {
      if (!isIdle || !root.screenOn) return
      if (root.pinConfigured) root.lock()
      root.screenOff()
    }
  }

  // --- device state the shell owns
  property bool silent: false
  property int volume: 50
  property int brightness: 70
  property bool flashlight: false
  property bool rotationLock: true
  property bool airplane: false

  // --- OSD
  property string osdIcon: ""
  property string osdLabel: ""
  property int osdValue: -1
  property int osdSerial: 0
  function showOsd(icon, label, value) {
    osdIcon = icon; osdLabel = label; osdValue = value === undefined ? -1 : value
    osdSerial++
  }

  // --- helpers
  function sys(args) {
    Quickshell.execDetached([shellDir + "/bin/ophone-sys"].concat(args))
  }
  function hypr(expr) { Hyprland.dispatch(expr) }

  function closeOverlays() {
    closeShade(); switcherOpen = false; powerMenuOpen = false; settingsOpen = false
  }

  // --- navigation
  function home() {
    if (locked) { pinVisible = false; return }
    homeRequested()
    const hadOverlay = anyOverlay
    closeOverlays()
    resetKeyboard()
    if (!hadOverlay || !atHome) hypr('hl.dsp.focus({ workspace = "' + homeWorkspace + '" })')
  }
  function showSwitcher() { if (locked) return; closeShade(); powerMenuOpen = false; switcherOpen = true }
  function toggleSwitcher() { if (switcherOpen) switcherOpen = false; else showSwitcher() }
  function nextApp() { hypr('hl.dsp.focus({ direction = "r" })') }
  function prevApp() { hypr('hl.dsp.focus({ direction = "l" })') }
  function launch(entry) {
    closeOverlays()
    entry.execute()
    hypr('hl.dsp.focus({ workspace = "' + appWorkspace + '" })')
  }

  // --- shade (animated from any value to open/closed)
  NumberAnimation { id: shadeAnim; target: root; property: "shade"; duration: 180; easing.type: Easing.OutCubic }
  function openShade() { if (locked) return; switcherOpen = false; shadeAnim.to = 1; shadeAnim.restart() }
  function closeShade() { if (shade === 0) return; shadeAnim.to = 0; shadeAnim.restart() }
  function toggleShade() { if (shade > 0) closeShade(); else openShade() }
  function settleShade(velocity) {
    if (velocity > 300 || (velocity > -300 && shade > 0.4)) openShade(); else closeShade()
  }

  // --- lock / screen
  function lock() { byKey = false; closeOverlays(); resetKeyboard(); pinVisible = false; locked = true; sys(["locked", "on"]) }
  function unlock() { byKey = false; locked = false; pinVisible = false; sys(["locked", "off"]) }
  function screenOff() { screenOn = false; hypr('hl.dsp.dpms({ action = "disable" })') }
  function screenOnNow() { screenOn = true; hypr('hl.dsp.dpms({ action = "enable" })') }

  // Power key: short press toggles the screen (locking on the way off),
  // long press opens the power menu.
  Timer { id: powerHold; interval: 600; onTriggered: { root.powerLongFired = true; root.powerMenu() } }
  property bool powerLongFired: false
  function powerPressed() { powerLongFired = false; powerHold.restart() }
  function powerReleased() {
    if (!powerHold.running) return
    powerHold.stop()
    if (powerLongFired) return
    if (screenOn) { lock(); screenOff() } else screenOnNow()
  }
  function powerMenu() {
    if (!screenOn) screenOnNow()
    closeShade(); switcherOpen = false; powerMenuOpen = true
  }

  function togglePowerMenu() { if (powerMenuOpen) powerMenuOpen = false; else powerMenu() }

  // Settings (docs/shell/DESIGN.md Non-goals: "A Settings/menu UI" -- the
  // gear tile in Shade.qml opens this). Same shape as showSwitcher()/
  // powerMenu(): closes whatever else is open first.
  function openSettings() { if (locked) return; closeShade(); switcherOpen = false; powerMenuOpen = false; settingsOpen = true }
  function closeSettings() { settingsOpen = false }
  function toggleSettings() { if (settingsOpen) closeSettings(); else openSettings() }

  // Home key: single press = home, double press = switcher.
  Timer { id: homeDouble; interval: 300; onTriggered: root.home() }
  function homePressed() {
    if (!screenOn) { screenOnNow(); return }
    if (homeDouble.running) { homeDouble.stop(); showSwitcher() } else homeDouble.restart()
  }

  // --- audio keys
  property var ringingCall: null      // set by Notifs when a call is ringing
  signal silenceRinger()
  function volumeUp() { setVolume(volume + 5) }
  function volumeDown() {
    if (ringingCall) { silenceRinger(); return }
    setVolume(volume - 5)
  }
  function setVolume(v) {
    volume = Math.max(0, Math.min(100, v))
    sys(["volume", String(volume)])
    showOsd(volume === 0 ? "\u{f075f}" : "\u{f057e}", "Volume", volume)
  }
  function toggleSilent() {
    silent = !silent
    sys(["silent", silent ? "on" : "off"])
    showOsd(silent ? "\u{f009b}" : "\u{f009a}", silent ? "Silent" : "Ringer on")
  }

  // --- quick settings
  function setBrightness(v) { brightness = Math.max(1, Math.min(100, Math.round(v))); sys(["brightness", String(brightness)]) }
  function toggleFlashlight() { flashlight = !flashlight; sys(["flashlight", flashlight ? "on" : "off"]) }
  function toggleRotationLock() { rotationLock = !rotationLock; sys(["rotation-lock", rotationLock ? "on" : "off"]) }
  function toggleAirplane() { airplane = !airplane; sys(["airplane", airplane ? "on" : "off"]) }
}
