"""Password hashing — thin wrapper over werkzeug so the algorithm lives in one place."""

from werkzeug.security import check_password_hash, generate_password_hash

# scrypt is werkzeug's default and is fine for a small, admin-provisioned user set.
_METHOD = "scrypt"


def hash_password(password: str) -> str:
    return generate_password_hash(password, method=_METHOD)


def verify_password(stored_hash: str, password: str) -> bool:
    return check_password_hash(stored_hash, password)
