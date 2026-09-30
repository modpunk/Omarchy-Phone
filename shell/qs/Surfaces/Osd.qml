import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Services
import qs.Widgets

// Volume / silent-mode toast. Shows for 1.5 s after each Phone.showOsd().
PanelWindow {
  id: osd
  visible: hideTimer.running
  anchors.top: true
  margins.top: Theme.statusH + Theme.px(10)
  exclusionMode: ExclusionMode.Ignore
  implicitWidth: Theme.px(220); implicitHeight: Theme.px(44)
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.namespace: "ophone-osd"
  color: "transparent"

  Connections { target: Phone; function onOsdSerialChanged() { hideTimer.restart() } }
  Timer { id: hideTimer; interval: 1500 }

  Rectangle {
    anchors.fill: parent; radius: height / 2
    color: Theme.surface
    Row {
      anchors.fill: parent; anchors.leftMargin: Theme.px(14); anchors.rightMargin: Theme.px(16)
      spacing: Theme.px(10)
      Glyph { anchors.verticalCenter: parent.verticalCenter; text: Phone.osdIcon; size: 20 }
      Label { visible: Phone.osdValue < 0; anchors.verticalCenter: parent.verticalCenter; text: Phone.osdLabel; size: 14 }
      Rectangle {
        visible: Phone.osdValue >= 0
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width - Theme.px(40); height: Theme.px(6); radius: height / 2
        color: Theme.surfaceHi
        Rectangle { width: parent.width * Phone.osdValue / 100; height: parent.height; radius: height / 2; color: Theme.accent }
      }
    }
  }
}
