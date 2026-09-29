import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Services
import qs.Widgets

// Heads-up banner for a new notification, just under the status bar.
PanelWindow {
  visible: Notifs.banner !== null && !Phone.locked && Phone.shade === 0
  anchors { top: true; left: true; right: true }
  margins.top: Theme.statusH + Theme.px(4)
  margins.left: Theme.px(8); margins.right: Theme.px(8)
  exclusionMode: ExclusionMode.Ignore
  implicitHeight: Math.max(1, loader.implicitHeight)
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.namespace: "ophone-banner"
  color: "transparent"

  Loader {
    id: loader
    width: parent.width
    active: Notifs.banner !== null
    sourceComponent: NotificationCard { compact: true; notification: Notifs.banner }
  }
  DragHandler { target: null; xAxis.enabled: false; onActiveChanged: if (!active && translation.y < -Theme.px(10)) Notifs.hideBanner() }
}
