# Omarchy Phone — QA sweep and backlog

Produced 2026-09-30 from a code-and-test-only sweep of `origin/main` (commit `7469fc3`, "Merge
pull request #9 from modpunk/shell-osk-content"). No hardware, no testkit, no `phone.sh`, no
telnet access were used — everything below comes from running the repo's own test suites and
reading the code, not from speculation. Every item cites the file(s) it's based on; anything not
personally verified in this sweep is marked **unverified**.

## Verified working (tests green)

| Suite | Command | Result |
|---|---|---|
| `apps/phone` full suite (incl. Docker SIP e2e) | `OMARCHY_PHONE_KEYRING=memory scripts/test.sh -v` | **94/94 passed**, 0 skipped, 0 failures, 11.9s. Docker was available and the `omarchy-phone-sipbed:edda5335eb9f` image was already cached, so `tests/test_sip.py` (real Asterisk 20 + two baresip endpoints) ran for real, not skipped. CI itself only runs 55 of these (`OMARCHY_PHONE_SKIP_SIPBED=1` there), so this sweep covers more than CI does. |
| `shell` unit tests | `shell/tests/run.sh` | **20/20 passed** (`test_bt_agent.py`, `test_pin.py`), 7.7s. Only warnings: `Gio.DBusConnection.register_object is deprecated` in `shell/bin/ophone-btagentd:114`, fires on every test, not a failure. |
| `qmllint` over `shell/qs/**/*.qml` | same invocation as `.github/workflows/shell.yml` | **Exit 0**, 0 syntax errors, 752 `[unqualified]`/`[unresolved-type]` warnings — all from Quickshell's runtime-resolved `qs.Commons`/`qs.Services`/`qs.Surfaces` namespace, exactly the class of warning CI's own comment says to expect and ignore. |
| `shell/im` build (`make -C shell/im`) | `wayland-scanner` + `cc -O2 -Wall -Wextra` | Builds clean, **zero compiler warnings**, produces `shell/bin/ophone-im` (23,192 bytes, ELF x86-64 PIE). Correctly `.gitignore`d (`git status` after the build shows nothing new tracked). |
| `Hyprland --verify-config` (bonus, matches `shell.yml`'s second check) | once per `shell/hypr/devices/*.lua` | `generic`, `iphone6s`, `preview` all report `config ok`, exit 0. |

Dependency notes for the above: GTK 4 + libadwaita + `gi.repository.Secret` (libsecret) were all
importable in this environment, so `test_accounts.py`'s keyring-adjacent tests ran for real (with
`OMARCHY_PHONE_KEYRING=memory`, the in-memory stand-in, not a real Secret Service — no desktop
keyring was unlocked). `python-phonenumbers` was **not** installed here, so `test_numbers.py` ran
the built-in fallback parser (`omarchy_phone/numbers.py`), not the libphonenumber path; CI
installs `python-phonenumbers`, so the libphonenumber path is exercised there, not in this sweep —
**both paths are asserted by the same test file, but this run only proves one of them.**

Not run: `apps/phone/scripts/screenshots.sh` and `shell/preview/run.sh` (both need a live/headless
Wayland session; `run.sh` also shares `/tmp/oph-$UID` with any other worktree already using it —
the repo's own `settings-app` work may be). Neither is required by CI (`docs/CI.md` explicitly
excludes `run.sh` from CI for the same reason). **Unverified** in this sweep.

## Feature → module → test → status matrix

| Feature (from the product's intended set) | Where it lives | Test coverage | Status |
|---|---|---|---|
| Dialer / tap-to-call (in-app) | `apps/phone/omarchy_phone/ui.py` (keypad, dial buttons), `numbers.py` (detection/linkify) | `test_numbers.py` (detection, false positives), `test_calls.py` (dial flows) | **Done, in-app.** System-wide tap-to-call (outside the Phone app) is not wired — see P2 below. |
| Contacts (vCard import/export, favorites, groups) | `omarchy_phone/vcard.py`, `store.py`, `ui.py` Contacts tab | `test_vcard.py` (2.1/3.0/4.0 import, round trip, store merge) | **Done.** |
| Call screening (block/allow/spam, unknown/withheld, DND) | `omarchy_phone/screening.py`, `calls.py` | `test_screening.py` (11 tests: precedence, DND+repeat caller, neighbour spoofing, emergency) | **Done.** |
| Call groups (contact groups for DND allow-lists; call merging into a group call) | `store.py` (`groups` table), `calls.py` (`merge`/`split`) | `test_calls.py::Flows.test_group_call`, `test_screening` DND-allowed-groups cases | **Done**, local mixing only (baresip capability: up to ~4 legs); server-side conference bridging for SIP is explicitly not done — see P2. |
| Recents / call history | `store.py` call-log table, `ui.py` Recents tab | Exercised indirectly by `test_calls.py` (missed/blocked/voicemail statuses) | **Done.** |
| SIP accounts (add/edit/remove, password via keyring) | `omarchy_phone/sip_account.py`, `keyring.py`, Settings → SIP account page in `ui.py` | `test_accounts.py` (18 tests: validation, baresip account-line building, keyring round trip, CRUD, password never in Store/state()/JSON) | **Done.** Landed recently (`9426fa6`, `daa2dde` on `origin/main`). |
| Voice calls | `backends/baresip.py`, `backends/loopback.py` | `test_calls.py`, `test_sip.py` (real two-way audio through Asterisk, tone in/WAV out) | **Done** for SIP (real audio, verified) and loopback (signalling only, no media — by design, see `docs/phone/DESIGN.md` §9). |
| Video calls (voice→video upgrade) | `backends/baresip.py` (`dial_video`/`accept_video`/`video_dir` re-INVITE), `ui.py` in-call screen | `test_calls.py` covers signalling (`video_on` state, `set_video`); **no test exercises actual video capture/render, because none exists** | **Signalling only.** `ui.py:826-829` renders a static `camera-video-symbolic` icon in a `.video-area` box — there is no `pipewiresrc` capture or GTK `Picture`/paintable sink anywhere in the tree. `docs/phone/DESIGN.md` §9 already says this ("video rendering" is in "Not done yet"); confirmed by grep, not just by trusting the doc. Also hardware-gated on the iPhone 6s (no camera driver yet, per README). |
| Copy/paste numbers | `ui.py` (`get_clipboard().set`/`read_text_async`, Paste button, long-press copy) | Exercised by `test_numbers.py`'s detection/formatting, not UI-level (GTK UI has no headless test) | **Done** (code-level); UI interaction itself is **unverified** here (no UI test harness for GTK in this repo). |
| Notifications (incoming/missed/silenced call cards, shell contract) | `omarchy_phone/notify.py`; shell side `shell/qs/Services/Notifs.qml`, `Widgets/CallCard.qml` | `test_notify.py` (app side, against a fake notification server it wrote itself) | **Done and cross-checked.** Verified by direct grep that the shell actually reads the same names the app sends: `category` (`call.incoming`/`call`/`call.silenced`/`call.unanswered`), hints `x-ophone-caller`/`x-ophone-number`/`x-ophone-video`, actions `accept`/`decline`/`silence`. No test launches both processes together, so this is "contract matches by inspection," not an integration test. |
| Lock screen | `shell/qs/Surfaces/LockScreen.qml`, `Services/LockAuth.qml`, `shell/bin/ophone-pin`, PAM | `shell/tests/test_pin.py` (9 tests) | **Done**, and hardened (see `docs/shell/DESIGN.md` "Lock screen PIN" for the F2–F4 security fixes already shipped: PIN separated from account password, idle auto-lock, faillock throttling). |
| OSK (on-screen keyboard, content-purpose-aware layouts) | `shell/im/ophone-im.c`, `shell/qs/Surfaces/Keyboard.qml`, `Services/Phone.qml` | Exercised by `shell/preview/run.sh`'s `osk*`/`kb*` scenarios (assertive, not just screenshots) — **not run in this sweep** (needs a live/headless Wayland session); `make -C shell/im` does build clean | **Believed done** per the merged `shell-osk`/`shell-osk-content` PRs (#7, #9) and a clean build; **not independently re-verified** here beyond compiling it. |
| Settings | Phone app: `ui.py` Settings page (own number, DND, policies, block/allow lists, SIP account sub-page). Shell: **no system Settings surface exists** in `shell/qs/Surfaces/` on `origin/main` today. | Phone-app settings exercised indirectly via `test_accounts.py`, `test_screening.py` | **Phone-app settings: done.** Shell-level Settings surface: **not present on `origin/main`**; shell-side work on this is understood to be in progress on a separate, not-yet-pushed local branch — not scored as a gap here since it's actively being built elsewhere. |

## Prioritized backlog

### P0 — blockers
None found. Both test suites are fully green, qmllint is clean of syntax errors, and the one
hardware blocker (real calls on the iPhone 6s) is a known, already-documented hardware gap, not a
regression to fix in this repo (see Hardware-gated section).

### P1 — should fix soon

1. **Lock-screen caller-name privacy rule is not implemented.** `docs/phone/DESIGN.md` §7 states:
   "Notifications on the lock screen show the caller name only if the shell says the device is
   unlocked." Grepped `apps/phone/omarchy_phone/notify.py` end to end: `incoming()` (lines ~85-93)
   always sets the notification `summary` to the caller name/number (`who`) unconditionally — there
   is no lock-state check anywhere in `notify.py`, `calls.py`, or `daemon.py` (grepped for
   `lock`/`isLocked`, only hits are unrelated `block`-list code). The design doc's privacy claim is
   aspirational, not built. Needed: either the daemon learns lock state (e.g. via `qs ipc` /a D-Bus
   call to the shell) and redacts `summary`/`x-ophone-caller` when locked, or the doc should be
   corrected to say this is shell-side-only (the shell's own lock screen already shows "a count of
   notifications, no content" per `docs/shell/DESIGN.md`'s Lock screen section — so the redaction
   may already happen at the *display* layer in the shell, not the *content* layer in the app; if
   so, the notification still carries the caller's name in its D-Bus payload the whole time, which
   is a smaller but real information-exposure gap for any *other* notification consumer). Worth a
   design decision, not just a doc fix.
2. **`AudioRouter` (PipeWire route switching) has zero test coverage.** `omarchy_phone/audio.py` is
   imported and wired into `daemon.py` (`from .audio import AudioRouter`, `self.audio =
   AudioRouter()`, `m_routes`/`m_route` methods, line ~27/70/84/190-194) and into `calls.py`, but
   there is no `test_audio.py`. `pw-dump`/`wpctl` interaction (earpiece/speaker/Bluetooth/headset
   routing, and the "route before the call is restored at hangup" behavior from
   `docs/phone/DESIGN.md` §6) is entirely unverified by the suite. This is real, shipped code with
   no regression safety net.
3. **System-wide tap-to-call has no shell hook.** `docs/phone/DESIGN.md` §4.1 describes
   `phonectl detect` turning text selections into `tel:` links "for the shell (e.g. a
   text-selection action)." Grepped all of `shell/` for `phonectl`: **zero matches.** The CLI
   command exists and is tested at the unit level (`numbers.py`'s detector), but nothing in the
   shell actually invokes it. Either build the shell-side hook or mark this DESIGN.md line as a
   future item rather than current capability.
4. **`shell/preview/run.sh` (the shell's own assertive OSK/content-purpose test scenarios) was not
   re-run in this sweep.** It's the only test surface for the on-screen-keyboard's focus-driven
   show/hide and per-content-purpose layout switching (`osknum`/`oskphone`/`oskpass`/`oskemail`/
   `oskurl`, each asserting `ipc keyboardLayout`, not just a screenshot, per `docs/shell/DESIGN.md`).
   It was skipped here only because it needs a live/headless Wayland session and shares a
   `/tmp/oph-$UID` scratch dir that a concurrent worktree may be using — not because it's expected
   to fail. Recommend someone re-run it (with a distinct `OPHONE_PREVIEW_DIR`) as a follow-up,
   since "believed done from the merged PR" is weaker evidence than a fresh green run.

### P2 — worth doing, not urgent

5. **Doc drift: stale test counts and stale status lines.**
   - `README.md:33` says "Works on the loopback test backend (48 tests pass)"; actual is 94 (and
     SIP/baresip backends are also covered now, not just loopback).
   - `docs/CI.md:12` says "Runs the ~48 `unittest` tests"; `docs/CI.md:18` says "verified... (55
     ran, 6 skipped, 0 failures)" — both predate the `test_accounts.py` suite (18 tests) that landed
     with the SIP account page.
   - `docs/shell/DESIGN.md:607` says `shell/preview/gtk4-field.py` is "a preview-only stand-in text
     field (apps/phone doesn't exist yet)" — `apps/phone` has existed and been merged since PR #3;
     this line is now misleading (the file itself may still be a legitimate lightweight stand-in
     for preview purposes, but the parenthetical reason is outdated).
6. **`qmllint`'s 752 warnings mean the shell has essentially no static type-checking today.**
   Every one of them is the expected `qs.Commons`/`qs.Services`/`qs.Surfaces` namespace-resolution
   warning (Quickshell resolves that module at runtime, no `qmldir`), which is why CI treats only a
   non-zero exit as a failure. The practical effect: a genuine typo in a `Theme.someProperty`
   reference would currently produce the *same* warning class as the expected noise and would not
   fail CI. Adding a `qmldir` (or an equivalent import-path trick) so qmllint can resolve those
   namespaces would let real `[unresolved-type]`/`[unqualified]` warnings stand out from the noise
   or disappear entirely — worth scoping as a follow-up, not blocking anything today.
7. **Deprecation warning in shipped code, not just tests.** `shell/bin/ophone-btagentd:114`:
   `Gio.DBusConnection.register_object is deprecated` fires on every run (test and real). Low risk
   today, but GLib deprecations do eventually get removed; worth a ticket to migrate to whatever
   API replaces it before that happens.
8. **Packaging/installation steps are all manual today (by design, not a bug, but worth listing
   together as a pre-release checklist item):** `data/phoned.service` and
   `data/org.omarchy.Phone.desktop` are "not installed automatically" (per `apps/phone/README.md`);
   `shell/system/*` (PAM service file, tmpfiles.d rule, logind drop-in, `bluetooth/main.conf`,
   `ophone-btagentd.service`) likewise need the image build to install them; `shell/bin/ophone-im`
   needs `make -C shell/im` at image-build time. None of this is testable from inside this repo —
   it's the companion `Omarchy-iPhone6s` image-build repo's job — but it's worth a single checklist
   doc (or a `docs/PACKAGING.md`) enumerating every one of these in one place, since right now
   they're scattered across four different READMEs.
9. **`docs/phone/DESIGN.md` §2.2's packaging note is unverified:** "Arch's `baresip` package must
   be checked for [`account`, `menu`, `ctrl_tcp`] plus `pipewire` (and `opus`, `srtp`) [modules]
   before packaging." This sweep used the test-bed's *compiled-from-source* baresip inside the
   `omarchy-phone-sipbed` Docker image, not Arch's packaged `baresip` binary, so whether Arch's
   package ships those modules enabled is still an open, unverified question.

### Nice-to-have

10. **MatrixRTC backend** — correctly scoped in `docs/phone/DESIGN.md` as "second backend, later."
    No code exists beyond `numbers.py` recognizing `matrix:`-shaped addresses as pass-through URIs
    (`vcard.py:171`, `numbers.py:7,44,48,128,281`) — there is no `backends/matrix.py`. This is
    intentional, not a regression; listed here only so it isn't mistaken for an oversight.
11. **Voicemail recording/playback** — "voicemail" throughout `calls.py`/`baresip.py`/`store.py`
    today means only *diverting* a call (SIP busy response, or marking history status
    `"voicemail"`); there is no audio recording or playback anywhere in the tree. Matches
    `docs/phone/DESIGN.md` §9's own "Not done yet" list; confirmed by grep, not just trusted from
    the doc.
12. **Group calls over SIP (server-side conference bridge)** — local mixing works and is tested
    (`test_calls.py::test_group_call`, loopback); a SIP-side bridge (Asterisk ConfBridge /
    FreeSWITCH) for more than ~4 legs is explicitly future work per `docs/phone/DESIGN.md` §6/§9.
13. **TLS/SRTP policy in the SIP account UI** — the account page exposes transport choice; SRTP/
    ZRTP policy beyond that is not yet surfaced in the UI (`docs/phone/DESIGN.md` §9 next-steps #2).
14. **A "Change PIN" entry in a Settings UI** — today `sudo ophone-pin set` is a shell command only
    (`docs/shell/DESIGN.md` "Lock screen PIN" and "Non-goals"); a GUI entry point is explicitly
    deferred until a Settings surface exists.

## Hardware-gated (blocked by the device, not by this repo's code)

These are not code gaps — they're blocked on the target hardware (iPhone 6s / HoolockLinux) and
were not something this sweep could touch (no phone/testkit access, by design of this task):

- **Real calls on the iPhone 6s at all.** Per `README.md`'s own Status table: "Touch input,
  charging and Wi-Fi are still missing on that device, so the Phone app can't place real calls
  there yet." Everything this sweep verified (94 app tests, 20 shell tests) ran on a development
  machine, not the phone.
- **Video capture/render.** Even once the software side is built (see P1/nice-to-have above), the
  iPhone 6s has no working camera driver under HoolockLinux today (not evidenced in this repo;
  inferred from the same README hardware-gap list — **unverified** beyond that inference, since
  camera status specifically isn't itemized in this repo's README).
- **Touch input** on the shell surfaces — the shell is fully keyboard-navigable specifically
  because touch doesn't work yet on this device (`docs/shell/DESIGN.md` "Keyboard" section); this
  is a deliberate current-state accommodation, not a shell bug.
- **Auto-rotation** — explicitly listed as a non-goal pending `iio-sensor-proxy` hardware support
  (`docs/shell/DESIGN.md` "Non-goals (v1) and next steps").

## What this sweep did not check

- GTK4/libadwaita UI interaction (clicking buttons, navigating screens) — no headless GTK test
  harness exists in this repo; everything UI-level is only exercised indirectly through the D-Bus
  API the UI itself calls.
- `apps/phone/scripts/screenshots.sh` and `shell/preview/run.sh` — both need a live/headless
  Wayland session; not run here (see "Verified working" and P1 item 4).
- Whether the real (non-test-bed) Arch `baresip` package has the required modules compiled in
  (P2 item 9).
- Anything requiring the physical phone, `testkit`/`phone.sh`, or the telnet bring-up address —
  out of scope for this task by explicit instruction.
