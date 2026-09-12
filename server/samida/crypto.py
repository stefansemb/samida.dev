from cryptography.fernet import Fernet, InvalidToken

from samida.config import Settings


class CryptoError(RuntimeError):
    pass


def _fernet(settings: Settings) -> Fernet:
    if not settings.secret_key:
        raise CryptoError(
            "SAMIDA_SECRET_KEY is not configured. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and put it in .env."
        )
    try:
        return Fernet(settings.secret_key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise CryptoError("SAMIDA_SECRET_KEY is invalid.") from exc


def encrypt_secret(plaintext: str, settings: Settings) -> str:
    return _fernet(settings).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, settings: Settings) -> str:
    try:
        return _fernet(settings).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CryptoError("Could not decrypt the stored key.") from exc
