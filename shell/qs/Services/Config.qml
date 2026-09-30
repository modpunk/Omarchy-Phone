pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// User settings: $XDG_CONFIG_HOME/omarchy-phone/shell.json (optional).
//   { "favorites": ["org.gnome.Calls", "foot", ...], "wallpaper": "/path.jpg",
//     "tapToCallClipboard": true }
Singleton {
  id: root
  property var favorites: ["omarchy-phone", "org.omarchy.Phone", "foot", "chromium", "org.gnome.Nautilus", "firefox", "Alacritty"]
  // Desktop-only or helper entries that make no sense on a phone grid.
  property var hidden: ["avahi", "bssh", "bvnc", "fcitx", "footclient", "foot-server", "hwloc", "lstopo",
                        "qv4l2", "qvidcap", "electron", "uuctl", "xgps", "xgpsspeed", "nm-connection-editor",
                        "org.freedesktop.impl", "kbd-layout-viewer", "cmake-gui", "jshell", "jconsole", "java"]
  function isHidden(e) {
    const id = (e.id || "").toLowerCase()
    for (const h of hidden) if (id.indexOf(h) >= 0) return true
    return false
  }
  property string wallpaper: Quickshell.env("OPHONE_WALLPAPER") || ""
  // Idle timeout before the shell locks (if a PIN is configured) and blanks
  // the screen (docs/shell/DESIGN.md "Idle auto-lock"). OPHONE_IDLE_SECONDS
  // overrides this for quick testing (shell/preview/run.sh scenarios).
  property int idleLockSeconds: 180
  // System-wide tap-to-call (docs/phone/DESIGN.md §4.1, Services/NumberDetect.qml):
  // opt-in and off by default, mirroring the in-app clipboard chip's own
  // privacy stance ("Clipboard detection (opt-in, off by default for
  // privacy)"). OPHONE_CLIPBOARD_DIAL=1 overrides this for previews/tests.
  property bool tapToCallClipboard: false

  FileView {
    path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/omarchy-phone/shell.json"
    printErrors: false
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try {
        const j = JSON.parse(text())
        if (Array.isArray(j.favorites)) root.favorites = j.favorites
        if (Array.isArray(j.hidden)) root.hidden = root.hidden.concat(j.hidden)
        if (typeof j.wallpaper === "string") root.wallpaper = j.wallpaper
        if (Number.isFinite(j.idleLockSeconds)) root.idleLockSeconds = j.idleLockSeconds
        if (typeof j.tapToCallClipboard === "boolean") root.tapToCallClipboard = j.tapToCallClipboard
      } catch (e) { console.warn("omarchy-phone: bad shell.json:", e) }
    }
  }
}
