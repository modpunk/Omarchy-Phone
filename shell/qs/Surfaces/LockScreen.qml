import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.Pam
import qs.Commons
import qs.Services
import qs.Widgets

// ext-session-lock lock screen: clock, motto, notification count, swipe up
// for the PIN pad. Incoming calls show on top so they can be answered locked.
// PAM service: /etc/pam.d/ophone-lock (shell/system/pam/ophone-lock), else
// "login". In the preview (OPHONE_DRY_RUN=1) PAM is never called: any PIN of
// four or more digits unlocks.
// Keyboard: any key shows the PIN pad; digits (top row or keypad) type the
// PIN, Backspace deletes, Enter unlocks, Esc hides the pad. An incoming call
// takes the keys first (Enter/A answers, Esc/D declines).
WlSessionLock {
  id: lock
  locked: Phone.locked

  PamContext {
    id: pam
    config: Quickshell.env("OPHONE_PAM_SERVICE") || "ophone-lock"
    property string pending: ""
    onResponseRequiredChanged: if (responseRequired) respond(pending)
    onCompleted: result => {
      lock.busy = false
      if (result === PamResult.Success) { lock.pin = ""; Phone.unlock() }
      else { lock.status = "Wrong PIN"; lock.pin = "" }
    }
    onError: err => { lock.busy = false; lock.status = "Unlock error"; console.warn("pam:", PamError.toString(err)) }
  }
  property bool busy: false
  property string status: ""
  property string pin: ""
  function key(k) {
    status = ""
    if (k === "del") pin = pin.slice(0, -1)
    else if (k === "ok") { if (pin.length) tryUnlock(pin) }
    else if (pin.length < 12) pin += k
  }
  function tryUnlock(p) {
    if (Phone.dryRun) {
      if (p.length >= 4) { pin = ""; Phone.unlock() } else { status = "PIN is at least 4 digits"; pin = "" }
      return
    }
    busy = true; status = ""; pam.pending = p; pam.start()
  }

  WlSessionLockSurface {
    color: Theme.background

    Item {
      id: lockKeys
      anchors.fill: parent
      focus: true
      Keys.onPressed: ev => {
        ev.accepted = true
        if (!Phone.screenOn || lock.busy) return
        const k = ev.key
        if (k >= Qt.Key_0 && k <= Qt.Key_9) {
          const d = String(k - Qt.Key_0)
          Phone.pinVisible = true; lock.key(d); pad.flash(d)
        } else if (k === Qt.Key_Backspace || k === Qt.Key_Delete) {
          if (Phone.pinVisible) { lock.key("del"); pad.flash("del") }
        } else if (k === Qt.Key_Return || k === Qt.Key_Enter) {
          if (Phone.pinVisible) { lock.key("ok"); pad.flash("ok") } else Phone.pinVisible = true
        } else if (k === Qt.Key_Escape) {
          Phone.pinVisible = false; lock.pin = ""; lock.status = ""
        } else if (!(ev.modifiers & Qt.MetaModifier)) Phone.pinVisible = true
      }
    }

    Rectangle {
      anchors.fill: parent
      gradient: Gradient {
        GradientStop { position: 0; color: Qt.darker(Theme.accent, 3.2) }
        GradientStop { position: 0.7; color: Theme.background }
      }
    }
    StatusRow { width: parent.width; showTime: false }
    SystemClock { id: clock; precision: SystemClock.Minutes }

    Item {
      id: face
      anchors.fill: parent
      opacity: Phone.pinVisible ? 0 : 1
      visible: opacity > 0
      Behavior on opacity { NumberAnimation { duration: 150 } }

      Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.12
        spacing: Theme.px(4)
        Glyph { anchors.horizontalCenter: parent.horizontalCenter; text: "\u{f033e}"; size: 18; color: Theme.dim }
        Label { anchors.horizontalCenter: parent.horizontalCenter; text: Qt.formatTime(clock.date, "HH:mm"); size: 72; font.weight: Font.Light }
        Label { anchors.horizontalCenter: parent.horizontalCenter; text: Qt.formatDate(clock.date, "dddd, d MMMM"); size: 15 }
        Item { width: 1; height: Theme.px(18) }
        Rectangle {
          anchors.horizontalCenter: parent.horizontalCenter
          visible: Notifs.count > 0
          height: Theme.px(34); width: nlab.implicitWidth + Theme.px(28); radius: height / 2
          color: Theme.alpha(Theme.surface, 0.85)
          Label { id: nlab; anchors.centerIn: parent; size: 13
                  text: Notifs.count + (Notifs.count === 1 ? " notification" : " notifications") }
        }
      }

      Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom; anchors.bottomMargin: Theme.navH + Theme.px(16)
        spacing: Theme.px(6)
        Glyph { anchors.horizontalCenter: parent.horizontalCenter; text: "\u{f0143}"; size: 20; color: Theme.dim }
        Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Swipe up to unlock"; size: 13; color: Theme.dim }
        Label { anchors.horizontalCenter: parent.horizontalCenter; text: Theme.productName + " · " + Theme.motto; size: 11; color: Theme.dim; font.italic: true }
      }
      DragHandler {
        target: null; xAxis.enabled: false
        onActiveChanged: if (!active && translation.y < -Theme.px(60)) Phone.pinVisible = true
      }
      TapHandler { onTapped: Phone.pinVisible = true }
    }

    PinPad {
      id: pad
      anchors.centerIn: parent
      anchors.verticalCenterOffset: Theme.px(20)
      opacity: Phone.pinVisible ? 1 : 0
      visible: opacity > 0
      Behavior on opacity { NumberAnimation { duration: 150 } }
      pin: lock.pin
      status: lock.status
      busy: lock.busy
      onKeyPressed: k => lock.key(k)
    }
    Label {
      visible: Phone.pinVisible
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.bottom: parent.bottom; anchors.bottomMargin: Theme.navH + Theme.px(10)
      text: "Cancel"; size: 14; color: Theme.dim
      TapHandler { onTapped: { Phone.pinVisible = false; lock.pin = ""; lock.status = "" } }
    }

    Loader {
      anchors.fill: parent
      active: Notifs.incomingCall !== null
      onActiveChanged: if (!active) lockKeys.forceActiveFocus()
      sourceComponent: CallCard { call: Notifs.incomingCall; onLockScreen: true }
    }

    // Screen off: swallow touches so pocket presses do nothing.
    MouseArea { anchors.fill: parent; visible: !Phone.screenOn }
  }
}
