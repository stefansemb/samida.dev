from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from samida.rate_limit import RateLimiter, client_ip


def _request(ip: str = "1.2.3.4", forwarded: str | None = None) -> Mock:
    request = Mock()
    request.client.host = ip
    request.headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return request


def test_client_ip_prefers_x_forwarded_for() -> None:
    request = _request(ip="127.0.0.1", forwarded="5.6.7.8, 127.0.0.1")
    assert client_ip(request) == "5.6.7.8"


def test_client_ip_falls_back_to_request_client() -> None:
    request = _request(ip="9.9.9.9")
    assert client_ip(request) == "9.9.9.9"


def test_allows_requests_under_the_limit() -> None:
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    request = _request()
    for _ in range(3):
        limiter.check(request)  # should not raise


def test_blocks_requests_over_the_limit() -> None:
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    request = _request()
    limiter.check(request)
    limiter.check(request)
    with pytest.raises(HTTPException) as exc_info:
        limiter.check(request)
    assert exc_info.value.status_code == 429


def test_limits_are_tracked_per_ip_independently() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    limiter.check(_request(ip="1.1.1.1"))
    limiter.check(_request(ip="2.2.2.2"))  # different IP, should not raise


def test_old_hits_expire_out_of_the_window() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=0.05)
    request = _request()
    limiter.check(request)
    import time

    time.sleep(0.06)
    limiter.check(request)  # should not raise - the earlier hit has expired
