"""Password hashing with scrypt (stdlib)."""
import hashlib
import hmac
import os

_N, _R, _P = 2 ** 13, 8, 1


def _derive(password, salt, n, r, p):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          maxmem=64 * 1024 * 1024, dklen=32)


def hash_password(password):
    salt = os.urandom(16)
    digest = _derive(password, salt, _N, _R, _P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = _derive(password, bytes.fromhex(salt), int(n), int(r), int(p))
        return hmac.compare_digest(candidate, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False
