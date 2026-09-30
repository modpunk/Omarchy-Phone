import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Services
import qs.Widgets

// Minimal on-screen keyboard. Sits above the nav bar with an exclusive zone
// (the app shrinks instead of being covered) and types through wtype
// (zwp_virtual_keyboard_v1). Never takes keyboard focus itself.
PanelWindow {
  id: kb
  visible: Phone.keyboardOpen && !Phone.locked
  anchors { bottom: true; left: true; right: true }
  implicitHeight: col.implicitHeight + Theme.px(12)
  exclusiveZone: implicitHeight
  WlrLayershell.layer: WlrLayer.Top
  WlrLayershell.namespace: "ophone-keyboard"
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
  color: Qt.darker(Theme.background, 1.25)

  property bool shift: false
  property bool caps: false
  property bool symbols: false

  readonly property var letters: [
    ["q","w","e","r","t","y","u","i","o","p"],
    ["a","s","d","f","g","h","j","k","l"],
    ["shift","z","x","c","v","b","n","m","bksp"],
    ["sym",",","space",".","enter"]
  ]
  readonly property var syms: [
    ["1","2","3","4","5","6","7","8","9","0"],
    ["@","#","$","_","&","-","+","(",")"],
    ["=","*","\"","'",":",";","!","?","bksp"],
    ["abc","/","space","~","enter"]
  ]
  readonly property var rows: symbols ? syms : letters
  readonly property real keyW: (width - Theme.px(6) * 11) / 10

  function type(k) {
    if (k === "shift") { if (shift && !caps) caps = true; else { caps = false; shift = !shift } return }
    if (k === "sym") { symbols = true; return }
    if (k === "abc") { symbols = false; return }
    if (k === "bksp") { Quickshell.execDetached(["wtype", "-k", "BackSpace"]); return }
    if (k === "enter") { Quickshell.execDetached(["wtype", "-k", "Return"]); return }
    if (k === "space") { Quickshell.execDetached(["wtype", " "]); return }
    const ch = (shift || caps) ? k.toUpperCase() : k
    Quickshell.execDetached(["wtype", "--", ch])
    if (shift && !caps) shift = false
  }
  function label(k) {
    switch (k) {
      case "shift": return caps ? "\u{f0632}" : "\u{f0636}"
      case "bksp": return "\u{f006e}"
      case "enter": return "\u{f0311}"
      case "space": return ""
      case "sym": return "?123"
      case "abc": return "ABC"
      default: return (shift || caps) && k.length === 1 ? k.toUpperCase() : k
    }
  }
  function widthOf(k) {
    if (k === "space") return keyW * 4 + Theme.px(6) * 3
    if (k === "shift" || k === "bksp") return keyW * 1.45
    if (k === "sym" || k === "abc" || k === "enter") return keyW * 1.9
    return keyW
  }

  Column {
    id: col
    y: Theme.px(6)
    anchors.horizontalCenter: parent.horizontalCenter
    spacing: Theme.px(8)
    Repeater {
      model: kb.rows
      delegate: Row {
        required property var modelData
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Theme.px(6)
        Repeater {
          model: parent.modelData
          delegate: Rectangle {
            required property string modelData
            readonly property bool special: modelData.length > 1
            width: kb.widthOf(modelData); height: Theme.px(40)
            radius: Theme.px(6)
            color: tap.pressed ? Theme.accent
                 : (modelData === "shift" && (kb.shift || kb.caps)) ? Theme.surfaceHi
                 : special ? Theme.alpha(Theme.surface, 0.6) : Theme.surface
            Text {
              anchors.centerIn: parent
              text: kb.label(parent.modelData)
              color: Theme.foreground
              font.family: parent.special && parent.modelData !== "sym" && parent.modelData !== "abc" ? Theme.fontFamily : Theme.textFamily
              font.pixelSize: Theme.font(parent.special ? 16 : 19)
            }
            TapHandler { id: tap; onTapped: kb.type(parent.modelData) }
          }
        }
      }
    }
  }
}
