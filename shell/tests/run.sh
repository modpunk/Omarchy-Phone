#!/usr/bin/env bash
# All shell/ unit tests, on a private D-Bus session bus so the Bluetooth
# agent test's mock org.bluez and fake notification daemon never touch the
# real desktop (same isolation as apps/phone/scripts/test.sh and
# shell/preview/run.sh). test_pin.py doesn't need D-Bus, but running
# everything under dbus-run-session is harmless and keeps one entry point.
#
#   shell/tests/run.sh              every test
#   shell/tests/run.sh test_pin     just one module
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
if [[ $# -gt 0 ]]; then
  exec dbus-run-session -- python3 -W ignore -m unittest "$@" -v
else
  exec dbus-run-session -- python3 -W ignore -m unittest discover -s . -t . -v
fi
