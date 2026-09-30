"""SIP account: validation and baresip account-line building. Pure (no GTK, no D-Bus, no keyring);
the password is always a separate argument, never a field that gets stored anywhere by this module.

Non-secret fields (display_name, username, domain, proxy, transport) live in Store settings under
the `sip_account` key (see store.py); the password lives only in the system keyring (keyring.py).
The two are combined into one baresip accounts-file-syntax line only at the point of use: pushing
it to a connected baresip over ctrl_tcp (`uanew`; see backends/baresip.py). It is never written to
a file, which is what keeps the password out of any plaintext config.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

TRANSPORTS = ("udp", "tcp", "tls")
_BAD_CHARS = set('";<>\n\r')
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:\d{1,5})?$"
                     r"|^\[[0-9A-Fa-f:]+\](:\d{1,5})?$")


@dataclass
class SipAccount:
    display_name: str = ""
    username: str = ""
    domain: str = ""
    proxy: str = ""
    transport: str = "udp"

    @property
    def aor(self) -> str:
        return f"sip:{self.username}@{self.domain}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SipAccount":
        return cls(display_name=(d.get("display_name") or "").strip(),
                   username=(d.get("username") or "").strip(),
                   domain=(d.get("domain") or "").strip(),
                   proxy=(d.get("proxy") or "").strip(),
                   transport=(d.get("transport") or "udp").strip().lower())


def split_username(text: str) -> tuple[str, str]:
    """If a full address was pasted into the username field ('user@domain' or 'sip:user@domain'),
    split it; otherwise return it unchanged with an empty domain."""
    u = text.strip()
    for prefix in ("sips:", "sip:"):
        if u.lower().startswith(prefix):
            u = u[len(prefix):]
            break
    if "@" in u:
        user, domain = u.split("@", 1)
        return user.strip(), domain.strip()
    return u, ""


def _valid_host(value: str) -> bool:
    return bool(_HOST_RE.match(value))


def validate(account: SipAccount, require_password: bool = False, password: str | None = None) -> list[str]:
    """Returns a list of human-readable problems; empty means the account is good to save."""
    errors = []
    if not account.username:
        errors.append("Username is required")
    elif any(c.isspace() for c in account.username) or "@" in account.username:
        errors.append("Username must not contain spaces or @ (put the domain in its own field)")
    elif set(account.username) & _BAD_CHARS:
        errors.append("Username contains invalid characters")

    if not account.domain:
        errors.append("Domain or registrar is required")
    elif any(c.isspace() for c in account.domain) or set(account.domain) & _BAD_CHARS:
        errors.append("Domain contains invalid characters")
    elif not _valid_host(account.domain):
        errors.append("Domain must be a hostname or IP address, optionally with :port")

    if account.transport not in TRANSPORTS:
        errors.append("Transport must be UDP, TCP or TLS")

    if account.proxy:
        p = account.proxy
        for prefix in ("sips:", "sip:"):
            if p.lower().startswith(prefix):
                p = p[len(prefix):]
                break
        host = p.split(";", 1)[0]  # a caller may already include ";transport=..."
        if any(c.isspace() for c in host) or set(host) & _BAD_CHARS or not _valid_host(host):
            errors.append("Outbound proxy must be a hostname or IP address, optionally with :port")

    if set(account.display_name) & _BAD_CHARS:
        errors.append("Display name must not contain quotes or line breaks")

    if require_password and not password:
        errors.append("Password is required")
    elif password and set(password) & _BAD_CHARS:
        errors.append("Password must not contain quotes, angle brackets or line breaks")

    return errors


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_baresip_line(account: SipAccount, password: str, regint: int = 300) -> str:
    """Build a baresip accounts-file-syntax line, e.g.:

      "Jane" <sip:jane@pbx.example.org;transport=tcp>;auth_pass="hunter2";
      outbound="sip:proxy.example.org;transport=tcp";regint=300

    (shown wrapped; it is one line.) Never written to disk by this app — see the module docstring.
    """
    uri = f"sip:{account.username}@{account.domain}"
    if account.transport in ("tcp", "tls"):
        uri += f";transport={account.transport}"
    params = []
    if password:
        params.append(f"auth_pass={_quoted(password)}")
    if account.proxy:
        proxy = account.proxy
        if not proxy.lower().startswith(("sip:", "sips:")):
            proxy = f"sip:{proxy}"
        if account.transport in ("tcp", "tls") and "transport=" not in proxy:
            proxy += f";transport={account.transport}"
        params.append(f"outbound={_quoted(proxy)}")
    params.append(f"regint={int(regint)}")
    line = ";".join([f"<{uri}>", *params])
    if account.display_name:
        line = f"{_quoted(account.display_name)} {line}"
    return line
