from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from fastapi import Request, status

from app.core.errors import AppError


@dataclass(slots=True)
class RateLimitRecord:
    timestamps: deque[float]


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def hit(self, *, bucket: str, key: str, limit: int, window_seconds: int = 60) -> None:
        now = monotonic()
        bucket_key = (bucket, key)

        with self._lock:
            timestamps = self._buckets[bucket_key]
            while timestamps and now - timestamps[0] > window_seconds:
                timestamps.popleft()

            if len(timestamps) >= limit:
                raise AppError(
                    code="rate_limit_exceeded",
                    message="Has superado temporalmente el limite de peticiones. Intentalo de nuevo en unos segundos.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    details={"bucket": bucket, "limit": limit, "windowSeconds": window_seconds},
                )

            timestamps.append(now)


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
