"""Safe client-IP resolution behind a known reverse proxy.

Never derive a ban identifier from user-provided forwarding headers unless the
socket peer matches an explicitly configured trusted proxy. In proxy mode
without that configuration, return no IP rather than banning the hosting proxy.
"""
from dataclasses import dataclass
import ipaddress
import os

HEADERS = ("x-forwarded-for", "x-real-ip", "cf-connecting-ip")


@dataclass(frozen=True)
class Config:
    mode: str
    trusted_proxies: tuple
    header: str


@dataclass(frozen=True)
class Identity:
    ip: str
    source: str  # "direct", "trusted_proxy", or "unverified"


def normalize_ip(value):
    if not isinstance(value, str):
        return ""
    try:
        # No ports, whitespace, IPv6 zone IDs, or user-controlled decoration.
        if not value or value != value.strip() or "%" in value:
            return ""
        return str(ipaddress.ip_address(value))
    except ValueError:
        return ""


def configuration(env=None):
    env = env if env is not None else os.environ
    # SaS is deployed through Bot-Hosting's reverse proxy by default.
    # This fails safely until the host verifies the correct forwarding setup.
    mode = str(env.get("SAS_CLIENT_IP_MODE", "proxy")).strip().lower()
    if mode not in ("proxy", "direct"):
        mode = "unverified"
    header = str(env.get("SAS_CLIENT_IP_HEADER", "")).strip().lower()
    if header not in HEADERS:
        header = ""
    networks = []
    for value in str(env.get("SAS_TRUSTED_PROXY_CIDRS", "")).split(","):
        value = value.strip()
        if not value:
            continue
        try:
            network = ipaddress.ip_network(value, strict=False)
            # Never allow 0.0.0.0/0 or ::/0 to trust arbitrary visitors.
            if network.prefixlen == 0:
                return Config(mode, (), "")
            networks.append(network)
        except ValueError:
            return Config(mode, (), "")
    return Config(mode, tuple(networks), header)


def _header_values(headers, header):
    # Works for both http.client HTTPMessage and a regular mapping in tests.
    if hasattr(headers, "get_all"):
        return headers.get_all(header, []) or []
    return [v for k, v in headers.items() if k.lower() == header]


def resolve(socket_peer, headers, config=None):
    config = config if config is not None else configuration()
    peer = normalize_ip(socket_peer)
    if not peer:
        return Identity("", "unverified")
    if config.mode == "direct":
        # Explicitly chosen for deployments with no reverse proxy.
        return Identity(peer, "direct")
    if config.mode != "proxy" or not config.trusted_proxies or not config.header:
        return Identity("", "unverified")
    peer_ip = ipaddress.ip_address(peer)
    if not any(peer_ip in net for net in config.trusted_proxies):
        return Identity("", "unverified")

    values = _header_values(headers, config.header)
    if len(values) != 1 or not isinstance(values[0], str) or len(values[0]) > 2048:
        return Identity("", "unverified")
    if config.header != "x-forwarded-for":
        value = normalize_ip(values[0])
        if not value or not ipaddress.ip_address(value).is_global:
            return Identity("", "unverified")
        return Identity(value, "trusted_proxy")

    # Read X-Forwarded-For from the trusted-proxy end, not from the
    # client-controlled leftmost element. This selects the first upstream
    # address that is NOT an explicitly trusted proxy.
    parts = values[0].split(",")
    if len(parts) > 32:
        return Identity("", "unverified")
    addresses = [normalize_ip(part.strip()) for part in parts]
    if not all(addresses):
        return Identity("", "unverified")
    for addr in reversed(addresses):
        hop = ipaddress.ip_address(addr)
        if not any(hop in net for net in config.trusted_proxies):
            return (Identity(addr, "trusted_proxy") if hop.is_global
                    else Identity("", "unverified"))
    return Identity("", "unverified")
