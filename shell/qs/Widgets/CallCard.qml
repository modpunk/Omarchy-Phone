import QtQuick
import Quickshell
import Quickshell.Widgets
import qs.Commons
import qs.Services

// Incoming call, full screen. Used both as its own overlay and inside the
// lock screen, so a call can be answered without unlocking.
// Keyboard: Enter or A answers, Esc or D declines; Left/Right picks a
// button (focus ring) and Enter/Space presses it.
Rectangle {
  id: root
  required property var call        // a Notification with category call.incoming
  property bool onLockScreen: false
  color: Theme.background

  property int sel: -1               // 0 = Decline, 1 = Accept, -1 = none (Enter answers)
  focus: true
  Component.onCompleted: forceActiveFocus()
  Keys.onPressed: ev => {
    const k = Phone.keyOf(ev)
    if (k === Qt.Key_Left) sel = 0
    else if (k === Qt.Key_Right) sel = 1
    else if (k === Qt.Key_Tab || k === Qt.Key_Backtab) sel = sel === 1 ? 0 : 1
    else if (k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space) { if (sel === 0) Notifs.decline(); else Notifs.answer() }
    else if (k === Qt.Key_A || k === Qt.Key_Y) Notifs.answer()
    else if (k === Qt.Key_Escape || k === Qt.Key_D || k === Qt.Key_N) Notifs.decline()
    ev.accepted = true
  }

  readonly property string caller: (call && (call.hints["x-ophone-caller"] || call.summary)) || "Unknown caller"
  readonly property string detail: (call && (call.hints["x-ophone-number"] || call.body)) || ""
  readonly property bool video: call && String(call.hints["x-ophone-video"] || "") === "true"

  Rectangle {
    anchors.fill: parent
    gradient: Gradient {
      GradientStop { position: 0; color: Qt.darker(Theme.good, 4) }
      GradientStop { position: 0.6; color: Theme.background }
    }
  }

  StatusRow { width: parent.width; showTime: !root.onLockScreen }

  Column {
    anchors.horizontalCenter: parent.horizontalCenter
    y: parent.height * 0.14
    spacing: Theme.px(10)
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: root.video ? "Incoming video call" : "Incoming call"; size: 14; color: Theme.dim }
    Rectangle {
      anchors.horizontalCenter: parent.horizontalCenter
      width: Theme.px(104); height: width; radius: width / 2
      color: Theme.surfaceHi
      clip: true
      IconImage { anchors.fill: parent; visible: root.call && root.call.image !== ""; source: root.call ? root.call.image : "" }
      Label {
        visible: !(root.call && root.call.image)
        anchors.centerIn: parent
        text: root.caller.split(/\s+/).map(w => w.charAt(0)).join("").slice(0, 2).toUpperCase()
        size: 40; color: Theme.foreground
      }
    }
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: root.caller; size: 28; width: root.width - Theme.px(40); horizontalAlignment: Text.AlignHCenter }
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: root.detail; size: 15; color: Theme.dim; width: root.width - Theme.px(40); horizontalAlignment: Text.AlignHCenter }
    Label { anchors.horizontalCenter: parent.horizontalCenter; visible: root.call && root.call.appName; text: "via " + (root.call ? root.call.appName : ""); size: 12; color: Theme.dim }
  }

  Row {
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom; anchors.bottomMargin: Theme.navH + Theme.px(60)
    spacing: Theme.px(90)
    RoundButton { glyph: "\u{f03f5}"; caption: "Decline"; focused: root.sel === 0; fill: Theme.urgent; ink: "white"; diameter: 72; onClicked: Notifs.decline() }
    RoundButton { glyph: root.video ? "\u{f0567}" : "\u{f03f2}"; caption: "Accept"; focused: root.sel === 1; fill: Theme.good; ink: "white"; diameter: 72; onClicked: Notifs.answer() }
  }
  Label {
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom; anchors.bottomMargin: Theme.navH + Theme.px(24)
    text: (root.onLockScreen ? "\u{f033e}  Answering keeps the phone locked · " : "") + "Vol\u2212 silences · Enter answers · Esc declines"
    font.family: Theme.fontFamily
    size: 11; color: Theme.dim
  }
}
