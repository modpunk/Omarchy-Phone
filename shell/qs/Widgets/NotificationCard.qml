import QtQuick
import Quickshell
import Quickshell.Widgets
import qs.Commons
import qs.Services

// One notification. Tap = default action, swipe sideways = dismiss.
Item {
  id: root
  required property var notification
  property bool compact: false
  implicitHeight: card.implicitHeight
  width: parent ? parent.width : 0

  Rectangle {
    id: card
    width: parent.width
    implicitHeight: body.implicitHeight + Theme.px(20)
    radius: Theme.radius
    color: Theme.surface
    x: drag.active ? drag.translation.x : 0
    opacity: 1 - Math.min(0.7, Math.abs(x) / width)
    Behavior on x { enabled: !drag.active; NumberAnimation { duration: 120 } }

    Row {
      id: body
      x: Theme.px(10); y: Theme.px(10)
      width: parent.width - Theme.px(20)
      spacing: Theme.px(10)
      Item {
        id: icon
        width: Theme.px(32); height: width
        readonly property string src: root.notification.image || (root.notification.appIcon ? Quickshell.iconPath(root.notification.appIcon, true) : "")
        IconImage { anchors.fill: parent; visible: icon.src !== ""; source: icon.src }
        Rectangle {
          visible: icon.src === ""
          anchors.fill: parent; radius: width / 2; color: Theme.surfaceHi
          Label { anchors.centerIn: parent; text: (root.notification.appName || "?").charAt(0).toUpperCase(); strong: true; color: Theme.accent }
        }
      }
      Column {
        width: parent.width - icon.width - parent.spacing
        spacing: Theme.px(2)
        Row {
          width: parent.width
          Label { text: root.notification.appName || "App"; size: 11; color: Theme.dim; width: parent.width }
        }
        Label { text: root.notification.summary; strong: true; size: 14; width: parent.width }
        Label {
          visible: text !== ""
          text: root.notification.body
          size: 13; width: parent.width; color: Theme.foreground
          wrapMode: Text.Wrap; maximumLineCount: root.compact ? 2 : 4
        }
        Flow {
          visible: !root.compact && actionRepeater.count > 0
          width: parent.width; spacing: Theme.px(8); topPadding: Theme.px(4)
          Repeater {
            id: actionRepeater
            model: root.notification.actions.filter(a => a.identifier !== "default")
            delegate: Rectangle {
              required property var modelData
              height: Theme.px(30); width: t.implicitWidth + Theme.px(20); radius: height / 2
              color: Theme.surfaceHi
              Label { id: t; anchors.centerIn: parent; text: parent.modelData.text; size: 12 }
              TapHandler { onTapped: parent.modelData.invoke() }
            }
          }
        }
      }
    }
    TapHandler { onTapped: Notifs.activate(root.notification) }
    DragHandler {
      id: drag
      target: null
      yAxis.enabled: false
      onActiveChanged: if (!active && Math.abs(translation.x) > card.width * 0.35) root.notification.dismiss()
    }
  }
}
