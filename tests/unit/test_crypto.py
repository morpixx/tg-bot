from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from services.crypto import decrypt, encrypt


def test_roundtrip_simple() -> None:
    assert decrypt(encrypt("hello")) == "hello"


def test_roundtrip_string_session() -> None:
    session = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789" * 3
    assert decrypt(encrypt(session)) == session


def test_roundtrip_unicode() -> None:
    text = "Привет мир 🔥"
    assert decrypt(encrypt(text)) == text


def test_roundtrip_empty_string() -> None:
    assert decrypt(encrypt("")) == ""


def test_different_ciphertexts_per_call() -> None:
    c1 = encrypt("same")
    c2 = encrypt("same")
    assert c1 != c2  # Fernet uses random IV


def test_decrypt_wrong_key_raises() -> None:
    ciphertext = encrypt("secret")
    # Patch with a different key
    from unittest.mock import patch
    new_key = Fernet.generate_key().decode()
    with patch("services.crypto._fernet", Fernet(new_key.encode())):
        with pytest.raises(InvalidToken):
            decrypt(ciphertext)


def test_decrypt_garbage_raises() -> None:
    with pytest.raises(InvalidToken):
        decrypt("not_a_valid_fernet_token")


def test_decrypt_truncated_raises() -> None:
    ciphertext = encrypt("value")
    with pytest.raises(InvalidToken):
        decrypt(ciphertext[:10])
