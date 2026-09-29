import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import qs.Commons
import qs.Services
import qs.Widgets

// Background layer: shows through on the (empty) home workspace.
// Clock, paged 4-column app grid, favourites dock.
// Keyboard: arrows/Tab move a focus ring over the grid and dock, Enter
// launches, PageUp/PageDown flip pages, typing filters apps by name.
PanelWindow {
  id: home
  anchors { top: true; bottom: true; left: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.layer: WlrLayer.Background
  WlrLayershell.namespace: "ophone-home"
  color: Theme.background
  // Take the keyboard only while the (empty) home workspace is showing and no
  // overlay is up; an app on the app workspace keeps its keys.
  WlrLayershell.keyboardFocus: Phone.atHome && !Phone.locked && !Phone.anyOverlay && Notifs.incomingCall === null
    ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

  readonly property var apps: DesktopEntries.applications.values
    .filter(e => !e.noDisplay && e.name && !Config.isHidden(e))
    .sort((a, b) => a.name.localeCompare(b.name))
  // Type-to-search: `query` filters the grid by name (prefix matches first).
  property string query: ""
  readonly property var shown: {
    const q = query.trim().toLowerCase()
    if (!q) return apps
    const hit = apps.filter(e => e.name.toLowerCase().includes(q))
    return hit.filter(e => e.name.toLowerCase().startsWith(q)).concat(hit.filter(e => !e.name.toLowerCase().startsWith(q)))
  }
  // Keyboard selection: 0..shown.length-1 = grid, then the dock. -1 = none
  // (no ring; touch never sets it).
  property int sel: -1
  onQueryChanged: { sel = query && shown.length ? 0 : -1; pages.currentIndex = 0 }
  onSelChanged: if (sel >= 0 && sel < shown.length) pages.currentIndex = Math.floor(sel / perPage)
  function clearKeys() { query = ""; sel = -1 }
  Connections {
    target: Phone
    function onAtHomeChanged() { if (!Phone.atHome) home.clearKeys() }
    function onHomeRequested() { home.clearKeys() }
    function onLockedChanged() { home.clearKeys() }
  }
  function entryAt(i) { return i < shown.length ? shown[i] : dock[i - shown.length] }
  function launchAt(i) { const e = entryAt(i); if (e) { clearKeys(); Phone.launch(e) } }

  function move(k) {
    const n = shown.length, d = dock.length, total = n + d
    if (!total) return
    if (sel < 0 || sel >= total) {
      let pg = pages.currentIndex
      if (k === Qt.Key_PageDown || k === Qt.Key_PageUp) pg = Math.max(0, Math.min(pages.count - 1, pg + (k === Qt.Key_PageDown ? 1 : -1)))
      sel = n ? Math.min(n - 1, pg * perPage) : n
      return
    }
    let s = sel
    if (k === Qt.Key_Tab) s = (s + 1) % total
    else if (k === Qt.Key_Backtab) s = (s - 1 + total) % total
    else if (k === Qt.Key_Home) s = 0
    else if (k === Qt.Key_End) s = total - 1
    else if (s < n) {                                   // in the grid
      const pos = s % perPage, row = Math.floor(pos / cols), col = pos % cols
      if (k === Qt.Key_Right) s = Math.min(total - 1, s + 1)
      else if (k === Qt.Key_Left) s = Math.max(0, s - 1)
      else if (k === Qt.Key_Up) s = row > 0 ? s - cols : s
      else if (k === Qt.Key_Down) {
        if (row < rows - 1 && s + cols < n) s += cols
        else if (row < rows - 1 && Math.floor((n - 1) % perPage / cols) > row && Math.floor((n - 1) / perPage) === Math.floor(s / perPage)) s = n - 1
        else if (d) s = n + Math.min(col, d - 1)
      } else if (k === Qt.Key_PageDown || k === Qt.Key_PageUp) {
        const pg = Math.max(0, Math.min(pages.count - 1, Math.floor(s / perPage) + (k === Qt.Key_PageDown ? 1 : -1)))
        s = Math.min(n - 1, pg * perPage + pos)
      }
    } else {                                            // in the dock
      const i = s - n
      if (k === Qt.Key_Right) s = Math.min(total - 1, s + 1)
      else if (k === Qt.Key_Left) s = s - 1
      else if (k === Qt.Key_Up && n) {
        const base = pages.currentIndex * perPage, cnt = Math.min(perPage, n - base)
        s = Math.min(base + Math.floor((cnt - 1) / cols) * cols + i, base + cnt - 1)
      } else if (k === Qt.Key_PageDown || k === Qt.Key_PageUp) {
        pages.currentIndex = Math.max(0, Math.min(pages.count - 1, pages.currentIndex + (k === Qt.Key_PageDown ? 1 : -1)))
        return
      }
    }
    sel = s
  }
  function onKey(ev) {
    const k = Phone.keyOf(ev)
    const nav = [Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab, Qt.Key_Backtab,
                 Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown]
    if (nav.indexOf(k) >= 0) { move(k); ev.accepted = true; return }
    if (k === Qt.Key_Return || k === Qt.Key_Enter) {
      if (sel >= 0) launchAt(sel); else if (query && shown.length) launchAt(0); else move(Qt.Key_Home)
    } else if (k === Qt.Key_Escape) {
      if (query) query = ""; else sel = -1
    } else if (k === Qt.Key_Backspace) {
      query = query.slice(0, -1)
    } else if (ev.text.length === 1 && ev.text >= " " && ev.text !== "\x7f" && !(ev.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) {
      if (ev.text !== " " || query) query += ev.text
    } else return
    ev.accepted = true
  }
  Item { anchors.fill: parent; focus: true; Keys.onPressed: ev => home.onKey(ev) }

  readonly property var dock: {
    const out = []
    if (apps.length === 0) return out   // re-evaluate once entries are scanned
    for (const id of Config.favorites) {
      const e = DesktopEntries.heuristicLookup(id)
      if (e && out.indexOf(e) < 0) out.push(e)
      if (out.length === 4) break
    }
    return out
  }

  // Cheap wallpaper: a vertical gradient from the theme, or an image when set.
  Rectangle {
    anchors.fill: parent
    gradient: Gradient {
      GradientStop { position: 0; color: Qt.darker(Theme.accent, 3.2) }
      GradientStop { position: 0.55; color: Theme.background }
      GradientStop { position: 1; color: Qt.darker(Theme.background, 1.4) }
    }
  }
  Image {
    anchors.fill: parent
    visible: Config.wallpaper !== ""
    source: Config.wallpaper ? "file://" + Config.wallpaper : ""
    fillMode: Image.PreserveAspectCrop
    sourceSize.width: width; sourceSize.height: height
    asynchronous: true
  }

  SystemClock { id: clock; precision: SystemClock.Minutes }

  Column {
    id: header
    y: Theme.statusH + Theme.px(18)
    anchors.horizontalCenter: parent.horizontalCenter
    spacing: Theme.px(2)
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: Qt.formatTime(clock.date, "HH:mm"); size: 54; font.weight: Font.Light }
    Item {   // the date line, or the search chip while typing
      anchors.horizontalCenter: parent.horizontalCenter
      width: home.width; height: Theme.px(26)
      Label { anchors.centerIn: parent; visible: !home.query; text: Qt.formatDate(clock.date, "dddd, d MMMM"); size: 14; color: Theme.foreground; opacity: 0.8 }
      Rectangle {
        visible: home.query !== ""
        anchors.centerIn: parent
        height: parent.height; radius: height / 2
        width: Math.min(home.width - 2 * Theme.pad, chip.implicitWidth + Theme.px(24))
        color: Theme.alpha(Theme.surface, 0.9)
        border.color: Theme.accent; border.width: Math.max(1, Theme.px(1.5))
        Row {
          id: chip
          anchors.centerIn: parent
          spacing: Theme.px(6)
          Glyph { text: "\u{f0349}"; size: 14; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
          Label { text: home.query; size: 14; anchors.verticalCenter: parent.verticalCenter }
          Label { text: home.shown.length + (home.shown.length === 1 ? " app" : " apps"); size: 11; color: Theme.dim; anchors.verticalCenter: parent.verticalCenter }
        }
      }
    }
  }

  readonly property int cols: 4
  readonly property int cellW: Math.floor((width - 2 * Theme.pad) / cols)
  readonly property int cellH: Theme.iconSize + Theme.px(30)
  readonly property int gridTop: header.y + header.height + Theme.px(22)
  // Room for the Omarchy Phone logo between the app grid and the dock.
  readonly property int logoH: Theme.px(40)
  readonly property int gridBottom: height - Theme.navH - dockBox.height - Theme.px(28) - logoH - Theme.px(16)
  readonly property int rows: Math.max(1, Math.floor((gridBottom - gridTop) / cellH))
  readonly property int perPage: rows * cols

  component AppIcon: Item {
    id: tile
    required property var entry
    property int flat: -1              // position in the keyboard order
    readonly property bool focused: flat >= 0 && home.sel === flat
    width: home.cellW; height: home.cellH
    property bool showLabel: true
    Rectangle {
      id: plate
      anchors.horizontalCenter: parent.horizontalCenter
      width: Theme.iconSize; height: width; radius: Theme.px(14)
      color: tap.pressed ? Theme.surfaceHi : Theme.alpha(Theme.surface, 0.85)
      readonly property string iconSrc: Quickshell.iconPath(tile.entry.icon, true)
      FocusRing { shown: tile.focused }
      IconImage {
        visible: plate.iconSrc !== ""
        anchors.centerIn: parent
        implicitSize: Math.round(parent.width * 0.72)
        source: plate.iconSrc
      }
      Label {   // no icon in the theme: first letter, like a monogram
        visible: plate.iconSrc === ""
        anchors.centerIn: parent
        text: tile.entry.name.charAt(0).toUpperCase(); size: 26; strong: true; color: Theme.accent
      }
    }
    Label {
      visible: tile.showLabel
      anchors.top: plate.bottom; anchors.topMargin: Theme.px(5)
      anchors.horizontalCenter: parent.horizontalCenter
      width: parent.width - Theme.px(6)
      horizontalAlignment: Text.AlignHCenter
      text: tile.entry.name; size: 11; strong: tile.focused
    }
    TapHandler { id: tap; onTapped: { home.clearKeys(); Phone.launch(tile.entry) } }
  }

  ListView {
    id: pages
    // ringRoom: headroom so the focus ring on the top row isn't clipped;
    // the pages' topPadding cancels it, so icons sit where they always did.
    readonly property int ringRoom: Theme.px(6)
    x: Theme.pad; y: home.gridTop - ringRoom
    width: parent.width - 2 * Theme.pad; height: home.rows * home.cellH + ringRoom
    orientation: ListView.Horizontal
    snapMode: ListView.SnapOneItem
    highlightRangeMode: ListView.StrictlyEnforceRange
    boundsBehavior: Flickable.StopAtBounds
    clip: true
    highlightMoveDuration: 160
    model: Math.max(1, Math.ceil(home.shown.length / home.perPage))
    delegate: Grid {
      id: page
      required property int index
      width: pages.width; height: pages.height
      topPadding: pages.ringRoom
      columns: home.cols
      Repeater {
        model: home.shown.slice(page.index * home.perPage, (page.index + 1) * home.perPage)
        delegate: AppIcon { required property var modelData; required property int index; entry: modelData; flat: page.index * home.perPage + index }
      }
    }
  }
  Label {
    visible: home.query !== "" && home.shown.length === 0
    anchors.horizontalCenter: parent.horizontalCenter
    y: pages.y + Theme.px(30)
    text: "No apps match \u201c" + home.query + "\u201d"; size: 14; color: Theme.dim
  }

  Row {
    anchors.horizontalCenter: parent.horizontalCenter
    y: pages.y + pages.height + Theme.px(4)
    spacing: Theme.px(6)
    visible: pages.count > 1
    Repeater {
      model: pages.count
      delegate: Rectangle {
        required property int index
        width: Theme.px(6); height: width; radius: width / 2
        color: Theme.foreground; opacity: index === pages.currentIndex ? 0.9 : 0.3
      }
    }
  }

  // Omarchy Phone logo (mark, wordmark and "Vox Libertatis"), centred in the
  // gap between the app grid and the dock.
  Image {
    id: brandLogo
    anchors.horizontalCenter: parent.horizontalCenter
    y: Math.round((pages.y + pages.height + Theme.px(12) + dockBox.y) / 2 - height / 2)
    width: Math.round(parent.width * 0.62); height: home.logoH
    source: Qt.resolvedUrl("../assets/omarchy-phone-logo.svg")
    sourceSize.width: width; sourceSize.height: height
    fillMode: Image.PreserveAspectFit
    smooth: true
    opacity: 0.9
  }

  Rectangle {
    id: dockBox
    anchors.bottom: parent.bottom; anchors.bottomMargin: Theme.navH + Theme.px(8)
    anchors.horizontalCenter: parent.horizontalCenter
    width: parent.width - 2 * Theme.pad; height: home.cellH - Theme.px(14)
    radius: Theme.px(22)
    color: Theme.alpha(Theme.surface, 0.55)
    visible: home.dock.length > 0
    Row {
      anchors.centerIn: parent
      Repeater {
        model: home.dock
        delegate: AppIcon { required property var modelData; required property int index; entry: modelData; showLabel: false; height: Theme.iconSize
                            flat: home.shown.length + index }
      }
    }
  }
}
