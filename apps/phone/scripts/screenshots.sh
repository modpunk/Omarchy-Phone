#!/bin/sh
# Render the UI headlessly (gtk4-broadwayd + cairo renderer) at 375x667 into docs/phone/screenshots.
# Uses the sandbox: two loopback phones, sample contacts, a few calls. No real services.
set -e
here=$(cd "$(dirname "$0")/.." && pwd)
out=${1:-$here/../../docs/phone/screenshots}
mkdir -p "$out"
exec "$here/scripts/sandbox.sh" sh -c '
set -e
out="$1"
d=$(( $$ % 300 + 100 ))
export GSK_RENDERER=cairo GDK_BACKEND=broadway BROADWAY_DISPLAY=:$d OMARCHY_PHONE_NO_UI_LAUNCH=1
gtk4-broadwayd :$d >/dev/null 2>&1 & BW=$!
trap "kill \$BW \$A \$B 2>/dev/null" EXIT
bin/phoned --number "+1 212 555 0101" --display Alice & A=$!
bin/phoned --profile bob --number "+1 646 555 0102" --display Bob & B=$!
for i in $(seq 50); do [ -S "$XDG_RUNTIME_DIR/broadway$((d + 1)).socket" ] && break; sleep 0.1; done
sleep 1.5
bin/phonectl import tests/data/sample.vcf >/dev/null
bin/phonectl dial loop:echo >/dev/null; sleep 1.2; bin/phonectl hangup
bin/phonectl --profile bob dial "+1 212 555 0101" >/dev/null; sleep 0.4; bin/phonectl --profile bob hangup; sleep 0.2
bin/phonectl block "+1 305 555 0166" >/dev/null
bin/phonectl simulate "+1 305 555 0166" >/dev/null; sleep 0.2
bin/phonectl simulate "+1 900 555 0123" "Prize Dept" >/dev/null; sleep 0.2
shot() { name=$1; shift; bin/omarchy-phone --screenshot "$out/$name.png" "$@"; }
shot keypad --page keypad "tel:+16465550102"
shot recents --page recents
shot contacts --page contacts
shot favorites --page favorites
bin/phonectl simulate "+1 312 555 0142" "Unknown Caller" >/dev/null; sleep 0.3
shot incoming
bin/phonectl state | grep -c "\"incoming\"" || true
bin/phonectl answer; bin/phonectl dial loop:bob >/dev/null; sleep 0.4
bin/phonectl --profile bob answer; sleep 0.3
shot incall
bin/phonectl call merge "{}" >/dev/null; sleep 0.3
shot groupcall
bin/phonectl hangup >/dev/null 2>&1; bin/phonectl --profile bob hangup >/dev/null 2>&1; sleep 0.2
shot sipaccount --page sip_account
bin/phonectl call save_sip_account "{\"account\": {\"display_name\": \"Jane Doe\", \"username\": \"jane\", \"domain\": \"pbx.example.org\", \"proxy\": \"proxy.example.org\", \"transport\": \"tcp\"}, \"password\": \"hunter2\"}" >/dev/null
sleep 0.2
shot sipaccount-filled --page sip_account
' sh "$out"
