import QtQuick
import qs.Commons

// Numeric PIN pad. Stateless: the owner keeps `pin` and handles keyPressed
// ("0".."9", "del", "ok"), so several lock surfaces can share one PIN.
Item {
  id: root
  property string pin: ""
  property string status: ""
  property bool busy: false
  signal keyPressed(string k)
  implicitWidth: grid.width; implicitHeight: col.implicitHeight

  function press(k) { if (!busy) keyPressed(k) }

  Column {
    id: col
    anchors.horizontalCenter: parent.horizontalCenter
    spacing: Theme.px(16)
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: root.status || (root.busy ? "Checking…" : "Enter PIN"); size: 14; color: root.status ? Theme.urgent : Theme.foreground }
    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: Theme.px(12); height: Theme.px(12)
      Repeater {
        model: Math.max(4, root.pin.length)
        delegate: Rectangle {
          required property int index
          width: Theme.px(12); height: width; radius: width / 2
          color: index < root.pin.length ? Theme.foreground : "transparent"
          border.color: Theme.foreground; border.width: Math.max(1, Theme.px(1.5))
        }
      }
    }
    Grid {
      id: grid
      anchors.horizontalCenter: parent.horizontalCenter
      columns: 3; spacing: Theme.px(18)
      Repeater {
        model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "del", "0", "ok"]
        delegate: Rectangle {
          required property string modelData
          width: Theme.px(70); height: width; radius: width / 2
          color: tap.pressed ? Theme.surfaceHi : (modelData.length === 1 ? Theme.alpha(Theme.surface, 0.8) : "transparent")
          Text {
            anchors.centerIn: parent
            text: parent.modelData === "del" ? "\u{f006e}" : parent.modelData === "ok" ? "\u{f012c}" : parent.modelData
            font.family: parent.modelData.length === 1 ? Theme.textFamily : Theme.fontFamily
            font.pixelSize: Theme.font(parent.modelData.length === 1 ? 28 : 24)
            color: Theme.foreground
          }
          TapHandler { id: tap; onTapped: root.press(parent.modelData) }
        }
      }
    }
  }
}
