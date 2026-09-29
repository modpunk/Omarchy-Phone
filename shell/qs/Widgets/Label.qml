import QtQuick
import qs.Commons

Text {
  property real size: 14
  property bool strong: false
  font.family: Theme.textFamily
  font.pixelSize: Theme.font(size)
  font.weight: strong ? Font.DemiBold : Font.Normal
  color: Theme.foreground
  elide: Text.ElideRight
}
