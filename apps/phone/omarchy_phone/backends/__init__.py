"""Calling backends. `create(kind, config)` builds one by id."""
from .base import Backend, BackendError  # noqa: F401


def create(kind: str, config: dict | None = None) -> Backend:
    if kind == "loopback":
        from .loopback import LoopbackBackend
        return LoopbackBackend(config)
    if kind == "sip":
        from .baresip import BaresipBackend
        return BaresipBackend(config)
    raise BackendError(f"unknown backend {kind!r} (available: loopback, sip)")
