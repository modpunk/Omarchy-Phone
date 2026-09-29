-- iPhone 6s (HoolockLinux): 750x1334 panel, scale 2 -> 375x667 logical.
-- Keys come from the SoC's gpio-keys as KEY_HOMEPAGE, KEY_POWER,
-- KEY_VOLUMEUP, KEY_VOLUMEDOWN, KEY_MUTE (ring/silent switch). xkb maps
-- these to the keysyms below.
return {
  monitors = {
    { output = "", mode = "750x1334@60", position = "0x0", scale = 2, transform = 0 },
  },
  touchdevice = { transform = 0 }, -- touch follows the panel; set output = "<name>" if the panel isn't the only output
  keys = {
    home = "XF86HomePage",
    power = "XF86PowerOff",
    volume_up = "XF86AudioRaiseVolume",
    volume_down = "XF86AudioLowerVolume",
    mute = "XF86AudioMute",
  },
  kb_layout = "us",
  terminal = "foot",
}
