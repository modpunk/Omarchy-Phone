import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Services
import qs.Widgets

// Incoming-call overlay while unlocked (LockScreen shows its own copy).
PanelWindow {
  visible: Notifs.incomingCall !== null && !Phone.locked
  anchors { top: true; bottom: true; left: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.namespace: "ophone-call"
  color: Theme.background
  WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
  Loader {
    anchors.fill: parent
    focus: true
    active: parent.visible
    sourceComponent: CallCard { call: Notifs.incomingCall }
  }
}
