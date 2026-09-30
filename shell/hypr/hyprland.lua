-- Omarchy Phone: Hyprland config for phones and other small screens.
-- Hyprland 0.56 Lua config. Start with:  Hyprland --config <this file>
--
-- Environment:
--   OPHONE_SHELL   path to the shell/ directory (default: next to this file)
--   OPHONE_DEVICE  device profile in hypr/devices/ (default: generic)

local function dirname(p) return (p:gsub("/[^/]*$", "")) end

local here = nil
if debug and debug.getinfo then
  local src = debug.getinfo(1, "S").source
  if src:sub(1, 1) == "@" then here = dirname(src:sub(2)) end
end
local shell = os.getenv("OPHONE_SHELL") or (here and dirname(here)) or "/usr/share/omarchy-phone/shell"
local device_name = os.getenv("OPHONE_DEVICE") or "generic"

local device = dofile(shell .. "/hypr/devices/" .. device_name .. ".lua")

---------------------------------------------------------------- environment
-- Phones here have no usable GPU: keep Qt on the software scene graph.
hl.env("QT_QUICK_BACKEND", "software")
hl.env("QT_QPA_PLATFORM", "wayland")
hl.env("GDK_BACKEND", "wayland")
hl.env("MOZ_ENABLE_WAYLAND", "1")
hl.env("OPHONE_SHELL", shell)
hl.env("OPHONE_DEVICE", device_name)
hl.env("XCURSOR_SIZE", "24")

------------------------------------------------------------------ monitors
for _, m in ipairs(device.monitors) do hl.monitor(m) end

------------------------------------------------------------ look and feel
hl.config({
  general = {
    gaps_in = 0,
    gaps_out = 0,
    border_size = 0,
    layout = "scrolling",
    resize_on_border = false,
    allow_tearing = false,
  },
  decoration = {
    rounding = 0,
    active_opacity = 1.0,
    inactive_opacity = 1.0,
    shadow = { enabled = false },
    blur = { enabled = false },
  },
  -- One full-width column per app. Swiping the nav bar moves focus between
  -- columns, and the layout slides the next app into view.
  scrolling = {
    column_width = 1.0,
    fullscreen_on_one_column = true,
    follow_focus = true,
  },
  animations = { enabled = true },
  misc = {
    disable_hyprland_logo = true,
    disable_splash_rendering = true,
    force_default_wallpaper = 0,
    background_color = "rgb(101315)",
    focus_on_activate = true,
    key_press_enables_dpms = false, -- only the power key wakes the screen
    mouse_move_enables_dpms = false,
    disable_watchdog_warning = true,
    allow_session_lock_restore = true,
  },
  cursor = { hide_on_touch = true, inactive_timeout = 1 },
  input = {
    kb_layout = device.kb_layout or "us",
    touchdevice = device.touchdevice or {},
  },
  gestures = { workspace_swipe_touch = false },
})

-- Cheap animations only: slides and fades, no pop-in scaling.
hl.curve("phone", { type = "bezier", points = { { 0.2, 0.9 }, { 0.3, 1 } } })
hl.animation({ leaf = "global", enabled = true, speed = 3, bezier = "phone" })
hl.animation({ leaf = "windows", enabled = true, speed = 3, bezier = "phone", style = "slide" })
hl.animation({ leaf = "layers", enabled = true, speed = 2.5, bezier = "phone", style = "fade" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 2.5, bezier = "phone", style = "fade" })
hl.animation({ leaf = "border", enabled = false })
hl.animation({ leaf = "fadeDim", enabled = false })

----------------------------------------------------- workspaces and windows
-- 1 = home (kept empty so the home-screen layer shows), 2 = apps.
hl.window_rule({ name = "apps-go-to-app-workspace", match = { class = ".*" }, workspace = "2" })
hl.window_rule({ name = "no-maximize-requests", match = { class = ".*" }, suppress_event = "maximize" })
-- Dialogs float, centered, never larger than the phone.
hl.window_rule({
  name = "dialogs-fit",
  match = { float = true },
  center = true,
  size = { "monitor_w*0.94", "monitor_h*0.8" },
})

hl.layer_rule({ name = "shell-no-anim-edges", match = { namespace = "^ophone-(edge|keyboard)$" }, no_anim = true })

------------------------------------------------------------ hardware keys
-- Keys dispatch Quickshell GlobalShortcuts (appid "ophone"). The shell gets
-- press and release, so it measures long presses itself, with no process
-- spawned per key. locked = true keeps them working on the lock screen.
local keys = device.keys or {}
local function key(sym, name, opts)
  if sym then hl.bind(sym, hl.dsp.global("ophone:" .. name), opts or { locked = true }) end
end
key(keys.home or "XF86HomePage", "home")
key(keys.power or "XF86PowerOff", "power")
key(keys.volume_up or "XF86AudioRaiseVolume", "volume-up", { locked = true, repeating = true })
key(keys.volume_down or "XF86AudioLowerVolume", "volume-down", { locked = true, repeating = true })
key(keys.mute or "XF86AudioMute", "mute")

-- Keyboard (a Bluetooth keyboard on a phone without working touch, or a desk
-- keyboard). Media keys on the keyboard hit the hardware-key binds above.
-- Inside shell surfaces the shell handles plain keys itself (arrows, Tab,
-- Enter, Esc, PageUp/PageDown, typing); see docs/shell/DESIGN.md "Keyboard".
local L = { locked = true }
local LR = { locked = true, repeating = true }
hl.bind("SUPER + H", hl.dsp.global("ophone:home"))
hl.bind("SUPER + TAB", hl.dsp.global("ophone:switcher"))
hl.bind("SUPER + N", hl.dsp.global("ophone:shade"))
hl.bind("SUPER + L", hl.dsp.global("ophone:lock"))
hl.bind("SUPER + K", hl.dsp.global("ophone:keyboard"))
hl.bind("SUPER + ESCAPE", hl.dsp.global("ophone:power"), L)          -- the power key: tap = lock + screen off / wake, hold = menu
hl.bind("SUPER + SHIFT + ESCAPE", hl.dsp.global("ophone:power-menu"), L)
hl.bind("SUPER + UP", hl.dsp.global("ophone:volume-up"), LR)
hl.bind("SUPER + DOWN", hl.dsp.global("ophone:volume-down"), LR)    -- also silences a ringing call
hl.bind("SUPER + M", hl.dsp.global("ophone:mute"), L)
hl.bind("SUPER + LEFT", hl.dsp.focus({ direction = "l" }))
hl.bind("SUPER + RIGHT", hl.dsp.focus({ direction = "r" }))
hl.bind("SUPER + RETURN", hl.dsp.exec_cmd(device.terminal or "foot"))
hl.bind("SUPER + W", hl.dsp.window.close())

------------------------------------------------------------------ startup
hl.on("hyprland.start", function()
  if device.autostart_shell ~= false then hl.exec_cmd("qs -p " .. shell .. "/qs") end
  if device.on_start then device.on_start(hl, shell) end
end)
