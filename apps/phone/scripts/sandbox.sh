#!/bin/sh
# Run a command inside a throwaway Omarchy Phone sandbox: private D-Bus session, temp data
# and runtime dirs, no notifications or ringtone, no audio route switching. Nothing touches
# ~/.config, ~/.local/share or the real session bus.
#   scripts/sandbox.sh sh -c 'bin/phoned & sleep 1; bin/phonectl state'
set -e
here=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d /tmp/omarchy-phone-sandbox.XXXXXX)
mkdir -p "$tmp/run" "$tmp/data"
chmod 700 "$tmp/run"
cleanup() {
    # portals may have mounted FUSE filesystems in the runtime dir
    for m in "$tmp/run/doc" "$tmp/run/gvfs"; do
        mountpoint -q "$m" 2>/dev/null && { fusermount3 -u "$m" 2>/dev/null || fusermount -u "$m" 2>/dev/null; }
    done
    rm -rf "$tmp"
}
trap cleanup EXIT
cd "$here"
env XDG_RUNTIME_DIR="$tmp/run" XDG_DATA_HOME="$tmp/data" \
    OMARCHY_PHONE_QUIET=1 OMARCHY_PHONE_NO_NOTIFY=1 OMARCHY_PHONE_AUDIO_DRYRUN=1 \
    OMARCHY_PHONE_SANDBOX="$tmp" \
    ADW_DISABLE_PORTAL=1 GDK_DEBUG=no-portals GIO_USE_VFS=local GTK_A11Y=none \
    dbus-run-session -- "$@"
