from tripweave.application.auth import (
    PasswordService,
    constant_time_equal,
    hash_token,
    normalize_email,
)
from tripweave.application.rate_limit import FixedWindowRateLimiter


def test_password_service_hashes_and_verifies_argon2() -> None:
    service = PasswordService()
    password_hash = service.hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2")
    assert service.verify_password(password_hash, "correct horse battery staple")
    assert not service.verify_password(password_hash, "wrong password")


def test_token_hashing_and_email_normalization() -> None:
    assert normalize_email(" Owner@Example.COM ") == "owner@example.com"
    assert hash_token("session-token") == hash_token("session-token")
    assert hash_token("session-token") != "session-token"
    assert constant_time_equal("abc", "abc")
    assert not constant_time_equal("abc", "abd")


def test_fixed_window_rate_limiter_blocks_after_limit() -> None:
    limiter = FixedWindowRateLimiter(max_attempts=2, window_seconds=60)

    assert limiter.allow("register:owner@example.com")
    assert limiter.allow("register:owner@example.com")
    assert not limiter.allow("register:owner@example.com")
    assert limiter.allow("register:other@example.com")
