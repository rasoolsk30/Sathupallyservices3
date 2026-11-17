"""Client IP resolution and lightweight in-process rate limiting.

Single-process only: sufficient for the MVP deployment (one uvicorn worker) and tests.
Documented limitation — move to Redis when running multiple workers.

Proxy trust model
-----------------
`X-Forwarded-For` is attacker-controlled header data. It is honoured ONLY when the
immediate socket peer is in the configured `TRUSTED_PROXIES` list (IPs or CIDRs).
With no trusted proxies configured (the default), the header is ignored completely,
so a client cannot rotate spoofed addresses to dodge per-IP rate limits or to poison
audit records. When a trusted proxy chain exists, entries are scanned right-to-left
and the first address that is NOT itself a trusted proxy is returned — the left-most
entries may have been supplied by the client and are never trusted blindly.
"""
from __future__ import annotations

import ipaddress
import logging
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import settings
from app.core.errors import RateLimitError

log = logging.getLogger("ssh.ratelimit")

_buckets: dict[str, deque[float]] = defaultdict(deque)
_network_cache: dict[str, tuple[ipaddress._BaseNetwork, ...]] = {}


def _trusted_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    raw = settings.trusted_proxies or ""
    cached = _network_cache.get(raw)
    if cached is not None:
        return cached
    networks: list[ipaddress._BaseNetwork] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            log.warning("TRUSTED_PROXIES entry ignored (not an IP or CIDR): %r", entry)
    result = tuple(networks)
    _network_cache[raw] = result
    return result


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse an address, tolerating '[::1]:443' and '1.2.3.4:5678' forms."""
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("["):  # bracketed IPv6, possibly with port
        end = text.find("]")
        if end != -1:
            text = text[1:end]
    elif text.count(":") == 1:  # IPv4 with port
        host, _, port = text.partition(":")
        if port.isdigit():
            text = host
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _is_trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    for network in _trusted_networks():
        if network.version == address.version and address in network:
            return True
    return False


def peer_ip(request: Request) -> str:
    """The raw socket peer address, regardless of headers."""
    return request.client.host if request.client else "unknown"


def client_ip(request: Request) -> str:
    """Resolve the effective client IP using the trusted-proxy model above."""
    peer_raw = peer_ip(request)
    peer = _parse_ip(peer_raw)

    # Untrusted or unparseable peer: X-Forwarded-For is ignored entirely.
    if peer is None or not _is_trusted(peer):
        return peer_raw

    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [candidate for candidate in (_parse_ip(part) for part in forwarded.split(",")) if candidate is not None]
    if not hops:
        return peer_raw

    for hop in reversed(hops):
        if not _is_trusted(hop):
            return str(hop)
    # Every hop is a trusted proxy: fall back to the earliest recorded address.
    return str(hops[0])


def check_rate_limit(key: str, *, limit: int, window_seconds: int = 60) -> None:
    now = time.monotonic()
    bucket = _buckets[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        retry_after = int(window_seconds - (now - bucket[0])) + 1
        raise RateLimitError(
            "Too many requests. Please try again shortly.",
            details={"retry_after_seconds": retry_after},
        )
    bucket.append(now)


def reset_rate_limits() -> None:
    """Test helper."""
    _buckets.clear()
    _network_cache.clear()
