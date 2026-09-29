import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import qs.Commons
import qs.Services
import qs.Widgets

// App switcher: one card per open window (foreign-toplevel list), newest
// first. Tap a card to switch, flick it up to close the app, tap the
// background to go back. Thumbnails are captured once when the switcher
// opens (live: false), since live capture is too costly without a GPU.
// Keyboard: Left/Right (or Tab) selects a card, Enter switches to it,
// Delete closes that app (Shift+Delete: all), Esc goes back.
PanelWindow {
  id: sw
  visible: Phone.switcherOpen && !Phone.locked
  anchors { top: true; bottom: true; left: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.namespace: "ophone-switcher"
  color: Theme.alpha(Theme.background, 0.94)
  WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

  readonly property var windows: ToplevelManager.toplevels.values.slice().reverse()

  TapHandler { onTapped: Phone.switcherOpen = false }

  property int sel: -1               // keyboard selection; -1 = none
  onVisibleChanged: sel = visible && Phone.takeByKey() && windows.length ? 0 : -1
  onSelChanged: if (sel >= 0) cards.positionViewAtIndex(sel, ListView.Center)
  readonly property int count: windows.length
  onCountChanged: if (sel >= count) sel = count - 1
  function onKey(ev) {
    const k = Phone.keyOf(ev), n = windows.length
    if (k === Qt.Key_Escape) { Phone.switcherOpen = false; return }
    if (!n) return
    if (sel < 0 && [Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab, Qt.Key_Backtab].indexOf(k) >= 0) { sel = 0; return }
    if (k === Qt.Key_Right || k === Qt.Key_Down || k === Qt.Key_Tab) sel = Math.min(n - 1, sel + 1)
    else if (k === Qt.Key_Left || k === Qt.Key_Up || k === Qt.Key_Backtab) sel = Math.max(0, sel - 1)
    else if (k === Qt.Key_Home) sel = 0
    else if (k === Qt.Key_End) sel = n - 1
    else if (k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space) {
      windows[Math.max(0, sel)].activate(); Phone.switcherOpen = false
    } else if (k === Qt.Key_Delete || k === Qt.Key_Backspace) {
      if (ev.modifiers & Qt.ShiftModifier) { for (const t of windows) t.close(); Phone.home() }
      else if (sel >= 0) windows[sel].close()
    }
  }
  Item { anchors.fill: parent; focus: true; Keys.onPressed: ev => { sw.onKey(ev); ev.accepted = true } }

  Label {
    anchors.centerIn: parent
    visible: sw.windows.length === 0
    text: "No open apps"; size: 16; color: Theme.dim
  }

  ListView {
    id: cards
    anchors.fill: parent
    anchors.topMargin: Theme.statusH + Theme.px(30)
    anchors.bottomMargin: Theme.navH + Theme.px(60)
    orientation: ListView.Horizontal
    spacing: Theme.px(14)
    leftMargin: (width - cardW) / 2; rightMargin: leftMargin
    snapMode: ListView.SnapToItem
    readonly property int cardW: Math.round(width * 0.68)
    model: sw.windows

    delegate: Item {
      id: slot
      required property var modelData
      required property int index
      width: cards.cardW; height: cards.height

      Column {
        id: card
        width: parent.width
        y: drag.active ? Math.min(0, drag.translation.y) : 0
        opacity: 1 + y / (slot.height * 0.8)
        spacing: Theme.px(8)
        Behavior on y { enabled: !drag.active; NumberAnimation { duration: 120 } }

        Row {
          spacing: Theme.px(8)
          IconImage {
            implicitSize: Theme.px(22)
            source: {
              const e = DesktopEntries.heuristicLookup(slot.modelData.appId)
              return Quickshell.iconPath(e ? e.icon : slot.modelData.appId, true)
            }
          }
          Label { text: slot.modelData.title || slot.modelData.appId; size: 13; width: card.width - Theme.px(30); anchors.verticalCenter: parent.verticalCenter }
        }
        Rectangle {
          width: parent.width; height: cards.height - Theme.px(30)
          radius: Theme.radius; color: Theme.surface
          FocusRing { shown: sw.sel === slot.index }
          ScreencopyView {
            anchors.fill: parent
            captureSource: sw.visible ? slot.modelData : null
            live: false
          }
        }
      }
      TapHandler { onTapped: { slot.modelData.activate(); Phone.switcherOpen = false } }
      DragHandler {
        id: drag
        target: null; xAxis.enabled: false
        onActiveChanged: if (!active && translation.y < -slot.height * 0.25) slot.modelData.close()
      }
    }
  }

  Row {
    anchors.bottom: parent.bottom; anchors.bottomMargin: Theme.navH + Theme.px(12)
    anchors.horizontalCenter: parent.horizontalCenter
    visible: sw.windows.length > 0
    RoundButton { glyph: "\u{f0156}"; caption: "Close all"; diameter: 44; glyphSize: 18
                  onClicked: { for (const t of sw.windows) t.close(); Phone.home() } }
  }
}
