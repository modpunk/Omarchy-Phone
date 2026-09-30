import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Services
import qs.Widgets

// System-wide tap-to-call (docs/phone/DESIGN.md §4.1, docs/BACKLOG.md P1):
// a small heads-up chip for phone numbers NumberDetect.qml finds in the
// clipboard. Tapping one calls Phone.dialNumber() (see Services/Phone.qml,
// end of file).
//
// Never shown while locked: consistent with every other overlay here
// (Banner, Shade, Switcher, CallSurface all check Phone.locked too), and
// for the obvious reason -- a locked phone has no business offering a
// one-tap way to call whatever number a bystander left on the clipboard.
PanelWindow {
  visible: NumberDetect.current.length > 0 && !Phone.locked
  anchors { bottom: true; left: true; right: true }
  margins.bottom: Theme.navH + Theme.px(10)
  margins.left: Theme.px(8); margins.right: Theme.px(8)
  exclusionMode: ExclusionMode.Ignore
  implicitHeight: Math.max(1, column.implicitHeight)
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.namespace: "ophone-tap-to-call"
  color: "transparent"

  // A dismissed/dialed chip clears the whole batch, not just itself: the
  // common case is one number per clipboard snapshot, and clearing
  // per-item would need per-item identity this detector doesn't have
  // (two matches can share the same uri/raw). Good enough for a chip that
  // times out with the clipboard's next change anyway.
  Column {
    id: column
    width: parent.width
    spacing: Theme.px(6)
    Repeater {
      model: NumberDetect.current
      delegate: TapToCallCard {
        // NumberDetect.current is a plain JS array of {uri, raw} objects:
        // Quickshell/QML exposes each object's own properties directly to
        // a delegate whose required properties share their names (`raw`,
        // `uri` below), not through `modelData.raw` -- that would silently
        // bind `undefined` instead (no error, just an empty label).
        width: column.width
        onDial: { Phone.dialNumber(uri); NumberDetect.clear() }
        onDismissed: NumberDetect.clear()
      }
    }
  }
}
