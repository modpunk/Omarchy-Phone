#!/usr/bin/env bash
# Fails the build on tracked files that look like firmware, private keys or
# other binaries that have no business living in this source repo, and on
# any tracked file over a generous size limit.
set -euo pipefail

MAX_BYTES=$((2 * 1024 * 1024))  # 2 MiB; the largest tracked file today is ~130 KiB
BAD_EXT_RE='\.(ipsw|dfu|img|img3|img4|im4p|im4m|bin|elf|dylib|so|a|o|apk|ipa|dmg|pem|key|p12|pfx|jks|keystore|der)$'
BAD_NAME_RE='(^|/)(id_rsa|id_ed25519|id_ecdsa)(\.[a-zA-Z0-9]+)?$|(^|/)\.env(\..+)?$'

status=0
while IFS= read -r -d '' f; do
  size=$(git cat-file -s "$(git rev-parse "HEAD:$f")" 2>/dev/null || wc -c <"$f")
  if [[ "$f" =~ $BAD_EXT_RE ]]; then
    echo "FAIL: $f: looks like firmware/binary/key material (blocked extension)"
    status=1
  fi
  if [[ "$f" =~ $BAD_NAME_RE ]]; then
    echo "FAIL: $f: looks like a private key or env file"
    status=1
  fi
  if (( size > MAX_BYTES )); then
    echo "FAIL: $f: $size bytes exceeds the $MAX_BYTES byte limit for this repo"
    status=1
  fi
done < <(git ls-files -z)

if (( status == 0 )); then
  echo "ok: no firmware/key/oversized files found"
fi
exit $status
