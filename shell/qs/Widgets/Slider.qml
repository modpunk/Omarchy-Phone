import QtQuick
import qs.Commons

// Labeled 0-100 slider: drag or tap the bar to set it. Same bar visual as
// Shade.qml's brightness bar, generalised with a label + value row so it
// also works for Settings' volume row. Left/Right nudging while focused is
// the caller's job (SettingsSurface.adjustSlider), same as Shade.qml's own
// brightness bar does it in Shade's onKey(), not in the bar itself.
Item {
  id: root
  property string glyph: ""
  property string label: ""
  property int value: 0
  property bool focused: false      // keyboard focus ring
  signal moved(int value)
  width: parent ? parent.width : 0
  implicitHeight: Theme.px(58)

  Item {
    id: head
    width: parent.width; height: Theme.px(16)
    Label { anchors.left: parent.left; text: root.label; size: 13; color: Theme.dim }
    Label { anchors.right: parent.right; text: root.value + "%"; size: 13; color: Theme.dim }
  }
  Rectangle {
    id: bar
    anchors.top: head.bottom; anchors.topMargin: Theme.px(6)
    width: parent.width; height: Theme.px(40); radius: height / 2
    color: Theme.surface
    Rectangle {
      width: Math.max(height, parent.width * root.value / 100); height: parent.height; radius: height / 2
      color: Theme.alpha(Theme.accent, 0.8)
    }
    FocusRing { shown: root.focused; gap: 3 }
    Glyph { x: Theme.px(12); anchors.verticalCenter: parent.verticalCenter; text: root.glyph; size: 18; color: Theme.background }
    DragHandler {
      target: null; yAxis.enabled: false
      onCentroidChanged: if (active) root.moved(Math.round(Math.max(0, Math.min(100, 100 * centroid.position.x / bar.width))))
    }
    TapHandler { onTapped: (ev) => root.moved(Math.round(Math.max(0, Math.min(100, 100 * ev.position.x / bar.width)))) }
  }
}
