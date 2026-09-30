pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Services.Pam

// Lock-screen PIN authentication (docs/shell/DESIGN.md "Lock screen PIN").
//
// This is a singleton -- not a plain child of LockScreen.qml's WlSessionLock
// -- on purpose. WlSessionLock's default property is a single Component
// (its per-output surface: see WlSessionLockSurface), so any plain object
// declared directly inside it, like a PamContext, gets swept into that
// Component along with everything else and re-instantiated once per output,
// in a child id-scope that WlSessionLock's own functions can't see back
// into. `pam` would exist, but "pam is not defined" from a function attached
// to the WlSessionLock itself -- a real bug, just never exercised before,
// since the preview's dryRun shortcut always returned before reaching
// pam.start(). A singleton sidesteps both problems: one PamContext for the
// whole shell (not one per screen), reachable by name from anywhere the way
// Phone and Notifs already are.
Singleton {
  id: root
  property bool busy: false
  property string lastError: ""
  signal succeeded()
  signal failed(string message)

  function tryUnlock(pin) {
    if (busy) return
    busy = true
    lastError = ""
    pam.pending = pin
    pam.start()
  }

  PamContext {
    id: pam
    // PAM service: /etc/pam.d/ophone-lock (shell/system/pam/ophone-lock), or
    // $OPHONE_PAM_SERVICE. configDirectory overrides PAM's own service-file
    // search path -- set by shell/tests/ and manual preview runs
    // ($OPHONE_PAM_DIR) to exercise the real pam_exec + pam_faillock chain
    // against a throwaway PIN file and faillock tally dir, instead of
    // /etc/pam.d and /etc/omarchy-phone.
    config: Quickshell.env("OPHONE_PAM_SERVICE") || "ophone-lock"
    configDirectory: Quickshell.env("OPHONE_PAM_DIR") || ""
    property string pending: ""
    onResponseRequiredChanged: if (responseRequired) respond(pending)
    onCompleted: result => {
      root.busy = false
      if (result === PamResult.Success) { root.succeeded() }
      else { root.lastError = "Wrong PIN"; root.failed(root.lastError) }
    }
    onError: err => {
      root.busy = false
      root.lastError = "Unlock error"
      console.warn("pam:", PamError.toString(err))
      root.failed(root.lastError)
    }
  }
}
