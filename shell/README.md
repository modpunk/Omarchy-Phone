# Omarchy Phone shell

The phone shell: a Hyprland config (`hypr/`, Lua, Hyprland 0.56) plus one
QuickShell process (`qs/`) for the home screen, status bar, shade, app
switcher, lock screen, on-screen keyboard and incoming-call surface. Design
notes: [docs/shell/DESIGN.md](../docs/shell/DESIGN.md). App integration:
[docs/shell/INTEGRATION.md](../docs/shell/INTEGRATION.md). Files the device
image installs: [system/README.md](system/README.md).

Preview on a desktop (nested and headless, own runtime dir; nothing shows on
or touches the host session):

    shell/preview/run.sh            # every scenario, screenshots to docs/shell/screenshots/
    shell/preview/run.sh keys       # just the keyboard scenarios
    shell/preview/run.sh --hold     # keep it running; attach with: source /tmp/oph-$UID/env

## Keyboard

Everything works from a keyboard (the first iPhone 6s has no working touch
yet, so a Bluetooth keyboard is its input). Anywhere:

| Keys | Action |
|---|---|
| `SUPER+H` | home |
| `SUPER+Tab` | app switcher |
| `SUPER+N` | shade (quick settings + notifications) |
| `SUPER+L` | lock |
| `SUPER+Esc` | power key: tap = lock + screen off / wake, hold = power menu |
| `SUPER+Shift+Esc` | power menu |
| `SUPER+Up` / `SUPER+Down`, `SUPER+M` | volume, silent mode (media keys work too) |
| `SUPER+Left` / `SUPER+Right` | previous / next app |
| `SUPER+K` | on-screen keyboard |

In the shell's own surfaces: arrows and Tab move the focus ring, Enter
activates, Esc closes or goes back. On the home screen, type to search apps
by name and use PageUp/PageDown to flip pages. In the switcher and shade,
Delete closes an app or dismisses a notification. On the lock screen, type
the PIN and press Enter. On an incoming call, Enter answers and Esc
declines. Full key map: [DESIGN.md, Keyboard](../docs/shell/DESIGN.md#keyboard).
