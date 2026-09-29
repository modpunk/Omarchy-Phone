"""Audio routing over PipeWire (pw-dump to inspect, wpctl to switch) and the ringtone.

Routes: earpiece, speaker, headset, bluetooth. On a laptop there is no earpiece, so the
built-in sink is reported as "speaker". Set OMARCHY_PHONE_AUDIO_DRYRUN=1 to report routes
without switching the system default sink.
"""
from __future__ import annotations

import json
import os
import subprocess

RINGTONE = "/usr/share/sounds/freedesktop/stereo/phone-incoming-call.oga"


def classify(node: dict) -> str:
    props = node.get("info", {}).get("props", {})
    name = (props.get("node.name") or "").lower()
    desc = (props.get("node.description") or props.get("node.nick") or "").lower()
    if name.startswith("bluez_output") or props.get("device.api") == "bluez5":
        return "bluetooth"
    if "earpiece" in name or "earpiece" in desc or "handset" in desc:
        return "earpiece"
    if any(k in desc for k in ("headphone", "headset")) or "headphones" in name:
        return "headset"
    return "speaker"


def parse_routes(dump: list[dict]) -> tuple[list[dict], str | None]:
    """Sinks from `pw-dump` output, plus the node.name of the current default sink."""
    routes, default = [], None
    for obj in dump:
        if obj.get("type") == "PipeWire:Interface:Metadata":
            for entry in obj.get("metadata", []) or []:
                if entry.get("key") == "default.audio.sink":
                    val = entry.get("value")
                    if isinstance(val, str):
                        try:
                            val = json.loads(val)
                        except ValueError:
                            val = {"name": val}
                    default = (val or {}).get("name")
        props = obj.get("info", {}).get("props", {}) if obj.get("type") == "PipeWire:Interface:Node" else {}
        if props.get("media.class") == "Audio/Sink":
            routes.append({"id": obj["id"], "name": props.get("node.name", ""),
                           "label": props.get("node.description") or props.get("node.name", ""),
                           "kind": classify(obj)})
    for r in routes:
        r["default"] = r["name"] == default
    return routes, default


class AudioRouter:
    def __init__(self, dry_run: bool | None = None):
        self.dry_run = bool(os.environ.get("OMARCHY_PHONE_AUDIO_DRYRUN")) if dry_run is None else dry_run
        self.saved: str | None = None       # node id to restore after the call
        self.current: dict | None = None
        self._ring: subprocess.Popen | None = None

    def routes(self) -> list[dict]:
        try:
            out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=3).stdout
            routes, _ = parse_routes(json.loads(out or "[]"))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            routes = []
        if self.current:
            for r in routes:
                r["default"] = r["id"] == self.current["id"]
        return routes

    def set_route(self, route_id: int) -> dict:
        routes = self.routes()
        target = next((r for r in routes if r["id"] == route_id), None)
        if target is None:
            raise ValueError(f"no such audio route {route_id}")
        if self.saved is None:
            cur = next((r for r in routes if r.get("default")), None)
            self.saved = str(cur["id"]) if cur else ""
        if not self.dry_run:
            subprocess.run(["wpctl", "set-default", str(route_id)], check=False, timeout=3)
        self.current = target
        return target

    def route_kind(self, kind: str) -> dict | None:
        r = next((r for r in self.routes() if r["kind"] == kind), None)
        return self.set_route(r["id"]) if r else None

    def restore(self):
        if self.saved and not self.dry_run:
            subprocess.run(["wpctl", "set-default", self.saved], check=False, timeout=3)
        self.saved = None
        self.current = None

    # ------------------------------------------------------------ ringtone
    @staticmethod
    def silent_mode() -> bool:
        """The shell's ring/silent switch ($XDG_RUNTIME_DIR/omarchy-phone/silent)."""
        path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "omarchy-phone", "silent")
        try:
            with open(path) as f:
                return f.read().strip() == "on"
        except OSError:
            return False

    def ring(self, on: bool):
        if on and self.silent_mode():
            return
        if on and self._ring is None and not os.environ.get("OMARCHY_PHONE_QUIET") and os.path.exists(RINGTONE):
            try:
                # loop the ringtone until stopped; pw-play exits after one pass so use a tiny shell loop
                self._ring = subprocess.Popen(["sh", "-c", f'while pw-play "{RINGTONE}"; do sleep 0.4; done'],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                              start_new_session=True)
            except OSError:
                self._ring = None
        elif not on and self._ring is not None:
            try:
                os.killpg(self._ring.pid, 15)
            except OSError:
                pass
            self._ring = None
