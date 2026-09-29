import QtQuick
import qs.Commons

// Quick-settings tile: glyph + short label, accent when on.
Rectangle {
  id: root
  property string glyph: ""
  property string label: ""
  property bool on: false
  property bool focused: false      // keyboard focus ring
  signal toggled()
  implicitWidth: Theme.px(78); implicitHeight: Theme.px(64)
  radius: Theme.radius
  color: on ? Theme.accent : (tap.pressed ? Theme.surfaceHi : Theme.surface)
  Column {
    anchors.centerIn: parent
    spacing: Theme.px(4)
    Glyph { anchors.horizontalCenter: parent.horizontalCenter; text: root.glyph; size: 22; color: root.on ? Theme.background : Theme.foreground }
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: root.label; size: 11; color: root.on ? Theme.background : Theme.foreground }
  }
  FocusRing { shown: root.focused; gap: 3; ink: root.on ? Theme.foreground : Theme.accent }
  TapHandler { id: tap; onTapped: root.toggled() }
}
