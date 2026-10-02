"""Hashing and session helpers with no plaintext credential persistence."""

from hashlib import sha256

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def opaque_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def normalize_login(value: str) -> str:
    return value.strip().casefold()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def password_matches(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False
