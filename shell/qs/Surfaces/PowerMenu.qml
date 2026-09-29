import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Services
import qs.Widgets

// Long-press Power.
PanelWindow {
  visible: Phone.powerMenuOpen
  anchors { top: true; bottom: true; left: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.namespace: "ophone-power"
  color: Theme.alpha(Theme.background, 0.92)

  TapHandler { onTapped: Phone.powerMenuOpen = false }

  Column {
    anchors.centerIn: parent
    spacing: Theme.px(28)
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: Theme.productName; size: 18; strong: true }
    Grid {
      anchors.horizontalCenter: parent.horizontalCenter
      columns: 2; spacing: Theme.px(36)
      RoundButton { glyph: "\u{f0425}"; caption: "Power off"; fill: Theme.urgent; ink: "white"; diameter: 72
                    onClicked: { Phone.powerMenuOpen = false; Phone.sys(["poweroff"]) } }
      RoundButton { glyph: "\u{f0709}"; caption: "Restart"; diameter: 72
                    onClicked: { Phone.powerMenuOpen = false; Phone.sys(["reboot"]) } }
      RoundButton { glyph: "\u{f033e}"; caption: "Lock"; diameter: 72
                    onClicked: { Phone.powerMenuOpen = false; Phone.lock() } }
      RoundButton { glyph: "\u{f0450}"; caption: "Reload shell"; diameter: 72
                    onClicked: { Phone.powerMenuOpen = false; Quickshell.reload(true) } }
    }
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Tap outside to cancel"; size: 12; color: Theme.dim }
  }
}
