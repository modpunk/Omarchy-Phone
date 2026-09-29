import QtQuick
import Quickshell
import Quickshell.Services.UPower
import Quickshell.Networking
import Quickshell.Bluetooth
import qs.Commons
import qs.Services

// Time on the left; call pill, silent, Wi-Fi, Bluetooth, battery on the right.
// Everything here is event driven (D-Bus properties, minute clock).
Item {
  id: root
  property bool showTime: true
  implicitHeight: Theme.statusH

  SystemClock { id: clock; precision: SystemClock.Minutes }

  readonly property var battery: UPower.displayDevice
  readonly property bool hasBattery: battery && battery.isPresent
  readonly property int pct: hasBattery ? Math.round(battery.percentage * 100) : -1
  readonly property bool charging: hasBattery && (battery.state === UPowerDeviceState.Charging || battery.state === UPowerDeviceState.FullyCharged)
  readonly property bool wifiOn: Networking.wifiEnabled
  readonly property bool online: {
    const devs = Networking.devices ? Networking.devices.values : []
    for (const d of devs) if (d.connected) return true
    return false
  }
  readonly property var btAdapter: Bluetooth.defaultAdapter
  readonly property bool btOn: btAdapter ? btAdapter.enabled : false
  readonly property bool btConnected: {
    const devs = Bluetooth.devices ? Bluetooth.devices.values : []
    for (const d of devs) if (d.connected) return true
    return false
  }

  function batteryGlyph() {
    if (pct < 0) return ""
    if (charging) return "\u{f0084}"
    if (pct >= 95) return "\u{f0079}"
    if (pct < 10) return "\u{f0083}"
    return String.fromCodePoint(0xf007a + Math.floor(pct / 10) - 1) // battery-10 .. battery-90
  }

  Label {
    visible: root.showTime
    anchors.left: parent.left; anchors.leftMargin: Theme.px(16)
    anchors.verticalCenter: parent.verticalCenter
    text: Qt.formatTime(clock.date, "HH:mm")
    size: 14; strong: true
  }

  Row {
    anchors.right: parent.right; anchors.rightMargin: Theme.px(12)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Theme.px(7)

    Rectangle {
      visible: Notifs.ongoingCall !== null
      height: Theme.px(18); width: callLbl.implicitWidth + Theme.px(28); radius: height / 2
      color: Theme.good
      anchors.verticalCenter: parent.verticalCenter
      Row {
        anchors.centerIn: parent; spacing: Theme.px(4)
        Glyph { text: "\u{f03f2}"; size: 11; color: Theme.background }
        Label { id: callLbl; text: "Call"; size: 11; strong: true; color: Theme.background }
      }
      TapHandler { onTapped: Notifs.activate(Notifs.ongoingCall) }
    }
    Glyph { visible: Phone.silent; text: "\u{f009b}"; size: 14; anchors.verticalCenter: parent.verticalCenter }
    Glyph { visible: Phone.airplane; text: "\u{f001d}"; size: 14; anchors.verticalCenter: parent.verticalCenter }
    Glyph {
      visible: !Phone.airplane
      text: !root.wifiOn ? "\u{f05aa}" : (root.online ? "\u{f0928}" : "\u{f092f}")
      color: root.wifiOn ? Theme.foreground : Theme.dim
      size: 14; anchors.verticalCenter: parent.verticalCenter
    }
    Glyph {
      visible: root.btOn
      text: root.btConnected ? "\u{f00b1}" : "\u{f00af}"
      size: 14; anchors.verticalCenter: parent.verticalCenter
    }
    Row {
      visible: root.pct >= 0
      spacing: Theme.px(2)
      anchors.verticalCenter: parent.verticalCenter
      Label { text: root.pct + "%"; size: 12; anchors.verticalCenter: parent.verticalCenter }
      Glyph {
        text: root.batteryGlyph(); size: 15; rotation: 90
        color: root.pct < 15 && !root.charging ? Theme.urgent : Theme.foreground
        anchors.verticalCenter: parent.verticalCenter
      }
    }
  }
}
