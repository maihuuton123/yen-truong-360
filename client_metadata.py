from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
from typing import Any

from fastapi import Request

from app.core.config import settings


USER_AGENT_MAX_LENGTH = 512


@dataclass(frozen=True)
class ReportTechnicalMetadata:
    reporter_ip_hash: str | None
    reporter_user_agent_hash: str | None
    request_fingerprint_hash: str | None
    observed_at: datetime
    technical_metadata: dict[str, Any]


def collect_report_technical_metadata(request: Request) -> ReportTechnicalMetadata:
    observed_at = datetime.now(timezone.utc)
    peer_host = request.client.host if request.client else None
    peer_port = request.client.port if request.client else None
    user_agent = clean_header_value(request.headers.get("user-agent"), max_length=USER_AGENT_MAX_LENGTH)
    trusted_proxy = is_trusted_proxy(peer_host)
    forwarded_for = clean_header_value(request.headers.get("x-forwarded-for"))
    real_ip = forwarded_header_ip(request.headers.get("x-real-ip"))
    forwarded_ip = first_forwarded_ip(forwarded_for) if forwarded_for else None

    if trusted_proxy and forwarded_ip:
        client_ip = forwarded_ip
        client_ip_source = "x-forwarded-for"
        forwarded_for_used = True
    elif trusted_proxy and real_ip:
        client_ip = real_ip
        client_ip_source = "x-real-ip"
        forwarded_for_used = False
    else:
        client_ip = peer_host
        client_ip_source = "direct"
        forwarded_for_used = False

    client_ip_hash = hash_technical_value(client_ip)
    user_agent_hash = hash_technical_value(user_agent)
    fingerprint_hash = hash_technical_value("|".join([client_ip or "", user_agent or ""]))

    metadata: dict[str, Any] = {
        "observed_at": observed_at.isoformat(),
        "client_ip_source": client_ip_source,
        "trusted_proxy": trusted_proxy,
        "forwarded_for_used": forwarded_for_used,
        "untrusted_forwarded_header_present": bool((forwarded_for or real_ip) and not trusted_proxy),
        "untrusted_forwarded_for_present": bool(forwarded_for and not trusted_proxy),
        "untrusted_real_ip_present": bool(real_ip and not trusted_proxy),
        "client_ip": client_ip,
        "peer_ip": peer_host,
        "user_agent": user_agent,
        "client_ip_hash": client_ip_hash,
        "peer_ip_hash": hash_technical_value(peer_host),
        "user_agent_hash": user_agent_hash,
        "request_fingerprint_hash": fingerprint_hash,
        "observed_source_port": peer_port,
        "source_port_note": "Transport metadata only; not a device or person identifier.",
        "forwarded_for_chain_length": forwarded_for_chain_length(forwarded_for),
    }

    return ReportTechnicalMetadata(
        reporter_ip_hash=client_ip_hash,
        reporter_user_agent_hash=user_agent_hash,
        request_fingerprint_hash=fingerprint_hash,
        observed_at=observed_at,
        technical_metadata=metadata,
    )


def is_trusted_proxy(peer_host: str | None) -> bool:
    if not peer_host:
        return False

    try:
        peer_ip = ipaddress.ip_address(peer_host)
    except ValueError:
        return False

    for trusted_proxy in settings.trusted_proxy_ips:
        try:
            network = ipaddress.ip_network(trusted_proxy, strict=False)
        except ValueError:
            continue
        if peer_ip in network:
            return True
    return False


def first_forwarded_ip(value: str) -> str | None:
    for item in value.split(","):
        candidate = item.strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None


def forwarded_header_ip(value: str | None) -> str | None:
    cleaned = clean_header_value(value)
    if not cleaned:
        return None
    try:
        return str(ipaddress.ip_address(cleaned))
    except ValueError:
        return None


def forwarded_for_chain_length(value: str | None) -> int:
    if not value:
        return 0
    return len([item for item in (part.strip() for part in value.split(",")) if item])


def clean_header_value(value: str | None, *, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if max_length is not None:
        return cleaned[:max_length]
    return cleaned


def hash_technical_value(value: str | None) -> str | None:
    if not value:
        return None
    salt = settings.auth_secret_key or settings.app_name
    return hmac.new(salt.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
