"""Password storage for the SIP account: the Secret Service (libsecret), never a plaintext file.

Uses `gi.repository.Secret` (libsecret's GObject introspection binding) so the app stays on the
PyGObject stack it already depends on, rather than adding the separate `keyring` PyPI package. This
needs the `libsecret` package's typelib (Arch: `libsecret`) plus a running Secret Service provider
(gnome-keyring, or KDE's `ksecretservice` compat daemon) on the session bus.

Set `OMARCHY_PHONE_KEYRING=memory` to use an in-process dict instead: nothing is ever written to
disk and the secret does not survive the process. `scripts/sandbox.sh` sets this (its private D-Bus
session has no Secret Service to talk to), and tests rely on it to stay offline and deterministic.
"""
from __future__ import annotations

import os

from gi.repository import GLib

_SCHEMA = None
_MEMORY: dict[str, str] = {}
_LABEL = "Omarchy Phone SIP password"


class KeyringError(RuntimeError):
    pass


def _use_memory() -> bool:
    return os.environ.get("OMARCHY_PHONE_KEYRING") == "memory"


def _schema():
    global _SCHEMA
    if _SCHEMA is None:
        import gi
        gi.require_version("Secret", "1")
        from gi.repository import Secret
        _SCHEMA = Secret.Schema.new("org.omarchy.Phone.SipAccount", Secret.SchemaFlags.NONE,
                                    {"profile": Secret.SchemaAttributeType.STRING})
    return _SCHEMA


def set_password(profile: str, password: str) -> None:
    if _use_memory():
        _MEMORY[profile] = password
        return
    try:
        from gi.repository import Secret
        ok = Secret.password_store_sync(_schema(), {"profile": profile}, Secret.COLLECTION_DEFAULT,
                                        f"{_LABEL} ({profile})", password, None)
    except (GLib.Error, ImportError, ValueError) as e:
        raise KeyringError(f"could not store the SIP password: {e}") from e
    if not ok:
        raise KeyringError("could not store the SIP password: the Secret Service refused it")


def get_password(profile: str) -> str | None:
    if _use_memory():
        return _MEMORY.get(profile)
    try:
        from gi.repository import Secret
        return Secret.password_lookup_sync(_schema(), {"profile": profile}, None)
    except (GLib.Error, ImportError, ValueError) as e:
        raise KeyringError(f"could not read the SIP password: {e}") from e


def clear_password(profile: str) -> None:
    if _use_memory():
        _MEMORY.pop(profile, None)
        return
    try:
        from gi.repository import Secret
        Secret.password_clear_sync(_schema(), {"profile": profile}, None)
    except (GLib.Error, ImportError, ValueError) as e:
        raise KeyringError(f"could not remove the SIP password: {e}") from e
