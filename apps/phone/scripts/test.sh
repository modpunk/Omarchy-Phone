#!/bin/sh
# All tests, inside the sandbox (private session bus, temp dirs) so nothing reaches the desktop.
here=$(cd "$(dirname "$0")/.." && pwd)
exec "$here/scripts/sandbox.sh" python3 -W ignore -m unittest discover -s tests -t . "$@"
