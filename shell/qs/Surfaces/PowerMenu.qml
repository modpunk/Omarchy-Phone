import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Services
import qs.Widgets

// Long-press Power. Keyboard: arrows/Tab select, Enter activates, Esc cancels.
PanelWindow {
  id: pm
  visible: Phone.powerMenuOpen
  anchors { top: true; bottom: true; left: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.namespace: "ophone-power"
  color: Theme.alpha(Theme.background, 0.92)
  WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

  property int sel: -1               // 0..3 in the grid below; -1 = none
  onVisibleChanged: sel = visible && Phone.takeByKey() ? 0 : -1
  function onKey(ev) {
    const k = Phone.keyOf(ev)
    if (k === Qt.Key_Escape) { Phone.powerMenuOpen = false; return }
    const step = { [Qt.Key_Left]: -1, [Qt.Key_Right]: 1, [Qt.Key_Up]: -2, [Qt.Key_Down]: 2, [Qt.Key_Tab]: 1, [Qt.Key_Backtab]: -1 }[k]
    if (step !== undefined) {
      if (sel < 0) sel = 0
      else if (k === Qt.Key_Tab || k === Qt.Key_Backtab) sel = (sel + step + 4) % 4
      else if (sel + step >= 0 && sel + step < 4 && (Math.abs(step) === 2 || Math.floor((sel + step) / 2) === Math.floor(sel / 2))) sel += step
    } else if ((k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space) && sel >= 0) {
      buttons.children[sel].clicked()
    }
  }
  Item { anchors.fill: parent; focus: true; Keys.onPressed: ev => { pm.onKey(ev); ev.accepted = true } }

  TapHandler { onTapped: Phone.powerMenuOpen = false }

  Column {
    anchors.centerIn: parent
    spacing: Theme.px(28)
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: Theme.productName; size: 18; strong: true }
    Grid {
      id: buttons
      anchors.horizontalCenter: parent.horizontalCenter
      columns: 2; spacing: Theme.px(36)
      RoundButton { glyph: "\u{f0425}"; caption: "Power off"; focused: pm.sel === 0; fill: Theme.urgent; ink: "white"; diameter: 72
                    onClicked: { Phone.powerMenuOpen = false; Phone.sys(["poweroff"]) } }
      RoundButton { glyph: "\u{f0709}"; caption: "Restart"; focused: pm.sel === 1; diameter: 72
                    onClicked: { Phone.powerMenuOpen = false; Phone.sys(["reboot"]) } }
      RoundButton { glyph: "\u{f033e}"; caption: "Lock"; focused: pm.sel === 2; diameter: 72
                    onClicked: { Phone.powerMenuOpen = false; Phone.lock() } }
      RoundButton { glyph: "\u{f0450}"; caption: "Reload shell"; focused: pm.sel === 3; diameter: 72
                    onClicked: { Phone.powerMenuOpen = false; Quickshell.reload(true) } }
    }
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Tap outside or press Esc to cancel"; size: 12; color: Theme.dim }
  }
}
