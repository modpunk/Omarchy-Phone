# Omarchy Phone — Phone app design

Status: v0.1 (first working version on the `phone-app` branch). Owner area: `apps/phone/`, `docs/phone/`.

## 1. Goals and constraints

The first target is an iPhone 6s running HoolockLinux: 375x667 logical pixels (scale 2), two cores,
2 GB RAM, **software rendering only**, and **no cellular modem**. Every "call" therefore travels over
Wi-Fi through an IP calling service. The app must:

- be touch-first at 375x667, and stay usable when Hyprland tiles it on a laptop;
- idle at near-zero CPU (a phone app lives all day in the background, waiting for calls);
- prefer open, self-hostable protocols; no vendor account is required to use it;
- keep contacts, history and screening decisions on the device.

Required features: contacts (vCard import/export, favorites, groups), dialer, call history, call
screening (unknown/spam rules, allow-lists, send-to-voicemail or reject), copy/paste of numbers,
tap-to-call on numbers detected in text (clipboard and in-app), voice-to-video upgrade and back,
group calls, mute/hold/speaker/Bluetooth routing, do-not-disturb.

## 2. Calling backend

### 2.1 Candidates

| Option | Protocol / hosting | Footprint on a 2-core phone | Video | Group | Verdict |
|---|---|---|---|---|---|
| **baresip** (libre + libbaresip) | SIP, SRTP/DTLS-SRTP, ZRTP; any SIP server (Asterisk, FreeSWITCH, Kamailio, or a commercial SIP trunk for PSTN numbers) | Very small C daemon, module-based (opus, pipewire, v4l2, avcodec). Designed to run headless and be controlled from outside | Yes, SDP re-INVITE adds/drops `m=video` | Local mixing of a few legs (`conference` style) or a server-side bridge | **Primary backend** |
| pjsip / pjsua2 | SIP | Small C library, but we would have to write and maintain bindings | Yes | Yes (conference bridge built in) | Good fallback if baresip hits a wall |
| liblinphone | SIP | Large C++ SDK, pulls in Qt/belle-sip stack; heavier on memory | Yes | Yes (server conferences) | Too heavy for the target |
| Sofia-SIP (as in GNOME Calls) | SIP | Small, but the Calls SIP provider is audio-only and tied to Calls | No | No | Prior art, not a base |
| **Matrix + MatrixRTC / Element Call** | Matrix, self-hostable (Synapse/Conduit + LiveKit SFU) | Element Call is a web app; native needs libwebrtc/LiveKit. A browser engine or libwebrtc under software rendering on 2 cores is the heaviest option | Yes | Yes (SFU) | **Second backend, later** — best for "call my Matrix contacts" and group video |
| Matrix legacy 1:1 VoIP (`m.call.*`) | Matrix | Needs GStreamer `webrtcbin` | Yes | No | Possible stepping stone to the above |
| XMPP Jingle (Conversations, Dino) | XMPP, self-hostable (Prosody/ejabberd) | GStreamer RTP stack, moderate | Yes | Limited (Muji) | Candidate third backend |
| Jami | P2P (OpenDHT), no server needed | `jamid` daemon, heavy (Qt/ffmpeg/pjsip inside) | Yes | Yes (swarm conferences) | Interesting for serverless, too heavy for v1 |
| Signal / WhatsApp / Telegram | Closed or unfederated | n/a | n/a | n/a | Rejected: no supported third-party clients, account binding to a phone number |

### 2.2 Decision

1. **A pluggable backend interface** (`omarchy_phone/backends/base.py`). The daemon, UI, screening, history
   and audio routing never talk to a protocol directly.
2. **SIP through baresip is the production backend.** SIP is the only open protocol that also reaches
   ordinary phone numbers: a user points it at any SIP provider (self-hosted Asterisk/FreeSWITCH, or a
   SIP trunk that owns a DID) and gets a real phone number without a modem. baresip is the lightest
   complete SIP stack on Linux, speaks PipeWire natively, supports opus + video, and runs as a separate
   process we control over its `ctrl_tcp` module (netstring-framed JSON). A crash in the media stack
   cannot take the UI down, and the stack can later be swapped for pjsip without touching the app.
   *Caveat:* baresip is not installed on the dev laptop; the adapter is written against the documented
   `ctrl_tcp` protocol and tested against a fake server. Arch's `baresip` package must be checked for the
   `ctrl_tcp` and `pipewire` modules before packaging.
3. **Matrix (MatrixRTC) is the second backend**, targeted once a LiveKit client can run natively
   without a browser engine. The interface already models what it needs (room-based group calls,
   participants joining/leaving, per-participant video).
4. **A loopback backend** ships now for development and tests: several local daemon instances find
   each other through a tiny JSON-over-UDP signalling protocol on 127.0.0.1. It exercises the entire
   call lifecycle (ringing, screening, answer, hold, video upgrade, group calls, history) with zero
   external services or accounts. It carries no media in v0.1.

### 2.3 Why not fork GNOME Calls?

Calls is GTK4/libadwaita and has pluggable providers, which is the right shape. But its SIP provider
(Sofia-SIP) is audio-only, it has no video, no group calls and no screening, its call routing relies on
`callaudiod` + ModemManager assumptions, and it is C/GObject with a large build. The features that make
this app worth having (screening, detection, video, groups) would all be new code either way. We keep
Calls' good ideas: providers as plugins, a separate audio policy, and "tel:" handling through the desktop.

### 2.4 Backend interface

```python
class Backend:
    id: str                        # "loopback", "sip", "matrix"
    capabilities: set[str]         # {"video", "hold", "group", "dtmf", "voicemail", "transfer"}
    def start(self, emit): ...     # emit(event: dict) delivers events to the daemon
    def stop(self): ...
    def dial(self, call_id, uri, video=False): ...
    def answer(self, call_id, video=False): ...
    def hangup(self, call_id, reason="normal"): ...    # also used for reject ("busy")
    def divert_to_voicemail(self, call_id): ...        # SIP 302 to the voicemail URI, or local voicemail
    def set_hold(self, call_id, on): ...
    def set_mute(self, call_id, on): ...
    def set_video(self, call_id, on): ...              # SIP re-INVITE / MatrixRTC track publish
    def send_dtmf(self, call_id, digits): ...
    def merge(self, call_ids) -> str: ...              # returns the conference id (group call)
```

Events flowing up: `incoming {call_id, remote, display_name, video}`, `state {call_id, state}`,
`video {call_id, on}`, `participants {call_id, list}`, `ended {call_id, reason}`. Call states:
`dialing → ringing(outgoing) → active ⇄ held → ended`, or `incoming → active | ended`.

## 3. Architecture

```
            ┌─────────── omarchy-phone (GTK4/libadwaita UI, 375x667) ───────────┐
            │ Favorites · Recents · Contacts · Keypad · In-call · Incoming      │
            └───────────────▲──────────────────────────────┬────────────────────┘
                 D-Bus signal Event(json)           D-Bus method Call(method, json)
            ┌───────────────┴──────────────────────────────▼────────────────────┐
            │ phoned  (session daemon, GLib main loop, bus name org.omarchy.Phone)│
            │  CallManager ─ Screening ─ Store(SQLite) ─ AudioRouter ─ Notifier  │
            │        │                                                           │
            │   Backend plugins:  loopback │ sip (baresip ctrl_tcp) │ matrix*    │
            └────────┼──────────────────────────────┼───────────────────────────┘
                 UDP 127.0.0.1               TCP 127.0.0.1:4444 → baresip → SIP server
```

- **phoned** is a small Python process on the GLib main loop (no threads, no polling; it sleeps
  in `poll()` until a socket or D-Bus message arrives). It owns every piece of state, so a UI crash or
  restart never drops a call, and the incoming-call path works while the UI is closed.
- **D-Bus API** is deliberately generic: one method `Call(s method, s json_args) → s json` and one signal
  `Event(s json)` on `org.omarchy.Phone1` at `/org/omarchy/Phone`. Adding a feature does not change the
  introspection XML. The full method list is in `docs/phone/API.md`.
- **The UI** is a D-Bus client that renders daemon state. It can be launched on demand; the daemon
  starts it for incoming calls.
- **`phonectl`** is the CLI: `phonectl dial <number>`, `phonectl detect < text`, `phonectl import x.vcf`,
  used by the shell, scripts, and the `tel:` URI handler (`x-scheme-handler/tel`).

### 3.1 Storage

SQLite at `$XDG_DATA_HOME/omarchy-phone/phone.db` (contacts, numbers, groups, favorites, call log,
screening lists, settings). No config file is written under `~/.config`. Contacts are also
importable/exportable as vCard 3.0/4.0 files; vCard is the interchange format, SQLite is the index.

### 3.2 Shell integration

The shell (`docs/shell/INTEGRATION.md`) is the notification server and needs nothing phone-specific
beyond freedesktop notifications:

- Ringing call → `category=call.incoming`, `urgency=critical`, `resident=true`, actions `accept`,
  `decline`, `silence` (plus `voicemail`), hints `x-ophone-caller` / `x-ophone-number` /
  `x-ophone-video`. The shell turns it into a full-screen call surface that also works over the lock
  screen. On any other notification server phoned also opens the app's own incoming page.
- Connected call → one resident `category=call` notification, shown by the shell as the status-bar
  call pill; its `default` action brings the in-call page forward.
- Silenced (screened) calls use `category=call.silenced` so they never take over the screen; missed
  and screened calls use `call.unanswered` with "Call back" / "Always allow".
- The app plays the ringtone and skips it when the shell's silent switch is on
  (`$XDG_RUNTIME_DIR/omarchy-phone/silent`).
- The daemon's `Event` signals (`incoming`, `call`, `ended`, `dnd`, …) are available to the shell or
  scripts. See `docs/phone/API.md` → "Shell hooks". All of this lives in `notify.py`.

## 4. Number handling

- **libphonenumber** is the reference implementation; the app uses it through `python-phonenumbers`
  (Arch `extra`) when installed: parsing, E.164 normalization, national/international formatting,
  and `PhoneNumberMatcher` for detection in text.
- A **built-in fallback** (`omarchy_phone/numbers.py`) keeps the app working without it (and is what
  the tests exercise here): E.164 normalization with a default region, NANP and common country calling
  codes, and a detector that avoids false positives on dates, times, IP addresses, versions, prices,
  card-like digit runs and order IDs.
- Numbers are stored as E.164 (`+15551234567`); anything not a phone number (SIP URI
  `sip:alice@example.org`, Matrix ID `@alice:example.org`) is stored as a URI and dialled as-is.
- Matching an incoming caller to a contact compares E.164 forms, falling back to the last 9 digits
  for numbers that arrive without a country code.

### 4.1 Tap-to-call, copy and paste

- Every number shown in the app (contact details, call log, notes) is a selectable label with
  `tel:` links from the detector; tap opens "Call / Copy / Add to contact".
- Keypad: **Paste** takes the first number found in the clipboard (not the raw text) and normalizes it.
  Long-press on the number field copies it.
- **Clipboard detection** (opt-in, off by default for privacy): when the app gains focus and the
  clipboard holds a phone number, a chip "Call +1 555-…" appears above the keypad. The app reads the
  clipboard only while focused; nothing is stored.
- System-wide: `phonectl detect` turns text into `tel:` links for the shell (e.g. a text-selection
  action), and the shipped `omarchy-phone-tel.desktop` makes `tel:` URIs from any app open the dialer.

## 5. Call screening

Screening is a pure function `screen(caller, context) → Decision(action, reason)` evaluated in the daemon
before the phone rings. Actions: `ring`, `silent` (log + notification, no ringtone), `voicemail`, `reject`.
First match wins:

1. **Emergency/allow-list** numbers and **favorites** always ring (even in DND).
2. **Block-list** (exact number, prefix like `+1900`, or wildcard like `+1555*`) → the rule's action
   (default `reject`).
3. **Anonymous / withheld** caller → the "withheld" policy (default `voicemail`).
4. **Do-not-disturb**: favorites and allow-listed groups pass (rule 1); a **repeat caller** (same number
   twice within 3 minutes) breaks through; everyone else goes `silent` or `voicemail` per setting.
5. **Spam heuristics**: premium-rate prefixes, neighbour spoofing (same country and first 6 digits as
   your own number, not a contact), and numbers the user reported as spam → spam action
   (default `voicemail`).
6. **Unknown callers** (not in contacts): the "unknown" policy (default `ring`; can be `silent`,
   `voicemail`, `reject`).
7. Otherwise `ring`.

Every decision is recorded in the call log with its reason ("Blocked: +1900*", "DND"), so screening is
never invisible, and a screened call can be allow-listed from its history row in one tap.

## 6. Audio and video

- **PipeWire** is the audio server. baresip uses its `pipewire` module; the daemon's `AudioRouter`
  inspects nodes with `pw-dump` and switches routes with `wpctl set-default`:
  - *Earpiece / Speaker*: the phone's sink profiles (on laptops: the built-in sink).
  - *Bluetooth*: any `bluez_output.*` sink (HFP/HSP for calls; WirePlumber switches profiles).
  - *Wired headset*: sinks whose port is headphones.
  The route before the call is restored at hangup.
- **Mute** is done in the backend (stop sending audio), not by muting the system source, so the mic
  state of other apps is untouched. **Hold** is a backend operation (SIP re-INVITE `sendonly`), and the
  local stream pauses.
- **Video**: upgrading a call re-negotiates with a video stream (SIP re-INVITE / MatrixRTC track).
  Capture uses the PipeWire camera portal (`pipewiresrc`); decode renders into a GTK `Picture` via a GL-
  free sink. At 375x667 with software rendering, video is capped at 320x240@15 fps VP8/H.264; the
  preview tile is rendered at half that. Downgrading drops the video stream but keeps the call.
- **Group calls**: two active calls can be **merged**; the backend capability decides whether it mixes
  locally (baresip, up to ~4 audio legs on 2 cores) or asks a server-side bridge (Asterisk ConfBridge,
  FreeSWITCH conference, MatrixRTC SFU). The UI shows a participant list and can add a participant by
  dialling while in a call.

## 7. Privacy and security

- No telemetry, no cloud contact sync by default; contacts, history and spam lists stay in SQLite on the
  device. Export is an explicit vCard file.
- Clipboard access is opt-in and only while the app is focused.
- SIP credentials are read from the Secret Service (libsecret) keyring, never written into the
  database. SIP uses TLS transport and SRTP (DTLS-SRTP or ZRTP) — the backend refuses unencrypted
  media unless the account explicitly allows it.
- The loopback backend binds to 127.0.0.1 only.
- Notifications on the lock screen show the caller name only if the shell says the device is unlocked;
  the default notification body is the number or contact name without the call log.

## 8. UI

GTK4 + libadwaita via PyGObject.

**Why not QuickShell/QML?** QuickShell is a toolkit for *shell* surfaces (layer-shell bars, panels,
lock screens) and is exactly what `shell/` uses; it is not meant for ordinary app windows, and has no
widget set for lists, forms and navigation. Plain Qt Quick would need a C++ plugin for D-Bus and its
software backend drops some effects. libadwaita was built for phones (Phosh; GNOME Calls, Chatty and
Contacts all run at 360 px wide): `Adw.NavigationView`, `Adw.ViewStack` + bottom `Adw.ViewSwitcherBar`,
swipe-back gestures, 48 px touch targets, and it renders with `GSK_RENDERER=cairo` on devices without
GPU drivers. Python shares code with the daemon, and a single-instance `Adw.Application` stays resident
after the first launch so incoming calls appear instantly.

Screens (bottom tab bar):

- **Favorites** — large tiles, one tap calls.
- **Recents** — call log with direction/missed/screened icons, filter "Missed"; tap calls back,
  row menu: add to contacts, allow, block, copy.
- **Contacts** — searchable list with group filter; detail page with tap-to-call numbers, favorite
  star, groups, video call, block. Header menu: import/export vCard, new contact.
- **Keypad** — number field with live formatting and contact match, Paste, clipboard chip,
  call / video call buttons.
- **In-call** (pushed over everything) — name, timer, state; buttons: mute, keypad, speaker/route,
  video, hold, add call, merge, end. Participant list in group calls. Video tiles when video is on.
- **Incoming** — full-screen: caller, screening reason if any; Answer, Answer with video, Decline,
  Voicemail. Also mirrored as a notification with actions.
- **Settings** — account/backend, DND toggle and policy, unknown/withheld/spam policies, block-list and
  allow-list editors, clipboard detection toggle.

## 9. v0.1 scope and next steps

Working in v0.1 (on this laptop, loopback backend): daemon + D-Bus API + CLI; calls between local
instances with ringing, answer, decline, voicemail diversion, hold/resume, mute, DTMF, voice↔video
switching (signalled; no media yet), merge into a group call and split/leave; contacts with vCard
2.1/3.0/4.0 import and 3.0/4.0 export, favorites and groups; call log with screening reasons;
screening engine (block/allow/spam lists with patterns, unknown/withheld/spam policies, neighbour
spoofing, DND with favorites, allowed groups and repeat callers); number detection with tap-to-call,
paste and opt-in clipboard detection; PipeWire route listing/switching incl. Bluetooth sinks;
notifications per the shell contract; the phone-size UI (screenshots in `docs/phone/screenshots/`).

Not done yet: real media (no RTP elements in this GStreamer install), the baresip backend against a
real baresip, voicemail recording/playback, video rendering, SIP account setup UI (credentials via
libsecret), MatrixRTC.

Next steps, in order:

1. Run the baresip backend against a local Asterisk in a container (loopback SIP, no external
   accounts); fix command-name differences in `backends/baresip.py:COMMANDS`.
2. SIP account page (server, user, libsecret password, TLS/SRTP policy) that writes baresip's config.
3. Media on the loopback backend (opus over UDP via GStreamer once `gst-plugins-good` is installed),
   so audio routing and mute can be tested end to end.
4. Voicemail store and playback; video preview/rendering via `pipewiresrc` and a GTK paintable sink.
5. Measure on the iPhone 6s (idle CPU of phoned, UI start time under `GSK_RENDERER=cairo`); consider
   keeping the UI resident.
6. MatrixRTC backend.
