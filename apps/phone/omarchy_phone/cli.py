"""phonectl: command-line control of the Omarchy Phone daemon.

  phonectl dial +1 212 555 0101 [--video]      phonectl state
  phonectl answer|hangup|decline [CALL]        phonectl history [--missed]
  phonectl import contacts.vcf                 phonectl export [out.vcf]
  phonectl block|allow|spam NUMBER [ACTION]    phonectl unblock NUMBER
  phonectl dnd [on|off]                        phonectl set KEY JSON
  phonectl detect [TEXT]   (reads stdin without TEXT; works without the daemon)
  phonectl simulate NUMBER [NAME]              (loopback: fake an incoming call)
  phonectl call METHOD '{"json": "args"}'      (any D-Bus method, see docs/phone/API.md)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import numbers


def _print(x):
    if isinstance(x, str):
        print(x)
    elif x is not None:
        print(json.dumps(x, indent=2, ensure_ascii=False))


def _only_call(c, call_id):
    if call_id:
        return call_id
    calls = c.call("state")["calls"]
    if not calls:
        sys.exit("no active call")
    return calls[0]["id"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="phonectl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=os.environ.get("OMARCHY_PHONE_PROFILE", "default"))
    ap.add_argument("--region", default="US", help="default region for detect without the daemon")
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--video", action="store_true")
    ap.add_argument("--missed", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "detect":
        text = " ".join(a.args) if a.args else sys.stdin.read()
        for m in numbers.find_numbers(text, a.region):
            print(f"{m.uri}\t{m.raw}")
        return

    from .client import Client, DaemonError

    c = Client(a.profile)
    try:
        if a.cmd == "dial":
            _print(c.call("dial", address=" ".join(a.args), video=a.video))
        elif a.cmd == "answer":
            c.call("answer", call_id=_only_call(c, a.args[0] if a.args else None), video=a.video)
        elif a.cmd == "decline":
            c.call("decline", call_id=_only_call(c, a.args[0] if a.args else None))
        elif a.cmd == "hangup":
            c.call("hangup", call_id=a.args[0] if a.args else None)
        elif a.cmd == "state":
            _print(c.call("state"))
        elif a.cmd == "history":
            for h in c.call("history", missed=a.missed):
                arrow = "<-" if h["direction"] == "in" else "->"
                print(f"{arrow} {h['status']:<10} {h['name'] or h['remote']:<28} {h['reason'] or ''}")
        elif a.cmd == "import":
            _print(c.call("import_vcard", path=os.path.abspath(a.args[0])))
        elif a.cmd == "export":
            _print(c.call("export_vcard", path=os.path.abspath(a.args[0]) if a.args else None))
        elif a.cmd in ("block", "allow", "spam"):
            _print(c.call("list_add", kind=a.cmd, pattern=a.args[0], action=a.args[1] if len(a.args) > 1 else None))
        elif a.cmd == "unblock":
            for kind in ("block", "spam"):
                c.call("list_remove", kind=kind, pattern=numbers.normalize(a.args[0]) or a.args[0])
        elif a.cmd == "dnd":
            on = None if not a.args else a.args[0] in ("on", "1", "true")
            print("do not disturb:", "on" if c.call("dnd", on=on) else "off")
        elif a.cmd == "set":
            c.call("set", key=a.args[0], value=json.loads(a.args[1]))
        elif a.cmd == "simulate":
            _print(c.call("simulate_incoming", remote=a.args[0], display=" ".join(a.args[1:]), video=a.video))
        elif a.cmd == "call":
            _print(c.call(a.args[0], **(json.loads(a.args[1]) if len(a.args) > 1 else {})))
        else:
            sys.exit(f"unknown command {a.cmd!r}; see phonectl --help")
    except DaemonError as e:
        sys.exit(f"phonectl: {e}")


if __name__ == "__main__":
    main()
