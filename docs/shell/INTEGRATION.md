# Omarchy Phone shell: integrating apps

The shell *is* the phone's notification daemon: it owns
`org.freedesktop.Notifications` on the session bus. Apps don't link anything
from the shell or need to agree on anything with it. They send standard
[freedesktop notifications](https://specifications.freedesktop.org/notification-spec/latest/),
and a few well-known hints and action ids switch on the phone surfaces below.

**Only one notification daemon can run.** Apps must not start their own (mako,
dunst, swaync, and so on). Talk to the bus.

## 1. Ordinary notifications

Anything that works on a Linux desktop works here:

```sh
notify-send -a "Messages" -i mail-message-new "Ada" "Running 5 minutes late"
```

or libnotify, `gdbus`, `dbus-send`, GLib's `GNotification`, Qt, Python `dbus-next`,
and so on.

| Feature | Behaviour |
|---|---|
| `app_name`, `app_icon`, `summary`, `body` | shown on the card (body is plain text, not markup) |
| `image-path` / `image-data` hint | replaces the icon (for example a contact photo) |
| action `default` | runs when the card is tapped. With no `default` action, a tap dismisses. |
| other actions | shown as buttons on the card in the shade |
| `urgency` | `critical` is kept until dismissed |
| `resident` | the notification stays after an action is invoked |
| new notification | 4 s banner under the status bar, unless the shade is open or the phone is locked |
| lock screen | shows only a count ("3 notifications"), never the content |

## 2. Incoming call: full-screen call surface

Send a notification with **`category = call.incoming`** (a standard category in
the spec) and the actions **`accept`** and **`decline`**:

```sh
gdbus call --session --dest org.freedesktop.Notifications \
  --object-path /org/freedesktop/Notifications \
  --method org.freedesktop.Notifications.Notify \
  "Phone" 0 "call-start" "Ada Lovelace" "+1 555 0100 · Wi-Fi call" \
  "['accept','Accept','decline','Decline','silence','Silence']" \
  "{'category': <'call.incoming'>, 'urgency': <byte 2>, 'resident': <true>}" 0
```

libnotify (C/Python/Vala):

```python
n = Notify.Notification.new("Ada Lovelace", "+1 555 0100 · Wi-Fi call", "call-start")
n.set_category("call.incoming"); n.set_urgency(Notify.Urgency.CRITICAL)
n.set_hint("resident", GLib.Variant("b", True))
n.add_action("accept", "Accept", on_accept); n.add_action("decline", "Decline", on_decline)
n.add_action("silence", "Silence", on_silence)
n.show()
```

What the shell does:

* Turns the screen on and shows a full-screen caller card with Decline/Accept.
  It shows on top of the lock screen too, so a call can be answered without
  unlocking.
* The caller name is `summary`, the detail line is `body`. The avatar is the
  `image-path`/`image-data` hint, or the caller's initials.
* **Accept**: emits `ActionInvoked(id, "accept")`, then closes the
  notification (`NotificationClosed(id, 2)`).
* **Decline**: emits `ActionInvoked(id, "decline")`, then closes it.
* **Volume down while ringing**: emits `ActionInvoked(id, "silence")` if you
  added a `silence` action. The card stays up and only your ringtone stops.
  Send `resident: true` so that invoking `silence` doesn't close the
  notification.
* **Caller hangs up / call is answered elsewhere**: call `CloseNotification(id)`
  and the surface goes away.

Treat `ActionInvoked` as the answer, and don't read meaning into the
`NotificationClosed` that follows.

Optional hints (the shell falls back to summary/body without them):

| Hint | Type | Use |
|---|---|---|
| `x-ophone-caller` | string | display name, if `summary` is something else |
| `x-ophone-number` | string | number / handle line |
| `x-ophone-video` | string `"true"` | says "Incoming video call" and shows a camera glyph on Accept |

The **app plays the ringtone**. Check silent mode first (see section 4).

## 3. Call in progress: status-bar pill

While a call is active, keep one notification with **`category = call`**, a
`default` action and `resident: true`. The shell shows a green "Call" pill in
the status bar instead of listing it with the other notifications, and tapping
the pill invokes `default`, which should bring your call window to the front.
Close the notification when the call ends.

## 4. Shell state and control (IPC)

Apps and scripts can query and drive the shell with `ophone-ctl` (a wrapper
around `qs -p <shell>/qs ipc call shell <fn>`):

| Command | Returns / does |
|---|---|
| `ophone-ctl isSilent` | `true` when the ring/silent switch or the Silent tile is on. Don't ring or vibrate. |
| `ophone-ctl isLocked` | `true` while the lock screen is up |
| `ophone-ctl notifications` | JSON list of current notifications (debugging) |
| `ophone-ctl answerCall` / `declineCall` | same as tapping the buttons |
| `ophone-ctl home`, `switcher`, `shade`, `lock`, `keyboard` | navigation |

Silent mode is also written to `$XDG_RUNTIME_DIR/omarchy-phone/silent`
(`on`/`off`), so you can read it without a process spawn.

Lock state is written the same way, to `$XDG_RUNTIME_DIR/omarchy-phone/locked` (`on`/`off`):
missing, unreadable, or anything other than `off` means treat the device as locked (see
`docs/phone/API.md` → "Shell hooks" for the caller-privacy consumer).

## 5. Bluetooth pairing confirmation

`shell/bin/ophone-btagentd` (registered as the system BlueZ agent -- see
[DESIGN.md](DESIGN.md#bluetooth-pairing-confirmation)) asks the user to
approve a pairing/authorization request the same way any other app would:
a plain notification with `pair`/`reject` actions, `urgency: critical`,
`resident: true`. Nothing shell-specific: no new hint, no new category, it's
just another card in the shade. While the phone is locked it shows only as a
count like any other notification, so a pairing request can't be approved
without unlocking first -- it simply times out and is rejected.

## 6. Windows

* Every app window goes to the app workspace and is shown full-screen, one app
  at a time. Dialogs (floating windows) are centered and sized to fit.
* Usable area on the iPhone 6s is 375x621 logical px (667 minus the 24 px status
  bar and 22 px nav bar), less when the on-screen keyboard is up, because it
  reserves an exclusive zone. Layouts must adapt to height changes.
* Ship a `.desktop` file (with `Icon=`), and it appears in the app grid. Put its
  id in `favorites` in `~/.config/omarchy-phone/shell.json` to put it in the dock:
  `{ "favorites": ["org.omarchy.Phone", "foot", "chromium"] }`.
* Set a stable Wayland `app_id` matching the desktop file id, so the switcher
  finds the right icon.
