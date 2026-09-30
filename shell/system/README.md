# System files for the phone image

Installed by the device image, not by the shell (they need root):

| File | Install to | Why |
|---|---|---|
| `logind-ophone.conf` | `/etc/systemd/logind.conf.d/omarchy-phone.conf` | logind must ignore the power key so Hyprland gets it |
| `pam/ophone-lock` | `/etc/pam.d/ophone-lock` | PAM service used by the lock screen's PIN pad (its own secret, checked with pam_exec + `bin/ophone-pin`; throttled with pam_faillock -- see [DESIGN.md](../../docs/shell/DESIGN.md)) |
| `tmpfiles.d/omarchy-phone.conf` | `/usr/lib/tmpfiles.d/omarchy-phone.conf` | creates `/etc/omarchy-phone` (the PIN hash lives there) and `/run/omarchy-phone/faillock` (pam_faillock's tally dir; the default `/run/faillock` isn't writable by the unprivileged session user this PAM stack runs as) |
| `bluetooth/main.conf` | `/etc/bluetooth/main.conf` | bluetoothd defaults: not discoverable/pairable at rest, no Just-Works re-pairing, resolvable LE address (F5 in the security review) |
| `systemd/ophone-btagentd.service` | `/usr/lib/systemd/user/ophone-btagentd.service`, then `systemctl --user enable --now ophone-btagentd.service` | runs `bin/ophone-btagentd`, the real BlueZ pairing agent that requires an on-screen Pair/Reject tap (F5/F6) instead of bluetoothd's default auto-accept agent |

Provisioning a PIN (once per device, not part of the image build):

    sudo ophone-pin set

Session start (e.g. from a greeter or autologin on tty1):

    OPHONE_DEVICE=iphone6s Hyprland --config /usr/share/omarchy-phone/shell/hypr/hyprland.lua

Runtime dependencies: hyprland (>= 0.56, Lua config), quickshell (>= 0.3),
wtype, wireplumber (wpctl), brightnessctl, networkmanager, bluez, upower,
a Nerd Font (JetBrainsMono Nerd Font), Noto Sans, Yaru icons, python (for
`bin/ophone-pin` and `bin/ophone-btagentd`) and python-gobject (for
`bin/ophone-btagentd`'s D-Bus/BlueZ agent -- both already pulled in by the
Phone app). Optional: wvkbd (alternative on-screen keyboard).
