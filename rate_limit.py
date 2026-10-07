from threading import RLock
from time import monotonic

from fastapi import HTTPException, Request, status

from app.core.config import settings


class FixedWindowRateLimiter:
    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = {}
        self._lock = RLock()

    def record(self, key: str, window_seconds: int) -> int:
        now = monotonic()
        window_start = now - window_seconds
        with self._lock:
            recent = [timestamp for timestamp in self._requests.get(key, []) if timestamp >= window_start]
            recent.append(now)
            self._requests[key] = recent
            return len(recent)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = monotonic()
        window_start = now - window_seconds
        with self._lock:
            recent = [timestamp for timestamp in self._requests.get(key, []) if timestamp >= window_start]

            if len(recent) >= limit:
                self._requests[key] = recent
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Ban gui qua nhanh. Vui long thu lai sau.",
                )

            recent.append(now)
            self._requests[key] = recent

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()


public_report_limiter = FixedWindowRateLimiter()
public_report_rapid_limiter = FixedWindowRateLimiter()
public_lookup_limiter = FixedWindowRateLimiter()


def limit_public_report_requests(request: Request) -> None:
    client_host = request.client.host if request.client else "unknown"
    public_report_limiter.check(
        key=client_host,
        limit=settings.public_report_rate_limit,
        window_seconds=settings.public_report_rate_limit_window_seconds,
    )


def limit_public_lookup_requests(request: Request) -> None:
    client_host = request.client.host if request.client else "unknown"
    public_lookup_limiter.check(
        key=client_host,
        limit=settings.public_lookup_rate_limit,
        window_seconds=settings.public_lookup_rate_limit_window_seconds,
    )
