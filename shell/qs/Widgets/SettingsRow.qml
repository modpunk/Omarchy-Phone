import QtQuick
import qs.Commons

// One settings list row: glyph, title (+ optional dim subtitle underneath),
// and either a plain right-aligned value (About) or an interactive trailing
// control such as a Switch (placed as this Item's child -- the default
// property aliases into it). Used by SettingsSurface for every row kind.
Item {
  id: root
  property string glyph: ""
  property string title: ""
  property string subtitle: ""
  property string value: ""         // plain right-aligned text (About rows)
  property bool dim: false          // greys the row out (placeholder / empty state)
  property bool focused: false      // keyboard focus ring
  default property alias trailing: trailingSlot.data
  width: parent ? parent.width : 0
  // Usually one line (Theme.px(44)), but grows for a wrapped subtitle (the
  // Wi-Fi placeholder's explanatory note is long enough to wrap on a 375u
  // screen).
  implicitHeight: Math.max(Theme.px(44), content.implicitHeight + Theme.px(12))

  FocusRing { shown: root.focused; gap: 2 }

  Row {
    id: content
    anchors.left: parent.left
    anchors.right: trailingSlot.left; anchors.rightMargin: Theme.px(8)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Theme.px(10)
    Glyph {
      visible: root.glyph !== ""
      text: root.glyph; size: 18; color: root.dim ? Theme.dim : Theme.foreground
      anchors.verticalCenter: parent.verticalCenter
    }
    Column {
      anchors.verticalCenter: parent.verticalCenter
      Label { text: root.title; size: 14; color: root.dim ? Theme.dim : Theme.foreground }
      Label { visible: root.subtitle !== ""; text: root.subtitle; size: 11; color: Theme.dim; wrapMode: Text.Wrap; width: root.width - Theme.px(40) }
    }
  }

  Item {
    id: trailingSlot
    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
    implicitWidth: childrenRect.width; implicitHeight: childrenRect.height
  }
  Label {
    visible: root.value !== "" && trailingSlot.implicitWidth === 0
    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
    text: root.value; size: 13; color: Theme.dim
  }
}
