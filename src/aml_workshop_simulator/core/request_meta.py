"""Technical metadata of an inbound request.

`X-Forwarded-For` is attacker-controlled unless the request really came through
a reverse proxy we operate. The header is therefore only consulted when the
*immediate* peer is one of the explicitly configured trusted proxies, and even
then only the right-most address that is not itself a trusted proxy is taken.
Without configuration the socket peer is used, which is always truthful.

Only what an administrator needs in order to recognise a participant's device
is stored: address, User-Agent and Accept-Language. No password, no raw session
identifier and no additional fingerprinting.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from fastapi import Request

from aml_workshop_simulator.core.config import settings

USER_AGENT_MAX_LENGTH = 512
ACCEPT_LANGUAGE_MAX_LENGTH = 120


@dataclass(frozen=True)
class RequestMeta:
    ip_address: str | None
    user_agent: str | None
    accept_language: str | None


def _networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = (settings.TRUSTED_PROXY_IPS or "").strip()
    if not raw:
        return []
    networks = []
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            continue
    return networks


def _is_trusted(address: str) -> bool:
    networks = _networks()
    if not networks:
        return False
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in networks)


def normalise_ip(value: str | None) -> str | None:
    """Valid IPv4/IPv6 literal, or None. Ports and junk are dropped."""
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith("[") and "]" in candidate:  # [::1]:1234
        candidate = candidate[1 : candidate.index("]")]
    elif candidate.count(":") == 1 and "." in candidate:  # 1.2.3.4:5678
        candidate = candidate.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    """The address to store for this request."""
    peer = normalise_ip(getattr(request.client, "host", None))
    if peer is None or not _is_trusted(peer):
        return peer

    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        return peer
    for raw in reversed(forwarded.split(",")):
        candidate = normalise_ip(raw)
        if candidate is None:
            continue
        if _is_trusted(candidate):
            continue
        return candidate
    return peer


def request_meta(request: Request) -> RequestMeta:
    user_agent = request.headers.get("User-Agent")
    accept_language = request.headers.get("Accept-Language")
    return RequestMeta(
        ip_address=client_ip(request),
        user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
        accept_language=(
            accept_language[:ACCEPT_LANGUAGE_MAX_LENGTH] if accept_language else None
        ),
    )
