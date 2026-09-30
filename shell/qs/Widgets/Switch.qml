import QtQuick
import qs.Commons

// Compact on/off pill: a settings row's trailing control (silent mode, the
// Bluetooth adapter, a paired device's connected state).
Rectangle {
  id: root
  property bool on: false
  property bool focused: false      // keyboard focus ring
  signal toggled()
  implicitWidth: Theme.px(46); implicitHeight: Theme.px(26)
  radius: height / 2
  color: on ? Theme.accent : Theme.surfaceHi
  FocusRing { shown: root.focused; gap: 3 }
  Rectangle {
    width: parent.height - Theme.px(4); height: width; radius: width / 2
    anchors.verticalCenter: parent.verticalCenter
    x: root.on ? parent.width - width - Theme.px(2) : Theme.px(2)
    color: root.on ? Theme.background : Theme.foreground
    Behavior on x { NumberAnimation { duration: 120 } }
  }
  TapHandler { onTapped: root.toggled() }
}
