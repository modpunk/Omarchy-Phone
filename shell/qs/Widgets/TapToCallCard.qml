import QtQuick
import qs.Commons

// One detected phone number, offered as a tap-to-call chip
// (docs/phone/DESIGN.md §4.1). Tap = dial: Phone.dialNumber() opens the
// Phone app's keypad pre-filled with this number, still requiring the
// app's own Call button (its existing confirm_call() safeguard) -- so a
// mis-tap out here can't place a call by itself. Swipe sideways = dismiss,
// the same gesture NotificationCard uses.
Item {
  id: root
  required property string raw
  required property string uri
  signal dial()
  signal dismissed()
  implicitHeight: card.implicitHeight
  width: parent ? parent.width : 0

  Rectangle {
    id: card
    width: parent.width
    implicitHeight: row.implicitHeight + Theme.px(20)
    radius: Theme.radius
    color: Theme.surface
    x: drag.active ? drag.translation.x : 0
    opacity: 1 - Math.min(0.7, Math.abs(x) / width)
    Behavior on x { enabled: !drag.active; NumberAnimation { duration: 120 } }

    Row {
      id: row
      x: Theme.px(14); y: Theme.px(10)
      width: parent.width - Theme.px(28)
      spacing: Theme.px(10)
      Glyph { anchors.verticalCenter: parent.verticalCenter; text: "\u{f03f2}"; size: 20; color: Theme.good }
      Label {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width - Theme.px(30)
        text: "Call " + root.raw + "?"
        strong: true; size: 14
      }
    }
    TapHandler { onTapped: root.dial() }
    DragHandler {
      id: drag
      target: null
      yAxis.enabled: false
      onActiveChanged: if (!active && Math.abs(translation.x) > card.width * 0.35) root.dismissed()
    }
  }
}
