import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Services
import qs.Widgets

// Top strip. Reserves its height, and dragging down on it pulls the shade.
PanelWindow {
  id: bar
  anchors { top: true; left: true; right: true }
  implicitHeight: Theme.statusH
  exclusiveZone: Theme.statusH
  WlrLayershell.layer: WlrLayer.Top
  WlrLayershell.namespace: "ophone-status"
  color: Phone.atHome ? "transparent" : Theme.background

  StatusRow { anchors.fill: parent }

  DragHandler {
    target: null
    xAxis.enabled: false
    onActiveChanged: {
      Phone.shadeDragging = active
      if (active) { Notifs.hideBanner(); Phone.switcherOpen = false }
      else Phone.settleShade(centroid.velocity.y)
    }
    onTranslationChanged: if (active) Phone.shade = Math.max(0, Math.min(1, translation.y / (Theme.screenHeight * 0.6)))
  }
  TapHandler { onTapped: Phone.openShade() }
}
