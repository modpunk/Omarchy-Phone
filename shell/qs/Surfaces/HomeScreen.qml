import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import qs.Commons
import qs.Services
import qs.Widgets

// Background layer: shows through on the (empty) home workspace.
// Clock, paged 4-column app grid, favourites dock.
PanelWindow {
  id: home
  anchors { top: true; bottom: true; left: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.layer: WlrLayer.Background
  WlrLayershell.namespace: "ophone-home"
  color: Theme.background

  readonly property var apps: DesktopEntries.applications.values
    .filter(e => !e.noDisplay && e.name && !Config.isHidden(e))
    .sort((a, b) => a.name.localeCompare(b.name))
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
    Label { anchors.horizontalCenter: parent.horizontalCenter; text: Qt.formatDate(clock.date, "dddd, d MMMM"); size: 14; color: Theme.foreground; opacity: 0.8 }
  }

  readonly property int cols: 4
  readonly property int cellW: Math.floor((width - 2 * Theme.pad) / cols)
  readonly property int cellH: Theme.iconSize + Theme.px(30)
  readonly property int gridTop: header.y + header.height + Theme.px(22)
  readonly property int gridBottom: height - Theme.navH - dockBox.height - Theme.px(28)
  readonly property int rows: Math.max(1, Math.floor((gridBottom - gridTop) / cellH))
  readonly property int perPage: rows * cols

  component AppIcon: Item {
    id: tile
    required property var entry
    width: home.cellW; height: home.cellH
    property bool showLabel: true
    Rectangle {
      id: plate
      anchors.horizontalCenter: parent.horizontalCenter
      width: Theme.iconSize; height: width; radius: Theme.px(14)
      color: tap.pressed ? Theme.surfaceHi : Theme.alpha(Theme.surface, 0.85)
      readonly property string iconSrc: Quickshell.iconPath(tile.entry.icon, true)
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
      text: tile.entry.name; size: 11
    }
    TapHandler { id: tap; onTapped: Phone.launch(tile.entry) }
  }

  ListView {
    id: pages
    x: Theme.pad; y: home.gridTop
    width: parent.width - 2 * Theme.pad; height: home.rows * home.cellH
    orientation: ListView.Horizontal
    snapMode: ListView.SnapOneItem
    highlightRangeMode: ListView.StrictlyEnforceRange
    boundsBehavior: Flickable.StopAtBounds
    clip: true
    model: Math.max(1, Math.ceil(home.apps.length / home.perPage))
    delegate: Grid {
      required property int index
      width: pages.width; height: pages.height
      columns: home.cols
      Repeater {
        model: home.apps.slice(index * home.perPage, (index + 1) * home.perPage)
        delegate: AppIcon { required property var modelData; entry: modelData }
      }
    }
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
        delegate: AppIcon { required property var modelData; entry: modelData; showLabel: false; height: Theme.iconSize }
      }
    }
  }
}
