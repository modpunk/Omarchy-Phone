#!/usr/bin/env bash
# Omarchy Phone shell preview: an isolated nested Hyprland on a desktop.
#
#   shell/preview/run.sh [scenario ...]   run scenarios, save screenshots, exit
#   shell/preview/run.sh --hold            start the session and wait (Ctrl-C to stop)
#
# Scenarios: home notification shade app keyboard switcher osd power lock pin call lockcall all
#
# Isolation: private XDG_RUNTIME_DIR (own Hyprland/Wayland/quickshell sockets),
# private D-Bus session (the preview's notification daemon never touches the
# host's), private XDG config/cache/data homes, host window output disabled
# (a 750x1334 headless output is used instead), OPHONE_DRY_RUN=1 so quick
# settings print instead of touching the host's Wi-Fi/Bluetooth/brightness.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHELL_DIR="$(dirname "$HERE")"
REPO="$(dirname "$SHELL_DIR")"
OUT="${OPHONE_SCREENSHOTS:-$REPO/docs/shell/screenshots}"
BASE="${OPHONE_PREVIEW_DIR:-/tmp/oph-$UID}"   # short: unix socket paths max out at 108 bytes

if [[ -z "${OPHONE_IN_PRIVATE_BUS:-}" ]]; then
  # Parent Wayland socket, as an absolute path so it survives the runtime-dir swap.
  host_rt="${XDG_RUNTIME_DIR:-/run/user/$UID}"
  host_wl="${WAYLAND_DISPLAY:-wayland-0}"
  [[ "$host_wl" == /* ]] || host_wl="$host_rt/$host_wl"
  [[ -S "$host_wl" ]] || { echo "no host Wayland socket at $host_wl" >&2; exit 1; }
  rm -rf "$BASE"; mkdir -p "$BASE"/{rt,config,cache,data,state}; chmod 700 "$BASE/rt"
  exec env -i \
    HOME="$HOME" USER="${USER:-$(id -un)}" PATH="$SHELL_DIR/bin:$PATH" LANG="${LANG:-C.UTF-8}" \
    TERM="${TERM:-dumb}" \
    OPHONE_IN_PRIVATE_BUS=1 OPHONE_HOST_WAYLAND="$host_wl" \
    XDG_RUNTIME_DIR="$BASE/rt" XDG_CONFIG_HOME="$BASE/config" XDG_CACHE_HOME="$BASE/cache" \
    XDG_DATA_HOME="$BASE/data" XDG_STATE_HOME="$BASE/state" XDG_DATA_DIRS="/usr/local/share:/usr/share" \
    OPHONE_PREVIEW_MODE="${OPHONE_PREVIEW_MODE:-}" OPHONE_PREVIEW_SCALE="${OPHONE_PREVIEW_SCALE:-}" \
    OPHONE_SCREENSHOTS="$OUT" OPHONE_PREVIEW_DIR="$BASE" \
    dbus-run-session -- "$0" "$@"
fi

[[ -n "$OPHONE_PREVIEW_MODE" ]] || unset OPHONE_PREVIEW_MODE
[[ -n "$OPHONE_PREVIEW_SCALE" ]] || unset OPHONE_PREVIEW_SCALE
ulimit -c 0   # a crash in the preview must not land in the host's coredump list
LOG="$BASE/log"; mkdir -p "$LOG" "$OUT"
PIDS=()
cleanup() {
  for ((i=${#PIDS[@]}-1; i>=0; i--)); do kill "${PIDS[i]}" 2>/dev/null || true; done
  sleep 0.5
  for p in "${PIDS[@]}"; do kill -9 "$p" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

export OPHONE_SHELL="$SHELL_DIR" OPHONE_DEVICE=preview OPHONE_DRY_RUN=1
export QT_QUICK_BACKEND=software QT_QPA_PLATFORM=wayland
export HYPRLAND_NO_SD_NOTIFY=1 HYPRLAND_NO_SD_VARS=1 HYPRLAND_NO_CRASHREPORTER=1

WAYLAND_DISPLAY="$OPHONE_HOST_WAYLAND" Hyprland --config "$SHELL_DIR/hypr/hyprland.lua" >"$LOG/hyprland.out" 2>&1 &
PIDS+=($!)

for _ in $(seq 100); do
  sig="$(ls "$XDG_RUNTIME_DIR/hypr" 2>/dev/null | head -1 || true)"
  [[ -n "$sig" && -S "$XDG_RUNTIME_DIR/hypr/$sig/.socket.sock" ]] && break
  sleep 0.1
done
[[ -n "$sig" ]] || { echo "nested Hyprland did not start; see $LOG/hyprland.out" >&2; exit 1; }
export HYPRLAND_INSTANCE_SIGNATURE="$sig"
wl="$(cd "$XDG_RUNTIME_DIR" && ls wayland-* | grep -v '\.lock$' | head -1)"
export WAYLAND_DISPLAY="$wl"

hyprctl output create headless >/dev/null
for _ in $(seq 50); do hyprctl monitors | grep -q HEADLESS-1 && break; sleep 0.1; done
if hyprctl configerrors | grep -q .; then echo "== Hyprland config errors:"; hyprctl configerrors; fi

qs -p "$SHELL_DIR/qs" >"$LOG/qs.out" 2>&1 &
PIDS+=($!)
QS_PID=$!
# Attach from another terminal:  source $BASE/env   (then hyprctl, grim, notify-send, qs ipc ...)
cat >"$BASE/env" <<ENV
export XDG_RUNTIME_DIR='$XDG_RUNTIME_DIR' WAYLAND_DISPLAY='$WAYLAND_DISPLAY'
export HYPRLAND_INSTANCE_SIGNATURE='$HYPRLAND_INSTANCE_SIGNATURE' DBUS_SESSION_BUS_ADDRESS='$DBUS_SESSION_BUS_ADDRESS'
export OPHONE_SHELL='$SHELL_DIR' OPHONE_DRY_RUN=1
ENV
ctl() { qs -p "$SHELL_DIR/qs" ipc call shell "$@" >/dev/null 2>&1; }
for _ in $(seq 100); do ctl ping && break; sleep 0.2; done
ctl ping || { echo "shell did not come up; see $LOG/qs.out" >&2; tail -30 "$LOG/qs.out" >&2; exit 1; }

shot() { sleep "${2:-1.2}"; grim -o HEADLESS-1 "$OUT/$1.png"; echo "saved $OUT/$1.png"; }
reset() { ctl reset; sleep 0.4; }
term() { launch foot -D /tmp "$@" bash --noprofile --norc -c 'printf "\033[1mOmarchy Phone\033[0m  Vox Libertatis\n\n"; exec bash --noprofile --norc'; }
launch() { "$@" >>"$LOG/apps.out" 2>&1 & PIDS+=($!); }
notify() { notify-send "$@" >>"$LOG/apps.out" 2>&1 || true; }
seed_notifications() {
  notify -a "Messages" -i mail-message-new "Ada" "Are we still on for 6? I'll bring the charger."
  notify -a "Calendar" -i x-office-calendar "Standup in 10 minutes" "Room 2 / Jitsi"
  notify -a "Updates" -i system-software-update "3 updates ready" "Tap to review Arch updates"
}

incoming_call() {   # what the phone app sends (docs/shell/INTEGRATION.md)
  gdbus call --session --dest org.freedesktop.Notifications --object-path /org/freedesktop/Notifications \
    --method org.freedesktop.Notifications.Notify "Phone" 0 "call-start" "Ada Lovelace" "+1 555 0100 · Wi-Fi call" \
    "['accept','Accept','decline','Decline']" "{'category': <'call.incoming'>, 'urgency': <byte 2>, 'resident': <true>}" 0 \
    >>"$LOG/apps.out" 2>&1
}
scenario() {
  case "$1" in
    home)         reset; shot 01-home ;;
    notification) reset; notify -a "Messages" -i mail-message-new "Ada" "Running 5 minutes late"; shot 02-notification-banner 0.8 ;;
    shade)        reset; seed_notifications; sleep 0.5; ctl shade; shot 03-shade ;;
    app)          reset; term; sleep 2; shot 04-app 1 ;;
    keyboard)     reset; term; sleep 2; ctl keyboard; shot 05-keyboard ;;
    switcher)     reset; term; sleep 1.5; term --title "Notes"; sleep 1.5; ctl switcher; shot 06-switcher 1.5 ;;
    lock)         reset; seed_notifications; ctl lock; shot 07-lock 1.5 ;;
    pin)          ctl lock; sleep 0.5; ctl pin; shot 08-lock-pin ;;
    call)         reset; incoming_call; shot 09-incoming-call ;;
    lockcall)     reset; ctl lock; sleep 0.5; incoming_call; shot 12-incoming-call-locked ;;
    osd)          reset; ctl volumeUp; shot 10-volume-osd 0.5 ;;
    power)        reset; ctl powerMenu; shot 11-power-menu ;;
    all)          for s in home notification shade app keyboard switcher osd power lock pin call lockcall; do scenario "$s"; done ;;
    *) echo "unknown scenario: $1" >&2; return 1 ;;
  esac
}

if [[ "${1:-}" == "--hold" ]]; then
  echo "preview running; attach with: source $BASE/env"
  echo "drive it with: qs -p $SHELL_DIR/qs ipc call shell <fn>   (Ctrl-C to stop)"
  wait "$QS_PID"
  exit 0
fi
for s in "${@:-all}"; do scenario "$s"; done
grep -E 'ERROR|WARN|error' "$LOG/qs.out" | grep -v -E 'QDBus|Could not register app ID' | head -20 || true
