import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Networking
import Quickshell.Bluetooth
import qs.Commons
import qs.Services
import qs.Widgets

// Pull-down shade: quick settings, brightness, notifications.
// Phone.shade (0..1) drives it, so it follows the finger while dragging.
// Keyboard: arrows/Tab move over the 9 tiles, the brightness bar and the
// notifications. Enter/Space toggles or opens, Left/Right on the bar changes
// brightness, Delete dismisses a notification (Shift+Delete: all), Esc closes.
PanelWindow {
  id: shade
  visible: Phone.shade > 0 && !Phone.locked
  anchors { top: true; bottom: true; left: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.namespace: "ophone-shade"
  color: "transparent"
  WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

  // Keyboard selection: 0..7 tiles, 8 brightness, 9.. notifications. -1 = none.
  readonly property int nTiles: 9
  readonly property int brightIdx: nTiles
  property int sel: -1
  readonly property int total: nTiles + 1 + notifList.count
  onVisibleChanged: sel = visible && Phone.takeByKey() ? 0 : -1
  onTotalChanged: if (sel >= total) sel = total - 1
  onSelChanged: if (sel > brightIdx) notifList.positionViewAtIndex(sel - brightIdx - 1, ListView.Contain)
  function notifAt(i) { return notifList.model[i - brightIdx - 1] }
  function onKey(ev) {
    const k = Phone.keyOf(ev), s = sel
    if (k === Qt.Key_Escape) { Phone.closeShade(); return }
    if (s < 0 && [Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab, Qt.Key_Backtab].indexOf(k) >= 0) { sel = 0; return }
    if (k === Qt.Key_Tab) sel = (s + 1) % total
    else if (k === Qt.Key_Backtab) sel = (s - 1 + total) % total
    else if (k === Qt.Key_Down) sel = s < nTiles ? (s + 4 < nTiles ? s + 4 : brightIdx) : Math.min(total - 1, s + 1)
    else if (k === Qt.Key_Up) sel = s < nTiles ? (s >= 4 ? s - 4 : s) : s === brightIdx ? 4 : s - 1
    else if (k === Qt.Key_Left || k === Qt.Key_Right) {
      const d = k === Qt.Key_Right ? 1 : -1
      if (s === brightIdx) Phone.setBrightness(Phone.brightness + 10 * d)
      else if (s < nTiles) sel = Math.max(0, Math.min(nTiles - 1, s + d))
    } else if (k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space) {
      if (s >= 0 && s < nTiles) tiles.children[s].toggled()
      else if (s > brightIdx && notifAt(s)) Notifs.activate(notifAt(s))
    } else if (k === Qt.Key_Delete || k === Qt.Key_Backspace) {
      if (ev.modifiers & Qt.ShiftModifier) Notifs.clearAll()
      else if (s > brightIdx && notifAt(s)) notifAt(s).dismiss()
    }
  }
  Item { anchors.fill: parent; focus: true; Keys.onPressed: ev => { shade.onKey(ev); ev.accepted = true } }

  Rectangle {
    anchors.fill: parent
    color: "black"; opacity: 0.5 * Phone.shade
    TapHandler { onTapped: Phone.closeShade() }
  }

  Rectangle {
    id: panel
    width: parent.width
    height: parent.height
    y: (Phone.shade - 1) * height
    color: Theme.background

    StatusRow { id: status; width: parent.width }

    SystemClock { id: clock; precision: SystemClock.Minutes }
    Row {
      id: dateRow
      anchors.top: status.bottom
      x: Theme.px(16)
      spacing: Theme.px(10)
      Label { text: Qt.formatTime(clock.date, "HH:mm"); size: 30; font.weight: Font.Light }
      Label { anchors.baseline: parent.children[0].baseline; text: Qt.formatDate(clock.date, "ddd d MMM"); size: 14; color: Theme.dim }
    }

    Grid {
      id: tiles
      anchors.top: dateRow.bottom; anchors.topMargin: Theme.px(10)
      anchors.horizontalCenter: parent.horizontalCenter
      columns: 4
      spacing: Theme.px(8)
      Tile { glyph: Networking.wifiEnabled ? "\u{f05a9}" : "\u{f05aa}"; focused: shade.sel === 0; label: "Wi-Fi"; on: Networking.wifiEnabled
             onToggled: Phone.sys(["wifi", Networking.wifiEnabled ? "off" : "on"]) }
      Tile { readonly property bool bt: Bluetooth.defaultAdapter ? Bluetooth.defaultAdapter.enabled : false
             glyph: bt ? "\u{f00af}" : "\u{f00b2}"; focused: shade.sel === 1; label: "Bluetooth"; on: bt
             onToggled: Phone.sys(["bluetooth", bt ? "off" : "on"]) }
      Tile { glyph: Phone.silent ? "\u{f009b}" : "\u{f009a}"; focused: shade.sel === 2; label: "Silent"; on: Phone.silent; onToggled: Phone.toggleSilent() }
      Tile { glyph: "\u{f001d}"; focused: shade.sel === 3; label: "Airplane"; on: Phone.airplane; onToggled: Phone.toggleAirplane() }
      Tile { glyph: Phone.flashlight ? "\u{f0244}" : "\u{f0245}"; focused: shade.sel === 4; label: "Torch"; on: Phone.flashlight; onToggled: Phone.toggleFlashlight() }
      Tile { glyph: Phone.rotationLock ? "\u{f0478}" : "\u{f0475}"; focused: shade.sel === 5; label: "Rotation"; on: Phone.rotationLock; onToggled: Phone.toggleRotationLock() }
      Tile { glyph: "\u{f030c}"; focused: shade.sel === 6; label: "Keyboard"; on: Phone.keyboardOpen; onToggled: { Phone.toggleKeyboard(); Phone.closeShade() } }
      Tile { glyph: "\u{f033e}"; focused: shade.sel === 7; label: "Lock"; onToggled: Phone.lock() }
      Tile { glyph: "\u{f0493}"; focused: shade.sel === 8; label: "Settings"; onToggled: Phone.openSettings() }
    }

    // Brightness slider
    Rectangle {
      id: bright
      anchors.top: tiles.bottom; anchors.topMargin: Theme.px(10)
      anchors.horizontalCenter: parent.horizontalCenter
      width: tiles.width; height: Theme.px(40); radius: height / 2
      color: Theme.surface
      Rectangle {
        width: Math.max(height, parent.width * Phone.brightness / 100); height: parent.height; radius: height / 2
        color: Theme.alpha(Theme.accent, 0.8)
      }
      FocusRing { shown: shade.sel === shade.brightIdx; gap: 3 }
      Glyph { x: Theme.px(12); anchors.verticalCenter: parent.verticalCenter; text: "\u{f00df}"; size: 18; color: Theme.background }
      DragHandler {
        target: null; yAxis.enabled: false
        onCentroidChanged: if (active) Phone.setBrightness(100 * centroid.position.x / bright.width)
      }
      TapHandler { onTapped: (ev) => Phone.setBrightness(100 * ev.position.x / bright.width) }
    }

    Item {
      id: notifHeader
      anchors.top: bright.bottom; anchors.topMargin: Theme.px(14)
      x: Theme.px(12); width: parent.width - Theme.px(24); height: Theme.px(28)
      Label { anchors.verticalCenter: parent.verticalCenter; text: Notifs.count ? "Notifications" : "No notifications"; size: 13; color: Theme.dim; strong: true }
      Rectangle {
        visible: Notifs.count > 0
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        height: Theme.px(26); width: clr.implicitWidth + Theme.px(20); radius: height / 2; color: Theme.surface
        Label { id: clr; anchors.centerIn: parent; text: "Clear"; size: 12 }
        TapHandler { onTapped: Notifs.clearAll() }
      }
    }

    ListView {
      id: notifList
      anchors.top: notifHeader.bottom; anchors.topMargin: Theme.px(6)
      anchors.bottom: handle.top
      x: Theme.px(12); width: parent.width - Theme.px(24)
      clip: true
      spacing: Theme.px(8)
      model: Notifs.feed.slice().reverse()
      delegate: NotificationCard { required property var modelData; required property int index; notification: modelData
                                   focused: shade.sel === shade.brightIdx + 1 + index }
    }

    // Grab handle: drag up (or tap) to close.
    Item {
      id: handle
      anchors.bottom: parent.bottom
      width: parent.width; height: Theme.px(34)
      Rectangle { anchors.centerIn: parent; width: Theme.px(44); height: Theme.px(5); radius: height / 2; color: Theme.dim }
      DragHandler {
        target: null; xAxis.enabled: false
        onTranslationChanged: if (active) Phone.shade = Math.max(0, Math.min(1, 1 + translation.y / panel.height))
        onActiveChanged: if (!active) Phone.settleShade(centroid.velocity.y)
      }
      TapHandler { onTapped: Phone.closeShade() }
    }
  }
}
