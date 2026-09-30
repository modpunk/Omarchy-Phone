import QtQuick
import qs.Commons

// Circular touch button with a glyph and an optional caption below it.
Item {
  id: root
  property string glyph: ""
  property string caption: ""
  property color fill: Theme.surface
  property color ink: Theme.foreground
  property real diameter: 64
  property real glyphSize: 26
  property real glyphRotation: 0
  property bool focused: false      // keyboard focus ring
  signal clicked()
  implicitWidth: Theme.px(diameter)
  implicitHeight: Theme.px(diameter) + (caption ? Theme.px(22) : 0)

  Rectangle {
    id: disc
    width: Theme.px(root.diameter); height: width; radius: width / 2
    anchors.horizontalCenter: parent.horizontalCenter
    color: tap.pressed ? Qt.lighter(root.fill, 1.3) : root.fill
    FocusRing { shown: root.focused }
    Glyph { anchors.centerIn: parent; text: root.glyph; size: root.glyphSize; color: root.ink; rotation: root.glyphRotation }
  }
  Label {
    visible: root.caption !== ""
    anchors.top: disc.bottom; anchors.topMargin: Theme.px(6)
    anchors.horizontalCenter: parent.horizontalCenter
    text: root.caption; size: 12; color: Theme.foreground
  }
  TapHandler { id: tap; onTapped: root.clicked() }
}
