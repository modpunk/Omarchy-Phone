import QtQuick
import qs.Commons

// A Nerd Font glyph (Material Design Icons range). Text rendering is the
// cheapest icon path under the software scene graph.
Text {
  property real size: 16
  font.family: Theme.fontFamily
  font.pixelSize: Theme.font(size)
  color: Theme.foreground
  horizontalAlignment: Text.AlignHCenter
  verticalAlignment: Text.AlignVCenter
}
