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
| `state` | | `{calls, speaker, dnd, registration, backends, profile, own_number}` |
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
`clipboard_detect`, `backend`. Actions are `ring`, `silent`, `voicemail`, `reject`.

## Events

`Event` carries `{"type": …}`:

| type | payload | when |
|---|---|---|
| `incoming` | `call` | a call passed screening and is ringing (or silenced) |
| `call` | `call` | any call state change |
| `ended` | `call` + `status`, `reason` | call finished; status is what the log records |
| `conference` | `conference`, `calls` | calls merged |
| `audio` | `speaker`, `route` | route changed |
| `registration` | `backend`, `ok`, `detail` | backend connected/disconnected |
| `contacts`, `history`, `lists`, `settings` | | data changed, reload |
| `dnd` | `on` | do-not-disturb toggled |
| `show` | `page`, `number`, `call_id` | UI should come forward |
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
- A shell can subscribe to `Event` for anything else (e.g. `dnd`).
