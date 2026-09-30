<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="brand/logo-light.svg">
    <img alt="Omarchy Phone: Vox Libertatis" src="brand/logo-light.svg" width="720">
  </picture>
</p>

# Omarchy Phone

*Vox Libertatis*

Omarchy (opinionated Arch Linux + Hyprland) adapted for small form factor devices: smartphones.

<p align="center">
  <img alt="Omarchy Phone home screen on an iPhone 6s" src="docs/screenshots/iphone6s-home.png" width="300">
  <br><sub>Running on real hardware: an iPhone 6s, Hyprland 0.56 with software rendering
  (screenshot taken on the phone).</sub>
</p>

## Status

Omarchy Phone boots on its first device, an **iPhone 6s** running Arch Linux ARM from RAM on
[HoolockLinux](https://github.com/HoolockLinux) (drivers, boot kit and userland image:
[Omarchy-iPhone6s](https://github.com/modpunk/Omarchy-iPhone6s)). On the phone today: Hyprland,
the phone shell's home screen, status bar and dock, a Bluetooth keyboard, and battery readings.
Touch input, charging and Wi-Fi are still missing on that device, so the Phone app can't place
real calls there yet.

| Component | What it is | State |
|---|---|---|
| `shell/` | The phone shell for Hyprland (QuickShell): status bar, home screen and app grid, dock, gesture nav bar, pull-down shade with quick settings, app switcher, PIN lock screen, incoming-call screen, volume OSD, power menu, on-screen keyboard. Hardware keys: home (press, double-press), power (lock, long-press menu), volume, ring switch. | Runs on the iPhone 6s; in review in [#2](https://github.com/modpunk/Omarchy-Phone/pull/2) |
| `apps/phone/` | The Phone app (GTK4 + libadwaita) and `phoned` daemon: calls over Wi-Fi through a pluggable backend (SIP via baresip first, MatrixRTC planned), contacts with vCard import/export, favourites and groups, recents, keypad, call screening (block/allow/spam lists, unknown and withheld caller policies, do-not-disturb), tap-to-call on detected numbers, voice/video switching, group calls, PipeWire audio routing. | Works on the loopback test backend (48 tests pass); in review in [#3](https://github.com/modpunk/Omarchy-Phone/pull/3) |
| `brand/` | The Omarchy Phone logo, mark, wordmark, app icons and social preview. | Done |

## Try it on a phone

Everything above runs on real hardware today, tethered over USB: the shell, the home screen, a
Bluetooth keyboard, and Hyprland with software rendering on an iPhone 6s. Nothing is written to
the phone's storage, so there's nothing to undo afterwards.

The full walkthrough — building the kernel and userland, DFU, pushing the image, pairing a
keyboard, and a troubleshooting table — lives in
[Omarchy-iPhone6s's getting-started guide](https://github.com/modpunk/Omarchy-iPhone6s/blob/main/docs/getting-started.md).

## Design

- One full-screen app at a time; everything scales from the screen width, so other phones get the
  same layout.
- Light enough for 2 slow cores, 2 GB of RAM and no GPU: few surfaces, cheap animations, no blur.
- Apps talk to the shell through plain freedesktop notifications, including incoming calls.

Design docs live next to the code: `docs/shell/DESIGN.md` and `docs/shell/INTEGRATION.md` for the
shell, `docs/phone/DESIGN.md` and `docs/phone/API.md` for the Phone app.

## First target device

iPhone 6s: 750x1334 panel at scale 2 (375x667 logical), 2 cores, 2 GB RAM, software rendering only.
See [Omarchy-iPhone6s](https://github.com/modpunk/Omarchy-iPhone6s) for how to boot it.

## Packages the phone image must add

Beyond what Omarchy/quickshell already installs:

- `wtype` — the on-screen keyboard's fallback typing path (already required
  before this; still needed for Enter and for apps with no focused
  text-input).
- Build-time only, wherever `shell/bin/ophone-im` gets compiled (see
  [docs/shell/DESIGN.md](docs/shell/DESIGN.md#on-screen-keyboard)): a C
  compiler, the `wayland` package (`wayland-scanner` + client headers), and
  `pkgconf`. `make -C shell/im` produces the binary; nothing new is needed at
  runtime (it links only `libwayland-client`, already a quickshell
  dependency).

squeekboard and wvkbd were considered and not used — see DESIGN.md for why.

## License and credits

The logo is derived from the [Omarchy](https://omarchy.org) logo, which is MIT licensed,
© David Heinemeier Hansson ([`brand/LICENSE-omarchy.txt`](brand/LICENSE-omarchy.txt)); the motto
font is Cinzel (SIL OFL 1.1). Omarchy Phone is a community project and is not affiliated with or
endorsed by Omarchy, DHH or 37signals.
