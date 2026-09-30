/*
 * ophone-im: input-method-v2 watcher/typer for the Omarchy Phone shell.
 *
 * Binds zwp_input_method_manager_v2 and becomes *a* (not *the*) input method
 * for the default seat, purely to learn when a text-input-v3 field is
 * focused. It does not draw anything and does not grab the hardware
 * keyboard: the on-screen keyboard is still QML (Surfaces/Keyboard.qml) and
 * still types most keys via wtype/virtual-keyboard-v1. This helper only
 * exists so the shell *knows* when to show/hide, and so plain characters can
 * go through commit_string instead of a synthetic key event, which is the
 * correct path for an input method to insert text.
 *
 * Protocol on stdout, one line per state change (emitted only once the
 * compositor confirms it with a "done", per the spec -- activate/deactivate
 * are pending until then):
 *   active        a text-input is now focused
 *   inactive      no text-input is focused any more
 *   unavailable   another input method is already bound to this seat; this
 *                 process prints this once and exits. The shell falls back
 *                 to manual-toggle-only (wtype) behaviour.
 *   content <name>  the focused field's content purpose, decoded from the
 *                 zwp_text_input_v3 content_type event (purpose + hint,
 *                 values per text-input-unstable-v3.xml -- not re-vendored
 *                 here since the input-method-v2 xml only *references* that
 *                 enum, it doesn't define it; wayland-scanner therefore
 *                 emits no constants for it, hence the #defines below).
 *                 Emitted right before "active" when a field gains focus,
 *                 and again whenever it changes while focused. name is one
 *                 of: normal, numeric, phone, email, url, password. Reset
 *                 to "normal" on every activate before the field's own
 *                 content_type (if any) arrives, so a purpose from the
 *                 previous field never leaks into one that doesn't set it.
 *
 * Commands on stdin, one per line:
 *   T<text>       commit <text> (rest of the line, no embedded newline) at
 *                 the cursor
 *   B             delete one byte before the cursor (backspace). Not
 *                 currently sent by the shell: delete_surrounding_text is
 *                 the protocol-correct way to delete, but foot -- despite
 *                 speaking text-input-v3 for IME composition -- doesn't act
 *                 on it, so Keyboard.qml uses a real BackSpace key event
 *                 (wtype) for every app instead. Kept for the apps that do
 *                 honor it (confirmed working in GTK4).
 * Both are no-ops (silently ignored) while inactive.
 */

#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>

#include "input-method-unstable-v2-client-protocol.h"

static struct wl_seat *seat;
static struct zwp_input_method_manager_v2 *im_manager;
static struct zwp_input_method_v2 *im;

static int pending_active;
static int active = -1; /* -1: unknown yet, forces the first report */
static uint32_t done_count;

/* zwp_text_input_v3.content_purpose (text-input-unstable-v3.xml) */
#define PURPOSE_NORMAL   0
#define PURPOSE_ALPHA    1
#define PURPOSE_DIGITS   2
#define PURPOSE_NUMBER   3
#define PURPOSE_PHONE    4
#define PURPOSE_URL      5
#define PURPOSE_EMAIL    6
#define PURPOSE_NAME     7
#define PURPOSE_PASSWORD 8
#define PURPOSE_PIN      9
#define PURPOSE_DATE     10
#define PURPOSE_TIME     11
#define PURPOSE_DATETIME 12
#define PURPOSE_TERMINAL 13
/* zwp_text_input_v3.content_hint (bitfield, same file) */
#define HINT_HIDDEN_TEXT   0x40
#define HINT_SENSITIVE_DATA 0x80

/* Pending (double-buffered, per zwp_input_method_v2's "done" semantics) and
 * current content purpose/hint, plus the name last emitted so we only print
 * a line when it actually changes. */
static uint32_t pending_purpose, pending_hint;
static uint32_t cur_purpose, cur_hint;
static char last_content[16] = "";

static const char *content_name(uint32_t purpose, uint32_t hint) {
  /* password and pin both hide characters; either sensitivity hint does
   * too, in case an app sets it without purpose=password (some do). */
  if (purpose == PURPOSE_PASSWORD || purpose == PURPOSE_PIN ||
      (hint & (HINT_HIDDEN_TEXT | HINT_SENSITIVE_DATA)))
    return "password";
  switch (purpose) {
    case PURPOSE_DIGITS:
    case PURPOSE_NUMBER: return "numeric";
    case PURPOSE_PHONE:  return "phone";
    case PURPOSE_EMAIL:  return "email";
    case PURPOSE_URL:    return "url";
    default:             return "normal";
  }
}

static void emit(const char *line) {
  printf("%s\n", line);
  fflush(stdout);
}

/* --- zwp_input_method_v2 listener ------------------------------------- */

static void im_activate(void *d, struct zwp_input_method_v2 *o) {
  (void)d; (void)o;
  pending_active = 1;
  /* zwp_text_input_v3's enable() resets purpose/hint to normal/none on the
   * client side; mirror that here so a field that never calls
   * set_content_type doesn't inherit the previous field's layout. Real
   * content_type events (if any) arrive after this and before the matching
   * done, overwriting these per the usual double-buffering. */
  pending_purpose = PURPOSE_NORMAL;
  pending_hint = 0;
}
static void im_deactivate(void *d, struct zwp_input_method_v2 *o) { (void)d; (void)o; pending_active = 0; }
static void im_surrounding_text(void *d, struct zwp_input_method_v2 *o, const char *text, uint32_t cursor, uint32_t anchor) {
  (void)d; (void)o; (void)text; (void)cursor; (void)anchor;
}
static void im_text_change_cause(void *d, struct zwp_input_method_v2 *o, uint32_t cause) { (void)d; (void)o; (void)cause; }
static void im_content_type(void *d, struct zwp_input_method_v2 *o, uint32_t hint, uint32_t purpose) {
  (void)d; (void)o;
  pending_hint = hint;
  pending_purpose = purpose;
}
static void im_done(void *d, struct zwp_input_method_v2 *o) {
  (void)d; (void)o;
  done_count++;
  int becoming_active = pending_active && active <= 0; /* active starts at -1 (unknown) */
  cur_purpose = pending_purpose;
  cur_hint = pending_hint;
  if (pending_active) {
    const char *name = content_name(cur_purpose, cur_hint);
    if (becoming_active || strcmp(name, last_content) != 0) {
      char line[32];
      snprintf(line, sizeof line, "content %s", name);
      emit(line);
      strncpy(last_content, name, sizeof last_content - 1);
      last_content[sizeof last_content - 1] = '\0';
    }
  }
  if (pending_active != active) {
    active = pending_active;
    emit(active ? "active" : "inactive");
  }
}
static void im_unavailable(void *d, struct zwp_input_method_v2 *o) {
  (void)d; (void)o;
  emit("unavailable");
  exit(0);
}

static const struct zwp_input_method_v2_listener im_listener = {
  .activate = im_activate,
  .deactivate = im_deactivate,
  .surrounding_text = im_surrounding_text,
  .text_change_cause = im_text_change_cause,
  .content_type = im_content_type,
  .done = im_done,
  .unavailable = im_unavailable,
};

/* --- registry ----------------------------------------------------------- */

static void registry_global(void *d, struct wl_registry *reg, uint32_t name, const char *iface, uint32_t ver) {
  (void)d; (void)ver;
  if (!seat && !strcmp(iface, wl_seat_interface.name))
    seat = wl_registry_bind(reg, name, &wl_seat_interface, 1);
  else if (!im_manager && !strcmp(iface, zwp_input_method_manager_v2_interface.name))
    im_manager = wl_registry_bind(reg, name, &zwp_input_method_manager_v2_interface, 1);
}
static void registry_global_remove(void *d, struct wl_registry *reg, uint32_t name) { (void)d; (void)reg; (void)name; }
static const struct wl_registry_listener registry_listener = { registry_global, registry_global_remove };

/* --- stdin command handling ---------------------------------------------- */

static void handle_line(char *line) {
  if (active <= 0) return; /* nothing focused: nothing to type into */
  if (line[0] == 'T') {
    zwp_input_method_v2_commit_string(im, line + 1);
    zwp_input_method_v2_commit(im, done_count);
  } else if (line[0] == 'B') {
    zwp_input_method_v2_delete_surrounding_text(im, 1, 0);
    zwp_input_method_v2_commit(im, done_count);
  }
}

int main(void) {
  struct wl_display *display = wl_display_connect(NULL);
  if (!display) {
    fprintf(stderr, "ophone-im: no Wayland display\n");
    return 1;
  }
  struct wl_registry *registry = wl_display_get_registry(display);
  wl_registry_add_listener(registry, &registry_listener, NULL);
  wl_display_roundtrip(display);

  if (!seat || !im_manager) {
    fprintf(stderr, "ophone-im: compositor has no wl_seat or input-method-v2; auto show/hide disabled\n");
    return 1;
  }

  im = zwp_input_method_manager_v2_get_input_method(im_manager, seat);
  zwp_input_method_v2_add_listener(im, &im_listener, NULL);

  char buf[8192];
  size_t buflen = 0;
  struct pollfd fds[2] = {
    { .fd = wl_display_get_fd(display), .events = POLLIN },
    { .fd = STDIN_FILENO, .events = POLLIN },
  };

  for (;;) {
    while (wl_display_prepare_read(display) != 0) wl_display_dispatch_pending(display);
    wl_display_flush(display);

    int n = poll(fds, 2, -1);
    if (n < 0) {
      wl_display_cancel_read(display);
      if (errno == EINTR) continue;
      break;
    }
    if (fds[0].revents & POLLIN) {
      if (wl_display_read_events(display) < 0) break;
    } else {
      wl_display_cancel_read(display);
    }
    if (wl_display_dispatch_pending(display) < 0) break;

    if (fds[1].revents & (POLLHUP | POLLERR)) break; /* the shell closed our stdin: quit */
    if (fds[1].revents & POLLIN) {
      ssize_t r = read(STDIN_FILENO, buf + buflen, sizeof(buf) - 1 - buflen);
      if (r <= 0) break;
      buflen += (size_t)r;
      buf[buflen] = '\0';
      char *start = buf, *nl;
      while ((nl = memchr(start, '\n', buflen - (size_t)(start - buf)))) {
        *nl = '\0';
        handle_line(start);
        start = nl + 1;
      }
      size_t rem = buflen - (size_t)(start - buf);
      memmove(buf, start, rem);
      buflen = rem;
      if (buflen >= sizeof(buf) - 1) buflen = 0; /* runaway line: drop it */
    }
  }
  return 0;
}
