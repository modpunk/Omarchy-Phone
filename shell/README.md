# Omarchy Phone shell

The phone shell: a Hyprland config (`hypr/`, Lua, Hyprland 0.56) plus one
QuickShell process (`qs/`) for the home screen, status bar, shade, app
switcher, lock screen, on-screen keyboard and incoming-call surface. Design
notes: [docs/shell/DESIGN.md](../docs/shell/DESIGN.md). App integration:
[docs/shell/INTEGRATION.md](../docs/shell/INTEGRATION.md). Files the device
image installs: [system/README.md](system/README.md).

## Security

Hardened per `~/Work/hoolock-iphone5s/notes/security-review.md` (F2-F6):
see [DESIGN.md](../docs/shell/DESIGN.md#lock-screen-pin) for the full
threat model. In short:

* **Lock screen PIN** (`bin/ophone-pin`, `system/pam/ophone-lock`): its own
  secret, independent of the account/SSH/sudo password, hashed with
  `scrypt` in `/etc/omarchy-phone/pin-hash`, checked via `pam_exec` with
  `pam_faillock` throttling. `sudo ophone-pin set` to provision one.
* **Idle auto-lock** (`Phone.qml`): locks (if a PIN is configured) and
  blanks the screen after `Config.idleLockSeconds` (default 180s) idle, via
  Hyprland's `ext-idle-notify-v1`. Boots locked whenever a PIN is
  configured, never unlocked-by-default the way it used to be.
* **Bluetooth pairing agent** (`bin/ophone-btagentd`): a real `KeyboardDisplay`
  BlueZ agent that requires an explicit on-screen Pair/Reject tap, replacing
  bluetoothd's default agent, which auto-accepted every Just-Works pairing.

Tests: `shell/tests/run.sh` (unit tests for `ophone-pin` and
`ophone-btagentd`, on a private D-Bus session bus).

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
