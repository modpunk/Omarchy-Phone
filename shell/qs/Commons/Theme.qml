pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Palette + layout unit for the phone shell.
//
// `u` is the layout unit: 1u = 1 logical px on a 375 px wide phone (iPhone
// 6s/7/8/SE2). Every size in the shell is a multiple of `u`, so a 360 px
// Android phone or a 414 px Plus-sized one gets the same layout, scaled.
// Palette defaults are Omarchy's Tokyo Night; if Omarchy's current theme
// state exists, its colors.toml overrides them (and theme swaps apply live).
Singleton {
  id: root

  property real screenWidth: Quickshell.screens.length ? Quickshell.screens[0].width : 375
  property real screenHeight: Quickshell.screens.length ? Quickshell.screens[0].height : 667
  readonly property real u: Math.max(0.75, Math.min(2.0, Math.min(screenWidth, screenHeight) / 375))
  function px(n) { return Math.round(n * u) }
  function font(n) { return Math.max(8, Math.round(n * u)) }

  // Structural sizes, all in units
  readonly property int statusH: px(24)
  readonly property int navH: px(22)
  readonly property int touch: px(44)
  readonly property int pad: px(12)
  readonly property int radius: px(14)
  readonly property int iconSize: px(56)

  readonly property string fontFamily: "JetBrainsMono Nerd Font"
  readonly property string textFamily: "Noto Sans"

  // Palette
  property color background: "#1a1b26"
  property color surface: "#24283b"
  property color surfaceHi: "#292e42"
  property color foreground: "#c0caf5"
  property color dim: "#565f89"
  property color accent: "#7aa2f7"
  property color good: "#9ece6a"
  property color urgent: "#f7768e"
  property color warn: "#e0af68"
  readonly property color scrim: Qt.rgba(0, 0, 0, 0.55)

  function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }

  readonly property string motto: "Vox Libertatis"
  readonly property string productName: "Omarchy Phone"

  FileView {
    path: Quickshell.env("HOME") + "/.local/state/omarchy/current/theme/colors.toml"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      const v = {}
      for (const line of text().split("\n")) {
        const m = line.match(/^\s*([a-z_]+)\s*=\s*"(#[0-9a-fA-F]{6,8})"/)
        if (m) v[m[1]] = m[2]
      }
      if (v.background) root.background = v.background
      if (v.lighter_background) root.surface = v.lighter_background
      if (v.selection) root.surfaceHi = v.selection
      if (v.bright_foreground || v.foreground) root.foreground = v.bright_foreground || v.foreground
      if (v.dark_foreground || v.muted) root.dim = v.dark_foreground || v.muted
      if (v.accent) root.accent = v.accent
      if (v.green) root.good = v.green
      if (v.red) root.urgent = v.red
      if (v.yellow) root.warn = v.yellow
    }
  }
}
