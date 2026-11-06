"""Argon2 password hashing shared by the administration APIs and CLI."""
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against the stored adaptive Argon2 hash."""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(plain_password: str) -> str:
    """Hash a password with the shared adaptive Argon2 policy."""
    return pwd_context.hash(plain_password)
