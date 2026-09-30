from time import monotonic

from fastapi import HTTPException, Request, status

from app.core.config import settings


class FixedWindowRateLimiter:
    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = {}

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = monotonic()
        window_start = now - window_seconds
        recent = [timestamp for timestamp in self._requests.get(key, []) if timestamp >= window_start]

        if len(recent) >= limit:
            self._requests[key] = recent
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Bạn gửi quá nhanh. Vui lòng thử lại sau.",
            )

        recent.append(now)
        self._requests[key] = recent

    def reset(self) -> None:
        self._requests.clear()


public_report_limiter = FixedWindowRateLimiter()
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
