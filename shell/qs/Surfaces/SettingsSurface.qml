import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Bluetooth
import qs.Commons
import qs.Services
import qs.Widgets

// Settings: Display, Sound, Bluetooth, Network, About. Opened from the gear
// tile in Shade.qml (or `ipc call shell settings`); a single scrollable list
// rather than a stack of sub-pages, small enough on this device that one
// screen covers it -- see docs/shell/DESIGN.md Non-goals, "A Settings/menu
// UI"; the SIP-account screen inside the Phone app is a separate, app-level
// settings surface (docs/phone/DESIGN.md), not this one.
//
// What's really wired here vs. a placeholder (be honest, this list is the
// PR description too): brightness and volume are Phone.qml's existing
// setBrightness()/setVolume() (already plumbed to ophone-sys ->
// brightnessctl/wpctl). Bluetooth reads and drives the real
// Quickshell.Bluetooth/bluez data source -- paired devices, connect()/
// disconnect(), the adapter's own on/off -- the same one Shade.qml's tile
// and StatusRow already use. Wi-Fi is a clearly-marked "not wired here yet"
// row: Shade.qml's Wi-Fi tile only flips the radio via nmcli, there is no
// SSID/network-selection data source in the shell yet, and this surface
// does not invent one. Kernel/uptime are `uname -r`/`uptime -p`, genuinely
// queried once when this first opens, not hardcoded strings.
//
// Keyboard: Tab/arrows (or Up/Down) move through the focusable rows
// (sliders, toggles, paired-device rows) -- headers/info/placeholder rows
// are skipped, the same way Shade.qml's own onKey() skips over its
// non-interactive rows. Left/Right nudge a focused slider by `step`.
// Enter/Space toggles/connects. Esc or the back chevron closes it -- the
// same affordance every other full-screen overlay here uses (Switcher,
// PowerMenu both close on Esc; there's no "back button" anywhere else to
// match since this is the first content page rather than a modal).
PanelWindow {
  id: settings
  visible: Phone.settingsOpen && !Phone.locked
  anchors { top: true; bottom: true; left: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.namespace: "ophone-settings"
  color: Theme.background
  WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

  readonly property var btAdapter: Bluetooth.defaultAdapter
  readonly property bool btOn: btAdapter ? btAdapter.enabled : false
  // Paired devices, not merely currently-connected ones -- "paired" is what
  // makes a connect/disconnect toggle meaningful here. Pairing itself is out
  // of scope for this surface (see shell/bin/ophone-btagentd and
  // docs/shell/DESIGN.md "Bluetooth pairing confirmation" for how a *new*
  // pairing is authorized).
  readonly property var pairedDevices: {
    const devs = Bluetooth.devices ? Bluetooth.devices.values : []
    return devs.filter(d => d.paired || d.bonded || d.connected)
  }

  // "Device" (About): the real target is the iPhone 6s (N71), but
  // shell/hypr/devices/ also has `generic` and `preview` profiles (this is
  // what's actually running under the desktop preview and CI's
  // --verify-config loop) -- OPHONE_DEVICE names whichever one is live, so
  // show that instead of always claiming real hardware that isn't there.
  readonly property string deviceLabel: {
    const d = Quickshell.env("OPHONE_DEVICE")
    return (!d || d === "iphone6s") ? "iPhone 6s (N71)" : d
  }

  // --- About: kernel/uptime, fetched once when Settings first opens.
  // Trivially available (plain `uname`/`uptime`, no root, no hardware
  // access) -- if either binary is missing (e.g. a minimal preview $PATH)
  // the row just stays at "unknown" rather than faking a value.
  property string kernelVersion: ""
  property string uptimeText: ""
  property bool sysInfoFetched: false
  Process { id: procUname; command: ["uname", "-r"]; running: false
            stdout: SplitParser { onRead: line => settings.kernelVersion = line } }
  Process { id: procUptime; command: ["uptime", "-p"]; running: false
            stdout: SplitParser { onRead: line => settings.uptimeText = line } }

  property int selF: -1   // index into focusRows (below); -1 = none, no ring
  onVisibleChanged: {
    selF = visible && Phone.takeByKey() ? 0 : -1
    if (visible && !sysInfoFetched) { sysInfoFetched = true; procUname.running = true; procUptime.running = true }
  }

  // Flat row model for the scrollable list. `kind` picks the delegate's
  // layout below; live values are read straight off Phone/Bluetooth in the
  // delegate itself (not copied into the row), so nothing here goes stale.
  readonly property var rows: {
    const out = []
    out.push({ kind: "header", text: "Display" })
    out.push({ kind: "brightness" })
    out.push({ kind: "header", text: "Sound" })
    out.push({ kind: "volume" })
    out.push({ kind: "silent" })
    out.push({ kind: "header", text: "Bluetooth" })
    out.push({ kind: "btAdapter" })
    if (settings.btOn) {
      if (settings.pairedDevices.length === 0) out.push({ kind: "btEmpty" })
      else for (const d of settings.pairedDevices) out.push({ kind: "btDevice", device: d })
    }
    out.push({ kind: "header", text: "Network" })
    out.push({ kind: "wifiPlaceholder" })
    out.push({ kind: "header", text: "About" })
    out.push({ kind: "aboutDevice" })
    out.push({ kind: "aboutShell" })
    out.push({ kind: "aboutKernel" })
    out.push({ kind: "aboutUptime" })
    return out
  }
  readonly property var focusKinds: ["brightness", "volume", "silent", "btAdapter", "btDevice"]
  readonly property var focusRows: {
    const out = []
    for (let i = 0; i < rows.length; i++) if (settings.focusKinds.indexOf(rows[i].kind) >= 0) out.push(i)
    return out
  }
  readonly property int selRow: selF >= 0 && selF < focusRows.length ? focusRows[selF] : -1
  onFocusRowsChanged: if (selF >= focusRows.length) selF = focusRows.length - 1
  onSelRowChanged: if (selRow >= 0) list.positionViewAtIndex(selRow, ListView.Contain)

  function adjustSlider(row, d) {
    if (row.kind === "brightness") Phone.setBrightness(Phone.brightness + 5 * d)
    else if (row.kind === "volume") Phone.setVolume(Phone.volume + 5 * d)
  }
  function activateRow(row) {
    if (row.kind === "silent") Phone.toggleSilent()
    else if (row.kind === "btAdapter") Phone.sys(["bluetooth", settings.btOn ? "off" : "on"])
    else if (row.kind === "btDevice") { if (row.device.connected) row.device.disconnect(); else row.device.connect() }
  }
  function onKey(ev) {
    const k = Phone.keyOf(ev), n = focusRows.length
    if (k === Qt.Key_Escape) { Phone.closeSettings(); return }
    // Home/End/PageUp/PageDown scroll the list directly rather than moving
    // the focus ring -- About and the Wi-Fi placeholder have nothing to
    // focus, but a keyboard-only user (docs/shell/DESIGN.md "Touch first,
    // keyboard complete") still has to be able to read them.
    if (k === Qt.Key_End) { if (n) selF = n - 1; list.positionViewAtEnd(); return }
    if (k === Qt.Key_Home) { selF = n ? 0 : -1; list.positionViewAtBeginning(); return }
    if (k === Qt.Key_PageDown) { list.contentY = Math.min(Math.max(0, list.contentHeight - list.height), list.contentY + list.height); return }
    if (k === Qt.Key_PageUp) { list.contentY = Math.max(0, list.contentY - list.height); return }
    if (selF < 0 && [Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab, Qt.Key_Backtab].indexOf(k) >= 0) { selF = n ? 0 : -1; return }
    if (!n) return
    if (k === Qt.Key_Tab || k === Qt.Key_Down) selF = (selF + 1) % n
    else if (k === Qt.Key_Backtab || k === Qt.Key_Up) selF = (selF - 1 + n) % n
    else if (k === Qt.Key_Left || k === Qt.Key_Right) {
      if (selRow >= 0) adjustSlider(rows[selRow], k === Qt.Key_Right ? 1 : -1)
    } else if (k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space) {
      if (selRow >= 0) activateRow(rows[selRow])
    }
  }
  Item { anchors.fill: parent; focus: true; Keys.onPressed: ev => { settings.onKey(ev); ev.accepted = true } }

  component Entry: Item {
    id: entry
    required property var modelData
    required property int index
    width: list.width
    readonly property bool focused: settings.selRow === index
    implicitHeight: body.implicitHeight

    Column {
      id: body
      width: parent.width
      spacing: Theme.px(4)

      Label {
        visible: entry.modelData.kind === "header"
        text: entry.modelData.text || ""
        size: 12; strong: true; color: Theme.dim
        topPadding: entry.index === 0 ? 0 : Theme.px(6)
      }

      Slider {
        visible: entry.modelData.kind === "brightness"
        width: parent.width
        glyph: "\u{f00df}"; label: "Brightness"; value: Phone.brightness
        focused: entry.focused
        onMoved: v => Phone.setBrightness(v)
      }
      Slider {
        visible: entry.modelData.kind === "volume"
        width: parent.width
        glyph: Phone.volume === 0 ? "\u{f075f}" : "\u{f057e}"; label: "Volume"; value: Phone.volume
        focused: entry.focused
        onMoved: v => Phone.setVolume(v)
      }

      SettingsRow {
        visible: entry.modelData.kind === "silent"
        width: parent.width
        glyph: Phone.silent ? "\u{f009b}" : "\u{f009a}"; title: "Silent mode"
        focused: entry.focused
        Switch { on: Phone.silent; onToggled: Phone.toggleSilent() }
      }

      SettingsRow {
        visible: entry.modelData.kind === "btAdapter"
        width: parent.width
        glyph: settings.btOn ? "\u{f00af}" : "\u{f00b2}"; title: "Bluetooth"
        subtitle: settings.btOn ? (settings.pairedDevices.length + " paired") : "Off"
        focused: entry.focused
        Switch { on: settings.btOn; onToggled: Phone.sys(["bluetooth", settings.btOn ? "off" : "on"]) }
      }
      SettingsRow {
        visible: entry.modelData.kind === "btEmpty"
        width: parent.width
        dim: true; title: "No paired devices"
      }
      SettingsRow {
        visible: entry.modelData.kind === "btDevice"
        width: parent.width
        readonly property var dev: entry.modelData.device
        glyph: "\u{f00b1}"
        title: dev ? (dev.name || dev.deviceName || dev.address) : ""
        subtitle: dev ? (dev.connected ? "Connected" + (dev.batteryAvailable ? " — " + Math.round(dev.battery * 100) + "%" : "") : "Not connected") : ""
        focused: entry.focused
        Switch {
          on: entry.modelData.device ? entry.modelData.device.connected : false
          onToggled: { const d = entry.modelData.device; if (d) { if (d.connected) d.disconnect(); else d.connect() } }
        }
      }

      SettingsRow {
        visible: entry.modelData.kind === "wifiPlaceholder"
        width: parent.width
        dim: true; glyph: "\u{f05aa}"; title: "Wi-Fi"
        subtitle: "Not wired here yet — the Wi-Fi driver/network stack is handled elsewhere"
      }

      SettingsRow { visible: entry.modelData.kind === "aboutDevice"; width: parent.width; title: "Device"; value: settings.deviceLabel }
      SettingsRow { visible: entry.modelData.kind === "aboutShell"; width: parent.width; title: "Shell"; value: Theme.productName + " " + Theme.version }
      SettingsRow { visible: entry.modelData.kind === "aboutKernel"; width: parent.width; title: "Kernel"; value: settings.kernelVersion || "unknown" }
      SettingsRow { visible: entry.modelData.kind === "aboutUptime"; width: parent.width; title: "Uptime"; value: settings.uptimeText || "unknown" }
    }
  }

  Item {
    id: header
    anchors.top: parent.top
    width: parent.width; height: Theme.px(52)
    Glyph {
      id: back
      x: Theme.pad; anchors.verticalCenter: parent.verticalCenter
      text: "\u{f0141}"; size: 22
      TapHandler { onTapped: Phone.closeSettings() }
    }
    Label { anchors.centerIn: parent; text: "Settings"; size: 16; strong: true }
  }

  ListView {
    id: list
    anchors.top: header.bottom; anchors.bottom: parent.bottom
    anchors.left: parent.left; anchors.right: parent.right
    anchors.margins: Theme.pad
    clip: true
    spacing: Theme.px(10)
    model: settings.rows
    delegate: Entry {}
  }
}
