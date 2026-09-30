import QtQuick
import qs.Commons

// Keyboard focus ring: an accent outline just outside its parent. Shown only
// while a key has selected the item, so touch use never sees it. No
// animation (software rendering).
Rectangle {
  property bool shown: false
  property real gap: 4
  property color ink: Theme.accent
  visible: shown
  anchors.fill: parent
  anchors.margins: -Theme.px(gap)
  radius: (parent && parent.radius !== undefined ? parent.radius : 0) + Theme.px(gap)
  color: "transparent"
  border.color: ink
  border.width: Math.max(2, Theme.px(3))
  z: 10
}
