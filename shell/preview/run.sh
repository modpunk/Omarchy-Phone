#!/usr/bin/env bash
# Omarchy Phone shell preview: an isolated nested Hyprland on a desktop.
#
#   shell/preview/run.sh [scenario ...]   run scenarios, save screenshots, exit
#   shell/preview/run.sh --hold            start the session and wait (Ctrl-C to stop)
#
# Scenarios: home notification shade app keyboard switcher osd power settings lock pin call lockcall all
# Keyboard scenarios (typed with wtype into the preview): kbhome kbdock kbsearch
#   kbshade kbnotif kbswitcher kbpower kbpin kbcall, or "keys" for all of them
# On-screen-keyboard focus scenarios: oskgtk (GTK4 field: auto-show, type
#   through the input method, manual hide, refocus) and oskfoot (a terminal
#   never auto-shows it; the manual toggle still does). Both assert, not just
#   screenshot; failures print "FAIL ...".
# Content-purpose layout scenarios (a GTK4 field with a given input-purpose):
#   osknum (digits -> numeric keypad), oskphone (phone -> dial pad), oskpass
#   (password -> masked QWERTY), oskemail/oskurl (-> QWERTY + convenience
#   key), or "oskcontent" for all five. Each asserts Phone.keyboardLayout,
#   not just the screenshot.
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
  # Test-only: seed a theme into the private XDG_STATE_HOME *before* Hyprland/qs
  # start, so Theme.qml's initial load sees it -- unlike writing to "$BASE/state"
  # after the fact, which races the shell's own startup (docs/shell/DESIGN.md
  # "Theme" -- verifying the live-reload fix needs a theme present at boot,
  # then swapped, to reproduce the actual bug scenario).
  if [[ -n "${OPHONE_SEED_THEME_DIR:-}" ]]; then
    mkdir -p "$BASE/state/omarchy/current"
    cp -r "$OPHONE_SEED_THEME_DIR" "$BASE/state/omarchy/current/theme"
    echo "${OPHONE_SEED_THEME_NAME:-seed}" >"$BASE/state/omarchy/current/theme.name"
  fi
  exec env -i \
    HOME="$HOME" USER="${USER:-$(id -un)}" PATH="$SHELL_DIR/bin:$PATH" LANG="${LANG:-C.UTF-8}" \
    TERM="${TERM:-dumb}" \
    OPHONE_IN_PRIVATE_BUS=1 OPHONE_HOST_WAYLAND="$host_wl" \
    XDG_RUNTIME_DIR="$BASE/rt" XDG_CONFIG_HOME="$BASE/config" XDG_CACHE_HOME="$BASE/cache" \
    XDG_DATA_HOME="$BASE/data" XDG_STATE_HOME="$BASE/state" XDG_DATA_DIRS="/usr/local/share:/usr/share" \
    OPHONE_PREVIEW_MODE="${OPHONE_PREVIEW_MODE:-}" OPHONE_PREVIEW_SCALE="${OPHONE_PREVIEW_SCALE:-}" \
    OPHONE_SCREENSHOTS="$OUT" OPHONE_PREVIEW_DIR="$BASE" \
    OPHONE_IDLE_SECONDS="${OPHONE_IDLE_SECONDS:-}" OPHONE_PIN_FILE="${OPHONE_PIN_FILE:-}" \
    OPHONE_PAM_DIR="${OPHONE_PAM_DIR:-}" OPHONE_PAM_SERVICE="${OPHONE_PAM_SERVICE:-}" \
    QT_LOGGING_RULES="${QT_LOGGING_RULES:-}" \
    dbus-run-session -- "$0" "$@"
fi

[[ -n "$OPHONE_PREVIEW_MODE" ]] || unset OPHONE_PREVIEW_MODE
[[ -n "$OPHONE_PREVIEW_SCALE" ]] || unset OPHONE_PREVIEW_SCALE
# Test-only overrides (docs/shell/DESIGN.md "Idle auto-lock" / "Lock screen
# PIN"): unset rather than leave as empty strings, so Phone.qml/LockScreen.qml
# see "not set" (Quickshell.env returns "" either way, but an explicit unset
# is clearer to read here and in `env` dumps).
[[ -n "$OPHONE_IDLE_SECONDS" ]] || unset OPHONE_IDLE_SECONDS
[[ -n "$OPHONE_PIN_FILE" ]] || unset OPHONE_PIN_FILE
[[ -n "$OPHONE_PAM_DIR" ]] || unset OPHONE_PAM_DIR
[[ -n "$OPHONE_PAM_SERVICE" ]] || unset OPHONE_PAM_SERVICE
[[ -n "$QT_LOGGING_RULES" ]] || unset QT_LOGGING_RULES
ulimit -c 0   # a crash in the preview must not land in the host's coredump list
LOG="$BASE/log"; mkdir -p "$LOG" "$OUT"
PIDS=()
cleanup() {
  for ((i=${#PIDS[@]}-1; i>=0; i--)); do kill "${PIDS[i]}" 2>/dev/null || true; done
  sleep 0.5
  for p in "${PIDS[@]}"; do kill -9 "$p" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

# Build the input-method-v2 helper if it's missing or stale (never touches
# anything outside the repo: object files land in shell/im/build/).
if [[ ! -x "$SHELL_DIR/bin/ophone-im" || "$SHELL_DIR/im/ophone-im.c" -nt "$SHELL_DIR/bin/ophone-im" ]]; then
  make -C "$SHELL_DIR/im" >"$LOG/build-ophone-im.out" 2>&1 || { echo "ophone-im build failed; see $LOG/build-ophone-im.out" >&2; exit 1; }
fi

export OPHONE_SHELL="$SHELL_DIR" OPHONE_DEVICE=preview OPHONE_DRY_RUN=1
export QT_QUICK_BACKEND=software QT_QPA_PLATFORM=wayland GDK_BACKEND=wayland
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
ipc() { qs -p "$SHELL_DIR/qs" ipc call shell "$@" 2>/dev/null; }
for _ in $(seq 100); do ctl ping && break; sleep 0.2; done
ctl ping || { echo "shell did not come up; see $LOG/qs.out" >&2; tail -30 "$LOG/qs.out" >&2; exit 1; }
ok=0; fail=0
assert_eq() { local desc="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then echo "OK   $desc"; ok=$((ok+1))
  else echo "FAIL $desc (expected '$expected', got '$actual')"; fail=$((fail+1)); fi
}
assert_has() { local desc="$1" needle="$2" haystack="$3"
  if grep -qF -- "$needle" <<<"$haystack"; then echo "OK   $desc"; ok=$((ok+1))
  else echo "FAIL $desc (did not find '$needle')"; fail=$((fail+1)); fi
}
# Poll instead of a fixed sleep: a freshly launched app (GTK4 + a portal, or
# a nested Hyprland already busy with several previous scenarios' windows)
# doesn't always get mapped and focused within a fixed delay.
wait_for() { local fn="$1" exp="$2" tries="${3:-25}"
  for _ in $(seq "$tries"); do [[ "$(ipc "$fn")" == "$exp" ]] && return 0; sleep 0.2; done
  return 1
}
wait_for_log() { local needle="$1" tries="${2:-15}"
  for _ in $(seq "$tries"); do grep -qF -- "$needle" "$LOG/apps.out" 2>/dev/null && return 0; sleep 0.2; done
  return 1
}

# Keys go to the preview only: wtype uses the preview's own WAYLAND_DISPLAY.
key() { wtype "$@"; sleep 0.2; }
# What a SUPER bind in hyprland.lua does (Hyprland doesn't run binds for
# virtual keyboards like wtype, so the scenarios dispatch the same global).
bind() { hyprctl dispatch "hl.dsp.global(\"ophone:$1\")" >/dev/null; sleep 0.4; }
shot() { sleep "${2:-1.2}"; grim -o HEADLESS-1 "$OUT/$1.png"; echo "saved $OUT/$1.png"; }
reset() { ctl reset; sleep 0.4; }
term() { launch foot -D /tmp "$@" bash --noprofile --norc -c 'printf "\033[1mOmarchy Phone\033[0m  Vox Libertatis\n\n"; exec bash --noprofile --norc'; }
launch() { "$@" >>"$LOG/apps.out" 2>&1 & PIDS+=($!); }
# Kill every app window launched by an earlier scenario (PIDS[0] is
# Hyprland, PIDS[1] is qs -- never touched). A crowded scrolling layout with
# several leftover terminals can leave a stale window with the compositor's
# keyboard focus, which would make the *next* scenario's focus/typing
# assertions pass or fail for the wrong reason. The oskgtk/oskfoot scenarios
# need a known, single-window focus state to mean anything.
clear_apps() {
  for ((i=${#PIDS[@]}-1; i>=2; i--)); do kill "${PIDS[i]}" 2>/dev/null || true; unset 'PIDS[i]'; done
  PIDS=("${PIDS[@]}")
  sleep 0.3
}
# A GTK4 window with a text field: the closest stand-in to the (not yet
# built) Phone app's dial/search field for exercising text-input-v3. An
# optional arg sets its input-purpose (digits, number, phone, email, url,
# password, pin, ...; see gtk4-field.py), which GTK4 forwards as the real
# text-input-v3 content_type the on-screen keyboard picks its layout from.
oskfield() { : >"$LOG/apps.out"; launch python3 "$HERE/gtk4-field.py" "${1:-normal}"; }
notify() { notify-send "$@" >>"$LOG/apps.out" 2>&1 || true; }
seed_notifications() {
  notify -a "Messages" -i mail-message-new "Ada" "Are we still on for 6? I'll bring the charger."
  notify -a "Calendar" -i x-office-calendar "Standup in 10 minutes" "Room 2 / Jitsi"
  notify -a "Updates" -i system-software-update "3 updates ready" "Tap to review Arch updates"
}

# Content-purpose-driven layout scenarios: focus a field with a given
# input-purpose and assert both that the keyboard auto-shows (the existing
# focus-driven path, untouched) and that it picked the right layout
# (Phone.keyboardLayout via the "keyboardLayout" ipc call -- the screenshot
# alone doesn't prove which layout is showing, this does).
oskcontent() {   # $1 gtk4-field.py purpose  $2 expected Phone.keyboardLayout  $3 screenshot name  $4 description
  reset; clear_apps; oskfield "$1"
  wait_for isKeyboardOpen true || true
  assert_eq "$4: field focus auto-shows the keyboard" "true" "$(ipc isKeyboardOpen)"
  wait_for keyboardLayout "$2" || true
  assert_eq "$4: keyboard picks the $2 layout" "$2" "$(ipc keyboardLayout)"
  shot "$3" 0.3
  # The field dying is a real deactivate (like oskgtk's own check), which
  # must reset the *layout* too, not just close the keyboard: this is the
  # only direct coverage of imPurpose's reset in Phone.imFocusOut and
  # ophone-im's reset-on-activate (Services/Phone.qml, ophone-im.c).
  kill "${PIDS[-1]}" 2>/dev/null || true
  wait_for isKeyboardOpen false || true
  assert_eq "$4: field dying resets the layout" "qwerty" "$(ipc keyboardLayout)"
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
    app)          reset; term; sleep 2
                  [[ "$(ipc isKeyboardOpen)" == "true" ]] && { bind keyboard; sleep 0.3; } # foot auto-shows it too; "app" illustrates the plain full-screen app
                  shot 04-app 1 ;;
    keyboard)     reset; term; sleep 2; shot 05-keyboard ;;   # auto-shown: foot speaks text-input-v3 too
    switcher)     reset; term; sleep 1.5; term --title "Notes"; sleep 1.5; ctl switcher; shot 06-switcher 1.5 ;;
    lock)         reset; seed_notifications; ctl lock; shot 07-lock 1.5 ;;
    pin)          ctl lock; sleep 0.5; ctl pin; shot 08-lock-pin ;;
    call)         reset; incoming_call; shot 09-incoming-call ;;
    lockcall)     reset; ctl lock; sleep 0.5; incoming_call; shot 12-incoming-call-locked ;;
    osd)          reset; ctl volumeUp; shot 10-volume-osd 0.5 ;;
    power)        reset; ctl powerMenu; shot 11-power-menu ;;
    settings)     reset; ctl settings; shot 31-settings ;;
    kbhome)       reset; key -k Right -k Down -k Right; shot 13-kb-home-focus 0.4 ;;
    kbdock)       reset; key -k Right -k Down -k Down -k Down -k Down -k Down -k Down -k Right; shot 14-kb-dock-focus 0.4 ;;
    kbsearch)     reset; key ma; shot 15-kb-search 0.6 ;;
    kbshade)      reset; seed_notifications; sleep 0.5; bind shade; key -k Right -k Down; shot 16-kb-shade-focus 0.4 ;;
    kbnotif)      reset; seed_notifications; sleep 0.5; bind shade; key -k Down -k Down -k Down; shot 17-kb-shade-notification 0.4 ;;
    kbswitcher)   reset; term; sleep 1.5; term --title "Notes"; sleep 1.5; bind switcher; key -k Right -k Left; shot 18-kb-switcher-focus 1.2 ;;
    kbpower)      reset; bind power-menu; key -k Down; shot 19-kb-power-focus 0.4 ;;
    kbpin)        reset; ctl lock; sleep 0.8; key 1; key 2; wtype 3; shot 20-kb-lock-pin 0 ;;
    kbcall)       reset; incoming_call; sleep 0.8; key -k Right; shot 21-kb-call-focus 0.4 ;;
    oskgtk)
      reset; clear_apps; oskfield
      wait_for isKeyboardOpen true || true
      assert_eq "GTK4 field focus auto-shows the keyboard" "true" "$(ipc isKeyboardOpen)"
      shot 22-osk-auto-show 0.3
      sleep 0.3  # give GTK's own text-input-v3 enable() a moment past our activate/done
      ipc typeText "hi"
      wait_for_log "TEXT:hi" || true
      assert_has "typed text reaches the field via the input method" "TEXT:hi" "$(cat "$LOG/apps.out")"
      key -k BackSpace   # backspace stays a real key event even with an IM bound (see Keyboard.qml)
      assert_eq "backspace (wtype) still reaches the field with an input method bound" "TEXT:h" "$(tail -1 "$LOG/apps.out")"
      bind keyboard; sleep 0.3   # manual toggle: hide it while the field is still focused
      assert_eq "manual toggle hides it even though the field is still focused" "false" "$(ipc isKeyboardOpen)"
      shot 23-osk-manual-hide 0.3
      bind keyboard; sleep 0.3   # manual toggle again: show it back
      assert_eq "manual toggle re-shows it" "true" "$(ipc isKeyboardOpen)"
      # Prove the pure protocol path too: killing the app (not "home") means
      # a real deactivate/done arrives, not just resetKeyboard() short-circuiting.
      kill "${PIDS[-1]}" 2>/dev/null || true
      wait_for isKeyboardOpen false || true
      assert_eq "the app dying (a real deactivate) closes it, and clears the manual pin" "false" "$(ipc isKeyboardOpen)"
      ctl home; sleep 0.5
      assert_eq "leaving the app (home) closes it" "false" "$(ipc isKeyboardOpen)"
      ;;
    oskfoot)
      reset; clear_apps; term
      wait_for isKeyboardOpen true || true
      # foot itself speaks text-input-v3 (for IME composition), so this is
      # the auto-show path, not the manual one -- typing must still reach
      # the terminal correctly through commit_string.
      assert_eq "foot auto-shows too (it supports text-input-v3 for IME composition)" "true" "$(ipc isKeyboardOpen)"
      ipc typeText "ls"; sleep 0.3
      shot 24-osk-foot-auto 0.3
      key -k BackSpace   # delete_surrounding_text is a no-op in foot; this is why bksp always uses wtype
      shot 25-osk-foot-backspace 0.3
      bind keyboard; sleep 0.3
      assert_eq "manual toggle still hides it" "false" "$(ipc isKeyboardOpen)"
      bind keyboard; sleep 0.3
      assert_eq "manual toggle still shows it back" "true" "$(ipc isKeyboardOpen)"
      ;;
    keys)         for s in kbhome kbdock kbsearch kbshade kbnotif kbswitcher kbpower kbpin kbcall; do scenario "$s"; done ;;
    osknum)       oskcontent digits numeric 26-osk-numeric "digits purpose" ;;
    oskphone)     oskcontent phone phone 27-osk-phone "phone purpose" ;;
    oskpass)      oskcontent password password 28-osk-password "password purpose" ;;
    oskemail)     oskcontent email email 29-osk-email "email purpose" ;;
    oskurl)       oskcontent url url 30-osk-url "url purpose" ;;
    oskcontent)   for s in osknum oskphone oskpass oskemail oskurl; do scenario "$s"; done ;;
    all)          for s in home notification shade app keyboard switcher osd power settings lock pin call lockcall keys oskgtk oskfoot oskcontent; do scenario "$s"; done ;;
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
if (( ok + fail > 0 )); then
  echo "assertions: $ok ok, $fail failed"
  (( fail == 0 )) || exit 1
fi
