import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
TOKEN_ALGORITHM = "HS256"

_revoked_tokens: dict[str, int] = {}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt, digest = password_hash.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False

    if algorithm != PASSWORD_ALGORITHM:
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(candidate, digest)


def _auth_secret() -> str:
    if not settings.auth_secret_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_SECRET_KEY is not configured.",
        )
    return settings.auth_secret_key


def _base64url_encode(content: bytes) -> str:
    return base64.urlsafe_b64encode(content).rstrip(b"=").decode("ascii")


def _base64url_decode(content: str) -> bytes:
    padding = "=" * (-len(content) % 4)
    return base64.urlsafe_b64decode((content + padding).encode("ascii"))


def _json_b64(data: dict[str, Any]) -> str:
    return _base64url_encode(json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def create_access_token(subject: str, username: str, role: str) -> tuple[str, int]:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.auth_token_expire_seconds)
    header = {"alg": TOKEN_ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": subject,
        "username": username,
        "role": role,
        "exp": int(expires_at.timestamp()),
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "type": "access",
        "jti": secrets.token_urlsafe(16),
    }
    signing_input = f"{_json_b64(header)}.{_json_b64(payload)}"
    signature = hmac.new(
        _auth_secret().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_base64url_encode(signature)}", settings.auth_token_expire_seconds


def decode_access_token(token: str) -> dict[str, Any]:
    if is_token_revoked(token):
        raise_credentials_error()

    try:
        header_raw, payload_raw, signature_raw = token.split(".", 2)
        header = json.loads(_base64url_decode(header_raw))
        payload = json.loads(_base64url_decode(payload_raw))
    except Exception:
        raise_credentials_error()

    if header.get("alg") != TOKEN_ALGORITHM or payload.get("type") != "access":
        raise_credentials_error()

    signing_input = f"{header_raw}.{payload_raw}"
    expected_signature = hmac.new(
        _auth_secret().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        supplied_signature = _base64url_decode(signature_raw)
    except Exception:
        raise_credentials_error()

    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise_credentials_error()

    expires_at = int(payload.get("exp", 0))
    if expires_at <= int(datetime.now(timezone.utc).timestamp()):
        raise_credentials_error()

    return payload


def revoke_token(token: str) -> None:
    try:
        payload = decode_access_token(token)
    except HTTPException:
        return

    _cleanup_revoked_tokens()
    _revoked_tokens[_token_fingerprint(token)] = int(payload["exp"])


def is_token_revoked(token: str) -> bool:
    _cleanup_revoked_tokens()
    return _token_fingerprint(token) in _revoked_tokens


def reset_revoked_tokens() -> None:
    _revoked_tokens.clear()


def _cleanup_revoked_tokens() -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    expired = [fingerprint for fingerprint, expires_at in _revoked_tokens.items() if expires_at <= now]
    for fingerprint in expired:
        _revoked_tokens.pop(fingerprint, None)


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def raise_credentials_error() -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Thông tin xác thực không hợp lệ hoặc đã hết hạn.",
        headers={"WWW-Authenticate": "Bearer"},
    )
