-- Preview on a desktop: nested Hyprland whose own window output is disabled.
-- shell/preview/run.sh adds a 750x1334 headless output (HEADLESS-1) at scale 2,
-- so the shell sees an iPhone-6s-sized screen and nothing shows on the host.
-- Override the size with OPHONE_PREVIEW_MODE / OPHONE_PREVIEW_SCALE.
local mode = os.getenv("OPHONE_PREVIEW_MODE") or "750x1334@60"
local scale = tonumber(os.getenv("OPHONE_PREVIEW_SCALE") or "2")
return {
  monitors = {
    { output = "WAYLAND-1", disabled = true },
    { output = "HEADLESS-1", mode = mode, position = "0x0", scale = scale },
  },
  keys = {},
  kb_layout = "us",
  terminal = "foot",
  autostart_shell = false, -- run.sh starts the shell so it can capture logs
}
