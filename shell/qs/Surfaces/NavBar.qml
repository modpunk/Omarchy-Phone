import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Services
import qs.Widgets

// Bottom gesture strip with the home pill.
//   swipe up             -> home
//   swipe up and hold, or past 35% of the screen -> app switcher
//   swipe left / right   -> previous / next app
//   keyboard glyph       -> toggle the on-screen keyboard
PanelWindow {
  id: nav
  anchors { bottom: true; left: true; right: true }
  implicitHeight: Theme.navH
  exclusiveZone: Theme.navH
  WlrLayershell.layer: WlrLayer.Top
  WlrLayershell.namespace: "ophone-nav"
  color: Phone.atHome && !Phone.keyboardOpen ? "transparent" : Theme.background

  Rectangle {
    id: pill
    anchors.centerIn: parent
    width: Theme.px(120); height: Theme.px(5); radius: height / 2
    color: Theme.foreground
    opacity: 0.8
    anchors.verticalCenterOffset: drag.active ? Math.max(-Theme.px(8), drag.translation.y / 6) : 0
  }

  Glyph {
    anchors.right: parent.right; anchors.rightMargin: Theme.px(10)
    anchors.verticalCenter: parent.verticalCenter
    text: "\u{f030c}"; size: 16
    color: Phone.keyboardOpen ? Theme.accent : Theme.dim
    // Shown whenever a field is focused (even if a Bluetooth keyboard is
    // suppressing the auto-show, so there's still a way to ask for it) or
    // it's already open for some other reason (e.g. a terminal).
    visible: !Phone.atHome || Phone.keyboardOpen || Phone.imFieldFocused
    TapHandler { onTapped: Phone.toggleKeyboard(); margin: Theme.px(10) }
  }

  Timer {
    id: hold
    interval: 350
    onTriggered: if (drag.active && -drag.translation.y > Theme.px(40)) { nav.decided = true; Phone.showSwitcher() }
  }
  property bool decided: false

  DragHandler {
    id: drag
    target: null
    onActiveChanged: {
      if (active) { nav.decided = false; return }
      hold.stop()
      if (nav.decided) return
      const dx = translation.x, dy = translation.y
      if (Math.abs(dx) > Theme.px(60) && Math.abs(dx) > Math.abs(dy)) {
        if (dx < 0) Phone.nextApp(); else Phone.prevApp()
      } else if (-dy > Theme.screenHeight * 0.35) {
        Phone.showSwitcher()
      } else if (-dy > Theme.px(24)) {
        Phone.home()
      }
    }
    onTranslationChanged: if (active) hold.restart()
  }
}
