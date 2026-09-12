from samida import auth
from samida.config import Settings


def test_is_owner_matches_configured_email_case_insensitively() -> None:
    settings = Settings(owner_email="Stese2026@Gmail.com")
    assert auth.is_owner("stese2026@gmail.com", settings) is True
    assert auth.is_owner(" STESE2026@GMAIL.COM ", settings) is True


def test_is_owner_rejects_other_emails() -> None:
    settings = Settings(owner_email="stese2026@gmail.com")
    assert auth.is_owner("someone-else@example.com", settings) is False


def test_is_owner_is_false_when_unconfigured() -> None:
    settings = Settings(owner_email=None)
    assert auth.is_owner("anyone@example.com", settings) is False
