"""Security checks for workspace password hashing."""

from argon2 import PasswordHasher, extract_parameters
from argon2.low_level import Type

from src.workspace.auth.passwords import hash_password, verify_password


def test_password_hashes_use_argon2id_with_fresh_salts():
    password = "A long example password with spaces and Unicode: café"
    first = hash_password(password)
    second = hash_password(password)
    params = extract_parameters(first)

    assert first != second
    assert password not in first
    assert params.type == Type.ID
    assert params.memory_cost >= 19456
    assert params.time_cost >= 2
    assert params.salt_len >= 16
    assert verify_password(password, first).valid
    assert verify_password(password, second).valid


def test_password_verification_rejects_incorrect_or_changed_text():
    password = "caf\u00e9 and spaces "
    encoded = hash_password(password)

    assert verify_password(password, encoded).valid
    assert not verify_password("wrong password", encoded).valid
    assert not verify_password("cafe\u0301 and spaces ", encoded).valid
    assert not verify_password(password.rstrip(), encoded).valid


def test_malformed_hash_is_rejected_without_logging_secrets(caplog):
    password = "example-password-that-must-not-be-logged"
    malformed_hash = "malformed-hash-that-must-not-be-logged"

    result = verify_password(password, malformed_hash)

    assert not result.valid
    assert not result.needs_rehash
    assert password not in caplog.text
    assert malformed_hash not in caplog.text


def test_successful_verification_flags_outdated_hash_parameters():
    password = "an example password"
    previous = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1).hash(password)
    current = hash_password(password)

    old_result = verify_password(password, previous)
    assert old_result.valid
    assert old_result.needs_rehash
    assert not verify_password(password, current).needs_rehash
    assert not verify_password("wrong", previous).needs_rehash
