#!/bin/sh
# Asterisk on 127.0.0.1:5060, baresip "alice" (ext 1001, ctrl_tcp :4444) and "bob" (ext 1002,
# ctrl_tcp :4445). The container stops when any of the three exits.
asterisk -f -q &
for i in $(seq 50); do asterisk -rx "core waitfullybooted" >/dev/null 2>&1 && break; sleep 0.2; done
baresip -f /sipbed/alice &
baresip -f /sipbed/bob &
wait -n
