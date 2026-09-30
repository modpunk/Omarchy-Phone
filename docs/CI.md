# CI

Four independent GitHub Actions workflows under `.github/workflows/`, each scoped to the part
of the tree it checks so unrelated changes don't wait on unrelated jobs. All four run today, on
`main`, even though `shell/` and `apps/phone/` are still just `.gitkeep` placeholders here — every
job checks for the files it needs and exits 0 with a "hasn't merged yet" message if they're
missing. Once the `shell` and `phone-app` branches merge, the same jobs start actually checking
their content with no workflow changes required.

## phone-app.yml — `apps/phone/**`

Runs the 143 `unittest` tests (`apps/phone/scripts/test.sh`) in an `archlinux:latest` container
(closest match to the Omarchy target). Installs `python`, `python-gobject`, `gtk4`, `libadwaita`,
`dbus`, `python-phonenumbers`, then runs the suite under the test script's own `dbus-run-session`
sandbox. `OMARCHY_PHONE_SKIP_SIPBED=1` is set explicitly to skip the ~6 docker-in-docker SIP
end-to-end tests (`tests/test_sip.py`, needs a real docker daemon to build `tests/sipbed/`) rather
than relying on that test's own `shutil.which("docker")` autodetection — verified end to end in a
fresh container (137 ran, 6 skipped, 0 failures).

**After the `phone-app` branch merges:** if `pyproject.toml`/`requirements.txt` shows up, add it
to the install step. If new system deps get added to the app (e.g. real PipeWire hardware access,
`baresip` for non-loopback backends), extend the `pacman -S` list — the current one only covers
what `tests/` actually imports, not everything in the app's README "Requirements" line, since
`omarchy_phone/ui.py` (which needs GTK4 proper) isn't imported by the test suite today.

## shell.yml — `shell/**`

Two checks, both against `archlinux:latest` (has `quickshell` and `hyprland` in the official
`extra` repo, no AUR/custom repo needed):

- **qmllint** over every `.qml` under `shell/qs/`. Quickshell's `import qs.Commons` /
  `qs.Services` / `qs.Surfaces` namespace is resolved by Quickshell itself at runtime (there's no
  `qmldir` for it), so qmllint can't follow it and warns on those imports and everything that
  depends on them transitively — that's expected and doesn't fail the job. Only fatal
  (non-import) errors, like a real syntax error, produce qmllint's own non-zero exit and fail the
  step. Verified: a deliberately broken `.qml` file does fail the step; the real tree passes clean.
- **`Hyprland --config shell/hypr/hyprland.lua --verify-config`** once per file in
  `shell/hypr/devices/` (`generic`, `iphone6s`, `preview` today — the loop picks up new ones
  automatically), with `OPHONE_DEVICE` set to each. Needs `--i-am-really-stupid`: GitHub Actions
  container jobs run as root, and Hyprland refuses to start — even just to verify a config — as
  root without that flag. Also needs its own `XDG_RUNTIME_DIR` (`mktemp -d`, `chmod 700`).

Not covered: actually rendering the shell (`shell/preview/run.sh`) needs a live Wayland
compositor, a virtual/headless GPU output and `wtype`/`grim` for the scenario screenshots — that's
a real desktop session, not something that fits a container CI job. Consider a self-hosted runner
with a nested Hyprland + Xvfb-equivalent if screenshot regression testing is ever wanted; out of
scope here.

## brand.yml — `brand/**`

`.github/scripts/check-brand.py` (stdlib only, no image library):

- every `brand/**/*.svg` parses as well-formed XML with a `<svg>` root.
- every `brand/png/*.png` has a valid PNG signature and its pixel dimensions (read from the IHDR
  chunk) match what its filename promises, per the mapping in `brand/tools/render.sh`:
  `icon-N.png` → N×N, `name-WxH.png` → W×H, `name-W.png` → width W (any height, e.g.
  `logo-dark-1600.png`).
- for PNGs whose source SVG is identifiable from that same mapping (`icon-*` ← `mark-dark.svg`,
  `logo-X-N` ← `logo-X.svg`, `social-preview-*` ← `social-preview.svg`), the PNG's height is also
  cross-checked against the source's `viewBox` aspect ratio (±1px for rsvg-convert's own
  rounding) — so a PNG that's the right size for its *filename* but wasn't re-rendered after the
  source SVG's proportions changed still fails.

**After brand changes land** (new icon sizes, a re-render): if a new PNG doesn't fit one of the
three filename patterns, or its source SVG isn't at the expected sibling path, the script prints a
"skip"/"no source SVG found" line instead of silently passing — decide then whether the convention
needs extending or the file needs renaming.

## guard.yml — whole repo, no path filter

Runs on every push and PR, unlike the other three, since a secret or a stray binary can land
anywhere:

- `.github/scripts/check-binaries.sh`: fails on tracked files with firmware/binary/key-shaped
  extensions (`.ipsw .dfu .img .img3 .img4 .im4p .im4m .bin .elf .dylib .so .a .o .apk .ipa .dmg
  .pem .key .p12 .pfx .jks .keystore .der`), on `id_rsa*`/`.env*`-shaped names, and on any tracked
  file over 2 MiB (the largest file in the repo today is ~130 KiB, so this has a lot of headroom
  before it needs raising for a legitimate screenshot or asset).
- `gitleaks detect` (binary downloaded fresh from the latest GitHub release each run, no pinned
  version — small tool, low risk, and it means new detection rules land automatically). Scans the
  checked-out tree, not full git history (`--no-git`), since the point is to catch secrets in the
  current state, not audit history.

Verified clean against `main`, and against the `shell` and `phone-app` branches individually
(`gitleaks detect --no-git -s .` in each worktree) — including the `tests/sipbed/` baresip/pjsip
fixture credentials, which are test-only dummy values and didn't trip any rule. If a future
fixture does trip gitleaks, add a `.gitleaksignore` (path-based) or a `.github/gitleaks.toml`
allowlist rather than disabling the job.

## Known follow-ups

- `archlinux:latest`'s keyring can go stale between CI runs; if `pacman -Syu` ever starts failing
  on package signatures, prepend `pacman -Sy --noconfirm archlinux-keyring` to the install step.
- `check-binaries.sh`'s `.env*` name pattern would also flag a legitimate `.env.example` /
  `.env.sample` — exclude those specifically if one ever needs to be committed.
- `guard.yml` has no path filter, so on a same-repo PR it runs once for the push and once for the
  PR event; harmless, just two check runs instead of one.
- these are path-filtered workflows, which GitHub *skips* (not "passes") when nothing in their
  path changed — fine as informational checks, but if any of the four ever becomes a required
  status check, it needs a `dorny/paths-filter`-style single workflow instead so there's always a
  result to require.
