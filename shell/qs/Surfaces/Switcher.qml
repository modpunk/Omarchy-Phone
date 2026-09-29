import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import qs.Commons
import qs.Services
import qs.Widgets

// App switcher: one card per open window (foreign-toplevel list), newest
// first. Tap a card to switch, flick it up to close the app, tap the
// background to go back. Thumbnails are captured once when the switcher
// opens (live: false), since live capture is too costly without a GPU.
PanelWindow {
  id: sw
  visible: Phone.switcherOpen && !Phone.locked
  anchors { top: true; bottom: true; left: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.namespace: "ophone-switcher"
  color: Theme.alpha(Theme.background, 0.94)

  readonly property var windows: ToplevelManager.toplevels.values.slice().reverse()

  TapHandler { onTapped: Phone.switcherOpen = false }

  Label {
    anchors.centerIn: parent
    visible: sw.windows.length === 0
    text: "No open apps"; size: 16; color: Theme.dim
  }

  ListView {
    id: cards
    anchors.fill: parent
    anchors.topMargin: Theme.statusH + Theme.px(30)
    anchors.bottomMargin: Theme.navH + Theme.px(60)
    orientation: ListView.Horizontal
    spacing: Theme.px(14)
    leftMargin: (width - cardW) / 2; rightMargin: leftMargin
    snapMode: ListView.SnapToItem
    readonly property int cardW: Math.round(width * 0.68)
    model: sw.windows

    delegate: Item {
      id: slot
      required property var modelData
      width: cards.cardW; height: cards.height

      Column {
        id: card
        width: parent.width
        y: drag.active ? Math.min(0, drag.translation.y) : 0
        opacity: 1 + y / (slot.height * 0.8)
        spacing: Theme.px(8)
        Behavior on y { enabled: !drag.active; NumberAnimation { duration: 120 } }

        Row {
          spacing: Theme.px(8)
          IconImage {
            implicitSize: Theme.px(22)
            source: {
              const e = DesktopEntries.heuristicLookup(slot.modelData.appId)
              return Quickshell.iconPath(e ? e.icon : slot.modelData.appId, true)
            }
          }
          Label { text: slot.modelData.title || slot.modelData.appId; size: 13; width: card.width - Theme.px(30); anchors.verticalCenter: parent.verticalCenter }
        }
        Rectangle {
          width: parent.width; height: cards.height - Theme.px(30)
          radius: Theme.radius; color: Theme.surface; clip: true
          ScreencopyView {
            anchors.fill: parent
            captureSource: sw.visible ? slot.modelData : null
            live: false
          }
        }
      }
      TapHandler { onTapped: { slot.modelData.activate(); Phone.switcherOpen = false } }
      DragHandler {
        id: drag
        target: null; xAxis.enabled: false
        onActiveChanged: if (!active && translation.y < -slot.height * 0.25) slot.modelData.close()
      }
    }
  }

  Row {
    anchors.bottom: parent.bottom; anchors.bottomMargin: Theme.navH + Theme.px(12)
    anchors.horizontalCenter: parent.horizontalCenter
    visible: sw.windows.length > 0
    RoundButton { glyph: "\u{f0156}"; caption: "Close all"; diameter: 44; glyphSize: 18
                  onClicked: { for (const t of sw.windows) t.close(); Phone.home() } }
  }
}
