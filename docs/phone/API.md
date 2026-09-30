# phoned D-Bus API

| | |
|---|---|
| Bus name | `org.omarchy.Phone.Daemon` (extra local instances: `org.omarchy.Phone.Daemon.<profile>`) |
| Object | `/org/omarchy/Phone` |
| Interface | `org.omarchy.Phone1` |
| Method | `Call(s method, s json_args) → s json` |
| Signal | `Event(s json)` |

`Call` returns `{"ok": true, "result": …}` or `{"ok": false, "error": "…", "kind": "…"}`. Arguments are a
JSON object of keyword arguments. From a shell:

```sh
gdbus call --session --dest org.omarchy.Phone.Daemon --object-path /org/omarchy/Phone \
  --method org.omarchy.Phone1.Call dial '{"address": "+1 212 555 0101"}'
# or
phonectl call dial '{"address": "+1 212 555 0101", "video": true}'
```

## Methods

**Calls**

| Method | Arguments | Result |
|---|---|---|
| `state` | | `{calls, speaker, dnd, registration, backends, profile, own_number}`; `registration` is `{backend_id: {state, ok, detail, reason}}` (see "Registration" below) |
| `dial` | `address`, `video=false` | call object |
| `answer` | `call_id`, `video=false` | |
| `decline` | `call_id`, `voicemail=false` | |
| `hangup` | `call_id=null` (all calls) | |
| `hold` | `call_id`, `on=true` | |
| `mute` | `on=true`, `call_id=null` (all calls) | |
| `video` | `call_id`, `on=true` | voice→video and back |
| `dtmf` | `call_id`, `digits` | |
| `merge` | `call_ids=null` (all connected) | conference id |
| `split` | `call_id` | take one leg out of a group call |
| `speaker` | `on=true` | selected route or null |
| `routes` | | PipeWire sinks `[{id, name, label, kind, default}]`, kind ∈ earpiece/speaker/headset/bluetooth |
| `route` | `id` | |
| `simulate_incoming` | `remote`, `display=""`, `video=false` | loopback only: fake an incoming call |
| `directory` | | loopback peers |
| `show` | `page`, `number=""` | asks the UI to show a tab or prefill the keypad |

A call object: `{id, remote, name, display, direction, backend, state, video, muted, held, silent,
screening: {action, reason, rule}, started, answered, conference, participants, contact_id}`.
States: `dialing`, `ringing`, `incoming`, `active`, `held`, `remote_held`.

**Contacts**: `contacts(query="", group=null)`, `favorites()`, `groups()`, `contact(id)`,
`lookup(address)`, `save_contact(contact)` → id, `delete_contact(id)`, `favorite(id, on)`,
`set_groups(id, groups)`, `import_vcard(text|path)` → `{added, updated}`,
`export_vcard(path=null, ids=null, version="3.0")` → text or `{path, count}`.

**History, screening, settings**: `history(limit=200, missed=false)`, `clear_history()`,
`lists(kind=null)`, `list_add(kind, pattern, action=null, note="")` (kind ∈ allow/block/spam;
numbers are normalized to E.164, patterns like `+1900*` kept as-is), `list_remove(kind, pattern)`,
`settings()`, `set(key, value)`, `dnd(on=null)` (null toggles), `detect(text)` →
`[{start, end, raw, e164, display}]`.

Settings keys: `region`, `own_number`, `dnd`, `dnd_action`, `dnd_repeat_callers`,
`dnd_allowed_groups`, `unknown_action`, `withheld_action`, `spam_action`, `neighbor_spoof_filter`,
`clipboard_detect`, `backend`, `sip_account` (read-only through `set`; use the SIP account methods
below — `set("sip_account", …)` is refused so a password can never be smuggled in through it).
Actions are `ring`, `silent`, `voicemail`, `reject`.

**SIP account**: `sip_account()` → the saved account without its password, or `null`:
`{display_name, username, domain, proxy, transport, has_password}`. `save_sip_account(account,
password=null)` validates and saves `account` (`{display_name="", username, domain, proxy="",
transport="udp"}`; `username` containing `user@domain` is split automatically) and, if `password` is
given, stores it in the system keyring (never in Store/settings, never in a file); a blank/omitted
`password` on an existing account keeps the current one, and one is required the first time. Raises
on invalid input (bad transport, empty username/domain, a password containing `"`, `<`, `>` or a
newline, …) with a joined, human-readable message. Also pushes the account live to a connected `sip`
backend (`uanew` over ctrl_tcp) so it does not wait for a daemon restart. `delete_sip_account()`
removes the saved account, clears its keyring entry, and tears down the live account (`uadel`).

**Registration**: `registration(backend=null, refresh=false)` → the `state()` call's `registration`
dict (or just one backend's, if `backend` is given); `refresh=true` also asks that backend to check
right now (baresip: sends `reginfo`) — the answer arrives as a `registration` `Event`, since the
check itself is asynchronous. Each backend's status is `{state, ok, detail, reason}`: `state` is one
of `connecting` (transport up, no verdict yet), `no_account` (nothing configured), `registering`,
`registered`, `failed`, or `offline` (not connected); `ok` is shorthand for `state == "registered"`;
`detail` is a human string (server, expiry, or the reason the transport is down); `reason` is set
only on `failed`, from baresip's last `REGISTER_FAIL` (e.g. `"401 Unauthorized"`). Before this, `sip`
reported `ok: true` as soon as its `ctrl_tcp` TCP connection came up, regardless of whether SIP
registration had actually succeeded — that is what `no_account`/`connecting`/`registering` now
distinguish from a real `registered`.

## Events

`Event` carries `{"type": …}`:

| type | payload | when |
|---|---|---|
| `incoming` | `call` | a call passed screening and is ringing (or silenced) |
| `call` | `call` | any call state change |
| `ended` | `call` + `status`, `reason` | call finished; status is what the log records |
| `conference` | `conference`, `calls` | calls merged |
| `audio` | `speaker`, `route` | route changed |
| `registration` | `backend`, `state`, `ok`, `detail`, `reason` | a backend's registration state changed (see "Registration" above) |
| `contacts`, `history`, `lists`, `settings` | | data changed, reload |
| `dnd` | `on` | do-not-disturb toggled |
| `show` | `page`, `number`, `call_id` | UI should come forward |
| `dtmf` | `call_id`, `digit` | the far end pressed a key (SIP: RFC 4733) |
| `error` | `detail` | an asynchronous failure |

## Shell hooks

phoned follows `docs/shell/INTEGRATION.md`:

- Ringing call → notification `category=call.incoming`, urgency critical, resident, actions
  `accept`, `decline`, `silence`, `voicemail`, `default`, hints `x-ophone-caller`, `x-ophone-number`,
  `x-ophone-video`. The shell's full-screen surface answers via `ActionInvoked`. When the
  notification server is not the phone shell, phoned also opens the app's own incoming page.
- Calls screened to *silent* use `category=call.silenced` (an ordinary card, never the full screen).
- Connected call → resident `category=call` notification (the status-bar pill); `default` brings
  the in-call page forward. Closed when the call ends.
- Missed / screened calls → `category=call.unanswered` with `callback` / `allow` actions.
- The ringtone is skipped when `$XDG_RUNTIME_DIR/omarchy-phone/silent` says `on`.
- `x-ophone-caller` and the notification summary carry the real caller name only when
  `$XDG_RUNTIME_DIR/omarchy-phone/locked` says `off`; otherwise (missing file, unreadable, any other
  content) they carry the generic "Incoming call" instead, per `docs/phone/DESIGN.md` → "Privacy and
  security". `shell/bin/ophone-sys` has a `locked on|off` case (mirroring its `silent on|off` case,
  which writes `$state/silent`) that writes `$state/locked`. `shell/qs/Services/Phone.qml` publishes
  it at every lock-state transition: `lock()` writes `on`, `unlock()` writes `off`, and the boot-time
  `_decideBootLock()` writes whichever it lands on. The shell also writes `on` unconditionally as
  soon as it starts, before boot lock state is even decided -- `$XDG_RUNTIME_DIR` is per-session
  tmpfs, so a stale `off` could otherwise survive a shell crash/restart and leak a caller name on an
  actually-locked device.
- A shell can subscribe to `Event` for anything else (e.g. `dnd`).
