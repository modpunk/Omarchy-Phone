# System files for the phone image

Installed by the device image, not by the shell (they need root):

| File | Install to | Why |
|---|---|---|
| `logind-ophone.conf` | `/etc/systemd/logind.conf.d/omarchy-phone.conf` | logind must ignore the power key so Hyprland gets it |
| `pam/ophone-lock` | `/etc/pam.d/ophone-lock` | PAM service used by the lock screen's PIN pad |

Session start (e.g. from a greeter or autologin on tty1):

    OPHONE_DEVICE=iphone6s Hyprland --config /usr/share/omarchy-phone/shell/hypr/hyprland.lua

Runtime dependencies: hyprland (>= 0.56, Lua config), quickshell (>= 0.3),
wtype, wireplumber (wpctl), brightnessctl, networkmanager, bluez, upower,
a Nerd Font (JetBrainsMono Nerd Font), Noto Sans, Yaru icons. Optional:
wvkbd (alternative on-screen keyboard).
