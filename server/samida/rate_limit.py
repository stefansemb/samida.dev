import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


def client_ip(request: Request) -> str:
    # Caddy's reverse_proxy adds this by default; request.client.host would
    # otherwise always be 127.0.0.1 (Caddy's own address) in production.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """A simple in-memory sliding-window limiter, keyed by client IP. Fine
    for a single-process deployment (no --workers, no multi-instance) - state
    isn't shared across processes and resets on restart, which is an
    acceptable tradeoff at this scale."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, request: Request) -> None:
        now = time.monotonic()
        hits = self._hits[client_ip(request)]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_requests:
            raise HTTPException(status_code=429, detail="Too many requests. Please try again shortly.")
        hits.append(now)


# Deliberately strict - registration and login are the endpoints someone
# would script against to mass-create accounts or brute-force a password.
register_limiter = RateLimiter(max_requests=5, window_seconds=3600)
login_limiter = RateLimiter(max_requests=10, window_seconds=60)

# A generous baseline across the whole API, mainly to bound the damage a
# script hammering any endpoint could do to the shared-cost tools (Ollama
# Cloud, the self-hosted SearxNG/CamoFox) - not meant to affect real usage.
global_limiter = RateLimiter(max_requests=120, window_seconds=60)


def enforce_register_limit(request: Request) -> None:
    register_limiter.check(request)


def enforce_login_limit(request: Request) -> None:
    login_limiter.check(request)
