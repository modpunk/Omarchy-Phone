import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Services
import qs.Widgets

// Minimal on-screen keyboard. Sits above the nav bar with an exclusive zone
// (the app shrinks instead of being covered), shown/hidden by Phone.qml
// (focus-driven via ophone-im, or by hand: SUPER+K, the nav-bar glyph, the
// shade tile). Types through the input method when a text field is focused,
// wtype (zwp_virtual_keyboard_v1) otherwise. Never takes keyboard focus
// itself.
//
// Layout follows the focused field's content purpose (Phone.keyboardLayout,
// derived from Phone.imPurpose -- see Services/Phone.qml and
// shell/im/ophone-im.c, which decodes it from the input-method-v2
// content_type event): a compact numeric keypad for digits/number fields, a
// phone dial pad for phone/tel fields, full QWERTY with an email/url
// convenience key otherwise, and full QWERTY (with a lock glyph on the
// space bar, no other change) for password fields -- passwords need the
// full character set, so there's no separate "password layout", just a
// masked flag. Every layout is exactly four rows, so
// implicitHeight/exclusiveZone -- and how much the app shrinks -- never
// changes when the focused field changes.
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

  readonly property string layout: Phone.keyboardLayout // qwerty | numeric | phone | email | url | password
  // Passwords still type through the normal QWERTY rows (see above): this
  // just gates the lock glyph on the space bar (see label()). Nothing in
  // this shell shows a preview of typed characters or offers clipboard
  // paste today, so there is nothing else to mask/disable here -- the
  // masking of what's on screen is the focused app's own job (a
  // text-input-v3 widget with purpose=password renders dots, e.g.
  // GtkEntry's visibility=false); this flag is the gate for if either is
  // ever added to the shell's own keyboard.
  readonly property bool masked: layout === "password"
  // A fresh field means a fresh keyboard state: a caps-locked or symbols
  // page left over from the previous field must not bleed into this one.
  onLayoutChanged: { shift = false; caps = false; symbols = false }

  readonly property var lettersBase: [
    ["q","w","e","r","t","y","u","i","o","p"],
    ["a","s","d","f","g","h","j","k","l"],
    ["shift","z","x","c","v","b","n","m","bksp"]
  ]
  // Bottom row varies by purpose: a plain comma/period, or a convenience
  // key for the punctuation an email/URL needs most (like a phone OSK).
  readonly property var row4Normal: ["sym", ",", "space", ".", "enter"]
  readonly property var row4Email: ["sym", "@", "space", ".com", "enter"]
  readonly property var row4Url: ["sym", "/", "space", ".com", "enter"]
  readonly property var letters: lettersBase.concat([
    layout === "email" ? row4Email : layout === "url" ? row4Url : row4Normal
  ])
  readonly property var syms: [
    ["1","2","3","4","5","6","7","8","9","0"],
    ["@","#","$","_","&","-","+","(",")"],
    ["=","*","\"","'",":",";","!","?","bksp"],
    ["abc","/","space","~","enter"]
  ]
  // digits/number purposes: a compact keypad (no letters, no symbols page
  // -- "." covers "number"'s decimal/sign case; a plain digits field just
  // won't need it). No Enter/Backspace-only row wider than the digit rows:
  // every row here fits within numericCols, so every key is the same size
  // (see widthOf) and nothing overflows the panel.
  readonly property var numericRows: [
    ["1","2","3"],
    ["4","5","6"],
    ["7","8","9"],
    [".","0","bksp","enter"]
  ]
  readonly property int numericCols: 4
  // phone/tel purpose: a classic dial pad, digits plus + * # (no Enter --
  // a phone-number field is dialed by the app's own call button, not a
  // keyboard Return; Backspace still edits a mis-dialed digit).
  readonly property var phoneRows: [
    ["1","2","3"],
    ["4","5","6"],
    ["7","8","9"],
    ["+","*","0","#","bksp"]
  ]
  readonly property int phoneCols: 5
  readonly property var rows: {
    if (layout === "numeric") return numericRows
    if (layout === "phone") return phoneRows
    return symbols ? syms : letters // qwerty, password, email, url
  }
  // The qwerty-family layouts are 10 columns wide; the digit pads size
  // their (uniform-width, see widthOf) keys off their own widest row
  // instead, so nothing overflows the panel.
  readonly property int cols: layout === "numeric" ? numericCols : layout === "phone" ? phoneCols : 10
  readonly property real keyW: (width - Theme.px(6) * (cols + 1)) / cols

  // A focused text-input-v3 field (GTK4, Chromium/Electron, most Qt) gets
  // plain characters through the input method (ophone-im, Services/Phone.qml)
  // instead of a synthetic key event: that's the protocol-correct path for
  // committing text. Backspace, Enter, and anything with no focused field
  // (a terminal, an app that never adopted text-input-v3) go through wtype
  // (virtual-keyboard-v1) instead: delete_surrounding_text is the "correct"
  // way for an input method to delete, but foot -- despite speaking
  // text-input-v3 for IME composition -- doesn't act on it (verified in
  // shell/preview/run.sh's oskfoot scenario), so backspace stays a real key
  // event, which every app already handles.
  function type(k) {
    if (k === "shift") { if (shift && !caps) caps = true; else { caps = false; shift = !shift } return }
    if (k === "sym") { symbols = true; return }
    if (k === "abc") { symbols = false; return }
    if (k === "bksp") { Quickshell.execDetached(["wtype", "-k", "BackSpace"]); return }
    if (k === "enter") { Quickshell.execDetached(["wtype", "-k", "Return"]); return }
    if (k === "space") {
      if (Phone.imFieldFocused) Phone.imCommit(" "); else Quickshell.execDetached(["wtype", " "])
      return
    }
    // .com (or any future multi-char convenience key) commits/types as a
    // literal string either way (commit_string and wtype's text argument
    // both take more than one character); only single letters case-shift.
    const ch = (shift || caps) && k.length === 1 ? k.toUpperCase() : k
    if (Phone.imFieldFocused) Phone.imCommit(ch); else Quickshell.execDetached(["wtype", "--", ch])
    if (shift && !caps) shift = false
  }
  function label(k) {
    switch (k) {
      case "shift": return caps ? "\u{f0632}" : "\u{f0636}"
      case "bksp": return "\u{f006e}"
      case "enter": return "\u{f0311}"
      case "space": return masked ? "\u{f033e}" : ""
      case "sym": return "?123"
      case "abc": return "ABC"
      default: return (shift || caps) && k.length === 1 ? k.toUpperCase() : k
    }
  }
  function widthOf(k) {
    if (k === "space") return keyW * 4 + Theme.px(6) * 3
    // Only the qwerty-family layouts (cols === 10) widen bksp/shift/enter:
    // the numeric/phone pads keep every key the same size, sized to their
    // own widest row (see cols), so nothing overflows the panel.
    if (cols === 10) {
      if (k === "shift" || k === "bksp") return keyW * 1.45
      if (k === "sym" || k === "abc" || k === "enter" || k === ".com") return keyW * 1.9
    }
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
              font.family: parent.special && parent.modelData !== "sym" && parent.modelData !== "abc" && parent.modelData !== ".com" ? Theme.fontFamily : Theme.textFamily
              font.pixelSize: Theme.font(parent.special ? 16 : 19)
            }
            TapHandler { id: tap; onTapped: kb.type(parent.modelData) }
          }
        }
      }
    }
  }
}
