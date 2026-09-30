pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// System-wide tap-to-call (docs/phone/DESIGN.md §4.1, docs/BACKLOG.md P1):
// watches the Wayland clipboard for phone numbers with the same detector
// `phonectl detect` already exposes (apps/phone/omarchy_phone/numbers.py),
// so a number copied from *any* app (Messages, a browser, a PDF, a
// terminal) can be tapped to call -- not just numbers already inside the
// Phone app.
//
// Opt-in and off by default (Config.tapToCallClipboard), mirroring the
// in-app clipboard chip's own stance (docs/phone/DESIGN.md "Clipboard
// detection (opt-in, off by default for privacy)"): nothing here touches
// the clipboard unless the user turned it on, or OPHONE_CLIPBOARD_DIAL=1
// overrides it for previews/tests (see shell/preview/run.sh).
//
// Follow-up, not implemented here: scanning notification bodies
// (Services/Notifs.qml) for numbers too. The clipboard path is the one
// this shell can watch cleanly with what it already has -- `wl-paste
// --watch`, the same external-process idiom Phone.qml's `imWatch` already
// uses for ophone-im. Scanning every incoming notification body is a
// separate, noisier surface (most notifications have no phone number in
// them at all) and deserves its own opt-in and its own change.
Singleton {
  id: root

  readonly property string shellDir: Quickshell.env("OPHONE_SHELL") || Quickshell.shellDir + "/.."
  // apps/phone lives next to shell/ in both the source tree and the
  // installed image (shell/system/README.md: shell installs under
  // /usr/share/omarchy-phone/shell) -- OPHONE_PHONECTL overrides this for
  // a non-standard layout.
  readonly property string phonectlPath: Quickshell.env("OPHONE_PHONECTL") || (shellDir + "/../apps/phone/bin/phonectl")
  readonly property string region: Quickshell.env("OPHONE_REGION") || "US"
  readonly property bool enabled: Config.tapToCallClipboard || Quickshell.env("OPHONE_CLIPBOARD_DIAL") === "1"

  // The most recent batch of numbers detected in one clipboard snapshot,
  // e.g. [{uri: "tel:+12125550101", raw: "(212) 555-0101"}]. Cleared once
  // dismissed, dialed, superseded by a later clipboard change that no
  // longer has a number in it, or after autoHideTimer times out.
  property var current: []

  function clear() { current = [] }

  // phonectl detect prints one "tel:+e164<TAB>raw text" line per match and
  // reads stdin when given no TEXT argument (works without phoned running
  // -- see apps/phone/omarchy_phone/cli.py). `wl-paste --watch <command>`
  // re-execs <command> with the new clipboard contents on its stdin every
  // time the clipboard changes, so piping it straight into phonectl detect
  // needs no polling and no extra glue script.
  //
  // phonectl prints *nothing* when a snapshot has no number in it, so a
  // plain `wl-paste --watch phonectl ... detect` would never signal "the
  // clipboard changed to something with no number" -- the chip would keep
  // showing the previous match forever. The `sh -c 'echo; exec ...'`
  // wrapper guarantees one blank marker line per snapshot regardless, so
  // every clipboard change -- match or not -- resets the batch.
  property var _batch: []
  Timer {
    id: settleTimer
    // A single clipboard snapshot's matches arrive as a burst of lines
    // (the marker, then zero or more matches) in one process's stdout;
    // 150ms of silence after the last line is "this invocation is done",
    // the same kind of debounce Phone.qml uses for ophone-im's
    // activate/content events.
    interval: 150
    onTriggered: { root.current = root._batch; root._batch = [] }
  }
  // A chip nobody taps shouldn't sit over every app indefinitely (also the
  // shell's usual heads-up shape -- Notifs.qml's own banner times out too).
  Timer { id: autoHideTimer; interval: 15000; onTriggered: root.clear() }
  onCurrentChanged: if (current.length > 0) autoHideTimer.restart(); else autoHideTimer.stop()

  Process {
    id: watcher
    running: root.enabled
    command: ["wl-paste", "--type", "text", "--watch", "sh", "-c", "echo; exec \"$0\" \"$@\"",
              root.phonectlPath, "--region", root.region, "detect"]
    stdout: SplitParser {
      onRead: line => {
        if (line === "") { root._batch = []; settleTimer.restart(); return }   // new snapshot marker
        const tab = line.indexOf("\t")
        if (tab < 0) return
        root._batch = root._batch.concat([{ uri: line.slice(0, tab), raw: line.slice(tab + 1) }])
        settleTimer.restart()
      }
    }
    onExited: (code, status) => {
      // wl-paste itself died (no wl-clipboard installed, no compositor
      // clipboard support, ...). Best-effort feature, no daemon to restart
      // against: back off and try again rather than spin, same shape as
      // Phone.qml's imRestart.
      if (root.enabled) restartTimer.restart()
    }
  }
  Timer { id: restartTimer; interval: 5000; onTriggered: { watcher.running = false; watcher.running = Qt.binding(() => root.enabled) } }
}
