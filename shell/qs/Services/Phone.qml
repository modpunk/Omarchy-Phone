pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Hyprland

// Shell-wide state and actions. Surfaces bind to these properties; the
// hardware keys, gestures and IPC all end up calling these functions.
Singleton {
  id: root

  readonly property bool dryRun: Quickshell.env("OPHONE_DRY_RUN") === "1"
  readonly property string shellDir: Quickshell.env("OPHONE_SHELL") || Quickshell.shellDir + "/.."
  readonly property int homeWorkspace: 1
  readonly property int appWorkspace: 2

  // --- surface state
  property bool locked: false
  property bool pinVisible: false
  property real shade: 0            // 0 = closed .. 1 = fully open
  property bool shadeDragging: false
  property bool switcherOpen: false
  property bool keyboardOpen: false
  property bool powerMenuOpen: false
  property bool screenOn: true
  readonly property bool atHome: Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id === homeWorkspace : true

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
    closeShade(); switcherOpen = false; powerMenuOpen = false
  }

  // --- navigation
  function home() {
    if (locked) { pinVisible = false; return }
    const hadOverlay = shade > 0 || switcherOpen || powerMenuOpen
    closeOverlays()
    keyboardOpen = false
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
  function settleShade(velocity) {
    if (velocity > 300 || (velocity > -300 && shade > 0.4)) openShade(); else closeShade()
  }

  // --- lock / screen
  function lock() { closeOverlays(); keyboardOpen = false; pinVisible = false; locked = true }
  function unlock() { locked = false; pinVisible = false }
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
