"""Exact route/origin/audience policy for migration-only adapters."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
import re


class InvalidBridgeBinding(ValueError):
    """An untrusted route, origin, audience, or nonce failed validation."""


_ROUTE = re.compile(r"\A/[A-Za-z0-9/_-]{1,240}\Z")
_AUDIENCE = re.compile(r"\A[A-Za-z0-9._:/-]{1,160}\Z")
_NONCE = re.compile(r"\A[A-Za-z0-9._~-]{16,256}\Z")


def canonical_origin(value: str) -> str:
    """Accept a serialized HTTPS origin only; discard no path or query silently."""

    if not isinstance(value, str) or not value or len(value) > 255:
        raise InvalidBridgeBinding("origin is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise InvalidBridgeBinding("origin is invalid") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise InvalidBridgeBinding("origin must be an HTTPS origin")
    hostname = parsed.hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if port == 443:
        port = None
    return f"https://{hostname}" + (f":{port}" if port is not None else "")


@dataclass(frozen=True)
class RouteGrant:
    route: str
    origin: str
    audience: str

    def __post_init__(self) -> None:
        if not isinstance(self.route, str) or not _ROUTE.fullmatch(self.route):
            raise InvalidBridgeBinding("route is invalid")
        if not isinstance(self.audience, str) or not _AUDIENCE.fullmatch(self.audience):
            raise InvalidBridgeBinding("audience is invalid")
        object.__setattr__(self, "origin", canonical_origin(self.origin))


class RouteGrantRegistry:
    """Configured exact triples. No wildcard, query, redirect, or prefix grants."""

    def __init__(self, grants: tuple[RouteGrant, ...] | list[RouteGrant]):
        materialized = tuple(grants)
        triples = [(g.route, g.origin, g.audience) for g in materialized]
        if len(set(triples)) != len(triples):
            raise ValueError("duplicate route/origin/audience grant")
        self._grants = frozenset(triples)

    def require(self, route: str, origin: str, audience: str) -> RouteGrant:
        if not isinstance(route, str) or not isinstance(audience, str):
            raise InvalidBridgeBinding("route binding is invalid")
        normalized_origin = canonical_origin(origin)
        triple = (route, normalized_origin, audience)
        if triple not in self._grants:
            raise InvalidBridgeBinding("route binding is not allowlisted")
        return RouteGrant(route, normalized_origin, audience)


def validate_nonce(value: str) -> str:
    if not isinstance(value, str) or not _NONCE.fullmatch(value):
        raise InvalidBridgeBinding("nonce is invalid")
    return value
